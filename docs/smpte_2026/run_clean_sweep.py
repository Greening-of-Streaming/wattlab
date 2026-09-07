#!/usr/bin/env python3
"""
run_clean_sweep.py — SMPTE-paper-only "clean protocol" re-run of the full
encode-parity sweep (Meridian, Big Buck Bunny, ReadySetGo), fixing the three
measurement-integrity gaps found while writing Section 3.5:

  1. WAIT-FOR-IDLE IS REAL, NOT A FIXED SLEEP.
     parity.py's own run_campaign() does `await asyncio.sleep(campaign.cooldown_s)`
     between rows — a flat 10s sleep, never checked against actual power. This
     script instead calls power.cooldown_between_runs() — the SAME active-probe
     dispatcher OWL's live /video "all codecs" page already uses (video.py's
     run_all_measurement) — with each row's own measured w_base as the next
     row's reference floor. That function is read ONLY, never modified: this
     script literally reuses OWL's existing mechanism, just from its own loop
     instead of parity.py's.

  2. THE CONTAMINATION FLAG PARITY.PY ALREADY COMPUTES BUT THROWS AWAY IS KEPT.
     video.measure_baseline() already returns `baseline_elevated` (CR-070: is
     this baseline above the rolling idle floor + tolerance?) and
     `baseline_reference_w`. parity._measure_recipe() drops both when it builds
     its row dict. This script's measure_recipe_clean() keeps them, so a row
     measured on top of residual heat is flagged in the artifact instead of
     silently accepted.

  3. OS PAGE-CACHE WARM-START BIAS IS NEUTRALISED, NOT IGNORED.
     Campaign.recipes() iterates clip -> codec -> bitrate -> profile -> rep, so
     every row for one clip runs consecutively (60-84 rows) before the next
     clip starts. After the first read, that clip's bytes sit in the page
     cache (GoS1 has 61GB RAM) for the rest of the block — every row EXCEPT
     the first for that clip gets a warm-cache advantage the first one didn't.
     Fix: evict the clip from cache (posix_fadvise DONTNEED — no root needed,
     touches only this file's pages, not the whole system) immediately before
     every row's first read. Every row now starts cold identically; within a
     row the repeat-to-fill-the-20s-window passes are naturally warm after
     the first, same as before, on every row equally. Run order stays
     deterministic (unchanged) — the eviction fixes the actual asymmetry
     directly, so reordering isn't needed on top of it.

SELF-CONTAINED BY DESIGN, SAME GUARANTEE AS docs/smpte_2026/run_sport_clip_sweep.py:
does NOT edit wattlab_service/parity.py, video.py, power.py, gpu.py, or
settings.json. It imports them read-only for Campaign/build_cmd/measurement
primitives and the live cooldown_wait_for_idle tunables (read, never written).
It never calls parity.run_campaign() (that's the flat-sleep loop this script
exists to replace) — it drives its own loop instead. Writes only to
results/calibration/_staging/ (never results/calibration/ directly — that
glob is what /video/budget reads its "latest" artifact from; S70/S71 both hit
that footgun, this script avoids it from the start). Nothing here is on any
serving path; a visitor hitting /video or /video/budget during this run sees
no difference at all.

n=3 PER POINT (Tania, 2026-09-06) — three independent replicates of every
recipe, meeting the WattLab call's n=3 primary-data bar. The reps are run as
three WHOLE PASSES over the matrix (pass 1 = every row once, then pass 2,
then pass 3), NOT as three back-to-back measurements of the same recipe:
consecutive repeats of one recipe share thermal state and a warm cache, so
they would understate run-to-run spread — exactly the quantity n=3 exists to
measure. A side benefit: an interrupted run always leaves COMPLETE passes.

TASK DEFINITION IS UNCHANGED FROM THE PUBLISHED DATASET (Tania's call,
2026-09-06, after checking what the published rows actually did): a 30 s
excerpt (DURATION_S), encoded back-to-back until the measured window reaches
20 s of wall clock (MIN_TASK_S), energy normalised per minute of content
encoded. That means n_encodes varies with encoder speed exactly as it did in
the canonical set (1-13 there; NVENC fills the window in 5-7 passes where
libx265 needs 1-2), and content_s varies with it. This script changes ONLY
the three integrity gaps above, plus n, plus the content list — so its rows
stay directly comparable to the existing 569.

Scope: same matched ladder as the ReadySetGo sweep (MATCHED_BITRATES below —
the post-ceiling-extension ladder, NOT parity.FULL_BITRATES) x the same 4
ABR-ladder-typical lower rungs, x 3 codecs x 3 profiles (cpu / gpu_baseline /
gpu_tuned for the sweep; cpu / gpu_baseline only for the ladder rungs, same
convention as everywhere else), x FOUR contents (Meridian, BBB, ReadySetGo,
football). Football carries the taller ceiling-extension ladder it needed in
the 2026-09-03 leg (FOOTBALL_BITRATES) — its VMAF targets sit above the
matched ladder's top on h265/av1, and interpolating an iso-quality bitrate
from a ladder that never reaches the target is what produced the empty
`bitrate_kbps_at_target` cells there. 1062 rows total (354 per pass). See
print_recipes() for the exact count and a runtime estimate.

VMAF is scored under v0.6.1 (VMAF_MODEL) — the consolidated dataset's
convention — not the live service's v1 default. That is a scoring-model
choice only: it is a terminal pass after the measurement window has closed,
so it touches no energy number. Everything else reads live settings.

Usage:
  1. python docs/smpte_2026/run_clean_sweep.py --print-only
     (sanity-check the recipe list / row count / time estimate, no encoding)
  2. python docs/smpte_2026/run_clean_sweep.py --dry
     (exercises the full pipeline incl. cache eviction with a synthetic power
     source — see the note in measure_recipe_clean() about why dry mode
     skips the real active-wait branch specifically, not just cooldown)
  3. python docs/smpte_2026/run_clean_sweep.py --run
     (the real metered run, unattended; needs /bench-preflight conditions:
     queue idle, meter exclusive. ~19h at n=3 — too long for one night, so
     run detached, e.g. nohup, same pattern run_sport_clip_sweep.py used to
     survive a dropped SSH session, and resume it on a later evening:)
  4. python docs/smpte_2026/run_clean_sweep.py --run --resume <artifact.json>
     (continues into the SAME artifact, skipping rows already measured and
     re-running any that stored an error; safe to repeat as often as needed)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "wattlab_service"))
import parity          # noqa: E402 — read-only use; nothing here mutates the file on disk
import video            # noqa: E402 — read-only use
import power            # noqa: E402 — read-only use
import energy           # noqa: E402 — read-only use
import quality          # noqa: E402 — read-only use
import settings as cfg  # noqa: E402 — read-only use (reads live tunables, writes nothing)
import queue_control    # noqa: E402
from confidence import confidence  # noqa: E402

# ---------------------------------------------------------------------------
# Content — all three, matched format (3840x2160, 16:9, 60fps nominal; see
# Section 3.2). Paths reused read-only from parity.CLIPS where they already
# exist; ReadySetGo's isn't in parity.CLIPS on disk (run_sport_clip_sweep.py
# injects it in-process only), so it's named directly here, same convention.
# ---------------------------------------------------------------------------
CLIP_KEYS = ["meridian_120s", "bbb_120s", "readysetgo_30s", "football_30s"]
READYSETGO_CLIP = Path("/home/gos/wattlab/test_content/readysetgo_30s_looped.mp4")
# Football: same key and same 35s master the 2026-09-03 sports-tier leg used, so
# rows carry the identical `clip` value and merge without a rename.
# LAB-INTERNAL SOURCE (Panasonic demo via a third-party upload, no citable
# licence): measurements are usable and publishable, the pictures are not.
FOOTBALL_CLIP = Path("/home/gos/wattlab/test_content/football_35s.mp4")

# Exactly the canonical post-ceiling-extension ladder ReadySetGo was already
# swept at (docs/smpte_2026/run_sport_clip_sweep.py) — NOT parity.FULL_BITRATES
# (pre-extension, 5-point). Frozen here standalone so this script has zero
# dependency on parity.py's constants changing under it.
MATCHED_BITRATES = {
    "h264": [3000, 4500, 6000, 8000, 11000, 13000, 15000],
    "h265": [1500, 2500, 3500, 5000, 7000, 8500, 10000],
    "av1":  [1000, 1800, 2800, 4000, 6000, 7500],
}

# Football is the high-spatial-detail tier (SI ~48 vs ReadySetGo's ~38): on the
# matched ladder its h265/av1 VMAF targets fell OFF THE TOP of the sweep, so the
# 2026-09-03 leg needed a ceiling extension afterwards (av1 +9/11/13 Mbps, h265
# +12/14/16). Folded in up front here so every iso-quality target is interior to
# the measured range on the first pass — h264 reached its targets on the matched
# ladder and is unextended.
FOOTBALL_BITRATES = {
    "h264": [3000, 4500, 6000, 8000, 11000, 13000, 15000],
    "h265": [1500, 2500, 3500, 5000, 7000, 8500, 10000, 12000, 14000, 16000],
    "av1":  [1000, 1800, 2800, 4000, 6000, 7500, 9000, 11000, 13000],
}

REPS = 3                   # n=3 per point, run as three whole passes (see header)
VMAF_MODEL = "v0"          # consolidated_encode_dataset convention, not the live v1

DURATION_S = 30            # matches the existing protocol exactly
BASELINE_POLLS = 5         # matches the existing protocol exactly
MIN_TASK_S = 20.0          # matches the existing protocol exactly — NOT part of
                           # what's being fixed here (see chat: that's about
                           # per-row normalization, a separate later step)
HEIGHT = 1080

PAUSE_FLAG = Path("/tmp/owl-paused")
LAB_SESSION_FLAG = Path("/tmp/owl-lab-session")
LOCK_FILE = Path("/tmp/gos-measure.lock")

ARTIFACT_DIR = REPO_ROOT / "results" / "calibration" / "_staging"
OUT_ARTIFACT = ARTIFACT_DIR / f"encode_parity_CLEAN_{datetime.now(timezone.utc).date()}.json"


def campaign() -> "parity.Campaign":
    return parity.Campaign(
        clips=list(CLIP_KEYS),
        codecs=["h264", "h265", "av1"],
        profiles=["cpu", "gpu_baseline", "gpu_tuned"],
        bitrates=MATCHED_BITRATES,          # matched ladder for the three 1080p-target clips
        clip_bitrates={"football_30s": FOOTBALL_BITRATES},  # football needs its ceiling
        duration_s=DURATION_S,
        baseline_polls=BASELINE_POLLS,
        cooldown_s=int(cfg.load().get("video_cooldown_s", 60)),  # fallback only —
                                             # see measure_recipe_clean(): the real
                                             # gap between rows comes from
                                             # power.cooldown_between_runs(), this
                                             # value is only what it falls back to
                                             # if the active wait times out.
        reps=1,                             # ONE pass here; the n=3 replication is the
                                            # outer pass loop in run_clean_campaign(),
                                            # so reps are independent, not back-to-back
        min_task_s=MIN_TASK_S,
        ladder_rungs=list(parity._LADDER_LOWER),  # same 4 ABR rungs as everyone else
    )


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Cache eviction — the new piece parity.py has no equivalent of at all.
# ---------------------------------------------------------------------------
def evict_from_cache(path: Path) -> bool:
    """Evict `path`'s pages from the OS page cache before it's read, so every
    row's first read of its clip starts cold and identically — not warmed by
    whatever ran immediately before it in the same clip's block of rows.

    posix_fadvise(DONTNEED) only needs an open file descriptor on the target
    file — no root, no /proc/sys/vm/drop_caches, no effect on any other
    process's cached data. Fails soft (returns False) on any error; a failed
    eviction is a data-quality note for that row, never a reason to abort the
    campaign — matches this codebase's own "fail loudly on real breakage,
    fail soft on nice-to-have provenance" convention (see video.probe_output_
    stream's docstring for the same principle applied to stream provenance)."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return False
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        return True
    except (OSError, AttributeError):
        # AttributeError: posix_fadvise doesn't exist on this platform (non-
        # Linux). OSError: some filesystems / mounts don't support it.
        return False
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Single-recipe measurement — parity._measure_recipe's math, unchanged, plus
# the cache eviction above and full baseline-dict passthrough (parity.py's
# version keeps only w_base and drops baseline_elevated/baseline_reference_w).
# The real wait-for-idle call lives in the OUTER loop (run_clean_campaign),
# not here — same split as video.py's run_all_measurement (cooldown before
# measure_baseline, not inside a single "measure one thing" helper).
# ---------------------------------------------------------------------------
async def measure_recipe_clean(ref: Path, job_id: str, codec: str, profile: str,
                               bps: int, clip_dur_s: float, height: int,
                               dry: bool) -> dict:
    cmd_str = parity.build_cmd(codec, profile, bps, height)
    out_path = video.UPLOAD_DIR / f"{job_id}_out.mp4"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd_list = video.apply_custom_cmd(cmd_str, ref, out_path)
    loop = asyncio.get_event_loop()

    cache_evicted = False if dry else evict_from_cache(ref)

    baseline = await video.measure_baseline(polls=BASELINE_POLLS)

    stop_event = asyncio.Event()
    poll_task = asyncio.create_task(video.poll_during_task(stop_event))
    t0 = time.time()
    n_enc = 0
    last_tx = None
    while True:
        last_tx = await loop.run_in_executor(None, lambda: video.transcode(cmd_list))
        n_enc += 1
        if time.time() - t0 >= MIN_TASK_S:
            break
    t1 = time.time()
    stop_event.set()
    readings = await poll_task

    delta_t = round(t1 - t0, 1)
    w_base = baseline["w_base"]
    task_samples_w = [round(r["watts"], 2) for r in readings]
    baseline_samples_w = baseline.get("baseline_samples_w")
    w_task = sum(r["watts"] for r in readings) / len(readings) if readings else w_base
    delta_w = round(w_task - w_base, 2)
    meters = power.meters_summary(baseline, readings, task_samples_w)
    if meters and "delta_w_combined" in meters:
        delta_w = meters["delta_w_combined"]
    delta_e_wh = energy.energy_wh(delta_w, delta_t)
    conf = confidence(delta_w, len(readings), w_base,
                      baseline_samples_w=baseline_samples_w,
                      task_samples_w=task_samples_w, meters=meters)

    content_s = clip_dur_s * n_enc
    wh_per_min = round(delta_e_wh / (content_s / 60), 4) if content_s else None
    attr_wh = energy.energy_wh(w_base + delta_w, delta_t)
    wh_per_min_attr = round(attr_wh / (content_s / 60), 4) if content_s else None
    out_size_mb = round(out_path.stat().st_size / 1024 / 1024, 2) \
        if out_path.exists() and out_path.stat().st_size > 0 else None
    stream = video.probe_output_stream(out_path)
    # Terminal pass — runs AFTER the measurement window has closed, so it cannot
    # touch any energy number. Scored under the consolidated dataset's v0.6.1
    # convention through an in-process settings override (same mechanism as
    # bin/rescore-*-v0.py); settings.json is read, never written, and a
    # concurrent visitor's own job still scores under the live default.
    vmaf_s = {**cfg.load(), "vmaf_model": VMAF_MODEL}
    vmaf = video.compute_vmaf(out_path, ref, s=vmaf_s)
    try:
        out_path.unlink()
    except FileNotFoundError:
        pass

    return {
        "vmaf": vmaf,
        "vmaf_model": quality.vmaf_model_id(vmaf_s) if vmaf is not None else None,
        "ffmpeg_cmd": (last_tx or {}).get("ffmpeg_cmd"),
        "transcode_ok": (last_tx or {}).get("success"),
        "n_encodes": n_enc, "content_s": round(content_s, 1),
        "w_base": round(w_base, 2),
        "delta_w": delta_w, "delta_e_wh_total": delta_e_wh, "delta_t_s": delta_t,
        "wh_per_min_video": wh_per_min,
        "wh_per_min_video_attributional": wh_per_min_attr,
        "poll_count": len(readings),
        "achieved_bitrate_bps": (stream or {}).get("bit_rate_bps"),
        "output_size_mb": out_size_mb,
        "confidence_flag": (conf or {}).get("flag"),
        "confidence": conf, "stream": stream or {},
        # --- new vs. parity._measure_recipe: kept, not dropped ---
        "cache_evicted": cache_evicted,
        "baseline_elevated": baseline.get("baseline_elevated"),
        "baseline_reference_w": baseline.get("baseline_reference_w"),
    }


