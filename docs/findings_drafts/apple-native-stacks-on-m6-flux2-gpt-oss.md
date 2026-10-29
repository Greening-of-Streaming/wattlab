---
slug: apple-native-stacks-on-m6-flux2-gpt-oss
version: 1
first_measured: 2026-10-28
last_refined: 2026-10-28
headline: "On an Apple M6, the Apple-native software stack is not automatically the frugal one: for FLUX.2 Klein image generation, MLX (mflux) spends 12 % MORE energy per image than PyTorch/MPS — while for gpt-oss-20b text generation it spends 17 % less per token than Ollama"
claim_short: "FLUX.2 Klein 4B, 1024 px, 4 steps, warm-model sessions, 20 images per run, n=3 per stack, all 🟢. Wh per image (± 95 % CI): RTX 5080 diffusers/CUDA 0.1423 ± 0.0017 · M6 diffusers/MPS 0.1189 ± 0.0016 · M6 mflux/MLX 0.1333 ± 0.0021. Seconds per image: 1.79 · 10.95 · 13.39. gpt-oss:20b, task T2, cold start, n=3 per runtime, all 🟢 (ci2). mWh per output token: M6 Ollama (llama.cpp/Metal) 0.1524 ± 0.0019 · M6 MLX (mlx-lm, MXFP4-Q8) 0.1260 ± 0.0022 (−17 %). Tokens/s: 36.4 vs 45.4."
confidence: green
scope: "Device layer only. GoS1: NVIDIA RTX 5080 16 GB (Ryzen 9 7900 host, Ubuntu 24.04, torch 2.11.0+cu128, diffusers 0.37.1). GoS2: Apple M6 Mac mini, 24 GB unified memory (torch 2.14.1 + diffusers 0.37.1 on MPS; mflux 0.24.0 + mlx 0.32.4; Ollama 0.35.1 Metal; mlx-lm 0.32.0). Images: warm model, generation window only. LLM: cold start (model load included), task T2. Network and CPE excluded. No amortised training cost."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - image/321bdc04
  - image/7d1fb715
  - image/5ad9d117
  - image/gos2-4641e0bf
  - image/gos2-f855cb05
  - image/gos2-8fd92801
  - image/gos2-c5ff14cc
  - image/gos2-39abe802
  - image/gos2-cd89edea
  - llm/gos2-cb79c7fa
  - llm/gos2-c0585e91
  - llm/gos2-36a1f1a7
  - llm/gos2-5f516ee5
  - llm/gos2-c39dc3fa
  - llm/gos2-7de0809c
related_findings:
  - apple-m6-image-energy-vs-rtx5080
  - apple-m6-llm-energy-per-token-vs-rtx5080
supersedes: null
tags: [image, llm, apple-silicon, m6, mlx, mflux, flux2, gpt-oss, cross-host, draft]
caveats:
  - "DRAFT pending lab review (CR-085). Measured 2026-10-28 by Claude; Tania checks before anything is posted."
  - "MARGINAL energy (above each machine's own idle: GoS1 ~75 W, GoS2 ~1.4 W). Whole-machine per-image figures would widen the GoS1↔GoS2 gap; they do not change the MPS↔MLX comparison (same machine, same idle)."
  - "Image method: same warm-model session protocol for all three stacks — model loaded and 2 warm-up images rendered OUTSIDE the window, 30 s settle, warm baseline with the model resident, window = GO → last image. Prompt encoding is done once per session on every stack (diffusers: encode-once, needed to fit the 16 GB RTX; mflux: memoised prompt encoder), so all three measure denoising + VAE decode from cached embeddings."
  - "MPS vs MLX are the same model weights (black-forest-labs/FLUX.2-klein-4B, bf16, no quantisation) on the same machine, but different kernels and numerics — images look alike, not pixel-identical. mflux peaked at 15.6 GB of unified memory."
  - "Output check (2026-10-29, n=1 pair): with the seeded noise drawn in float32 (fixed that day — bf16 noise differed between the two PyTorch builds, so the trio's GoS1 and GoS2 images were different pictures), one same-seed FLUX.2 Klein image from GoS1 CUDA and GoS2 MPS scored SSIM 0.991 / PSNR 38.2 dB: the same picture, differing in fine detail. Records image/ab0e5846 and image/gos2-64638985. mflux draws its noise with MLX's RNG, so MLX images are compared by eye only."
  - "mflux 0.24.0 was released the day before this measurement (2026-10-27); FLUX.2 support in mflux is new and may speed up in later releases. This is a snapshot of the two stacks as shipped, not of what MLX can do in principle."
  - "LLM comparison is runtime + conversion, not runtime alone: Ollama serves the GGUF gpt-oss:20b, MLX the mlx-community MXFP4-Q8 conversion (MXFP4 experts, 8-bit elsewhere). MLX decodes greedily (2,674 tokens every run); Ollama samples, and 2 of its 3 runs stopped at its 4,096-token context (4,004 output tokens), the third at 3,475. Longer outputs carry longer contexts, so per-token normalisation slightly favours the shorter MLX answers. Runs not interleaved: Ollama first (to 22:15), MLX 1–2 h later the same night (baselines 1.45–1.55 W vs 1.35–1.56 W). Two earlier MLX attempts were discarded: one set died of a Metal out-of-memory (Ollama's copy still resident), one set baselined at 9–10 W (no pre-job idle wait) — both fixed in code (CR-085, 2026-10-28) before the runs cited here."
  - "GoS2 idle floor re-measured after these installs: 1.325 W ± 0.076 W (n=2 clean runs, docs/gos2_design.md row 4) — unchanged, so the new environments add nothing at idle."
