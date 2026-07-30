"""
rig.py — client-decode rig power control (/decode page backend).

The rig is three playback devices (Pi 5, Pi 400, Google TV Streamer), each
powered through its own Tapo P110 "Lab" plug, sharing one 4K monitor (its own
plug), plus an optional Shelly "master" switch feeding the strip that powers
the three device plugs. Devices are OFF by default; the monitor auto-switches
to the single live HDMI signal, so the screen follows whichever one device is
powered (verified 2026-07-29, see decode-bench README on GoS1).

This module owns:
  RIG            — the rig topology (devices, plugs, boot expectations).
  plug_status()/plug_set()      — Tapo control for arbitrary plug IPs
                                  (power.py's cache+lock pattern, generalised;
                                  power.py itself stays meter-only).
  shelly_status()/shelly_set()  — master switch; Gen1/Gen2+ auto-detected.
  rig_cache + rig_poller()      — background state machine driving the tiles.
  device_on()/device_off()/device_cycle(), monitor_power(), master_power().

State machine per device (tile colour in parentheses):
  off (red) → powering (orange: relay on, draw < boot threshold)
            → booting  (orange: draw up, ready-probe failing; progress bar)
            → ready    (green) [→ busy badge while a decode job runs]
  graceful stop: stopping (orange: ssh shutdown/adb reboot -p → wait → relay
  off) → off.  Probe not passing within 3× expected boot → stuck (red+badge).
  Master OFF ⇒ device plugs are unpowered/unreachable → unpowered (grey) —
  a modelled state, not an error.

⚠ HAZARD (do not "fix"): the Tapo at 192.168.1.35 (Lab-C) powers the Bouygues
ROUTER. It must never appear in this config or any control surface — relay-off
would kill the LAN including the path to turn it back on. A guard test greps
every /decode response for that IP.

All ssh/adb/Shelly subprocess+HTTP calls run via asyncio.to_thread — never on
the event loop. Tests monkeypatch the module-level IO functions (plug_status,
plug_set, shelly_status, shelly_set, probe_ready, send_shutdown).
"""
import asyncio
import json
import logging
import subprocess
import time
import urllib.request
from dotenv import dotenv_values

log = logging.getLogger(__name__)

_config = dotenv_values("/home/gos/wattlab/.env")

ADB_BIN = "/srv/data/owl/decode-bench/tools/platform-tools/adb"

# --- Rig topology -----------------------------------------------------------
#
# plug_ip may be a list of candidate IPs (first that answers wins, cached) —
# Lab-D has a pending DHCP reservation move (.1 → .36), so both are listed
# until the plug's lease renews. expected_boot_s: pi5 measured 2026-07-29;
# pi400/gtv are placeholders until the first live verification measures them.
RIG: dict = {
    "devices": {
        "pi5": {
            "label": "Pi 5", "plug_name": "Lab-A",
            "plug_ip": "192.168.1.146",
            "kind": "ssh", "target": "admin@192.168.1.102",
            "expected_boot_s": 29, "boot_threshold_w": 1.0,
            "shutdown_wait_s": 22,
            # Known settled idle (W) — the decode guard's reference floor
            # (stability alone settles on post-boot plateaus; see the
            # 2026-07-30 negative-ΔW row that motivated this).
            "idle_w": 3.4,
        },
        "pi400": {
            "label": "Pi 400", "plug_name": "Lab-B",
            "plug_ip": "192.168.1.31",
            "kind": "ssh", "target": "nebul2@192.168.1.108",
            "expected_boot_s": 45, "boot_threshold_w": 1.0,
            "shutdown_wait_s": 22,
            "idle_w": 3.0,
        },
        "gtv": {
            "label": "Google TV", "plug_name": "Lab-D",
            "plug_ip": "192.168.1.36",
            # The owner's re-pinned reservation (.126, the July address) took
            # effect on the 2026-07-30 boot — the interim .189 lease is dead.
            # The "stuck/no-network" episode was this address move mid-flight.
            "kind": "adb", "target": "192.168.1.126:5555",
            "expected_boot_s": 90, "boot_threshold_w": 0.4,
            "shutdown_wait_s": 15,
            "idle_w": 1.0,
        },
    },
    "monitor": {
        "label": "4K monitor", "plug_name": "Lab-E",
        "plug_ip": "192.168.1.71",
        # Above this draw the panel is showing a picture — could be Ben's Mac
        # extension, so the Off button asks for confirmation client-side.
        "in_use_threshold_w": 15.0,
    },
    # Shelly on the Lab-A/B/D strip. None ⇒ master tile absent. Settings key
    # rig_shelly_ip overrides. Generation AND capability are auto-detected:
    # the installed unit (2026-07-29) is a Plug PM Gen3 (S3PL-30116EU) — a
    # 16 A pass-through METER with no relay (RPC exposes PM1.*, no Switch.*),
    # so the tile is strip-metering only; swap in a relay model (Plug S,
    # 1PM) and the Rig on/off button appears without a code change.
    "shelly_ip": "192.168.1.17",
    "tapo_standby_w": 0.65,   # per-plug standby the master switch saves
}

