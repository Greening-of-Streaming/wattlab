# WattLab — Claude Code Context File
# Auto-loaded by Claude Code. Keep this current.
# Last updated: 2026-05-12 (Session 24 — GoS1 4TB data disk added; OWL bulk/archival data moved to /srv/data)
# Public name: OWL (Online WattLab). "WattLab" is the legacy/internal/repo name.
# See also: GOS1_INFRA.md — server infrastructure, Nextcloud backup, personal stack context
# See also: TESTING.md — three-tier testing strategy
# See also: CHANGE_REQUESTS.md — active CRs only (20 entries after the 2026-05-12 close-out sweep). Tracks: A storage/persistence (CR-012 + CR-031 storage section + downstream CR-003 / CR-007), B confidence model (CR-028 Phase 2 — Tania reply pending), C widget extensions (CR-024, CR-035, deferred resume-job), D result rendering / framing (CR-037 AI tethering — biggest open framing item — + CR-027 tier copy; the rest of this track shipped), E small polish (CR-005), F strategic / exploratory (CR-008, CR-009, CR-018 T2/T3, CR-025, CR-029, CR-033, CR-039 quality judge, CR-041 chip-age), G member trust (CR-040 reproducibility kit). See "Groupings & dependencies" appendix at end of CHANGE_REQUESTS.md for the full dependency map.
# See also: CHANGE_REQUESTS_CLOSED.md — shipped CRs archive (CR-001, CR-001b, CR-002, CR-006, CR-010, CR-011, CR-014, CR-015, CR-016, CR-017, CR-019, CR-020, CR-021, CR-022, CR-023, CR-026, CR-030, CR-032, CR-034, CR-036, CR-038, CR-042). Each entry preserves the original problem statement and direction; Status line names the closing commit. (CR-032 / CR-034 / CR-036 / CR-038 closed in the 2026-05-12 sweep.)
# See also: docs/wattlab_traffic_light_confidence.md — Tania's §9 statistical framework for the confidence flag (CR-028 Phase 2 spec). docs/wattlab_parameters_audit.md — every settings parameter classified Arbitrary / Empirical / Calibrated / Constrained, with paths to principled derivation.
# See also: AUDIT_BRIEF.md + AUDIT_RESPONSE.md — pre-CR-001 architecture audit + recommendations
# See also: JOURNAL.md — session-by-session change log (full detail; not auto-loaded)
# See also: REM/CLAUDE.md — sibling project (distributed fleet via Tapo P110 + TP-Link cloud); repo at dom-robinson/stats. OWL = bench, REM = meter on the building.

## Project Identity
- **Name:** WattLab
- **Repo:** https://github.com/greeningofstreaming/wattlab
- **Host:** GoS1 — Ubuntu 24, `192.168.1.62`, externally `gos1.duckdns.org:2222`
- **Owner:** GoS (Greening of Streaming), French NGO loi 1901
- **Mission:** Measure environmental impact of streaming. Neutral, technically credible.
- **Full spec:** See WATTLAB_SPEC.md in repo root

## GoS Framing (always apply)
- "Not eco-warriors. Just people who dislike waste."
- If it can't be measured, it shouldn't be asserted.
- Separate device / network / data center / production+storage impacts explicitly.
- State scoping assumptions. Signal uncertainty. Traffic Light Confidence on all claims.
- Audience: CTOs, operators, infrastructure players, policymakers.

## GoS1 Server
- OS: Ubuntu 24, kernel 6.17
- CPU: AMD Ryzen 9 7900, 24 cores
- GPU: AMD Radeon RX 7800 XT — VAAPI (video) + ROCm (AI), 12GB VRAM
- RAM: 61GB
- Disk: 500GB NVMe system disk (`nvme0n1`, `/` — ~264GB free, May 2026) + 4TB NVMe data disk (`nvme1n1`, ext4, mounted `/srv/data`, in fstab w/ `nofail` — added S24 2026-05-12). `/srv/data/owl/{test_content,results,corpus,.chroma}` hold OWL bulk/archival data, symlinked back into the repo; `/srv/data/rem/` holds Simon's REM display-test clips (symlinked from `/home/simon/rem`); `/srv/data/media/` is a general bucket.
- Cooling: 9 fans total — 5 case (the 5th re-enabled via a Y-splitter S24 2026-05-12), 2 GPU (integrated), 1 CPU (header can take a 2nd), 1 PSU internal. Relevant to CR-005 (fan control).
- Python: 3.12.3 · Node: 20.x
- Claude Code: `~/.npm-global/bin/claude`, authenticated as nebul2
- Git: bs@ctoic.net / nebul2
- SSH users: simon, tania, dom, marisol, gos (owner)
- External: `ssh -p 2222 user@gos1.duckdns.org`
- Idle power: ~51-54W (stable), occasional drift to 58W — figure predates the S24 NVMe + 5th case fan; recalibration pending will refresh it.

