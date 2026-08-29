"""rig.py state machine + control-op tests — all hardware IO monkeypatched."""
import asyncio
import time

import pytest

import rig

# Originals captured before the autouse fixture stubs them — for tests of the
# real implementations (the fixture neutralises hardware IO for everyone else).
_ORIG_SEND_SHUTDOWN = rig.send_shutdown
_ORIG_PROBE_READY = rig.probe_ready


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
    rig.DISCOVERED_TARGETS.clear()
    rig._discover_last.clear()
    rig.apply_target_overrides({})
    rig.apply_hdmi_assignments({})
    monkeypatch.setattr(rig, "atv_cmd", lambda dev, *c, **k: "")   # never shell out to pyatv
    monkeypatch.setattr(rig, "_neigh_table", lambda: {})     # no LAN IO from tests
    monkeypatch.setattr(rig, "_ping_sweep", lambda *a, **k: None)
    rig.rig_cache["screen_owner"] = None
    monkeypatch.setattr(rig, "shelly_ip", lambda: None)
    monkeypatch.setattr(rig, "master_tapo_ip", lambda: None)
    monkeypatch.setattr(rig, "probe_ready", lambda dev: False)
    monkeypatch.setattr(rig, "send_shutdown", lambda dev: None)
    monkeypatch.setattr(rig, "adb_auth_state", lambda dev: None)
    monkeypatch.setattr(rig, "adb_reconnect", lambda dev: None)
    monkeypatch.setattr(rig, "set_signal", lambda dev, on: None)
    # Never broadcast real WoL from a test run — pytest runs ON the lab LAN
    # and a magic packet would wake the household's C2 every suite run.
    monkeypatch.setattr(rig.lg, "wake", lambda *a, **k: None)

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
    assert rig.rig_cache["devices"]["pi400"]["state"] == "powering"

    _stub_plugs(monkeypatch, on=True, watts=4.0)   # draw above threshold
    _run(rig.poll_once())
    assert rig.rig_cache["devices"]["pi400"]["state"] == "booting"

    monkeypatch.setattr(rig, "probe_ready", lambda dev: True)
    _run(rig.poll_once())
    assert rig.rig_cache["devices"]["pi400"]["state"] == "ready"


def test_stuck_after_three_times_expected(monkeypatch):
    _stub_plugs(monkeypatch, on=True, watts=4.0)
    _run(rig.poll_once())
    d = rig.rig_cache["devices"]["pi400"]
    limit = 3 * rig.RIG["devices"]["pi400"]["expected_boot_s"]
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
    for name, d in rig.rig_cache["devices"].items():
        if rig.RIG["devices"][name].get("parked"):
            continue
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
    rig.PAUSED_PLUGS.add(rig.RIG["devices"]["pi400"]["plug_ip"])
    _run(rig.poll_once())
    assert rig.RIG["devices"]["pi400"]["plug_ip"] not in called
    assert "paused" in rig.rig_cache["devices"]["pi400"]["detail"]


def test_device_off_graceful_then_relay(monkeypatch):
    events = []
    monkeypatch.setattr(rig, "send_shutdown", lambda dev: events.append("shutdown"))

    async def _set(ip, on, **kw):
        events.append(("relay", on))
    monkeypatch.setattr(rig, "plug_set", _set)
    monkeypatch.setitem(rig.RIG["devices"]["pi400"], "shutdown_wait_s", 0)

    async def scenario():
        rig.rig_cache["devices"]["pi400"]["state"] = "ready"
        await rig.device_off("pi400")
        assert rig.rig_cache["devices"]["pi400"]["state"] == "stopping"
        await asyncio.sleep(0.2)   # let the background _stop task run
    _run(scenario())
    assert events == ["shutdown", ("relay", False)]
    assert rig.rig_cache["devices"]["pi400"]["state"] == "off"


def test_relay_master_off_refused_while_device_alive(monkeypatch):
    rig.rig_cache["master"]["switchable"] = True
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    with pytest.raises(rig.RigError) as e:
        _run(rig.master_power(False))
    assert e.value.status == 409
    assert "Pi 400" in e.value.reason


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
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    rig.rig_cache["devices"]["gtv"]["state"] = "booting"
    _run(rig.master_power(False))
    assert sorted(stopped) == ["gtv", "pi400"]


