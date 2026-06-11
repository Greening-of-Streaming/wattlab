"""
CR-065 — dual daisy-chained P110, staggered polling.

Covers the four contract points of the integration:
  1. Single-meter parity: with no TAPO_P110_IP_2, the shared samplers return
     exactly the pre-CR-065 shapes and meters_summary stays None.
  2. Dual-meter capture: secondary samples ride the baseline dict /
     TaskReadings sidecar, staggered by half the interval.
  3. Fail-soft: a dropped secondary stream degrades the run to honest
     single-meter data (flagged, never silently dual).
  4. The ci2 combine: per-meter ΔW against each meter's own baseline (the
     daisy-chain offset cancels), simple-mean combine, n_task gates stay on
     the primary poll count.

The registry is monkeypatched (power._meter_ips) so these tests never depend
on the host's real .env — the GoS1 dev box genuinely has two meters wired.
"""
import asyncio

import pytest

import power
from confidence import confidence


# Settings dict for confidence() — explicit so the host settings.json can't
# steer the assertions.
CONF_S = {
    "variance_idle_pct": 2.0, "variance_idle_drift_pct": 0.0,
    "conf_positive_green": 0.95, "conf_positive_yellow": 0.80,
    "conf_green_polls": 10, "conf_yellow_polls": 5,
    "variance_pct": 2.0, "variance_green_x": 3.0, "variance_yellow_x": 1.5,
}


def _single(monkeypatch):
    monkeypatch.setattr(power, "_meter_ips", lambda: ["10.0.0.1"])


def _dual(monkeypatch, secondary=None, fail_after=None):
    """Register two meters and script the secondary's readings."""
    monkeypatch.setattr(power, "_meter_ips", lambda: ["10.0.0.1", "10.0.0.2"])
    seq = {"i": 0}

    async def fake_read(idx=0, retries=3):
        assert idx == 1, "samplers must read the primary via read_watts only"
        i = seq["i"]
        seq["i"] += 1
        if fail_after is not None and i >= fail_after:
            raise RuntimeError("secondary meter gone")
        vals = secondary or [80.0]
        return vals[i % len(vals)]

    monkeypatch.setattr(power, "_read_meter_watts", fake_read)


async def _primary():
    return 79.0


# --- 1. Single-meter parity --------------------------------------------------

def test_baseline_single_meter_parity(monkeypatch):
    _single(monkeypatch)
    b = asyncio.run(power.sample_baseline(3, read_watts=_primary, interval=0))
    assert b == {"w_base": 79.0, "samples_w": [79.0, 79.0, 79.0]}


def test_task_single_meter_parity(monkeypatch):
    _single(monkeypatch)

    async def run():
        stop = asyncio.Event()
        task = asyncio.create_task(
            power.sample_task(stop, read_watts=_primary, tuples=True, interval=0))
        await asyncio.sleep(0.01)
        stop.set()
        return await task

    readings = asyncio.run(run())
    assert isinstance(readings, power.TaskReadings)
    assert readings.samples_w_2 is None and readings.degraded is False
    assert all(isinstance(r, tuple) and r[1] == 79.0 for r in readings)
    assert power.meters_summary({"samples_w": [79.0]}, readings, [79.0]) is None


def test_video_baseline_shape_unchanged(monkeypatch):
    import video
    _single(monkeypatch)
    monkeypatch.setattr(video, "get_power_watts", _primary)
    monkeypatch.setattr(video, "read_sensors",
                        lambda: {"cpu_tctl": 40.0, "gpu_junction": 50.0,
                                 "gpu_ppt_w": 10.0})
    monkeypatch.setattr(video, "POLL_INTERVAL", 0)
    b = asyncio.run(video.measure_baseline(polls=2))
    assert b == {"w_base": 79.0, "baseline_samples_w": [79.0, 79.0],
                 "cpu_temp_base": 40.0, "gpu_temp_base": 50.0}


# --- 2. Dual-meter capture ---------------------------------------------------

def test_baseline_dual_collects_secondary(monkeypatch):
    _dual(monkeypatch, secondary=[80.0, 80.5, 81.0])
    b = asyncio.run(power.sample_baseline(3, read_watts=_primary, interval=0))
    assert b["w_base"] == 79.0 and b["samples_w"] == [79.0] * 3
    assert b["baseline_samples_w_2"] == [80.0, 80.5, 81.0]
    assert "meter2_degraded" not in b


def test_task_dual_sidecar_and_stagger(monkeypatch):
    _dual(monkeypatch, secondary=[81.0])
    sleeps = []
    real_sleep = asyncio.sleep

    async def spy_sleep(d):
        sleeps.append(d)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", spy_sleep)

    async def run():
        stop = asyncio.Event()
        task = asyncio.create_task(
            power.sample_task(stop, read_watts=_primary, tuples=True,
                              interval=1.0))
        for _ in range(8):
            await real_sleep(0)
        stop.set()
        return await task

    readings = asyncio.run(run())
    assert readings.samples_w_2 and all(v == 81.0 for v in readings.samples_w_2)
    # The secondary's first sleep is the half-interval stagger.
    assert 0.5 in sleeps


# --- 3. Fail-soft ------------------------------------------------------------

def test_secondary_failure_degrades_not_fails(monkeypatch):
    _dual(monkeypatch, secondary=[80.0], fail_after=0)
    b = asyncio.run(power.sample_baseline(3, read_watts=_primary, interval=0))
    assert b["w_base"] == 79.0                      # primary untouched
    assert b.get("meter2_degraded") is True
    assert "baseline_samples_w_2" not in b

    readings = power.TaskReadings([(0, 79.0)])
    readings.degraded = True
    assert power.meters_summary(b, readings, [79.0]) == {"degraded": True}


