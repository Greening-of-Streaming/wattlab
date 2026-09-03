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
import shutil
import statistics
import subprocess
import time
from pathlib import Path

import decode_sync
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
    "bbb_h264_1080_upscale4k": {
        "label": "BBB H.264 1080p, device-upscaled to 4K — 90 s · Pi 5 only (R15 Leg A)",
        "clips": {"bbb_h264_upscale4k": "bbb_h264_6min.mp4"},
        # Same 1080p source and bench window as bbb_h264_4k, so the three-way
        # comparison is clean: native 1080p (bbb_h264_rt) vs native 4K
        # (bbb_h264_4k, server-upscaled at encode) vs THIS (1080p source,
        # device-side ffmpeg -vf scale to 4K during decode). Isolates the
        # scale step itself as the added variable over native-1080p decode.
        # RUN_QUEUE R15 Leg A (2026-08-30) — headless only, Pi 5 has no HDMI
        # attached (unplugged since 2026-08-19), so this is decode-only, not
        # decode+present; that's the same scoping bbb_h264_4k already uses.
        "output_scale": "3840x2160",
        "devices": ["pi5"],
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 15,
                  "startup_skip_s": 8, "window_s": 90, "gap_s": 10},
    },
    "bbb_codecs_rt": {
        "label": "BBB codec panel — H.264 / HEVC / AV1, realtime 150 s each",
        "clips": {"bbb_h264_rt": "bbb_h264_6min.mp4",
                  "bbb_hevc_rt": "bbb_h265_6min.mp4",
                  "bbb_av1_rt": "bbb_av1_6min.mp4"},
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 15,
                  "startup_skip_s": 8, "window_s": 150, "gap_s": 10},
    },
    # Sports tier (CR-081, 2026-09-03, owner's pick): broadcast-style football
    # coverage — Panasonic's "Barcelona Football" 4K demo as uploaded to
    # YouTube by The 4K Media Group (-gXGcLDIjPI): 3840×2160 **60 fps** SDR
    # AV1 (a 30 fps re-upload of the same demo, PVwUSv0eMzM, was rejected).
    # © Panasonic, re-uploaded by a third party — LAB-INTERNAL ONLY: no
    # licence to cite, never shown or redistributed outside the lab;
    # measurements on it are fine, the pictures are not. Replaces Kranjska
    # (1440×1080p30 mountain bike) as the sports family per Tania's call;
    # kranjska* families stay for the rows pooled on them. Built by
    # decode_bench/prep_family.py (family key "football").
    "football_codecs_rt": {
        "label": "Football codec panel — H.264 / HEVC / AV1, realtime 150 s each "
                 "(Panasonic Barcelona demo, 1080p60, lab-internal source)",
        "clips": {"football_h264_rt": "football_h264_6min.mp4",
                  "football_hevc_rt": "football_h265_6min.mp4",
                  "football_av1_rt": "football_av1_6min.mp4"},
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 15,
                  "startup_skip_s": 8, "window_s": 150, "gap_s": 10},
    },
    # 45 s quick check on the sports tier (owner ask, 2026-09-03 22:20): the
    # bbb_h264_smoke shape on the football clip — one short row per box.
    "football_h264_45s": {
        "label": "Football H.264 — 45 s quick check (1080p60, lab-internal source)",
        "clips": {"football_h264_45s": "football_h264_6min.mp4"},
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 5,
                  "startup_skip_s": 8, "window_s": 45, "gap_s": 5},
    },
}

# Parametric loop templates (2026-07-31): family × codec, tester-set duration
# via the window_s override on /decode/run (30–3600 s). H.264 points at the
# 60-min concatenated clips so even a ~1 h window never runs out; H.265/AV1 use
# the 20-min clips (their runs stay short). No player-side looping needed — the
# clip is always longer than the window and bench.py stops at window_s.
# ⚠ Clip lengths are 60:01 / 20:01 and the window starts after startup_skip_s
# (8 s): a 3600 s / 1100 s window ends AFTER the clip → alive_at_window_end
# False on an otherwise perfect row (2026-08-17). Caps below clamp the
# override so the window always ends inside the clip.
LOOP_FAMILIES = ("bbb", "meridian", "kranjska", "football")
LOOP_CODECS = ("h264", "h265", "av1")
for _fam in LOOP_FAMILIES:
    for _cod in LOOP_CODECS:
        _clip = (f"{_fam}_{_cod}_60min.mp4" if _cod == "h264"
                 else f"{_fam}_{_cod}_20min.mp4")
        TEMPLATES[f"loop_{_fam}_{_cod}"] = {
            "label": f"Loop — {_fam.upper()} {_cod.upper()} (tester-set duration)",
            "clips": {f"{_fam}_{_cod}_loop": _clip},
            "max_window_s": 3540 if _cod == "h264" else 1080,
            "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 5,
                      "startup_skip_s": 8, "window_s": 150, "gap_s": 10},
        }

# Iso-BITRATE loop family (2026-08-17, VP9 re-run): per content ONE bitrate for
# all four codecs, SOFTWARE encoders at production points, two-pass ABR, 20-min
# loops built by concat — see /srv/data/owl/campaign_2026-08-17_vp9b/
# iso_family_manifest.json for bitrates, VMAF at that bitrate and encoder points.
# VP9 ships as WebM: MP4/vp09 stalls the Google TV player (2026-08-09, 3/3).
ISO_FAMILIES = ("bbbiso", "kranjskaiso", "meridianiso", "footballiso")
ISO_CODECS = ("h264", "h265", "av1", "vp9")
for _fam in ISO_FAMILIES:
    for _cod in ISO_CODECS:
        _ext = "webm" if _cod == "vp9" else "mp4"
        TEMPLATES[f"loop_{_fam}_{_cod}"] = {
            "label": (f"Loop — {_fam[:-3].upper()} iso-bitrate {_cod.upper()} "
                      f"(software encode, tester-set duration)"),
            "clips": {f"{_fam}_{_cod}_loop": f"{_fam}_{_cod}_20min.{_ext}"},
            "max_window_s": 1080,
            "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 5,
                      "startup_skip_s": 8, "window_s": 150, "gap_s": 10},
        }

