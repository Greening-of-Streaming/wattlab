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
        "resume_page": None,
    }


def test_snapshot_pending_jobs_listed_with_positions():
    queue_control.enqueue("j1", "video", "a", _noop_coro())
    queue_control.enqueue("j2", "llm", "b", _noop_coro())
    snap = queue_control.snapshot()
    assert len(snap["pending"]) == 2
    assert snap["pending"][0] == {"job_id": "j1", "type": "video", "label": "a", "position": 1, "resume_page": None}
    assert snap["pending"][1] == {"job_id": "j2", "type": "llm",   "label": "b", "position": 2, "resume_page": None}


def test_snapshot_carries_resume_page():
    # Sub-pages (e.g. /rag/compare) pass page= so ↩ Resume lands on the right page.
    queue_control.enqueue("jc", "rag", "RAG compare", _noop_coro(), page="/rag/compare")
    snap = queue_control.snapshot()
    assert snap["pending"][0]["resume_page"] == "/rag/compare"


# --- Per-tier concurrent-job cap (CR-001 part D) ----------------------------
#
# Tests stub `_visitor_key()` directly rather than building real Request
# objects + cookies, so the cap-logic tests stay decoupled from the
# audience/auth wiring (which has its own tests).

def test_anonymous_visitor_capped_at_one_by_default(monkeypatch):
    """Default queue_anonymous_cap=1 → 2nd Anonymous job from same IP rejected."""
    monkeypatch.setattr(queue_control, "visitor_key", lambda r: "a:203.0.113.7")
    assert queue_control.enqueue("j1", "video", "x", _noop_coro(), request=object()) == 1
    assert queue_control.enqueue("j2", "video", "y", _noop_coro(), request=object()) is None


def test_different_anonymous_visitors_each_get_a_slot(monkeypatch):
    """The cap is per-visitor — IP A and IP B each get 1 slot."""
    keys = iter(["a:1.1.1.1", "a:2.2.2.2"])
    monkeypatch.setattr(queue_control, "visitor_key", lambda r: next(keys))
    assert queue_control.enqueue("j1", "video", "a", _noop_coro(), request=object()) == 1
    assert queue_control.enqueue("j2", "video", "b", _noop_coro(), request=object()) == 2


def test_member_visitor_default_cap_is_four(monkeypatch):
    """Default queue_member_cap=4 → 5th Member job from same email rejected."""
    monkeypatch.setattr(queue_control, "visitor_key", lambda r: "m:user@example.com")
    for i in range(4):
        assert queue_control.enqueue(f"j{i}", "video", str(i), _noop_coro(),
                                      request=object()) == i + 1
    assert queue_control.enqueue("j5", "video", "fifth", _noop_coro(),
                                  request=object()) is None


def test_lab_tier_uncapped(monkeypatch):
    """Lab returns visitor_key=None → cap is None → only MAX_QUEUE_DEPTH bites."""
    monkeypatch.setattr(queue_control, "visitor_key", lambda r: None)
    for i in range(queue_control.MAX_QUEUE_DEPTH):
        assert queue_control.enqueue(f"j{i}", "video", str(i), _noop_coro(),
                                      request=object()) == i + 1
    # The depth cap, not the per-visitor cap, is what stops the next one.
    assert queue_control.enqueue("overflow", "video", "x", _noop_coro(),
                                  request=object()) is None


def test_anonymous_running_job_counts_toward_cap(monkeypatch):
    """A running Anonymous job blocks a new one from the same IP, even if
    the pending queue is empty."""
    monkeypatch.setattr(queue_control, "visitor_key", lambda r: "a:203.0.113.9")
    queue_control.current_job_id = "running"
    queue_control.current_visitor_key = "a:203.0.113.9"
    assert queue_control.enqueue("j2", "video", "x", _noop_coro(),
                                  request=object()) is None


