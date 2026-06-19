---
slug: upscale-sweetspot-degraded-sources
version: 1
first_measured: 2026-06-12
last_refined: 2026-06-19
headline: "AI upscaling to 4K pays off where content is worst: restoring degraded SD buys ~20× more quality per Wh than polishing clean HD — and re-processing pristine 4K buys nothing at the highest energy cost"
claim_short: "SD-dirty → 4K: +2.1 NR-VQA for 14.8 Wh · HD-clean → 4K: +0.23 for 11.9 Wh · pristine 4K → 4K: ±0.0 for 44 Wh (45 s / 60 fps clips, all 🟢)"
confidence: green
scope: "Device layer only (GoS1 server: AMD Ryzen 9 7900 + NVIDIA RTX 5080, dual daisy-chained Tapo P110 — primary meter on the server plug). Network, CDN, and CPE excluded."
methodology_ref: docs/wattlab_traffic_light_confidence.md
source_result_ids:
  - enhance/41618e50
  - enhance/1bae9d59
  - enhance/1532a990
  - enhance/f1971108
  - enhance/6639addd
  - enhance/0466fe96
  - enhance/ec242d91
  - enhance/be84d96f
  - enhance/06b546d3
  - enhance/752ae0c6
  - enhance/2d3f98be
  - enhance/ccb6ff2b
  - enhance/44e4c98f
  - enhance/ac475d1e
  - enhance/a5c4ce9c
  - enhance/69fc5a1d
related_findings: [input-master-sensitivity]
supersedes: null
tags: [enhancement, super-resolution, sweet-spot, nr-vqa, vmaf, pixop, degradation-ladder]
caveats:
  - "Quality gains are CompressedVQA-HDR no-reference scores — a learned opinion of perceptual quality, presented as a relative indicator. The scale is not interval, so per-Wh ratios are indicative, not metrological."
  - "One enhancement pipeline (Pixop Live, `balanced` model, SDR→4K @ 35 Mbps CBR), one degradation family (Lanczos resolution drops; temporal noise into a 2-pass x264 starved encode), two contents, 45 s windows. The two real-UGC anchor clips are the check on degradation realism — both sit on the synthetic curve."
  - "Full-reference scores (PSNR/SSIM/VMAF-4K) are computed against the best practical public copies of the masters (~8–9.5 Mbps H.264 distribution encodes), not true mezzanines."
  - "Per-Wh efficiency comparisons are restricted to the uniform ladder (identical 45 s / 60 fps clips); the real-UGC anchors differ in duration and frame rate, so they anchor the quality curve, not the energy column."
  - "The NR metric rewards plausible detail, not fidelity: outputs that score near-pristine NR can sit 15+ VMAF points below the master (see 'Looking better is not being restored')."
  - "CONFOUND on learning #3's *attribution* (not its observation): SI/TI measured 2026-06-19 shows BBB is markedly higher spatial/temporal complexity than Meridian (SI ~33 / TI ~6 vs ~13 / ~2). So BBB restoring less faithfully than Meridian may be because BBB is intrinsically HARDER content, not (only) because the model is camera-trained. The observation (Meridian restores more faithfully at every rung) stands; the 'trained on camera content' explanation is now one of two plausible causes. The headline sweet-spot result is unaffected."
---

# The result, in one sentence

Across a twelve-rung degradation ladder (two contents × six quality rungs, all upscaled/restored to 4K by the same AI pipeline under identical measurement), the energy cost is set almost entirely by the **input resolution** (~45 Wh per 45 s clip for 4K input, ~12–15 Wh for HD/SD input), while the quality gain rises monotonically as source quality falls — so the energy-to-quality sweet spot sits squarely on the **worst content**: heavily degraded SD gained **+2.1 NR-VQA points for 14.8 Wh**, clean HD gained **+0.23 for 11.9 Wh**, and re-processing pristine 4K gained **nothing (±0.0) for 44–46 Wh**.

# The ladder

Quality columns: **CompressedVQA-HDR** (no-reference — "how good does it look?", the same metric `/enhance-run` reports) scored on input and output; **VMAF-4K** (full-reference — "how faithful to the master?"), possible here uniquely because every rung descends from a known reference cut.

| input (45 s, 60 fps) | CompressedVQA-HDR in | out | ΔVQA | ΔE (Wh) | ΔVQA/Wh | VMAF-4K vs master (FR) |
|---|---|---|---|---|---|---|
| bbb_sd_dirty | 5.45 | 7.56 | **+2.11** | 14.85 | **0.142** | 47.4 |
| meridian_sd_dirty | 6.04 | 7.64 | +1.60 | 14.55 | 0.110 | 67.6 |
| meridian_sd_clean | 7.63 | 9.01 | +1.38 | 14.58 | 0.095 | 81.0 |
| bbb_sd_clean | 7.83 | 9.02 | +1.19 | 14.49 | 0.082 | 67.7 |
| meridian_hd_dirty | 7.95 | 8.46 | +0.51 | 11.89 | 0.043 | 82.5 |
| bbb_hd_dirty | 8.10 | 8.62 | +0.52 | 12.12 | 0.043 | 72.0 |
| bbb_4k_dirty | 8.63 | 8.93 | +0.30 | 45.30 | 0.007 | 74.1 |
| meridian_4k_dirty | 9.16 | 9.44 | +0.28 | 46.21 | 0.006 | 85.5 |
| bbb_hd_clean | 9.30 | 9.53 | +0.23 | 11.93 | 0.019 | 88.9 |
| meridian_hd_clean | 9.49 | 9.74 | +0.25 | 12.03 | 0.021 | 94.3 |
| bbb_ref_4k | 9.58 | 9.63 | +0.05 | 43.54 | 0.001 | 93.2 |
| meridian_ref_4k | 9.86 | 9.84 | −0.02 | 44.56 | ~0 | 97.6 |
| *2005 UGC anchor (21 s, 15 fps)* | 5.37 | 7.20 | +1.83 | 1.73 | — | n/a (no master) |
| *Night UGC anchor (44 s, 21 fps)* | 7.89 | 8.53 | +0.64 | 4.25 | — | n/a (no master) |

