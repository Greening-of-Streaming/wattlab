---
slug: apple-m6-encode-energy-vs-ryzen-rtx5080
version: 1
first_measured: 2026-10-05
last_refined: 2026-10-05
headline: "Same encodes, two machines: the Apple M6 uses 26–40 % less marginal energy than a Ryzen 9 7900 on identical software encoders, and its media engine 15–22 % less than NVENC at comparable quality — in VBR mode"
claim_short: "Meridian-120s → 1080p ABR, n=3, all 🟢. Software encoders (bit-identical output): M6 CPU −26 % (H.264), −40 % (H.265), −40 % (AV1) marginal Wh vs Ryzen 9 7900. Hardware, VBR: M6 media engine −15 % (H.264, VMAF 88.6 vs 89.6) and −22 % (H.265, VMAF 88.0 vs 87.4, 20 % smaller file) vs RTX 5080 NVENC, but NVENC ~1.5× faster. Whole-machine: M6 2.3–3.4× cheaper per encode."
confidence: green
scope: "Device layer only. GoS1: AMD Ryzen 9 7900 + NVIDIA RTX 5080 (Ubuntu 24.04). GoS2: Apple M6 Mac mini (12-core CPU, 24 GB unified memory, macOS 27.0.1). Network, CDN, and CPE excluded. One clip (Meridian 120 s, low spatial complexity), 1080p ABR ladder bitrates."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - video/gos2-7ce583d6
  - video/gos2-458bce99
  - video/gos2-1f818306
  - video/gos2-b1e5704d
  - video/gos2-c3b3c5f5
  - video/gos2-bc2bb207
  - video/gos2-d9cc4c70
  - video/gos2-bc10c254
  - video/gos2-b5f4c041
  - video/b17c728d
  - video/83cb8c30
  - video/cb11b30c
  - video/gos2-bfaa8efb
  - video/gos2-095c80b4
  - video/gos2-2bf6a8ab
  - video/gos2-5ad2fd07
  - video/gos2-e691fcd1
  - video/gos2-fa0f4fec
  - video/88392150
  - video/e96c3e1b
  - video/dec790ee
  - video/ddc571d1
  - video/7867e832
  - video/a8704164
related_findings:
  - abr-all-codecs-meridian-120s
  - av1-hw-sw-vmaf-tradeoff
supersedes: null
tags: [video, encode, apple-silicon, m6, nvenc, cross-host, draft]
caveats:
  - "DRAFT pending lab review. Measured overnight 2026-10-04/05 by Claude with the owner asleep; Tania checks before anything is posted (publication rule 2026-08-17)."
  - "MARGINAL vs WHOLE-MACHINE. Headline percentages are OWL's standard marginal ΔE (energy above each machine's own idle floor). The two idle floors differ ~50× (GoS1 ~78 W, GoS2 ~1.4–2 W). The whole-machine view (wall power × time) makes the M6 2.3–3.4× cheaper per encode — valid only if the machine would otherwise sit idle or be off; state which view any quote uses."
  - "RATE CONTROL MATTERS MORE THAN SILICON ON THE M6 MEDIA ENGINE. In constant-bitrate mode (`-constant_bit_rate 1`, chosen to mirror NVENC's `-rc cbr`), the M6 encoder is slower (30.4 s vs 20.3 s), uses more energy (0.196 vs 0.170 Wh) and scores 5 VMAF lower (83.3 vs 88.6) at the same file size; raising the CBR target to 12 Mb/s only reaches VMAF 86.3 (bits go to filler). NVENC loses ~0.9 VMAF in CBR. The like-for-like hardware claim is therefore made in VBR on both; the CBR numbers stay on record."
  - "NVENC VBR overshoots the H.265 target (35.4 MB vs ~28.6 MB for 2 Mb/s); the M6 hit 28.2 MB. The H.265 hardware comparison is at comparable quality, not identical size."
  - "One clip (Meridian 120 s, SI ~13 / TI ~2 — easy content). Bitrate→VMAF points do not generalise to harder content; the within-encoder machine-to-machine ratios are the robust read."
  - "Software encoders: identical x264/x265/SVT-AV1 parameters and bit-identical output (VMAF equal to 2 decimals on both machines), but different ffmpeg builds (GoS1 /usr/local/bin/ffmpeg-master, GoS2 Homebrew 9.0.2) and library versions."
  - "Measurement differences: GoS1 enters focus mode (systemd timers stopped); GoS2 has no focus mode yet. GoS2's inner meter (P110 fw 1.3.1) refreshes every 2.0 s at low load, GoS1's every ≤1 s; both dual-meter (ci2). No thermal sensors on GoS2."
  - "Interim mechanism: GoS1 drives GoS2 over SSH; the SSH round-trip (~0.3 s) is inside GoS2's timed window."