# Network-path arms (2026-08-18, Ben: isolate the connection method's power
# share — Wi-Fi vs Ethernet vs no network, low/high bitrate, burst vs paced
# ["live-like"] delivery). Same BBB content, H.264 (hardware on every STB),
# three bitrates; the origin's ?pace_kbps= caps delivery at 1.25× the clip
# rate so the player cannot buffer ahead. STB Ethernet↔Wi-Fi swaps need a
# cable/managed switch (no shell path on unrooted Android TV) — the Pi 400
# carries the full three-way comparison tonight; the STBs run bitrate ×
# pacing on their current interface (GTV/Bbox Ethernet, Fire TV Wi-Fi).
_NET_CLIPS = {1500: "bbbnet_h264_1500k_20min.mp4", 8000: "bbbiso_h264_20min.mp4",
              20000: "bbbnet_h264_20000k_20min.mp4"}
_NET_BENCH = {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 5,
              "startup_skip_s": 8, "window_s": 600, "gap_s": 10}
_PI_WIFI = "192.168.1.110"   # Pi 400 wlan0 (eth0 = the rig target .108)
for _kb, _clip in _NET_CLIPS.items():
    for _pace in ("burst", "paced"):
        _q = f"pace_kbps={int(_kb * 1.25)}" if _pace == "paced" else ""
        TEMPLATES[f"net_b{_kb}_{_pace}"] = {
            "label": f"Net — BBB H.264 {_kb/1000:g} Mb/s HTTP {_pace} (current interface)",
            "clips": {f"net_b{_kb}_{_pace}": _clip}, "url_query": _q,
            "ssh_source": "http", "max_window_s": 1080, "bench": dict(_NET_BENCH),
            "devices": ["gtv", "firestick", "bbox", "pi400"],
        }
        TEMPLATES[f"net_pi_wifi_b{_kb}_{_pace}"] = {
            "label": f"Net — Pi 400 over Wi-Fi, BBB H.264 {_kb/1000:g} Mb/s HTTP {_pace}",
            "clips": {f"net_pi_wifi_b{_kb}_{_pace}": _clip}, "url_query": _q,
            "ssh_source": "http", "ssh_host_override": _PI_WIFI,
            "pre_cmd": "sudo nmcli dev disconnect eth0", "pre_wait_s": 8,
            "post_cmd": "sudo nmcli dev connect eth0",
            "max_window_s": 1080, "bench": dict(_NET_BENCH), "devices": ["pi400"],
        }
    TEMPLATES[f"net_pi_local_b{_kb}"] = {
        "label": f"Net — Pi 400 local file (/dev/shm), BBB H.264 {_kb/1000:g} Mb/s — no network",
        "clips": {f"net_pi_local_b{_kb}": _clip}, "max_window_s": 1080,
        "bench": dict(_NET_BENCH), "devices": ["pi400"],
    }
TEMPLATES["net_pi_eth_b8000_wifioff"] = {
    "label": "Net — Pi 400 Ethernet HTTP 8 Mb/s burst with the Wi-Fi radio OFF (radio-idle control)",
    "clips": {"net_pi_eth_b8000_wifioff": _NET_CLIPS[8000]}, "ssh_source": "http",
    "pre_cmd": "sudo nmcli radio wifi off", "pre_wait_s": 5,
    "post_cmd": "sudo nmcli radio wifi on",
    "max_window_s": 1080, "bench": dict(_NET_BENCH), "devices": ["pi400"],
}
TEMPLATES["net_local_b8000"] = {
    "label": "Net — STB local file (adb push), BBB H.264 8 Mb/s — no network",
    "clips": {"net_local_b8000": _NET_CLIPS[8000]}, "delivery": "local",
    "max_window_s": 1080, "bench": dict(_NET_BENCH), "devices": ["gtv", "firestick"],
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


def looped_marked_name(clip: str, loops: int, marker: bool = True) -> str:
    """`loopmarked_x{N}_<clip>` — N repetitions of [marker head + content] in
    one file, subdir-safe like marked_name(). `marker=False` gives the
    marker-FREE variant (`loopplain_x{N}_…`) used where a codec/colour-matched
    marker cannot be built safely — see _ensure_looped_marked_clips_sync."""
    p = Path(clip)
    stem = f"{'loopmarked' if marker else 'loopplain'}_x{loops}_{p.name}"
    return str(p.parent / stem) if p.parent != Path(".") else stem


# --- Synchronised intra-content family (2026-09-03, JOURNAL S73) --------------
#
# One clip, several boxes, every power sample tagged with the CONTENT TIME the
# box was decoding — so per-scene decode power can be compared across silicon
# (Fire TV vs GTV = same MT8696, different OS; Xiaomi Gen 2 vs Gen 3 = same
# vendor, different Amlogic generation) instead of just comparing window means.
# Three mechanisms, all opt-in via the flags below:
#   · `looped_marker` — the clip is N × [5 s black · 5 s white · 5 s black +
#     content], so every loop re-states the black/white/black head. On the box
#     that holds the shared screen the head is a hard electrical timestamp on
#     the panel meter (see decode_sync.marker_edges_from_clock), which is what
#     validates the software clock against physically displayed frames.
#   · `sync_start` — the per-device bench.py PROCESSES meet at a file barrier
#     right before launch (decode_sync.rendezvous), so they start within a
#     couple of seconds instead of drifting apart by each box's own settle,
#     idle-guard and baseline duration.
#   · `content_clock` — bench.py polls the player's own position beside the
#     meter loop; the analysis maps power samples onto content time from that.
# Window: 6 loops of the 6-min clips ≈ 2251 s; cap at 2185 s so the window
# always ends INSIDE the file (Just Player hits EOF → STOPPED → a false
# alive_at_window_end False, the same trap the loop_* caps document above).
SYNC_LOOPS = 6


def _sync_template(key: str, label: str, src: str, loops: int,
                   max_window_s: int, marker: bool = True) -> None:
    TEMPLATES[key] = {
        "label": label,
        "clips": {key.replace("loop_", ""):
                  looped_marked_name(src, loops, marker)},
        "looped_marker": {"source": src, "loops": loops, "marker": marker},
        "content_clock": {"every_s": 2.0,
                          "head_s": MARKER_HEAD_S if marker else 0},
        "sync_start": True,
        "max_window_s": max_window_s,
        "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 5,
                  "startup_skip_s": 5, "window_s": max_window_s, "gap_s": 10},
    }


for _cod in ("h264", "h265", "av1"):
    _sync_template(f"loop_bbb_{_cod}_sync",
                   f"Sync — BBB {_cod.upper()} ×{SYNC_LOOPS} looped marker, "
                   f"content clock (video-only)",
                   f"bbb_{_cod}_6min.mp4", SYNC_LOOPS, 2185)

