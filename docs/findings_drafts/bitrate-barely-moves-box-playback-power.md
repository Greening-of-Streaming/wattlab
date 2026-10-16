---
slug: bitrate-barely-moves-box-playback-power
version: 1
first_measured: 2026-09-03
last_refined: 2026-10-16
headline: "Across a 128× bitrate span (0.25 → 32 Mb/s, H.264 1080p60), four streaming boxes' playback power rises only 15–26 % (+0.30 to +0.53 W), linearly at 10–17 mW per Mb/s"
claim_short: "Device-total W, 0.25 → 32 Mb/s, n=3 (Fire TV 0.25 Mb/s n=2): Fire TV 1.80 → 2.10 (+17 %), Google TV 1.69 → 2.13 (+26 %), Xiaomi Gen 2 2.73 → 3.26 (+19 %), Xiaomi Gen 3 2.50 → 2.88 (+15 %). Linear fits r = 0.92–0.99, slopes 10.4 / 13.2 / 17.2 / 13.0 mW per Mb/s."
confidence: green
scope: "Client device layer only — four streaming boxes at the wall, playing a 2-minute BBB H.264 1080p60 NVENC CBR ladder over Wi-Fi from a LAN origin. Display not metered. Network, CDN and data-centre energy excluded: the network cost of a higher bitrate is not in these numbers."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - decode/bf22114b
  - decode/acb6fefc
  - decode/b6e748a9
related_findings: [hdr-costs-the-screen-4k-costs-the-box, stb-decode-and-play-content-over-codec, tv-screen-draws-20x-the-streaming-box]
supersedes: null
tags: [decode, client-device, bitrate, set-top-box, protocol-v3, draft]
caveats:
  - "DRAFT pending lab review. Not yet checked by Tania; not for posting."
  - "Read as device-total watts, not ΔW. The Fire TV's foregrounded player UI (the baseline state between rungs) draws more than playing video, so its per-row ΔW is negative and flagged 🔴 on two of three passes; its absolute draw is clean and replicates. The other three boxes are 🟢 on every row."
  - "One Fire TV 0.25 Mb/s repeat ended PAUSED and is excluded, leaving that cell at n=2."
  - "One content (Big Buck Bunny, animation), one codec (H.264), one resolution (1080p60). At 32 Mb/s Wi-Fi delivery starts to stall on the Xiaomi Gen 2 (85–90 % PLAYING); the Fire TV sustains it."
  - "Box plugs (fw 1.3.1) refresh about every 2 s below ~12 W while polled at 1 s; means are unaffected. CIs are from rep means."
  - "Over Ethernet, the Google TV's 1.5 → 20 Mb/s step costs ~+0.17 W at n=3 (CR-074), consistent with the slope here."
---

# The result, in one sentence

Multiplying the bitrate by 128 raises a streaming box's playback power by only **15–26 %** — about **0.3–0.5 W** — rising in a straight line at **10–17 mW per Mb/s**.

# Why this matters

"Lower the resolution" and "lower the bitrate" are standard energy-saving advice for viewers and services. At the box, the measured effect is small and predictable: going from a quarter-megabit stream to 32 Mb/s costs less than half a watt, and on a TV setup that is a rounding error next to the screen (see the related findings).

That does not make bitrate free — the network and storage side is outside this finding — but it does mean device-side savings from bitrate cuts should be quoted in tenths of a watt, not as a share of "streaming energy".

| Box | 0.25 Mb/s | 32 Mb/s | Δ [95 % CI] | Slope | r |
|---|---|---|---|---|---|
| Fire TV Stick 4K | 1.80 W | 2.10 W | +0.30 W [0.23, 0.37] (+17 %) | 10.4 mW/Mb/s | 0.98 |
| Google TV Streamer | 1.69 W | 2.13 W | +0.44 W [0.37, 0.51] (+26 %) | 13.2 mW/Mb/s | 0.98 |
| Xiaomi TV Box Gen 2 | 2.73 W | 3.26 W | +0.53 W [0.38, 0.67] (+19 %) | 17.2 mW/Mb/s | 0.99 |
| Xiaomi TV Box Gen 3 | 2.50 W | 2.88 W | +0.39 W [0.32, 0.45] (+15 %) | 13.0 mW/Mb/s | 0.92 |

Seven rungs (0.25, 0.5, 1.5, 4, 8, 16, 32 Mb/s), n=3 per rung per box; slope and r from a linear fit of rung means against bitrate.

# How it was measured

Batch `bae281b52f90` (2026-09-03): a seven-rung NVENC CBR ladder of the same 2-minute BBB 1080p60 clip, 90 s per rung, four boxes started together by the rendezvous barrier and each on its own P110 plug polled at 1 s. Three passes, the third at 13:20; 84 of 84 rows completed.

# What this finding does not measure

Network, CDN and storage energy at higher bitrates; other codecs, resolutions or content; Ethernet-connected boxes (except the one CR-074 cross-check); the display.
