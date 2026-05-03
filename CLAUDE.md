# WattLab — Claude Code Context File
# Auto-loaded by Claude Code. Keep this current.
# Last updated: 2026-05-03 (Session 19)
# Public name: OWL (Online WattLab). "WattLab" is the legacy/internal/repo name.
# See also: GOS1_INFRA.md — server infrastructure, Nextcloud backup, personal stack context
# See also: TESTING.md — three-tier testing strategy
# See also: CHANGE_REQUESTS.md — open CRs. CR-001 in progress on `feature/cr-001-two-tier` (parts A/B1/B2/C1/C2a/C2b shipped, C2c + D remaining). CR-001b resolved by CR-011+CR-015. CR-002, CR-014 done. CR-003…CR-013 + CR-015/017/018/019 captured.
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
- RAM: 61GB · Disk: 457GB, 221GB free (April 2026)
- Python: 3.12.3 · Node: 20.x
- Claude Code: `~/.npm-global/bin/claude`, authenticated as nebul2
- Git: bs@ctoic.net / nebul2
- SSH users: simon, tania, dom, marisol, gos (owner)
- External: `ssh -p 2222 user@gos1.duckdns.org`
- Idle power: ~51-54W (stable), occasional drift to 58W

## Network Topology
```
BouyguesBox (192.168.1.x)
├── GoS1 (ethernet) → 192.168.1.62
└── Nighthawk RAX120 (AP mode)
    ├── MacBook (WiFi)
    └── Tapo P110 (WiFi) → 192.168.1.159
```

## Thermal Sensors
- CPU: `data['k10temp-pci-00c3']['Tctl']['temp1_input']`
- GPU junction: `data['amdgpu-pci-0300']['junction']['temp2_input']`
- GPU PPT: `data['amdgpu-pci-0300']['PPT']['power1_average']`
- Read via: `subprocess.run(['sensors', '-j'], ...)`

## Environment
- `.env` at `/home/gos/wattlab/.env` — gitignored
- Variables: `TAPO_EMAIL`, `TAPO_PASSWORD`, `TAPO_P110_IP`, `WATTLAB_GATE_PASSWORD`

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
├── .gitignore                    # includes test_content/, results/
├── README.md
├── CLAUDE.md
├── JOURNAL.md
├── TESTING.md                    # three-tier testing strategy
├── WATTLAB_SPEC.md               # full product spec
├── data_analysis_nov25/          # Nov25 hackathon scripts
├── data_cleanup/
│   └── clean_measures.py         # Tania — aligns Tapo CSVs
├── test_content/
│   └── meridian_4k.mp4           # Netflix Open Content, CC BY 4.0, 812MB
├── results/                      # [to create] persistent JSON results
│   ├── video/
│   └── llm/
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
- Gate password: in `.env` as `WATTLAB_GATE_PASSWORD` (ask owner)

## Roadmap

**Phases 1–8 shipped:** research integrity (persistence + export), measurement quality (LLM batched/warm-cold/streaming, H.265+AV1), settings & lab config, demo mode + GoS visual identity, image generation (SD-Turbo CPU/GPU + SDXL-Turbo), public access (nginx + cert + IP-gate), guided tour + credibility (confidence popover, resume), RAG energy test (Chroma + compare-3-modes).

