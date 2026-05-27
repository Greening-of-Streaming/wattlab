---
slug: llm-cold-inference-mwh-per-token
version: 1
first_measured: 2026-04-24
last_refined: 2026-05-08
headline: "Cold LLM inference on the GoS1 bench: TinyLlama (1.1B) at ~0.07 mWh/token, Mistral 7B at ~0.96 mWh/token — both on the pre-S30 ladder"
claim_short: "T3 cold inference · TinyLlama 0.0718 mWh/token 🟡 · Mistral 7B 0.9639 mWh/token 🟢 · ratio ≈ 13× per token"
confidence: yellow
scope: "Device layer only (GoS1: AMD Ryzen 9 7900 + Radeon RX 7800 XT, Ollama 0.20.2). Network and CPE excluded. No amortised training cost."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - llm/2d79c99c
  - llm/163c6442
related_findings: []
supersedes: null
tags: [llm, cold-inference, tinyllama, mistral, mwh-per-token, pre-s30-panel]
caveats:
  - "Pre-S30 panel. Both `mistral` (7B v0.3) and the version of `tinyllama` used here were the models on the bench before the S30 ladder refresh (2026-05-27). Mistral 7B was retired in that refresh in favour of `mistral-nemo:12b`. The data on disk is real and these were the live measurements at the time; a re-measurement on the new panel would produce a v2 via `supersedes`."
  - "TinyLlama returned 🟡 confidence here (n=2-poll task window; ΔW close to the noise floor). Mistral 7B returned 🟢. The ratio is therefore not n=1 across both rows — interpret as approximate."
  - "CLAUDE.md prose at the time of import cited slightly different per-token figures (Mistral 0.943 mWh/token, TinyLlama 0.061 mWh/token). Numbers here are taken from the source result files."
  - "Energy per token is reward-asymmetric: a model that produces a longer answer at the same per-token cost will look cheaper per token but more expensive per task. The TinyLlama-vs-Mistral ratio in this finding is per-token, not per-answer."
  - "T3 is the standard task category in OWL's LLM measurement protocol. Cold = no warm-up; the model is loaded freshly before measurement."
---

# What was measured

Two cold inferences on the same T3 task, executed via Ollama and measured at the wall through the Tapo P110:

- `tinyllama` (1.1B parameters, GGUF Q4): single T3 run, 2026-04-24
- `mistral` (7B v0.3, GGUF Q4): T3 run, 2026-05-08 (the closer-to-CLAUDE.md-prose match)

Each model was unloaded before the measurement, baseline was taken across 10 polls × 1 s, then the task was issued and polled at 1 Hz until completion.

# Numbers, from the stored result files

| Model | mWh per token | Tokens / s | W_base / W_task | Confidence |
|---|---|---|---|---|
| TinyLlama 1.1B | 0.0718 | (per file) | (per file) | 🟡 |
| Mistral 7B    | 0.9639 | 49.7 | 61.8 W / 234.2 W | 🟢 |

Per-token ratio: Mistral 7B / TinyLlama ≈ 13.4× — the larger model uses an order of magnitude more energy per token in this measurement.

# What this measurement does not establish

- Answer quality is not measured here. CLAUDE.md notes that TinyLlama produced corpus-grounded but generic answers on the RAG faithfulness probe (see the separate `rag-faithfulness-rem-question` finding); per-token energy alone is not a complete picture.
- The bench does not measure end-to-end LLM inference (no client device, no network).
- These figures predate the S30 ladder refresh and the move to the dynamic model catalog. A current measurement on `qwen3:1.7b` and `mistral-nemo:12b` is a follow-up that would create a v2.

# Read alongside

The RAG faithfulness finding (`rag-faithfulness-rem-question`) on the same TinyLlama version — same retrieval, smaller model generated a hallucinated answer. Energy per token and answer correctness are independent axes.
