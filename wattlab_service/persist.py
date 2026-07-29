import csv
import io
import json
from datetime import datetime
from pathlib import Path

import carbon
import canonical
import gpu
import power
import version

RESULTS_DIR = Path("/home/gos/wattlab/results")


def save_result(job_type: str, job_id: str, data: dict,
                visitor_key: str | None = None) -> Path:
    """Write a completed job result to results/{job_type}/{date}_{job_id}.json.

    Single insertion point for CO2e enrichment: walks the result tree and
    attaches a `co2e` block to every nested `energy` dict (see carbon.py).
    The intensity in use at save time is recorded inline so historical
    results stay accurate even if the live grid mix changes later.

    `visitor_key` (CR-026) — Anonymous → 'a:<pseudonymised-IP token>' (keyed
    hash of the truncated IP, never the raw address — analytics.hash_ip),
    Member → 'm:<email>', Lab → None. Persisted so list_results / load_result
    can scope to
    own-jobs for non-Lab visitors. Pre-CR-026 results have no key and
    are invisible to non-Lab listings.

    If `visitor_key` is not passed, falls back to queue_control's
    current_visitor_key — set by the worker before each job's coroutine
    runs, so save_result inside a workload module picks it up without
    needing to thread it through every call site.
    """
    if visitor_key is None:
        try:
            import queue_control as _qc
            visitor_key = _qc.current_visitor_key
        except Exception:
            visitor_key = None
    out_dir = RESULTS_DIR / job_type
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = out_dir / f"{date_str}_{job_id}.json"
    payload = {
        "job_id": job_id,
        "saved_at": datetime.now().isoformat(),
        "visitor_key": visitor_key,
        **data,
    }
    # Stamp the exact code that produced this result (provenance for CR-040
    # reproduce bundles + Track A analytics / re-flagging after formula changes).
    payload["owl_version"] = version.version_dict()
    # Stamp the GPU that produced this result (CR-060) so AMD (VAAPI/ROCm) and
    # NVIDIA (NVENC/CUDA) runs can never be silently compared across a hw swap.
    # Key is `gpu_hardware`, NOT `gpu` — the video CPU-vs-GPU "both" mode already
    # uses a top-level `gpu` key for the GPU-side measurement (video.py).
    payload["gpu_hardware"] = gpu.stamp()
    # Stamp the power meter too (cheap-wins pass, 2026-06-09) — the analogue of
    # gpu_hardware. A future PDU/IPMI swap (CR-031 §2) then can't be silently
    # compared against Tapo P110 runs; records meter name + polling resolution.
    payload["power_hardware"] = power.stamp()
    # CR-070 — pre-job idle guard provenance. The queue worker's guard outcome
    # (did wall power return to the previous job's floor before this job's
    # first baseline?) rides on the job's FIRST stored result — consume-once,
    # matched to the currently running job, so calibration artifacts and
    # re-saves never inherit it.
    try:
        import queue_control as _qc
        _stamp = _qc.consume_pre_job_stamp(job_id)
        if _stamp is not None and "pre_job_cooldown" not in payload:
            payload["pre_job_cooldown"] = _stamp
    except Exception:
        pass
    carbon.walk_and_enrich(payload)
    # CR-037 — anchor AI energy to a real video encode ("≈ N× a 120s encode").
    # AI result types only; video would just read "≈ 1×" of itself.
    if job_type in ("llm", "image"):
        canonical.enrich_result(payload)
    path.write_text(json.dumps(payload, indent=2))
    return path


def append_history_line(category: str, data: dict,
                        filename: str = "history.jsonl") -> Path:
    """Append one JSON line to results/<category>/<filename> (CR-012).

    Drift-tracking journal for variance calibration + thermal-recovery probe;
    also the CR-067 job-failure journal (filename="job_failures.jsonl").
    Append-only, no schema lock-in. `ts` and `owl_version` are stamped on
    every line so future analyses can correlate drift with code changes,
    kernel versions, hardware swaps.
    """
    out_dir = RESULTS_DIR / category
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    payload = {
        "ts": datetime.now().isoformat(),
        **data,
        "owl_version": version.version_dict(),
    }
    with path.open("a") as f:
        f.write(json.dumps(payload) + "\n")
    return path


