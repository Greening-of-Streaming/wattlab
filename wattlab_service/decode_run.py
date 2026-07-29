"""
decode_run.py — Stage 2 of /decode: decode runs from the page, v2.

v2 (2026-07-29 design talk): MODE is the first-class choice.
  headless — devices are fully independent (own meter, own silicon, no shared
             resource), so selected devices run IN PARALLEL: one queue job
             fans out to one bench.py per device. Pis decode to null (pure
             decode); the GTV always renders (Android has no null sink) — its
             headless rows carry a display caveat and the screen simply is
             not claimed.
  screen   — exclusive, one device: the run claims the shared monitor first,
             meters it as context (Lab-E), and (default on) brackets the
             content rows with a white/black PANEL CALIBRATION pair — the
             probe that measured white−black = +5.0 W on this LCD
             (2026-07-29), anchoring every session against panel drift.

Templates are device-agnostic row sets (content × codec × regime); the
device selection composes with them at materialisation time, with live
addresses from rig.RIG. The proven July harness
(/srv/data/owl/decode-bench/bench.py) does every measured second; progress
is parsed from its phase log lines per device.

Results: ONE combined envelope per run — devices side by side (the July
report's cross-device tables, live), plus a flattened top-level `runs` list
(device-stamped) for the generic results machinery.
"""
import asyncio
import json
import logging
import re
import subprocess
import time
from pathlib import Path

import rig
from persist import save_result
from runtime import jobs

log = logging.getLogger(__name__)

BENCH_DIR = Path("/srv/data/owl/decode-bench")
BENCH = BENCH_DIR / "bench.py"
STREAMS = BENCH_DIR / "streams"
STREAM_BASE_URL = "http://192.168.1.62:8123"
_WL_ENV = "WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000"

MODES = ("headless", "screen")

# --- Templates (device-agnostic) --------------------------------------------
TEMPLATES: dict = {
    "bbb_h264_smoke": {
        "label": "Smoke — BBB H.264, one 90 s row",
        "clips": {"bbb_h264_smoke": "bbb_h264_6min.mp4"},
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 15,
                  "startup_skip_s": 10, "window_s": 90, "gap_s": 5},
    },
    "bbb_h264_rt": {
        "label": "BBB H.264 — realtime 150 s (July replication row)",
        "clips": {"bbb_h264_rt": "bbb_h264_6min.mp4"},
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 15,
                  "startup_skip_s": 8, "window_s": 150, "gap_s": 10},
    },
    "bbb_codecs_rt": {
        "label": "BBB codec panel — H.264 / HEVC / AV1, realtime 150 s each",
        "clips": {"bbb_h264_rt": "bbb_h264_6min.mp4",
                  "bbb_hevc_rt": "bbb_h265_6min.mp4",
                  "bbb_av1_rt": "bbb_av1_6min.mp4"},
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 15,
                  "startup_skip_s": 8, "window_s": 150, "gap_s": 10},
    },
}

# Screen-mode marker head (2026-07-30, Ben's design): 5 s black · 5 s white ·
# 5 s black prepended to the CONTENT clip as one contiguous video (content
# stream-copied — re-encoding would change the decode workload; markers are
# codec/res/fps-matched NVENC segments). At 1 s cadence each segment carries
# ~5 samples; raw per-second samples are persisted, so the panel response
# segments out post-hoc by edge detection — the hackathon energy-signature
# technique, one row instead of the old 2×90 s bracket.
MARKER_HEAD_S = 15
_MARKER_PATTERN = "black5-white5-black5"


def template_phases(tpl: dict) -> list:
    b = tpl["bench"]
    return [("settle", b["settle_s"]),
            ("baseline", round(b["baseline_samples"] * b["cadence_s"])),
            ("starting", b["startup_skip_s"]),
            ("sampling", b["window_s"]),
            ("finishing", 5)]


_PHASE_PATTERNS = [
    (re.compile(r": settle "), "settle"),
    (re.compile(r": baseline "), "baseline"),
    (re.compile(r": started — sampling|: started - sampling"), "sampling"),
    (re.compile(r": base=.*task=.*dW="), "finishing"),
]
# bench.py's live sample feed (added 2026-07-29): "] sample 4.958W ctx=30.66W"
_SAMPLE_RE = re.compile(r"\] sample ([0-9.]+)W(?: ctx=([0-9.]+)W)?")


