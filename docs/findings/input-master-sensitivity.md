---
slug: input-master-sensitivity
version: 1
first_measured: 2026-05-26
last_refined: 2026-05-26
headline: "Input-master bitrate has no measurable effect on H.265 re-encode energy (CPU 1.7 %, GPU 4.9 % spread); input-codec has a small effect carried by the AV1-as-source case (CPU 3.4 %, GPU 10.3 % spread)"
claim_short: "Re-encode `h265_both` on 2-min 1080p siblings · bitrate axis (1.3 → 14.6 Mbps): flat · codec-of-origin axis (H.264 5.1 / H.265 3.4 / AV1 2.3 Mbps): AV1 source raises GPU energy by ~10 %"
confidence: green
scope: "Device layer only (GoS1: AMD Ryzen 9 7900 + Radeon RX 7800 XT, VAAPI full pipeline for GPU paths). Two-minute 1080p siblings of Big Buck Bunny. Variance floor at measurement time: variance_pct ≈ 1.29 % (S25 calibration)."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - video/2328a8ab
  - video/2c112a4d
  - video/97ec1c07
  - video/883b15b0
  - video/dc0679b2
  - video/683d3a30
related_findings:
  - abr-all-codecs-meridian-120s
supersedes: null
tags: [video, h265, input-sensitivity, cr-047, picker-design]
caveats:
  - "n=1 per input variant. The spreads reported are differences between single observations, not statistical confidence intervals. The variance_pct floor at measurement time (1.29 %) is what 'noise' means in the verdicts below."
  - "Test 2 (codec-of-origin) varies two things at once: codec AND bitrate (industry-typical streaming bitrates per codec, not equal bitrate). A clean 'codec-only' separation would require an equal-bitrate codec test, which this measurement does not provide."
  - "Decode on the GPU path is still software (OWL presets do not apply `-hwaccel vaapi` to decode). The codec-of-origin effect on the GPU side therefore reflects software decode cost, not hardware decode cost."
  - "The H.265 re-encode workload is what was measured. Other re-encode targets (libx264, av1_vaapi, etc.) may have different input-sensitivity behaviour and are not covered here."
---

# What was measured

Two questions tested independently:

**Test 1 — Input bitrate axis.** Three siblings of `bbb_120s.mp4` (2 min, 3840×2160 H.264), re-encoded with `libx264 -preset medium` at three explicit bitrate targets (light 15 Mbps, mid 5 Mbps, aggro 1 Mbps). Each then run through the OWL `h265_both` workload (CPU vs GPU H.265 encode + terminal VMAF pass).

**Test 2 — Input codec axis.** Three 2-min siblings downscaled to 1080p and encoded at industry-typical streaming bitrates per codec (H.264 5.1 Mbps, H.265 3.4 Mbps, AV1 2.3 Mbps). Each then run through the same `h265_both` workload.

# Numbers, from the stored result files

**Test 1 — Input bitrate (re-encode CPU and GPU energy):**

| Variant | CPU ΔE | CPU duration | GPU ΔE | GPU duration | GPU VMAF |
|---|---|---|---|---|---|
| light (15 Mbps source) | 1.31 Wh | 65.7 s | 0.335 Wh | 13.5 s | 84.6 |
| mid (5 Mbps source)    | 1.31 Wh | 65.3 s | 0.320 Wh | 13.3 s | 84.8 |
| aggro (1 Mbps source)  | 1.33 Wh | 62.2 s | 0.324 Wh | 13.4 s | 82.4 |

CPU energy spread: 1.7 % (at the noise floor of 1.29 %).
GPU energy spread: 4.9 % (~4× noise — detectable but below the threshold that would warrant a separate picker variant).

**Test 2 — Input codec (re-encode CPU and GPU energy, on 1080p sources at industry bitrates):**

| Input codec | CPU ΔE | GPU ΔE |
|---|---|---|
| H.264 (5.1 Mbps) | (per file) | (per file) |
| H.265 (3.4 Mbps) | (per file) | (per file) |
| AV1 (2.3 Mbps)   | (per file) | (per file) — highest |

CPU spread across codecs: 3.4 %.
GPU spread across codecs: 10.3 %. The H.264-vs-H.265 difference is flat; the AV1-as-source case is what carries most of the GPU-side jump.

# What this measurement establishes

- Input bitrate doesn't move the H.265 re-encode energy needle on this workload (≤5 % on either CPU or GPU).
- Codec of the source master moves the GPU side by ~10 %, with AV1-as-source carrying most of that. The CPU side stays flat (3.4 %).
- Higher-quality source codecs produced higher-quality output VMAF *even at lower bitrate* — AV1-as-source at 2.3 Mbps produced higher GPU VMAF than H.264-as-source at 5.1 Mbps. This is a bonus finding on the quality axis, not the energy axis.

# What this measurement was for

CR-047's design decision: the `/video` source picker matrix needed grounding. The verdict here justified collapsing the originally-sketched 5-variants-per-source shape to **2 variants per parent** (full + 2-min extract). The vignette (parent-level still image, no measurement purpose) is orthogonal to the variant list.

# What this measurement does not establish

- Other re-encode targets (libx264, av1_vaapi, etc.) — not tested. Cannot generalise the "input bitrate is flat" verdict to other workloads.
- Repeated runs (n>1) — not done here. The 1.7 % and 4.9 % spreads are differences between single observations.
- High-motion vs talking-head content — single source content type.

# Source

Original analysis: `docs/input_sensitivity_findings.md`. This finding is a summary; the analysis document has the full bench log + per-run thermal traces.