# ---------------------------------------------------------------------------
# The campaign loop — parity.run_campaign()'s structure (checkpoint after
# every row so an overnight crash leaves a valid partial artifact), but with
# a real cooldown call in place of the flat sleep.
# ---------------------------------------------------------------------------
def partition_prior_rows(prior_rows: list, redo_flagged: bool = False) -> tuple:
    """Split a resumed artifact's rows into (keep, redo).

    Always redo a row that stored an `error` — it holds no measurement. With
    `redo_flagged`, also redo a row whose baseline tripped CR-070's
    `baseline_elevated`: it IS a measurement, but one taken on top of residual
    heat, and the 2026-09-06 two-pass run showed those rows are exactly the ones
    that fail to reproduce (median pass-to-pass spread 24% vs 1.8% for clean
    rows, 8 of 10 reading low, as an inflated w_base predicts).

    Redone rows are not discarded — run_clean_campaign moves them to the
    artifact's `superseded_rows`, so the evidence behind that comparison
    survives the re-measurement."""
    keep, redo = [], []
    for row in prior_rows:
        if row.get("error"):
            redo.append((row, "error"))
        elif redo_flagged and row.get("baseline_elevated") is True:
            redo.append((row, "baseline_elevated"))
        else:
            keep.append(row)
    return keep, redo


