"""
decode_run.py — Stage 2 of /decode: decode runs from the page, v2.

v2 (2026-07-29 design talk): MODE is the first-class choice.
  headless — devices are fully independent (own meter, own silicon, no shared
             resource), so selected devices run IN PARALLEL: one queue job
             fans out to one bench.py per device. Pis decode to null (pure
             decode); the GTV always renders (Android has no null sink) — its
             headless rows carry a display caveat and the screen simply is
             not claimed.
  screen   — exclusive, one device: the run claims the shared monitor first,
             meters it as context (Lab-E), and (default on) brackets the
             content rows with a white/black PANEL CALIBRATION pair — the
             probe that measured white−black = +5.0 W on this LCD
             (2026-07-29), anchoring every session against panel drift.

Templates are device-agnostic row sets (content × codec × regime); the
device selection composes with them at materialisation time, with live
addresses from rig.RIG. The proven July harness
(/srv/data/owl/decode-bench/bench.py) does every measured second; progress
is parsed from its phase log lines per device.

Results: ONE combined envelope per run — devices side by side (the July
report's cross-device tables, live), plus a flattened top-level `runs` list
(device-stamped) for the generic results machinery.
"""
import asyncio
import json
import logging
import re
import statistics
import subprocess
import time
from pathlib import Path

import rig
from persist import save_result
from runtime import jobs

log = logging.getLogger(__name__)

BENCH_DIR = Path("/srv/data/owl/decode-bench")
BENCH = BENCH_DIR / "bench.py"
STREAMS = BENCH_DIR / "streams"
STREAM_BASE_URL = "http://192.168.1.62:8123"
_WL_ENV = "WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000"

MODES = ("headless", "screen")

# --- Templates (device-agnostic) --------------------------------------------
TEMPLATES: dict = {
    "bbb_h264_smoke": {
        "label": "Smoke — BBB H.264, one 90 s row",
        "clips": {"bbb_h264_smoke": "bbb_h264_6min.mp4"},
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 15,
                  "startup_skip_s": 10, "window_s": 90, "gap_s": 5},
    },
    "bbb_h264_rt": {
        "label": "BBB H.264 — realtime 150 s (July replication row)",
        "clips": {"bbb_h264_rt": "bbb_h264_6min.mp4"},
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 15,
                  "startup_skip_s": 8, "window_s": 150, "gap_s": 10},
    },
    "bbb_h264_4k": {
        "label": "BBB H.264 4K — 90 s (resolution vs 1080p, same content)",
        "clips": {"bbb_h264_4k": "bbb_h264_4k_2min.mp4"},
        # Same BBB content upscaled to 3840×2160@60 (NVENC ~20 Mbps), so a run
        # against the 1080p templates isolates RESOLUTION as the only variable
        # — the Nov-2025 hackathon's dominant server-side driver, now on the
        # client. NB fixed-function boxes (GTV) handle 4K60 in hardware;
        # Pi 5 software-decoding 4K60 H.264 is a genuine stress test — if it
        # can't sustain realtime the row still measures what it does (a result
        # in itself). 120 s clip fits the 90 s window + 15 s marker head.
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 15,
                  "startup_skip_s": 8, "window_s": 90, "gap_s": 10},
    },
    "bbb_h264_hw_rt": {
        "label": "Pi 400 HW H.264 (v4l2m2m) — realtime 150 s · Pi 400 only",
        "clips": {"bbb_h264_hw_rt": "bbb_h264_6min.mp4"},
        # bcm2835-codec stateful decoder — the block the Pi 5 dropped; July
        # measured +0.35 W vs +1.25 W software on the same board (3.6×);
        # UI re-measured +0.22 W (2026-07-30, run 270ba366).
        "decoder": "h264_v4l2m2m",
        "devices": ["pi400"],   # only board with a reachable H.264 block
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 15,
                  "startup_skip_s": 8, "window_s": 150, "gap_s": 10},
    },
    "bbb_h264_hw_sat": {
        "label": "Pi 400 HW H.264 saturated (race-to-idle) — 150 s · Pi 400 only",
        "clips": {"bbb_h264_hw_sat": "bbb_h264_6min.mp4"},
        # Saturated regime pair for bbb_h264_hw_rt (R6 reconciliation,
        # 2026-08-08): -stream_loop -1 instead of -re, decoder runs flat out.
        # Sustained ΔW, comparable to July's pi_unpaced/pi_sw_matrix rows —
        # never compare a saturated row to a realtime one.
        "decoder": "h264_v4l2m2m",
        "pacing": "saturated",
        "devices": ["pi400"],
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 15,
                  "startup_skip_s": 8, "window_s": 150, "gap_s": 10},
    },
    "bbb_h264_sw_sat": {
        "label": "SW H.264 saturated (race-to-idle) — 150 s · Pi boards only",
        "clips": {"bbb_h264_sw_sat": "bbb_h264_6min.mp4"},
        "pacing": "saturated",
        "devices": ["pi400", "pi5"],   # ffmpeg-over-ssh path only
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 15,
                  "startup_skip_s": 8, "window_s": 150, "gap_s": 10},
    },
    "bbb_h264_gtv_local": {
        "label": "GTV local-file H.264 — delivery share removed · GTV only",
        "clips": {"bbb_h264_local": "bbb_h264_6min.mp4"},
        # July's delivery decomposition arm: clip pushed to the box, played
        # via file:///sdcard/Download/… — the ~+0.21 W network share is out,
        # leaving decode+render+player. Pair with the Pi 400 screen HW arm
        # for the honest like-for-like cross-device comparison.
        "delivery": "local",
        "devices": ["gtv"],
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 5,
                  "startup_skip_s": 8, "window_s": 150, "gap_s": 10},
    },
    "bbb_h264_best_rt": {
        "label": "BBB H.264 best-path — Pi 5 SW · Pi 400 HW · GTV HW, parallel",
        "clips": {"bbb_h264_best": "bbb_h264_6min.mp4"},
        # Each board on its best decode path: Pi 400 names its hardware block,
        # Pi 5 has none (software IS its best path), the GTV's pipeline is
        # always fixed-function. The cross-silicon table from the July report,
        # as one parallel run.
        "decoder_by_device": {"pi400": "h264_v4l2m2m"},
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 15,
                  "startup_skip_s": 8, "window_s": 150, "gap_s": 10},
    },
    "bbb_codecs_rt": {
        "label": "BBB codec panel — H.264 / HEVC / AV1, realtime 150 s each",
        "clips": {"bbb_h264_rt": "bbb_h264_6min.mp4",
                  "bbb_hevc_rt": "bbb_h265_6min.mp4",
                  "bbb_av1_rt": "bbb_av1_6min.mp4"},
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 15,
                  "startup_skip_s": 8, "window_s": 150, "gap_s": 10},
    },
}

