"""
routes_peer.py — the node-to-node job API (CR-085 autonomy Phase 4).

Served by every OWL node. Lab tier (LAN/tunnel only) AND an HMAC signature
(peer.verify) on every call. Jobs run on THIS node's own queue, meters and
scorer, and are stamped by this node's persist.save_result; the caller mirrors
progress and imports the envelope verbatim (peer.follow / persist.import_result).
Feature modules never import main.
"""
import glob
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

import gpu
import hosts
import peer
import persist
import queue_control
import settings as cfg
from capabilities import PEER_API, requires
from runtime import jobs, job_status as _job_status

router = APIRouter()


async def require_peer(request: Request):
    body = await request.body()
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    if not peer.verify(request.method, path, body, request.headers.get(peer.HEADER, "")):
        raise HTTPException(status_code=403, detail="peer signature invalid")


_DEPS = [Depends(requires(PEER_API)), Depends(require_peer)]


def _engines() -> dict:
    """What this node can encode on: CPU always; hardware when its backend has it."""
    out = {"cpu": {"label": "CPU (software)", "codecs": ["h264", "h265", "av1"]}}
    if gpu.BACKEND.available:
        out["gpu"] = {"label": {"apple": "Apple media engine (VBR)", "nvidia": "NVENC",
                                "amd": "VAAPI"}.get(gpu.BACKEND.vendor, "GPU"),
                      "codecs": [c for c in ("h264", "h265", "av1") if gpu.supports(c)]}
    return out


@router.get("/peer/info", dependencies=_DEPS)
async def peer_info():
    import image_gen, llm, version
    s = cfg.load()
    return {"host": hosts.identity(hosts.local_host()), "gpu": gpu.stamp(),
            "engines": _engines(),
            "image_models": list(image_gen.IMAGE_MODELS.keys()),
            "llm_models": list(llm.MODELS.keys()),
            "mlx_models": sorted((s.get("local_mlx_models") or {}).keys()),
            "queue_depth": queue_control.depth(),
            "version": version.version_dict()}


_PRESET = {("both", "h264"): "both", ("both", "h265"): "h265_both", ("both", "av1"): "av1_both",
           ("cpu", "h264"): "cpu", ("cpu", "h265"): "h265_cpu", ("cpu", "av1"): "av1_cpu",
           ("gpu", "h264"): "gpu", ("gpu", "h265"): "h265_gpu", ("gpu", "av1"): "av1_gpu"}


@router.post("/peer/jobs", dependencies=_DEPS)
async def peer_submit(request: Request):
    req = json.loads(await request.body() or b"{}")
    jtype, p = req.get("type"), req.get("params") or {}
    job_id = f"{hosts.local_host()['id']}-{uuid.uuid4().hex[:8]}"
    label = f"Peer job ({jtype})"

    if jtype == "video":
        import routes_video
        from sources import PRELOADED
        codec, engine = p.get("codec", "h264"), p.get("engine", "both")
        preset = _PRESET.get((engine, codec))
        src = PRELOADED.get(p.get("source_key"))
        if preset is None or src is None or not src["path"].exists():
            return JSONResponse({"error": "unknown preset/source on this node"}, status_code=400)
        if engine != "cpu" and not gpu.supports(codec):
            return JSONResponse({"error": f"no hardware {codec} encoder on this node"}, status_code=400)
        vmaf = p.get("compute_vmaf")
        async def coro():
            await routes_video.run_job(job_id, src["path"], preset, False,
                                       source_key=p.get("source_key"),
                                       vmaf_override=None if vmaf is None else bool(vmaf))
    elif jtype == "llm":
        import routes_llm
        async def coro():
            await routes_llm.run_llm_job(job_id, p["model_key"], p.get("task_key", "T2"),
                                         1, False, None, p.get("device", "gpu"))
    elif jtype == "llm_mlx":
        import remote_ai
        async def coro():
            try:
                jobs[job_id].update({"status": "running", "stage": "baseline"})
                r = await remote_ai.run_local_mlx(p["model_key"], p.get("task_key", "T2"), job_id, jobs)
                persist.save_result("llm", job_id, r)
                jobs[job_id].update({"status": "done", "stage": "done", "result": r})
            except Exception as e:
                jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}
    elif jtype in ("image_session", "image"):
        import remote_ai, image_gen, curated
        async def coro():
            try:
                jobs[job_id].update({"status": "running", "stage": "starting"})
                if jtype == "image_session":
                    prompt = (p.get("prompt") or "").strip()
                    r = await remote_ai.run_image_session(
                        "local", p.get("model_key", "sd-turbo"), jobs, job_id,
                        per_prompt=int(p.get("per_prompt", 5)), settle_s=int(p.get("settle_s", 30)),
                        prompts=[prompt] if prompt else None, target_s=float(p.get("target_s", 30)))
                else:
                    r = await image_gen.run_image_measurement(
                        (p.get("prompt") or curated.CANONICAL_IMAGE_PROMPT), job_id, jobs,
                        device=p.get("device", "gpu"), model_key=p.get("model_key", "sd-turbo"))
                persist.save_result("image", job_id, r)
                jobs[job_id].update({"status": "done", "stage": "done", "result": r})
            except Exception as e:
                jobs[job_id].update({"status": "error", "stage": "error", "error": str(e)})
    else:
        return JSONResponse({"error": f"unknown job type {jtype!r}"}, status_code=400)

    position = queue_control.enqueue(job_id, jtype.split("_")[0], label, coro, request=None)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