def _recipe_key(rc: dict) -> tuple:
    """Identity of one measured point, used to skip what a resumed run already has."""
    return (rc["clip"], rc["codec"], rc["profile"], rc["bps"], rc["height"],
            rc["kind"], rc["rep"])


def _row_key(row: dict) -> tuple:
    """The same identity, read back off a stored row."""
    return (row["clip"], row["codec"], row["profile"], row["target_bitrate_kbps"],
            row["height"], row["rung"], row["rep"])


def expand_passes(camp: "parity.Campaign", reps: int = REPS) -> list:
    """The full n=`reps` recipe list, ordered as WHOLE PASSES over the matrix.

    camp.recipes() itself yields rep innermost — three consecutive measurements
    of the same recipe, which share thermal state and a warm page cache and so
    understate run-to-run spread. The campaign is therefore built with reps=1
    and repeated here instead, so replicate k of every point is separated from
    replicate k+1 by a full pass over the matrix (~6 h). Also means an
    interrupted run leaves complete passes rather than a ragged matrix."""
    out = []
    for rep_i in range(reps):
        for rc in camp.recipes():          # camp.reps == 1 -> exactly one pass
            out.append({**rc, "rep": rep_i})
    return out


async def run_clean_campaign(camp: "parity.Campaign", clips_map: dict, *,
                             dry: bool = False, log=print,
                             resume: Optional[Path] = None,
                             reps: Optional[int] = None,
                             redo_flagged: bool = False) -> dict:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    # reps: None -> the real n (REPS), or a single pass in --dry, where the point
    # is plumbing rather than statistics. Explicit values are for tests.
    n_reps = reps if reps is not None else (1 if dry else REPS)
    recipes = expand_passes(camp, n_reps)
    total = len(recipes)
    log(f"[clean-sweep] {'DRY ' if dry else ''}campaign: {total} rows "
        f"({len(camp.clips)} clip(s) x {len(camp.codecs)} codec(s), "
        f"duration={camp.duration_s}s, {n_reps} pass(es))")

    started = time.time()
    fp = parity.fingerprint()
    rows = []
    artifact = {
        "schema": "encode-parity-clean/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dry_run": dry, "synthetic_energy": dry, "complete": False,
        "fingerprint": fp,
        "protocol": {
            "clips": camp.clips, "duration_s": camp.duration_s,
            "scale": "1080p (scale=-2:1080)", "audio": "aac 128k",
            "gop_frames": int(cfg.load().get("encode_gop_frames", 120)),
            "baseline_polls": camp.baseline_polls,
            "cooldown_fixed_fallback_s": camp.cooldown_s,
            "cooldown_method": "active (power.cooldown_between_runs, real wait-for-idle "
                                "against each row's own measured w_base — NOT a fixed "
                                "sleep; see run_clean_sweep.py header)",
            "cache_eviction": "posix_fadvise DONTNEED on the source clip before every "
                               "row's first read (see evict_from_cache())",
            "reps": n_reps, "min_task_s": camp.min_task_s,
            "rep_order": "whole passes over the matrix (rep is the OUTER loop), so "
                          "replicates of one point are ~a pass apart, never back-to-back",
            "clip_bitrates": {"football_30s": "ceiling-extended ladder (h265 to 16 Mbps, "
                                               "av1 to 13) — see FOOTBALL_BITRATES"},
            "vmaf_model_setting": VMAF_MODEL,
            "ladder_rungs": camp.ladder_rungs,
            "expected_rows": total, "elapsed_s": 0,
        },
        "rows": rows,
    }
    date = artifact["generated_at"][:10]
    suffix = "_DRY" if dry else ""
    out = ARTIFACT_DIR / f"encode_parity_CLEAN_{parity.fingerprint_slug(fp)}_{date}{suffix}.json"

    # Never silently clobber a previous night's artifact: a fresh --run that
    # lands on the same fingerprint+date as an existing file would overwrite
    # pass 1 rather than continue it. Refuse, and name the fix.
    if resume is None and out.exists() and not dry:
        raise SystemExit(
            f"ABORT: {out} already exists. Continue it with\n"
            f"  --run --resume {out}\n"
            "or move it aside if you really want a fresh artifact.")

    # --- resume ----------------------------------------------------------
    # Continue into the SAME artifact: keep every row already measured, re-run
    # any that stored an error, and leave the original generated_at/fingerprint
    # in place (with this session's appended) so the artifact says honestly that
    # it was collected over more than one sitting.
    done: set = set()
    if resume is not None:
        prior = json.loads(resume.read_text())
        kept, redo = partition_prior_rows(prior.get("rows", []), redo_flagged)
        dropped = len(redo)
        rows.extend(kept)
        done = {_row_key(r) for r in kept}
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        artifact["superseded_rows"] = prior.get("superseded_rows", []) + [
            {**row, "superseded_at": stamp, "superseded_reason": why} for row, why in redo]
        artifact["generated_at"] = prior.get("generated_at", artifact["generated_at"])
        artifact["fingerprint"] = prior.get("fingerprint", fp)
        artifact["resumed"] = prior.get("resumed", []) + [
            {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "fingerprint": fp, "rows_already_present": len(kept)}]
        if prior.get("fingerprint", {}).get("sha") != fp.get("sha"):
            log(f"[clean-sweep] NOTE: resuming under a different code fingerprint "
                f"({prior.get('fingerprint', {}).get('sha')} -> {fp.get('sha')}); "
                "recorded in artifact['resumed'].")
        out = resume
        why = {}
        for _, w in redo:
            why[w] = why.get(w, 0) + 1
        log(f"[clean-sweep] resuming {out.name}: {len(kept)} rows kept"
            + (f", re-running {dropped} ({why}) -> artifact['superseded_rows']" if dropped else "")
            + f", {total - len(done)} to go")

    def checkpoint():
        artifact["protocol"]["elapsed_s"] = round(time.time() - started, 1)
        out.write_text(json.dumps(artifact, indent=2))

    orig_watts = parity._install_synthetic_meter() if dry else None
    stopped = [] if dry else video.focus_mode_enter()
    if not dry:
        video.LOCK_FILE.write_text("clean-sweep campaign\n")

    fallback_s = camp.cooldown_s
    last_floor = None   # reference_w for the NEXT row's cooldown; None = skip (first row)

    try:
        for idx, rc in enumerate(recipes):
            clip_key, codec, profile = rc["clip"], rc["codec"], rc["profile"]
            bps, height, rep, rkind = rc["bps"], rc["height"], rc["rep"], rc["kind"]
            if _recipe_key(rc) in done:
                continue
            ref = parity.ensure_clip(clips_map[clip_key], camp.duration_s)
            clip_dur_s = camp.duration_s or video._probe_duration(ref) or 0
            job_id = f"clean_{idx:03d}_{clip_key}_{codec}_{profile}_{height}p_{bps}_r{rep}"
            log(f"[clean-sweep] {idx + 1}/{total}  pass {rep + 1}  {codec:5s} "
                f"{profile:12s} {height:>4}p {bps:>6}k  {clip_key} [{rkind}]")

            cd = None
            if not dry and last_floor is not None:
                # THE FIX: real wait-for-idle, same dispatcher + same live
                # tunables (cooldown_idle_tolerance_w / _settle_polls /
                # _max_wait_s) OWL's own /video page already uses. Falls
                # back to `fallback_s` internally if it times out, or if
                # cooldown_wait_for_idle is off in settings.json.
                cd = await power.cooldown_between_runs(
                    fixed_seconds=fallback_s, reference_w=last_floor,
                    stage="clean_sweep_cooldown",
                )
            elif dry and idx > 0:
                # Dry mode deliberately does NOT exercise the real active-wait
                # branch: wait_for_thermal_floor() reads power.get_power_watts
                # directly (not video.get_power_watts, the name
                # _install_synthetic_meter() patches), so it would poll the
                # REAL P110 even in a "dry" run. Skipped here rather than
                # silently touching real hardware from a mode whose whole
                # point is not to. The real branch is only exercised in --run.
                await asyncio.sleep(0.1)

            try:
                m = await measure_recipe_clean(ref, job_id, codec, profile, bps,
                                               clip_dur_s, height, dry)
            except Exception as exc:                      # never lose the run to one bad recipe
                log(f"[clean-sweep]      ! recipe failed: {exc!r}")
                m = {"error": repr(exc), "vmaf": None, "w_base": last_floor}
            last_floor = m.get("w_base", last_floor)
            log(f"[clean-sweep]      -> vmaf={m.get('vmaf')} dW={m.get('delta_w')}W "
                f"wh/min={m.get('wh_per_min_video')} n_enc={m.get('n_encodes')} "
                f"cache_evicted={m.get('cache_evicted')} "
                f"baseline_elevated={m.get('baseline_elevated')} "
                f"{m.get('confidence_flag')}")
            rows.append({
                "clip": clip_key, "codec": codec, "profile": profile,
                "encoder_kind": "cpu" if profile == "cpu" else "gpu",
                "target_bitrate_kbps": bps, "height": height, "rung": rkind, "rep": rep,
                "cooldown": cd,
                **m,
            })
            checkpoint()
        artifact["complete"] = True
    finally:
        if not dry:
            try:
                video.LOCK_FILE.unlink()
            except FileNotFoundError:
                pass
            video.focus_mode_exit(stopped)
        if orig_watts is not None:
            video.get_power_watts = orig_watts
        checkpoint()

    log(f"[clean-sweep] wrote {out}  ({len(rows)} rows, complete={artifact['complete']}, "
        f"{artifact['protocol']['elapsed_s']}s)")
    return artifact


