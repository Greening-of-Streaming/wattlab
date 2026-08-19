#!/usr/bin/env python3
"""CR-074 daytime step (Ben on-site, 2026-08-19): after the Ethernet cable is pulled from a
box it re-appears on Wi-Fi with a NEW address. This script:
  1. sweeps the LAN for ADB (port 5555) hosts, identifies GTV / Bbox / Fire TV by model,
  2. writes `rig_target_overrides` to /settings (the rig follows within ~10 s),
  3. checks each target answers ADB and shows only wlan0 with an IPv4,
  4. runs the six Wi-Fi arms (3 bitrates × burst/paced) with n=3 on the requested devices
     into the same batch, plus (Fire TV) the local-file control.
Usage:  python3 wifi_day.py discover            # step 1 only, prints what it found
        python3 wifi_day.py run gtv bbox         # steps 1–4 for the named devices
        python3 wifi_day.py revert               # clear the overrides (cables back in)
"""
import json, os, subprocess, sys, time, urllib.request
sys.path.insert(0, "/srv/data/owl/campaign_2026-08-18_netpath")
import net_feeder as nf

ADB = "/srv/data/owl/decode-bench/tools/platform-tools/adb"
MODELS = {"Google TV Streamer": "gtv", "Bouygtel4K": "bbox", "AFTKRT": "firestick"}
BASE = "http://127.0.0.1:8000"

def sh(*a, timeout=25):
    return subprocess.run(list(a), capture_output=True, text=True, timeout=timeout).stdout

def discover():
    out = sh("nmap", "-p5555", "--open", "-oG", "-", "192.168.1.0/24", timeout=120)
    hosts = [l.split()[1] for l in out.splitlines() if "/open/" in l]
    found = {}
    for ip in hosts:
        sh(ADB, "connect", f"{ip}:5555", timeout=15)
        model = sh(ADB, "-s", f"{ip}:5555", "shell", "getprop", "ro.product.model").strip()
        ifaces = sh(ADB, "-s", f"{ip}:5555", "shell", "ip -o -4 addr show").strip().replace("\n", " ; ")
        auth = "unauthorized" in sh(ADB, "devices")
        for m, name in MODELS.items():
            if model.startswith(m):
                found[name] = {"target": f"{ip}:5555", "model": model, "ifaces": ifaces}
        print(f"{ip:16} {model:22} {ifaces[:90]}")
    return found

def set_overrides(ov):
    body = json.dumps({"rig_target_overrides": ov}).encode()
    req = urllib.request.Request(BASE + "/settings", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r: print("settings:", r.status)
    except Exception as e:
        print("settings POST failed:", e, "— falling back to editing settings.json")
        p = "/home/gos/wattlab/settings.json"; s = json.load(open(p)); s["rig_target_overrides"] = ov
        json.dump(s, open(p, "w"), indent=2)
    time.sleep(12)

def run(devs):
    found = discover()
    ov = {d: found[d]["target"] for d in devs if d in found}
    missing = [d for d in devs if d not in found]
    if missing: print("NOT FOUND on Wi-Fi (cable still in? box asleep? ADB unauthorized?):", missing)
    for d, t in ov.items():
        if "eth0" in found[d]["ifaces"] and "wlan0" not in found[d]["ifaces"]:
            print(f"⚠ {d} still shows eth0 only — cable not pulled? proceeding anyway")
    if not ov: return
    set_overrides(ov)
    st = json.load(urllib.request.urlopen(BASE + "/decode/status.json"))
    for d in ov: print(d, "rig state:", (st.get("devices") or {}).get(d, {}).get("state"))
    cells = []
    for rep in (1, 2, 3):
        for pace in ("burst", "paced"):
            for kb in nf.KB:
                cells.append((f"net_b{kb}_{pace}", list(ov), rep))
        if "firestick" in ov: cells.append(("net_local_b8000", ["firestick"], rep))
    done_p = nf.DIR / "done_wifi.txt"; done = set(done_p.read_text().split()) if done_p.exists() else set()
    for tpl, ds, rep in cells:
        key = f"{tpl}#wifi#r{rep}#{'-'.join(ds)}"
        if key in done: continue
        resp = nf.post_run(tpl, ds); jid = resp["job_id"]; nf.log(f"{key} → {jid}")
        d = nf.poll(jid, nf.W + 900)
        if d is None: nf.log(f"{key} TIMEOUT"); continue
        summ = {r["device"]: (r.get("delta_w"), (r.get("confidence") or {}).get("flag"),
                              (r.get("provenance") or {}).get("playback_state_midwindow"))
                for r in (d.get("result") or {}).get("runs", []) or []}
        nf.OUT.open("a").write(json.dumps({"tpl": tpl, "wifi": True, "rep": rep, "job": jid, "summary": summ, "t": time.time()}) + "\n")
        done_p.open("a").write(key + "\n"); nf.log(f"{key} done: {summ}")
    nf.log("wifi day feeder finished — remember: python3 wifi_day.py revert once the cables are back")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "discover"
    if cmd == "discover": discover()
    elif cmd == "revert": set_overrides({}); print("overrides cleared")
    elif cmd == "run": run(sys.argv[2:] or ["gtv", "bbox"])
