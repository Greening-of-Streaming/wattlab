"""Portable decode-energy bench: one protocol, pluggable device drivers.

Same measurement shape as stb-decode-2026-07 (settle -> baseline -> start ->
startup skip -> sample window -> stop -> OWL confidence -> checkpoint), so new
rows are directly comparable with the July Google TV panel.

Device drivers:
  adb — Android/Google TV: launches a URL in Just Player via intent, decoder
        provenance from logcat CCodec allocations, mid-window screenshot saved
        (overlay/state provenance). Protocol fix vs July: NO `pm clear` (grants
        only), so the first-run tooltip overlay never re-appears.
  ssh — Linux boxes (Raspberry Pi 4/5): each run carries its own player/decode
        command; the harness only starts it, meters the window, and kills it.

Usage:  python3 bench.py <config.json>
Resumable: per-row checkpoint to results/<config name>.json; completed rows skip.
"""
import asyncio, json, shlex, statistics, subprocess, sys, threading, time
from pathlib import Path
from dotenv import dotenv_values

sys.path.insert(0, "/home/gos/wattlab/wattlab_service")
import confidence as owl_confidence

HERE = Path(__file__).parent
ADB_BIN = str(HERE / "tools" / "platform-tools" / "adb")
ENV = dotenv_values("/home/gos/wattlab/.env")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class Meters:
    """Primary (device) + optional context (monitor) P110, mW path, own loop thread."""
    def __init__(self, primary_ip, context_ip=None):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        from tapo import ApiClient
        self._primary_ip = primary_ip
        client = ApiClient(ENV["TAPO_EMAIL"], ENV["TAPO_PASSWORD"])
        self.primary = self._run(client.p110(primary_ip))
        self.context = self._run(client.p110(context_ip)) if context_ip else None

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=15)

    def read(self):
        p = None
        for attempt in range(5):
            try:
                p = self._run(self.primary.get_energy_usage()).current_power / 1000.0
                break
            except Exception:
                # Tapo KLAP throttle (403) or transient — back off, re-auth on the
                # last tries by rebuilding the handle, then give up (caller skips sample)
                time.sleep(2 + 2 * attempt)
                if attempt >= 2:
                    try:
                        from tapo import ApiClient
                        client = ApiClient(ENV["TAPO_EMAIL"], ENV["TAPO_PASSWORD"])
                        self.primary = self._run(client.p110(self._primary_ip))
                    except Exception:
                        pass
        c = None
        if self.context:
            try:
                c = self._run(self.context.get_energy_usage()).current_power / 1000.0
            except Exception:
                pass
        return p, c


def sample_window(meters, seconds, cadence):
    """Returns (primary_w, context_w, primary_t, context_t) — real epoch
    timestamps per sample (2026-07-30) so raw traces export as
    timestamp,alias,power_w (LEM-shaped) and marker segmentation aligns on
    wall-clock rather than assumed cadence."""
    pri, ctx, pri_t, ctx_t = [], [], [], []
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        t1 = time.monotonic()
        p, c = meters.read()
        now = time.time()
        if p is not None:
            pri.append(p)
            pri_t.append(round(now, 2))
            # live feed for the /decode progress UI (additive, 2026-07-29)
            log(f"sample {p:.3f}W" + (f" ctx={c:.2f}W" if c is not None else ""))
        if c is not None:
            ctx.append(c)
            ctx_t.append(round(now, 2))
        time.sleep(max(0, cadence - (time.monotonic() - t1)))
    return pri, ctx, pri_t, ctx_t


class AdbDevice:
    def __init__(self, cfg):
        self.adb = [ADB_BIN, "-s", cfg["serial"]]
        self.player = cfg.get("player", "com.brouken.player")
        subprocess.run(self.adb[:1] + ["connect", cfg["serial"]],
                       capture_output=True, text=True, timeout=15)

    def sh(self, *args, timeout=25):
        return subprocess.run(self.adb + ["shell"] + list(args), capture_output=True,
                              text=True, timeout=timeout).stdout

    def prepare(self, run):
        # wake first — an Asleep box takes the intent but stays in ~0.6 W standby
        for _ in range(3):
            self.sh("input", "keyevent", "KEYCODE_WAKEUP")
            time.sleep(2)
            if "mWakefulness=Awake" in self.sh("dumpsys", "power"):
                break
        else:
            raise RuntimeError("box did not wake (mWakefulness != Awake)")
        # grants only — no pm clear (avoids the July first-run overlay confound)
        for p in ("READ_EXTERNAL_STORAGE", "READ_MEDIA_AUDIO",
                  "READ_MEDIA_IMAGES", "READ_MEDIA_VIDEO"):
            self.sh("pm", "grant", self.player, f"android.permission.{p}")
        self.sh("am", "force-stop", self.player)
        self.sh("input", "keyevent", "KEYCODE_HOME")

    def start(self, run):
        subprocess.run(self.adb + ["logcat", "-c"], capture_output=True, timeout=20)
        self.sh("am", "start", "-a", "android.intent.action.VIEW", "-d", run["url"],
                "-t", "video/mp4", f"{self.player}/.PlayerActivity")

    def provenance(self, run, results_dir):
        out = subprocess.run(self.adb + ["logcat", "-d"], capture_output=True,
                             text=True, timeout=25).stdout
        codecs = sorted({l.split("allocate(")[1].split(")")[0] for l in out.splitlines()
                         if "CCodec" in l and "allocate(c2." in l})
        shot = results_dir / f"{run['name']}_midwindow.png"
        try:
            png = subprocess.run(self.adb + ["exec-out", "screencap", "-p"],
                                 capture_output=True, timeout=25).stdout
            shot.write_bytes(png)
        except Exception:
            shot = None
        return {"decoders_allocated": codecs,
                "screenshot": shot.name if shot else None}

    def still_running(self, run):
        out = self.sh("dumpsys", "media_session")
        return self.player in out

    def stop(self, run):
        self.sh("am", "force-stop", self.player)
        self.sh("input", "keyevent", "KEYCODE_HOME")


