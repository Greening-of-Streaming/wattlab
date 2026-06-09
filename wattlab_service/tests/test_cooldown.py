"""
Unit tests for the unified cooldown dispatcher (power.cooldown_between_runs)
and the idle-wait timeout decision endpoint.

The dispatcher is the single code path every inter-pass cooldown now routes
through (video / llm / rag / image compares + batch + variance). These tests
pin its strategy switch (fixed vs idle), the non-interactive timeout fallback,
and the interactive Run / Cancel / Wait decisions — without real sleeps or a
live P110 (wait_for_thermal_floor and asyncio.sleep are stubbed).
"""
import asyncio
import pytest

import power
import settings


@pytest.fixture
def no_sleep(monkeypatch):
    async def _nosleep(*a, **k):
        return None
    monkeypatch.setattr(asyncio, "sleep", _nosleep)


def _settings(monkeypatch, **over):
    base = {
        "cooldown_wait_for_idle": True,
        "cooldown_idle_tolerance_w": 3.0,
        "cooldown_idle_settle_polls": 3,
        "cooldown_idle_max_wait_s": 120,
        "cooldown_dialog_watchdog_s": 75,
    }
    base.update(over)
    monkeypatch.setattr(settings, "load", lambda: base)


# ── strategy switch ─────────────────────────────────────────────────────────

def test_toggle_off_uses_fixed(monkeypatch, no_sleep):
    _settings(monkeypatch, cooldown_wait_for_idle=False)
    r = asyncio.run(power.cooldown_between_runs(fixed_seconds=10, reference_w=55.0))
    assert r["method"] == "fixed"
    assert r["settled"] is True
    assert r["timed_out"] is False
    assert r["waited_s"] == 10.0


def test_respect_toggle_false_forces_fixed(monkeypatch, no_sleep):
    # Variance calibration path: toggle ON, but respect_toggle=False keeps it fixed.
    _settings(monkeypatch, cooldown_wait_for_idle=True)
    r = asyncio.run(power.cooldown_between_runs(
        fixed_seconds=70, reference_w=55.0, respect_toggle=False))
    assert r["method"] == "fixed"


def test_no_reference_forces_fixed(monkeypatch, no_sleep):
    # Toggle ON but no idle floor captured → fall back to fixed.
    _settings(monkeypatch, cooldown_wait_for_idle=True)
    r = asyncio.run(power.cooldown_between_runs(fixed_seconds=10, reference_w=None))
    assert r["method"] == "fixed"


def test_idle_settles(monkeypatch, no_sleep):
    _settings(monkeypatch)
    async def _settled(*a, **k):
        return {"waited_s": 4.0, "final_w": 56.0, "settled": True}
    monkeypatch.setattr(power, "wait_for_thermal_floor", _settled)
    r = asyncio.run(power.cooldown_between_runs(fixed_seconds=10, reference_w=55.0))
    assert r["method"] == "idle"
    assert r["settled"] is True
    assert r["timed_out"] is False
    assert r["waited_s"] == 4.0


# ── timeout handling ────────────────────────────────────────────────────────

def test_timeout_noninteractive_fallback(monkeypatch, no_sleep):
    _settings(monkeypatch)
    async def _timeout(*a, **k):
        return {"waited_s": 120.0, "final_w": 80.0, "settled": False}
    monkeypatch.setattr(power, "wait_for_thermal_floor", _timeout)
    # No interactive_eligible on the (absent) job → non-interactive fallback.
    r = asyncio.run(power.cooldown_between_runs(
        fixed_seconds=10, reference_w=55.0, allow_dialog=True,
        jobs={"j": {}}, job_id="j"))
    assert r["method"] == "idle+fallback"
    assert r["settled"] is False
    assert r["timed_out"] is True
    # one fixed fallback sleep added on top of the 120 s wait
    assert r["waited_s"] == pytest.approx(130.0)


def test_timeout_interactive_run_now(monkeypatch, no_sleep):
    _settings(monkeypatch)
    async def _timeout(*a, **k):
        return {"waited_s": 120.0, "final_w": 80.0, "settled": False}
    monkeypatch.setattr(power, "wait_for_thermal_floor", _timeout)
    async def _decide(*a, **k):
        return "run"
    monkeypatch.setattr(power, "_await_cooldown_decision", _decide)
    jobs = {"j": {"interactive_eligible": True}}
    r = asyncio.run(power.cooldown_between_runs(
        fixed_seconds=10, reference_w=55.0, allow_dialog=True, jobs=jobs, job_id="j"))
    assert r["method"] == "idle"          # proceeded now, no extra sleep
    assert r["settled"] is False
    assert r["timed_out"] is True
    assert r["waited_s"] == 120.0


def test_timeout_interactive_cancel_raises(monkeypatch, no_sleep):
    _settings(monkeypatch)
    async def _timeout(*a, **k):
        return {"waited_s": 120.0, "final_w": 80.0, "settled": False}
    monkeypatch.setattr(power, "wait_for_thermal_floor", _timeout)
    async def _decide(*a, **k):
        return "cancel"
    monkeypatch.setattr(power, "_await_cooldown_decision", _decide)
    jobs = {"j": {"interactive_eligible": True}}
    with pytest.raises(power.CooldownCancelled):
        asyncio.run(power.cooldown_between_runs(
            fixed_seconds=10, reference_w=55.0, allow_dialog=True, jobs=jobs, job_id="j"))


