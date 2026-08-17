# VP9 one-off — first high-level indication vs the OWL trio (2026-08-09, revised 2026-08-17)

One-off bench run prompted by the Disney+/HEVC royalty story: where does VP9 sit against
the three codecs OWL measures (H.264, HEVC, AV1), on encode (GoS1 server) and client
decode (portable rig)? **First indication, not a lab-reviewed finding** — n=1 per encode
row, n=2–3 per decode row, one operating point per encoder, one content family (BBB) on
the decode side. Nothing here joins OWL's standing codec set.

Scope: device layer only (GoS1 server / named client devices). Network, CDN and
production excluded. Energy, not CO₂e.

**Status (2026-08-17):** working document, still under discussion — it lives in the repo
rather than on the OWL findings page for that reason. The LinkedIn post that summarised
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

Thierry also pointed to the AWS MediaConvert settings post (July 2022) whose closing table
lists transcode durations: HEVC ~10–25 % longer than AVC (25:41 / 29:20 vs 23:25 / 23:02
wall-clock), AV1 in ~11 min. Two readings: (a) a commercial HEVC encoder is nowhere near
x265's slow-preset cost relative to x264 — the reference implementation and the product
are different things, and comparisons must name which one they measured; (b) those are
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

---
*Sources: `results/diagnostics/encode_parity_nvenc_24c_2026-08-09.json` (VP9 encode rows,
🟢), `results/calibration/encode_parity_nvenc_24c_2026-06-20.json` (S53 comparison rows),
decode envelopes under `results/decode/` dated 2026-08-09 (session jsonl + job ids in
`/srv/data/owl/campaign_2026-08-09_vp9/decode_results.jsonl`; WebM rescue jobs 833244a9,
90ee8608; discarded GTV mp4 rows documented above), prep sweeps + NEG scores in
`/srv/data/owl/campaign_2026-08-09_vp9/`.*
