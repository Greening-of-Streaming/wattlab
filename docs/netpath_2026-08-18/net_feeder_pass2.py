#!/usr/bin/env python3
"""Pass 2/3 for CR-074 (Ben, 2026-08-19 02:10): repeat the Ethernet arms on the boxes that
cannot switch interface tonight (GTV, Bbox) so tomorrow only their Wi-Fi arms remain, plus
the GTV local-file control. Waits for pass 1 (campaign_done) then posts 14 jobs to the same
batch. Keys are rep-aware (done_pass2.txt)."""
import json, time, sys
sys.path.insert(0, "/srv/data/owl/campaign_2026-08-18_netpath")
import net_feeder as nf
from pathlib import Path

DIR = nf.DIR; DONE = DIR / "done_pass2.txt"; OUT = nf.OUT
while not (DIR / "campaign_done").exists():
    time.sleep(60)
nf.log("pass2: pass 1 finished — starting Ethernet repeats on gtv+bbox (+ gtv local)")
done = set(DONE.read_text().split()) if DONE.exists() else set()
cells = []
for rep in (2, 3):
    for pace in ("burst", "paced"):
        for kb in nf.KB:
            cells.append((f"net_b{kb}_{pace}", ["gtv", "bbox"], rep))
    cells.append(("net_local_b8000", ["gtv"], rep))
for tpl, devs, rep in cells:
    key = f"{tpl}#r{rep}"
    if key in done: continue
    try:
        resp = nf.post_run(tpl, devs)
    except Exception as e:
        nf.log(f"POST failed {key}: {e}"); time.sleep(60)
        try: resp = nf.post_run(tpl, devs)
        except Exception as e2: nf.log(f"POST failed twice {key}: {e2}"); continue
    jid = resp["job_id"]; nf.log(f"{key} → {jid}")
    d = nf.poll(jid, nf.W + 900)
    if d is None: nf.log(f"{key} {jid} TIMEOUT"); continue
    summ = {}
    for r in (d.get("result") or {}).get("runs", []) or []:
        p = r.get("provenance") or {}
        summ[r["device"]] = {"dw": r.get("delta_w"), "flag": (r.get("confidence") or {}).get("flag"),
                             "mid": p.get("playback_state_midwindow"), "alive": r.get("alive_at_window_end")}
    OUT.open("a").write(json.dumps({"tpl": tpl, "rep": rep, "job": jid, "stage": d.get("stage"), "summary": summ, "t": time.time()}) + "\n")
    DONE.open("a").write(key + "\n")
    nf.log(f"{key} done: " + " · ".join(f"{k} {v['dw']} {v['flag'] or ''} {v['mid'] or ''}" for k, v in summ.items()))
    time.sleep(5)
nf.log("pass2 finished"); (DIR / "pass2_done").write_text(time.strftime("%F %T") + "\n")
