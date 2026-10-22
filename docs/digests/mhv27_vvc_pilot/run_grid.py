#!/usr/bin/env python3
"""MHV'27 VVC pilot — metered encode grid on GoS1 (CPU, 10-bit, Meridian 30 s).

Protocol = docs/smpte_2026/run_clean_sweep.py (real wait-for-idle via
power.cooldown_between_runs, baseline_elevated kept, posix_fadvise eviction, reps as
whole passes, 30 s excerpt repeated until the window is >= 20 s), with three changes:
  * recipes are parity.build_cmd(codec, "cpu", kbps, 1080, bit_depth=10) for
    h265 (x265 Main10), av1 (SVT-AV1 10-bit) and vvc (libvvenc);
  * energy is also normalised per 1000 frames encoded;
  * VMAF v0.6.1 is scored with both sides of the graph pinned to yuv420p10le
    (in-process wrap of quality._fr_prep; quality.py on disk is untouched).

Usage:
  run_grid.py --plan GRID.json [--resume ARTIFACT] [--dry]
GRID.json = {"h265": [kbps, ...], "av1": [...], "vvc": [...]}
"""
import argparse, asyncio, json, os, shutil, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path("/home/gos/wattlab")
sys.path.insert(0, str(REPO / "wattlab_service"))
import parity, video, power, energy, quality, settings as cfg   # noqa: E402
from confidence import confidence                                # noqa: E402

REPS = 3
DURATION_S = 30
BASELINE_POLLS = 5
MIN_TASK_S = 20.0
CODEC_ORDER = ["h265", "av1", "vvc"]
PAUSE_FLAG, LAB_FLAG = Path("/tmp/owl-paused"), Path("/tmp/owl-lab-session")
OUT_DIR = REPO / "results" / "calibration" / "_staging"
KEEP_DIR = Path("/srv/data/owl/mhv27_vvc_pilot/grid_outputs")   # rep-0 outputs kept for decode
CLIPS = {"meridian_120s": parity.CLIPS["meridian_120s"],
         "football_30s": REPO / "test_content" / "football_35s.mp4"}   # LAB-INTERNAL source (pictures)

_orig_fr_prep = quality._fr_prep


def _fr_prep_10bit(tw, th):
    return (f"[0:v]crop={tw}:{th}:0:0,format=yuv420p10le,setpts=PTS-STARTPTS[d];"
            f"[1:v]scale={tw}:{th}:flags=bicubic,format=yuv420p10le,setpts=PTS-STARTPTS[r];")


quality._fr_prep = _fr_prep_10bit
VMAF_S = {**cfg.load(), "vmaf_model": "v0"}


def evict(path: Path) -> bool:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return False
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def n_frames(path: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
                          "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return int(out)


async def measure(ref: Path, job_id: str, codec: str, kbps: int, clip_dur_s: float,
                  frames_per_pass: int, keep: bool, keep_name: str = "") -> dict:
    cmd_str = parity.build_cmd(codec, "cpu", kbps, 1080, bit_depth=10)
    out_path = video.UPLOAD_DIR / f"{job_id}_out.mp4"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd_list = video.apply_custom_cmd(cmd_str, ref, out_path)
    loop = asyncio.get_event_loop()
    cache_evicted = evict(ref)
    baseline = await video.measure_baseline(polls=BASELINE_POLLS)
    stop = asyncio.Event()
    poll_task = asyncio.create_task(video.poll_during_task(stop))
    t0 = time.time()
    n_enc, last_tx, enc_times = 0, None, []
    while True:
        te = time.time()
        last_tx = await loop.run_in_executor(None, lambda: video.transcode(cmd_list))
        enc_times.append(round(time.time() - te, 1))
        n_enc += 1
        if time.time() - t0 >= MIN_TASK_S or not (last_tx or {}).get("success"):
            break
    t1 = time.time()
    stop.set()
    readings = await poll_task

    delta_t = round(t1 - t0, 1)
    w_base = baseline["w_base"]
    task_samples_w = [round(r["watts"], 2) for r in readings]
    w_task = sum(r["watts"] for r in readings) / len(readings) if readings else w_base
    delta_w = round(w_task - w_base, 2)
    meters = power.meters_summary(baseline, readings, task_samples_w)
    if meters and "delta_w_combined" in meters:
        delta_w = meters["delta_w_combined"]
    delta_e_wh = energy.energy_wh(delta_w, delta_t)
    conf = confidence(delta_w, len(readings), w_base,
                      baseline_samples_w=baseline.get("baseline_samples_w"),
                      task_samples_w=task_samples_w, meters=meters)
    frames_out = n_frames(out_path) if out_path.exists() else None   # frames actually encoded per pass
    frames = (frames_out or frames_per_pass) * n_enc
    content_s = clip_dur_s * n_enc
    stream = video.probe_output_stream(out_path) or {}
    vmaf = video.compute_vmaf(out_path, ref, s=VMAF_S)
    if keep:
        KEEP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out_path), str(KEEP_DIR / (keep_name or f"{codec}_{kbps}k.mp4")))   # /tmp -> /srv/data: cross-device
    else:
        out_path.unlink(missing_ok=True)
    return {
        "vmaf": vmaf, "vmaf_model": quality.vmaf_model_id(VMAF_S),
        "vmaf_graph": "both sides format=yuv420p10le",
        "ffmpeg_cmd": (last_tx or {}).get("ffmpeg_cmd"), "transcode_ok": (last_tx or {}).get("success"),
        "n_encodes": n_enc, "encode_wall_s": enc_times, "content_s": round(content_s, 1),
        "frames_encoded": frames, "frames_per_pass_out": frames_out,
        "w_base": round(w_base, 2), "delta_w": delta_w, "delta_e_wh_total": delta_e_wh,
        "delta_t_s": delta_t,
        "wh_per_1000_frames": round(delta_e_wh / frames * 1000, 5) if frames else None,
        "wh_per_min_video": round(delta_e_wh / (content_s / 60), 4) if content_s else None,
        "poll_count": len(readings), "achieved_bitrate_bps": stream.get("bit_rate_bps"),
        "confidence_flag": (conf or {}).get("flag"), "confidence": conf, "meters": meters,
        "baseline_samples_w": baseline.get("baseline_samples_w"), "task_samples_w": task_samples_w,
        "stream": stream, "cache_evicted": cache_evicted,
        "baseline_elevated": baseline.get("baseline_elevated"),
        "baseline_reference_w": baseline.get("baseline_reference_w"),
    }


