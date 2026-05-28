"""
CR-061 — In-app overnight benchmark.

ONE long-running queue job that sequences many sub-measurements (variance
calibration → video all-codecs × reps × sources → AI compare panels), reports
"step i/N" progress for /queue-status, persists a self-describing manifest after
every step (so a cancelled/crashed run is still viewable), and honours a
cooperative cancel checked between top-level steps.

FUTURE-PROOFING is the whole point of the data model: the set of "measures" is a
registry (`MEASURES` + `ORDER`) and each is toggled by a `bench_run_*` setting,
so adding or retiring a measure is a registry + settings change — the coroutine,
the persistence, and the results viewer don't change. The stored manifest's
`steps` are self-describing (each carries its own `kind` + `result_ref`), and the
viewer renders whatever a stored run contains, tolerating unknown/absent kinds.

The sub-runners are the EXISTING ones — we don't reimplement measurement:
  variance  → video.run_variance_calibration            (no per-run JSON)
  video     → main.run_job(..., "all_codecs", ...)       (self-persists "video")
  llm       → main.run_llm_compare_models_job            (self-persists "llm")
  rag       → main.run_rag_compare_models_job            (self-persists "llm")
  image     → image_gen.run_image_compare_models_measurement (we persist "image")
`main` is imported lazily inside the run callables to avoid the import cycle
(main imports benchmark for its endpoints).
"""
import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import persist
import version

# Fixed AI fixtures — the benchmark exercises the panels' logic; exact
# correctness is not the point (a model failing still produces energy data).
DEFAULT_SOURCES = ["meridian_120s", "bbb_120s"]
LLM_PROMPT = "What is the capital of France? Reply with just the city name."
LLM_EXPECTED = "Paris"
RAG_QUESTION = "What does OWL measure, and in what unit?"
RAG_EXPECTED = "energy"


def _now() -> str:
    return datetime.now().isoformat()


# --- Measure run callables (async (step, jobs, sub_id, settings) -> result_ref|None)

async def _run_variance(step, jobs, sub_id, s):
    import video
    await video.run_variance_calibration(sub_id, jobs)
    return None  # variance writes settings.json + history.jsonl, no per-run JSON


async def _run_video(step, jobs, sub_id, s):
    import main
    import sources
    src_key = step["params"]["source_key"]
    src = sources.PRELOADED.get(src_key)
    if not src or not src.get("path") or not Path(src["path"]).exists():
        raise RuntimeError(f"source {src_key!r} not available")
    await main.run_job(sub_id, src["path"], "all_codecs", False, source_key=src_key)
    return {"type": "video", "job_id": sub_id}


async def _run_llm(step, jobs, sub_id, s):
    import main
    await main.run_llm_compare_models_job(sub_id, LLM_PROMPT, LLM_EXPECTED, "gpu")
    return {"type": "llm", "job_id": sub_id}


async def _run_rag(step, jobs, sub_id, s):
    import main
    await main.run_rag_compare_models_job(sub_id, RAG_QUESTION, RAG_EXPECTED)
    return {"type": "llm", "job_id": sub_id}  # rag persists under results/llm/


async def _run_image(step, jobs, sub_id, s):
    import image_gen
    import llm
    # Free GPU VRAM held by Ollama before loading the diffusers pipeline, and
    # WAIT until it's actually released. A fixed sleep isn't enough — a 20B-class
    # model (gpt-oss:20b from the LLM step) holds ~10 GB and takes well over 3 s
    # to evict, so the image pipeline OOMs ("HIP out of memory … 0 bytes free").
    # Poll Ollama's /api/ps until empty, then a short reclaim buffer.
    try:
        llm.unload_all_loaded_models()
        for _ in range(45):  # up to ~90 s
            if not llm.loaded_models():
                break
            if jobs is not None and sub_id in jobs:
                jobs[sub_id]["stage"] = "waiting for GPU VRAM (Ollama unload)"
            await asyncio.sleep(2)
        await asyncio.sleep(int(s.get("llm_unload_settle_s", 3)) + 3)  # VRAM reclaim buffer
    except Exception:
        pass
    result = await image_gen.run_image_compare_models_measurement(None, sub_id, jobs)
    persist.save_result("image", sub_id, result)
    return {"type": "image", "job_id": sub_id}


