# WattLab — Claude Code Context File
# Auto-loaded by Claude Code. Keep this current.
# Last updated: 2026-06-01 (Session 37 — root-caused two recurring /demo guided-tour bugs at the structural level: (1) tour-trap on LLM/Image steps — /demo/last/{llm,image} fed compare_models records (no .energy) into the single-run renderer, which bailed before revealNext → fix decouples Next-reveal from rendering (goStep reveals on step entry) + mode-filters the pre-load; (2) findings-embed 404 for every non-Lab visitor — generic /results applies CR-026 visitor scoping to lab-measured finding sources, invisible to tests because the suite runs as Lab → new scoped /findings/source/* carve-out (cited-only, visitor_key=None). + /findings "Beta · under development" badge + back-nav breadcrumbs. NB: S36 (RTX 5080 swap — first light + n=10 NVENC-vs-VAAPI A/B) was journaled in JOURNAL.md but its CLAUDE.md one-liner was only added this session. 391 tests passing.)
# Public name: OWL (Online WattLab). "WattLab" is the legacy/internal/repo name.
# See also:
#   - JOURNAL.md — session-by-session change log (full detail; not auto-loaded)
#   - CHANGE_REQUESTS.md — active CRs (groupings appendix at end maps dependencies)
#   - CHANGE_REQUESTS_CLOSED.md — closed CRs archive (problem statement + closing commit preserved)
#   - TESTING.md — three-tier testing strategy
#   - WATTLAB_SPEC.md — full product spec
#   - GOS1_INFRA.md — server infrastructure, Nextcloud backup, personal stack context
#   - AUDIT_BRIEF.md + AUDIT_RESPONSE.md — pre-CR-001 architecture audit + recommendations
#   - docs/wattlab_traffic_light_confidence.md — Tania §9 statistical framework (CR-028 Phase 2 spec)
#   - docs/wattlab_parameters_audit.md — every settings parameter classified Arbitrary/Empirical/Calibrated/Constrained
#   - docs/input_sensitivity_findings.md — empirical justification for the length-only `/video` picker matrix (S29 pre-CR-047 tests)
#   - REM/CLAUDE.md — sibling project (distributed fleet via Tapo P110 + TP-Link cloud); repo at dom-robinson/stats. OWL = bench, REM = meter on the building.

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
- Cooling: 9 fans total — 5 case (the 5th re-enabled via a Y-splitter S24 2026-05-13), 2 GPU (integrated), 1 CPU (header can take a 2nd), 1 PSU internal. Case + CPU fans run a BIOS curve (quiet below ~70 °C, never observed ramping in any OWL run) and aren't Linux-controllable — see closed CR-005.
- Python: 3.12.3 · Node: 20.x
- Claude Code: `~/.npm-global/bin/claude`, authenticated as nebul2
- Git: bs@ctoic.net / nebul2
- SSH users: simon, tania, dom, marisol, gos (owner)
- External: `ssh -p 2222 user@gos1.duckdns.org`
- Idle power: ~56-58W steady (S24 thermal-recovery probe, post-NVMe + 5th case fan; ~3-5W up on the old ~51-54W), brief drift to ~60-63W after sustained load. `variance_pct` **1.29%** as of 2026-05-14 (S25 overnight calibration, n=32, cooldown 10s — cleanest run on record: idle 2.3% / drift 1.1% / cpu 0.95% / gpu 0.63%); matches the S23 verification value at much larger n. Historical range 1.29–3.62% — calibration-dependent and code-coupled, see JOURNAL.md S25 for the full table.

## Network Topology
```
Bbox Wi-Fi 7 (192.168.1.x)
├── GoS1 (ethernet) → 192.168.1.62
├── MacBook (Wi-Fi)
└── Tapo P110 (Wi-Fi) → 192.168.1.159
```
(Nighthawk RAX120 AP retired 2026-05-26 when the Bbox was upgraded to Wi-Fi 7 — all wireless now goes direct to the Bbox.)

