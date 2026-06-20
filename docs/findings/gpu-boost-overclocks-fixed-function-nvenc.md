---
slug: gpu-boost-overclocks-fixed-function-nvenc
version: 1
first_measured: 2026-06-20
last_refined: 2026-06-20
headline: "NVIDIA GPU Boost over-clocks the NVENC transcode pipeline into a wasteful zone: ~9-12% more energy for identical encode time and VMAF. Pinning the SM clock removes it — and makes GPU energy reproducible across reboots and ambient temperature."
claim_short: "h264_nvenc 1080p, Meridian 120s: full boost (SM 2872 MHz) = 0.280 Wh in 12.1 s. Pinned at the knee (SM 2572 MHz) = 0.255 Wh in 12.5 s — 9% less energy, same VMAF, +0.4 s."
confidence: green
scope: "Device layer only (GoS1: AMD Ryzen 9 7900 + NVIDIA RTX 5080, driver 610.43.02). GPU power read from the card's internal sensor (nvidia-smi power.draw). Network, CDN, and CPE excluded."
methodology_ref: docs/encode_parity_calibration_2026-06.md
source_result_ids:
  - video/05fcba93
related_findings:
  - av1-hw-sw-vmaf-tradeoff
  - abr-all-codecs-meridian-120s
supersedes: null
tags: [video, gpu, nvenc, gpu-boost, energy, clocks, datacenter, reproducibility]
caveats:
  - "Measured on one clip (Meridian, low complexity SI~13/TI~2), one codec (h264_nvenc), one resolution (1080p), n=2 measured encodes per clock after a discarded warm-up. The shape (energy U-curve vs SM clock) is a property of the fixed-function pipeline and is expected to generalise across NVENC codecs; the exact knee clock and percentage will shift with content, resolution, and driver."
  - "Two sweep rows (1380, 1080 MHz targets) returned transient failures — at starved core clocks the unpinned GDDR7 memory clock can drop to a low pstate that briefly cannot sustain the CUDA decode+scale stage. The pipeline recovered at 780 MHz, so this is a transient, not a hard floor. It is a reason to pin near the knee (well above the starvation zone), not deep in the basin."
  - "Wh/min FALLS monotonically as the clock drops and is the WRONG metric for a fixed encode job — lower clock means lower power but more wall-minutes for the same work. The honest metric is Wh per clip (energy), which is U-shaped. This finding reports Wh per clip."
  - "The energy minimum is the ~2000-2270 MHz basin (~11.5% saving) but it costs +17-34% encode time for ~2% more energy than the knee. The recommended pin (2572 MHz) is the knee — nearly all the saving at negligible time cost — chosen because OWL's live /video path must stay fast and reproducible, not minimal-energy at any latency."
  - "The cited measurement (video/05fcba93) is a live-path GPU all-codecs run at default (unpinned) boost — i.e. the 'before' state. The pinned-vs-swept numbers come from the clock sweep stored at results/calibration/gpu_clock_sweep_2026-06-20.json."
---

# The result, in one sentence

On GoS1's RTX 5080, an identical 1080p `h264_nvenc` encode of a 120 s clip draws **83.5 W over 12.09 s (0.280 Wh) at full GPU Boost (SM 2872 MHz)** but only **73.4 W over 12.50 s (0.255 Wh) when the SM clock is pinned to 2572 MHz** — **9% less energy for the same encode and the same VMAF**, the extra time being four-tenths of a second.

# Why this happens

NVENC is a **fixed-function** encoder: a dedicated silicon block that runs at its own fixed rate regardless of how fast the general CUDA cores are clocked. In OWL's GPU transcode path the CUDA cores only **decode and scale** each frame (`scale_cuda`) and then hand it to the encoder. We isolated where the power actually goes:

- Decode + `scale_cuda` + NVENC (the production path): **84.6 W**
- Decode + `scale_cuda` with **no encoding at all**: **84.8 W** — essentially the same
- CPU decode + CPU scale + NVENC **only**: **66.0 W**

