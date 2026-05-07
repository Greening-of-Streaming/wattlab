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
    # Confidence — variance-based ΔW thresholds (replace old conf_*_delta_w)
    "variance_pct": 2.0,        # measured system variance as % of baseline power
    "variance_green_x": 5.0,    # 🟢  ΔW must exceed this × noise_w
    "variance_yellow_x": 2.0,   # 🟡  ΔW must exceed this × noise_w
    # Variance calibration outputs (written by calibration run, not user-edited)
    "variance_idle_pct": None,   # CV of raw idle P110 readings across all baseline periods
    "variance_cpu_pct": None,    # CV of ΔW across H264-CPU runs
    "variance_gpu_pct": None,    # CV of ΔW across H265-GPU runs
    # Variance calibration run parameters
    "variance_runs": 10,         # how many H264-CPU + H265-GPU pairs to run
    "variance_cooldown_s": 60,   # seconds between each run pair
    "variance_cpu_cmd": (
        "ffmpeg -y -i {input} -c:v libx264 -crf 23"
        " -vf scale=-2:1080 -c:a aac -b:a 128k {output}"
    ),
    "variance_gpu_cmd": (
        "ffmpeg -y -hwaccel vaapi -hwaccel_output_format vaapi"
        " -extra_hw_frames 32"
        " -vaapi_device /dev/dri/renderD128 -i {input}"
        " -vf scale_vaapi=w=-2:h=1080:format=nv12"
        " -c:v hevc_vaapi -qp 28 -c:a aac -b:a 128k {output}"
    ),
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
