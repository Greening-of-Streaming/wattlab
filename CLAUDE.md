# WattLab — Claude Code Context File
# Auto-loaded by Claude Code. Keep this current — and keep it LEAN: one-liners here, detail in JOURNAL.md.
# Last updated: 2026-06-11 (Session 44 — CR-064: Jon's answers implemented — conditional input normalization
#   (VFR/pix_fmt → FFV1/NUT yuv444p10le, pre-baseline so energy stays clean), per-job encoder logs,
#   hdr_4k repro = 96.8% peak VRAM (Jon's OOM theory supported; exclusion stays). Tests 628.
#   Service restart PENDING (normalize stage + logs need a reload).)
# Public name: OWL (Online WattLab). "WattLab" is the legacy/internal/repo name.
# See also:
#   - ARCHITECTURE.md — module map + request/job flows (the orientation doc; READ FIRST for code work)
#   - JOURNAL.md — session-by-session change log (full detail; newest first)
#   - CHANGE_REQUESTS.md — 16 active CRs (+ groupings appendix); CHANGE_REQUESTS_CLOSED.md — closed archive
#   - TESTING.md — pytest suite (628 tests) + manual checklist · WATTLAB_SPEC.md — historical design intent
#   - GOS1_INFRA.md — server infra, backups, incident log · docs/result_envelope.md — mode→renderer contract
#   - docs/architecture_review_2026-06.md (refactor rationale, executed S41–42) · AUDIT_BRIEF/RESPONSE.md (2026-05 audit)
#   - docs/wattlab_traffic_light_confidence.md (Tania §9 spec) · docs/wattlab_parameters_audit.md (param taxonomy)
#   - docs/input_sensitivity_findings.md (CR-047 pre-test) · docs/gpu_swap_amd_baseline.md (frozen AMD-era data)
#   - REM/CLAUDE.md — sibling project (Tapo fleet via TP-Link cloud). OWL = bench, REM = meter on the building.

## Project Identity
- **Name:** WattLab · **Repo:** https://github.com/greeningofstreaming/wattlab
- **Host:** GoS1 — Ubuntu 24, `192.168.1.62`, externally `gos1.duckdns.org:2222`
- **Owner:** GoS (Greening of Streaming), French NGO loi 1901
- **Mission:** Measure environmental impact of streaming. Neutral, technically credible.

## GoS Framing (always apply)
- "Not eco-warriors. Just people who dislike waste."
- If it can't be measured, it shouldn't be asserted.
- Separate device / network / data center / production+storage impacts explicitly.
- State scoping assumptions. Signal uncertainty. Traffic Light Confidence on all claims.
- Audience: CTOs, operators, infrastructure players, policymakers.

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

## Network Topology
Bbox Wi-Fi 7 (192.168.1.x) ── GoS1 ethernet `.62` · MacBook Wi-Fi · Tapo P110 Wi-Fi `.159`
(External-access incidents + DuckDNS updater: see GOS1_INFRA.md.)

## Thermal Sensors
- One source of truth: `power.read_sensors_dict()` → `{cpu_tctl, gpu_junction, gpu_ppt_w}`; per-module
  `read_sensors()` wrappers delegate to it.
