# WattLab — Claude Code Context File
# Auto-loaded by Claude Code. Keep this current — and keep it LEAN: one-liners here, detail in JOURNAL.md.
# Last updated: 2026-09-03 (S73: ten devices — Xiaomi Gen 2 revived + Gen 3 onboarded, Apple TV back;
#   synchronised four-box playback with a per-box content clock; two-axis STB campaign at n=3; bitrate
#   ladder; 4K/HDR arms; loop-validity finding; headless = no-sink regime; football sports tier.
#   See JOURNAL S73 + docs/intra_content_sync_2026-09-03.md. Earlier session headers live in JOURNAL.)

# Public name: OWL (Online WattLab). "WattLab" is the legacy/internal/repo name.
# See also:
#   - ARCHITECTURE.md — module map + request/job flows (the orientation doc; READ FIRST for code work)
#   - JOURNAL.md — session-by-session change log (full detail; newest first)
#   - CHANGE_REQUESTS.md — 28 active CRs (+ backlog notes + groupings appendix); CHANGE_REQUESTS_CLOSED.md — closed archive
#   - TESTING.md — pytest suite (1074 tests) + manual checklist · WATTLAB_SPEC.md — historical design intent
#   - GOS1_INFRA.md — server infra, backups, incident log · docs/result_envelope.md — mode→renderer contract
#   - docs/architecture_review_2026-06.md (refactor rationale, executed S41–42) · AUDIT_BRIEF/RESPONSE.md (2026-05 audit)
#   - OWL_AUDIT.md — 2026-07-05 nine-dimension re-audit → CR-066–069 + CR-031/008 updates; disposition in AUDIT_RESPONSE.md
#   - docs/wattlab_traffic_light_confidence.md (Tania §9 spec) · docs/wattlab_parameters_audit.md (param taxonomy)
#   - docs/input_sensitivity_findings.md (CR-047 pre-test) · docs/dual_meter_pretest_findings.md (CR-065 pre-test)
#   - docs/gpu_swap_amd_baseline.md (frozen AMD-era data)
#   - REM/CLAUDE.md — sibling project (Tapo fleet via TP-Link cloud). OWL = bench, REM = field meter; LEM = Local
#     Energy Measurement (mW-lossless local plug polling; repos on the Greening-of-Streaming GitHub org).
#   - docs/vp9_oneoff_2026-08.md (+ docs/vp9_rerun_2026-08-17/) — the VP9 report the LinkedIn thread revolves around
#   - docs/methodology_vs_code_2026-08-19.md — methodology-vs-implementation inconsistency journal (owner review)
#   - docs/TOOLSET_STRATEGY.md — decode-rig toolset decision doc · docs/smpte_2026/ — SMPTE 2026 tables
#   - .claude/skills/ — operational skills (bench-preflight, decode-campaign, ship-service-change, finding-draft, session-close)

## Project Identity
- **Name:** WattLab · **Repo:** https://github.com/greeningofstreaming/wattlab
- **Host:** GoS1 — Ubuntu 24, `192.168.1.62`, externally `gos1.duckdns.org:2222`
- **Owner:** GoS (Greening of Streaming), French NGO loi 1901
- **Mission:** Measure environmental impact of streaming. Neutral, technically credible.

## GoS Framing (always apply)
- If it can't be measured, it shouldn't be asserted. (The old "not eco-warriors" line is retired from public copy.)
- Separate device / network / data center / production+storage impacts explicitly.
- State scoping assumptions. Signal uncertainty. Traffic Light Confidence on all claims.
- Audience: CTOs, operators, infrastructure players, policymakers.
- Board steer (2026-05-11): AI jobs stay tethered to streaming; carbon = indicative add-on, hard-badged, never
  quoted as GoS data; OWL = member-recruitment loss-leader, not a production tool; lightweight over ambitious.
- Publication rule (2026-08-17): finish with a few affirmations we can stand behind (n + CI stated, operating
  point named); Tania checks before Ben posts; credit the critics.
