"""
Unit tests for `queue_control.py`.

Mirrors the test pattern set by tests/test_carbon.py (S16):
  - Module-state reset between cases via autouse fixture
  - No HTTP, no real filesystem state — pure logic tests
  - Plain `def test_<name>():` shape, no classes

What's covered:
  - enqueue position counting and depth-cap behaviour
  - depth() reflects pending + running
  - paused() reflects PAUSE_FLAG file presence
  - snapshot() shape regression (keys consumers depend on)
  - The CR-001b seam: enqueue(request=...) accepts both None and a stub

What's NOT covered:
  - The async _worker() loop. Integration-level (event loop, timing).
    Manual smoke-test: queue a job and watch it run, like test_carbon's
    "no live HTTP" deferral.
"""
from pathlib import Path

import pytest

import queue_control


# --- Fixtures ---------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_queue_state(tmp_path):
    """Clear queue state and inject a temp jobs dict + lock file path before
    every test; restore afterwards. Mirrors test_carbon.reset_live_cache.
    """
    # Save originals
    orig_jobs = queue_control._jobs
    orig_lock = queue_control._lock_file
    orig_pause = queue_control.PAUSE_FLAG

    # Per-test scratch
    queue_control._jobs = {}
    queue_control._lock_file = tmp_path / "fake.lock"
    queue_control.pending_queue.clear()
    queue_control.current_job_id = None
    # Use a tmp path for PAUSE_FLAG so tests don't touch /tmp/owl-paused
    queue_control.PAUSE_FLAG = str(tmp_path / "paused")

    yield

    queue_control.pending_queue.clear()
    queue_control.current_job_id = None
    queue_control._jobs = orig_jobs
    queue_control._lock_file = orig_lock
    queue_control.PAUSE_FLAG = orig_pause


def _noop_coro():
    async def _():
        return None
    return _


# --- enqueue ----------------------------------------------------------------

def test_enqueue_returns_position_one_for_first_job():
    pos = queue_control.enqueue("j1", "video", "label", _noop_coro())
    assert pos == 1


def test_enqueue_increments_position():
    assert queue_control.enqueue("j1", "video", "a", _noop_coro()) == 1
    assert queue_control.enqueue("j2", "video", "b", _noop_coro()) == 2
    assert queue_control.enqueue("j3", "llm",   "c", _noop_coro()) == 3


def test_enqueue_returns_none_when_full():
    """MAX_QUEUE_DEPTH cap: positions 1..8, then None."""
    for i in range(queue_control.MAX_QUEUE_DEPTH):
        assert queue_control.enqueue(f"j{i}", "video", str(i), _noop_coro()) == i + 1
    assert queue_control.enqueue("overflow", "video", "x", _noop_coro()) is None


def test_enqueue_populates_jobs_dict():
    queue_control.enqueue("jA", "llm", "tinyllama-T1", _noop_coro())
    j = queue_control._jobs["jA"]
    assert j["stage"] == "queued"
    assert j["queue_position"] == 1
    assert j["type"] == "llm"
    assert j["label"] == "tinyllama-T1"
    assert j["result"] is None
    assert j["error"] is None


def test_enqueue_sets_queue_event():
    queue_control.queue_event.clear()
    queue_control.enqueue("jE", "video", "x", _noop_coro())
    assert queue_control.queue_event.is_set()


def test_enqueue_accepts_request_none():
    """The CR-001b seam: request=None is the documented default."""
    pos = queue_control.enqueue("j1", "video", "x", _noop_coro(), request=None)
    assert pos == 1


def test_enqueue_accepts_stub_request():
    """The CR-001b seam: a non-None request value passes through (no validation today)."""
    stub = object()  # any value; not used today
    pos = queue_control.enqueue("j1", "video", "x", _noop_coro(), request=stub)
    assert pos == 1


# --- depth ------------------------------------------------------------------

def test_depth_zero_when_idle():
    assert queue_control.depth() == 0


def test_depth_counts_queued():
    queue_control.enqueue("j1", "video", "a", _noop_coro())
    queue_control.enqueue("j2", "video", "b", _noop_coro())
    assert queue_control.depth() == 2


def test_depth_counts_running_plus_queued():
    queue_control.enqueue("j1", "video", "a", _noop_coro())
    queue_control.current_job_id = "running-job"
    assert queue_control.depth() == 2  # 1 queued + 1 running


# --- paused -----------------------------------------------------------------

def test_paused_false_when_flag_absent():
    assert queue_control.paused() is False


def test_paused_true_when_flag_present(tmp_path):
    Path(queue_control.PAUSE_FLAG).touch()
    assert queue_control.paused() is True


# --- snapshot ---------------------------------------------------------------

def test_snapshot_shape_when_idle():
    """REGRESSION: /queue endpoint consumers depend on these exact keys."""
    snap = queue_control.snapshot()
    assert set(snap.keys()) == {"depth", "running", "pending", "paused"}
    assert snap["depth"] == 0
    assert snap["running"] is None
    assert snap["pending"] == []
    assert snap["paused"] is False


def test_snapshot_running_job_populated():
    queue_control._jobs["running-job"] = {
        "stage": "measuring", "type": "video", "label": "h264-cpu",
    }
    queue_control.current_job_id = "running-job"
    snap = queue_control.snapshot()
    assert snap["running"] == {
        "job_id": "running-job",
        "stage": "measuring",
        "type": "video",
        "label": "h264-cpu",
    }


def test_snapshot_pending_jobs_listed_with_positions():
    queue_control.enqueue("j1", "video", "a", _noop_coro())
    queue_control.enqueue("j2", "llm", "b", _noop_coro())
    snap = queue_control.snapshot()
    assert len(snap["pending"]) == 2
    assert snap["pending"][0] == {"job_id": "j1", "type": "video", "label": "a", "position": 1}
    assert snap["pending"][1] == {"job_id": "j2", "type": "llm",   "label": "b", "position": 2}
