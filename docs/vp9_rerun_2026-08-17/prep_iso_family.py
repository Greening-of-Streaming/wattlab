#!/usr/bin/env python3
"""Build the iso-bitrate decode family (unmetered prep, GoS1).

Per content: ONE bitrate (= the existing H.264 family clip's bitrate, kranjska capped
for the Pi 400 /dev/shm ceiling), four SOFTWARE encoders at production points, two-pass
ABR, GOP 120, yuv420p, silent AAC 128k (catalogue loop clips carry AAC), 120 s → VMAF v1
vs the reference (OWL's quality.compute_vmaf, same scorer/model as the service) → concat
×10 stream-copy → 20-min loop clip in decode-bench streams/ (vp9 → .webm: MP4/vp09
stalls the Google TV player).  Resumable: skips outputs that exist. Manifest JSON.
"""
import json, subprocess, sys, time, shlex
from pathlib import Path

sys.path.insert(0, "/home/gos/wattlab/wattlab_service")
import quality  # noqa: E402  (VMAF v1 via the scoring binary from settings)

FF = "/usr/local/bin/ffmpeg-master"
DIR = Path("/srv/data/owl/campaign_2026-08-17_vp9b")
STREAMS = Path("/srv/data/owl/decode-bench/streams")
NICE = ["nice", "-n", "19"]

CONTENTS = {
    # fam: (reference for encode + scoring, target kbps)
    "bbbiso":      ("/srv/data/owl/campaign_2026-08-09_r12/bbb_1080p60_ref.mov", 8000),
    "kranjskaiso": ("/srv/data/owl/campaign_2026-08-09_r12k/kranjska_1080p30_ref.mov", 10000),
    "meridianiso": (str(DIR / "meridian_1080p60_ref.mov"), 4500),
}
MERIDIAN_SRC = "/home/gos/wattlab/test_content/meridian_120s.mp4"  # 4K H.264 master (compressed)

VP9_COMMON = ["-row-mt", "1", "-tile-columns", "3", "-threads", "16",
              "-auto-alt-ref", "1", "-lag-in-frames", "25", "-profile:v", "0",
              "-deadline", "good", "-cpu-used", "2"]

def venc(codec, kbps, passno, logbase):
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

def run(cmd, log):
    with open(log, "a") as fh:
        fh.write("\n$ " + " ".join(shlex.quote(c) for c in cmd) + "\n")
        fh.flush()
        r = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(f"exit {r.returncode}: {' '.join(cmd[:8])}…  (see {log})")

def probe(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
        "format=duration,bit_rate,size:stream=codec_name,width,height,r_frame_rate",
        "-of", "json", str(path)], text=True)
    return json.loads(out)

def main():
    log = DIR / "prep.log"
    manifest_p = DIR / "iso_family_manifest.json"
    manifest = json.loads(manifest_p.read_text()) if manifest_p.exists() else {}
    t0 = time.time()

    # Meridian 1080p ProRes ref from the compressed 4K master (generational caveat).
    mref = Path(CONTENTS["meridianiso"][0])
    if not mref.exists():
        print("making meridian 1080p ref …", flush=True)
        run(NICE + [FF, "-y", "-v", "warning", "-i", MERIDIAN_SRC, "-an",
                    "-vf", "scale=1920:1080:flags=lanczos", "-c:v", "prores_ks",
                    "-profile:v", "3", str(mref)], log)

    for fam, (ref, kbps) in CONTENTS.items():
        for codec in ("h264", "h265", "av1", "vp9"):
            ext = "webm" if codec == "vp9" else "mp4"
            clip = DIR / f"{fam}_{codec}_120s.{ext}"
            loop = STREAMS / f"{fam}_{codec}_20min.{ext}"
            key = f"{fam}_{codec}"
            if not clip.exists():
                print(f"[{time.time()-t0:6.0f}s] encode {key} @{kbps}k …", flush=True)
                base = ["-y", "-v", "warning", "-i", ref,
                        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
                logbase = str(DIR / f"pass_{key}")
                run(NICE + [FF] + base + ["-map", "0:v", "-an"] + venc(codec, kbps, 1, logbase)
                    + ["-f", "null", "-"], log)
                # WebM only takes Opus/Vorbis audio; MP4 family clips carry AAC (catalogue).
                aud = ["-c:a", "libopus", "-b:a", "128k"] if ext == "webm" else ["-c:a", "aac", "-b:a", "128k"]
                run(NICE + [FF] + base + ["-map", "0:v", "-map", "1:a", "-shortest"]
                    + venc(codec, kbps, 2, logbase) + aud + [str(clip)], log)
            if key not in manifest or manifest[key].get("vmaf") is None:
                print(f"[{time.time()-t0:6.0f}s] vmaf {key} …", flush=True)
                score = quality.compute_vmaf(clip, ref)
                pr = probe(clip)
                v = next(s for s in pr["streams"] if s.get("width"))
                manifest[key] = {
                    "family": fam, "codec": codec, "target_kbps": kbps, "clip_120s": str(clip),
                    "achieved_kbps": round(int(pr["format"]["bit_rate"]) / 1000),
                    "size_mb_120s": round(int(pr["format"]["size"]) / 1e6, 1),
                    "duration_s": round(float(pr["format"]["duration"]), 2),
                    "video": {k: v.get(k) for k in ("codec_name", "width", "height", "r_frame_rate")},
                    "vmaf": score, "vmaf_model": quality.vmaf_model_id(),
                    "reference": ref, "encoder_point": {
                        "h264": "libx264 medium", "h265": "libx265 medium",
                        "av1": "libsvtav1 preset 6", "vp9": "libvpx-vp9 good cpu-used 2"}[codec],
                    "rate_control": "two-pass ABR", "gop_frames": 120,
                    "audio": "silent Opus 128k (WebM)" if ext == "webm" else "silent AAC 128k",
                }
                manifest_p.write_text(json.dumps(manifest, indent=1))
            if not loop.exists():
                print(f"[{time.time()-t0:6.0f}s] concat ×10 → {loop.name} …", flush=True)
                lst = DIR / f"concat_{key}.txt"
                lst.write_text("".join(f"file '{clip}'\n" for _ in range(10)))
                tmp = loop.with_name("part_" + loop.name)  # keep the extension: ffmpeg picks the muxer from it
                run(NICE + [FF, "-y", "-v", "warning", "-f", "concat", "-safe", "0", "-i", str(lst),
                            "-c", "copy", str(tmp)], log)
                tmp.rename(loop)
            pr = probe(loop)
            manifest[key]["loop_clip"] = str(loop)
            manifest[key]["loop_duration_s"] = round(float(pr["format"]["duration"]), 1)
            manifest[key]["loop_size_gb"] = round(int(pr["format"]["size"]) / 1e9, 3)
            manifest_p.write_text(json.dumps(manifest, indent=1))
            print(f"   {key}: {manifest[key]['achieved_kbps']} kb/s, VMAF {manifest[key]['vmaf']}, "
                  f"loop {manifest[key]['loop_duration_s']} s / {manifest[key]['loop_size_gb']} GB", flush=True)
    (DIR / "prep_done").write_text(time.strftime("%F %T") + "\n")
    print(f"PREP DONE in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
