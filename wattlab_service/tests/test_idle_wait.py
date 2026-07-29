"""idle_wait — the shared settle loop (GoS1 floor guard + decode rig guard)."""
import asyncio

import idle_wait


def _run(coro):
    return asyncio.run(coro)


def _feeder(values):
    it = iter(values)

    async def read():
        return next(it)
    return read


def test_reference_mode_settles_at_or_below_floor():
    # 3 consecutive at/below 100+2 → settled (asymmetric: 97 counts).
    r = _run(idle_wait.wait_for_stable(
        _feeder([110, 105, 101, 97, 100]), reference_w=100, tolerance_w=2,
        settle_polls=3, max_wait_s=30, poll_interval_s=0))
    assert r["settled"] is True
    assert r["final_w"] == 100
    assert r["readings"] == [110, 105, 101, 97, 100]


def test_reference_mode_resets_on_excursion():
    r = _run(idle_wait.wait_for_stable(
        _feeder([101, 100, 120, 101, 100, 99]), reference_w=100, tolerance_w=2,
        settle_polls=3, max_wait_s=30, poll_interval_s=0))
    assert r["settled"] is True
    assert r["readings"][-3:] == [101, 100, 99]


def test_self_stability_mode_settles_on_flat_span():
    r = _run(idle_wait.wait_for_stable(
        _feeder([9.0, 5.0, 3.4, 3.3, 3.4, 3.35]), tolerance_w=0.5,
        settle_polls=4, max_wait_s=30, poll_interval_s=0))
    assert r["settled"] is True
    assert r["final_w"] == 3.35


def test_timeout_returns_unsettled():
    async def read():
        return 50.0
    r = _run(idle_wait.wait_for_stable(
        read, reference_w=10, tolerance_w=1, settle_polls=3,
        max_wait_s=0, poll_interval_s=0))
    assert r["settled"] is False
    assert "skipped" not in r


def test_skip_probe_short_circuits():
    calls = {"n": 0}

    def should_skip():
        calls["n"] += 1
        return calls["n"] >= 2
    r = _run(idle_wait.wait_for_stable(
        _feeder([50, 50, 50]), reference_w=10, tolerance_w=1, settle_polls=3,
        max_wait_s=30, poll_interval_s=0, should_skip=should_skip))
    assert r["settled"] is False
    assert r["skipped"] is True


def test_on_sample_receives_rounded_values():
    seen = []
    r = _run(idle_wait.wait_for_stable(
        _feeder([3.333, 3.334, 3.336]), tolerance_w=0.5, settle_polls=3,
        max_wait_s=30, poll_interval_s=0,
        on_sample=lambda w, e: seen.append(w)))
    assert r["settled"] is True
    assert seen == [3.33, 3.33, 3.34]
