#!/usr/bin/env python3
"""
run-bitrate-ceiling-ext.py — supplemental encode-parity campaign, 2026-08-28.

Adds a thin top layer of high-bitrate points to the existing S53 encode-parity
sweep (results/calibration/encode_parity_nvenc_24c_2026-06-20.json) so the
iso-VMAF table closes its 94/96 gaps wherever that's still a realistic
streaming bitrate. Does NOT touch the 207 existing rows — writes to its own
fresh artifact; merging into the canonical file is a deliberate, reviewed
step done AFTER this run, not part of it.

Scope decided 2026-08-28 (see chat): H.264/H.265 extended on Meridian+BBB up
to a defensible premium/live-tier ceiling; AV1 gets exactly one more point
(94 only — VMAF 96 for AV1 at 1080p is being deliberately left undocumented-
as-unreachable, not chased); Kranjska's already-generous H.264/H.265 ladder
is left alone (it already exceeds realistic streaming bitrates); Kranjska AV1
gets one optional matching point for consistency (--include-kranjska-av1).

Usage:
  bin/run-bitrate-ceiling-ext.py --print-only              # verify recipe, no encode
  bin/run-bitrate-ceiling-ext.py --run                     # the real metered run
  bin/run-bitrate-ceiling-ext.py --run --include-kranjska-av1
  bin/run-bitrate-ceiling-ext.py --run --skip-lab-session  # pause only, no visitor lockout

Handles pause/lock/cleanup itself: sets /tmp/owl-paused (+ /tmp/owl-lab-session
unless --skip-lab-session) before the first encode, restores both — even on
Ctrl-C or a crash — before exiting. Refuses to start if the queue isn't
already idle.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "wattlab_service"))
import parity   # noqa: E402
import queue_control  # noqa: E402

PAUSE_FLAG = Path("/tmp/owl-paused")
LAB_SESSION_FLAG = Path("/tmp/owl-lab-session")
LOCK_FILE = Path("/tmp/gos-measure.lock")

ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "results" / "calibration"
OUT_ARTIFACT = ARTIFACT_DIR / "encode_parity_nvenc_24c_2026-08-28_bitrate_ext.json"

# --- Mandatory tier: Meridian + BBB, H.264/H.265 to a defensible premium-tier
# ceiling, AV1 one point (targeting VMAF 94, not 96 — see module docstring).
MANDATORY = parity.Campaign(
    clips=["meridian_120s", "bbb_120s"],
    codecs=["h264", "h265", "av1"],
    profiles=["cpu", "gpu_baseline", "gpu_tuned"],
    bitrates={
        "h264": [13000, 15000],
        "h265": [8500, 10000],
        "av1":  [7500],
    },
    duration_s=30,
    baseline_polls=5, cooldown_s=10,   # matches the original S53 protocol exactly
    min_task_s=20.0,
)

# --- Optional tier: extend the same "sport gets headroom" courtesy to AV1 on
# Kranjska that H.264/H.265 already got (their ladder already covers this).
KRANJSKA_AV1 = parity.Campaign(
    clips=["kranjska_120s"],
    codecs=["av1"],
    profiles=["cpu", "gpu_baseline", "gpu_tuned"],
    bitrates={"av1": [13000]},
    duration_s=30,
    baseline_polls=5, cooldown_s=10,
    min_task_s=20.0,
)


def log(msg: str) -> None:
    print(msg, flush=True)


def preflight() -> bool:
    """Refuse to start unless the box is actually idle. Mirrors /bench-preflight."""
    ok = True
    if LOCK_FILE.exists():
        log(f"ABORT: {LOCK_FILE} already exists (held by: {LOCK_FILE.read_text()!r}) "
            "— something else is mid-measurement.")
        ok = False
    if PAUSE_FLAG.exists():
        log(f"ABORT: {PAUSE_FLAG} already set — a prior pause was never cleared. "
            "Investigate before adding another.")
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
            f"falling back to curl http://127.0.0.1:8000/live check.")
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
    camps = [("MANDATORY", MANDATORY), ("KRANJSKA_AV1 (optional)", KRANJSKA_AV1)]
    total = 0
    for name, camp in camps:
        n = camp.count()
        total += n
        log(f"\n=== {name}: {n} rows ===")
        for idx, rc in enumerate(camp.recipes()):
            log(f"  {idx}: {rc['clip']:15s} {rc['codec']:5s} {rc['profile']:12s} "
                f"{rc['height']}p {rc['bps']:>6}k [{rc['kind']}]")
    log(f"\nTOTAL rows if both run: {total}  "
        f"(~{round(total * 50 / 60, 1)} min at ~50s/row observed average)")


async def run_real(include_kranjska: bool, use_lab_session: bool) -> int:
    if not preflight():
        return 2

    log(f"Setting {PAUSE_FLAG} (backs off the live 5s power poller)")
    PAUSE_FLAG.write_text("bin/run-bitrate-ceiling-ext.py — supplemental parity campaign\n")
    if use_lab_session:
        log(f"Setting {LAB_SESSION_FLAG} (non-Lab job submission refused, browsing stays open)")
        LAB_SESSION_FLAG.write_text("bitrate-ceiling extension campaign\n")

    try:
        log("\n--- MANDATORY campaign (Meridian+BBB, H.264/H.265/AV1 ceiling points) ---")
        await parity.run_campaign(MANDATORY, dry=False, merge_into=None, log=log)
        # run_campaign wrote its own fresh file (fingerprint_slug + today's date).
        # Rename/move it to our fixed OUT_ARTIFACT name so the kranjska leg (if any)
        # merges into the SAME file rather than creating a second one.
        fp = parity.fingerprint()
        slug = parity.fingerprint_slug(fp)
        from datetime import datetime, timezone
        date = datetime.now(timezone.utc).isoformat(timespec="seconds")[:10]
        produced = ARTIFACT_DIR / f"encode_parity_{slug}_{date}.json"
        if produced.exists() and produced != OUT_ARTIFACT:
            produced.replace(OUT_ARTIFACT)
            log(f"renamed {produced.name} -> {OUT_ARTIFACT.name}")

        if include_kranjska:
            log("\n--- OPTIONAL campaign (Kranjska AV1 ceiling point) ---")
            await parity.run_campaign(KRANJSKA_AV1, dry=False, merge_into=OUT_ARTIFACT, log=log)

        log(f"\nDONE. Extension artifact: {OUT_ARTIFACT}")
        log("This is a SEPARATE file from the canonical 06-20 artifact — nothing in "
            "the original 207-row dataset was touched. Merging the two is a deliberate "
            "follow-up step, not automatic.")
        return 0
    finally:
        log(f"\nRestoring normal state...")
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
    p.add_argument("--include-kranjska-av1", action="store_true",
                   help="also run the optional Kranjska AV1 ceiling point")
    p.add_argument("--skip-lab-session", action="store_true",
                   help="only set the pause flag, skip the visitor-lockout flag")
    args = p.parse_args()

    if args.print_only:
        print_recipes()
        return 0
    if args.run:
        return asyncio.run(run_real(args.include_kranjska_av1, not args.skip_lab_session))
    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
