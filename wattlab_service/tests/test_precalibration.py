"""
CR-024 · thermal-recovery probe promoted to a queued server job.

Unit coverage for the pure engine helpers + endpoint wiring + button render.
The ~65-min probe itself (real CPU/GPU encodes) needs GoS1 and is not run here;
these pin everything around it: distance parsing, ETA, param resolution, the
missing-input guard, the enqueue + status endpoints, and the /settings button.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

import main
import precalibration
import queue_control

# VARIANCE_RUN + the precal panel are Lab-gated; TestClient's client.host is
# "testclient" (not an IP) so it resolves Anonymous by default. This header
# makes the origin loopback → Lab, matching how the operator reaches /settings.
_LAB = {"x-real-ip": "127.0.0.1"}


# --- pure helpers ----------------------------------------------------------

def test_parse_distances_from_string_sorted_unique():
    assert precalibration.parse_distances("0,5,12") == [0, 5, 12]
    assert precalibration.parse_distances("12,5,0,5") == [0, 5, 12]


def test_parse_distances_from_list():
    assert precalibration.parse_distances([3, 1, 2, 1]) == [1, 2, 3]


def test_parse_distances_falls_back_on_garbage():
    d = precalibration.DEFAULT_DISTANCES
    assert precalibration.parse_distances("nonsense") == d
    assert precalibration.parse_distances("") == d
    assert precalibration.parse_distances(None) == d
    assert precalibration.parse_distances([-5, -1]) == d  # all-negative filtered → empty → default


def test_probe_params_null_baseline_resolves_to_baseline_polls():
    s = {"precal_distances": "0,10", "precal_pre_cool_s": 20,
         "precal_baseline_polls": None, "baseline_polls": 7}
    dist, pre, npolls = precalibration._probe_params(s)
    assert dist == [0, 10]
    assert pre == 20
    assert npolls == 7  # null → baseline_polls, per the CR default


def test_probe_params_explicit_baseline_wins():
    _, _, npolls = precalibration._probe_params(
        {"precal_baseline_polls": 15, "baseline_polls": 7})
    assert npolls == 15


def test_estimated_minutes_positive_and_monotonic():
    small = precalibration.estimated_minutes([0, 10], 30, 10)
    big = precalibration.estimated_minutes([0, 10, 60, 120], 30, 10)
    assert small >= 1
    assert big > small


# --- engine guard (no encodes: fails before focus mode / lock) -------------

def test_run_raises_when_probe_input_missing(monkeypatch, tmp_path):
    """The input existence check runs before focus_mode_enter/LOCK_FILE, so a
    missing asset surfaces as a clean job error and never leaves the box in
    focus mode."""
    monkeypatch.setattr(precalibration, "_INPUT_CPU", tmp_path / "missing.mp4")
    with pytest.raises(FileNotFoundError):
        asyncio.run(precalibration.run_thermal_recovery_probe("j", {}))


# --- endpoints -------------------------------------------------------------

def test_precalibration_run_enqueues_precalibration_job(monkeypatch):
    """POST /precalibration/run mirrors /variance/run: enqueues a
    'precalibration' job and returns its id/position. enqueue is stubbed so the
    worker never starts a real encode."""
    seen = {}

    def fake_enqueue(job_id, job_type, label, coro, request=None):
        seen["job_type"] = job_type
        seen["label"] = label
        return 1

    monkeypatch.setattr(queue_control, "enqueue", fake_enqueue)
    r = TestClient(main.app).post("/precalibration/run", headers=_LAB)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["job_id"]
    assert data["queue_position"] == 1
    assert seen["job_type"] == "precalibration"


def test_precalibration_run_429_when_queue_full(monkeypatch):
    monkeypatch.setattr(queue_control, "enqueue",
                        lambda *a, **k: None)  # queue full → None
    r = TestClient(main.app).post("/precalibration/run", headers=_LAB)
    assert r.status_code == 429


def test_precalibration_job_status_reports_stage():
    from runtime import jobs
    jobs["tprecal"] = {"status": "running", "stage": "distance 5s (2/12)"}
    try:
        r = TestClient(main.app).get("/precalibration/job/tprecal")
        assert r.status_code == 200
        j = r.json()
        assert j["status"] == "running"
        assert "distance" in j["stage"]
    finally:
        jobs.pop("tprecal", None)


# --- /settings button render (Lab tier via loopback TestClient) ------------

def test_settings_page_renders_rerun_probe_button():
    body = TestClient(main.app).get("/settings", headers=_LAB).text
    assert 'id="precalBtn"' in body
    assert "runThermalProbe()" in body
    assert "Re-run probe" in body
    # ETA badge carries a server-computed estimate.
    assert "min" in body and "distances" in body
