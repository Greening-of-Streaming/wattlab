#!/usr/bin/env python3
"""
clean_sweep_to_csv.py — renders the 2026-09-06 clean-protocol sweep into the
consolidated dataset's exact 19-column schema.

Writes two files, and NEVER writes `consolidated_encode_dataset.csv` (Tania's
canonical file is read-only here — owner's rule 2026-09-03, same as
append_readysetgo_to_consolidated.py and append_football_to_consolidated.py):

  1. clean_sweep_2026-09-06.csv              — the 708 clean rows on their own
  2. consolidated_encode_dataset_2026-09-07.csv — Tania's 569 rows verbatim,
                                                  then those 708 appended

Two new `dataset` values, mirroring the existing s53_*/readysetgo_*/football_*
structure:
  - clean_iso_bitrate_sweep_2026-09-06    (516 rows, rung=sweep, 1080p)
  - clean_abr_ladder_typical_2026-09-06   (192 rows, rung=ladder)

NOT emitted: an `*_iso_quality_interpolated` component. Every other campaign has
one, but theirs interpolates from a single measured pass; this run has two, so
the interpolation input is a modelling choice (mean of passes? per-pass curves
then averaged?) that belongs to the analysis, not to this transcription. The
measured rows below carry everything that choice needs.

Schema notes for whoever reads the output:
  - ONE ROW PER MEASUREMENT, not per recipe: each recipe appears twice, once per
    pass, distinguished by the `notes` column ("pass 1 of 2" / "pass 2 of 2").
    The 19-column schema has no replicate column and is not extended here.
  - `n` is n_encodes (how many times the 30 s excerpt was encoded inside that
    row's >=20 s window), exactly as in the existing rows — NOT the replicate
    count.
  - `vmaf_version` says "explicit override" because these scores were produced
    under a deliberate v0.6.1 setting while the live service defaults to v1;
    the existing rows say "pre-OWL-v1" because they predate that default. Both
    are v0.6.1 — group on the "v0.6.1" prefix, not the full string.
  - Rows re-measured on 2026-09-07 after tripping `baseline_elevated` say so in
    `notes`; the superseded originals stay in the JSON artifact's
    `superseded_rows`, and are deliberately not rendered here.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "results" / "calibration" / "_staging" / "encode_parity_CLEAN_nvenc_24c_2026-09-06.json"
CONSOLIDATED = Path(__file__).parent / "consolidated_encode_dataset.csv"           # read-only (Tania's)
STANDALONE = Path(__file__).parent / "clean_sweep_2026-09-06.csv"
VERSIONED = Path(__file__).parent / "consolidated_encode_dataset_2026-09-07.csv"

SOURCE_FILE = "results/calibration/_staging/encode_parity_CLEAN_nvenc_24c_2026-09-06.json"
VMAF_VERSION = "v0.6.1 (default model, explicit override 2026-09-06)"
HARDWARE = {"cpu": "Ryzen 9 7900 (24c CPU, libx264/libx265/libsvtav1)",
            "gpu_baseline": "RTX 5080 NVENC", "gpu_tuned": "RTX 5080 NVENC"}
ENCODER_KIND = {"cpu": "cpu", "gpu_baseline": "gpu", "gpu_tuned": "gpu"}
COMPLEXITY = {
    "meridian_120s": "low (SI~13/TI~2)",
    "bbb_120s": "high (SI~33/TI~6)",
    "readysetgo_30s": "sport (SI~38.5/TI~40.4, measured 2026-08-28)",
    "football_30s": "sport-broadcast (SI~48.3/TI~10.3, measured 2026-09-04)",
}
DATASET = {"sweep": "clean_iso_bitrate_sweep_2026-09-06",
           "ladder": "clean_abr_ladder_typical_2026-09-06"}
BASE_NOTE = {"sweep": "measured point",
             "ladder": "fixed ABR-ladder rung (typical per-resolution bitrate)"}

FIELDS = ["dataset", "hardware", "vmaf_version", "clip", "complexity", "codec", "profile",
          "encoder_kind", "rung", "resolution_p", "target_kbps", "achieved_kbps", "vmaf",
          "wh_per_min", "delta_w_watts", "n", "confidence", "source_file", "notes"]

PROTOCOL_NOTE = ("clean protocol: active wait-for-idle (not a flat 10s sleep), "
                 "baseline_elevated persisted, page cache evicted per row")


def _key(r: dict) -> tuple:
    return (r["clip"], r["codec"], r["profile"], r["target_bitrate_kbps"], r["height"], r["rep"])


def rows_from_artifact(artifact: dict) -> list:
    n_passes = artifact["protocol"]["reps"]
    redone = {_key(r) for r in artifact.get("superseded_rows", [])}
    out = []
    for r in artifact["rows"]:
        rung = r["rung"]
        note = f"{BASE_NOTE[rung]}; pass {r['rep'] + 1} of {n_passes}; {PROTOCOL_NOTE}"
        if _key(r) in redone:
            note += "; re-measured 2026-09-07 after the original tripped baseline_elevated"
        out.append({
            "dataset": DATASET[rung],
            "hardware": HARDWARE[r["profile"]],
            "vmaf_version": VMAF_VERSION,
            "clip": r["clip"],
            "complexity": COMPLEXITY[r["clip"]],
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
            "notes": note,
        })
    return out


def main() -> int:
    artifact = json.loads(ARTIFACT.read_text())
    if not artifact.get("complete"):
        print("ABORT: artifact is not complete — refusing to render a partial run.")
        return 2
    new_rows = rows_from_artifact(artifact)
    assert len(new_rows) == len(artifact["rows"]), "row count must match the artifact exactly"

    with STANDALONE.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(new_rows)
    print(f"wrote {STANDALONE.name}: {len(new_rows)} rows")

    existing = CONSOLIDATED.read_text()
    if DATASET["sweep"] in existing:
        print(f"ABORT: {CONSOLIDATED.name} already carries the clean rows — nothing to do.")
        return 2
    VERSIONED.write_text(existing if existing.endswith("\n") else existing + "\n")
    with VERSIONED.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writerows(new_rows)
    n_prior = sum(1 for _ in csv.DictReader(CONSOLIDATED.open()))
    print(f"wrote {VERSIONED.name}: {n_prior} of Tania's rows (verbatim) + {len(new_rows)} clean rows "
          f"= {n_prior + len(new_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
