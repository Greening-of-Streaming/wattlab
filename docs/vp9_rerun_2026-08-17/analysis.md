### Encode — GoS1, 1080p, one-pass ABR, 30 s trims, dual meter, all rows 🟢

108 rows measured; 2 excluded for elevated baseline (w_base > median 80.1 + 10 W): meridian_120s vp9/slow 2500k rep1 (w_base 98.7 W); meridian_120s x264/slow 2500k rep2 (w_base 95.0 W).


**bbb_120s** — Wh per minute of output (marginal | attributional), n, VMAF v1, achieved kb/s, encode s per minute of video

| encoder | point | target | n | Wh/min | ±sd | attrib. | VMAF | ach. kb/s | s/min |
|---|---|---|---|---|---|---|---|---|---|
| libx264 | medium | 2500k | 3 | **0.302** | 0.003 | 0.65 | 89.7 | 2783 | 16 |
| libx264 | medium | 5000k | 3 | **0.330** | 0.005 | 0.70 | 94.0 | 5675 | 17 |
| libx264 | slow | 2500k | 3 | **0.375** | 0.004 | 0.80 | 89.8 | 2782 | 19 |
| libx264 | slow | 5000k | 3 | **0.427** | 0.003 | 0.92 | 94.2 | 5667 | 22 |
| libx265 | medium | 2500k | 3 | **0.618** | 0.008 | 1.33 | 91.5 | 2867 | 32 |
| libx265 | medium | 5000k | 3 | **0.718** | 0.012 | 1.53 | 94.9 | 5924 | 37 |
| libx265 | slow | 2500k | 3 | **1.328** | 0.021 | 2.88 | 92.7 | 2851 | 69 |
| libx265 | slow | 5000k | 3 | **1.591** | 0.034 | 3.40 | 95.7 | 5903 | 82 |
| SVT-AV1 | preset 10 (default) | 2500k | 3 | **0.482** | 0.011 | 1.06 | 94.6 | 2433 | 26 |
| SVT-AV1 | preset 10 (default) | 5000k | 3 | **0.462** | 0.010 | 1.03 | 96.6 | 4396 | 25 |
| SVT-AV1 | preset 3 | 2500k | 3 | **3.744** | 0.186 | 7.87 | 95.4 | 2291 | 186 |
| SVT-AV1 | preset 3 | 5000k | 3 | **3.839** | 0.066 | 8.06 | 97.1 | 4108 | 191 |
| libvpx-VP9 | cpu-used 4 | 2500k | 3 | **1.368** | 0.034 | 3.00 | 93.8 | 3661 | 72 |
| libvpx-VP9 | cpu-used 4 | 5000k | 3 | **1.507** | 0.012 | 3.20 | 96.2 | 6393 | 77 |
| libvpx-VP9 | cpu-used 2 | 2500k | 3 | **1.761** | 0.021 | 3.79 | 94.0 | 3594 | 91 |
| libvpx-VP9 | cpu-used 2 | 5000k | 3 | **1.962** | 0.017 | 4.18 | 96.4 | 6325 | 100 |
| libvpx-VP9 | cpu-used 1 | 2500k | 3 | **2.295** | 0.028 | 4.87 | 94.2 | 3620 | 117 |
| libvpx-VP9 | cpu-used 1 | 5000k | 3 | **2.518** | 0.033 | 5.35 | 96.6 | 6411 | 128 |

**meridian_120s** — Wh per minute of output (marginal | attributional), n, VMAF v1, achieved kb/s, encode s per minute of video

