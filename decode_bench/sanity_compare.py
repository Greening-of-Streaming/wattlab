#!/usr/bin/env python3
"""Compare fresh decode rows (a batch) against reference campaign cells:
same device/content/codec → Δ of w_task and delta_w vs the reference mean,
with the reference's own range as the yardstick. Usage:
sanity_compare.py <new_batch> <ref_batch> [<ref_batch> ...]"""
import json, sys, statistics, urllib.request

def batch(bid):
    req = urllib.request.Request(f"http://127.0.0.1:8000/decode/batch/{bid}.json", headers={"x-real-ip": "127.0.0.1"})
    return json.load(urllib.request.urlopen(req, timeout=20))

def cells(d):
    out = {}
    for key, xs in d["cells"].items():
        xs = [c for c in xs if not c.get("error") and c.get("delta_w") is not None]
        if not xs: continue
        dev, content, codec, mode = key.split("|")
        k = (dev, content.replace(" (iso-bitrate)", "").strip(), codec, mode or "headless")
        out[k] = {"n": len(xs), "task": statistics.mean(c["w_task"] for c in xs), "task_rng": (min(c["w_task"] for c in xs), max(c["w_task"] for c in xs)),
                  "dw": statistics.mean(c["delta_w"] for c in xs), "dw_rng": (min(c["delta_w"] for c in xs), max(c["delta_w"] for c in xs)),
                  "base": statistics.mean(c["w_base"] for c in xs), "win": xs[0].get("window_s")}
    return out

new = cells(batch(sys.argv[1])); refs = {}
for b in sys.argv[2:]:
    for k, v in cells(batch(b)).items():
        refs.setdefault(k, (b, v))
print(f"{'device':9} {'content':9} {'codec':5} | new task / Δ (win)        | ref task / Δ (n, win, ref batch)        | task diff | Δ diff | verdict")
for k in sorted(new):
    n = new[k]; r = refs.get(k)
    if not r:
        print(f"{k[0]:9} {k[1]:9} {k[2]:5} | {n['task']:.2f} / {n['dw']:+.2f} ({n['win']}) | no reference cell"); continue
    b, rv = r; td = n["task"] - rv["task"]; dd = n["dw"] - rv["dw"]
    tol = max(0.15, (rv["task_rng"][1] - rv["task_rng"][0]))     # ref spread or 0.15 W, whichever larger
    verdict = "OK" if abs(td) <= tol and abs(dd) <= max(0.2, rv["dw_rng"][1] - rv["dw_rng"][0] + 0.1) else "CHECK"
    print(f"{k[0]:9} {k[1]:9} {k[2]:5} | {n['task']:.2f} / {n['dw']:+.2f} ({n['win']}) | {rv['task']:.2f} / {rv['dw']:+.2f} (n={rv['n']}, {rv['win']}, {b[:8]}) | {td:+.2f} | {dd:+.2f} | {verdict}")
