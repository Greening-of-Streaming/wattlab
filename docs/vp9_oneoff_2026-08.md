# VP9 one-off — first high-level indication vs the OWL trio (2026-08-09, re-run 2026-08-17→18)

One-off bench run prompted by the Disney+/HEVC royalty story: where does VP9 sit against
the three codecs OWL measures (H.264, HEVC, AV1), on encode (GoS1 server) and client
decode (portable rig)? **First indication, not a lab-reviewed finding** — n=1 per encode
row, n=2–3 per decode row, one operating point per encoder, one content family (BBB) on
the decode side. Nothing here joins OWL's standing codec set.

Scope: device layer only (GoS1 server / named client devices). Network, CDN and
production excluded. Energy, not CO₂e.

**Status (2026-08-29):** working document, still under discussion. **§6 adds a 2026-08-29 correction: fresh Roku + Apple TV runs do NOT support the "VP9 is cheaper in software" claim made in the LinkedIn thread — read §6 first.** §5 adds the overnight re-run of 17→18 Aug (iso-bitrate, software vs software, n=2–3) that the discussion asked for; read §5.3 next. The VP9 result stays a report in the repo rather than an entry on the OWL findings
page until the discussion settles. The LinkedIn post that summarised
the 08-09 run drew substantive comments (Thierry Fautier, Jan Ozer, Murat Pisat); §4
records what that discussion added and what it corrects, in particular that the
software-vs-hardware encode ratio in the original headline is a statement about NVIDIA/AMD
silicon, not a fair codec-versus-codec comparison for software VOD. Read §4 alongside §2.

**Read this first — the caveats:**
- Encode rows are n=1, ONE operating point per encoder (stated explicitly in §2), one
  server, one-pass ABR. Encoder speed settings dominate the result; move the dial and the
  multiplier moves.
- Decode rows are the realtime playback regime only, one content family, small n.
- The software-vs-software comparison is the market-relevant one for VOD; the NVENC row is
  context for GPU transcode pipelines.
- Two accounting lenses now exist (see §4.3): the numbers below are *marginal* (idle
  subtracted); an *attributional* view charges for machine occupancy and roughly doubles
  the CPU-encode figures.

---

## 1. The structural facts (no measurement needed)

- **VP9 hardware encode exists, but is vendor-scattered, not ubiquitous.** NVIDIA has
  never shipped a VP9 NVENC (confirmed on the RTX 5080: h264/hevc/av1 only) and AMD's
  VCN has none either; Intel Quick Sync has had VP9 encode since Kaby Lake (2016), and
  Google encodes VP9 on custom ASICs (Argos VCU) for YouTube. On OWL's bench — and on
  any NVIDIA/AMD-GPU transcode pipeline — VP9 encode is **CPU-only**; the trio's
  hardware encode path (2.5–4.4× cheaper than CPU, S53) is unavailable to VP9 there.
  The structural gap vs H.264/HEVC is *ubiquity* of the hardware path, not existence.
- **Client hw decode:** TV-class silicon has hw VP9 (proven below on the MediaTek Google
  TV; LG α9 and Fire TV silicon list it too); neither Raspberry Pi has it (Pi 400:
  hw H.264 only; Pi 5: no hw video decode at all).

## 2. Encode — VP9 CPU vs the trio (GoS1, parity harness)

Protocol: parity harness (S53 protocol — 30 s clips, 1080p, pinned GOP 120, dual-meter,
focus mode), 4 rows, all 🟢. VP9 = libvpx-vp9 `-deadline good -cpu-used 2 -row-mt 1
-tile-columns 3 -threads 16 -auto-alt-ref 1 -lag-in-frames 25 -profile:v 0` (documented
operating-point decision: production-VOD speed point; libvpx defaults would strand it
near single-thread). Bitrates = two interior rungs of the S53 h265 CPU ladder so rows
compare directly against the stored S53 dataset. Artifact:
`results/diagnostics/encode_parity_nvenc_24c_2026-08-09.json`.

**Operating points — state them, they are the result** (all one-pass ABR, 24-core Ryzen 9
7900, ffmpeg N-124403):

| encoder | speed setting used | where that sits on its dial |
|---|---|---|
| libx264 (S53) | `medium` (default) | middle |
| libx265 (S53) | `medium` (default) | middle |
| libsvtav1 (S53) | library default (preset 10) | fast end |
| libvpx-vp9 (this run) | `-cpu-used 2`, good deadline | slow-ish middle |
| NVENC h264/hevc/av1 (S53) | baseline bundle | hardware, seconds per clip |

