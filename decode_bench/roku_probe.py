#!/usr/bin/env python3
"""Roku decode-energy probe, driven through ECP (2026-08-29 onboarding).

⚠ UNVERIFIED MECHANISM — read this before running a real campaign.

Roku has no ADB/logcat equivalent and no first-party "play this URL" API.
The community technique (used by Home Assistant, openHAB, etc.) is an
UNDOCUMENTED app-launch trick over the External Control Protocol (ECP, port
8060, no auth): POST /launch/<appId>?u=<url>&t=v launches a hidden system app
("PlayOnRoku", id 15985) with that URL. Researched 2026-08-29 before writing
this:
  - Roku deliberately disabled 15985 for third parties on Roku OS 11.5+ (a
    Roku engineer confirmed this on the Home Assistant forum; HA's own
    integration hit the same wall — github.com/home-assistant/core#83819).
    This box's own /query/device-info reports software-version 14.0.4, i.e.
    current firmware — 15985 is very likely to just flash the splash screen
    and crash back out. --app-id lets you try it anyway for one row.
  - The documented-working replacement needs a one-time, non-developer-mode
    Channel Store install: "Media Assistant" (free, app id 782875,
    github.com/MedievalApple/Media-Assistant) — search the Channel Store on
    the box itself and add it before running this probe with the default
    --app-id.
  - Nothing in any source confirms whether playback shows a clean full-frame
    picture or persistent transport-control chrome once past the opening
    seconds — unlike the other rig devices, that has to be watched on a
    physical screen this first time, not assumed from bench numbers alone.
  - /query/media-player (state/position/duration) IS official, documented,
    and needs no app install — liveness proof here is solid regardless of
    which launch path is used.

Protocol mirrors atv_probe.py: baseline (parked on Home) → launch → settle →
sampled window (1 s) with a liveness poll every ~10 s → Home (stop) → park.
confidence.py on the raw samples, like every other OWL row.

Usage:
  python3 roku_probe.py --plug 192.168.1.NN --roku 192.168.1.13 \\
      --out /srv/data/owl/roku/probe.jsonl [--n 1] [--window 60] \\
      [--app-id 782875] [--clips h264,h265,av1,vp9]

Start with --n 1 --window 30 on ONE codec and watch the screen before
trusting this for anything — this is a first live test, not a proven path.
"""
import argparse, asyncio, json, statistics, sys, threading, time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from dotenv import dotenv_values

sys.path.insert(0, "/home/gos/wattlab/wattlab_service")
import confidence as owl_confidence   # noqa: E402

