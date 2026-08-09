# VP9 one-off — first high-level indication vs the OWL trio (2026-08-09)

One-off bench run prompted by the Disney+/HEVC royalty story: where does VP9 sit against
the three codecs OWL measures (H.264, HEVC, AV1), on encode (GoS1 server) and client
decode (portable rig)? **First indication, not a lab-reviewed finding** — n=1 per encode
row, n=2–3 per decode row, one operating point per encoder, one content family (BBB) on
the decode side. Nothing here joins OWL's standing codec set.

Scope: device layer only (GoS1 server / named client devices). Network, CDN and
production excluded. Energy, not CO₂e.

---

## 1. The structural facts (no measurement needed)

- **NVENC has never shipped a VP9 encoder** — confirmed on the RTX 5080 (h264/hevc/av1
  NVENC only). On OWL's bench, VP9 encode is **CPU-only**; the trio's hardware encode
  path (2.5–4.4× cheaper than CPU, S53) simply does not exist for VP9.
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

**Energy per minute of 1080p output (Wh/min), CPU encoders, matched target bitrates:**

| encoder | Meridian 2500k | Meridian 5000k | BBB 2500k | BBB 5000k |
|---|---|---|---|---|
| **libvpx-vp9 (today)** | **2.09** | **2.55** | **1.72** | **1.93** |
| libx265 (S53) | 0.67 | 0.78 | 0.62 | 0.70 |
| libx264 (S53, nearest rungs) | 0.33–0.39 | — | 0.30–0.33 | — |
| libsvtav1 (S53, nearest rungs) | 0.35–0.38 | — | 0.39–0.46 | — |
| *NVENC any codec (S53, context)* | *0.11–0.14* | | *0.09–0.15* | |

**First indication:** at a like-for-like speed point, VP9 software encode cost
**~3× libx265 and ~5–6× libx264/SVT-AV1** per minute of video on the same 24-core CPU —
the most energy-expensive encoder of the four — and **~15× the NVENC hardware path**
the trio actually uses in production-style pipelines. There is no hardware path to
close that gap for VP9 on this class of encoder hardware.

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

## 4. LinkedIn draft

> With VP9 back in the news (Disney+ reportedly moving away from HEVC over royalties),
> a fair question from the energy side: what would that switch actually *cost*?
> VP9 isn't one of the three codecs OWL measures continuously, so we ran a quick
> one-off on the bench — one server, three client devices, device layer only.
>
> Decode first, because clients dominate fleet energy: on a retail Google TV box, all
> four codecs (H.264, HEVC, AV1, VP9) decoded in hardware at essentially the same power —
> within ~0.06 W of each other. Where hardware decode doesn't exist and the CPU does the
> work (we used Raspberry Pis as a proxy), VP9 was actually the *cheapest* codec to
> decode — and software HEVC cost ~2–2.5× software VP9. On the decode side, an
> HEVC→VP9 move looks energy-neutral on TV silicon and mildly favourable where decoding
> falls back to software.
>
> Encode is the other way round. Most encode silicon (including our server GPU) has no
> VP9 hardware encoder, so VP9 encoding runs in software: at a matched production speed
> point and matched bitrates it drew roughly 3× the energy of software HEVC per minute
> of video, and ~15× the hardware-encode path the other codecs get. Encode happens once
> per title; decode happens millions of times — but it's a real asymmetry worth naming.
>
> One surprise en route: VP9 in an MP4 container stalled the TV box's playback three
> times running; the same stream in WebM played flawlessly. Packaging details can matter
> as much as codec choice.
>
> Quick test, small n, realtime playback regime, energy not CO₂e — a first indication,
> not a lab-reviewed finding. Methodology: wattlab.greeningofstreaming.org/methodology

---
*Sources: `results/diagnostics/encode_parity_nvenc_24c_2026-08-09.json` (VP9 encode rows,
🟢), `results/calibration/encode_parity_nvenc_24c_2026-06-20.json` (S53 comparison rows),
decode envelopes under `results/decode/` dated 2026-08-09 (session jsonl + job ids in
`/srv/data/owl/campaign_2026-08-09_vp9/decode_results.jsonl`; WebM rescue jobs 833244a9,
90ee8608; discarded GTV mp4 rows documented above), prep sweeps + NEG scores in
`/srv/data/owl/campaign_2026-08-09_vp9/`.*
