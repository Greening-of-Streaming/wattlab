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

n=1 PER POINT — same design as the existing dataset, deliberately not scoped
up to real repeat replication (n=3+) here. That's a separate, larger, later
decision (see chat), not bundled into this fix.

Scope: same matched ladder as the ReadySetGo sweep (MATCHED_BITRATES below —
the post-ceiling-extension ladder, NOT parity.FULL_BITRATES) x the same 4
ABR-ladder-typical lower rungs, x 3 codecs x 3 profiles (cpu / gpu_baseline /
gpu_tuned for the sweep; cpu / gpu_baseline only for the ladder rungs, same
convention as everywhere else), x all three contents (Meridian, BBB,
ReadySetGo). 252 rows total. See print_recipes() for the exact count and a
runtime estimate.

Usage:
  1. python docs/smpte_2026/run_clean_sweep.py --print-only
     (sanity-check the recipe list / row count / time estimate, no encoding)
  2. python docs/smpte_2026/run_clean_sweep.py --dry
     (exercises the full pipeline incl. cache eviction with a synthetic power
     source — see the note in measure_recipe_clean() about why dry mode
     skips the real active-wait branch specifically, not just cooldown)
  3. python docs/smpte_2026/run_clean_sweep.py --run
     (the real metered run, unattended; needs /bench-preflight conditions:
     queue idle, meter exclusive. ~4.5h — run detached, e.g. nohup, same
     pattern run_sport_clip_sweep.py used to survive a dropped SSH session)
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
CLIP_KEYS = ["meridian_120s", "bbb_120s", "readysetgo_30s"]
READYSETGO_CLIP = Path("/home/gos/wattlab/test_content/readysetgo_30s_looped.mp4")

# Exactly the canonical post-ceiling-extension ladder ReadySetGo was already
# swept at (docs/smpte_2026/run_sport_clip_sweep.py) — NOT parity.FULL_BITRATES
# (pre-extension, 5-point). Frozen here standalone so this script has zero
# dependency on parity.py's constants changing under it.
MATCHED_BITRATES = {
    "h264": [3000, 4500, 6000, 8000, 11000, 13000, 15000],
    "h265": [1500, 2500, 3500, 5000, 7000, 8500, 10000],
    "av1":  [1000, 1800, 2800, 4000, 6000, 7500],
}

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
        bitrates=MATCHED_BITRATES,          # same ladder for all three clips
        duration_s=DURATION_S,
        baseline_polls=BASELINE_POLLS,
        cooldown_s=int(cfg.load().get("video_cooldown_s", 60)),  # fallback only —
                                             # see measure_recipe_clean(): the real
                                             # gap between rows comes from
                                             # power.cooldown_between_runs(), this
                                             # value is only what it falls back to
                                             # if the active wait times out.
        reps=1,                             # n=1 per point, deliberately (see chat)
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
    vmaf = video.compute_vmaf(out_path, ref)          # terminal pass
    try:
        out_path.unlink()
    except FileNotFoundError:
        pass

    return {
        "vmaf": vmaf,
        "vmaf_model": quality.vmaf_model_id() if vmaf is not None else None,
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
async def run_clean_campaign(camp: "parity.Campaign", clips_map: dict, *,
                             dry: bool = False, log=print) -> dict:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    total = camp.count()
    log(f"[clean-sweep] {'DRY ' if dry else ''}campaign: {total} rows "
        f"({len(camp.clips)} clip(s) x {len(camp.codecs)} codec(s), "
        f"duration={camp.duration_s}s)")

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
            "reps": camp.reps, "min_task_s": camp.min_task_s,
            "ladder_rungs": camp.ladder_rungs,
            "expected_rows": total, "elapsed_s": 0,
        },
        "rows": rows,
    }
    date = artifact["generated_at"][:10]
    suffix = "_DRY" if dry else ""
    out = ARTIFACT_DIR / f"encode_parity_CLEAN_{parity.fingerprint_slug(fp)}_{date}{suffix}.json"

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
        for idx, rc in enumerate(camp.recipes()):
            clip_key, codec, profile = rc["clip"], rc["codec"], rc["profile"]
            bps, height, rep, rkind = rc["bps"], rc["height"], rc["rep"], rc["kind"]
            ref = parity.ensure_clip(clips_map[clip_key], camp.duration_s)
            clip_dur_s = camp.duration_s or video._probe_duration(ref) or 0
            job_id = f"clean_{idx:03d}_{clip_key}_{codec}_{profile}_{height}p_{bps}_r{rep}"
            log(f"[clean-sweep] {idx + 1}/{total}  {codec:5s} {profile:12s} {height:>4}p "
                f"{bps:>6}k  {clip_key} [{rkind}]")

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
         "readysetgo_30s": READYSETGO_CLIP}
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


def print_recipes() -> None:
    camp = campaign()
    n = camp.count()
    log(f"=== clean sweep: {n} rows across {camp.clips} ===")
    by_kind = {}
    for rc in camp.recipes():
        by_kind[rc["kind"]] = by_kind.get(rc["kind"], 0) + 1
    log(f"  breakdown: {by_kind}")
    log(f"\n~{round(n * 65 / 3600, 2)} h at ~65s/row planning estimate "
        "(observed ~54.7s/row on the real ReadySetGo run under the OLD flat-"
        "10s-cooldown protocol [4596.7s / 84 rows], +~10s/row for a genuine "
        "settle-verified wait instead of an unverified flat sleep — see chat).")


async def run_real(use_lab_session: bool, dry: bool) -> int:
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
        log(f"\n--- clean sweep ({camp.count()} rows) ---")
        await run_clean_campaign(camp, clips_map(), dry=dry, log=log)
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
            LAB_SESSION_FLAG.unlink(missing_ok=True)
            LOCK_FILE.unlink(missing_ok=True)  # belt-and-braces; run_clean_campaign does this itself
            log(f"  {PAUSE_FLAG}: {'still present (!)' if PAUSE_FLAG.exists() else 'removed'}")
            log(f"  {LAB_SESSION_FLAG}: {'still present (!)' if LAB_SESSION_FLAG.exists() else 'removed'}")
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
    args = p.parse_args()

    if args.print_only:
        print_recipes()
        return 0
    if args.dry:
        return asyncio.run(run_real(not args.skip_lab_session, dry=True))
    if args.run:
        return asyncio.run(run_real(not args.skip_lab_session, dry=False))
    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