class SshDevice:
    def __init__(self, cfg):
        self.target = f"{cfg['user']}@{cfg['host']}"
        self.opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
        self.proc = None

    def sh(self, cmd, timeout=20):
        return subprocess.run(["ssh"] + self.opts + [self.target, cmd],
                              capture_output=True, text=True, timeout=timeout).stdout

    def prepare(self, run):
        if run.get("stop_cmd"):
            self.sh(run["stop_cmd"] + " || true")

    def start(self, run):
        self.proc = subprocess.Popen(["ssh"] + self.opts + [self.target, run["cmd"]],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def provenance(self, run, results_dir):
        return {"cmd": run["cmd"]}

    def still_running(self, run):
        return self.proc is not None and self.proc.poll() is None

    def stop(self, run):
        if run.get("stop_cmd"):
            self.sh(run["stop_cmd"] + " || true")
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None


class WebosDevice:
    """LG webOS native decode (CR-071): the C2's own SoC decodes + displays the
    clip via the built-in Chromium browser (a direct clip URL autoplays as a
    media document). Metered on the monitor's own plug (Lab-E), so the number is
    all-in — panel + SoC, NOT decode-isolated. Isolate decode with the
    differential method: this native run minus a GTV-on-HDMI run of the same
    clip cancels the ~80 W panel. (webOS 22 exposes no ssap screen-off, so the
    cleaner blank-panel isolation isn't available — verified 2026-07-31.)"""

    def __init__(self, cfg):
        import lg
        self.lg = lg
        self.host = cfg["host"]

    def prepare(self, run):
        # Clean idle = Home (browser closed) so the pre-baseline floor is the
        # app-shell, not a leftover decoding clip. In Always-Ready standby the
        # first call is rejected (SSAP 1008 until the panel wakes) — raw WoL,
        # then retry (2026-08-01).
        try:
            self.lg.go_home(self.host)
        except Exception:
            deadline = time.time() + 40
            while True:
                self.lg.wake()
                time.sleep(4)
                try:
                    self.lg.go_home(self.host)
                    break
                except Exception:
                    if time.time() > deadline:
                        raise

    def start(self, run):
        self.lg.launch_url(self.host, run["url"])

    def provenance(self, run, results_dir):
        return {"url": run["url"], "current_app": self.lg.current_app(self.host)}

    def still_running(self, run):
        return (self.lg.current_app(self.host) or "").endswith("browser")

    def stop(self, run):
        self.lg.go_home(self.host)


DRIVERS = {"adb": AdbDevice, "ssh": SshDevice, "webos": WebosDevice}


def wait_for_stable_idle(meters, ig, cadence):
    """Pre-baseline guard (2026-07-30, protocol v3): the SAME settle loop
    GoS1's CR-070 floor guard uses (wattlab_service/idle_wait.py), run in
    self-stability mode — a freshly booted device has no prior floor, so
    settle when the last N readings span ≤ tolerance. Configured via the
    cfg["idle_guard"] block (absent → no guard, protocol v2 behaviour)."""
    import asyncio
    import idle_wait

    async def _read():
        while True:
            p, _ = meters.read()
            if p is not None:
                return p
            await asyncio.sleep(1)

    return asyncio.run(idle_wait.wait_for_stable(
        _read, tolerance_w=ig["tolerance_w"],
        settle_polls=ig["settle_polls"], max_wait_s=ig["max_wait_s"],
        reference_w=ig.get("reference_w"),   # floor mode when known (CR-070
        poll_interval_s=cadence))            # semantics); else self-stability


def one_run(dev, meters, run, cfg, results_dir):
    cadence = cfg.get("cadence_s", 1.5)
    dev.prepare(run)
    log(f"{run['name']}: settle {cfg.get('settle_s', 15)}s")
    time.sleep(cfg.get("settle_s", 15))
    guard = None
    if cfg.get("idle_guard"):
        log(f"{run['name']}: idle-guard (tol {cfg['idle_guard']['tolerance_w']}W)")
        g = wait_for_stable_idle(meters, cfg["idle_guard"], cadence)
        guard = {"settled": g["settled"], "waited_s": g["waited_s"],
                 "final_w": g["final_w"]}
        log(f"{run['name']}: idle-guard "
            f"{'settled' if g['settled'] else 'TIMEOUT'} after {g['waited_s']}s "
            f"(final {g['final_w']}W)")
    log(f"{run['name']}: baseline {cfg.get('baseline_samples', 20)} samples @{cadence}s")
    base_p, base_c, base_pt, base_ct = sample_window(
        meters, cfg.get("baseline_samples", 20) * cadence, cadence)
    dev.start(run)
    time.sleep(cfg.get("startup_skip_s", 10))
    window = run.get("window_s", cfg["window_s"])
    log(f"{run['name']}: started — sampling {window}s")
    half = window / 2
    task_p, task_c, task_pt, task_ct = sample_window(meters, half, cadence)
    prov = dev.provenance(run, results_dir)
    p2, c2, pt2, ct2 = sample_window(meters, window - half, cadence)
    task_p += p2
    task_c += c2
    task_pt += pt2
    task_ct += ct2
    alive_at_end = dev.still_running(run)
    dev.stop(run)

    w_base = statistics.mean(base_p)
    w_task = statistics.mean(task_p)
    delta_w = w_task - w_base
    conf = owl_confidence.confidence(delta_w, len(task_p), w_base,
                                     baseline_samples_w=base_p, task_samples_w=task_p)
    row = {
        "run": run["name"], "device": cfg["device"], "provenance": prov,
        "url_or_cmd": run.get("url") or run.get("cmd"),
        "w_base": round(w_base, 3), "w_task": round(w_task, 3),
        "delta_w": round(delta_w, 3), "window_s": window,
        "wh_window_device_total": round(w_task * window / 3600, 4),
        "n_base": len(base_p), "n_task": len(task_p),
        "task_min": round(min(task_p), 3), "task_max": round(max(task_p), 3),
        "context_task_w": round(statistics.mean(task_c), 2) if task_c else None,
        # Screen-mode record (2026-07-30): the monitor's full trace, not just
        # its mean — raw samples feed the marker-head segmentation analysis.
        "context_base_w": round(statistics.mean(base_c), 2) if base_c else None,
        "context_delta_w": (round(statistics.mean(task_c)
                                  - statistics.mean(base_c), 3)
                            if task_c and base_c else None),
        "context_wh_window": (round(statistics.mean(task_c) * window / 3600, 4)
                              if task_c else None),
        "raw_context_w": [round(x, 2) for x in task_c] or None,
        "raw_context_baseline_w": [round(x, 2) for x in base_c] or None,
        "alive_at_window_end": alive_at_end,
        "confidence": {k: (round(v, 4) if isinstance(v, float) else v)
                       for k, v in conf.items() if k in
                       ("flag", "label", "method", "confidence_positive", "ci_delta_w_95")},
        "raw_baseline_w": [round(x, 3) for x in base_p],
        "raw_task_w": [round(x, 3) for x in task_p],
        # Epoch timestamps parallel to the raw arrays (2026-07-30) — feed the
        # LEM-style export and wall-clock marker segmentation.
        "raw_baseline_t": base_pt, "raw_task_t": task_pt,
        "raw_context_t": task_ct or None,
        "raw_context_baseline_t": base_ct or None,
        "idle_guard": guard,
    }
    log(f"{run['name']}: base={w_base:.2f}W task={w_task:.2f}W dW={delta_w:+.2f}W "
        f"({conf.get('flag', '?')}) alive_at_end={alive_at_end}")
    return row


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text())
    results_dir = HERE / "results"
    out = results_dir / f"{cfg['name']}.json"
    done = {}
    if out.exists():
        done = {r["run"]: r for r in json.loads(out.read_text())["rows"]}
        log(f"resuming — {len(done)} rows recorded")
    meters = Meters(cfg["meter_ip"], cfg.get("monitor_meter_ip"))
    p, c = meters.read()
    log(f"meter check: primary={p:.3f}W context={c if c is None else f'{c:.3f}W'}")
    dev = DRIVERS[cfg["device"]["type"]](cfg["device"])
    rows = list(done.values())
    for run in cfg["runs"]:
        if run["name"] in done and "error" not in done[run["name"]]:
            continue
        rows = [r for r in rows if r["run"] != run["name"]]
        try:
            rows.append(one_run(dev, meters, run, cfg, results_dir))
        except Exception as e:
            log(f"{run['name']}: EXCEPTION {e!r}")
            try:
                dev.stop(run)
            except Exception:
                pass
            rows.append({"run": run["name"], "error": repr(e)})
        out.write_text(json.dumps({
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "protocol": {k: cfg.get(k) for k in
                         ("window_s", "cadence_s", "baseline_samples",
                          "settle_s", "startup_skip_s", "idle_guard",
                          "protocol_version")},
            "config": cfg["name"], "rows": rows}, indent=1))
        time.sleep(cfg.get("gap_s", 10))
    log("ALL DONE")


main()