def clips_map() -> dict:
    m = {"meridian_120s": parity.CLIPS["meridian_120s"],
         "bbb_120s": parity.CLIPS["bbb_120s"],
         "readysetgo_30s": READYSETGO_CLIP,
         "football_30s": FOOTBALL_CLIP}
    return m


def preflight() -> bool:
    """Refuse to start unless the box is actually idle. Mirrors /bench-preflight
    and run_sport_clip_sweep.py's own check."""
    ok = True
    if LOCK_FILE.exists():
        log(f"ABORT: {LOCK_FILE} already exists (held by: {LOCK_FILE.read_text()!r}) "
            "— something else is mid-measurement.")
        ok = False
    if PAUSE_FLAG.exists():
        log(f"ABORT: {PAUSE_FLAG} already set — a prior pause was never cleared. "
            "Investigate before adding another.")
        ok = False
    for key, path in clips_map().items():
        if not path.exists():
            log(f"ABORT: {key} -> {path} does not exist.")
            ok = False
    try:
        snap = queue_control.snapshot()
        depth = snap.get("queue_depth", snap.get("depth"))
        if depth not in (0, None):
            log(f"ABORT: live queue_depth={depth}, not idle. Wait for it to drain "
                "(or check /queue-status) before starting.")
            ok = False
    except Exception as exc:
        log(f"NOTE: couldn't read live queue state in-process ({exc!r}); "
            "falling back to curl http://127.0.0.1:8000/live check.")
        try:
            out = subprocess.run(["curl", "-s", "http://127.0.0.1:8000/live"],
                                  capture_output=True, text=True, timeout=5)
            data = json.loads(out.stdout)
            if data.get("queue_depth", 0) != 0 or data.get("paused"):
                log(f"ABORT: /live reports queue_depth={data.get('queue_depth')} "
                    f"paused={data.get('paused')} — not idle.")
                ok = False
        except Exception as exc2:
            log(f"ABORT: could not confirm service is idle at all ({exc2!r}).")
            ok = False
    return ok


