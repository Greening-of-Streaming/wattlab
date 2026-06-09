#!/usr/bin/env python3
"""ForTania — flatten last night's /video runs into a spreadsheet (CSV).

Created 2026-05-29 at Ben's request: Tania wanted all of the overnight video
runs in one downloadable spreadsheet. This script IS the record — re-run it to
regenerate, or tweak NIGHT_START / NIGHT_END / the column set and re-run.

  python3 data_exports/for_tania_video.py

Writes the canonical copy to   data_exports/ForTania.csv
and (if PUBLISH_DIR exists) a public copy nginx serves un-gated from /static/.

One row per transcode (codec x CPU/GPU). Handles both result shapes:
  - mode='all_codecs'  -> codecs[codec][cpu|gpu]   (6 rows/file)
  - mode='both'        -> top-level cpu / gpu       (2 rows/file)
"""
import csv
import glob
import json
import os
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO_DIR = os.path.join(REPO, "results", "video")

# "Last night" = the overnight benchmark window (2026-05-28 evening -> 29 morning).
NIGHT_START = datetime(2026, 5, 28, 18, 0, 0)
NIGHT_END = datetime(2026, 5, 29, 9, 0, 0)

OUT_CANONICAL = os.path.join(REPO, "data_exports", "ForTania.csv")
# Public copy: nginx serves /static/ un-gated; the random subdir is the "hidden link".
PUBLISH_DIR = os.path.join(REPO, "wattlab_service", "static", "dl-9e58fc984c102e35")

COLUMNS = [
    "job_id", "saved_at", "mode", "source_key",
    "codec", "side", "preset_label", "preset_detail",
    "success", "duration_s", "output_size_mb",
    "bit_rate_kbps", "profile", "width", "height", "gop_avg", "has_b_frames",
    "w_base", "w_task", "delta_w", "delta_t_s", "delta_e_wh", "poll_count",
    "confidence_flag", "confidence_label", "confidence_positive", "confidence_method",
    "co2e_grams", "intensity_g_per_kwh",
    "vmaf",
    "cpu_mean_c", "cpu_peak_c", "gpu_mean_c", "gpu_peak_c",
    "gpu_ppt_mean_w", "gpu_ppt_peak_w",
    "owl_sha",
]


def cell_row(d, cell, codec, side):
    """Flatten one transcode 'cell' dict into a CSV row."""
    en = cell.get("energy", {}) or {}
    conf = en.get("confidence", {}) or {}
    co2 = en.get("co2e", {}) or {}
    inten = co2.get("intensity", {}) or {}
    st = cell.get("stream", {}) or {}
    th = cell.get("thermals", {}) or {}
    tr = cell.get("transcode", {}) or {}
    br = st.get("bit_rate_bps")
    return {
        "job_id": d.get("job_id"),
        "saved_at": d.get("saved_at"),
        "mode": d.get("mode"),
        "source_key": (d.get("source") or {}).get("key"),
        "codec": codec,
        "side": side.upper(),
        "preset_label": cell.get("preset_label"),
        "preset_detail": cell.get("preset_detail"),
        "success": tr.get("success"),
        "duration_s": tr.get("duration_s"),
        "output_size_mb": cell.get("output_size_mb"),
        "bit_rate_kbps": round(br / 1000, 1) if br else None,
        "profile": st.get("profile"),
        "width": st.get("width"),
        "height": st.get("height"),
        "gop_avg": st.get("gop_avg"),
        "has_b_frames": st.get("has_b_frames"),
        "w_base": en.get("w_base"),
        "w_task": en.get("w_task"),
        "delta_w": en.get("delta_w"),
        "delta_t_s": en.get("delta_t_s"),
        "delta_e_wh": en.get("delta_e_wh"),
        "poll_count": en.get("poll_count"),
        "confidence_flag": conf.get("flag"),
        "confidence_label": conf.get("label"),
        "confidence_positive": conf.get("confidence_positive"),
        "confidence_method": conf.get("method"),
        "co2e_grams": co2.get("grams"),
        "intensity_g_per_kwh": inten.get("g_per_kwh"),
        "vmaf": cell.get("vmaf"),
        "cpu_mean_c": th.get("cpu_mean"),
        "cpu_peak_c": th.get("cpu_peak"),
        "gpu_mean_c": th.get("gpu_mean"),
        "gpu_peak_c": th.get("gpu_peak"),
        "gpu_ppt_mean_w": th.get("gpu_ppt_mean_w"),
        "gpu_ppt_peak_w": th.get("gpu_ppt_peak_w"),
        "owl_sha": (d.get("owl_version") or {}).get("sha"),
    }


def in_window(d):
    try:
        ts = datetime.fromisoformat(d["saved_at"])
    except (KeyError, ValueError):
        return False
    return NIGHT_START <= ts <= NIGHT_END


def collect():
    rows = []
    for path in sorted(glob.glob(os.path.join(VIDEO_DIR, "*.json"))):
        with open(path) as fh:
            d = json.load(fh)
        if not in_window(d):
            continue
        if d.get("mode") == "all_codecs":
            for codec, sides in (d.get("codecs") or {}).items():
                for side in ("cpu", "gpu"):
                    if side in sides:
                        rows.append(cell_row(d, sides[side], codec, side))
        else:  # 'both' or single-side
            for side in ("cpu", "gpu"):
                if isinstance(d.get(side), dict):
                    cell = d[side]
                    # 'both'-mode cells have no stream block; derive codec from the label.
                    codec = (cell.get("stream") or {}).get("codec")
                    if not codec:
                        codec = (cell.get("preset_label") or "?").split()[0].lower()
                    rows.append(cell_row(d, cell, codec, side))
    return rows


def main():
    rows = collect()
    os.makedirs(os.path.dirname(OUT_CANONICAL), exist_ok=True)
    with open(OUT_CANONICAL, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} rows from {len({r['job_id'] for r in rows})} runs -> {OUT_CANONICAL}")
    if os.path.isdir(PUBLISH_DIR):
        import shutil
        pub = os.path.join(PUBLISH_DIR, "ForTania.csv")
        shutil.copy2(OUT_CANONICAL, pub)
        print(f"published -> {pub}")


if __name__ == "__main__":
    main()
