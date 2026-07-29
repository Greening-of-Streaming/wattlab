# Client decode energy: what a missing hardware decoder costs

**Draft report — 2026-07-29** (overnight bench run 2026-07-28/29; raw per-row JSON with 1.5 s
samples under `/srv/data/owl/decode-bench/results/`, harness `bench.py` alongside).

## Why this measurement exists (OWL / REM / LEM)

GoS's dual-track methodology pairs **REM (field — *where* effects exist, fleet-scale, ~30 s cloud
cadence)** with **OWL (bench — *why* and by how much, marginal-over-baseline, per-run confidence)**.
Decode happens on the *client*, per viewer — REM's territory — but until now only OWL's server had
bench-grade instrumentation. This rig applies OWL's method (per-run idle baseline, ΔW, Traffic-Light
confidence, raw samples persisted) to consumer playback devices, using **LEM's principle** that a
local-API smart plug reads milliwatts at 1–2 s — the resolution that makes sub-watt codec deltas
measurable at all. It is a first close of the loop `REM/DUAL_TRACK_METHODOLOGY.md` says neither
track can close alone. Encode is paid once per title; decode is paid per viewer-hour — at fleet
scale the numbers below are the ones that multiply.

## Rig

Three devices, one protocol (settle → baseline → start → skip → sampled window → OWL
`confidence.py`), identical 1080p matched-VMAF (~92–93) NVENC encodes (BBB 60 fps unless noted):

| Device | Silicon | Decode paths | Meter (P110, mW local API) |
|---|---|---|---|
| Raspberry Pi 5 (16 GB, Bookworm) | 4× A76 @ 2.4 GHz | **software only** (see finding 4) | Lab-A `.146`, fw 1.3.1 |
| Raspberry Pi 400 (4 GB, Bookworm) | 4× A72 @ 1.8 GHz | software + **hw H.264** (`bcm2835-codec`, stateful v4l2m2m) | Lab-B `.31`, fw 1.3.1 |
| Google TV Streamer (July round) | MediaTek fixed-function | hw H.264/HEVC/AV1 | `.94`, fw 1.4.6 |

Pi runs are headless pure decode (`ffmpeg … -an -f null -`): clips in `/dev/shm` (no network, no
SD I/O), video-only, no display path. Both Pi desktops at 1920×1080@60 scanout throughout.
Two regimes per cell: **realtime** (`-re`, paced at 1×, 150 s window — what a player pays while
playing) and **full-speed** (`-stream_loop -1`, saturated, 120 s — race-to-idle power).
All 21 rows 🟢; key realtime rows n=2.

## Results — marginal power ΔW over idle (BBB 1080p60)

| | Pi 5 sw | Pi 400 sw | Pi 400 **hw** | Google TV hw* |
|---|---|---|---|---|
| **Realtime** H.264 | +1.57 / +1.60 | +1.25 | **+0.35** | +0.88* |
| **Realtime** HEVC | +2.56 / +2.57 | +2.54 | — | +0.87* |
| **Realtime** AV1 | +1.81 / +1.85 | +1.75 | — | +0.78* |
| **Full-speed** H.264 | +5.13 | +2.62 | +0.64 | — |
| **Full-speed** HEVC | +4.76 | +2.83 | — | — |
| **Full-speed** AV1 | +4.15 | +2.15 | — | — |

\* Google TV rows are full playback (display output + audio) from the July round — indicative
context, not a strict like-for-like against the headless `-an` Pi rows.
Idle baselines: Pi 5 ~3.4 W · Pi 400 ~3.0 W · GTV ~1.0 W. Pi 5 full-speed panel also ran
Meridian and Kranjska: content moves each codec ≤0.11 W — the decoder, not the content, drives cost.

Replication note: Pi 5 realtime HEVC reached n=3 (+2.56/+2.57/+2.63 ✓). A third H.264 realtime row
measured ΔW +0.97 with **identical task power** (5.09 vs 4.94/4.96 W) against an **elevated
baseline** (4.12 vs ~3.4 W) — the hot-baseline-undercounts-ΔW failure mode OWL closed on the bench
with CR-070's pre-job idle guard. `bench.py` has no baseline-floor guard yet; until it does,
cross-check `w_task` when a ΔW looks anomalous. Task-power agreement across all three runs is
itself a strong replication.

## Findings (measured)