## Network Topology
```
BouyguesBox (192.168.1.x)
├── GoS1 (ethernet) → 192.168.1.62
└── Nighthawk RAX120 (AP mode)
    ├── MacBook (WiFi)
    └── Tapo P110 (WiFi) → 192.168.1.159
```

## Thermal Sensors
- One source of truth: `power.read_sensors_dict()` → `{cpu_tctl, gpu_junction, gpu_ppt_w}`. The per-module `read_sensors()` wrappers (video/llm/image_gen/rag) just delegate to it.
- CPU: `data['k10temp-pci-00c3']['Tctl']['temp1_input']` (k10temp is on the CPU bus — name is stable).
- GPU: chip key is **resolved dynamically** via `power.amdgpu_chip(data)` — the one amdgpu chip with a `junction` sub-key (the discrete RX 7800 XT; the iGPU has only `edge`/`PPT`). *Do not hardcode the PCI address* — it shifts on PCIe re-enumeration (the S24 NVMe add moved it `amdgpu-pci-0300` → `amdgpu-pci-0400`, which silently broke the old lookups). Then `data[gpu]['junction']['temp2_input']` and `data[gpu]['PPT']['power1_average']`.
- Read via: `subprocess.run(['sensors', '-j'], ...)`

## Environment
- `.env` at `/home/gos/wattlab/.env` — gitignored
- Variables: `TAPO_EMAIL`, `TAPO_PASSWORD`, `TAPO_P110_IP`, `OWL_AUTH_SECRET` (CR-001 magic-link signing key), `OWL_GMAIL_USER` + `OWL_GMAIL_APP_PASSWORD` (Gmail SMTP for magic-link delivery)

## Installed Packages
- Python: tapo==0.8.12, python-dotenv, fastapi, uvicorn, python-multipart, torch 2.5.1+rocm6.2, diffusers, transformers, accelerate, pillow
- System: lm-sensors, ffmpeg 6.1.1, nmap
- AI: Ollama 0.20.2 (systemd service, port 11434)
- Models: tinyllama:latest (1.1B), mistral:latest (7B), gemma3:12b (12B), phi4:latest (14B), x/z-image-turbo (12GB, GPU blocked), x/flux2-klein (5.7GB, CUDA/MLX only)
- Image gen: stabilityai/sd-turbo + stabilityai/sdxl-turbo via diffusers (CPU for SD-Turbo only; GPU via ROCm for both; cached in ~/.cache/huggingface)

## Repo Structure
```
wattlab/
├── .env                          # gitignored
├── .gitignore                    # ignores test_content, results, corpus, .chroma (now symlinks — no trailing slash so they still match)
├── README.md
├── CLAUDE.md
├── JOURNAL.md
├── TESTING.md                    # three-tier testing strategy
├── WATTLAB_SPEC.md               # full product spec
├── data_analysis_nov25/          # Nov25 hackathon scripts
├── data_cleanup/
│   └── clean_measures.py         # Tania — aligns Tapo CSVs
├── test_content/   ->  /srv/data/owl/test_content   # symlink (S24, 4TB disk); meridian_4k.mp4 = Netflix Open Content CC BY 4.0, 812MB
├── results/        ->  /srv/data/owl/results        # symlink (S24, 4TB disk); persistent result JSON — {video,llm,image,diagnostics}/
├── corpus/         ->  /srv/data/owl/corpus         # symlink (S24); RAG source PDFs (papers/)
├── .chroma/        ->  /srv/data/owl/.chroma        # symlink (S24); RAG vector store
└── wattlab_service/
    ├── main.py                   # FastAPI routes + all HTML UI + queue worker
    ├── video.py                  # P110 + ffmpeg + thermals + focus mode
    ├── llm.py                    # Ollama inference + P110 measurement
    ├── image_gen.py              # SD-Turbo CPU diffusion + P110 measurement
    ├── persist.py                # Flat-file result storage + CSV/JSON export
    ├── settings.py               # Lab config (15 params, settings.json)
    ├── sources.py                # Pre-loaded test content registry
    └── power.py                  # Power measurement interface (Tapo P110); swap here for PDU/IPMI
```

## Measurement Protocol
1. Focus mode: stop background timers (sudoers: `/etc/sudoers.d/wattlab-focus`)
2. LLM only: unload model (keep_alive=0), sleep 3s
3. Baseline: 10 polls × 1s → W_base
4. Lock: `/tmp/gos-measure.lock`
5. Task: ffmpeg (nice -n -5) or Ollama API
6. Poll P110 + sensors at 1s
7. Compute: ΔW, ΔE = ΔW × (ΔT/3600) Wh, mWh/token (LLM)
8. Write result JSON to results/{type}/{date}_{job_id}.json
9. Focus exit: parallel timer restart (ThreadPoolExecutor + run_in_executor)

## Focus Mode Timers
sysstat-collect, anacron, fwupd-refresh, apt-daily, apt-daily-upgrade,
man-db, motd-news, update-notifier-download
Sudoers: `/etc/sudoers.d/wattlab-focus`