_STOPPED_STATES = ("off", "unpowered", "unreachable")


def shelly_ip() -> str | None:
    """Configured Shelly master IP — settings key `rig_shelly_ip` wins over the
    RIG constant so Ben can enable the master from /settings without a deploy."""
    try:
        import settings as _cfg
        return (_cfg.load().get("rig_shelly_ip") or "").strip() or RIG["shelly_ip"]
    except Exception:
        return RIG["shelly_ip"]


# --- Tapo plug control (arbitrary IPs) --------------------------------------
#
# Same recovery pattern as power.py's _read_meter_watts: cached handle per IP,
# per-IP asyncio lock (KLAP sessions are exclusive), drop + rebuild on error.
# Separate caches from power.py — the bench meter must never share a handle.

_PLUG_CACHE: dict = {}
_PLUG_LOCKS: dict = {}
_RESOLVED_IP: dict = {}   # device plug key → the candidate IP that answered

# Plug IPs a running measurement owns right now (Stage 2 sets this while
# bench.py samples at 1.5 s) — the rig poller skips these entirely so it never
# contends for the KLAP session mid-row.
PAUSED_PLUGS: set = set()


async def _plug_handle(ip: str):
    from tapo import ApiClient
    device = _PLUG_CACHE.get(ip)
    if device is None:
        client = ApiClient(_config["TAPO_EMAIL"], _config["TAPO_PASSWORD"])
        device = await client.p110(ip)
        _PLUG_CACHE[ip] = device
    return device


async def _resolve_ip(plug_ip) -> str:
    """plug_ip may be one IP or a candidate list; return the first that
    answers (cached until it stops answering)."""
    if isinstance(plug_ip, str):
        return plug_ip
    key = tuple(plug_ip)
    cached = _RESOLVED_IP.get(key)
    order = ([cached] + [ip for ip in plug_ip if ip != cached]) if cached else list(plug_ip)
    last_err = None
    for ip in order:
        try:
            lock = _PLUG_LOCKS.setdefault(ip, asyncio.Lock())
            async with lock:
                d = await asyncio.wait_for(_plug_handle(ip), 8)
                await asyncio.wait_for(d.get_device_info(), 8)
            _RESOLVED_IP[key] = ip
            return ip
        except Exception as e:
            _PLUG_CACHE.pop(ip, None)
            last_err = e
    raise last_err or RuntimeError(f"no plug answered at {plug_ip}")


async def plug_status(plug_ip, retries: int = 2) -> dict:
    """{"on": bool, "watts": float, "ip": str} for the plug at plug_ip
    (str or candidate list). Raises on total failure — callers map that to
    unreachable/unpowered."""
    ip = await _resolve_ip(plug_ip)
    lock = _PLUG_LOCKS.setdefault(ip, asyncio.Lock())
    for attempt in range(retries):
        try:
            async with lock:
                d = await _plug_handle(ip)
                info = await asyncio.wait_for(d.get_device_info(), 10)
                energy = await asyncio.wait_for(d.get_energy_usage(), 10)
            return {"on": bool(info.device_on),
                    "watts": energy.current_power / 1000.0, "ip": ip}
        except Exception:
            _PLUG_CACHE.pop(ip, None)
            if attempt == retries - 1:
                raise
            await asyncio.sleep(1)


