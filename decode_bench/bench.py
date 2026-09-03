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
import asyncio, json, re, shlex, statistics, subprocess, sys, threading, time
import urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from dotenv import dotenv_values

sys.path.insert(0, "/home/gos/wattlab/wattlab_service")
import confidence as owl_confidence
import decode_sync

HERE = Path(__file__).parent


def _find_adb() -> str:
    """$OWL_ADB_BIN → decode_bench/tools/platform-tools/adb (a gitignored
    symlink to /srv/data/owl/decode-bench/tools — platform-tools r37.0.0, the
    binary rig.py uses) → that /srv/data path directly → PATH. The symlink
    matters because HERE differs by invocation: /srv/data/owl/decode-bench
    when the service runs bench.py through its symlink, the repo checkout when
    run by hand. 2026-08-26."""
    import os
    import shutil
    for cand in (os.environ.get("OWL_ADB_BIN"),
                 HERE / "tools" / "platform-tools" / "adb",
                 "/srv/data/owl/decode-bench/tools/platform-tools/adb",
                 shutil.which("adb")):
        if cand and Path(cand).is_file():
            return str(cand)
    return str(HERE / "tools" / "platform-tools" / "adb")   # fails loudly at first use


ADB_BIN = _find_adb()
ENV = dotenv_values("/home/gos/wattlab/.env")


_LOG_LOCK = threading.Lock()