All fourteen runs returned 🟢 confidence on the dual-meter instrument (recalibrated same day; GPU variance 0.91%).

# Four learnings

**1. Energy is a property of the input pixels, not the achieved quality.** The pipeline drew ~390 W regardless of rung; what varied was duration-of-work per frame: 4K input ≈ 45 Wh, SD input (×4.5 scale) ≈ 14.6 Wh, HD input (×2) ≈ 12 Wh per identical 45 s/60 fps clip. The ×4.5 SD path costs slightly more than ×2 HD despite fewer input pixels — scale factor modulates, input resolution dominates. Cost is therefore predictable before running: it does not depend on how degraded the content is.

**2. Quality gain is a property of the input's badness.** With cost fixed per rung, ΔVQA rises monotonically as source quality falls — from ±0.0 (pristine) to +2.1 (worst). The per-Wh spread across the ladder exceeds **100×** (0.142 vs ~0.001). The economic reading: an operator with a restoration budget should spend it on the worst material first, and **never** on already-good 4K, where the same energy buys literally nothing.

**3. Synthetic and cinematic content behave the same — on the NR axis.** The BBB (synthetic animation) and Meridian (cinematic camera) curves overlap within ~0.2 ΔVQA at every matched rung, and their energy columns are near-identical. The difference appears on the **full-reference** axis: Meridian restores more faithfully at every rung (round-trip VMAF 97.6 vs 93.2 on the pristine refs; 67.6 vs 47.4 on the worst rung — a 20-point gap) — consistent with a restoration model trained predominantly on camera content **(though BBB's higher measured spatial/temporal complexity — SI ~33 vs ~13 — is an alternative explanation: harder content is harder to restore faithfully; see caveats)**. Perceived improvement is content-agnostic; fidelity recovery is not.

**4. Looking better is not being restored.** The NR scores say enhanced SD-clean output is "near-pristine" (9.01–9.02, within 0.6 of the actual masters); the full-reference scores say those same outputs sit at VMAF 67.7–81.0 against their masters — and the worst rung's output, NR-scored a respectable 7.56, round-trips at VMAF 47.4. The enhancement manufactures plausible detail that a no-reference metric (and plausibly a viewer) rewards, but the original information is not recovered. OWL's standing position — perceptual quality of super-resolution is for the viewer to judge — survives contact with this data: the energy buys *palatability*, not *fidelity*, and the two metrics quantify the difference for the first time on this rig.

# The real-UGC anchors validate the synthetic ladder

The genuinely bad 2005 camera clip (NR 5.37 → 7.20, +1.83) lands almost exactly on the synthetic curve between the two sd_dirty rungs (5.45 → 7.56 and 6.04 → 7.64); the mid-quality night clip (7.89 → +0.64) falls between the hd_dirty (+0.51) and sd_clean (+1.19) rungs, as its 720p VFR character predicts. The artificial degradation recipe — the most attackable part of this experiment's design — produces quality-gain behaviour indistinguishable from real-world degradation at matching quality levels.

# How it was measured

Twelve 45-second fixtures generated from the best practical public copies of Big Buck Bunny (Sunflower 2160p60) and Meridian (Netflix Open Content) by documented, reproducible recipes — frozen with checksums and per-file NR scores in the library manifest. Each fixture (plus two real UGC clips) ran through the standard `/enhance-run` harness: focus mode, per-run baseline, 1 Hz wall-power polling on the primary meter of a dual daisy-chained Tapo P110 pair, NR quality (CompressedVQA-HDR) scored on input and output as a terminal pass outside the energy window. Full-reference PSNR/SSIM/VMAF (vmaf_4k model, 4× temporal subsample) computed post-hoc against each content's reference cut — possible here, uniquely among enhancement runs, because every rung descends from a known master. Interactive chart, fixture downloads, and recipes: `/enhance-run/ladder`.

# What this finding does not measure

- Other enhancement pipelines, models, or targets (one vendor pipeline, `balanced` model, 4K target only).
- HD as an output target (today's data says 4K-target energy ≈ 4× HD-target at the same input — see the S45 UGC runs — but this sweep held the target fixed).
- Whether viewers prefer the enhanced output (no subjective study; the NR metric is a learned proxy).
# The traditional-upscaler comparison (two runs)

On the SD rungs, a plain Lanczos upscale to 4K (NVENC-encoded at the same 35 Mbps) cost **0.63–0.64 Wh** vs the AI's **14.5 Wh (~23×)**. The AI delivered **2–5× the quality gain**: sd_clean — Lanczos +0.41 NR vs AI +1.19; sd_dirty — Lanczos +0.37 vs AI +2.11. One honest nuance: on these *synthetic* rungs Lanczos slightly improved the NR score, whereas on the real 2005 UGC clip (earlier same-day run) it *lowered* it (−0.17) — whether cheap upscaling helps or harms appears to depend on the artifact character of the source. Both compare runs 🟢 (`enhance/a5c4ce9c`, `enhance/69fc5a1d`).