# --- Materialisation ---------------------------------------------------------

def _row_for(dev_cfg: dict, name: str, clip: str, mode: str,
             window_s: int | None = None) -> dict:
    row: dict = {"name": name}
    if window_s:
        row["window_s"] = window_s
    if dev_cfg["kind"] == "adb":
        row["url"] = f"{STREAM_BASE_URL}/{clip}"
        return row
    if mode == "screen":
        # Pin scanout to the July display protocol (1080p60) before playback:
        # discovered live 2026-07-30 that both Pis default to 4K on this
        # panel — the Pi 400 (4K30 ceiling) then renders mpv --fs unscaled
        # in a quarter of the screen, and 4K scanout differs from every July
        # display-attached baseline anyway.
        row["cmd"] = (
            f"o=$({_WL_ENV} wlr-randr | awk '/^[[:alnum:]]/{{print $1}}' | head -1); "
            f"{_WL_ENV} wlr-randr --output $o --mode 1920x1080@60; sleep 2; "
            f"{_WL_ENV} mpv --fs --no-audio --loop=inf /dev/shm/decode/{clip}")
        row["stop_cmd"] = "pkill mpv"
    else:
        stem = Path(clip).stem
        row["cmd"] = (f"ffmpeg -nostdin -re -i /dev/shm/decode/{clip} "
                      f"-an -f null - ")
        row["stop_cmd"] = f"pkill -f 'ffmpeg.*{stem}'"
    return row


def _materialize(job_id: str, tpl_key: str, dev_name: str, mode: str,
                 calibrate: bool) -> Path:
    tpl = TEMPLATES[tpl_key]
    dev_cfg = rig.RIG["devices"][dev_name]
    marked = mode == "screen" and calibrate
    runs = []
    for run_name, clip in tpl["clips"].items():
        if marked:
            # Marker-headed variant: window extends over the 15 s head; the
            # skip shrinks so the head lands inside the sampled window.
            runs.append(_row_for(dev_cfg, run_name, f"marked_{clip}", mode,
                                 window_s=tpl["bench"]["window_s"] + MARKER_HEAD_S))
        else:
            runs.append(_row_for(dev_cfg, run_name, clip, mode))
    cfg = dict(tpl["bench"])
    if marked:
        cfg["startup_skip_s"] = 2
    cfg["name"] = f"ui-{tpl_key}-{job_id}-{dev_name}"
    cfg["meter_ip"] = dev_cfg["plug_ip"]
    if mode == "screen":
        cfg["monitor_meter_ip"] = rig.RIG["monitor"]["plug_ip"]
    if dev_cfg["kind"] == "adb":
        cfg["device"] = {"type": "adb", "serial": dev_cfg["target"],
                         "player": "com.brouken.player"}
    else:
        user, host = dev_cfg["target"].split("@", 1)
        cfg["device"] = {"type": "ssh", "host": host, "user": user}
    cfg["runs"] = runs
    path = Path(f"/tmp/owl-decode-{job_id}-{dev_name}.json")
    path.write_text(json.dumps(cfg, indent=1))
    return path


def _needed_clips(tpl_key: str, mode: str, calibrate: bool) -> list:
    clips = list(TEMPLATES[tpl_key]["clips"].values())
    if mode == "screen" and calibrate:
        return [f"marked_{c}" for c in clips]
    return clips


_FFMPEG = "/usr/local/bin/ffmpeg-master"
_NVENC = {"h264": "h264_nvenc", "hevc": "hevc_nvenc", "av1": "av1_nvenc"}