def test_software_master_off_refused_while_busy():
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    rig.rig_cache["devices"]["pi400"]["busy"] = True
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
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    with pytest.raises(rig.RigError):
        _run(rig.master_power(False))


def test_tapo_master_off_unpowers_devices(monkeypatch):
    monkeypatch.setattr(rig, "master_tapo_ip", lambda: "10.0.0.5")

    async def _status(ip, **kw):
        return {"on": False, "watts": 0.0, "ip": ip}
    monkeypatch.setattr(rig, "plug_status", _status)
    _run(rig.poll_once())
    for name, d in rig.rig_cache["devices"].items():
        if rig.RIG["devices"][name].get("parked"):
            continue
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
    rig.rig_cache["devices"]["bbox"]["state"] = "ready"
    rig.rig_cache["devices"]["gtv"]["state"] = "ready"
    _run(rig.claim_screen("bbox"))
    assert calls == [("10.0.0.9", rig.RIG["devices"]["bbox"]["hdmi_input"])]
    assert rig.rig_cache["screen_owner"] == "bbox"


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
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    rig.rig_cache["devices"]["gtv"]["state"] = "ready"
    _run(rig.claim_screen("pi400"))
    assert ("Google TV", False) in calls
    assert ("Pi 400", True) in calls
    assert rig.rig_cache["screen_owner"] == "pi400"


def test_claim_screen_refused_for_unpowered_target():
    with pytest.raises(rig.RigError) as e:
        _run(rig.claim_screen("pi400"))   # state off
    assert e.value.status == 409


def test_claim_screen_refused_while_any_job_runs():
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    rig.rig_cache["devices"]["gtv"]["busy"] = True
    with pytest.raises(rig.RigError) as e:
        _run(rig.claim_screen("pi400"))
    assert e.value.status == 409


def test_claim_screen_failure_is_reported_not_swallowed(monkeypatch):
    """2026-07-29 live lesson (legacy PA329C path): a silently failing signal
    command made the UI claim success while the panel never moved. 502."""
    monkeypatch.setitem(rig.RIG["monitor"], "lg_host", None)   # legacy path
    def _boom(dev, on):
        raise RuntimeError(f"{dev['label']}: output control failed")
    monkeypatch.setattr(rig, "set_signal", _boom)
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    rig.rig_cache["devices"]["gtv"]["state"] = "ready"
    with pytest.raises(rig.RigError) as e:
        _run(rig.claim_screen("gtv"))
    assert e.value.status == 502
    assert "claim incomplete" in e.value.reason
    assert rig.rig_cache["screen_owner"] is None


def test_screen_owner_cleared_when_owner_powers_off(monkeypatch):
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    rig.rig_cache["screen_owner"] = "pi400"
    _stub_plugs(monkeypatch, on=False, watts=0.0)
    _run(rig.poll_once())
    assert rig.rig_cache["screen_owner"] is None


def test_recycle_c2_panel_reboots_to_home(monkeypatch):
    """C2 screen-run prep: power-cycle Lab-E, wait for webOS, go Home."""
    sets = []

    async def _set(ip, on, **kw):
        sets.append((ip, on))
    monkeypatch.setattr(rig, "plug_set", _set)
    monkeypatch.setattr(rig, "probe_ready", lambda dev: True)
    homes = []
    monkeypatch.setattr(rig.lg, "go_home", lambda host: homes.append(host))

    async def _nosleep(_s):
        return None
    monkeypatch.setattr(rig.asyncio, "sleep", _nosleep)

    _run(rig.recycle_c2_panel("c2"))
    ip = rig.RIG["devices"]["c2"]["plug_ip"]
    assert (ip, False) in sets and (ip, True) in sets        # power-cycled
    assert homes == [rig.RIG["devices"]["c2"]["target"]]     # booted to Home
    assert rig.rig_cache["devices"]["c2"]["state"] == "ready"


def test_recycle_c2_panel_rejects_non_webos():
    with pytest.raises(rig.RigError) as e:
        _run(rig.recycle_c2_panel("pi400"))
    assert e.value.status == 400