def log(msg):
    # One write under a lock (2026-09-03): the content-clock thread logs too,
    # and print()'s two writes could interleave a "] clock" line into a
    # "] sample" line — which the service's _SAMPLE_RE would then miss.
    with _LOG_LOCK:
        sys.stdout.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        sys.stdout.flush()


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
    # Just Player version is a controlled variable, not a detail. Installed
    # 2026-09-02: Fire TV 0.196, Xiaomi Gen 2 + Gen 3 0.196 (pinned to match
    # the Fire TV), GTV 0.212-legacy (its July/Aug campaigns ran on this).
    # Onboarding the Xiaomi pair on the then-latest v0.216, the first screen-
    # mode launch sat on the app's "Choose a video to play" empty-state
    # screen while media_session reported PLAYING and decoders were genuinely
    # allocated (decode ran invisibly behind the UI, no error anywhere). It
    # reproduced once on v0.196 too, so it's an intermittent cold-start
    # glitch rather than a version regression (JOURNAL S73) — but pinning
    # the version across boxes is still the right call for any cross-device
    # comparison. Re-onboarding: install a version the fleet already runs
    # (github.com/moneytoo/Player/releases), never "latest", and take a mid-
    # window screenshot / marker row before trusting the first row.
    def __init__(self, cfg):
        self.serial = cfg["serial"]
        self.adb = [ADB_BIN, "-s", cfg["serial"]]
        self.player = cfg.get("player", "com.brouken.player")
        self.state_at_end = None
        self.start_cmd_epoch = None     # wall time of the launch intent
        self.playing_epoch = None       # first PLAYING seen after it
        subprocess.run(self.adb[:1] + ["connect", cfg["serial"]],
                       capture_output=True, text=True, timeout=15)

    def sh(self, *args, timeout=25):
        return subprocess.run(self.adb + ["shell"] + list(args), capture_output=True,
                              text=True, errors="replace", timeout=timeout).stdout

    # --- keep-awake + play-verify (2026-08-16, the "playback dies mid-window"
    # forensics; JOURNAL S61/S62). Three independent killers were found:
    #   · Android TV inattentive SLEEP timer (secure sleep_timeout; GTV default
    #     1 200 000 ms = the 20-min death) — fires even while the player holds
    #     keep-screen-on;
    #   · screensaver (system screen_off_timeout; Fire TV default 300 000 ms =
    #     the 5-min death) — held off only while the player is actually PLAYING;
    #   · GTV CEC "active source lost" → standby_now (box sleeps 30 s after the
    #     TV/another source asserts Active Source; caught live: PowerManager
    #     "Going to sleep due to hdmi").
    # And Just Player launched by VIEW intent can come up PAUSED at a remembered
    # position (seen on both boxes) — the old still_running() only checked the
    # session existed, so a paused player counted as "alive".
    KEEP_AWAKE = (("secure", "sleep_timeout", "-1"),
                  ("system", "screen_off_timeout", "2147460000"))

    def ensure_keep_awake(self):
        """Idempotent: pin the box's sleep/screensaver timers to never and
        (where the shell command exists) stop CEC active-source-lost standby.
        Returns what was applied — recorded in provenance so a factory reset
        or firmware update that reverts it is visible in the row."""
        applied = {}
        for ns, key, val in self.KEEP_AWAKE:
            cur = self.sh("settings", "get", ns, key).strip()
            if cur != val:
                self.sh("settings", "put", ns, key, val)
                cur = self.sh("settings", "get", ns, key).strip()
            applied[f"{ns}.{key}"] = cur
        out = self.sh("cmd", "hdmi_control", "cec_setting", "get",
                      "power_state_change_on_active_source_lost")
        if "=" in out:
            if "none" not in out:
                self.sh("cmd", "hdmi_control", "cec_setting", "set",
                        "power_state_change_on_active_source_lost", "none")
                out = self.sh("cmd", "hdmi_control", "cec_setting", "get",
                              "power_state_change_on_active_source_lost")
            applied["cec.power_state_change_on_active_source_lost"] = out.split("=")[-1].strip()
        return applied

    def playback_state(self):
        """Just Player's media-session state: 'PLAYING' | 'PAUSED' | 'BUFFERING'
        | 'STOPPED' | 'ERROR' | 'NONE' | None (no session). Handles both dumpsys
        formats: Android 14 'state=PLAYING(3)' and Android 11 'state=3'."""
        out = self.sh("dumpsys", "media_session")
        names = {"0": "NONE", "1": "STOPPED", "2": "PAUSED", "3": "PLAYING",
                 "6": "BUFFERING", "7": "ERROR"}
        best = None
        block = False
        for line in out.splitlines():
            if "package=" in line:
                block = self.player in line
            if block and "state=PlaybackState" in line and "{state=" in line:
                tok = line.split("{state=")[1].split(",")[0].strip()
                num = tok.split("(")[-1].rstrip(")") if "(" in tok else tok
                st = names.get(num, tok)
                if st == "PLAYING":
                    return "PLAYING"
                best = best or st
        return best

    def content_position(self):
        """Content clock sample (2026-09-03): the player's media-session
        position, extrapolated with the box's own uptime read in the SAME
        shell call (media3 freezes `position` between state changes — see
        decode_sync). One short-timeout call; never reconnects adb (that is
        still_running()'s job). None when there is no session/uptime."""
        t0 = time.time()
        try:
            out = self.sh("dumpsys media_session; echo "
                          f"{decode_sync.UPTIME_MARK}; cat /proc/uptime",
                          timeout=10)
        except subprocess.TimeoutExpired:
            return None
        t1 = time.time()
        ps = decode_sync.parse_media_session(out, self.player)
        up = decode_sync.parse_uptime_ms(out)
        if not ps or up is None:
            return None
        return {"t": (t0 + t1) / 2, "dt": t1 - t0,
                "pos_s": decode_sync.extrapolate_position_s(ps, up),
                "state": ps["state"], "speed": ps["speed"]}

    def prepare(self, run):
        # wake first — an Asleep box takes the intent but stays in ~0.6 W standby
        for _ in range(3):
            self.sh("input", "keyevent", "KEYCODE_WAKEUP")
            time.sleep(2)
            if "mWakefulness=Awake" in self.sh("dumpsys", "power"):
                break
        else:
            raise RuntimeError("box did not wake (mWakefulness != Awake)")
        self.keep_awake = self.ensure_keep_awake()
        # grants only — no pm clear (avoids the July first-run overlay confound)
        for p in ("READ_EXTERNAL_STORAGE", "READ_MEDIA_AUDIO",
                  "READ_MEDIA_IMAGES", "READ_MEDIA_VIDEO"):
            self.sh("pm", "grant", self.player, f"android.permission.{p}")
        self.sh("am", "force-stop", self.player)
        self.sh("input", "keyevent", "KEYCODE_HOME")
        # Optional per-run device-side setup (2026-08-18, network-path arms):
        # a list of adb shell command strings run before the baseline.
        for c in run.get("pre_shell", []) or []:
            self.sh(*shlex.split(c))
        if run.get("pre_wait_s"):
            time.sleep(float(run["pre_wait_s"]))

    def start(self, run):
        # Grow the ring buffer before clearing it: a Xiaomi logs ~5k lines a
        # minute, so on the 30-min looped-clip windows the decoder allocation
        # had scrolled out long before the mid-window provenance read (every
        # 4K HEVC row came back with decoders_allocated=[] on 2026-09-03).
        # 32 MB holds well over an hour; boxes that cap the size just keep
        # their default (the call is best-effort).
        subprocess.run(self.adb + ["logcat", "-G", "32M"], capture_output=True, timeout=20)
        subprocess.run(self.adb + ["logcat", "-c"], capture_output=True, timeout=20)
        # --ei position 0: Just Player honours a `position` extra (ms) — defeats
        # its remembered-position resume so every row starts at the head.
        self.start_cmd_epoch = time.time()
        self.playing_epoch = None
        self.sh("am", "start", "-a", "android.intent.action.VIEW", "-d", run["url"],
                "-t", "video/mp4", "--ei", "position", "0",
                f"{self.player}/.PlayerActivity")
        # Verify it is actually PLAYING; a paused launch gets one play press
        # (MEDIA_PLAY is play-not-toggle: harmless if it did start).
        self.play_presses = 0
        # 30 s budget: the Bbox sits in BUFFERING for >12 s on a cold HTTP
        # start (a 12 s budget killed a healthy row on 2026-08-16 — the raise
        # message itself then read PLAYING). BUFFERING is progress, not paused.
        deadline = time.time() + 30
        while time.time() < deadline:
            st = self.playback_state()
            if st == "PLAYING":
                self.playing_epoch = time.time()
                return
            if st in ("PAUSED", "NONE", "STOPPED") and self.play_presses < 2:
                self.sh("input", "keyevent",
                        "KEYCODE_MEDIA_PLAY" if self.play_presses == 0
                        else "KEYCODE_DPAD_CENTER")
                self.play_presses += 1
                log(f"{run['name']}: player {st} after launch — pressed play "
                    f"({self.play_presses})")
                time.sleep(3)
                continue
            time.sleep(1)
        st = self.playback_state()          # one last look before failing the row
        if st == "PLAYING":
            self.playing_epoch = time.time()
            return
        raise RuntimeError(f"player not PLAYING after launch (state={st})")

    def provenance(self, run, results_dir):
        # errors="replace": the Bbox emitted a non-UTF-8 byte in logcat and the
        # default strict decode killed a finished 1 h row (2026-08-15).
        out = subprocess.run(self.adb + ["logcat", "-d"], capture_output=True,
                             text=True, errors="replace", timeout=25).stdout
        # Codec2 (CCodec) devices log "allocate(c2.foo.bar)"; older Amlogic
        # boxes on Android 11 (Gen 2 Xiaomi, confirmed 2026-09-02) still run
        # the legacy OMX IL HAL instead and never emit a CCodec line at all —
        # missing this made a genuinely hw-decoding box look like it had no
        # video decoder allocated (only the audio c2 line showed). Codec name
        # itself (e.g. OMX.amlogic.avc.decoder.awesome2) still proves hw
        # decode; caught via any "OMX.<vendor>...." token in an OmxComponent
        # line, same dedup treatment as the c2 names.
        # OMX.google.android.index.* are extension-index names logged by the
        # same HAL, not decoders — drop them (they buried the real component
        # in a 14-item list on the first rows, 2026-09-03).
        # The OMX name is not always on an OmxComponent line: Gen 2's AV1
        # decoder only ever appeared as "MediaCodec: [OMX.amlogic.av1.decoder
        # .awesome2] setting surface generation" (60 s probe, 2026-09-03), so
        # MediaCodec-tagged lines are scanned too.
        codecs = sorted({l.split("allocate(")[1].split(")")[0] for l in out.splitlines()
                         if "CCodec" in l and "allocate(c2." in l}
                        | {m for l in out.splitlines()
                           if "OmxComponent" in l or "MediaCodec" in l
                           for m in re.findall(r"OMX\.(?!google\.android\.index\.)[\w.]+", l)})
        # Per-device filename: three adb boxes in one parallel run used to
        # overwrite each other's `<run>_midwindow.png` (2026-08-15).
        tag = self.adb[-1].replace(":", "_").replace(".", "-")
        shot = results_dir / f"{run['name']}_{tag}_midwindow.png"
        try:
            png = subprocess.run(self.adb + ["exec-out", "screencap", "-p"],
                                 capture_output=True, timeout=25).stdout
            # The Bbox (MediaTek) prepends "<<<<< OSAL Init / MV_Time_Init OK."
            # text before the PNG header — strip to the real image.
            i = png.find(b"\x89PNG")
            if i > 0:
                png = png[i:]
            shot.write_bytes(png)
        except Exception:
            shot = None
        return {"decoders_allocated": codecs,
                "screenshot": shot.name if shot else None,
                "playback_state_midwindow": self.playback_state(),
                "play_presses_after_launch": getattr(self, "play_presses", None),
                "keep_awake": getattr(self, "keep_awake", None)}

    def still_running(self, run):
        # PLAYING only — a paused/errored player with a live session used to
        # count as alive (alive_at_window_end lied on the 2026-08-15 rows).
        # 2026-08-18: the Fire TV (Wi-Fi ADB) answered "not PLAYING" at the end
        # of 24/30 windows whose power traces were flat to the last second and
        # that answered PLAYING on every out-of-harness poll — so retry a few
        # times, reconnect ADB if the dump came back empty, and RECORD what was
        # seen (row.playback_state_at_end) so a False is diagnosable.
        seen = []
        for attempt in range(3):
            st = self.playback_state()
            seen.append(st)
            if st == "PLAYING":
                self.state_at_end = "PLAYING" if attempt == 0 else f"PLAYING (after {seen[:-1]})"
                return True
            if st is None:   # empty/failed dumpsys → ADB hiccup: reconnect once
                subprocess.run([ADB_BIN, "connect", self.serial],
                               capture_output=True, text=True, timeout=15)
            time.sleep(3)
        self.state_at_end = str(seen)
        return False

    def stop(self, run):
        self.sh("am", "force-stop", self.player)
        self.sh("input", "keyevent", "KEYCODE_HOME")


