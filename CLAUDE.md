# WattLab — Claude Code Context File
# Auto-loaded by Claude Code. Keep this current.
# Last updated: 2026-05-27 (Session 32 — CR-051 RAG corpus self-service: Member upload + delete, corpus_manifest.py with audit log + ownership matrix, per-Member quotas, hardened upload path (size cap, %PDF magic, sanitisation, traversal guards). 101 existing PDFs migrated as origin=Lab. New RAG_CORPUS_DELETE_OWN capability. Active 15 CRs, 307 tests.)
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

**Active CRs:** 15 entries in `CHANGE_REQUESTS.md`. **Recently closed (S30 + S31, 2026-05-26 → 2026-05-27):** CR-048 — `/llm/compare` page (hybrid showcase + member "Try your own", Wh-per-correct-answer headline, mWh/tok kept as supporting column to expose the perverse incentive). CR-049 — `/rag/compare` sibling page, same shape, BBC corpus prompt as canonical showcase. CR-050 — dynamic model catalog (`model_catalog.py` auto-discovers from `ollama list` and HF cache, per-surface enable lists on `/settings`); active-probe thermal-floor cooldown (`power.wait_for_thermal_floor`, ±3 W of cold reference, asymmetric "at or below floor" settle); Ollama `keep_alive` eviction between models (`llm.unload_all_loaded_models`) so VRAM-resident models don't inflate the floor by ~60 W each; 🔴 confidence rows greyed in tables but excluded from cheapest pick + bust card + charts; side-by-side Wh-vs-params + mWh/tok-vs-params charts gated at ≥3 trusted-correct; N-way `/image/compare` (iterates every enabled image model with the same thermal-floor cooldown); 4 Hz local UI ticker for smooth cooldown counter between server polls. Also S30: CR-033 (curated demo chip-row H.265/AV1 on `/demo`), CR-046 (BBB preloaded + generic vignette — the FOKUS-match angle was investigated and dropped, since the FOKUS header is post-processed BBB with laser-eye effects so no literal frame-match is meaningful), CR-047 (parent-source + variants schema for `/video` Source picker, collapsed to length-axis after empirical pre-test in `docs/input_sensitivity_findings.md`). See "Groupings & dependencies" appendix at end for the dependency map. Closed CRs (with original problem statements) in `CHANGE_REQUESTS_CLOSED.md`.

### Recent sessions (one-line summary; full detail in JOURNAL.md + git log)
Earlier sessions (S1–S25) live in `JOURNAL.md`; recent arc below.
- **S26 (2026-05-20):** Credibility & recruitment bundle — external-links registry in `main.py`, `canonical.py` + Meridian-120s baseline pin, **CR-037** closed (AI→streaming tethering: "≈ N× a 120 s 1080p H.265 GPU encode" enrichment + 5-principle expander), **CR-040** closed video-only (per-result reproduce.zip + button), **CR-027** verified-closed (found already shipped). 218 → 234 tests.
- **S27 (2026-05-21):** Versioning + build stamp (`VERSION 0.4.0` + `version.py`, footer on every page, `owl_version` stamped on every result); CR-037 readout bug fixed in bespoke live renderers (`renderLLMSingle`/`renderLLMAll`/`/image renderResult`); CR-027/037/040 bodies migrated to `CHANGE_REQUESTS_CLOSED.md`. 234 → 237 tests.
- **S28 (2026-05-22):** **CR-044 VMAF** — perceptual quality on multi-video compare cards (terminal pass, excluded from draw; VAAPI 1080→1088 crop fix). **CR-028 Phase 2** (Tania §9 v2) — shared `confidence.py` CI model (`SE_final = max(SE_calibrated, SE_per_run) + SE_drift`, `confidence_positive = Φ(z)`); raw baseline+task samples persisted; legacy variance fallback; absorbed CR-020. Key Finding ⭐: AV1 hw vs sw at same 1500 kbps. CSV spreadsheet-safety. **CR-045 captured**; CR-028 + CR-044 closed. 237 → **272 tests**.
- **S30 (2026-05-27):** Picker UX polish package, riding on the S29 variants schema. **Source vignettes** — small JPEG thumbnails (~3-6 KB each, 160 px wide) extracted from each source via ffmpeg (`gos.jpg` t=25 s, `meridian.jpg` t=60 s, `bbb.jpg` t=180 s), stored under `wattlab_service/static/source_vignettes/`, wired into the `vignette` field on each parent in `sources.py`. `_video_source_picker_html()` renders them as 32 px-high `<img>` left of the parent header. Closes **CR-046** (BBB-preloaded + generic vignette): the originally-sketched FOKUS-matched vignette angle was explored via dHash perceptual hashing then dropped after visual confirmation that the FOKUS event header is post-processed BBB content (added laser-eye effects), so no literal frame-match is meaningful — the generic `bbb.jpg` already satisfies the identifying-thumbnail goal. **CR-033 demo chip-row** — `/demo` step 1's video block gains a two-chip codec selector (H.265 default, AV1 alternate), both on `meridian_120s`; `selectDemoCodec()` updates chip styling + the run-button label, `runDemoVideo()` reads the choice to dispatch `h265_both` vs `av1_both`. Result-card path needed zero changes (codec-agnostic). **CR-047 follow-up** — `run_job` now takes `source_key=`, stamps `result["source"] = {key, parent}` on persisted result JSON when the job came from a preloaded source; legacy `/video/upload` (custom file) leaves it unset. Unlocks future filtering / analytics on the variant schema. Parallel session shipped **CR-048** (`/llm/compare` page, energy per correct answer, Phase 1) which is the latest active capture (Phase 2 = P110 backfill + RAG mirror). **290 tests** holding steady (no new test files; refactor + UI only).
- **S29 (2026-05-26):** CLAUDE.md pruning pass + FOKUS Berlin prep + variants schema. **CR-046 Phase 1** — Big Buck Bunny preloaded: 4K full master from archive.org (642 MB) + first-120 s stream-copy extract; both under a new `bbb` parent in `sources.py`. **CR-047** — parent-source + variants schema for `/video` Source picker, killing the hardcoded radio block (`main.py:~2807-2845`); `_video_source_picker_html()` renders from `sources.get_grouped_sources()` so adding a variant only requires editing `sources.py`. Picker now grouped by parent header ("Big Buck Bunny 4K · CC BY 3.0") with short variant labels ("2 min extract") underneath. **VMAF stage** added to the encode progress widget (`_BOTH_STAGES` / `_ALL_STAGES` + `stage="vmaf"` server-side + `vmaf_done`/`vmaf_total` poll fields so "VMAF · 1 of 2 encodes scored" surfaces during the post-encode quality pass — fixed the "looks like it restarted" UX). Warning text on full-length radios bumped to reflect VMAF cost (Meridian-full ~14-18 min incl. VMAF; BBB-full ~12-16 min). **Pre-CR-047 design tests** — input-bitrate sensitivity (CRF span, same codec) and codec-of-origin sensitivity (industry-typical H.264 5 / H.265 3 / AV1 2 Mbps) both run; first axis flat (1.7 % CPU, 4.9 % GPU — at noise), second moderate (3.4 % CPU, 10.3 % GPU — AV1 carries the jump). Justifies the picker shape: **2 variants per parent** (full + 2-min extract), plus an optional vignette (still image) on the parent for UI friendliness — vignette is orthogonal to variants, not a third slot. All in `docs/input_sensitivity_findings.md`. 272 → **290 tests**.

