---
slug: streaming-box-plays-4-7x-cheaper-than-general-purpose
version: 1
first_measured: 2026-07-30
last_refined: 2026-07-30
headline: "Playing the same video, display attached: a fixed-function streaming box draws 4–7× less than a general-purpose board — even against the board's own hardware decoder"
claim_short: "BBB 1080p60 H.264, local file, screen on, marker-verified: Google TV +0.30 W · Pi 400 hw +1.32 W (4.4×) · Pi 400 sw +1.96 W (6.5×) · Pi 5 sw +2.03 W (6.8×). All 🟢."
confidence: green
scope: "Client device layer, display attached (device and monitor metered separately). Local delivery — network/CDN share excluded by design (measured separately at ~+0.3 W on the GTV). One clip, one rung, one board pair + one STB."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - decode/357b087d
  - decode/606d5ad3
  - decode/d99775a0
  - decode/ea55f33b
related_findings: [hw-decoder-cuts-client-energy-4x, codec-decode-energy-depends-on-silicon-and-regime]
supersedes: null
tags: [decode, playback, client-device, cross-silicon, fixed-function, owl-rem-lem, protocol-v3, draft]
caveats:
  - "DRAFT pending lab review. Single content (BBB 1080p60), single rung (~matched-VMAF 1080p), one device per silicon class."
  - "The GTV row is full playback on Android (player app + compositor inherent to the platform); the Pi rows are mpv on a desktop compositor. That asymmetry IS the finding's frame — each device on the playback stack a real product would use — not a lab artefact, but don't read the ratios as decoder-silicon ratios alone."
  - "Pi 400 hardware path is v4l2m2m via mpv --hwdec=v4l2m2m-copy (the zero-copy path composites incorrectly on this stack — copy adds some CPU cost, so +1.32 W is an upper bound on the board's hw-decode playback)."
  - "Display energy is metered separately (shared LCD, ~31 W while showing content) and excluded from the device figures."
---

# The result, in one sentence

Playing the same 1080p60 H.264 file from local storage with the screen attached, a Google TV Streamer draws **+0.30 W** where a Raspberry Pi 400 draws **+1.32 W with its hardware decoder** and **+1.96 W in software**, and a Raspberry Pi 5 — which shipped without the H.264 block — draws **+2.03 W**: purpose-built streaming silicon plays video for **4–7× less energy** than a general-purpose board, and the gap survives even when the board's own hardware decoder is engaged.

# Why this matters

Decode energy is paid **per viewer, per hour** — it is the multiplier on every fleet-scale number REM observes. Two consequences follow from this panel:

1. **Device class dominates codec choice.** The whole hw-vs-sw-vs-silicon spread here (~1.7 W) dwarfs the ≤0.08 W codec spread measured on fixed-function silicon in July. What a viewer *watches on* matters more than what codec they receive.
2. **"It has hardware decode" is not the end of the story.** The Pi 400's engaged hardware block still lands 4.4× above the STB — general-purpose platforms pay for compositors, OS overhead and memory paths that fixed-function pipelines avoid. And a device generation that *drops* a block (Pi 5) hands the whole cost to software.

# How it was measured

OWL decode rig (`/decode`, protocol v3): per-device Tapo P110 mW meters at 1 s cadence, reference-floor idle guard before every baseline, screen attached and metered separately (Lab-E), delivery local (Pi: tmpfs; GTV: adb-pushed file — the ~+0.3 W HTTP delivery share measured separately and excluded). Screen rows carry the in-clip 5 s black·white·black marker head; automated segmentation verified real content on screen for every row (marker swing ~5 W on the shared LCD). All four rows 🟢.

# What this finding does not measure

- Other content, rungs, codecs, or displays (OLED response is CR-071's territory).
- The GTV's decoder in isolation — Android always renders; the row is honest full playback.
- Network delivery (excluded by design here; +0.3 W measured separately on the GTV — see the July delivery-mode finding for why buffering strategy outweighs codec).