def test_timeout_interactive_wait_then_settle(monkeypatch, no_sleep):
    _settings(monkeypatch)
    calls = {"n": 0}
    async def _floor(*a, **k):
        calls["n"] += 1
        # first window times out, second settles (operator chose Wait again)
        if calls["n"] == 1:
            return {"waited_s": 120.0, "final_w": 80.0, "settled": False}
        return {"waited_s": 5.0, "final_w": 56.0, "settled": True}
    monkeypatch.setattr(power, "wait_for_thermal_floor", _floor)
    async def _decide(*a, **k):
        return "wait"
    monkeypatch.setattr(power, "_await_cooldown_decision", _decide)
    jobs = {"j": {"interactive_eligible": True}}
    r = asyncio.run(power.cooldown_between_runs(
        fixed_seconds=10, reference_w=55.0, allow_dialog=True, jobs=jobs, job_id="j"))
    assert r["method"] == "idle"
    assert r["settled"] is True
    assert r["waited_s"] == pytest.approx(125.0)   # 120 (timed out) + 5 (settled)
    assert calls["n"] == 2


def test_dialog_not_offered_without_allow_dialog(monkeypatch, no_sleep):
    # interactive_eligible True but allow_dialog False (binary/batch sites) →
    # straight to non-interactive fallback, dialog never consulted.
    _settings(monkeypatch)
    async def _timeout(*a, **k):
        return {"waited_s": 120.0, "final_w": 80.0, "settled": False}
    monkeypatch.setattr(power, "wait_for_thermal_floor", _timeout)
    def _boom(*a, **k):
        raise AssertionError("dialog must not be consulted when allow_dialog=False")
    monkeypatch.setattr(power, "_await_cooldown_decision", _boom)
    jobs = {"j": {"interactive_eligible": True}}
    r = asyncio.run(power.cooldown_between_runs(
        fixed_seconds=10, reference_w=55.0, allow_dialog=False, jobs=jobs, job_id="j"))
    assert r["method"] == "idle+fallback"
    assert r["timed_out"] is True


# ── label single-source-of-truth (every page inherits the toggle) ───────────
#
# The cooldown *wording* must funnel through main._bake_durations' tokens just
# like the cooldown *execution* funnels through cooldown_between_runs above.
# A page that hardcodes "(10s)" survives a wait-for-idle switch and lies to the
# visitor — exactly the /image + /llm/compare bug these pin against recurring.

def test_bake_cooldown_paren_says_idle_when_toggle_on(monkeypatch):
    import main
    _settings(monkeypatch, cooldown_wait_for_idle=True, video_cooldown_s=10,
              baseline_polls=10, llm_rest_s=10)
    out = main._bake_durations("X {COOLDOWN_PAREN} Y")
    assert out == "X (→ idle) Y"


def test_bake_cooldown_paren_says_fixed_seconds_when_toggle_off(monkeypatch):
    import main
    _settings(monkeypatch, cooldown_wait_for_idle=False, video_cooldown_s=42,
              baseline_polls=10, llm_rest_s=10)
    out = main._bake_durations("X {COOLDOWN_PAREN} Y")
    assert out == "X (42s) Y"


def test_bake_cooldown_label_follows_toggle(monkeypatch):
    import main
    _settings(monkeypatch, cooldown_wait_for_idle=True, video_cooldown_s=10,
              baseline_polls=10, llm_rest_s=10)
    assert main._bake_durations("{COOLDOWN_LABEL}") == "Cooldown (→ idle)"
    _settings(monkeypatch, cooldown_wait_for_idle=False, video_cooldown_s=10,
              baseline_polls=10, llm_rest_s=10)
    assert main._bake_durations("{COOLDOWN_LABEL}") == "Cooldown (10s)"


def test_no_page_hardcodes_a_fixed_second_cooldown_label():
    """Guard for future pages: no page f-string may emit a raw `{COOLDOWN_S}`
    token. It bakes to a bare number regardless of cooldown_wait_for_idle, which
    is how the fixed "(10s)" label outlived the wait-for-idle switch. New
    cooldown labels must use {COOLDOWN_PAREN} / {COOLDOWN_LABEL} instead."""
    import main
    src = open(main.__file__).read()
    assert "{{COOLDOWN_S}}" not in src, (
        "A page f-string emits {{COOLDOWN_S}} — use {{COOLDOWN_PAREN}} so the "
        "cooldown label respects the wait-for-idle toggle.")


# ── decision endpoint (logic, auth-independent) ─────────────────────────────

def test_decision_endpoint_sets_choice(monkeypatch):
    import main
    main.jobs["jx"] = {"stage": "awaiting_cooldown_decision",
                       "cooldown_decision": None,
                       "cooldown_decision_options": ["wait", "run", "cancel"]}
    out = asyncio.run(main.cooldown_decision("jx", "run"))
    assert out == {"ok": True, "decision": "run"}
    assert main.jobs["jx"]["cooldown_decision"] == "run"
    del main.jobs["jx"]


def test_decision_endpoint_rejects_when_not_waiting(monkeypatch):
    import main
    main.jobs["jy"] = {"stage": "compare_models"}
    resp = asyncio.run(main.cooldown_decision("jy", "run"))
    # returns a JSONResponse with 409 when the job isn't parked
    assert getattr(resp, "status_code", None) == 409
    del main.jobs["jy"]


def test_decision_endpoint_rejects_disallowed_option(monkeypatch):
    import main
    main.jobs["jz"] = {"stage": "awaiting_cooldown_decision",
                       "cooldown_decision_options": ["run", "cancel"]}
    resp = asyncio.run(main.cooldown_decision("jz", "wait"))   # 'wait' not offered
    assert getattr(resp, "status_code", None) == 400
    del main.jobs["jz"]