async def plug_set(plug_ip, on: bool, retries: int = 2) -> None:
    ip = await _resolve_ip(plug_ip)
    lock = _PLUG_LOCKS.setdefault(ip, asyncio.Lock())
    for attempt in range(retries):
        try:
            async with lock:
                d = await _plug_handle(ip)
                await asyncio.wait_for(d.on() if on else d.off(), 10)
            return
        except Exception:
            _PLUG_CACHE.pop(ip, None)
            if attempt == retries - 1:
                raise
            await asyncio.sleep(1)


# --- Shelly master (generation auto-detect) ---------------------------------

_SHELLY_GEN: dict = {}   # ip → 1 | 2


def _http_json(url: str, timeout: float = 6.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _shelly_probe(ip: str) -> dict:
    """Detect generation AND capability. Gen2+: has Switch.* → switchable;
    only PM1.* (Plug PM Gen3) → meter-only. Gen1: /status with relays[]."""
    try:
        _http_json(f"http://{ip}/rpc/Shelly.GetDeviceInfo")
    except Exception:
        s = _http_json(f"http://{ip}/status")   # raises if not Gen1 either
        return {"gen": 1, "switchable": bool(s.get("relays"))}
    methods = _http_json(f"http://{ip}/rpc/Shelly.ListMethods").get("methods", [])
    return {"gen": 2, "switchable": "Switch.GetStatus" in methods,
            "pm1": "PM1.GetStatus" in methods}


def _shelly_caps(ip: str) -> dict:
    caps = _SHELLY_GEN.get(ip)
    if caps is None:
        caps = _shelly_probe(ip)
        _SHELLY_GEN[ip] = caps
    return caps


def _shelly_status_sync(ip: str) -> dict:
    caps = _shelly_caps(ip)
    if caps["gen"] >= 2:
        if caps["switchable"]:
            s = _http_json(f"http://{ip}/rpc/Switch.GetStatus?id=0")
            return {"on": bool(s.get("output")), "apower_w": s.get("apower"),
                    "gen": caps["gen"], "switchable": True}
        s = _http_json(f"http://{ip}/rpc/PM1.GetStatus?id=0")
        return {"on": None, "apower_w": s.get("apower"),
                "gen": caps["gen"], "switchable": False}
    s = _http_json(f"http://{ip}/status")
    relay = (s.get("relays") or [{}])[0]
    meter = (s.get("meters") or [{}])[0]
    return {"on": bool(relay.get("ison")) if s.get("relays") else None,
            "apower_w": meter.get("power"), "gen": 1,
            "switchable": bool(s.get("relays"))}


def _shelly_set_sync(ip: str, on: bool) -> None:
    caps = _shelly_caps(ip)
    if not caps.get("switchable"):
        raise RigError(400, "master plug is metering-only (no relay) — "
                            "cannot switch the strip")
    if caps["gen"] >= 2:
        _http_json(f"http://{ip}/rpc/Switch.Set?id=0&on={'true' if on else 'false'}")
    else:
        _http_json(f"http://{ip}/relay/0?turn={'on' if on else 'off'}")


async def shelly_status() -> dict:
    """{"configured", "reachable", "on" (None when meter-only), "apower_w",
    "gen", "switchable"}. Never raises."""
    ip = shelly_ip()
    if not ip:
        return {"configured": False, "reachable": False, "on": None,
                "apower_w": None, "gen": None, "switchable": False}
    try:
        s = await asyncio.to_thread(_shelly_status_sync, ip)
        return {"configured": True, "reachable": True, **s}
    except Exception:
        caps = _SHELLY_GEN.get(ip) or {}
        return {"configured": True, "reachable": False, "on": None,
                "apower_w": None, "gen": caps.get("gen"),
                "switchable": caps.get("switchable", False)}


async def shelly_set(on: bool) -> None:
    ip = shelly_ip()
    if not ip:
        raise RigError(400, "master switch not configured")
    await asyncio.to_thread(_shelly_set_sync, ip, on)


# --- Device probes / graceful shutdown (subprocess, monkeypatchable) --------

_SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=4",
             "-o", "StrictHostKeyChecking=accept-new"]


def _run(cmd: list, timeout: int = 20):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe_ready(dev: dict) -> bool:
    """True when the device is ready for work: SSH answers (Pis) or Android
    reports boot completed (GTV). Runs in a thread; must stay cheap."""
    try:
        if dev["kind"] == "ssh":
            return _run(["ssh"] + _SSH_OPTS + [dev["target"], "true"]).returncode == 0
        serial = dev["target"]
        _run([ADB_BIN, "connect", serial], timeout=10)
        out = _run([ADB_BIN, "-s", serial, "shell", "getprop",
                    "sys.boot_completed"], timeout=10).stdout
        return out.strip().endswith("1")
    except Exception:
        return False


