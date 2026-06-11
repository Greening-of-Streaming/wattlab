# OWL Architecture Review — 2026-06-10

**Status (2026-06-11):** executed — Phases 0–4 shipped S41–S42; the parallel PowerBackend track (CR-031 §2) remains open. Kept as the rationale record.
**Inputs:** four observations from a previous external architecture review, evaluated against measured codebase data.
**Companions:** `AUDIT_BRIEF.md` + `AUDIT_RESPONSE.md` (2026-05-01 access-spine audit), `CHANGE_REQUESTS.md` CR-031 (deployment portability).

---

## Data gathered (2026-06-09)

- `main.py` is **13,275 lines — 60% of the 22,309-line service**. Next largest module: `video.py` at 1,319.
- **112 of 191 commits since March (59%) touch `main.py`** (next: `video.py`, 27).
- At the 2026-05-01 audit `main.py` was ~5,800 lines. It **more than doubled in five weeks**, while the three spine modules that audit introduced (`audience.py` 75, `capabilities.py` 182, `queue_control.py` 241) total 498 lines.
- Roughly **half of `main.py` is not Python**: ~3,700 lines in multi-line string templates plus ~2,000 HTML-ish f-string lines, ~700 CSS-ish, ~570 JS-ish. 19 separate `<!DOCTYPE html>` page shells; 34 module-level template constants.
- Page handlers: `video_page` ~960 lines, `rag_page` ~850, `llm_page` ~770, `image_page` ~650, `settings_page` ~520, `_DEMO_HTML` ~1,330, `_CARBON_JS` ~1,030, `_RESULT_JS` ~770.
- All job orchestration (`run_job`, `run_llm_job`, `run_llm_compare_models_job`, `run_rag_compare_job`, `run_enhance_job`, …) lives in `main.py`, not the feature modules.
- Mode special-casing: 23 per-mode branches in `persist.py`, ~41 mode references in `main.py`, 9 mode branches inside `_RESULT_JS` alone.
- Tests: 34 files / ~5,600 lines, but only 9 exercise routes via TestClient (all as Lab tier).

---

## Observation 1 — "main.py is the new gravity well": TRUE, and worse than stated

The numbers confirm it; the trend is the damning part. The access-spine refactor succeeded at its own goal (policy single-sourcing) yet **did nothing to bend the growth curve** — every feature since (compare pages S31, findings S32, benchmark S35/36, enhance-run S40, demo tour) accreted routes, HTML, JS, *and* orchestration into `main.py`.

Why this specifically increases fragility (evidence from session history):

1. **JS in Python strings** — no lint, no highlighting, brace-escaping hazards. The S38 `ReferenceError` (cooldown helpers missing from `_CARBON_JS`) is a direct symptom: `_CARBON_JS` is defined at line ~718 and *re-assigned* at ~1750 by string concatenation. `test_js_bundling.py` — a test that greps source strings — exists *because* there is no module boundary to test. Guard tests pinning string content are compensating for missing code boundaries.
2. **Import-time baking** — `_PROGRESS_JS = _bake_durations(_PROGRESS_JS)` runs at import. This is why S39's label fix "needed a service restart" and why the running service can silently disagree with code on disk and with the test suite.
3. **Shared string constants are a hidden dependency graph** — `_RESULT_JS` carries every feature's renderers into every page. S39 bug 2 (`wlRenderImageCard` dropping `model_errors` while `wlRenderComparePanel` surfaced them) is two renderers in one constant drifting with nothing forcing parity.
4. **Regressions cluster here** — S37 (both demo-tour bugs), S38 (bundling), S39 (all three image-compare bugs) were all in `main.py`'s embedded presentation layer; none in `video.py`/`llm.py`/`power.py`. There is also a pure AI-agent cost: every small change means navigating a 13k-line file.

## Observation 2 — "the next problem is blast radius": AGREE, with sharpening

Access control is solved; `capabilities.py` is the best module in the codebase (one policy table, routes declare capabilities, tier moves are one-row edits, test-guarded).

But "responsibilities not sufficiently isolated" is too vague to act on. The blast radius is **not uniform** — it concentrates in two couplings:

