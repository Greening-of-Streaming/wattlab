import glob, json, statistics as st
from collections import defaultdict
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
B="20260818ae7ba7b0"; R=defaultdict(list)
for f in sorted(glob.glob("/home/gos/wattlab/results/decode/2026-08-19_*.json")):
    e=json.load(open(f))
    if e.get("batch_id")!=B: continue
    for r in e["runs"]:
        p=r.get("provenance") or {}; w=r.get("raw_task_w") or []
        flat=len(w)>=300 and abs(st.mean(w[-60:])-st.mean(w[len(w)//3:2*len(w)//3]))<=0.15
        ok=r.get("delta_w") is not None and not r.get("error")
        if r["device"] in ("gtv","firestick","bbox"): ok = ok and p.get("playback_state_midwindow")=="PLAYING" and (r.get("alive_at_window_end") is True or flat)
        if not ok: continue
        dev=r["device"]; t=e["template"]; ts=e["saved_at"]
        if dev=="pi400":
            iface = "wifi" if "pi_wifi" in t else ("local" if "pi_local" in t else "eth")
            if "wifioff" in t: iface="eth_radiooff"
        elif dev=="firestick": iface = "local" if "net_local" in t else "wifi"
        else: iface = "local" if "net_local" in t else ("wifi" if ts >= "2026-08-19T09:45" else "eth")
        kb = 8000 if "net_local" in t else int(t.split("_b")[1].split("_")[0])
        pace = "paced" if t.endswith("paced") else ("burst" if t.endswith("burst") else "local")
        R[(dev,iface,kb,pace)].append(r["delta_w"])
def m(dev,iface,kb,pace):
    v=R.get((dev,iface,kb,pace)); return (st.mean(v), (st.stdev(v) if len(v)>1 else 0), len(v)) if v else (None,0,0)
DEV=[("gtv","Google TV (hw decode)"),("bbox","Bbox 4K operator box (hw decode)"),("firestick","Fire TV Stick (hw decode, Wi-Fi only)"),("pi400","Raspberry Pi 400 (software decode)")]
CASES=[(1500,"burst"),(1500,"paced"),(8000,"burst"),(8000,"paced"),(20000,"burst"),(20000,"paced")]
ETH="#4a7fb5"; WIFI="#e0832a"; LOC="#7a7a7a"
plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False})
fig,axes=plt.subplots(2,2,figsize=(14,9.5)); axes=axes.flat
for ax,(dev,label) in zip(axes,DEV):
    x=np.arange(len(CASES)); wdt=0.38
    eth=[m(dev,"eth",kb,pc) for kb,pc in CASES]; wifi=[m(dev,"wifi",kb,pc) for kb,pc in CASES]
    if any(v[0] is not None for v in eth):
        ax.bar(x-wdt/2,[v[0] or 0 for v in eth],wdt,yerr=[v[1] for v in eth],color=ETH,label="Ethernet",capsize=3)
    ax.bar(x+wdt/2,[v[0] or 0 for v in wifi],wdt,yerr=[v[1] for v in wifi],color=WIFI,label="Wi-Fi",capsize=3)
    for i,(e_,w_) in enumerate(zip(eth,wifi)):
        if e_[0] is not None: ax.text(i-wdt/2,e_[0]+0.03,f"{e_[0]:.2f}",ha="center",fontsize=8,color=ETH)
        if w_[0] is not None: ax.text(i+wdt/2,w_[0]+0.03,f"{w_[0]:.2f}",ha="center",fontsize=8,color=WIFI)
    loc=m(dev,"local",8000,"local")
    top=max([v[0] or 0 for v in eth+wifi]+[loc[0] or 0])*1.3+0.05
    if loc[0] is not None:
        ax.axhline(loc[0],color=LOC,ls="--",lw=1)
        ax.text(-0.45,top*0.93,f"— — local file, no network: {loc[0]:.2f} W (8 Mb/s)",fontsize=8,color=LOC,va="top")
    ax.set_xticks(x); ax.set_xticklabels([f"{kb/1000:g} Mb/s\n{pc}" for kb,pc in CASES],fontsize=9)
    ax.set_ylabel("ΔW above idle (W)"); ax.set_title(label,fontsize=11,loc="left",fontweight="bold")
    ax.set_ylim(0,top)
    n_e=max([v[2] for v in eth] or [0]); n_w=max([v[2] for v in wifi] or [0])
    ax.text(0.99,0.97,f"n = {n_e or '—'} Ethernet · {n_w} Wi-Fi",transform=ax.transAxes,ha="right",va="top",fontsize=8,color="#555")
axes[0].legend(loc="upper left",bbox_to_anchor=(0,0.9),frameon=False)
fig.suptitle("Connection method vs device power — same BBB H.264 clip at three bitrates, unpaced (burst) and server-paced, 600 s windows\nOWL bench · batch 20260818ae7ba7b0 · 2026-08-18/19 · error bars = sd over repeats (Pi 400 n=1)",fontsize=11)
fig.tight_layout(rect=(0,0,1,0.94)); fig.savefig("netpath_detail.png",dpi=160)
fig2,ax=plt.subplots(figsize=(9,4.8)); labels=[]; E=[]; W=[]; Eerr=[]; Werr=[]
for dev,label in DEV:
    ev=[m(dev,"eth",kb,pc)[0] for kb,pc in CASES if m(dev,"eth",kb,pc)[0] is not None]
    wv=[m(dev,"wifi",kb,pc)[0] for kb,pc in CASES if m(dev,"wifi",kb,pc)[0] is not None]
    labels.append(label.split(" (")[0]); E.append(st.mean(ev) if ev else 0); W.append(st.mean(wv) if wv else 0)
    Eerr.append(st.stdev(ev) if len(ev)>1 else 0); Werr.append(st.stdev(wv) if len(wv)>1 else 0)
both=[i for i,(dev,_) in enumerate(DEV) if dev!="firestick"]
labels.append("All devices with both\n(GTV, Bbox, Pi 400)"); E.append(st.mean([E[i] for i in both])); W.append(st.mean([W[i] for i in both])); Eerr.append(0); Werr.append(0)
x=np.arange(len(labels)); wdt=0.38
ax.bar(x-wdt/2,E,wdt,yerr=Eerr,color=ETH,label="Ethernet (mean of the 6 sub-cases)",capsize=3)
ax.bar(x+wdt/2,W,wdt,yerr=Werr,color=WIFI,label="Wi-Fi (mean of the 6 sub-cases)",capsize=3)
for i in range(len(labels)):
    if E[i]: ax.text(i-wdt/2,E[i]+0.03,f"{E[i]:.2f}",ha="center",fontsize=9,color=ETH)
    ax.text(i+wdt/2,W[i]+0.03,f"{W[i]:.2f}",ha="center",fontsize=9,color=WIFI)
    if E[i]: ax.text(i,max(E[i],W[i])+0.2,f"Wi-Fi +{W[i]-E[i]:.2f} W",ha="center",fontsize=10,fontweight="bold",color="#333")
    else: ax.text(i,W[i]+0.2,"(no Ethernet port)",ha="center",fontsize=9,color="#777")
ax.set_xticks(x); ax.set_xticklabels(labels,fontsize=9); ax.set_ylabel("ΔW above idle (W)"); ax.legend(frameon=False,loc="upper left")
ax.set_title("Ethernet vs Wi-Fi — average extra power while playing, per device and overall\n(averaged over 1.5 / 8 / 20 Mb/s × burst/paced; one content (BBB); Fire TV is Wi-Fi only)",fontsize=11,loc="left")
ax.set_ylim(0,max(W)*1.4); fig2.tight_layout(); fig2.savefig("netpath_summary.png",dpi=160)
json.dump({"per_device":{l:{"eth":e,"wifi":w} for l,e,w in zip(labels,E,W)}}, open("netpath_summary.json","w"), indent=1)
print("charts ok", {l:(round(e,2),round(w,2)) for l,e,w in zip(labels,E,W)})