- Primary-data bar (WattLab call 2026-09-03): **n=3 is the minimum for anything that leaves the room**;
  the traffic light keeps its single meaning (website / white papers / LinkedIn) — academic papers report
  the actual statistics (r, CI, n) and never overstate; the r threshold for "primary" data is undecided
  (Tania to advise; the same n/r bar is GoS's proposed input to the Policy Lab / IEEE methodology).

## GoS1 Server
- CPU: AMD Ryzen 9 7900, 24 cores · RAM: 61GB · Python 3.12.3 · Node 20.x
- GPU: **NVIDIA RTX 5080 (16GB) — NVENC (video) + CUDA (AI)**; swapped from AMD RX 7800 XT 2026-05-29 (S36, CR-060).
  AMD-era baselines frozen in `docs/gpu_swap_amd_baseline.md`; rollback procedure in `docs/gpu_swap_checklist.md`.
- Disk: 500GB NVMe system (`/`) + 4TB NVMe data (`/srv/data`). `/srv/data/owl/{test_content,results,corpus,.chroma}`
  hold OWL bulk data, symlinked back into the repo. ⚠ HF cache (27G) + Ollama models (54G) still on the system disk.
- Idle power: **~79 W display-blanked / ~101 W active display** since the GPU swap (+20 W vs AMD era ~57 W) —
  idle↔load crossover means the swap is a capability/quality upgrade, not a same-workload energy win.
- Variance calibration: live values in `settings.json` (recal 2026-06-10: idle 1.84%, n=20, cooldown 50s).
  Ambient-sensitive (2–6× swing in heat waves) — calibrate under normal ambient only.
- Location: **basement since 2026-06-19** (cooler, steadier ambient; idle floor there still to re-confirm; see GOS1_INFRA.md).

## Network Topology
Bbox Wi-Fi 7 (192.168.1.x) ── GoS1 ethernet `.62` · MacBook Wi-Fi · Tapo P110 ×2 daisy-chained (CR-065):
wall → `.159` (outer, original) → `.91` (inner, primary, "GoS1b-server") → GoS1
(Server + both plugs **fixed/reserved Bbox IPs** since 2026-06-19; **every rig/lab address reserved 2026-08-26** —
table in decode_bench/README.md §Network. External-access incidents + DuckDNS updater: see GOS1_INFRA.md.)

## Thermal Sensors
- One source of truth: `power.read_sensors_dict()` → `{cpu_tctl, gpu_junction, gpu_ppt_w}`; per-module
  `read_sensors()` wrappers delegate to it.
- CPU: `sensors -j` → `k10temp-pci-00c3.Tctl` (CPU-bus chip, name stable).
- GPU: vendor-abstracted via `gpu.BACKEND.read_gpu_sensors()` (CR-060). Nvidia path: `nvidia-smi` temp + power
  (`power.draw` is instantaneous vs AMD's `power1_average` — open sampling-semantics question, see closed CR-060).
  AMD path (rollback): amdgpu chip resolved dynamically, never by PCI address (re-enumeration shifts it).

## Environment
- `.env` at repo root (gitignored; `.env.example` is the tracked template): `TAPO_EMAIL`, `TAPO_PASSWORD`,
  `TAPO_P110_IP` (inner/primary plug) + `TAPO_P110_IP_2` (outer plug, optional — CR-065 daisy-chain),
  `OWL_AUTH_SECRET` (magic-link signing), `OWL_SMTP_USER` + `OWL_SMTP_PASSWORD` (Gmail SMTP
  for magic-link delivery — note: SMTP names, not the old OWL_GMAIL_* ones).

## Installed Packages & Models
- Python: fastapi/uvicorn, tapo 0.8.12, **torch 2.11.0+cu128**, diffusers/transformers/accelerate, chroma.
- System: lm-sensors, ffmpeg 6.1.1 + `/usr/local/bin/ffmpeg-master` (driven by `ffmpeg_bin`; ships NVENC
  encoders + `scale_cuda`; `av1_nvenc` has no `-profile` knob, `-rc cbr` is the ABR-equivalent).
- Ollama 0.20.2 (port 11434). Ladder (S30): tinyllama (anchor, **off the default panel**), qwen3:1.7b/4b/8b,
  mistral-nemo:12b, phi4, gpt-oss:20b. Live panel = `llm_enabled_models` in settings.json (currently the 6
  non-tinyllama ones). CANONICAL_RAG_MODEL = qwen3:4b. **MODELS dicts are live views (CR-050) — never edit as
  literals; add/remove via `ollama pull` or settings.**
- Image gen (diffusers, `image_enabled_models`): sd-turbo, sdxl-turbo, sdxl-lightning, sana-600m. SD 3.5 Medium
  is the next add (gated, needs HF token). Avoid FLUX.1-schnell NF4 paths on non-CUDA (see memory).
- NR-VQA sandbox (runtime dep, NOT in git): `/srv/data/owl/vqa-eval/` = CompressedVQA-HDR + venv + weights;
  feeds `pixop.probe_vqa_nr` via subprocess; settings `vqa_enabled`/`vqa_dir`/`vqa_timeout_s`.
  ⚠ `NR/VQA_NR.py` is locally patched (`< video_length_read`, ~line 59) — upstream crashes on 23.976 fps;
  reapply after any re-clone. Fail-softs to "no score" if missing.

## Repo Structure
**See ARCHITECTURE.md for the module map** (main.py = ~640-line app assembly; eighteen flat `routes_*.py` feature
modules incl. `routes_decode.py`/`routes_rem.py`; rig side = `rig.py` (state machine + plugs), `decode_run.py`
(templates → bench configs), `decode_batch.py`, `lg.py` (webOS), `origin_control.py` (:8123 origin child), `idle_wait.py`;
`runtime.py` jobs/telemetry; `ui.py` page chrome + serve-time wording; measurement modules `video.py`
`llm.py` `image_gen.py` `rag.py`; `power.py`/`gpu.py` instrumentation; `persist.py`/`settings.py` storage).
Key paths: `wattlab_service/static/wl-*.js` (shared JS bundles, sha cache-busted, configured via `/ui-config.js`);
`results/` → `/srv/data/owl/results` (per-result JSON, `{type}/{date}_{job_id}.json`); `test_content/`, `corpus/`,
`.chroma/` similarly symlinked; `docs/findings/` (finding markdowns); `infra/` (nginx), `systemd/`, `bin/` (ops
scripts, see bin/README.md). Feature modules NEVER import main; tests monkeypatch the routes_* module that
binds a name, not main.

## Measurement Protocol
1. Focus mode: stop background timers (sudoers: `/etc/sudoers.d/wattlab-focus`)
2. LLM only: unload model (keep_alive=0), sleep 3s
3. Baseline: `baseline_polls` × 1 s → W_base (live value 5; rolling floor `power.LAST_W_BASE`, CR-070)
4. Lock: `/tmp/gos-measure.lock`
5. Task: ffmpeg (nice -n -5) or Ollama API
6. Poll P110(s) + sensors at 1s (dual-meter: 2nd plug staggered 0.5s, per-meter ΔW combine — CR-065)
7. Compute: ΔW, ΔE = ΔW × (ΔT/3600) Wh, mWh/token (LLM)
8. Write result JSON to results/{type}/{date}_{job_id}.json
9. Focus exit: parallel timer restart (ThreadPoolExecutor + run_in_executor)

Focus-mode timers: sysstat-collect, anacron, fwupd-refresh, apt-daily{,-upgrade}, man-db, motd-news,
update-notifier-download.
Cooldowns route through ONE dispatcher: execution `power.cooldown_between_runs`, wording `_bake_durations`
tokens, footer `wlCooldownSummary` (test-guarded — no raw sleeps or hardcoded `{COOLDOWN_S}s`).

## Traffic Light Confidence
Single implementation `confidence.py`, shared by all four measurement modules (CR-028 Phase 2, Tania §9 v2 —
full math in `docs/wattlab_traffic_light_confidence.md`). Contract:
`confidence(delta_w, poll_count, w_base, baseline_samples_w=…, task_samples_w=…)` → `confidence_positive = Φ(ΔW/SE)`;
🟢 ≥0.95 AND n_task≥10 · 🟡 ≥0.80 AND n_task≥5 · 🔴 otherwise (thresholds are settings). Raw samples are persisted
in every result; legacy results without them fall back to the old variance-threshold flag (`method` = ci|variance; ci2 = CR-065 dual-meter per-meter combine).

## Scope Statements
Video: "Device layer only (GoS1 server). Network, CDN, and CPE excluded."
LLM: "Device layer only (GoS1 server). Network and CPE excluded. No amortised training cost."

## Services & URLs
wattlab (systemd, port 8000, 1 worker — `sudo systemctl restart wattlab` is in Claude's sudoers since 2026-07-07; never restart mid-job) · ollama (11434).
LAN `http://192.168.1.62:8000` · public `https://wattlab.greeningofstreaming.org` (nginx + certbot).
Pages: `/video /llm /rag /image /demo /findings /benchmark /enhance-run /enhance-run/ladder /video/budget /decode
/decode/batches /decode/batch/{id} /prepare-rem /settings /queue-status /methodology /carbon /privacy`.
Hidden: `/audience` (Lab-only visit dashboard — anonymous aggregate counts from analytics.py; not in any nav).
Auth tiers (CR-001): Anonymous (public) · Member (magic-link, allowlist `data/members.json`) · Lab (LAN/loopback).
Policy lives ONLY in `capabilities.py`; routes never compare tiers. Tests run as Lab — reason about
Anonymous/Member explicitly; probe Anonymous with a real public IP header like 8.8.8.8 (Python ≥3.12.4 counts
TEST-NET 203.0.113.x as private → Lab).

## Roadmap
**Phases 1–8 shipped** (research integrity → measurement quality → settings → demo → image gen → public access →
tour/credibility → RAG). **Active: 28 CRs** in CHANGE_REQUESTS.md — newest CR-078–083 (device×codec reliability
survey, HD/4K ladder × resolution sweep, decode-pipeline provenance survey, football sports tier + all-night
campaign, Demo Content page, Lab-session reservations); each CR carries its own status; closed archive in
CHANGE_REQUESTS_CLOSED.md.

### Recent sessions (one line each — full entries in JOURNAL.md, which also holds the condensed S26–S66 index)
- S69 (08-26→27): SMPTE-desk handoff; adb path fixed; SoC audit (GTV = MT8696 like the Fire TV); MAC target follower;
  Apple TV onboarded over pyatv (VLC via Companion) and CR-075 closed 🟢 (AV1/VP9 +29 % on A10X); screen map in /settings.
- S70–S71 (08-28→29, Tania): SMPTE encode-parity gap closure (240-row dataset, VMAF v0/v1 mismatch fixed) + ReadySetGo leg.
- S72 (08-29): Roku onboarded (ECP, Dom's channel); switch-install re-cabling; two marker-encoder bugs fixed (HEVC coded
  height, VP9 container); LinkedIn VP9 claim corrected (AV1/VP9 tie on Apple TV and Roku).
- S73 (09-02→03): Xiaomi Gen 2 revived (PSU fault) + Gen 3 onboarded, Just Player pinned 0.196; two-axis STB campaign
  at n=3 (Axis A: GTV +0.26–0.43 W over Fire TV on the same MT8696; Axis B: Gen 3 −0.30…−0.37 W on HEVC/AV1/VP9);
  **sync mechanism** (looped marker clip + file rendezvous + media3 content clock → intra-content power: cross-box
  r≈0.8 at 1080p, single-box SNR 2–3 at 4K; texture ↑ / motion ↓); ladder linear 11–17 mW/Mbps (n=3); 4K costs MT8696
  +0.37 W, Amlogic ~0; loop-validity finding (multi-minute loops neutral, 30 s loops cost Gen 3 +0.10 W); **headless
  STB rows are a no-sink regime** (Fire TV −0.77 W playback) → dummy plugs ordered; Apple TV back on Lab-F6/HDMI_2;
  football sports family built (`prep_family.py`); CR-080–083; WattLab call outcomes (n=3 bar). Tests 1074.
  **Overnight 09-03→04 (CR-081 delivered):** football through the encode-parity sweep (84 + 18 ceiling-ext + 3 recheck
  rows, VMAF v0 rescore, versioned consolidated CSV — Tania's untouched) and the decode rig (rt ×3 + iso loops ×3, ten
  devices, 214 rows): football needs ~2× ReadySetGo's bits at VMAF 92 while NVENC's Wh/min doesn't move; the GTV plays it at
  BBB's watts; Gen 3's modern-codec edge narrows on sport. Panel auto-off (~4 h) paused the Apple TV once — standing
  hazard. `docs/football_sports_tier_2026-09-04.md`.

### Deferred / open (unique items only — CRs track themselves)
- **VMAF-stage polish bundle on `/video`** (owner notes 2026-06-10): (1) progress bar during the VMAF stage
  (server stamps vmaf_done/vmaf_total; verify `-progress` works on the scoring pass, else render the counters);
  (2) spurious "Wait for Idle" after first/second VMAF run (suspect stage-strip index vs extra cooldown call — cf.
  the S39 duplicate-key class); (3) faster scoring: `vmaf_n_subsample`/`vmaf_n_threads` first; GPU libvmaf_cuda
  needs a rebuild AND heats the GPU between passes (integrity caveat — CPU scoring stays cleaner); (4) per-run
  VMAF checkbox defaulting from `vmaf_enabled` (video.py:229).
- **Guided Tour Findings step** — redesign to aggregate across all stored results, not echo the session run.
- **Power-user/visitor UX watch** — revisit if a visible density toggle becomes needed.
- **2026-07 audit doc-debt residue** (after the 2026-08-19 sweep): VERSION/tag reconciliation (`v1.0.0` tag is
  150+ commits stale; `VERSION` frozen at 1.0.0) · back-fill the 28 closed-CR entries missing closing-commit hashes ·
  ARCHITECTURE.md is refreshed but its per-module line counts will drift again — regenerate, don't hand-edit.
- **C2 panel auto-off (~4 h after the last remote/SSAP input) kills overnight Apple TV / C2 rows** (09-04 03:54):
  disable it on the C2 (General › Power › Auto Power Off) or keep-alive from the rig before the next overnight.
- **Rig harness open items** (S65/S66): Fire TV `alive_at_window_end` false negative (instrumented via
  `playback_state_at_end`, root cause open) · Fire TV loses ADB authorisation after a mains power cycle (on-site
  accept, ONE reconnect) · C2 SSAP timeouts at window end lose rows · parity has no inter-row idle guard ·
  Apple TV: never headless (VLC pauses on HDMI loss) — needs its HDMI_2 slot for every row · Roku's
  `idle_w`/`expected_boot_s`/`startup_skip_s` are still unmeasured guesses pending an `onboard_device.py` run ·
  **headless STB rows are a no-sink regime** (S73: Fire TV −0.77 W playback, Gen 2 −0.42 W; rows carry
  `hdmi_input`, null = no sink) — Fire TV, Gen 2 and Bbox pool with the screened corpus only once the HDMI dummy
  plugs (ordered 2026-09-03) are fitted and verified · the shared VMAF scorer mis-pairs WebM frames by timestamp
  (S65 trap; `prep_family.py` works around it, `quality.compute_vmaf` does not).

## Key Findings to Date
Canonical store is **`/findings`** (one markdown per finding under `docs/findings/`, strict schema, cites a real
stored result). Don't restate findings as prose here — prose drifts (see memory). Current slugs (14):
`abr-all-codecs-meridian-120s` · `av1-hw-sw-vmaf-tradeoff` ⭐ · `input-master-sensitivity` ·
`llm-cold-inference-mwh-per-token` 🟡 · `rag-faithfulness-rem-question` 🟡 · `sd-turbo-cpu-image-first-run` ·
`upscale-sweetspot-degraded-sources` · `gpu-boost-overclocks-fixed-function-nvenc` (v2, prior-art positioned) ·
`hw-decoder-cuts-client-energy-4x` (3.7× rt / 4.6× sat, lab-reviewed) · `codec-decode-energy-depends-on-silicon-and-regime` 🟡 ·
`streaming-box-plays-4-7x-cheaper-than-general-purpose` · `stb-decode-and-play-content-over-codec` (DRAFT) ·
`appletv-a10x-av1-vp9-software-fallback` 🟢 · `looped-excerpt-measures-as-continuous` (DRAFT).
Not catalogued (live on `/methodology`): French grid evolution (Eco2mix lifecycle series); CR-016 insight —
Eco2mix `taux_co2` is combustion-only, never compare it to lifecycle means. VP9 stays a report
(`docs/vp9_oneoff_2026-08.md`) until the discussion settles.

## Visual Identity
Owl SVG `wattlab_service/static/owl.svg`; GoS round bug footer-only. Dark theme `#0a0a0a` bg / `#00ff99`
accent — tokens centralised in `_BASE_STYLES` (`ui.py:~334`). REM re-skin: `rem-theme.css`.
