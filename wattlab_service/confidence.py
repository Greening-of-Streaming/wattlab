"""
CR-028 Phase 2 — unified single-run confidence (Tania's §9 v2).

Scope: *single-run measurability* — "can this one run be distinguished from
idle?" — not run-to-run repeatability. One shared implementation for all four
measurement modules (video / llm / image_gen / rag), replacing the four
near-identical variance-threshold copies.

CI model (when a run carries raw per-poll samples):

    SE_calibrated = (variance_idle_pct/100 · w_base) · sqrt(1/n_base + 1/n_task)
    SE_per_run    = sqrt(std_base² / n_base + std_task² / n_task)
    SE_drift      = variance_idle_drift_pct/100 · w_base      # worst-case, additive
    SE_final      = max(SE_calibrated, SE_per_run) + SE_drift
    z             = delta_w / SE_final
    confidence_positive = Φ(z)                                # one-sided P(task > idle)

    🟢 Repeatable    confidence_positive ≥ conf_positive_green (0.95)  AND n_task ≥ conf_green_polls
    🟡 Early insight confidence_positive ≥ conf_positive_yellow (0.80) AND n_task ≥ conf_yellow_polls
    🔴 Need more data otherwise

Decisions 2026-05-22 (Ben + Tania, from `docs/wattlab_traffic_light_confidence.md` §9):
  - Inputs = option C: only `variance_idle_pct` as the calibrated idle floor.
    `variance_cpu_pct` / `variance_gpu_pct` are run-level repeatability CVs and
    are NOT used here — they belong to a later aggregate-confidence layer.
  - Drift folded in additively (worst-case / safest), not in quadrature.
  - First pass uses raw `n` and 1.96 — no autocorrelation correction yet
    (n_effective = floor(duration_s/5) and Student-t are documented future work).
  - Applied to all four modules via this module.

Legacy fallback: results saved before raw samples were persisted (and any caller
not yet threading them) keep the original variance-threshold flag, so historical
results don't lose their badge. `method` in the returned dict records which path
produced the flag ("ci" / "ci2" / "variance" — "ci2" is the CR-065 dual-meter
per-meter combine, see confidence()).
"""
import math
import statistics

import settings as cfg


