# Set-top-box decode energy: codec, content and delivery mode

**Draft finding report — 2026-07-27** (untracked; interactive version with charts:
`/srv/data/owl/stb-decode-2026-07/results/stb_decode_report.html`, raw data + harnesses alongside).

**Rig:** Google TV Streamer ("Office TV", 192.168.1.126) on a dedicated Tapo P110 (mW API path,
fw 1.4.6 → 1.5 s cadence) · Just Player (media3) via ADB, one pipeline for all codecs, hardware
MediaTek decoders (`c2.mtk.avc/hevc/av1.decoder`, logcat-verified) · 1080p matched-VMAF (~92–93)
NVENC encodes at the S53 parity operating points, served from GoS1 over LAN Wi-Fi.
**Scope:** device layer only (the box; monitor metered separately, network/CDN excluded).

## Results (device-total W during playback)

| Content | Round | H.264 | HEVC | AV1 |
|---|---|---|---|---|
| BBB (60fps anim., 4–8 Mb/s) | 6-min | 1.887 | 1.872 | 1.805 |
| | 20-min | 2.235 | 2.200 | 2.165 |
| Meridian (60fps film, 3–4.5 Mb/s) | 6-min | 1.565 | 1.538 | 1.531 |
| | 20-min | 2.024 | 1.955 | 1.943 |
| Kranjska MTB (30fps sports, 11–13 Mb/s) | 6-min | 1.600 | 1.614 | 1.590 |
| | 20-min | 2.084 | 2.087 | 2.062 |

All 24 runs 🟢 on OWL's confidence model. Significance: Welch t on 30-s block means
(autocorrelation-honest). 20-min round: all three BBB pairs significant (h264 vs av1 p≈7×10⁻⁶),
Meridian h264 vs both (p≈5×10⁻⁸, 4×10⁻¹⁰), Kranjska all ns. Codec ordering av1 ≤ h265 ≤ h264
replicated in both rounds for all three contents.

## Findings

1. **Decode is nearly flat across codecs on fixed-function silicon.** Largest within-content
   codec difference: 0.08 W (~4%). AV1 is consistently *cheapest* by a hair — bitrate-driven,
   not compute-driven. Content (frame rate, audio presence) moves the needle more than codec
   (0.29 W spread across contents).
2. **Bitrate barely registers.** Kranjska carries 2–3× Meridian's bits for ~0.1 W more.
3. **Delivery mode outweighs codec by 5–14×.** Sustained rolling-buffer streaming (20-min files)
   sits +0.33–0.48 W (mean +0.42 W) above burst-buffered playback of the same content+codec
   (6-min files, radio mostly idle). Verified mechanism: server TCP counters show continuous
   ~stream-rate delivery in the sustained case.
4. **Delivery-mode decomposition (back-to-back, same clip bbb_h264 20-min):** local file
   2.029 W / 1.4 MB Wi-Fi RX vs sustained HTTP 2.237 W / 2,545 MB RX → **network delivery alone
   = +0.21 W (~10%)**. The HTTP arm reproduces the earlier round-B value (2.235 W) almost exactly.
   The remaining ~0.14 W of the 20-vs-6-min premium is not network (candidates: window length,
   first-run overlay — see caveats).
5. **Encode:decode ratio (same 2 min of video):** bench GPU encode = 1.9–4.0× one device decode;
   CPU encode = 6.2–22.7×. Encoding is amortised across the audience; decode is per-viewer.
6. **⚠ Unexplained: media3 fetched ~2.1× the file size** in the sustained-HTTP arm (2,545 MB for a
   1,221 MB file). Possible double-fetch/buffer-discard behaviour — needs its own experiment before
   claiming; would be a player-efficiency finding, not a codec one.

## Caveats

- Box home-screen baseline drifts 0.9–1.4 W between runs → ordered comparisons use device-total W,
  not ΔW. ΔW per run is recorded for magnitude context.
- The 20-min protocol's per-run app reset re-triggered Just Player's first-run tooltip overlay in
  all nine runs (screenshot-verified, identical composition — codec comparisons unaffected; it is
  one candidate for the non-network share of the premium). Future protocols: force-stop + grants,
  no `pm clear`.
- Kranjska 20-min logcat ring wrapped: h264/av1 decoder provenance captured mid-run
  (screenshots + logcat excerpts in results dir), h265 inferred.
- Meridian's 5.1-AAC re-encode is silent on this box (PCE quirk) — no audio-decode cost in its rows.
- Cast Default Media Receiver cannot decode AV1 on this box (audio-only fallback) — hence the
  ADB/Just Player pipeline. A 2-min cast round exists but is context-only (window-truncation bug).
- One discarded 20-min attempt (permission stall after app reset → UI screen, not decode).
- One box, three 1080p contents, one rung per codec. No claim beyond this panel.

## Data

`/srv/data/owl/stb-decode-2026-07/` — `streams/` (all encodes), `results/` (per-round JSON with
raw 1.5 s samples, analysis_summary.json, harness scripts, provenance screenshots, this report).
