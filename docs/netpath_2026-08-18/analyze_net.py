#!/usr/bin/env python3
"""Morning analysis for the network-path campaign (CR-074, 2026-08-18→19). Emits markdown.
Gates: adb rows need PLAYING at mid-window + (alive flag or flat trace); ssh rows need no error.
Reports ΔW ± per-run 95 % CI half-width, n=1 unless repeated."""
import glob, json, statistics as st
from collections import defaultdict
BATCH = "20260818ae7ba7b0"
envs = [json.load(open(f)) for f in sorted(glob.glob("/home/gos/wattlab/results/decode/2026-08-19_*.json"))]
envs = [e for e in envs if e.get("batch_id") == BATCH]
R = defaultdict(list); lost = []
for e in envs:
    tpl = e["template"]
    for r in e["runs"]:
        dev = r["device"]; p = r.get("provenance") or {}
        w = r.get("raw_task_w") or []
        flat = len(w) >= 300 and abs(st.mean(w[-60:]) - st.mean(w[len(w)//3:2*len(w)//3])) <= 0.15
        ok = r.get("delta_w") is not None and not r.get("error")
        if dev in ("gtv", "firestick", "bbox"):
            ok = ok and p.get("playback_state_midwindow") == "PLAYING" and (r.get("alive_at_window_end") is True or flat)
        if not ok:
            lost.append(f"{tpl} {dev} {e['job_id']}: {r.get('error') or p.get('playback_state_midwindow')}"); continue
        ci = (r.get("confidence") or {}).get("ci_delta_w_95")
        R[(tpl, dev)].append({"dw": r["delta_w"], "hw": (ci[1]-ci[0])/2 if ci else None,
                              "flag": (r.get("confidence") or {}).get("flag"), "wb": r.get("w_base"),
                              "ifaces": p.get("ifaces_midwindow"), "job": e["job_id"]})
def cell(tpl, dev):
    rs = R.get((tpl, dev), [])
    if not rs: return "—"
    m = st.mean(x["dw"] for x in rs); hw = [x["hw"] for x in rs if x["hw"] is not None]
    return f"**{m:+.2f}** ±{st.mean(hw):.2f} {''.join(x['flag'] or '?' for x in rs)}" if hw else f"**{m:+.2f}**"
out = [f"### Network-path campaign — batch `{BATCH}` — {len(envs)} jobs, {sum(len(v) for v in R.values())} valid rows, {len(lost)} lost\n"]
out.append("ΔW above device idle (W), 600 s windows, BBB H.264 (hardware decode on the STBs, software on the Pi 400); ± = per-run 95 % CI half-width.\n")
out.append("**Pi 400 (software decode; ffmpeg -re → -f null; eth0 vs wlan0 vs local /dev/shm)**\n")
out.append("| bitrate | local file (no network) | Ethernet HTTP burst | Ethernet HTTP paced | Wi-Fi HTTP burst | Wi-Fi HTTP paced |")
out.append("|---|---|---|---|---|---|")
for kb in (1500, 8000, 20000):
    out.append(f"| {kb/1000:g} Mb/s | {cell(f'net_pi_local_b{kb}','pi400')} | {cell(f'net_b{kb}_burst','pi400')} | {cell(f'net_b{kb}_paced','pi400')} | {cell(f'net_pi_wifi_b{kb}_burst','pi400')} | {cell(f'net_pi_wifi_b{kb}_paced','pi400')} |")
out.append(f"\nEthernet 8 Mb/s burst with the Wi-Fi radio OFF (control): {cell('net_pi_eth_b8000_wifioff','pi400')}\n")
for dev, label in (("gtv", "Google TV (Ethernet, hardware decode)"), ("bbox", "Bbox 4K (Ethernet, hardware decode; idle drifts ±0.3 W)"), ("firestick", "Fire TV Stick (Wi-Fi only)")):
    out.append(f"\n**{label}**\n")
    out.append("| bitrate | HTTP burst | HTTP paced (1.25× rate) |")
    out.append("|---|---|---|")
    for kb in (1500, 8000, 20000):
        out.append(f"| {kb/1000:g} Mb/s | {cell(f'net_b{kb}_burst',dev)} | {cell(f'net_b{kb}_paced',dev)} |")
    if dev in ("gtv", "firestick"):
        out.append(f"\nLocal file 8 Mb/s (adb push, no network): {cell('net_local_b8000', dev)}\n")
out.append("\nInterfaces recorded mid-window on the Pi rows: " + "; ".join(sorted({f"{k[0]}: {x['ifaces']}" for k, v in R.items() if k[1]=='pi400' for x in v if x['ifaces']}))[:1500])
out.append("\nLost/excluded rows:\n" + "\n".join(f"- {l}" for l in lost))
md = "\n".join(out); open("/srv/data/owl/campaign_2026-08-18_netpath/analysis.md", "w").write(md + "\n"); print(md)