_WL_ENV = "WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000"


def set_signal(dev: dict, on: bool) -> None:
    """Raise/drop the device's HDMI signal WITHOUT touching power.

    The shared monitor does not gate hot-plug per input (verified 2026-07-29:
    the GTV still saw full EDID while the Pi 5 held the picture), so devices
    cannot detect losing the screen. Arbitration is therefore active: the
    screen goes to whichever single device has a live signal.

    Reliability lessons (first live claims, 2026-07-29):
    - Pi raise must PULSE (off → 2 s → on): a plain --on is a no-op when the
      output is already enabled — no fresh hot-plug, the panel never re-scans.
    - GTV wake/sleep must retry + verify mWakefulness: a single keyevent
      frequently doesn't stick (same finding as bench.py's prepare())."""
    if dev["kind"] == "ssh":
        # DPMS via wlopm, NOT output disable via wlr-randr: labwc auto-revives
        # a session's only output when disabled (seen live 2026-07-29 as the
        # Pi 400's black-desktop-with-cursor stealing the panel back). DPMS
        # drops the TMDS signal while the output stays configured — nothing
        # for the compositor to revert.
        if on:
            # Repair every layer, then pulse: re-enable any wlr-disabled
            # output (a leftover --off makes DPMS a no-op on zero heads —
            # bit the Pi 5 on 2026-07-29), then DPMS off→on for the fresh
            # signal transition the panel's auto-switch needs.
            cmd = (f"outs=$({_WL_ENV} wlr-randr | awk '/^[[:alnum:]]/{{print $1}}'); "
                   f"for o in $outs; do {_WL_ENV} wlr-randr --output $o --on || true; done; "
                   f"sleep 1; {_WL_ENV} wlopm --off '*'; sleep 2; "
                   f"{_WL_ENV} wlopm --on '*'")
        else:
            cmd = f"{_WL_ENV} wlopm --off '*'"
        r = _run(["ssh"] + _SSH_OPTS + [dev["target"], cmd], timeout=40)
        if r.returncode != 0:
            raise RuntimeError(
                f"{dev['label']}: signal raise/drop failed "
                f"(rc={r.returncode} {(r.stderr or '').strip()[:120]})")
        return
    serial = dev["target"]
    _run([ADB_BIN, "connect", serial], timeout=10)
    if on:
        # A wake keyevent on an already-Awake box produces NO signal
        # transition and the panel never re-scans — force one: sleep first
        # if awake, then wake + HOME so the box actually draws.
        state = _run([ADB_BIN, "-s", serial, "shell",
                      "dumpsys power | grep -m1 mWakefulness"], timeout=15).stdout
        if "mWakefulness=Awake" in state:
            _run([ADB_BIN, "-s", serial, "shell", "input", "keyevent",
                  "KEYCODE_SLEEP"], timeout=15)
            time.sleep(3)
    key = "KEYCODE_WAKEUP" if on else "KEYCODE_SLEEP"
    # Sleeping boxes report Asleep OR Dozing (ambient/screensaver state) —
    # both mean the HDMI signal is down. Only Awake counts for wake.
    wants = ("mWakefulness=Awake",) if on else ("mWakefulness=Asleep",
                                                "mWakefulness=Dozing")
    for _ in range(4):
        _run([ADB_BIN, "-s", serial, "shell", "input", "keyevent", key],
             timeout=15)
        time.sleep(2)
        state = _run([ADB_BIN, "-s", serial, "shell",
                      "dumpsys power | grep -m1 mWakefulness"],
                     timeout=15).stdout
        if any(w in state for w in wants):
            if on:
                _run([ADB_BIN, "-s", serial, "shell", "input", "keyevent",
                      "KEYCODE_HOME"], timeout=15)
            return
    raise RuntimeError(f"{dev['label']}: did not reach "
                       + "/".join(w.split('=')[1] for w in wants))


