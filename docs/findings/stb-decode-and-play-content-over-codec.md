---
slug: stb-decode-and-play-content-over-codec
version: 1
first_measured: 2026-08-16
last_refined: 2026-08-17
headline: "On modern hardware-decode set-top boxes, an hour of 1080p playback costs ~0.25–0.65 W over the home screen — and the content moves that number more than the codec does"
claim_short: "Google TV Streamer + Fire TV Stick 4K, 1080p over LAN, 1100–3540 s windows, all 🟢: BBB (animation) +0.60/+0.64/+0.60 W (GTV h264/hevc/av1), +0.59/+0.44/+0.52 W (Fire TV); live-action Meridian/Kranjska +0.25–0.46 W. Codec spread within a content ≤0.1 W; content spread ~0.35 W."
confidence: green
scope: "Client device layer only — the set-top box at the wall (Google TV Streamer, Fire TV Stick 4K 2nd gen), decode + render to HDMI, home-screen idle as baseline. Display, network, CDN, origin excluded. Boxes' sleep/screensaver/CEC-standby timers pinned for the bench (disclosed)."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - decode/2c793c73
  - decode/64383dd8
  - decode/5b1def60
  - decode/d9710c6f
  - decode/d507b5ad
  - decode/06ee3d06
  - decode/545c99c1
  - decode/5e2c4daa
  - decode/b6b496f7
  - decode/d1be6ebe
related_findings: [hw-decoder-cuts-client-energy-4x, codec-decode-energy-depends-on-silicon-and-regime, appletv-a10x-av1-vp9-software-fallback]
supersedes: null
tags: [decode, client-device, set-top-box, google-tv, fire-tv, content-dependence, long-window, protocol-v3, draft]
caveats:
  - "DRAFT pending lab review. Two boxes, one resolution (1080p), one bitrate rung per codec (matched-VMAF ~92 NVENC encodes), one player (Just Player / media3), LAN HTTP delivery."
  - "Bench configuration: the boxes' inattentive-sleep timer (GTV default 20 min), screensaver (Fire TV default 5 min) and the GTV's HDMI-CEC active-source-lost standby were pinned OFF so a full window plays; a living-room box on defaults sleeps at 20 min. Every row records the pinned values (`keep_awake`). Earlier long-window rows taken WITHOUT this (2026-07-31, 2026-08-15) are invalid — box asleep, not decode — and are not cited."
  - "Fire TV Stick is Wi-Fi only (no Ethernet port): its ΔW includes the radio's share of streaming; the Google TV is on Ethernet. Link quality is not the confound (Wi-Fi 7 AP metres away)."
  - "One Fire TV row (Meridian H.264, +0.19→−0.19 W) is excluded: its baseline caught an Amazon home-screen autoplay burst (1.56 W vs the usual ~1.43). Repeat pending."
  - "n=1 per (box, content, codec) cell except GTV BBB H.264 (n=3 across 2026-08-16/17: +0.65, +0.60, +0.52 W). Cell CIs are tight (±0.05–0.15 W) because windows are 1100–3540 samples, but between-run baseline drift (~0.1 W) is not inside them."
  - "The operator box on the same bench (Bbox 4K) is NOT part of this claim: its 6.3–6.8 W idle drifts more than its H.264/HEVC decode delta, so its cells are inside its own noise even over an hour; only its AV1 rows (+1.2–1.4 W, no hardware AV1 decoder in logcat) are 🟢 — reported separately."
---

# The result, in one sentence

Playing 1080p for an hour on a Google TV Streamer or a Fire TV Stick 4K adds **about 0.6 W** over the home screen for a bright, high-motion animation and **0.25–0.45 W** for live-action drama or sport — and within either content, choosing H.264, HEVC or AV1 changes that by **≤0.1 W**.

# Why this matters

Decode energy is paid per viewer, per hour. These are the boxes on the shelves now, all-hardware decode for all three codecs, and the number is small enough that a 34 s window cannot see it: OWL's own first attempts read 0.0–0.3 W with 🔴 flags. On long windows the signal is unambiguous — **~0.6 Wh per hour of playback**, over a ~1.4 W home-screen floor — and it says two things a codec debate tends to miss. First, on decode silicon **the codec is nearly free**: HEVC and AV1 cost the viewer nothing measurable over H.264, so the encode-side energy and bitrate savings of newer codecs are not paid back at the client. Second, **the picture is not free**: the same box on the same codec draws 0.35 W more for Big Buck Bunny than for Meridian — bright, saturated, high-motion frames cost more to decode and render than dark, quiet ones, and any per-title or per-hour client-energy figure that ignores content is quoting one clip.

# How it was measured

decode-bench harness (`decode_bench/bench.py`, protocol v3): the box's own Tapo P110 (fw 1.3.1, local mW API, 1 s), pre-baseline stable-idle guard on the home screen, 20-sample baseline, launch via ADB VIEW intent into Just Player streaming from OWL's Range-correct origin over LAN, 8 s startup skip, then a 3540 s (H.264, 60-min clips) or 1100 s (HEVC/AV1, 20-min clips) sampled window, OWL `confidence.py` per row. Liveness is proven per row: media-session state PLAYING at mid-window, a mid-window screenshot showing content, and a flat trace to the last bin (six 10-min bins agree within ~0.03 W). All nine cited campaign jobs ran overnight 2026-08-16→17 (`results/decode/2026-08-17_*.json`); the reference hour is `2c793c73` (2026-08-16). Content: Big Buck Bunny (animation), Meridian (dark drama), Kranjska (MTB sport), all 1080p matched-VMAF encodes.

# What this finding does not measure

- The display: the boxes render to HDMI but the panel is on its own plug and excluded — see the C2 native rows for why panel content-dependence (30–75 W) swamps decode.
- Any resolution above 1080p, HDR, or bitrate ladders; adaptive streaming behaviour; a real service's app (Just Player is a neutral local player).
- Software decode on these boxes (not reachable), or the operator Bbox (see caveats).
- Whether the ~0.35 W content spread is decode, render/compositor, or panel-facing output processing — the box is one meter.