---

# The result, in one sentence

On the same Apple M6 Mac mini, the same FLUX.2 Klein 4B weights cost 0.119 Wh per image under PyTorch/MPS and 0.133 Wh under Apple's own MLX framework (mflux) — 12 % more — because MLX drew slightly less power (36 W vs 39 W above idle) but took 22 % longer per image; for gpt-oss-20b text generation the same switch goes the other way, with MLX spending 17 % less energy per token than Ollama (0.126 vs 0.152 mWh) at 1.25× the speed.

# Why this matters

"Use the native stack" is the usual advice for Apple silicon, and for LLM token generation OWL has measured it paying off (MLX −26 to −47 % per token on Qwen3, 2026-10-05 draft; −17 % on gpt-oss here). This campaign shows the advice does not transfer automatically to diffusion: the per-image energy depends on how well a given release of a given library maps the model onto the GPU, not on the framework's badge. A credible energy claim has to name the software stack and its version, not just the hardware.

The cross-machine comparison holds for the new model too: on the same diffusers code, the M6 spends 16 % less energy per image than the RTX 5080, while the RTX is 6.1× faster.

# How it was measured

**Images.** OWL's warm-model image session (`remote_ai.run_image_session`), identical on all three stacks: 4 prompts × 5 images (plus time-fill to a 30 s window), 1024 px, 4 steps, guidance 1.0, fixed seeds; dual P110 meters per machine, ΔE = ΔW × ΔT, confidence by the CR-028 CI model (method ci2). n = 3 sessions per stack.

| Machine · stack | Wh / image (± 95 % CI) | s / image | ΔW above idle |
|---|---|---|---|
| GoS1 RTX 5080 · diffusers / CUDA | 0.1423 ± 0.0017 | 1.79 | ~285 W |
| GoS2 M6 · diffusers / MPS | **0.1189 ± 0.0016** | 10.95 | ~39 W |
| GoS2 M6 · mflux / MLX | 0.1333 ± 0.0021 | 13.39 | ~36 W |

Per-run values (Wh / image): GoS1 0.1420 / 0.1418 / 0.1431 · MPS 0.1182 / 0.1194 / 0.1191 · MLX 0.1323 / 0.1337 / 0.1338.

**LLM.** OWL's cold-start protocol on GoS2 (unload, settle, baseline, stream task T2, mWh per output token), gpt-oss:20b, n = 3 per runtime.

| Runtime (GoS2 M6) | mWh / token (± 95 % CI) | tokens / s | output tokens | ΔW above idle |
|---|---|---|---|---|
| Ollama 0.35.1 · llama.cpp / Metal, GGUF | 0.1524 ± 0.0019 | 36.4 | 3,475 / 4,004 / 4,004 | ~20.0 W |
| mlx-lm 0.32.0 · MLX, MXFP4-Q8 | **0.1260 ± 0.0022** | 45.4 | 2,674 ×3 | ~20.6 W |

Per-run values (mWh / token): Ollama 0.1531 / 0.1524 / 0.1516 · MLX 0.1269 / 0.1251 / 0.1259. Both draw the same power above idle; MLX finishes sooner, so the whole gap is speed.

# What this finding does not measure

- Not training, not network, not the user's device.
- Not image or answer quality: the stacks' outputs differ numerically.
- Not quantised MLX variants (mflux `-q 4/8`) — they trade quality for speed and would be a different model, not a different stack.
- Not the Neural Engine (Core ML): Apple's Core ML diffusion path does not cover FLUX.2.
- One image model and one LLM; other models may rank the stacks differently.