def _visitor_match(data: dict, visitor_key: str | None) -> bool:
    """True if this record is visible to a caller with `visitor_key`.

    None caller (Lab) → everything visible.
    Non-None caller (Anonymous/Member) → only records with matching key.
    """
    if visitor_key is None:
        return True
    return data.get("visitor_key") == visitor_key


def list_results(job_type: str, limit: int = 10,
                 visitor_key: str | None = None) -> list:
    """Return summary metadata for last N results, newest first.

    `visitor_key` filters to own-jobs (CR-026) — None = unfiltered (Lab).
    """
    out_dir = RESULTS_DIR / job_type
    if not out_dir.exists():
        return []
    files = list(out_dir.glob("*.json"))
    results = []
    for f in files:
        try:
            data = json.loads(f.read_text())
            if not _visitor_match(data, visitor_key):
                continue
            results.append(_summarise(job_type, data))
        except Exception:
            pass
    results.sort(key=lambda r: r.get("saved_at") or "", reverse=True)
    return results[:limit]


def load_result(job_type: str, job_id: str,
                visitor_key: str | None = None) -> dict | None:
    """Load full result for a job_id.

    `visitor_key` filters to own-jobs (CR-026) — None = unfiltered (Lab).
    Returns None on mismatch (same shape as a not-found, so callers don't
    leak existence to a non-owner).
    """
    out_dir = RESULTS_DIR / job_type
    if not out_dir.exists():
        return None
    matches = list(out_dir.glob(f"*_{job_id}.json"))
    if not matches:
        return None
    data = json.loads(matches[0].read_text())
    if not _visitor_match(data, visitor_key):
        return None
    return data


def delete_result(job_type: str, job_id: str) -> bool:
    """Delete the stored result JSON for one job (Lab-only dev cleanup; gated at
    the route). Returns True if a file was removed. There is no separate CSV to
    delete — CSV is generated on the fly from the JSON. job_id is matched via the
    same dir-scoped glob load_result uses, so it can't escape RESULTS_DIR."""
    out_dir = RESULTS_DIR / job_type
    if not out_dir.exists():
        return False
    removed = False
    for p in out_dir.glob(f"*_{job_id}.json"):
        p.unlink(missing_ok=True)
        removed = True
    return removed


def to_csv(job_type: str, data: dict) -> str:
    """Flatten a result dict to CSV string."""
    output = io.StringIO()
    if job_type == "image":
        fieldnames = [
            "job_id", "saved_at", "prompt", "full_prompt", "modifier",
            "steps", "size", "model", "load_s", "gen_s", "total_s",
            "w_base", "w_task", "delta_w", "delta_e_wh",
            "co2e_g", "co2e_intensity_g_per_kwh", "co2e_source", "co2e_zone",
            "poll_count", "confidence", "cpu_base", "cpu_end",
        ]
        rows = _image_rows(data)
    elif job_type == "enhance":
        fieldnames = [
            "job_id", "saved_at", "mode", "side", "preset_key", "preset_origin",
            "input_name", "live", "output_res", "output_size_mb", "vqa_score",
            "w_base", "w_task", "delta_w", "delta_e_wh",
            "co2e_g", "co2e_intensity_g_per_kwh", "co2e_source", "co2e_zone",
            "poll_count", "confidence", "command",
        ]
        rows = _enhance_rows(data)
    elif job_type == "video":
        fieldnames = [
            "job_id", "saved_at", "mode", "preset", "duration_s",
            "output_size_mb", "vmaf", "vmaf_model",
            "w_base", "w_task", "delta_w", "delta_e_wh",
            "co2e_g", "co2e_intensity_g_per_kwh", "co2e_source", "co2e_zone",
            "poll_count", "confidence",
            "cpu_base", "cpu_peak", "cpu_mean",
            "gpu_base", "gpu_peak", "gpu_mean", "gpu_ppt_mean_w", "gpu_ppt_peak_w",
            "ffmpeg_cmd",
        ]
        rows = _video_rows(data)
    elif job_type == "rem":
        fieldnames = _REM_FIELDNAMES
        rows = _rem_rows(data)
    else:
        fieldnames = [
            "job_id", "saved_at", "model", "task", "duration_s",
            "output_tokens", "tokens_per_sec",
            "w_base", "w_task", "delta_w", "delta_e_wh", "mwh_per_token",
            "co2e_g", "co2e_intensity_g_per_kwh", "co2e_source", "co2e_zone",
            "poll_count", "confidence", "cpu_base", "gpu_base",
            "response",
        ]
        rows = _llm_rows(data)
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    # CR-036 — disclaimer that the `co2e_*` columns are indicative (third-party
    # grid factors × Wh), not a GoS primary measurement.
    # CR-044 follow-up: emit it as a TRAILING `#` line, not a leading one.
    # The leading variant put a non-data row (carrying a semicolon + stray
    # commas) on line 1, which made spreadsheet delimiter-sniffers
    # (Numbers/Excel) guess ";" and collapse the whole sheet to ~2 columns.
    # With the real comma-delimited header now on line 1, sniffers detect
    # commas correctly; parsers using `comment='#'` (pandas etc.) still skip
    # the trailing disclaimer.
    # No semicolon (or any non-comma delimiter) anywhere in this line: Numbers
    # sniffs the *whole* file for a delimiter, so a single ';' in the trailing
    # disclaimer was enough to make it pick ';' and collapse the sheet to ~2
    # columns. Comma must be the only delimiter-like char in the file.
    disclaimer = (
        "# OWL CSV export — energy columns (w_*, delta_*) are 🟢 direct "
        "measurements. co2e_* columns are 🟡 indicative (Wh × third-party "
        "grid intensity, not measured). See /methodology."
    )
    return output.getvalue() + disclaimer + "\n"