# Resolution and HDR arms (2026-09-03). Short sources on purpose: a 2-min 4K
# clip loops 15× inside the same ~33 min, so each content bin carries n=15
# instead of n=6 — the intra-content signal is a per-bin mean, and more
# repetitions of the same scene is exactly what tightens it.
#   4K: the existing matched-corpus 3840×2160@60 encode (`bbb_h264_4k`'s clip).
#   HDR: the only true HDR10 4K on the rig (HEVC Main 10, bt2020/PQ, 59.94 fps)
#     — a Pixop proto output upscaled from dirty SD, so the CONTENT provenance
#     is weaker than BBB; it is here to exercise the 10-bit/PQ decode path,
#     not to make a content claim. MARKER-FREE (marker=False): a matched
#     marker could not be built safely for it — see the builder's docstring.
_sync_template("loop_bbb4k_h264_sync",
               "Sync 4K — BBB H.264 3840×2160 ×15 looped marker, content clock",
               "bbb_h264_4k_2min.mp4", 15, 1955)
# 4K60 in HEVC (2026-09-03): the H.264 4K60 arm launched on the Google TV only
# — both Amlogic boxes' players went to ERROR (their AVC blocks are
# 4K30-class) and the Fire TV never left BUFFERING. Every box on the bench
# decodes 4K60 HEVC in hardware, so this is the resolution arm that covers
# all four at fixed codec and frame rate. Same source, same NVENC CBR rate
# class (20 Mbps), 2-min clip looped 15×; hevc_nvenc heads match the
# content's CTU-padded coded height by the _marker_encoder rule.
_sync_template("loop_bbb4k_h265_sync",
               "Sync 4K — BBB HEVC 3840×2160@60 ×15 looped marker, content clock",
               "bbb_h265_4k_2min.mp4", 15, 1955)
# Bitrate ladder (2026-09-03, owner's request at the end of the night; also
# CR-079's HD rung): the same BBB at seven CBR rates, 0.25 → 32 Mbps, so
# bitrate becomes the CONTROLLED variable — the corpus' own encodes are
# near-constant-rate (7.7-8.1 Mbps in every 20 s bin), which is why bits was
# unusable as a content-hardness descriptor on the sync runs. Seven rows per
# box in one job, four boxes in parallel with the start barrier, 90 s windows.
# Rungs are 2-min NVENC CBR encodes of the 4K master scaled to 1080p60, 2 s
# GOP, video-only (built by the session's build_ladder.sh — a decode-load
# probe, NOT matched-VMAF corpus encodes; the corpus operating point is the
# 8 Mbps rung, VMAF ≈ 92). Four boxes × 32 Mbps ≈ 130 Mbps on one Wi-Fi AP:
# the top rungs may rebuffer — the content clock's rate check records it.
LADDER_KBPS = (250, 500, 1500, 4000, 8000, 16000, 32000)
TEMPLATES["ladder_bbb_h264"] = {
    "label": "Bitrate ladder — BBB H.264 1080p60, 0.25→32 Mbps, 90 s each "
             "(video-only, sync start)",
    "clips": {f"bbb_h264_{k}k": f"bbbladder_h264_{k}k_2min.mp4"
              for k in LADDER_KBPS},
    "content_clock": {"every_s": 2.0, "head_s": 0},
    "sync_start": True,
    "max_window_s": 100,
    "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 5,
              "startup_skip_s": 8, "window_s": 90, "gap_s": 10},
}

# Loop-validity check (owner ask, WattLab call 2026-09-03): does a looped
# excerpt measure the same as the continuous original? Every rig loop family
# is a concat of one 2-min excerpt (bbb_h264_20min = ×10), so this is the
# assumption under all of them. One NVENC encode of 600 s of BBB (corpus
# recipe, keyframes forced every 30 s so the stream-copy cuts are exact):
# A the continuous 600 s · B its 120–240 s excerpt ×5 · C its 120–150 s
# excerpt ×20 (Tania's caveat: very short loops add artificial cuts — and the
# ReadySetGo sports source is only ~30 s, so C is the go/no-go for CR-081).
# Family key `bbbloopcheck` keeps decode_batch's family/codec cell parsing.
TEMPLATES["bbbloopcheck_h264"] = {
    "label": "Loop validity — BBB H.264 1080p60 8 Mbps: continuous 600 s vs "
             "120 s ×5 vs 30 s ×20 (video-only, sync start)",
    "clips": {"cont_600s": "bbbcont_h264_600s.mp4",
              "loop120_x5": "bbbloop120x5_h264_600s.mp4",
              "loop30_x20": "bbbloop30x20_h264_600s.mp4"},
    "content_clock": {"every_s": 2.0, "head_s": 0},
    "sync_start": True,
    "max_window_s": 610,
    "bench": {"cadence_s": 1.0, "baseline_samples": 20, "settle_s": 5,
              "startup_skip_s": 8, "window_s": 600, "gap_s": 10},
}

# 30 × 45.011 s = 1350 s of clip (no 15 s head — marker-free), so the window
# has to fit inside THAT, not inside 30 × 60 s.
_sync_template("loop_hdrmeridian_h265_sync",
               "Sync HDR — Meridian HEVC Main10 4K bt2020/PQ ×30 looped, "
               "content clock (no marker head: see builder docstring)",
               "hdrmeridian_h265_4k_45s.mp4", 30, 1290, marker=False)


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
# Content-clock + start-barrier feed (2026-09-03): "] clock pos=12.3 state=PLAYING"
# and "…: sync waiting for 3 peers" / "…: sync go at …". Both are consumed like
# the sample line (continue) so they never reach _PHASE_PATTERNS — a stray
# ": settle "-shaped line would advance the row counter.
_CLOCK_RE = re.compile(r"\] clock pos=(-?[0-9.]+|None) state=(\S+)")
_SYNC_RE = re.compile(r": sync (.+)$")


# --- Materialisation ---------------------------------------------------------

