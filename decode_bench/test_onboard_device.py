"""Pure unit tests for onboard_device.py's curve analysis — no hardware,
no rig import. Run: python3 -m pytest decode_bench/test_onboard_device.py -q"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from onboard_device import (detect_true_floor, detect_true_settle_time,
                            replay_guard_convergence, verdict_for_curve,
                            recommend)


def _curve(vals, cadence=1.0):
    return [(round(i * cadence, 2), v) for i, v in enumerate(vals)]


def test_fast_device_guard_converges_correctly():
    """An Android-class box: flat from t=0. The guard should declare
    settled almost immediately and that call should NOT be false-early."""
    curve = _curve([2.1, 2.15, 2.08, 2.12, 2.1, 2.11, 2.09, 2.13, 2.1, 2.1])
    v = verdict_for_curve(curve, tolerance_w=0.5, settle_polls=4)
    assert v["floor_w"] == 2.1 or abs(v["floor_w"] - 2.1) < 0.05
    assert v["guard_settle_s"] is not None
    assert v["true_settle_s"] == 0.0          # already flat from the start
    assert v["false_early_settle"] is False


def test_apple_tv_class_device_false_early_settle():
    """Reproduces tonight's failure mode: a plateau near the eventual floor
    for a few seconds, then a real rise, then the true settle much later.
    The guard (self-stability, 4-poll window, 0.5 W tolerance) locks onto
    the early plateau and calls it settled — falsely."""
    vals = ([2.2, 2.3, 2.1, 2.2]           # looks stable at t=0-3 (guard fires here)
            + [4.5, 6.8, 8.4, 7.9, 6.2, 5.1, 4.0, 3.2, 2.6, 2.3]  # real transient
            + [2.15] * 10)                  # true floor from here on
    curve = _curve(vals)
    v = verdict_for_curve(curve, tolerance_w=0.5, settle_polls=4)
    assert v["guard_settle_s"] == 3.0        # fires at the 4th sample (index 3)
    assert v["true_settle_s"] > v["guard_settle_s"]
    assert v["false_early_settle"] is True


def test_never_settles_within_window_returns_none():
    vals = [2.0, 5.0, 2.0, 6.0, 2.0, 7.0, 2.0, 8.0]   # never stabilizes
    curve = _curve(vals)
    v = verdict_for_curve(curve, tolerance_w=0.3, settle_polls=4)
    assert v["true_settle_s"] is None or v["guard_settle_s"] is None


def test_detect_true_floor_uses_the_tail():
    curve = _curve([9, 8, 7, 6, 5, 4, 3, 2.1, 2.0, 2.05, 1.95, 2.0])
    floor = detect_true_floor(curve, tail_frac=0.25)
    assert abs(floor - 2.0) < 0.1


def test_recommend_flags_guard_insufficient_and_sizes_the_floor():
    fast = verdict_for_curve(_curve([2.1] * 10), 0.5, 4)
    slow_vals = [2.2, 2.3, 2.1, 2.2] + [5, 6, 4, 3, 2.3] + [2.15] * 10
    slow = verdict_for_curve(_curve(slow_vals), 0.5, 4)
    rec = recommend([fast, slow], tolerance_w=0.5, cadence_s=1.0)
    assert rec["guard_alone_sufficient"] is False   # one bad rep taints the verdict
    assert rec["min_settle_s"] >= slow["true_settle_s"]
    assert rec["min_baseline_samples"] > 0


def test_recommend_all_clean_reps_says_guard_is_enough():
    reps = [verdict_for_curve(_curve([1.5 + 0.02 * (i % 3) for i in range(12)]), 0.5, 4)
            for _ in range(3)]
    rec = recommend(reps, tolerance_w=0.5, cadence_s=1.0)
    assert rec["guard_alone_sufficient"]
