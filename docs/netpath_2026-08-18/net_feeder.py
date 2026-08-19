#!/usr/bin/env python3
"""Network-path campaign (2026-08-18 night, Ben's A1): does the connection method
change client power? Arms through OWL's /decode queue, one job at a time, batch
`20260818ne7pa7h0`:
  shared (gtv, firestick, bbox on their current interface + pi400 over Ethernet):
      3 bitrates × {burst, paced}                       6 jobs
  STB local-file control (gtv, firestick)              1 job
  Pi 400: Wi-Fi × 3 bitrates × {burst, paced}          6 jobs
          local /dev/shm × 3 bitrates (no network)     3 jobs
          Ethernet with Wi-Fi radio off (control)      1 job
Windows 600 s, n=1 (initial test). Between Pi jobs the feeder makes sure eth0 is
back (a crashed Wi-Fi arm would otherwise strand the .108 target).
"""
import json, subprocess, time, urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
DIR = Path("/srv/data/owl/campaign_2026-08-18_netpath")
DONE = DIR / "done.txt"; OUT = DIR / "results.jsonl"
BATCH = "20260818ae7ba7b0"
W = 600
KB = (1500, 8000, 20000)
PI_WIFI = "192.168.1.110"; PI_ETH = "192.168.1.108"

cells = []
for pace in ("burst", "paced"):
    for kb in KB:
        cells.append((f"net_b{kb}_{pace}", ["gtv", "firestick", "bbox", "pi400"]))
cells.append(("net_local_b8000", ["gtv", "firestick"]))
for pace in ("burst", "paced"):
    for kb in KB:
        cells.append((f"net_pi_wifi_b{kb}_{pace}", ["pi400"]))
for kb in KB:
    cells.append((f"net_pi_local_b{kb}", ["pi400"]))
cells.append(("net_pi_eth_b8000_wifioff", ["pi400"]))


def log(m): print(time.strftime("%F %T"), m, flush=True)

def post_run(tpl, devs):
    body = json.dumps({"template": tpl, "mode": "headless", "devices": devs, "window_s": W,
                       "cadence_s": 1, "calibrate": False, "batch_id": BATCH}).encode()
    req = urllib.request.Request(BASE + "/decode/run", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r: return json.load(r)

def poll(jid, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(BASE + f"/decode/job/{jid}", timeout=15) as r: d = json.load(r)
            if d.get("stage") in ("done", "error"): return d
        except Exception: pass
        time.sleep(15)
    return None

def pi_eth_ok():
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", f"nebul2@{PI_ETH}", "true"],
                       capture_output=True, timeout=20)
    return r.returncode == 0

def pi_heal():
    if pi_eth_ok(): return True
    log("Pi eth0 unreachable — restoring over Wi-Fi")
    subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", f"HostName={PI_WIFI}",
                    f"nebul2@{PI_WIFI}", "sudo nmcli dev connect eth0; sudo nmcli radio wifi on"],
                   capture_output=True, timeout=60)
    time.sleep(6)
    return pi_eth_ok()

def main():
    done = set(DONE.read_text().split()) if DONE.exists() else set()
    log(f"start: {len(cells)} cells, {len(done)} done, batch {BATCH}")
    for tpl, devs in cells:
        if tpl in done: continue
        if "pi400" in devs and not pi_heal():
            log(f"{tpl}: Pi 400 unreachable on both paths — dropping pi400 from this cell")
            devs = [d for d in devs if d != "pi400"]
            if not devs: continue
        try:
            resp = post_run(tpl, devs)
        except Exception as e:
            log(f"POST failed {tpl}: {e}"); time.sleep(60)
            try: resp = post_run(tpl, devs)
            except Exception as e2: log(f"POST failed twice {tpl}: {e2}"); continue
        jid = resp["job_id"]; log(f"{tpl} → {jid}")
        d = poll(jid, W + 900)
        if d is None: log(f"{tpl} {jid} TIMEOUT"); continue
        summ = {}
        for r in (d.get("result") or {}).get("runs", []) or []:
            p = r.get("provenance") or {}
            summ[r["device"]] = {"dw": r.get("delta_w"), "flag": (r.get("confidence") or {}).get("flag"),
                                 "mid": p.get("playback_state_midwindow"), "alive": r.get("alive_at_window_end"),
                                 "ifaces": p.get("ifaces_midwindow"), "err": r.get("error")}
        OUT.open("a").write(json.dumps({"tpl": tpl, "job": jid, "stage": d.get("stage"), "summary": summ, "t": time.time()}) + "\n")
        DONE.open("a").write(tpl + "\n")
        log(f"{tpl} done: " + " · ".join(f"{k} {v['dw']} {v['flag'] or ''} {v['mid'] or ''} {v['ifaces'] or ''}" for k, v in summ.items()))
        time.sleep(5)
    pi_heal()
    log("feeder finished"); (DIR / "campaign_done").write_text(time.strftime("%F %T") + "\n")

if __name__ == "__main__":
    main()