def _ensure_marked_clips_sync(clips: list) -> None:
    """Build `marked_<clip>` (5 s black·white·black head + stream-copied
    content) for any clip missing its marked variant. Marker segments are
    codec/res/fps-matched NVENC encodes, cached in streams/marked_segments/."""
    ff = _FFMPEG if Path(_FFMPEG).exists() else "ffmpeg"
    seg_dir = STREAMS / "marked_segments"
    seg_dir.mkdir(exist_ok=True)
    for clip in clips:
        dst = STREAMS / f"marked_{clip}"
        if dst.exists():
            continue
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,width,height,r_frame_rate,pix_fmt",
             "-of", "csv=p=0", str(STREAMS / clip)],
            capture_output=True, text=True, check=True, timeout=30).stdout.strip()
        codec, w, h, pix, fps = probe.split(",")
        enc = _NVENC.get(codec)
        if enc is None:
            raise RuntimeError(f"no marker encoder for codec {codec!r}")
        seg_paths = []
        for seg, color in (("black", "black"), ("white", "white"),
                           ("black2", "black")):
            seg_p = seg_dir / f"{codec}_{w}x{h}_{fps.split('/')[0]}_{seg}.mp4"
            if not seg_p.exists():
                subprocess.run(
                    [ff, "-loglevel", "error", "-f", "lavfi",
                     "-i", f"color=c={color}:s={w}x{h}:r={fps}", "-t", "5",
                     "-pix_fmt", pix, "-c:v", enc, "-y", str(seg_p)],
                    check=True, timeout=120)
            seg_paths.append(seg_p)
        listing = "".join(f"file '{p}'\n" for p in seg_paths
                          + [STREAMS / clip])
        list_path = Path(f"/tmp/owl-marked-{clip}.txt")
        list_path.write_text(listing)
        try:
            subprocess.run(
                [ff, "-loglevel", "error", "-f", "concat", "-safe", "0",
                 "-i", str(list_path), "-c", "copy", "-y", str(dst)],
                check=True, timeout=600)
        finally:
            list_path.unlink(missing_ok=True)


def _stage_clips_sync(dev_cfg: dict, clips: list) -> None:
    target = dev_cfg["target"]
    subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                    target, "mkdir -p /dev/shm/decode"],
                   check=True, timeout=20)
    for clip in clips:
        subprocess.run(["scp", "-o", "BatchMode=yes",
                        str(STREAMS / clip), f"{target}:/dev/shm/decode/"],
                       check=True, timeout=180)


# --- Orchestration -----------------------------------------------------------

async def _wait_ready(name: str, sub: dict, timeout_s: float) -> None:
    dev = rig.rig_cache["devices"][name]
    if dev["state"] == "off":
        await rig.device_on(name)
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        if dev["state"] == "ready":
            return
        if dev["state"] in ("stuck", "unreachable", "unpowered"):
            raise RuntimeError(f"device is {dev['state']}")
        sub["detail"] = f"device {dev['state']}"
        await asyncio.sleep(3)
    raise RuntimeError(f"not ready after {int(timeout_s)}s")


