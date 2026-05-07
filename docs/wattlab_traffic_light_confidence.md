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

The current rule compares `delta_w` against empirical thresholds:

```text
yellow_threshold = variance_yellow_x * noise_w
green_threshold  = variance_green_x  * noise_w
```

This is useful, but the multipliers `variance_yellow_x` and `variance_green_x` are not currently tied to a formal confidence interval. A more statistically solid single-run method would express both calibrated uncertainty and per-run uncertainty as confidence intervals.

### 9.1 Use Workload-Specific Calibrated Variance

Instead of averaging all calibration outputs into one global `variance_pct`, use the more conservative calibrated variance for the relevant workload class:

```text
effective_calibrated_variance_pct =
  max(variance_idle_pct, variance_for_this_workload_type)
```

For video:

```text
CPU video run:
  variance_for_this_workload_type = variance_cpu_pct

GPU video run:
  variance_for_this_workload_type = variance_gpu_pct
```

With the current checked-in values:

```text
variance_idle_pct = 1.79 %
variance_cpu_pct  = 0.82 %
variance_gpu_pct  = 0.64 %

CPU calibrated variance = max(1.79, 0.82) = 1.79 %
GPU calibrated variance = max(1.79, 0.64) = 1.79 %
```

Rationale: every measurement contains idle/background/instrument noise, so `variance_idle_pct` should act as a floor. Workload-specific variance can only increase that floor if the workload calibration is noisier.

### 9.2 Calibrated Confidence Interval

Convert the calibrated variance percentage into watts:

```text
sigma_calibrated_w =
  effective_calibrated_variance_pct / 100 * w_base
```

If we treat this as the calibrated standard deviation of watt-level measurement noise, then the standard error of the difference between baseline mean and task mean is:

```text
SE_calibrated =
  sigma_calibrated_w * sqrt((1 / n_base) + (1 / n_task))
```

Then the calibrated 95% confidence interval for `delta_w` is:

```text
CI_calibrated_95 =
  delta_w +/- t_critical * SE_calibrated
```

For a simple first implementation, `t_critical = 1.96` is acceptable when sample counts are reasonably large. For small sample counts, use a Student-t critical value with approximate degrees of freedom.

### 9.3 Per-Run Confidence Interval

For the specific run, keep all baseline and task samples:

```text
baseline samples: b1, b2, ..., bn
task samples:     t1, t2, ..., tm
```

Compute:

```text
w_base = mean(baseline_samples)
w_task = mean(task_samples)
delta_w = w_task - w_base

std_base = sample_standard_deviation(baseline_samples)
std_task = sample_standard_deviation(task_samples)
```

Then estimate the per-run standard error:

```text
SE_per_run =
  sqrt((std_base^2 / n_base) + (std_task^2 / n_task))
```

The per-run 95% confidence interval is:

```text
CI_per_run_95 =
  delta_w +/- t_critical * SE_per_run
```

This catches a run that was unusually noisy even if the historical calibration is quiet.

### 9.4 Conservative Combined Confidence Interval

The calibrated interval and per-run interval answer different questions:

| Interval | Question |
|---|---|
| Calibrated CI | How uncertain should we be based on historical lab noise? |
| Per-run CI | How uncertain was this particular run? |

For a traffic-light decision, use the more conservative standard error:

```text
SE_final =
  max(SE_calibrated, SE_per_run)
```

Then:

```text
CI_final_95 =
  delta_w +/- t_critical * SE_final
```

This preserves the calibrated floor while allowing a noisy run to widen the uncertainty interval.

The same interval can be converted into energy terms:

```text
delta_e_wh =
  delta_w * duration_s / 3600

CI_energy_95 =
  CI_final_95 * duration_s / 3600
```

### 9.5 Confidence Score Instead of Empirical Multipliers

A cleaner mathematical option is to replace `variance_yellow_x` and `variance_green_x` with a direct confidence score.

Define:

```text
z =
  delta_w / SE_final
```

Then convert `z` into a one-sided confidence that the true workload delta is above zero:

```text
confidence_positive =
  Phi(z)
```

where `Phi()` is the standard normal cumulative distribution function.