# Median wall-clock seconds to encode one 30 s excerpt, per path — measured
# across the 426 real rows on disk (canonical 240 + ReadySetGo 84 + football
# 102): delta_t_s / n_encodes. Used ONLY for the planning estimate below.
ENCODE_S_PER_30S = {
    ("h264", "cpu"): 8.6,  ("h264", "gpu_baseline"): 3.7, ("h264", "gpu_tuned"): 7.6,
    ("h265", "cpu"): 17.6, ("h265", "gpu_baseline"): 4.0, ("h265", "gpu_tuned"): 14.3,
    ("av1",  "cpu"): 9.5,  ("av1",  "gpu_baseline"): 3.6, ("av1",  "gpu_tuned"): 8.8,
}
ROW_OVERHEAD_S = 20        # 5-poll baseline + VMAF terminal pass + probe/bookkeeping
ROW_COOLDOWN_S = 20        # budget for the ACTIVE wait-for-idle (the old flat sleep was 10)


def estimate_seconds(recipes: list) -> float:
    """Planning estimate: for each row, how long the >=20 s window actually takes
    given that path's encoder speed, plus fixed per-row overhead."""
    total = 0.0
    for rc in recipes:
        per_enc = ENCODE_S_PER_30S[(rc["codec"], rc["profile"])]
        n_enc = 1
        while per_enc * n_enc < MIN_TASK_S:
            n_enc += 1
        total += per_enc * n_enc + ROW_OVERHEAD_S + ROW_COOLDOWN_S
    return total


