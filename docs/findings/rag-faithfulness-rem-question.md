---
slug: rag-faithfulness-rem-question
version: 1
first_measured: 2026-04-29
last_refined: 2026-04-29
headline: "RAG retrieval surfaced the correct GoS REM papers across three models; the smallest model (TinyLlama 1.1B) then generated a hallucinated answer combining the correct retrieval with an adjacent JRC chunk"
claim_short: "Same top-k=3 retrieval, three models — TinyLlama 1.1B hallucinated 'European Commission framework'; Gemma 3 12B and Phi-4 14B stayed faithful to the GoS source"
confidence: yellow
scope: "Device layer only. RAG corpus = GoS REM whitepapers + adjacent IEA / BBC / industry energy papers (ChromaDB top-k=3 retrieval, all-MiniLM-L6-v2 embeddings)."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - llm/5efb2079
related_findings:
  - llm-cold-inference-mwh-per-token
supersedes: null
tags: [rag, faithfulness, tinyllama, gemma3, phi4, pre-s30-panel, hallucination]
caveats:
  - "Pre-S30 panel. Gemma 3 12B was retired in the S30 ladder refresh (2026-05-27). The data on disk is real; a re-measurement on the new panel (e.g. with `qwen3:8b`, `mistral-nemo:12b`, `phi4`) would create a v2."
  - "n=1 — single run on the 'What is REM' question via `rag_compare` mode. The hallucination is not necessarily reproducible across repeated runs (sampling temperature is non-zero) and a follow-up at higher n would tighten the claim."
  - "The hallucination characterisation ('European Commission framework') is what the TinyLlama answer contains in this run. Other answers in other runs might hallucinate differently; this finding is a single observed instance, not a statistical claim about TinyLlama's failure mode in general."
  - "Retrieval quality and answer quality are independent. This finding shows that identical retrieval can produce different-quality answers depending on the consuming model — it does not score the retrieval itself."
---

# What was measured

A single `rag_compare` run on the question *"What is REM (Remote Energy Measurement)?"* — three models (TinyLlama 1.1B, Gemma 3 12B, Phi-4 14B), each receiving the same top-3 retrieved chunks from the OWL corpus (ChromaDB, all-MiniLM-L6-v2 embeddings). All three models retrieved the same chunks — the GoS REM whitepapers plus an adjacent JRC-Commission energy paper. The difference between the runs is what each model did with those chunks at generation time.

# Observed answers

- **TinyLlama 1.1B (the small model)**: generated text combining the GoS REM source with a description of REM as "a framework provided by the European Commission" — a hallucination. The retrieval was correct; the generation merged the correct source with an adjacent corpus chunk in a way that produced an incorrect summary.
- **Gemma 3 12B** and **Phi-4 14B**: stayed faithful to the GoS source. Both correctly identified REM as the Greening of Streaming Remote Energy Measurement project.

# What this measurement establishes

- Retrieval and generation are separate failure surfaces. The same retrieved chunks can produce a correct or hallucinated answer depending on the model.
- At this corpus size and on this question, the small (1.1B) model is the only one that failed; the 12B and 14B models did not.

# What this measurement does not establish

- It does not generalise. One question, one set of retrieved chunks, one run per model. Hallucinations on other questions, other retrievals, or repeated runs are not characterised here.
- It does not score Gemma 3 vs Phi-4 on any other axis. Both were correct on this question; that is all this run measures.
- It does not measure retrieval quality. By construction (top-k=3, fixed embedding model) retrieval was identical across the three models in this run.

# Why this matters for the bench

OWL's RAG measurement pipeline reports energy per inference cleanly. Without a faithfulness axis, the energy story alone would read as "small model is cheaper" — but the small model is the one that hallucinated. Energy per correct answer is a more useful headline than energy per token for any model where correctness is the goal. See CR-039 (energy × quality axis for AI jobs) for the explicit treatment.
