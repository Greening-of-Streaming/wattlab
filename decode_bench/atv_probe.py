#!/usr/bin/env python3
"""Apple TV decode-energy probe, driven through VLC for tvOS (CR-075, 2026-08-26).

Why VLC: AirPlay `play_url` is dead on tvOS 18 (pyatv #2403 — the receiver
accepts POST /play, then answers 500 to GET /playback-info and never fetches
the URL; reproduced here for MP4 and HLS with the origin logging 0 requests).
What works: Companion `launch_app` with VLC's x-callback stream scheme,
after a ONE-TIME on-screen "Open VLC?" confirmation on the remote. So this
probe measures *VLC on tvOS* (VideoToolbox for H.264/HEVC where VLC uses it;
dav1d for AV1; VP9 whatever VLC picks on an A10X) — not the native player.
Say so wherever a number from here is quoted.

Protocol (mirrors bench.py v3 as far as AirPlay allows): home screen →
settle → baseline (1 s mW samples) → launch clip → settle → sampled window
(1 s) with a liveness poll every ~10 s in a side thread (pyatv playback
state + position advance; weaker than the in-clip marker, which cannot be
injected through this path) → stop → home. confidence.py on the raw
samples, like every other OWL row.

Usage:
  python3 atv_probe.py --plug 192.168.1.NN --out /srv/data/owl/atv/probe.jsonl \
      [--n 2] [--window 120] [--settle 20] [--baseline 40] [--clips h264,h265,av1,vp9]
"""
import argparse, asyncio, json, statistics, subprocess, sys, threading, time
from pathlib import Path
from dotenv import dotenv_values

sys.path.insert(0, "/home/gos/wattlab/wattlab_service")
import confidence as owl_confidence   # noqa: E402