def recipes(plan: dict) -> list:
    return [{"codec": c, "kbps": k, "rep": rep}
            for rep in range(REPS) for c in CODEC_ORDER for k in plan.get(c, [])]


async def main(a) -> int:
    plan = json.loads(Path(a.plan).read_text())
    ref = parity.ensure_clip(CLIPS[a.clip], DURATION_S)
    fpp = n_frames(ref)
    todo = recipes(plan)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if a.resume:
        out = Path(a.resume)
        art = json.loads(out.read_text())
    else:
        tag = "" if a.clip == "meridian_120s" else f"{a.clip}_"
        out = OUT_DIR / f"mhv27_vvc_pilot_encode_{tag}{datetime.now(timezone.utc):%Y-%m-%dT%H%M}.json"
        art = {"schema": "mhv27-vvc-pilot-encode/v1",
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "fingerprint": parity.fingerprint(),
               "protocol": {"clip": a.clip, "excerpt_s": DURATION_S, "ref_packets": fpp,
                            "chain": "scale=-2:1080,format=yuv420p10le", "audio": "aac 128k",
                            "gop_frames": int(cfg.load().get("encode_gop_frames", 120)),
                            "baseline_polls": BASELINE_POLLS, "min_task_s": MIN_TASK_S, "reps": REPS,
                            "rep_order": "whole passes", "cooldown": "power.cooldown_between_runs",
                            "vmaf": "v0.6.1, both sides yuv420p10le", "plan": plan},
               "rows": [], "complete": False}
    done = {(r["codec"], r["target_kbps"], r["rep"]) for r in art["rows"] if not r.get("error")}
    art["rows"] = [r for r in art["rows"] if not r.get("error")]
    todo = [r for r in todo if (r["codec"], r["kbps"], r["rep"]) not in done]
    print(f"[grid] {len(todo)} rows to go -> {out}  frames/pass={fpp}", flush=True)
    if a.dry:
        for r in todo:
            print("  ", r, parity.build_cmd(r["codec"], "cpu", r["kbps"], 1080, bit_depth=10))
        return 0
    if video.LOCK_FILE.exists():
        print("ABORT: measurement lock held"); return 2

    def checkpoint():
        out.write_text(json.dumps(art, indent=2))

    created = []
    for f in (PAUSE_FLAG, LAB_FLAG):
        if not f.exists():
            f.write_text("mhv27 vvc pilot encode grid\n"); created.append(f)
    stopped = video.focus_mode_enter()
    video.LOCK_FILE.write_text("mhv27 vvc pilot encode grid\n")
    last_floor = None
    try:
        for i, r in enumerate(todo):
            cd = None
            if last_floor is not None:
                cd = await power.cooldown_between_runs(fixed_seconds=60, reference_w=last_floor,
                                                       stage="mhv27_grid_cooldown")
            job_id = f"mhv27_{a.clip}_{r['codec']}_{r['kbps']}_r{r['rep']}"
            print(f"[grid] {i + 1}/{len(todo)} {r}  {datetime.now():%H:%M:%S}", flush=True)
            try:
                m = await measure(ref, job_id, r["codec"], r["kbps"], DURATION_S, fpp, keep=r["rep"] == 0,
                                  keep_name=f"{'' if a.clip == 'meridian_120s' else a.clip + '_'}{r['codec']}_{r['kbps']}k.mp4")
            except Exception as exc:
                m = {"error": repr(exc)}
            last_floor = m.get("w_base", last_floor)
            print(f"[grid]    -> vmaf={m.get('vmaf')} kbps={(m.get('achieved_bitrate_bps') or 0) // 1000} "
                  f"dW={m.get('delta_w')} Wh/1000f={m.get('wh_per_1000_frames')} n_enc={m.get('n_encodes')} "
                  f"{m.get('confidence_flag')} elevated={m.get('baseline_elevated')}", flush=True)
            art["rows"].append({"clip": a.clip, "codec": r["codec"], "target_kbps": r["kbps"], "rep": r["rep"],
                                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "cooldown": cd, **m})
            checkpoint()
        art["complete"] = True
    finally:
        video.LOCK_FILE.unlink(missing_ok=True)
        video.focus_mode_exit(stopped)
        for f in created:
            f.unlink(missing_ok=True)
        checkpoint()
    print(f"[grid] done -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--resume")
    ap.add_argument("--clip", default="meridian_120s", choices=sorted(CLIPS))
    ap.add_argument("--dry", action="store_true")
    sys.exit(asyncio.run(main(ap.parse_args())))
