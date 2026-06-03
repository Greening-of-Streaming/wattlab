"""
Pixop partner GPU transcode/upscale — energy measurement wrapper.

Backs the hidden, Lab-only `/enhance-run` page. Pixop's `pixop/live` image is a
thin wrapper around NVEncC (NVIDIA HW encoder); its entrypoint forwards CLI args
straight to `nvencc`. A real enhance run (480p H.264 → 1080p HEVC 10-bit, ×2
super-resolution + HDR passthrough) already works bare-metal on GoS1's RTX 5080.
This module wraps that `docker run` in OWL's existing measurement harness so the
ENERGY cost of the enhancement is a P110-polled ΔWh with a confidence flag, just
like every other workload.

Design decisions (verified ground truth, 2026-06-03):
  - The license is baked INTO the image (`/opt/pixop/license.jwt`, customer gos).
    OWL supplies NO license — do not mount `PIXOP_LICENSE_JWT` or a host file.
  - Container contract: host dirs mount to `/mnt/host/input` + `/mnt/host/output`;
    presets are passed to nvencc via `--option-file <file.args>` (NOT `-p`).
  - OWL owns its workdir under `/srv/data/owl` (gos-owned), so it can create
    input/output/presets itself with no root chown. Jon's `/home/jon/...` is
    permission-locked and must NOT be referenced.

Single-sourcing: baseline / 1 Hz polling / focus mode / cooldown / output probe
are all REUSED from video.py + power.py — never reimplemented here. Cooldown goes
through `power.cooldown_between_runs` (no raw asyncio.sleep), keeping the
cooldown-dispatcher audit clean.
"""
import asyncio
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

import settings as cfg
from confidence import confidence
from power import cooldown_between_runs
from video import (
    measure_baseline, poll_during_task, focus_mode_enter, focus_mode_exit,
    probe_output_stream, _probe_duration, _ffprobe_bin, LOCK_FILE,
)

SCOPE = "Device layer only (GoS1 server). Network, CDN, CPE excluded."
_TAIL = 2000  # chars of stdout/stderr retained on the result


# --- Config -----------------------------------------------------------------

def config() -> dict:
    """Effective pixop config: settings.json overlaid with OWL_PIXOP_* env vars
    (env wins, for ops flexibility without a settings write)."""
    s = cfg.load()
    workdir = os.environ.get("OWL_PIXOP_WORKDIR", s.get("pixop_workdir", "/srv/data/owl/pixop"))
    return {
        "image_tag":     os.environ.get("OWL_PIXOP_IMAGE_TAG", s.get("pixop_image_tag", "pixop/live:2026.06.03")),
        "workdir":       workdir,
        # Pixop license is mounted in at runtime (NOT baked into the image, despite
        # earlier notes) — Jon's run_pixop_nvencc.sh mounts ./license.jwt to
        # /opt/pixop/license.jwt:ro. Default to <workdir>/license.jwt; env overrides.
        "license_path":  os.environ.get("OWL_PIXOP_LICENSE_FILE", str(Path(workdir) / "license.jwt")),
        "presets":       s.get("pixop_presets", []) or [],
        "cooldown_s":    s.get("pixop_cooldown_s", 60),
        "docker_timeout_s": s.get("pixop_docker_timeout_s", 1800),
        "baseline_polls":   s.get("baseline_polls", 10),
    }


def _workdir_paths(c: dict) -> tuple[Path, Path, Path]:
    base = Path(c["workdir"])
    return base / "input", base / "output", base / "presets"


def ensure_workdir(c: Optional[dict] = None) -> None:
    """mkdir -p the three subdirs. OWL owns /srv/data/owl, so no root needed.
    Fails soft — preflight surfaces an unwritable workdir as a reason."""
    c = c or config()
    for p in _workdir_paths(c):
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def list_presets(c: Optional[dict] = None) -> list[str]:
    """Configured preset list, else auto-listed *.args basenames in presets/."""
    c = c or config()
    if c["presets"]:
        return list(c["presets"])
    _, _, pre = _workdir_paths(c)
    try:
        return sorted(p.name for p in pre.glob("*.args"))
    except Exception:
        return []


