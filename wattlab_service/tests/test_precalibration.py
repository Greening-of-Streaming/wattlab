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


# --- recovery read scaled to the node (2026-10-10) --------------------------

def _pts(rows):
    return [{"distance_s": d, "workload": w, "mean_w": m} for d, w, m in rows]


# GoS2's 2026-10-10 probe (recovery_20261010_074153_summary.csv), floor ~1.37 W.
_GOS2 = _pts([
    (0, "cpu", 30.054), (2, "cpu", 4.052), (5, "cpu", 1.925), (8, "cpu", 1.823),
    (12, "cpu", 1.789), (18, "cpu", 1.73), (25, "cpu", 1.569), (35, "cpu", 1.394),
    (50, "cpu", 1.395), (70, "cpu", 1.373), (95, "cpu", 1.412), (120, "cpu", 1.408),
    (0, "gpu", 26.559), (2, "gpu", 2.865), (5, "gpu", 1.437), (8, "gpu", 1.405),
    (12, "gpu", 1.396), (18, "gpu", 1.452), (25, "gpu", 1.352), (35, "gpu", 1.469),
    (50, "gpu", 1.357), (70, "gpu", 1.341), (95, "gpu", 1.332), (120, "gpu", 1.331),
])


def test_recovery_low_floor_node_sees_the_cpu_tail():
    """The old fixed ±1 W rule called GoS2's CPU curve recovered at 5 s while it
    sat +0.55 W (+40 %) above a 1.4 W floor; the scaled rule waits for 35 s."""
    r = precalibration.recovery_summary(_GOS2)
    assert 1.3 < r["floor_w"] < 1.45
    assert r["tolerance_w"] < 0.2
    assert r["recovery_s"] == {"cpu": 35, "gpu": 5}
    assert r["encodes_per_point"] == 1


def test_recovery_must_stay_within_tolerance():
    """A point that dips inside the band and climbs out again doesn't count."""
    pts = _pts([(0, "cpu", 100), (5, "cpu", 76.0), (10, "cpu", 80.0), (20, "cpu", 76.2),
                (60, "cpu", 76.0), (90, "cpu", 76.1)])
    assert precalibration.recovery_summary(pts)["recovery_s"]["cpu"] == 20


def test_recovery_tolerance_never_tighter_than_two_percent():
    pts = _pts([(0, "gpu", 90), (5, "gpu", 76.9), (60, "gpu", 76.0), (90, "gpu", 76.0)])
    r = precalibration.recovery_summary(pts)
    assert r["tolerance_w"] == round(76.0 * 0.02, 3)
    assert r["recovery_s"]["gpu"] == 5


def test_recovery_none_without_settled_points():
    assert precalibration.recovery_summary(_pts([(0, "cpu", 90), (5, "cpu", 80)])) is None


# --- re-runs add to the curve (2026-10-10) ----------------------------------

def _write(dirp, stamp, rows, n_polls=5):
    f = dirp / f"recovery_{stamp}_summary.csv"
    lines = ["distance_s,workload,encode_s,n_polls,mean_w,std_w,cv_pct,min_w,max_w,sample_window_s"]
    lines += [f"{d},{w},15.0,{n_polls},{m},0.1,1.0,{m},{m},5.2" for d, w, m in rows]
    f.write_text("\n".join(lines) + "\n")
    return f


_ROWS = [(0, "cpu", 30.0), (5, "cpu", 1.9), (60, "cpu", 1.4), (0, "gpu", 25.0), (5, "gpu", 1.4), (60, "gpu", 1.35)]


def test_probe_rerun_is_pooled_with_the_previous_run(tmp_path):
    _write(tmp_path, "20261010_074153", _ROWS)
    _write(tmp_path, "20261011_090000", [(d, w, m + 0.1) for d, w, m in _ROWS])
    series = precalibration.probe_series(tmp_path)
    assert [p.name for p, _ in series] == ["recovery_20261010_074153_summary.csv",
                                           "recovery_20261011_090000_summary.csv"]
    pooled = {(p["distance_s"], p["workload"]): p for p in precalibration.pool(series)}
    p = pooled[(5, "cpu")]
    assert p["n_runs"] == 2 and p["run_means"] == [1.9, 2.0]
    assert p["mean_w"] == 1.95 and p["run_sd_w"] is not None
    assert precalibration.recovery_summary(list(pooled.values()))["encodes_per_point"] == 2


def test_probe_from_another_era_or_shape_is_not_pooled(tmp_path):
    _write(tmp_path, "20260707_005223", _ROWS)                     # 3 months earlier
    _write(tmp_path, "20261009_120000", _ROWS, n_polls=10)          # other poll count
    _write(tmp_path, "20261009_130000", _ROWS[:3])                  # other distances
    _write(tmp_path, "20261010_074153", _ROWS)
    series = precalibration.probe_series(tmp_path)
    assert [p.name for p, _ in series] == ["recovery_20261010_074153_summary.csv"]
    assert all(p["n_runs"] == 1 and p["run_sd_w"] is None for p in precalibration.pool(series))


def test_precalibration_data_reports_pooled_sources(tmp_path, monkeypatch):
    import routes_settings
    _write(tmp_path, "20261010_074153", _ROWS)
    _write(tmp_path, "20261011_090000", _ROWS)
    monkeypatch.setattr(routes_settings.paths, "repo", lambda *a: tmp_path)
    d = TestClient(main.app).get("/precalibration/data", headers=_LAB).json()
    assert d["available"] and len(d["sources"]) == 2
    assert d["recovery"]["encodes_per_point"] == 2