def test_status_payload_shape():
    p = rig.status_payload()
    assert set(p) == {"master", "monitor", "devices", "screen_owner",
                      "screen_settling", "total_w", "saving_note", "age_s",
                      "idle_off"}
    for name, d in p["devices"].items():
        assert set(d) == {"label", "plug_name", "device_class", "shape", "silicon",
                          "os", "chip_vendor", "target", "target_source", "hdmi_input",
                          "screen_claimable", "conn", "state", "watts", "busy",
                          "detail", "elapsed_s", "expected_s", "adb_auth",
                          "network"}
        assert d["device_class"] in ("sbc", "stb", "tv")
        assert d["conn"] in ("ssh", "adb", "webos", "atv", "roku")
        assert d["network"] in ("ethernet", "wifi")
    # Transparency: which devices are Wi-Fi (2026-08-29: no longer just the
    # Fire TV Stick — Roku has no Ethernet port either; Xiaomi also has none
    # but is `parked` (bricked pending a replacement unit) so it's hidden
    # from this payload entirely, same as any other parked device).
    assert [n for n, d in p["devices"].items() if d["network"] == "wifi"] == \
        ["firestick", "roku"]
    assert "xiaomi" not in p["devices"]   # parked — hidden from the console
    assert p["monitor"]["panel"]          # bench schematic display identity
    assert p["monitor"]["plug_name"] == "Lab-E"


def test_lab_c_router_plug_never_in_config_or_payload():
    """192.168.1.35 (Lab-C) powers the Bouygues router — relay-off would kill
    the LAN including the path to recover it. It must never be part of the
    rig surface."""
    import json
    assert "192.168.1.35" not in json.dumps(rig.RIG)
    assert "192.168.1.35" not in json.dumps(rig.status_payload())


# --- Idle auto-off (2026-08-15: rig found fully powered after a week away) ---

def _idle_settings(monkeypatch, enabled=True, hours=4.0, monitor=False):
    monkeypatch.setattr(rig, "idle_off_settings",
                        lambda: {"enabled": enabled, "hours": hours,
                                 "monitor": monitor})


def _no_hold(monkeypatch, tmp_path):
    monkeypatch.setattr(rig, "RIG_HOLD_FILE", tmp_path / "hold")


def test_idle_off_fires_after_window_and_stops_every_powered_box(monkeypatch, tmp_path):
    _idle_settings(monkeypatch); _no_hold(monkeypatch, tmp_path)
    stopped = []

    async def _fake_off(name):
        stopped.append(name)
        rig.rig_cache["devices"][name]["state"] = "stopping"
    monkeypatch.setattr(rig, "device_off", _fake_off)
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    rig.rig_cache["devices"]["gtv"]["state"] = "stuck"
    rig.rig_cache["devices"]["c2"]["state"] = "ready"   # webOS: never a target
    rig.rig_cache["last_activity"] = time.time() - 4.5 * 3600
    assert _run(rig._maybe_idle_off()) is True
    assert sorted(stopped) == ["gtv", "pi400"]
    last = rig.rig_cache["idle_off_last"]
    assert last["idle_h"] >= 4.4 and sorted(last["stopped"]) == ["gtv", "pi400"]
    # Clock reset — a second sweep right after does not fire again.
    assert _run(rig._maybe_idle_off()) is False


def test_idle_off_waits_for_the_window(monkeypatch, tmp_path):
    _idle_settings(monkeypatch); _no_hold(monkeypatch, tmp_path)
    monkeypatch.setattr(rig, "device_off", None)   # would explode if called
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    rig.rig_cache["last_activity"] = time.time() - 3.9 * 3600
    assert _run(rig._maybe_idle_off()) is False
    st = rig.idle_off_state()
    assert st["armed"] and 0 < st["off_in_s"] <= 0.1 * 3600 + 5


def test_idle_off_disabled_or_nothing_powered_is_a_noop(monkeypatch, tmp_path):
    _no_hold(monkeypatch, tmp_path)
    monkeypatch.setattr(rig, "device_off", None)
    rig.rig_cache["last_activity"] = time.time() - 40 * 3600
    _idle_settings(monkeypatch, enabled=False)
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    assert _run(rig._maybe_idle_off()) is False
    assert rig.idle_off_state()["armed"] is False
    _idle_settings(monkeypatch, enabled=True)
    rig.rig_cache["devices"]["pi400"]["state"] = "off"
    assert _run(rig._maybe_idle_off()) is False
    assert rig.idle_off_state()["off_in_s"] is None