def describe_preset(preset_name: str, c: Optional[dict] = None) -> str:
    """Human-friendly one-liner derived from the preset's ACTUAL flags (so it
    stays truthful if Jon tweaks a preset). E.g. 'AI restore + upscale to 1080p ·
    SDR→HDR · 20 Mbps'. Empty string on any parse miss (fail-soft)."""
    c = c or config()
    _, _, pre = _workdir_paths(c)
    try:
        args = " ".join(read_preset_args(pre / preset_name))
    except Exception:
        return ""
    if not args:
        return ""
    bits = []
    # Resolution / scaling
    scale = None
    m = re.search(r"--output-res\s+(\S+)", args)
    if m:
        res = m.group(1)
        if "scale=2" in res:
            scale = "×2 super-res"
        else:
            wxh = res.split(",")[0]
            if "x" in wxh and wxh != "0x0":
                scale = f"upscale to {wxh.split('x')[1]}p"
    if scale:
        bits.append(scale)
    # Colour / HDR
    if "sdr_to_hdr=on" in args:
        bits.append("SDR→HDR")
    elif "smpte2084" in args:
        bits.append("HDR passthrough")
    elif "transfer bt709" in args:
        bits.append("stays SDR")
    # Bitrate
    mb = re.search(r"--cbr\s+(\d+)", args)
    if mb:
        bits.append(f"{round(int(mb.group(1)) / 1000)} Mbps")
    return " · ".join(bits)


def list_inputs(c: Optional[dict] = None) -> list[str]:
    """Files staged in input/ (video containers only)."""
    c = c or config()
    inp, _, _ = _workdir_paths(c)
    exts = {".mov", ".mp4", ".mkv", ".m4v", ".y4m", ".webm"}
    try:
        return sorted(p.name for p in inp.iterdir()
                      if p.is_file() and p.suffix.lower() in exts)
    except Exception:
        return []


# --- Preflight --------------------------------------------------------------