| encoder | point | target | n | Wh/min | ±sd | attrib. | VMAF | ach. kb/s | s/min |
|---|---|---|---|---|---|---|---|---|---|
| libx264 | medium | 2500k | 3 | **0.343** | 0.004 | 0.75 | 88.9 | 2433 | 18 |
| libx264 | medium | 5000k | 3 | **0.389** | 0.005 | 0.87 | 93.3 | 4890 | 22 |
| libx264 | slow | 2500k | 2 | **0.407** | 0.005 | 0.91 | 90.2 | 2439 | 22 |
| libx264 | slow | 5000k | 3 | **0.550** | 0.009 | 1.19 | 94.2 | 4898 | 29 |
| libx265 | medium | 2500k | 3 | **0.663** | 0.002 | 1.44 | 90.0 | 2464 | 35 |
| libx265 | medium | 5000k | 3 | **0.765** | 0.002 | 1.71 | 92.8 | 4926 | 42 |
| libx265 | slow | 2500k | 3 | **1.685** | 0.019 | 3.62 | 90.5 | 2463 | 87 |
| libx265 | slow | 5000k | 3 | **2.097** | 0.029 | 4.47 | 93.3 | 4924 | 106 |
| SVT-AV1 | preset 10 (default) | 2500k | 3 | **0.358** | 0.007 | 0.80 | 88.3 | 1690 | 20 |
| SVT-AV1 | preset 10 (default) | 5000k | 3 | **0.378** | 0.003 | 0.84 | 90.6 | 3397 | 21 |
| SVT-AV1 | preset 3 | 2500k | 3 | **4.704** | 0.147 | 9.93 | 89.0 | 1715 | 235 |
| SVT-AV1 | preset 3 | 5000k | 3 | **5.610** | 0.119 | 11.79 | 91.5 | 3473 | 278 |
| libvpx-VP9 | cpu-used 4 | 2500k | 3 | **1.667** | 0.029 | 3.64 | 87.5 | 2780 | 87 |
| libvpx-VP9 | cpu-used 4 | 5000k | 3 | **1.956** | 0.011 | 4.19 | 90.0 | 5439 | 101 |
| libvpx-VP9 | cpu-used 2 | 2500k | 2 | **2.191** | 0.010 | 4.67 | 87.7 | 2796 | 112 |
| libvpx-VP9 | cpu-used 2 | 5000k | 3 | **2.577** | 0.013 | 5.47 | 90.7 | 5383 | 131 |
| libvpx-VP9 | cpu-used 1 | 2500k | 3 | **2.435** | 0.035 | 5.25 | 88.2 | 2822 | 126 |
| libvpx-VP9 | cpu-used 1 | 5000k | 3 | **2.945** | 0.014 | 6.30 | 91.6 | 5407 | 150 |

**Everything-at-default (x264 medium · x265 medium · SVT-AV1 p10 · VP9 cpu-used 4)** — energy per minute relative to x264 (same clip, same target), mean of the two targets

| clip | x264 | x265 | SVT-AV1 | VP9 |
|---|---|---|---|---|
| bbb_120s | 1.0× | 2.1× | 1.5× | 4.6× |
| meridian_120s | 1.0× | 2.0× | 1.0× | 4.9× |

**Jan Ozer's everything-slow set (x264 slow · x265 slow · SVT-AV1 p3 · VP9 cpu-used 2)** — energy per minute relative to x264 (same clip, same target), mean of the two targets

| clip | x264 | x265 | SVT-AV1 | VP9 |
|---|---|---|---|---|
| bbb_120s | 1.0× | 3.6× | 9.5× | 4.6× |
| meridian_120s | 1.0× | 4.0× | 10.8× | 5.0× |

Jan's ladder (14 sources, i9-14900, two-pass, wall-clock time): x264 1.0× · x265 8.5× · SVT-AV1 8.6× · libvpx 9.5×.


### Decode — rig, headless realtime, 1080 s windows, iso-bitrate software-encoded family

30 jobs, 142 valid device-rows; excluded/lost rows: 7.

Clip quality at that bitrate (VMAF v1 vs reference, frame-aligned): bbb h264 97.94; bbb h265 98.17; bbb av1 98.34; bbb vp9 98.52; kranjska h264 90.49; kranjska h265 86.96; kranjska av1 86.96; kranjska vp9 89.16; meridian h264 93.32; meridian h265 93.73; meridian av1 92.69; meridian vp9 91.11.


**Google TV (MediaTek, hw)** — ΔW above device idle (mean of valid reps, n; per-run 95 % CI half-width shown as ±)