**(a) Result-shape ↔ renderer fan-out.** Each result mode (`single`, `both`, `all_codecs`, `batch`, `all`, `all_both`, `rag`, `rag_compare`, `compare_models`, `codecs_single`, …) is consumed by ≥7 surfaces: fresh-result JS card, previous-runs expansion, `/demo` pre-load, `persist._summarise`, CSV rows, findings embeds, benchmark views. No schema exists (2026-05-01 hot zone #9 — still fully open). S37 bug 1 was exactly this: `/demo/last` fed `compare_models` records into the single-run renderer.

**(b) Duplicated page scaffolding.** 19 hand-rolled page shells assembled via `.replace("{TOKEN}", …)` chains. Chrome changes fan out to up to 19 sites; a missed token fails silently.

Sharpened diagnosis: **the bottleneck is the presentation layer — untyped result shapes consumed by string-assembled renderers.**

## Observation 3 — "feature boundaries first-class (`features/` tree)": right direction, wrong first move, over-specified

Per-feature route modules are the correct end-state (FastAPI `APIRouter`; an agent fixing an image bug should load ~800 lines, not 13k). Three disagreements with the proposal as written:

1. **As the first move it relocates the problem.** Splitting now moves embedded HTML/JS mud into six smaller piles; the S37/38/39 regression class survives untouched because it lives in the string-assembly mechanism, not file placement. The split is also *risky because of* that mechanism — shared constants and `.replace()` chains are exactly what break when code moves (S38 was caused by constant-bundling reorganisation). Extract the front-end first; the split then becomes mechanical.
2. **The proposed shape is over-engineered at 22k lines.** `features/video/{routes,rendering,orchestration}` (3–4 files per feature) is astronautics. One module per feature (~800–1,500 lines) is enough. The measurement modules (`video.py`, `llm.py`, `image_gen.py`, `rag.py`) are already well-factored — leave them byte-identical (which also makes the "software abstraction is energy-imperceptible" rule trivially auditable: no re-baselining needed).
3. **Incremental, never big-bang.** One feature per session, newest/least-entangled first: enhance-run → benchmark → findings → image → rag → llm → video.

## Observation 4 — "extract rendering before deeper refactors": AGREE — highest-leverage move

This was the 2026-05-01 audit's own post-CR-001 recommendation ("moving JS to static files and extracting result-card rendering helpers") — never executed; five weeks later the presentation layer doubled and produced essentially all recent regressions. Supporting facts:

- Recent and upcoming CRs are presentation-heavy (CR-057 home repositioning, CR-004 graphing, CR-043 previews, CR-045 toggle).
- A working precedent exists: `static/wl-charts.js` served as a real asset, no bundling pain.
- Extraction converts the guard-test burden into ordinary file boundaries.

Refinement: extraction must include **killing import-time baking** — replace baked tokens (`{COOLDOWN_PAREN}`, `{METER_NAME}`, …) with per-request `window.WL_CFG = {…}` injection. Values stay single-sourced (settings / `_bake_durations` logic); only the binding time changes from import to serve. This ends restart-coupled copy and test-vs-live divergence.

**Recommend against Jinja2 / any template engine** — not a framework migration per se, but it would force re-escaping every brace in ~6,000 template lines for zero blast-radius benefit. Keep f-strings/`.replace`; relocate and unify them.

---

## Risks the previous review missed

1. **No result-shape contract** — the actual blast-radius engine (see Obs. 2a). Minimal fix: one documented canonical result envelope + `mode → renderer` dispatch tables (JS side and `persist._summarise`). Not full Pydantic.
2. **Import-time module state generally** — settings read at import, baked constants, `_CARBON_JS` self-reassignment. "Restart needed" in session notes is an architecture property, not an ops chore. (Also a container blocker — see alignment section.)
3. **`jobs` dict is free-form** (2026-05-01 hot zone #6, unaddressed): status/stage overloaded strings mutated from many sites; the S39 audit found the cooldown stamp-key already inconsistent (`cooldowns` list vs `cooldown` dict). Lower priority; fix when touched.
4. **Test blind spots are structural** — only 9/34 test files exercise routes, all as Lab tier; the rest of the main.py surface is protected by string-grep guards. Every refactor phase needs the `AUDIT_RESPONSE.md` manual smoke checklist until extraction enables real unit tests.
5. **Sequencing hazard: in-flight work** — `feature/cr-063-pixop-enhance-run` plus shared-tree Pixop/FLUX WIP must land before any main.py refactor, or rebase pain will be severe. Hard ordering constraint.
6. **Hygiene that misleads agents** — `main.py.bak`, `main.py.session15`, `main.py.session15b`, `persist.py.session15b` checked in; they pollute greps. `ARCHITECTURE.md` (prescribed 2026-05-01) was never written.
7. **Don't extend `persist.py` during this work** — flat-file blocker / CR-031 §1 DB decision is a separate axis.

## Agree / disagree summary

| Observation | Verdict |
|---|---|
| 1 — main.py gravity well | **Agree** — 60% of code, 59% of commits, 2× growth in 5 weeks |
| 2 — blast radius is the risk | **Agree, sharpened** — result-shape↔renderer coupling + duplicated scaffolding |
| 3 — `features/` first-class | **Direction yes; as proposed no** — wrong order, over-deep, must be incremental |
| 4 — rendering extraction first | **Agree, strongest recommendation** — plus kill import-time baking |

---

## Containerisation & power-backend alignment (CR-031)

Mid-term priority (owner-flagged 2026-06-10, will become critical): containerise OWL and support non-P110 meters (PDUs with their own APIs). Assessment of how this plan relates:

**The power-meter swap is already architecturally cheap and is NOT blocked (or helped much) by this refactor — by design.** The metering surface is one module: every consumer reads watts through `power.get_power_watts()` (the only read path — `rag/llm/video/image_gen/main` all import it from `power`), and meter identity through `power.stamp()` / `meter_display_name()` (shipped as CR-031 §2 cheap-wins, 2026-06-09). Cooldown/thermal-floor logic consumes watts and is meter-agnostic. The PDU move is therefore: introduce `power.BACKEND` mirroring the proven `gpu.BACKEND` pattern (CR-060 — zero call-site edits at the GPU swap), with `TapoBackend` as first implementation and `METER_KIND`/`METER_RESOLUTION_S` already scaffolded for resolution-aware confidence. It touches `power.py` + tests, not `main.py` — **it can run as a parallel track at any time without conflicting with Phases 0–4.**

Where this plan *does* advance containerisation directly:

- **Phase 1 kills import-time config binding** — baked-at-import constants are an anti-pattern in containers (config must be injectable at runtime; restart-coupled copy breaks the image-immutable model). Serve-time `WL_CFG` is the 12-factor-compatible shape.
- **Phase 3 shrinks main.py to app assembly**, making the *real* container blockers visible and isolatable in one place: focus-mode sudoers + host systemd timers (become host-concern/no-op in a container), `sensors -j` subprocess (host hwmon access), `/tmp/gos-measure.lock`, GPU device passthrough, `settings.json` + `results/` as volume mounts. None of these get worse under this plan; today they're scattered through 13k lines.
- **Nothing in Phases 0–4 deepens P110 or host coupling.** Measurement modules stay byte-identical; the power surface stays one module.

Suggested amendment adopted below: **CR-031 §2 (PowerBackend protocol) is listed as an independent parallel track**, not folded into a phase — it should mirror `gpu.py` and can land whenever a PDU candidate is concrete.

---

## Roadmap

Each phase independently shippable; all tests green between phases; `AUDIT_RESPONSE.md` smoke checklist at each merge; measurement modules byte-identical throughout (no energy re-baselining per the imperceptibility rule).

| Phase | Scope | Effort | Risk |
|---|---|---|---|
| **0 — Preconditions & hygiene** | Land/merge CR-063 branch; delete `.bak`/`.session15*` files; write 1–2 page `ARCHITECTURE.md` (current + target state) | ~0.5 day | none |
| **1 — Front-end extraction** | `_CARBON_JS`, `_RESULT_JS`, `_PROGRESS_JS`, `_LIVE_JS`, `_BENCH_HYDRATE_JS` + big per-page `<script>` blocks → `static/*.js` (precedent: `wl-charts.js`). Replace `_bake_durations` import-time baking with per-request `window.WL_CFG`. Golden-page test (old vs new rendered HTML) during transition; existing guard tests pin the critical strings. **Eliminates the S37/38/39 regression class.** | 2–3 days | medium, well-mitigated |
| **2 — Page shell unification** | `ui.py` with `render_page(request, title, body, scripts=[])` owning DOCTYPE, `_BASE_STYLES`, header/auth chip, footer, queue badge, lock badges. Collapse 19 shells + `.replace()` chains. | 1–2 days | low |
| **3 — Per-feature route modules** | `APIRouter` per feature, one flat module each, one feature per session: enhance-run → benchmark → findings → image → rag → llm → video → settings/demo/methodology. Each takes its routes + `run_*_job` orchestration + page template. `main.py` → app assembly, middleware, queue worker, home; target <1,500 lines. | 3–5 days (spread) | low after 1–2 |
| **4 — Result-render contract** | Canonical result envelope documented once; `mode → renderer` dispatch (JS + `persist._summarise`); loud missing-mode failure; small `JobRecord` shape; unify cooldown stamp-key. Opportunistic/piecemeal. | 2–3 days | low |
| **∥ — PowerBackend protocol (CR-031 §2)** | `power.BACKEND` mirroring `gpu.BACKEND`; `TapoBackend` first impl; resolution-aware confidence via `METER_RESOLUTION_S`. Independent of Phases 0–4; schedule when a PDU candidate is concrete. | 1–2 days | low |

**Explicit non-goals:** no Jinja2/template engine; no database (CR-031 §1 decides separately); no edits to `video.py`/`llm.py`/`image_gen.py`/`rag.py`/`power.py` measurement paths within Phases 0–4; no `features/` deep tree; no big-bang commit.

**Total: ~8–13 days across sessions**, front-loaded so the highest-regression surface (embedded JS) is fixed first, and stopping after any phase leaves the codebase strictly better.
