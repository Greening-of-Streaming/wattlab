#!/usr/bin/env python3
"""Summarise trials_<tag>.jsonl from gos2-ext-ssd-campaign. usage: analyse.py [run|smoke]"""
import json, statistics as st, sys
from collections import defaultdict
from pathlib import Path
OUT = Path("/srv/data/owl/campaign_2026-11-04_gos2_ext_ssd")
tag = sys.argv[1] if len(sys.argv) > 1 else "run"
T = [["phase A"]]
rows = [json.loads(l) for l in (OUT / f"trials_{tag}.jsonl").open()]
TV = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571}
def ci(v): return TV.get(len(v) - 1, 2.0) * st.stdev(v) / len(v) ** .5 if len(v) > 1 else float("nan")
def w(s, skip=0, drop_end=0, col=1):
    v = [x[col] for x in s[skip:len(s) - drop_end if drop_end else None] if x[col] is not None]
    return st.mean(v or [x[col] for x in s if x[col] is not None])
print("== A idle by disk state")
by = defaultdict(list); soc = defaultdict(list); out = defaultdict(list); gate = defaultdict(list)
for r in rows:
    if r["phase"] != "A": continue
    by[r["disk"]].append(w(r["samples"])); out[r["disk"]].append(w(r["samples"], col=2) - w(r["samples"]))
    gate[r["disk"]].append(min(r["cpu_idle"])); soc[r["disk"]].append(r.get("soc", {}))
for k, v in by.items():
    print(f"  {k:9} {st.mean(v):.3f} W ± {ci(v):.3f} (n={len(v)}) windows {[round(x, 3) for x in v]} self-draw {st.mean(out[k]):.3f} W cpu idle min {min(gate[k])}")
    print("     cluster", {c: round(st.mean(d[c] for d in soc[k] if c in d), 3) for c in soc[k][0]} if soc[k][0] else {})
if len(by) == 2:
    d = [a - b for a, b in zip(by["mounted"], by["ejected"])]
    print(f"  mounted - ejected {st.mean(d):.3f} W ± {ci(d):.3f}")
print("== B I/O: delta W over the 45 s baseline before each job, first 5 s of the job dropped")
b = defaultdict(list); e = defaultdict(list); mb = defaultdict(list); cpu = defaultdict(list); bw = defaultdict(list)
for r in rows:
    if r["phase"] != "B": continue
    k = (r["op"], r["rate"], r["disk"]); base = w(r["baseline"], skip=5)
    jw = w(r["samples"], skip=5, drop_end=1) - base
    j = r["job"]; b[k].append(jw); bw[k].append(base); mb[k].append(j["mb_s"]); cpu[k].append((j["cpu_user_s"] + j["cpu_sys_s"]) / j["secs"])
    e[k].append(jw * j["secs"] / (j["bytes"] / 1e9))
print(f"  {'op':5} {'rate':>5} {'disk':8} {'dW':>7} {'±CI':>6} {'base W':>7} {'MB/s':>7} {'J/GB':>7} {'cpu core':>8}")
for k in sorted(b, key=lambda x: (x[0], x[1] or 1e9, x[2])):
    print(f"  {k[0]:5} {k[1]:>5} {k[2]:8} {st.mean(b[k]):7.3f} {ci(b[k]):6.3f} {st.mean(bw[k]):7.3f} {st.mean(mb[k]):7.0f} {st.mean(e[k]):7.2f} {st.mean(cpu[k]):8.3f}")
print("== C encode, delta over the 90 s baseline before each")
c = defaultdict(list)
for r in rows:
    if r["phase"] != "C": continue
    tail = r["tail_s"]; s = r["samples"]; n = len(s) - tail
    enc = w(s, skip=3, drop_end=tail); base = w(r["baseline"], skip=5); tw = w(s[-tail:]) if tail else 0
    c[r["arm"]].append(dict(base=base, enc=enc, d=enc - base, T=n, de=(enc - base) * n / 3600, ge=enc * n / 3600, tail=tw - base, order=r["rep"]))
for arm, v in c.items():
    f = lambda k: [x[k] for x in v]
    print(f"  {arm:17} n={len(v)} base {st.mean(f('base')):.3f} W enc {st.mean(f('enc')):.3f} W dW {st.mean(f('d')):.3f} ± {ci(f('d')):.3f} T {st.mean(f('T')):.0f} s dE {st.mean(f('de')):.4f} ± {ci(f('de')):.4f} Wh gross {st.mean(f('ge')):.4f} Wh tail dW {st.mean(f('tail')):.3f}")
    print("     dW per run", [round(x, 3) for x in f("d")])
for a, bb in (("external", "internal"), ("internal_ejected", "internal")):
    if a in c and bb in c and len(c[a]) == len(c[bb]):
        d = [x["de"] - y["de"] for x, y in zip(c[a], c[bb])]
        print(f"  dE {a} - {bb}: {st.mean(d):+.4f} Wh ± {ci(d):.4f} ({100 * st.mean(d) / st.mean(x['de'] for x in c[bb]):+.1f} %)")
