#!/usr/bin/env python3
"""Per-cell summary of an OWL decode campaign (batch): device × content × codec
→ n, base/task/ΔW mean and range, flags, liveness. Optional CSV (DIGEST_SPEC).
Usage: batch_cells.py <batch_id> [--csv out.csv] [--device atv]"""
import argparse, csv, json, statistics, urllib.request

p = argparse.ArgumentParser(); p.add_argument("batch"); p.add_argument("--csv"); p.add_argument("--device")
a = p.parse_args()
req = urllib.request.Request(f"http://127.0.0.1:8000/decode/batch/{a.batch}.json", headers={"x-real-ip": "127.0.0.1"})
d = json.load(urllib.request.urlopen(req, timeout=20))
print(f"batch {a.batch} '{d.get('label') or ''}' cells={d['n_cells']} errors={d['n_errors']}")
out = []
for key in sorted(d["cells"]):
    dev, content, codec, mode = key.split("|")
    if a.device and dev != a.device: continue
    xs = [c for c in d["cells"][key] if not c.get("error") and c.get("delta_w") is not None]
    errs = [c for c in d["cells"][key] if c.get("error")]
    if not xs and not errs: continue
    wt = [c["w_task"] for c in xs]; dw = [c["delta_w"] for c in xs]; wb = [c["w_base"] for c in xs]
    row = {"device": dev, "content": content, "codec": codec, "mode": mode or "headless", "n": len(xs), "errors": len(errs),
           "window_s": xs[0].get("window_s") if xs else None,
           "w_base_mean_w": round(statistics.mean(wb), 3) if xs else None,
           "w_task_mean_w": round(statistics.mean(wt), 3) if xs else None, "w_task_min_w": min(wt) if xs else None, "w_task_max_w": max(wt) if xs else None,
           "w_task_sd_w": round(statistics.pstdev(wt), 3) if len(wt) > 1 else None,
           "delta_w_mean_w": round(statistics.mean(dw), 3) if xs else None, "delta_w_min_w": min(dw) if xs else None, "delta_w_max_w": max(dw) if xs else None,
           "flags": "".join(str(c.get("flag"))[:1] for c in xs), "alive_at_end": "".join("Y" if c.get("alive_at_end") else "n" for c in xs),
           "jobs": " ".join(c.get("job_id", "") for c in xs)}
    out.append(row)
    print(f"{dev:9} {content:24} {codec:6} n={row['n']}{'!'+str(len(errs)) if errs else ''} win={row['window_s']} base {row['w_base_mean_w']} task {row['w_task_mean_w']} ({row['w_task_min_w']}–{row['w_task_max_w']}) Δ {row['delta_w_mean_w']:+} ({row['delta_w_min_w']:+}–{row['delta_w_max_w']:+}) {row['flags']} alive {row['alive_at_end']}")
if a.csv and out:
    with open(a.csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    print("csv →", a.csv)
