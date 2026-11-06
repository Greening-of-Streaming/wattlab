---
slug: encode-energy-levers-nvenc-vs-apple-m6
version: 1
first_measured: 2026-10-12
last_refined: 2026-10-13
headline: "What moves encode energy depends on the silicon. On an RTX 5080, NVENC's preset alone moves energy up to 2.9× for no VMAF gain. On an Apple M6, no encoder setting does — only where the 4K source is decoded and scaled. At matched quality the M6 media engine uses about 5× less energy above idle."
claim_short: "Meridian 120 s 4K60 → 1080p, batch encode, n=3 per point, all 🟢. NVENC (SM clock capped 2572 MHz) H.265 2 Mb/s, presets p1/p4/p7/p7+quality bundle: 0.171/0.240/0.551/0.707 Wh, VMAF 87.8/87.4/87.3/87.8. Apple M6 media engine: bitrate, rate control and four encoder options within ±5 % energy (prio_speed 1 possibly −10–20 %). M6 decode+scale location: CPU 0.190 Wh vs hardware decode + CPU scale 0.0445 Wh at equal VMAF 88.0. At matched quality: M6 0.0415/0.0445 Wh (VMAF 88.6/88.0) vs NVENC p4 0.211/0.240 Wh (VMAF 89.6/87.4) — 5.1× (H.264) / 5.4× (H.265) less marginal energy."
confidence: green
scope: "Device layer only, encode only. GoS1: AMD Ryzen 9 7900 + NVIDIA RTX 5080 (Ubuntu 24.04, ffmpeg-master, NVENC, SM clock capped at 2572 MHz). GoS2: Apple M6 Mac mini (24 GB, macOS 27.0.1, Homebrew ffmpeg 9.0.2, VideoToolbox). Network, CDN, packaging and playback excluded. Batch regime (encode as fast as possible) unless stated as live (real-time input). Energy = marginal ΔE above each machine's own idle floor, wall-measured with two P110 meters per machine."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  # NVENC anchors (H.264 4 Mb/s, H.265 2 Mb/s, preset p4)
  - video/fdd5c778
  - video/094d10d7
  - video/c7f0e34c
  - video/e9220249
  - video/87c8c8df
  - video/f0cd8085
  # NVENC presets p1 / p7 / p7+bundle, H.264 then H.265
  - video/66925e75
  - video/630571d1
  - video/2f82ca5a
  - video/34f8ab09
  - video/4663207d
  - video/c8448a0a
  - video/76528684
  - video/a23fbd5e
  - video/1ec984c4
  - video/9918e451
  - video/8c1eb158
  - video/6e514039
  - video/00a18e12
  - video/894609ff
  - video/4aa7d1b7
  - video/d1149665
  - video/8cc05f2d
  - video/106eb531
  # M6 — hardware decode + CPU scale (matched quality), H.264 then H.265
  - video/9292da5e
  - video/f31d44bc
  - video/df7e73d1
  - video/f434d4b4
  - video/95e0881f
  - video/d8c2f939
  # M6 — CPU decode + CPU scale, H.264 then H.265
  - video/f25735bf
  - video/0118185e
  - video/589d47ef
  - video/7c6753fd
  - video/b82483d3
  - video/0b7862b9
  # M6 — full media-engine pipeline (hardware decode + scale_vt), H.264 then H.265
  - video/0b64f41a
  - video/bc5cbaa4
  - video/b15c90c1
  - video/efe96ad9
  - video/8e98a25b
  - video/5e17f849
  # Live (real-time) — NVENC H.264 / H.265 / ladder, then M6 H.264 / H.265 / ladder
  - video/92bd4a03
  - video/34f956e5
  - video/4bce0b7a
  - video/4e54e390
  - video/4202e41a
  - video/1792d1d2
  - video/37588318
  - video/2d32c86f
  - video/b72137c1
  - video/c4fcd606
  - video/7753acdd
  - video/300d5a93
  - video/5f4b148f
  - video/ea513bb7
  - video/892ca25b
  - video/ac98b3ef
  - video/227b5482
  - video/dc15e201
related_findings:
  - gpu-boost-overclocks-fixed-function-nvenc
  - abr-all-codecs-meridian-120s
  - hw-decoder-cuts-client-energy-4x
