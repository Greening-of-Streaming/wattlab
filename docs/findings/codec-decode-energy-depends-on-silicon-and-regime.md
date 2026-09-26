---
slug: codec-decode-energy-depends-on-silicon-and-regime
version: 2
first_measured: 2026-07-29
last_refined: 2026-09-22
headline: "Which codec is cheapest to decode has no silicon-independent answer: near-flat on one hardware decoder but resolvable on another, up to ~60% spread in software — and the measurement regime can flip the ranking"
claim_short: "Hw (Google TV): codec spread ≤0.08 W, unresolvable. Hw (Allwinner H618, n=3): H.264 +1.073 > HEVC +0.966 ≈ VP9 +0.971 W — H.264 dearer by 0.107 W, separated (t=4.96). Sw at 1× (both Pis): h264 +1.57 < av1 +1.83 < hevc +2.56 W. Sw saturated: ranking inverts."
confidence: yellow
scope: "Client device layer only (Google TV Streamer hw; TV Box W5 / Allwinner H618 hw, screen-attached; Raspberry Pi 5 / Pi 400 sw, headless pure decode). Network, CDN excluded; Pi rows exclude display and audio. The three decode paths sit in different sink regimes and are not pooled."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - decode/64e14084
  - decode/0e55456b
  - decode/35b5ff43
  - decode/374a67b2
  - decode/a6c84770
  - decode/a574cbdf
  - decode/3fb59067
  - decode/23e5aba9
  - decode/6da9885f
  - decode/dec0de06
  - decode/dec0de05
  - decode/dec0de04
related_findings: [hw-decoder-cuts-client-energy-4x, stb-decode-and-play-content-over-codec, appletv-a10x-av1-vp9-software-fallback, looped-excerpt-measures-as-continuous]
supersedes: null
tags: [decode, codecs, client-device, hevc, av1, methodology]
caveats:
  - "The \"hardware is a wash\" half is now vendor-specific (2026-09-22). On the Allwinner H618 (TV Box W5, n=3, BBB iso-bitrate 1080p60, screen-attached) the three hardware codecs do NOT collapse: H.264 +1.073 W vs HEVC +0.966 and VP9 +0.971, i.e. H.264 dearer by ~0.107 W (≈11%), Welch t=4.96, 95% CI +0.038..+0.176, rep ranges non-overlapping. HEVC and VP9 tie. Note the OLDER codec is the expensive one, so this is not \"newer codecs cost more\" in hardware. Fixed-function decode makes codec choice cheap, not free, and how cheap is a property of the part."
  - "The same W5 campaign produced three AV1 rows (+0.442 W) that are NOT a decode measurement and must never be quoted as one: the H618 has no AV1 block, Just Player falls back to in-app libgav1, and the box presents 1.7 fps against a 1080p60 source (its H.264 marker clip returns 60.0 fps in the same session). Because it is not doing the work its ΔW lands 58% BELOW the cheapest codec it can actually play. Every gate the rig applies passed those rows. A device that cannot sustain a codec will systematically flatter it — see docs/w5_onboarding_2026-09-21.md and CR-078."
  - "Yellow because the software realtime panels here are BBB 1080p60 only (n=1–3 per cell) and the Google TV rows are full playback (display + audio) vs the Pis' headless pure decode — the cross-device comparison is indicative, not strict."
  - "Corroborated at scale 2026-08-01 (54-cell suite, 3 content families): the software ordering h264 < av1 < hevc held on the Pi 5 across every family and both run modes (HEVC ~1.9× H.264), and fixed-function marginals stayed ≤ ~0.5 W — see the campaign store /srv/data/owl/campaign_2026-07-31/."
  - "Matched-VMAF encodes, so bitrate co-varies with codec (BBB: 8.0/6.6/4.0 Mb/s for h264/hevc/av1) — the honest iso-quality framing, not equal-bitrate."
  - "Why AV1 draws less than its CPU share suggests (85.5% busy yet lowest saturated power) is conjecture — instruction-mix/power-density hypothesis, needs PMU counters."
  - "Which regime a real player occupies depends on its buffering strategy (July's Google TV burst-vs-sustained finding shows +0.42 W between modes); no Pi player's buffering has been characterised."
---

# The result, in one sentence

On fixed-function hardware (Google TV) the three codecs decode within **0.08 W** of each other; in software at playback pace the spread is up to **~60%** with the same ordering on two different Pi generations (**h264 < av1 < hevc**); and when decode runs flat-out instead of paced, the ranking **inverts** (AV1 lowest, H.264 highest).

On a **second** fixed-function decoder (Allwinner H618) the codecs do **not** collapse: H.264 costs **+0.107 W (≈11%) more** than HEVC and VP9, which tie — separated at n=3 (t=4.96, 95% CI +0.038…+0.176). So "hardware makes codec choice free" is true of the part tested, not of hardware decode as such.

# Why this matters

Codec-energy claims are routinely made without stating the decode path or the measurement regime — this data shows either omission can flip the conclusion. Concretely, for the industry's live HEVC-rollback question: rolling back to H.264 is **energy-neutral on hardware-decode devices** (≤0.08 W) and **energy-reducing on software-decoding clients** (−1.0 W of +2.56 on these boards). And a codec's "energy cost" is not one number: paced at 1×, H.264 software decode is cheapest; racing to idle, the same board makes AV1's instantaneous draw the lowest. If it can't be stated with silicon path and regime attached, it shouldn't be asserted.

# How it was measured

Same 1080p matched-VMAF (~92–93) NVENC encodes across all three devices. Google TV: Just Player full playback, hw MediaTek decoders, July 2026 round (n=9, all 🟢). Pis: decode-bench headless pure decode from tmpfs, realtime (`-re`) and saturated (`-stream_loop -1`) regimes, Tapo P110 mW path, OWL confidence per row; key realtime rows n=2–3. Full narrative + conjecture list: `docs/pi_decode_energy_2026-07.md`.

**Allwinner H618 (added 2026-09-22):** TV Box W5, BBB iso-bitrate 1080p60 @8 Mb/s (same bit volume for every codec, so not a bitrate artefact), Just Player via VIEW intent, screen mode on the shared LG C2 (sink `panel:HDMI_1`), 1095 s windows, 1 s cadence, n=3 per codec, batch `3e54b322a9b4`, 12 rows, none discarded; decoder provenance read from logcat on every row (`OMX.allwinner.video.decoder.{avc,hevc,vp9}`). Presented frame rate verified from SurfaceFlinger timestamps at 60.0 fps on all nine hardware rows. Onboarding record, traps and the AV1 exclusion: `docs/w5_onboarding_2026-09-21.md`.

# What this finding does not measure

- Realtime software panels beyond BBB; resolutions beyond 1080p; HDR.
- **AV1 on the Allwinner H618** — the box cannot sustain it (1.7 fps), so no AV1 decode-energy figure exists for that silicon at all. The stored rows measure a failure, not a decode.
- Playback with display attached on the Pis, or any Pi player's buffering behaviour — so it does not name a single "greenest codec for playback" per device.
- Equal-bitrate codec comparison (bitrate co-varies under matched quality).