## Traffic Light Confidence
Variance-relative thresholds (Session 11). `noise_w = variance_pct/100 × w_base`
- 🟢 Repeatable: ΔW > variance_green_x × noise_w AND ≥conf_green_polls polls (defaults: 5×, 10 polls)
- 🟡 Early insight: ΔW ≥ variance_yellow_x × noise_w OR ≥conf_yellow_polls polls (defaults: 2×, 5 polls)
- 🔴 Need more data: below yellow threshold
- `variance_pct` default 2.0% — auto-updated by variance calibration run
- `confidence(delta_w, poll_count, w_base)` — all four modules (video, llm, image_gen, rag)

## Scope Statements
Video: "Device layer only (GoS1 server). Network, CDN, and CPE excluded."
LLM: "Device layer only (GoS1 server). Network and CPE excluded. No amortised training cost."

## Running Services
| Service | Port | Status |
|---|---|---|
| wattlab (systemd) | 8000 | ✅ 1 worker |
| ollama (systemd) | 11434 | ✅ active |

## Current URLs
- LAN: `http://192.168.1.62:8000` (paths: `/video /llm /image /demo /settings /queue-status /methodology /rag /carbon`)
- Tunnel: `ssh -p 2222 -L 8000:localhost:8000 user@gos1.duckdns.org`
- Public (HTTPS via certbot): `https://wattlab.greeningofstreaming.org`
- Auth model: tier-based (CR-001). Anonymous = no auth, Member = magic-link sign-in via `/auth/sign-in` (allowlist `data/members.json`), Lab = LAN/loopback IP.

## Roadmap

**Phases 1–8 shipped:** research integrity (persistence + export), measurement quality (LLM batched/warm-cold/streaming, H.265+AV1), settings & lab config, demo mode + GoS visual identity, image generation (SD-Turbo CPU/GPU + SDXL-Turbo), public access (nginx + cert + IP-gate), guided tour + credibility (confidence popover, resume), RAG energy test (Chroma + compare-3-modes).

**Active CRs:** see `CHANGE_REQUESTS.md` (20 entries — CR-003 iso-energy, CR-004 graphing, CR-005 fan control, CR-007 carbon variance, CR-008 REM↔OWL, CR-009 web client, CR-012 calibration history, CR-018 T2/T3 historical, CR-024 probe button, CR-025 RT Linux, CR-027 tier copy, CR-028 confidence model, CR-029 encoding rigor, CR-031 portability, CR-033 curated demo video, CR-035 encode progress bar, CR-037 AI workloads tethered to the Language Lab AI position paper *(biggest open framing item)*, CR-039 energy-vs-quality axis for AI *(exploratory; tension with CR-029 §6 to resolve)*, CR-040 "Reproduce this result" downloadable bundle, CR-041 new-vs-aged silicon benchmark *(opportunistic)*). **Closed in the 2026-05-12 sweep:** CR-032 (per-mode CO₂e rows), CR-034 (unified results card — absorbed CR-013), CR-036 (carbon "indicative only" hardening), CR-038 (efficiency-winner verdict) — all in `CHANGE_REQUESTS_CLOSED.md` along with CR-042 (Pixop placeholder, closed 2026-05-12). CR-019 resume-job hook deferred to a follow-up CR — capture if/when it surfaces in real visitor traffic. See "Groupings & dependencies" appendix at end of `CHANGE_REQUESTS.md` for cross-CR dependencies.

