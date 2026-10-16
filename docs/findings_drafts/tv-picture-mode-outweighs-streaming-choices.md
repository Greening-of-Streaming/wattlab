---
slug: tv-picture-mode-outweighs-streaming-choices
version: 1
first_measured: 2026-10-10
last_refined: 2026-10-16
headline: "On an LG C2 OLED, switching to Vivid or Sports picture mode adds 39 % (+20.4–20.7 W) on football and 21–22 % on an ad break; Eco mode saved nothing over Standard (+0.25 W) — one setting outweighs every streaming-side choice we have measured"
claim_short: "Football, panel W (n=3): Standard 52.69 · Eco 52.94 · FilmMaker 55.13 · Vivid 73.05 · Sports 73.37. Vivid − Standard +20.36 W [95 % CI 19.93–20.79]. Ad break: Vivid +10.49 W (+21 %), Sports +10.91 W (+22 %). Box flat at 1.79–1.88 W throughout."
confidence: green
scope: "Client device layer only — the TV panel, metered at the wall, fed over HDMI by a Google TV Streamer on its own meter. Each mode at its factory defaults on this set (Vivid/Sports at OLED light 100, the others at 80). Network, CDN and data-centre energy excluded. One TV model (LG C2 55\" OLED)."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - decode/c2pm1010
related_findings: [tv-screen-draws-20x-the-streaming-box, hdr-costs-the-screen-4k-costs-the-box]
supersedes: null
tags: [decode, client-device, display, tv-panel, picture-mode, lg-c2, draft]
caveats:
  - "DRAFT pending lab review. Not yet checked by Tania; not for posting."
  - "Picture modes are bundles. Vivid and Sports raise OLED light from 80 to 100 along with contrast and colour, so this measures the mode as shipped, not brightness alone. A viewer who turns Standard up to 100 would close part of the gap — untested."
  - "Eco on this set drew 0.25 W more than Standard on football (95 % CI +0.08 to +0.43 W) and 0.35 W more on the ad break: a difference of ~0.5 %, i.e. no saving. That is this firmware's Eco at its defaults; other brands' eco modes (Accedo measured one at ~51 W vs 120–130 W) can behave very differently."
  - "Content moves the size of the effect: +39 % on bright, green-field football, +21–22 % on a mixed ad break. Dark film content was not run."
  - "One ad-break Standard row (the campaign's first) was discarded: the panel sat flat at ~41 W for 108 of 120 s, a frozen picture under a PLAYING player state. Ad-break Standard is therefore n=2; every football cell is n=3."
  - "No per-row baseline by design: modes are compared as paired absolute watts within each pass, mode order varying between passes. The traffic light here rests on those paired CIs, not on per-row ΔW flags."
---

# The result, in one sentence

On the TV we measured, choosing **Vivid or Sports** picture mode adds about **20 W (+39 %)** while watching football — more than every streaming-side choice we have measured put together — and **Eco saved nothing** over Standard.

# Why this matters

Advice on reducing the energy of streaming usually targets the stream: lower the resolution, pick a newer codec, turn the bitrate down. On the same setup, those choices move the box by tenths of a watt (see the related findings). The picture mode moves the screen by twenty.

This confirms, with independent wall measurements, what Fraunhofer FOKUS (HbbTV Symposium 2024) and Accedo reported: the TV's own settings dominate. It also adds a caution about labels — on this set, the mode called Eco is not the frugal one.

| Picture mode | Football W | vs Standard | Ad break W | vs Standard |
|---|---|---|---|---|
| Standard | 52.69 | — | 49.11 (n=2) | — |
| Eco | 52.94 | +0.25 W (+0.5 %) | 49.46 | +0.35 W |
| FilmMaker | 55.13 | +2.44 W (+4.6 %) | 48.71 | −0.40 W |
| Vivid | 73.05 | +20.36 W (+38.6 %) | 59.60 | +10.49 W (+21.4 %) |
| Sports | 73.37 | +20.68 W (+39.2 %) | 60.03 | +10.91 W (+22.2 %) |

n=3 per cell unless stated; 120 s windows; the Google TV Streamer feeding the TV stayed at 1.79–1.88 W in every mode.

# How it was measured

`run_modes.py` set each picture mode over webOS's local API, read the settings back before and after each window (unchanged on every row), then played a 120 s football clip or a 1080p ad-break reel from the Google TV Streamer. Panel and box sat on separate P110 plugs polled at 1 s. Three whole passes, with the mode order varying between passes.

# What this finding does not measure

Other TV models or panel technologies (LCD backlights respond differently); manual brightness changes within a mode; ambient-light sensors; dark film content; the network or data centre.