def send_shutdown(dev: dict) -> None:
    """Best-effort graceful shutdown; the relay cut follows after
    shutdown_wait_s regardless."""
    try:
        if dev["kind"] == "ssh":
            _run(["ssh"] + _SSH_OPTS + [dev["target"], "sudo -n shutdown -h now"])
        else:
            serial = dev["target"]
            _run([ADB_BIN, "connect", serial], timeout=10)
            _run([ADB_BIN, "-s", serial, "shell", "reboot", "-p"], timeout=15)
    except Exception:
        log.debug("send_shutdown failed for %s", dev.get("label"), exc_info=True)


# --- State machine + cache ---------------------------------------------------

class RigError(Exception):
    """Control-op refusal; routes map to an HTTP status + reason."""
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _blank_dev() -> dict:
    return {"state": "off", "watts": None, "detail": "", "busy": False,
            "boot_started": None, "elapsed_s": None, "probe_fails": 0}


rig_cache: dict = {
    "devices": {name: _blank_dev() for name in RIG["devices"]},
    "monitor": {"on": None, "watts": None, "in_use_hint": False,
                "reachable": False},
    "master": {"configured": False, "reachable": False, "on": None,
               "apower_w": None, "gen": None, "switchable": False},
    "screen_owner": None,
    "updated_monotonic": None,
}

_OP_LOCKS: dict = {}   # device name → asyncio.Lock for control ops


def _op_lock(name: str) -> asyncio.Lock:
    return _OP_LOCKS.setdefault(name, asyncio.Lock())


async def _step_device(name: str, master_off: bool) -> None:
    dev_cfg = RIG["devices"][name]
    d = rig_cache["devices"][name]
    now = time.monotonic()

    if d["state"] == "stopping":       # owned by the device_off task
        return
    if _plug_key(dev_cfg) & PAUSED_PLUGS:
        d["detail"] = "measuring — polling paused"
        return

    if master_off:
        d.update({"state": "unpowered", "watts": None, "boot_started": None,
                  "elapsed_s": None, "detail": "master off"})
        if rig_cache["screen_owner"] == name:
            rig_cache["screen_owner"] = None
        return

    try:
        ps = await plug_status(dev_cfg["plug_ip"])
    except Exception:
        d.update({"state": "unreachable", "watts": None,
                  "detail": f"{dev_cfg['plug_name']} not answering"})
        return

    d["watts"] = round(ps["watts"], 3)
    if not ps["on"]:
        d.update({"state": "off", "boot_started": None, "elapsed_s": None,
                  "detail": f"{dev_cfg['plug_name']} ready"})
        if rig_cache["screen_owner"] == name:
            rig_cache["screen_owner"] = None
        return

    # Relay is on.
    if d["state"] in ("off", "unpowered", "unreachable"):
        # Powered from outside this UI (Tapo app, etc.) — adopt it.
        d["state"] = "powering"
        d["boot_started"] = now

    if d["boot_started"] is not None:
        d["elapsed_s"] = round(now - d["boot_started"], 1)

    if d["state"] == "powering" and ps["watts"] >= dev_cfg["boot_threshold_w"]:
        d["state"] = "booting"

    if d["state"] in ("powering", "booting"):
        ready = await asyncio.to_thread(probe_ready, dev_cfg)
        if ready:
            d.update({"state": "ready", "probe_fails": 0,
                      "detail": "ssh ok" if dev_cfg["kind"] == "ssh" else "adb ok"})
            return
        limit = 3 * dev_cfg["expected_boot_s"]
        if d["elapsed_s"] is not None and d["elapsed_s"] > limit:
            d.update({"state": "stuck",
                      "detail": f"not ready after {int(d['elapsed_s'])}s — power-cycle?"})
        else:
            d["detail"] = ("waiting for draw" if d["state"] == "powering"
                           else f"waiting on {'SSH' if dev_cfg['kind'] == 'ssh' else 'ADB'}")
        return

    if d["state"] in ("ready", "busy"):
        # Cheap liveness re-probe every ~4 poll cycles.
        if int(now) % 12 < 3:
            ready = await asyncio.to_thread(probe_ready, dev_cfg)
            if ready:
                d["probe_fails"] = 0
            else:
                d["probe_fails"] += 1
                if d["probe_fails"] >= 2 and not d["busy"]:
                    d.update({"state": "booting", "boot_started": now,
                              "detail": "lost contact — re-probing"})


def _plug_key(dev_cfg: dict) -> set:
    ips = dev_cfg["plug_ip"]
    return set([ips] if isinstance(ips, str) else ips)