# --- Internal helpers ---

def _vmaf_model_export(score, model):
    """Model provenance for exports. Results stored without `vmaf_model`
    predate 2026-07-17, when the only model OWL ever ran was libvmaf's
    built-in vmaf_v0.6.1 — exporting that as fact keeps old rows
    self-describing next to v1-scored rows (different score currencies)."""
    if score is None:
        return None
    return model or "vmaf_v0.6.1"


def _co2e_fields(energy: dict) -> dict:
    """Pull the four flat CO2e CSV fields out of an `energy` dict's `co2e`
    block. Returns empty values if the block is absent (older results)."""
    c = (energy or {}).get("co2e") or {}
    i = c.get("intensity") or {}
    return {
        "co2e_g": c.get("grams"),
        "co2e_intensity_g_per_kwh": i.get("g_per_kwh"),
        "co2e_source": i.get("source"),
        "co2e_zone": i.get("zone"),
    }


# --- REM-prep CSV (one row per generated file). The first two columns are the
# output filename + share token so energy is trivially associated with the file. ---
_REM_FIELDNAMES = [
    "output_filename", "share_token", "batch_id", "job_id", "saved_at",
    "codec", "device", "height", "target_mode", "target_value",
    "achieved_vmaf", "vmaf_model", "achieved_bitrate_kbps", "converged",
    "w_base", "w_task", "delta_w", "delta_t_s", "delta_e_wh",
    "decode_wh", "encode_wh",
    "co2e_g", "co2e_intensity_g_per_kwh", "co2e_source", "co2e_zone",
    "poll_count", "confidence",
    "cpu_base", "cpu_peak", "gpu_base", "gpu_peak",
    "segment_total_s", "concat_method", "size_mb",
]


def _rem_row(data: dict) -> dict:
    """Flatten one rem_prep result dict to a CSV row (null-safe for produce-only
    runs where `energy`/`thermals` are None)."""
    e = data.get("energy") or {}
    t = data.get("thermals") or {}
    o = data.get("output") or {}
    seg = data.get("segment_layout_s") or {}
    es = data.get("energy_split") or {}
    mode = data.get("target_mode") or "vmaf"
    target_value = (data.get("target_bitrate_kbps") if mode == "bitrate"
                    else data.get("target_vmaf"))
    return {
        "output_filename": o.get("filename"),
        "share_token": o.get("share_token"),
        "batch_id": data.get("batch_id"),
        "job_id": data.get("job_id"),
        "saved_at": data.get("saved_at"),
        "codec": data.get("codec"),
        "device": data.get("device"),
        "height": data.get("height"),
        "target_mode": mode,
        "target_value": target_value,
        "achieved_vmaf": data.get("achieved_vmaf"),
        "vmaf_model": _vmaf_model_export(data.get("achieved_vmaf"),
                                         data.get("vmaf_model")),
        "achieved_bitrate_kbps": data.get("achieved_bitrate_kbps"),
        "converged": data.get("converged"),
        "w_base": e.get("w_base"), "w_task": e.get("w_task"),
        "delta_w": e.get("delta_w"), "delta_t_s": e.get("delta_t_s"),
        "delta_e_wh": e.get("delta_e_wh"),
        "decode_wh": es.get("decode_wh"), "encode_wh": es.get("encode_wh"),
        **_co2e_fields(e),
        "poll_count": e.get("poll_count"),
        "confidence": (e.get("confidence") or {}).get("label"),
        "cpu_base": t.get("cpu_base"), "cpu_peak": t.get("cpu_peak"),
        "gpu_base": t.get("gpu_base"), "gpu_peak": t.get("gpu_peak"),
        "segment_total_s": seg.get("total"),
        "concat_method": o.get("concat_method"),
        "size_mb": o.get("size_mb"),
    }


