# WattLab — Testing Strategy

*Rewritten 2026-06-11 to match reality: the automated tiers are now the pytest suite (1046 tests as of 2026-08-29 — the count drifts upward and the other docs must not quote it; `python3 -m pytest -q` from `wattlab_service/` is authoritative). The `scripts/smoke.sh` / `scripts/integration.sh` outlines this file used to carry were never written and have been deleted.*

## Philosophy

Three tiers, each with a clear time budget and a clear coverage scope. The goal is the **sweet spot** where tests get *run*, not avoided. A one-minute suite that runs before every push is worth more than a 30-minute suite that runs once a quarter.

We deliberately do **not** test:
- Real ffmpeg / LLM / image measurements — require GPU + minutes of wall time + actual heat. Validated by accumulated `results/*.json` history.
- Tapo P110 power readings — physical device, single point of failure. Hardware mock would be more code than the actual measurement layer.
- Cross-browser rendering / mobile layout pixels — needs Playwright/Selenium harness. Overkill for current audience.
- Network resilience / timeout edge cases — nginx + uvicorn defaults are sufficient for our load profile.

These are covered by Tier 3 manual checks before high-stakes use.

---

## Tier 1 — Full pytest suite (~1 minute)

**When:** Before every push. Run as a habit, not as a gate.
**Catches:** "I broke an import" · "an endpoint is 500-ing" · "JSON shape changed" · "a template token didn't get baked" · "the JS bundle has a syntax error."

```bash
cd wattlab_service && python3 -m pytest -q
# 1027 passed in ~57s (2026-08-19)
```

**Where it lives:** `wattlab_service/tests/` — 55 test files (~12,200 lines) plus `conftest.py`.

**Import-path note:** run pytest from inside `wattlab_service/` (or point it at `wattlab_service/tests/`). The suite's `tests/conftest.py` inserts `wattlab_service/` onto `sys.path` so tests can `import persist`, `import settings`, etc. Running bare `pytest` from the repo root collects nothing useful.

**What it covers** (by family — file names are descriptive):
- **Routes + access tiers** — `test_auth.py`, `test_audience.py`, `test_capabilities.py`, `test_queue_control.py`: FastAPI TestClient against the real app; sign-in flow, capability gating, queue actions.
- **Measurement-adjacent pure logic** — `test_confidence.py`, `test_cooldown.py`, `test_sensors.py`, `test_vmaf.py`, `test_encode_norm.py`: the CI confidence model, cooldown dispatch, sensor parsing — everything around the measurement that doesn't need hardware.
- **Result contract + persistence** — `test_result_envelope.py`, `test_persist_visitor_scope.py`, `test_persist_history.py`, `test_delete_result.py`: the mode→renderer contract (`docs/result_envelope.md`), CSV/JSON export shape, visitor scoping.
- **Decode rig + REM** — `test_rig.py`, `test_decode_run.py`, `test_routes_decode.py`, `test_decode_batch.py`, `test_origin.py`, `test_rem_prep.py`: rig state machine (plug/boot thresholds, auto-off), template → bench config materialisation (incl. the iso and net_* families), batch collation, Range-correct origin, REM file prep. The C2 wake (`rig.lg.wake`) is stubbed by an autouse fixture so the suite never wakes the household TV.
- **Factorisation guards** — `test_js_bundling.py`, `test_ui_config.py`, `test_gpu_ui_factorisation.py`, `test_page_model_defaults.py`: source-level guards that ban known regression classes (hardcoded cooldown labels, hardcoded GPU/encoder names, hardcoded model keys, JS syntax errors via `node --check`).

**⚠ Known gotcha — tests run as Lab tier.** pytest's TestClient connects from loopback, which the audience layer resolves to **Lab** (full access). Anonymous/Member behaviour — CR-026 visitor-scoping 404s, lock badges, gated uploads — never surfaces by default; any test of those paths must construct the tier explicitly, and any reasoning about "the tests pass so anonymous is fine" is wrong by construction. (This bit us in S37: a `/findings` 404 affecting every non-Lab visitor was invisible to a green suite.)

**Failure mode:** fix before pushing. The suite has been kept green after every commit since it existed; don't break that property.

---

## Tier 2 — Targeted deep runs (~seconds, on demand)

**When:** Before merging anything that touches `persist.py`, the result envelope, settings, or a measurement-adjacent module — run the relevant family with everything you changed in scope, plus any differential checks.
**Catches:** "Persistence shape drifted" · "a mode summarises differently than the renderer expects" · "a settings key fell out of sync."

```bash
cd wattlab_service
pytest tests/test_result_envelope.py tests/test_persist_visitor_scope.py   # result-contract work
pytest tests/ -k "cooldown or confidence"                                  # measurement-protocol work
pytest tests/ -k "js_bundling or ui_config"                                # template/JS work
```

The heavyweight differential check for envelope changes — re-summarising every stored result on disk and diffing (used to validate the S42 `_SUMMARISERS` dispatch against all 274 results: 0 diffs) — is a once-per-contract-change exercise, not part of routine. See `docs/result_envelope.md` for what counts as a contract change.

**Monkeypatch note (post-S42 refactor):** orchestration names live in the twelve `routes_*.py` modules, with compat aliases re-exported from `main`. When patching in tests, **patch the `routes_*` module that binds the name**, not `main` — patching the alias doesn't affect the binding the route actually calls.

---

## Tier 3 — Manual checklist (~5 minutes)

**When:** Before any demo, external feedback push, tagged release, or change that touches HTML/CSS/JS visibly.
**Catches:** "the UI looks broken" · "a flow is half-wired" · "mobile is unreadable."