@router.get("/peer/jobs/{job_id}", dependencies=_DEPS)
async def peer_status(job_id: str):
    return _job_status(job_id)


@router.post("/peer/jobs/{job_id}/cancel", dependencies=_DEPS)
async def peer_cancel(job_id: str):
    return {"cancelled": bool(queue_control.cancel_pending(job_id))}


def _result_path(job_type: str, job_id: str):
    if job_type not in ("video", "llm", "image") or "/" in job_id or ".." in job_id:
        return None
    m = sorted(glob.glob(str(persist.RESULTS_DIR / job_type / f"*_{job_id}.json")))
    return Path(m[-1]) if m else None


@router.get("/peer/results/{job_type}/{job_id}", dependencies=_DEPS)
async def peer_result(job_type: str, job_id: str):
    p = _result_path(job_type, job_id)
    if p is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    d = json.loads(p.read_text())
    if not (d.get("host") or {}).get("id"):
        # Pre-envelope-v2 results carry no host: by construction they are this
        # node's (GoS1). Make the read-time default explicit for the importer.
        d["host"] = hosts.result_host(d)
        d["host_inferred"] = True
    return d


@router.get("/peer/results/{job_type}", dependencies=_DEPS)
async def peer_result_index(job_type: str, since: str = ""):
    """Replication index (Phase 5): envelopes THIS node produced (host = this
    node), saved after `since` (ISO), oldest first."""
    if job_type not in ("video", "llm", "image"):
        return JSONResponse({"error": "bad type"}, status_code=400)
    me = hosts.local_host()["id"]
    out = []
    for f in sorted((persist.RESULTS_DIR / job_type).glob("*.json")):
        if since and f.name[:10] < since[:10]:
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if hosts.result_host(d).get("id") != me or (since and str(d.get("saved_at", "")) <= since):
            continue
        out.append({"job_id": d.get("job_id"), "saved_at": d.get("saved_at")})
    return {"host": me, "type": job_type, "results": out}


@router.get("/peer/members", dependencies=_DEPS)
async def peer_members():
    """Member allowlist for replication to other nodes (one writer — the node
    whose peers mark it members_source)."""
    import auth
    return {"host": hosts.local_host()["id"], "members": auth.list_members()}


@router.post("/peer/replicate-now", dependencies=_DEPS)
async def peer_replicate_now():
    """Trigger an immediate pull from this node's peers (drills, tests)."""
    import asyncio, replication
    return await asyncio.get_event_loop().run_in_executor(None, replication.pull_all)