async def _run_bench_for(job_id: str, tpl_key: str, name: str, mode: str,
                         calibrate: bool, sub: dict) -> dict:
    """Full per-device pipeline: ready → stage → bench.py → rows. Updates
    `sub` (the job's per-device progress dict) as it goes; returns the
    device section of the combined envelope. Raises on failure."""
    dev_cfg = rig.RIG["devices"][name]
    d = rig.rig_cache["devices"][name]
    cfg_path = None
    paused: set = set()
    try:
        sub.update({"stage": "device", "phase_started": time.monotonic()})
        await _wait_ready(name, sub, 3 * dev_cfg["expected_boot_s"] + 45)

        if dev_cfg["kind"] == "ssh":
            sub.update({"stage": "staging",
                        "detail": "copying clips to /dev/shm"})
            await asyncio.to_thread(_stage_clips_sync, dev_cfg,
                                    _needed_clips(tpl_key, mode, calibrate))

        cfg_path = _materialize(job_id, tpl_key, name, mode, calibrate)
        cfg = json.loads(cfg_path.read_text())
        result_path = BENCH_DIR / "results" / f"{cfg['name']}.json"

        d["busy"] = True
        paused = {cfg["meter_ip"]}
        if cfg.get("monitor_meter_ip"):
            paused.add(cfg["monitor_meter_ip"])
        rig.PAUSED_PLUGS |= paused
        sub.update({"stage": "settle", "row": 0,
                    "phase_started": time.monotonic(), "detail": ""})

        proc = await asyncio.create_subprocess_exec(
            "python3", str(BENCH), str(cfg_path), cwd=str(BENCH_DIR),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        lines = []
        row_i = 0
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode(errors="replace").rstrip()
            m = _SAMPLE_RE.search(line)
            if m:
                sub["live_w"] = float(m.group(1))
                if m.group(2):
                    sub["monitor_w"] = float(m.group(2))
                continue
            lines.append(line)
            for pat, phase in _PHASE_PATTERNS:
                if pat.search(line):
                    if phase == "settle":
                        row_i += 1
                    sub.update({"stage": phase, "row": row_i,
                                "phase_started": time.monotonic(),
                                "detail": line.split("] ")[-1][:120]})
                    break
        rc = await proc.wait()
        if rc != 0 or not result_path.exists():
            raise RuntimeError(
                f"bench.py exit {rc}: {' | '.join(lines[-3:])[:300]}")
        bench_out = json.loads(result_path.read_text())
        section = {
            "label": dev_cfg["label"], "kind": dev_cfg["kind"],
            "meter": {"model": "Tapo P110", "ip": cfg["meter_ip"],
                      "fw": "1.3.1", "cadence_s": cfg["cadence_s"]},
            "rows": bench_out.get("rows", []),
        }
        if dev_cfg["kind"] == "adb" and mode == "headless":
            section["display_caveat"] = (
                "Android renders regardless of the shared monitor; headless "
                "here means the screen was not claimed — rows are indicative "
                "vs the Pis' true null-sink decode (July 2026 convention).")
        sub.update({"stage": "done", "detail": ""})
        return section
    except Exception as e:
        sub.update({"stage": "error", "detail": str(e)[:200]})
        raise
    finally:
        d["busy"] = False
        rig.PAUSED_PLUGS -= paused
        if cfg_path:
            cfg_path.unlink(missing_ok=True)


async def run_decode_job(job_id: str, tpl_key: str, devices: list,
                         mode: str, calibrate: bool) -> None:
    tpl = TEMPLATES[tpl_key]
    job = jobs[job_id]
    phases = template_phases(tpl)
    n_rows = len(tpl["clips"])
    job.update({"status": "running", "stage": "running",
                "template": tpl_key, "mode": mode, "calibrate": calibrate,
                "phases": phases, "row_n": n_rows,
                "devices": {name: {"stage": "queued", "row": None,
                                   "detail": "", "phase_started": None}
                            for name in devices}})
    try:
        if mode == "screen" and calibrate:
            job["stage"] = "preparing marker clips"
            await asyncio.to_thread(_ensure_marked_clips_sync,
                                    list(tpl["clips"].values()))
        if mode == "screen":
            # Exclusive: power/ready first, then hand it the monitor.
            name = devices[0]
            await _wait_ready(name, job["devices"][name],
                              3 * rig.RIG["devices"][name]["expected_boot_s"] + 45)
            job["devices"][name]["detail"] = "claiming screen"
            await rig.claim_screen(name)

        outcomes = await asyncio.gather(
            *[_run_bench_for(job_id, tpl_key, name, mode, calibrate,
                             job["devices"][name]) for name in devices],
            return_exceptions=True)

        sections, flat_runs, errors = {}, [], {}
        for name, out in zip(devices, outcomes):
            if isinstance(out, Exception):
                errors[name] = str(out)[:300]
                sections[name] = {"error": errors[name]}
            else:
                sections[name] = out
                for r in out["rows"]:
                    flat_runs.append({**r, "device": name})
        if not flat_runs:
            raise RuntimeError("all devices failed: " + json.dumps(errors))

        envelope = {
            "mode": f"ui_{mode}",
            "template": tpl_key,
            "template_label": tpl["label"],
            "calibrate": bool(mode == "screen" and calibrate),
            "devices": sections,
            "runs": flat_runs,
            "protocol": {"harness": "decode-bench bench.py (July 2026 protocol)",
                         "launched_from": "/decode", "parallel": mode == "headless",
                         **({"marker_head": {"pattern": _MARKER_PATTERN,
                                             "seconds": MARKER_HEAD_S,
                                             "note": "in-window; segment via "
                                                     "raw-sample edge detection"}}
                            if mode == "screen" and calibrate else {}),
                         **{k: tpl["bench"].get(k) for k in
                            ("window_s", "cadence_s", "baseline_samples",
                             "settle_s", "startup_skip_s")}},
        }
        save_result("decode", job_id, envelope)
        status = "done" if not errors else "done"
        job.update({"status": status, "stage": "done", "result": envelope,
                    "partial_errors": errors or None})
    except Exception as e:
        log.warning("decode job %s failed: %s", job_id, e)
        job.update({"status": "error", "stage": "error", "error": str(e)})
