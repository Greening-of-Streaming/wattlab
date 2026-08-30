"""
lg.py — LG webOS display control for the decode rig (CR-071).

The rig's shared display is an LG OLED55C2 (paired 2026-07-30). Unlike the
auto-switching PA329C, the C2 holds its selected input, so screen
arbitration is an explicit HDMI input select over webOS (aiowebostv / SSAP)
— cleaner than the per-device sleep/wake + DPMS dance: devices stay awake,
one command picks who is shown.

Also exposes power state and OLED backlight/brightness — a first-class
energy variable a recipe can sweep (an OLED's emission tracks content
luminance, unlike the LCD).

Config in rig.RIG["monitor"]: host + client_key path. All calls run in a
worker thread (aiowebostv is async; rig control ops are sync-in-executor)
and never raise past status() — a disconnected TV degrades to "unknown",
not an error. Monkeypatchable for tests via the module-level functions.
"""
import asyncio
import logging
import socket
import time
from pathlib import Path

log = logging.getLogger(__name__)

CLIENT_KEY_PATH = Path("/srv/data/owl/lg/client_key")

# The C2's MAC (same for its Ethernet .25 and Wi-Fi .109 answers). Needed for
# raw Wake-on-LAN: in Always-Ready STANDBY the TV answers the SSAP port but
# REJECTS every connection with WS close 1008 until the panel is awake
# (established 2026-08-01 — looked exactly like a broken TV; survived a mains
# cold boot because AC-restore boots back to standby). A magic packet needs no
# SSAP at all, so it is the one wake lever that works from standby;
# connect-then-power_on (the old lg.power(True) path) cannot.
C2_MAC = "ac:5a:f0:2f:b8:dc"


def wake(mac: str = C2_MAC) -> None:
    """Raw WoL magic packet (broadcast, ports 9+7). Fire-and-forget; pair with
    a probe/retry loop — the C2 takes ~10-20 s from standby to accepting SSAP."""
    pkt = b"\xff" * 6 + bytes.fromhex(mac.replace(":", "")) * 16
    for port in (9, 7):
        for dst in ("255.255.255.255", "192.168.1.255"):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.sendto(pkt, (dst, port))
                s.close()
            except Exception:
                pass


def _key() -> str | None:
    try:
        return CLIENT_KEY_PATH.read_text().strip() or None
    except Exception:
        return None


async def _with_client(host: str, key: str, coro_fn):
    from aiowebostv import WebOsClient
    # Retry the connect: a single 12 s attempt intermittently times out under
    # load (seen on the C2 in a 5-device parallel run, 2026-07-31), failing the
    # whole decode row. 3 attempts turns a transient hiccup into a short delay.
    last = None
    for attempt in range(3):
        client = WebOsClient(host, client_key=key)
        try:
            await asyncio.wait_for(client.connect(), 12)
        except Exception as e:
            last = e
            try:
                await client.disconnect()
            except Exception:
                pass
            if attempt < 2:
                await asyncio.sleep(2)
            continue
        try:
            return await coro_fn(client)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
    raise last


def set_input(host: str, hdmi_input: str) -> None:
    """Show `hdmi_input` (e.g. 'HDMI_4') on the TV. Raises on failure so the
    caller can surface a 502 (the UI must not claim a switch that didn't
    happen — same discipline as the DPMS/adb path)."""
    key = _key()
    if not key:
        raise RuntimeError("LG client key missing — TV not paired")

    async def _do(c):
        await c.set_input(hdmi_input)
    asyncio.run(_with_client(host, key, _do))


def power(host: str, on: bool) -> None:
    key = _key()
    if not key:
        raise RuntimeError("LG client key missing")

    if on:
        # Raw WoL FIRST — the old connect-then-power_on path deadlocked in
        # Always-Ready standby (SSAP rejects the connect with 1008 until the
        # panel is awake, so the wake command could never be delivered).
        # Wake, then poll until SSAP accepts (proof it is actually on).
        for _ in range(3):
            wake()
            time.sleep(2)

        async def _check(c):
            return await c.get_power_state()
        last = None
        for _ in range(10):
            try:
                asyncio.run(_with_client(host, key, _check))
                return
            except Exception as e:
                last = e
                time.sleep(3)
        raise RuntimeError(f"C2 did not wake after WoL: {last}")

    async def _do(c):
        await c.power_off()
    asyncio.run(_with_client(host, key, _do))