### Pages render correctly (1 min)
- [ ] Open https://wattlab.greeningofstreaming.org on desktop **and** phone
- [ ] Owl + "WattLab ← Home" wordmark at top of every page (except the `/auth/*` flow)
- [ ] Sub-labels readable on phone (no `#555` ghost text)
- [ ] `/methodology` shows owl + GoS logo in topbar **and** the auth chip top-right (CR-021)
- [ ] `/queue-status` shows the owl wordmark via the shared chrome **and** the auth chip top-right
- [ ] Footer on every page shows the **Methodology →** link and the GitHub-issues link
- [ ] Anonymous tier: sign-in chip is the prominent CTA variant (filled accent background, ⚿ glyph, 0.85rem)
- [ ] Member/Lab: chip is the recessive status pill
- [ ] Browser console clean (Cmd+Opt+J on Chrome) — no JS errors

### Video flow (1.5 min)
- [ ] `/video` → Compare All Codecs → `meridian_120s` → Run
- [ ] Stage list advances correctly through 12 stages
- [ ] Matrix populates with all 6 cells (3 codecs × CPU/GPU)
- [ ] Confidence flags present (🟢/🟡)
- [ ] Most-efficient and fastest cells highlighted
- [ ] Download both CSV and JSON — both parse, CSV has `output_size_mb` column

### LLM flow (1 min)
- [ ] `/llm` → smallest model in the panel → T3 → Run
- [ ] Streaming output appears word-by-word
- [ ] mWh/token shown after completion
- [ ] Download CSV — has `response` column with full text (multi-line, properly quoted)

### RAG flow (1.5 min)
- [ ] `/rag` → green dot, "Index ready · N chunks"
- [ ] Click "Browse corpus documents" — list expands, shows ●/○ indicators per doc
- [ ] Question textarea pre-filled with "What is REM (Remote Energy Measurement)?"
- [ ] Run **Compare 3 modes** with the default model → progress shows "⏱ Cooling down" between modes
- [ ] No negative `mWh/tok` values in any mode (would indicate cooldown bug regression)
- [ ] Phi-4 single run → answer mentions GoS streaming workflows (encoder, origin, packager, telco)

### Guided Tour (2 min)
- [ ] `/demo` → step through Welcome → Findings (9 steps: … Decode is step 8)
- [ ] Welcome step: "→ Read the full measurement methodology" link below the two `<details>` blocks (CR-021 sibling)
- [ ] Each step's prev-runs panel populates from the `/demo/last/{type}` carve-out endpoint, not from visitor-scoped `/results/{type}/list`
- [ ] Run-button labels are explicit: "Run a standard transcode", "Run a standard LLM generation", "Run a standard image generation", "Run a standard RAG energy test" (each names model + duration)
- [ ] Click "Run a standard transcode" — accent banner under the stage list cycles **Side 1 of 2 — CPU encode → Cooldown — letting thermals settle before GPU → Side 2 of 2 — GPU encode**
- [ ] LLM result card shows the prompt as an italic blockquote at the top; carbon strip below the response preview
- [ ] Image result card shows the prompt and a carbon strip
- [ ] RAG progress: accent banner shows **Mode 1 of 3 — No retrieval (control) → Mode 2 of 3 — RAG (small corpus) → Mode 3 of 3 — RAG Large (full corpus)**
- [ ] RAG result card shows the question as an italic blockquote and a carbon strip with "best of 3 modes (X)" headline
- [ ] Findings step: video transcoding section is the visual headline (not a row in a table)
- [ ] LLM / Image / RAG sections appear as collapsible `<details>` blocks below
- [ ] All numbers populate (no "—" placeholders for workloads that ran)

### CR-026 anonymous-tier integrity (1 min)
- [ ] Anonymous: `/` → 302 redirect to `/demo` (not the work nav grid)
- [ ] Anonymous: `/video` upload form shows "Members only" lock badge + disabled file input
- [ ] Anonymous: `POST /video/upload` returns 403 (curl-test, no cookie)
- [ ] Anonymous: `GET /results/{type}/{other-job-id}/download.json` returns 404 (must not leak)
- [ ] Member sign-in via magic link: chip turns into `<email> · Sign out` form; upload unlocks; own-jobs visible in prev-runs panels

---

## Pre-release additions

For tagged releases (`v1.x.y`):
- [ ] Run Tier 1, 2, 3 in order
- [ ] Variance calibration (`/settings → Run variance calibration`) — completes 🟢
- [ ] `df -h /srv/data` — > 10 GB free for next month of results
- [ ] `git status` clean (or only intentional untracked)
- [ ] `JOURNAL.md`, `CLAUDE.md`, `README.md` updated

---

## When to relax this

| Change | Run |
|---|---|
| Typo, comment, doc-only | Tier 1 |
| CSS-only / colour palette / spacing | Tier 1 + visual spot-check on `/`, `/video`, `/rag` |
| Logic change in a single module | Tier 1 + Tier 2 (relevant family) |
| Schema / persistence / endpoint shape | Tier 1 + Tier 2 |
| Anything HTML / JS visible | Tier 1 + relevant Tier 3 flow |
| Pre-demo / pre-feedback-push / pre-release | All three tiers |

---

## What this strategy is NOT

- **Not a CI gate.** Nothing here runs in GitHub Actions. WattLab is single-server, single-maintainer; CI overhead would slow us more than it'd help. If we ever onboard a contributor, that's the trigger to wire Tier 1 into a pre-push hook.
- **Not exhaustive.** We test plumbing, not measurements. Measurement correctness is validated by accumulated runs in `results/*.json` and by the variance calibration framework.
- **Not static.** When a bug bites in production, add a test that would have caught it (the factorisation-guard family exists exactly this way). When a Tier 3 step never finds anything for six months, delete it.