# Parametric loop templates (2026-07-31): family × codec, tester-set duration
# via the window_s override on /decode/run (30–3600 s). H.264 points at the
# 60-min concatenated clips so even a ~1 h window never runs out; H.265/AV1 use
# the 20-min clips (their runs stay short). No player-side looping needed — the
# clip is always longer than the window and bench.py stops at window_s.
LOOP_FAMILIES = ("bbb", "meridian", "kranjska")
LOOP_CODECS = ("h264", "h265", "av1")
for _fam in LOOP_FAMILIES:
    for _cod in LOOP_CODECS:
        _clip = (f"{_fam}_{_cod}_60min.mp4" if _cod == "h264"
                 else f"{_fam}_{_cod}_20min.mp4")
        TEMPLATES[f"loop_{_fam}_{_cod}"] = {
            "label": f"Loop — {_fam.upper()} {_cod.upper()} (tester-set duration)",
            "clips": {f"{_fam}_{_cod}_loop": _clip},
            "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 5,
                      "startup_skip_s": 8, "window_s": 150, "gap_s": 10},
        }

# Screen-mode marker head (2026-07-30, Ben's design): 5 s black · 5 s white ·
# 5 s black prepended to the CONTENT clip as one contiguous video (content
# stream-copied — re-encoding would change the decode workload; markers are
# codec/res/fps-matched NVENC segments). At 1 s cadence each segment carries
# ~5 samples; raw per-second samples are persisted, so the panel response
# segments out post-hoc by edge detection — the hackathon energy-signature
# technique, one row instead of the old 2×90 s bracket.
MARKER_HEAD_S = 15
_MARKER_PATTERN = "black5-white5-black5"