def print_recipes(passes: Optional[int] = None) -> None:
    camp = campaign()
    n_passes = passes if passes is not None else REPS
    recipes = expand_passes(camp, n_passes)
    n = len(recipes)
    per_pass = camp.count()
    log(f"=== clean sweep: {n} rows ({n_passes} passes x {per_pass}) across {camp.clips} ===")
    by_kind, by_clip = {}, {}
    for rc in recipes:
        by_kind[rc["kind"]] = by_kind.get(rc["kind"], 0) + 1
        by_clip[rc["clip"]] = by_clip.get(rc["clip"], 0) + 1
    log(f"  breakdown: {by_kind}")
    log(f"  per clip:  {by_clip}   (football carries the ceiling-extended ladder)")
    log(f"  task:      {DURATION_S}s excerpt, encoded back-to-back to a >={MIN_TASK_S:.0f}s "
        f"window, {BASELINE_POLLS}-poll baseline — unchanged from the published dataset")
    log(f"  vmaf:      scored {VMAF_MODEL} (dataset convention), terminal pass, "
        "no effect on any energy number")
    est = estimate_seconds(recipes)
    log(f"\n~{est / 3600:.1f} h total, ~{est / n_passes / 3600:.1f} h per pass "
        f"(~{est / n:.0f}s/row), from the MEASURED per-path encode speeds in "
        "ENCODE_S_PER_30S plus 20s overhead and a 20s active-cooldown budget. "
        "Anchor: the real ReadySetGo run logged 54.7s/row under the old flat-10s "
        "protocol [4596.7s / 84 rows].\nToo long for one night — run it detached "
        "and continue with --resume.")


