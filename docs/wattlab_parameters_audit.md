# OWL Parameters — Arbitrary, Empirical, Calibrated

> **Note (2026-06-11):** values below are a 2026-05-07 snapshot and several have since drifted (e.g. `baseline_polls`, `video_cooldown_s`); `settings.json` is the live truth. The Arbitrary/Empirical/Calibrated/Constrained classification is the durable content here.

Generated: 2026-05-07 (post-CR-022 resolution).

This audit responds to Tania's meeting question: *"How should I think about these versions?"* — specifically about `baseline_polls = 8` and other numbers chosen by intuition.

Each parameter is tagged:

- **Arbitrary** — chosen by intuition; no derivation, no measurement basis. These are Tania's main targets for principled redesign.
- **Empirical** — set from observation (e.g. thermal-recovery probe), not arbitrary but not formally derived either.
- **Calibrated** — output of a measurement process (e.g. variance calibration). Re-derived automatically.
- **Constrained** — set by external limits (hardware, API).
- **Operational** — policy/quota number; not measurement-relevant.

Default values reflect `settings.json` as of 2026-05-07. CV figures (`variance_*_pct`) are from a quick n=6 verification calibration; a longer overnight n=24 run will land final values.

---

## Measurement-relevant

### Baseline windows

| Param | Value | Type | What it controls | Path to principled |
|---|---|---|---|---|
| `baseline_polls` | 8 | **Arbitrary** | Number of 1-second polls before each task to estimate `w_base`. Drives `n_base` in §9 SE_calibrated and SE_per_run. | Derive from desired width of CI on `w_base`: `SE = σ_baseline / √n`. With idle CV ≈ 2.4%, `n=8 → SE ≈ 0.85% of w_base`; `n=16 → ≈ 0.6%`. Pick `n` such that SE ≤ X% of `w_base` for chosen X. |
| `video_cooldown_s` | 40 | **Empirical** | Wait after a video task before the next baseline. | Set from S21 thermal-recovery probe (12-distance × CPU+GPU): post-CPU and post-GPU baselines converge by `d=5s`; 40s is comfortably margined. Could be tightened with more probe data, or formalised as `≥ k × τ_thermal`. |
| `llm_rest_s` | 10 | **Arbitrary** | Wait between LLM jobs. Smaller because LLM thermals settle faster than video (no large fan ramp). | No probe data exists for LLM. Would need an LLM-specific thermal-recovery probe analogous to S21's video probe. |
| `llm_unload_settle_s` | 3 | **Empirical** | Wait after `keep_alive=0` returns before measuring baseline. Used in `llm.py` and `rag.py`. | Empirical: gives Ollama time to actually release VRAM. Hard to principle-derive without instrumenting Ollama. |

### Calibration job

| Param | Value | Type | What it controls | Path to principled |
|---|---|---|---|---|
| `variance_runs` | 24 | **Arbitrary** | Number of CPU+GPU pairs in a calibration job. Determines SE on the CV estimate. | Derivable from desired SE on the CV: `SE(CV) ≈ CV / √(2·(n−1))`. For n=24, SE ≈ 14% of value — i.e. our 0.95% gpu CV is real to ~±0.14 percentage points. Pick `n` for desired tightness. |
| `variance_cooldown_s` | 90 | **Empirical** | Pause between calibration runs. Same role as `video_cooldown_s` but applied to the calibration job specifically. | Could collapse to one shared cooldown if probe data supports it. |

### Confidence flag (the §9 redesign zone)

These are the parameters `wattlab_traffic_light_confidence.md` §9 proposes to rework.

