#!/usr/bin/env python3
"""
rescore-football-v0.py — v0.6.1 rescore of the 2026-09-03 football sports-tier
encode-parity sweep (clone of rescore-readysetgo-v0.py, constants only).

Same bug class as the 2026-08-28 bitrate-ceiling extension (see
bin/rescore-bitrate-ext-v0.py): the sweep ran under the live service's
current default (vmaf_model=v1, settings.json), but the canonical dataset
it's meant to sit alongside for iso-VMAF comparison (BBB/Meridian/Kranjska
in consolidated_encode_dataset.csv) is v0.6.1. Rather than re-running the
full metered campaign (another ~77 min touching the P110), this re-runs
each row's EXACT stored ffmpeg_cmd (deterministic CBR encode, same
input/settings -> bit-identical output) against the still-present trimmed
reference clip, and scores the result under v0.6.1 via an in-process
settings override — video.compute_vmaf(s=...) — that does NOT touch the
live service's settings.json, so it has zero effect on what any concurrent
visitor's job gets scored with.

No power measurement, no focus mode, no lock/pause needed — this is pure
CPU/GPU re-encode + score, energy-irrelevant. Adds vmaf_v0/vmaf_v0_model
fields to each row alongside the existing v1 `vmaf` field; does not touch
delta_w/wh_per_min (those are valid regardless of VMAF model).
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "wattlab_service"))
import video     # noqa: E402
import quality   # noqa: E402
import settings as cfg  # noqa: E402

# _staging/, not results/calibration/ directly — budget_data.ARTIFACT_GLOB picks the
# newest complete "encode_parity_*.json" by mtime for /video/budget, and this file would
# otherwise get served as the live canonical dataset (caught 2026-08-29, same regression
# class as the S70 bitrate-ceiling extension file).
ARTIFACT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "results" / "calibration" / "_staging" / \
    "encode_parity_football_2026-09-03.json"
REF_DIR = Path("/tmp/wattlab_parity_clips")
REF = REF_DIR / "football_35s_30s.mp4"
OUT_DIR = Path("/tmp/wattlab_rescore_v0_football")

V0_SETTINGS = {**cfg.load(), "vmaf_model": "v0"}


def main() -> int:
    if not REF.exists():
        print(f"ABORT: reference clip missing: {REF}")
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    d = json.loads(ARTIFACT.read_text())
    rows = d["rows"]
    print(f"[rescore] {len(rows)} rows to re-encode + score under vmaf_model=v0")

    for i, r in enumerate(rows):
        if "vmaf_v0" in r:
            continue  # already done in a prior pass — don't redo deterministic work

        out_path = OUT_DIR / f"row{i:03d}_{r['clip']}_{r['codec']}_{r['profile']}_{r['target_bitrate_kbps']}.mp4"
        cmd = r["ffmpeg_cmd"]
        parts = cmd.split()
        orig_out = None
        for tok in parts:
            if tok.endswith(".mp4") and "wattlab_uploads" in tok:
                orig_out = tok
                break
        if orig_out:
            cmd_fixed = cmd.replace(orig_out, str(out_path))
        else:
            print(f"  {i+1}/{len(rows)}: WARN could not locate original output path in "
                  f"stored ffmpeg_cmd, appending output manually")
            cmd_fixed = cmd + f" {out_path}"

        print(f"  {i+1}/{len(rows)}: {r['clip']:15s} {r['codec']:5s} {r['profile']:12s} "
              f"{r['target_bitrate_kbps']}k ...", end=" ", flush=True)

        try:
            subprocess.run(cmd_fixed, shell=True, check=True,
                            capture_output=True, text=True, timeout=180)
            vmaf_v0 = video.compute_vmaf(out_path, REF, s=V0_SETTINGS)
            r["vmaf_v0"] = vmaf_v0
            r["vmaf_v0_model"] = quality.vmaf_model_id(V0_SETTINGS)
            print(f"vmaf_v0={vmaf_v0}  (v1 was {r.get('vmaf')})")
        except subprocess.CalledProcessError as exc:
            print(f"ENCODE FAILED: {exc.stderr[-300:] if exc.stderr else exc}")
            r["vmaf_v0_error"] = f"encode failed: {exc}"
        except Exception as exc:
            print(f"SCORE FAILED: {exc!r}")
            r["vmaf_v0_error"] = f"score failed: {exc!r}"
        finally:
            out_path.unlink(missing_ok=True)

        # checkpoint after every row
        ARTIFACT.write_text(json.dumps(d, indent=2))

    ok = sum(1 for r in rows if "vmaf_v0" in r)
    print(f"\n[rescore] done: {ok}/{len(rows)} rows now carry vmaf_v0. Artifact updated in place: {ARTIFACT}")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