Interpretation:

```text
confidence_positive = 0.50
  means the measured delta is indistinguishable from zero.

confidence_positive = 0.95
  means the run gives about 95% one-sided confidence that task power is above baseline.

confidence_positive = 0.99
  means the run gives about 99% one-sided confidence that task power is above baseline.
```

Then traffic lights can be thresholded directly:

```text
Green:
  confidence_positive >= 0.95
  and n_effective >= n_green_min

Yellow:
  confidence_positive >= 0.80
  and n_effective >= n_yellow_min

Red:
  otherwise
```

This is cleaner than saying "`delta_w` must exceed 5 times the noise floor" because the score has a direct statistical meaning.

### 9.6 What Replaces `variance_yellow_x` and `variance_green_x`?

In the current system:

```text
variance_yellow_x = 2
variance_green_x  = 5
```

These are empirical signal-to-noise multipliers:

```text
yellow means delta_w is at least 2x the estimated noise
green means delta_w is at least 5x the estimated noise
```

In the CI-based system, these can be replaced by confidence thresholds:

```text
confidence_yellow = 0.80
confidence_green  = 0.95
```

or, more conservative:

```text
confidence_yellow = 0.90
confidence_green  = 0.975
```

Recommended first version:

```text
Yellow: confidence_positive >= 0.80
Green:  confidence_positive >= 0.95
```

Rationale:

| Threshold | Meaning |
|---|---|
| `0.80` | Directional evidence; useful for "early insight", but not enough to cite strongly. |
| `0.95` | Conventional statistical threshold for "detected above baseline" in a single-run measurement. |

### 9.7 How Many Polls Are Appropriate?

The current system uses:

```text
conf_yellow_polls = 5
conf_green_polls  = 10
```

These are operational safeguards. They prevent a very short task from turning green based on one or two lucky samples.

In a CI-based system, sample count already affects confidence through:

```text
SE = standard_deviation / sqrt(n)
```

So, as `n_task` grows, the confidence interval naturally gets narrower. That means fewer hard poll-count thresholds are needed.

However, a minimum sample count is still useful because 1-second power readings are autocorrelated: adjacent samples are not fully independent. A 10-second task does not provide the same evidence as 10 independent laboratory repetitions.

Recommended first version:

```text
n_yellow_min = 5 task samples
n_green_min  = 10 task samples
```

This keeps the current operational guardrails while moving the actual decision from empirical multipliers to confidence intervals.

More robust future version:

Use effective sample count instead of raw sample count:

```text
block_s = 5
n_effective = floor(duration_s / block_s)
```

Then use:

```text
Yellow:
  n_effective >= 1 or 2

Green:
  n_effective >= 2 or 3
```

Rationale: if power readings are correlated over several seconds, 5-second blocks are closer to independent evidence than raw 1-second samples.

### 9.8 Proposed Single-Run Function

The confidence function could be:

```text
single_run_confidence(
  delta_w,
  n_base,
  n_task,
  std_base,
  std_task,
  w_base,
  variance_idle_pct,
  variance_workload_pct
) -> confidence_positive
```

With:

```text
effective_calibrated_variance_pct =
  max(variance_idle_pct, variance_workload_pct)

sigma_calibrated_w =
  effective_calibrated_variance_pct / 100 * w_base

SE_calibrated =
  sigma_calibrated_w * sqrt((1 / n_base) + (1 / n_task))

SE_per_run =
  sqrt((std_base^2 / n_base) + (std_task^2 / n_task))

SE_final =
  max(SE_calibrated, SE_per_run)

z =
  delta_w / SE_final

confidence_positive =
  Phi(z)
```

Then:

```text
Green:
  confidence_positive >= confidence_green
  and n_task >= n_green_min

Yellow:
  confidence_positive >= confidence_yellow
  and n_task >= n_yellow_min

Red:
  otherwise
```

This makes the traffic light more solid because:

1. It uses the historical lab calibration as a floor.
2. It uses the actual variance observed during the specific run.
3. It produces an interpretable confidence value.
4. It avoids arbitrary "2x" and "5x" multipliers.
5. It still preserves minimum-duration safeguards for very short tasks.