1. **A hardware decoder is worth 3.6× while playing, 4.1× saturated — on the same board, same
   file.** Pi 400 H.264 realtime: hw +0.35 W vs sw +1.25 W; full-speed +0.64 vs +2.62 W.
   That is the direct, single-variable measurement of what dedicated silicon buys.
2. **The Pi 5 pays for its dropped H.264 block.** It software-decodes H.264 at +1.57 W where its
   predecessor's hardware does the job for +0.35 W. Newer device, older codec, ~4.5× the energy —
   the client-side mirror of OWL's `input-master-sensitivity` finding (servers pay when codecs
   outrun their hardware; clients pay when hardware drops a codec).
3. **In software, HEVC is the dearest codec at 1× on both boards** (Pi 5 +2.56, Pi 400 +2.54 W),
   with H.264 cheapest and AV1 between (ordering h264 < av1 < hevc, consistent across two SoC
   generations). Relevant to any HEVC-rollback debate: on fixed-function boxes the codec choice
   moves ≤0.08 W (July), but on software-decoding clients codec choice changes decode power by
   up to ~60%.
4. **Both Pis' HEVC hardware exists but is unreachable from stock Bookworm userspace** (stateless
   V4L2 blocks; ffmpeg 5.1/mpv have no V4L2-request path, VLC 3.0.23 built `--disable-mmal
   --disable-libva`, GStreamer 1.22 lacks `v4l2slh265dec` — it lands in 1.24). The Pi 5 has no AV1
   or H.264 hardware at all; the Pi 400's usable hardware is H.264 only. **Stock-OS users
   software-decode everything** — capability stranded by packaging, with a measurable energy price.
5. **Measurement regime changes the codec ranking.** Saturated, AV1 draws the *least* power of the
   three on the Pi 5 (+4.15 vs H.264 +5.13 W) despite using the most CPU time; paced at 1×, H.264
   is cheapest. A codec energy claim without its regime (and buffering model) stated is not
   interpretable — this is a methodology finding for OWL as much as a result.

## Conjecture — explicitly needing validation or more data

- **Why AV1 draws less than its CPU share suggests** (instruction-mix / power-density hypothesis:
  NEON-dense H.264 kernels vs dav1d's mix). Plausible, unproven — needs perf/PMU counters or
  per-rail measurement. Currently an interpretation, not a result.
- **Which regime real players occupy.** Race-to-idle favours H.264 (Pi 5: 0.022 Wh/video-min vs
  AV1 0.041 sustained-decode); the July Google TV delivery-mode finding (+0.42 W burst-vs-sustained)
  proves buffering strategy matters, but no Pi player's buffering has been characterised. Claiming
  "codec X is cheapest for playback" on these boards requires the display-path player arm (mpv/KMS),
  not `-f null`.
- **Pi 400 software decode measuring cheaper than Pi 5's** (+1.25 vs +1.57 W realtime H.264).
  n=1 per board, boards differ in DRAM, clocks and process — do not yet read as "older is more
  efficient" without repeats and a clocks-matched control.
- **Generality**: realtime panels and the whole Pi 400 set are BBB-only (Pi 5 full-speed panel is
  3 contents); one rung (1080p ~matched-VMAF, so bitrate co-varies with codec); no 4K, no HDR, no
  display attached. GTV cross-device ratios are indicative only (see table note).
- **GStreamer 1.24 unstrands the HEVC blocks** — expected, untested. The measured hw-vs-sw gap
  (finding 1) predicts roughly a 2 W saving per stream on these boards if it works.
- Lab-A/B plugs assumed ≥1 Hz-class from fw 1.3.1 (S47); `bin/probe-p110-fw` has not been run on
  them — a 10-minute hygiene item that would firm every row's effective sample count.

## Provenance & discipline

Two early rows were discarded as contaminated (a concurrent full-speed job overlapped the first
realtime H.264/HEVC windows; the stray-process risk is now closed with codec-targeted stop
commands). Discarded values are retained in the raw logs, marked, and excluded here. The Range-
request defect in the ad-hoc `:8123` file server (returns 200/full-body to ranged GETs) was
demonstrated to break ffmpeg-over-HTTP and remains the prime suspect for July's media3 2.1×
over-fetch — clips were therefore staged locally for every Pi row.

## Next (one line each)

Player-with-display arm on both Pis (mpv/KMS) · GStreamer 1.24 hw-HEVC trial · probe-p110-fw on
Lab plugs · repeat panels for n≥2 on remaining cells · degraded-ladder rungs (where sw decode
falls below realtime) · fold into `/findings` once lab-reviewed.