def test_idle_off_never_cuts_a_running_job(monkeypatch, tmp_path):
    _idle_settings(monkeypatch); _no_hold(monkeypatch, tmp_path)
    monkeypatch.setattr(rig, "device_off", None)
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    rig.rig_cache["devices"]["pi400"]["busy"] = True
    rig.rig_cache["last_activity"] = time.time() - 40 * 3600
    assert _run(rig._maybe_idle_off()) is False
    # A busy poll counts as activity — the window restarts once the job ends.
    assert time.time() - rig.rig_cache["last_activity"] < 5


def test_idle_off_honours_a_fresh_bench_hold_file(monkeypatch, tmp_path):
    """Standalone bench.py campaigns touch RIG_HOLD_FILE per row — a fresh
    touch is activity; a stale one (crashed campaign) is not."""
    _idle_settings(monkeypatch)
    hold = tmp_path / "hold"
    monkeypatch.setattr(rig, "RIG_HOLD_FILE", hold)
    monkeypatch.setattr(rig, "device_off", None)
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    rig.rig_cache["last_activity"] = time.time() - 40 * 3600
    hold.touch()
    assert _run(rig._maybe_idle_off()) is False
    assert rig.idle_off_state()["hold_active"] is True
    import os
    stale = time.time() - rig.HOLD_STALE_S - 60
    os.utime(hold, (stale, stale))
    stopped = []

    async def _fake_off(name):
        stopped.append(name)
    monkeypatch.setattr(rig, "device_off", _fake_off)
    assert _run(rig._maybe_idle_off()) is True
    assert stopped == ["pi400"]


def test_idle_off_monitor_opt_in(monkeypatch, tmp_path):
    _no_hold(monkeypatch, tmp_path)
    calls = []

    async def _fake_off(name):
        calls.append(name)

    async def _mon(on):
        calls.append(("monitor", on))
    monkeypatch.setattr(rig, "device_off", _fake_off)
    monkeypatch.setattr(rig, "monitor_power", _mon)
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    rig.rig_cache["last_activity"] = time.time() - 40 * 3600
    _idle_settings(monkeypatch, monitor=False)
    _run(rig._maybe_idle_off())
    assert calls == ["pi400"]
    calls.clear()
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    rig.rig_cache["last_activity"] = time.time() - 40 * 3600
    _idle_settings(monkeypatch, monitor=True)
    _run(rig._maybe_idle_off())
    assert calls == ["pi400", ("monitor", False)]


def test_idle_off_then_switchable_master_cut(monkeypatch, tmp_path):
    _idle_settings(monkeypatch); _no_hold(monkeypatch, tmp_path)
    rig.rig_cache["master"]["switchable"] = True
    rig.rig_cache["master"]["configured"] = True
    calls = []

    async def _fake_off(name):
        rig.rig_cache["devices"][name]["state"] = "off"
        calls.append(name)

    async def _master(on):
        calls.append(("master", on))
    monkeypatch.setattr(rig, "device_off", _fake_off)
    monkeypatch.setattr(rig, "master_power", _master)
    rig.rig_cache["devices"]["pi400"]["state"] = "ready"
    rig.rig_cache["last_activity"] = time.time() - 40 * 3600

    async def _go():
        assert await rig._maybe_idle_off() is True
        await asyncio.sleep(0.05)   # let the follow-up task run
    _run(_go())
    assert calls == ["pi400", ("master", False)]
    assert rig.rig_cache["idle_off_last"]["master"] == "off"


def test_control_ops_and_external_power_count_as_activity(monkeypatch):
    rig.rig_cache["last_activity"] = time.time() - 40 * 3600

    async def _set(ip, on, **kw):
        pass
    monkeypatch.setattr(rig, "plug_set", _set)
    _run(rig.device_on("pi400"))
    assert time.time() - rig.rig_cache["last_activity"] < 5
    # Box powered from the Tapo app: the poller adopts it AND restarts the clock.
    rig.rig_cache["devices"]["gtv"]["state"] = "off"
    rig.rig_cache["last_activity"] = time.time() - 40 * 3600
    _stub_plugs(monkeypatch, on=True, watts=0.1)
    _run(rig._step_device("gtv", master_off=False))
    assert rig.rig_cache["devices"]["gtv"]["state"] == "powering"
    assert time.time() - rig.rig_cache["last_activity"] < 5


