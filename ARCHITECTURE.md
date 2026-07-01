# OWL — Architecture

One- to two-page orientation for humans and AI agents. **Current state (post
2026-06 refactor, Phases 0–4 complete).**
Deeper context: `docs/architecture_review_2026-06.md` (the refactor plan, now
executed), `docs/result_envelope.md` (the result-shape contract),
`AUDIT_BRIEF.md` / `AUDIT_RESPONSE.md` (2026-05 access-spine audit),
`WATTLAB_SPEC.md` (product).

## What OWL is

A FastAPI service on GoS1 that runs streaming/AI workloads (video transcode,
LLM inference, image generation, RAG) while measuring wall power (Tapo P110)
and thermals, and publishes per-run energy results with statistical
confidence. Single process, single worker, one job at a time (measurement
integrity demands exclusive hardware access).

## Module map (`wattlab_service/`)

| Layer | Modules | Notes |
|---|---|---|
| **App assembly** | `main.py` (~430 lines) | FastAPI app, middleware, capability-gate exception handler, startup (queue worker + pollers), home page, `/live` `/power` `/carbon`, `/ui-config.js`, `/queue`(+`-status`), cooldown-decision. Nothing feature-shaped lives here. |
| **Feature routes** | `routes_video.py`, `routes_llm.py`, `routes_rag.py`, `routes_image.py`, `routes_enhance.py`, `routes_benchmark.py`, `routes_budget.py`, `routes_findings.py`, `routes_finding_draft.py`, `routes_results.py`, `routes_settings.py`, `routes_demo.py`, `routes_methodology.py`, `routes_auth.py` | One flat module per feature, each an `APIRouter`: its routes + page template + `run_*_job` orchestration. **Never import `main`.** `main.py` keeps a commented alias block (benchmark.py + tests reach `run_job`, `run_llm_compare_models_job`, … through it). `routes_budget.py` = `/video/budget` calculator + `/video/budget/reconfigure` (Lab re-cal). `routes_finding_draft.py` = Lab-only `/findings/draft` LLM-assisted finding drafter (`CREATE_FINDING`). |
| **Finding drafter** | `finding_draft.py` | ⚠ **OWL's only non-measurement LLM use** — everywhere else models are measurement *targets*. Drafts a `docs/findings/<slug>.md` from cited results for human review (gpt-oss:20b via Ollama). Deterministic code derives confidence/scope/signals; the LLM only verbalises. Guardrails (`validate_draft`): GoS bandwidth→network-energy ban, confidence/scope honesty, number-consistency, schema. Refuses to run while `/tmp/gos-measure.lock` is held (GPU contention). `save_draft` is the only disk write — it re-validates and round-trips through `findings.load`. |
| **Shared runtime** | `runtime.py` | The `jobs` dict (mutated in place, never reassigned), the live power/sensors cache + pollers, `job_status()`. |
| **Page chrome + UI copy** | `ui.py` | `render_page()` (the single page shell: doctype, title, auth chip + back link, footer, design tokens, bundle tags), lock badges, external-URL registry, serve-time wording config (`_ui_cfg`/`_bake_durations`), CR-037 AI framing bands, CR-060 GPU UI-copy helpers, `_model_date_line`. |
| **Static JS bundles** | `static/wl-*.js` | Real files (lintable, cacheable, `?v=<sha>`): `wl-live`, `wl-carbon`, `wl-progress`, `wl-result`, `wl-bench-hydrate`, `wl-charts`. Settings/meter copy reaches them per request via `/ui-config.js` → `window.WL_CFG` — **no import-time baking, no restart-coupled copy.** |
| **Access spine** | `audience.py`, `capabilities.py`, `queue_control.py` | `audience.tier(request)` → Anonymous/Member/Lab. `capabilities._REQUIRED_TIER` **is** the security policy; routes declare capabilities via `Depends(requires(CAP))`, never tiers. `queue_control` is the single enqueue path + worker. |
| **Auth** | `auth.py`, `email_send.py` (+ `routes_auth.py`) | CR-001 magic-link sign-in (allowlist `data/members.json`), Gmail SMTP. |
| **Measurement** | `video.py`, `llm.py`, `image_gen.py`, `rag.py`, `pixop.py`, `benchmark.py`, `parity.py` | One per workload. Byte-stable through the whole refactor (energy-imperceptibility rule). `parity.py` = the re-runnable encode-parity / energy-quality calibration harness (codec × CPU/GPU × bitrate × clip, reusing `video.run_single`-style measurement + terminal VMAF; writes a fingerprinted artifact under `results/calibration/`). |
| **Budget data** | `budget_data.py` | Shapes the latest measured `parity.py` artifact into the `/video/budget` recipe table (VMAF-vs-bitrate interpolation, 5-rung ABR-ladder sums); falls back to the illustrative fixture when no complete artifact exists. |
| **Instrumentation** | `power.py`, `gpu.py` | `power._read_meter_watts()` is the **only** wall-power read path (`get_power_watts()` = primary meter; CR-065 dual-meter sampling via `power.sample_baseline`/`sample_task`, cached per-meter KLAP handles — sessions are exclusive per device, never poll a registered plug out-of-band); `power.cooldown_between_runs` the only inter-run cooldown path. GPU telemetry + naming via `gpu.BACKEND` (CR-060). The planned PDU/meter swap mirrors this as `power.BACKEND` (CR-031 §2). |
| **Analysis** | `confidence.py`, `carbon.py`, `canonical.py`, `curated.py` | Shared CI/traffic-light model; CO₂e context (reference-only). |
| **Storage** | `persist.py`, `settings.py`, `sources.py`, `model_catalog.py`, `corpus_manifest.py`, `findings.py`, `reproduce.py` | Flat-file JSON under `results/`. `persist._SUMMARISERS` is the mode→summariser dispatch (see result envelope). `settings.json` is **live state** — never include it in feature commits. LLM `MODELS` dicts are live views — never edit as literals. |
| **Meta** | `version.py` | Build stamp at process start; `-local` suffix = dirty tree at launch. |

