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
import paths
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
_DIAG_DIR  = paths.repo('results', 'diagnostics')
_INPUT_CPU = paths.repo('test_content', 'meridian_4k.mp4')
_INPUT_GPU = paths.repo('test_content', 'meridian_120s.mp4')

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


SETTLED_FROM_S = 60      # distances at/after this are the settled idle floor
TOL_SD_MULT = 3          # tolerance: 3 × the floor's own scatter…
TOL_MIN_PCT = 2.0        # …but never tighter than 2 % of the floor


def recovery_summary(points: list) -> dict | None:
    """Recovery read from the probe's summary points, scaled to the node.

    A fixed "within 1 W" test (the chart's old rule) fits GoS1's 76 W floor and
    says nothing on GoS2's 1.4 W one — there it called a +0.55 W (+40 %) tail
    "recovered" at 5 s. The tolerance here comes from the floor itself:
    max(3 × sd of the settled point means, 2 % of the floor). A workload has
    recovered at the first distance from which every later point stays
    within it. None when the probe has no settled points to define a floor."""
    settled = [p["mean_w"] for p in points if p["distance_s"] >= SETTLED_FROM_S]
    if not settled:
        return None
    floor = statistics.mean(settled)
    sd = statistics.stdev(settled) if len(settled) > 1 else 0.0
    tol = max(TOL_SD_MULT * sd, floor * TOL_MIN_PCT / 100)
    def recovered_at(curve):
        at = None
        for d, w in reversed(curve):
            if abs(w - floor) > tol:
                break
            at = d
        return at

    n = max(p.get("n_runs", 1) for p in points)
    rec, rec_runs = {}, {}
    for wl in sorted({p["workload"] for p in points}):
        pts = sorted((p for p in points if p["workload"] == wl), key=lambda p: p["distance_s"])
        rec[wl] = recovered_at([(p["distance_s"], p["mean_w"]) for p in pts])
        # Each run read against the same floor + band: the spread of these is
        # how sure the pooled recovery time is.
        if n > 1:
            rec_runs[wl] = [recovered_at([(p["distance_s"], p["run_means"][i]) for p in pts
                                          if len(p.get("run_means", [])) > i])
                            for i in range(n)]
    return {"floor_w": round(floor, 3), "floor_sd_w": round(sd, 3),
            "tolerance_w": round(tol, 3), "tolerance_pct": round(100 * tol / floor, 1),
            "settled_from_s": SETTLED_FROM_S, "recovery_s": rec,
            "recovery_runs_s": rec_runs, "encodes_per_point": n}


SERIES_WINDOW_DAYS = 14  # probes this close to the latest one are pooled with it


def read_summary(path) -> list:
    """One probe's summary CSV → [{distance_s, workload, encode_s, n_polls,
    mean_w, std_w, cv_pct, min_w, max_w}]."""
    out = []
    with Path(path).open() as f:
        for row in csv.DictReader(f):
            out.append({"distance_s": int(row["distance_s"]), "workload": row["workload"],
                        "encode_s": float(row["encode_s"]), "n_polls": int(row["n_polls"]),
                        **{k: float(row[k]) for k in ("mean_w", "std_w", "cv_pct", "min_w", "max_w")}})
    return out


def _stamp(path) -> datetime:
    # recovery_YYYYMMDD_HHMMSS_summary.csv
    return datetime.strptime("_".join(Path(path).stem.split("_")[1:3]), "%Y%m%d_%H%M%S")


def probe_series(diag_dir) -> list:
    """[(path, points)] — the latest probe plus every earlier one that repeats
    it: same distances, workloads and poll count, run within
    SERIES_WINDOW_DAYS of it. A re-run from /settings therefore ADDS to the
    curve; a probe from another era (other GPU, other room, other settings)
    never mixes in. Oldest first."""
    shape = lambda pts: (sorted((p["distance_s"], p["workload"]) for p in pts),
                         sorted({p["n_polls"] for p in pts}))

    def complete(pts):
        # Both workloads at every distance, out to the settled zone. A probe
        # still being written (pre-.partial code) or killed mid-sweep isn't.
        keys = {(p["distance_s"], p["workload"]) for p in pts}
        wls = {w for _, w in keys}
        ds = {d for d, _ in keys}
        return (len(wls) == 2 and keys == {(d, w) for d in ds for w in wls}
                and max(ds, default=0) >= SETTLED_FROM_S)

    runs = []
    for f in sorted(Path(diag_dir).glob("recovery_*_summary.csv")):
        try:
            pts = read_summary(f)
            _stamp(f)
        except (ValueError, KeyError, OSError):
            continue
        if complete(pts):
            runs.append((f, pts))
    if not runs:
        return []
    latest, lp = runs[-1]
    series = [(f, pts) for f, pts in runs
              if (_stamp(latest) - _stamp(f)).days < SERIES_WINDOW_DAYS and shape(pts) == shape(lp)]
    return series


def pool(series: list) -> list:
    """Per distance × workload across the runs of a series: mean_w = mean of
    the run means, run_sd_w = their spread (None with one run), n_runs, and
    run_means (each run's own point)."""
    by = {}
    for _, pts in series:
        for p in pts:
            by.setdefault((p["distance_s"], p["workload"]), []).append(p)
    out = []
    for (d, wl), ps in sorted(by.items()):
        means = [p["mean_w"] for p in ps]
        out.append({**ps[-1], "mean_w": round(statistics.mean(means), 3),
                    "run_sd_w": round(statistics.stdev(means), 3) if len(means) > 1 else None,
                    "n_runs": len(means), "run_means": means})
    return out


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
    # Written under a .partial name and renamed only when the sweep completes:
    # a cancelled or killed probe must never become the chart's "latest" run.
    partial_path = summary_path.with_name(summary_path.name + ".partial")
    cancelled = False

    stopped = focus_mode_enter()
    LOCK_FILE.write_text(job_id)
    n_ok = n_fail = 0
    t_start = time.time()
    try:
        with raw_path.open("w", newline="") as raw_f, \
             partial_path.open("w", newline="") as sum_f:
            raw_writer = csv.DictWriter(raw_f, fieldnames=_RAW_FIELDS)
            summary_writer = csv.DictWriter(sum_f, fieldnames=_SUMMARY_FIELDS)
            raw_writer.writeheader()
            summary_writer.writeheader()
            for i, d in enumerate(distances, 1):
                if jobs and jobs.get(job_id, {}).get("cancel_requested"):
                    cancelled = True
                    break
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
    if cancelled:
        partial_path.unlink(missing_ok=True)
        return {"cancelled": True, "pairs_ok": n_ok, "pairs_failed": n_fail,
                "raw_csv": str(raw_path)}
    partial_path.rename(summary_path)

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
