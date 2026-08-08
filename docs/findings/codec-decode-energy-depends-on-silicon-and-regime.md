---
slug: codec-decode-energy-depends-on-silicon-and-regime
version: 1
first_measured: 2026-07-29
last_refined: 2026-08-09
headline: "Which codec is cheapest to decode has no silicon-independent answer: a wash on hardware, up to ~60% spread in software — and the measurement regime can flip the ranking"
claim_short: "Hw (Google TV): codec spread ≤0.08 W. Sw at 1× (both Pis): h264 +1.57 < av1 +1.83 < hevc +2.56 W. Sw saturated: ranking inverts (av1 +4.15 < h264 +5.13 W)."
confidence: yellow
scope: "Client device layer only (Google TV Streamer hw; Raspberry Pi 5 / Pi 400 sw, headless pure decode). Network, CDN excluded; Pi rows exclude display and audio."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - decode/dec0de06
  - decode/dec0de05
  - decode/dec0de04
related_findings: [hw-decoder-cuts-client-energy-4x]
supersedes: null
tags: [decode, codecs, client-device, hevc, av1, methodology]
caveats:
  - "Yellow because the software realtime panels here are BBB 1080p60 only (n=1–3 per cell) and the Google TV rows are full playback (display + audio) vs the Pis' headless pure decode — the cross-device comparison is indicative, not strict."
  - "Corroborated at scale 2026-08-01 (54-cell suite, 3 content families): the software ordering h264 < av1 < hevc held on the Pi 5 across every family and both run modes (HEVC ~1.9× H.264), and fixed-function marginals stayed ≤ ~0.5 W — see the campaign store /srv/data/owl/campaign_2026-07-31/."
  - "Matched-VMAF encodes, so bitrate co-varies with codec (BBB: 8.0/6.6/4.0 Mb/s for h264/hevc/av1) — the honest iso-quality framing, not equal-bitrate."
  - "Why AV1 draws less than its CPU share suggests (85.5% busy yet lowest saturated power) is conjecture — instruction-mix/power-density hypothesis, needs PMU counters."
  - "Which regime a real player occupies depends on its buffering strategy (July's Google TV burst-vs-sustained finding shows +0.42 W between modes); no Pi player's buffering has been characterised."
---

# The result, in one sentence

On fixed-function hardware (Google TV) the three codecs decode within **0.08 W** of each other; in software at playback pace the spread is up to **~60%** with the same ordering on two different Pi generations (**h264 < av1 < hevc**); and when decode runs flat-out instead of paced, the ranking **inverts** (AV1 lowest, H.264 highest).

# Why this matters

Codec-energy claims are routinely made without stating the decode path or the measurement regime — this data shows either omission can flip the conclusion. Concretely, for the industry's live HEVC-rollback question: rolling back to H.264 is **energy-neutral on hardware-decode devices** (≤0.08 W) and **energy-reducing on software-decoding clients** (−1.0 W of +2.56 on these boards). And a codec's "energy cost" is not one number: paced at 1×, H.264 software decode is cheapest; racing to idle, the same board makes AV1's instantaneous draw the lowest. If it can't be stated with silicon path and regime attached, it shouldn't be asserted.

# How it was measured

Same 1080p matched-VMAF (~92–93) NVENC encodes across all three devices. Google TV: Just Player full playback, hw MediaTek decoders, July 2026 round (n=9, all 🟢). Pis: decode-bench headless pure decode from tmpfs, realtime (`-re`) and saturated (`-stream_loop -1`) regimes, Tapo P110 mW path, OWL confidence per row; key realtime rows n=2–3. Full narrative + conjecture list: `docs/pi_decode_energy_2026-07.md`.

# What this finding does not measure

- Realtime software panels beyond BBB; resolutions beyond 1080p; HDR.
- Playback with display attached on the Pis, or any Pi player's buffering behaviour — so it does not name a single "greenest codec for playback" per device.
- Equal-bitrate codec comparison (bitrate co-varies under matched quality).