async def poll_once() -> None:
    """One full rig sweep — factored out of rig_poller() so tests can await it
    with the IO functions monkeypatched."""
    master = await shelly_status()
    rig_cache["master"] = master
    master_off = bool(master["configured"] and master["reachable"]
                      and master.get("switchable") and master["on"] is False)

    mon_cfg = RIG["monitor"]
    if _plug_key({"plug_ip": mon_cfg["plug_ip"]}) & PAUSED_PLUGS:
        pass   # a measurement owns the monitor plug — keep last values
    else:
        try:
            ms = await plug_status(mon_cfg["plug_ip"])
            rig_cache["monitor"] = {
                "on": ms["on"], "watts": round(ms["watts"], 2),
                "in_use_hint": ms["watts"] >= mon_cfg["in_use_threshold_w"],
                "reachable": True}
        except Exception:
            rig_cache["monitor"] = {"on": None, "watts": None,
                                    "in_use_hint": False, "reachable": False}

    for name in RIG["devices"]:
        try:
            await _step_device(name, master_off)
        except Exception:
            log.debug("rig poll: %s step failed", name, exc_info=True)

    rig_cache["updated_monotonic"] = time.monotonic()


async def rig_poller():
    """Background task (started from main.py startup, like runtime pollers).
    ~3 s cadence while anything is active, ~10 s when the whole rig is idle —
    the Lab plugs share the household KLAP budget with the bench meter."""
    while True:
        try:
            await poll_once()
        except Exception:
            log.debug("rig_poller sweep failed", exc_info=True)
        active = any(d["state"] not in ("off", "unpowered", "unreachable")
                     for d in rig_cache["devices"].values())
        await asyncio.sleep(3 if active else 10)


# --- Control operations ------------------------------------------------------

async def device_on(name: str) -> None:
    dev_cfg = _dev_cfg(name)
    d = rig_cache["devices"][name]
    async with _op_lock(name):
        if d["busy"]:
            raise RigError(409, f"{dev_cfg['label']} is running a job")
        m = rig_cache["master"]
        if m["configured"] and m.get("switchable") and m["on"] is False:
            raise RigError(409, "master is off — turn the rig on first")
        await plug_set(dev_cfg["plug_ip"], True)
        d.update({"state": "powering", "boot_started": time.monotonic(),
                  "elapsed_s": 0.0, "detail": "relay on"})


async def device_off(name: str) -> None:
    """Graceful: shutdown command → wait → relay off. Runs as a background
    task; the tile shows `stopping` while it is in flight."""
    dev_cfg = _dev_cfg(name)
    d = rig_cache["devices"][name]
    async with _op_lock(name):
        if d["busy"]:
            raise RigError(409, f"{dev_cfg['label']} is running a job")
        d.update({"state": "stopping", "detail": "graceful shutdown",
                  "boot_started": None, "elapsed_s": None})

    async def _stop():
        try:
            await asyncio.to_thread(send_shutdown, dev_cfg)
            await asyncio.sleep(dev_cfg["shutdown_wait_s"])
            await plug_set(dev_cfg["plug_ip"], False)
            d.update({"state": "off", "watts": 0.0,
                      "detail": f"{dev_cfg['plug_name']} ready"})
            if rig_cache["screen_owner"] == name:
                rig_cache["screen_owner"] = None
        except Exception as e:
            d.update({"state": "stuck", "detail": f"stop failed: {e}"})

    asyncio.create_task(_stop())


async def device_cycle(name: str) -> None:
    """Hard power-cycle for a stuck device (relay off → 3 s → on)."""
    dev_cfg = _dev_cfg(name)
    d = rig_cache["devices"][name]
    async with _op_lock(name):
        if d["busy"]:
            raise RigError(409, f"{dev_cfg['label']} is running a job")
        await plug_set(dev_cfg["plug_ip"], False)
        await asyncio.sleep(3)
        await plug_set(dev_cfg["plug_ip"], True)
        d.update({"state": "powering", "boot_started": time.monotonic(),
                  "elapsed_s": 0.0, "probe_fails": 0, "detail": "power-cycled"})


