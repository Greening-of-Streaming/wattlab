---
slug: hdr-costs-the-screen-4k-costs-the-box
version: 1
first_measured: 2026-10-04
last_refined: 2026-10-16
headline: "HDR and 4K cost energy in different places: HDR adds 3.7–4.4 W (7–8 %) at an OLED screen and nothing at six of seven boxes; 4K adds 0.28–1.07 W (11–21 %) at every box and nothing measurable at the screen"
claim_short: "LG C2 panel, HDR − SDR: +3.92 W HD, +4.35 W 4K (FilmMaker), +3.70 W 4K (Standard), all CIs > 0; 4K − HD +0.05 W [−0.20, +0.29]. Seven boxes, 4K − HD (SDR): +0.28 to +1.07 W; HDR10 − SDR at 4K: within ±0.03 W on six, +0.91 W on Apple TV 4K (2017). n=3, matched Meridian clips."
confidence: green
scope: "Client device layer only — the TV panel and seven streaming boxes, each on its own wall meter. Matched Meridian HD and 4K clips (SDR and HDR10 grades) over LAN HTTP. Network, CDN and data-centre energy excluded; the network cost of 4K's higher bitrate is not in these numbers."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - decode/uhd1004a
  - decode/uhd1004b
related_findings: [tv-screen-draws-20x-the-streaming-box, bitrate-barely-moves-box-playback-power, appletv-a10x-av1-vp9-software-fallback]
supersedes: null
tags: [decode, client-device, display, hdr, 4k, resolution, set-top-box, lg-c2, draft]
caveats:
  - "DRAFT pending lab review. Not yet checked by Tania; not for posting."
  - "'4K' here is 4K as delivered: the 4K clips also carry a higher bitrate (Apple TV position rate 20 vs 8 Mb/s). The box cost therefore bundles resolution and bitrate; the bitrate finding puts the bitrate share at roughly 10–17 mW per Mb/s, i.e. about 0.1–0.2 W of the 4K step."
  - "One TV (LG C2 55\" OLED). HDR switches the panel into its HDR picture mode at OLED light 100 (from 80), which is how HDR is shipped on this set; the premium is that bundle. The panel's 4K − HD difference in HDR (+0.47 W) has a wide CI [−1.32, +2.26] — read it as 'not resolved', not as a cost."
  - "The Apple TV 4K (2017) is the exception on HDR (+0.91 W, CI +0.45 to +1.37): it is also the one box whose home screen runs autoplay previews. Its rows are checked by playback position rate, not presented fps; one rep-1 HD HDR10 row was discarded for a box-state shift (carried in discarded[])."
  - "The Bbox presents ~51 fps on every arm, HD and 4K alike — consistent with a 50 Hz output mode, not a 4K stall. Fire TV and Roku each had one rep-1 row re-run (carried in discarded[]); Xiaomi Gen 3 SDR arms are n=6 (no-op output-mode repeats kept as ordinary repeats)."
  - "Box plugs (fw 1.3.1) refresh about every 2 s below ~12 W while polled at 1 s; means are unaffected, per-sample spread understated. CIs here are from rep means."
---

# The result, in one sentence

**HDR costs the screen, 4K costs the box**: on our OLED, HDR adds about 4 W (7–8 %) and the boxes don't notice it; 4K adds 0.3–1.1 W at every box and the screen doesn't notice it.

# Why this matters

"Streaming in 4K is worse for the planet" is one of the most repeated claims in the field, usually argued from data volume. At the home end, the measured picture is more specific. Resolution is a box-side cost — real, and 11–21 % of the box's draw, but tenths of a watt. HDR is a screen-side cost of several watts, because the TV drives the panel harder to show it.

So the two are levers for different people. 4K is a decision for the service and the box (and the network, which this finding does not measure). HDR is a decision for the TV and its settings, and its cost is roughly ten times larger in watts on the set we measured.

| Box | HD SDR W | 4K − HD (SDR) | HDR10 − SDR at 4K |
|---|---|---|---|
| Fire TV Stick 4K | 1.86 | +0.38 W (+20 %) | −0.02 W |
| Xiaomi TV Box Gen 3 | 2.47 | +0.28 W (+11 %) | 0.00 W |
| Xiaomi TV Box Gen 2 | 2.79 | +0.47 W (+17 %) | −0.02 W |
| Roku | 2.06 | +0.30 W (+14 %) | 0.00 W |
| Google TV Streamer | 1.93 | +0.41 W (+21 %) | −0.01 W |
| Bbox | 6.06 | +1.07 W (+18 %) | +0.02 W |
| Apple TV 4K (2017) | 5.69 | +1.04 W (+18 %) | **+0.91 W** |

Panel (LG C2, fed by the Google TV Streamer): HDR premium +3.92 W [2.21, 5.64] in HD FilmMaker, +4.35 W [3.79, 4.91] in 4K FilmMaker, +3.70 W [3.07, 4.34] in 4K Standard. n=3 per cell (Xiaomi Gen 3 SDR n=6); brackets are 95 % CIs.

# How it was measured

Four matched Meridian clips — HD and 4K, each in an SDR and an HDR10 grade — played over LAN HTTP. The TV and every box sat on their own P110 plugs, polled at 1 s; each row took a home-screen baseline first. Playback was verified per row: presented frame rate on the Android boxes, playback position rate on the Apple TV and Roku. Three whole passes; rows the campaign set aside are kept, with reasons, in each result's discarded[] block.

# What this finding does not measure

The network and CDN cost of 4K's larger stream; LCD or other TV models; HDR formats other than HDR10 (Dolby Vision, HLG); 8K; display-off box consumption.