Tests: `wattlab_service/tests/` (pytest; TestClient runs as **Lab tier** —
reason about Anonymous/Member explicitly. Note: Python ≥3.12.4 counts
TEST-NET ranges like 203.0.113.x as `is_private` → Lab; probe tiers with a
genuinely public IP like 8.8.8.8).

## Request flow

```
request → maintenance middleware → route handler (routes_<feature>.py)
            └ Depends(requires(CAPABILITY)) → audience.tier() → 403 gate page if below tier
          page GET  → handler builds body, ui.render_page() adds the shell
                      (chrome-less exceptions: /findings, /methodology, auth/gate, asset-404)
          job POST  → queue_control.enqueue(run_*_job, page=…) → runtime.jobs[job_id]
                       → queue worker (queue_control) runs one job at a time
```

## Job / measurement flow

```
run_*_job (routes_<feature>.py)          ← orchestration: stages, cooldowns, jobs[] updates
  └ measurement module (video.py, …)     ← focus mode → baseline (10×1s) → task → polls
      └ power.get_power_watts() @1s + power.read_sensors_dict()
  └ confidence.confidence(...)           ← 🟢/🟡/🔴 per-run CI flag
  └ carbon enrichment (reference-only)
  └ persist.save(...) → results/{type}/{date}_{job_id}.json
front-end polls /…/job/{id} → stage strip → result card (wlRender* in wl-result.js)
```

Inter-run cooldowns: **only** via `power.cooldown_between_runs` (fixed vs
wait-for-idle toggle); wording via `ui._bake_durations` tokens / `WL_CFG`;
footer via `wlCooldownSummary` (accepts both stamp shapes — see envelope doc).
All single-sourced and test-guarded — keep them that way.

## The result-shape contract (Phase 4)

`docs/result_envelope.md` catalogues every `job_type × mode`, its shape, and
its consumers. **Adding a mode = registering it in `persist._SUMMARISERS`,
the type's `wlRender*Card`, and that doc.** Unregistered modes are loud:
`"unrecognised_mode"` on summaries, `_wlBadRecord()` on cards.

## Known weaknesses (accepted)

1. `jobs` dict is free-form; status/stage are unvalidated strings (formal
   `JobRecord` = remaining Phase-4 item, fix when next touched).
2. Cooldown stamp-key variants on disk (`cooldowns` list vs `cooldown` dict) —
   renderer tolerates both; unify writers next time measurement modules are
   edited for a measurement reason.
3. Flat-file persistence won't scale past the next growth spurt (CR-031 §1
   decision pending — don't extend `persist.py` before it's made).
4. Only a minority of test files exercise routes via TestClient, all as Lab.

## Still open (separate tracks)

- **PowerBackend protocol (CR-031 §2)** — `power.BACKEND` mirroring
  `gpu.BACKEND`; schedule when a PDU candidate is concrete.
- **Containerisation (CR-031 §3)** — the host couplings are now visible in
  one place each: focus-mode sudoers (measurement modules), `sensors -j`
  (power.py), `/tmp/gos-measure.lock`, `settings.json` + `results/` volumes.

**Conventions to hold:** policy lives in `capabilities.py` (docs mirror it,
never fork it); truth in code over docs; tests green at every merge;
measurement modules byte-identical unless the change *is* a measurement
change; rollback anchor: tag `v0.8.7` (pre-refactor).
