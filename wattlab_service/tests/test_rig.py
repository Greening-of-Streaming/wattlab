"""rig.py state machine + control-op tests — all hardware IO monkeypatched."""
import asyncio
import time

import pytest

import rig


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fresh_rig(monkeypatch):
    """Reset the cache and neutralise all hardware IO between tests."""
    for name in rig.RIG["devices"]:
        rig.rig_cache["devices"][name] = rig._blank_dev()
    rig.rig_cache["monitor"] = {"on": None, "watts": None,
                                "in_use_hint": False, "reachable": False}
    rig.rig_cache["master"] = {"configured": False, "reachable": False,
                               "on": None, "apower_w": None, "gen": None,
                               "switchable": False}
    rig.PAUSED_PLUGS.clear()
    rig._OP_LOCKS.clear()   # asyncio locks can't be reused across event loops
    rig.rig_cache["screen_owner"] = None
    monkeypatch.setattr(rig, "shelly_ip", lambda: None)
    monkeypatch.setattr(rig, "master_tapo_ip", lambda: None)
    monkeypatch.setattr(rig, "probe_ready", lambda dev: False)
    monkeypatch.setattr(rig, "send_shutdown", lambda dev: None)
    monkeypatch.setattr(rig, "set_signal", lambda dev, on: None)

    async def _no_plug(ip, **kw):
        raise RuntimeError("plug IO not stubbed in this test")
    monkeypatch.setattr(rig, "plug_status", _no_plug)
    monkeypatch.setattr(rig, "plug_set", _no_plug)
    yield


def _stub_plugs(monkeypatch, on: bool, watts: float):
    async def _status(ip, **kw):
        return {"on": on, "watts": watts, "ip": "stub"}
    monkeypatch.setattr(rig, "plug_status", _status)


def test_relay_off_is_off(monkeypatch):
    _stub_plugs(monkeypatch, on=False, watts=0.0)
    _run(rig.poll_once())
    for d in rig.rig_cache["devices"].values():
        assert d["state"] == "off"


def test_powering_then_booting_then_ready(monkeypatch):
    _stub_plugs(monkeypatch, on=True, watts=0.1)
    _run(rig.poll_once())
    assert rig.rig_cache["devices"]["pi5"]["state"] == "powering"

    _stub_plugs(monkeypatch, on=True, watts=4.0)   # draw above threshold
    _run(rig.poll_once())
    assert rig.rig_cache["devices"]["pi5"]["state"] == "booting"

    monkeypatch.setattr(rig, "probe_ready", lambda dev: True)
    _run(rig.poll_once())
    assert rig.rig_cache["devices"]["pi5"]["state"] == "ready"


def test_stuck_after_three_times_expected(monkeypatch):
    _stub_plugs(monkeypatch, on=True, watts=4.0)
    _run(rig.poll_once())
    d = rig.rig_cache["devices"]["pi5"]
    limit = 3 * rig.RIG["devices"]["pi5"]["expected_boot_s"]
    d["boot_started"] = time.monotonic() - limit - 5
    _run(rig.poll_once())
    assert d["state"] == "stuck"
    assert "power-cycle" in d["detail"]


def test_master_off_means_unpowered(monkeypatch):
    async def _master():
        return {"configured": True, "reachable": True, "on": False,
                "apower_w": 0.0, "gen": 2, "switchable": True}
    monkeypatch.setattr(rig, "shelly_status", _master)
    _run(rig.poll_once())
    for d in rig.rig_cache["devices"].values():
        assert d["state"] == "unpowered"
    payload = rig.status_payload()
    assert payload["saving_note"] and "saving" in payload["saving_note"]


def test_meter_only_master_never_unpowers(monkeypatch):
    """A Plug PM (no relay) reports on=None — devices must poll normally."""
    async def _master():
        return {"configured": True, "reachable": True, "on": None,
                "apower_w": 2.4, "gen": 2, "switchable": False}
    monkeypatch.setattr(rig, "shelly_status", _master)
    _stub_plugs(monkeypatch, on=False, watts=0.0)
    _run(rig.poll_once())
    for d in rig.rig_cache["devices"].values():
        assert d["state"] == "off"
    assert rig.status_payload()["saving_note"] is None


def test_paused_plug_is_skipped(monkeypatch):
    called = []

    async def _status(ip, **kw):
        called.append(ip)
        return {"on": False, "watts": 0.0, "ip": "x"}
    monkeypatch.setattr(rig, "plug_status", _status)
    rig.PAUSED_PLUGS.add(rig.RIG["devices"]["pi5"]["plug_ip"])
    _run(rig.poll_once())
    assert rig.RIG["devices"]["pi5"]["plug_ip"] not in called
    assert "paused" in rig.rig_cache["devices"]["pi5"]["detail"]


