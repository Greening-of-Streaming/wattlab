#!/usr/bin/env python3
"""merge_football_ext.py — fold the football ceiling-extension (and recheck) artifacts into the
football dataset: (1) finalize each (v0 rescore → primary `vmaf`), (2) write
encode_parity_football_2026-09-03_merged_final.json (base + ext rows; the recheck rows are kept in
their own file, not merged — they duplicate base rungs), (3) regenerate football_iso_vmaf_table.csv
from the merged rows, (4) append the ext rows as dataset `football_bitrate_ceiling_ext_2026-09-04` to
consolidated_encode_dataset_2026-09-04.csv and REWRITE its football_iso_quality_interpolated rows from
the regenerated table. Tania's consolidated_encode_dataset.csv is never touched."""
import csv, json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; STAGING = ROOT / "results" / "calibration" / "_staging"; HERE = Path(__file__).parent
BASE_FINAL = STAGING / "encode_parity_football_2026-09-03_final.json"
EXT = sorted(STAGING.glob("encode_parity_football_ceiling_ext_*.json"))
def finalize(rows):
    out = []
    for r in rows:
        r = dict(r); v1 = r.pop("vmaf"); v1m = r.pop("vmaf_model", None); v0 = r.pop("vmaf_v0"); r.pop("vmaf_v0_model", None)
        r["vmaf"] = v0; r["vmaf_v1_bonus"] = v1; r["vmaf_v1_bonus_model"] = v1m; out.append(r)
    return out
base = json.loads(BASE_FINAL.read_text())
ext_rows = []
for p in EXT:
    if "_final" in p.name: continue
    d = json.loads(p.read_text()); assert all("vmaf_v0" in r for r in d["rows"]), f"{p.name} not rescored"
    ext_rows += finalize(d["rows"])
merged = dict(base); merged["rows"] = base["rows"] + ext_rows
merged["protocol"] = dict(base["protocol"]); merged["protocol"]["note"] = base["protocol"].get("note", "") + \
    f" | 2026-09-04: + {len(ext_rows)} bitrate-ceiling extension rows (AV1 9–13 Mbps, HEVC 12–16 Mbps, same protocol, separate artifact)."
MERGED = STAGING / "encode_parity_football_2026-09-03_merged_final.json"; MERGED.write_text(json.dumps(merged, indent=2))
print("merged", len(merged["rows"]), "rows →", MERGED.name)
# regenerate iso table from the merged file by pointing the table script at it
tbl = (HERE / "make_football_iso_vmaf_table.py").read_text().replace("encode_parity_football_2026-09-03_final.json", MERGED.name)
exec(compile(tbl, "make_football_iso_vmaf_table(merged)", "exec"), {"__name__": "__main__", "__file__": str(HERE / "make_football_iso_vmaf_table.py")})
# versioned CSV: add ext rows, replace the interpolated rows
VERS = HERE / "consolidated_encode_dataset_2026-09-04.csv"
rows = list(csv.DictReader(VERS.open()))
fields = list(rows[0].keys())
keep = [r for r in rows if r["dataset"] != "football_iso_quality_interpolated_2026-09-03"]
app = (HERE / "append_football_to_consolidated.py").read_text()
ns = {"__name__": "x", "__file__": str(HERE / "append_football_to_consolidated.py")}; exec(compile(app, "append", "exec"), ns)
new_ext = ns["sweep_ladder_rows"](ext_rows)
for r in new_ext: r["dataset"] = "football_bitrate_ceiling_ext_2026-09-04"; r["notes"] = "bitrate-ceiling extension point (separate artifact, additive)"; r["source_file"] = str(MERGED.relative_to(ROOT))
new_iso = ns["iso_quality_rows"]()
# the h264 gpu_tuned recheck (3 rows) goes in as its own dataset — the main artifact keeps its measured outlier
RECHECK = sorted(p for p in STAGING.glob("encode_parity_football_recheck_*.json") if "_final" not in p.name)
new_rc = []
for p in RECHECK:
    d = json.loads(p.read_text())
    rows_rc = finalize(d["rows"]) if all("vmaf_v0" in r for r in d["rows"]) else d["rows"]
    for r in ns["sweep_ladder_rows"](rows_rc):
        r["dataset"] = "football_h264_gputuned_recheck_2026-09-04"; r["source_file"] = str(p.relative_to(ROOT))
        r["notes"] = "re-measure of the main sweep's 11/13/15 Mbps h264 gpu_tuned rows (its 13000k row read 32.5 W, an outlier)"
        new_rc.append(r)
with VERS.open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=fields); w.writeheader()
    for r in keep + new_ext + new_rc + new_iso: w.writerow(r)
print(f"{VERS.name}: {len(keep)} kept + {len(new_ext)} ext + {len(new_rc)} recheck + {len(new_iso)} iso rows")