def _rem_rows(data: dict) -> list:
    return [_rem_row(data)]


def rem_batch_csv(batch_id: str) -> str:
    """Combined energy CSV for every stored rem result sharing `batch_id`, one
    row per file (sorted by saved_at). 'Live': returns only completed rows if
    fetched before all codecs in the batch finish."""
    out_dir = RESULTS_DIR / "rem"
    rows = []
    if out_dir.exists():
        for p in out_dir.glob("*.json"):
            try:
                d = json.loads(p.read_text())
            except Exception:
                continue
            if d.get("batch_id") == batch_id:
                rows.append(_rem_row(d))
    rows.sort(key=lambda r: r.get("saved_at") or "")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=_REM_FIELDNAMES, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    disclaimer = (
        "# OWL CSV export — energy columns (w_*, delta_*) are 🟢 direct "
        "measurements. co2e_* columns are 🟡 indicative (Wh × third-party "
        "grid intensity, not measured). See /methodology."
    )
    return output.getvalue() + disclaimer + "\n"


# ── Result-summary dispatch (Phase 4 of the 2026-06 refactor) ───────────────
# One summariser per (job_type, mode). docs/result_envelope.md is the
# catalogue of every mode and its consumers — register a new mode THERE and
# HERE (and in the wlRender* card for its type). An unregistered mode still
# summarises through the single-run shape so listings don't break, but the
# summary carries "unrecognised_mode": <mode> — loud in /results lists and
# trivially greppable — instead of being silently mis-summarised (the
# S37-class failure).


def _sum_benchmark(summary: dict, data: dict) -> dict:
    # CR-061 — benchmark-run manifest. Self-describing: summarise from the
    # steps list, tolerant of whatever measures a stored run contains.
    steps = data.get("steps", [])
    summary["benchmark_run_id"] = data.get("benchmark_run_id")
    summary["status"] = data.get("status")
    summary["started_at"] = data.get("started_at")
    summary["finished_at"] = data.get("finished_at")
    summary["total_steps"] = data.get("total_steps", len(steps))
    summary["n_done"] = sum(1 for s in steps if s.get("status") == "done")
    summary["n_error"] = sum(1 for s in steps if s.get("status") == "error")
    return summary


# --- image ---

def _sum_image_single(summary: dict, data: dict) -> dict:
    e = data.get("energy", {})
    gen = data.get("generation", {})
    summary["delta_e_wh"] = e.get("delta_e_wh")
    summary["delta_t_s"] = gen.get("total_s")
    summary["confidence"] = e.get("confidence", {})
    summary["b64_png"] = gen.get("b64_png", "")
    return summary


def _sum_image_both(summary: dict, data: dict) -> dict:
    for side in ("cpu", "gpu"):
        s = data.get(side, {})
        e = s.get("energy", {})
        gen = s.get("generation", {})
        summary[side] = {
            "delta_e_wh": e.get("delta_e_wh"),
            "delta_t_s": gen.get("total_s"),
            "confidence": e.get("confidence", {}),
            "b64_png": gen.get("b64_png", ""),
        }
    return summary


def _sum_image_compare_models(summary: dict, data: dict) -> dict:
    def _model_summary(s):
        e = s.get("energy", {})
        gen = s.get("generation", {})
        return {
            "model_key": s.get("model_key"),
            "model_label": gen.get("model_label"),
            "size_px": gen.get("size"),
            "wh_per_image": e.get("wh_per_image"),
            "delta_e_wh": e.get("delta_e_wh"),
            "delta_t_s": gen.get("gen_s_per_image"),
            "confidence": e.get("confidence", {}),
            "b64_png": gen.get("b64_png", ""),
        }
    # Legacy small/large aliases (pre-2026-05-27 records have only these).
    for side in ("small", "large"):
        summary[side] = _model_summary(data.get(side, {}))
    # N-way schema: carry the full per-model list so the renderer can
    # show every model (not just the first two). Without this, summaries
    # dropped to small/large and a 3-model run rendered only 2 cards.
    summary["models"] = [_model_summary(m) for m in data.get("models", [])]
    return summary


