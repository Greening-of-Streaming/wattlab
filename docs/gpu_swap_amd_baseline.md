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
| preset | Wh | ΔW wall | dur s | GPU PPT W | GPU peak °C |
|---|---|---|---|---|---|
| H.264 CPU | 0.404 | 39.6 | 36.6 | 4.5 | 39.8 |
| **H.264 GPU** | **0.376** | 69.1 | **19.4** | 48.5 | 46.8 |
| H.265 CPU | 1.281 | 77.2 | 59.6 | 3.8 | 40.5 |
| **H.265 GPU** | **0.315** | 67.0 | **16.8** | 46.4 | 46.7 |
| AV1 CPU | 0.639 | 73.9 | 31.0 | 3.8 | 40.5 |
| **AV1 GPU** | **0.312** | 67.6 | **16.5** | 47.8 | 47.3 |

### bbb_120s (n=10 each)
| preset | Wh | ΔW wall | dur s | GPU PPT W | GPU peak °C |
|---|---|---|---|---|---|
| H.264 CPU | 0.368 | 41.4 | 31.9 | 3.9 | 37.7 |
| **H.264 GPU** | **0.352** | 70.6 | **17.9** | 51.5 | 46.0 |
| H.265 CPU | 1.295 | 78.5 | 59.3 | 3.9 | 39.5 |
| **H.265 GPU** | **0.288** | 72.5 | **14.2** | 51.1 | 46.0 |
| AV1 CPU | 0.963 | 77.6 | 44.0 | 3.9 | 40.1 |
| **AV1 GPU** | **0.284** | 72.4 | **14.0** | 52.2 | 46.3 |

## Headline (what the 5080 has to beat)
- **H.265 / AV1 GPU**: ~0.29–0.32 Wh and ~14–17 s — roughly **4–4.5× less energy and ~4× faster** than the CPU path.
- **H.264 GPU**: ~a wash on energy vs CPU (0.35–0.38 Wh) but ~2× faster.
- GPU's own draw under load: **~46–52 W PPT** (idle ~4 W). Wall ΔW ~67–72 W on the GPU path includes the CPU still decoding/feeding frames.
- All GPU presets flagged 🟢 on all 10 reps.

## Known caveats in this batch
- **No VMAF** — every preset's `vmaf` was empty this run, so this is energy-only; the AV1 hw-vs-sw *quality* tradeoff (`av1-hw-sw-vmaf-tradeoff`) is not measurable from here.
- **AV1 CPU on bbb** had high spread (cv ≈ 40.6%) — one outlier rep; treat that single cell as soft.
- LLM panel (`ce0110ae`) used the "capital of France" prompt; Mistral-Nemo and Phi-4 emitted only 2 tokens, so their mWh/token are denominator artifacts, not efficiency readings (not part of the GPU baseline, noted for completeness).