def _row_for(dev_cfg: dict, name: str, clip: str, mode: str,
             window_s: int | None = None, decoder: str | None = None,
             delivery: str = "http", pacing: str = "realtime",
             url_query: str = "", ssh_source: str = "shm",
             output_scale: str | None = None) -> dict:
    """url_query (2026-08-18, network-path arms): appended to every HTTP clip
    URL, e.g. "pace_kbps=10000" — the origin caps that response's rate.
    ssh_source: "shm" (default: clip staged in /dev/shm) or "http" (ffmpeg
    reads the origin URL, so the Pi's network path is inside the window).
    output_scale (2026-08-30, R15 Leg A): "WIDTHxHEIGHT" (e.g. "3840x2160")
    — adds an ffmpeg -vf scale filter to the headless decode-only path, so a
    1080p source is decoded AND upscaled, isolating the scale step's own
    cost from native-4K decode (RUN_QUEUE R15). Headless (ssh, non-screen)
    only for now — screen-mode mpv scaling is a separate, unimplemented leg;
    ignored for every non-ssh device kind (webos/atv/roku/adb play via their
    own app and never reach this branch)."""
    row: dict = {"name": name}
    if window_s:
        row["window_s"] = window_s
    q = f"?{url_query}" if url_query else ""
    if pacing == "saturated" and (mode == "screen" or dev_cfg["kind"] != "ssh"):
        # Real players pace themselves — a saturated row only exists on the
        # headless ffmpeg-over-ssh path. Refuse rather than silently pace.
        raise ValueError("saturated pacing is headless ssh only")
    if dev_cfg["kind"] == "webos":
        # C2 native decode: the harness WebosDevice launches this URL in the
        # built-in browser; its own SoC decodes+displays (no cmd/player).
        row["url"] = f"{STREAM_BASE_URL}/{clip}{q}"
        return row
    if dev_cfg["kind"] == "atv":
        # Apple TV: VLC for tvOS fetches the URL itself (Companion launch with
        # VLC's x-callback stream scheme — bench.py AtvDevice, CR-075).
        row["url"] = f"{STREAM_BASE_URL}/{clip}{q}"
        return row
    if dev_cfg["kind"] == "roku":
        # Roku: Media Assistant fetches the URL itself (ECP app-launch —
        # bench.py RokuDevice, 2026-08-29 onboarding; UNVALIDATED mechanism,
        # see roku_probe.py's docstring for the research trail).
        row["url"] = f"{STREAM_BASE_URL}/{clip}{q}"
        return row
    if dev_cfg["kind"] == "adb":
        if delivery == "local":
            # July delivery-decomposition arm — clip staged by adb push.
            row["url"] = f"file:///sdcard/Download/decode/{Path(clip).name}"
        else:
            row["url"] = f"{STREAM_BASE_URL}/{clip}{q}"
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
        src = (f"{STREAM_BASE_URL}/{clip}{q}" if ssh_source == "http"
               else f"/dev/shm/decode/{shm}")
        vf = f"-vf scale={output_scale.replace('x', ':')} " if output_scale else ""
        row["cmd"] = (f"ffmpeg -nostdin {pace}{dec}-i '{src}' "
                      f"-an {vf}-f null - ")
        row["stop_cmd"] = f"pkill -f 'ffmpeg.*{stem}'"
    return row


