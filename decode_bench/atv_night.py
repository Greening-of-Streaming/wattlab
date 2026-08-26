#!/usr/bin/env python3
"""Sequential Apple TV campaign through the OWL queue (CR-075, 2026-08-26):
for rep in 1..n, for each template: POST /decode/run (atv, headless mode —
the display is attached by hand and disclosed), wait for the job to finish,
run atv_watch.py alongside for anomalies. Rows are stamped with batch_id so
/decode/batches shows the campaign. Writes a line per job to --log.
Usage: atv_night.py --batch <hex> --n 3 --window 120 --templates loop_bbbiso_h264,... --log file"""
import argparse, json, subprocess, sys, time, urllib.request

BASE = "http://127.0.0.1:8000"


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "x-real-ip": "127.0.0.1"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def job(jid):
    return json.load(urllib.request.urlopen(f"{BASE}/decode/job/{jid}", timeout=10))


def main():
    p = argparse.ArgumentParser(); p.add_argument("--batch", required=True); p.add_argument("--n", type=int, default=3)
    p.add_argument("--window", type=int, default=120); p.add_argument("--templates", required=True); p.add_argument("--log", required=True)
    p.add_argument("--gap", type=int, default=20)
    a = p.parse_args(); tpls = [t for t in a.templates.split(",") if t]
    with open(a.log, "a") as lg:
        for rep in range(1, a.n + 1):
            for tpl in tpls:
                r = post("/decode/run", {"template": tpl, "devices": ["atv"], "mode": "headless",
                                         "window_s": a.window, "batch_id": a.batch})
                jid = r.get("job_id")
                line = f"{time.strftime('%H:%M:%S')} rep {rep} {tpl} → {r}"
                print(line, flush=True); lg.write(line + "\n"); lg.flush()
                if not jid:
                    time.sleep(30); continue
                w = subprocess.Popen([sys.executable, "/home/gos/wattlab/decode_bench/atv_watch.py", "--job", jid,
                                      "--out", f"/srv/data/owl/atv/watch_{jid}.jsonl", "--every", "15", "--hours", "0.3",
                                      "--idle_floor_w", "3.5"], stdout=open(f"/srv/data/owl/atv/watch_{jid}.log", "w"), stderr=subprocess.STDOUT)
                t0 = time.time()
                while time.time() - t0 < 900:
                    j = job(jid)
                    if j.get("status") in ("done", "error"):
                        break
                    time.sleep(10)
                res = j.get("result") or {}; sec = (res.get("devices") or {}).get("atv") or {}; rows = sec.get("rows") or []
                summ = [(rw.get("run"), rw.get("w_base"), rw.get("w_task"), rw.get("delta_w"), (rw.get("confidence") or {}).get("flag"), rw.get("alive_at_window_end"), rw.get("error")) for rw in rows]
                line = f"{time.strftime('%H:%M:%S')}   {jid} {j.get('status')} {j.get('error') or ''} {summ}"
                print(line, flush=True); lg.write(line + "\n"); lg.flush()
                try:
                    w.terminate()
                except Exception:
                    pass
                time.sleep(a.gap)
        lg.write(f"{time.strftime('%H:%M:%S')} ALL DONE\n")
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
