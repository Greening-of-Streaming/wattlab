---
slug: looped-excerpt-measures-as-continuous
version: 1
first_measured: 2026-09-03
last_refined: 2026-09-03
headline: "Looping a 2-minute excerpt measures the same as playing the continuous original; a 30-second loop does not on every box"
claim_short: "Four STBs, one 600 s H.264 1080p60 encode of Big Buck Bunny, n=3 paired passes: its 120 s excerpt ×5 sits within 0.02 W of the continuous 600 s (CIs straddle zero, ±0.03–0.04 W bound on three boxes); its 30 s excerpt ×20 costs the Google TV Streamer +0.012 ±0.009 W and Xiaomi Gen 3 +0.101 ±0.027 W (+3.8 %)."
confidence: green
scope: "Client device layer only (Fire TV Stick 4K, Google TV Streamer, Xiaomi TV Box Gen 2 and Gen 3, all on Wi-Fi, headless, Just Player). Realtime playback of a video-only LAN HTTP file; 600 s windows; means over PLAYING-only samples. Network, CDN and display excluded. Loops are stream-copy concatenations of the same encode with a keyframe at every cut, not player-side repeat."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - decode/7e3b31a9
  - decode/40259132
  - decode/52f9cf24
related_findings: [stb-decode-and-play-content-over-codec, codec-decode-energy-depends-on-silicon-and-regime]
supersedes: null
tags: [decode, client-device, methodology, looping, content, protocol-v3, draft]
caveats:
  - "DRAFT pending lab review. Numbers are from the three stored jobs; the equivalence bound and the 30 s-loop cost need Tania's read before this leaves the room."
  - "One content (Big Buck Bunny), one codec and rate (H.264 1080p60 NVENC CBR 8 Mbps), one excerpt (120–240 s of the clip). The multi-minute result matches how every rig loop family is built (a 2-min excerpt ×10 or ×30); it has not been tested on the software-decode Pis or on 4K/HDR streams."
  - "Xiaomi Gen 3's 120 s-loop difference is +0.019 ±0.237 W: inconclusive on that box at n=3, because the box alternated between two draw states ~0.15 W apart across passes (also seen in the 4K HEVC synchronised run the same day), not because of the loop."
  - "Each 600 s window ends with the clip, so the last ~12 of 600 samples per row sit after end-of-file; they are excluded from the cited means by the box's own media-session clock, identically for all three arms. The stored rows' window means include them and read up to 0.01 W lower."
  - "Cuts here are keyframe-aligned splices of one encode (no decoder reinitialisation, no black frames, no audio). A player-side repeat, a splice with a different coded size, or an audio-bearing clip may behave differently — the S72/S73 marker-encoder failures show splices with a coded-height change freeze hardware HEVC decoders outright."
  - "n=3 passes per arm per box, paired within pass (the three arms run back to back in one job per box, all four boxes started together by the rendezvous barrier). Per-rung confidence on every row is 🟢; the claim is an equivalence, so the CI half-width is the number that carries, not the light."
---

# The result, in one sentence

Playing a 2-minute excerpt five times over costs the same as playing the 10 minutes it came from, on all four set-top boxes tested; playing a 30-second excerpt twenty times over costs measurably more on two of them — up to +0.10 W (+3.8 %) on the Xiaomi Gen 3.

# Why this matters

Every long-window row on the OWL decode rig is a loop: the 20- and 60-minute clips the boxes play are one 2-minute excerpt concatenated ten or thirty times, because the rig has to outlast the 20-minute inactivity timers on Android TV and because the test corpus is short. That is a methodological assumption sitting under a lot of numbers, and it was unmeasured. It now has a bound: for multi-minute excerpts the loop is invisible to the meter, within 0.03–0.04 W on three of the four boxes (under 2 % of playback draw), with the fourth inconclusive for reasons of its own.

The same measurement says where the assumption breaks. Cutting every 30 seconds — one splice per 1 800 frames, keyframe-aligned, no decoder reset — is enough to raise the Google TV Streamer by 0.012 W and the Xiaomi Gen 3 by 0.10 W, consistently across three passes. So a very short source cannot be looped into a long test clip and compared like for like with the rest of the corpus on every device: the cut has a price on some silicon, and the price is device-specific. The 5-second UVG sequence the encode side adopted as its sports clip (ReadySetGo, on disk as seven repeats) is exactly that case, six times over, and this result is the reason the decode rig now needs a longer source before it can take that clip as its sports tier (CR-081).

# How it was measured

One encode of the first 600 s of the 4K Big Buck Bunny master, scaled to 1080p60, NVENC CBR 8 Mbps, GOP 2 s, with a keyframe forced every 30 s so that stream-copy cuts land exactly on frame boundaries; video-only like the rig's synchronised families. From that single file: arm A, the continuous 600 s; arm B, the 120–240 s excerpt cut with stream copy and concatenated five times; arm C, the 120–150 s excerpt concatenated twenty times. All three are 600 s long to within 0.7 s and carry the same bitstream at the same rate.

The three arms ran back to back in one job per box, the four boxes launched together through the rig's file-based start barrier, in three passes an hour apart. Each row: 20 s baseline, 5 s settle, 8 s startup skip, 600 s of 1 Hz P110 samples on the box's own plug, the box's media-session position polled every 2 s. Means are taken over the samples the box's own clock marks PLAYING at 1× (588–589 of 600 per row, the remainder being the post-end-of-file tail), and the arm differences are paired within pass before averaging, with t-based 95 % CIs at n=3.

| box | A continuous, W | B − A, 120 s ×5 | C − A, 30 s ×20 |
|---|---|---|---|
| Fire TV Stick 4K | 1.867 ±0.022 | +0.007 ±0.029 | +0.026 ±0.050 |
| Google TV Streamer | 1.944 ±0.036 | −0.003 ±0.024 | +0.012 ±0.009 |
| Xiaomi TV Box Gen 2 | 2.954 ±0.058 | +0.006 ±0.042 | +0.008 ±0.028 |
| Xiaomi TV Box Gen 3 | 2.682 ±0.025 | +0.019 ±0.237 | +0.101 ±0.027 |

Full narrative, the per-pass values and the Gen 3 two-state note: `docs/intra_content_sync_2026-09-03.md` §5h.

# What this finding does not measure

Player-side repeat (a player re-opening the file), which restarts the pipeline each time and is not how the rig loops. Loops that change the coded picture size, colour metadata or codec at the splice — those are known to freeze hardware HEVC decoders, a different failure. Audio-bearing clips (the loop families the rig pools have audio; this test is video-only, like the synchronised families). Software-decode devices (the Pis), 4K or HDR streams, and any content other than Big Buck Bunny at one rate. Whether the 30 s-loop cost on Gen 3 comes from the decoder, the display pipeline or the player is not established; only its size is.