def protocol_settings() -> dict:
    """The decode protocol knobs — /settings wins over template defaults
    (owner directive 2026-07-30: all parameters in /settings; same machinery
    as GoS1 where possible). idle_guard present ⇒ protocol v3 (the guard is
    a protocol change vs the July rows — envelopes carry the stamp)."""
    import settings as _cfg
    s = _cfg.load()
    guard = None
    if s.get("decode_idle_guard", True) in (True, "true", "on", "1", 1):
        guard = {"tolerance_w": float(s.get("decode_idle_tolerance_w", 0.5)),
                 "settle_polls": int(s.get("decode_idle_settle_polls", 4)),
                 # 30 s cap (was 60): with idle_w floors tuned to real awake
                 # idle, settle is a few s; the cap just bounds a noisy panel
                 # (C2) rather than being the common path (2026-07-31).
                 "max_wait_s": int(s.get("decode_idle_max_wait_s", 30))}
    return {
        "cadence_s": float(s.get("decode_cadence_s", 1.0)),
        # Short post-prepare quiesce only — the idle guard owns "are we at
        # the floor yet" (default was 15 s pre-guard; lowered 2026-07-30).
        "settle_s": int(s.get("decode_settle_s", 5)),
        "baseline_samples": int(s.get("decode_baseline_samples", 20)),
        "screen_startup_skip_s": int(s.get("decode_screen_startup_skip_s", 5)),
        "idle_guard": guard,
        "protocol_version": 3 if guard else 2,
    }


def template_phases(tpl: dict, window_s: int | None = None,
                    cadence_s: float | None = None) -> list:
    b = tpl["bench"]
    cad = cadence_s if cadence_s is not None else b["cadence_s"]
    win = int(window_s) if window_s is not None else b["window_s"]
    return [("settle", b["settle_s"]),
            ("baseline", round(b["baseline_samples"] * cad)),
            ("starting", b["startup_skip_s"]),
            ("sampling", win),        # honour the tester-set duration override
            ("finishing", 5)]


_PHASE_PATTERNS = [
    (re.compile(r": settle "), "settle"),
    (re.compile(r": baseline "), "baseline"),
    (re.compile(r": started — sampling|: started - sampling"), "sampling"),
    (re.compile(r": base=.*task=.*dW="), "finishing"),
]
# bench.py's live sample feed (added 2026-07-29): "] sample 4.958W ctx=30.66W"
_SAMPLE_RE = re.compile(r"\] sample ([0-9.]+)W(?: ctx=([0-9.]+)W)?")


# --- Materialisation ---------------------------------------------------------

def _row_for(dev_cfg: dict, name: str, clip: str, mode: str,
             window_s: int | None = None, decoder: str | None = None,
             delivery: str = "http", pacing: str = "realtime") -> dict:
    row: dict = {"name": name}
    if window_s:
        row["window_s"] = window_s
    if pacing == "saturated" and (mode == "screen" or dev_cfg["kind"] != "ssh"):
        # Real players pace themselves — a saturated row only exists on the
        # headless ffmpeg-over-ssh path. Refuse rather than silently pace.
        raise ValueError("saturated pacing is headless ssh only")
    if dev_cfg["kind"] == "webos":
        # C2 native decode: the harness WebosDevice launches this URL in the
        # built-in browser; its own SoC decodes+displays (no cmd/player).
        row["url"] = f"{STREAM_BASE_URL}/{clip}"
        return row
    if dev_cfg["kind"] == "adb":
        if delivery == "local":
            # July delivery-decomposition arm — clip staged by adb push.
            row["url"] = f"file:///sdcard/Download/decode/{Path(clip).name}"
        else:
            row["url"] = f"{STREAM_BASE_URL}/{clip}"
        return row
    shm = Path(clip).name       # staged flat into /dev/shm/decode/
    if mode == "screen":
        # Pin scanout to the July display protocol (1080p60) before playback:
        # discovered live 2026-07-30 that both Pis default to 4K on this
        # panel — the Pi 400 (4K30 ceiling) then renders mpv --fs unscaled
        # in a quarter of the screen, and 4K scanout differs from every July
        # display-attached baseline anyway.
        # --hwdec=v4l2m2m-copy, NOT auto: auto picks the zero-copy path,
        # which decodes but composites garbage (full-blue screen, live
        # 2026-07-30); the copy variant displays correctly (BBB verified
        # on the Pi 400 by eye).
        hw = "--hwdec=v4l2m2m-copy " if decoder else ""
        row["cmd"] = (
            f"o=$({_WL_ENV} wlr-randr | awk '/^[[:alnum:]]/{{print $1}}' | head -1); "
            f"{_WL_ENV} wlr-randr --output $o --mode 1920x1080@60; sleep 2; "
            f"{_WL_ENV} mpv --fs --no-audio --loop=inf {hw}/dev/shm/decode/{shm}")
        row["stop_cmd"] = "pkill mpv"
    else:
        stem = Path(clip).stem
        dec = f"-c:v {decoder} " if decoder else ""
        pace = "-re " if pacing == "realtime" else "-stream_loop -1 "
        row["cmd"] = (f"ffmpeg -nostdin {pace}{dec}-i /dev/shm/decode/{shm} "
                      f"-an -f null - ")
        row["stop_cmd"] = f"pkill -f 'ffmpeg.*{stem}'"
    return row