class SshDevice:
    def __init__(self, cfg):
        self.target = f"{cfg['user']}@{cfg['host']}"
        # -o HostName pins the address: ~/.ssh/config on GoS1 aliases the Pi's
        # Wi-Fi IP to its Ethernet IP, which silently sent every "Wi-Fi" ssh
        # over eth0 (2026-08-18) — and a config alias must never decide which
        # interface a measurement rides on.
        self.opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                     "-o", f"HostName={cfg['host']}"]
        self.proc = None

    def sh(self, cmd, timeout=20):
        return subprocess.run(["ssh"] + self.opts + [self.target, cmd],
                              capture_output=True, text=True, timeout=timeout).stdout

    def prepare(self, run):
        if run.get("stop_cmd"):
            self.sh(run["stop_cmd"] + " || true")
        # Optional per-run host-side setup (2026-08-18, network-path arms):
        # e.g. `sudo nmcli dev disconnect eth0` before a Wi-Fi arm.
        if run.get("pre_cmd"):
            self.sh(run["pre_cmd"] + " || true", timeout=60)
        if run.get("pre_wait_s"):
            time.sleep(float(run["pre_wait_s"]))

    def start(self, run):
        self.proc = subprocess.Popen(["ssh"] + self.opts + [self.target, run["cmd"]],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def provenance(self, run, results_dir):
        # Mid-window record of the host's active interfaces (network-path
        # arms, 2026-08-18): proves which link carried the traffic.
        ifaces = self.sh("ip -o -4 addr show | awk '{print $2, $4}' | tr '\\n' ' '").strip()
        return {"cmd": run["cmd"], "ifaces_midwindow": ifaces or None}

    def still_running(self, run):
        return self.proc is not None and self.proc.poll() is None

    def stop(self, run):
        if run.get("stop_cmd"):
            self.sh(run["stop_cmd"] + " || true")
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None
        if run.get("post_cmd"):     # e.g. restore the interface dropped in pre_cmd
            self.sh(run["post_cmd"] + " || true", timeout=60)


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
        # The C2's SSAP connect intermittently fails under a multi-device
        # start (lg._with_client already retries the connect 3×; a whole
        # launch still failed 2026-08-15 with a bare TimeoutError). One more
        # full attempt after a pause before the row is declared lost.
        try:
            self.lg.launch_url(self.host, run["url"])
        except Exception as e:
            # SSAP 1008 / timeout here = the panel dropped into Always-Ready
            # standby between prepare and start (lost meridian_h264 C2 row,
            # 2026-08-17). Wake it (raw WoL) and retry for up to 40 s.
            log(f"{run['name']}: webOS launch failed ({e!r}) — waking + retrying")
            deadline = time.time() + 40
            while True:
                self.lg.wake()
                time.sleep(4)
                try:
                    self.lg.launch_url(self.host, run["url"])
                    break
                except Exception:
                    if time.time() > deadline:
                        raise

    def provenance(self, run, results_dir):
        return {"url": run["url"], "current_app": self.lg.current_app(self.host)}

    def still_running(self, run):
        return (self.lg.current_app(self.host) or "").endswith("browser")

    def stop(self, run):
        self.lg.go_home(self.host)


class AtvDevice:
    """Apple TV over pyatv (CR-075, 2026-08-26). AirPlay `play_url` is dead on
    tvOS 18 (the receiver accepts POST /play, then 500s GET /playback-info and
    never fetches — pyatv #2403), so playback is VLC for tvOS launched by the
    Companion protocol with VLC's x-callback stream scheme; VLC fetches the
    clip URL from the origin with Range requests. One-time on-screen "Open
    VLC?" confirmation on the remote the first time (already accepted on the
    rig box).

    ⚠ Companion command reliability, 2026-08-29 (real, live-confirmed, not
    guessed): `atv("stop")` does NOT reliably halt VLC playback — confirmed
    twice live, with direct visual confirmation the video kept playing
    minutes after `stop` was sent. `park()` now uses `atv("home")` instead,
    which DID reliably stop it in the same test. Separately (and more
    seriously): pyatv's own `playing` query reported "Idle" BOTH times while
    the video was actually still playing — so `still_running()`'s liveness
    check (below) may give false NEGATIVES (reporting a row dead when it was
    genuinely still playing), not just miss genuine failures. No better
    liveness signal is currently known for this device — no
    screenshot/logcat equivalent exists, unlike the Android boxes. Treat any
    `alive_at_window_end: False` on this device with real skepticism, not as
    settled fact, until a more reliable signal is found.

    Baseline state is the tvOS Home Screen (via `home`, not "VLC's library
    screen" as originally assumed — that assumption predates the `stop`→
    `home` fix and hasn't been re-verified against the new park() behaviour).
    The home screen can itself show elevated states (ambient previews 6-15 W,
    an occasional AirPlay promotional overlay to ~6 W) — a harness choice,
    recorded in provenance. Rows are "VLC on tvOS", not the native player —
    say so when quoting."""

    ATVREMOTE = ("/srv/data/owl/pyatv-venv/bin/atvremote", "/tmp/pyatv-venv/bin/atvremote")
    CREDS = Path("/srv/data/owl/atv")

    def __init__(self, cfg):
        self.host = cfg["host"]
        self.bin = next((b for b in self.ATVREMOTE if Path(b).is_file()), None)
        if not self.bin:
            raise RuntimeError("atvremote not installed (pyatv venv missing)")
        self.cc = (self.CREDS / "companion_creds").read_text().strip()
        self.ac = (self.CREDS / "airplay_creds").read_text().strip()
        self.state_at_end = None

    def atv(self, *cmds, timeout=45):
        r = subprocess.run([self.bin, "-s", self.host, "--companion-credentials", self.cc,
                            "--airplay-credentials", self.ac, *cmds],
                           capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")

    def playing(self):
        out = self.atv("playing", "app", timeout=35)
        d = {"state": None, "position_s": None, "title": None, "app": None}
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

    def park(self):
        # 2026-08-29: switched from `atv("stop")` to `atv("home")` — CONFIRMED
        # LIVE that `stop` does not reliably halt VLC playback (twice, with
        # direct visual confirmation both times: video kept playing minutes
        # after `stop` was sent, with pyatv's OWN `playing` query wrongly
        # reporting "Idle" throughout — so `still_running()`'s liveness check
        # may also be unreliable, not just this). `home` DID reliably stop it
        # in the same live test. Baseline state is therefore the tvOS Home
        # Screen now, not "VLC stopped on its library screen" (the old
        # rationale below, kept for the wattage figures which are still
        # believed accurate for a clean idle floor — not re-verified against
        # this specific park() change yet).
        #
        # Old rationale (VLC-stopped baseline): NOT the tvOS Settings app —
        # on tvOS 26.6 launching Settings pushes the box from ~2.2 W to
        # ~5.7 W for tens of seconds (it goes off checking things) — that was
        # the "screensaver ramp" of 2026-08-26. VLC-stopped was 2.15–2.3 W
        # flat. (2026-08-29 re-characterization found the REAL floor sits
        # ~2.9-3.1 W on tvOS 26.6 regardless — see rig.py's atv idle_w note.)
        self.atv("home")

    def prepare(self, run):
        self.state_at_end = None
        self.atv("turn_on")       # asleep between rows is normal headless (tvOS sleeps in minutes)
        self.park()

    def start(self, run):
        self.atv(f"launch_app=vlc-x-callback://x-callback-url/stream?url={run['url']}")

    def provenance(self, run, results_dir):
        p = self.playing()
        return {"url": run["url"], "player": "VLC for tvOS via Companion launch_app",
                "baseline_state": "VLC stopped (library screen)", "playback_state_midwindow": p}

    def still_running(self, run):
        p = self.playing()
        self.state_at_end = p
        return p.get("state") == "Playing"

    def stop(self, run):
        self.park()


class RokuDevice:
    """Roku over ECP (2026-08-29 onboarding). No ADB/logcat equivalent — the
    only remote-control surface is ECP (port 8060), which needs "Control by
    mobile apps" set to Permissive on the box (confirmed live, 2026-08-29:
    Default/Disabled 403s a plain keypress).

    Playback is Dom's own "Greening of Streaming" Roku channel (app id
    775528, already installed, built for hackathons, dormant ~1 year) — NOT
    the Media Assistant community hack this class used before. Dom's app is
    a simple .m3u playlist player: its playlist-URL setting must be pointed
    at a LOCAL playlist ONE TIME (its old default, one of Dom's personal
    domains, is dead — that's what caused every earlier attempt here to
    404) — set in the app's own on-screen settings to PLAYLIST_URL below;
    ECP has no known way to change that setting itself, so re-pointing it is
    a manual on-device step if it's ever lost. From then on this driver
    rewrites PLAYLIST_PATH's CONTENT to a single-entry playlist for each
    row's clip before every launch — the app re-fetches its (unchanged) URL
    fresh each launch, so the file swap is enough; no per-row on-device
    action needed.

    Menu navigation (all found live, 2026-08-29, and NOT obviously
    guessable): after launch the app needs ~2s before input lands — too
    early and keypresses are silently dropped. Default focus sits 4 rows
    above the first playable item regardless of playlist length (a
    single-item playlist does NOT start pre-focused on that item). One
    Select then enters the track view; a SECOND Select is what actually
    launches playback — structural, still required even with only one
    entry. Playback then starts WINDOWED, not full-screen; one more
    keypress expands it — confirmed "Right" from this exact nav path (an
    earlier, differently-reached windowed state needed "Left" instead, so
    this is state-path-dependent, not a fixed toggle — re-verify if the nav
    sequence above ever changes). No ECP parameter was found to jump
    straight to a track or skip any of this.
    Liveness = /query/media-player state + position — no screenshot/logcat
    equivalent, same evidentiary tier as the Apple TV (AtvDevice)."""

    APP_ID = "775528"   # Dom's "Greening of Streaming" channel
    PLAYLIST_PATH = Path("/srv/data/owl/decode-bench/streams/gos_local_test.m3u")
    PLAYLIST_URL = "http://192.168.1.62:8123/gos_local_test.m3u"   # set ONCE in the app's settings

    def __init__(self, cfg):
        self.host = cfg["host"]
        self.state_at_end = None

    def _ecp(self, method, path, params=None, timeout=10):
        qs = ("?" + urllib.parse.urlencode(params)) if params else ""
        req = urllib.request.Request(f"http://{self.host}:8060{path}{qs}", method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def _key(self, name):
        self._ecp("POST", f"/keypress/{name}")

    def _state(self):
        try:
            root = ET.fromstring(self._ecp("GET", "/query/media-player"))
        except Exception as e:
            return {"state": f"ERR {type(e).__name__}"}
        d = {"state": root.get("state"), "error": root.get("error")}
        pos = root.find("position")
        if pos is not None and pos.text:
            try:
                d["position_s"] = int(pos.text.strip().rstrip("ms").strip()) / 1000.0
            except ValueError:
                pass
        return d

    def content_position(self):
        """Content clock sample (2026-09-03): ECP reports the live player
        position directly — no extrapolation needed."""
        t0 = time.time()
        st = self._state()
        t1 = time.time()
        if st.get("position_s") is None:
            return None
        return {"t": (t0 + t1) / 2, "dt": t1 - t0, "pos_s": st["position_s"],
                "state": "PLAYING" if st.get("state") == "play"
                         else str(st.get("state")).upper(),
                "speed": 1.0}

    def prepare(self, run):
        self.state_at_end = None
        self._key("Home")

    def start(self, run):
        # No known launch-time override for the app's playlist URL itself —
        # instead, rewrite the (already-configured) playlist's CONTENT to a
        # single entry for THIS row's clip; the app re-fetches its URL fresh
        # on every launch, so this is enough to steer which clip plays
        # without ever touching the app's on-screen settings again.
        self.PLAYLIST_PATH.write_text(
            f"#EXTM3U\n#EXTINF:-1,{run['name']}\n{run['url']}\n")
        self._ecp("POST", f"/launch/{self.APP_ID}")
        time.sleep(3)          # app is ready in ~2s (found live, 2026-08-29); small margin
        for _ in range(4):     # default focus sits 4 rows above the first playable
            self._key("Down")  # item (found live, 2026-08-29, physical remote) — NOT
            time.sleep(0.5)    # item 0 of the playlist; a single-item .m3u still needs this
        self._key("Select")   # enters the track list (still true with only 1 entry)
        time.sleep(2)
        self._key("Select")   # a SECOND confirm actually launches it (found live, 2026-08-29 —
        time.sleep(2)          # structural, not about list size: still needed with 1 item)
        self._key("Right")    # windowed -> full-screen (found live, 2026-08-29; NOT "Left" —
                               # that was true for a different nav path reached manually earlier)

    def provenance(self, run, results_dir):
        return {"url": run["url"],
                "player": f"Dom's Greening-of-Streaming channel (ECP launch/{self.APP_ID}, "
                          "playlist-driven — see class docstring)",
                "playback_state_midwindow": self._state()}

    def still_running(self, run):
        st = self._state()
        self.state_at_end = st
        return st.get("state") == "play"

    def stop(self, run):
        self._key("Home")


DRIVERS = {"adb": AdbDevice, "ssh": SshDevice, "webos": WebosDevice, "atv": AtvDevice,
           "roku": RokuDevice}


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


def _clock_loop(poll, every_s, stop, out, run_name):
    """Content-clock thread (2026-09-03; shape from roku_probe.py's liveness
    thread): call the driver's content_position() every `every_s` and append
    [t, pos_s, state, dt]. Runs beside the meter loop — they share nothing but
    stdout (log() is locked). Never raises; a failed poll is a None row."""
    while not stop.is_set():
        try:
            s = poll()
        except Exception:
            s = None
        if s:
            out.append([round(s["t"], 2),
                        round(s["pos_s"], 3) if s.get("pos_s") is not None else None,
                        s.get("state"), round(s.get("dt") or 0, 2)])
            log(f"clock pos={out[-1][1]} state={s.get('state')}")
        else:
            out.append([round(time.time(), 2), None, None, None])
            log("clock pos=None state=None")
        stop.wait(every_s)


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
    # Synchronised start (2026-09-03): the other devices of this job are
    # separate processes — meet them at a file barrier right before launch.
    # Log wording must avoid the service's phase tokens (": settle ",
    # ": baseline ", ": started", ": base=").
    sync = None
    if cfg.get("sync"):
        log(f"{run['name']}: sync waiting for "
            f"{len(cfg['sync'].get('peers', [])) - 1} peers")
        sync = decode_sync.rendezvous(cfg["sync"], run["name"], log=log)
    dev.start(run)
    # Content clock (2026-09-03): poll the player's position beside the meter
    # loop so every power sample can be mapped to content time afterwards.
    clock, stop_clock, clock_th = [], threading.Event(), None
    cc = cfg.get("content_clock")
    poll = getattr(dev, "content_position", None)
    if cc and poll:
        clock_th = threading.Thread(
            target=_clock_loop,
            args=(poll, float(cc.get("every_s", 2.0)), stop_clock, clock,
                  run["name"]),
            daemon=True)
        clock_th.start()
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
    if clock_th:
        stop_clock.set()          # before still_running(): it may adb-reconnect
        clock_th.join(timeout=15)
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
        "playback_state_at_end": getattr(dev, "state_at_end", None),
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
        # Synchronised-start + content-clock record (2026-09-03). The clock
        # list gets the raw_ prefix on purpose: the service single-stores
        # raw_* arrays in runs[] and keeps only the summary in devices[].rows.
        "sync": sync,
        "start_cmd_epoch": getattr(dev, "start_cmd_epoch", None),
        "playing_epoch": getattr(dev, "playing_epoch", None),
        "raw_content_clock": clock or None,
        "content_clock": ({**cc, **decode_sync.clock_summary(clock)}
                          if cc and clock_th else None),
    }
    log(f"{run['name']}: base={w_base:.2f}W task={w_task:.2f}W dW={delta_w:+.2f}W "
        f"({conf.get('flag', '?')}) alive_at_end={alive_at_end}")
    return row


# OWL's /decode idle auto-off (rig.py) stops every powered box after N hours
# without activity. A standalone CLI campaign is invisible to the service, so
# each row touches this hold file — rig.py treats a fresh mtime as activity
# (stale after 30 min, so a crashed campaign can't pin the rig on).
RIG_HOLD_FILE = Path("/tmp/owl-rig-hold")


def _touch_rig_hold():
    try:
        RIG_HOLD_FILE.touch()
    except OSError:
        pass


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
        _touch_rig_hold()   # tell OWL's idle auto-off a campaign is live
        try:
            rows.append(one_run(dev, meters, run, cfg, results_dir))
        except Exception as e:
            import traceback
            log(f"{run['name']}: EXCEPTION {e!r}")
            # Persist WHERE it failed: a bare TimeoutError() from a webOS
            # connect vs a meter read vs a player launch are different faults
            # (2026-08-15 C2 row was undiagnosable from `TimeoutError()` alone).
            tb = traceback.extract_tb(e.__traceback__)
            where = [f"{f.name}:{f.lineno}" for f in tb[-4:]]
            try:
                dev.stop(run)
            except Exception:
                pass
            if cfg.get("sync"):
                # Tell the peers at the start barrier not to wait for us.
                try:
                    Path(cfg["sync"]["dir"], f"{cfg['sync']['self']}.abort").touch()
                except OSError:
                    pass
            rows.append({"run": run["name"], "error": repr(e),
                         "error_where": where,
                         "error_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        out.write_text(json.dumps({
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "protocol": {k: cfg.get(k) for k in
                         ("window_s", "cadence_s", "baseline_samples",
                          "settle_s", "startup_skip_s", "idle_guard",
                          "protocol_version")},
            "config": cfg["name"], "rows": rows}, indent=1))
        time.sleep(cfg.get("gap_s", 10))
    _touch_rig_hold()   # the campaign's own end is the last activity
    log("ALL DONE")


if __name__ == "__main__":
    main()
