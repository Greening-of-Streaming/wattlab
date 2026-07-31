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
from pathlib import Path

log = logging.getLogger(__name__)

CLIENT_KEY_PATH = Path("/srv/data/owl/lg/client_key")


def _key() -> str | None:
    try:
        return CLIENT_KEY_PATH.read_text().strip() or None
    except Exception:
        return None


async def _with_client(host: str, key: str, coro_fn):
    from aiowebostv import WebOsClient
    client = WebOsClient(host, client_key=key)
    try:
        await asyncio.wait_for(client.connect(), 12)
        return await coro_fn(client)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


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

    async def _do(c):
        if on:
            await c.power_on()          # Wake-on-LAN
        else:
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


def set_brightness(host: str, pct: int) -> None:
    """OLED backlight 0–100 (luna picture setting). A recipe dimension."""
    key = _key()
    if not key:
        raise RuntimeError("LG client key missing")
    pct = max(0, min(100, int(pct)))

    async def _do(c):
        # aiowebostv exposes luna calls; backlight is the OLED energy knob.
        await c.luna_request(
            "luna://com.webos.settingsservice/setSystemSettings",
            {"category": "picture", "settings": {"backlight": str(pct)}})
    asyncio.run(_with_client(host, key, _do))


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