def _materialize(job_id: str, tpl_key: str, dev_name: str, mode: str,
                 calibrate: bool, upload_name: str | None = None,
                 cadence_s: float | None = None,
                 window_s: int | None = None) -> Path:
    tpl = resolve_template(tpl_key, upload_name)
    dev_cfg = rig.RIG["devices"][dev_name]
    marked = mode == "screen" and calibrate
    base_window = int(window_s) if window_s is not None else tpl["bench"]["window_s"]
    runs = []
    for run_name, clip in tpl["clips"].items():
        decoder = (tpl.get("decoder")
                   or (tpl.get("decoder_by_device") or {}).get(dev_name))
        delivery = tpl.get("delivery", "http")
        pacing = tpl.get("pacing", "realtime")
        if marked:
            # Marker-headed variant: window extends over the 15 s head; the
            # skip shrinks so the head lands inside the sampled window.
            runs.append(_row_for(dev_cfg, run_name, marked_name(clip), mode,
                                 window_s=base_window + MARKER_HEAD_S,
                                 decoder=decoder, delivery=delivery,
                                 pacing=pacing))
        else:
            runs.append(_row_for(dev_cfg, run_name, clip, mode,
                                 decoder=decoder, delivery=delivery,
                                 pacing=pacing))
    cfg = dict(tpl["bench"])
    proto = protocol_settings()
    cfg.update({k: proto[k] for k in
                ("cadence_s", "settle_s", "baseline_samples",
                 "protocol_version")})
    if cadence_s is not None:
        cfg["cadence_s"] = float(cadence_s)   # per-run slider override
    cfg["window_s"] = base_window             # tester-set duration override
    if proto["idle_guard"]:
        # Reference mode when the device's settled idle is known (rig
        # config) — same asymmetric floor semantics as GoS1's CR-070 guard.
        # Self-stability alone settles on post-boot plateaus (negative-ΔW
        # incident 2026-07-30, run 57e8ba84).
        cfg["idle_guard"] = dict(proto["idle_guard"])
        if dev_cfg.get("idle_w") is not None:
            cfg["idle_guard"]["reference_w"] = dev_cfg["idle_w"]
    if marked:
        cfg["startup_skip_s"] = proto["screen_startup_skip_s"]
    cfg["name"] = f"ui-{tpl_key}-{job_id}-{dev_name}"
    cfg["meter_ip"] = dev_cfg["plug_ip"]
    # The C2's device plug IS the monitor plug (Lab-E) — no separate screen
    # meter, so skip the context meter (it would just duplicate meter_ip).
    if mode == "screen" and dev_cfg["kind"] != "webos":
        cfg["monitor_meter_ip"] = rig.RIG["monitor"]["plug_ip"]
    if dev_cfg["kind"] == "adb":
        cfg["device"] = {"type": "adb", "serial": dev_cfg["target"],
                         "player": "com.brouken.player"}
    elif dev_cfg["kind"] == "webos":
        cfg["device"] = {"type": "webos", "host": dev_cfg["target"]}
    else:
        user, host = dev_cfg["target"].split("@", 1)
        cfg["device"] = {"type": "ssh", "host": host, "user": user}
    cfg["runs"] = runs
    path = Path(f"/tmp/owl-decode-{job_id}-{dev_name}.json")
    path.write_text(json.dumps(cfg, indent=1))
    return path


