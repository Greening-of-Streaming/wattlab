---
slug: apple-m6-image-energy-vs-rtx5080
version: 2
first_measured: 2026-10-05
last_refined: 2026-10-05
headline: "One image, two machines: with model loading kept out of the measurement, an Apple M6 Mac mini uses 10–31 % less energy per image than an RTX 5080 — the RTX is 4.6–6.7× faster"
claim_short: "Warm-model sessions, generation window only, 100 images per session (4 prompts × 25), n=3, all 🟢. Wh per image, steady state: SANA-Sprint 0.6B 1024 px — RTX 5080 0.0175, M6 0.0157 (−10 %); SDXL-Turbo 512 px — 0.0136 vs 0.0093 (−31 %). Whole window incl. ramp: 0.0163 vs 0.0154 and 0.0125 vs 0.0091. Whole machine: M6 1.4–1.8× cheaper. Prompt complexity: no effect on time or energy."
confidence: green
scope: "Device layer only. GoS1: NVIDIA RTX 5080 (CUDA, torch 2.11) in a Ryzen 9 7900 host. GoS2: Apple M6 Mac mini, 24 GB unified memory (Metal/MPS, torch 2.14.1). diffusers 0.37.1 on both, identical model files, identical runner script. Network excluded. No amortised training cost. Generation only — model load and 2 warm-up images excluded."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - image/89f7ba16
  - image/b87d1d53
  - image/939e5e29
  - image/gos2-7b4209cf
  - image/gos2-b17ab828
  - image/gos2-b376d791
  - image/3cc0f76c
  - image/3e8c9114
  - image/521de028
  - image/gos2-131eebb1
  - image/gos2-c0d07b7e
  - image/gos2-f928b53f
related_findings:
  - sd-turbo-cpu-image-first-run
  - apple-m6-llm-energy-per-token-vs-rtx5080
supersedes: null
tags: [image, apple-silicon, m6, cross-host, sana, draft]
caveats:
  - "DRAFT pending lab review. Version 2 (2026-10-05) replaces an earlier draft that reported a SANA-Sprint 'tie' — that figure came from OWL's oneshot convention (power polled across import + load + generation, ΔT = generation only), which diluted the fast RTX's ΔW by ~14–19 %. The owner suspected exactly this; the warm-model session method below removes it."
  - "METHOD: same runner script on both machines; model loaded and 2 warm-up images rendered OUTSIDE the window; 30 s settle; baseline with the model resident; window = GO → last image. Warm and cold baselines agree after 30 s settle (GoS1 74.5 vs 75.6 W; GoS2 1.3 vs 1.5 W) — a 10 s settle in the smoke test left the RTX clocks high (+34 W) and must not be used."
  - "METER RAMP: the first prompt block reads 9–27 % low (RTX 22–27 %, M6 9–12 %) with identical generation time — the P110 lags the power step at the window start. Steady-state figures (prompt blocks 2–4) are the headline; whole-window figures understate both machines, the RTX more (27 s window vs 180 s)."
  - "PROMPT CONTROL: four prompts (canonical; a long multi-object scene longer than CLIP's 77 tokens; text rendering; high-detail texture) took identical time per block (e.g. M6 SANA 44.99 / 44.92 / 44.94 / 44.96 s). Diffusion compute is set by steps × resolution, not prompt content."
  - "MARGINAL vs WHOLE-MACHINE: headline is energy above idle (~75 W vs ~1.4 W). Whole-machine figures assume the machine would otherwise idle."
  - "Image sizes differ between models (SANA-Sprint 1024 px, SDXL-Turbo 512 px): compare machines within a model. Quality not scored (visual check only)."
  - "GoS2 measured via the interim SSH mechanism (CR-085); no thermal sensors or focus mode on GoS2."
---

# The result, in one sentence

Generating the same images from the same model files with the same script, an Apple M6 Mac mini spent 10 % less energy per image than an RTX 5080 on SANA-Sprint (1024 px) and 31 % less on SDXL-Turbo (512 px), once model loading and warm-up were kept out of the measurement — while the RTX finished each image 4.6–6.7× sooner.

# Why this matters

The first pass of this comparison said "tie" — and it was the measurement method, not the machines: averaging power over model load made the fast GPU look cheaper per image. With a clean generation-only window the M6 is ahead on both models, by less on the modern bf16 SANA-Sprint (where the RTX's tensor cores do best) than on SDXL-Turbo. Prompt complexity does not move the result at all.

# How it was measured

`POST /image/session` (CR-085): one runner script on both hosts; load + 2 warm-up images; 30 s settle; warm-model baseline on each machine's own dual P110 meters; then 4 prompts × 25 images, timed from GoS1's clock (GO → last image). ΔE = ΔW × window; Wh per image; CR-028 CI confidence. n = 3 sessions per (model × machine), interleaved.

| Model | Machine | Wh / image, steady state (blocks 2–4) | Wh / image, whole window | s / image | Whole machine Wh / image |
|---|---|---|---|---|---|
| SANA-Sprint 0.6B, 1024 px, 2 steps | RTX 5080 | 0.0175 ± 0.0002 | 0.0163 ± 0.0001 | 0.269 | 0.0219 |
| SANA-Sprint 0.6B, 1024 px, 2 steps | Apple M6 | **0.0157 ± 0.0005** | 0.0154 ± 0.0004 | 1.798 | 0.0161 |
| SDXL-Turbo, 512 px, 4 steps | RTX 5080 | 0.0136 ± 0.0001 | 0.0125 ± 0.0001 | 0.225 | 0.0172 |
| SDXL-Turbo, 512 px, 4 steps | Apple M6 | **0.0093 ± 0.0001** | 0.0091 ± 0.0001 | 1.026 | 0.0095 |

# What this finding does not measure

- Not image quality (no metric scored), not larger models (FLUX-class), not CPU paths.
- Not model-load energy (excluded by design) — it matters for one-off generations.
- Not Ollama's image runners (broken on GoS1's Ollama 0.20.2; see report).