def test_status_payload_carries_idle_off(monkeypatch, tmp_path):
    _idle_settings(monkeypatch); _no_hold(monkeypatch, tmp_path)
    p = rig.status_payload()
    assert set(p["idle_off"]) >= {"enabled", "hours", "idle_s", "armed",
                                  "off_in_s", "hold_active", "last"}


# --- adb authorisation (2026-08-15: both adb boxes stuck-unauthorised) -------

def test_unauthorized_adb_box_is_named_not_generic_stuck(monkeypatch):
    _stub_plugs(monkeypatch, on=True, watts=1.2)
    monkeypatch.setattr(rig, "adb_auth_state",
                        lambda dev: "unauthorized" if dev["kind"] == "adb" else None)
    _run(rig.poll_once())
    g = rig.rig_cache["devices"]["gtv"]
    assert g["state"] == "stuck" and g["adb_auth"] == "unauthorized"
    assert "not authorised" in g["detail"]
    assert rig.status_payload()["devices"]["gtv"]["adb_auth"] == "unauthorized"
    # ssh boxes are untouched by the adb check
    assert rig.rig_cache["devices"]["pi400"]["state"] in ("powering", "booting")


def test_stuck_box_self_heals_when_probe_recovers(monkeypatch):
    _stub_plugs(monkeypatch, on=True, watts=4.0)
    d = rig.rig_cache["devices"]["gtv"]
    d.update({"state": "stuck", "boot_started": time.monotonic(),
              "detail": "not ready"})
    monkeypatch.setattr(rig, "probe_ready", lambda dev: True)
    monkeypatch.setattr(rig.time, "monotonic", lambda: 12.0)   # inside the re-probe window
    _run(rig.poll_once())
    assert d["state"] == "ready" and d["adb_auth"] is None


def test_adb_repair_claims_screen_and_reconnects_once(monkeypatch):
    calls = []
    monkeypatch.setattr(rig, "adb_reconnect", lambda dev: calls.append(dev["label"]))
    monkeypatch.setattr(rig, "adb_auth_state", lambda dev: "unauthorized")
    monkeypatch.setattr(rig, "adb_host_fingerprint", lambda: "AA:BB")
    monkeypatch.setattr(rig.lg, "set_input", lambda host, inp: None)
    monkeypatch.setattr(rig.asyncio, "sleep", _fake_sleep)
    rig.rig_cache["devices"]["gtv"]["state"] = "stuck"
    out = _run(rig.adb_repair("gtv"))
    assert calls == ["Google TV"]
    assert out["fingerprint"] == "AA:BB" and out["adb_auth"] == "unauthorized"
    assert rig.rig_cache["screen_owner"] == "gtv"


def test_adb_repair_refused_for_ssh_and_unpowered():
    with pytest.raises(rig.RigError) as e:
        _run(rig.adb_repair("pi400"))
    assert e.value.status == 400
    with pytest.raises(rig.RigError) as e:
        _run(rig.adb_repair("gtv"))       # state off
    assert e.value.status == 409


async def _fake_sleep(s):
    return None


def test_target_overrides_follow_settings_and_revert():
    import rig
    default_gtv = rig.RIG_TARGETS_DEFAULT["gtv"]
    eff = rig.apply_target_overrides({"gtv": "192.168.1.143:5555", "nope": "x"})
    assert eff["gtv"] == "192.168.1.143:5555"
    assert rig.RIG["devices"]["gtv"]["target"] == "192.168.1.143:5555"
    eff = rig.apply_target_overrides({})
    assert rig.RIG["devices"]["gtv"]["target"] == default_gtv
    assert eff["gtv"] == default_gtv


# --- Target discovery by MAC (2026-08-26) -------------------------------------

_NEIGH = """192.168.1.10 dev eno2 FAILED
192.168.1.173 dev eno2 lladdr 70:F7:54:37:4F:E4 REACHABLE
192.168.1.99 dev eno2 lladdr 70:f7:54:37:4f:e4 STALE
192.168.1.126 dev eno2 lladdr b4:23:a2:af:e4:a4 STALE
192.168.1.1 dev eno2 lladdr 00:11:22:33:44:55 INCOMPLETE
"""


