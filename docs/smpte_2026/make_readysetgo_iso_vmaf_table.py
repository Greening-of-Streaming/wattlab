"""
make_readysetgo_iso_vmaf_table.py — the same iso-VMAF interpolation as
make_iso_vmaf_table.py, standalone for the ReadySetGo sweep instead of the
live BBB/Meridian/Kranjska canonical artifact (which make_iso_vmaf_table.py
reads via budget_data.latest_artifact_path() — deliberately NOT touched
here, same self-containment rule as run_sport_clip_sweep.py).

For codec x profile, interpolate the bitrate that reaches each VMAF target
and the Wh/min at that bitrate, using the same primitives /video/budget uses
(budget_data._bitrate_at_vmaf / _wh_at_bitrate). Only 1080p sweep rows feed
the curves; ladder rungs are fixed-bitrate and excluded, matching the live
page's own convention.

Usage: python3 docs/smpte_2026/make_readysetgo_iso_vmaf_table.py
Writes readysetgo_iso_vmaf_table.csv next to this script.
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wattlab_service import budget_data  # noqa: E402

# _staging/, not results/calibration/ directly — see finalize_readysetgo_v0.py's
# docstring: this file would otherwise get served as the live /video/budget dataset.
ARTIFACT = Path(__file__).resolve().parents[2] / "results" / "calibration" / "_staging" / \
    "encode_parity_readysetgo_2026-08-28_final.json"
VMAF_TARGETS = [88, 90, 92, 94, 96]
PROFILES = ["cpu", "gpu_baseline", "gpu_tuned"]
COMPLEXITY = "sport (SI~38.5/TI~40.4, measured 2026-08-28)"


def main():
    artifact = json.loads(ARTIFACT.read_text())
    rows = [r for r in artifact["rows"]
            if r.get("vmaf") is not None and not r.get("error")
            and r.get("rung", "sweep") == "sweep" and r.get("height", 1080) == 1080]

    out_path = Path(__file__).parent / "readysetgo_iso_vmaf_table.csv"
    with out_path.open("w", newline="") as fh:
        fh.write(f"# Iso-VMAF table derived from {ARTIFACT.name} "
                 f"(measured {artifact.get('generated_at')}; rescored to VMAF v0.6.1, "
                 "see protocol.note; 1080p single rendition; linear interpolation "
                 "between measured sweep points, method as /methodology#energy-budget)\n")
        w = csv.writer(fh)
        w.writerow(["clip", "complexity", "codec", "profile", "vmaf_target",
                    "bitrate_kbps_at_target", "wh_per_min_at_target",
                    "max_measured_vmaf", "sweep_points"])
        for codec in ("h264", "h265", "av1"):
            for profile in PROFILES:
                sel = [r for r in rows if r["codec"] == codec and r["profile"] == profile]
                if not sel:
                    continue
                max_v = round(max(r["vmaf"] for r in sel), 2)
                for t in VMAF_TARGETS:
                    br = budget_data._bitrate_at_vmaf(sel, t)
                    wh = budget_data._wh_at_bitrate(sel, br) if br else None
                    w.writerow(["readysetgo_30s", COMPLEXITY, codec, profile, t,
                                br if br is not None else "",
                                wh if wh is not None else "",
                                max_v, len(sel)])
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