# --- Registry — THE single edit point to add/retire a measure ----------------

@dataclass(frozen=True)
class Measure:
    id: str
    kind: str            # renderer-dispatch key on the results viewer
    label: str
    result_type: Optional[str]   # results/<dir> the sub-runner persists to, or None
    enabled_key: str             # the bench_run_* settings flag (ignored if enabled_fn set)
    run: Callable
    per_source: bool = False
    repeatable: bool = False
    fatal: bool = False          # if True, a failure aborts the whole run
    enabled_fn: Optional[Callable] = None  # predicate over settings; overrides enabled_key


MEASURES = {
    "variance": Measure(
        "variance", "variance", "Variance calibration", None,
        "", _run_variance, fatal=True,
        # Driven by the existing Variance Runs slider — 0 skips it (here and in
        # the standalone calibration). No separate bench_run_variance flag.
        enabled_fn=lambda s: int(s.get("variance_runs", 0)) > 0),
    "video_all_codecs": Measure(
        "video_all_codecs", "video", "Video all-codecs", "video",
        "bench_run_video", _run_video, per_source=True, repeatable=True, fatal=True),
    "llm_compare": Measure(
        "llm_compare", "llm", "LLM compare panel", "llm",
        "bench_run_llm", _run_llm),
    "rag_compare": Measure(
        "rag_compare", "rag", "RAG compare panel", "llm",
        "bench_run_rag", _run_rag),
    "image_compare": Measure(
        "image_compare", "image", "Image compare panel", "image",
        "bench_run_image", _run_image),
}
ORDER = ["variance", "video_all_codecs", "llm_compare", "rag_compare", "image_compare"]


def _is_enabled(m: "Measure", s: dict) -> bool:
    return m.enabled_fn(s) if m.enabled_fn else bool(s.get(m.enabled_key, True))


def build_plan(s: dict) -> list:
    """Expand the enabled registry × settings into an ordered list of step
    specs. video_all_codecs (per_source + repeatable) fans out to one step per
    (source, rep). Adding/retiring a measure changes only MEASURES/ORDER + the
    bench_run_* flag — this function and everything downstream are untouched."""
    reps = max(1, int(s.get("bench_video_reps", 5)))
    srcs = s.get("bench_sources") or DEFAULT_SOURCES
    plan, idx = [], 0
    for mid in ORDER:
        m = MEASURES.get(mid)
        if m is None or not _is_enabled(m, s):
            continue
        if m.per_source:
            for src in srcs:
                for rep in range(1, reps + 1):
                    plan.append({"index": idx, "id": m.id, "kind": m.kind,
                                 "label": f"{m.label} · {src} · rep {rep}/{reps}",
                                 "params": {"source_key": src, "rep": rep, "reps": reps}})
                    idx += 1
        else:
            plan.append({"index": idx, "id": m.id, "kind": m.kind,
                         "label": m.label, "params": {}})
            idx += 1
    return plan


def _config(s: dict) -> dict:
    return {
        "video_reps": max(1, int(s.get("bench_video_reps", 5))),
        "sources": s.get("bench_sources") or DEFAULT_SOURCES,
        "enabled": [mid for mid in ORDER if mid in MEASURES and _is_enabled(MEASURES[mid], s)],
    }


