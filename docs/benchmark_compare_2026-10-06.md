# Full-benchmark comparison — GoS1 (Sep 5 vs Oct 6) and GoS2 (Oct 6)

**Status:** internal check, 2026-10-06. Not for publication (Tania reviews first).

> **⚠ Correction (same night, 22:35):** every all-codecs step's **first** pass (x264 CPU) took its baseline
> while the previous step was still winding down. Benchmark steps bypassed the pre-job idle guard (fixed in
> `003ec0f`). x264 CPU baselines read GoS1 94–111 W vs 78–92 W for the other passes, and GoS2 11–30 W vs ~2 W.
> **All x264 CPU rows below understate ΔE, on both machines, Sep 5 included**, and the "x264 −41/−48 %" GoS2-vs-GoS1
> line and the "x264 +6–7 % since Sep 5" line are **not valid**. The other passes (x265, SVT-AV1, all hardware)
> were preceded by the in-job idle wait and stand. A video-only rerun with the fix ran overnight, see § 4. Script + raw tables:
`/srv/data/owl/campaign_2026-10-06_gos2_autonomy/compare.{py,_out.txt}`.

| Run | Benchmark | Config | Duration |
|---|---|---|---|
| GoS1, 2026-09-05 (night) | `591d63c9` | calibration n=20 · video 10 reps × {meridian, bbb} · LLM · RAG · image | 5 h 11 min |
| GoS1, 2026-10-06 (afternoon/evening) | `1eb2b633` | identical | 5 h 11 min |
| GoS2, 2026-10-06 | `9c91df3a` (on GoS2) | calibration n=5 · video 3 reps × same 2 sources · LLM · image (no RAG corpus) | 1 h 29 min |

## 1. Did the CR-085 work change GoS1? — No

All 12 video rows (2 sources × 3 codecs × CPU/GPU), every run 🟢, VMAF identical to two decimals:

| | Oct 6 vs Sep 5 | Welch t |
|---|---|---|
| NVENC (H.264 / H.265 / AV1, both sources) | −2.7 % … +1.6 % | \|t\| ≤ 1.7 |
| x265, SVT-AV1 (CPU) | +0.1 % … +2.0 % | \|t\| ≤ 1.7 |
| **x264 (CPU)** | **+6.3 % (meridian), +7.1 % (bbb)** | **2.06, 1.87** |

Only x264 drifts, and only borderline (t ≈ 2, n = 10 + 10). Nothing in this week's code touches GoS1's encode
commands, so the likely cause is time of day or ambient temperature: Sep 5 ran 02:00–07:00, today 16:40–21:50.
x264 is also the noisiest encoder on both machines. Treat GoS1 as unchanged, with x264 CPU ±7 % across days.

## 2. GoS2 (M6) vs GoS1 (Ryzen 9 7900 + RTX 5080), Oct 6 — marginal ΔE per encode

| | meridian | bbb | Note |
|---|---|---|---|
| x264 CPU | −41 % | −48 % | GoS2 meridian x264 is noisy (0.30 ± 0.08 Wh, n = 3) |
| x265 CPU | −39 % | −42 % | |
| SVT-AV1 CPU | −39 % | −44 % | same VMAF |
| H.264 hardware (VT VBR vs NVENC preset) | −13 % | −15 % | VMAF 88.6 vs 88.7 · 91.1 vs 91.4 |
| H.265 hardware | −18 % | −17 % | VMAF **88.0 vs 84.5** · 88.7 vs 87.8 — rate control differs (VT VBR vs OWL's NVENC preset) |
| AV1 hardware | — | — | the M6 has no AV1 encoder; recorded as unavailable |

Consistent with the GoS2 report (`docs/gos2_m6_report_2026-10.md` §1, §0): CPU encodes ~40–48 % less energy
above idle, hardware ~13–18 %. Whole-machine ratios are larger again because of the 1.3 W vs ~78 W idle.

## 3. LLM / RAG / image panels — not comparable at this n

The compare panels are **one cold run per model** (n = 1), mostly 🟡/🔴. Values swing several-fold between runs
on the same machine (GoS1 mistral-nemo 8.3 → 0.9 mWh/token, phi4 8.95 → 1.3), and GoS2's qwen3:1.7b came out
negative (ΔW below noise). Use them as smoke tests that the panels run, never as figures. The dedicated n = 3
runs in the GoS2 report are the reference for AI workloads.
