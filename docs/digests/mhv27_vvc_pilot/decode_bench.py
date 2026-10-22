#!/usr/bin/env python3
"""MHV'27 VVC pilot — host decode energy (ad hoc, not an OWL mode).

Same measurement primitives as parity / run_clean_sweep.py: video.measure_baseline ->
poll_during_task around the task -> power.meters_summary (dual-meter ci2) -> confidence(),
with a real wait-for-idle (power.cooldown_between_runs against the previous row's w_base),
posix_fadvise cache eviction before each row, and reps as whole passes over the matrix.
Runs unchanged on GoS1 (ffmpeg-master) and GoS2 (Homebrew ffmpeg 9.0.2), each node reading
its own meters through its own repo checkout.

Regimes:
  afap   ffmpeg [-threads N] -i S -an -f null -   repeated back to back until >= MIN_TASK_S
  paced  ffmpeg -re -i S -an -f null -            one pass of the 30 s clip (>= MIN_TASK_S)
Energy is normalised per 1000 decoded frames (frame= from ffmpeg's last stats line);
speed= is kept per invocation so real-time-ness is on file.

Usage (from the repo root of the node that measures):
  python decode_bench.py --streams DIR --out FILE.jsonl --arms vvc,hevc,dav1d [--regimes afap,paced]
                         [--reps 3] [--threads1] [--dry]
Rig client (Pi 5): add --ssh USER@HOST --ffmpeg /dev/shm/.../ffmpeg --remote-streams /dev/shm/DIR
  --meter-ip PLUG_IP. GoS1 reads that plug (power.use_meters), ffmpeg runs on the client over ssh.
  The wattlab service must be stopped for the window (the rig poller owns the plug's KLAP session).
"""
import contextlib
import argparse, asyncio, json, os, re, socket, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(os.environ.get("OWL_REPO", Path.home() / "wattlab"))
sys.path.insert(0, str(REPO / "wattlab_service"))
import video, power, energy, settings as cfg       # noqa: E402
from confidence import confidence                  # noqa: E402

MIN_TASK_S = 20.0
BASELINE_POLLS = 5
PAUSE_FLAG, LAB_FLAG = Path("/tmp/owl-paused"), Path("/tmp/owl-lab-session")

# arm -> (stream codec, decoder args placed before -i)
ARMS = {
    "vvc":     ("vvc",  ["-c:v", "vvc"]),
    "hevc":    ("hevc", ["-c:v", "hevc"]),
    "dav1d":   ("av1",  ["-c:v", "libdav1d"]),
    # GoS2 only: VideoToolbox hardware decode, frames downloaded to system memory
    "hevc_vt": ("hevc", ["-hwaccel", "videotoolbox", "-c:v", "hevc"]),
    "av1_vt":  ("av1",  ["-hwaccel", "videotoolbox", "-c:v", "av1"]),
}
STATS_RE = re.compile(r"frame=\s*(\d+).*?speed=\s*([\d.]+)x")


def evict(path: Path) -> bool:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return False
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        return True
    except (OSError, AttributeError):        # macOS has no posix_fadvise
        return False
    finally:
        os.close(fd)


REMOTE = {"ssh": None, "ffmpeg": None, "streams": None}
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=15"]


def ffmpeg_bin() -> str:
    return REMOTE["ffmpeg"] or video._ffmpeg_bin()


def remote_wrap(cmd: list) -> list:
    if not REMOTE["ssh"]:
        return cmd
    import shlex
    return ["ssh", *SSH_OPTS, REMOTE["ssh"], " ".join(shlex.quote(c) for c in cmd)]


def decode_cmd(stream: Path, arm: str, regime: str, threads1: bool) -> list:
    dec = ARMS[arm][1]
    if REMOTE["streams"]:
        stream = Path(REMOTE["streams"]) / stream.name
    return [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y",
            *(["-re"] if regime == "paced" else []),
            *(["-threads", "1"] if threads1 else []),
            *dec, "-i", str(stream), "-an", "-f", "null", "-"]


def run_once(cmd: list) -> dict:
    p = subprocess.run(remote_wrap(cmd), capture_output=True, text=True)
    last = None
    for m in STATS_RE.finditer(p.stderr.replace("\r", "\n")):
        last = m
    hw_fail = any(s in p.stderr for s in ("Failed setup for format", "hwaccel initialisation returned error",
                                          "No device available for decoder"))
    return {"rc": p.returncode, "frames": int(last.group(1)) if last else None,
            "speed": float(last.group(2)) if last else None, "hw_fallback": hw_fail,
            "stderr_tail": p.stderr[-400:] if p.returncode else None}