supersedes: null
tags: [video, encode, apple-silicon, m6, nvenc, sensitivity, cross-host, live, draft]
caveats:
  - "DRAFT pending lab review. Measured 2026-10-12/13 by Claude (overnight + the following morning); Tania checks before anything is posted (publication rule 2026-08-17). Full campaign, every row and the running notes: /srv/data/owl/campaign_2026-10-12_encode_sensitivity/ (NOTES.md, summary.txt, *.jsonl)."
  - "MATCHED QUALITY REQUIRES CPU SCALING ON THE M6. The fully hardware M6 pipeline (VideoToolbox decode + scale_vt) is cheaper still — 0.0177 / 0.0186 Wh — but Apple's hardware scaler costs ~3.5 VMAF (85.1 / 84.5 vs 88.6 / 88.0 at the same bitrate). Hardware DECODE is quality-neutral; the loss is the scaler (scale_vt has no quality options; forcing bt709 colour made it worse, 82.9). The 5× headline uses the quality-preserving pipeline."
  - "NVENC NUMBERS ARE AT A CAPPED SM CLOCK (2572 MHz, the knee from gpu-boost-overclocks-fixed-function-nvenc). At default boost NVENC uses ~9–12 % more for the same encode, so the M6 ratio would be slightly larger, not smaller."
  - "WHY NVENC IS EXPENSIVE: the card's board sensor rises from ~18 W idle to 61–79 W during every hardware encode — 86–98 % of the wall ΔW — whatever the bitrate, preset, rate control or content. NVENC energy is that awake power × encode time; presets change the time. This is consistent with published board telemetry (arXiv 2605.01187: 50–55 W, flat across P1/P4/P7) but that work reports neither wall energy per job nor decode/scale."
  - "PRESETS AT EVERY BITRATE (Kranjska, hard content, H.265 1–6 Mb/s): p7 over p4 adds +0.14…+0.43 VMAF at each rate (≈1–3 % bitrate at iso-VMAF) for 2.3× energy; the quality bundle (tune hq, multipass, spatial/temporal AQ, lookahead) LOWERS VMAF by 0.9–1.6 on hard content (VMAF does not reward AQ's perceptual targeting). Effort on hard content: H.264 p1/p4/p7/bundle 71.3/73.2/73.5/71.6 VMAF at 0.078/0.083/0.171/0.184 Wh."
  - "THE M6's ENCODER OPTIONS: power_efficient and spatial_aq produced bit-identical VMAF to the default and no energy change (power_efficient = kVTCompressionPropertyKey_MaximizePowerEfficiency — no published energy measurement found). prio_speed 1: VMAF equal or +0.4/+1.2, energy −12 % (main run) / −20 % ± 16 % (4-min runs) — 'possibly 10–20 % less', not claimed. CBR: +2–4 % energy, −3.6 to −4.3 VMAF."
  - "`-realtime` ON THE M6 BREAKS RATE CONTROL ON HARD CONTENT: 5.8 Mb/s delivered for a 4 Mb/s H.264 target, 6.8 Mb/s for a 2 Mb/s H.265 target (3.4×); on easy content it held target. No public report of this found (2026-10-13). Anyone using it for live encoding should check delivered bitrate."
  - "ON HARD CONTENT THE M6 NEEDS MORE BITS for the same VMAF than NVENC: Kranjska at the same bitrate scores 5–6.6 VMAF lower (full-hardware pipeline; Kranjska needs no 4K downscale, so this is the encoder itself). Its energy is flat with bitrate (±7 % over 2–16 Mb/s), so the energy gap survives at iso-VMAF but the delivered file is larger — the network/storage side is outside this finding."
  - "LIVE (real-time input, -re, 120 s of 4K60 → 1080p): NVENC 1.27 ± 0.06 Wh (H.264), 1.27 ± 0.09 (H.265), 1.37 ± 0.06 (3-rung ladder) vs M6 0.021 ± 0.004 / 0.023 ± 0.003 / 0.032 ± 0.004 Wh — 43–61× less above idle, 51–57× whole-machine. These M6 live rows use the full-hardware pipeline (−3.5 VMAF); the matched-quality live pipeline was not measured. M6 live ΔW is 0.6–1.0 W, near the plug's resolution, though all 9 rows are 🟢 and the reps agree within ±12 %."
  - "Meters: two Tapo P110 per machine, per-meter combine (ci2). GoS2's inner plug (fw 1.3.1) refreshes every 2 s below ~12 W, so most M6 task windows have ~55 % fresh samples; the two GoS2 meters agree within 0.1–0.3 W on every row. powermetrics could not serve as a third check: on this M6 / macOS 27.0.1 it reports 0 W for CPU, GPU and combined power even under full load."
  - "One easy clip (Meridian 120 s, 3840×2160 59.94, SI~13/TI~2) for the headline; Kranjska (1920×1440 30, sport) for hard-content checks. 8-bit SDR only; no AV1 (the M6 has no AV1 encoder). VMAF v1 (vmaf_v1.0.16), scored on GoS1 for both machines' outputs against the same sha256-verified source; hardware encodes were byte-size-identical across reps."
  - "One invalid row excluded and re-measured (GoS2 job ff617b49: first job after a service restart had no pre-job idle guard and caught the tail of an unmeasured timing encode)."
  - "Supersedes the hardware-encode framing of the draft apple-m6-encode-energy-vs-ryzen-rtx5080: its M6 media-engine rows decoded and scaled on the CPU (OWL's GoS2 default), which is why it found only −9 to −18 % vs NVENC."
