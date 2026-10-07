# Full-benchmark comparison — GoS1 (Sep 5 vs Oct 6) and GoS2 (Oct 6)

**Status:** internal check, 2026-10-06/07. Not for publication (Tania reviews first). Sections: §1–3 the first
full benchmarks (§1 and §2's x264 rows superseded); **§4 the clean video rerun on both nodes (current figures)**;
**§5 the AI panels on both nodes with the corrected methods (current figures)**.

> **⚠ Correction (same night, 22:35):** every all-codecs step's **first** pass (x264 CPU) took its baseline
> while the previous step was still winding down. Benchmark steps bypassed the pre-job idle guard (fixed in
> `003ec0f`). x264 CPU baselines read GoS1 94–111 W vs 78–92 W for the other passes, and GoS2 11–30 W vs ~2 W.
> **All x264 CPU rows below understate ΔE, on both machines, Sep 5 included**, and the "x264 −41/−48 %" GoS2-vs-GoS1
> line and the "x264 +6–7 % since Sep 5" line are **not valid**. The other passes (x265, SVT-AV1, all hardware)
> were preceded by the in-job idle wait, but see § 4: the bad first baseline also loosened the next in-job wait,
> so x265 CPU (−4–6 %) and some hardware rows (−1–4 %) were also understated. Corrected figures are in § 4. Script + raw tables:
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

## 4. Clean rerun, 2026-10-06/07 overnight (after the fix)

Video-only benchmarks, 10 reps × {meridian, bbb} on **both** nodes, with the pre-step idle guard (`003ec0f`) and
GoS2's idle criteria tightened to 0.5 W / 6 polls (was GoS1's 3 W / 3, which accepted 2–3× GoS2's idle).
GoS1 `44549e35`, GoS2 `bb05eda7`. Script and full table:
`/srv/data/owl/campaign_2026-10-07_bench_rerun/{analyse.py,analyse_out.txt}`.

**Baselines are now clean**: x264 CPU baseline GoS1 80 W (was 102–106), GoS2 1.8 W (was 18–28).

| ΔE Wh, mean ± sd (n=10) | GoS1 meridian | GoS1 bbb | GoS2 meridian | GoS2 bbb | GoS2 vs GoS1 |
|---|---|---|---|---|---|
| x264 CPU | **0.736 ± 0.012** | **0.657 ± 0.007** | **0.509 ± 0.011** | **0.411 ± 0.005** | −31 % / −37 % |
| x265 CPU | 1.241 ± 0.020 | 1.252 ± 0.008 | 0.735 ± 0.006 | 0.695 ± 0.004 | −41 % / −45 % |
| SVT-AV1 CPU | 0.632 ± 0.007 | 0.806 ± 0.011 | 0.383 ± 0.002 | 0.449 ± 0.002 | −39 % / −44 % |
| H.264 hardware | 0.199 ± 0.003 | 0.218 ± 0.012 | 0.180 ± 0.002 | 0.185 ± 0.002 | −9 % / −15 % |
| H.265 hardware | 0.225 ± 0.003 | 0.234 ± 0.004 | 0.185 ± 0.002 | 0.191 ± 0.003 | −18 % / −19 % |
| AV1 hardware | 0.213 ± 0.005 | 0.220 ± 0.002 | — (no AV1 encoder) | — | — |

(GoS1 hardware = OWL's NVENC preset; GoS2 hardware = Apple media engine in VBR. Rate control differs, so the
hardware rows are not the matched-VBR comparison: that is the report's §1, re-checked separately.)

What changed vs the contaminated runs (Welch t, rerun vs Oct 6):
- **x264 CPU** +44–46 % (GoS1), +70–73 % (GoS2); t = 4.6–21. The old figures were wrong.
- **x265 CPU** GoS1 +4–6 % (t 3.8–6.6): cascade from the bad first baseline. AV1 CPU unchanged (+0.4–0.6 %).
- **Hardware rows** GoS1 −1.5 … +3.7 %; GoS2 +0.7 … +3.6 % (the loose 3 W tolerance).
- Run-to-run spread collapsed: x264 sd 6–9 % → **1–2 %**. The "x264 is noisy" impression came from the
  contamination, not from the encoder.

**GoS2 AI re-check** under the tight idle criteria (n=3, clean baselines 1.3–1.65 W): qwen3:4b Ollama
0.1536 ± 0.0043 mWh/token, MLX 0.1044 ± 0.0010, SDXL-Turbo session 0.0092 ± 0.0001 Wh/img, all 🟢, **unchanged**
from the earlier figures. The AI results stand.

**Not rerun (method, owner's call):** the benchmark's LLM panel (prompt gives 1.7–6 s windows, 2-token answers)
and image panel (2.7–3.7 s windows on GoS1, model load in the window). Proposal: run the LLM panel on task T2,
and the image panel as the warm-model session the Lab buttons already use.

## 5. AI panels on both nodes, corrected methods (2026-10-07)

Panels-only benchmarks after `8536d55`: **LLM** = task T2 (~300-token answer, graded on mentioning AV1) instead
of the one-word factoid; **image** = a warm-model session per model (load + warm-up outside the window, 30 s
settle, ≥30 s of generation) instead of one-shot runs with model load in a 3 s window. GoS1 `8839d3ef`, GoS2
`c5a8e18b`, run in parallel 19:22–19:32 (separate meters). **Every row 🟢**, every LLM answer correct. These are
**single panel runs (n = 1 per model)**: indicative only, below the n = 3 bar for anything that leaves the room.
The n = 3 figures are in `docs/gos2_m6_report_2026-10.md`.

| LLM, task T2 (marginal mWh/token) | GoS1 (RTX 5080) | GoS2 (M6) | GoS2 vs GoS1 |
|---|---|---|---|
| qwen3:1.7b | 0.126 (9 s) | 0.069 (28 s) | −46 % |
| qwen3:4b | 0.315 (22 s) | 0.156 (83 s) | −50 % |
| qwen3:8b | 0.498 (19 s) | 0.253 (103 s) | −49 % |
| mistral-nemo:12b · phi4 · gpt-oss:20b | 0.531 · 0.765 · 0.411 | — (not on GoS2) | — |

| Image, warm session (Wh/image) | GoS1 | GoS2 | GoS2 vs GoS1 |
|---|---|---|---|
| SD-Turbo | 0.0247 | 0.0172 | −30 % |
| SDXL-Turbo | 0.0130 | 0.0087 | −33 % |
| SANA-Sprint | 0.0164 | 0.0144 | −12 % |
| SANA-600m | 0.0167 | — (not on GoS2) | — |
| SDXL-Lightning | not measured: its loader is not supported by the session runner yet | — | — |

Caveats: (1) **GoS1 ran Ollama 0.20.2**, upgraded to 0.35.1 (GoS2's version) at 19:44, after this run.
Re-measure GoS1's LLM row before any cross-machine LLM claim. (2) Each machine runs at its own speed: GoS1 is
3–5× faster on LLM and 2–4× on images; the energy figures are marginal (above each machine's own idle). (3) The
image figures sit in the same range as the report's n = 3 session results: SDXL-Turbo GoS2 0.0092 there vs 0.0087
here.
