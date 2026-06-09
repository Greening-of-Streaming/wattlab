# OWL — Architecture

One- to two-page orientation for humans and AI agents. **Current state + target state.**
Deeper context: `docs/architecture_review_2026-06.md` (the active refactor plan),
`AUDIT_BRIEF.md` / `AUDIT_RESPONSE.md` (2026-05 access-spine audit), `WATTLAB_SPEC.md` (product).

## What OWL is

A FastAPI service on GoS1 that runs streaming/AI workloads (video transcode, LLM inference,
image generation, RAG) while measuring wall power (Tapo P110) and thermals, and publishes
per-run energy results with statistical confidence. Single process, single worker, one
job at a time (measurement integrity demands exclusive hardware access).

## Module map (`wattlab_service/`)

| Layer | Modules | Notes |
|---|---|---|
| **App / routes / UI** | `main.py` (~13k lines) | Routing, all HTML/JS/CSS templates, page handlers, job orchestration (`run_*_job`), queue worker. **The refactor target** — shrinking toward app assembly only. |
| **Access spine** | `audience.py`, `capabilities.py`, `queue_control.py` | `audience.tier(request)` → Anonymous/Member/Lab. `capabilities._REQUIRED_TIER` **is** the security policy; routes declare capabilities via `Depends(requires(CAP))`, never tiers. `queue_control` is the single enqueue path (capability + lock + caps). |
| **Auth** | `auth.py`, `email_send.py` | CR-001 magic-link sign-in (allowlist `data/members.json`), Gmail SMTP. |
| **Measurement** | `video.py`, `llm.py`, `image_gen.py`, `rag.py`, `pixop.py`, `benchmark.py` | One per workload. Byte-stable during refactors (energy-imperceptibility rule: pure-software moves don't confound measurements, but these files changing would force re-verification). |
| **Instrumentation** | `power.py`, `gpu.py` | `power.get_power_watts()` is the **only** wall-power read path; `power.stamp()`/`meter_display_name()` carry meter identity; `power.cooldown_between_runs` is the only inter-run cooldown path. GPU telemetry + encoder/runtime naming go through `gpu.BACKEND` (vendor abstraction, CR-060 — survived the AMD→Nvidia swap with zero call-site edits). The planned PDU/meter swap mirrors this pattern as `power.BACKEND` (CR-031 §2). |
| **Analysis** | `confidence.py`, `carbon.py`, `canonical.py`, `curated.py` | Shared CI/traffic-light model; CO₂e context (reference-only — GoS stands behind energy, not carbon). |
| **Storage** | `persist.py`, `settings.py`, `sources.py`, `model_catalog.py`, `corpus_manifest.py`, `findings.py`, `reproduce.py` | Flat-file JSON under `results/` (symlink → `/srv/data/owl/`). `settings.json` is **live state** — never include it in feature commits. `model_catalog` makes LLM `MODELS` dicts live views — never edit them as literals. |
| **Meta** | `version.py` | Build stamp resolved at process start; `-local` suffix = dirty tree at launch. |

Static assets: `wattlab_service/static/` (`wl-charts.js` is the precedent for real JS files).
Tests: `wattlab_service/tests/` (pytest; TestClient runs as **Lab tier** — anonymous/member
scoping bugs don't surface there; reason about tiers explicitly).

## Request flow

```
request → maintenance middleware → route handler
            └ Depends(requires(CAPABILITY)) → audience.tier() → 403 gate page if below tier
          page GET  → handler builds HTML from module-level template constants (f-string/.replace)
          job POST  → queue_control.enqueue(run_*_job, page=…) → jobs[job_id] dict
                       → queue worker (main.py) runs one job at a time
```

## Job / measurement flow

```
run_*_job (main.py)                      ← orchestration: stages, cooldowns, jobs[] updates
  └ measurement module (video.py, …)     ← focus mode → baseline (10×1s) → task → polls
      └ power.get_power_watts() @1s + power.read_sensors_dict()
  └ confidence.confidence(...)           ← 🟢/🟡/🔴 per-run CI flag
  └ carbon enrichment (reference-only)
  └ persist.save(...) → results/{type}/{date}_{job_id}.json   (stamps version, gpu_hardware,
                                                               power_hardware, raw samples)
front-end polls /…/job/{id} → stage strip (WL_*_STAGES) → result card (wlRender* JS)
```

Inter-run cooldowns: **only** via `power.cooldown_between_runs` (fixed vs wait-for-idle
toggle); wording via `_bake_durations` tokens; footer via `wlCooldownSummary`. All three
are single-sourced and test-guarded — keep them that way.

## Known weaknesses (accepted, being addressed — see the review doc)

1. `main.py` holds 60% of the code; ~half of it is HTML/JS/CSS inside Python strings.
2. JS in strings → no lint; shared constants (`_RESULT_JS`, `_CARBON_JS`) couple all pages.
3. Template tokens baked at **import time** → copy/settings changes need a service restart.
4. No result-shape schema: each mode (`single`, `all_codecs`, `compare_models`, …) is known
   only to its consumers (renderers, `persist._summarise`, CSV rows, demo pre-load).
5. `jobs` dict is free-form; status/stage are unvalidated strings.
6. Flat-file persistence won't scale past the next growth spurt (CR-031 §1 decision pending —
   don't extend `persist.py` before it's made).

## Target state (2026-06 refactor, phased — `docs/architecture_review_2026-06.md`)

- **Phase 1:** big JS constants → `static/*.js`; import-time baking → per-request `window.WL_CFG`.
- **Phase 2:** one `ui.py` `render_page()` page shell (today: 19 hand-rolled DOCTYPE shells).
- **Phase 3:** one flat route module per feature (`APIRouter`), one feature per session
  (enhance-run → benchmark → findings → image → rag → llm → video); `main.py` < 1,500 lines
  (app assembly, middleware, queue worker, home).
- **Phase 4:** documented result envelope + `mode → renderer` dispatch; small `JobRecord`.
- **Parallel:** `power.BACKEND` protocol (CR-031 §2) when a PDU candidate is concrete.
- **Non-goals:** no template engine, no DB inside this refactor, no edits to measurement
  modules, no deep `features/` tree, no big-bang commits.

**Conventions to hold:** policy lives in `capabilities.py` (docs mirror it, never fork it);
truth in code over docs; every phase lands with tests green + the `AUDIT_RESPONSE.md` smoke
checklist; rollback anchor: tag `v0.8.7`.
