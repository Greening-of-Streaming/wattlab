# WattLab Traffic-Light Confidence Logic

Generated: 2026-05-07

This document explains how WattLab assigns the traffic-light confidence flag shown on workload results.

## 1. What the Flag Means

The traffic light is a simple confidence indicator for one measured run.

It asks:

> Is the measured power increase above idle large enough, and sampled for long enough, to be worth trusting?

It does not currently estimate formal statistical confidence intervals, p-values, or run-to-run uncertainty for a specific task. It is a signal-strength and sample-count rule.

| Flag | Label | Meaning |
|---|---|---|
| Green | Repeatable | Power delta is clearly above the configured noise floor and the task ran long enough. |
| Yellow | Early insight | Directional result: either the signal is above a lower threshold or there are enough samples, but it does not meet the green rule. |
| Red | Need more data | The run is too close to the noise floor and/or too short. |

## 2. Inputs Used

For every measured workload, WattLab calculates:

| Variable | Meaning |
|---|---|
| `w_base` | Mean idle baseline power in watts. |
| `w_task` | Mean power in watts while the workload runs. |
| `delta_w` | `w_task - w_base`; the extra power attributed to the workload. |
| `poll_count` | Number of task-period power readings. Power is sampled once per second. |
| `variance_pct` | Configured estimate of measurement/system variance as a percentage of baseline power. |
| `variance_green_x` | Multiplier applied to the noise estimate for the green threshold. |
| `variance_yellow_x` | Multiplier applied to the noise estimate for the yellow threshold. |
| `conf_green_polls` | Minimum number of task samples required for green. |
| `conf_yellow_polls` | Minimum number of task samples that can qualify a result for yellow. |

## 3. Formula

First, WattLab estimates the run's noise floor in watts:

```text
noise_w = variance_pct / 100 * max(w_base, 1.0)
```

The `max(w_base, 1.0)` guard prevents division/scale problems if a baseline were ever zero or invalidly tiny.

Then it computes thresholds:

```text
yellow_threshold = variance_yellow_x * noise_w
green_threshold  = variance_green_x  * noise_w
```

The flag is assigned as:

```text
Green / Repeatable:
  delta_w > green_threshold
  AND poll_count >= conf_green_polls

Yellow / Early insight:
  delta_w >= yellow_threshold
  OR poll_count >= conf_yellow_polls

Red / Need more data:
  otherwise
```

In code, this logic appears in the workload modules:

| Workload | Function |
|---|---|
| Video | `confidence()` in `wattlab_service/video.py` |
| LLM | `confidence()` in `wattlab_service/llm.py` |
| Image generation | `confidence()` in `wattlab_service/image_gen.py` |
| RAG | `confidence()` in `wattlab_service/rag.py` |

The video version also adds a hint when the power signal is strong enough for green but the task was too short to meet the green poll-count threshold.

## 4. Current Settings

The checked-in `settings.json` currently has:

```json
{
  "baseline_polls": 7,
  "conf_green_polls": 10,
  "conf_yellow_polls": 5,
  "variance_pct": 1.08,
  "variance_green_x": 5,
  "variance_yellow_x": 2,
  "variance_idle_pct": 1.79,
  "variance_cpu_pct": 0.82,
  "variance_gpu_pct": 0.64
}
```

Defaults live in `wattlab_service/settings.py`; runtime settings are loaded from `/home/gos/wattlab/settings.json` on GoS1. The `/settings` page exposes these values, with write access limited to local/private clients.

## 5. Worked Example

Suppose:

```text
w_base = 55 W
variance_pct = 1.08
variance_yellow_x = 2
variance_green_x = 5
conf_yellow_polls = 5
conf_green_polls = 10
```

Then:

```text
noise_w = 1.08 / 100 * 55 = 0.594 W
yellow_threshold = 2 * 0.594 = 1.188 W
green_threshold  = 5 * 0.594 = 2.970 W
```

So:

| Example run | Result |
|---|---|
| `delta_w = 4 W`, `poll_count = 12` | Green: signal exceeds green threshold and sample count is at least 10. |
| `delta_w = 4 W`, `poll_count = 4` | Yellow: strong signal, but too short for green. |
| `delta_w = 1.5 W`, `poll_count = 6` | Yellow: signal exceeds yellow threshold and sample count is at least 5. |
| `delta_w = 0.5 W`, `poll_count = 4` | Red: weak signal and too few samples. |
| `delta_w = 0.5 W`, `poll_count = 6` | Yellow under current rule, because enough samples alone qualify for yellow. Treat cautiously. |

## 6. How Variance Is Set

`variance_pct` can be edited manually, but it is intended to be derived from WattLab's variance calibration workflow.

The calibration job:

1. Runs H.264 CPU and H.265 GPU encodes repeatedly on the Meridian full source.
2. Collects idle baseline readings across all baseline windows.
3. Computes:
   - `variance_idle_pct`: coefficient of variation of raw idle P110 readings.
   - `variance_cpu_pct`: coefficient of variation of delta-W across H.264 CPU runs.
   - `variance_gpu_pct`: coefficient of variation of delta-W across H.265 GPU runs.
4. Stores the mean of the available values as `variance_pct`.

The calibration implementation is `run_variance_calibration()` in `wattlab_service/video.py`.

Current checked-in calibration-derived values:

```text
variance_idle_pct = 1.79 %
variance_cpu_pct  = 0.82 %
variance_gpu_pct  = 0.64 %
variance_pct      = 1.08 %
```

The mean is:

```text
(1.79 + 0.82 + 0.64) / 3 = 1.083... %
```

Rounded, that gives the current `variance_pct` of `1.08`.

## 7. Interpretation Caveats

The current rule is useful as a fast operational indicator, but it has limits:

| Caveat | Why it matters |
|---|---|
| It is not a formal statistical test. | There is no confidence interval or p-value for an individual result. |
| It uses a global variance percentage. | The same `variance_pct` is applied to video, LLM, image generation, and RAG, even though their noise patterns may differ. |
| Yellow can be triggered by sample count alone. | A weak but long enough run can become yellow even if `delta_w` is below the yellow power threshold. |
| It uses mean power only. | It does not consider within-run variance, outliers, ramp-up/ramp-down shape, or thermal drift except indirectly. |
| It does not require repeated runs of the same task. | Green means "strong enough signal in this run", not "replicated across N independent runs". |
| Negative or near-zero `delta_w` will be red unless sample count alone reaches yellow. | This can happen for very short or low-power workloads close to the P110/system noise floor. |

## 8. Practical Use

Use the flag this way:

| Flag | Recommended interpretation |
|---|---|
| Green | Reasonable to cite as a single-run measurement, especially when comparing large deltas. |
| Yellow | Treat as directional. Repeat the run, use a longer input, or batch the task. |
| Red | Do not cite. Increase task duration, batch size, or measurement sensitivity. |

For a stronger statistical methodology, WattLab would need repeated runs per condition and a report of mean, standard deviation, confidence interval, and possibly a paired comparison between CPU/GPU conditions.

## 9. Proposed Improvement: CI-Based Single-Run Confidence

This section is a proposed replacement for the current single-run traffic light. It is scoped to **single-run measurability**: "can this one run be distinguished from idle?" It is not a repeatability test across many runs.

### 9.1 Correct Use of Existing Calibration Fields

The current calibration fields do not all describe the same statistical object:

| Field | Current meaning | Use in single-run CI? |
|---|---|---|
| `variance_idle_pct` | CV of individual 1-second idle P110 readings during calibration | Yes, as the calibrated idle noise floor. |
| `variance_cpu_pct` | CV of run-level mean `delta_w` across repeated H.264 CPU calibration runs | No, reserve for aggregate/repeated-run confidence. |
| `variance_gpu_pct` | CV of run-level mean `delta_w` across repeated H.265 GPU calibration runs | No, reserve for aggregate/repeated-run confidence. |

So the corrected single-run method should **not** use:

```text
max(variance_idle_pct, variance_cpu_pct)
max(variance_idle_pct, variance_gpu_pct)
```

Those values are not directly comparable. For the first CI-based implementation, use:

```text
calibrated_cv_pct = variance_idle_pct
```

### 9.2 Required Per-Run Samples

Persist these arrays in every video result JSON:

```text
baseline_samples_w
task_samples_w
```

Then each run can compute:

```text
w_base = mean(baseline_samples_w)
w_task = mean(task_samples_w)
delta_w = w_task - w_base

n_base = count(baseline_samples_w)
n_task = count(task_samples_w)

std_base = sample standard deviation of baseline_samples_w
std_task = sample standard deviation of task_samples_w
```

This uses the actual noise observed during the run instead of relying only on calibration.

### 9.3 Two Uncertainty Estimates

Compute a calibrated uncertainty from the idle calibration:

```text
sigma_calibrated_w =
  variance_idle_pct / 100 * w_base

SE_calibrated =
  sigma_calibrated_w * sqrt((1 / n_base) + (1 / n_task))
```

Compute a per-run uncertainty from the actual samples:

```text
SE_per_run =
  sqrt((std_base^2 / n_base) + (std_task^2 / n_task))
```

Use the conservative one:

```text
SE_final =
  max(SE_calibrated, SE_per_run)
```

Rationale:

| Estimate | Protects against |
|---|---|
| `SE_calibrated` | Overconfidence when this run looks artificially quiet. |
| `SE_per_run` | Background spikes or instability during this specific run. |
| `max(...)` | Always uses the wider uncertainty estimate. |

### 9.4 Confidence Score

Convert the measured power increase into a one-sided confidence score:

```text
z =
  delta_w / SE_final

confidence_positive =
  Phi(z)
```

`Phi()` is the standard normal cumulative distribution function.

Interpretation:

| `confidence_positive` | Meaning |
|---|---|
| `0.50` | The run is indistinguishable from zero extra power. |
| `0.80` | Directional evidence that the task is above idle. |
| `0.95` | Conventional single-run detection threshold. |
| `0.99` | Strong single-run detection. |

This replaces the old `variance_yellow_x` and `variance_green_x` signal-to-noise multipliers with a directly interpretable confidence value.

### 9.5 Traffic-Light Thresholds

Recommended first pass:

```text
Green:
  confidence_positive >= 0.95
  and n_task >= 10

Yellow:
  confidence_positive >= 0.80
  and n_task >= 5

Red:
  otherwise
```

The minimum sample counts remain useful because 1-second power samples are autocorrelated. A very short task should not turn green from one or two lucky readings, even if the formula returns a high score.

Future refinement: replace raw sample count with effective sample count, for example 5-second blocks:

```text
n_effective = floor(duration_s / 5)
```

### 9.6 Result Fields to Store

Store the computed values so old results can be reflagged later:

```text
confidence_method
baseline_samples_w
task_samples_w
std_base_w
std_task_w
se_calibrated_w
se_per_run_w
se_final_w
confidence_positive
ci_delta_w_95
ci_delta_e_wh_95
```

The 95% intervals are:

```text
ci_delta_w_95 =
  delta_w +/- 1.96 * SE_final

ci_delta_e_wh_95 =
  ci_delta_w_95 * duration_s / 3600
```

For small sample counts, a Student-t critical value can replace `1.96`.

### 9.7 Short Implementation Guidance

For CR-028 Phase 2, scoped to video:

1. Persist raw `baseline_samples_w` and `task_samples_w` for every video run.
2. Build the CI-based single-run flag from actual run samples plus `variance_idle_pct`.
3. Do not use `variance_cpu_pct` or `variance_gpu_pct` in the single-run CI formula.
4. Keep `variance_cpu_pct` and `variance_gpu_pct` for a later aggregate/repeated-run confidence layer.
5. Replace the old `variance_yellow_x` / `variance_green_x` decision with `confidence_positive` thresholds.
6. Keep minimum task-sample safeguards for short runs.
