# AMD RX 7800 XT — pre-swap energy baseline

**Captured:** 2026-05-29, overnight orchestrated benchmark
**Purpose:** Frozen reference for the CR-060 GPU swap (RX 7800 XT → NVIDIA RTX 5080).
After the swap + reboot, re-run the same in-app benchmark (CR-061) and compare the
NVENC GPU rows against the VAAPI GPU rows below.

## Provenance
- Benchmark orchestrator run: `results/benchmark/2026-05-29_e29ccef7.json` (24 steps, 0 errors, 6h31m wall, 00:06→06:37).
- OWL version at capture: `0.8.6` / sha `88a2696` (dirty).
- ffmpeg: ffmpeg-master at `/usr/local/bin/ffmpeg-master`; Mesa VA pinned (CR-022).
- GPU path = full VAAPI pipeline (hw decode + `scale_vaapi` + `*_vaapi` encode, `/dev/dri/renderD128`).
- CPU path = libx264 / libx265 / libsvtav1, 24 cores, `nice -n -5`.
- Rate control: ABR (constant bitrate target) on all presets — H.264 4000 kbps, H.265 2000 kbps, AV1 1500 kbps. CPU and GPU receive identical tasks per codec.
- n = 10 reps per (codec, path, source). Sources: `meridian_120s`, `bbb_120s` (both 120 s, 1080p output).
- 20 video result files: `840e19f7 ec47714b 49fd9f3c 25ec1757 457f84c4 3327cadf be0558cd c2201908 d44754a0 b2253b8b 4afecb34 0d648007 261036bf 8cda7603 53533583 84d9fde2 a98f78c6 927561fc a57cf59d af5df7e1` (under `results/video/2026-05-29_*.json`).

## Calibration context (READ BEFORE COMPARING)
Variance calibration for this batch (`results/variance/history.jsonl`, ts 03:28:53):

| metric | value |
|---|---|
| `variance_pct` | **3.07%** |
| `variance_idle_pct` | 4.06% |
| `variance_idle_drift_pct` | 3.92% |
| `variance_cpu_pct` | 2.86% |
| `variance_gpu_pct` | 2.30% |
| `w_base_mean` | 59.09 W |
| runs | 30/30 |

This is the **warm-ambient regime**, not OWL's clean 1.29% (S25). Room temperature swings
calibration 2–6×. The post-swap re-run should be calibrated under comparable ambient, or the
A/B confidence floor will differ and muddy the comparison. Log ambient at re-run time.

## Energy baseline — AMD RX 7800 XT (VAAPI)

Wh = wall energy for the 120 s encode. ΔW_wall = mean wall delta. GPU_PPT = the GPU's own
reported power during the task (the most swap-relevant figure — NVENC will move this directly).

### meridian_120s (n=10 each)
| preset | Wh | ΔW wall | dur s | GPU PPT W | GPU peak °C | VMAF |
|---|---|---|---|---|---|---|
| H.264 CPU | 0.404 | 39.6 | 36.6 | 4.5 | 39.8 | 93.98 |
| **H.264 GPU** | **0.376** | 69.1 | **19.4** | 48.5 | 46.8 | 92.11 |
| H.265 CPU | 1.281 | 77.2 | 59.6 | 3.8 | 40.5 | 93.94 |
| **H.265 GPU** | **0.315** | 67.0 | **16.8** | 46.4 | 46.7 | 92.00 |
| AV1 CPU | 0.639 | 73.9 | 31.0 | 3.8 | 40.5 | 92.43 |
| **AV1 GPU** | **0.312** | 67.6 | **16.5** | 47.8 | 47.3 | 90.80 |

### bbb_120s (n=10 each)
| preset | Wh | ΔW wall | dur s | GPU PPT W | GPU peak °C | VMAF |
|---|---|---|---|---|---|---|
| H.264 CPU | 0.368 | 41.4 | 31.9 | 3.9 | 37.7 | 91.73 |
| **H.264 GPU** | **0.352** | 70.6 | **17.9** | 51.5 | 46.0 | 88.04 |
| H.265 CPU | 1.295 | 78.5 | 59.3 | 3.9 | 39.5 | 89.42 |
| **H.265 GPU** | **0.288** | 72.5 | **14.2** | 51.1 | 46.0 | 84.41 |
| AV1 CPU | 0.963 | 77.6 | 44.0 | 3.9 | 40.1 | 90.74 |
| **AV1 GPU** | **0.284** | 72.4 | **14.0** | 52.2 | 46.3 | 81.49 |

## Headline (what the 5080 has to beat)
- **H.265 / AV1 GPU**: ~0.29–0.32 Wh and ~14–17 s — roughly **4–4.5× less energy and ~4× faster** than the CPU path.
- **H.264 GPU**: ~a wash on energy vs CPU (0.35–0.38 Wh) but ~2× faster.
- GPU's own draw under load: **~46–52 W PPT** (idle ~4 W). Wall ΔW ~67–72 W on the GPU path includes the CPU still decoding/feeding frames.
- All GPU presets flagged 🟢 on all 10 reps.

