"""
rem_prep.py — "Prepare REM Files" engine (REM↔OWL integration, 2026-06-23 spec).

Produces encoded video files for REM device-playback energy experiments. For a
chosen source it:

  1. Encodes the VIDEO to a constant TARGET QUALITY (VMAF) — bitrate is the free
     variable, quality the held constant. The bitrate search runs on a short
     representative EXCERPT (the bitrate→VMAF curve is content-driven and ~duration-
     invariant for ABR/CBR), seeded from the measured encode-parity curves
     (budget_data), then ONE full encode at the converged bitrate confirms VMAF on
     the deliverable. Energy is measured on the FINAL CLEAN VIDEO ENCODE ONLY.

  2. Assembles the REM playback file by concatenating a fixed timer/marker
     structure with the encoded video, all at the SAME encode params so they bolt
     together with the concat demuxer (-c copy):

        [timer][black][white][black][video][black tail]  ≈ 10 min

     The black/white/black markers let REM delimit the analysis window. Concat
     runs OUTSIDE the measurement window (production, like the VMAF terminal pass),
     so the markers never dilute the codec energy figure.

Design mirrors parity.py / video.py: pure functions + async measured encodes, no
FastAPI imports, monkeypatch-testable (tests patch video.transcode / video.compute_vmaf).
The PRESETS table in video.py is left untouched — build_encode_cmd reuses the
fragments (video._norm_args, gpu.BACKEND.ffmpeg_*) but parameterises height/bitrate
so REM can target arbitrary resolution (incl. 4K) and a per-iteration bitrate.

Software encoders (libx264/libx265/libsvtav1) are the default (reproducible codec-
comparison reference); NVENC is offered for speed. Every segment is pinned to 4:2:0
8-bit + AAC 48 kHz stereo so it is TV-displayable and concat-compatible.

PLANNED (agreed with Simon 2026-06-26):
  * HDR/PQ migration — REM is SDR 8-bit ONLY today (build_encode_cmd pins yuv420p).
    Simon's timer config already supports PQ (HEVC main10, bt2020, master-display/
    max-cll); making the whole REM path HDR-capable (10-bit, bt2020, smpte2084
    transfer + mastering metadata, end-to-end through markers + concat) is the next
    feature. Ship SDR first, then SDR+HDR.
  * Decode/encode energy split — the metered figure is currently a full TRANSCODE
    (decode + scale + encode in one window), not pure encode. Add a null-sink decode
    pass (`ffmpeg -i <src> -f null -`) measured in the same protocol and report
    decode / encode (= transcode - decode) / total; keep Simon's encode-to-raw as an
    occasional cross-check (raw is I/O-bound + huge at 4K). Note the decode/encode
    overlap caveat: in one ffmpeg process they run concurrently, so the subtraction
    is an approximation (the raw method is the clean isolation).

The pluggable timer (generate_timer_segment) is wired to Simon's look via
bin/rem_timer.sh (settings `rem_timer_script_path`): OWL calls it `<out> <w> <h>
<fps> <dur>`, it draws the MM:SS count-down + GoS logo, OWL re-encodes to match.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

import gpu
import power
import settings as cfg
import sources
import video
from confidence import confidence

CPU_ENCODER = {"h264": "libx264", "h265": "libx265", "av1": "libsvtav1"}
CPU_NORM_KEY = {"h264": "cpu", "h265": "h265_cpu", "av1": "av1_cpu"}
CODEC_LABEL = {"h264": "H.264", "h265": "H.265", "av1": "AV1"}
_CODEC_BR_SCALE = {"h264": 1.0, "h265": 0.6, "av1": 0.5}

# Bitrate search guard-rails (kbps). The seed + secant keep us well inside this;
# the clamp just stops a runaway probe on pathological content.
_BPS_FLOOR = 200
_BPS_CEIL = 60000

# Constant audio across every segment so the concat demuxer can -c copy. anullsrc
# is constant silence (the spec: white noise NOT needed, constant audio IS).
_ANULLSRC = "anullsrc=channel_layout=stereo:sample_rate=48000"
_AUDIO_ARGS = ["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2"]

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _round50(kbps: float) -> int:
    return int(round(kbps / 50.0) * 50)


def _clamp_bps(kbps: float) -> int:
    return int(max(_BPS_FLOOR, min(_BPS_CEIL, kbps)))


def _find_font() -> Optional[str]:
    return next((f for f in _FONT_CANDIDATES if Path(f).exists()), None)


def rem_dirs() -> tuple[Path, Path, Path]:
    """(output_dir, upload_dir, work_dir). All on the rem_output_dir disk
    (/srv/data) so multi-GB 4K files never land on /tmp."""
    base = Path(cfg.load().get("rem_output_dir", "/srv/data/owl/rem_out"))
    out = base
    uploads = base / "_uploads"
    work = base / "_work"
    for d in (out, uploads, work):
        d.mkdir(parents=True, exist_ok=True)
    return out, uploads, work


def _probe_props(path: Path) -> dict:
    """{width, height, fps} of a video file's first stream. fps is the raw
    r_frame_rate string (e.g. '60/1', '30000/1001') so lavfi color/timer
    segments match the encoded video's cadence exactly."""
    try:
        out = subprocess.run(
            [video._ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=20,
        )
        s = json.loads(out.stdout).get("streams", [{}])[0]
        return {"width": s.get("width"), "height": s.get("height"),
                "fps": s.get("r_frame_rate") or "30"}
    except Exception:
        return {"width": None, "height": None, "fps": "30"}


def _trim(src: Path, dur: int, work_dir: Path, tag: str) -> Path:
    """Stream-copy the first `dur` seconds of `src` (energy-free, runs outside
    any measurement window). The cut is GOP-approximate, which is fine: the
    search excerpt is encoded-from and scored-against the same clip, and the
    deliverable video is allowed a couple of seconds of slack around 6.5 min."""
    out = work_dir / f"{src.stem}_{tag}.mp4"
    if not out.exists():
        subprocess.run(
            [video._ffmpeg_bin(), "-y", "-i", str(src), "-t", str(dur),
             "-c", "copy", str(out)],
            capture_output=True, text=True, check=True,
        )
    return out


def _excerpt_path(source_key: Optional[str], input_path: Path,
                  excerpt_s: int, work_dir: Path) -> Path:
    """Representative ~2-min clip for the bitrate search. Prefer the curated
    `*_120s` extract sibling of a known source (hand-picked, representative);
    else trim the input."""
    if source_key:
        parent = sources.get_parent_for(source_key)
        if parent:
            for v in parent["variants"]:
                if v["length"] == "extract" and v["path"].exists():
                    return v["path"]
    return _trim(input_path, excerpt_s, work_dir, "excerpt")


# ---------------------------------------------------------------------------
# Encode-command builder — reuses the live /video fragments, parameterised by
# height + bitrate (PRESETS hardcode 1080p + settings bitrate; left untouched).
# Pins 4:2:0 8-bit + constant AAC so output is TV-displayable AND concat-safe.
# ---------------------------------------------------------------------------
def build_encode_cmd(codec: str, device: str, height: int, bps: int,
                     input_path, output_path, *, width: Optional[int] = None) -> list:
    """Real-path encode command list. device ∈ {"cpu","gpu"}. When `width` is
    given the scale is forced to exactly width×height (needed when a segment's
    aspect must match the encoded video's pixel dims — e.g. Simon's timer
    mezzanine); otherwise width is derived from source AR (scale=-2:height)."""
    gop = str(int(cfg.load().get("encode_gop_frames", 120)))
    i, o = str(input_path), str(output_path)
    if device == "cpu":
        vf = f"scale={width}:{height},setsar=1" if width else f"scale=-2:{height}"
        return [
            video._ffmpeg_bin(), "-y", "-i", i,
            "-c:v", CPU_ENCODER[codec], "-b:v", f"{bps}k",
            *video._norm_args(CPU_NORM_KEY[codec]),
            "-vf", vf, "-pix_fmt", "yuv420p",
            *_AUDIO_ARGS, o,
        ]
    b = gpu.BACKEND
    scale = f"scale_cuda={width}:{height}" if width else b.ffmpeg_scale_filter(height)
    return [
        video._ffmpeg_bin(), "-y", *b.ffmpeg_hwaccel_args(), "-i", i,
        "-vf", scale,
        "-c:v", b.ffmpeg_encoder(codec), "-b:v", f"{bps}k",
        *b.ffmpeg_gpu_norm_args(codec, gop),
        *_AUDIO_ARGS, o,
    ]


def _segment_color_cmd(color: str, codec: str, device: str, w: int, h: int,
                       fps: str, bps: int, dur: int, output_path) -> list:
    """Encode a solid-colour (black/white) marker at exactly w×h, matching the
    video's codec/params, with constant silent audio."""
    gop = str(int(cfg.load().get("encode_gop_frames", 120)))
    src = ["-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:r={fps}:d={dur}",
           "-f", "lavfi", "-i", _ANULLSRC]
    if device == "cpu":
        venc = ["-c:v", CPU_ENCODER[codec], "-b:v", f"{bps}k",
                *video._norm_args(CPU_NORM_KEY[codec]), "-pix_fmt", "yuv420p"]
    else:
        b = gpu.BACKEND
        venc = ["-c:v", b.ffmpeg_encoder(codec), "-b:v", f"{bps}k",
                *b.ffmpeg_gpu_norm_args(codec, gop)]
    return [video._ffmpeg_bin(), "-y", *src, *venc, *_AUDIO_ARGS,
            "-t", str(dur), str(output_path)]


def _timer_lavfi(w: int, h: int, fps: str, dur: int) -> str:
    """Placeholder timer filter — black with a centred count-up if a monospace
    font is available, else plain black. Cosmetic only; the black/white/black
    markers are the real REM analysis delimiters. Replaced wholesale when
    Simon's timer script/mezzanine is wired via settings."""
    base = f"color=c=black:s={w}x{h}:r={fps}:d={dur}"
    font = _find_font()
    if font:
        base += (f",drawtext=fontfile={font}:text='%{{pts\\:hms}}':"
                 f"fontcolor=white:fontsize={max(24, h // 12)}:"
                 f"x=(w-text_w)/2:y=(h-text_h)/2")
    return base


def generate_timer_segment(codec: str, device: str, w: int, h: int, fps: str,
                           bps: int, dur: int, out_path: Path, work_dir: Path) -> Path:
    """Pluggable timer: rem_timer_script_path (executable, args:
    out w h fps dur) → else rem_timer_mezzanine_path (normalised to params) →
    else OWL lavfi placeholder. Always re-encoded to the video's params so it
    concatenates cleanly."""
    s = cfg.load()
    script = s.get("rem_timer_script_path") or ""
    mezz = s.get("rem_timer_mezzanine_path") or ""
    gop = str(int(s.get("encode_gop_frames", 120)))
    if script and Path(script).exists() and os.access(script, os.X_OK):
        raw = work_dir / f"{out_path.stem}_raw.mp4"
        subprocess.run([script, str(raw), str(w), str(h), str(fps), str(dur)],
                       capture_output=True, text=True, check=True)
        cmd = build_encode_cmd(codec, device, h, bps, raw, out_path, width=w)
        video.transcode(cmd)
        raw.unlink(missing_ok=True)
        return out_path
    if mezz and Path(mezz).exists():
        trimmed = _trim(Path(mezz), dur, work_dir, f"{out_path.stem}_mezz")
        cmd = build_encode_cmd(codec, device, h, bps, trimmed, out_path, width=w)
        video.transcode(cmd)
        return out_path
    # lavfi placeholder
    if device == "cpu":
        venc = ["-c:v", CPU_ENCODER[codec], "-b:v", f"{bps}k",
                *video._norm_args(CPU_NORM_KEY[codec]), "-pix_fmt", "yuv420p"]
    else:
        b = gpu.BACKEND
        venc = ["-c:v", b.ffmpeg_encoder(codec), "-b:v", f"{bps}k",
                *b.ffmpeg_gpu_norm_args(codec, gop)]
    cmd = [video._ffmpeg_bin(), "-y",
           "-f", "lavfi", "-i", _timer_lavfi(w, h, fps, dur),
           "-f", "lavfi", "-i", _ANULLSRC, *venc, *_AUDIO_ARGS,
           "-t", str(dur), str(out_path)]
    video.transcode(cmd)
    return out_path


# ---------------------------------------------------------------------------
# Bitrate seeding + search math
# ---------------------------------------------------------------------------
def _seed_bitrate(codec: str, height: int, target: float) -> int:
    """Seed the search from the measured encode-parity curves (budget_data), so
    it converges in ~2-4 iterations not 6+. Falls back to a codec-scaled
    settings default (bumped for >1080p) when no artifact covers the recipe."""
    try:
        import budget_data
        p = budget_data.latest_artifact_path()
        if p:
            art = json.loads(Path(p).read_text())
            rows = [r for r in art.get("rows", [])
                    if r.get("codec") == codec and r.get("vmaf") is not None
                    and r.get("rung", "sweep") == "sweep"]
            # Prefer CPU-profile rows (software is the default encoder).
            cpu_rows = [r for r in rows if r.get("encoder_kind") == "cpu"] or rows
            b = budget_data._bitrate_at_vmaf(cpu_rows, target)
            if b:
                seed = b * ((height / 1080.0) ** 1.5 if height and height > 1080 else 1.0)
                return _clamp_bps(_round50(seed))
    except Exception:
        pass
    base = cfg.load().get("h264_bitrate_kbps", 4000) * _CODEC_BR_SCALE.get(codec, 1.0)
    if height and height > 1080:
        base *= (height / 1080.0) ** 1.5
    return _clamp_bps(_round50(base))


def _next_bitrate(samples: list, target: float) -> int:
    """Secant within the bracket around `target`; bump out when target is
    outside the measured range. samples: [(bps, vmaf), ...]."""
    vb = sorted((v, b) for b, v in samples)
    below = [(v, b) for v, b in vb if v < target]
    above = [(v, b) for v, b in vb if v >= target]
    if below and above:
        v0, b0 = below[-1]
        v1, b1 = above[0]
        f = 0.0 if v1 == v0 else (target - v0) / (v1 - v0)
        return _clamp_bps(_round50(b0 + f * (b1 - b0)))
    if not above:                       # everything below target → need more bits
        return _clamp_bps(_round50(max(b for _, b in vb) * 1.6))
    return _clamp_bps(_round50(min(b for _, b in vb) * 0.6))


def _accept(samples: list, target: float, tol: float):
    """Pick the accepted (bps, vmaf). The search STOPS on a symmetric band
    (|vmaf - target| <= tol), so acceptance must honor the same band — otherwise a
    probe that converges a hair UNDER target (e.g. 91.99 vs a 92 target) gets
    discarded and the search falls back to its high seed, overshooting both quality
    and bitrate. Any encode at or above `target - tol` clears quality; among those
    pick the LOWEST bitrate (don't ship more bits than the target needs). Only when
    nothing reaches the band do we fall back to the closest overall."""
    if not samples:
        return None
    in_band = [(b, v) for b, v in samples if v >= target - tol]
    if in_band:
        return min(in_band, key=lambda bv: bv[0])
    return min(samples, key=lambda bv: abs(bv[1] - target))


def _slope(samples: list, target: float):
    """Local VMAF-per-kbps slope from the pair bracketing target, for the
    full-clip corrective step. None if no bracket."""
    vb = sorted((v, b) for b, v in samples)
    below = [(v, b) for v, b in vb if v < target]
    above = [(v, b) for v, b in vb if v >= target]
    if below and above:
        v0, b0 = below[-1]
        v1, b1 = above[0]
        if b1 != b0:
            return (v1 - v0) / (b1 - b0)
    return None


async def encode_to_vmaf(excerpt: Path, work_dir: Path, codec: str, device: str,
                         height: int, target: float, tol: float, max_iters: int,
                         jobs: Optional[dict], job_id: str) -> dict:
    """Un-metered bitrate search on the excerpt. Returns the converged bitrate,
    the per-iteration log, and the local slope for a later full-clip correction."""
    loop = asyncio.get_event_loop()
    samples: list = []
    iterations: list = []
    measured: set = set()
    bps = _seed_bitrate(codec, height, target)
    for it in range(max(1, max_iters)):
        bps = _round50(_clamp_bps(bps))
        if bps in measured:
            break                       # converged / saturated (no new probe)
        measured.add(bps)
        if jobs is not None and job_id in jobs:
            jobs[job_id].update({"stage": "searching", "iter_done": it,
                                 "iter_max": max_iters})
        out = work_dir / f"rem_{job_id}_search_{it}.mp4"
        cmd = build_encode_cmd(codec, device, height, bps, excerpt, out)
        await loop.run_in_executor(None, lambda c=cmd: video.transcode(c))
        v = video.compute_vmaf(out, excerpt)
        out.unlink(missing_ok=True)
        if v is None:                   # can't score → fall back to the seed
            iterations.append({"bps": bps, "vmaf": None})
            break
        samples.append((bps, v))
        iterations.append({"bps": bps, "vmaf": v, "delta": round(v - target, 2)})
        if jobs is not None and job_id in jobs:
            jobs[job_id]["iterations"] = list(iterations)
            jobs[job_id]["iter_done"] = it + 1
        if abs(v - target) <= tol:
            break
        bps = _next_bitrate(samples, target)
    accepted = _accept(samples, target, tol)
    seed = _seed_bitrate(codec, height, target)
    return {
        "bps": accepted[0] if accepted else seed,
        "excerpt_vmaf": accepted[1] if accepted else None,
        "iterations": iterations,
        "slope": _slope(samples, target),
        "converged": bool(accepted and abs(accepted[1] - target) <= tol),
    }


# ---------------------------------------------------------------------------
# Full-clip encode — metered (energy math mirrors video.run_single) or produce-only.
# Keeps the output file (it becomes the video segment in the concat).
# ---------------------------------------------------------------------------
def _rem_vmaf(distorted, reference, height: int = 1080) -> Optional[float]:
    """Terminal VMAF for the REM deliverable — a REPORTING score, so speed it up
    for big 4K clips via temporal subsampling + all cores (keeps it under
    compute_vmaf's 600s timeout). Doubles the subsample above 1080p. Honors the
    global vmaf_enabled toggle. The bitrate SEARCH keeps the precise globals."""
    s = cfg.load()
    sub = int(s.get("rem_vmaf_n_subsample", 5) or 1)
    if height and height > 1080:
        sub *= 2                      # 4K decodes two heavy streams — more headroom
    s2 = {**s, "vmaf_n_subsample": max(1, sub),
          "vmaf_n_threads": int(s.get("rem_vmaf_n_threads", 24))}
    return video.compute_vmaf(distorted, reference, s2)


def _energy_from_readings(readings: list, baseline: dict, delta_t: float) -> dict:
    """Shared ΔW / ΔE / confidence math for one metered window's polls. Used by
    BOTH the encode pass and the decode-only probe so the two figures are
    computed identically and subtract cleanly (encode = transcode − decode)."""
    w_base = baseline["w_base"]
    task_samples_w = [round(r["watts"], 2) for r in readings]
    baseline_samples_w = baseline.get("baseline_samples_w")
    w_task = sum(r["watts"] for r in readings) / len(readings) if readings else w_base
    delta_w = round(w_task - w_base, 2)
    meters = power.meters_summary(baseline, readings, task_samples_w)
    if meters and "delta_w_combined" in meters:
        delta_w = meters["delta_w_combined"]
    delta_e_wh = round(delta_w * (delta_t / 3600), 4)
    conf = confidence(delta_w, len(readings), w_base,
                      baseline_samples_w=baseline_samples_w,
                      task_samples_w=task_samples_w, meters=meters)
    return {
        "w_base": round(w_base, 2), "w_task": round(w_task, 2),
        "delta_w": round(delta_w, 2), "delta_t_s": delta_t,
        "delta_e_wh": delta_e_wh, "poll_count": len(readings),
        "baseline_samples_w": baseline_samples_w, "task_samples_w": task_samples_w,
        "confidence": conf, **({"meters": meters} if meters else {}),
    }


async def _measure_encode(video_clip: Path, out_path: Path, codec: str, device: str,
                          height: int, bps: int, baseline: dict,
                          jobs: Optional[dict], job_id: str,
                          score_vmaf: bool = True) -> dict:
    cmd = build_encode_cmd(codec, device, height, bps, video_clip, out_path)
    duration_s = video._probe_duration(video_clip)
    progress_cb = (video._make_progress_cb(jobs, job_id, duration_s)
                   if jobs is not None else None)
    if jobs is not None:
        video._clear_progress(jobs, job_id)
    stop_event = asyncio.Event()
    t_start = time.time()
    poll_task = asyncio.create_task(video.poll_during_task(stop_event))
    tx = await asyncio.get_event_loop().run_in_executor(
        None, lambda: video.transcode(cmd, progress_cb=progress_cb))
    t_end = time.time()
    stop_event.set()
    readings = await poll_task
    if jobs is not None:
        video._clear_progress(jobs, job_id)

    delta_t = round(t_end - t_start, 1)
    energy = _energy_from_readings(readings, baseline, delta_t)
    cpu_temps = [r["cpu_tctl"] for r in readings if r.get("cpu_tctl")]
    gpu_temps = [r["gpu_junction"] for r in readings if r.get("gpu_junction")]

    # Terminal pass — measurement window is closed (stop_event set, polling done).
    vmaf = _rem_vmaf(out_path, video_clip, height) if score_vmaf else None
    stream = video.probe_output_stream(out_path)
    out_size_mb = (round(out_path.stat().st_size / 1024 / 1024, 2)
                   if out_path.exists() and out_path.stat().st_size > 0 else None)
    return {
        "output_path": out_path, "bps": bps, "vmaf": vmaf, "metered": True,
        "transcode": tx, "stream": stream, "output_size_mb": out_size_mb,
        "energy": energy,
        "thermals": {
            "cpu_base": baseline.get("cpu_temp_base"),
            "cpu_peak": round(max(cpu_temps), 1) if cpu_temps else None,
            "gpu_base": baseline.get("gpu_temp_base"),
            "gpu_peak": round(max(gpu_temps), 1) if gpu_temps else None,
        },
    }


# ---------------------------------------------------------------------------
# Decode-only energy probe — isolates the encoder (Simon 2026-06-26). The metered
# encode above times a full TRANSCODE (decode + scale + encode); subtracting a
# decode-only pass leaves the encoder's share. See the module header for the
# overlap caveat (decode/encode run concurrently in one ffmpeg process, so this
# is an approximation; Simon's encode-to-raw is the clean cross-check).
# ---------------------------------------------------------------------------
def build_decode_cmd(codec: str, device: str, height: int, input_path) -> list:
    """Same front-end as build_encode_cmd but NO encoder/output — frames are
    decoded (and scaled, on CPU) then sunk to `-f null`. CPU mirrors decode+scale
    so the split's 'encode' is the pure encoder; GPU is best-effort hw-decode
    (scale_cuda→null is awkward), so its split lumps scale into 'encode'."""
    i = str(input_path)
    if device == "cpu":
        return [video._ffmpeg_bin(), "-y", "-i", i,
                "-vf", f"scale=-2:{height}", "-an", "-f", "null", "-"]
    b = gpu.BACKEND
    return [video._ffmpeg_bin(), "-y", *b.ffmpeg_hwaccel_args(), "-i", i,
            "-an", "-f", "null", "-"]


async def _measure_decode(video_clip: Path, codec: str, device: str, height: int,
                          baseline: dict, jobs: Optional[dict],
                          job_id: str) -> Optional[dict]:
    """Metered decode-only probe (build_decode_cmd). Returns an energy dict
    shaped like _measure_encode's, or None if the probe fails — fail-soft, a
    missing split must never sink the deliverable."""
    cmd = build_decode_cmd(codec, device, height, video_clip)
    stop_event = asyncio.Event()
    t_start = time.time()
    poll_task = asyncio.create_task(video.poll_during_task(stop_event))
    tx = await asyncio.get_event_loop().run_in_executor(
        None, lambda: video.transcode(cmd))
    t_end = time.time()
    stop_event.set()
    readings = await poll_task
    if not (tx or {}).get("success", False):
        return None
    return _energy_from_readings(readings, baseline, round(t_end - t_start, 1))


async def _produce_encode(video_clip: Path, out_path: Path, codec: str, device: str,
                          height: int, bps: int, jobs: Optional[dict],
                          job_id: str, score_vmaf: bool = True) -> dict:
    cmd = build_encode_cmd(codec, device, height, bps, video_clip, out_path)
    duration_s = video._probe_duration(video_clip)
    progress_cb = (video._make_progress_cb(jobs, job_id, duration_s)
                   if jobs is not None else None)
    tx = await asyncio.get_event_loop().run_in_executor(
        None, lambda: video.transcode(cmd, progress_cb=progress_cb))
    if jobs is not None:
        video._clear_progress(jobs, job_id)
    vmaf = _rem_vmaf(out_path, video_clip, height) if score_vmaf else None
    stream = video.probe_output_stream(out_path)
    out_size_mb = (round(out_path.stat().st_size / 1024 / 1024, 2)
                   if out_path.exists() and out_path.stat().st_size > 0 else None)
    return {"output_path": out_path, "bps": bps, "vmaf": vmaf, "metered": False,
            "transcode": tx, "stream": stream, "output_size_mb": out_size_mb,
            "energy": None, "thermals": None}


def _pick_better(a: dict, b: dict, target: float, tol: float) -> dict:
    """Of two full-clip encodes pick the deliverable. Honor the same symmetric band
    as the search: an encode at or above `target - tol` clears quality, so among
    those prefer the LOWEST bitrate; otherwise prefer the closest to target. The
    loser's output is removed."""
    def score(r):
        v = r.get("vmaf")
        if v is None:
            return (2, 0.0, 9e9)
        if v >= target - tol:
            return (0, float(r.get("bps") or 9e9), 0.0)   # clears quality → fewest bits
        return (1, 0.0, target - v)                       # under-quality → closest to target
    win, lose = (a, b) if score(a) <= score(b) else (b, a)
    try:
        Path(lose["output_path"]).unlink(missing_ok=True)
    except Exception:
        pass
    return win


# ---------------------------------------------------------------------------
# Concat assembly — demuxer (-c copy) with a concat-filter re-encode fallback.
# ---------------------------------------------------------------------------
def assemble_rem_file(segments: list, out_path: Path, codec: str, device: str,
                      bps: int) -> dict:
    """Concat `segments` (in order) into out_path. Tries the demuxer (-c copy,
    fast, byte-preserving) first; on any failure re-encodes via the concat
    filter (slower, always correct). Returns {method, ok}."""
    list_file = Path(str(out_path) + ".concat.txt")
    # concat demuxer needs POSIX-quoted paths, one per line.
    list_file.write_text("".join(f"file '{Path(p).as_posix()}'\n" for p in segments))
    cmd = [video._ffmpeg_bin(), "-y", "-f", "concat", "-safe", "0",
           "-i", str(list_file), "-c", "copy", "-movflags", "+faststart",
           str(out_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0
    if ok:
        list_file.unlink(missing_ok=True)
        return {"method": "copy", "ok": True}

    # Fallback — re-encode through the concat filter.
    gop = str(int(cfg.load().get("encode_gop_frames", 120)))
    inputs: list = []
    for p in segments:
        inputs += ["-i", str(p)]
    n = len(segments)
    fc = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n)) + \
         f"concat=n={n}:v=1:a=1[v][a]"
    if device == "cpu":
        venc = ["-c:v", CPU_ENCODER[codec], "-b:v", f"{bps}k",
                *video._norm_args(CPU_NORM_KEY[codec]), "-pix_fmt", "yuv420p"]
    else:
        b = gpu.BACKEND
        venc = ["-c:v", b.ffmpeg_encoder(codec), "-b:v", f"{bps}k",
                *b.ffmpeg_gpu_norm_args(codec, gop)]
    cmd2 = [video._ffmpeg_bin(), "-y", *inputs, "-filter_complex", fc,
            "-map", "[v]", "-map", "[a]", *venc, *_AUDIO_ARGS,
            "-movflags", "+faststart", str(out_path)]
    r2 = subprocess.run(cmd2, capture_output=True, text=True)
    list_file.unlink(missing_ok=True)
    ok2 = r2.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0
    return {"method": "filter", "ok": ok2,
            "stderr": "" if ok2 else (r2.stderr or "")[-500:]}


# ---------------------------------------------------------------------------
# Share-token registry — the deliverable's download link is intentionally un-gated
# (a remote collaborator with the unguessable token can fetch it without LAN/SSH).
# ---------------------------------------------------------------------------
def _public_base() -> str:
    """Canonical public origin for absolute share links (no trailing slash).
    Server-authoritative on purpose: a link built from the request host would be
    'localhost' when the page is opened through Simon's SSH tunnel."""
    return str(cfg.load().get("public_base_url",
                              "https://wattlab.greeningofstreaming.org")).rstrip("/")


def _token_index_path(out_dir: Path) -> Path:
    return out_dir / "share_tokens.json"


def register_share_token(out_dir: Path, filename: str) -> str:
    """Mint an unguessable token, map it to `filename`, return the token."""
    token = uuid.uuid4().hex
    idx_path = _token_index_path(out_dir)
    try:
        idx = json.loads(idx_path.read_text()) if idx_path.exists() else {}
    except Exception:
        idx = {}
    idx[token] = filename
    idx_path.write_text(json.dumps(idx, indent=2))
    return token


def resolve_share_token(token: str) -> Optional[Path]:
    """Resolve a share token to its file path, or None. Basename-checked."""
    out_dir, _, _ = rem_dirs()
    try:
        idx = json.loads(_token_index_path(out_dir).read_text())
    except Exception:
        return None
    name = idx.get(token)
    if not name or Path(name).name != name:
        return None
    p = out_dir / name
    return p if p.is_file() else None


# ---------------------------------------------------------------------------
# Orchestration — the job coroutine. Writes progress into `jobs`, returns the
# result dict (the route wrapper persists it + marks the job done).
# ---------------------------------------------------------------------------
async def run_rem_prep_job(job_id: str, *, jobs: Optional[dict] = None,
                           source_key: Optional[str] = None,
                           upload_name: Optional[str] = None,
                           codec: str = "h264", device: str = "cpu",
                           height: int = 1080, target_vmaf: Optional[float] = None,
                           fixed_bitrate_kbps: Optional[int] = None,
                           batch_id: Optional[str] = None,
                           score_vmaf: bool = True,
                           metered: bool = True) -> dict:
    s = cfg.load()
    bitrate_mode = fixed_bitrate_kbps is not None
    # VMAF is intrinsic to the search, so it's always scored in VMAF mode; the
    # skip toggle only applies to the reporting score in bitrate mode.
    score_vmaf = score_vmaf or not bitrate_mode
    target = float(target_vmaf if target_vmaf is not None else s.get("rem_target_vmaf", 92))
    tol = float(s.get("rem_vmaf_tolerance", 0.5))
    max_iters = int(s.get("rem_max_iters", 6))
    excerpt_s = int(s.get("rem_search_excerpt_s", 120))
    video_s = int(s.get("rem_video_s", 390))
    timer_s = int(s.get("rem_timer_s", 60))
    marker_s = int(s.get("rem_marker_s", 30))
    tail_s = int(s.get("rem_tail_s", 60))
    out_dir, upload_dir, work_dir = rem_dirs()

    # Resolve the source file.
    if upload_name:
        input_path = upload_dir / Path(upload_name).name
        src_label = upload_name
    elif source_key:
        info = sources.get_source_info(source_key)
        if not info:
            raise ValueError(f"unknown source '{source_key}'")
        input_path = Path(info["path"])
        src_label = info["label"]
    else:
        raise ValueError("no source selected")
    if not input_path.exists():
        raise FileNotFoundError(f"source file missing: {input_path}")

    video_clip = _trim(input_path, video_s, work_dir, f"{job_id}_video")

    def _set(**kw):
        if jobs is not None and job_id in jobs:
            jobs[job_id].update(kw)

    loop = asyncio.get_event_loop()
    stopped = video.focus_mode_enter()
    video.LOCK_FILE.write_text(job_id)
    try:
        if bitrate_mode:
            # Direct encode at the requested bitrate — no search, no excerpt.
            # slope=None makes the corrective full pass below self-skip.
            accepted_bps = _clamp_bps(int(fixed_bitrate_kbps))
            search = {"bps": accepted_bps, "excerpt_vmaf": None, "iterations": [],
                      "slope": None, "converged": True, "skipped": True}
        else:
            _set(stage="seeding", iter_done=0, iter_max=max_iters, iterations=[])
            excerpt = _excerpt_path(source_key, input_path, excerpt_s, work_dir)
            search = await encode_to_vmaf(excerpt, work_dir, codec, device, height,
                                          target, tol, max_iters, jobs, job_id)
            accepted_bps = int(search["bps"])
        video_seg = work_dir / f"rem_{job_id}_seg_video.mp4"
        _set(stage="encoding")
        if metered:
            base = await video.measure_baseline(polls=int(s.get("baseline_polls", 10)))
            enc = await _measure_encode(video_clip, video_seg, codec, device,
                                        height, accepted_bps, base, jobs, job_id,
                                        score_vmaf=score_vmaf)
            # One corrective full pass if the full-clip VMAF drifts off target.
            if (enc["vmaf"] is not None and abs(enc["vmaf"] - target) > tol
                    and search.get("slope")):
                corr = _clamp_bps(_round50(
                    accepted_bps + (target - enc["vmaf"]) / search["slope"]))
                if abs(corr - accepted_bps) >= 50:
                    _set(stage="encoding_correction")
                    base2 = await video.measure_baseline(
                        polls=int(s.get("baseline_polls", 10)))
                    video_seg2 = work_dir / f"rem_{job_id}_seg_video2.mp4"
                    enc2 = await _measure_encode(video_clip, video_seg2, codec, device,
                                                 height, corr, base2, jobs, job_id)
                    enc = _pick_better(enc, enc2, target, tol)
            video_result = enc
            # Decode-only probe (same focus window) → isolate encode energy.
            if s.get("rem_measure_decode_split", True):
                _set(stage="measuring_decode")
                dec_base = await video.measure_baseline(
                    polls=int(s.get("baseline_polls", 10)))
                video_result["decode_energy"] = await _measure_decode(
                    video_clip, codec, device, height, dec_base, jobs, job_id)
        else:
            video_result = await _produce_encode(video_clip, video_seg, codec, device,
                                                  height, accepted_bps, jobs, job_id,
                                                  score_vmaf=score_vmaf)
        accepted_bps = int(video_result["bps"])
    finally:
        video.LOCK_FILE.unlink(missing_ok=True)
        loop.run_in_executor(None, video.focus_mode_exit, stopped)

    if not (video_result.get("transcode") or {}).get("success", True):
        raise RuntimeError("video encode failed: "
                           + ((video_result.get("transcode") or {}).get("stderr") or ""))

    # --- Assembly (production; outside the measurement window) ---------------
    _set(stage="assembling")
    video_seg = Path(video_result["output_path"])
    props = _probe_props(video_seg)
    w, h = props["width"], props["height"]
    fps = props["fps"]
    if not w or not h:
        raise RuntimeError("could not probe encoded video dimensions for assembly")

    black = work_dir / f"rem_{job_id}_black.mp4"
    white = work_dir / f"rem_{job_id}_white.mp4"
    tail = work_dir / f"rem_{job_id}_tail.mp4"
    timer = work_dir / f"rem_{job_id}_timer.mp4"
    video.transcode(_segment_color_cmd("black", codec, device, w, h, fps,
                                       accepted_bps, marker_s, black))
    video.transcode(_segment_color_cmd("white", codec, device, w, h, fps,
                                       accepted_bps, marker_s, white))
    video.transcode(_segment_color_cmd("black", codec, device, w, h, fps,
                                       accepted_bps, tail_s, tail))
    generate_timer_segment(codec, device, w, h, fps, accepted_bps, timer_s,
                           timer, work_dir)

    final = out_dir / f"rem_{job_id}_{codec}_{height}p.mp4"
    segments = [timer, black, white, black, video_seg, tail]
    asm = assemble_rem_file(segments, final, codec, device, accepted_bps)
    if not asm["ok"]:
        raise RuntimeError(f"concat assembly failed ({asm.get('method')}): "
                           + asm.get("stderr", ""))

    final_stream = video.probe_output_stream(final)
    pix_fmt = (final_stream or {}).get("pix_fmt")
    pix_ok = pix_fmt == "yuv420p"
    final_size_mb = (round(final.stat().st_size / 1024 / 1024, 2)
                     if final.exists() else None)
    token = register_share_token(out_dir, final.name)

    # Clean up intermediate segments + trims (keep the final deliverable).
    for p in (black, white, tail, timer, video_seg):
        try:
            Path(p).unlink(missing_ok=True)
        except Exception:
            pass
    _set(stage="done")

    # Decode/encode energy split (Simon 2026-06-26): encode = transcode − decode.
    transcode_energy = video_result.get("energy")
    decode_energy = video_result.get("decode_energy")
    energy_split = None
    if transcode_energy and decode_energy:
        t_wh = transcode_energy.get("delta_e_wh") or 0.0
        d_wh = decode_energy.get("delta_e_wh") or 0.0
        energy_split = {
            "method": "transcode_minus_decode",
            "transcode_wh": t_wh,
            "decode_wh": d_wh,
            "encode_wh": round(max(0.0, t_wh - d_wh), 4),
            "decode": decode_energy,
            "note": "encode = full transcode − decode-only probe. Decode and encode "
                    "overlap in one ffmpeg process, so this is an approximation "
                    "(encode-to-raw is the clean isolation). On GPU the probe is "
                    "hw-decode only, so scale is counted under encode.",
        }

    return {
        "mode": "rem_prep",
        "job_id": job_id,
        "batch_id": batch_id,
        "source": {"key": source_key, "upload": upload_name, "label": src_label},
        "codec": codec, "codec_label": CODEC_LABEL.get(codec, codec.upper()),
        "device": device, "height": height,
        "target_mode": "bitrate" if bitrate_mode else "vmaf",
        "target_vmaf": None if bitrate_mode else target,
        "target_bitrate_kbps": accepted_bps if bitrate_mode else None,
        "tolerance": tol,
        "metered": metered,
        "achieved_vmaf": video_result.get("vmaf"),
        "achieved_bitrate_kbps": accepted_bps,
        "converged": bool(search.get("converged")),
        "search": {"iterations": search.get("iterations"),
                   "excerpt_vmaf": search.get("excerpt_vmaf"),
                   "skipped": bool(search.get("skipped")),
                   "seeded_from": None if bitrate_mode
                                  else ("parity" if search.get("iterations") else None)},
        "energy": video_result.get("energy"),
        "energy_split": energy_split,
        "thermals": video_result.get("thermals"),
        "video_stream": video_result.get("stream"),
        "video_encode": {"transcode": video_result.get("transcode"),
                         "output_size_mb": video_result.get("output_size_mb")},
        "segment_layout_s": {"timer": timer_s, "marker": marker_s,
                             "video": video_s, "tail": tail_s,
                             "total": timer_s + 3 * marker_s + video_s + tail_s},
        "output": {
            "filename": final.name,
            "size_mb": final_size_mb,
            "stream": final_stream,
            "pix_fmt_ok": pix_ok,
            "concat_method": asm.get("method"),
            "download_url": f"/prepare-rem/output/{final.name}",
            "share_token": token,
            # Absolute + public so a link copied from the SSH tunnel still works.
            "share_url": f"{_public_base()}/rem-file/{token}",
        },
        "scope": "Device layer only (GoS1 server). Production/encode energy of the "
                 "video segment only; markers/timer assembled outside the measurement "
                 "window. Network, CDN, CPE excluded.",
    }