def test_device_off_graceful_then_relay(monkeypatch):
    events = []
    monkeypatch.setattr(rig, "send_shutdown", lambda dev: events.append("shutdown"))

    async def _set(ip, on, **kw):
        events.append(("relay", on))
    monkeypatch.setattr(rig, "plug_set", _set)
    monkeypatch.setitem(rig.RIG["devices"]["pi5"], "shutdown_wait_s", 0)

    async def scenario():
        rig.rig_cache["devices"]["pi5"]["state"] = "ready"
        await rig.device_off("pi5")
        assert rig.rig_cache["devices"]["pi5"]["state"] == "stopping"
        await asyncio.sleep(0.2)   # let the background _stop task run
    _run(scenario())
    assert events == ["shutdown", ("relay", False)]
    assert rig.rig_cache["devices"]["pi5"]["state"] == "off"


def test_relay_master_off_refused_while_device_alive(monkeypatch):
    rig.rig_cache["master"]["switchable"] = True
    rig.rig_cache["devices"]["pi5"]["state"] = "ready"
    with pytest.raises(rig.RigError) as e:
        _run(rig.master_power(False))
    assert e.value.status == 409
    assert "Pi 5" in e.value.reason


def test_software_master_on_refused():
    """Meter-only Shelly: 'Rig on' has nothing to switch — explicit 400."""
    with pytest.raises(rig.RigError) as e:
        _run(rig.master_power(True))
    assert e.value.status == 400
    assert "individually" in e.value.reason


def test_software_master_off_cascades_graceful_stops(monkeypatch):
    stopped = []

    async def _fake_off(name):
        stopped.append(name)
        rig.rig_cache["devices"][name]["state"] = "stopping"
    monkeypatch.setattr(rig, "device_off", _fake_off)
    rig.rig_cache["devices"]["pi5"]["state"] = "ready"
    rig.rig_cache["devices"]["gtv"]["state"] = "booting"
    _run(rig.master_power(False))
    assert sorted(stopped) == ["gtv", "pi5"]


def test_software_master_off_refused_while_busy():
    rig.rig_cache["devices"]["pi5"]["state"] = "ready"
    rig.rig_cache["devices"]["pi5"]["busy"] = True
    with pytest.raises(rig.RigError) as e:
        _run(rig.master_power(False))
    assert e.value.status == 409


def test_tapo_master_is_switchable(monkeypatch):
    monkeypatch.setattr(rig, "master_tapo_ip", lambda: "10.0.0.5")

    async def _status(ip, **kw):
        assert ip == "10.0.0.5"
        return {"on": True, "watts": 5.44, "ip": ip}
    monkeypatch.setattr(rig, "plug_status", _status)
    s = _run(rig.shelly_status())
    assert s["switchable"] is True
    assert s["kind"] == "tapo"
    assert s["on"] is True
    assert s["apower_w"] == 5.4


def test_tapo_master_off_shows_zero_not_unreachable(monkeypatch):
    """Master off ⇒ the downstream Shelly meter is dark; the Tapo's own
    reading stands in so the strip bar shows 0.0 W."""
    monkeypatch.setattr(rig, "master_tapo_ip", lambda: "10.0.0.5")

    async def _status(ip, **kw):
        return {"on": False, "watts": 0.0, "ip": ip}
    monkeypatch.setattr(rig, "plug_status", _status)
    s = _run(rig.shelly_status())
    assert s["reachable"] is True
    assert s["on"] is False
    assert s["apower_w"] == 0.0


def test_tapo_master_power_uses_plug_set(monkeypatch):
    monkeypatch.setattr(rig, "master_tapo_ip", lambda: "10.0.0.5")
    rig.rig_cache["master"]["switchable"] = True
    calls = []

    async def _set(ip, on, **kw):
        calls.append((ip, on))
    monkeypatch.setattr(rig, "plug_set", _set)
    _run(rig.master_power(True))
    assert calls == [("10.0.0.5", True)]
    # off refused while a device is up (same rule as the relay Shelly)
    rig.rig_cache["devices"]["pi5"]["state"] = "ready"
    with pytest.raises(rig.RigError):
        _run(rig.master_power(False))


def test_tapo_master_off_unpowers_devices(monkeypatch):
    monkeypatch.setattr(rig, "master_tapo_ip", lambda: "10.0.0.5")

    async def _status(ip, **kw):
        return {"on": False, "watts": 0.0, "ip": ip}
    monkeypatch.setattr(rig, "plug_status", _status)
    _run(rig.poll_once())
    for d in rig.rig_cache["devices"].values():
        assert d["state"] == "unpowered"


def test_busy_device_refuses_power_ops():
    rig.rig_cache["devices"]["gtv"]["busy"] = True
    for op in (rig.device_on, rig.device_off, rig.device_cycle):
        with pytest.raises(rig.RigError) as e:
            _run(op("gtv"))
        assert e.value.status == 409


