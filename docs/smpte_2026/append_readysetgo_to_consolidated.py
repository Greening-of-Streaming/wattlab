#!/usr/bin/env python3
"""
append_readysetgo_to_consolidated.py — one-shot, reviewed step folding the
ReadySetGo sport-clip sweep into consolidated_encode_dataset.csv, in the
exact column schema and conventions the file already uses (see
consolidated_encode_dataset.md for the schema's provenance rules).

Adds three new `dataset` values, mirroring the existing s53_* structure:
  - readysetgo_iso_bitrate_sweep_2026-08-28   (60 rows, rung=sweep, 1080p)
  - readysetgo_abr_ladder_typical_2026-08-28  (24 rows, rung=ladder)
  - readysetgo_iso_quality_interpolated_2026-08-28 (45 rows, from
    readysetgo_iso_vmaf_table.csv)

Run once; re-running is safe (guards against duplicate append by dataset name).
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# _staging/, not results/calibration/ directly — see finalize_readysetgo_v0.py's
# docstring: this file would otherwise get served as the live /video/budget dataset.
FINAL_ARTIFACT = ROOT / "results" / "calibration" / "_staging" / "encode_parity_readysetgo_2026-08-28_final.json"
ISO_VMAF_CSV = Path(__file__).parent / "readysetgo_iso_vmaf_table.csv"
CONSOLIDATED = Path(__file__).parent / "consolidated_encode_dataset.csv"

COMPLEXITY_LONG = "sport (SI~38.5/TI~40.4, measured 2026-08-28)"
COMPLEXITY_SHORT = "sport"
VMAF_VERSION = "v0.6.1 (default model, pre-OWL-v1)"
HARDWARE = {"cpu": "Ryzen 9 7900 (24c CPU, libx264/libx265/libsvtav1)",
            "gpu_baseline": "RTX 5080 NVENC", "gpu_tuned": "RTX 5080 NVENC"}
ENCODER_KIND = {"cpu": "cpu", "gpu_baseline": "gpu", "gpu_tuned": "gpu"}
SOURCE_FILE = "results/calibration/_staging/encode_parity_readysetgo_2026-08-28_final.json"

FIELDS = ["dataset", "hardware", "vmaf_version", "clip", "complexity", "codec", "profile",
          "encoder_kind", "rung", "resolution_p", "target_kbps", "achieved_kbps", "vmaf",
          "wh_per_min", "delta_w_watts", "n", "confidence", "source_file", "notes"]


def sweep_ladder_rows(artifact_rows: list) -> list:
    out = []
    for r in artifact_rows:
        rung = r["rung"]
        dataset = ("readysetgo_iso_bitrate_sweep_2026-08-28" if rung == "sweep"
                   else "readysetgo_abr_ladder_typical_2026-08-28")
        notes = ("measured point" if rung == "sweep"
                 else "fixed ABR-ladder rung (typical per-resolution bitrate)")
        out.append({
            "dataset": dataset,
            "hardware": HARDWARE[r["profile"]],
            "vmaf_version": VMAF_VERSION,
            "clip": r["clip"],
            "complexity": COMPLEXITY_LONG,
            "codec": r["codec"],
            "profile": r["profile"],
            "encoder_kind": ENCODER_KIND[r["profile"]],
            "rung": rung,
            "resolution_p": r["height"],
            "target_kbps": r["target_bitrate_kbps"],
            "achieved_kbps": round(r["achieved_bitrate_bps"] / 1000.0, 1) if r.get("achieved_bitrate_bps") else "",
            "vmaf": r["vmaf"],
            "wh_per_min": r["wh_per_min_video"],
            "delta_w_watts": r["delta_w"],
            "n": r["n_encodes"],
            "confidence": r["confidence"]["label"],
            "source_file": SOURCE_FILE,
            "notes": notes,
        })
    return out


def iso_quality_rows() -> list:
    out = []
    with ISO_VMAF_CSV.open() as fh:
        lines = [ln for ln in fh if not ln.startswith("#")]
    for row in csv.DictReader(lines):
        br = row["bitrate_kbps_at_target"]
        wh = row["wh_per_min_at_target"]
        unreachable = br == ""
        notes = (f"target VMAF unreachable in sweep (max measured {row['max_measured_vmaf']})"
                 if unreachable else
                 f"bitrate LINEARLY INTERPOLATED between {row['sweep_points']} measured sweep points, "
                 "not independently measured")
        out.append({
            "dataset": "readysetgo_iso_quality_interpolated_2026-08-28",
            "hardware": HARDWARE[row["profile"]],
            "vmaf_version": VMAF_VERSION,
            "clip": row["clip"],
            "complexity": COMPLEXITY_SHORT,
            "codec": row["codec"],
            "profile": row["profile"],
            "encoder_kind": ENCODER_KIND[row["profile"]],
            "rung": "iso_quality_interp",
            "resolution_p": 1080,
            "target_kbps": br,
            "achieved_kbps": "",
            "vmaf": row["vmaf_target"],
            "wh_per_min": wh,
            "delta_w_watts": "",
            "n": "",
            "confidence": "",
            "source_file": "docs/smpte_2026/readysetgo_iso_vmaf_table.csv",
            "notes": notes,
        })
    return out


def main() -> int:
    existing = CONSOLIDATED.read_text()
    if "readysetgo_iso_bitrate_sweep_2026-08-28" in existing:
        print("ABORT: readysetgo rows already present in consolidated_encode_dataset.csv "
              "— refusing to double-append. Edit/remove manually if a genuine re-run is needed.")
        return 2

    artifact = json.loads(FINAL_ARTIFACT.read_text())
    new_rows = sweep_ladder_rows(artifact["rows"]) + iso_quality_rows()
    assert len(new_rows) == 60 + 24 + 45, f"unexpected row count: {len(new_rows)}"

    with CONSOLIDATED.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        for row in new_rows:
            w.writerow(row)

    print(f"appended {len(new_rows)} rows to {CONSOLIDATED} "
          f"(60 sweep + 24 ladder + 45 iso_quality_interp)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