def _materialize(job_id: str, tpl_key: str, dev_name: str, mode: str,
                 calibrate: bool, upload_name: str | None = None,
                 cadence_s: float | None = None,
                 window_s: int | None = None,
                 sync_peers: list | None = None,
                 context_meter: bool = False) -> Path:
    tpl = resolve_template(tpl_key, upload_name)
    dev_cfg = rig.RIG["devices"][dev_name]
    # `not looped_marker`: the sync family's clip ALREADY carries a marker head
    # per loop. Marking it again would build a second 2 GB file and shift every
    # content position by 15 s — the content clock would silently disagree with
    # the file (2026-09-03).
    marked = mode == "screen" and calibrate and not tpl.get("looped_marker")
    base_window = int(window_s) if window_s is not None else tpl["bench"]["window_s"]
    if tpl.get("max_window_s"):
        base_window = min(base_window, int(tpl["max_window_s"]))
    runs = []
    for run_name, clip in tpl["clips"].items():
        decoder = (tpl.get("decoder")
                   or (tpl.get("decoder_by_device") or {}).get(dev_name))
        delivery = tpl.get("delivery", "http")
        pacing = tpl.get("pacing", "realtime")
        output_scale = (tpl.get("output_scale")
                        or (tpl.get("output_scale_by_device") or {}).get(dev_name))
        extra = {"url_query": tpl.get("url_query", ""),
                 "ssh_source": tpl.get("ssh_source", "shm"),
                 "output_scale": output_scale}
        if marked:
            # Marker-headed variant: window extends over the 15 s head; the
            # skip shrinks so the head lands inside the sampled window.
            row = _row_for(dev_cfg, run_name, marked_name(clip), mode,
                           window_s=base_window + MARKER_HEAD_S,
                           decoder=decoder, delivery=delivery,
                           pacing=pacing, **extra)
        else:
            row = _row_for(dev_cfg, run_name, clip, mode,
                           decoder=decoder, delivery=delivery,
                           pacing=pacing, **extra)
        # Per-run device/host hooks (2026-08-18): run by bench.py before the
        # baseline (pre_*) and after stop (post_cmd) — e.g. drop the Pi's
        # Ethernet before a Wi-Fi arm and restore it afterwards.
        for k in ("pre_shell", "pre_cmd", "post_cmd", "pre_wait_s"):
            if tpl.get(k) is not None:
                row[k] = tpl[k]
        runs.append(row)
    cfg = dict(tpl["bench"])
    proto = protocol_settings()
    cfg.update({k: proto[k] for k in
                ("cadence_s", "settle_s", "baseline_samples",
                 "protocol_version")})
    if cadence_s is not None:
        cfg["cadence_s"] = float(cadence_s)   # per-run slider override
    cfg["window_s"] = base_window             # tester-set duration override
    # Per-device settle/baseline floor (2026-08-27): the 5 s / 20-sample
    # protocol default was tuned against the Android boxes' fast post-stop
    # settle. The Apple TV's own draw keeps moving for 15-20+ s after `stop`
    # (an atv_probe.py run with 20-30 s settle / 40-45 s baseline stayed
    # clean all night; the campaign's default 5 s / 20 s produced base sd
    # up to 2 W and rows that never should have flagged 🔴). `max()` so a
    # tester's slider override can only raise it, never undercut the floor.
    if dev_cfg.get("min_settle_s") is not None:
        cfg["settle_s"] = max(cfg["settle_s"], int(dev_cfg["min_settle_s"]))
    if dev_cfg.get("min_baseline_samples") is not None:
        cfg["baseline_samples"] = max(cfg["baseline_samples"],
                                      int(dev_cfg["min_baseline_samples"]))
    if proto["idle_guard"]:
        # Reference mode when the device's settled idle is known (rig
        # config) — same asymmetric floor semantics as GoS1's CR-070 guard.
        # Self-stability alone settles on post-boot plateaus (negative-ΔW
        # incident 2026-07-30, run 57e8ba84).
        cfg["idle_guard"] = dict(proto["idle_guard"])
        if dev_cfg.get("idle_w") is not None:
            cfg["idle_guard"]["reference_w"] = dev_cfg["idle_w"]
        # Per-device max_wait_s floor (2026-08-29): the Apple TV's guard was
        # seen hitting the global 30 s ceiling still unsettled (5.28 W final,
        # its known screensaver/Settings-app contamination range, not its
        # ~2.1-2.3 W clean floor) — it needed longer to wait the excursion
        # out, not a shorter fuse. Same max()-floor semantics as settle_s
        # above; a settings-side increase can still raise it further.
        if dev_cfg.get("min_idle_max_wait_s") is not None:
            cfg["idle_guard"]["max_wait_s"] = max(
                cfg["idle_guard"]["max_wait_s"], int(dev_cfg["min_idle_max_wait_s"]))
        # Per-device tolerance_w floor (2026-08-29, same day as the max_wait_s
        # floor above — turned out to be the wrong half of the fix). Live
        # power-watches on the Apple TV show frequent BRIEF single-sample
        # spikes (6.1 W AirPlay-overlay, 8.2 W on a "Welcome to Apple TV"
        # screen) against a genuinely noisy ~2.9-3.8 W floor — a permanent,
        # recurring feature of this box's idle state, not a one-time
        # contamination event that eventually clears. Against the global
        # 0.5 W tolerance, settle_polls likely NEVER succeeds, so max_wait_s
        # just burns its full ceiling every single run before giving up
        # anyway — raising it to 90 s made runs slower without making them
        # more reliable. A wider tolerance lets normal jitter read as
        # "settled" quickly, while max_wait_s reverts to being the rare-case
        # circuit breaker it was meant to be.
        if dev_cfg.get("min_idle_tolerance_w") is not None:
            cfg["idle_guard"]["tolerance_w"] = max(
                cfg["idle_guard"]["tolerance_w"], float(dev_cfg["min_idle_tolerance_w"]))
    if marked:
        cfg["startup_skip_s"] = proto["screen_startup_skip_s"]
    cfg["name"] = f"ui-{tpl_key}-{job_id}-{dev_name}"
    cfg["meter_ip"] = dev_cfg["plug_ip"]
    # The C2's device plug IS the monitor plug (Lab-E) — no separate screen
    # meter, so skip the context meter (it would just duplicate meter_ip).
    # context_meter (2026-09-03): a headless multi-box run can still park the
    # panel on ONE device (`screen_device`) so its marker heads are verified
    # electrically. Exactly one process may own Lab-E — KLAP is single-session.
    if (mode == "screen" or context_meter) and dev_cfg["kind"] != "webos":
        cfg["monitor_meter_ip"] = rig.RIG["monitor"]["plug_ip"]
    if dev_cfg["kind"] == "adb":
        cfg["device"] = {"type": "adb", "serial": dev_cfg["target"],
                         "player": "com.brouken.player"}
    elif dev_cfg["kind"] == "webos":
        cfg["device"] = {"type": "webos", "host": dev_cfg["target"]}
    elif dev_cfg["kind"] == "atv":
        cfg["device"] = {"type": "atv", "host": dev_cfg["target"]}
    elif dev_cfg["kind"] == "roku":
        cfg["device"] = {"type": "roku", "host": dev_cfg["target"]}
    else:
        user, host = dev_cfg["target"].split("@", 1)
        # ssh_host_override: reach the same box on another interface (Pi 400
        # Wi-Fi arms: control + traffic over wlan0 while eth0 is dropped).
        host = tpl.get("ssh_host_override") or host
        cfg["device"] = {"type": "ssh", "host": host, "user": user}
    cfg["runs"] = runs
    # Content clock + cross-process start barrier (2026-09-03) — both opt-in
    # from the template, so every existing template materialises byte-identical
    # configs. loop_len_s is DERIVED (ffprobe / loops), never assumed: the
    # h264 6-min head+content is 375.137 s, not 375.
    if tpl.get("content_clock"):
        loops = int((tpl.get("looped_marker") or {}).get("loops", 1))
        clip0 = list(tpl["clips"].values())[0]
        cfg["content_clock"] = {**tpl["content_clock"], "loops": loops,
                                "loop_len_s": round(_loop_len_s(clip0, loops), 3)}
    if tpl.get("sync_start") and sync_peers and len(sync_peers) > 1:
        cfg["sync"] = {"dir": f"/tmp/owl-sync-{job_id}", "self": dev_name,
                       "peers": list(sync_peers), "lead_s": 3.0,
                       "max_wait_s": 120}
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


_LOOP_LEN_CACHE: dict = {}


def _loop_len_s(clip: str, loops: int) -> float:
    """One loop of a looped-marker clip = (head + content). Measured off the
    built file so it matches what the player actually advances through, and
    cached — four devices materialise the same clip within a second."""
    key = (clip, loops)
    if key not in _LOOP_LEN_CACHE:
        _LOOP_LEN_CACHE[key] = _clip_duration_s(clip) / max(1, loops)
    return _LOOP_LEN_CACHE[key]


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
    if mode == "screen" and calibrate and not tpl.get("looped_marker"):
        return [marked_name(c) for c in clips]
    return clips


_FFMPEG = "/usr/local/bin/ffmpeg-master"
# hevc: libx265, NOT hevc_nvenc (2026-08-29 — see below). h264/av1 stay NVENC.
# vp9: libvpx-vp9 (2026-08-29, added to unblock a screen-mode Apple TV/Roku
# comparison) — NVIDIA has no VP9 NVENC path at all (see docs/vp9_oneoff
# report §1), so there was never an nvenc option here. Checked before adding
# it, learning from the hevc case: libvpx-vp9's output matches this
# project's VP9 source content's coded dimensions exactly (clean 1080, no
# padding) — same class of bug is not expected, but this specific codec path
# is NOT yet confirmed live on real hardware the way hevc's fix was.
_NVENC = {"h264": "h264_nvenc", "hevc": "libx265", "av1": "av1_nvenc", "vp9": "libvpx-vp9"}


def _marker_encoder(codec: str, height: int, coded_height: int) -> str | None:
    """Encoder for a marker segment. The rule that generalises the 2026-08-29
    Roku fix (2026-09-03, caught on the HEVC sync run): a stream-copy concat
    must not change the CODED picture size mid-stream, so the segment's
    encoder is chosen to reproduce the CONTENT's padding, whatever it is.
      · HEVC content coded at a clean 1080 (libx265, the iso family) →
        libx265 segments (the S72 fix);
      · HEVC content CTU-padded to 1088 (hevc_nvenc, bbb_h265_6min) →
        hevc_nvenc segments, which pad identically. libx265 heads on that
        content froze the decoder on all four Android boxes at the first
        head→content splice: position kept advancing at 1× while every box
        sat at idle power for 36 min and the panel showed one frozen frame.
    h264_nvenc/av1_nvenc/libvpx-vp9 already match their sources."""
    enc = _NVENC.get(codec)
    if codec == "hevc" and coded_height != height:
        return "hevc_nvenc"
    return enc


