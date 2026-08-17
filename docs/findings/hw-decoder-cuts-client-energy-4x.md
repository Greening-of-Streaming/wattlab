---
slug: hw-decoder-cuts-client-energy-4x
version: 1
first_measured: 2026-07-29
last_refined: 2026-08-09
headline: "A hardware decoder cuts client decode power ~3.7× — and having the silicon isn't enough: stock software must be able to reach it"
claim_short: "Pi 400, same board, same 1080p60 file — H.264 hw +0.41 W vs sw +1.50 W playing (3.7×, n=6/3); +0.59 vs +2.72 W saturated (4.6×, n=3). Pi 5 (block dropped): +1.57 W."
confidence: green
scope: "Client device layer only (Raspberry Pi 400 / Pi 5, headless pure decode; Google TV as playback context). Network, CDN, display excluded on the Pis."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - decode/dec0de04
  - decode/dec0de05
  - decode/c22219b7
  - decode/37374ca2
  - decode/bffab9f5
  - decode/596c3ee6
related_findings: [codec-decode-energy-depends-on-silicon-and-regime, stb-decode-and-play-content-over-codec]
supersedes: null
tags: [decode, client-device, hw-vs-sw, raspberry-pi, owl-rem-lem, protocol-v3]
caveats:
  - "Realtime rows are BBB 1080p60 only; single board pair; one rung."
  - "Ratio reconciled 2026-08-09 (R6): n≥3 interleaved under protocol v3 gives 3.7× realtime / 4.6× saturated, replicating July v2 within noise; a 07-30 single-pair read of ~7× rested on one baseline-suspect hw row (+0.221 W, below the n=6 range 0.33–0.51). The hw arm's own rep spread (CV ~18% of ~0.4 W) is why single-pair ratios ranged 3.6–7×."
  - "Pi rows are headless pure decode (ffmpeg -f null, audio disabled) — no display path. A real player adds display/compositor energy on top."
  - "Both Pis' HEVC hardware blocks exist but are unreachable from stock Bookworm userspace (stateless V4L2; GStreamer <1.24, no V4L2-request ffmpeg/mpv, VLC built without the hw paths) — so 'hw vs sw' could only be measured for H.264, on the Pi 400."
  - "Cross-board Pi 400 vs Pi 5 software comparison is n=1 per board with uncontrolled DRAM/clock differences; the same-board hw-vs-sw pair is the clean single-variable read."
---

# The result, in one sentence

On the same Raspberry Pi 400, decoding the same 1080p60 H.264 file, the hardware decode path (`bcm2835-codec` v4l2m2m) drew **+0.41 W** (n=6) where software drew **+1.50 W** (n=3) while playing at 1× — **3.7× less** — and the Raspberry Pi 5, which shipped without that hardware block, pays **+1.57 W** in software for the same stream.

# Why this matters

Encode energy is paid once per title; **decode energy is paid per viewer, per hour**. OWL's bench has measured the server side since day one — this is the first OWL-grade measurement (per-run idle baseline, ΔW, traffic-light confidence, raw samples persisted) of the client layer that REM's field fleet observes, using the local-mW plug principle LEM documents. A device generation that drops a decoder block, or an OS release that can't reach one, multiplies the per-viewer number by ~4 — invisible in any spec sheet, visible at the wall.

The second half of the headline is the sharper finding: on **both** Pi generations the HEVC hardware sits idle behind software that cannot drive it. Stock-OS users software-decode everything. Stranded silicon is an energy bug.

# How it was measured

decode-bench harness (`/srv/data/owl/decode-bench/`): clips staged in tmpfs (no network, no SD I/O), `ffmpeg -f null` pure decode (every frame decoded, none displayed), Tapo P110 local mW API at 1.5 s, per-run baseline, OWL `confidence.py` per row. Two regimes per cell: realtime (`-re`, 150 s) and full-speed (`-stream_loop -1`, 120 s). All cited rows 🟢; key realtime rows replicated n=2–3. Full narrative + conjecture list: `docs/pi_decode_energy_2026-07.md`.

# What this finding does not measure

- Playback with a display attached (the mpv/KMS arm is future work) — these are decode-only watts.
- Any codec other than H.264 for the hw-vs-sw pair (see caveats), any content other than BBB for realtime rows, any resolution other than 1080p.
- Whether GStreamer 1.24 unstrands the HEVC blocks (expected, untested — the measured gap predicts roughly 2 W per stream on these boards).