# Built-in webOS browser (Chromium). Launching it with a `target` URL is our
# native-decode path: the C2's own α9 SoC decodes a clip served fullscreen by
# the origin, metered on Lab-E — the all-in "smart-TV app" figure (panel + SoC,
# NOT decode-isolated; the OLED brightness swing dwarfs the decode delta).
_BROWSER_APP = "com.webos.app.browser"
_HOME_APP = "com.webos.app.home"


def launch_url(host: str, url: str) -> None:
    """Open `url` fullscreen in the webOS browser (native playback). Raises on
    failure — the caller must not claim a play that didn't happen."""
    key = _key()
    if not key:
        raise RuntimeError("LG client key missing — TV not paired")

    async def _do(c):
        await c.launch_app_with_params(_BROWSER_APP, {"target": url})
    asyncio.run(_with_client(host, key, _do))


def go_home(host: str) -> None:
    """Return the panel to Home — the TV-native 'idle' (closes the browser
    playback so the baseline is the app-shell, not a decoding clip)."""
    key = _key()
    if not key:
        raise RuntimeError("LG client key missing")

    async def _do(c):
        try:
            await c.close_app(_BROWSER_APP)
        except Exception:
            pass
        await c.launch_app(_HOME_APP)
    asyncio.run(_with_client(host, key, _do))


def current_app(host: str) -> str | None:
    """Foreground app id (e.g. 'com.webos.app.browser'), or None. Never raises —
    used by the decode harness's still_running() check."""
    key = _key()
    if not key:
        return None
    try:
        async def _do(c):
            return await c.get_current_app()
        return asyncio.run(_with_client(host, key, _do))
    except Exception:
        return None


# Screen-off decode (Ben's isolation idea): blank the OLED while the SoC keeps
# decoding, so Lab-E ≈ board+decode with the ~80 W panel removed — IF webOS
# keeps the video pipeline alive with the screen off (to be verified live; it
# may suspend rendering). ssap tvpower endpoints, not the settings service.
def screen_off(host: str) -> None:
    key = _key()
    if not key:
        raise RuntimeError("LG client key missing")

    async def _do(c):
        await c.request("ssap://com.webos.service.tvpower/power/turnOffScreen")
    asyncio.run(_with_client(host, key, _do))


def screen_on(host: str) -> None:
    key = _key()
    if not key:
        raise RuntimeError("LG client key missing")

    async def _do(c):
        await c.request("ssap://com.webos.service.tvpower/power/turnOnScreen")
    asyncio.run(_with_client(host, key, _do))


def set_brightness(host: str, pct: int) -> None:
    """OLED backlight 0–100 (luna picture setting). A recipe dimension.

    2026-08-30 bugfix: this called c.luna_request(...), a method the
    installed aiowebostv version (0.7.x here) doesn't have — only
    c.request(...) — so this had never actually worked (never exercised
    before tonight's OLED brightness sweep, R9). Verified live against
    the C2: get_brightness() before/after now shows the value actually
    changing."""
    key = _key()
    if not key:
        raise RuntimeError("LG client key missing")
    pct = max(0, min(100, int(pct)))

    async def _do(c):
        await c.request(
            "luna://com.webos.settingsservice/setSystemSettings",
            {"category": "picture", "settings": {"backlight": str(pct)}})
    asyncio.run(_with_client(host, key, _do))


def get_brightness(host: str) -> int | None:
    """Current OLED backlight 0-100, or None on any failure. Added
    2026-08-30 alongside the set_brightness fix — a sweep needs to
    record (and restore) the starting value."""
    key = _key()
    if not key:
        return None

    async def _do(c):
        r = await c.request(
            "luna://com.webos.settingsservice/getSystemSettings",
            {"category": "picture", "keys": ["backlight"]})
        return r
    try:
        r = asyncio.run(_with_client(host, key, _do))
        val = (r or {}).get("settings", {}).get("backlight")
        return int(val) if val is not None else None
    except Exception:
        return None


def status(host: str) -> dict:
    """{"reachable", "power", "current_input", "paired"}. Never raises."""
    key = _key()
    if not key:
        return {"reachable": False, "power": None, "current_input": None,
                "paired": False}

    async def _do(c):
        ps = await c.get_power_state()
        app = await c.get_current_app()   # 'com.webos.app.hdmi4' etc.
        inp = None
        if isinstance(app, str) and "hdmi" in app.lower():
            inp = "HDMI_" + app.rsplit("hdmi", 1)[-1]
        return {"reachable": True, "power": ps.get("state"),
                "current_input": inp, "paired": True}
    try:
        return asyncio.run(_with_client(host, key, _do))
    except Exception:
        return {"reachable": False, "power": None, "current_input": None,
                "paired": True}
