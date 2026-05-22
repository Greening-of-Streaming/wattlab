"""
CR-028 Phase 2 — unified single-run confidence (Tania §9 v2).

Covers the CI model in confidence.py: the SE_final formula (worst-case +
additive drift), Φ(z) → confidence_positive, the green/yellow/red thresholds
(both the probability AND the minimum task-poll guards), the option-C input
choice (cpu/gpu CVs unused), and the legacy variance fallback when raw
samples are absent. Also asserts all four measurement modules share the one
implementation.
"""
import math

import confidence as C


def _settings(**over):
    s = {
        "variance_pct": 2.0,
        "variance_green_x": 5.0,
        "variance_yellow_x": 2.0,
        "variance_idle_pct": 2.0,
        "variance_idle_drift_pct": 1.0,
        "variance_cpu_pct": 1.0,
        "variance_gpu_pct": 1.0,
        "conf_green_polls": 10,
        "conf_yellow_polls": 5,
        "conf_positive_green": 0.95,
        "conf_positive_yellow": 0.80,
    }
    s.update(over)
    return s


# ── legacy fallback ──────────────────────────────────────────────────────────

def test_legacy_used_when_no_samples():
    r = C.confidence(10.0, 15, 50.0, None, None, _settings())
    assert r["method"] == "variance"
    assert r["flag"] == "🟢"  # noise=1.0, green=5; 10>5 and 15>=10


def test_null_positive_thresholds_do_not_crash():
    # A hand-edited settings.json with explicit null thresholds must coalesce
    # to defaults, not raise (regression — `cp >= None` would crash a run).
    s = _settings(conf_positive_green=None, conf_positive_yellow=None)
    r = C.confidence(40, 8, 57, [57] * 8, [97] * 8, s)
    assert r["flag"] in ("🟢", "🟡", "🔴") and r["method"] == "ci"


def test_legacy_used_only_when_samples_absent():
    # None or empty arrays -> legacy (old results). A present array, even with
    # one element, uses the CI model (see test_single_task_poll_uses_ci_and_is_red).
    assert C.confidence(10.0, 5, 50.0, None, [60] * 5, _settings())["method"] == "variance"
    assert C.confidence(10.0, 5, 50.0, [50] * 5, None, _settings())["method"] == "variance"
    assert C.confidence(10.0, 5, 50.0, [50] * 5, [], _settings())["method"] == "variance"


# ── CI model: SE_final formula ──────────────────────────────────────────────

def test_se_final_is_worst_case_plus_additive_drift():
    # zero per-run noise -> SE_final = SE_calibrated + SE_drift
    base = [50.0] * 4          # n=4, std 0, mean 50
    task = [60.0] * 10         # n=10, std 0, mean 60, delta 10
    r = C.confidence(10.0, 10, 50.0, base, task, _settings())
    se_cal = 0.02 * 50 * math.sqrt(1 / 4 + 1 / 10)
    se_drift = 0.01 * 50
    assert r["method"] == "ci"
    assert r["se_final_w"] == round(se_cal + se_drift, 3)


def test_drift_term_is_additive():
    base, task = [50.0] * 4, [60.0] * 10
    no_drift = C.confidence(10, 10, 50, base, task, _settings(variance_idle_drift_pct=0.0))
    with_drift = C.confidence(10, 10, 50, base, task, _settings(variance_idle_drift_pct=1.0))
    assert with_drift["se_final_w"] == round(no_drift["se_final_w"] + 0.01 * 50, 3)


# ── CI model: thresholds ─────────────────────────────────────────────────────

def test_strong_long_signal_is_green():
    base, task = [50.0] * 10, [60.0] * 12
    r = C.confidence(10, 12, 50, base, task, _settings())
    assert r["flag"] == "🟢" and r["label"] == "Repeatable"
    assert r["confidence_positive"] >= 0.95


def test_strong_but_too_few_polls_is_yellow_with_hint():
    base, task = [50.0] * 4, [60.0] * 6   # n_task 6 < green_polls 10
    r = C.confidence(10, 6, 50, base, task, _settings())
    assert r["flag"] == "🟡"
    assert r["confidence_positive"] >= 0.95   # would be green on polls alone
    assert "hint" in r


def test_near_idle_is_red_with_straddling_ci():
    base, task = [50.0] * 4, [50.4, 50.5, 50.6]   # delta ~0.5, tiny
    r = C.confidence(0.5, 3, 50, base, task, _settings())
    assert r["flag"] == "🔴"
    lo, hi = r["ci_delta_w_95"]
    assert lo < 0 < hi          # interval includes zero -> not distinguishable
    assert "hint" in r


def test_single_task_poll_uses_ci_and_is_red():
    # Regression: a 1-poll run HAS samples, so it must use the CI model (not
    # fall back to legacy). n_task=1 fails the yellow poll-guard -> 🔴, even
    # when ΔW is large. Previously it leaked to legacy and flagged 🟡.
    base = [57.0] * 10
    task = [110.0]            # single strong task poll
    r = C.confidence(53, 1, 57, base, task, _settings())
    assert r["method"] == "ci"
    assert r["flag"] == "🔴"


def test_few_task_polls_below_yellow_guard_is_red():
    base, task = [57.0] * 10, [110.0, 109.0, 111.0]   # n_task=3 < yellow polls 5
    r = C.confidence(53, 3, 57, base, task, _settings())
    assert r["method"] == "ci"
    assert r["flag"] == "🔴"


def test_zero_delta_is_half_confidence():
    base, task = [50.0] * 6, [50.0] * 6
    r = C.confidence(0.0, 6, 50, base, task, _settings())
    assert abs(r["confidence_positive"] - 0.5) < 0.01
    assert r["flag"] == "🔴"


# ── option C: cpu/gpu CVs must not affect the single-run flag ─────────────────

def test_cpu_gpu_cvs_not_used_in_single_run():
    base, task = [50.0] * 6, [58.0] * 8
    a = C.confidence(8, 8, 50, base, task, _settings(variance_cpu_pct=1.0, variance_gpu_pct=1.0))
    b = C.confidence(8, 8, 50, base, task, _settings(variance_cpu_pct=99.0, variance_gpu_pct=99.0))
    assert a["confidence_positive"] == b["confidence_positive"]
    assert a["se_final_w"] == b["se_final_w"]


def test_idle_cv_does_affect_single_run():
    base, task = [50.0] * 6, [58.0] * 8
    low = C.confidence(8, 8, 50, base, task, _settings(variance_idle_pct=1.0))
    high = C.confidence(8, 8, 50, base, task, _settings(variance_idle_pct=10.0))
    assert high["se_final_w"] > low["se_final_w"]


# ── shared across all four modules ───────────────────────────────────────────

def test_all_modules_share_one_confidence():
    import video, llm, image_gen, rag
    assert video.confidence is C.confidence
    assert llm.confidence is C.confidence
    assert image_gen.confidence is C.confidence
    assert rag.confidence is C.confidence
