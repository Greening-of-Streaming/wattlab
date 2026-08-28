#!/usr/bin/env python3
"""
merge-bitrate-ext.py — merge the rescored (vmaf_v0-carrying) bitrate-ceiling
extension into a new, complete 240-row artifact so /video/budget's
"latest complete artifact by mtime" pickup sees a correct, full dataset
instead of the 33-row extension file on its own.

The original 06-20 canonical file (207 rows) is left untouched. This writes
a NEW file that becomes the new "latest" — that's deliberate: it's supposed
to supersede 06-20 as OWL's live dataset now that it's genuinely more
complete, not just sit alongside it unused.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/home/gos/wattlab/results/calibration/encode_parity_nvenc_24c_2026-06-20.json")
EXT = Path("/home/gos/wattlab/results/calibration/encode_parity_nvenc_24c_2026-08-28_bitrate_ext.json")
OUT = Path("/home/gos/wattlab/results/calibration/encode_parity_nvenc_24c_2026-06-20_plus_ext.json")

base = json.loads(BASE.read_text())
ext = json.loads(EXT.read_text())

assert base["complete"] and ext["complete"]
assert all("vmaf_v0" in r for r in ext["rows"]), "extension has un-rescored rows"

merged_rows = list(base["rows"])  # 207 originals, untouched, vmaf field is v0.6.1 natively
for r in ext["rows"]:
    r = dict(r)
    v1 = r.pop("vmaf")             # the v1 score from the real metered run
    v1_model = r.pop("vmaf_model")
    v0 = r.pop("vmaf_v0")
    v0_model = r.pop("vmaf_v0_model", None)
    r["vmaf"] = v0                 # primary field matches the v0.6.1 convention of the
                                    # other 207 rows (absent vmaf_model == v0.6.1)
    r["vmaf_v1_bonus"] = v1        # kept, clearly labelled, not the primary comparator
    r["vmaf_v1_bonus_model"] = v1_model
    merged_rows.append(r)

merged = dict(base)  # keep original fingerprint/protocol as the base of truth
merged["rows"] = merged_rows
merged["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
merged["complete"] = True
merged["protocol"] = dict(base["protocol"])
merged["protocol"]["expected_rows"] = len(merged_rows)
merged["protocol"]["note"] = (
    "Merged 2026-08-28: 207 original S53 rows (06-20, unmodified) + 33 supplemental "
    "high-bitrate-ceiling rows (extending Meridian/BBB H.264/H.265/AV1 and Kranjska AV1 "
    "toward realistic streaming-bitrate VMAF 94-96 coverage). Extension rows' `vmaf` is "
    "the v0.6.1 rescore (matches the rest of this file); the live-run v1 score is kept "
    "under vmaf_v1_bonus for reference, not used in any v0.6.1 comparison."
)

OUT.write_text(json.dumps(merged, indent=2))
print(f"wrote {OUT} ({len(merged_rows)} rows, {len(base['rows'])} original + {len(ext['rows'])} extension)")