# --- enhance (CR-064 — partner GPU transcode/upscale, writer pixop.py) ---

def _sum_enhance_single(summary: dict, data: dict) -> dict:
    r = data.get("result", {})
    e = r.get("energy", {})
    summary["preset_key"] = r.get("preset_key")
    summary["preset_label"] = r.get("preset_label")
    summary["input_name"] = r.get("input_name")
    summary["live"] = r.get("live")
    summary["delta_e_wh"] = e.get("delta_e_wh")
    summary["delta_t_s"] = e.get("delta_t_s")
    summary["confidence"] = e.get("confidence", {}).get("flag")
    summary["vqa_score"] = (r.get("vqa") or {}).get("score")
    return summary


def _sum_enhance_compare(summary: dict, data: dict) -> dict:
    c = data.get("comparison", {})
    summary["preset_key"] = data.get("preset_key")
    summary["input_name"] = data.get("input_name")
    summary["ff_filter"] = data.get("ff_filter")
    summary["target_res"] = data.get("target_res")
    summary["ml_delta_e_wh"] = c.get("ml_delta_e_wh")
    summary["ff_delta_e_wh"] = c.get("ff_delta_e_wh")
    summary["energy_ratio"] = c.get("energy_ratio")
    for side, key in (("ml", "ml_confidence"), ("ffmpeg", "ff_confidence")):
        e = (data.get(side, {}).get("result") or {}).get("energy") or {}
        summary[key] = e.get("confidence", {}).get("flag")
    summary["ml_vqa_score"] = ((data.get("ml", {}).get("result") or {}).get("vqa") or {}).get("score")
    summary["ff_vqa_score"] = ((data.get("ffmpeg", {}).get("result") or {}).get("vqa") or {}).get("score")
    return summary


# --- video ---

def _sum_video_both(summary: dict, data: dict) -> dict:
    cpu_r = data.get("cpu", {})
    gpu_r = data.get("gpu", {})
    cpu_e = cpu_r.get("energy", {})
    gpu_e = gpu_r.get("energy", {})
    summary["cpu_preset"] = cpu_r.get("preset_label")
    summary["gpu_preset"] = gpu_r.get("preset_label")
    summary["cpu_delta_e_wh"] = cpu_e.get("delta_e_wh")
    summary["gpu_delta_e_wh"] = gpu_e.get("delta_e_wh")
    summary["cpu_duration_s"] = cpu_e.get("delta_t_s")
    summary["gpu_duration_s"] = gpu_e.get("delta_t_s")
    summary["cpu_confidence"] = cpu_e.get("confidence", {}).get("flag")
    summary["gpu_confidence"] = gpu_e.get("confidence", {}).get("flag")
    return summary


def _sum_video_codecs(summary: dict, data: dict) -> dict:
    a = data.get("analysis", {})
    best = a.get("most_efficient")
    summary["most_efficient"] = best["label"] if best else None
    summary["best_delta_e_wh"] = best["delta_e_wh"] if best else None
    fastest = a.get("fastest")
    summary["fastest"] = fastest["label"] if fastest else None
    # flag if all green
    codecs = data.get("codecs", {})
    flags = [data["codecs"][c][s]["energy"].get("confidence", {}).get("flag")
             for c in codecs for s in ("cpu", "gpu")
             if c in codecs and s in codecs[c]]
    summary["all_green"] = all(f == "🟢" for f in flags if f)
    return summary


def _sum_video_single(summary: dict, data: dict) -> dict:
    result = data.get("result", {})
    e = result.get("energy", {})
    summary["preset"] = result.get("preset_label")
    summary["delta_e_wh"] = e.get("delta_e_wh")
    summary["duration_s"] = e.get("delta_t_s")
    summary["confidence"] = e.get("confidence", {}).get("flag")
    return summary


# --- llm family (rag persists under results/llm/) ---