### Deferred / open (active items only — completed ones removed; see CHANGE_REQUESTS_CLOSED.md / JOURNAL.md for history)
- **Transcoding apples-to-apples (GOP / profile)** — see **CR-029** sub-item 2 (Tania-led); VMAF (CR-044) now makes the gap measurable (see AV1 hw-vs-sw Key Finding).
- **Benchmark 2** — codec-natural rate control (CRF/QP). Folded into **CR-045** as its V1 ("Constant quality (per-codec)").
- **Dockerize OWL** — see **CR-031** sub-section 3 (containerisation, two-stage plan: FastAPI+VAAPI, then ROCm).
- **Guided Tour Findings step** — currently echoes session run; redesign to aggregate across all stored results to surface body-of-evidence learnings (see Key Findings).
- **RAG visitor upload + corpus PDF view** — see `CHANGE_REQUESTS.md` follow-ups.
- **Power-user/visitor UX watch** — progressive-disclosure pilot live across test pages; revisit if a visible density toggle becomes needed.

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

### Video — AV1 hardware vs software: the energy↔quality tradeoff ⭐ (S28, CR-044 VMAF, clean ≥10s 🟢 run `e18a9d57` 2026-05-22)
At the **same 1500 kbps ABR target**, on Meridian-120s, all six encodes 🟢:
- **SVT-AV1 (CPU, libsvtav1):** 14.51 MB · **VMAF 92.74** · 0.71 Wh
- **av1_vaapi (GPU, RX 7800 XT):** 20.34 MB · **VMAF 90.79** · 0.32 Wh
- **Headline:** hardware AV1 uses **~55% less energy** (and is ~2.3× faster) **but** delivers **~2 VMAF lower** *and* a **~40% larger file** — it hits the bitrate target while SVT-AV1 undershoots it (~967 kbps actual) yet still scores higher. So SVT-AV1 is markedly more **bit-efficient**; the hardware encoder buys speed/energy by giving up compression quality. The direction is consistent on a noisier tiny-clip run (7.63 vs 9.16 MB; 91.51 vs 89.70 VMAF), slightly more pronounced at length.
- AV1 is the codec where the hw/sw gap shows; for H.264/H.265 the CPU↔GPU VMAF gap is ≤2 and within noise (H.264 94.0/92.1, H.265 94.1/92.0). **First OWL result that pairs energy with a measured quality axis** — the canonical use-case for CR-044 (VMAF) and the motivation for CR-045 (same-quality compare).
- *Caveat:* cross-codec VMAF here is NOT apples-to-apples (different per-codec bitrate targets); only the within-AV1 CPU-vs-GPU comparison (same 1500 kbps) is a fair quality read. Tiny clips (≤~4 s) are unreliable for this and now correctly flag 🔴.

### Video — Input-master sensitivity (S29, 2026-05-26, CR-047 pre-test)
On a `h265_both` re-encode of a 2-min 1080p source, neither input bitrate nor input codec moves the CPU encode energy needle (≤3.4 % spread, ~2-3× noise floor). GPU side shows a modest codec-of-origin effect (10.3 %), but only **AV1 carries the jump** — H.264↔H.265 is flat. **Why:** libx265 encode dominates CPU runtime (~95 % of total); on the GPU path the encode is so fast (~12 s) that the still-software decoder becomes the proportional bottleneck. Bonus VMAF finding: higher-quality source codec → higher output VMAF *even at lower bitrate* — AV1 at 2.3 Mbps gives VMAF 88.2 (GPU) vs H.264 at 5.1 Mbps giving 87.0. Justified collapsing CR-047's picker matrix from 5 candidate variant slots per source to 2 (full + 2-min extract); the vignette (parent-level still for UI friendliness) is orthogonal, not a variant. Full data in `docs/input_sensitivity_findings.md`.

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
