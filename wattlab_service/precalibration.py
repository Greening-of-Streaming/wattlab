"""
Thermal-recovery probe as a first-class server job (CR-024).

Promotes the `bin/probe-thermal-recovery` CLI into an importable async engine so
the "▶ Re-run probe" button on /settings can enqueue it through queue_control
like every other measurement, instead of the operator dropping to a shell.

Same measurement contract as video.run_variance_calibration: holds the
measurement lock, enters focus mode, drives jobs[job_id]["stage"], writes the
exact CSVs the CLI wrote (so /precalibration/data reads either identically), and
appends a CR-012 diagnostics history line.

Deliberately does NOT touch /tmp/owl-paused: run through the queue this IS the
sole worker job, so — like the variance calibration — it relies on queue
serialisation rather than pausing itself. The CLI touched the pause flag only
because it ran outside the queue.

Encoder commands come from video.variance_template (CPU + h265_gpu), so the
workload is identical to variance calibration and routes through gpu.BACKEND
(no VAAPI `-t` cap needed post-CR-022 / ffmpeg-master).
"""
import asyncio
import csv
import statistics
import time
from datetime import datetime
from pathlib import Path

import settings as cfg
import persist
from power import get_power_watts
from video import (LOCK_FILE, UPLOAD_DIR, POLL_INTERVAL, apply_custom_cmd,
                   focus_mode_enter, focus_mode_exit, transcode,
                   variance_template)

# Same fixed inputs the CLI used: CPU on the 12-min 4K master, GPU on the 120s
# asset. Module constants for now — CR-031 will lift the hardcoded repo root.
_DIAG_DIR  = Path("/home/gos/wattlab/results/diagnostics")
_INPUT_CPU = Path("/home/gos/wattlab/test_content/meridian_4k.mp4")
_INPUT_GPU = Path("/home/gos/wattlab/test_content/meridian_120s.mp4")

# Dense in 0–15s where the recovery action lives, sparse past 30s.
DEFAULT_DISTANCES = [0, 2, 5, 8, 12, 18, 25, 35, 50, 70, 95, 120]

_RAW_FIELDS = ["ts", "distance_s", "workload", "poll_idx", "watts"]
_SUMMARY_FIELDS = ["distance_s", "workload", "encode_s", "n_polls",
                   "mean_w", "std_w", "cv_pct", "min_w", "max_w",
                   "sample_window_s"]


def parse_distances(raw) -> list:
    """Normalise a settings value (list[int] or a comma string like '0,5,12')
    to a sorted unique list of non-negative ints. Falls back to
    DEFAULT_DISTANCES on empty/garbage so the job never runs zero distances."""
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        try:
            vals = [int(p) for p in parts]
        except ValueError:
            return list(DEFAULT_DISTANCES)
    elif isinstance(raw, (list, tuple)):
        try:
            vals = [int(v) for v in raw]
        except (ValueError, TypeError):
            return list(DEFAULT_DISTANCES)
    else:
        return list(DEFAULT_DISTANCES)
    vals = sorted({v for v in vals if v >= 0})
    return vals or list(DEFAULT_DISTANCES)


def _probe_params(s: dict) -> tuple:
    """(distances, pre_cool_s, n_polls) resolved from settings. n_polls falls
    back to baseline_polls when precal_baseline_polls is null (the CR default)."""
    distances = parse_distances(s.get("precal_distances", DEFAULT_DISTANCES))
    pre_cool_s = int(s.get("precal_pre_cool_s", 30))
    n_polls = int(s.get("precal_baseline_polls") or s.get("baseline_polls", 10))
    return distances, pre_cool_s, n_polls


def estimated_minutes(distances, pre_cool_s, n_polls) -> int:
    """Rough wall-time for the ETA badge (deliberately approximate — labelled
    '≈'). Each distance runs a CPU and a GPU pair; each workload is pre-cool +
    an ~18 s encode + the distance wait + the sample window."""
    per_pair = sum(2 * (pre_cool_s + 18 + d + n_polls) for d in distances)
    return max(1, round(per_pair / 60))


async def _sample_idle(n_polls: int) -> list:
    readings = []
    for _ in range(n_polls):
        readings.append(await get_power_watts())
        await asyncio.sleep(POLL_INTERVAL)
    return readings