def test_parse_neigh_prefers_fresh_entry_and_ignores_failed():
    t = rig._parse_neigh(_NEIGH)
    assert t["70:f7:54:37:4f:e4"] == "192.168.1.173"   # REACHABLE beats STALE, case-folded
    assert t["b4:23:a2:af:e4:a4"] == "192.168.1.126"
    assert "00:11:22:33:44:55" not in t


def test_discover_target_sweeps_once_when_table_is_cold(monkeypatch):
    tables = [{}, {"70:f7:54:37:4f:e4": "192.168.1.173"}]
    swept = []
    monkeypatch.setattr(rig, "_neigh_table", lambda: tables.pop(0))
    monkeypatch.setattr(rig, "_ping_sweep", lambda: swept.append(1))
    dev = {"kind": "adb", "macs": ["EC:6C:9A:EF:73:A1", "70:f7:54:37:4f:e4"]}
    assert rig.discover_target(dev) == "192.168.1.173:5555"
    assert swept == [1]
    assert rig.discover_target({"kind": "adb"}) is None      # no MACs → no scan


def test_discovered_target_outranks_settings_and_default():
    rig.DISCOVERED_TARGETS["bbox"] = "192.168.1.173:5555"
    eff = rig.apply_target_overrides({"bbox": "192.168.1.50:5555"})
    assert eff["bbox"] == "192.168.1.173:5555"
    assert rig.target_source("bbox") == "discovered"
    rig.DISCOVERED_TARGETS.clear()
    eff = rig.apply_target_overrides({"bbox": "192.168.1.50:5555"})
    assert eff["bbox"] == "192.168.1.50:5555"
    assert rig.target_source("bbox") == "settings"
    rig.apply_target_overrides({})
    assert rig.target_source("bbox") == "default"


def test_poller_follows_a_box_to_its_new_lease_and_forgets_it_when_off(monkeypatch):
    """Bbox powered, not answering on .10 past its boot time → the sweep
    finds its Wi-Fi MAC at .173 → target switches, then ADB succeeds → ready
    with the provenance in the detail; plug off → back to the default."""
    _stub_plugs(monkeypatch, on=True, watts=4.9)
    monkeypatch.setattr(rig, "discover_target", lambda dev: "192.168.1.173:5555")
    d = rig.rig_cache["devices"]["bbox"]
    d.update({"state": "booting", "boot_started": time.monotonic() - 200})
    _run(rig.poll_once())
    assert rig.RIG["devices"]["bbox"]["target"] == "192.168.1.173:5555"
    assert rig.DISCOVERED_TARGETS["bbox"] == "192.168.1.173:5555"
    assert d["state"] == "booting" and "found at 192.168.1.173:5555" in d["detail"]
    # the sweep is rate-limited: past boot time again but inside the window → no rescan
    calls = []
    monkeypatch.setattr(rig, "discover_target", lambda dev: calls.append(1) or None)
    d.update({"boot_started": time.monotonic() - 60})
    _run(rig.poll_once())
    assert calls == [] and d["state"] == "booting"
    monkeypatch.setattr(rig, "probe_ready", lambda dev: dev["target"] == "192.168.1.173:5555")
    _run(rig.poll_once())
    assert d["state"] == "ready" and "followed by MAC" in d["detail"]
    payload = rig.status_payload()["devices"]["bbox"]
    assert payload["target"] == "192.168.1.173:5555"
    assert payload["target_source"] == "discovered"
    _stub_plugs(monkeypatch, on=False, watts=0.0)
    _run(rig.poll_once())
    assert "bbox" not in rig.DISCOVERED_TARGETS
    rig.apply_target_overrides({})
    assert rig.RIG["devices"]["bbox"]["target"] == rig.RIG_TARGETS_DEFAULT["bbox"]