async def claim_screen(name: str) -> None:
    """Hand the shared monitor to `name`: drop every other powered device's
    HDMI signal, raise the target's — the panel's verified auto-switch
    behaviour does the rest. Others stay dark until claimed or power-cycled
    (restoring them would steal the input straight back)."""
    dev_cfg = _dev_cfg(name)
    d = rig_cache["devices"][name]
    if d["state"] in _STOPPED_STATES or d["state"] == "stopping":
        raise RigError(409, f"{dev_cfg['label']} is not powered")
    busy = [RIG["devices"][n]["label"]
            for n, dd in rig_cache["devices"].items() if dd["busy"]]
    if busy:
        raise RigError(409, "job running on: " + ", ".join(busy)
                            + " — signal changes would contaminate the row")
    failures = []
    for other, dd in rig_cache["devices"].items():
        if other != name and dd["state"] not in _STOPPED_STATES:
            try:
                await asyncio.to_thread(set_signal, RIG["devices"][other], False)
            except Exception as e:
                failures.append(str(e))
    await asyncio.sleep(2)   # let the panel register the losses first
    try:
        await asyncio.to_thread(set_signal, dev_cfg, True)
    except Exception as e:
        failures.append(str(e))
    if failures:
        # Do NOT record ownership we can't have delivered — the UI must not lie.
        raise RigError(502, "claim incomplete: " + "; ".join(failures)[:300])
    rig_cache["screen_owner"] = name
    rig_cache["screen_claimed_at"] = time.monotonic()


async def monitor_power(on: bool) -> None:
    await plug_set(RIG["monitor"]["plug_ip"], on)


async def master_power(on: bool) -> None:
    """Master toggle. With a relay-equipped Shelly this switches the strip
    (off refused until every device is down). With the metering-only Plug PM
    it degrades to a SOFTWARE master: 'off' gracefully stops every powered
    box; 'on' is refused — boxes are powered individually so the monitor's
    auto-switch stays deterministic."""
    switchable = rig_cache["master"].get("switchable")
    if switchable:
        if not on:
            lively = [RIG["devices"][n]["label"]
                      for n, d in rig_cache["devices"].items()
                      if d["state"] not in _STOPPED_STATES]
            if lively:
                raise RigError(409,
                               "power devices off first: " + ", ".join(lively))
        await shelly_set(on)
        return
    if on:
        raise RigError(400, "no strip relay — power boxes individually (the "
                            "screen follows the single powered device)")
    busy = [RIG["devices"][n]["label"]
            for n, d in rig_cache["devices"].items() if d["busy"]]
    if busy:
        raise RigError(409, "job running on: " + ", ".join(busy))
    for name, d in rig_cache["devices"].items():
        if d["state"] not in _STOPPED_STATES and d["state"] != "stopping":
            await device_off(name)


def _dev_cfg(name: str) -> dict:
    if name not in RIG["devices"]:
        raise RigError(404, f"unknown device {name!r}")
    return RIG["devices"][name]


def status_payload() -> dict:
    """The /decode/status.json response — assembled from cache only (no IO)."""
    devices = {}
    for name, cfg_d in RIG["devices"].items():
        d = rig_cache["devices"][name]
        devices[name] = {
            "label": cfg_d["label"], "plug_name": cfg_d["plug_name"],
            "state": d["state"], "watts": d["watts"], "busy": d["busy"],
            "detail": d["detail"], "elapsed_s": d["elapsed_s"],
            "expected_s": cfg_d["expected_boot_s"],
        }
    master = rig_cache["master"]
    monitor = rig_cache["monitor"]
    total = sum(w for w in
                ([d["watts"] for d in rig_cache["devices"].values()]
                 + [monitor.get("watts")])
                if isinstance(w, (int, float)))
    n_plugs = len(RIG["devices"])
    saving = None
    if master["configured"] and master.get("switchable") and master["on"] is False:
        saving = (f"rig fully off — saving ~"
                  f"{n_plugs * RIG['tapo_standby_w']:.1f} W of Tapo standby")
    claimed_at = rig_cache.get("screen_claimed_at")
    settling = bool(rig_cache["screen_owner"] and claimed_at
                    and time.monotonic() - claimed_at < 12)
    return {"master": master, "monitor": monitor, "devices": devices,
            "screen_owner": rig_cache["screen_owner"],
            "screen_settling": settling,
            "total_w": round(total, 2), "saving_note": saving,
            "age_s": (None if rig_cache["updated_monotonic"] is None else
                      round(time.monotonic() - rig_cache["updated_monotonic"], 1))}
