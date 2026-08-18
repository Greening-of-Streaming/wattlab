# /methodology vs the code — inconsistency journal (2026-08-19)

*Owner review requested (Ben, 2026-08-18 evening): "reread /methodology, keep it in memory as you reread all
the code; journal aspects of methodology that aren't actually implemented and design choices in the code which
could or should be documented in methodology." Compiled overnight from `wattlab_service/routes_methodology.py`
(v0.7, 2026-08-15) against the measurement modules; every item carries file:line references. Nothing on the
page or in the code was changed. Severity: 3 = a reader could draw a wrong conclusion · 2 = a stated protocol
differs from the implemented one · 1 = precision/wording.*

**Which numbers on the page are live vs literal:** only `baseline_polls`, `video_cooldown_s`, `conf_*_polls`,
`variance_runs`, `variance_cooldown_s`, GPU/meter/partner names and the recovery chart are baked at serve time
(`routes_methodology.py:788–814`). The 95 %/80 % cut-points, "8 polls", idle 79 W, tapo 0.8.12, Ollama 0.20.2,
kernel 6.17, bitrates 4000/2000/1500, "v1 since 2026-07-17" and the footer version/date are literals. The page
does not use `ui._bake_durations` (`ui.py:746–757`), so it lacks the toggle-aware "→ idle" cooldown wording
every other page carries.

## A. Claimed but not implemented (NOT-IMPLEMENTED)