| content | H.264 | HEVC | AV1 | VP9 |
|---|---|---|---|---|
| BBB 1080p60 @8 Mb/s | **+0.59** ±0.05 n=3 🟢🟢🟢 | **+0.57** ±0.06 n=2 🟢🟢 | **+0.55** ±0.06 n=2 🟢🟢 | **+0.58** ±0.06 n=3 🟢🟢🟢 |
| Kranjska 1440×1080p30 @10 Mb/s | **+0.29** ±0.06 n=3 🟢🟢🟢 | **+0.28** ±0.08 n=2 🟢🟢 | **+0.28** ±0.06 n=2 🟢🟢 | **+0.30** ±0.06 n=3 🟢🟢🟢 |
| Meridian 1080p60 @4.5 Mb/s | **+0.53** ±0.07 n=3 🟢🟢🟢 | **+0.50** ±0.08 n=2 🟢🟢 | **+0.51** ±0.08 n=2 🟢🟢 | **+0.57** ±0.06 n=3 🟢🟢🟢 |

**Fire TV Stick 4K (hw, Wi-Fi)** — ΔW above device idle (mean of valid reps, n; per-run 95 % CI half-width shown as ±)

| content | H.264 | HEVC | AV1 | VP9 |
|---|---|---|---|---|
| BBB 1080p60 @8 Mb/s | **+0.52** ±0.15 n=3 🟢🟢🟢 | **+0.49** ±0.18 n=2 🟢🟢 | **+0.51** ±0.18 n=2 🟢🟢 | **+0.46** ±0.20 n=3 🟢🟢🟢 |
| Kranjska 1440×1080p30 @10 Mb/s | **+0.36** ±0.17 n=3 🟢🟢🟢 | **+0.34** ±0.18 n=1 🟢 | **+0.28** ±0.21 n=2 🟢🟢 | **+0.37** ±0.17 n=3 🟢🟢🟢 |
| Meridian 1080p60 @4.5 Mb/s | **+0.41** ±0.19 n=3 🟢🟢🟢 | **+0.44** ±0.18 n=2 🟢🟢 | **+0.37** ±0.20 n=2 🟢🟢 | **+0.42** ±0.17 n=1 🟢 |

**Pi 400 (software)** — ΔW above device idle (mean of valid reps, n; per-run 95 % CI half-width shown as ±)

| content | H.264 | HEVC | AV1 | VP9 |
|---|---|---|---|---|
| BBB 1080p60 @8 Mb/s | **+1.40** ±0.17 n=3 🟢🟢🟢 | **+3.01** ±0.15 n=2 🟢🟢 | **+1.58** ±0.17 n=2 🟢🟢 | **+1.13** ±0.17 n=3 🟢🟢🟢 |
| Kranjska 1440×1080p30 @10 Mb/s | **+1.08** ±0.15 n=3 🟢🟢🟢 | **+2.41** ±0.17 n=2 🟢🟢 | **+1.82** ±0.17 n=2 🟢🟢 | **+1.15** ±0.18 n=3 🟢🟢🟢 |
| Meridian 1080p60 @4.5 Mb/s | **+1.42** ±0.17 n=3 🟢🟢🟢 | **+3.25** ±0.13 n=2 🟢🟢 | **+1.45** ±0.18 n=2 🟢🟢 | **+1.19** ±0.15 n=3 🟢🟢🟢 |

**Bbox 4K (operator CPE)** — ΔW above device idle (mean of valid reps, n; per-run 95 % CI half-width shown as ±)

| content | H.264 | HEVC | AV1 | VP9 |
|---|---|---|---|---|
| BBB 1080p60 @8 Mb/s | **-0.06** ±0.25 n=3 🟡🔴🔴 | **+0.17** ±0.20 n=2 🟡🟢 | **+1.23** ±0.21 n=2 🟢🟢 | **+0.04** ±0.21 n=3 🔴🔴🔴 |
| Kranjska 1440×1080p30 @10 Mb/s | **-0.21** ±0.21 n=3 🔴🔴🔴 | **-0.28** ±0.21 n=2 🔴🔴 | **+1.23** ±0.21 n=2 🟢🟢 | **-0.10** ±0.21 n=3 🔴🟡🔴 |
| Meridian 1080p60 @4.5 Mb/s | **+0.07** ±0.21 n=3 🔴🟡🟡 | **+0.07** ±0.21 n=2 🔴🟡 | **+1.28** ±0.21 n=2 🟢🟢 | **+0.06** ±0.21 n=3 🔴🔴🟡 |

**LG C2 (all-in, panel)** — ΔW above device idle (mean of valid reps, n; per-run 95 % CI half-width shown as ±)