def _llm_tail(summary: dict, e: dict, i: dict) -> dict:
    summary["mwh_per_token"] = e.get("mwh_per_token")
    summary["tokens_per_sec"] = i.get("tokens_per_sec")
    summary["confidence"] = e.get("confidence", {}).get("flag")
    return summary


def _sum_llm_rag(summary: dict, data: dict) -> dict:
    summary["task"] = f"RAG/{data.get('rag_mode', 'baseline')}"
    return _llm_tail(summary, data.get("energy", {}), data.get("inference", {}))


def _sum_llm_rag_compare(summary: dict, data: dict) -> dict:
    summary["task"] = "RAG compare (3 modes)"
    rl = data.get("results", {}).get("rag_large", {})
    return _llm_tail(summary, rl.get("energy", {}), rl.get("inference", {}))


def _sum_llm_all(summary: dict, data: dict) -> dict:
    summary["task"] = "T1+T2+T3"
    t3 = data.get("tasks", {}).get("T3", {})
    return _llm_tail(summary, t3.get("energy", {}), t3.get("inference", {}))


def _sum_llm_all_both(summary: dict, data: dict) -> dict:
    summary["task"] = "T1+T2+T3 · CPU vs GPU"
    t3 = data.get("gpu", {}).get("T3", {})
    return _llm_tail(summary, t3.get("energy", {}), t3.get("inference", {}))


def _sum_llm_both(summary: dict, data: dict) -> dict:
    summary["task"] = data.get("task_label")
    gpu = data.get("gpu", {})
    return _llm_tail(summary, gpu.get("energy", {}), gpu.get("inference", {}))


def _sum_llm_batch(summary: dict, data: dict) -> dict:
    summary["task"] = data.get("task_label")
    agg = data.get("aggregate", {})
    runs = data.get("runs", [])
    summary["mwh_per_token"] = agg.get("mwh_per_token_mean")
    summary["tokens_per_sec"] = agg.get("tokens_per_sec_mean")
    try:
        summary["confidence"] = runs[-1]["energy"]["confidence"]["flag"]
    except (IndexError, KeyError):
        summary["confidence"] = None
    return summary


def _sum_llm_single(summary: dict, data: dict) -> dict:
    summary["task"] = data.get("task_label")
    return _llm_tail(summary, data.get("energy", {}), data.get("inference", {}))


def _sum_decode_panel(summary: dict, data: dict) -> dict:
    """decode_panel — external decode-bench import (client-device decode energy).
    One envelope per device; runs[] carry per-run energy blocks."""
    runs = data.get("runs", [])
    summary["device"] = (data.get("device") or {}).get("name")
    summary["runs"] = len(runs)
    flags = [((r.get("energy") or {}).get("confidence") or {}).get("flag")
             for r in runs]
    summary["all_green"] = bool(flags) and all(f == "🟢" for f in flags if f)
    deltas = [(r.get("energy") or {}).get("delta_w") for r in runs
              if (r.get("energy") or {}).get("delta_w") is not None]
    if deltas:
        summary["delta_w_min"] = min(deltas)
        summary["delta_w_max"] = max(deltas)
    return summary


# mode → summariser, per job_type. The single-run summariser doubles as the
# fallback for each family (matching the pre-dispatch else-branches, so
# legacy records keep their exact summaries).
_SUMMARISERS = {
    "image": {
        "cpu": _sum_image_single, "gpu": _sum_image_single,
        "both": _sum_image_both,
        "compare_models": _sum_image_compare_models,
    },
    "video": {
        "single": _sum_video_single, "?": _sum_video_single,
        "both": _sum_video_both,
        "all_codecs": _sum_video_codecs,
        "codecs_cpu": _sum_video_codecs, "codecs_gpu": _sum_video_codecs,
    },
    "enhance": {
        "enhance": _sum_enhance_single,
        "enhance_compare": _sum_enhance_compare,
    },
    "decode": {
        "decode_panel": _sum_decode_panel,
    },
    "llm": {
        "single": _sum_llm_single,
        "rag": _sum_llm_rag,
        "rag_compare": _sum_llm_rag_compare,
        "all": _sum_llm_all,
        "all_both": _sum_llm_all_both,
        "both": _sum_llm_both,
        "batch": _sum_llm_batch,
        # compare-across-models records carry no top-level energy block;
        # the single-style summary (Nones) matches pre-dispatch behaviour.
        "compare_models": _sum_llm_single,
        "rag_compare_models": _sum_llm_single,
    },
}

