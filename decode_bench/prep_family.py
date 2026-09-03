#!/usr/bin/env python3
"""prep_family.py — build a decode-rig content family from a long master.

One command turns a continuous master (ProRes/H.264, any resolution ≥ 1080p)
into everything the rig's templates expect for a family `<fam>` (CR-081,
2026-09-03; generalises Tania's `docs/vp9_rerun_2026-08-17/prep_iso_family.py`):

  1. `<fam>_1080p_ref.mov`  — 120 s excerpt, 1920×1080, ProRes 422 HQ, the
     scoring reference (same construction as `bbb_1080p_ref.mov`, r12).
  2. `<fam>_{h264,h265,av1}.mp4` — the **matched-VMAF NVENC catalogue clips**:
     for each codec the bitrate is searched until VMAF v1 vs the ref lands in
     [target−0.5, target+1.0] (target 92.5 → the "~92–93" of the existing
     bbb/meridian/kranjska families); CBR, GOP 120, source audio as AAC 128k.
  3. `<fam>_<codec>_{6,20,60}min.mp4` — stream-copy concat ×3/×10/×30 (the
     loop_<fam>_<codec> templates; loop validity measured 2026-09-03, doc §5h).
  4. `<fam>iso_{h264,h265,av1}_20min.mp4` + `<fam>iso_vp9_20min.webm` — the
     iso-bitrate SOFTWARE family at the H.264 catalogue bitrate (capped for
     the Pi 400 tmpfs ceiling), two-pass ABR, GOP 120, silent audio, ×10.
Every clip is VMAF-scored and written to a manifest with the model id.

Resumable (skips outputs that exist). GPU encodes are quick; the software
iso family is the slow part (≈ 15–40 min for one content). Run from anywhere:

  python3 prep_family.py --master /srv/data/owl/test_content/x.mov --family skate --start 30
"""
import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/gos/wattlab/wattlab_service")
import quality  # noqa: E402

FF = "/usr/local/bin/ffmpeg-master"
STREAMS = Path("/srv/data/owl/decode-bench/streams")
NICE = ["nice", "-n", "19"]
CODECS = ("h264", "h265", "av1")
SEED_KBPS = {"h264": 8000, "h265": 6000, "av1": 4000}
VP9_COMMON = ["-row-mt", "1", "-tile-columns", "3", "-threads", "16",
              "-auto-alt-ref", "1", "-lag-in-frames", "25", "-profile:v", "0",
              "-deadline", "good", "-cpu-used", "2"]


def log_run(cmd, log):
    with open(log, "a") as fh:
        fh.write("\n$ " + " ".join(shlex.quote(str(c)) for c in cmd) + "\n")
        fh.flush()
        r = subprocess.run([str(c) for c in cmd], stdout=fh, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(f"exit {r.returncode}: {' '.join(str(c) for c in cmd[:6])} …  (see {log})")


def probe(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
        "format=duration,bit_rate,size:stream=codec_name,codec_type,width,height,r_frame_rate,pix_fmt,profile",
        "-of", "json", str(path)], text=True)
    return json.loads(out)


def nvenc_args(codec, kbps):
    common = ["-rc", "cbr", "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps*2}k",
              "-g", "120", "-pix_fmt", "yuv420p", "-preset", "p5"]
    if codec == "h264":
        return ["-c:v", "h264_nvenc", "-profile:v", "high", "-bf", "2"] + common
    if codec == "h265":
        return ["-c:v", "hevc_nvenc", "-profile:v", "main", "-tag:v", "hvc1", "-bf", "2"] + common
    if codec == "av1":
        return ["-c:v", "av1_nvenc"] + common
    raise ValueError(codec)


def sw_args(codec, kbps, passno, logbase):
    g = ["-g", "120", "-pix_fmt", "yuv420p", "-b:v", f"{kbps}k",
         "-pass", str(passno), "-passlogfile", logbase]
    if codec == "h264":
        return ["-c:v", "libx264", "-preset", "medium", "-profile:v", "high",
                "-x264-params", "scenecut=0:open_gop=0"] + g
    if codec == "h265":
        return ["-c:v", "libx265", "-preset", "medium", "-profile:v", "main", "-tag:v", "hvc1",
                "-x265-params", "scenecut=0:open-gop=0"] + g
    if codec == "av1":
        return ["-c:v", "libsvtav1", "-preset", "6", "-svtav1-params", "scd=0"] + g
    if codec == "vp9":
        return ["-c:v", "libvpx-vp9"] + VP9_COMMON + g
    raise ValueError(codec)