So this is VP9 at a moderately slow point against x264/x265 at their middle and SVT-AV1 at
a fast one — not "everything at slow". Jan Ozer's everything-at-slow ladder (§4.2) gives a
very different multiplier from the same encoders, and both are right for their point.

**Energy per minute of 1080p output (Wh/min), software encoders, matched target bitrates:**

| encoder | Meridian 2500k | Meridian 5000k | BBB 2500k | BBB 5000k |
|---|---|---|---|---|
| **libvpx-vp9 (today)** | **2.09** | **2.55** | **1.72** | **1.93** |
| libx265 (S53) | 0.67 | 0.78 | 0.62 | 0.70 |
| libx264 (S53, nearest rungs) | 0.33–0.39 | — | 0.30–0.33 | — |
| libsvtav1 (S53, nearest rungs) | 0.35–0.38 | — | 0.39–0.46 | — |
| *NVENC any codec (S53, GPU-pipeline context only)* | *0.11–0.14* | | *0.09–0.15* | |

**First indication (software vs software):** at the operating points above, VP9 software
encode cost **~3× libx265 and ~5–6× libx264/SVT-AV1** per minute of video on the same
24-core CPU. That multiplier is a property of the operating points as much as of the
codecs: with x265 and SVT-AV1 pushed to their slow settings the gap collapses to roughly
parity in wall-clock terms (§4.2).

**Hardware context, not a codec comparison:** the trio's NVENC path on this box is ~15×
cheaper than the VP9 software rows. That ratio describes NVIDIA/AMD GPUs having no VP9
encoder (Intel Quick Sync and YouTube-style ASICs do), so it applies to GPU transcode
pipelines and *not* to cloud VOD, which is largely software for every codec. The original
LinkedIn headline led with this number; it should have led with the table above.

Compression efficiency at this speed point (same scorer, VMAF-NEG, same 1080p60 source,
from the decode-clip prep sweep): VP9 needed **4048 kb/s** to hit the NEG≈93 rung that
x264 hit at 4051 kb/s — x264-class efficiency, short of x265 (3565) and far short of
SVT-AV1 (2669). Slower libvpx settings would improve compression at even higher energy
cost.

Caveats: n=1 per row; libvpx ABR overshot targets by 12–44% (achieved bitrates in the
artifact — energy-per-minute is unaffected, bitrate-matched *quality* comparisons should
use the NEG sweep above); today's rows carry VMAF v1 while S53 rows are v0.6.1 — the two
scales are not comparable, so no cross-artifact VMAF claims; `-cpu-used` is the dominant
energy knob for libvpx and other speed points would move the multiplier.

## 3. Decode — VP9 on three client devices

Protocol: decode-bench July protocol via /decode (headless realtime 1×,
`calibrate=false`, window 105 s, per-row OWL confidence), clips ALL CPU-encoded from the
same 120 s 1080p60 ProRes master at the VMAF-NEG≈93 rung: h264 93.04 @4051 kb/s ·
hevc 93.29 @3565 · vp9 93.57 @4048 · av1 93.58 @2669. **Iso-quality, NOT iso-bitrate.**
Regime: **realtime only** — the known sw ordering inversion under saturated pacing is
out of scope here; do not quote these numbers for full-speed transcode-style decode.

**ΔW above device idle during playback (mean of reps, all rows 🟢):**

| device | decode path | vp9 | h264 | av1 | hevc |
|---|---|---|---|---|---|
| Pi 5 | software (all) | **1.07** (n=3) | 1.16 | 1.30 | 2.30 |
| Pi 400 | software (all) | **1.16** (n=3) | 1.44 | 1.50 | 2.95 |
| Google TV (MediaTek) | hardware (all, logcat-proven) | **0.38** (n=2, WebM) | 0.33 | 0.32 | 0.36 |

**First indications:**
- **With hardware decode (TV-class silicon), codec choice is an energy rounding error** —
  all four codecs land within ~0.06 W of each other (replicates the July ≤0.08 W spread
  finding, now extended to VP9: `c2.mtk.vp9.decoder` allocation confirmed by logcat).
- **In software, VP9 was the cheapest of the four** on both Pis — below H.264 despite
  carrying 1.5× AV1's bitrate — and software HEVC cost ~2–2.5× software VP9. The July
  realtime ordering (h264 < av1 < hevc) replicates exactly, with VP9 slotting in below
  h264.