def init_manifest(bid: str, plan: list, config: dict) -> dict:
    return {
        "schema_version": 1,
        "benchmark_run_id": bid,
        "job_id": bid,            # so persist.load_result / glob *_{bid}.json works
        "visitor_key": None,      # operator-only; Lab sees all
        "status": "queued",       # queued | running | done | cancelled | error
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
        "config": config,
        "total_steps": len(plan),
        "steps": [{**st, "status": "pending", "result_ref": None,
                   "started_at": None, "finished_at": None, "error": None}
                  for st in plan],
        "owl_version": version.version_dict(),
    }


def _persist(manifest: dict) -> Path:
    """Write the manifest directly (stable per-run filename from created_at, so
    re-writes across midnight don't fork a second file). Matches load_result's
    `*_{bid}.json` glob."""
    manifest["saved_at"] = _now()
    day = (manifest.get("created_at") or _now())[:10]
    out_dir = persist.RESULTS_DIR / "benchmark"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}_{manifest['benchmark_run_id']}.json"
    path.write_text(json.dumps(manifest, indent=2))
    return path


def load_manifest(bid: str) -> Optional[dict]:
    return persist.load_result("benchmark", bid, visitor_key=None)


def create_run(bid: str, s: dict) -> dict:
    """Pre-create + persist a queued manifest (so a cancel-before-start still
    shows up in the results list). Called by POST /benchmark/run."""
    manifest = init_manifest(bid, build_plan(s), _config(s))
    _persist(manifest)
    return manifest


def cancel_queued(bid: str) -> None:
    """Mark a queued-but-not-started run cancelled (the coroutine never ran)."""
    m = load_manifest(bid)
    if not m or m.get("status") not in ("queued", "running"):
        return
    for st in m["steps"]:
        if st["status"] in ("pending", "running"):
            st["status"] = "skipped"
    m["status"] = "cancelled"
    m["finished_at"] = _now()
    _persist(m)


async def run_benchmark_job(bid: str, jobs: dict, s: dict) -> dict:
    """The benchmark coroutine. Sequences steps, reports progress on
    jobs[bid]['stage'], persists the manifest after every step, and checks
    jobs[bid]['cancel_requested'] between steps (coarse cancel — lands after the
    current step; an in-flight ffmpeg/inference can't be killed mid-step)."""
    manifest = load_manifest(bid) or create_run(bid, s)
    manifest["status"] = "running"
    manifest["started_at"] = _now()
    _persist(manifest)
    total = manifest["total_steps"]

    for step in manifest["steps"]:
        if jobs.get(bid, {}).get("cancel_requested"):
            for st in manifest["steps"]:
                if st["status"] in ("pending", "running"):
                    st["status"] = "skipped"
            manifest["status"] = "cancelled"
            manifest["finished_at"] = _now()
            _persist(manifest)
            return {"benchmark_run_id": bid, "status": "cancelled"}

        m = MEASURES.get(step["id"])
        if bid in jobs:
            jobs[bid]["stage"] = f"step {step['index'] + 1}/{total}: {step['label']}"
        step["status"] = "running"
        step["started_at"] = _now()
        _persist(manifest)

        if m is None:  # a retired measure present in a pre-built manifest
            step["status"] = "error"
            step["error"] = f"unknown measure {step['id']!r}"
            step["finished_at"] = _now()
            _persist(manifest)
            continue

        sub_id = uuid.uuid4().hex[:8]
        jobs[sub_id] = {"stage": "queued", "type": step["kind"], "label": step["label"],
                        "benchmark_run_id": bid, "result": None, "error": None}
        try:
            step["result_ref"] = await m.run(step, jobs, sub_id, s)
            step["status"] = "done"
        except Exception as ex:
            step["status"] = "error"
            step["error"] = str(ex)
            if m.fatal:
                step["finished_at"] = _now()
                manifest["status"] = "error"
                manifest["finished_at"] = _now()
                _persist(manifest)
                raise
        step["finished_at"] = _now()
        _persist(manifest)

    manifest["status"] = "done"
    manifest["finished_at"] = _now()
    _persist(manifest)
    return {"benchmark_run_id": bid, "status": "done"}