async def run_real(use_lab_session: bool, dry: bool,
                   resume: Optional[Path] = None,
                   passes: Optional[int] = None,
                   redo_flagged: bool = False) -> int:
    if not dry and not preflight():
        return 2

    if not dry:
        log(f"Setting {PAUSE_FLAG} (backs off the live 5s power poller)")
        PAUSE_FLAG.write_text("docs/smpte_2026/run_clean_sweep.py — clean-protocol re-run\n")
        if use_lab_session:
            log(f"Setting {LAB_SESSION_FLAG} (non-Lab job submission refused, browsing stays open)")
            LAB_SESSION_FLAG.write_text("clean-sweep campaign\n")

    try:
        camp = campaign()
        n_passes = passes if passes is not None else (1 if dry else REPS)
        n_rows = len(expand_passes(camp, n_passes))
        est = estimate_seconds(expand_passes(camp, n_passes))
        log(f"\n--- clean sweep ({n_rows} rows, {n_passes} pass(es), ~{est / 3600:.1f} h"
            + (f", resuming {resume.name}" if resume else "") + ") ---")
        await run_clean_campaign(camp, clips_map(), dry=dry, log=log, resume=resume,
                                 reps=n_passes, redo_flagged=redo_flagged)
        log(f"\nDONE. Artifact written under {ARTIFACT_DIR}/ "
            "(never results/calibration/ directly — see header note on the "
            "S70/S71 /video/budget-glob footgun).")
        log("This is a SEPARATE file from the existing canonical dataset — folding it "
            "in (or replacing the old rows) is a deliberate, reviewed follow-up step.")
        return 0
    finally:
        if not dry:
            log("\nRestoring normal state...")
            PAUSE_FLAG.unlink(missing_ok=True)
            # Only lower the lab-session flag if THIS script raised it. Under
            # --skip-lab-session the flag belongs to someone else — since CR-083
            # usually a /queue-status reservation, whose ticker owns what it
            # raised; deleting it there reads as a hand-end and closes that
            # person's slot early (their reservation is then finished, never
            # re-raised). Same reasoning as lab_reservations.tick()'s ownership rule.
            if use_lab_session:
                LAB_SESSION_FLAG.unlink(missing_ok=True)
            LOCK_FILE.unlink(missing_ok=True)  # belt-and-braces; run_clean_campaign does this itself
            log(f"  {PAUSE_FLAG}: {'still present (!)' if PAUSE_FLAG.exists() else 'removed'}")
            log(f"  {LAB_SESSION_FLAG}: "
                + ("not ours, left alone" if not use_lab_session
                   else ('still present (!)' if LAB_SESSION_FLAG.exists() else 'removed')))
            log(f"  {LOCK_FILE}: {'still present (!)' if LOCK_FILE.exists() else 'removed'}")
            log("Queue worker will pick back up on its own now that the pause flag is gone.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--print-only", action="store_true", help="show the recipe list, no encoding")
    p.add_argument("--dry", action="store_true",
                   help="exercise the full pipeline with a synthetic power source "
                        "(no real meter contention; see note re: the active-wait branch)")
    p.add_argument("--run", action="store_true", help="actually run it (metered, real)")
    p.add_argument("--skip-lab-session", action="store_true",
                   help="only set the pause flag, skip the visitor-lockout flag")
    p.add_argument("--passes", type=int, metavar="N",
                   help=f"how many whole passes over the matrix to run (default {REPS} = "
                        "the full n=3). Fewer now, the rest later with --resume: the "
                        "artifact keeps whichever passes it already holds.")
    p.add_argument("--redo-flagged", action="store_true",
                   help="with --resume: also re-measure rows whose baseline tripped "
                        "baseline_elevated (contaminated by residual heat). The originals "
                        "move to the artifact's superseded_rows, they are not deleted.")
    p.add_argument("--resume", metavar="ARTIFACT.json",
                   help="continue a previous run into the SAME artifact: rows already "
                        "measured are skipped, rows that stored an error are re-run")
    args = p.parse_args()

    resume = Path(args.resume).expanduser().resolve() if args.resume else None
    if resume is not None and not resume.exists():
        print(f"ABORT: --resume {resume} does not exist")
        return 2

    if args.redo_flagged and resume is None:
        print("ABORT: --redo-flagged only means anything with --resume")
        return 2
    if args.passes is not None and not (1 <= args.passes <= REPS):
        print(f"ABORT: --passes must be between 1 and {REPS}")
        return 2

    if args.print_only:
        print_recipes(args.passes)
        return 0
    if args.dry:
        return asyncio.run(run_real(not args.skip_lab_session, dry=True, resume=resume,
                                    passes=args.passes, redo_flagged=args.redo_flagged))
    if args.run:
        return asyncio.run(run_real(not args.skip_lab_session, dry=False, resume=resume,
                                    passes=args.passes, redo_flagged=args.redo_flagged))
    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