---

# The result, in one sentence

On the same encodes from the same source bytes, an Apple M6 Mac mini spent 26–40 % less energy than a Ryzen 9 7900 running the identical software encoders (with bit-identical output), and its media engine spent 15–22 % less than an RTX 5080's NVENC at comparable quality — but only once both are run in variable-bitrate mode, and NVENC remained about 1.5× faster.

# Why this matters

The M6 is new and nobody has published energy *per encode* for it — reviews report peak watts and speed. For a streaming operator the useful number is Wh per job at a stated quality. Two practical points fall out: (1) on Apple silicon, the rate-control mode is a bigger lever than the hardware — CBR costs 5 VMAF, 50 % more time and 15 % more energy for the same file; (2) the per-job advantage of a low-idle machine is modest at the margin and large at the wall — the deciding factor is utilisation, not the encoder.

# How it was measured

OWL's standard video protocol on both machines through one code path (CR-085): idle baseline, encode, cooldown, second baseline, encode; dual-meter P110 sampling on each machine's own plugs; ΔE = ΔW × ΔT; confidence by the CR-028 CI model; VMAF scored on GoS1 against the same source (sha256-verified copy on GoS2). Source: Meridian 120 s (Netflix Open Content, CC BY 4.0) → 1080p, H.264 4 Mb/s, H.265 2 Mb/s, AV1 1.5 Mb/s, GOP 120, 2 B-frames. n = 3 per engine, interleaved by repetition across machines.

| Engine | Machine | ΔE (Wh, mean ± 95 % CI) | Time (s) | VMAF | Size (MB) |
|---|---|---|---|---|---|
| x264 (CPU) | Ryzen 9 7900 | 0.722 ± 0.008 | 36.7 | 93.19 | 57.1 |
| x264 (CPU) | Apple M6 | 0.532 ± 0.005 | 39.7 | 93.19 | 57.1 |
| x265 (CPU) | Ryzen 9 7900 | 1.238 ± 0.030 | 61.1 | 89.91 | 28.6 |
| x265 (CPU) | Apple M6 | 0.737 ± 0.011 | 60.6 | 89.90 | 28.6 |
| SVT-AV1 (CPU) | Ryzen 9 7900 | 0.635 ± 0.026 | 31.9 | 87.83 | 14.4 |
| SVT-AV1 (CPU) | Apple M6 | 0.379 ± 0.010 | 31.1 | 87.80 | 14.1 |
| H.264 hw, VBR | RTX 5080 NVENC | 0.199 ± 0.012 | 12.8 | 89.56 | 60.2 |
| H.264 hw, VBR | M6 media engine | 0.170 ± 0.011 | 20.3 | 88.60 | 56.4 |
| H.265 hw, VBR | RTX 5080 NVENC | 0.224 ± 0.008 | 14.7 | 87.36 | 35.4 |
| H.265 hw, VBR | M6 media engine | 0.174 ± 0.005 | 21.1 | 88.02 | 28.2 |
| H.264 hw, CBR | RTX 5080 NVENC | 0.199 ± 0.006 | 12.8 | 88.69 | 57.2 |
| H.264 hw, CBR | M6 media engine | 0.196 ± 0.007 | 30.4 | 83.25 | 57.1 |
| H.265 hw, CBR | RTX 5080 NVENC | 0.225 ± 0.007 | 14.7 | 84.54 | 28.9 |
| H.265 hw, CBR | M6 media engine | 0.198 ± 0.002 | 32.2 | 83.40 | 28.6 |

No AV1 hardware row for the M6: its media engine decodes AV1 but has no AV1 encoder (Apple spec; confirmed — no `av1_videotoolbox` in ffmpeg on the machine).

# What this finding does not measure

- Not network, CDN, packaging or playback — device layer, encode only.
- Not harder content, other resolutions, 10-bit/HDR, or live (real-time) encoding.
- Not why: the gap between machines is consistent with process node, core design and platform idle draw, but a wall meter cannot attribute it. Unified memory is unlikely to explain the hardware-encode result (NVENC's pipeline also keeps frames on the GPU) — see the report `docs/gos2_m6_report_2026-10.md`.
- Not a ranking of NVENC: OWL's NVENC preset is CBR; VBR closes most of its quality gap but overshoots the H.265 size target.