def _phi(z: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _legacy(delta_w: float, poll_count: int, w_base: float, s: dict) -> dict:
    """Original variance-threshold flag (pre-CR-028-Phase-2)."""
    noise_w = s["variance_pct"] / 100.0 * max(w_base, 1.0)
    green_thresh = s["variance_green_x"] * noise_w
    yellow_thresh = s["variance_yellow_x"] * noise_w
    if delta_w > green_thresh and poll_count >= s["conf_green_polls"]:
        return {"flag": "🟢", "label": "Repeatable", "method": "variance"}
    elif delta_w >= yellow_thresh or poll_count >= s["conf_yellow_polls"]:
        result = {"flag": "🟡", "label": "Early insight", "method": "variance"}
        if delta_w > green_thresh and poll_count < s["conf_green_polls"] and noise_w:
            ratio = int(round(delta_w / noise_w))
            result["hint"] = (f"Strong signal ({ratio}× noise floor) — task too short for 🟢. "
                              f"Use a longer clip or batch mode.")
        return result
    else:
        return {"flag": "🔴", "label": "Need more data", "method": "variance"}


def _se_one_meter(baseline_samples_w, task_samples_w, idle_cv):
    """Per-meter (ΔW, SE) under the §9 v2 model: SE = max(calibrated,
    per-run), each meter's ΔW against its OWN baseline mean. Shared by the
    single-meter path and each leg of the dual-meter combine."""
    n_base = len(baseline_samples_w)
    n_task = len(task_samples_w)
    w_base_m = sum(baseline_samples_w) / n_base
    w_task_m = sum(task_samples_w) / n_task
    delta = w_task_m - w_base_m
    se_cal = idle_cv * max(w_base_m, 1.0) * math.sqrt(1.0 / n_base + 1.0 / n_task)
    std_base = statistics.stdev(baseline_samples_w) if n_base >= 2 else 0.0
    std_task = statistics.stdev(task_samples_w) if n_task >= 2 else 0.0
    se_per_run = math.sqrt(std_base ** 2 / n_base + std_task ** 2 / n_task)
    return delta, max(se_cal, se_per_run), w_base_m


def confidence(delta_w: float, poll_count: int, w_base: float,
               baseline_samples_w=None, task_samples_w=None,
               s: dict = None, meters: dict = None) -> dict:
    """Single-run confidence flag. Falls back to the legacy variance model
    when raw per-poll sample arrays aren't supplied.

    Returns at least {flag, label, method}; the CI path also returns
    confidence_positive, se_final_w and ci_delta_w_95, and may add a hint.

    CR-065 dual-meter: pass the run's `energy.meters` block (from
    power.meters_summary) as `meters`. When it carries a healthy outer-meter
    stream, each meter's ΔW/SE is computed against its own baseline (the
    daisy-chain offset cancels per meter), then combined as a simple mean
    with SE = √(SE₁² + SE₂²)/2 — method "ci2". The n_task threshold gates
    stay on the PRIMARY poll count: they are a task-duration proxy, and two
    meters double samples without lengthening the task. A degraded or absent
    `meters` block leaves the single-meter "ci" path byte-identical to
    pre-CR-065. Both meters' SE_calibrated use the primary-calibrated
    `variance_idle_pct` (the outer plug has no separate calibration; the
    pre-test put cross-meter agreement at ~1%).
    """
    if s is None:
        s = cfg.load()

    # Legacy fallback ONLY when raw samples are entirely absent (older results
    # saved before persistence, or an un-migrated caller). A *new* run with
    # samples — even a single task poll — must use the CI model, where the
    # minimum-poll guards correctly drive a too-short run to 🔴 rather than
    # leaking to the legacy model's looser OR-thresholds (which flag 🟡 on a
    # strong ΔW regardless of poll count). std_* are guarded for n < 2 below.
    if not baseline_samples_w or not task_samples_w:
        return _legacy(delta_w, poll_count, w_base, s)

    n_task = len(task_samples_w)

    idle_cv = (s.get("variance_idle_pct") or s.get("variance_pct") or 0.0) / 100.0
    drift_cv = (s.get("variance_idle_drift_pct") or 0.0) / 100.0

    outer = (meters or {}).get("outer") or {}
    b2 = outer.get("baseline_samples_w")
    t2 = outer.get("task_samples_w")

    delta_1, se_1, w_base_m = _se_one_meter(baseline_samples_w, task_samples_w,
                                            idle_cv)
    se_drift = drift_cv * max(w_base_m, 1.0)                 # worst-case, additive
    if b2 and t2:
        delta_2, se_2, _ = _se_one_meter(b2, t2, idle_cv)
        delta = (delta_1 + delta_2) / 2.0
        se_final = math.sqrt(se_1 ** 2 + se_2 ** 2) / 2.0 + se_drift
        method = "ci2"
    else:
        delta = delta_1
        se_final = se_1 + se_drift
        method = "ci"

    if se_final <= 0:
        cp = 1.0 if delta > 0 else 0.5
    else:
        cp = _phi(delta / se_final)

    # Coalesce None as well as missing: load() supplies the DEFAULTS, but a
    # hand-edited settings.json with an explicit `null` would otherwise make
    # `cp >= None` crash the whole measurement. Confidence is the credibility
    # core — a config typo must never take a run down.
    green_p = s.get("conf_positive_green")
    green_p = 0.95 if green_p is None else green_p
    yellow_p = s.get("conf_positive_yellow")
    yellow_p = 0.80 if yellow_p is None else yellow_p
    green_n = s["conf_green_polls"]
    yellow_n = s["conf_yellow_polls"]
    ci95 = 1.96 * se_final

    result = {
        "method": method,
        "confidence_positive": round(cp, 4),
        "se_final_w": round(se_final, 3),
        "ci_delta_w_95": [round(delta - ci95, 3), round(delta + ci95, 3)],
    }
    if cp >= green_p and n_task >= green_n:
        result["flag"], result["label"] = "🟢", "Repeatable"
    elif cp >= yellow_p and n_task >= yellow_n:
        result["flag"], result["label"] = "🟡", "Early insight"
        if cp >= green_p and n_task < green_n:
            result["hint"] = (f"Strong signal (p={cp:.2f} above idle) but only {n_task} "
                              f"task polls — needs ≥{green_n} for 🟢. Use a longer clip "
                              f"or batch mode.")
    else:
        result["flag"], result["label"] = "🔴", "Need more data"
        result["hint"] = (f"p(above idle) = {cp:.2f}; need ≥{yellow_p:.0%} and "
                          f"≥{yellow_n} task polls for 🟡.")
    return result
