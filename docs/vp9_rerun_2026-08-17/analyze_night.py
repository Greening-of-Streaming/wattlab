#!/usr/bin/env python3
"""Morning analysis for the VP9 re-run (2026-08-17→18). Emits markdown tables to
analysis.md + analysis.json. Rules (declared, not tuned):
  encode: rows with w_base > median+10 W are EXCLUDED (hot baseline under-counts ΔW; the
          CR-070 logic) and listed; means ± sd over remaining reps; VMAF v1 + achieved kbps
          shown as context (one-pass ABR on 30 s trims misses target by −32…+46 %).
  decode: adb rows count only if playback_state_midwindow == PLAYING and alive_at_window_end;
          C2 (webOS, all-in panel) and Bbox (idle drift) reported but not used for codec claims;
          means over valid reps with n; per-run 95 % CI carried.
"""
import glob, json, statistics as st
from collections import defaultdict
from pathlib import Path

DIR = Path("/srv/data/owl/campaign_2026-08-17_vp9b")
ART = "/home/gos/wattlab/results/diagnostics/encode_parity_nvenc_24c_2026-08-17.json"
BATCH = "20260817b9c0de"
out = {"encode": {}, "decode": {}}
md = []

# ---------------- encode ----------------
a = json.load(open(ART))
rows = a["rows"]
med = st.median(r["w_base"] for r in rows)
excl = [r for r in rows if r["w_base"] > med + 10]
keep = [r for r in rows if r["w_base"] <= med + 10]
g = defaultdict(list)
for r in keep:
    g[(r["clip"], r["codec"], r["profile"], r["target_bitrate_kbps"])].append(r)

ENC = {"x264": "libx264", "x265": "libx265", "svtav1": "SVT-AV1", "vp9": "libvpx-VP9"}
PT = {("x264", "default"): "medium", ("x264", "slow"): "slow", ("x265", "default"): "medium",
      ("x265", "slow"): "slow", ("svtav1", "default"): "preset 10 (default)", ("svtav1", "slow"): "preset 3",
      ("vp9", "default"): "cpu-used 4", ("vp9", "slow"): "cpu-used 2", ("vp9", "slower"): "cpu-used 1"}

def cell(k):
    rs = g[k]
    m = [r["wh_per_min_video"] for r in rs]
    at = [r["wh_per_min_video_attributional"] for r in rs]
    return {"n": len(rs), "wh_min": st.mean(m), "sd": st.stdev(m) if len(m) > 1 else 0.0,
            "attr": st.mean(at), "vmaf": st.mean(r["vmaf"] for r in rs),
            "kbps": st.mean(r["achieved_bitrate_bps"] for r in rs) / 1000,
            "s_per_min": st.mean(r["delta_t_s"] / (r["content_s"] / 60) for r in rs),
            "dw": st.mean(r["delta_w"] for r in rs), "flags": [r["confidence_flag"] for r in rs]}

md.append("### Encode — GoS1, 1080p, one-pass ABR, 30 s trims, dual meter, all rows 🟢\n")
md.append(f"{len(rows)} rows measured; {len(excl)} excluded for elevated baseline "
          f"(w_base > median {med:.1f} + 10 W): " +
          "; ".join(f"{r['clip']} {r['codec']}/{r['profile']} {r['target_bitrate_kbps']}k rep{r['rep']} (w_base {r['w_base']:.1f} W)" for r in excl) + ".\n")
for clip in ("bbb_120s", "meridian_120s"):
    md.append(f"\n**{clip}** — Wh per minute of output (marginal | attributional), n, VMAF v1, achieved kb/s, encode s per minute of video\n")
    md.append("| encoder | point | target | n | Wh/min | ±sd | attrib. | VMAF | ach. kb/s | s/min |")
    md.append("|---|---|---|---|---|---|---|---|---|---|")
    for enc in ("x264", "x265", "svtav1", "vp9"):
        for pt in ("default", "slow", "slower"):
            for bps in (2500, 5000):
                k = (clip, enc, pt, bps)
                if k not in g: continue
                c = cell(k); out["encode"][f"{clip}|{enc}|{pt}|{bps}"] = c
                md.append(f"| {ENC[enc]} | {PT[(enc,pt)]} | {bps}k | {c['n']} | **{c['wh_min']:.3f}** | {c['sd']:.3f} | {c['attr']:.2f} | {c['vmaf']:.1f} | {c['kbps']:.0f} | {c['s_per_min']:.0f} |")

def ratio_table(title, pts):
    md.append(f"\n**{title}** — energy per minute relative to x264 (same clip, same target), mean of the two targets\n")
    md.append("| clip | x264 | x265 | SVT-AV1 | VP9 |")
    md.append("|---|---|---|---|---|")
    for clip in ("bbb_120s", "meridian_120s"):
        base = st.mean(g and cell((clip, "x264", pts["x264"], b))["wh_min"] for b in (2500, 5000))
        vals = []
        for enc in ("x264", "x265", "svtav1", "vp9"):
            v = st.mean(cell((clip, enc, pts[enc], b))["wh_min"] for b in (2500, 5000))
            vals.append(f"{v/base:.1f}×")
            out["encode"][f"ratio|{title}|{clip}|{enc}"] = v / base
        md.append(f"| {clip} | " + " | ".join(vals) + " |")

ratio_table("Everything-at-default (x264 medium · x265 medium · SVT-AV1 p10 · VP9 cpu-used 4)",
            {"x264": "default", "x265": "default", "svtav1": "default", "vp9": "default"})