### Recent sessions (one-line summary; full detail in JOURNAL.md + git log)
- **S10 (2026-04-07):** centralised power cache, ffmpeg cmd in result JSON, GPU PPT note, home nav restructure.
- **S11 (2026-04-09):** /methodology page; variance-based confidence framework (replaces fixed-W thresholds); /variance/run calibration endpoint.
- **S12 (2026-04-10):** video preset overhaul (3 codec rows × CPU/GPU/Both); full VAAPI pipeline; VAAPI surface-pool fix; meridian_120s test asset.
- **S13 (2026-04-10):** ABR rate control across all 6 presets; all_codecs compare mode; HTTPS via certbot.
- **S14 (2026-04-24):** Gemma 3 12B + Phi-4 added; SDXL-Turbo image gen; Compare Models ⚡; progressive-disclosure pilot; live telemetry badge; queue pause flag (/tmp/owl-paused); owl logo across all 10 pages.
- **S15 (2026-04-29):** _BASE_STYLES palette (CSS-var contrast pass); RAG compare cooldown; corpus browser; LLM CSV gains response column.
- **S16 (2026-05-01):** **CO₂e measurement** — `carbon.py` module (Eco2mix→ElectricityMaps→Ember static fallback ladder), `walk_and_enrich()` injects co2e block on all result shapes, `_CARBON_JS` UI helpers (live/EST badges, comparison strip with collapsed details + live French production mix), fmtMass auto-switches g/mg/µg, "below measurement floor" rendering when ΔE=0. **CR-002 methodology accuracy pass** — placeholders + settings injection so `baseline_polls`/`video_cooldown_s`/confidence thresholds can never drift from settings.json. **First test suite** — `wattlab_service/tests/test_carbon.py`, 28 tests, sets the testing pattern for the upcoming access-spine modules. Strategy docs landed: `CHANGE_REQUESTS.md` (CR-001 two-tier OWL + CR-001b demo lock + CR-002…CR-009), `AUDIT_BRIEF.md` + `AUDIT_RESPONSE.md`, `TRAINING_OWL_5MIN.md`, `rem-theme.css`.
- **S17 (2026-05-01 / 2026-05-02):** **Access spine refactor (audit's #1 recommendation, A/3 + B/3 + C/3)** — extract `queue_control.py`, add `audience.py` + `capabilities.py`, tag every route with `requires(...)`, remove `_is_local`. Sets the seam (`enqueue(request=None)`) for CR-001b demo lock. **CR-002 closure** — popover (`_CONF_HELP_WIDGET`) rewritten to framework-correct copy + `position:fixed` offset bug fixed (was `+window.scrollY`, sent popover offscreen when scrolled), Guided Tour gains placeholder injection, ~13 fresh-run badges + all prev-run badges across `/video` `/llm` `/rag` `/image` wrapped in `class="conf-badge"` so the popover fires uniformly. **CR-014** RAG compare-3-modes gains the carbon comparison strip (was missing — only single-mode had it). **CRs captured:** CR-010 (France historical reference row in comparison strip), CR-011 (staging via maintenance-page swap), CR-012 (persist variance calibration history), CR-013 (prev-run rows clickable for full stored detail). Settings.save partial-update fix (settings.py) so `/settings` form posts merge cleanly with on-disk state.
- **S18 (2026-05-03):** Long carbon-credibility session — closed CR-010, CR-006, CR-011, CR-016, CR-018 Tier 1; captured CR-015, CR-017, CR-018 Tier 2/3. Sixteen commits. **CR-010** carbon strip pinned home-zone reference row + ≥25% divergence note + zone-aware live-source explainer. **CR-006** AI workloads re-framed as "Beta · exploratory" (landing nav + h1 chips on /llm /rag /image + Demo Tour entering-beta band on steps 2/3/4). **CR-011** staging via maintenance-page swap — `bin/stage-on`/`stage-off` + `STAGING.md` + nginx vhost (`error_page 503 @maintenance` + `/static/` direct + `/tmp/owl-maintenance` watch) applied + smoke-tested green; `bin/README.md` established as the canonical home for operator scripts. **CR-016** live FR carbon now derives from Eco2mix production mix × IPCC AR6 lifecycle factors instead of trusting `taux_co2` (direct only) — fixed a spurious ~4× live-vs-static gap that was almost entirely a methodology artefact; live and static now on the same boundary; 2 regression tests. **CO2e UI hierarchy**: carbon strip moved from top of every result to bottom (12 sites), headline number shrunk 1.5rem→1rem, "HIGH-LEVEL CO₂e ESTIMATE" caption framing the block, EV-distance equivalence (`≈ X mm/m/km driving a typical EV` at 50 g/km T&E 2024), inline `wlCarbonRow` label gains "(est.)". **CR-018 Tier 1** five curated FR historical dates (Jan 2020, Jun 2020, Jun 2022, Jan 2024, Jun 2024) in the carbon strip's collapsed details, all computed via `bin/fetch-historical-mix` from Eco2mix consolidated using the same lifecycle math as live (so directly comparable). Methodology page picks up the lifecycle framing + historical subsection. Variance recalibration (variance_pct 1.08 → 3.62) + three `*_bitrate_kbps` settings fields. `.gitignore` expanded; four tracked `__pycache__/*.pyc` slips removed. **CRs captured:** CR-015 (auto-lower maintenance flag on inactivity, follow-up to CR-011), CR-017 (24/7-projection toggle on the carbon strip), CR-018 Tier 2/3 (visitor-pickable any-month + interactive timeline). 111 tests passing.
- **S19 (2026-05-03):** **CR-001 two-tier OWL — bulk of the work** on `feature/cr-001-two-tier`. Eight commits + this close. **CR-001b** marked resolved (`bin/stage-on` + CR-015 cover the original intent — no code shipped under that name). **Part A** magic-link auth foundation (`auth.py` HMAC-signed magic-link tokens 15-min TTL + session cookies 30-day TTL, anti-enumeration on POST sign-in, `email_send.py` Gmail SMTP with dry-run flag, member allowlist `data/members.json`, `audience.tier()` resolves Member from cookie, gate middleware bypasses `/auth/*` and valid sessions). **Part B/1** tier-aware routing on `/` (Anonymous → 302 `/demo`, Member/Lab → nav grid; sign-in/Sign-out/Lab chip top-right server-rendered). **Part B/2** capability matrix as product copy on `/demo` Findings step (Public-vs-GoS-member 7-row table + Join-GoS CTA — locks ARE the membership pitch). **Part C1** Member-tier capability constants in `capabilities.py` (`CUSTOM_PROMPT`, `BATCH_COMPARE`, `RAG_CORPUS_UPLOAD`, `RESULTS_EXPORT_CSV`); snapshot test pinned. **Part C2a** `capabilities.gate(request, *caps)` imperative helper for runtime cap dispatch; retags `/llm/run-all` → BATCH_COMPARE, `/rag/build-index` → RAG_CORPUS_UPLOAD; inline `gate()` on `/llm/run` (prompt set, repeats>1, device=='both'), `/video/use-source` + `/video/upload` (preset='all_codecs', custom_cmd*), `/image/start` (device in {both, compare_models}). **Part C2b** `curated.py` (CANONICAL_IMAGE_PROMPT / CANONICAL_RAG_QUESTION / CANONICAL_RAG_MODEL); `/image/start`, `/rag/run`, `/rag/run-compare` made `prompt`/`question` optional → curated server-side when absent, `gate(CUSTOM_PROMPT or BATCH_COMPARE)` when present; `/demo` JS dropped hardcoded prompt/question params on image and RAG calls. **/demo navigation dead-end fix**: when no previous result on file (or fetch errors), all four `showPrev*()` poll functions now reveal the per-step back/next/again block — previously the visitor was stuck with only a Run button. **Factorisation contract** held throughout: capability table is policy; routes only call `requires`/`gate`; business modules tier-blind; no runtime "is this default?" detection. **Captured:** CR-019 (unify the in-progress widget — `/demo` rolls its own simpler version per step, while main pages share `wlRenderProgress` + `wlStageList`; ~½ day refactor). 168 tests passing.
- **S20 (2026-05-03):** **CR-001 close-out** on `feature/cr-001-two-tier` — three commits, CR done. **Part C2c** `_LOCK_STYLES` + `_lock_badge_html()` + `_lock_class()` + `_disabled_attr()` helpers in main.py; applied across `/llm` (prompt editor, Both, repeats>1, Run All), `/video` (all-codecs preset; custom-cmd textarea predicate moves SETTINGS_READ_FULL → CUSTOM_PROMPT so Members get edit too), `/image` (prompt textarea, Both, Compare Models), `/rag` (question, Compare-3-modes, Build/Rebuild). Per-page JS reads `CAN_CUSTOM_PROMPT` / `CAN_BATCH_COMPARE` flags from server and skips locked form params for Anonymous so the runtime gate doesn't trip on pre-filled defaults. **Part D** per-tier queue caps + per-tier upload size cap, enforced at the single chokepoint (`queue_control.enqueue`). `_visitor_key()` resolves Anonymous → `a:<ip>`, Member → `m:<email>`, Lab → None (uncapped); 12 new queue tests; settings.json gains `queue_anonymous_cap=1`, `queue_member_cap=4`, `upload_size_anonymous_mb=100`, `upload_size_member_mb=1024`; `/video/upload` Content-Length pre-check returns 413 before reading the body; `/settings` page renders a "Tier limits" section. **Task #10** `WATTLAB_GATE_PASSWORD` retired — middleware + GET/POST `/gate` removed (77 lines from main.py); `bin/stage-on`/`stage-off`/`bin/README.md` drop the gate cookie (loopback `/live` is now Lab tier directly); `CLAUDE.md`/`TESTING.md` updated. 180 tests passing.
- **S21 (2026-05-04):** **Variance-calibration integrity pass.** Owner queried inflated `variance_idle_pct` (11.03%) and `variance_gpu_pct` (3.00%) from overnight calibration; investigation surfaced two coupled bugs. **CR-022 — `scale_vaapi` surface-pool leak**: VAAPI filter chain (`-vf scale_vaapi=…`) leaks surfaces and crashes near end-of-stream on long inputs (~7000+ frames at 1080p). Reproducible in standalone ffmpeg on both `meridian_4k.mp4` (frame 43076) and `meridian_120s.mp4` (frame 7178). Affects `variance_gpu_cmd` + `PRESETS["h265_gpu"]/["av1_gpu"]/["gpu"]`. Fix: `gpu_encode_max_s=30` setting + `_maybe_cap_vaapi()` helper in `transcode()` injects `-t 30` before `-i` on VAAPI cmds; result dict gains `gpu_capped_at_s`. **CR-023 — silent-failure on calibration**: `run_variance_calibration` ignored `transcode_result["success"]`, so failed encodes silently produced ΔW from partial data. Fix: gate ΔW append on success, track `cpu_failed`/`gpu_failed`, abort settings update if ≥50% fail. **Diagnostic — `bin/probe-thermal-recovery`**: 12-distance × CPU+GPU thermal-recovery probe, ~65 min wall time, writes `results/diagnostics/recovery_<ts>.csv` + `_summary.csv`. Confirmed bimodal-idle hypothesis was wrong: post-CPU and post-GPU baselines converge by d=5s, mean within-window CV = 2.14% (calibration's 11% was inflated by CR-022 + CR-023, not by recovery time). **UI — "More calibration details" dropdown** on `/settings` (Lab tier): renders the recovery curve from the latest probe data via Chart.js 4.4.0 (matches REM). Factorisation shipped: `wattlab_service/static/wl-charts.js` is the shared chart helper (`WlCharts.line({canvas, datasets, xLabel, yLabel, yUnit})` with semantic colour names — `cpu`, `gpu`, `accent`, `warn`, `err` — resolved against the OWL palette). Future charts on `/methodology` etc. drop in with the same shape; swapping Chart.js for uPlot/ECharts is a one-file change. New endpoint `GET /precalibration/data` (Lab tier) serves the latest probe CSV as JSON. **CRs captured:** CR-024 (re-run probe button on the panel — half-day; route through `queue_control.enqueue`).
- **S22 (2026-05-05):** **Bundle 2 — carbon-strip calibration + 24/7 projection.** Two commits. **Part 1** (variance integrity + CR archive split) confirmed n=24 / cooldown=90 calibration yielded clean idle 2.41% / cpu 1.33% / gpu 4.77% (`variance_pct=2.84`); created `CHANGE_REQUESTS_CLOSED.md` with 10 fully-shipped CRs (CR-001/001b/002/006/010/011/014/016/022/023); slimmed `CHANGE_REQUESTS.md` 1582→1098 lines; CLAUDE.md cross-refs updated. **Part 2** (Bundle 2) — closed **CR-030** (carbon UI calibration: typography shrink 1rem→0.85rem accent→text-3, EV-equivalence floor at 0.0005 g, `massTitle` µg/mg disambiguation tooltip with scientific notation across every mass cell, plus a NEW sub-#4 added during visual review — drift note when home-zone live grid intensity differs ≥1% from the run's saved intensity, surfaces the saved-vs-live temporal mismatch on 9 call sites) and **CR-017** (24/7 continuous-service projection toggle — V1 toggle-only with `as-measured / 1h / 1d / 1mo / 1y`, multiplier wires through headline + EV + reference + comparison + historical rows, URL hash state via `history.replaceState`, hidden when no `durationS`; `fmtEnergy` auto-switches Wh/kWh/MWh/GWh and `fmtMass` extended upward to kg/t for sane projection display). Plus bonus video compare-mode label fix ("best of CPU vs GPU" / "most efficient codec across all comparisons"). Use-phase scope clarifier added: caption now reads "HIGH-LEVEL CO₂e ESTIMATE · USE PHASE · for comparison with other activities" with tooltip + formula `<details>` line spelling out manufacturing/embodied carbon are not included. **Captured:** CR-032 (per-mode CO₂e rows inside the carbon strip details for compare results — half-day; deferred). 181 tests passing throughout. Branched off main onto `feature/bundle-2-carbon-ui` after merging `feature/cr-001-two-tier` to local main.
- **S23 (2026-05-07 / 2026-05-08):** **Polish + closure marathon — twelve commits on `main`.** Three CRs fully closed (CR-022, CR-026, CR-019), three more closed via the quick-wins bundle (CR-021, CR-015, _HEADER factorisation), three new CRs captured (CR-033, CR-034, CR-035), parameters audit doc shipped for Tania, /demo refactored across six iterative polish commits, and the active CR list pruned 21 → 19. **CR-022 fully resolved** (`9e1d076`) by upstream ffmpeg master fixing the `scale_vaapi` leak; `_maybe_cap_vaapi` and `gpu_encode_max_s` deleted; new `ffmpeg_bin` setting routes every preset + custom command through `/usr/local/bin/ffmpeg-master`; n=6 verification calibration confirms idle 2.26% / cpu 0.66% / gpu 0.95% (S22's 4.77% was the cap producing only ~30 polls per run). **`docs/wattlab_parameters_audit.md`** (`6d14f1e`) responds to Tania's meeting question — every parameter classified Arbitrary / Empirical / Calibrated / Constrained with a "path to principled" column. **CR-026 anon-integrity** (`caa025b`): persistence layer scopes own-jobs by `visitor_key`; CUSTOM_UPLOAD moved to Member; new WORKING_NAV cap retires the home-redirect tier compare; route audit test asserts every endpoint is gated. **Quick-wins bundle** (`2db2cbd`): CR-021 sign-in CTA chip variant + `_HEADER` factorisation (`/queue-status` and `/methodology` adopt unified chrome) + CR-015 maintenance-flag watchdog (Lab middleware + bash script + systemd timer + `max_idle_mins` setting). **CR-019** (`2484599`): `/demo`'s four poll loops use the shared `wlRenderProgress` widget; `_job_status()` helper injects live watts; resume-job hook deferred. **/demo polish** (`c68f4ac` → `e76824d`): predetermined small video job (`meridian_120s` + `h265_both`); `/demo/last/{type}` carve-out endpoint; `_PROGRESS_JS` finally appended to `_DEMO_HTML` (had landed in `queue_page()` instead — masked until run-handler try/catch surfaced it); explicit "Run a standard <task>" button labels; methodology link in footer + Welcome-step inline; LLM/RAG/image/video result cards gain prompt blockquote + carbon strip; RAG progress shows `Mode 1/2/3 of 3 — No retrieval / RAG / RAG Large`; video progress shows `Side 1/2 of 2 — CPU/GPU encode`. **CR-035 captured** (`7c58893`) — encode progress bar via `ffmpeg -progress pipe:1`. **Final docs pass** (Session 23 part 12+): all `.md` files reviewed for staleness; README access section rewritten to reflect three-tier model; WATTLAB_SPEC.md gains historical-spec disclaimer at top; TESTING.md picks up CR-026 + /demo regression checks; JOURNAL.md gets full S20/S22/S23 entries. 196 tests passing throughout.
- **S24 (2026-05-12):** **GoS1 storage expansion.** 4TB NVMe (`nvme1n1`, SPCC) added as a dedicated data disk — wiped the factory MSR partition, fresh GPT, single ext4 (`-m 1`), in `/etc/fstab` by UUID with `nofail`, mounted `/srv/data`; `wattlab.service` drop-in adds `RequiresMountsFor=/srv/data`. OWL bulk/archival data relocated: `test_content/` `results/` `corpus/` `.chroma/` moved under `/srv/data/owl/` and **symlinked** back into the repo (zero code/settings changes — paths are hardcoded in `persist.py`/`sources.py`/`video.py`/`main.py` + `settings.json`). Simon's 77 GB of REM display-test clips moved `/home/simon/rem` → `/srv/data/rem` (symlinked back, kept `simon:simon`). System disk freed 249 GB → 170 GB used. `.gitignore` trailing slashes dropped on the four relocated dirs so the patterns still match symlinks. Methodology page Hardware Disclosure "Storage" row updated. Also S24: re-enabled a 5th case fan via a Y-splitter (was deactivated) — GoS1 now runs 9 fans (5 case / 2 GPU / 1 CPU / 1 PSU). **Still pending:** variance recalibration (2nd NVMe + extra fan nudge idle draw up a few W — the `~51–54W` idle figure and the Hardware Disclosure "Idle power" row will want refreshing once that's run).

### Deferred / open
- [ ] **Confidence multiplier grounding** — see **CR-028 Phase 2** (`variance_green_x`/`variance_yellow_x` 5×/2× threshold values absorbed into the unified statistical model).
- [ ] **Transcoding apples-to-apples (GOP / profile)** — see **CR-029** sub-item 2 (Tania-led CPU-vs-GPU encode-parameter validation).
- [ ] **Benchmark 2** — codec-natural rate control (CRF/QP) alongside Benchmark 1 (ABR). Add to `WATTLAB_SPEC.md`. *Distinct from CR-029: CR-029 normalises the existing ABR benchmark; Benchmark 2 is a sibling family.*
- [x] **Access spine refactor** (audit's #1 recommendation) — `audience.py` + `capabilities.py` + `queue_control.py` shipped S17 parts A/3 + B/3 + C/3. Spine seam (`enqueue(request=None)`) ready for CR-001b.
- [ ] **Dockerize OWL** — see **CR-031** sub-section 3 (containerisation readiness, two-stage plan: FastAPI+VAAPI, then ROCm).
- [x] **Factorise `_HEADER` constant** — done 2026-05-07 (Session 23 part 4 alongside CR-021). `_HEADER_STYLES` + `_header_html(request)` helper; `/queue-status` and `/methodology` now render the same auth chip + back link as standard pages.
- [ ] **Guided Tour Findings step** — currently echoes session run; redesign to aggregate across all stored results to surface body-of-evidence learnings (see Key Findings).
- [ ] **RAG visitor upload + corpus PDF view** — see `CHANGE_REQUESTS.md` follow-ups.
- [ ] **Power-user/visitor UX watch** — progressive-disclosure pilot is live across test pages; revisit if a visible density toggle becomes needed.
- [x] **Confirm GPU variance with a long-run calibration** — done 2026-05-05 overnight at n=24/cooldown=90/gpu_encode_max_s=90: idle 2.41% / cpu 1.33% / **gpu 4.77%**. *Updated 2026-05-07:* post-CR-022-resolution quick n=6 calibration gives idle 2.26% / cpu 0.66% / **gpu 0.95%** — full encodes now (no `-t` cap), GPU lands at the bottom of Tania's 3–5% expectation. Longer overnight run incoming.
- [x] **`scale_vaapi` long-term fix** — done 2026-05-07 (Session 23 part 1 — `9e1d076`). Upstream ffmpeg master fixes the leak; `_maybe_cap_vaapi` and `gpu_encode_max_s` deleted; all presets + custom commands + calibration templates route through `ffmpeg_bin` (default `/usr/local/bin/ffmpeg-master`). CR-022 fully closed.
- [x] **CR-026 anonymous-tier integrity pass** — done 2026-05-07 (Session 23 part 2 — `caa025b`). Persistence layer scopes own-jobs by `visitor_key`; CUSTOM_UPLOAD moved Anonymous → Member; new WORKING_NAV cap retires the home-redirect tier compare; route audit test asserts every endpoint has `Depends(requires(...))` or an explicit waiver. Phase E (curated content expansion) deferred to a follow-up CR.

## Key Findings to Date

### Video — ABR All-Codecs benchmark (Meridian 120s, n=3, all 🟢) — canonical
Identical-bitrate ABR (H.264 4000 kbps · H.265 2000 kbps · AV1 1500 kbps). GPU = full VAAPI pipeline.
- **H.264:** CPU 37.3s / 0.83 Wh · GPU 17.5s / 0.37 Wh → GPU **~55% less energy, ~53% faster**
- **H.265:** CPU 70.3s / 1.58 Wh · GPU 14.5s / 0.29 Wh → GPU **~81% less energy, ~79% faster**
- **AV1:** CPU 30.8s / 0.65 Wh · GPU 14.5s / 0.30 Wh → GPU **~55% less energy, ~53% faster**
- H.265 GPU and AV1 GPU both finish at **exactly 14.5s** — VAAPI hardware clock is the GPU-path ceiling.
- Most efficient: AV1 GPU and H.265 GPU (gap within noise).
- AV1 CPU beats H.265 CPU on speed AND energy — SVT-AV1 multi-core advantage.
- Results within 1% across 3 runs; supersedes all CRF/QP comparisons.

### LLM Cold Inference 🟢/🟡
- Mistral 7B T3: **0.943 mWh/token** 🟢
- TinyLlama T3: **0.061 mWh/token** 🟡 (~15× more efficient — but generic-boilerplate answers).
- TinyLlama short tasks are below the P110 floor; batched mode required for reliable readings.

### Image generation
- SD-Turbo CPU first run: **0.2063 Wh/image**, 12.15s, ~30 W delta. Backend: Ryzen 9 7900, 8 steps, 512×512.
- SD-Turbo + SDXL-Turbo on GPU (ROCm, fp16 small / fp32 VAE upcast at 512×512) shipped in S14; Compare Models ⚡ runs both at 4 native steps for apples-to-apples size comparison.
- VRAM ceiling: SDXL-Turbo at 1024×1024 busts the 12 GB Navi31 budget via the fp32 VAE upcast — 512×512 is the sweet spot.

### RAG faithfulness ⭐ (S15, "What is REM?")
All three models (TinyLlama 1.1B, Gemma 3 12B, Phi-4 14B) **retrieved identical correct chunks** — the GoS REM whitepapers. But TinyLlama hallucinated *"REM is a framework provided by the European Commission"*, blending the GoS source with an adjacent JRC chunk. Gemma and Phi-4 stayed faithful. **Headline:** RAG retrieval works at small scale; RAG *quality* depends on the consuming model's faithfulness. Hallucination is a third axis on the energy/quality tradeoff.

### French grid evolution (S18, CR-018 Tier 1 historical data)
Same lifecycle methodology (Eco2mix mix × IPCC AR6 factors), monthly mean gCO2e/kWh:
- Jan 2020: **65.8** · Jun 2020: **54.6** · Jun 2022: **59.5** · Jan 2024: **53.4** · Jun 2024: **26.9**
- Jun 2022 → Jun 2024 = **55% reduction in two years** (nuclear back + solar buildout). Bigger story than the popular "nuclear corrosion crisis" framing — Jan 2023 was 63.2, only marginally worse than Jan 2020. The crisis didn't dominate monthly lifecycle averages because France stayed mostly nuclear even at the worst.
- Live diurnal range can hit ~22 g/kWh on a sunny + nuclear-heavy weekend afternoon and ~85 g/kWh during a winter cold-snap evening.
- **Methodology insight (CR-016):** Eco2mix's `taux_co2` is direct combustion only and isn't comparable to lifecycle annual means. Mixing the two produced a spurious ~4× live-vs-static gap. After CR-016, both are lifecycle and the real gap is ~1.5–2×.

## Visual Identity
- Project mark: owl SVG at `wattlab_service/static/owl.svg` (2.4KB teal/green geometric).
- Org mark: GoS round bug, footer only (`_LOGO`).
- Dark theme: `#0a0a0a` bg, `#00ff99` accent — all tokens centralised in `_BASE_STYLES` (`main.py:~276`).
- For external/family theming see `rem-theme.css` (drop-in stylesheet that re-skins REM with OWL palette).
