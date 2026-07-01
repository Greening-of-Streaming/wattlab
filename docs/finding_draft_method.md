# LLM-assisted finding drafter — method note

*Added 2026-06-24. Engine: `wattlab_service/finding_draft.py`; routes:
`routes_finding_draft.py`; capability: `CREATE_FINDING` (Lab).*

## What it is

A Lab-only assistant that **drafts** a `docs/findings/<slug>.md` from one or more
stored measurement results, for an operator to edit and approve. It is the
**first non-measurement use of an LLM in OWL** — everywhere else the local models
are measurement *targets*. The drafter reuses the already-installed
`gpt-oss:20b` (13 GB, fits the RTX 5080) via the existing Ollama path; no new
model, no fine-tuning.

## Why it is built the way it is

OWL's first principle is *"if it can't be measured, it shouldn't be asserted."*
An LLM that "picks up weak signals" is in tension with that, so the architecture
draws a hard line:

- **The LLM never detects signals.** Deterministic code (`gather_context`,
  `detect_signals`) reads the result JSON, pulls the traffic-light confidence
  flags, and qualifies cross-run context. The LLM is handed those facts and only
  **verbalises** them. A 🔴 (below-noise) measurement is, by OWL's own rules, not
  an assertable finding — the engine refuses to mark such a draft `ok`.
- **The LLM never sets the load-bearing fields.** `confidence` is the weakest
  cited result's flag; `scope` is copied verbatim from the cited result's
  as-measured scope; `source_result_ids`, `methodology_ref`, slug, and dates are
  derived. The LLM authors only `headline`, `claim_short`, `body_md`, `tags`,
  `caveats`.
- **Human-gated.** `POST /findings/draft` never writes disk. Only
  `POST /findings/draft/save` writes, after the operator edits, and it
  re-validates and round-trips the file through the canonical `findings.load`
  before keeping it (rolls back on failure).

## Guardrails (`validate_draft`)

Each issue is `error` (blocks save) or `warning` (surfaced, non-blocking):

| Check | Severity | Rule |
|---|---|---|
| `bandwidth_network_energy` | error | A sentence linking a data/bitrate term to *network* energy. GoS does not accept the bandwidth→network-energy link (CLAUDE.md §GoS Framing). "Networks use energy" alone is fine. |
| `confidence_inflated` / `red_source` | error | Finding confidence may be no greener than the weakest cited measurement; a red source is not assertable. |
| `scope_mismatch` | error | Scope must match a cited result's as-measured scope, not an invented one. |
| `schema_missing` / `bad_slug` / `dangling_source` | error | Same schema contract the findings loader enforces; every source must resolve on disk. |
| `unverified_number` | warning | A unit-bearing figure in the prose that doesn't trace (±1%, with rounding) to any value in the cited result JSON — i.e. a possible hallucination. |
| `motto` / `slug_exists` | warning | "not eco-warriors" slogan; overwriting an existing slug. |

## Measurement integrity

The drafting model competes for the GPU/VRAM. `draft_finding` refuses to run
while a measurement holds `/tmp/gos-measure.lock`, and the model is loaded with
Ollama's default keep-alive — the existing `llm.unload_all_loaded_models()` clears
VRAM before any measurement baseline, so the only requirement is "don't draft
*during* a measurement."

## Deliberately out of scope

- Auto-rewriting the public per-result card text (the rule-based f-strings in
  `video.py`/`llm.py`/`image_gen.py` remain the source of truth). Revisit only
  after this human-gated tool proves the guardrails hold.
- Fine-tuning / LoRA — no training corpus of result→analysis pairs exists, and
  fine-tuning teaches style, not the facts/guardrails that matter here.
- A larger model — would need the HF/Ollama caches moved off the system disk
  first (see memory `model_caches_on_system_disk`).