def test_unknown_device_404():
    with pytest.raises(rig.RigError) as e:
        _run(rig.device_on("toaster"))
    assert e.value.status == 404


def test_claim_screen_webos_sets_input(monkeypatch):
    """C2 path: a single HDMI input-select, no per-device signal juggling."""
    calls = []
    monkeypatch.setitem(rig.RIG["monitor"], "lg_host", "10.0.0.9")
    monkeypatch.setattr(rig.lg, "set_input",
                        lambda host, hdmi: calls.append((host, hdmi)))
    rig.rig_cache["devices"]["pi5"]["state"] = "ready"
    rig.rig_cache["devices"]["gtv"]["state"] = "ready"
    _run(rig.claim_screen("pi5"))
    assert calls == [("10.0.0.9", "HDMI_4")]     # pi5's mapped port
    assert rig.rig_cache["screen_owner"] == "pi5"


def test_claim_screen_webos_refuses_unmapped_device(monkeypatch):
    monkeypatch.setitem(rig.RIG["monitor"], "lg_host", "10.0.0.9")
    monkeypatch.setattr(rig.lg, "set_input", lambda host, hdmi: None)
    # temporarily drop the port map on gtv
    monkeypatch.setitem(rig.RIG["devices"]["gtv"], "hdmi_input", None)
    rig.rig_cache["devices"]["gtv"]["state"] = "ready"
    with pytest.raises(rig.RigError) as e:
        _run(rig.claim_screen("gtv"))
    assert e.value.status == 409


def test_claim_screen_legacy_darkens_others(monkeypatch):
    """PA329C fallback path (no lg_host): signal-juggling still works."""
    monkeypatch.setitem(rig.RIG["monitor"], "lg_host", None)
    calls = []
    monkeypatch.setattr(rig, "set_signal",
                        lambda dev, on: calls.append((dev["label"], on)))
    rig.rig_cache["devices"]["pi5"]["state"] = "ready"
    rig.rig_cache["devices"]["gtv"]["state"] = "ready"
    _run(rig.claim_screen("pi5"))
    assert ("Google TV", False) in calls
    assert ("Pi 5", True) in calls
    assert rig.rig_cache["screen_owner"] == "pi5"


def test_claim_screen_refused_for_unpowered_target():
    with pytest.raises(rig.RigError) as e:
        _run(rig.claim_screen("pi5"))   # state off
    assert e.value.status == 409


def test_claim_screen_refused_while_any_job_runs():
    rig.rig_cache["devices"]["pi5"]["state"] = "ready"
    rig.rig_cache["devices"]["gtv"]["busy"] = True
    with pytest.raises(rig.RigError) as e:
        _run(rig.claim_screen("pi5"))
    assert e.value.status == 409


def test_claim_screen_failure_is_reported_not_swallowed(monkeypatch):
    """2026-07-29 live lesson: a silently failing signal command made the UI
    claim success while the panel never moved. Failures must 502."""
    def _boom(dev, on):
        raise RuntimeError(f"{dev['label']}: output control failed")
    monkeypatch.setattr(rig, "set_signal", _boom)
    rig.rig_cache["devices"]["pi5"]["state"] = "ready"
    rig.rig_cache["devices"]["gtv"]["state"] = "ready"
    with pytest.raises(rig.RigError) as e:
        _run(rig.claim_screen("gtv"))
    assert e.value.status == 502
    assert "claim incomplete" in e.value.reason
    assert rig.rig_cache["screen_owner"] is None


def test_screen_owner_cleared_when_owner_powers_off(monkeypatch):
    rig.rig_cache["devices"]["pi5"]["state"] = "ready"
    rig.rig_cache["screen_owner"] = "pi5"
    _stub_plugs(monkeypatch, on=False, watts=0.0)
    _run(rig.poll_once())
    assert rig.rig_cache["screen_owner"] is None


def test_status_payload_shape():
    p = rig.status_payload()
    assert set(p) == {"master", "monitor", "devices", "screen_owner",
                      "screen_settling", "total_w", "saving_note", "age_s"}
    for name, d in p["devices"].items():
        assert set(d) == {"label", "plug_name", "device_class", "silicon",
                          "conn", "state", "watts", "busy",
                          "detail", "elapsed_s", "expected_s"}
        assert d["device_class"] in ("sbc", "stb", "tv")
        assert d["conn"] in ("ssh", "adb")
    assert p["monitor"]["panel"]          # bench schematic display identity
    assert p["monitor"]["plug_name"] == "Lab-E"


def test_lab_c_router_plug_never_in_config_or_payload():
    """192.168.1.35 (Lab-C) powers the Bouygues router — relay-off would kill
    the LAN including the path to recover it. It must never be part of the
    rig surface."""
    import json
    assert "192.168.1.35" not in json.dumps(rig.RIG)
    assert "192.168.1.35" not in json.dumps(rig.status_payload())
