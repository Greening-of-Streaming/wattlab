#!/usr/bin/env python3
"""Unmeasured scout for the MHV'27 VVC pilot: bitrate -> VMAF v0.6.1 + wall time per codec,
same commands as the metered grid (parity.build_cmd, 10-bit). No meter is read; nothing
here is an energy number. Outputs kept in OUT so the encode nearest VMAF 92 per codec
becomes the decode stream.
Usage: scout.py [--clip football_30s] CODEC KBPS [KBPS ...]   -> appends to scout.jsonl"""
import json, shlex, subprocess, sys, time
from pathlib import Path
REPO = Path("/home/gos/wattlab"); sys.path.insert(0, str(REPO / "wattlab_service"))
import parity, video, quality, settings as cfg

HERE = Path(__file__).resolve().parent
OUT = Path("/srv/data/owl/mhv27_vvc_pilot/scout"); OUT.mkdir(parents=True, exist_ok=True)
CLIPS = {"meridian_120s": parity.CLIPS["meridian_120s"],
         "football_30s": REPO / "test_content" / "football_35s.mp4"}   # LAB-INTERNAL source (pictures)
args = sys.argv[1:]
clip = "meridian_120s"
if args[0] == "--clip":
    clip, args = args[1], args[2:]
ref = parity.ensure_clip(CLIPS[clip], 30)
codec = args[0]
for kbps in map(int, args[1:]):
    out = OUT / (f"{codec}_{kbps}k.mp4" if clip == "meridian_120s" else f"{clip}_{codec}_{kbps}k.mp4")
    argv = video.apply_custom_cmd(parity.build_cmd(codec, "cpu", kbps, 1080, bit_depth=10), ref, out)
    t0 = time.time()
    p = subprocess.run(["/usr/bin/time", "-f", "TIME %e %P %M", "nice", "-n", "-5", *argv],
                       capture_output=True, text=True)
    wall = time.time() - t0
    tline = [l for l in p.stderr.splitlines() if l.startswith("TIME ")]
    cpu_pct = tline[-1].split()[2] if tline else None
    log_tail = [l for l in p.stderr.splitlines() if "vvenc" in l.lower() or "x265 [info]" in l or "Svt[info]" in l][:40]
    stream = video.probe_output_stream(out) or {}
    s = {**cfg.load(), "vmaf_model": "v0"}
    vmaf = video.compute_vmaf(out, ref, s=s)
    row = {"clip": clip, "codec": codec, "target_kbps": kbps, "rc": p.returncode, "wall_s": round(wall, 1),
           "cpu_pct": cpu_pct, "achieved_kbps": round((stream.get("bit_rate_bps") or 0) / 1000, 1),
           "vmaf_v061": vmaf, "vmaf_model": quality.vmaf_model_id(s), "file": str(out),
           "cmd": " ".join(shlex.quote(a) for a in argv), "enc_log": log_tail}
    print(json.dumps({k: row[k] for k in ("codec", "target_kbps", "rc", "wall_s", "cpu_pct", "achieved_kbps", "vmaf_v061")}), flush=True)
    with open(HERE / "scout.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
