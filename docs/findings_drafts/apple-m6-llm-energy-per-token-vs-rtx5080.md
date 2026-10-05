---
slug: apple-m6-llm-energy-per-token-vs-rtx5080
version: 1
first_measured: 2026-10-05
last_refined: 2026-10-05
headline: "Same model file, two machines: an Apple M6 Mac mini spends 44–51 % less energy per generated token than an RTX 5080 — and Apple's own MLX runtime takes a further 26–47 % off — while the RTX is 3–5× faster"
claim_short: "qwen3 1.7B/4B/8B, task T2 (medium reasoning), cold start, n=3. mWh per output token, marginal: RTX 5080 (Ollama) 0.130 / 0.294 / 0.496 · M6 Ollama, byte-identical GGUF 0.073 / 0.160 / 0.245 · M6 MLX 4-bit 0.039 / 0.105 / 0.182. Tokens/s: RTX 308 / 185 / 127 · M6 Ollama 91 / 47 / 27 · M6 MLX 120 / 55 / 32. Whole-machine: M6+MLX 3.4–4.7× cheaper per token."
confidence: green
scope: "Device layer only. GoS1: NVIDIA RTX 5080 16 GB (Ryzen 9 7900 host, Ubuntu 24.04, Ollama 0.20.2, CUDA). GoS2: Apple M6 Mac mini, 24 GB unified memory, macOS 27.0.1 (Ollama 0.35.1 Metal; mlx-lm 0.32.0). Network and CPE excluded. No amortised training cost. Single prompt task (T2), cold start (model load included)."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - llm/dcfe2bf7
  - llm/0d5a2c2c
  - llm/18ff7f0e
  - llm/gos2-f079b955
  - llm/gos2-2020644d
  - llm/gos2-ae79f829
  - llm/gos2-154efd8e
  - llm/gos2-092d00ab
  - llm/gos2-877b51c2
  - llm/e3c40ec3
  - llm/8423e5dd
  - llm/213a6c8f
  - llm/gos2-b29364f3
  - llm/gos2-efb92bf2
  - llm/gos2-61914d6d
  - llm/gos2-b3c5f2da
  - llm/gos2-a9d833e5
  - llm/gos2-bd841599
  - llm/515904d1
  - llm/5f5e8d12
  - llm/0575b37f
  - llm/gos2-afae8350
  - llm/gos2-4eb06e95
  - llm/gos2-aee6aeff
  - llm/gos2-8db534da
  - llm/gos2-58b8ba54
  - llm/gos2-117e7169
related_findings:
  - llm-cold-inference-mwh-per-token
  - apple-m6-encode-energy-vs-ryzen-rtx5080
supersedes: null
tags: [llm, apple-silicon, m6, mlx, ollama, cross-host, draft]
caveats:
  - "DRAFT pending lab review. Measured overnight 2026-10-05 by Claude with the owner asleep; Tania checks before anything is posted."
  - "Confidence: green for every run except GoS1 qwen3:1.7b (🟡 ×3 — runs last ~7 s at 308 tok/s, too few meter polls). The 1.7B RTX figure is indicative."
  - "MARGINAL vs WHOLE-MACHINE: headline uses energy above each machine's own idle (~78 W vs ~1.4 W). Whole-machine per-token figures in the report widen the gap; they assume the machine would otherwise idle."
  - "Ollama versions differ (GoS1 0.20.2, GoS2 0.35.1) — the GGUF file is byte-identical (digests 8f68893c685c / 359d7dd4bcda / 500a1f067a9f) but the llama.cpp underneath is ~15 releases apart. Upgrading GoS1 needs owner sudo."
  - "MLX is a different engine, not a re-run: mlx-community 4-bit conversions (not the GGUF Q4_K_M file) and greedy decoding by default (identical token count every run), whereas Ollama samples at its default temperature (output lengths vary run to run). Per-token normalisation absorbs most of this; longer outputs also carry longer contexts."
  - "Cold start includes model load on both (Ollama: server up, model unloaded; MLX: runtime imported, model not loaded). Warm-inference per-token figures would be lower on both and are not measured here."
  - "One task (T2) of one model family (Qwen3, thinking mode on). Not measured: prompt-heavy workloads (prefill-bound, where the RTX's compute advantage matters more), concurrency/batching, models that exceed the RTX's 16 GB VRAM."
  - "GoS2 measured through the interim SSH mechanism (CR-085); no focus mode on GoS2; inner P110 refreshes every 2 s at low load."
---

# The result, in one sentence

Running the byte-identical Qwen3 model file under Ollama on both machines, the Apple M6 Mac mini spent 44–51 % less energy per generated token than the NVIDIA RTX 5080, and switching the Mac to Apple's MLX runtime saved a further 26–47 % — but the RTX produced tokens 3–5× faster.

# Why this matters

Token generation is limited by memory bandwidth: every token reads the whole active weight set. The RTX 5080's GDDR7 delivers several times the M6's 170 GB/s unified memory, which buys speed — but at ~200–230 W above idle against the M6's ~21–27 W (measured, this campaign), the 4–5× speed does not pay for itself per token. For latency-tolerant local inference the energy-efficient choice is the low-power machine, and on that machine the software stack (MLX vs llama.cpp) is worth as much again as the hardware choice.

# How it was measured

OWL's cold-start LLM protocol on both machines through the same code path (CR-085): unload model, settle, baseline on the machine's own dual P110 meters, stream task T2 ("Explain the trade-offs between H.264, H.265, and AV1 for a streaming operator…"), ΔE = ΔW × ΔT, mWh per output token, confidence by the CR-028 CI model. n = 3 per (model × engine), interleaved across machines.

| Model | Engine | mWh / token (± 95 % CI) | tokens / s |
|---|---|---|---|
| qwen3:1.7b | RTX 5080 · Ollama | 0.130 ± 0.009 (🟡) | 308 |
| qwen3:1.7b | M6 · Ollama | 0.073 ± 0.028 | 91 |
| qwen3:1.7b | M6 · MLX | 0.039 ± 0.003 | 120 |
| qwen3:4b | RTX 5080 · Ollama | 0.294 ± 0.010 | 185 |
| qwen3:4b | M6 · Ollama | 0.160 ± 0.008 | 47 |
| qwen3:4b | M6 · MLX | 0.105 ± 0.001 | 55 |
| qwen3:8b | RTX 5080 · Ollama | 0.496 ± 0.006 | 127 |
| qwen3:8b | M6 · Ollama | 0.245 ± 0.010 | 27 |
| qwen3:8b | M6 · MLX | 0.182 ± 0.004 | 32 |

# What this finding does not measure

- Not training, not network, not the user's device.
- Not answer quality: MLX and Ollama outputs differ (different quantisation and decoding).
- Not the unified-memory *capacity* advantage (models larger than 16 GB) — untested.
- Not batched / multi-user serving, where a discrete GPU's throughput changes the per-token picture.