ORIGIN = "http://192.168.1.62:8123"
ENV = dotenv_values("/home/gos/wattlab/.env")
CLIPS = {   # same iso-bitrate BBB family as atv_probe.py
    "h264": "_atv/bbbiso_h264_3min.mp4",
    "h265": "_atv/bbbiso_h265_3min.mp4",
    "av1":  "_atv/bbbiso_av1_3min.mp4",
    "vp9":  "_atv/bbbiso_vp9_3min.webm",
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _ecp(roku_ip, method, path, params=None, timeout=10):
    import urllib.parse
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    req = urllib.request.Request(f"http://{roku_ip}:8060{path}{qs}", method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def device_info(roku_ip) -> dict:
    root = ET.fromstring(_ecp(roku_ip, "GET", "/query/device-info"))
    return {c.tag: c.text for c in root}


def media_player_state(roku_ip) -> dict:
    """{state, position_s, duration_s, error} from /query/media-player — the
    ONE part of this probe that is officially documented, no app required."""
    try:
        root = ET.fromstring(_ecp(roku_ip, "GET", "/query/media-player"))
    except Exception as e:
        return {"state": f"ERR {type(e).__name__}", "t": time.time()}
    d = {"state": root.get("state"), "error": root.get("error"), "t": time.time()}
    for tag in ("position", "duration"):
        el = root.find(tag)
        if el is not None and el.text:
            try:
                d[f"{tag}_s"] = int(el.text.strip().rstrip("ms").strip()) / 1000.0
            except ValueError:
                pass
    return d


def launch(roku_ip, app_id: str, url: str, video_name: str, video_format: str):
    """POST /launch/<appId>?u=<url>&t=v&videoName=...&videoFormat=... — the
    undocumented casting convention (see module docstring for caveats)."""
    _ecp(roku_ip, "POST", f"/launch/{app_id}",
         {"u": url, "t": "v", "videoName": video_name, "videoFormat": video_format})


def go_home(roku_ip):
    _ecp(roku_ip, "POST", "/keypress/Home")


class Meter:
    """One P110, mW path — identical shape to atv_probe.py's Meter."""
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


def sample(meter: Meter, seconds: float, roku_ip=None, cadence: float = 1.0, live_every: float = 0):
    samples, live, stop = [], [], threading.Event()

    def liveness():
        while not stop.is_set():
            try:
                live.append(media_player_state(roku_ip))
            except Exception as ex:
                live.append({"state": f"ERR {type(ex).__name__}", "t": time.time()})
            stop.wait(live_every)
    th = threading.Thread(target=liveness, daemon=True) if (live_every and roku_ip) else None
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
    return {"polls": len(live), "playing_polls": sum(1 for s in states if s == "play"),
            "position_advances": advancing, "position_pairs": max(0, len(pos) - 1),
            "states": states}


def run_row(meter, roku_ip, codec, rep, a) -> dict:
    url = f"{ORIGIN}/{CLIPS[codec]}"
    video_format = "mkv" if codec == "vp9" else "mp4"   # CLIPS' vp9 is .webm; Roku's videoFormat enum has no webm — mkv is the closer container hint
    log(f"row {codec} #{rep}: Home + settle {a.settle}s")
    go_home(roku_ip)
    time.sleep(a.settle)
    base, _ = sample(meter, a.baseline)
    log(f"  baseline {statistics.mean(base):.3f} W (n={len(base)}) → launch/{a.app_id} {url}")
    t_launch = time.time()
    launch(roku_ip, a.app_id, url, f"owl_{codec}_{rep}", video_format)
    time.sleep(a.settle)
    task, live = sample(meter, a.window, roku_ip=roku_ip, live_every=10)
    go_home(roku_ip)
    w_base, w_task = statistics.mean(base), statistics.mean(task)
    delta = w_task - w_base
    conf = owl_confidence.confidence(delta, len(task), w_base,
                                     baseline_samples_w=base, task_samples_w=task)
    ls = liveness_summary(live)
    row = {"probe": "roku_probe.py", "device": "Roku Express 4K (3940EU2, Realtek RTD1315)",
           "launch_mechanism": f"ECP /launch/{a.app_id} (undocumented — see module docstring)",
           "plug_ip": meter.ip, "roku_ip": roku_ip, "codec": codec, "clip": CLIPS[codec], "rep": rep,
           "t_launch": t_launch, "window_s": a.window, "settle_s": a.settle,
           "w_base": round(w_base, 3), "w_task": round(w_task, 3), "delta_w": round(delta, 3),
           "n_base": len(base), "n_task": len(task),
           "task_min": round(min(task), 3), "task_max": round(max(task), 3),
           "base_sd": round(statistics.pstdev(base), 3), "task_sd": round(statistics.pstdev(task), 3),
           "confidence": conf, "liveness": ls,
           "baseline_samples_w": [round(x, 3) for x in base],
           "task_samples_w": [round(x, 3) for x in task]}
    log(f"  {codec} #{rep}: base {w_base:.3f} task {w_task:.3f} Δ {delta:+.3f} W "
        f"{conf.get('flag')} · media-player state={ls['playing_polls']}/{ls['polls']} 'play', "
        f"position advanced {ls['position_advances']}/{ls['position_pairs']}"
        + ("  ⚠ liveness never confirmed 'play' — check the screen, this row is suspect"
           if not ls['playing_polls'] else ""))
    return row


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--plug", required=True, help="Tapo P110 IP metering the Roku")
    p.add_argument("--roku", required=True, help="Roku's own IP (ECP port 8060)")
    p.add_argument("--out", required=True)
    p.add_argument("--n", type=int, default=1)
    p.add_argument("--window", type=int, default=60)
    p.add_argument("--settle", type=int, default=10)
    p.add_argument("--baseline", type=int, default=20)
    p.add_argument("--clips", default="h264")
    p.add_argument("--app-id", default="782875",
                   help="782875=Media Assistant (needs Channel Store install first); "
                        "15985=legacy PlayOnRoku (likely blocked on OS ≥ 11.5, try for comparison)")
    a = p.parse_args()
    codecs = [c.strip() for c in a.clips.split(",") if c.strip()]
    meter = Meter(a.plug)
    info = device_info(a.roku)
    log(f"meter {a.plug} reads {meter.read():.3f} W; Roku {info.get('friendly-device-name')} "
        f"software {info.get('software-version')}"
        + ("  ⚠ software ≥ 11-series — appId 15985 is very likely blocked, use --app-id 782875 "
           "(Media Assistant, install from the Channel Store first)"
           if a.app_id == "15985" else ""))
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    for rep in range(1, a.n + 1):
        for codec in codecs:
            row = run_row(meter, a.roku, codec, rep, a)
            with out.open("a") as f:
                f.write(json.dumps(row) + "\n")
    log("ALL DONE")


if __name__ == "__main__":
    main()