## Thermal Sensors
- One source of truth: `power.read_sensors_dict()` → `{cpu_tctl, gpu_junction, gpu_ppt_w}`. The per-module `read_sensors()` wrappers (video/llm/image_gen/rag) just delegate to it.
- CPU: `data['k10temp-pci-00c3']['Tctl']['temp1_input']` (k10temp is on the CPU bus — name is stable). Read in `power.py` via `subprocess.run(['sensors', '-j'], ...)`.
- GPU: **vendor-abstracted (CR-060).** The GPU half of `read_sensors_dict()` delegates to `gpu.BACKEND.read_gpu_sensors()`, which returns the same `{gpu_junction, gpu_ppt_w}` shape on any card. AMD path: the one amdgpu chip with a `junction` sub-key (discrete card; iGPU has only `edge`/`PPT`) — resolved dynamically by `gpu.AmdBackend._amdgpu_chip` (aliased as `power.amdgpu_chip`), *never* by PCI address (it shifts on PCIe re-enumeration — the S24 NVMe add moved it `amdgpu-pci-0300`→`0400` and silently broke the old lookups), then `['junction']['temp2_input']` + `['PPT']['power1_average']`. Nvidia path: `nvidia-smi --query-gpu=temperature.gpu,power.draw` (temp mapped to `gpu_junction` to keep the schema stable; note `power.draw` is instantaneous vs AMD's `power1_average` — see CR-060 open Q).

## Environment
- `.env` at `/home/gos/wattlab/.env` — gitignored
- Variables: `TAPO_EMAIL`, `TAPO_PASSWORD`, `TAPO_P110_IP`, `OWL_AUTH_SECRET` (CR-001 magic-link signing key), `OWL_GMAIL_USER` + `OWL_GMAIL_APP_PASSWORD` (Gmail SMTP for magic-link delivery)

## Installed Packages
- Python: tapo==0.8.12, python-dotenv, fastapi, uvicorn, python-multipart, torch 2.5.1+rocm6.2, diffusers, transformers, accelerate, pillow
- System: lm-sensors, ffmpeg 6.1.1, nmap. The `/usr/local/bin/ffmpeg-master` build (driven by `ffmpeg_bin`) **already ships the NVENC encoders** (`h264_nvenc`/`hevc_nvenc`/`av1_nvenc`) + the `scale_cuda` filter — so no ffmpeg rebuild is needed for the CR-060 Nvidia swap (resolves the old open Q). `av1_nvenc` exposes no `-profile` knob; `-rc cbr` is the ABR-equivalent. (Still pending for the swap: torch `+rocm6.2`→`+cu12x` wheel + Nvidia driver/CUDA.)
- AI: Ollama 0.20.2 (systemd service, port 11434)
- Models (S30 ladder refresh, 2026-05-27): tinyllama:latest (1.1B, anchor), qwen3:1.7b (modern tiny), qwen3:4b (modern small — also CANONICAL_RAG_MODEL), qwen3:8b (modern 8B), mistral-nemo:12b (French AI lab × NVIDIA — replaced mistral 7B + gemma3:12b), phi4:latest (14B reasoning), gpt-oss:20b (ceiling, MXFP4 partial-offload). Compare-panel = 5 of these: tinyllama / qwen3:4b / mistral-nemo:12b / phi4 / gpt-oss:20b. Retired: mistral 7B + gemma3:12b. x/z-image-turbo (12GB, GPU blocked), x/flux2-klein (5.7GB, CUDA/MLX only).
- Image gen: stabilityai/sd-turbo + stabilityai/sdxl-turbo via diffusers (CPU for SD-Turbo only; GPU via ROCm for both; cached in ~/.cache/huggingface). **Cached but not yet wired into the pipeline (S30 audit):** Sana 0.6B (`Efficient-Large-Model/Sana_600M_512px_diffusers`, ~9 GB on disk fp16+fp32+Gemma-2B text encoder) and SDXL-Lightning 4-step UNet (`ByteDance/SDXL-Lightning`, 2 GB). SD 3.5 Medium (`stabilityai/stable-diffusion-3.5-medium`) is the next add but needs HF token + accepted license (gated). **Avoid on this hw:** FLUX.1-schnell — bitsandbytes NF4 is CUDA-only; ROCm path is ~80s/image + ~35 GB host-RAM spike at quantization load.

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
    ├── video.py                  # P110 + ffmpeg + thermals + focus mode (GPU presets via gpu.BACKEND)
    ├── llm.py                    # Ollama inference + P110 measurement (GPU-agnostic via Ollama)
    ├── image_gen.py              # SD-Turbo CPU diffusion + P110 measurement
    ├── persist.py                # Flat-file result storage + CSV/JSON export (stamps gpu_hardware)
    ├── settings.py               # Lab config (settings.json)
    ├── sources.py                # Pre-loaded test content registry
    ├── gpu.py                    # CR-060 — GPU vendor abstraction (AMD VAAPI/ROCm ↔ Nvidia NVENC/CUDA); auto-detected at import into gpu.BACKEND
    └── power.py                  # Power measurement interface (Tapo P110); GPU telemetry delegates to gpu.py
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
CR-028 Phase 2 CI model (Tania §9 v2, shipped) — single implementation in `confidence.py`, shared by all four modules. Per-run "can this be told apart from idle?":
- `SE_final = max(SE_calibrated, SE_per_run) + SE_drift`; `SE_calibrated = variance_idle_pct/100·w_base·√(1/n_base+1/n_task)`; `SE_per_run = √(σ²_base/n_base + σ²_task/n_task)`; `SE_drift = variance_idle_drift_pct/100·w_base` (additive = worst-case, per the 2026-05-22 decision).
- `confidence_positive = Φ(ΔW/SE_final)`. 🟢 `≥conf_positive_green (0.95)` AND `n_task≥conf_green_polls (10)`; 🟡 `≥conf_positive_yellow (0.80)` AND `n_task≥conf_yellow_polls (5)`; 🔴 otherwise.
- Option C: only `variance_idle_pct` feeds the single-run flag; `variance_cpu_pct`/`variance_gpu_pct` are run-level repeatability CVs reserved for a future aggregate layer. First pass: raw n + 1.96 (autocorrelation/Student-t are future refinements).
- Requires raw `baseline_samples_w` + `task_samples_w` (now persisted in every result's energy dict). **Legacy fallback:** results without raw samples keep the old variance-threshold flag (`variance_green_x`/`variance_yellow_x`); `confidence()` records `method` = `ci` | `variance`.
- `confidence(delta_w, poll_count, w_base, baseline_samples_w=…, task_samples_w=…)` — `from confidence import confidence` in video / llm / image_gen / rag. Absorbed CR-020 (per-run baseline-CV gate) and the 5×/2× threshold grounding.

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

**Active CRs:** 15 entries in `CHANGE_REQUESTS.md`. Closed CRs (with original problem statements + closing commit) live in `CHANGE_REQUESTS_CLOSED.md` — that file is now the single source of truth for "what shipped and when." This header keeps only the recent-arc one-liners below.

### Recent sessions (one-line summary; full detail in JOURNAL.md + git log)
Earlier sessions (S1–S25) live in `JOURNAL.md`; recent arc below.
- **S26 (2026-05-20):** Credibility & recruitment bundle — CR-037 (AI→streaming tethering), CR-040 (per-result reproduce.zip), CR-027 (capability matrix). 218 → 234 tests.
- **S27 (2026-05-21):** Versioning + build stamp (`VERSION` + `version.py`, footer + result-stamping). 234 → 237 tests.
- **S28 (2026-05-22):** CR-044 (VMAF) + CR-028 Phase 2 (Tania §9 v2 — `confidence.py`, shared CI model, raw samples persisted). 237 → 272 tests. Key Finding ⭐: AV1 hw vs sw at same 1500 kbps.
- **S29 (2026-05-26):** CR-046 Phase 1 (BBB preloaded) + CR-047 (variants schema for `/video` Source picker) + VMAF stage in progress widget. 272 → 290 tests.
- **S30 (2026-05-27):** Picker UX polish — source vignettes + CR-033 demo chip-row + CR-046 close-out + CR-047 source-key on result JSON. **290 tests** (refactor + UI only).
- **S31 (2026-05-27 overnight):** AI-comparison trilogy — CR-048 (`/llm/compare`) + CR-049 (`/rag/compare`) + CR-050 (dynamic model catalog + active-probe thermal floor + Ollama eviction + N-way `/image/compare`). 290 tests.
- **S32 (2026-05-27):** CR-051 RAG corpus self-service (Member upload + delete, audit log, ownership matrix). 292 → 307 tests.
- **S32 close-out (2026-05-27 evening):** Findings-chain shipped behind `findings_enabled` flag — CR-054 (data model + AV1 worked example), CR-055 (`/findings` index), CR-056 (bulk import of 5 more findings), CR-058 (`/demo` step 7 rewire). CR-057 (home-page repositioning) drafted, awaiting lab UX review. CR-012 also closed — variance + thermal-probe drift journals (`results/{variance,diagnostics}/history.jsonl` via new `persist.append_history_line`). 307 → 339 tests.
- **S33 (2026-05-28):** S32 close-out + md tidy + `/findings` bug fixes (wlCarbonStrip include; sequential embed hydration to dodge nginx 3-conn 429s) + kicked off overnight variance calibration. 339 tests.
- **S34 (2026-05-28):** CR-061 in-app benchmark orchestrator (`benchmark.py` + `results/benchmark/`, multi-step variance→video→llm→rag→image run) + CR-029 §2 encode normalization.
- **S35 (2026-05-29):** CR-060 GPU-backend abstraction shipped pre-swap (`gpu.py`; AMD byte-identical; auto-detect + `gpu_hardware` stamp). Overnight benchmark `e29ccef7` analysed → AMD pre-swap baseline frozen (`docs/gpu_swap_amd_baseline.md`). 339 → 385 tests.
- **S36 (2026-05-29):** GPU swap — RTX 5080 first light. `gpu.BACKEND` auto-resolved to Nvidia with zero code edits (CR-060 as designed). Vendor-neutral wall idle ~57–59 W → **~79 W (+20 W / +34%)** — real but display-state-sensitive (blanked P8 ~79 W vs active P3 ~101 W); the GPU-sensor 4→18 W jump is mostly a board-vs-core sensor-scope artifact, not hardware. Overnight n=10 post-swap benchmark (`f56dfa77`): NVENC beats VAAPI on energy (H.264 −42%, H.265 −22%, AV1 −25%) and equals-or-beats quality in 5/6 (NVENC AV1 **+4.3 VMAF** on animation). Idle↔load crossover: +20 W idle = 480 Wh/day → swap is energy-positive only for H.264-heavy near-saturated loads, never for H.265 → reframed as a capability/quality/speed upgrade, not a same-workload energy win. AMD baseline VMAF correction. CR-061 Member benchmark view + `/benchmark` nav link.
- **S37 (2026-06-01):** Root-caused two recurring `/demo` guided-tour bugs. (1) Tour trapped on LLM/Image steps — `/demo/last/{llm,image}` fed `compare_models` records (no `.energy`) into the single-run renderer, which bailed before `revealNext`; fix decouples Next-reveal from rendering (`goStep` reveals on entry) + mode-filters the pre-load. (2) Findings embeds 404'd for every non-Lab visitor — generic `/results` applies CR-026 visitor scoping to lab-measured finding sources; **invisible to tests because the suite runs as Lab** → new scoped `/findings/source/*` carve-out (cited-only, `visitor_key=None`). + `/findings` "Beta" badge + back-nav. 389 → 392 tests.
- **S38 (2026-06-02):** **CR-062** omnibus (umbrella, created+closed). Headline = **unified cooldown / wait-for-idle**: `cooldown_wait_for_idle` toggle + `power.cooldown_between_runs` as the single path for every inter-pass cooldown (fixed vs active-probe idle-floor; variance stays fixed via `respect_toggle=False`); idle-wait timeout dialog (Wait/Run/Cancel + watchdog) for attended Lab compares; per-result `cooldowns[]` stamping; result-card summary + live "Cooldowns done" log; toggle-aware `Rest (→ idle)` labels. Plus: `/video` **codec split** (Compare codecs CPU / GPU / all — `run_codecs_single_measurement` + shared `wlRenderCodecsSingle`); **image compare 2-of-3 fix** (fresh card routed to N-aware `wlRenderImageCard`); **Lab test-data delete** panel (`DELETE /results/{type}/{id}` + /settings dropdown); **queue resume** routing (`enqueue(page=)` + `resume_page`; compare pages gained `?job=` handlers); **JS bundling fix** (cooldown helpers → `_CARBON_JS`; froze compare progress via ReferenceError) + `test_js_bundling.py` guard. 392 → 427 tests. **Known issue:** `/video` `Rest (→ idle)` live counter renders but doesn't tick (deferred). Infra: GoS1 `eno2` RTL8125 link flaps (suspect EEE/2.5G) intermittently kill all remote access — see CR-062 note.

### Deferred / open (active items only — completed ones removed; see CHANGE_REQUESTS_CLOSED.md / JOURNAL.md for history)
- **Transcoding apples-to-apples (GOP / profile)** — see **CR-029** sub-item 2 (Tania-led); VMAF (CR-044) now makes the gap measurable (see AV1 hw-vs-sw Key Finding).
- **Benchmark 2** — codec-natural rate control (CRF/QP). Folded into **CR-045** as its V1 ("Constant quality (per-codec)").
- **Dockerize OWL** — see **CR-031** sub-section 3 (containerisation, two-stage plan: FastAPI+VAAPI, then ROCm).
- **Guided Tour Findings step** — currently echoes session run; redesign to aggregate across all stored results to surface body-of-evidence learnings (see Key Findings).
- **RAG visitor upload + corpus PDF view** — see `CHANGE_REQUESTS.md` follow-ups.
- **Power-user/visitor UX watch** — progressive-disclosure pilot live across test pages; revisit if a visible density toggle becomes needed.

## Key Findings to Date

Canonical store is the catalog at **`/findings`** (CR-054/055/056, shipped S32). Each finding is one markdown file under `docs/findings/<slug>.md` with a strict schema (frontmatter + analysis prose) and cites a real `source_result_id` on disk. The catalog is authoritative; **don't restate findings as prose here** — drift between this file and the finding markdown is a known hazard (see memory: claude-md-prose-can-drift-from-disk).

Slugs currently published (`docs/findings/`):

- `abr-all-codecs-meridian-120s` — ABR all-codecs benchmark (n=1 on disk; the popular "n=3" claim is unsupported, caveat noted)
- `av1-hw-sw-vmaf-tradeoff` ⭐ — energy↔quality tradeoff at same 1500 kbps (the canonical use-case for VMAF + CR-045)
- `input-master-sensitivity` — input bitrate / codec-of-origin sensitivity (CR-047 pre-test)
- `llm-cold-inference-mwh-per-token` 🟡 — pre-S30 panel, re-measurement on the new ladder = future v2
- `rag-faithfulness-rem-question` 🟡 — pre-S30 panel, single observed hallucination (n=1, not a statistical claim)
- `sd-turbo-cpu-image-first-run` — first-image energy on CPU

Not catalogued (don't fit the strict "cite one stored measurement" schema; live on `/methodology`):

- **French grid evolution (S18):** monthly lifecycle gCO2e/kWh from Eco2mix × IPCC AR6 factors. Jan 2020 65.8 → Jun 2024 26.9 (55% reduction in 2 yrs); derived from `carbon.HISTORICAL_INTENSITY`, not a measurement run.
- **CR-016 methodology insight:** Eco2mix's `taux_co2` is direct combustion only — never compare it to lifecycle annual means. Both paths now use lifecycle factors.

## Visual Identity
- Project mark: owl SVG at `wattlab_service/static/owl.svg` (2.4KB teal/green geometric).
- Org mark: GoS round bug, footer only (`_LOGO`).
- Dark theme: `#0a0a0a` bg, `#00ff99` accent — all tokens centralised in `_BASE_STYLES` (`main.py:~276`).
- For external/family theming see `rem-theme.css` (drop-in stylesheet that re-skins REM with OWL palette).