def _ensure_marked_clips_sync(clips: list) -> None:
    """Build `marked_<clip>` (5 s black·white·black head + stream-copied
    content) for any clip missing its marked variant. Marker segments are
    codec/res/fps-matched encodes, cached in streams/marked_segments/.

    hevc uses libx265, not hevc_nvenc (2026-08-29, Roku HEVC onboarding):
    found live that hevc_nvenc pads its coded height to the next CTU-aligned
    multiple of 64 (1080 -> 1088) while this project's source HEVC content is
    coded at a clean 1080 — concatenating NVENC-padded marker segments onto
    unpadded content via stream-copy spliced a real coded-buffer-size
    discontinuity mid-stream. Roku's Realtek hardware HEVC decoder froze on
    the last marker frame for the rest of the window (confirmed live via the
    screen's own power trace: flat at the marker's black level for the full
    ~165 s task window, never transitioning to real content); VLC on Apple TV
    tolerated the same file fine (software decoders reallocate on the fly).
    libx265 encodes a clean, unpadded 1080 matching the source — confirmed
    live on the actual Roku hardware that this produces normal, varying
    playback power (65-94 W) instead of the flat ~37 W failure signature.
    Only regenerates cached segments — delete streams/marked_segments/hevc_*
    once to pick this up for existing content.

    2026-09-03 — that fix was content-specific, not a rule: bbb_h265_6min is
    hevc_nvenc content coded at 1088, and libx265 heads on it produced the
    same freeze on every Android box. The rule is "match the content's coded
    height" — see _marker_encoder(), which now chooses per clip."""
    for clip in clips:
        dst = STREAMS / marked_name(clip)
        if dst.exists():
            continue
        seg_paths = _marker_segments_for(clip)
        _concat_copy(seg_paths + [STREAMS / clip], dst,
                     f"/tmp/owl-marked-{Path(clip).name}.txt", timeout=600)


def _marker_segments_for(clip: str) -> list:
    """The three codec/res/fps-matched marker segments for `clip`, built and
    cached in streams/marked_segments/ on first use. Shared by the single-head
    (marked_) and looped (loopmarked_) builders."""
    ff = _FFMPEG if Path(_FFMPEG).exists() else "ffmpeg"
    seg_dir = STREAMS / "marked_segments"
    seg_dir.mkdir(exist_ok=True)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,width,height,r_frame_rate,pix_fmt",
         "-of", "csv=p=0", str(STREAMS / clip)],
        capture_output=True, text=True, check=True, timeout=30).stdout.strip()
    codec, w, h, pix, fps = probe.split(",")
    coded_h = int(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=coded_height", "-of", "csv=p=0",
         str(STREAMS / clip)],
        capture_output=True, text=True, check=True, timeout=30).stdout.strip() or h)
    enc = _marker_encoder(codec, int(h), coded_h)
    if enc is None:
        raise RuntimeError(f"no marker encoder for codec {codec!r}")
    # Segments for padded content are a distinct cache entry.
    pad_tag = f"_c{coded_h}" if coded_h != int(h) else ""
    # Colour metadata has to be carried onto the marker segments too
    # (2026-09-03, HDR onboarding). Same failure class as the hevc coded-height
    # and VP9 container bugs above: stream-copy concat splices the segments in
    # untouched, so an untagged SDR black next to bt2020/PQ content is a real
    # mid-stream discontinuity for the decoder AND flips the panel out of HDR.
    # Empty/unknown fields are simply not passed (SDR clips are unaffected —
    # they build byte-identical segments to before, so the existing cache and
    # every existing marked_ clip stay valid).
    # key=value, NOT positional csv: ffprobe emits these in its own struct
    # order (color_space, color_transfer, color_primaries), not the order they
    # are requested in — reading them positionally silently swaps primaries
    # and matrix (caught live 2026-09-03: libx265 rejected "bt2020nc" as a
    # color_primaries value). Same trap the pix_fmt/r_frame_rate note above
    # records for the geometry probe.
    cprobe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=color_primaries,color_transfer,color_space",
         "-of", "default=noprint_wrappers=1", str(STREAMS / clip)],
        capture_output=True, text=True, check=True, timeout=30).stdout
    cvals = dict(l.split("=", 1) for l in cprobe.strip().splitlines() if "=" in l)
    prim = cvals.get("color_primaries", "")
    trc = cvals.get("color_transfer", "")
    spc = cvals.get("color_space", "")
    color_args, color_tag = [], ""
    for flag, val in (("-color_primaries", prim), ("-color_trc", trc),
                      ("-colorspace", spc)):
        if val and val != "unknown":
            color_args += [flag, val]
    if color_args:
        color_tag = "_" + "-".join(v for v in (prim, trc, spc)
                                   if v and v != "unknown")
    # Segment container matches the SOURCE clip's own extension (2026-08-29,
    # VP9 onboarding) — was hardcoded to .mp4 for every codec. h264/hevc/av1
    # sources are already .mp4 so this never showed up; VP9 sources are
    # .webm (documented elsewhere: VP9-in-MP4 already stalls the GTV
    # player). Found live: a VP9 marker built as .mp4 then concatenated
    # onto .webm content produced the exact same flat-black stuck-decoder
    # failure as the earlier hevc_nvenc coded-height bug, despite matching
    # profile/pix_fmt/color exactly — confirmed the container mismatch was
    # the cause by rebuilding the marker segments as .webm and confirming
    # live on Roku that playback becomes normal (65-94 W varying) instead
    # of flat ~37 W.
    seg_ext = Path(clip).suffix
    seg_paths = []
    for seg, color in (("black", "black"), ("white", "white"),
                       ("black2", "black")):
        seg_p = (seg_dir /
                 f"{codec}_{w}x{h}_{fps.split('/')[0]}{pad_tag}{color_tag}_{seg}{seg_ext}")
        if not seg_p.exists():
            subprocess.run(
                [ff, "-loglevel", "error", "-f", "lavfi",
                 "-i", f"color=c={color}:s={w}x{h}:r={fps}", "-t", "5",
                 "-pix_fmt", pix, "-c:v", enc, *color_args, "-y", str(seg_p)],
                check=True, timeout=300)
        seg_paths.append(seg_p)
    return seg_paths