def segment_marker_trace(w: list) -> dict | None:
    """Split a screen trace with the black·white·black marker head into
    segment means — the hackathon energy-signature technique, automated.

    Edge-detects (threshold at the head's lo/hi midpoint) rather than
    trusting clocks, so the mode-resync transient and start offsets don't
    matter. Per segment the first sample is dropped as transition; the first
    black's mean uses only its last 4 samples (the resync transient can
    extend that run). Returns None when no credible marker pattern is found
    (e.g. headless rows, panel not responding)."""
    if not w or len(w) < 12:
        return None
    n_head = MARKER_HEAD_S + 8
    head = w[:n_head]

    def _sustained(candidates):
        """First candidate with ≥3 head samples within ±0.6 W — a one-off
        transient (e.g. the 13 W mode-resync dip) can't form a rail."""
        for v in candidates:
            if sum(1 for x in head if abs(x - v) <= 0.6) >= 3:
                return v
        return None

    lo = _sustained(sorted(head))
    hi = _sustained(sorted(head, reverse=True))
    if lo is None or hi is None or hi - lo < 1.0:
        return None
    mid = (lo + hi) / 2
    runs = []          # [is_high, start_idx, end_idx]
    for i, x in enumerate(head):
        st = x >= mid
        if runs and runs[-1][0] == st:
            runs[-1][2] = i
        else:
            runs.append([st, i, i])
    def _mean(lo_i, hi_i):
        xs = w[lo_i:hi_i + 1]
        return round(statistics.mean(xs), 2) if xs else None

    for j in range(len(runs) - 2):
        a, b, c = runs[j], runs[j + 1], runs[j + 2]
        if ((not a[0]) and b[0] and (not c[0])
                and min(a[2] - a[1], b[2] - b[1], c[2] - c[1]) >= 2):
            black = _mean(max(a[1] + 1, a[2] - 3), a[2])
            white = _mean(b[1] + 1, b[2])
            black2 = _mean(c[1] + 1, c[2])
            content = (round(statistics.mean(w[c[2] + 2:]), 2)
                       if len(w) > c[2] + 2 else None)
            return {"black_w": black, "white_w": white, "black2_w": black2,
                    "content_w": content,
                    "marker_swing_w": (round(white - min(black, black2), 2)
                                       if white and black and black2 else None),
                    "content_from_idx": c[2] + 2}
    # Fallback: leading black consumed by the playback start-skip (GTV rows —
    # no mode-set delay, so the window opens mid-head): accept white→black
    # when the white run starts within the first ~4 samples.
    for j in range(min(2, len(runs) - 1)):
        b, c = runs[j], runs[j + 1]
        if (b[0] and (not c[0]) and b[1] <= 4
                and (b[2] - b[1]) >= 2 and (c[2] - c[1]) >= 2):
            white = _mean(b[1] + 1, b[2])
            black2 = _mean(c[1] + 1, c[2])
            content = (round(statistics.mean(w[c[2] + 2:]), 2)
                       if len(w) > c[2] + 2 else None)
            return {"black_w": None, "white_w": white, "black2_w": black2,
                    "content_w": content,
                    "marker_swing_w": (round(white - black2, 2)
                                       if white and black2 else None),
                    "content_from_idx": c[2] + 2,
                    "note": "leading black consumed by start-skip"}
    return None


UPLOADS_SUBDIR = "_uploads"     # inside STREAMS → served by :8123 for the GTV


def marked_name(clip: str) -> str:
    """marked_ variant path for a clip, subdir-safe (_uploads/x.mp4 →
    _uploads/marked_x.mp4)."""
    p = Path(clip)
    return str(p.parent / f"marked_{p.name}") if p.parent != Path(".") \
        else f"marked_{clip}"


def _clip_duration_s(clip: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(STREAMS / clip)],
        capture_output=True, text=True, check=True, timeout=30).stdout.strip()
    return float(out)


def resolve_template(tpl_key: str, upload_name: str | None) -> dict:
    """TEMPLATES[key], or a dynamic single-row template for an uploaded clip
    (key 'upload'). Upload window fits the clip: min(150 s, duration − 15 s),
    floor 30 s — a too-short window is refused rather than measured wrong."""
    if tpl_key != "upload":
        return TEMPLATES[tpl_key]
    clip = f"{UPLOADS_SUBDIR}/{upload_name}"
    dur = _clip_duration_s(clip)
    window = min(150, int(dur) - 15)
    if window < 30:
        raise ValueError(f"clip too short ({dur:.0f}s) — need ≥45 s")
    return {"label": f"uploaded clip — {upload_name}",
            "clips": {"uploaded_clip": clip},
            "bench": {"cadence_s": 1.0, "baseline_samples": 20,
                      "settle_s": 15, "startup_skip_s": 8,
                      "window_s": window, "gap_s": 10}}


def _needed_clips(tpl: dict, mode: str, calibrate: bool) -> list:
    clips = list(tpl["clips"].values())
    if mode == "screen" and calibrate:
        return [marked_name(c) for c in clips]
    return clips


_FFMPEG = "/usr/local/bin/ffmpeg-master"
_NVENC = {"h264": "h264_nvenc", "hevc": "hevc_nvenc", "av1": "av1_nvenc"}