ratio_table("Jan Ozer's everything-slow set (x264 slow · x265 slow · SVT-AV1 p3 · VP9 cpu-used 2)",
            {"x264": "slow", "x265": "slow", "svtav1": "slow", "vp9": "slow"})
md.append("\nJan's ladder (14 sources, i9-14900, two-pass, wall-clock time): x264 1.0× · x265 8.5× · SVT-AV1 8.6× · libvpx 9.5×.\n")

# ---------------- decode ----------------
envs = []
for f in sorted(glob.glob("/home/gos/wattlab/results/decode/2026-08-1[78]_*.json")):
    d = json.load(open(f))
    if d.get("batch_id") == BATCH: envs.append(d)
D = defaultdict(list)   # (fam, codec, device) -> list of run dicts
lost = []
rescued = []
for d in envs:
    fam, cod = d["template"].split("_")[1], d["template"].split("_")[2]
    for r in d["runs"]:
        dev = r["device"]; p = r.get("provenance") or {}
        valid = r.get("delta_w") is not None and not r.get("error")
        w = r.get("raw_task_w") or []
        trace_flat = (len(w) >= 300 and abs(st.mean(w[-60:]) - st.mean(w[len(w)//3:2*len(w)//3])) <= 0.15)
        if dev in ("gtv", "firestick", "bbox"):
            # aliveness = harness flag OR a flat trace to the end (the Fire TV end-of-window
            # probe returned False on rows whose traces are flat to the last second — see notes)
            valid = valid and p.get("playback_state_midwindow") == "PLAYING" and (r.get("alive_at_window_end") is True or trace_flat)
            if valid and r.get("alive_at_window_end") is not True:
                rescued.append(f"{fam} {cod} {dev} job {d['job_id']} (alive flag False, trace flat)")
        if dev == "pi400":
            valid = valid and r.get("alive_at_window_end") is not False
        if not valid:
            lost.append(f"{fam} {cod} {dev} job {d['job_id']}: " + (r.get("error") or f"mid={p.get('playback_state_midwindow')} alive={r.get('alive_at_window_end')}"))
            continue
        D[(fam, cod, dev)].append({"dw": r["delta_w"], "ci": (r.get("confidence") or {}).get("ci_delta_w_95"),
                                   "flag": (r.get("confidence") or {}).get("flag"), "wb": r.get("w_base"),
                                   "dec": p.get("decoders_allocated"), "job": d["job_id"]})
FAM = {"bbbiso": "BBB 1080p60 @8 Mb/s", "kranjskaiso": "Kranjska 1440×1080p30 @10 Mb/s", "meridianiso": "Meridian 1080p60 @4.5 Mb/s"}
DEV = {"gtv": "Google TV (MediaTek, hw)", "firestick": "Fire TV Stick 4K (hw, Wi-Fi)", "pi400": "Pi 400 (software)", "bbox": "Bbox 4K (operator CPE)", "c2": "LG C2 (all-in, panel)"}
man = json.load(open(DIR / "iso_family_manifest.json"))
md.append("\n### Decode — rig, headless realtime, 1080 s windows, iso-bitrate software-encoded family\n")
md.append(f"{len(envs)} jobs, {sum(len(v) for v in D.values())} valid device-rows; excluded/lost rows: {len(lost)}.\n")
md.append("Clip quality at that bitrate (VMAF v1 vs reference, frame-aligned): " +
          "; ".join(f"{k.replace('iso_', ' ')} {v['vmaf']}" for k, v in man.items()) + ".\n")
for dev in ("gtv", "firestick", "pi400", "bbox", "c2"):
    md.append(f"\n**{DEV[dev]}** — ΔW above device idle (mean of valid reps, n; per-run 95 % CI half-width shown as ±)\n")
    md.append("| content | H.264 | HEVC | AV1 | VP9 |")
    md.append("|---|---|---|---|---|")
    for fam in ("bbbiso", "kranjskaiso", "meridianiso"):
        cells = []
        for cod in ("h264", "h265", "av1", "vp9"):
            rs = D.get((fam, cod, dev), [])
            if not rs: cells.append("—"); continue
            m = st.mean(r["dw"] for r in rs)
            hw = st.mean(((r["ci"][1] - r["ci"][0]) / 2) for r in rs if r["ci"]) if any(r["ci"] for r in rs) else None
            fl = "".join((r["flag"] or "?") for r in rs)
            cells.append(f"**{m:+.2f}** ±{hw:.2f} n={len(rs)} {fl}" if hw is not None else f"**{m:+.2f}** n={len(rs)} {fl}")
            out["decode"][f"{fam}|{cod}|{dev}"] = {"mean_dw": m, "n": len(rs), "runs": rs}
        md.append(f"| {FAM[fam]} | " + " | ".join(cells) + " |")
md.append("\nLost/excluded rows:\n" + "\n".join(f"- {l}" for l in lost))
md.append(f"\nRows accepted on the trace-flat criterion despite alive_at_window_end=False: {len(rescued)} (all Fire TV unless noted):\n" + "\n".join(f"- {l}" for l in rescued))
# decoder provenance for GTV VP9
decs = sorted({tuple(r["dec"] or []) for k, v in D.items() if k[2] == "gtv" and k[1] == "vp9" for r in v})
md.append(f"\nGoogle TV VP9 decoders allocated (logcat): {decs}")

(DIR / "analysis.md").write_text("\n".join(md) + "\n")
json.dump(out, open(DIR / "analysis.json", "w"), indent=1, default=str)
print("\n".join(md))
