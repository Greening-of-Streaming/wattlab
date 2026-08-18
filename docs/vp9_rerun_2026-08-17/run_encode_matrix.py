#!/usr/bin/env python3
"""VP9 re-run, encode arm (2026-08-17): four SOFTWARE encoders × two speed points,
measured through the parity harness, zero service edits (same wrapper shape as the
2026-08-09 run_vp9_encode.py — monkeypatch parity.build_cmd / _encoder_kind).

Speed points ("the operating point is the codec"):
  default = OWL/S53 defaults: x264 medium · x265 medium · SVT-AV1 library default (10) ·
            libvpx good cpu-used 4
  slow    = Jan Ozer's everything-slow set: x264 slow · x265 slow · SVT-AV1 preset 3 ·
            libvpx good cpu-used 2  (the 2026-08-09 VP9 point)
Everything else = CR-029 §2 normalisation (pinned GOP, profile, scenecut off, 1080p,
AAC 128k, one-pass ABR at 2500/5000 kbps = S53 h265 CPU ladder interior rungs).

Rows: 2 clips × 4 encoders × 2 bitrates × 2 points × reps — reps OUTERMOST so repeats
of a cell are never thermally adjacent (parity's default puts rep innermost).

Artifacts → results/diagnostics/ (never calibration: /video/budget must stay blind).

Usage:
  python3 run_encode_matrix.py --print-only
  python3 run_encode_matrix.py --probe          # time ONE unmetered encode per arm (bbb trim)
  python3 run_encode_matrix.py [--reps 3]       # REAL metered run (needs /tmp/owl-paused)
"""
import argparse, asyncio, json, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, "/home/gos/wattlab/wattlab_service")
import parity            # noqa: E402
import settings as cfg   # noqa: E402
import video             # noqa: E402

parity.ARTIFACT_DIR = Path("/home/gos/wattlab/results/diagnostics")

CLIPS = ["bbb_120s", "meridian_120s"]
ENCODERS = ["x264", "x265", "svtav1", "vp9"]
POINTS = ["default", "slow", "slower"]   # "slower" exists for vp9 only (cpu-used 1)
BITRATES = [2500, 5000]

SPEED = {  # encoder → point → extra args
    "x264":   {"default": ["-preset", "medium"], "slow": ["-preset", "slow"]},
    "x265":   {"default": ["-preset", "medium"], "slow": ["-preset", "slow"]},
    "svtav1": {"default": [],                    "slow": ["-preset", "3"]},
    "vp9":    {"default": ["-cpu-used", "4"],    "slow": ["-cpu-used", "2"],
               "slower": ["-cpu-used", "1"]},
}
NORM_KEY = {"x264": "cpu", "x265": "h265_cpu", "svtav1": "av1_cpu"}
LIB = {"x264": "libx264", "x265": "libx265", "svtav1": "libsvtav1", "vp9": "libvpx-vp9"}


def build_cmd(codec, profile, bitrate_kbps, height=1080):
    if codec not in SPEED or profile not in SPEED[codec]:
        raise ValueError(f"unexpected recipe {codec}/{profile}")
    gop = str(int(cfg.load().get("encode_gop_frames", 120)))
    if codec == "vp9":
        norm = ["-g", gop, "-profile:v", "0", "-auto-alt-ref", "1", "-lag-in-frames", "25",
                "-row-mt", "1", "-tile-columns", "3", "-threads", "16", "-deadline", "good",
                "-pix_fmt", "yuv420p"]
    else:
        norm = video._norm_args(NORM_KEY[codec])
    parts = ["ffmpeg", "-y", "-i", "{input}", "-c:v", LIB[codec], "-b:v", f"{bitrate_kbps}k",
             *SPEED[codec][profile], *norm, "-vf", f"scale=-2:{height}",
             "-c:a", "aac", "-b:a", "128k", "{output}"]
    return " ".join(parts)


parity.build_cmd = build_cmd
parity._encoder_kind = lambda profile: "cpu"


class RepOuterCampaign(parity.Campaign):
    def recipes(self):
        for rep in range(self.reps):
            for clip_key in self.clips:
                for codec in self.codecs:
                    for bps in self._bitrates_for(clip_key).get(codec, []):
                        for profile in self.profiles:
                            if profile not in SPEED[codec]:
                                continue
                            yield {"clip": clip_key, "codec": codec, "profile": profile,
                                   "bps": bps, "height": 1080, "rep": rep, "kind": "sweep"}


def campaign(reps: int) -> parity.Campaign:
    s = cfg.load()
    return RepOuterCampaign(
        clips=CLIPS, codecs=ENCODERS, profiles=POINTS,
        bitrates={e: BITRATES for e in ENCODERS}, duration_s=30,
        baseline_polls=int(s.get("baseline_polls", 10)),
        cooldown_s=int(s.get("video_cooldown_s", 10)),
        reps=reps, min_task_s=20.0,
    )


def probe():
    """Unmetered timing of one encode per (encoder, point) on the bbb 30 s trim at 5000k
    (bbb = high complexity → worst case). Prints per-arm seconds and a projected total."""
    ref = parity.ensure_clip(parity.CLIPS["bbb_120s"], 30)
    out = Path("/tmp/wattlab_uploads/probe_out.mp4")
    out.parent.mkdir(exist_ok=True)
    timings = {}
    for enc in ENCODERS:
        for pt in POINTS:
            if pt not in SPEED[enc]:
                continue
            cmd = video.apply_custom_cmd(build_cmd(enc, pt, 5000), ref, out)
            t0 = time.time()
            subprocess.run(["nice", "-n", "-5", *cmd], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=True)
            dt = time.time() - t0
            timings[f"{enc}/{pt}"] = round(dt, 1)
            print(f"  {enc:7} {pt:8} {dt:6.1f} s for 30 s of bbb 1080p60", flush=True)
    # projection: window = max(dt, 20 s), + ~30 s/row overhead (baseline, VMAF, cooldown)
    per_cell = {k: max(v, 20.0) + 30 for k, v in timings.items()}
    rows_per_arm = len(CLIPS) * len(BITRATES)  # per rep
    total = sum(per_cell.values()) * rows_per_arm
    print(f"projected per rep ≈ {total/60:.0f} min → 3 reps ≈ {3*total/3600:.1f} h "
          f"(bbb-only timing, meridian is faster)")
    Path(__file__).with_name("probe_timings.json").write_text(json.dumps(timings, indent=1))
    out.unlink(missing_ok=True)


async def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--print-only", action="store_true")
    p.add_argument("--probe", action="store_true")
    p.add_argument("--reps", type=int, default=3)
    a = p.parse_args(argv)
    camp = campaign(a.reps)
    if a.print_only:
        for i, rc in enumerate(camp.recipes()):
            print(f"# {i}: rep{rc['rep']} {rc['clip']} {rc['codec']}/{rc['profile']} {rc['bps']}k")
            print("  " + build_cmd(rc["codec"], rc["profile"], rc["bps"]))
        print(f"total rows: {camp.count()}")
        return 0
    if a.probe:
        probe()
        return 0
    if not Path("/tmp/owl-paused").exists():
        print("REFUSING: /tmp/owl-paused not present (service poller would contend for the P110)")
        return 2
    await parity.run_campaign(camp)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