async def _measure_one(workload, cmd_tpl, input_video, distance_s, n_polls,
                       pre_cool_s, run_idx, raw_writer, summary_writer,
                       jobs, job_id, stage_prefix) -> bool:
    """Pre-cool, encode, wait `distance_s`, sample `n_polls`; write the raw and
    summary CSV rows. Returns False (and skips the sample) on a failed encode."""
    def _stage(msg):
        if jobs and job_id in jobs:
            jobs[job_id]["stage"] = f"{stage_prefix} · {workload} {msg}"

    _stage(f"pre-cool {pre_cool_s}s")
    await asyncio.sleep(pre_cool_s)

    out_path = UPLOAD_DIR / f"probe_{run_idx}_{workload}.mp4"
    cmd = apply_custom_cmd(cmd_tpl, input_video, out_path)
    _stage("encode")
    t0 = time.time()
    result = await asyncio.get_event_loop().run_in_executor(None, transcode, cmd)
    encode_s = round(time.time() - t0, 1)
    out_path.unlink(missing_ok=True)
    if not result.get("success"):
        _stage("encode FAILED — skipped")
        return False

    _stage(f"wait {distance_s}s · sample {n_polls}p")
    if distance_s > 0:
        await asyncio.sleep(distance_s)

    t_sample_start = time.time()
    readings = await _sample_idle(n_polls)
    t_sample_end = time.time()

    for i, w in enumerate(readings):
        raw_writer.writerow({
            "ts": datetime.fromtimestamp(t_sample_start + i * POLL_INTERVAL)
                          .isoformat(timespec="seconds"),
            "distance_s": distance_s, "workload": workload,
            "poll_idx": i, "watts": round(w, 3),
        })

    mean_w = round(statistics.mean(readings), 3)
    std_w = round(statistics.stdev(readings), 3) if len(readings) > 1 else 0.0
    cv_pct = round(std_w / mean_w * 100, 2) if mean_w else 0.0
    summary_writer.writerow({
        "distance_s": distance_s, "workload": workload, "encode_s": encode_s,
        "n_polls": n_polls, "mean_w": mean_w, "std_w": std_w, "cv_pct": cv_pct,
        "min_w": round(min(readings), 3), "max_w": round(max(readings), 3),
        "sample_window_s": round(t_sample_end - t_sample_start, 1),
    })
    return True


async def run_thermal_recovery_probe(job_id: str, jobs: dict) -> dict:
    """Run the full CPU+GPU recovery sweep across the configured distances.

    Writes results/diagnostics/recovery_<ts>{,_summary}.csv (the shape
    /precalibration/data reads) and appends a diagnostics history line. Raises
    FileNotFoundError if a probe input is missing (surfaced as the job error).
    """
    s = cfg.load()
    distances, pre_cool_s, n_polls = _probe_params(s)
    cpu_tpl = variance_template("cpu", s)
    gpu_tpl = variance_template("h265_gpu", s)

    for label, p in (("CPU", _INPUT_CPU), ("GPU", _INPUT_GPU)):
        if not p.exists():
            raise FileNotFoundError(f"{label} probe input missing at {p}")

    _DIAG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = _DIAG_DIR / f"recovery_{ts}.csv"
    summary_path = _DIAG_DIR / f"recovery_{ts}_summary.csv"

    stopped = focus_mode_enter()
    LOCK_FILE.write_text(job_id)
    n_ok = n_fail = 0
    t_start = time.time()
    try:
        with raw_path.open("w", newline="") as raw_f, \
             summary_path.open("w", newline="") as sum_f:
            raw_writer = csv.DictWriter(raw_f, fieldnames=_RAW_FIELDS)
            summary_writer = csv.DictWriter(sum_f, fieldnames=_SUMMARY_FIELDS)
            raw_writer.writeheader()
            summary_writer.writeheader()
            for i, d in enumerate(distances, 1):
                run_idx = f"{i:02d}_d{d:03d}"
                prefix = f"distance {d}s ({i}/{len(distances)})"
                if jobs and job_id in jobs:
                    jobs[job_id]["stage"] = prefix
                for workload, tpl, inp in (("cpu", cpu_tpl, _INPUT_CPU),
                                           ("gpu", gpu_tpl, _INPUT_GPU)):
                    ok = await _measure_one(
                        workload, tpl, inp, d, n_polls, pre_cool_s, run_idx,
                        raw_writer, summary_writer, jobs, job_id, prefix)
                    n_ok += int(ok)
                    n_fail += int(not ok)
                    raw_f.flush()
                    sum_f.flush()
    finally:
        focus_mode_exit(stopped)
        LOCK_FILE.unlink(missing_ok=True)

    elapsed_min = round((time.time() - t_start) / 60, 1)
    result = {
        "distances": distances, "n_distances": len(distances),
        "pairs_ok": n_ok, "pairs_failed": n_fail,
        "elapsed_min": elapsed_min,
        "summary_csv": str(summary_path), "raw_csv": str(raw_path),
    }
    try:
        persist.append_history_line("diagnostics",
                                    {"kind": "thermal_recovery_probe",
                                     "job_id": job_id, **result})
    except Exception:
        pass  # history is best-effort; a probe that ran must not fail on logging
    return result
