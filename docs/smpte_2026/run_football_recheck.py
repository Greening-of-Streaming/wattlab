#!/usr/bin/env python3
"""
run_football_clip_sweep.py — encode-parity campaign for the `football` sports
tier (CR-081, 2026-09-03): a clone of run_sport_clip_sweep.py (Tania's
ReadySetGo sweep) with the clip constants swapped. Same 84-row recipe, same
frozen Meridian/BBB ladder, same 30 s / 5-poll / 10 s-cooldown S53 protocol, so
the rows sit beside the canonical dataset. Source: the Panasonic "Barcelona
Football" 4K60 demo (YouTube re-upload, LAB-INTERNAL, no citable licence —
measurements are fine, the pictures are not), 50–85 s excerpt re-wrapped as
4K60 H.264 High ~30 Mbps limited-range bt709 (BBB/Meridian's masters are
limited-range too; ReadySetGo was stretched to full range).

SELF-CONTAINED BY DESIGN: does NOT modify wattlab_service/parity.py — no
edits to CLIPS / FULL_BITRATES / full_campaign() / ladder_campaign() in that
module, no effect on the live /video/budget artifact or any other
website-serving code path. It imports parity.py read-only for the Campaign
machinery (and the real measurement primitives — there's no other way to
take a real power measurement), and injects this one clip into
parity.CLIPS **at runtime, in this process only** rather than editing the
file on disk. Writes its own artifact file; folding it into
consolidated_encode_dataset.csv is a later, deliberate, reviewed step, same
pattern as bin/run-bitrate-ceiling-ext.py used for the 2026-08-28 extension.

Ladder: intentionally the EXACT SAME per-codec bitrate points already
measured for Meridian/BBB in the canonical merged dataset (see
docs/smpte_2026/consolidated_encode_dataset.md, caveat 9) — NOT
parity.FULL_BITRATES, which is only the pre-extension 5-point version.
Copied explicitly below so this script has zero dependency on parity.py's
constants ever changing under it. Per Tania 2026-08-28: keep this ladder
even if it undershoots useful VMAF on the new content — extending upward
for iso-VMAF coverage is a separate, later, additive step, never a reason
to fold a per-clip override back into the shared ladder (that's the exact
mistake Kranjska's SPORTS_BITRATES made, and the whole reason this script
exists instead of reusing parity.full_campaign() directly).

Usage:
  1. python docs/smpte_2026/run_sport_clip_sweep.py --print-only
     (sanity-check the recipe list / row count)
  2. python docs/smpte_2026/run_sport_clip_sweep.py --run
     (the real metered run, unattended; needs /bench-preflight conditions:
     queue idle, meter exclusive)

Base-ladder only: this covers the matched BBB/Meridian bitrate points, not
an iso-VMAF-92 extension. Per Tania 2026-08-28, extending upward is a
separate, later, additive step (mirrors bin/run-bitrate-ceiling-ext.py's
relationship to the original S53 sweep) — decided AFTER scoring this run's
real VMAF, not baked in here.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "wattlab_service"))
import parity          # noqa: E402 — read-only use; nothing here mutates the file on disk
import queue_control   # noqa: E402

# Sourced 2026-08-28: ReadySetGo (horse-racing starting-gate footage), converted
# from native yuv420p10le/3840x2160/120fps/limited-range to match BBB/Meridian's
# format — 60fps (2:1 frame-drop decimation, no blending), 8-bit 4:2:0, full-range
# (zscale limited->full stretch, Tania's call), tagged bt709. Looped to 35.0s so
# ensure_clip()'s -t 30 trims to an exact 30.000s window with margin. See chat log
# 2026-08-28 for the KartingTime clip that was prepped alongside this one but not
# (yet) wired in here.
CLIP_KEY = "football_30s"
SOURCE_CLIP = Path("/home/gos/wattlab/test_content/football_35s.mp4")
# ---------------------------------------------------------------------------

ARTIFACT_DIR = REPO_ROOT / "results" / "calibration"
OUT_ARTIFACT = ARTIFACT_DIR / "_staging" / f"encode_parity_football_recheck_{datetime.now(timezone.utc).date()}.json"

# Exactly the canonical Meridian/BBB ladder from the merged dataset
# (results/calibration/encode_parity_nvenc_24c_2026-06-20_plus_ext.json —
# base S53 sweep + the 2026-08-28 bitrate-ceiling extension). Frozen here
# standalone — do NOT resync this to parity.FULL_BITRATES; that constant is
# the pre-extension version and is not what BBB/Meridian's canonical rows
# were actually measured at.
# RECHECK (2026-09-04 00:25): the main sweep's h264 gpu_tuned 13000k row read ΔW 32.5 W /
# 0.147 Wh/min against 49–52 W / 0.22 on its neighbours — one outlier in 84 🟢 rows. Re-measure
# that row and its neighbours in a separate artifact so the main artifact is left as measured.
MATCHED_BITRATES = {"h264": [11000, 13000, 15000]}

PAUSE_FLAG = Path("/tmp/owl-paused")
LAB_SESSION_FLAG = Path("/tmp/owl-lab-session")
LOCK_FILE = Path("/tmp/gos-measure.lock")


def campaign() -> "parity.Campaign":
    return parity.Campaign(
        clips=[CLIP_KEY],
        codecs=["h264"],
        profiles=["gpu_tuned"],
        bitrates=MATCHED_BITRATES,
        duration_s=30,                    # matches the S53 protocol exactly (Meridian/BBB)
        baseline_polls=5, cooldown_s=10,  # matches the S53 protocol exactly
        min_task_s=20.0,
        ladder_rungs=[],  # same 4 ABR rungs as everyone else
    )


def log(msg: str) -> None:
    print(msg, flush=True)


def preflight() -> bool:
    """Refuse to start unless the box is actually idle. Mirrors /bench-preflight
    and bin/run-bitrate-ceiling-ext.py's own check."""
    ok = True
    if LOCK_FILE.exists():
        log(f"ABORT: {LOCK_FILE} already exists (held by: {LOCK_FILE.read_text()!r}) "
            "— something else is mid-measurement.")
        ok = False
    if PAUSE_FLAG.exists():
        log(f"ABORT: {PAUSE_FLAG} already set — a prior pause was never cleared. "
            "Investigate before adding another.")
        ok = False
    if not SOURCE_CLIP.exists():
        log(f"ABORT: {SOURCE_CLIP} does not exist — fill in SOURCE_CLIP at the top "
            "of this script once the clip is sourced.")
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
    log(f"=== football full sweep: {n} rows ===")
    for idx, rc in enumerate(camp.recipes()):
        log(f"  {idx}: {rc['clip']:15s} {rc['codec']:5s} {rc['profile']:12s} "
            f"{rc['height']}p {rc['bps']:>6}k [{rc['kind']}]")
    log(f"\n~{round(n * 50 / 60, 1)} min at ~50s/row observed average "
        "(from the base S53 06-20 campaign: 9796.6s / 207 rows = 47.3s/row — "
        "expect a bit slower on the CPU-profile rows given real motion).")