def test_meters_summary_degraded_when_either_side_missing(monkeypatch):
    # Baseline captured both meters but the task stream dropped → degraded.
    readings = power.TaskReadings([(0, 100.0)])
    baseline = {"samples_w": [79.0, 79.0], "baseline_samples_w_2": [80.0, 80.0]}
    assert power.meters_summary(baseline, readings, [100.0]) == {"degraded": True}


# --- 4. Combine maths + ci2 --------------------------------------------------

def test_meters_summary_offset_cancels():
    # Outer meter reads a constant +1 W (inner-plug self-draw): per-meter ΔW
    # combine must return the same delta as the inner meter alone.
    baseline = {"baseline_samples_w": [79.0, 79.2, 78.8],
                "baseline_samples_w_2": [80.0, 80.2, 79.8]}
    readings = power.TaskReadings([(0, 0)])
    readings.samples_w_2 = [180.0, 180.2, 179.8]
    task_1 = [179.0, 179.2, 178.8]
    m = power.meters_summary(baseline, readings, task_1)
    assert m["combine_method"] == "mean"
    assert m["inner"]["delta_w"] == 100.0
    assert m["outer"]["delta_w"] == 100.0
    assert m["delta_w_combined"] == 100.0
    assert m["inner"]["w_base"] == 79.0 and m["outer"]["w_base"] == 80.0
    assert m["outer"]["task_samples_w"] == [180.0, 180.2, 179.8]


def test_confidence_ci2_method_and_tighter_se():
    base_1 = [79.0, 79.5, 78.5, 79.2, 78.8]
    task_1 = [150.0, 151.0, 149.0, 150.5, 149.5, 150.2]
    base_2 = [80.0, 80.4, 79.6, 80.1, 79.9]
    task_2 = [151.0, 151.8, 150.2, 151.4, 150.6, 151.1]
    meters = {"outer": {"baseline_samples_w": base_2, "task_samples_w": task_2}}
    single = confidence(71.0, len(task_1), 79.0, baseline_samples_w=base_1,
                        task_samples_w=task_1, s=CONF_S)
    dual = confidence(71.0, len(task_1), 79.0, baseline_samples_w=base_1,
                      task_samples_w=task_1, s=CONF_S, meters=meters)
    assert single["method"] == "ci"
    assert dual["method"] == "ci2"
    # Two independent meters: combined SE = √(SE₁²+SE₂²)/2 < either alone.
    assert dual["se_final_w"] < single["se_final_w"]


def test_confidence_ci2_n_task_gate_stays_primary():
    # 4 primary polls < conf_yellow_polls=5 → 🔴 even though the dual streams
    # carry 8 samples total: the gate is a task-duration proxy, and a second
    # meter doesn't lengthen the task.
    base = [79.0, 79.1, 78.9, 79.0, 79.0]
    task = [150.0, 150.5, 149.5, 150.2]
    meters = {"outer": {"baseline_samples_w": [80.0, 80.1, 79.9, 80.0, 80.0],
                        "task_samples_w": [151.0, 151.5, 150.5, 151.2]}}
    r = confidence(71.0, len(task), 79.0, baseline_samples_w=base,
                   task_samples_w=task, s=CONF_S, meters=meters)
    assert r["method"] == "ci2"
    assert r["flag"] == "🔴"


def test_confidence_degraded_meters_falls_back_to_ci():
    base = [79.0, 79.5, 78.5]
    task = [150.0, 151.0, 149.0]
    plain = confidence(71.0, 3, 79.0, baseline_samples_w=base,
                       task_samples_w=task, s=CONF_S)
    degraded = confidence(71.0, 3, 79.0, baseline_samples_w=base,
                          task_samples_w=task, s=CONF_S,
                          meters={"degraded": True})
    assert degraded == plain
    assert degraded["method"] == "ci"


# --- Cached-handle rebuild (KLAP sessions are exclusive) ----------------------

def test_read_meter_rebuilds_handle_on_error(monkeypatch):
    _config = {"TAPO_EMAIL": "x", "TAPO_PASSWORD": "y",
               "TAPO_P110_IP": "10.0.0.1"}
    monkeypatch.setattr(power, "_config", _config)
    monkeypatch.setattr(power, "_meter_ips", lambda: ["10.0.0.1"])
    power._DEVICE_CACHE.clear()
    builds = []

    class FakeEnergy:
        current_power = 79123

    class FakeDevice:
        def __init__(self):
            self.calls = 0

        async def get_energy_usage(self):
            self.calls += 1
            # First handle dies on its first read (session stolen elsewhere).
            if len(builds) == 1 and self.calls == 1:
                raise RuntimeError("403 Forbidden")
            return FakeEnergy()

    class FakeClient:
        def __init__(self, email, password):
            pass

        async def p110(self, ip):
            builds.append(ip)
            return FakeDevice()

    monkeypatch.setattr(power, "ApiClient", FakeClient)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    try:
        w = asyncio.run(power._read_meter_watts(0))
    finally:
        power._DEVICE_CACHE.clear()
    assert w == pytest.approx(79.123)
    assert len(builds) == 2          # dropped + rebuilt after the 403


def test_ui_config_exposes_meter_cadence(monkeypatch):
    monkeypatch.setattr(power, "_meter_ips", lambda: ["10.0.0.1", "10.0.0.2"])
    from fastapi.testclient import TestClient
    import main
    body = TestClient(main.app).get("/ui-config.js").text
    assert "meter_cadence" in body
    assert "two staggered meters" in body