def _concat_copy(parts: list, dst: Path, list_path: str, timeout: int) -> None:
    """concat demuxer + stream copy — never re-encodes (re-encoding the content
    would change the very decode workload being measured)."""
    ff = _FFMPEG if Path(_FFMPEG).exists() else "ffmpeg"
    lp = Path(list_path)
    lp.write_text("".join(f"file '{p}'\n" for p in parts))
    try:
        subprocess.run(
            [ff, "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(lp), "-c", "copy", "-y", str(dst)],
            check=True, timeout=timeout)
    finally:
        lp.unlink(missing_ok=True)


def _ensure_looped_marked_clips_sync(specs: list) -> None:
    """Build `loopmarked_x{N}_<clip>` = N × [marker head + content] for each
    (source clip, loops) pair that is missing (2026-09-03, sync family).

    Why a pre-built file rather than player-side looping: it gives every box
    ONE monotonic content timeline for the whole run (Just Player's position
    would reset to 0 on each loop, and mpv/--loop=inf hides the wrap entirely),
    and it re-states the black·white·black head every loop so the panel meter
    can timestamp the loop boundary electrically on whichever box holds the
    screen. Same stream-copy discipline and the same cached, codec-matched
    segments as the single-head builder — including the HEVC coded-height and
    VP9 container fixes documented there, which apply verbatim here.

    NOTE the output is video-only (marker segments carry no audio track, so
    concat drops the source AAC/Opus): a different regime from the audio-
    bearing loop_* rows. Stated on the envelope, not just here.

    `marker=False` builds N × content with NO head. That is the honest
    fallback where a matched marker cannot be built: for the HDR 4K source
    (2026-09-03) libx265 would not write the PQ transfer into the VUI, and its
    segments code at a clean 2160 while the source is CTU-padded to 2176 — the
    exact coded-height discontinuity that froze Roku's decoder in S72. The
    content clock does not need the marker (it is the player's own position);
    what is lost is the on-screen electrical validation and the head-dip
    alignment check, which the analysis then reports as unavailable."""
    for spec in specs:
        src, loops = spec[0], spec[1]
        marker = spec[2] if len(spec) > 2 else True
        dst = STREAMS / looped_marked_name(src, loops, marker)
        if dst.exists():
            continue
        seg_paths = _marker_segments_for(src) if marker else []
        parts = (seg_paths + [STREAMS / src]) * int(loops)
        _concat_copy(parts, dst,
                     f"/tmp/owl-loopmarked-{Path(src).name}.txt", timeout=1800)
        # A short concat (a dropped repetition) would silently halve the loop
        # length and mis-map every content bin — check before anything runs.
        head = MARKER_HEAD_S if marker else 0
        want = int(loops) * (head + _clip_duration_s(src))
        got = _clip_duration_s(looped_marked_name(src, loops, marker))
        if abs(got - want) > 1.5:
            dst.unlink(missing_ok=True)
            raise RuntimeError(
                f"looped marker clip {dst.name} is {got:.1f}s, expected "
                f"{want:.1f}s — concat incomplete, removed")


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
    kind = rig.RIG["devices"][name].get("kind")
    is_webos = kind == "webos"
    t0 = time.monotonic()
    last_wake = 0.0
    while time.monotonic() - t0 < timeout_s:
        if dev["state"] == "ready":
            return
        if kind == "atv" and time.monotonic() - last_wake > 8:
            # tvOS sleeps within minutes when parked headless (2026-08-26);
            # the poller reports it asleep and a job that wants it wakes it.
            await asyncio.to_thread(rig.atv_wake, rig.RIG["devices"][name])
            last_wake = time.monotonic()
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
                         window_s: int | None = None,
                         sync_peers: list | None = None,
                         context_meter: bool = False) -> dict:
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

        if dev_cfg["kind"] == "ssh" and tpl.get("ssh_source", "shm") != "http":
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
                                upload_name, cadence_s, window_s,
                                sync_peers=sync_peers,
                                context_meter=context_meter)
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
            m = _CLOCK_RE.search(line)
            if m:
                sub["pos_s"] = None if m.group(1) == "None" else float(m.group(1))
                sub["play_state"] = m.group(2)
                continue
            m = _SYNC_RE.search(line)
            if m:
                sub["detail"] = f"sync {m.group(1)}"[:120]
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
        # Looped-marker + panel meter (2026-09-03): every loop's white onset is
        # predicted from the box's own content clock and looked for on Lab-E.
        # The residuals are the software clock's error vs the frames actually
        # on the glass — the calibration that makes the other boxes' clocks
        # trustworthy for content-time binning.
        loop_len = (cfg.get("content_clock") or {}).get("loop_len_s")
        if loop_len:
            for row in bench_out.get("rows", []):
                if row.get("raw_context_w") and row.get("raw_content_clock"):
                    ml = decode_sync.marker_edges_from_clock(
                        row["raw_context_w"], row.get("raw_context_t") or [],
                        row["raw_content_clock"], loop_len,
                        head_s=cfg["content_clock"].get("head_s", MARKER_HEAD_S))
                    if ml.get("loops"):
                        row["screen_marker_loops"] = ml
        # HDMI sink provenance (2026-09-03): a box with no HDMI input is a
        # different regime — the Fire TV plays 0.77 W lower and its ΔW drops
        # to a third with no sink, Gen 2 0.42 W lower (JOURNAL S73). The
        # screen-map slot (settings › rig_hdmi_inputs, applied into RIG) is
        # the best proxy the rig has for "had a sink"; null = headless/no sink.
        hdmi_in = dev_cfg.get("hdmi_input") or None
        for row in bench_out.get("rows", []):
            row.setdefault("hdmi_input", hdmi_in)
        section = {
            "label": dev_cfg["label"], "kind": dev_cfg["kind"],
            "hdmi_input": hdmi_in,
            "meter": {"model": "Tapo P110", "ip": cfg["meter_ip"],
                      "fw": "1.3.1", "cadence_s": cfg["cadence_s"]},
            "rows": bench_out.get("rows", []),
        }
        # Keep the bench's phase log tail (samples excluded) when any row
        # errored — the only place the failure sequence survives (2026-08-15).
        if any("error" in r for r in section["rows"]):
            section["log_tail"] = lines[-40:]
        if dev_cfg["kind"] == "atv":
            section["display_caveat"] = (
                "Apple TV rows are VLC for tvOS (Companion launch), liveness = "
                "pyatv playback state, no in-clip marker" +
                (" — headless: the screen was not claimed, the box renders "
                 "regardless" if mode == "headless" else ""))
        if dev_cfg["kind"] == "adb" and mode == "headless":
            section["display_caveat"] = (
                "Android renders regardless of the shared monitor; headless "
                "here means the screen was not claimed — rows are indicative "
                "vs the Pis' true null-sink decode (July 2026 convention)."
                + (" This box has NO HDMI cable attached at all (not just "
                   "unclaimed) — unverified whether it decodes/renders the "
                   "same way with zero display sink; confirm with a live "
                   "smoke test before trusting this row (2026-08-29)."
                   if not dev_cfg.get("hdmi_input") else ""))
        if dev_cfg["kind"] == "roku":
            section["display_caveat"] = (
                "Roku rows play through Dom's own 'Greening of Streaming' "
                "channel (app 775528, playlist-driven — see bench.py's "
                "RokuDevice), liveness = /query/media-player state + "
                "position advancing; screen-mode marker segmentation works "
                "normally. Still no logcat-equivalent decoder provenance — "
                "no way to confirm which decoder block actually ran, unlike "
                "the Android boxes' CCodec allocations." +
                (" Headless: the screen was not claimed, the box renders "
                 "regardless" if mode == "headless" else ""))
        sub.update({"stage": "done", "detail": ""})
        return section
    except Exception as e:
        sub.update({"stage": "error", "detail": str(e)[:200]})
        if sync_peers:
            # Release peers waiting at the start barrier (covers failures
            # BEFORE bench.py exists — e.g. _wait_ready timing out).
            try:
                Path(f"/tmp/owl-sync-{job_id}").mkdir(parents=True, exist_ok=True)
                Path(f"/tmp/owl-sync-{job_id}", f"{name}.abort").touch()
            except OSError:
                pass
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
                         window_s: int | None = None,
                         batch_id: str | None = None,
                         screen_device: str | None = None) -> None:
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
    sync_dir = Path(f"/tmp/owl-sync-{job_id}")
    try:
        if mode == "screen" and calibrate and not tpl.get("looped_marker"):
            job["stage"] = "preparing marker clips"
            await asyncio.to_thread(_ensure_marked_clips_sync,
                                    list(tpl["clips"].values()))
        if tpl.get("looped_marker"):
            lm = tpl["looped_marker"]
            job["stage"] = "preparing looped marker clip"
            await asyncio.to_thread(_ensure_looped_marked_clips_sync,
                                    [(lm["source"], lm["loops"],
                                      lm.get("marker", True))])
        if screen_device and mode != "screen":
            # Headless run, but one box keeps the panel so its marker heads
            # land on Lab-E. Claim BEFORE the gather: claim_screen refuses
            # (409) once any device is marked busy by _run_bench_for.
            await _wait_ready(screen_device, job["devices"][screen_device],
                              3 * rig.RIG["devices"][screen_device]["expected_boot_s"] + 45)
            job["devices"][screen_device]["detail"] = "claiming screen"
            await rig.claim_screen(screen_device)
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

        sync_peers = (list(devices)
                      if tpl.get("sync_start") and len(devices) > 1 else None)
        if sync_peers:
            sync_dir.mkdir(parents=True, exist_ok=True)
        outcomes = await asyncio.gather(
            *[_run_bench_for(job_id, tpl_key, tpl, name, mode, calibrate,
                             job["devices"][name], upload_name, cadence_s,
                             window_s, sync_peers=sync_peers,
                             context_meter=(name == screen_device))
              for name in devices],
            return_exceptions=True)

        sections, flat_runs, errors = {}, [], {}
        for name, out in zip(devices, outcomes):
            if isinstance(out, Exception):
                errors[name] = str(out)[:300]
                sections[name] = {"error": errors[name]}
            else:
                for r in out["rows"]:
                    flat_runs.append({**r, "device": name})
                # Single-store (envelope_version 1, CR-073): the raw sample
                # arrays live ONCE, in runs[]. devices[].rows keeps every
                # scalar (a per-device summary) — files were 2× their size.
                # Readers of the old shape (raw_* in both) still work.
                sections[name] = {**out, "rows": [
                    {k: v for k, v in r.items() if not k.startswith("raw_")}
                    for r in out["rows"]]}
        if not flat_runs:
            raise RuntimeError("all devices failed: " + json.dumps(errors))

        envelope = {
            "mode": f"ui_{mode}",
            "template": tpl_key,
            "template_label": tpl["label"],
            "calibrate": bool(mode == "screen" and calibrate),
            "batch_id": batch_id,          # CR-073: campaign = batch (None = solo)
            "devices": sections,
            "runs": flat_runs,
            "protocol": {"harness": "decode-bench bench.py",
                         "launched_from": "/decode", "parallel": mode == "headless",
                         # the window actually run (tester override / clip
                         # clamp), not the template default (was wrong pre-2026-08-17)
                         "window_s": (flat_runs[0].get("window_s")
                                      or tpl["bench"]["window_s"]),
                         "pacing": tpl.get("pacing", "realtime"),
                         **({"marker_head": {"pattern": _MARKER_PATTERN,
                                             "seconds": MARKER_HEAD_S,
                                             "note": "in-window; segment via "
                                                     "raw-sample edge detection"}}
                            if mode == "screen" and calibrate else {}),
                         **({"sync_start": bool(sync_peers),
                             "content_clock": tpl.get("content_clock"),
                             "looped_marker": tpl.get("looped_marker"),
                             "screen_device": screen_device,
                             "marker_head": {"pattern": _MARKER_PATTERN,
                                             "seconds": MARKER_HEAD_S,
                                             "note": "repeated once per loop"},
                             "regime_note":
                                 "looped marker-headed clip, VIDEO-ONLY (the "
                                 "marker segments carry no audio track, so the "
                                 "concat drops the source AAC/Opus) — not "
                                 "comparable with the audio-bearing loop_* "
                                 "rows; compare only within this template"}
                            if tpl.get("looped_marker") else {}),
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
        shutil.rmtree(sync_dir, ignore_errors=True)
        if upload_name:
            # Same retention rules as /enhance-run: evict-class uploads are
            # deleted at run end, proc/keep follow uploads.py's sweep. The
            # generated marked_ variant is always removed (regenerable).
            import uploads
            up_dir = STREAMS / UPLOADS_SUBDIR
            await asyncio.to_thread(uploads.cleanup_after_job, up_dir,
                                    upload_name)
            (up_dir / f"marked_{upload_name}").unlink(missing_ok=True)