## Known caveats in this batch
- **VMAF column corrected (S36, 2026-05-29).** An earlier draft of this doc claimed "no VMAF this run" — that was **wrong**: all 120 cells (3 codecs × CPU/GPU × 2 sources × n=10) have VMAF populated, now in the tables above. The hw-vs-sw quality tradeoff (`av1-hw-sw-vmaf-tradeoff`) *is* measurable here — notably **AV1 GPU on bbb drops to 81.49 vs 90.74 CPU (−9.3)**, the largest CPU↔GPU quality gap in the batch (VAAPI AV1 struggling on hard content at 1500 kbps).
- **AV1 CPU on bbb** had high spread (cv ≈ 40.6%) — one outlier rep; treat that single cell as soft.
- LLM panel (`ce0110ae`) used the "capital of France" prompt; Mistral-Nemo and Phi-4 emitted only 2 tokens, so their mWh/token are denominator artifacts, not efficiency readings (not part of the GPU baseline, noted for completeness).

---

## Post-swap A/B — RTX 5080 (NVENC) vs RX 7800 XT (VAAPI)

**Captured:** full n=10 benchmark `results/benchmark/2026-05-29_f56dfa77.json` (24 steps, overnight 23:27→03:52, 2026-05-30). Same scale + sources as the AMD baseline above. A quick n=2 pre-run (`46772ea7`) gave the same directional read and is superseded by this.

### GPU transcode — energy / time / quality (n=10 each)
Format: AMD Wh/s/VMAF → Nvidia Wh/s/VMAF (Δenergy, Δtime, ΔVMAF).

| GPU preset | Meridian (natural) | BBB (animated) |
|---|---|---|
| H.264 | 0.376/19.4/92.1 → 0.218/12.3/93.3 (**−42 %**, −37 %, +1.2) | 0.352/17.9/88.0 → 0.230/12.7/89.6 (−35 %, −29 %, +1.6) |
| H.265 | 0.315/16.8/92.0 → 0.247/14.1/90.0 (−22 %, −16 %, **−2.0**) | 0.288/14.2/84.4 → 0.254/14.1/85.2 (−12 %, ~0 %, +0.8) |
| AV1 | 0.312/16.5/90.8 → 0.233/12.8/92.7 (−25 %, −22 %, +1.9) | 0.284/14.0/81.5 → 0.241/12.8/85.8 (−15 %, −9 %, **+4.3**) |

- **NVENC beats VAAPI on energy + time across all 6 cells**, quality equal-or-better in 5 of 6 (H.265 the only give-up, −2 VMAF @ 2000 kbps).
- **AV1 is the decisive win** — lower energy, faster, *and* higher quality, most dramatically on animated content (**+4.3 VMAF on BBB**, where VAAPI AV1 had collapsed to 81.5). The 7800 XT's hardware-AV1 quality penalty is essentially gone on the 5080.
- **CPU paths match the AMD baseline** (H.264-CPU 0.40 vs 0.40, H.265-CPU 1.24 vs 1.28, AV1-CPU 0.62 vs 0.64 Wh on Meridian) — same encoder + silicon → the bench is sound. Energy CV 1.8–4.5 % on GPU paths.

### Idle cost + crossover (the counterweight)
- **Idle rose ~+20 W at the wall** (~57–59 W AMD → ~79 W 5080) — intrinsic to the bigger Blackwell card, not a fault (see JOURNAL S36). Vendor-neutral wall figure; the GPU-sensor PPT jump (~48→~80 W under load) is partly the AMD-core-domain-vs-Nvidia-board-power mismatch, so read wall ΔW (~64 W both cards), not PPT.
- **Total-energy model** `E = W_idle·T + Σ ΔE_encode` → the +20 W idle = **480 Wh/day** the per-encode NVENC savings must repay. Break-even GPU **duty cycle** (120 s clips, Meridian):

| Codec (GPU) | Saving/encode | Break-even duty | Break-even volume |
|---|---|---|---|
| H.264 | 0.158 Wh | **~43 %** | ~3,000 clips/day |
| AV1 | 0.079 Wh | **~90 %** | ~6,100 clips/day |
| H.265 | 0.068 Wh | **never** | 0.068 Wh × max 6,128/day = 417 Wh < 480 Wh |

- **Conclusion:** the swap is energy-positive only for **H.264-heavy, near-saturated** duty cycles; for H.265 the idle penalty is never repaid by transcode alone. Treat the 5080 as a **capability / quality / speed upgrade** (CUDA tooling, AV1 quality, ~2–4× faster encodes), not a same-workload energy win.