| content | H.264 | HEVC | AV1 | VP9 |
|---|---|---|---|---|
| BBB 1080p60 @8 Mb/s | **+16.61** ±1.63 n=3 🟢🟢🟢 | **+15.71** ±1.63 n=2 🟢🟢 | **+15.95** ±1.62 n=2 🟢🟢 | **+15.89** ±1.62 n=3 🟢🟢🟢 |
| Kranjska 1440×1080p30 @10 Mb/s | **+1.37** ±1.62 n=2 🟢🟡 | **+0.12** ±1.63 n=1 🔴 | **+0.31** ±1.62 n=1 🔴 | **+0.25** ±1.62 n=3 🔴🔴🔴 |
| Meridian 1080p60 @4.5 Mb/s | **-2.08** ±1.62 n=3 🔴🔴🔴 | **-3.12** ±1.62 n=2 🔴🔴 | **-3.21** ±1.62 n=2 🔴🔴 | **-3.32** ±1.61 n=1 🔴 |

Lost/excluded rows:
- meridianiso vp9 firestick job 0649ef79: mid=PLAYING alive=False
- meridianiso vp9 c2 job 0649ef79: WSMessageTypeError('Received message 8:1008 is not WSMsgType.TEXT')
- kranjskaiso h265 c2 job 11d95f9d: TimeoutError()
- meridianiso vp9 firestick job 4da1e7d8: mid=PLAYING alive=False
- meridianiso vp9 c2 job 4da1e7d8: WSMessageTypeError('Received message 8:1008 is not WSMsgType.TEXT')
- kranjskaiso h265 firestick job b4d1476c: mid=PAUSED alive=False
- kranjskaiso h264 c2 job f7c90141: TimeoutError()

Rows accepted on the trace-flat criterion despite alive_at_window_end=False: 24 (all Fire TV unless noted):
- bbbiso vp9 firestick job 347daf4d (alive flag False, trace flat)
- bbbiso av1 firestick job 7141a3ec (alive flag False, trace flat)
- bbbiso h265 firestick job b5e00ee0 (alive flag False, trace flat)
- meridianiso av1 firestick job 0028f669 (alive flag False, trace flat)
- meridianiso av1 firestick job 102838b1 (alive flag False, trace flat)
- kranjskaiso h265 firestick job 11d95f9d (alive flag False, trace flat)
- meridianiso h264 firestick job 1346c767 (alive flag False, trace flat)
- kranjskaiso av1 firestick job 14a7de55 (alive flag False, trace flat)
- meridianiso h265 firestick job 24e65d43 (alive flag False, trace flat)
- meridianiso h264 firestick job 3e470f32 (alive flag False, trace flat)
- kranjskaiso av1 firestick job 42715dd6 (alive flag False, trace flat)
- meridianiso h265 firestick job 57c1895f (alive flag False, trace flat)
- meridianiso h264 firestick job 5ba7f131 (alive flag False, trace flat)
- bbbiso vp9 firestick job 5f23d935 (alive flag False, trace flat)
- kranjskaiso vp9 firestick job 80370bc3 (alive flag False, trace flat)
- kranjskaiso h264 firestick job 874baeef (alive flag False, trace flat)
- bbbiso h265 firestick job 89a40c75 (alive flag False, trace flat)
- kranjskaiso vp9 firestick job 9ea8debb (alive flag False, trace flat)
- bbbiso vp9 firestick job a99609f4 (alive flag False, trace flat)
- kranjskaiso h264 firestick job b8c2999d (alive flag False, trace flat)
- kranjskaiso vp9 firestick job daab9f4e (alive flag False, trace flat)
- bbbiso av1 firestick job e511ea36 (alive flag False, trace flat)
- meridianiso vp9 firestick job f76c6c8d (alive flag False, trace flat)
- kranjskaiso h264 firestick job f7c90141 (alive flag False, trace flat)

Google TV VP9 decoders allocated (logcat): [('c2.android.opus.decoder', 'c2.mtk.vp9.decoder')]

---
Generated by `analyze_night.py` from `results/diagnostics/encode_parity_nvenc_24c_2026-08-17.json` (108 rows) and the decode envelopes of batch `20260817b9c0de` (30 jobs). Scripts in this directory are the exact campaign drivers (copied from `/srv/data/owl/campaign_2026-08-17_vp9b/`). Interpretation lives in `docs/vp9_oneoff_2026-08.md` §5.