def _image_present(c: dict) -> bool:
    try:
        r = subprocess.run(["docker", "image", "inspect", c["image_tag"]],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def preflight(c: Optional[dict] = None) -> dict:
    """What's configured / runnable. Drives the page's graceful state.

    `ok_selftest` needs only the image (the `--check-device` probe). `ok_transcode`
    additionally needs a writable workdir + ≥1 preset + ≥1 input. NO license gate —
    the license is baked into the image.
    """
    c = c or config()
    ensure_workdir(c)
    inp, out, pre = _workdir_paths(c)

    image_present = _image_present(c)
    workdir_ok = (inp.is_dir() and out.is_dir() and pre.is_dir()
                  and os.access(inp, os.R_OK) and os.access(out, os.W_OK))
    license_present = Path(c["license_path"]).exists()
    presets = list_presets(c)
    inputs = list_inputs(c)

    reasons = []
    if not image_present:
        reasons.append(f"docker image '{c['image_tag']}' not found")
    if not workdir_ok:
        reasons.append(f"workdir {c['workdir']} missing input/output/presets (or not writable)")
    if not license_present:
        reasons.append(f"no Pixop license.jwt at {c['license_path']}")
    if not presets:
        reasons.append(f"no *.args preset staged in {pre}")
    if not inputs:
        reasons.append(f"no input clip staged in {inp}")

    return {
        "image_tag": c["image_tag"],
        "image_present": image_present,
        "workdir_ok": workdir_ok,
        "license_present": license_present,
        "presets": presets,
        "inputs": inputs,
        "ok_selftest": image_present,
        "ok_transcode": bool(image_present and workdir_ok and license_present and presets and inputs),
        "reasons": reasons,
    }


# --- Self-test (plumbing only, no measurement, no license needed) -----------

def self_test(c: Optional[dict] = None) -> dict:
    """`docker run --rm --gpus all <tag> --check-device` — proves docker + GPU +
    image without a license and without measuring energy. The baked license is
    `max 1 instance`, so refuse if a measured run holds the lock."""
    c = c or config()
    if LOCK_FILE.exists():
        return {"ok": False, "returncode": None, "image_tag": c["image_tag"],
                "stdout_tail": "", "stderr_tail": "", "duration_s": 0.0,
                "error": "a measurement is in progress — try again when idle"}
    cmd = ["docker", "run", "--rm", "--gpus", "all", c["image_tag"], "--check-device"]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:
        return {"ok": False, "returncode": None, "image_tag": c["image_tag"],
                "stdout_tail": "", "stderr_tail": str(e)[-_TAIL:],
                "duration_s": round(time.time() - t0, 1), "error": str(e)}
    return {
        "ok": r.returncode == 0,
        "returncode": r.returncode,
        "image_tag": c["image_tag"],
        "stdout_tail": (r.stdout or "")[-_TAIL:],
        "stderr_tail": (r.stderr or "")[-_TAIL:],
        "duration_s": round(time.time() - t0, 1),
    }


# --- Docker command + subprocess --------------------------------------------

def _output_name(input_name: str, preset_name: str) -> str:
    return f"{Path(input_name).stem}__{Path(preset_name).stem}.mp4"


def read_preset_args(preset_path) -> list[str]:
    """Parse an nvencc `.args` preset into a token list, mirroring Jon's
    run_pixop_nvencc.sh exactly: strip CR, trim, skip blank + full-line `#`
    comments, drop a trailing ` #...` comment, then whitespace-tokenize. The
    preset is expanded host-side into argv (NOT passed via `--option-file`),
    matching the verified working invocation."""
    args: list[str] = []
    for raw in Path(preset_path).read_text().splitlines():
        line = raw.rstrip("\r").strip()
        if not line or line.startswith("#"):
            continue
        if " #" in line:            # trailing inline comment
            line = line.split(" #", 1)[0].strip()
        if line:
            args.extend(line.split())
    return args


def build_pacer_cmd(input_name: str, c: Optional[dict] = None) -> list[str]:
    """Host-side 1x "faucet" for live mode: ffmpeg -re stream-copies the input's
    compressed packets to stdout at native frame rate. `-c copy` means NO decode,
    so it adds <0.5 W over idle (measured 0.1-0.2 W, below the noise floor) and is
    input-independent — nvencc still does its own decode, identical to batch."""
    c = c or config()
    inp, _, _ = _workdir_paths(c)
    ff = cfg.load().get("ffmpeg_bin", "ffmpeg")
    return [ff, "-re", "-i", str(inp / input_name), "-c", "copy", "-f", "mpegts", "-"]


def build_docker_cmd(input_name: str, preset_name: str, output_name: str,
                     c: Optional[dict] = None, live: bool = False) -> list[str]:
    """The verified container contract (from Jon's run_pixop_nvencc.sh):
      - the license is MOUNTED in at /opt/pixop/license.jwt:ro (not baked, not env),
      - the host workdir is a single mount at /mnt/host (so input/output/presets
        live under /mnt/host/{input,output,presets}),
      - the preset `.args` is expanded host-side into argv (NOT `--option-file`),
      - runtime flags: --network host, --init, --user <uid>:<gid> (outputs owned by
        the OWL service user), + the NVIDIA/UCX/log env. The PIXOP_LIVE_PULSE_*
        telemetry env in Jon's script is NOT required (verified) and is omitted.

    live=True: keep docker stdin open (`-i`) and read a piped mpegts stream
    (`--input-format mpegts -i -`) from the host pacer instead of the input file,
    so the encode runs at 1x realtime (the Pixop Live profile)."""
    c = c or config()
    base = Path(c["workdir"])
    _, _, pre = _workdir_paths(c)
    preset_args = read_preset_args(pre / preset_name)
    cmd = [
        "docker", "run", "--rm", "--gpus", "all", "--network", "host",
        "-v", f"{c['license_path']}:/opt/pixop/license.jwt:ro",
        "-v", f"{base}:/mnt/host",
        "--init",
    ]
    if live:
        cmd.append("-i")          # keep stdin open for the piped TS
    cmd += [
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-e", "NVIDIA_DRIVER_CAPABILITIES=all",
        "-e", "UCX_ERROR_SIGNALS=SIGILL,SIGBUS,SIGFPE",
        "-e", "PIXOP_LOG_MODE=TERMINAL",
        c["image_tag"],
        *preset_args,
    ]
    cmd += (["--input-format", "mpegts", "-i", "-"] if live
            else ["-i", f"/mnt/host/input/{input_name}"])
    cmd += ["-o", f"/mnt/host/output/{output_name}"]
    return cmd


# NVEncC prints a summary line like
#   "encoded 705 frames, 51.91 fps, 18067.47 kbps, 63.27 MB"
# when the encode completes. That fps is the steady-state throughput (excludes
# container/cuDNN cold-start), which is what the realtime/Live verdict uses.
_ENCODE_STATS_RE = re.compile(r"encoded\s+(\d+)\s+frames?,\s*([\d.]+)\s*fps", re.IGNORECASE)


def parse_encode_stats(text: Optional[str]) -> Optional[dict]:
    """Pull {frames, fps} from NVEncC's completion summary, or None."""
    if not text:
        return None
    m = _ENCODE_STATS_RE.search(text)
    if not m:
        return None
    try:
        return {"frames": int(m.group(1)), "fps": round(float(m.group(2)), 2)}
    except ValueError:
        return None


def run_transcode_subprocess(cmd: list[str], timeout_s: int,
                             pacer_cmd: Optional[list[str]] = None) -> dict:
    """Run the docker transcode, capturing returncode + tails + NVEncC's encode
    fps. Batch mode (pacer_cmd=None) runs docker directly. Live mode pipes a
    host-side `ffmpeg -re -c copy` pacer into docker's stdin so the encode runs
    at 1x realtime (the pacer's draw is negligible — see build_pacer_cmd)."""
    t0 = time.time()
    out = err = ""
    rc: Optional[int] = None
    if pacer_cmd is None:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
            out, err, rc = r.stdout or "", r.stderr or "", r.returncode
        except subprocess.TimeoutExpired:
            err, rc = f"timed out after {timeout_s}s", None
    else:
        pacer = subprocess.Popen(pacer_cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL)
        proc = subprocess.Popen(cmd, stdin=pacer.stdout, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        pacer.stdout.close()   # let the pacer get SIGPIPE if docker exits first
        try:
            out, err = proc.communicate(timeout=timeout_s)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            err = (err or "") + f"\ntimed out after {timeout_s}s"
            rc = None
        finally:
            pacer.terminate()
            try:
                pacer.wait(timeout=5)
            except Exception:
                pacer.kill()
    combined = (out or "") + "\n" + (err or "")
    return {
        "success": rc == 0,
        "returncode": rc,
        "duration_s": round(time.time() - t0, 1),
        "docker_cmd": " ".join(cmd),
        "live": pacer_cmd is not None,
        "stdout_tail": (out or "")[-_TAIL:] if rc != 0 else "",
        "stderr_tail": (err or "")[-_TAIL:] if rc != 0 else "",
        "encode_stats": parse_encode_stats(combined),
    }


# --- Realtime / Live feasibility --------------------------------------------

def _probe_input(path) -> tuple[Optional[float], Optional[float]]:
    """(duration_s, source_fps) of an input clip, or (None, None). fps from the
    stream's r_frame_rate; reuses video._probe_duration for the duration."""
    duration = _probe_duration(path)
    fps = None
    try:
        out = subprocess.run(
            [_ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        val = out.stdout.strip()
        if "/" in val:
            num, den = val.split("/", 1)
            fps = round(float(num) / float(den), 3) if float(den) else None
        elif val:
            fps = round(float(val), 3)
    except Exception:
        fps = None
    return duration, fps


def realtime_verdict(rtf: Optional[float]) -> str:
    """Live-feasibility verdict from the steady-state realtime factor."""
    if rtf is None:
        return "unknown"
    if rtf >= 1.15:
        return "live"        # keeps up with realtime + headroom
    if rtf >= 1.0:
        return "marginal"    # realtime, no headroom
    return "file"            # sub-realtime — batch/File only on this hardware


def build_realtime(content_s: Optional[float], source_fps: Optional[float],
                   encode_stats: Optional[dict], encode_wall_s: Optional[float],
                   live: bool = False) -> dict:
    """Realtime block.

    Batch: steady-state RTF (encode_fps / source_fps) is the headline feasibility
    metric (verdict live/marginal/file); wall-clock RTF is the cold-start caveat.

    Live (1x-paced): encode fps is pinned to the source rate, so headroom is
    meaningless — the question is whether the box SUSTAINED 1x (no back-pressure),
    i.e. wall ≈ content duration. verdict = live_sustained | live_behind."""
    fps = (encode_stats or {}).get("fps")
    frames = (encode_stats or {}).get("frames")
    rtf_steady = round(fps / source_fps, 2) if (fps and source_fps) else None
    rtf_wall = round(content_s / encode_wall_s, 2) if (content_s and encode_wall_s) else None
    if live:
        if rtf_wall is None:
            verdict = "unknown"
        else:
            verdict = "live_sustained" if rtf_wall >= 0.9 else "live_behind"
    else:
        primary = rtf_steady if rtf_steady is not None else rtf_wall
        verdict = realtime_verdict(primary)
    return {
        "live": live,
        "content_s": content_s,
        "source_fps": source_fps,
        "encode_fps": fps,
        "frame_count": frames,
        "rtf_steady": rtf_steady,
        "rtf_wall": rtf_wall,
        "verdict": verdict,
    }


# --- Measured run -----------------------------------------------------------

async def run_enhance_measurement(input_name: str, preset_name: str,
                                  job_id: str, jobs: Optional[dict] = None,
                                  live: bool = False) -> dict:
    """Measure the energy of one partner GPU transcode/upscale.

    Mirrors video.run_video_measurement + run_single: focus mode → baseline →
    1 Hz polling around the docker transcode → ΔW/ΔE + confidence → cooldown →
    terminal output probe. Returns a dict shaped like the video single result so
    the page's render helpers + persist's CO2e/gpu_hardware stamping work unchanged.
    """
    c = config()
    pf = preflight(c)
    if not pf["ok_transcode"]:
        raise RuntimeError("partner transcode not configured: " + "; ".join(pf["reasons"]))
    if input_name not in pf["inputs"]:
        raise RuntimeError(f"unknown input: {input_name!r}")
    if preset_name not in pf["presets"]:
        raise RuntimeError(f"unknown preset: {preset_name!r}")

    inp, out, _ = _workdir_paths(c)
    input_path = inp / input_name
    output_name = _output_name(input_name, preset_name)
    output_path = out / output_name
    cmd = build_docker_cmd(input_name, preset_name, output_name, c, live=live)
    pacer_cmd = build_pacer_cmd(input_name, c) if live else None

    if jobs is not None:
        jobs[job_id]["stage"] = "baseline"
    stopped = focus_mode_enter()
    baseline = await measure_baseline(polls=c["baseline_polls"])
    LOCK_FILE.write_text(job_id)
    try:
        if jobs is not None:
            jobs[job_id]["stage"] = "transcoding"
        stop_event = asyncio.Event()
        poll_task = asyncio.create_task(poll_during_task(stop_event))
        t_start = time.time()
        transcode_result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: run_transcode_subprocess(cmd, c["docker_timeout_s"],
                                                   pacer_cmd=pacer_cmd))
        t_end = time.time()
        stop_event.set()
        readings = await poll_task

        if jobs is not None:
            jobs[job_id]["stage"] = "cooldown"
        cd = await cooldown_between_runs(
            fixed_seconds=c["cooldown_s"], reference_w=baseline["w_base"],
            stage="cooldown", jobs=jobs, job_id=job_id,
        )
    finally:
        LOCK_FILE.unlink(missing_ok=True)
        asyncio.get_event_loop().run_in_executor(None, focus_mode_exit, stopped)

    # --- Energy (identical formula to video.run_single) ---
    delta_t = round(t_end - t_start, 1)
    w_base = baseline["w_base"]
    task_samples_w = [round(r["watts"], 2) for r in readings]
    baseline_samples_w = baseline.get("baseline_samples_w")
    w_task = sum(r["watts"] for r in readings) / len(readings) if readings else w_base
    delta_w = round(w_task - w_base, 2)
    delta_e_wh = round(delta_w * (delta_t / 3600), 4)
    conf = confidence(delta_w, len(readings), w_base,
                      baseline_samples_w=baseline_samples_w,
                      task_samples_w=task_samples_w)

    cpu_temps = [r["cpu_tctl"] for r in readings if r.get("cpu_tctl")]
    gpu_temps = [r["gpu_junction"] for r in readings if r.get("gpu_junction")]
    gpu_ppts = [r["gpu_ppt_w"] for r in readings if r.get("gpu_ppt_w")]

    # --- Terminal probe (after lock released — never polled) ---
    if jobs is not None:
        jobs[job_id]["stage"] = "probe"
    out_size_mb = round(output_path.stat().st_size / 1024 / 1024, 2) \
        if output_path.exists() and output_path.stat().st_size > 0 else None
    stream = probe_output_stream(output_path)
    # Realtime / Live feasibility — encode throughput vs the source frame rate.
    # ffprobe of the input runs here (post-measurement), so it never enters energy.
    content_s, source_fps = _probe_input(input_path)
    realtime = build_realtime(content_s, source_fps,
                              transcode_result.get("encode_stats"),
                              transcode_result.get("duration_s"), live=live)
    # NB: no VMAF here. For super-resolution there is no 1080p ground-truth
    # reference — VMAF vs a bicubic-upscaled source would penalise the AI detail
    # the enhancement adds, so it would be a misleading quality number. Energy is
    # the headline; output stream params are the provenance. (Honest-metric call.)

    if jobs is not None:
        jobs[job_id]["stage"] = "done"

    return {
        "mode": "enhance",
        "job_id": job_id,
        "baseline": baseline,
        "cooldown": cd,
        "result": {
            "preset_key": preset_name,
            "preset_label": ("Partner GPU transcode / upscale"
                             + (" · Live (1× paced)" if live else "")),
            "preset_detail": preset_name,
            "live": live,
            "input_name": input_name,
            "output_name": output_name,
            "transcode": transcode_result,
            "output_size_mb": out_size_mb,
            "stream": stream,
            "realtime": realtime,
            "energy": {
                "w_base": round(w_base, 2),
                "w_task": round(w_task, 2),
                "delta_w": round(delta_w, 2),
                "delta_t_s": delta_t,
                "delta_e_wh": delta_e_wh,
                "poll_count": len(readings),
                "baseline_samples_w": baseline_samples_w,
                "task_samples_w": task_samples_w,
                "confidence": conf,
            },
            "thermals": {
                "cpu_base": baseline["cpu_temp_base"],
                "cpu_peak": round(max(cpu_temps), 1) if cpu_temps else None,
                "cpu_mean": round(sum(cpu_temps) / len(cpu_temps), 1) if cpu_temps else None,
                "gpu_base": baseline["gpu_temp_base"],
                "gpu_peak": round(max(gpu_temps), 1) if gpu_temps else None,
                "gpu_mean": round(sum(gpu_temps) / len(gpu_temps), 1) if gpu_temps else None,
                "gpu_ppt_mean_w": round(sum(gpu_ppts) / len(gpu_ppts), 1) if gpu_ppts else None,
                "gpu_ppt_peak_w": round(max(gpu_ppts), 1) if gpu_ppts else None,
            },
        },
        "scope": SCOPE,
    }
