import json
from pathlib import Path

SETTINGS_FILE = Path("/home/gos/wattlab/settings.json")

DEFAULTS = {
    "baseline_polls": 10,
    "video_cooldown_s": 60,
    "llm_rest_s": 10,
    "llm_unload_settle_s": 3,
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
    # Variance commands derive from video.PRESETS["cpu"] / ["h265_gpu"] at
    # run time (see video.variance_template). Hardcoded strings used to live
    # here but drifted out of sync with /video after S13's ABR migration —
    # calibration was on -crf 23 / -qp 28 while /video ran -b:v Nk.
    # Encoding targets — ABR bitrate per codec (applied to both CPU and GPU presets)
    "h264_bitrate_kbps": 4000,
    "h265_bitrate_kbps": 2000,
    "av1_bitrate_kbps":  1500,
    # ffmpeg binary path — installed side-by-side with Ubuntu's stock 6.1.1
    # so the system /usr/bin/ffmpeg stays untouched for anything else
    # linked against its shared libs. The static build at this path is
    # what fixes the scale_vaapi surface-pool leak that previously
    # required a -t cap on every VAAPI encode.
    "ffmpeg_bin": "/usr/local/bin/ffmpeg-master",
    # CR-044 — VMAF perceptual quality score on >1-video comparison cards.
    # Computed as a TERMINAL pass after a job's measurement window closes,
    # so its CPU draw never enters a reported energy figure. Requires the
    # libvmaf-enabled ffmpeg_bin (system /usr/bin/ffmpeg lacks it).
    "vmaf_enabled": True,
    "vmaf_n_subsample": 1,   # score every Nth frame (TEMPORAL only). 1 = full.
    "vmaf_n_threads": 12,    # libvmaf worker threads (box has 24 cores).
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
    # CR-050 — per-surface enabled model lists. Empty list (or absent key)
    # means "all available enabled" so a fresh server with no settings file
    # just works. Settings UI writes ordered lists; model_catalog filters
    # the auto-detected available set against these.
    "llm_enabled_models":   [],
    "rag_enabled_models":   [],
    "image_enabled_models": [],
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
