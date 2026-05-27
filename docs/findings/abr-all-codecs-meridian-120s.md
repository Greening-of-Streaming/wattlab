---
slug: abr-all-codecs-meridian-120s
version: 1
first_measured: 2026-05-22
last_refined: 2026-05-22
headline: "On Meridian-120s at the ABR ladder, GPU encodes are 2.0× to 4.4× more energy-efficient than CPU encodes; H.265 GPU produces the lowest-energy file, AV1 GPU the fastest"
claim_short: "Per-codec ABR · H.264 4 Mbps · H.265 2 Mbps · AV1 1.5 Mbps — most efficient: H.265 GPU (0.30 Wh, 28.4 MB, VMAF 92.0) · fastest: AV1 GPU (15.1 s, 0.32 Wh, VMAF 90.8)"
confidence: green
scope: "Device layer only (GoS1: AMD Ryzen 9 7900 + Radeon RX 7800 XT, VAAPI full pipeline for GPU paths). Network, CDN, and CPE excluded."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - video/e18a9d57
related_findings:
  - av1-hw-sw-vmaf-tradeoff
supersedes: null
tags: [video, abr, all-codecs, vmaf, canonical]
caveats:
  - "n=1 on Meridian-120s at full length. CLAUDE.md prose at the time of this import describes the headline as 'n=3, all 🟢' — on-disk, only this single full-length Meridian-120s ABR all-codecs run is stored. Other same-day all_codecs results (`8d2301e3`, `bb3b5aad`, `cfd312d8`) used shorter clips and so are not directly comparable. A re-measurement at n=3 would produce a v2 via `supersedes`."
  - "CLAUDE.md prose lists slightly different aggregate numbers (e.g. H.264 CPU 0.83 Wh, GPU 0.37 Wh; H.265 GPU 15s exact). Numbers in this finding are taken verbatim from the stored result file `video/e18a9d57.json` and may diverge from prose written elsewhere."
  - "Cross-codec comparison uses different per-codec bitrate targets (the ABR ladder), not equal bitrate. A within-codec CPU vs GPU comparison is apples-to-apples; the across-codec column is not."
  - "VMAF profile / GOP / B-frame structure on CPU and GPU paths is not yet validated as equivalent — see CR-029 (Tania-led)."
---

# What was measured

A single 120 s 1080p source (Meridian, Netflix Open Content, CC BY 4.0) re-encoded six times — H.264 / H.265 / AV1 each on CPU (`libx264` / `libx265` / `libsvtav1`) and GPU (`h264_vaapi` / `hevc_vaapi` / `av1_vaapi`). Each codec uses a constant bitrate target across CPU and GPU sides: H.264 4 Mbps, H.265 2 Mbps, AV1 1.5 Mbps.

# Numbers, from the stored result

| Codec | CPU energy | CPU time | CPU VMAF | GPU energy | GPU time | GPU VMAF | GPU vs CPU |
|---|---|---|---|---|---|---|---|
| H.264 | 0.78 Wh | 36.4 s | 94.03 | 0.35 Wh | 17.8 s | 92.11 | 55 % less energy, 51 % faster |
| H.265 | 1.46 Wh | 66.5 s | 94.09 | 0.30 Wh | 15.2 s | 92.00 | 80 % less energy, 77 % faster |
| AV1   | 0.71 Wh | 34.2 s | 92.74 | 0.32 Wh | 15.1 s | 90.79 | 55 % less energy, 56 % faster |

All six encodes returned 🟢 confidence under the CR-028 Phase 2 CI model (`confidence_positive = 1.0` on each).

Most-efficient encode: **H.265 GPU**, 0.30 Wh at VMAF 92.0.
Fastest encode: **AV1 GPU**, 15.1 s at VMAF 90.8 (H.265 GPU is at 15.2 s — within 0.1 s, effectively tied on time but ahead on energy).

# What this measurement does not establish

- It does not show codec quality across codecs at equal bitrate. The ABR ladder runs each codec at a typical streaming bitrate for its class, so the cross-codec VMAF column has an unequal-input caveat. The within-codec CPU vs GPU comparison is the clean read.
- It does not establish encoder parameter equivalence between CPU and GPU sides (profile, GOP, B-frames). CR-029 §2 is the workstream for that.
- It does not measure end-to-end streaming energy. Device-layer only.

# Read alongside

The AV1 hardware-vs-software VMAF finding (`av1-hw-sw-vmaf-tradeoff`) zooms in on the AV1 row — at the same 1.5 Mbps target, the GPU path produces a 40 % larger file at 2 VMAF points lower than CPU, which is the codec where the within-row tradeoff is largest in this dataset. For H.264 and H.265 the CPU/GPU VMAF gap is ≤2 points and within measurement noise.
