#!/usr/bin/env python3
"""Summarise atv_probe.py rows: per-codec device-total W and ΔW (mean ± range
over reps), liveness, confidence flags; optional summary CSV (DIGEST_SPEC).
Usage: atv_summary.py probe.jsonl [--csv out.csv]"""
import argparse, csv, json, statistics
from pathlib import Path

p = argparse.ArgumentParser(); p.add_argument("jsonl"); p.add_argument("--csv")
a = p.parse_args()
rows = [json.loads(l) for l in Path(a.jsonl).read_text().splitlines() if l.strip()]
by = {}
for r in rows:
    by.setdefault(r["codec"], []).append(r)
print(f"{'codec':6} {'n':>2} {'W_task mean':>11} {'range':>13} {'ΔW mean':>8} {'range':>13} {'base mean':>9} {'flags':>8}  liveness")
out = []
for codec in ("h264", "h265", "av1", "vp9"):
    rs = by.get(codec, [])
    if not rs:
        continue
    wt = [r["w_task"] for r in rs]; dw = [r["delta_w"] for r in rs]; wb = [r["w_base"] for r in rs]
    flags = "".join(r["confidence"].get("flag", "?")[:1] for r in rs)
    live = " ".join(f"{r['liveness']['playing_polls']}/{r['liveness']['polls']}" for r in rs)
    print(f"{codec:6} {len(rs):>2} {statistics.mean(wt):11.3f} {min(wt):6.3f}–{max(wt):6.3f} {statistics.mean(dw):+8.3f} {min(dw):+6.3f}–{max(dw):+6.3f} {statistics.mean(wb):9.3f} {flags:>8}  {live}")
    out.append({"codec": codec, "n": len(rs), "w_task_mean_w": round(statistics.mean(wt), 3),
                "w_task_min_w": min(wt), "w_task_max_w": max(wt),
                "delta_w_mean_w": round(statistics.mean(dw), 3), "delta_w_min_w": min(dw), "delta_w_max_w": max(dw),
                "w_base_mean_w": round(statistics.mean(wb), 3), "task_sd_mean_w": round(statistics.mean(r["task_sd"] for r in rs), 3),
                "confidence_flags": " ".join(r["confidence"].get("flag", "?") for r in rs),
                "playing_polls": " ".join(f"{r['liveness']['playing_polls']}/{r['liveness']['polls']}" for r in rs),
                "clip": rs[0]["clip"], "window_s": rs[0]["window_s"], "baseline_state": rs[0].get("baseline_state")})
print("\nper row:")
for r in rows:
    c = r["confidence"]
    print(f"  {r['codec']:5} #{r['rep']} base {r['w_base']:.3f} (sd {r['base_sd']:.3f}) task {r['w_task']:.3f} (sd {r['task_sd']:.3f}, {r['task_min']:.2f}–{r['task_max']:.2f}) Δ {r['delta_w']:+.3f} {c.get('flag')} p={c.get('confidence_positive', '')} · playing {r['liveness']['playing_polls']}/{r['liveness']['polls']} adv {r['liveness']['position_advances']}/{r['liveness']['position_pairs']}")
if a.csv and out:
    with open(a.csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    print("csv →", a.csv)