def test_settings_override_anonymous_cap(monkeypatch):
    """A bumped queue_anonymous_cap in settings.json takes effect immediately
    (read live, no restart)."""
    monkeypatch.setattr(queue_control, "visitor_key", lambda r: "a:198.51.100.5")
    import settings as _cfg
    monkeypatch.setattr(_cfg, "load",
                        lambda: {**_cfg.DEFAULTS, "queue_anonymous_cap": 3})
    for i in range(3):
        assert queue_control.enqueue(f"j{i}", "video", str(i), _noop_coro(),
                                      request=object()) == i + 1
    assert queue_control.enqueue("j4", "video", "fourth", _noop_coro(),
                                  request=object()) is None


def test_enqueue_records_visitor_key_in_pending_entry(monkeypatch):
    """The pending-queue entry carries visitor_key so the worker can
    publish it to current_visitor_key when the job starts."""
    monkeypatch.setattr(queue_control, "visitor_key", lambda r: "a:test")
    queue_control.enqueue("j1", "video", "x", _noop_coro(), request=object())
    assert queue_control.pending_queue[0]["visitor_key"] == "a:test"


# --- _visitor_key resolution ------------------------------------------------

def _stub_request(headers=None, cookies=None, client_host=""):
    class _StubClient:
        host = client_host
    class _StubReq:
        def __init__(self):
            self.headers = headers or {}
            self.cookies = cookies or {}
            self.client = _StubClient()
    return _StubReq()


def test_visitor_key_anonymous_pseudonymises_x_real_ip():
    # 8.8.8.8 chosen because Python's ipaddress.is_private flags TEST-NET
    # ranges (203.0.113/24) as private — they'd resolve to Lab here.
    # GDPR: the raw IP must never become the key — it's truncated + keyed-hashed
    # (analytics.hash_ip), so the token is stable but not the address.
    import analytics
    req = _stub_request(headers={"x-real-ip": "8.8.8.8"})
    key = queue_control.visitor_key(req)
    assert key == f"a:{analytics.hash_ip('8.8.8.8')}"
    assert "8.8.8.8" not in key


def test_visitor_key_anonymous_falls_back_to_client_host():
    """No X-Real-IP header (no nginx in front) → use client.host, pseudonymised."""
    import analytics
    req = _stub_request(headers={}, client_host="1.1.1.1")
    key = queue_control.visitor_key(req)
    assert key == f"a:{analytics.hash_ip('1.1.1.1')}"
    assert "1.1.1.1" not in key


def test_visitor_key_lab_returns_none():
    """Loopback IP → Lab tier → None (uncapped)."""
    req = _stub_request(headers={"x-real-ip": "127.0.0.1"})
    assert queue_control.visitor_key(req) is None


def test_visitor_key_request_none_returns_none():
    """Tests calling enqueue with request=None must opt out of cap accounting."""
    assert queue_control.visitor_key(None) is None


def test_visitor_key_member_uses_email_lowercased(monkeypatch):
    """Member tier → 'm:<email>', case-folded so MIXED@case treated the same."""
    import audience as _aud
    import auth as _auth
    monkeypatch.setattr(_aud, "tier", lambda r: _aud.Tier.Member)
    monkeypatch.setattr(_auth, "member_email_from_request", lambda r: "Foo@Bar.COM")
    req = _stub_request()
    assert queue_control.visitor_key(req) == "m:foo@bar.com"


# --- empty_pending (CR-064 — /queue-status "Empty queue") ---------------------

def test_empty_pending_drains_and_marks_cancelled():
    queue_control.enqueue("j1", "video", "a", _noop_coro())
    queue_control.enqueue("j2", "enhance", "b", _noop_coro())
    drained = queue_control.empty_pending()
    assert sorted(drained) == ["j1", "j2"]
    assert queue_control.pending_queue == []
    for jid in ("j1", "j2"):
        assert queue_control._jobs[jid]["status"] == "error"
        assert "Cancelled" in queue_control._jobs[jid]["error"]


def test_empty_pending_leaves_running_job_alone():
    queue_control.current_job_id = "running"
    queue_control._jobs["running"] = {"status": "running"}
    assert queue_control.empty_pending() == []
    assert queue_control._jobs["running"]["status"] == "running"
    assert queue_control.depth() == 1
