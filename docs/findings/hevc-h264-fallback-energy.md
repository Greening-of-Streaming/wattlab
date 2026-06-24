---
slug: hevc-h264-fallback-energy
version: 1
first_measured: 2026-06-20
last_refined: 2026-06-24
headline: "Dropping HEVC for H.264 cuts encode energy ~47–68% but raises per-stream bitrate up to ~2× for the same quality — the energy shifts from the encoder to the network"
claim_short: "VMAF 92, 1080p CPU — BBB: H.264 0.316 Wh/min @ ~4,980 kbps vs HEVC 0.649 Wh/min @ ~3,480 kbps (H.264 = 51% less encode energy, +43% bitrate). Meridian H.264 ~2× bitrate; Kranjska (sport) near-parity."
confidence: green
scope: "Device layer only (GoS1: AMD Ryzen 9 7900 + RTX 5080, NVENC). Network, CDN, and CPE excluded. No amortised training cost. Network/delivery energy is INFERRED from measured bitrate, not measured here."
methodology_ref: docs/encode_parity_calibration_2026-06.md
source_result_ids:
  - calibration/encode_parity_nvenc_24c_2026-06-20
related_findings:
  - av1-hw-sw-vmaf-tradeoff
  - abr-all-codecs-meridian-120s
supersedes: null
tags: [video, hevc, h264, codec, bitrate-efficiency, frand, encode-parity]
caveats:
  - "Encode energy is measured directly at the wall (Tapo P110, 1 Hz, OWL focus-mode protocol, all rows 🟢). Network/delivery energy is NOT measured — it is inferred from the measured bitrate gap. OWL is device-layer only. Quantifying the delivery delta in Wh needs a per-GB intensity factor with its own confidence flag; we deliberately do not assert one here."
  - "Iso-quality bitrates are interpolated from a 5-point bitrate sweep per codec to the VMAF-92 target, not measured exactly at 92. BBB and Kranjska bracket 92 within the sweep; Meridian reaches 92 below the swept floor for both codecs (HEVC well under 1,500 kbps, H.264 under 3,000), so its '~2×' is a lower-bound read, not a precise crossover."
  - "CPU path (libx264 / libx265, best-effort presets) is the headline because it represents quality-first VOD production. On the hardware NVENC path the encode-energy gap nearly vanishes (~0.13 Wh/min for both codecs) — fixed-function ASIC silicon flattens codec complexity — so a hardware encode farm sees little encode-side saving from the downgrade, while the bitrate penalty is unchanged."
  - "Single 30 s window per (clip × codec × bitrate), 1080p, one GOP setting. Numbers shift with resolution, preset, content and ffmpeg/driver version."
  - "The codec-efficiency gap is strongly content-dependent (see body): largest on low-complexity content, moderate on high-spatial, near-zero on high-temporal sport at VMAF 92."
---

# The result, in one sentence

At a fixed quality target (VMAF 92) on 1080p sources, encoding **H.264 instead of HEVC used 47–68% less energy per minute of video** on the CPU path — but H.264 needed **up to ~2× the bitrate** for the same quality, so the data carried by every delivered stream rises. The energy of a codec downgrade does not disappear; it moves from the encoder onto the network and storage.

# Why this matters

The Unified Patent Court's June 2026 HEVC injunction against Disney (InterDigital, 11 EU states) puts a concrete option on the table for streamers: turn HEVC off and fall back to H.264 in the affected countries. The intuitive read is "older codec, simpler, surely cheaper." OWL's measurements show the energy story is split, and runs the opposite way at each end:

- **At the encoder, the downgrade is cheaper.** HEVC buys its compression efficiency by spending far more compute. On the CPU path, H.264 encoded with roughly half to a third of HEVC's energy per minute of video.
- **In delivery, the downgrade is more expensive — and that cost scales with the audience.** H.264 needs more bits for the same perceptual quality. The encode saving is paid once per title; the bitrate penalty is paid per viewer-hour. At a major platform's scale, the second term dominates.

This is the first OWL finding that pairs measured encode energy with the *bit-efficiency* axis to reason about a real industry decision, and it makes the trade-off legible: a codec choice is not a single "more/less energy" number, it is a redistribution between layers.

# The numbers

Measured CPU encode energy and the interpolated bitrate to reach VMAF 92, per source:

- **Big Buck Bunny** (high spatial complexity, SI ~33 / TI ~6): H.264 **0.316 Wh/min** @ ~4,980 kbps vs HEVC **0.649 Wh/min** @ ~3,480 kbps — H.264 is **51% less encode energy** but needs **+43% bitrate**.
- **Meridian** (low complexity, SI ~13 / TI ~2): H.264 **0.333 Wh/min** vs HEVC **0.627 Wh/min** — **47% less encode energy**; both clear VMAF 92 below the swept bitrate floor, with HEVC reaching it at well under half H.264's bitrate (**~2× penalty**).
- **Kranjska downhill MTB** (high temporal complexity, SI ~101 / TI ~45): H.264 **0.241 Wh/min** @ ~9,210 kbps vs HEVC **0.749 Wh/min** @ ~9,120 kbps — **68% less encode energy** and **near-parity bitrate (~+1%)**.

Concretely, the BBB-class +43% is ~1.5 Mbps extra, roughly **+1.3 GB on a two-hour stream** — carried by network and client decode on every play.

# The content-dependence is the headline nuance

The HEVC efficiency advantage is not a constant. It is largest on low-complexity content (Meridian, ~2×), moderate on high-spatial content (BBB, +43%), and **almost vanishes on high-motion sport** (Kranjska, near-parity at VMAF 92). So "turn off HEVC" is comparatively cheap for live sport but expensive for a catalogue of films and series. A platform's exposure to the downgrade depends on what it streams.

Note the SI/TI complexity figures above are the *measured* values (ITU-T P.910), which invert these clips' informal reputations: BBB is genuinely high-complexity, Meridian low.

# How it was measured

Part of the 2026-06 encode-parity / energy-quality calibration sweep: codec × {CPU, GPU baseline, GPU tuned} × 5 bitrates × 3 sources, 1080p, 30 s windows, via OWL's real measured path (focus mode, `/tmp/gos-measure.lock`, 1 Hz Tapo P110, terminal VMAF after the measurement window so scoring draw never enters the energy). NVENC is too fast for 1 Hz sampling, so each encode is repeated to ≥20 s wall-clock and normalised back to per-content-minute. All cited rows returned 🟢 confidence. Full method note: `docs/encode_parity_calibration_2026-06.md`.

# What this finding does not measure

- **Delivery energy in Wh.** OWL is device-layer only. The bitrate gap is the *lever*; converting it to network/CDN/device Wh needs a per-GB intensity factor we don't assert here.
- **Decode energy.** Early OWL work suggests some TV sets draw a few percent more to decode HEVC than H.264 (just above the noise floor) — i.e. the downgrade likely also trims a little client-side energy — but that data is being re-measured for publication and is not part of this finding.
- **Iso-quality at exactly VMAF 92.** Bitrates are interpolated from a 5-point sweep, not searched precisely to 92.

# Read alongside

- `av1-hw-sw-vmaf-tradeoff` — the same energy-vs-bit-efficiency trade-off seen for AV1 hardware vs software.
- `abr-all-codecs-meridian-120s` — the broader all-codec ABR energy picture this sweep extends.
