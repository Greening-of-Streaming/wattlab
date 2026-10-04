"""
remote_video.py — encode measurements on a remote compute host (CR-085).

GoS1's service drives the remote host over SSH (hosts.py) and polls the
remote host's OWN plugs (power.use_meters). The measurement contract is the
local one, unchanged: shared baseline/task samplers (power.py), the same
energy arithmetic and dual-meter combine, the same confidence model, VMAF
scored on GoS1 against the same source bytes (sha256-verified copy).

What differs from a GoS1 run, and is recorded on the result:
  · no focus mode on the remote host yet (`remote_focus: "none"`)
  · thermals are not sampled remotely (fields present, values None)
  · the rolling idle floor (power.LAST_W_BASE) is per host — a GoS2 baseline
    must never become GoS1's pre-job reference, or the next GoS1 job's idle
    guard would wait for ~1 W.
"""

import asyncio
import re
import shlex
import time
from pathlib import Path
from typing import Optional

import energy
import hosts
import power
import settings as cfg
from confidence import confidence
from video import (LOCK_FILE, UPLOAD_DIR, _attach_vmaf, _clear_progress,
                   _make_progress_cb, _probe_duration, analyse,
                   cooldown_between_runs, probe_output_stream, transcode)

REMOTE_THERMAL_KEYS = ("cpu_base", "cpu_peak", "cpu_mean", "gpu_base", "gpu_peak",
                       "gpu_mean", "gpu_ppt_mean_w", "gpu_ppt_peak_w")

# Per-host rolling idle floor (the remote analogue of power.LAST_W_BASE).
_HOST_FLOOR: dict = {}

_BPS_KEY = {"h264": "h264_bitrate_kbps", "h265": "h265_bitrate_kbps",
            "av1": "av1_bitrate_kbps"}


def preset_key(host_id: str, codec: str, engine_id: str) -> str:
    """Side key on the result. The pair renderer and analyse() treat a key
    containing 'gpu' as the hardware side, so hardware engines map there."""
    e = hosts.engine(hosts.get(host_id) or {}, engine_id) or {}
    side = "gpu" if e.get("kind") == "hw" else "cpu"
    return f"{host_id}_{codec}_{side}"


async def _baseline(host: dict, polls: int) -> dict:
    """Baseline on the host's meters with the host's own rolling floor."""
    saved = power.LAST_W_BASE
    power.LAST_W_BASE = _HOST_FLOOR.get(host["id"])
    try:
        with power.use_meters(host["meters"]):
            b = await power.sample_baseline(polls, read_watts=power.get_power_watts)
        _HOST_FLOOR[host["id"]] = b["w_base"]
    finally:
        power.LAST_W_BASE = saved
    return {
        "w_base": b["w_base"],
        "baseline_samples_w": b["samples_w"],
        "cpu_temp_base": None,
        "gpu_temp_base": None,
        **{k: b[k] for k in ("baseline_samples_w_2", "meter2_degraded",
                             "baseline_reference_w", "baseline_elevated") if k in b},
    }


async def _encode_once(host: dict, engine_id: str, codec: str, in_rel: str,
                       input_path: Path, job_id: str, baseline: dict,
                       jobs: Optional[dict]) -> dict:
    s = cfg.load()
    bps = int(s[_BPS_KEY[codec]])
    gop = int(s.get("encode_gop_frames", 120))
    key = preset_key(host["id"], codec, engine_id)
    eng = hosts.engine(host, engine_id)
    spec = hosts.codec_spec(host, engine_id, codec)
    out_rel = f"{host.get('workdir', 'owl')}/out/{job_id}_{key}_out.mp4"
    remote = hosts.encode_cmd(host, engine_id, codec, in_rel, out_rel, bps, gop)
    cmd = hosts.ssh_base(host) + [remote]

    duration_s = _probe_duration(input_path)
    progress_cb = _make_progress_cb(jobs, job_id, duration_s) if jobs is not None else None
    if jobs is not None:
        _clear_progress(jobs, job_id)
        if duration_s is not None:
            jobs[job_id]["input_duration_s"] = round(duration_s, 1)

    stop_event = asyncio.Event()
    t_start = time.time()
    with power.use_meters(host["meters"]):
        poll_task = asyncio.create_task(
            power.sample_task(stop_event, read_watts=power.get_power_watts))
    tr = await asyncio.get_event_loop().run_in_executor(
        None, lambda: transcode(cmd, progress_cb=progress_cb))
    t_end = time.time()
    stop_event.set()
    readings = await poll_task
    if jobs is not None:
        _clear_progress(jobs, job_id)
    if not tr.get("success"):
        raise RuntimeError(f"{host['label']} {spec['encoder']} encode failed: "
                           f"{tr.get('stderr', '')[-300:]}")
    tr["ffmpeg_version"] = hosts.remote_ffmpeg_version(host)
    tr["ffmpeg_cmd"] = remote          # the command that ran ON the host

    delta_t = round(t_end - t_start, 1)
    w_base = baseline["w_base"]
    task_samples_w = [round(r["watts"], 2) for r in readings]
    w_task = sum(r["watts"] for r in readings) / len(readings) if readings else w_base
    delta_w = round(w_task - w_base, 2)
    meters = power.meters_summary(baseline, readings, task_samples_w)
    if meters and "delta_w_combined" in meters:
        delta_w = meters["delta_w_combined"]
    conf = confidence(delta_w, len(readings), w_base,
                      baseline_samples_w=baseline.get("baseline_samples_w"),
                      task_samples_w=task_samples_w, meters=meters)

    # Pull the encode back for size, ffprobe and the terminal VMAF pass —
    # all scored on GoS1 so every engine is judged by the same scorer.
    local_out = UPLOAD_DIR / f"{job_id}_{key}_out.mp4"
    fetched = await asyncio.to_thread(hosts.fetch, host, out_rel, local_out)
    hosts.run(host, f"rm -f {shlex.quote(out_rel)}")
    out_size_mb = round(local_out.stat().st_size / 1024 / 1024, 2) \
        if fetched and local_out.exists() else None

    return {
        "preset_key": key,
        "preset_label": f"{hosts.CODEC_LABEL[codec]} · {eng['label']} · {host['label']}",
        "preset_detail": f"{spec['encoder']} · {bps} kbps ABR · 1080p · {host.get('chip', '')}",
        "engine": {"id": engine_id, "kind": eng.get("kind", "cpu"),
                   "label": eng["label"], "encoder": spec["encoder"]},
        "host": hosts.identity(host),
        "transcode": tr,
        "output_size_mb": out_size_mb,
        "stream": probe_output_stream(local_out) if fetched else None,
        "energy": {
            "w_base": round(w_base, 2),
            "w_task": round(w_task, 2),
            "delta_w": round(delta_w, 2),
            "delta_t_s": delta_t,
            "delta_e_wh": energy.energy_wh(delta_w, delta_t),
            "poll_count": len(readings),
            "baseline_samples_w": baseline.get("baseline_samples_w"),
            "task_samples_w": task_samples_w,
            "confidence": conf,
            **({"meters": meters} if meters else {}),
        },
        # Same key set as a GoS1 side (analyse() and the renderers index
        # them); values None until remote sensors exist.
        "thermals": {**{k: None for k in REMOTE_THERMAL_KEYS},
                     "note": "not sampled on remote hosts"},
    }


