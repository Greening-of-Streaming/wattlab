#!/usr/bin/env python3
"""
finalize_readysetgo_v0.py — same field-renaming step bin/merge-bitrate-ext.py
did for the BBB/Meridian bitrate-ceiling extension, applied to the ReadySetGo
sweep: swap the primary `vmaf` field to the v0.6.1 rescore (matching the
convention of every other row in consolidated_encode_dataset.csv — absent
`vmaf_model` == v0.6.1), keep the live-run v1 score under `vmaf_v1_bonus` for
reference only.

Both files live under results/calibration/_staging/, not results/calibration/ directly —
budget_data.ARTIFACT_GLOB picks the newest complete "encode_parity_*.json" by mtime for
/video/budget, and either of these would otherwise get served as the live canonical
dataset (caught 2026-08-29, same regression class as the S70 bitrate-ceiling extension
file — see JOURNAL Session 71).

Input: results/calibration/_staging/encode_parity_readysetgo_2026-08-28.json (84 rows,
all carrying vmaf_v0 from bin/rescore-readysetgo-v0.py).
Output: results/calibration/_staging/encode_parity_readysetgo_2026-08-28_final.json
(the raw file is left untouched — this writes a new file).
"""
import json
from pathlib import Path

STAGING = Path("/home/gos/wattlab/results/calibration/_staging")
SRC = STAGING / "encode_parity_readysetgo_2026-08-28.json"
OUT = STAGING / "encode_parity_readysetgo_2026-08-28_final.json"

d = json.loads(SRC.read_text())
assert all("vmaf_v0" in r for r in d["rows"]), "not all rows rescored yet"

final_rows = []
for r in d["rows"]:
    r = dict(r)
    v1 = r.pop("vmaf")
    v1_model = r.pop("vmaf_model")
    v0 = r.pop("vmaf_v0")
    r.pop("vmaf_v0_model", None)
    r["vmaf"] = v0                  # primary field, matches the v0.6.1 convention
    r["vmaf_v1_bonus"] = v1         # kept, clearly labelled, not the primary comparator
    r["vmaf_v1_bonus_model"] = v1_model
    final_rows.append(r)

out = dict(d)
out["rows"] = final_rows
out["protocol"] = dict(d["protocol"])
out["protocol"]["note"] = (
    "Rescored 2026-08-28: sweep ran under the live service's then-default "
    "vmaf_model=v1; re-encoded each row's stored ffmpeg_cmd (deterministic, "
    "no re-measurement) and rescored under an in-process vmaf_model=v0 "
    "override (bin/rescore-readysetgo-v0.py) to match the v0.6.1 convention "
    "of the BBB/Meridian/Kranjska canonical dataset. `vmaf` here is the "
    "v0.6.1 rescore; the original v1 score is kept under vmaf_v1_bonus."
)

OUT.write_text(json.dumps(out, indent=2))
print(f"wrote {OUT} ({len(final_rows)} rows)")