- CPU: `sensors -j` → `k10temp-pci-00c3.Tctl` (CPU-bus chip, name stable).
- GPU: vendor-abstracted via `gpu.BACKEND.read_gpu_sensors()` (CR-060). Nvidia path: `nvidia-smi` temp + power
  (`power.draw` is instantaneous vs AMD's `power1_average` — open sampling-semantics question, see closed CR-060).
  AMD path (rollback): amdgpu chip resolved dynamically, never by PCI address (re-enumeration shifts it).

## Environment
- `.env` at repo root (gitignored; `.env.example` is the tracked template): `TAPO_EMAIL`, `TAPO_PASSWORD`,
  `TAPO_P110_IP`, `OWL_AUTH_SECRET` (magic-link signing), `OWL_SMTP_USER` + `OWL_SMTP_PASSWORD` (Gmail SMTP
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
**See ARCHITECTURE.md for the module map** (main.py = ~500-line app assembly; twelve flat `routes_*.py` feature
modules; `runtime.py` jobs/telemetry; `ui.py` page chrome + serve-time wording; measurement modules `video.py`
`llm.py` `image_gen.py` `rag.py`; `power.py`/`gpu.py` instrumentation; `persist.py`/`settings.py` storage).
Key paths: `wattlab_service/static/wl-*.js` (shared JS bundles, sha cache-busted, configured via `/ui-config.js`);
`results/` → `/srv/data/owl/results` (per-result JSON, `{type}/{date}_{job_id}.json`); `test_content/`, `corpus/`,
`.chroma/` similarly symlinked; `docs/findings/` (finding markdowns); `infra/` (nginx), `systemd/`, `bin/` (ops
scripts, see bin/README.md). Feature modules NEVER import main; tests monkeypatch the routes_* module that
binds a name, not main.

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

Focus-mode timers: sysstat-collect, anacron, fwupd-refresh, apt-daily{,-upgrade}, man-db, motd-news,
update-notifier-download.
Cooldowns route through ONE dispatcher: execution `power.cooldown_between_runs`, wording `_bake_durations`
tokens, footer `wlCooldownSummary` (test-guarded — no raw sleeps or hardcoded `{COOLDOWN_S}s`).

## Traffic Light Confidence
Single implementation `confidence.py`, shared by all four measurement modules (CR-028 Phase 2, Tania §9 v2 —
full math in `docs/wattlab_traffic_light_confidence.md`). Contract:
`confidence(delta_w, poll_count, w_base, baseline_samples_w=…, task_samples_w=…)` → `confidence_positive = Φ(ΔW/SE)`;
🟢 ≥0.95 AND n_task≥10 · 🟡 ≥0.80 AND n_task≥5 · 🔴 otherwise (thresholds are settings). Raw samples are persisted
in every result; legacy results without them fall back to the old variance-threshold flag (`method` = ci|variance).

## Scope Statements
Video: "Device layer only (GoS1 server). Network, CDN, and CPE excluded."
LLM: "Device layer only (GoS1 server). Network and CPE excluded. No amortised training cost."

## Services & URLs
wattlab (systemd, port 8000, 1 worker — restart needs the OWNER: not in Claude's sudoers) · ollama (11434).
LAN `http://192.168.1.62:8000` · public `https://wattlab.greeningofstreaming.org` (nginx + certbot).
Pages: `/video /llm /rag /image /demo /findings /benchmark /enhance-run /settings /queue-status /methodology /carbon`.
Auth tiers (CR-001): Anonymous (public) · Member (magic-link, allowlist `data/members.json`) · Lab (LAN/loopback).
Policy lives ONLY in `capabilities.py`; routes never compare tiers. Tests run as Lab — reason about
Anonymous/Member explicitly; probe Anonymous with a real public IP header like 8.8.8.8 (Python ≥3.12.4 counts
TEST-NET 203.0.113.x as private → Lab).

## Roadmap
**Phases 1–8 shipped** (research integrity → measurement quality → settings → demo → image gen → public access →
tour/credibility → RAG). **Active: 16 CRs** in CHANGE_REQUESTS.md; closed archive (problem + closing commit) in
CHANGE_REQUESTS_CLOSED.md.

### Recent sessions (true one-liners — full entries in JOURNAL.md)
- S26–S30 (05-20→27): credibility bundle, versioning, VMAF + CI confidence model, BBB/variants picker, model-ladder refresh. 218→290 tests.
- S31–S33 (05-27/28): compare trilogy (CR-048/049/050), RAG corpus self-service (CR-051), findings catalog (CR-054–058). →339.
- S34–S35 (05-28/29): CR-061 benchmark orchestrator + CR-029 §2 encode norm; CR-060 GPU abstraction + AMD baseline frozen. →385.
- S36 (05-29): GPU swap — RTX 5080 first light, zero code edits; NVENC beats VAAPI on energy, +20 W idle. 
- S37 (06-01): /demo tour trap + findings-embed 404 fixes. →392.
- S38 (06-02): CR-062 omnibus — unified cooldown/wait-for-idle, /video codec split, queue resume, JS bundling guard. →427.
- S39 (06-03): compare-page cooldown-label factoring + /image compare fixes. →432.
- S40 (06-08): CR-063 Pixop /enhance-run integration (pixop.py). →505.
- S41 (06-10): architecture review; refactor Phases 0–1 (JS bundles → files, serve-time config); tinyllama-default fix; idle-wait readout. →560.
- S42 (06-10/11): refactor Phases 2–4 — ui.render_page(), twelve routes_*.py + runtime.py, result-envelope contract. →566.
- CR-064 arc (06-10 evening): /enhance-run revamp — uploads, NVEncC args editor, queue controls, upload TTL sweep, UGC VFR×forcecfr bisect. →614.
- S43 (06-11): /video batch-box selection affordance fix (boxes looked dead; clicks worked) + doc cleanup. →615.
- S44 (06-11): CR-064 Jon's answers — conditional input normalization (pre-baseline, energy-clean) + per-job logs; hdr_4k = 96.8% VRAM (OOM theory). →628.

### Deferred / open (unique items only — CRs track themselves)
- **VMAF-stage polish bundle on `/video`** (owner notes 2026-06-10): (1) progress bar during the VMAF stage
  (server stamps vmaf_done/vmaf_total; verify `-progress` works on the scoring pass, else render the counters);
  (2) spurious "Wait for Idle" after first/second VMAF run (suspect stage-strip index vs extra cooldown call — cf.
  the S39 duplicate-key class); (3) faster scoring: `vmaf_n_subsample`/`vmaf_n_threads` first; GPU libvmaf_cuda
  needs a rebuild AND heats the GPU between passes (integrity caveat — CPU scoring stays cleaner); (4) per-run
  VMAF checkbox defaulting from `vmaf_enabled` (video.py:229).
- **Guided Tour Findings step** — redesign to aggregate across all stored results, not echo the session run.
- **Power-user/visitor UX watch** — revisit if a visible density toggle becomes needed.

## Key Findings to Date
Canonical store is **`/findings`** (one markdown per finding under `docs/findings/`, strict schema, cites a real
stored result). Don't restate findings as prose here — prose drifts (see memory). Current slugs:
`abr-all-codecs-meridian-120s` · `av1-hw-sw-vmaf-tradeoff` ⭐ · `input-master-sensitivity` ·
`llm-cold-inference-mwh-per-token` 🟡 · `rag-faithfulness-rem-question` 🟡 · `sd-turbo-cpu-image-first-run`.
Not catalogued (live on `/methodology`): French grid evolution (Eco2mix lifecycle series); CR-016 insight —
Eco2mix `taux_co2` is combustion-only, never compare it to lifecycle means.

## Visual Identity
Owl SVG `wattlab_service/static/owl.svg`; GoS round bug footer-only. Dark theme `#0a0a0a` bg / `#00ff99`
accent — tokens centralised in `_BASE_STYLES` (`ui.py:~334`). REM re-skin: `rem-theme.css`.