| Param | Value | Type | What it controls | §9 disposition |
|---|---|---|---|---|
| `conf_green_polls` | 10 | **Arbitrary** | Min task polls for green. | §9 keeps as guardrail (1Hz polls aren't independent — autocorrelation defeats raw N). Could be derived from a target effective sample count `n_eff = duration_s / autocorr_s`, requires an autocorrelation measurement first. |
| `conf_yellow_polls` | 5 | **Arbitrary** | Min task polls for yellow. | Same as above. |
| `variance_green_x` | 5.0 | **Arbitrary** ("wet finger") | Multiplier on `noise_w` for green threshold. | §9 retires this — replaced by `confidence_positive ≥ 0.95`. |
| `variance_yellow_x` | 2.0 | **Arbitrary** ("wet finger") | Multiplier on `noise_w` for yellow. | §9 retires this — replaced by `confidence_positive ≥ 0.80`. |
| `variance_pct` | 1.29 | **Calibrated** | Mean of (idle, cpu, gpu) CVs. Used in current formula `noise_w = variance_pct/100 × w_base`. | §9 retires the "mean of three" averaging. Replaced by `max(variance_idle_pct, variance_workload_pct)` floor. |
| `variance_idle_pct` | 2.26 | **Calibrated** | CV of raw idle P110 readings during all baseline windows. | §9 keeps as the always-applied floor. |
| `variance_cpu_pct` | 0.66 | **Calibrated** | CV of ΔW across H.264 CPU runs. | §9 uses for CPU video runs. *Open units-shape question — sent separately.* |
| `variance_gpu_pct` | 0.95 | **Calibrated** | CV of ΔW across H.265 GPU runs. | §9 uses for GPU video runs. *Same units question.* |

### Codec targets

| Param | Value | Type | What it controls |
|---|---|---|---|
| `h264_bitrate_kbps` | 4000 | **Arbitrary** (industry rule-of-thumb) | H.264 ABR target at 1080p. Chosen to give roughly equivalent perceptual quality across the three codecs at 1080p, following common ratios. Could be validated with VMAF/SSIM. Out of scope for confidence framework; CR-029 (encoding rigor) territory. |
| `h265_bitrate_kbps` | 2000 | **Arbitrary** | H.265 target. |
| `av1_bitrate_kbps` | 1500 | **Arbitrary** | AV1 target. |

### In-code (not in `settings.json`)

| Param | Value | Type | What it controls |
|---|---|---|---|
| `POLL_INTERVAL` | 1.0 s | **Constrained** | P110 polling cadence used during baselines and tasks (`video.py`, `llm.py`, `image_gen.py`, `rag.py`). The hardware reports at 1 mW; the public HTTP API exposes 1 W at ~1 Hz. Lifting this requires the direct-device path (separate roadmap item). |
| `carbon.POLL_INTERVAL_S` | 300 s | **Operational** | Live grid-intensity poll cadence for Eco2mix/ElectricityMaps. Unrelated to power measurement. |

---

## Operational (not measurement-relevant)

Listed for completeness. Policy choices for the public deployment, not measurement parameters.

| Param | Value |
|---|---|
| `queue_anonymous_cap` | 1 |
| `queue_member_cap` | 4 |
| `upload_size_anonymous_mb` | 100 |
| `upload_size_member_mb` | 1024 |

---

## Summary

**Strong candidates for principled derivation:**

1. **`baseline_polls`** — derive from desired SE on `w_base`. Direct path.
2. **`variance_runs`** — derive from desired SE on the CV estimate. Direct path.
3. **`conf_green_polls` / `conf_yellow_polls`** — derive from autocorrelation of 1 Hz P110 polls (effective sample count). Needs an autocorrelation measurement first.
4. **`variance_green_x` / `variance_yellow_x`** — already retired by §9.

**Empirical, could be tightened:**

5. **`video_cooldown_s` / `llm_rest_s` / `variance_cooldown_s`** — could be unified and principled with more thermal-recovery probe data. LLM recovery probe doesn't exist yet.

**Calibrated (auto-updating; the question is whether the calibration computes the right thing):**

- All `variance_*_pct`. Open shape question on `variance_cpu_pct` / `variance_gpu_pct` — they're CV of *mean ΔW across runs* (already √n-smoothed), but §9.2 plugs them in as if they were σ of single per-second readings. Three reconciliation paths sent separately.

**Out of scope for confidence work but worth listing:**

- Codec bitrate targets (`h264/h265/av1_bitrate_kbps`) — apples-to-apples question, CR-029.
