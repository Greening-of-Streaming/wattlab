"""Flatten the encode-parity calibration artifact into a full iso-VMAF table.

For every clip x codec x profile, interpolate the bitrate that reaches each VMAF
target and the Wh/min at that bitrate, using the same primitives /video/budget
uses (budget_data._bitrate_at_vmaf / _wh_at_bitrate). Only 1080p sweep rows feed
the curves; ladder rungs are fixed-bitrate and excluded, matching the live page.

Unlike build_recipes() this does not collapse the GPU profiles to the shipped
choice — all three profiles (cpu, gpu_baseline, gpu_tuned) are emitted so the
paper can show the tuned-bundle comparison too.

Usage: python3 docs/smpte_2026/make_iso_vmaf_table.py
Writes iso_vmaf_table.csv next to this script.
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wattlab_service import budget_data

VMAF_TARGETS = [88, 90, 92, 94, 96]
PROFILES = ["cpu", "gpu_baseline", "gpu_tuned"]


def main():
    path = budget_data.latest_artifact_path()
    if not path:
        sys.exit("no complete calibration artifact found")
    artifact = json.loads(Path(path).read_text())
    rows = [r for r in artifact["rows"]
            if r.get("vmaf") is not None and not r.get("error")
            and r.get("rung", "sweep") == "sweep" and r.get("height", 1080) == 1080]

    out_path = Path(__file__).parent / "iso_vmaf_table.csv"
    with out_path.open("w", newline="") as fh:
        fh.write(f"# Iso-VMAF table derived from {Path(path).name} "
                 f"(measured {artifact.get('generated_at')}; VMAF v0.6.1 default model; "
                 "1080p single rendition; linear interpolation between measured sweep "
                 "points, method as /methodology#energy-budget)\n")
        w = csv.writer(fh)
        w.writerow(["clip", "complexity", "codec", "profile", "vmaf_target",
                    "bitrate_kbps_at_target", "wh_per_min_at_target",
                    "max_measured_vmaf", "sweep_points"])
        for clip, cx in budget_data._CLIP_COMPLEXITY.items():
            for codec in ("h264", "h265", "av1"):
                for profile in PROFILES:
                    sel = [r for r in rows if r["clip"] == clip
                           and r["codec"] == codec and r["profile"] == profile]
                    if not sel:
                        continue
                    max_v = round(max(r["vmaf"] for r in sel), 2)
                    for t in VMAF_TARGETS:
                        br = budget_data._bitrate_at_vmaf(sel, t)
                        wh = budget_data._wh_at_bitrate(sel, br) if br else None
                        w.writerow([clip, cx, codec, profile, t,
                                    br if br is not None else "",
                                    wh if wh is not None else "",
                                    max_v, len(sel)])
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