def concat(parts_file, n, out, log):
    lst = out.with_suffix(".concat.txt")
    lst.write_text("".join(f"file '{parts_file}'\n" for _ in range(n)))
    tmp = out.with_name("part_" + out.name)
    log_run(NICE + [FF, "-y", "-v", "warning", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", tmp], log)
    tmp.rename(out)
    lst.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--master", required=True)
    ap.add_argument("--family", required=True, help="family key, [a-z0-9]+ (templates: loop_<fam>_<codec>, <fam>iso_<codec>)")
    ap.add_argument("--start", type=float, default=30.0, help="excerpt start in the master (s)")
    ap.add_argument("--duration", type=float, default=120.0)
    ap.add_argument("--vmaf-target", type=float, default=92.5)
    ap.add_argument("--iso-cap", type=int, default=12000, help="kbps ceiling for the iso family (Pi 400 tmpfs)")
    ap.add_argument("--skip-iso", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    fam = a.family
    assert fam.isalnum() and fam.islower(), "family key must be [a-z0-9]+"
    master = Path(a.master)
    assert master.exists(), master
    work = Path(f"/srv/data/owl/family_{fam}")
    work.mkdir(exist_ok=True)
    log = work / "prep.log"
    man_p = work / "manifest.json"
    man = json.loads(man_p.read_text()) if man_p.exists() else {}
    man.setdefault("_source", {"master": str(master), "excerpt_start_s": a.start,
                               "excerpt_s": a.duration, "built": time.strftime("%F %T"),
                               "vmaf_target": a.vmaf_target, "vmaf_model": quality.vmaf_model_id()})
    t0 = time.time()
    say = lambda m: print(f"[{time.time()-t0:6.0f}s] {m}", flush=True)
    if a.dry_run:
        print(json.dumps(man["_source"], indent=1)); print("work:", work); return

    # 1. reference + audio
    ref = work / f"{fam}_1080p_ref.mov"
    aud = work / f"{fam}_audio_aac.m4a"
    if not ref.exists():
        say("1080p ProRes reference …")
        log_run(NICE + [FF, "-y", "-v", "warning", "-ss", a.start, "-t", a.duration, "-i", master, "-an",
                        "-vf", "scale=1920:1080:flags=lanczos", "-c:v", "prores_ks", "-profile:v", "3", ref], log)
    if not aud.exists():
        say("audio → AAC 128k …")
        log_run(NICE + [FF, "-y", "-v", "warning", "-ss", a.start, "-t", a.duration, "-i", master, "-vn",
                        "-c:a", "aac", "-b:a", "128k", "-ac", "2", aud], log)
    man["_source"]["reference"] = str(ref)

    # 2. matched-VMAF NVENC catalogue clips
    def score(clip):
        """VMAF v1 via OWL's scorer. WebM (VP9) goes through a timebase-
        normalised graph: WebM's 1 ms timebase mis-pairs frames when libvmaf
        pairs by timestamp and under-scores by 10+ points (S65 lesson; the
        football VP9 clip read 80.4 raw vs 94.0 normalised, 2026-09-03)."""
        clip = Path(clip)
        if clip.suffix != ".webm":
            return quality.compute_vmaf(clip, ref)
        import tempfile, os
        s = quality.cfg.load()
        model_opt, _ = quality._resolve_model(s, "hd")
        nt = int(s.get("vmaf_n_threads", 12) or 12)
        fps = probe(ref)["streams"][0]["r_frame_rate"]
        fd, vlog = tempfile.mkstemp(prefix="owl_vmaf_", suffix=".json"); os.close(fd)
        lavfi = (f"[0:v]settb=1/({fps}),setpts=N,format=yuv420p[d];"
                 f"[1:v]settb=1/({fps}),setpts=N,format=yuv420p[r];"
                 f"[d][r]libvmaf=n_threads={nt}:model={model_opt}:log_fmt=json:log_path={vlog}")
        subprocess.run([quality._scoring_bin(s), "-y", "-i", str(clip), "-i", str(ref),
                        "-lavfi", lavfi, "-f", "null", "-"], capture_output=True, text=True, timeout=900)
        v = quality._parse_vmaf_log(Path(vlog)); os.unlink(vlog)
        return v

    for codec in CODECS:
        key = f"{fam}_{codec}"
        final = STREAMS / f"{key}.mp4"
        if final.exists() and man.get(key, {}).get("vmaf") is not None:
            continue
        tried = man.get(key, {}).get("search", {})
        tried = {int(k): v for k, v in tried.items()}
        kbps = SEED_KBPS[codec]
        lo, hi = a.vmaf_target - 0.5, a.vmaf_target + 1.0
        chosen = None
        for _ in range(7):
            kbps = int(round(kbps / 100.0)) * 100
            if kbps not in tried:
                cand = work / f"{key}_{kbps}k.mp4"
                if not cand.exists():
                    say(f"{key}: encode {kbps}k …")
                    log_run(NICE + [FF, "-y", "-v", "warning", "-i", ref, "-an"] + nvenc_args(codec, kbps) + [cand], log)
                say(f"{key}: vmaf {kbps}k …")
                v = score(cand)
                tried[kbps] = v
                man.setdefault(key, {})["search"] = {str(k): tried[k] for k in sorted(tried)}
                man_p.write_text(json.dumps(man, indent=1))
                say(f"{key}: {kbps}k → VMAF {v}")
            v = tried[kbps]
            if v is None:
                raise RuntimeError(f"VMAF failed for {key} @ {kbps}k")
            if lo <= v <= hi:
                chosen = kbps; break
            # bracket: step by the ratio of the miss, damped
            step = 1.35 if abs(v - a.vmaf_target) > 3 else 1.15
            kbps = kbps * step if v < lo else kbps / step
        if chosen is None:
            ok = [k for k, v in tried.items() if v is not None and v >= lo]
            chosen = min(ok) if ok else max(tried)
        cand = work / f"{key}_{chosen}k.mp4"
        say(f"{key}: chosen {chosen}k (VMAF {tried[chosen]}) → {final.name}")
        log_run(NICE + [FF, "-y", "-v", "warning", "-i", cand, "-i", aud, "-map", "0:v", "-map", "1:a",
                        "-c", "copy", "-shortest", "-movflags", "+faststart", final], log)
        pr = probe(final)
        vs = next(s for s in pr["streams"] if s.get("width"))
        man[key] = {"family": fam, "codec": codec, "kbps": chosen, "vmaf": tried[chosen],
                    "vmaf_model": quality.vmaf_model_id(), "search": {str(k): tried[k] for k in sorted(tried)},
                    "clip": str(final), "achieved_kbps": round(int(pr["format"]["bit_rate"]) / 1000),
                    "duration_s": round(float(pr["format"]["duration"]), 2),
                    "video": {k: vs.get(k) for k in ("codec_name", "profile", "width", "height", "r_frame_rate", "pix_fmt")},
                    "encoder": {"h264": "h264_nvenc p5 high", "h265": "hevc_nvenc p5 main", "av1": "av1_nvenc p5"}[codec],
                    "rate_control": "CBR, GOP 120", "audio": "source audio AAC 128k"}
        man_p.write_text(json.dumps(man, indent=1))

    # 3. loops
    for codec in CODECS:
        key = f"{fam}_{codec}"
        src = STREAMS / f"{key}.mp4"
        for n, tag in ((3, "6min"), (10, "20min"), (30, "60min")):
            out = STREAMS / f"{key}_{tag}.mp4"
            if out.exists():
                continue
            say(f"concat ×{n} → {out.name} …")
            concat(src, n, out, log)
            pr = probe(out)
            man[key].setdefault("loops", {})[tag] = {"file": str(out), "duration_s": round(float(pr["format"]["duration"]), 1),
                                                    "size_gb": round(int(pr["format"]["size"]) / 1e9, 3)}
            man_p.write_text(json.dumps(man, indent=1))

    # 4. iso-bitrate software family at the H.264 catalogue bitrate (capped)
    if not a.skip_iso:
        iso_kbps = min(man[f"{fam}_h264"]["kbps"], a.iso_cap)
        for codec in ("h264", "h265", "av1", "vp9"):
            ext = "webm" if codec == "vp9" else "mp4"
            key = f"{fam}iso_{codec}"
            clip = work / f"{key}_120s.{ext}"
            loop = STREAMS / f"{key}_20min.{ext}"
            if not clip.exists():
                say(f"{key}: two-pass software encode @{iso_kbps}k …")
                base = ["-y", "-v", "warning", "-i", ref, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
                logbase = str(work / f"pass_{key}")
                log_run(NICE + [FF] + base + ["-map", "0:v", "-an"] + sw_args(codec, iso_kbps, 1, logbase) + ["-f", "null", "-"], log)
                auda = ["-c:a", "libopus", "-b:a", "128k"] if ext == "webm" else ["-c:a", "aac", "-b:a", "128k"]
                log_run(NICE + [FF] + base + ["-map", "0:v", "-map", "1:a", "-shortest"] + sw_args(codec, iso_kbps, 2, logbase) + auda + [clip], log)
            if man.get(key, {}).get("vmaf") is None:
                say(f"{key}: vmaf …")
                v = score(clip)
                pr = probe(clip)
                vs = next(s for s in pr["streams"] if s.get("width"))
                man[key] = {"family": f"{fam}iso", "codec": codec, "target_kbps": iso_kbps, "vmaf": v,
                            "vmaf_model": quality.vmaf_model_id(), "clip_120s": str(clip),
                            "achieved_kbps": round(int(pr["format"]["bit_rate"]) / 1000),
                            "video": {k: vs.get(k) for k in ("codec_name", "width", "height", "r_frame_rate")},
                            "encoder": {"h264": "libx264 medium", "h265": "libx265 medium",
                                        "av1": "libsvtav1 preset 6", "vp9": "libvpx-vp9 good cpu-used 2"}[codec],
                            "rate_control": "two-pass ABR, GOP 120",
                            "audio": "silent Opus 128k (WebM)" if ext == "webm" else "silent AAC 128k"}
                man_p.write_text(json.dumps(man, indent=1))
                say(f"{key}: VMAF {v}")
            if not loop.exists():
                say(f"concat ×10 → {loop.name} …")
                concat(clip, 10, loop, log)
                pr = probe(loop)
                man[key]["loop_clip"] = str(loop)
                man[key]["loop_duration_s"] = round(float(pr["format"]["duration"]), 1)
                man_p.write_text(json.dumps(man, indent=1))

    (STREAMS / f"{fam}_manifest.json").write_text(json.dumps(man, indent=1))
    say(f"FAMILY {fam} DONE — manifest {man_p} (+ copy in streams/)")


if __name__ == "__main__":
    main()