async def measure_row(stream: Path, arm: str, regime: str, threads1: bool) -> dict:
    cmd = decode_cmd(stream, arm, regime, threads1)
    loop = asyncio.get_event_loop()
    cache_evicted = None if REMOTE["ssh"] else evict(stream)   # client streams sit in /dev/shm (RAM)
    baseline = await video.measure_baseline(polls=BASELINE_POLLS)
    stop = asyncio.Event()
    poll_task = asyncio.create_task(video.poll_during_task(stop))
    t0 = time.time()
    runs = []
    while True:
        runs.append(await loop.run_in_executor(None, run_once, cmd))
        if time.time() - t0 >= MIN_TASK_S or runs[-1]["rc"] != 0:
            break
    t1 = time.time()
    stop.set()
    readings = await poll_task

    delta_t = round(t1 - t0, 1)
    w_base = baseline["w_base"]
    task_samples_w = [round(r["watts"], 3) for r in readings]
    w_task = sum(r["watts"] for r in readings) / len(readings) if readings else w_base
    delta_w = round(w_task - w_base, 3)
    meters = power.meters_summary(baseline, readings, task_samples_w)
    if meters and "delta_w_combined" in meters:
        delta_w = meters["delta_w_combined"]
    delta_e_wh = energy.energy_wh(delta_w, delta_t)
    conf = confidence(delta_w, len(readings), w_base,
                      baseline_samples_w=baseline.get("baseline_samples_w"),
                      task_samples_w=task_samples_w, meters=meters)
    frames = sum(r["frames"] or 0 for r in runs)
    return {
        "cmd": " ".join(cmd), "n_invocations": len(runs), "frames": frames,
        "speed_x": [r["speed"] for r in runs], "rc": [r["rc"] for r in runs],
        "hw_fallback": any(r["hw_fallback"] for r in runs),
        "stderr_tail": next((r["stderr_tail"] for r in runs if r["stderr_tail"]), None),
        "w_base": round(w_base, 3), "delta_w": delta_w, "delta_t_s": delta_t,
        "delta_e_wh": delta_e_wh,
        "wh_per_1000_frames": round(delta_e_wh / frames * 1000, 5) if frames else None,
        "poll_count": len(readings), "confidence_flag": (conf or {}).get("flag"),
        "confidence": conf, "meters": meters,
        "baseline_samples_w": baseline.get("baseline_samples_w"),
        "task_samples_w": task_samples_w,
        "baseline_elevated": baseline.get("baseline_elevated"),
        "baseline_reference_w": baseline.get("baseline_reference_w"),
        "cache_evicted": cache_evicted,
    }


def matrix(arms, regimes, reps, threads1):
    rows = []
    for rep in range(reps):                     # whole passes: replicates never back-to-back
        for arm in arms:
            for regime in regimes:
                rows.append({"arm": arm, "regime": regime, "threads1": False, "rep": rep})
            if threads1:
                rows.append({"arm": arm, "regime": "afap", "threads1": True, "rep": rep})
    return rows


def key(r):
    return (r["arm"], r["regime"], r["threads1"], r["rep"])


async def main(a) -> int:
    streams = {p.name.split("_")[0]: p for p in Path(a.streams).glob("*.mp4")}
    arms = a.arms.split(",")
    for arm in arms:
        if ARMS[arm][0] not in streams:
            print(f"ABORT: no {ARMS[arm][0]} stream in {a.streams}"); return 2
    out = Path(a.out)
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            r = json.loads(line)
            if not r.get("error"):
                done.add(key(r))
    todo = [r for r in matrix(arms, a.regimes.split(","), a.reps, a.threads1) if key(r) not in done]
    REMOTE.update(ssh=a.ssh, ffmpeg=a.ffmpeg, streams=a.remote_streams)
    ffv = subprocess.run(remote_wrap([ffmpeg_bin(), "-hide_banner", "-version"]), capture_output=True,
                         text=True).stdout.splitlines()[0]
    host = a.ssh.split("@")[-1] if a.ssh else socket.gethostname()
    print(f"[decode] {socket.gethostname()} {ffv} — {len(todo)} rows to go ({len(done)} done)", flush=True)
    if a.dry:
        for r in todo:
            print(" ", r, " ".join(decode_cmd(streams[ARMS[r['arm']][0]], r["arm"], r["regime"], r["threads1"])))
        return 0
    if Path(video.LOCK_FILE).exists():
        print("ABORT: measurement lock held"); return 2

    created = []
    for f, why in ((PAUSE_FLAG, "mhv27 decode bench\n"), (LAB_FLAG, "mhv27 decode bench\n")):
        if not f.exists():
            f.write_text(why); created.append(f)
    stopped = video.focus_mode_enter()
    Path(video.LOCK_FILE).write_text("mhv27 decode bench\n")
    last_floor = None
    meter_ctx = power.use_meters([a.meter_ip]) if a.meter_ip else contextlib.nullcontext()
    meter_ctx.__enter__()
    try:
        for i, r in enumerate(todo):
            stream = streams[ARMS[r["arm"]][0]]
            cd = None
            if last_floor is not None:
                cd = await power.cooldown_between_runs(fixed_seconds=60, reference_w=last_floor,
                                                       stage="mhv27_decode_cooldown")
            print(f"[decode] {i + 1}/{len(todo)} {r}", flush=True)
            try:
                m = await measure_row(stream, r["arm"], r["regime"], r["threads1"])
            except Exception as exc:
                m = {"error": repr(exc)}
            last_floor = m.get("w_base", last_floor)
            row = {**r, "host": host, "meter_ip": a.meter_ip, "ffmpeg_version": ffv, "stream": stream.name,
                   "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cooldown": cd, **m}
            print(f"[decode]    -> dW={m.get('delta_w')} W  Wh/1000f={m.get('wh_per_1000_frames')}  "
                  f"speed={m.get('speed_x')}  {m.get('confidence_flag')}  elevated={m.get('baseline_elevated')}",
                  flush=True)
            with open(out, "a") as f:
                f.write(json.dumps(row) + "\n")
    finally:
        meter_ctx.__exit__(None, None, None)
        try:
            Path(video.LOCK_FILE).unlink()
        except FileNotFoundError:
            pass
        video.focus_mode_exit(stopped)
        for f in created:
            f.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--streams", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--arms", required=True)
    ap.add_argument("--regimes", default="afap,paced")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--threads1", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--ssh")
    ap.add_argument("--ffmpeg")
    ap.add_argument("--remote-streams")
    ap.add_argument("--meter-ip")
    sys.exit(asyncio.run(main(ap.parse_args())))
