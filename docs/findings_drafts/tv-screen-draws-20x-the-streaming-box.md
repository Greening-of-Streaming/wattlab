---
slug: tv-screen-draws-20x-the-streaming-box
version: 1
first_measured: 2026-10-04
last_refined: 2026-10-16
headline: "Watching a streaming box on a 55-inch OLED TV, the screen draws 21–29× the power of the box: the box is 3.3–4.5 % of the pair at the wall, across HD/4K and SDR/HDR"
claim_short: "LG C2 55\" panel 49.6–57.2 W vs Google TV Streamer 1.93–2.34 W, six arms (HD/4K × SDR/HDR, FilmMaker and Standard modes), n=3 each, all rows 🟢. Six other boxes on the same clips: 1.86–7.64 W — the hungriest is still under a seventh of the panel."
confidence: green
scope: "Client device layer only — the TV panel and the streaming box, each on its own wall meter. Matched Meridian clips over LAN HTTP, 2160p60 HDMI output. Network, CDN, router and data-centre energy excluded. One TV model (LG C2 55\" OLED, 2022) and one source box for the paired arms; the other six boxes ran into the same TV without being displayed."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - decode/uhd1004a
  - decode/uhd1004b
related_findings: [tv-picture-mode-outweighs-streaming-choices, hdr-costs-the-screen-4k-costs-the-box, streaming-box-plays-4-7x-cheaper-than-general-purpose]
supersedes: null
tags: [decode, client-device, display, tv-panel, google-tv, lg-c2, draft]
caveats:
  - "DRAFT pending lab review. Not yet checked by Tania; not for posting."
  - "One TV. An OLED's draw follows picture content and settings; an LCD with a backlight behaves differently, and a larger or smaller panel scales the ratio. Say 'on the TV we measured', not 'a TV'."
  - "The ratio is panel ÷ box at the same moment, both meters polled together. It is not a household's daily split: standby hours, other screens and the router are outside it."
  - "The paired arms use the Google TV Streamer, one of the frugal boxes (1.9–2.3 W). The Bbox (6.0–7.1 W) and Apple TV 4K 2017 (5.7–7.6 W) ran on their own meters into the same TV but were not displayed, so their screen share is inferred, not paired."
  - "Two Standard-mode rep-1 rows were set aside and re-run (carried in the result's discarded[] block). The plugs on the boxes (fw 1.3.1) refresh about every 2 s below ~12 W while polled at 1 s: means are unaffected; per-sample spread is understated, so the ± here are rep-to-rep SDs."
---

# The result, in one sentence

On the setup we measured, the screen draws **21–29 times** what the streaming box feeding it draws: the box is **3.3–4.5 %** of the pair at the wall, whatever the resolution or dynamic range.

# Why this matters

Energy estimates for watching video routinely spend their effort on the stream — the codec, the bitrate, the resolution — and then apply a modelled figure for "the device". The French Arcom/Arcep/ADEME study (2024) puts terminals, mostly TVs, at 72–90 % of audiovisual impact. This finding splits that terminal figure with two wall meters instead of a model: the box is a small fraction of it.

That changes where the savings are. Anything that touches only the box — a more efficient decoder, a different codec, a lower bitrate — acts on about 4 % of the home's draw while watching. Anything that touches the screen acts on the other 96 %.

| Arm (Meridian clip, matched grade) | Panel W | Box W | Panel ÷ box | Box share |
|---|---|---|---|---|
| HD SDR, FilmMaker | 52.80 ±0.10 | 1.93 ±0.01 | 27.4× | 3.5 % |
| HD HDR, FilmMaker | 56.73 ±0.68 | 1.94 ±0.01 | 29.3× | 3.3 % |
| 4K SDR, FilmMaker | 52.85 ±0.01 | 2.34 ±0.02 | 22.6× | 4.2 % |
| 4K HDR, FilmMaker | 57.20 ±0.22 | 2.33 ±0.01 | 24.5× | 3.9 % |
| 4K SDR, Standard | 49.56 ±0.29 | 2.34 ±0.02 | 21.2× | 4.5 % |
| 4K HDR, Standard | 53.27 ±0.18 | 2.34 ±0.04 | 22.8× | 4.2 % |

All n=3, ± = SD across reps, every row 🟢.

# How it was measured

The LG C2 and the Google TV Streamer each sat on their own Tapo P110 plug, polled together at 1 s. Each row: a home-screen baseline, then the clip played over LAN HTTP from GoS1's origin, with the TV's picture settings read before and after (unchanged on every kept row) and the box's presented frame rate checked (60 fps). Three whole passes over the arm list. The six other boxes ran the same four Meridian clips on their own meters, HDMI into the C2's other inputs.

# What this finding does not measure

The network, CDN and data centre; standby time across a day; any TV other than this one OLED; sound bars or AV receivers; embodied energy.