_MODE_DEFAULTS = {"image": "cpu", "video": "?", "llm": "single",
                  "enhance": "enhance", "decode": "decode_panel"}
_FALLBACKS = {"image": _sum_image_single, "video": _sum_video_single,
              "llm": _sum_llm_single, "enhance": _sum_enhance_single,
              "decode": _sum_decode_panel}


def _summarise(job_type: str, data: dict) -> dict:
    summary = {"job_id": data.get("job_id"), "saved_at": data.get("saved_at")}
    if job_type == "benchmark":
        return _sum_benchmark(summary, data)
    family = job_type if job_type in _SUMMARISERS else "llm"
    mode = data.get("mode", _MODE_DEFAULTS[family])
    summary["mode"] = mode
    if family == "image":
        summary["full_prompt"] = data.get("full_prompt", data.get("prompt", ""))
        summary["model_label"] = data.get("model_label")
    elif family == "llm":
        summary["model"] = data.get("model_label")
    handler = _SUMMARISERS[family].get(mode)
    if handler is None:
        # Loud contract (docs/result_envelope.md): a mode nobody registered.
        summary["unrecognised_mode"] = mode
        handler = _FALLBACKS[family]
    return handler(summary, data)


def _enhance_rows(data: dict) -> list:
    """CR-064 — one row per measured pass (single = 1, compare = 2)."""
    def _row(r: dict, side: str) -> dict:
        e = r.get("energy", {})
        s = r.get("stream") or {}
        res = (f"{s.get('width')}x{s.get('height')}"
               if s.get("width") and s.get("height") else None)
        return {
            "job_id": data.get("job_id"),
            "saved_at": data.get("saved_at"),
            "mode": data.get("mode"),
            "side": side,
            "preset_key": r.get("preset_key"),
            "preset_origin": r.get("preset_origin"),
            "input_name": r.get("input_name") or data.get("input_name"),
            "live": r.get("live"),
            "output_res": res,
            "output_size_mb": r.get("output_size_mb"),
            "vqa_score": (r.get("vqa") or {}).get("score"),
            "w_base": e.get("w_base"),
            "w_task": e.get("w_task"),
            "delta_w": e.get("delta_w"),
            "delta_e_wh": e.get("delta_e_wh"),
            **_co2e_fields(e),
            "poll_count": e.get("poll_count"),
            "confidence": e.get("confidence", {}).get("flag"),
            "command": (r.get("transcode") or {}).get("docker_cmd"),
        }
    if data.get("mode") == "enhance_compare":
        return [_row(data.get("ml", {}).get("result") or {}, "ai"),
                _row(data.get("ffmpeg", {}).get("result") or {}, "ffmpeg")]
    return [_row(data.get("result") or {}, "ai")]


def _image_rows(data: dict) -> list:
    e = data.get("energy", {})
    gen = data.get("generation", {})
    t = data.get("thermals", {})
    return [{
        "job_id": data.get("job_id"),
        "saved_at": data.get("saved_at"),
        "prompt": data.get("prompt"),
        "full_prompt": data.get("full_prompt"),
        "modifier": data.get("modifier"),
        "steps": gen.get("steps"),
        "size": gen.get("size"),
        "model": gen.get("model"),
        "load_s": gen.get("load_s"),
        "gen_s": gen.get("gen_s"),
        "total_s": gen.get("total_s"),
        "w_base": e.get("w_base"), "w_task": e.get("w_task"),
        "delta_w": e.get("delta_w"), "delta_e_wh": e.get("delta_e_wh"),
        **_co2e_fields(e),
        "poll_count": e.get("poll_count"),
        "confidence": e.get("confidence", {}).get("label"),
        "cpu_base": t.get("cpu_base"), "cpu_end": t.get("cpu_end"),
    }]


def _video_rows(data: dict) -> list:
    common = {
        "job_id": data.get("job_id"),
        "saved_at": data.get("saved_at"),
        "mode": data.get("mode"),
    }
    mode = data.get("mode")
    if mode == "both":
        return [_video_result_row(common, data["cpu"]),
                _video_result_row(common, data["gpu"])]
    elif mode == "all_codecs":
        rows = []
        for codec_name, codec_data in data.get("codecs", {}).items():
            for side in ("cpu", "gpu"):
                if side in codec_data:
                    rows.append(_video_result_row(common, codec_data[side]))
        return rows
    else:
        return [_video_result_row(common, data.get("result", {}))]