def _scope(host: dict) -> str:
    return (f"Device layer only ({host['label']}, {host.get('chip', '')}). "
            "Network, CDN, CPE excluded.")


async def run_remote(input_path: Path, job_id: str, host_id: str, codec: str,
                     engine_id: str, jobs: dict = None,
                     vmaf_override: Optional[bool] = None) -> dict:
    """One remote job. `engine_id` = a registry engine id, or "both" for the
    host's CPU engine then its hardware engine (the "both" result shape, so
    the existing pair renderer and analyse() apply unchanged)."""
    host = hosts.get(host_id)
    if host is None:
        raise ValueError(f"unknown or disabled host '{host_id}'")
    s = cfg.load()
    if vmaf_override is not None:
        s = {**s, "vmaf_enabled": bool(vmaf_override)}
    if engine_id == "both":
        kinds = {e.get("kind"): eid for eid, e in (host.get("engines") or {}).items()
                 if codec in (e.get("codecs") or {})}
        if "cpu" not in kinds or "hw" not in kinds:
            raise ValueError(f"{host['label']} has no CPU+hardware pair for {codec}")
        sequence = [kinds["cpu"], kinds["hw"]]
    else:
        if not hosts.codec_spec(host, engine_id, codec):
            raise ValueError(f"{host['label']}/{engine_id} cannot encode {codec}")
        sequence = [engine_id]

    if jobs is not None: jobs[job_id]["stage"] = "sync"
    inp = await asyncio.to_thread(hosts.ensure_input, host, Path(input_path))

    sides, baselines, cooldown = [], [], None
    LOCK_FILE.write_text(job_id)
    try:
        for i, eid in enumerate(sequence):
            if i:
                if jobs is not None: jobs[job_id]["stage"] = "rest"
                saved = power.LAST_W_BASE
                try:
                    with power.use_meters(host["meters"]):
                        cooldown = await cooldown_between_runs(
                            fixed_seconds=s["video_cooldown_s"],
                            reference_w=sides[0]["energy"]["w_base"],
                            stage="rest", jobs=jobs, job_id=job_id)
                finally:
                    power.LAST_W_BASE = saved
            if jobs is not None: jobs[job_id]["stage"] = "baseline" if not i else "baseline_2"
            baseline = await _baseline(host, s["baseline_polls"])
            baselines.append(baseline)
            if jobs is not None: jobs[job_id]["stage"] = f"{eid}_encode"
            sides.append(await _encode_once(host, eid, codec, inp["rel"], input_path,
                                            job_id, baseline, jobs))
    finally:
        LOCK_FILE.unlink(missing_ok=True)

    await _attach_vmaf(sides, Path(input_path), job_id, s, jobs)
    common = {"job_id": job_id, "host": hosts.identity(host),
              "input": {"name": Path(input_path).name, "sha256": inp["sha256"]},
              "remote_focus": "none", "scope": _scope(host)}
    if len(sides) == 1:
        return {"mode": "single", "baseline": baselines[0], "result": sides[0], **common}
    analysis = analyse(sides[0], sides[1])
    # analyse() words the hardware side "GPU"; keep its winner keys (the pair
    # renderer reads them) but name the real engine in the prose.
    hw_label = sides[1]["engine"]["label"]
    for k in ("finding", "quality_note"):
        if isinstance(analysis.get(k), str):
            analysis[k] = re.sub(r"\bGPU\b", hw_label, analysis[k])
    analysis["side_labels"] = {"CPU": sides[0]["engine"]["label"], "GPU": hw_label}
    return {"mode": "both", "cpu": sides[0], "gpu": sides[1],
            "analysis": analysis, "cooldown": cooldown, **common}