def test_poller_does_not_sweep_before_the_box_has_had_time_to_boot(monkeypatch):
    _stub_plugs(monkeypatch, on=True, watts=4.9)
    calls = []
    monkeypatch.setattr(rig, "discover_target", lambda dev: calls.append(1) or None)
    d = rig.rig_cache["devices"]["bbox"]
    d.update({"state": "booting", "boot_started": time.monotonic() - 5})
    _run(rig.poll_once())
    assert calls == [] and d["state"] == "booting"


# --- Screen map: four HDMI sockets, seven devices (2026-08-26) ----------------

def test_hdmi_defaults_leave_pi5_pi400_and_firestick_headless():
    # 2026-08-29 reshuffle (Ben's actual on-site cabling during the switch
    # install): Roku took HDMI_3 from the Pi 400; Apple TV took HDMI_4 from
    # the Fire TV (it cannot be measured headless at all — VLC pauses on
    # HDMI loss). Both Pi boards and the Fire TV are fully valid headless
    # (ADB/SSH prove decode without a screen) — though the Fire TV and the
    # (never-cabled) Xiaomi still owe a live no-HDMI-sink smoke test before
    # their headless rows can be trusted (Ben's catch, same date).
    m = rig.apply_hdmi_assignments({})
    assert set(m) == {"HDMI_1", "HDMI_2", "HDMI_3", "HDMI_4"}
    assert m["HDMI_1"] == "bbox" and m["HDMI_2"] == "gtv"
    assert m["HDMI_3"] == "roku" and m["HDMI_4"] == "atv"
    assert rig.RIG["devices"]["pi5"]["hdmi_input"] is None
    assert rig.RIG["devices"]["pi400"]["hdmi_input"] is None
    assert rig.RIG["devices"]["firestick"]["hdmi_input"] is None
    assert rig.RIG["devices"]["xiaomi"]["hdmi_input"] is None
    assert rig.RIG["devices"]["c2"]["hdmi_input"] is None
    assert rig.hdmi_map() == m


def test_hdmi_assignment_recables_a_socket_and_unplugs_the_previous_device():
    # Fire TV takes the Bbox's socket; "" unplugs the Bbox explicitly.
    m = rig.apply_hdmi_assignments({"firestick": "HDMI_1", "bbox": ""})
    assert m["HDMI_1"] == "firestick"
    assert rig.RIG["devices"]["firestick"]["hdmi_input"] == "HDMI_1"
    assert rig.RIG["devices"]["bbox"]["hdmi_input"] is None
    # devices not mentioned keep their rig.py default
    assert rig.RIG["devices"]["gtv"]["hdmi_input"] == "HDMI_2"
    rig.apply_hdmi_assignments({})
    assert rig.RIG["devices"]["bbox"]["hdmi_input"] == "HDMI_1"


def test_hdmi_assignment_one_device_per_socket_and_ignores_junk():
    # atv also asks for HDMI_2 — gtv (earlier in RIG order) keeps it.
    m = rig.apply_hdmi_assignments({"atv": "HDMI_2", "pi5": "HDMI_9", "c2": "HDMI_1", "nope": "HDMI_4"})
    assert m["HDMI_2"] == "gtv" and rig.RIG["devices"]["atv"]["hdmi_input"] is None
    assert rig.RIG["devices"]["pi5"]["hdmi_input"] is None       # unknown socket
    assert rig.RIG["devices"]["c2"]["hdmi_input"] is None        # the panel itself
    assert m["HDMI_1"] == "bbox"
    assert rig.apply_hdmi_assignments("garbage") == rig.apply_hdmi_assignments({})


def test_claim_screen_refused_for_headless_devices_with_a_pointer(monkeypatch):
    monkeypatch.setitem(rig.RIG["monitor"], "lg_host", "10.0.0.9")
    monkeypatch.setattr(rig.lg, "set_input", lambda host, hdmi: None)
    for name in ("pi5", "pi400"):
        rig.rig_cache["devices"][name]["state"] = "ready"
        with pytest.raises(rig.RigError) as e:
            _run(rig.claim_screen(name))
        assert e.value.status == 409 and "HDMI inputs" in e.value.reason and "/settings" in e.value.reason
    assert rig.rig_cache["screen_owner"] is None


