---
slug: av1-hw-sw-vmaf-tradeoff
version: 1
first_measured: 2026-05-22
last_refined: 2026-05-22
headline: "AV1 hardware uses ~55% less energy than software at 1500 kbps, but loses ~2 VMAF points and produces ~40% larger files"
claim_short: "1500 kbps ABR — SVT-AV1: 0.71 Wh · VMAF 92.74 · 14.5 MB · 34 s    av1_vaapi: 0.32 Wh · VMAF 90.79 · 20.3 MB · 15 s"
confidence: green
review_status: for-comment
impact: 2
scope: "Device layer only (GoS1: AMD Ryzen 9 7900 + Radeon RX 7800 XT). Network, CDN, and CPE excluded. No amortised training cost."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - video/e18a9d57
related_findings: []
supersedes: null
tags: [video, av1, vmaf, hw-vs-sw, cr-044]
caveats:
  - "Cross-codec VMAF in this run is NOT apples-to-apples — H.264 / H.265 / AV1 ran at different per-codec bitrate targets (4 / 2 / 1.5 Mbps ABR ladder). Only the within-AV1 CPU-vs-GPU comparison at the same 1500 kbps is a fair quality read."
  - "Tiny clips (≤~4 s) fall below the P110 measurement floor for this comparison and correctly flag 🔴; this finding requires ≥10 s of GPU encode runtime."
  - "av1_vaapi hit the 1500 kbps bitrate target (20.3 MB file). libsvtav1 undershot to ~967 kbps actual (14.5 MB file) yet still scored higher VMAF — so SVT-AV1 is markedly more bit-efficient, and the hardware encoder buys its speed/energy advantage by giving up compression quality."
  - "Meridian is now MEASURED (2026-06-19, ITU-T P.910 SI/TI) to be LOW spatial complexity (SI ~13 / TI ~2) — an easy clip. This HW-vs-SW tradeoff is therefore measured on easy content; on harder content the ~2-VMAF gap and the bit-efficiency penalty may differ (the finding already flags content-sensitivity). The within-AV1 same-1500-kbps comparison on this clip is unaffected. NB this is the frozen AMD-era result (RX 7800 XT / av1_vaapi); it is NOT contradicted by the 2026-06 RTX-5080 NVENC parity run, which is a different encoder."
---

# The result, in one sentence

At an identical 1500 kbps ABR target on a 120 s 1080p Meridian source, AMD's `av1_vaapi` hardware encoder used **0.32 Wh** to produce a file scoring VMAF **90.79**, while `libsvtav1` (SVT-AV1) on the CPU used **0.71 Wh** for a file scoring VMAF **92.74**. The GPU path is **~2.3× faster** and uses **~55% less energy** — but produces a **~40% larger file** at **~2 VMAF points lower** perceptual quality.

# Why this matters

This is the first OWL finding that pairs energy with a measured perceptual quality axis (VMAF, shipped in CR-044). Until VMAF landed, *"AV1 GPU is faster and cheaper"* looked like an unqualified win. With VMAF, the trade-off is visible: the hardware encoder's speed and energy advantage comes from a less compression-efficient encode that produces a larger file at lower perceptual quality. Operators choosing between paths can now see what they are giving up.

For the other two codecs in the same run (H.264 and H.265) the CPU-vs-GPU VMAF gap is ≤2 points and within measurement noise — H.264 scored **94.0** (CPU) vs **92.1** (GPU); H.265 scored **94.1** vs **92.0**. **AV1 is the codec where the hardware-vs-software gap actually shows in our measurements** — and it is the codec where the streaming industry's adoption decision is most active.

# How it was measured

A single 120-second 1080p source (Meridian, Netflix Open Content, CC BY 4.0). Six encodes total — H.264 / H.265 / AV1 each on CPU (`libx264` / `libx265` / `libsvtav1`) and GPU (`h264_vaapi` / `hevc_vaapi` / `av1_vaapi`). Constant per-codec ABR bitrate target across CPU and GPU sides (4 / 2 / 1.5 Mbps). Energy measured at the wall via a Tapo P110 plug at 1 Hz, with the same focus-mode + lock-file + cooldown protocol every other OWL run uses. VMAF computed as a *terminal* pass after each measurement window closes, so its CPU draw never enters the reported energy.

All six encodes returned 🟢 confidence (CR-028 Phase 2 confidence-interval model — `confidence_positive = 1.0` on all six). The full source measurement, including raw P110 sample arrays, codec-by-codec energy and VMAF, and per-encode thermal traces, is embedded below.

# What this finding does not measure

- A single source, single resolution, single bitrate per codec. The numbers will shift with different content (high-motion vs. talking-head), different resolutions, and different VAAPI driver versions.
- No iso-VMAF search — i.e., *"what bitrate would SVT-AV1 need to hit VMAF 90.79?"* That is the V2 question owned by CR-045 (*"Same Bitrate / Same Quality"*).
- Profile, GOP, B-frame structure are not yet validated apples-to-apples across CPU and GPU paths. CR-029 §2 is Tania's workstream for that. Until CR-029 lands, the within-AV1 same-codec comparison is the cleanest read in this dataset; the across-codec VMAF column should be interpreted with the bitrate-target caveat in mind.

# Read alongside

The canonical *Video — ABR All-Codecs benchmark* finding (Meridian 120 s, n=3, all 🟢) covers the broader picture — H.264 / H.265 / AV1 at the standard ABR ladder, CPU vs GPU energy and speed. This finding is the *zoom-in* on the AV1 hardware-vs-software pair specifically, made possible by VMAF.
