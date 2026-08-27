---
slug: appletv-a10x-av1-vp9-software-fallback
version: 1
first_measured: 2026-08-26
last_refined: 2026-08-27
headline: "Apple TV 4K (2017, A10X): H.264/HEVC play at the same power; AV1 and VP9 both cost +29% more — the third silicon-coverage instance"
claim_short: "Device-total W, VLC for tvOS, n=3 per codec across three content families: H.264 4.10 W, HEVC 4.07 W, AV1 5.25 W, VP9 5.28 W — hardware pair (VideoToolbox) flat, software-fallback pair +1.19 W (+29%), gap stable per content (+1.0 to +1.3 W)."
confidence: green
scope: "Client device layer only (Apple TV 4K, 2017, A10X Fusion, tvOS 26.6). Network, CDN, display excluded. Player is VLC for tvOS via Companion launch, not the native tvOS player."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - decode/7a453a7c
  - decode/c03615b2
  - decode/53b55302
  - decode/85aa43b7
  - decode/959fc2be
  - decode/87a42c89
  - decode/e4333696
  - decode/dbb70a0d
related_findings: [codec-decode-energy-depends-on-silicon-and-regime, stb-decode-and-play-content-over-codec, hw-decoder-cuts-client-energy-4x]
supersedes: null
tags: [decode, client-device, apple-tv, av1, vp9, codec, silicon-coverage, owl-rem-lem, protocol-v3]
caveats:
  - "Player is VLC for tvOS (org.videolan.vlc-ios), launched via pyatv Companion's x-callback stream scheme — AirPlay play_url is dead on both tvOS 18 and 26 (upstream pyatv #2403/#2512, receiver-side, no client fix). Not the native tvOS player; VLC's per-codec decoder choice (VideoToolbox vs software) is inferred from the energy signature, not logged."
  - "n=3 per codec per content family except Kranjska AV1 (n=2 — one rep excluded, alive_at_window_end=False, an isolated one-off playback hiccup not repeated on any other row that night)."
  - "Measured post a mid-campaign tvOS update to 26.6. Roughly the first half of the campaign's baselines sat on an elevated, stable plateau (~3.2-4.0 W vs the device's previously-observed ~2.1-2.3 W idle floor) — device-total W while PLAYING (the cited metric) is unaffected and matches pre-update numbers; absolute idle-W and ΔW-over-baseline figures for this device on tvOS 26.6 are not used here and should be treated as unconfirmed pending a re-check on a quiet night."
  - "Display attached and stable throughout every cited row. A companion result on the same device (job fe9d69b0, not cited here) shows headless rows read a media-session clock, not decode energy, and must never be compared to these figures."
  - "One content family (BBB) carries the hardware-pair (H.264/HEVC) confirmation; the +29% software-fallback gap is confirmed across all three content families (BBB, Kranjska, Meridian)."
  - "One box, one generation (2017 A10X). No Apple silicon before the A17 Pro / M3 has a hardware AV1 decoder, so the AV1 finding is expected to generalise across earlier Apple TV/tvOS generations; VP9 hardware support on later Apple silicon is untested."
---

# The result, in one sentence

On the 2017 Apple TV 4K (A10X Fusion, tvOS 26.6), playing the same 1080p60 content via VLC for tvOS, H.264 and HEVC draw the same device-total power (**4.10 W** and **4.07 W**, VideoToolbox hardware) while AV1 and VP9 both draw **+1.19 W more (+29%)** — confirmed across three content families, n=3 per codec.

# Why this matters

This is the **third independent silicon vendor** to show the same shape in OWL's decode panel: a codec with a hardware block is free; a codec without one is paid for in software, at a cost set by the silicon, not the codec. MediaTek (Google TV Streamer, Fire TV Stick — same MT8696 part) shows AV1 free where it has the block. Marvell (the Bbox operator CPE) shows AV1 costing +1.2–1.4 W where it doesn't. Apple silicon of this generation now shows the same penalty for **two** codecs at once — AV1 and VP9 — from the platform whose codec support was directly questioned in the LinkedIn thread this campaign's VP9 report grew out of. The panel's "codec cost is a property of silicon coverage" claim (`codec-decode-energy-depends-on-silicon-and-regime`) now spans three vendors, not two.

# How it was measured

OWL `/decode` rig (`decode_bench/bench.py`'s `AtvDevice` driver, sequenced by `decode_bench/atv_night.py`): Apple TV controlled over pyatv (Companion + AirPlay), playback via `launch_app=vlc-x-callback://…/stream?url=<origin URL>` (AirPlay's native `play_url` does not work on this tvOS — see caveats). Own Tapo P110 (Lab-F3, local mW API, 1 s cadence). Protocol: park (VLC stopped, relaunched to its library screen) → settle (25 s floor, above the generic protocol default — this device's post-`stop` settle is slower than the Android boxes the default was tuned against) → 40-sample baseline → launch → 120 s sampled window → stop → park. `confidence.py` on the raw 1 s samples; every cited row 🟢. Content: iso-bitrate BBB/Kranjska/Meridian families (S65/C17 recipe), 1080p60, matched-VMAF NVENC encodes, served by the Range-correct OWL origin. n=3 per codec per content family (n=2 for one cell — see caveats). Full campaign table and narrative: `~/dev/smpte-4951/digests/2026-08-appletv-vlc.md` (SMPTE #4951, entry C19).

# What this finding does not measure

- The native tvOS player — VLC only (see caveats). AirPlay `play_url` is dead on this tvOS; a driver holding the AirPlay session open against upstream pyatv PR #2899 could reach the native player and is not built.
- Headless playback — a separate, already-published result on the same device shows headless rows are not decode energy at all.
- 4K, HDR, or any resolution/bit-depth other than 1080p60.
- Any Apple silicon generation other than the 2017 A10X.
- Absolute idle-W for this device post the tvOS 26.6 update (see caveats) — only the device-total **playing** figures, which are unaffected, are cited.