**Active CRs:** see `CHANGE_REQUESTS.md` (CR-001 two-tier OWL, CR-001b demo lock, CR-002…CR-009).

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
- **S19 (2026-05-03):** **CR-001 two-tier OWL — bulk of the work** on `feature/cr-001-two-tier`. Eight commits + this close. **CR-001b** marked resolved (`bin/stage-on` + CR-015 cover the original intent — no code shipped under that name). **Part A** magic-link auth foundation (`auth.py` HMAC-signed magic-link tokens 15-min TTL + session cookies 30-day TTL, anti-enumeration on POST sign-in, `email_send.py` Gmail SMTP with dry-run flag, member allowlist `data/members.json`, `audience.tier()` resolves Member from cookie, gate middleware bypasses `/auth/*` and valid sessions). **Part B/1** tier-aware routing on `/` (Anonymous → 302 `/demo`, Member/Lab → nav grid; sign-in/Sign-out/Lab chip top-right server-rendered). **Part B/2** capability matrix as product copy on `/demo` Findings step (Public-vs-GoS-member 7-row table + Join-GoS CTA — locks ARE the membership pitch). **Part C1** Member-tier capability constants in `capabilities.py` (`CUSTOM_PROMPT`, `BATCH_COMPARE`, `RAG_CORPUS_UPLOAD`, `RESULTS_EXPORT_CSV`); snapshot test pinned. **Part C2a** `capabilities.gate(request, *caps)` imperative helper for runtime cap dispatch; retags `/llm/run-all` → BATCH_COMPARE, `/rag/build-index` → RAG_CORPUS_UPLOAD; inline `gate()` on `/llm/run` (prompt set, repeats>1, device=='both'), `/video/use-source` + `/video/upload` (preset='all_codecs', custom_cmd*), `/image/start` (device in {both, compare_models}). **Part C2b** `curated.py` (CANONICAL_IMAGE_PROMPT / CANONICAL_RAG_QUESTION / CANONICAL_RAG_MODEL); `/image/start`, `/rag/run`, `/rag/run-compare` made `prompt`/`question` optional → curated server-side when absent, `gate(CUSTOM_PROMPT or BATCH_COMPARE)` when present; `/demo` JS dropped hardcoded prompt/question params on image and RAG calls. **/demo navigation dead-end fix**: when no previous result on file (or fetch errors), all four `showPrev*()` poll functions now reveal the per-step back/next/again block — previously the visitor was stuck with only a Run button. **Factorisation contract** held throughout: capability table is policy; routes only call `requires`/`gate`; business modules tier-blind; no runtime "is this default?" detection. **Captured:** CR-019 (unify the in-progress widget — `/demo` rolls its own simpler version per step, while main pages share `wlRenderProgress` + `wlStageList`; ~½ day refactor). 168 tests passing. **Remaining on CR-001:** C2c (UI affordances on workload pages — hide Member-only inputs for Anonymous, `_lock_badge(cap)` helper), D (per-tier queue caps + Anonymous upload size cap), task #10 (retire `WATTLAB_GATE_PASSWORD`).

### Deferred / open
- [ ] **Confidence multiplier grounding** — `variance_green_x`/`variance_yellow_x` (5×/2×) by judgement; statistical grounding pending session with Tanya.
- [ ] **Transcoding apples-to-apples** — bitrate is ABR-controlled; GOP/profile still default-per-encoder. Working session with Simon/Tanya.
- [ ] **Benchmark 2** — codec-natural rate control (CRF/QP) alongside Benchmark 1 (ABR). Add to `WATTLAB_SPEC.md`.
- [x] **Access spine refactor** (audit's #1 recommendation) — `audience.py` + `capabilities.py` + `queue_control.py` shipped S17 parts A/3 + B/3 + C/3. Spine seam (`enqueue(request=None)`) ready for CR-001b.
- [ ] **Dockerize OWL** — isolate from future GoS1 projects. Two-stage plan (FastAPI+VAAPI, then ROCm). Long-term.
- [ ] **Factorise `_HEADER` constant** — mirror `_FOOTER` so `/methodology` and `/queue-status` use the same shape as standard pages.
- [ ] **Guided Tour Findings step** — currently echoes session run; redesign to aggregate across all stored results to surface body-of-evidence learnings (see Key Findings).
- [ ] **RAG visitor upload + corpus PDF view** — see `CHANGE_REQUESTS.md` follow-ups.
- [ ] **Power-user/visitor UX watch** — progressive-disclosure pilot is live across test pages; revisit if a visible density toggle becomes needed.

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