def _ensure_marked_clips_sync(clips: list) -> None:
    """Build `marked_<clip>` (5 s black·white·black head + stream-copied
    content) for any clip missing its marked variant. Marker segments are
    codec/res/fps-matched NVENC encodes, cached in streams/marked_segments/."""
    ff = _FFMPEG if Path(_FFMPEG).exists() else "ffmpeg"
    seg_dir = STREAMS / "marked_segments"
    seg_dir.mkdir(exist_ok=True)
    for clip in clips:
        dst = STREAMS / marked_name(clip)
        if dst.exists():
            continue
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,width,height,r_frame_rate,pix_fmt",
             "-of", "csv=p=0", str(STREAMS / clip)],
            capture_output=True, text=True, check=True, timeout=30).stdout.strip()
        codec, w, h, pix, fps = probe.split(",")
        enc = _NVENC.get(codec)
        if enc is None:
            raise RuntimeError(f"no marker encoder for codec {codec!r}")
        seg_paths = []
        for seg, color in (("black", "black"), ("white", "white"),
                           ("black2", "black")):
            seg_p = seg_dir / f"{codec}_{w}x{h}_{fps.split('/')[0]}_{seg}.mp4"
            if not seg_p.exists():
                subprocess.run(
                    [ff, "-loglevel", "error", "-f", "lavfi",
                     "-i", f"color=c={color}:s={w}x{h}:r={fps}", "-t", "5",
                     "-pix_fmt", pix, "-c:v", enc, "-y", str(seg_p)],
                    check=True, timeout=120)
            seg_paths.append(seg_p)
        listing = "".join(f"file '{p}'\n" for p in seg_paths
                          + [STREAMS / clip])
        list_path = Path(f"/tmp/owl-marked-{Path(clip).name}.txt")
        list_path.write_text(listing)
        try:
            subprocess.run(
                [ff, "-loglevel", "error", "-f", "concat", "-safe", "0",
                 "-i", str(list_path), "-c", "copy", "-y", str(dst)],
                check=True, timeout=600)
        finally:
            list_path.unlink(missing_ok=True)


def _stage_clips_sync(dev_cfg: dict, clips: list) -> None:
    target = dev_cfg["target"]
    # Purge first: /dev/shm is RAM-backed (8 GB on the Pi 5) and staged clips
    # accumulate across runs. Without this the long campaign clips fill it and
    # later/larger clips stage TRUNCATED and fail to decode — the Pi 5 kranjska
    # 5.2 GB clip hit a 100%-full /dev/shm mid-campaign (2026-07-31). Each run
    # now stages only its own clip(s) into a clean shm (largest single ≈5 GB).
    subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                    target, "rm -f /dev/shm/decode/*; mkdir -p /dev/shm/decode"],
                   check=True, timeout=20)
    for clip in clips:
        subprocess.run(["scp", "-o", "BatchMode=yes",
                        str(STREAMS / clip), f"{target}:/dev/shm/decode/"],
                       check=True, timeout=600)


def _stage_clips_adb_sync(dev_cfg: dict, clips: list) -> None:
    """Local-delivery staging for the GTV: adb push to /sdcard/Download/decode
    (the July decomposition arm's location; Just Player has media perms)."""
    serial = dev_cfg["target"]
    adb = rig.ADB_BIN
    subprocess.run([adb, "connect", serial], capture_output=True, timeout=15)
    subprocess.run([adb, "-s", serial, "shell", "mkdir", "-p",
                    "/sdcard/Download/decode"], check=True, timeout=20)
    for clip in clips:
        subprocess.run([adb, "-s", serial, "push", str(STREAMS / clip),
                        f"/sdcard/Download/decode/{Path(clip).name}"],
                       check=True, capture_output=True, timeout=600)


# --- Orchestration -----------------------------------------------------------

async def _wait_ready(name: str, sub: dict, timeout_s: float) -> None:
    dev = rig.rig_cache["devices"][name]
    if dev["state"] == "off":
        await rig.device_on(name)
    is_webos = rig.RIG["devices"][name].get("kind") == "webos"
    t0 = time.monotonic()
    last_wake = 0.0
    while time.monotonic() - t0 < timeout_s:
        if dev["state"] == "ready":
            return
        if is_webos and time.monotonic() - last_wake > 8:
            # The C2 drops into Always-Ready standby between queued jobs and
            # then rejects SSAP — the poller (rightly) never auto-wakes the
            # household TV, so a job that WANTS the C2 must wake it itself.
            # A 1 h C2 row was lost to "not ready after 90s" (2026-08-15).
            await asyncio.to_thread(rig.lg.wake)
            last_wake = time.monotonic()
        if dev["state"] in ("stuck", "unreachable", "unpowered"):
            raise RuntimeError(f"device is {dev['state']}")
        sub["detail"] = f"device {dev['state']}"
        await asyncio.sleep(3)
    raise RuntimeError(f"not ready after {int(timeout_s)}s")