ATVREMOTE = "/tmp/pyatv-venv/bin/atvremote"
ATV_IP = "192.168.1.152"
CREDS = Path("/srv/data/owl/atv")
ORIGIN = "http://192.168.1.62:8123"
ENV = dotenv_values("/home/gos/wattlab/.env")
CLIPS = {   # iso-bitrate BBB family (S65 recipe), 3-min cuts of the 20-min files
    "h264": "_atv/bbbiso_h264_3min.mp4",
    "h265": "_atv/bbbiso_h265_3min.mp4",
    "av1":  "_atv/bbbiso_av1_3min.mp4",
    "vp9":  "_atv/bbbiso_vp9_3min.webm",
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def atv(*cmds, timeout=45):
    cc = (CREDS / "companion_creds").read_text().strip()
    ac = (CREDS / "airplay_creds").read_text().strip()
    r = subprocess.run([ATVREMOTE, "-s", ATV_IP, "--companion-credentials", cc,
                        "--airplay-credentials", ac, *cmds],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr


def playing() -> dict:
    """{state, position_s, title, app} from `atvremote playing app`."""
    out = atv("playing", "app", timeout=35)
    d = {"state": None, "position_s": None, "title": None, "app": None, "t": time.time()}
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("Device state:"):
            d["state"] = s.split(":", 1)[1].strip()
        elif s.startswith("Position:"):
            try:
                d["position_s"] = float(s.split(":", 1)[1].strip().split("/")[0].rstrip("s"))
            except ValueError:
                pass
        elif s.startswith("Title:"):
            d["title"] = s.split(":", 1)[1].strip()
        elif s.startswith("App:"):
            d["app"] = s.split(":", 1)[1].strip()
    return d


def launch(url: str) -> str:
    return atv(f"launch_app=vlc-x-callback://x-callback-url/stream?url={url}")


class Meter:
    """One P110, mW path (get_energy_usage.current_power / 1000), own loop."""
    def __init__(self, ip):
        from tapo import ApiClient
        self.ip = ip
        self.loop = asyncio.new_event_loop()
        self.client = ApiClient(ENV["TAPO_EMAIL"], ENV["TAPO_PASSWORD"])
        self.dev = self.loop.run_until_complete(self.client.p110(ip))

    def read(self) -> float:
        for attempt in range(3):
            try:
                e = self.loop.run_until_complete(
                    asyncio.wait_for(self.dev.get_energy_usage(), 5))
                return e.current_power / 1000.0
            except Exception as ex:
                log(f"meter {self.ip}: {type(ex).__name__} — reconnecting")
                time.sleep(1 + attempt)
                self.dev = self.loop.run_until_complete(self.client.p110(self.ip))
        raise RuntimeError("meter unreachable")


def sample(meter: Meter, seconds: float, cadence: float = 1.0, live_every: float = 0):
    samples, live, stop = [], [], threading.Event()

    def liveness():
        while not stop.is_set():
            try:
                live.append(playing())
            except Exception as ex:
                live.append({"state": f"ERR {type(ex).__name__}", "t": time.time()})
            stop.wait(live_every)
    th = threading.Thread(target=liveness, daemon=True) if live_every else None
    if th:
        th.start()
    t0 = time.monotonic()
    nxt = t0
    while time.monotonic() - t0 < seconds:
        samples.append(meter.read())
        nxt += cadence
        time.sleep(max(0.0, nxt - time.monotonic()))
    stop.set()
    if th:
        th.join(timeout=40)
    return samples, live


def liveness_summary(live: list) -> dict:
    states = [l.get("state") for l in live]
    pos = [l["position_s"] for l in live if l.get("position_s") is not None]
    advancing = sum(1 for a, b in zip(pos, pos[1:]) if b > a)
    return {"polls": len(live),
            "playing_polls": sum(1 for s in states if s == "Playing"),
            "position_advances": advancing,
            "position_pairs": max(0, len(pos) - 1),
            "apps": sorted({l.get("app") for l in live if l.get("app")}),
            "states": states}


def run_row(meter, codec, rep, a) -> dict:
    url = f"{ORIGIN}/{CLIPS[codec]}"
    log(f"row {codec} #{rep}: home + settle {a.settle}s")
    atv("stop"); atv("home")
    time.sleep(a.settle)
    base, _ = sample(meter, a.baseline)
    log(f"  baseline {statistics.mean(base):.3f} W (n={len(base)}) → launch {url}")
    t_launch = time.time()
    launch(url)
    time.sleep(a.settle)
    task, live = sample(meter, a.window, live_every=10)
    atv("stop"); atv("home")
    w_base, w_task = statistics.mean(base), statistics.mean(task)
    delta = w_task - w_base
    conf = owl_confidence.confidence(delta, len(task), w_base,
                                     baseline_samples_w=base, task_samples_w=task)
    ls = liveness_summary(live)
    row = {"probe": "atv_probe.py", "device": "Apple TV 4K 1st gen (AppleTV6,2, A10X, tvOS 18.0 22J357)",
           "player": "VLC for tvOS (org.videolan.vlc-ios) via Companion launch_app x-callback",
           "plug_ip": meter.ip, "codec": codec, "clip": CLIPS[codec], "rep": rep,
           "t_launch": t_launch, "window_s": a.window, "settle_s": a.settle,
           "w_base": round(w_base, 3), "w_task": round(w_task, 3), "delta_w": round(delta, 3),
           "n_base": len(base), "n_task": len(task),
           "task_min": round(min(task), 3), "task_max": round(max(task), 3),
           "base_sd": round(statistics.pstdev(base), 3), "task_sd": round(statistics.pstdev(task), 3),
           "confidence": conf, "liveness": ls,
           "baseline_samples_w": [round(x, 3) for x in base],
           "task_samples_w": [round(x, 3) for x in task]}
    log(f"  {codec} #{rep}: base {w_base:.3f} task {w_task:.3f} Δ {delta:+.3f} W "
        f"{conf.get('flag')} · playing {ls['playing_polls']}/{ls['polls']} polls, "
        f"position advanced {ls['position_advances']}/{ls['position_pairs']}")
    return row


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--plug", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--n", type=int, default=2)
    p.add_argument("--window", type=int, default=120)
    p.add_argument("--settle", type=int, default=20)
    p.add_argument("--baseline", type=int, default=40)
    p.add_argument("--clips", default="h264,h265,av1,vp9")
    a = p.parse_args()
    codecs = [c.strip() for c in a.clips.split(",") if c.strip()]
    meter = Meter(a.plug)
    log(f"meter {a.plug} reads {meter.read():.3f} W; Apple TV {atv('power_state').strip()}")
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    # interleave: rep 1 of every codec, then rep 2 … (drift shared across codecs)
    for rep in range(1, a.n + 1):
        for codec in codecs:
            row = run_row(meter, codec, rep, a)
            with out.open("a") as f:
                f.write(json.dumps(row) + "\n")
    log("ALL DONE")


if __name__ == "__main__":
    main()