def test_status_payload_carries_the_screen_map():
    rig.apply_hdmi_assignments({})
    p = rig.status_payload()
    assert p["monitor"]["hdmi_inputs"] == rig.hdmi_map()
    # 2026-08-29: atv now holds HDMI_4 by default (see the reshuffle note on
    # test_hdmi_defaults_leave_pi5_pi400_and_firestick_headless).
    assert p["devices"]["atv"]["hdmi_input"] == "HDMI_4"
    assert p["devices"]["gtv"]["hdmi_input"] == "HDMI_2"
    assert p["devices"]["atv"]["conn"] == "atv"
    assert p["devices"]["atv"]["screen_claimable"] is True
    assert p["devices"]["gtv"]["screen_claimable"] is True
    assert p["devices"]["c2"]["screen_claimable"] is True     # the panel itself
    rig.apply_hdmi_assignments({"pi400": "HDMI_4", "atv": ""})
    p = rig.status_payload()
    assert p["devices"]["pi400"]["screen_claimable"] is True and p["devices"]["atv"]["screen_claimable"] is False


# --- Apple TV device kind (pyatv) -------------------------------------------

def test_atv_power_state_parses_atvremote_output(monkeypatch):
    monkeypatch.setattr(rig, "atv_cmd", lambda dev, *c, **k: "PowerState.On\n")
    assert rig.atv_power_state(rig.RIG["devices"]["atv"]) == "On"
    monkeypatch.setattr(rig, "atv_cmd", lambda dev, *c, **k: "PowerState.Off\n")
    assert rig.atv_power_state(rig.RIG["devices"]["atv"]) == "Off"

    def boom(dev, *c, **k):
        raise RuntimeError("no venv")
    monkeypatch.setattr(rig, "atv_cmd", boom)
    assert rig.atv_power_state(rig.RIG["devices"]["atv"]) is None


def test_atv_probe_ready_and_graceful_shutdown_go_through_pyatv(monkeypatch):
    calls = []

    def fake(dev, *c, **k):
        calls.append(c)
        return "PowerState.On\n" if c == ("power_state",) else ""
    monkeypatch.setattr(rig, "atv_cmd", fake)
    assert _ORIG_PROBE_READY(rig.RIG["devices"]["atv"]) is True
    _ORIG_SEND_SHUTDOWN(rig.RIG["devices"]["atv"])
    assert ("turn_off",) in calls
    rig.set_signal(rig.RIG["devices"]["atv"], False)    # no-op, must not raise


def test_atv_is_followed_by_mac_as_a_bare_ip(monkeypatch):
    monkeypatch.setattr(rig, "_neigh_table", lambda: {"90:dd:5d:ab:70:8e": "192.168.1.77"})
    monkeypatch.setattr(rig, "_ping_sweep", lambda *a, **k: None)
    assert rig.discover_target(rig.RIG["devices"]["atv"]) == "192.168.1.77"
    assert rig.discover_target(rig.RIG["devices"]["bbox"]) is None      # not in the table


def test_atv_poller_readiness_via_power_state(monkeypatch):
    _stub_plugs(monkeypatch, on=True, watts=3.0)
    monkeypatch.setattr(rig, "probe_ready", lambda dev: dev["kind"] == "atv")
    d = rig.rig_cache["devices"]["atv"]
    d.update({"state": "booting", "boot_started": time.monotonic() - 5})
    _run(rig.poll_once())
    assert d["state"] == "ready" and d["detail"] == "pyatv ok"


def test_atv_asleep_is_reported_not_stuck_and_on_wakes_it(monkeypatch):
    calls = []

    def fake(dev, *c, **k):
        calls.append(c)
        return "PowerState.Off\n" if c == ("power_state",) else ""
    monkeypatch.setattr(rig, "atv_cmd", fake)
    monkeypatch.setattr(rig, "probe_ready", lambda dev: _ORIG_PROBE_READY(dev) if dev["kind"] == "atv" else False)
    _stub_plugs(monkeypatch, on=True, watts=1.5)
    d = rig.rig_cache["devices"]["atv"]
    d.update({"state": "booting", "boot_started": time.monotonic() - 500})
    _run(rig.poll_once())
    assert d["state"] == "booting" and "asleep" in d["detail"]     # never "stuck"

    async def _set(ip, on, **kw):
        pass
    monkeypatch.setattr(rig, "plug_set", _set)
    _run(rig.device_on("atv"))
    assert ("turn_on",) in calls