- **Packaging datum:** VP9-in-MP4 (vp09) stalled the Google TV player in all 3 attempts —
  hw decoder allocated, then playback froze near-idle; rows discarded per protocol
  (jobs 2f099d1d, plus r2/r3). The identical stream remuxed to **WebM played flawlessly
  twice** (jobs 833244a9, 90ee8608). Container/packaging, not the decoder, was the
  blocker on this retail box — worth knowing before any VP9 rollout claim.

Caveats: one content family (BBB 1080p60); realtime regime only; Pi rows are ffmpeg
software decode (headless — no display/compositor); GTV number is device-total wall
power on a ~1.2 W idle box; n small throughout — first indication, not a finding.

## 4. What the discussion added (2026-08-15 → 17)

The LinkedIn post summarising this run (mid-August 2026) drew comments that sharpen it.
Recorded here so the document, not the thread, is the reference.

### 4.1 The speed dial (Thierry Fautier)

Thierry quoted iso-VMAF compute ratios of the order HEVC ~4×, AV1 ~5×, VP9 ~20× relative
to H.264, and asked that the distribution budget (bits saved downstream) be included.
Reconciliation: software encoders have a speed dial; OWL ran libvpx at a production-VOD
point (`cpu-used 2`) where it compressed x264-class and its premium bought nothing; the
larger ratios come from slower settings that buy compression at more energy. Compute-time
ratios and watt-metered energy are related but not the same figure. Distribution energy
is outside this document's scope (device layer only) and is not asserted either way.

Thierry also pointed to the AWS MediaConvert settings post (July 2022), which lists
transcode durations in several tables — and the HEVC-vs-AVC gap depends on which one you
read: **CBR 10 Mbps** multi-pass HQ 22:34 vs 37:22 (HEVC ~66 % longer, the figure Thierry
quotes); **QVBR** multi-pass HQ 22:41 vs 25:22 (~12 %); the closing bit-depth table (QVBR
L8) 23:25 vs 25:41 at 8-bit (~10 %) and 23:02 vs 29:20 at 10-bit (~27 %); AV1 ~11–13 min
throughout. Rate-control mode alone moves the HEVC penalty from ~12 % to ~66 % (under CBR
both encoders must spend the fixed bits and HEVC's extra tools do more work; under QVBR
each picks its own bitrate for the quality target) — one more dial that has to be stated.
Two further readings: (a) even at 66 % a commercial HEVC encoder is nowhere near x265's
slow-preset cost relative to x264 — the reference implementation and the product are
different things, and comparisons must name which one they measured; (b) those are
wall-clock times on a managed service (the AV1 rows finishing in half AVC's time point to
a different backend), and at the same QVBR level the HEVC/AV1 files came out *larger* than
AVC, so the rows are neither CPU-time nor matched-quality — they are not an energy datum.

### 4.2 Everything-at-slow (Jan Ozer)

Jan's objection: most VOD (and much live) is software, so comparing software VP9 with
hardware H.264/HEVC/AV1 doesn't reflect the market. Accepted — see §2, "hardware context".

His data: total per-title convex-hull ladder encode time across 14 1080p sources on an
i9-14900, x264 slow / x265 slow / SVT-AV1 preset 3 / libvpx cpu-used 2, two-pass 200 %
constrained VBR, top rung ~VMAF 93: **x264 1.0× · x265 8.5× · SVT-AV1 8.6× · libvpx 9.5×**.

