import json
from pathlib import Path

SETTINGS_FILE = Path("/home/gos/wattlab/settings.json")

DEFAULTS = {
    # Kill switch for anonymous aggregate visit counting (analytics.py — no
    # IP/cookie/UA stored; the /audience dashboard reads it). ON by default.
    "analytics_enabled": True,
    # Canonical public origin for building absolute share links that must work
    # off-LAN (e.g. /rem-file/{token}). Used instead of the request host so a
    # link copied from an SSH-tunnelled session (host=localhost) is still public.
    "public_base_url": "https://wattlab.greeningofstreaming.org",
    "baseline_polls": 10,
    "video_cooldown_s": 60,
    "llm_rest_s": 10,
    "llm_unload_settle_s": 3,
    # --- Unified cooldown between measurement passes (power.cooldown_between_runs) ---
    # Master toggle. ON  → wait until wall power settles back to the captured idle
    #                       floor before the next pass (active-probe, the rag/compare
    #                       technique) for EVERY cooldown that respects the toggle.
    #                 OFF → fixed sleep of the relevant *_cooldown_s / *_rest_s key.
    # Variance calibration ignores this (respect_toggle=False) — it always runs its
    # fixed variance_cooldown_s protocol.
    "cooldown_wait_for_idle": True,
    # Idle-wait tuning (were hardcoded at the 4 compare call sites pre-unification).
    "cooldown_idle_tolerance_w": 3.0,   # settled = reading ≤ floor + this
    "cooldown_idle_settle_polls": 3,    # consecutive in-band reads to confirm settle
    "cooldown_idle_max_wait_s": 120,    # cap before timeout → dialog / fallback
    # Live idle-wait readout in the progress widget ("⏳ Idle wait 12s · 65.2 W
    # → target ≤ 61.0 W") on every page that runs a cooldown. UI-only — does
    # not affect cooldown behaviour. Reaches the browser via /ui-config.js.
    "cooldown_show_wait_detail": True,
    # On idle-wait timeout in an ATTENDED Lab run, park the job and show the
    # Wait-again / Run-anyway / Cancel dialog. Auto-resolve to the non-interactive
    # default (one fixed fallback sleep, then proceed, settled:false) after:
    "cooldown_dialog_watchdog_s": 75,
    # CR-070 — pre-job idle guard: between queued jobs the worker waits for
    # wall power to return to the previous job's baseline floor before the
    # next job's first baseline (queue_control._pre_job_idle_guard). Attended
    # Lab runs get a "Run job anyway" button in the live idle-wait readout
    # once the wait has lasted this many seconds (UI threshold only — the
    # wait itself still settles or times out at cooldown_idle_max_wait_s):
    "pre_job_skip_after_s": 5,
    # Confidence — poll count thresholds (kept)
    "conf_green_polls": 10,
    "conf_yellow_polls": 5,
    # Confidence — CR-028 Phase 2 CI model (Tania §9): one-sided P(task > idle).
    # Used when a run carries raw per-poll samples; see confidence.py.
    "conf_positive_green": 0.95,   # 🟢  confidence_positive ≥ this AND n_task ≥ conf_green_polls
    "conf_positive_yellow": 0.80,  # 🟡  confidence_positive ≥ this AND n_task ≥ conf_yellow_polls
    # Confidence — legacy variance-based ΔW thresholds. Retained as the
    # fallback for results saved before raw samples were persisted (the CI
    # model needs baseline_samples_w + task_samples_w).
    "variance_pct": 2.0,        # measured system variance as % of baseline power
    "variance_green_x": 5.0,    # 🟢  ΔW must exceed this × noise_w  (legacy)
    "variance_yellow_x": 2.0,   # 🟡  ΔW must exceed this × noise_w  (legacy)
    # Variance calibration outputs (written by calibration run, not user-edited)
    "variance_idle_pct": None,        # mean of within-window CVs across all baselines —
                                      # noise floor a single measurement actually faces
                                      # (feeds the confidence flag via variance_pct)
    "variance_idle_drift_pct": None,  # CV across the *means* of each baseline window —
                                      # diagnostic for slow drift or periodic external
                                      # events between windows; not consumed by confidence
    "variance_cpu_pct": None,         # CV of ΔW across H264-CPU runs
    "variance_gpu_pct": None,         # CV of ΔW across H265-GPU runs
    # Variance calibration run parameters
    "variance_runs": 10,         # how many H264-CPU + H265-GPU pairs to run
    "variance_cooldown_s": 60,   # seconds between each run pair
    # CR-024 thermal-recovery probe (POST /precalibration/run). Defaults match
    # bin/probe-thermal-recovery so the button and the CLI produce identical CSVs.
    "precal_distances": "0,2,5,8,12,18,25,35,50,70,95,120",  # sample points after each encode
    "precal_pre_cool_s": 30,      # settle before each encode
    "precal_baseline_polls": None,  # idle polls per distance; null → baseline_polls
    # Variance commands derive from video.PRESETS["cpu"] / ["h265_gpu"] at
    # run time (see video.variance_template). Hardcoded strings used to live
    # here but drifted out of sync with /video after S13's ABR migration —
    # calibration was on -crf 23 / -qp 28 while /video ran -b:v Nk.
    # Encoding targets — ABR bitrate per codec (applied to both CPU and GPU presets)
    "h264_bitrate_kbps": 4000,
    "h265_bitrate_kbps": 2000,
    "av1_bitrate_kbps":  1500,
    # CR-029 §2 — apples-to-apples GOP. Pinned identically on every preset so
    # the keyframe cadence is the same on the CPU and GPU paths (audit found
    # VAAPI defaulted to 120 vs ~250-321 on the CPU encoders). 120 frames = 2 s
    # on the 59.94 fps canonical Meridian source (a streaming-standard segment
    # length). Operator-tunable; the rest of the normalization (profile, closed
    # GOP, B-frames) lives in video._norm_args. Changing this re-bases the video
    # numbers — re-run variance calibration after.
    "encode_gop_frames": 120,
    # ffmpeg binary path — installed side-by-side with Ubuntu's stock 6.1.1
    # so the system /usr/bin/ffmpeg stays untouched for anything else
    # linked against its shared libs. The static build at this path is
    # what fixes the scale_vaapi surface-pool leak that previously
    # required a -t cap on every VAAPI encode.
    "ffmpeg_bin": "/usr/local/bin/ffmpeg-master",
    # CR-060 — GPU name for public UI copy (Hardware Disclosure table).
    # Default "" = auto-detect from the live backend (gpu.BACKEND.name), so a
    # card swap (or whichever card wins auto-detect in a dual-card box) labels
    # itself with zero settings edits — same reboot-only contract as the
    # functional code + per-result provenance stamp. Set a non-empty string
    # ONLY to override the detected name with curated copy (e.g. to add VRAM);
    # remember it then becomes manual and won't track a future swap.
    "gpu_display_name": "",
    # CR-044 — VMAF perceptual quality score on >1-video comparison cards.
    # Computed as a TERMINAL pass after a job's measurement window closes,
    # so its CPU draw never enters a reported energy figure. Requires the
    # libvmaf-enabled ffmpeg_bin (system /usr/bin/ffmpeg lacks it).
    "vmaf_enabled": True,
    "vmaf_n_subsample": 1,   # score every Nth frame (TEMPORAL only). 1 = full.
    "vmaf_n_threads": 12,    # libvmaf worker threads (box has 24 cores).
    # VMAF model + scoring binary (quality.py). Model: "v0" = libvmaf built-in
    # vmaf_v0.6.1 (all OWL scores before 2026-07-17), "v1" = Netflix
    # vmaf_v1.0.16 file models under vmaf_model_dir (needs libvmaf >= 3.2.0),
    # or an absolute path to any model json. The upgrade/rollback lever: flip
    # here, nowhere else — every stored score carries `vmaf_model` provenance
    # (absent = legacy = v0.6.1). v0 and v1 scores are DIFFERENT currencies
    # (same clip pair measured 77.95 v0 vs 83.59 v1) — never compare across.
    # vmaf_ffmpeg_bin is the scoring-only ffmpeg: v1 needs a newer libvmaf
    # than the pinned encode binary, and ffmpeg_bin must never be bumped for
    # scoring (binary changes confound energy measurements). Empty = score
    # via ffmpeg_bin (v0 only).
    "vmaf_model": "v0",
    "vmaf_model_dir": "/srv/data/owl/vmaf/model",
    "vmaf_ffmpeg_bin": "",
    # Operator quality target — the VMAF an encode should hit while minimising
    # energy. 92 is the figure operators most often cite. Anchors the
    # /video/budget calculator and the encode-parity/calibration study (the
    # quality the CPU/GPU recipes are tuned and compared at). Display/analysis
    # anchor only — does NOT alter what /video encodes per-run.
    "target_vmaf": 92,
    # Pixop partner GPU transcode/upscale (hidden /enhance-run page, Lab-only).
    # The pixop/live image wraps NVEncC; its license is baked INTO the image
    # (/opt/pixop/license.jwt) so OWL supplies NONE. OWL owns its own workdir
    # (/srv/data/owl is gos-owned → no root chown needed); it mounts the three
    # subdirs to the container's /mnt/host/{input,output,presets} contract.
    "pixop_image_tag": "pixop/live:2026.06.03",
    "pixop_workdir": "/srv/data/owl/pixop",  # contains input/ output/ presets/
    "pixop_presets": [],                     # [] = auto-list *.args in presets/
    "pixop_cooldown_s": 60,
    "pixop_docker_timeout_s": 1800,
    # No-reference VQA for /enhance-run (CompressedVQA-HDR — Sun et al.,
    # arXiv:2507.11900, Apache 2.0). Runs as a TERMINAL pass via subprocess to
    # a sandboxed venv (NOT the service env), so its GPU draw never enters a
    # reported energy figure and the model never loads into uvicorn. Fail-soft:
    # a missing sandbox just omits the score.
    "vqa_enabled": True,
    "vqa_dir": "/srv/data/owl/vqa-eval",  # sandbox root: CompressedVQA-HDR/ + venv/
    "vqa_timeout_s": 600,                 # per-file cap (~14 s observed on the 5080)
    # CR-064 — /enhance-run revamp (June-10 call). Member upload caps (Lab
    # uncapped); "60 s" = clip DURATION (runs are 1×-paced, so duration ≈
    # processing time). Colour templates feed the generated 2×3 combo matrix
    # (output format × SD/HD/4K) — swap for Jon's input-agnostic templates
    # when they arrive.
    "enhance_upload_max_mb": 1024,
    "enhance_upload_max_duration_s": 60,
    # Un-kept uploads are swept this many hours after their run (mtime is
    # touched at job end), so the result card's source-vs-output comparison
    # keeps working all session — deletion happens "afterwards", not at done.
    "enhance_upload_ttl_h": 12,
    "enhance_template_sdr": "nvencc_fhd_709_20mbps.args",
    "enhance_template_hdr": "nvencc_fhd_pq_20mbps.args",
    # --- Prepare REM Files (/prepare-rem, Lab-only) — REM↔OWL integration ---
    # Encode a source to a constant TARGET QUALITY (VMAF), then wrap it in a
    # timer + black/white/black marker structure so REM can delimit the analysis
    # window during device playback. Bitrate is the free variable, quality the
    # constant target. See docs / the meeting spec (2026-06-23).
    "rem_measure_decode_split": True, # metered runs add a decode-only probe → report encode = transcode − decode
    # Terminal VMAF on the REM deliverable is a REPORTING score (not a search
    # target), so subsample temporally + use all cores to keep big 4K clips fast
    # and under compute_vmaf's 600s timeout. The helper doubles the subsample for
    # >1080p automatically. (The bitrate-search VMAF keeps the precise globals.)
    "rem_vmaf_n_subsample": 5,        # score every Nth frame for the deliverable score
    "rem_vmaf_n_threads": 24,         # all cores (terminal pass, outside the energy window)
    "rem_target_mode": "vmaf",        # default form mode: "vmaf" (search) or "bitrate" (direct)
    "rem_default_bitrate_kbps": 4000, # prefill for the bitrate-mode input
    "rem_target_vmaf": 92,            # default quality target (operator-overridable per run)
    "rem_vmaf_tolerance": 0.5,        # accept when |measured - target| <= this
    "rem_max_iters": 6,              # bitrate-search iteration cap on the excerpt
    # Segment layout (seconds) → [timer][black][white][black][video][tail] ≈ 10 min.
    "rem_timer_s": 60,
    "rem_marker_s": 30,              # each of the three black/white/black markers
    "rem_video_s": 390,             # 6.5 min of content
    "rem_tail_s": 60,
    # The bitrate search runs on a short representative excerpt (the bitrate→VMAF
    # curve is content-driven, ~duration-invariant for ABR/CBR), then ONE full
    # encode at the converged bitrate confirms VMAF on the deliverable.
    "rem_search_excerpt_s": 120,
    # Pluggable timer asset (Simon delivers later): a shell script (run with
    # output-path + W H fps dur args) takes precedence, else a pristine mezzanine
    # is normalised to the encode params, else OWL generates a lavfi placeholder.
    "rem_timer_script_path": "",
    "rem_timer_mezzanine_path": "",
    # Generated 10-min REM files live here (large — hundreds of MB to GB; NOT /tmp).
    "rem_output_dir": "/srv/data/owl/rem_out",
    # --- Decode rig (/decode console + decode_run protocol) ---------------
    # ⚠ Every key the /settings "Decode rig" section edits MUST be listed here:
    # save() only persists keys present in DEFAULTS (found 2026-08-15 — the
    # section had been a silent no-op since it shipped, values fell back to the
    # code defaults). Defaults below = the values decode_run.py/rig.py used.
    "decode_cadence_s": 1.0,           # meter sampling cadence for decode rows
    "decode_settle_s": 5,              # post-prepare quiesce before the idle guard
    "decode_baseline_samples": 20,
    "decode_idle_guard": True,         # ON ⇒ protocol v3 (settle loop before baseline)
    "decode_idle_tolerance_w": 0.5,
    "decode_idle_settle_polls": 4,
    "decode_idle_max_wait_s": 30,
    "decode_screen_startup_skip_s": 5,
    "rig_master_tapo_ip": "",          # P110 at the wall switching the strip; "" = none
    "rig_shelly_ip": "",               # override for rig.RIG["shelly_ip"]; "" = code default
    # Idle auto-off (rig.py): the rig is OFF by default — after this many
    # hours with no Lab control op / decode job / bench.py row / Lab visit
    # to /decode, every powered box is gracefully stopped (then the master
    # if one is switchable). rig_idle_off_monitor also cuts the shared
    # screen's plug (Lab-E) — OFF by default because that panel is the
    # household TV / a Mac extension, not only the bench monitor.
    "rig_idle_off_enabled": True,
    "rig_idle_off_hours": 4.0,
    "rig_target_overrides": {},      # {device: target} — follow a box that moved to Wi-Fi (CR-074)
    "rig_idle_off_monitor": False,
    "rag_corpus_path": "/home/gos/wattlab/corpus/papers",
    "rag_chroma_path": "/home/gos/wattlab/.chroma",
    # CR-015 — auto-lower the maintenance flag after this many minutes of
    # Lab-tier inactivity. The owl-maintenance-watchdog systemd timer fires
    # every minute and runs `stage-off` if the flag's mtime is older than
    # this threshold. The Lab-tier middleware in main.py touches the flag
    # on every request, so the window stays open as long as the operator
    # is using the LAN URL or SSH tunnel.
    "max_idle_mins": 30,
    # CR-001 part D — per-tier queue caps + Anonymous upload size.
    # Concurrent (queued + running) jobs per visitor; Lab is uncapped.
    # Anonymous = keyed by client IP; Member = keyed by allowlisted email.
    # Conference-day spike from Anonymous can't drain the queue and
    # starve Members.
    "queue_anonymous_cap": 1,
    "queue_member_cap": 4,
    # Upload byte cap, in MB. Anonymous = 100 MB (sized so a 1080p clip
    # gets ~30s+ of transcode wall-time, comparable to the bundled
    # meridian_120s asset). Member/Lab = 1024 MB (today's 1GB).
    "upload_size_anonymous_mb": 100,
    "upload_size_member_mb":    1024,
    # --- Unified upload store (uploads.py) — shared by /video, /enhance-run,
    # /prepare-rem. Retention is per-file (filename prefix evict_/proc_/keep_);
    # see uploads.RETENTIONS. `uploads_dir` is the shared dir for features with
    # no special storage need (/video moved off /tmp; /prepare-rem); /enhance-run
    # keeps its pixop docker-mount input dir. "Remove when short of space"
    # (evict, the default) deletes the oldest evict-class uploads when free space
    # on the dir's disk drops below `uploads_min_free_gb`, with a generous
    # `uploads_evict_ttl_h` backstop. (/enhance-run still reads enhance_upload_ttl_h.)
    "uploads_dir":           "/srv/data/owl/uploads",
    "uploads_min_free_gb":   20,
    "uploads_evict_ttl_h":   72,
    # CR-050 — per-surface enabled model lists. Empty list (or absent key)
    # means "all available enabled" so a fresh server with no settings file
    # just works. Settings UI writes ordered lists; model_catalog filters
    # the auto-detected available set against these.
    "llm_enabled_models":   [],
    "rag_enabled_models":   [],
    "image_enabled_models": [],
    # CR-051 — RAG corpus upload caps. Members can self-serve add/remove
    # documents on the corpus; without ceilings the corpus could be flooded
    # (each upload also triggers re-embed work). Lab is uncapped.
    "rag_upload_max_mb":         50,    # per-file size cap (Members)
    "rag_member_doc_count_cap":  10,    # max files per Member email
    "rag_member_total_mb_cap":   200,   # max total bytes per Member email
    # CR-054 — Findings catalog feature flag. False removes the
    # `GET /findings/<slug>` route from production (returns 404). No nav
    # links exist anywhere in OWL until CR-055 (catalog index) ships, so
    # `false` here completely undiscoverable + `true` is preview-by-URL.
    "findings_enabled":          True,
    # Guided-tour pinned results. job_id per tour step type; the /demo/last
    # carve-out serves the pin first and falls back to latest-matching —
    # EXCEPT "enhance", which is pin-ONLY (member uploads are private, never
    # serve latest). "rag" maps to a results/llm/ record with mode
    # "rag_compare". No /settings UI — set via POST /settings (Lab) or by
    # editing settings.json; values are live state, set at deploy, never
    # committed with features.
    "demo_pinned_results": {},  # e.g. {"video": "…", "llm": "…", "rag": "…", "image": "…", "enhance": "…"}
    # CR-061 — in-app overnight benchmark. The set of "measures" is a registry
    # in benchmark.py; these bench_run_* flags toggle which run, so retiring or
    # adding a measure is a registry+flag change, not a code rewrite. Video is
    # the anchor (all-codecs × reps × sources); the AI panels are coverage.
    "bench_video_reps":   5,
    "bench_sources":      ["meridian_120s", "bbb_120s"],
    # Variance is gated by the existing `variance_runs` slider (0 = skip), not a
    # bench_run_* flag — see benchmark.MEASURES["variance"].enabled_fn.
    "bench_run_video":    True,
    "bench_run_llm":      True,
    "bench_run_rag":      True,
    "bench_run_image":    True,
}


def load() -> dict:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            return {**DEFAULTS, **{k: data[k] for k in DEFAULTS if k in data}}
        except Exception:
            pass
    return dict(DEFAULTS)


def save(data: dict) -> dict:
    """Partial-update save: any key in `data` that is also a recognised
    setting overwrites the on-disk value; every other key is preserved.

    Previously this merged against DEFAULTS instead of the current state,
    which silently wiped variance calibration outputs (variance_*_pct)
    on every POST /settings call that didn't include them. The fix is
    to merge against load() — load() already overlays DEFAULTS with the
    on-disk file, so the merge base is what's actually live.
    """
    current = load()
    merged = {**current, **{k: data[k] for k in DEFAULTS if k in data}}
    SETTINGS_FILE.write_text(json.dumps(merged, indent=2))
    return merged