async def _run_bench_for(job_id: str, tpl_key: str, tpl: dict, name: str,
                         mode: str, calibrate: bool, sub: dict,
                         upload_name: str | None = None,
                         cadence_s: float | None = None,
                         window_s: int | None = None) -> dict:
    """Full per-device pipeline: ready → stage → bench.py → rows. Updates
    `sub` (the job's per-device progress dict) as it goes; returns the
    device section of the combined envelope. Raises on failure."""
    dev_cfg = rig.RIG["devices"][name]
    d = rig.rig_cache["devices"][name]
    cfg_path = None
    paused: set = set()
    try:
        sub.update({"stage": "device", "phase_started": time.monotonic()})
        await _wait_ready(name, sub, 3 * dev_cfg["expected_boot_s"] + 45)

        if dev_cfg["kind"] == "ssh":
            sub.update({"stage": "staging",
                        "detail": "copying clips to /dev/shm"})
            await asyncio.to_thread(_stage_clips_sync, dev_cfg,
                                    _needed_clips(tpl, mode, calibrate))
        elif tpl.get("delivery") == "local":
            sub.update({"stage": "staging",
                        "detail": "adb push to /sdcard/Download"})
            await asyncio.to_thread(_stage_clips_adb_sync, dev_cfg,
                                    _needed_clips(tpl, mode, calibrate))

        cfg_path = _materialize(job_id, tpl_key, name, mode, calibrate,
                                upload_name, cadence_s, window_s)
        cfg = json.loads(cfg_path.read_text())
        result_path = BENCH_DIR / "results" / f"{cfg['name']}.json"

        d["busy"] = True
        rig.touch_activity(f"decode job {job_id} on {name}")
        paused = {cfg["meter_ip"]}
        if cfg.get("monitor_meter_ip"):
            paused.add(cfg["monitor_meter_ip"])
        rig.PAUSED_PLUGS |= paused
        sub.update({"stage": "settle", "row": 0,
                    "phase_started": time.monotonic(), "detail": ""})

        proc = await asyncio.create_subprocess_exec(
            "python3", str(BENCH), str(cfg_path), cwd=str(BENCH_DIR),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            # 8 MB line buffer: the default 64 KB overflowed on a 4K / 5-device
            # run (a long bench line) with "Separator is not found, and chunk
            # exceed the limit", killing the whole run (2026-07-31).
            limit=8 * 1024 * 1024)
        lines = []
        row_i = 0
        while True:
            try:
                raw = await proc.stdout.readline()
            except (asyncio.LimitOverrunError, ValueError):
                # Pathologically long line (>8 MB) — drain a bounded chunk and
                # carry on rather than crash the run; bench.py still writes the
                # row's own result file. (A plain re-read would hit the same
                # limit; read(n) can't.)
                try:
                    chunk = await proc.stdout.read(1024 * 1024)
                except Exception:
                    chunk = b""
                if not chunk:
                    break
                continue
            if not raw:
                break
            line = raw.decode(errors="replace").rstrip()
            m = _SAMPLE_RE.search(line)
            if m:
                sub["live_w"] = float(m.group(1))
                if m.group(2):
                    sub["monitor_w"] = float(m.group(2))
                continue
            lines.append(line)
            for pat, phase in _PHASE_PATTERNS:
                if pat.search(line):
                    if phase == "settle":
                        row_i += 1
                    sub.update({"stage": phase, "row": row_i,
                                "phase_started": time.monotonic(),
                                "detail": line.split("] ")[-1][:120]})
                    break
        rc = await proc.wait()
        if rc != 0 or not result_path.exists():
            raise RuntimeError(
                f"bench.py exit {rc}: {' | '.join(lines[-3:])[:300]}")
        bench_out = json.loads(result_path.read_text())
        if mode == "screen" and calibrate:
            # The marker head shows up on the SCREEN meter. For HDMI devices
            # that's the separate monitor/context trace; for the C2 the panel
            # IS the primary meter (Lab-E), so the head is in the task trace.
            marker_key = ("raw_task_w" if dev_cfg["kind"] == "webos"
                          else "raw_context_w")
            for row in bench_out.get("rows", []):
                seg = segment_marker_trace(row.get(marker_key) or [])
                if seg:
                    row["screen_marker_segments"] = seg
        section = {
            "label": dev_cfg["label"], "kind": dev_cfg["kind"],
            "meter": {"model": "Tapo P110", "ip": cfg["meter_ip"],
                      "fw": "1.3.1", "cadence_s": cfg["cadence_s"]},
            "rows": bench_out.get("rows", []),
        }
        # Keep the bench's phase log tail (samples excluded) when any row
        # errored — the only place the failure sequence survives (2026-08-15).
        if any("error" in r for r in section["rows"]):
            section["log_tail"] = lines[-40:]
        if dev_cfg["kind"] == "adb" and mode == "headless":
            section["display_caveat"] = (
                "Android renders regardless of the shared monitor; headless "
                "here means the screen was not claimed — rows are indicative "
                "vs the Pis' true null-sink decode (July 2026 convention).")
        sub.update({"stage": "done", "detail": ""})
        return section
    except Exception as e:
        sub.update({"stage": "error", "detail": str(e)[:200]})
        raise
    finally:
        d["busy"] = False
        rig.touch_activity(f"decode job {job_id} on {name} finished")
        rig.PAUSED_PLUGS -= paused
        if cfg_path:
            cfg_path.unlink(missing_ok=True)