Reconciliation with §2: at everything-slow, VP9 is only ~1.1× x265 and SVT-AV1; at OWL's
default-preset points it is 3× and 5–6×. Same curve, different point — the operating point
matters more than the codec name. His figures are wall-clock time not energy (on a
saturated CPU the two track closely — S53's "speed, not draw" result), and per-ladder
rather than per-minute-of-output. The natural next step (agreed in principle with both
commenters) is a joint piece: four software encoders each swept across their speed dial at
matched target quality, energy per minute of output on both accounting lenses (§4.3).

### 4.3 Marginal vs attributional energy (methodology v0.7)

Prompted by the speed-dial exchange, `/methodology` v0.7 (2026-08-15, commit `79045ab`) now
documents a second accounting lens. OWL's headline figures are *marginal*: idle subtracted,
the job charged only for ΔW × Δt. An *attributional* view, (W_base + ΔW) × Δt, charges the
job for occupying the machine — the honest lens for a dedicated encode fleet. Same
samples, no re-measurement; parity rows now persist both. Recomputed over the S53 + VP9
rows (nominal 79 W GoS1 idle floor): attribution ×2.1–2.7 on CPU rows; occupancy per
minute of video NVENC ~8 s · x265 31–41 s · VP9 90–130 s; VP9-vs-NVENC-h265 ratio
16.3× → 14.7× while the absolute gap widens 1.97 → 4.22 Wh/min (Meridian 2500k). Realtime
decode is immune (every codec occupies the device for the same window). Ratios hold under
either lens; slow encoders look worse in absolute terms once idle is charged.

### 4.4 Client decode availability (Murat Pisat)

"Apple lacks a VP9 decoder; not every smart TV has one." Apple silicon has had hardware
VP9 decode since 2020 (YouTube 4K on tvOS 14+), narrower than its HEVC path; across the
wider TV fleet hardware VP9 is patchy. That is §3's finding restated from the field: with a
hardware path codec choice is an energy rounding error, without one the CPU pays ~3×.

## 5. Overnight re-run, 2026-08-17→18 — iso-bitrate, software vs software, repeats

Run in direct response to §4: Jan's "compare software with software" and everything-at-slow
ladder, Thierry's speed dial, Tania's iso-bitrate ask. Two sequenced campaigns, same GoS1
harness and rig as §2/§3, all rows 🟢 unless stated. Raw artifacts:
`results/diagnostics/encode_parity_nvenc_24c_2026-08-17.json` (108 rows), decode envelopes
`results/decode/2026-08-1[78]_*.json` batch `20260817b9c0de`
(campaign page `/decode/batch/20260817b9c0de`), analysis + clip manifest in
`/srv/data/owl/campaign_2026-08-17_vp9b/`.

### 5.1 Encode — four software encoders × speed points (GoS1, 24-core Ryzen 9 7900)

Protocol: parity harness, 30 s 1080p trims of `bbb_120s` (high complexity) and `meridian_120s`
(low), one-pass ABR at 2500 / 5000 kbps, pinned GOP 120, AAC 128k, dual P110, focus mode,
VMAF v1 (3d0h) per row, **n=3 per cell, reps not adjacent**. Two rows excluded for an elevated
baseline (w_base > median + 10 W; hot baselines under-count ΔW): meridian VP9 cpu-used 2 2500k
rep 2 (98.7 W) and meridian x264 slow 2500k rep 3 (95.1 W). Operating points:

| encoder | "default" point (= S53/OWL) | "slow" point (= Jan's set) | extra |
|---|---|---|---|
| libx264 | `-preset medium` | `-preset slow` | |
| libx265 | `-preset medium` | `-preset slow` | |
| SVT-AV1 | preset 10 (library default) | `-preset 3` | |
| libvpx-VP9 (good, row-mt, 3 tile-cols, 16 thr) | `-cpu-used 4` | `-cpu-used 2` | `-cpu-used 1` |

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

Jan's ladder (14 sources, i9-14900, two-pass, per-title convex hull, wall-clock time):
x264 1.0× · x265 8.5× · SVT-AV1 8.6× · libvpx 9.5×.

**What these rows support (n=3, sd ≤5 %, all 🟢):**

1. **The operating point decides which "new" codec is the expensive one.** At everyone's
   defaults VP9 is the outlier: ~4.7× x264, ~2.3× x265, 3–5× SVT-AV1 per minute of video. At
   Jan's everything-slow set VP9 is *not* the outlier: SVT-AV1 preset 3 costs ~2× VP9 and
   ~2.5× x265; the three newer codecs sit 4–11× above x264 slow. Direction agrees with Jan's
   ladder (x264 far cheapest, the rest a large multiple); magnitudes differ (24-core thread
   scaling, one-pass vs two-pass, fixed-bitrate rows vs per-title ladders) and we do not claim
   his numbers or ours are "the" ratio.
2. **On a saturated CPU, time is energy.** ΔW was 65–71 W on every software row regardless
   of encoder, so energy-per-minute ratios equal wall-clock ratios; a timing ladder like Jan's
   is a fair proxy for marginal encode energy on a dedicated box. For the same reason the
   attributional lens (§4.3) multiplies every row by ~2.2 and leaves the ratios unchanged.
3. **libvpx's dial is short on this box.** cpu-used 4 → 2 → 1 spans 1.7× in energy for
   about +0.5 VMAF; its fastest useful multithreaded point already costs more than x265
   *slow*. x264's medium → slow spans 1.2–1.4×, x265's 2.1×, SVT-AV1's preset 10 → 3 8–15×.
4. **No iso-bitrate quality claim from these rows.** One-pass ABR on 30 s trims missed its
   target by −32 % (SVT-AV1, Meridian) to +46 % (libvpx, BBB): VP9's higher VMAF at "2500k" on
   BBB was bought with ~45 % more bits. Achieved bitrates are in the tables; the compression
   comparison belongs to a CRF/two-pass sweep, not here.

### 5.2 Decode — VP9 vs the trio at iso-bitrate, three contents, five devices

Protocol: new **iso-bitrate loop family** — per content ONE bitrate for all four codecs
(BBB 1080p60 8 Mb/s, Kranjska 1440×1080p30 10 Mb/s, Meridian 1080p60 4.5 Mb/s = the bitrate of
each existing H.264 family clip), **software encoders at production points** (x264 medium,
x265 medium, SVT-AV1 preset 6, libvpx cpu-used 2), two-pass ABR, GOP 120, silent audio track,
120 s from the ProRes references (Meridian: from the compressed 4K master), concatenated ×10 to
20-min loops; VP9 in WebM (MP4/vp09 stalls the Google TV player). Clip quality at that bitrate
(VMAF v1, frame-aligned): BBB 97.9 / 98.2 / 98.3 / **98.5** (H.264/HEVC/AV1/VP9), Kranjska
90.5 / 87.0 / 87.0 / **89.2**, Meridian 93.3 / 93.7 / 92.7 / **91.1** — so at these bitrates the
four streams are of broadly comparable quality, VP9 never the worst on the ProRes-sourced
contents. Headless realtime playback via `/decode`, **1080 s windows**, five devices in
parallel, n=2 (n=3 for H.264 and VP9), gates: PLAYING at mid-window (adb devices) + a trace flat
to the window end (the Fire TV end-of-window liveness probe returned False on rows whose power
trace is flat to the last second — a harness false negative, listed for repair; three rows where
the trace really dropped or the player was PAUSED are excluded).

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

**What these rows support:**

5. **With a hardware decoder, VP9 costs what the other three cost.** On the Google TV
   (`c2.mtk.vp9.decoder` allocated on every VP9 row) and the Fire TV Stick, VP9 sits inside the
   ±0.1 W codec spread on all three contents at iso-bitrate; the per-run 95 % CIs (±0.05–0.20 W)
   overlap. **Content moves the number 2×** (Google TV: BBB ~0.58 W, Kranjska ~0.30 W) —
   any per-hour client figure that ignores content is quoting one clip. Fire TV emits no
   decoder provenance; its VP9 level is consistent with hardware decode.
6. **Without one, VP9 is the cheapest software decode.** On the Pi 400 (all four in software)
   VP9 1.1–1.2 W is tied with or below H.264 (1.1–1.4), AV1 1.5–1.8, HEVC 2.4–3.3 W (2–3× VP9),
   on all three contents. This replicates the 08-09 BBB-only result at iso-bitrate.
7. Operator box (Bbox 4K): AV1 +1.2 W on every content (software AV1, no hardware path listed);
   H.264/HEVC/VP9 all inside its idle drift (🔴/🟡) — no ranking. LG C2 (webOS, all-in panel):
   BBB +16 W but Kranjska/Meridian ≈ 0 or negative — the OLED panel draws by picture, not by
   codec; not a decode measurement (unchanged from S63).

### 5.3 What we would now say, and what we would not

Say: the software-encode cost of VP9 depends on the operating point more than on the codec —
at defaults it is the dearest of the four on a 24-core server, at an everything-slow setting
SVT-AV1 is; on hardware clients VP9 decode is energy-neutral vs H.264/HEVC/AV1 at matched bits;
where decode falls back to software VP9 is the cheapest of the four and HEVC the dearest.
Not say: any iso-bitrate *quality* ranking from the encode rows; any hardware-vs-software
"×15" as a codec property; anything about distribution energy; anything from the C2 or the
Bbox beyond "software AV1".

Still one server, five client devices, 1080p, one-pass ABR encode; a first indication with
repeats, not a lab-reviewed finding. Thanks to Thierry Fautier and Jan Ozer, whose comments
set the design of this run.

## 6. Correction, 2026-08-29 — Roku and Apple TV say AV1 and VP9 tie in software decode

Direct response to §4.4 (Murat Pisat) and to a claim Ben made in the same LinkedIn thread: that
*if* the Apple TV falls back to software decode, VP9 would at least be cheaper to decode than the
other codecs there. Roku and Apple TV have since joined the rig (§3/§5.2 predate both), so this
was testable directly rather than argued from the Pi 400 datum in §5.2 point 6. **It does not hold
up — logged here as a correction, not a footnote.**

Protocol: same iso-bitrate BBB 1080p60 @8 Mb/s clip family as §5.2 (x264 medium / x265 medium /
SVT-AV1 preset 6 / libvpx-VP9 cpu-used 2, two-pass ABR) — no new encodes, two more client devices
added to that dataset. Two device states, batch `c876cc890df2`, all rows 🟢:
- **Roku Express 4K**, headless (`calibrate=false`), 150 s window, n=3 per codec, all four codecs.
  Decoder path unconfirmed — Roku exposes no logcat-equivalent provenance (§3's standing gap).
- **Apple TV 4K** (AppleTV6,2, 2017 A10X, tvOS 26.6), screen mode (marker-calibrated, 165 s
  window), n=3, AV1 and VP9 only, via VLC for tvOS over Companion (AirPlay `play_url` is dead on
  tvOS 18+). This is a genuine software-decode reading for both codecs, not an assumption: the
  A10X predates Apple's 2020-era hardware VP9 path and its 2023-era hardware AV1 path (§4.4), and
  VLC does not use either platform decode block regardless.

**ΔW above device idle (mean of reps, all rows 🟢):**

| device | decode path | H.264 | HEVC | AV1 | VP9 |
|---|---|---|---|---|---|
| Roku Express 4K (headless) | unconfirmed | 0.381 (n=3) | 0.470 (n=3) | 0.476 (n=3) | 0.481 (n=3) |
| Apple TV 4K (screen, VLC) | software (silicon-confirmed) | — | — | **3.435** (n=3, 3.387–3.486) | **3.495** (n=3, 3.473–3.536) |

**What these rows support:**

8. **The claim doesn't hold on either device.** Apple TV: VP9 is +0.060 W *above* AV1 (+1.7%) —
   smaller than the run-to-run spread inside either 3-run set (AV1 spans 0.10 W, VP9 spans 0.06 W).
   Roku: the AV1/VP9 gap is +0.005 W. Both read as a tie; neither shows VP9 cheaper, and the one
   lean that exists on the Apple TV points the wrong way for the claim.
9. **This does not contradict §5.2's Pi 400 result — it complicates it.** On the Pi 400 (ARM,
   software decode, §5.2 point 6), VP9 really was the cheapest of the four. On Roku and the Apple
   TV's A10X, AV1 and VP9 tie instead. Read as: "VP9 cheapest in software" is not a codec property
   that transfers across CPU architectures — it held on one device tested so far, not on three.
   Treat as an open architecture-dependence question, not a resolved one either way.
10. **The simpler, defensible statement:** AV1 and VP9 cost about the same to decode in software
    on the two devices checked here. Roku's own H.264/HEVC pair sits ~0.09–0.10 W below the
    AV1/VP9 pair — consistent with §5.2/§3's software ordering (newer codecs cost more), just
    without VP9 breaking away from AV1 the way the LinkedIn claim asserted.

Caveats: one content family (BBB, iso-bitrate); n=3 per cell; Roku decoder path unconfirmed;
Apple TV `alive_at_window_end: False` on every atv row here — a known pyatv liveness
false-negative (`playing` can misreport "Idle" mid-playback), not treated as invalidating since
the raw traces and screen-context ΔW confirm real, varying playback throughout.

---
*Sources: `results/diagnostics/encode_parity_nvenc_24c_2026-08-09.json` (VP9 encode rows,
🟢), `results/calibration/encode_parity_nvenc_24c_2026-06-20.json` (S53 comparison rows),
decode envelopes under `results/decode/` dated 2026-08-09 (session jsonl + job ids in
`/srv/data/owl/campaign_2026-08-09_vp9/decode_results.jsonl`; WebM rescue jobs 833244a9,
90ee8608; discarded GTV mp4 rows documented above), prep sweeps + NEG scores in
`/srv/data/owl/campaign_2026-08-09_vp9/`; §6 rows from batch `c876cc890df2`,
`results/decode/2026-08-29_{0ec0f05a,305561b2,97c47248,6ce7dc03,704959dc,e2a6de84,9114fb90,
d6a6242e,b5f5bbb2,38b13c96,41c25f50,5fe6c26d}.json` (Roku, headless) and
`results/decode/2026-08-29_{1f2c4f9e,c7479e15,b1d642f8,4728f8b8,f10c86a0,f5ecaf0a}.json`
(Apple TV, screen).*