So the encoder is not the consumer. The power lives in the **CUDA decode+scale stage**, which GPU Boost runs near the card's maximum (SM ~2880 MHz, GDDR7 14801 of 15001 MHz). Because that stage finishes its work and then waits on the fixed-rate encoder, clocking it higher buys **no throughput** — it just spends watts spinning the cores faster while they idle-wait. Faster clock, same finish time, more energy.

This is why a longstanding assumption fails here. The usual "race to idle" intuition — run faster, finish sooner, save energy — only holds when the thing you are speeding up is the bottleneck. Here it isn't, so higher clocks are pure waste.

# The energy curve

Locking the SM clock at descending steps and re-measuring the same encode traces a clear **U-shape** in energy-per-clip:

- SM 2872 MHz — 12.09 s — 83.5 W — **0.280 Wh** (full boost = unpinned default)
- SM 2572 MHz — 12.50 s — 73.4 W — **0.255 Wh** (knee: lowest clock still holding ~12 s — -9%)
- SM 2272 MHz — 14.12 s — 63.3 W — **0.248 Wh** (energy minimum — -11.5% but +17% time)
- SM 1965 MHz — 16.24 s — 55.1 W — **0.249 Wh** (minimum basin, tied)
- SM 1672 MHz — 18.44 s — 52.4 W — **0.268 Wh** (rising again — decode+scale now bottlenecked)
- SM 779 MHz — 40.16 s — 46.4 W — **0.518 Wh** (time blown up — ~2x the minimum)

Drop the wasteful boost and energy falls; drop too far and the decode+scale stage becomes the bottleneck, time balloons, and energy climbs back up.

# Why the reading changed across a reboot — and the data-centre angle

This investigation started because the same all-codecs benchmark drew ~8 W more on GPU paths after GoS1 was rebooted and moved to a cooler basement on 2026-06-19 — identical encode time, identical VMAF, +15-18% energy. GPU Boost is **headroom-driven**: a cooler, less power-constrained GPU sustains **higher** clocks for the same workload. So the cooler room simultaneously lowered idle power (-1.7 W) and raised load power (+8 W) — the same cause, opposite signs — by letting the boost algorithm reach further into the wasteful zone.

That connects to a known data-centre tension, with a sharper twist. The established trade-off is that **over-cooling wastes facility energy** and operators are generally advised to run *warmer*: raising inlet temperature saves chiller energy, and although it raises IT power via server fans and silicon leakage (which rises roughly exponentially with temperature, ~0.35-0.5 %/degC of server power in the ASHRAE band), the net usually favours the warmer setpoint. The twist this finding adds: for **clock-insensitive accelerator workloads** (fixed-function transcode, and plausibly other boost-pinned-but-bottlenecked jobs), colder silicon also pushes GPU Boost to over-clock for no throughput gain — so aggressive cooling can waste energy on *two* fronts at once (cooling overhead **and** wasted compute), while the conventional fan/leakage argument already points toward warmer. The clean fix is not thermal at all: **pin the clock**, and the workload draws the same energy regardless of how cold the room is.

# What we changed (recommended)

Pin the GPU to **SM 2572 MHz** at boot (`nvidia-smi -pm 1 && nvidia-smi -lgc 2572,2572` via a systemd unit), then re-run the `/reconfigure` encode-parity calibration so the `/video/budget` GPU energy column reflects the pinned, reproducible state. The pin captures ~9% of the available saving at +0.4 s/clip and — more importantly for a measurement instrument — removes the ambient-temperature drift that made GPU energy float between reboots and seasons.

# What this finding does not measure

- A single clip, codec, and resolution. The U-curve shape should hold for other NVENC codecs (h265/av1) and resolutions, but the knee clock and the percentage will move.
- It does not re-measure the wall (Tapo) energy under the pin — the sweep used the GPU's internal power sensor for clean, fast 5 Hz sampling. A confirming wall-meter run is the natural follow-up via `/reconfigure`.
- It does not claim a facility-level (PUE) result. The data-centre paragraph is mechanism and direction, grounded in the cited literature, not a measured PUE delta on GoS1.