async def run_decode_job(job_id: str, tpl_key: str, devices: list,
                         mode: str, calibrate: bool,
                         upload_name: str | None = None,
                         cadence_s: float | None = None,
                         window_s: int | None = None) -> None:
    tpl = resolve_template(tpl_key, upload_name)
    job = jobs[job_id]
    phases = template_phases(tpl, window_s, cadence_s)
    n_rows = len(tpl["clips"])
    job.update({"status": "running", "stage": "running",
                "template": tpl_key, "mode": mode, "calibrate": calibrate,
                "phases": phases, "row_n": n_rows,
                "devices": {name: {"stage": "queued", "row": None,
                                   "detail": "", "phase_started": None}
                            for name in devices}})
    try:
        if mode == "screen" and calibrate:
            job["stage"] = "preparing marker clips"
            await asyncio.to_thread(_ensure_marked_clips_sync,
                                    list(tpl["clips"].values()))
        if mode == "screen":
            # Exclusive: power/ready first, then hand it the monitor.
            name = devices[0]
            if rig.RIG["devices"][name]["kind"] == "webos":
                # Boot the panel to a fresh Home first: a screensaver-free,
                # reproducible baseline (the screensaver can't be disabled via
                # API, only pushed to 30 min, and may already be running).
                # Also avoids racing bench.py's webOS connection — the C2 IS
                # the panel, so there's no HDMI input to claim.
                job["devices"][name]["detail"] = "power-cycling panel"
                await rig.recycle_c2_panel(name)
            else:
                await _wait_ready(name, job["devices"][name],
                                  3 * rig.RIG["devices"][name]["expected_boot_s"] + 45)
                job["devices"][name]["detail"] = "claiming screen"
                await rig.claim_screen(name)

        outcomes = await asyncio.gather(
            *[_run_bench_for(job_id, tpl_key, tpl, name, mode, calibrate,
                             job["devices"][name], upload_name, cadence_s,
                             window_s)
              for name in devices],
            return_exceptions=True)

        sections, flat_runs, errors = {}, [], {}
        for name, out in zip(devices, outcomes):
            if isinstance(out, Exception):
                errors[name] = str(out)[:300]
                sections[name] = {"error": errors[name]}
            else:
                sections[name] = out
                for r in out["rows"]:
                    flat_runs.append({**r, "device": name})
        if not flat_runs:
            raise RuntimeError("all devices failed: " + json.dumps(errors))

        envelope = {
            "mode": f"ui_{mode}",
            "template": tpl_key,
            "template_label": tpl["label"],
            "calibrate": bool(mode == "screen" and calibrate),
            "devices": sections,
            "runs": flat_runs,
            "protocol": {"harness": "decode-bench bench.py",
                         "launched_from": "/decode", "parallel": mode == "headless",
                         "window_s": tpl["bench"]["window_s"],
                         "pacing": tpl.get("pacing", "realtime"),
                         **({"marker_head": {"pattern": _MARKER_PATTERN,
                                             "seconds": MARKER_HEAD_S,
                                             "note": "in-window; segment via "
                                                     "raw-sample edge detection"}}
                            if mode == "screen" and calibrate else {}),
                         **{**protocol_settings(),
                            **({"cadence_s": float(cadence_s)}
                               if cadence_s is not None else {})}},
        }
        save_result("decode", job_id, envelope)
        status = "done" if not errors else "done"
        job.update({"status": status, "stage": "done", "result": envelope,
                    "partial_errors": errors or None})
    except Exception as e:
        log.warning("decode job %s failed: %s", job_id, e)
        job.update({"status": "error", "stage": "error", "error": str(e)})
    finally:
        if upload_name:
            # Same retention rules as /enhance-run: evict-class uploads are
            # deleted at run end, proc/keep follow uploads.py's sweep. The
            # generated marked_ variant is always removed (regenerable).
            import uploads
            up_dir = STREAMS / UPLOADS_SUBDIR
            await asyncio.to_thread(uploads.cleanup_after_job, up_dir,
                                    upload_name)
            (up_dir / f"marked_{upload_name}").unlink(missing_ok=True)