---

# The result, in one sentence

Encoding the same 4K60 clip to 1080p, an RTX 5080's NVENC spends 0.17 to 0.71 Wh depending only on its preset — with no VMAF gain from the slow presets — while an Apple M6's media engine spends about the same energy whatever encoder setting it is given, and at matched quality uses about 5× less energy above idle than NVENC (0.0445 vs 0.240 Wh for H.265, VMAF 88.0 vs 87.4).

# Why this matters

Encoder guides tell operators to pick presets and rate control for quality; nobody publishes what those choices cost in energy, and the answer turns out to depend on the silicon. On NVIDIA the card has a large "awake" cost (~45–60 W above idle) that no setting removes, so energy is simply that power multiplied by encode time — slow presets roughly double or triple the energy and, measured by VMAF at a fixed bitrate, buy almost nothing (≤ +0.4 VMAF, ≈ 1–3 % bitrate). On the Apple M6 the encoder block draws so little (≈ 2 W above idle) that its own settings disappear in the noise; what matters is whether the 4K source is decoded on the media engine or the CPU (a 4.3× difference at identical quality). For a live service the contrast is starkest: encoding in real time, NVENC holds the card awake for the full duration of the content.

| Same job, Meridian 4K60 → 1080p | NVENC (RTX 5080) | Apple M6 |
|---|---|---|
| Bitrate 2 → 16 Mb/s | ±3 % | ±7 % |
| Encoder effort (preset / speed options) | **−29 % … +195 %** | −12 % … +4 % |
| CBR vs VBR | ±2 % (−0.9 VMAF) | +2–4 % (**−3.6 to −4.3 VMAF**) |
| Output 720p / 2160p | −26…−34 % / +186…+216 % | −12…+3 % / +78…+92 % |
| Decode + scale on the CPU instead of the hardware | +83 … +86 % | **+330 %** (vs hardware decode + CPU scale) |

| Matched quality, batch | Wh per 120 s (mean ± 95 % CI, n=3) | VMAF |
|---|---|---|
| NVENC H.264 4 Mb/s, p4 | 0.211 ± 0.003 | 89.56 |
| M6 H.264 4 Mb/s, hardware decode + CPU scale | 0.0415 ± 0.0013 | 88.60 |
| NVENC H.265 2 Mb/s, p4 | 0.240 ± 0.003 | 87.36 |
| M6 H.265 2 Mb/s, hardware decode + CPU scale | 0.0445 ± 0.0014 | 88.02 |
| M6 H.265, CPU decode + CPU scale (OWL's GoS2 default) | 0.190 ± 0.002 | 88.02 |

# How it was measured

Both machines ran OWL's standard single-encode job through their own OWL instance (queue, pre-job idle guard, focus mode, dual P110 meters, CI-based traffic light), driven from one campaign script with identical ffmpeg commands apart from the encoder block. Each parameter was varied one at a time around a shared anchor (Meridian 120 s → 1080p, VBR, H.264 4 Mb/s / H.265 2 Mb/s, GOP 120, 2 B-frames, no audio), n = 3 per point, run order shuffled per repetition, both nodes in parallel. Short encodes were looped (`-stream_loop`) so every measured window was ≥ 25 s (4 minutes for the M6 precision and pipeline runs); energy is reported per 120 s pass. GoS1's GPU SM clock was capped at 2572 MHz for the whole campaign and logged at 1 Hz (max 2565 MHz on every row). VMAF was computed afterwards on GoS1 with OWL's own VMAF graph for both machines' outputs, on the first pass of each encode. About 340 measured jobs, all 🟢 after excluding one documented invalid row.

# What this finding does not measure

- Not the network, CDN or storage cost of the different file sizes — notably the M6 needing more bits than NVENC for the same VMAF on hard content.
- Not perceived quality beyond VMAF (AQ's perceptual benefit is invisible to VMAF), HDR/10-bit, AV1, or other content than one easy and one hard clip.
- Not the matched-quality M6 pipeline in live (real-time) mode — the live rows use the full-hardware pipeline at −3.5 VMAF.
- Not why the M6 encoder draws so little: a wall meter cannot attribute power inside the SoC, and powermetrics reports 0 W on this machine.
- Not other NVIDIA cards or default (uncapped) GPU boost — expected to widen, not narrow, the gap.