async def run_real(use_lab_session: bool) -> int:
    if not preflight():
        return 2

    # Inject the new clip into parity.CLIPS for THIS PROCESS ONLY — never
    # written to wattlab_service/parity.py. Dies with this process.
    parity.CLIPS[CLIP_KEY] = SOURCE_CLIP

    log(f"Setting {PAUSE_FLAG} (backs off the live 5s power poller)")
    PAUSE_FLAG.write_text("docs/smpte_2026/run_football_clip_sweep.py — football encode sweep (CR-081)\n")
    if use_lab_session:
        log(f"Setting {LAB_SESSION_FLAG} (non-Lab job submission refused, browsing stays open)")
        LAB_SESSION_FLAG.write_text("football encode sweep (CR-081)\n")

    try:
        camp = campaign()
        log(f"\n--- sport-clip full sweep ({camp.count()} rows) ---")
        await parity.run_campaign(camp, dry=False, merge_into=None, log=log)
        # run_campaign wrote its own fresh file (fingerprint_slug + today's date) —
        # rename to our fixed OUT_ARTIFACT name for a predictable path.
        fp = parity.fingerprint()
        slug = parity.fingerprint_slug(fp)
        date = datetime.now(timezone.utc).isoformat(timespec="seconds")[:10]
        produced = ARTIFACT_DIR / f"encode_parity_{slug}_{date}.json"
        OUT_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        if produced.exists() and produced != OUT_ARTIFACT:
            produced.replace(OUT_ARTIFACT)
            log(f"renamed {produced.name} -> {OUT_ARTIFACT.name}")
        log(f"\nDONE. Artifact: {OUT_ARTIFACT}")
        log("This is a SEPARATE file — nothing in the canonical BBB/Meridian dataset was "
            "touched. Folding it into consolidated_encode_dataset.csv is a deliberate, "
            "reviewed follow-up step, not automatic.")
        return 0
    finally:
        log("\nRestoring normal state...")
        PAUSE_FLAG.unlink(missing_ok=True)
        LAB_SESSION_FLAG.unlink(missing_ok=True)
        LOCK_FILE.unlink(missing_ok=True)  # belt-and-braces; run_campaign already does this itself
        log(f"  {PAUSE_FLAG}: {'still present (!)' if PAUSE_FLAG.exists() else 'removed'}")
        log(f"  {LAB_SESSION_FLAG}: {'still present (!)' if LAB_SESSION_FLAG.exists() else 'removed'}")
        log(f"  {LOCK_FILE}: {'still present (!)' if LOCK_FILE.exists() else 'removed'}")
        log("Queue worker will pick back up on its own now that the pause flag is gone.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--print-only", action="store_true", help="show the recipe list, no encoding")
    p.add_argument("--run", action="store_true", help="actually run it (metered, real)")
    p.add_argument("--skip-lab-session", action="store_true",
                   help="only set the pause flag, skip the visitor-lockout flag")
    args = p.parse_args()

    if args.print_only:
        print_recipes()
        return 0
    if args.run:
        return asyncio.run(run_real(not args.skip_lab_session))
    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
