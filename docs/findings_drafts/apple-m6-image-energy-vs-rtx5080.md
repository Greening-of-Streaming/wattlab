---
slug: apple-m6-image-energy-vs-rtx5080
version: 1
first_measured: 2026-10-05
last_refined: 2026-10-05
headline: "One image, two machines: a 1024-px SANA-Sprint image costs ~0.014 Wh on an RTX 5080 and ~0.015 Wh on an Apple M6 — a tie at the margin; the M6 wins only once its tiny idle draw is counted, and the RTX is 6.6× faster"
claim_short: "GPU path, batch 50, n=3, all 🟢. Wh per image, marginal (energy above idle): SANA-Sprint 0.6B 1024 px 2 steps — RTX 5080 0.0140, M6 0.0146 (≈ tie); SDXL-Turbo 512 px 4 steps — 0.0105 vs 0.0085 (M6 −19 %); SD-Turbo 512 px 20 steps — 0.0216 vs 0.0172 (M6 −20 %). Whole machine: M6 1.3–1.7× cheaper. RTX 4.7–6.6× faster."
confidence: green
scope: "Device layer only. GoS1: NVIDIA RTX 5080 (CUDA, torch 2.11) in a Ryzen 9 7900 host. GoS2: Apple M6 Mac mini, 24 GB unified memory (Metal/MPS, torch 2.14.1). diffusers 0.37.1 on both, identical model files. Network excluded. No amortised training cost. Generation only (model load excluded from ΔT)."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - image/3b671420
  - image/4b306d84
  - image/b156d048
  - image/gos2-d90790a4
  - image/gos2-82a3de95
  - image/gos2-ee130afb
  - image/f9bdb51a
  - image/4d4f872f
  - image/2c8eee89
  - image/gos2-f10fccbb
  - image/gos2-9038f5c6
  - image/gos2-fc85b49c
  - image/5018ce34
  - image/92297a48
  - image/3bfc4234
  - image/gos2-798b85e9
  - image/gos2-f2ea1345
  - image/gos2-5ae563c5
related_findings:
  - sd-turbo-cpu-image-first-run
  - apple-m6-llm-energy-per-token-vs-rtx5080
supersedes: null
tags: [image, apple-silicon, m6, cross-host, sana, draft]
caveats:
  - "DRAFT pending lab review. Measured overnight 2026-10-05 by Claude with the owner asleep; Tania checks before anything is posted."
  - "METHOD: OWL's image convention averages wall power over model load + generation but uses generation time only. At the public page's default batch (5 images, ~2 s on the RTX) model load dominates and the cross-host comparison INVERTS (RTX looked ~2× more efficient). These figures use batch 50 (Lab /image/bench) so load is negligible on both; the default-batch runs remain on record (report §3)."
  - "MARGINAL vs WHOLE-MACHINE: idle floors ~76–78 W (GoS1) vs ~1.4 W (GoS2). The headline tie is marginal; the whole-machine view (M6 1.3–1.7× cheaper) assumes the machine would otherwise idle."
  - "SANA-Sprint uses bf16 and its distilled guidance 4.5 (catalog family added 2026-10-05); SD/SDXL-Turbo fp16, guidance 0. Image sizes differ between models (1024 vs 512 px) — compare machines within a model, not models across rows."
  - "Same prompt (OWL canonical, random style modifier per run); quality not scored (visual check only, both machines produce correct images)."
  - "GoS2 measured via the interim SSH mechanism (CR-085); no thermal sensors or focus mode on GoS2; RTX SD-Turbo CI is wide (±0.0050)."
---

# The result, in one sentence

Generating the same images from the same model files, an RTX 5080 and an Apple M6 Mac mini spend roughly the same energy per image above idle — a tie on the efficient SANA-Sprint model, about 20 % in the M6's favour on the older SD/SDXL-Turbo — while the RTX finishes 4.7–6.6× sooner; counting the whole machine, the M6 is 1.3–1.7× cheaper.

# Why this matters

Diffusion is compute-bound, unlike LLM token generation — and here the discrete GPU's raw compute buys its energy back: the RTX draws ~170–205 W above idle (measured) but finishes so much faster that energy per image is level. The bigger lever is the model: a 1024-px SANA-Sprint image costs about what a 512-px SD-Turbo image does, on either machine.

# How it was measured

OWL's GPU image protocol on both machines through one code path (CR-085, `/image/bench`): baseline on each machine's own dual P110 meters, generate 50 images, ΔE = ΔW × generation time, Wh per image, CR-028 CI confidence. n = 3 per (model × machine), interleaved.

| Model | Machine | Wh / image (± 95 % CI) | s / image | Whole machine Wh / image |
|---|---|---|---|---|
| SANA-Sprint 0.6B, 1024 px, 2 steps | RTX 5080 | 0.0140 ± 0.0004 | 0.27 | 0.0198 |
| SANA-Sprint 0.6B, 1024 px, 2 steps | Apple M6 | 0.0146 ± 0.0005 | 1.79 | 0.0153 |
| SDXL-Turbo, 512 px, 4 steps | RTX 5080 | 0.0105 ± 0.0001 | 0.22 | 0.0150 |
| SDXL-Turbo, 512 px, 4 steps | Apple M6 | 0.0085 ± 0.0004 | 1.03 | 0.0089 |
| SD-Turbo, 512 px, 20 steps | RTX 5080 | 0.0216 ± 0.0050 | 0.40 | 0.0303 |
| SD-Turbo, 512 px, 20 steps | Apple M6 | 0.0172 ± 0.0002 | 2.06 | 0.0180 |

# What this finding does not measure

- Not image quality (no metric scored), not larger models (FLUX-class), not CPU paths.
- Not model-load energy (excluded by design) — relevant for one-off generations.
- Not Ollama's image runners (broken on GoS1's Ollama 0.20.2; see report).
