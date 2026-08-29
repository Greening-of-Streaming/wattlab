---
name: finding-draft
description: Draft or import a finding into docs/findings/ — build the frontmatter against the findings.py schema, pull every number from the cited stored result JSON (canonical source), apply the GoS framing guardrails (regime, scope, traffic-light honesty, energy-not-CO2e), and validate before showing. Use when the user asks to "write a finding", "draft a finding", "catalogue this result", or types /finding-draft.
argument-hint: [slug or the result id(s) to write up]
---

# Draft a finding (WattLab / OWL)

Findings are editorial markdown at `docs/findings/<slug>.md`, validated on load by
`wattlab_service/findings.py`. Seed from the user: $ARGUMENTS

**Draft, validate, show for approval. Findings are public-facing GoS claims — never write one straight to disk and move on.**

## 1. Canonical source first

- Resolve each `source_result_id` (`<type>/<token>`, e.g. `decode/dec0de04`) to its file under
  `results/<type>/` and **read the stored JSON**. Every number in the finding comes from there.
- If CLAUDE.md/JOURNAL prose disagrees with the result file, the file wins; note the discrepancy
  in `caveats`. Never fudge n (an n=1 is written as n=1).
- The loader **raises if a cited result doesn't exist on disk** — check before drafting.

## 2. Frontmatter — exact schema (`findings.py:_REQUIRED_FIELDS`)

Required: `slug` (must match filename, `^[a-z0-9][a-z0-9-]{0,80}$`), `version` (int),
`first_measured`, `last_refined` (YYYY-MM-DD), `headline`, `claim_short`, `confidence`
(`green|yellow|red` — from the source result's traffic light, not optimism), `scope`,
`methodology_ref` (usually `docs/wattlab_traffic_light_confidence.md`), `source_result_ids` (list).
Optional: `related_findings`, `supersedes`, `tags`, `caveats`.

There are **no** `impact`/`review_status` schema fields — DRAFT status is a `draft` tag plus a
`"DRAFT pending lab review. …"` first caveat. Impact is an editorial gate, not a field:
score 0–3 on actionability; **0 = park it, don't publish**.

## 3. Body — house sections (match recent findings)

`# The result, in one sentence` · `# Why this matters` · `# How it was measured` ·
`# What this finding does not measure`. Same voice and depth as
`hw-decoder-cuts-client-energy-4x.md`.

## 4. GoS framing guardrails (all must hold)

- If it can't be measured, it isn't asserted. Conjectures go in the report doc, not the claim.
- **State the regime** — e.g. sw codec ordering inverts between realtime and saturated; any
  claim that flips with load conditions must name its regime in `claim_short` or `scope`.
- Scope statement separates layers explicitly ("Device layer only … Network, CDN excluded").
- Energy (W/Wh) is the result; CO₂e is reference-only context — keep it out of claims.
- Caveats carry every known limit (single board, one rung, n, display path excluded, …).
- **Startup-skip asymmetry is not comparable across devices** (found 2026-08-29, Roku onboarding):
  `startup_skip_s` exists to exclude the launch/buffering transient from steady-state ΔW, but
  devices needing real UI navigation before playback starts (e.g. Roku's menu select) skip
  proportionally more real time than a near-instant launch (e.g. Android's VIEW intent). Sustained
  ΔW claims are unaffected by this — but never quote "time to first frame," startup energy cost, or
  any latency figure across devices without naming this asymmetry explicitly; see CR-077.

## 5. Validate, cross-link, register

- Validate: `cd wattlab_service && python3 -c "import findings; print(findings.load('<slug>'))"` —
  must return a Finding, not raise. Then `pytest tests/ -k findings`.
- Add reciprocal `related_findings` links in the existing findings it touches.
- Add the slug to the **Key Findings** list in `CLAUDE.md` (slug + emoji only — no prose restating
  the claim; prose drifts).
- Commit the finding file by name. `/findings` picks it up without a restart (mtime-cached loader).