| # | sev | Page claim (routes_methodology.py) | What the code does |
|---|---|---|---|
| 1 | **3** | "Every test … video, LLM, image generation, RAG — follows the same core protocol: 1. Focus mode" (:420–424) | `focus_mode_enter` is called by video.py, image_gen.py, pixop.py, parity.py, precalibration.py, rem_prep.py — **never by llm.py or rag.py**. LLM/RAG rows are measured with system timers live. Either add focus mode to those two modules or say on the page that AI-text jobs run without it (their windows are short and GPU-bound; the timers' CPU noise is small but real). |
| 11 | 2 | "Encode-parity rows now carry the attributional figure … earlier stored results can be recomputed against the documented idle floor" (:486) | Only `parity._measure_recipe` (parity.py:381–405) computes `wh_per_min_video_attributional`; the stored calibration artifact (`results/calibration/encode_parity_nvenc_24c_2026-06-20.json`) has neither `w_base` nor the field; nothing in the UI (wl-result.js, routes_budget.py, findings) renders it; the "recomputation" exists only in offline scripts using a **nominal 79 W** floor (`docs/vp9_rerun_2026-08-17/analyze_night.py`, `docs/vp9_oneoff_2026-08.md` §4.3). Say "nominal 79 W" and where the figure is (not) shown. |
| 31 | 2 | "every OWL result" carries the Φ(ΔW/SE) traffic light (:520 ff.) | A finding's `confidence` (green/yellow/red) is an **author-assigned frontmatter field** (findings.py:29–51), distinct from the per-run flag; and the `review_status`/`impact` axes described in JOURNAL/memory do not exist in `findings.py` on `main`. State the finding-level semantics (weakest cited result, editorial) or implement the derivation. |

## B. Numbers or semantics differ (MISMATCH)

| # | sev | Page | Code |
|---|---|---|---|
| 2 | 2 | "a configurable cooldown (currently {VIDEO_COOLDOWN_S} seconds …) allows the system to return to thermal equilibrium" (:449) | `cooldown_wait_for_idle` defaults ON (settings.py:25): `power.cooldown_between_runs` (power.py:448–569) waits for the previous W_base + `cooldown_idle_tolerance_w` (3 W) for `cooldown_idle_settle_polls` (3) consecutive reads, cap 120 s, then dialog / "Run anyway" / one fallback fixed sleep, stamping `settled`, `timed_out`. The live 10 s is only the fallback; the settle is an asymmetric-tolerance floor check, not "equilibrium" (idle_wait.py:56–61). |
| 5 | 1 | Lock is step 4, after baseline (:420–424) | llm.py:318 / rag.py:570 take the lock after the baseline; video takes it via the queue before. "Prevents concurrent measurements from overlapping" is only true once held. |
| 15 | 2 | Decode rig uses "the same baseline/ΔW/confidence method" (:648) | `decode_bench/bench.py:463–464` calls OWL `confidence()` with no settings → GoS1's `variance_idle_pct` 2.38 % / `variance_idle_drift_pct` 1.12 % of a ~79 W idle are applied to a 0.5–20 W client device (settings.py:59, confidence.py:113–114). Either calibrate per device or state that the drift term is GoS1's. |
| 16 | 2 | Open Questions: "GOP structure and profile level are still default-per-encoder and have not been explicitly normalised" (:700) | **Stale since CR-029 §2:** video.py:296–304 pins `-g encode_gop_frames` (120), `-profile:v`, `-bf 2`, closed GOP, scenecut off; gpu.py:149–158 mirrors it for NVENC. Level remains unpinned (that part is still true). |
| 17 | 1 | "All presets use ABR … file sizes match as confirmation" (:628) | NVENC path uses `-rc cbr` (gpu.py:36–42, documented in code as the ABR-equivalent). |
| 19 | 2 | Encode-parity / budget calibration "under the same protocol" (:654) | parity.py:502 cools with a plain `asyncio.sleep(cooldown_s)` — no idle guard, no pre-job guard; artifacts record `baseline_polls 5, cooldown_s 10, min_task_s 20`; before 2026-08-15 no per-row `w_base`, so hot baselines were undetectable (2/108 rows in the 08-17 run had 95–99 W baselines and were excluded post hoc). Also undocumented: `wh_per_min` is normalised by content encoded (`content_s = clip × n_encodes`, parity.py:380) and the 30 s trim (`ensure_clip`). |
| 21 | 1 | Thermal-recovery probe "8 polls" (:566, chart label :581) | precalibration.py:77 uses `precal_baseline_polls or baseline_polls` (= 5 live). |
| 22 | 2 | AI energy expressed as "a multiple of a real video encode — pinned canonical H.265 GPU encode of Meridian-120s" (:645) | `canonical/video_baseline.json` is `hevc_vaapi` on the RX 7800 XT, pinned 2026-05-20 (canonical.py:18) — the multiplier is against AMD-era hardware; page doesn't say so. Re-pin on the 5080 or label it. |
| 23 | 1 | LLM ladder lists TinyLlama (:640) | `llm_enabled_models` excludes it (settings.json); anchor-only. |
| 27 | 1 | Decode roster: GTV, Pi 5, Pi 400, Fire TV (:648) | rig.py also has the LG C2 native (CR-071) and the Bbox operator CPE; Pi 5 is parked; C2 rows carry the picture-mode confound (S61/S63). |

## C. Methodologically significant behaviour the page does not state (UNDOCUMENTED)

| # | sev | Behaviour | Where |
|---|---|---|---|
| 3 | 2 | **CR-070 pre-job idle guard**: before every dispatched job the queue worker waits for the previous baseline's floor (`power.LAST_W_BASE`, rolling), Lab may skip after `pre_job_skip_after_s` (→ `method="idle+skipped"`); every baseline stamps `baseline_elevated` / `baseline_reference_w`. Defines what W_base means for queued campaigns. | queue_control.py:150–178, power.py:225–268 |
| 4 | 1 | Variance calibration is the one path that bypasses the idle guard (`respect_toggle=False`). | video.py:1108–1112 |
| 7 | 1 | On a healthy dual-meter run the headline ΔW/ΔE is the **two-meter combine** (`delta_w_combined`, mean of per-meter deltas), not the formula's single mean − W_base; only the topology row mentions ci2, under "confidence". | video.py:608–611, power.py:313–350 |
| 8 | 2 | **RAG ΔE mixes windows**: ΔW is averaged over embedding + Chroma query + inference, but Δt = inference only. "Energy delta of retrieval" (:642) is therefore retrieval power × inference time. | rag.py:501–525, 571–591 |
| 9 | 2 | **Image ΔE mixes windows**: polling spans model load + generation, `delta_t = gen_s` ("measure only generation time"). Wh/image = (mean power over load+gen − idle) × gen time. | image_gen.py:306–319 |
| 10 | 1 | LLM E_token divides by **output** tokens (`eval_count`) only; prompt tokens excluded; page writes N_tokens. | llm.py:269–270 |
| 12 | 2 | **Hot-baseline exclusion rule** used in analyses (drop rows with `w_base > median + 10 W`; hot baselines under-count ΔW) is nowhere on the page; `baseline_elevated` uses a 3 W tolerance instead. | analyze_night.py:4, vp9 report §5.1 |
| 13 | 1 | 95 % / 80 % cut-points are literals; live keys `conf_positive_green/yellow` not baked (tokens exist for the legacy multipliers the page no longer shows). | :525/:530/:698, settings.py:50–51 |
| 14 | 2 | Dual-meter SE = √(SE₁²+SE₂²)/2 + drift; the outer plug (fw 1.4.0) refreshes every ~1.5 s so 1 s polls contain duplicates → effective n smaller than poll count; the page's "1-second intervals on each of two staggered meters" is poll cadence, not fresh-sample rate; firmware asymmetry omitted. | confidence.py:130–133, power.py:153–165 |
| 18 | 1 | VMAF model resolves per variant: HD `vmaf_v1.0.16_3d0h.json`, UHD `vmaf_v1.0.16_1d5h_2160.json`, v0 4K `vmaf_4k_v0.6.1`; a missing v1 file silently falls back to v0 (stamped); `vmaf_n_subsample` 1 for /video, 4 for the FR sandwich, 5 for REM; 600 s timeout → score None; DEFAULTS `vmaf_model="v0"` (page's "v1 since 07-17" holds only via live settings). | quality.py:70–99, 195; pixop.py:1341; settings.py:110,123,168 |
| 20 | 1 | Tuned NVENC bundle listed without `-tune hq -aq-strength 8`. | :659 vs parity.py:94–96 |
| 24 | 2 | **Decode protocol v3 knobs** unstated: settle 5 s → self-stability idle guard (tolerance 0.5 W, 4 polls, cap 30 s; reference floor when the device has `idle_w`) → 20-sample baseline → start → `startup_skip_s` 8 s → window (150 s default, 30–3600 override, clamped by `max_window_s`) → `n_task` from 1 Hz Tapo (failed KLAP reads skipped). July envelopes are protocol v2 (no guard). | decode_run.py:243–267, bench.py:421–450, settings.py:203–207 |
| 25 | **3** | **Keep-awake pins, CEC rule, PLAYING gate, liveness**: the bench pins `secure sleep_timeout=-1`, `system screen_off_timeout=2147460000`, sets `cec … active_source_lost=none` (owner also disabled C2 SIMPLINK); start requires media-session PLAYING (2 presses); `still_running` retries 3×; `alive_at_window_end` + `playback_state_at_end` recorded but **rows are not excluded or flagged by any importer/route** — the "row counts only with a non-black mid-window screenshot / flat trace" rule from S61/S65 is analysis practice, not code. A reader cannot tell that pre-2026-08-16 hour-long STB rows may be dead-playback artefacts, nor that a living-room box on defaults would have slept at 20 min. | bench.py:110–147, 200–224, 254–275, 477–478 |
| 26 | 1 | Mid-window screenshot + logcat decoder provenance (`decoders_allocated`) is how "hardware vs software" is proven; screen-mode context meter + marker head black5-white5-black5. | bench.py:226–252, decode_run.py:232–240 |
| 28 | 1 | `wh_window_device_total` is stored beside ΔW; page doesn't say which figure findings quote (ΔW). | bench.py:472 |
| 29 | 2 | **Iso-bitrate decode family audio confound**: VP9 ships as WebM + Opus, the other codecs MP4 + AAC; the GTV allocates `c2.android.opus.decoder` (software) on VP9 rows — any VP9-vs-others decode delta includes an audio-decoder change. VP9 isn't on the page at all. | decode_run.py:169–174, campaign prep manifest |
| 30 | 1 | Fire TV Wi-Fi caveat present (:648); its ADB-liveness false negative and 5-min screensaver history are not. | S65/S66 |
| 32 | 1 | Idle 79 W literal (:612) — consistent with analyses (median 80.1 W on 2026-08-17) but should be baked (recovery-chart floor already is). | :744 |
| 33 | 1 | Footer "0.7 · 2026-08-15" predates the 08-16/18 decode fixes; no changelog anchor. | :708 |
| — | 1 | Network-path arms (CR-074): origin `?pace_kbps=` server-side pacing, per-run `pre_cmd`/`post_cmd` interface toggles, `ifaces_midwindow` provenance — new this week, undocumented (expected; note for the next methodology bump). | decode_run.py, origin.py, bench.py |

## D. Verified consistent (no action)

Baseline mean / ΔW / ΔE formula (energy.py:22) · LLM `keep_alive=0` + 3 s settle (llm.py:130,312–313) · SE/Φ
model and n gates (confidence.py:88–170) with legacy fallback · variance ≥50 %-fail refusal (video.py:1213–1237)
· local mW reads (`current_power/1000`) · CUDA full pipeline (gpu.py:26–42) · VMAF scored after the window,
crop-not-scale (video.py:770–807, quality.py:145–155) · FR sandwich anchors/uhd model (pixop.py:1338–1420) ·
budget page v0 note (routes_budget.py:252) · GPU sensor = reference only · hardware table names · thermal-recovery
distances (precalibration.py:43).

## E. Suggested disposition (for the owner's decision, not applied)

- **Fix on the page now (wording only):** 16 (GOP normalised — stale), 17 (CBR), 21 (probe polls), 22 (AMD-era
  anchor label), 23 (TinyLlama), 27 (roster), 20 (bundle), 32/13 (bake the literals), 33 (footer/changelog).
- **Add a "what the numbers exclude" paragraph per module:** 8, 9, 10 (window/denominator definitions), 7 + 14
  (dual-meter combine and effective n), 3 + 4 + 2 (the three guards and which paths bypass them), 12 (exclusion
  rule), 11 (attributional: nominal floor, where shown).
- **Add a decode-rig protocol section (v3):** 24, 25, 26, 28, 29, 30 — including the disclosure that sleep timers
  are pinned on the bench and the liveness gates a row must pass to count.
- **Code decisions the owner should make:** 1 (focus mode for LLM/RAG — implement or disclose), 15 (per-device
  drift calibration for decode confidence), 25 (make the liveness gates part of the importer/collator, not
  analysis practice), 31 (finding-level confidence derivation), 19 (inter-row idle guard in parity).