def _video_result_row(common: dict, r: dict) -> dict:
    e = r.get("energy", {})
    t = r.get("thermals", {})
    return {
        **common,
        "preset": r.get("preset_label"),
        "duration_s": e.get("delta_t_s"),
        "output_size_mb": r.get("output_size_mb"),
        "vmaf": r.get("vmaf"),
        "vmaf_model": _vmaf_model_export(r.get("vmaf"), r.get("vmaf_model")),
        "w_base": e.get("w_base"), "w_task": e.get("w_task"),
        "delta_w": e.get("delta_w"), "delta_e_wh": e.get("delta_e_wh"),
        **_co2e_fields(e),
        "poll_count": e.get("poll_count"),
        "confidence": e.get("confidence", {}).get("label"),
        "cpu_base": t.get("cpu_base"), "cpu_peak": t.get("cpu_peak"), "cpu_mean": t.get("cpu_mean"),
        "gpu_base": t.get("gpu_base"), "gpu_peak": t.get("gpu_peak"), "gpu_mean": t.get("gpu_mean"),
        "gpu_ppt_mean_w": t.get("gpu_ppt_mean_w"), "gpu_ppt_peak_w": t.get("gpu_ppt_peak_w"),
        "ffmpeg_cmd": r.get("transcode", {}).get("ffmpeg_cmd", ""),
    }


def _llm_rows(data: dict) -> list:
    mode = data.get("mode", "single")
    common = {"job_id": data.get("job_id"), "saved_at": data.get("saved_at"),
              "model": data.get("model_label")}

    def _row(task_label, i, e, t):
        return {**common,
            "task": task_label,
            "duration_s": i.get("duration_s"),
            "output_tokens": i.get("output_tokens"),
            "tokens_per_sec": i.get("tokens_per_sec"),
            "w_base": e.get("w_base"), "w_task": e.get("w_task"),
            "delta_w": e.get("delta_w"), "delta_e_wh": e.get("delta_e_wh"),
            "mwh_per_token": e.get("mwh_per_token"),
            **_co2e_fields(e),
            "poll_count": e.get("poll_count"),
            "confidence": e.get("confidence", {}).get("label"),
            "cpu_base": t.get("cpu_base"), "gpu_base": t.get("gpu_base"),
            "response": i.get("response", ""),
        }

    if mode == "all":
        rows = []
        for tk, tr in data.get("tasks", {}).items():
            rows.append(_row(f"{tk} {tr.get('task_label','')}",
                             tr.get("inference", {}), tr.get("energy", {}),
                             tr.get("thermals", {})))
        return rows
    elif mode == "all_both":
        rows = []
        for dev in ("cpu", "gpu"):
            for tk, tr in data.get(dev, {}).items():
                rows.append(_row(f"{tk} {tr.get('task_label','')} ({dev})",
                                 tr.get("inference", {}), tr.get("energy", {}),
                                 tr.get("thermals", {})))
        return rows
    elif mode == "both":
        rows = []
        for dev in ("cpu", "gpu"):
            tr = data.get(dev, {})
            rows.append(_row(f"{data.get('task_label','')} ({dev})",
                             tr.get("inference", {}), tr.get("energy", {}),
                             tr.get("thermals", {})))
        return rows
    elif mode == "rag":
        e = data.get("energy", {})
        i = data.get("inference", {})
        t = data.get("thermals", {})
        label = f"RAG/{data.get('rag_mode','')} — {data.get('question','')[:50]}"
        return [_row(label, i, e, t)]
    elif mode == "rag_compare":
        rows = []
        for m, res in data.get("results", {}).items():
            e = res.get("energy", {})
            i = res.get("inference", {})
            t = res.get("thermals", {})
            rows.append(_row(f"RAG/{m} — {data.get('question','')[:40]}", i, e, t))
        return rows
    elif mode == "batch":
        rows = []
        t = data.get("thermals", {})
        for run in data.get("runs", []):
            rows.append(_row(f"{data.get('task_label','')} run {run['run']}",
                             run.get("inference", {}), run.get("energy", {}), t))
        return rows
    else:  # single
        e = data.get("energy", {})
        i = data.get("inference", {})
        t = data.get("thermals", {})
        return [_row(data.get("task_label", ""), i, e, t)]
