# Input-sensitivity findings (variant-axis exploration for the picker)

Captured 2026-05-26 while sketching CR-047 (parent source + variants schema).
The intent: figure out which input-side axes actually move energy on an
OWL re-encode, before committing to a picker matrix that exposes them.

## Test 1 — Input bitrate (compression ratio) — done 2026-05-26

**Question:** does the bitrate of the source master move the energy of an
OWL `h265_both` re-encode?

**Inputs:** three siblings of `bbb_120s.mp4` (2 min, 3840×2160 H.264),
re-encoded with `libx264 -preset medium` at explicit bitrate targets:

| label | target | actual | size |
|---|---|---|---|
| light  | 15 Mbps | 14.6 Mbps | 209 MB |
| mid    |  5 Mbps |  5.1 Mbps |  73 MB |
| aggro  |  1 Mbps |  1.3 Mbps |  18 MB |

**Workload:** `h265_both` (CPU vs GPU H.265 encode + VMAF terminal pass on
each), routed through `/video/upload` from loopback so the service did
its normal focus-mode + lock dance. Result IDs in `/srv/data/owl/results/video/`:
- light: `2026-05-26_2328a8ab.json`
- mid:   `2026-05-26_2c112a4d.json`
- aggro: `2026-05-26_97ec1c07.json`

(See `/tmp/owl_bench_*.log` for the exact poll timeline; bench harness at
`/tmp/owl_input_sensitivity_bench.py`.)

**Result (n=1 per input, all 🟢):**

| variant | CPU ΔW | CPU Wh | CPU dur | GPU ΔW | GPU Wh | GPU dur | VMAF cpu | VMAF gpu |
|---|---|---|---|---|---|---|---|---|
| light | 71.8 W | 1.3122 Wh | 65.7 s | 88.8 W | 0.3354 Wh | 13.5 s | 91.61 | 84.56 |
| mid   | 72.5 W | 1.3143 Wh | 65.3 s | 85.9 W | 0.3197 Wh | 13.3 s | 91.56 | 84.76 |
| aggro | 77.2 W | 1.3340 Wh | 62.2 s | 86.3 W | 0.3236 Wh | 13.4 s | 91.72 | **82.37** |

**Spread (light vs aggro):**
- CPU ΔE: **1.7 %** — at the noise floor (`variance_pct` = 1.29 %).
- GPU ΔE: **4.9 %** — ~4× noise, detectable but below the 10–20 % threshold
  that would earn the variants a picker slot.

**Verdict:** input bitrate doesn't move energy on the H.265 re-encode
workload. The picker matrix collapses from the originally-sketched 5-per-source
shape to **2 variants per parent** (full + 2-min extract). The vignette
(still image identifying the source in the picker, no measurement
purpose — owner clarified mid-design) is a parent-level field, orthogonal
to the variant list, not a third slot.

**Why energy is flat:** libx265 dominates the CPU run. Once the H.264
decoder reconstructs the frames, the encoder workload depends on the
*frame stream* (resolution × duration × content), not the input bitrate.
Decode is a tiny fraction of total CPU time. VAAPI is similar — hw-decode
shrugs at input bitrate.

**The interesting finding is on quality, not energy.** GPU VMAF dropped
from 84.6 (light) → 82.4 (aggro) — ~2.3 VMAF below the higher-bitrate
inputs. Re-encoding a 1.3 Mbps master can't recover what's missing in
the source. CPU encoder absorbed this gracefully (91.6 VMAF stable);
the GPU encoder didn't. That's a *measurable* finding for the FOKUS
audience — "preserving master quality matters even when re-encode energy
is identical" — but it's a key finding / curated demo, not a picker variant.

**Test inputs kept at:** `/tmp/bbb_120s_{light,mid,aggro}.mp4` until
CR-047 ships (then wipe).

## Test 2 — Input codec (decode-side sensitivity) — done 2026-05-26

**Question:** does the codec of the source master move the energy of an
OWL re-encode? Hypothesis: yes — software decode cost varies meaningfully
between H.264, H.265, and AV1. OWL's current presets don't apply
`-hwaccel vaapi`, so decode runs in software on CPU even for the VAAPI
encode path.

**Inputs:** three 2-min siblings of bbb_120s, downscaled to 1080p and
encoded at industry-typical streaming bitrates:

| codec | bitrate (target / actual) | size | rationale |
|---|---|---|---|
| H.264 (libx264 medium) | 5 / 5.11 Mbps | 73 MB | Mainstream OTT 1080p (Netflix Standard, YouTube, Twitch) |
| H.265 (libx265 medium) | 3 / 3.08 Mbps | 44 MB | Premium-tier 1080p (Netflix Premium, Apple TV+) |
| AV1 (libsvtav1 preset 6) | 2 / 2.26 Mbps | 33 MB | Cutting-edge streaming 1080p (Netflix AV1, YouTube AV1) |

Each is a realistic "master" in its codec — not a forced apples-to-apples
bitrate. We're answering the operational question *"if upstream delivers
in different codecs, does my re-encode workload change?"*

**Workload:** `h265_both` (same as Test 1).

Result IDs in `/srv/data/owl/results/video/`:
- H.264 input: `2026-05-26_883b15b0.json`
- H.265 input: `2026-05-26_dc0679b2.json`
- AV1 input:   `2026-05-26_683d3a30.json`

**Result (n=1 per input, all 🟢):**

| src codec | CPU ΔW | CPU Wh | CPU dur | GPU ΔW | GPU Wh | GPU dur | VMAF cpu | VMAF gpu |
|---|---|---|---|---|---|---|---|---|
| H.264 | 72.6 W | 1.2086 Wh | 59.8 s | 67.0 W | 0.2084 Wh | 11.2 s | 91.75 | 86.96 |
| H.265 | 75.2 W | 1.2352 Wh | 59.0 s | 66.7 W | 0.2112 Wh | 11.3 s | 92.91 | 87.57 |
| AV1   | 76.3 W | 1.2497 Wh | 58.9 s | 66.7 W | 0.2298 Wh | 12.3 s | 93.07 | 88.18 |

**Spread (H.264 ↔ AV1, the codec extremes):**
- CPU ΔE: **3.4 %** (~2.6× noise floor) — borderline detectable
- GPU ΔE: **10.3 %** — clearly real

**Why GPU side shows it more sharply:** with `-hwaccel vaapi` absent, the
decoder runs in software on CPU even for the GPU encode path. On the CPU
pipeline that decode is ~5–10 % of total runtime so it's swamped by the
libx265 encode. On the GPU pipeline the encode is so fast (~11 s) that
decode dominates → codec-of-origin sensitivity surfaces. GPU duration also
climbs 11.2 s (H.264) → 12.3 s (AV1) — software decode is the bottleneck
once the GPU encoder isn't.

The AV1 step is what carries the spread (H.264→H.265 is +1.3 %; H.265→AV1
is +8.8 %). That maps to the known software-decode cost ladder: AV1 is
notably more expensive than H.265 in software, while H.264↔H.265 is closer.

**Bonus finding on VMAF:** higher-quality source codec → higher output
VMAF, *even though file sizes go down*. AV1 at 2.3 Mbps delivers higher
output VMAF (88.18 GPU) than H.264 at 5.1 Mbps (86.96 GPU). The codec-
efficiency story made concrete on OWL — pairs naturally with the S28 AV1
hw-vs-sw finding (same 1500 kbps, sw beats hw on VMAF by ~2 points).

**Verdict for the picker:** don't add codec-of-origin as a per-source
variant. 10 % is in the grey zone, the AV1 jump is the only thing carrying
it, and the matrix balloons fast (source × codec-of-origin × extract = 9+
items per source).

**Verdict as a Key Finding:** worth surfacing. *"Your re-encode workload
pays a measurable cost when the upstream codec evolves faster than your
hardware decoder."* Clean talking point for the FOKUS / member-meeting
audience, and a natural follow-up to the AV1 hw-vs-sw story.

**Test inputs kept at:** `/tmp/bbb_120s_1080p_{h264,h265,av1}.mp4` until
CR-047 ships (then wipe).

## Summary

| Axis | Spread CPU | Spread GPU | Picker? | Key finding? |
|---|---|---|---|---|
| Input bitrate (CRF span) | 1.7 % | 4.9 % | No | Quality-bleed-through (yes) |
| Input codec (industry-typical) | 3.4 % | 10.3 % | No | Yes — decode-cost ladder |

**Final picker shape per source:** 2 variants — full + 2-min extract — on
the length axis only. Plus an optional vignette (still image) on the
*parent*, used as a UI thumbnail; it's orthogonal to the variant list
and serves no measurement purpose. Move forward with CR-047 against
this shape.
