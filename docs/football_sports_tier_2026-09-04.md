# The football sports tier — encode and decode, overnight 2026-09-03 → 04

*Ben's session, unattended run 22:58 → 05:55 (CR-081). Owner's brief: "get the new sports content into
all the data sets; leave as few questions as possible in the morning." Nothing of Tania's was edited;
every new row lives in a new or versioned file (see §4).*

## 1. The content

Panasonic's "Barcelona Football" 4K demo as re-uploaded to YouTube (`-gXGcLDIjPI`, The 4K Media Group):
3840×2160 **60 fps** SDR, AV1 as served, 193 s, broadcast-style coverage (long-lens follow pans, cuts).
**Lab-internal only** — © Panasonic, third-party upload, no citable licence: the measurements are usable,
the pictures are never shown or redistributed outside the lab (owner's decision 2026-09-03). Two other
candidates were tried and dropped the same evening: CableLabs "Moment of Intensity" (CC BY-NC-ND, 4K59.94
ProRes — rejected on viewing: slow motion, soft shots, no coverage) and the 30 fps upload of the same
Panasonic demo. Nothing with an open licence, ≥ 2 min, 4K60 and broadcast coverage exists in the public
datasets (Netflix Open Content has no sport; UVG/Xiph/EBU/JVET are 5–10 s clips).

Excerpt 50–170 s (clear of the intro card and the outro fade). SI ≈ 48.3 / TI ≈ 10.3 on the 1080p
30 s trim (ffmpeg `siti`) — much more spatial detail than ReadySetGo (38.5) at a quarter of its
temporal activity (40.4).

Built by the new `decode_bench/prep_family.py`: 1080p ProRes reference → matched-VMAF NVENC search →
`football_{h264,h265,av1}.mp4` (9.2 / 6.9 / 6.2 Mbps at VMAF v1 92.7 / 92.0 / 92.5) → 6/20/60-min
loops → iso software family at 9.2 Mbps (`footballiso_*_20min`, VMAF 93.0 x264 / 94.0 x265 / 94.3
SVT-AV1 / 94.0 VP9 after the WebM timebase fix). Encode source for the parity harness:
`test_content/football_35s.mp4` (4K60 H.264 High ~40 Mbps, limited range like BBB/Meridian).

## 2. Encode side — the parity sweep (GoS1, 22:58 → 00:09, 84 rows 🟢) + extension + recheck

Same 84-row recipe as Tania's ReadySetGo leg (`run_football_clip_sweep.py`, frozen BBB/Meridian ladder,
S53 protocol, VMAF v1 live then rescored to v0.6.1). **Iso-quality at VMAF v0.6.1 = 92**, bitrate and
Wh per minute of content, after the ceiling extension (§2b):

| codec / profile | football kbps @92 (Wh/min) | ReadySetGo | BBB | Meridian |
|---|---|---|---|---|
| H.264 CPU (x264) | 10 497 (0.421) | 5 718 (0.527) | 5 658 (0.322) | 2 928 (0.333) |
| H.264 NVENC baseline | 11 755 (0.130) | 5 841 (0.174) | 6 793 (0.140) | 3 364 (0.109) |
| H.264 NVENC tuned | 13 441 (0.162) | 6 000 (0.263) | 7 237 (0.222) | 4 422 (0.212) |
| HEVC CPU (x265) | 9 581 (1.091) | 4 218 (1.039) | 4 041 (0.649) | 1 481 (0.627) |
| HEVC NVENC baseline | 11 350 (0.138) | 4 540 (0.188) | 5 122 (0.144) | 3 000 (0.129) |
| HEVC NVENC tuned | 11 623 (0.361) | 4 472 (0.407) | 4 549 (0.381) | 2 634 (0.379) |
| AV1 CPU (SVT-AV1) | 8 022 (0.420) | 3 902 (0.550) | 1 737 (0.389) | 1 170 (0.349) |
| AV1 NVENC baseline | 8 748 (0.133) | 4 032 (0.184) | 3 448 (0.140) | 1 585 (0.125) |
| AV1 NVENC tuned | 10 595 (0.256) | 4 659 (0.278) | 3 487 (0.256) | 2 215 (0.255) |

- **Football needs about twice ReadySetGo's bits and 2–5× Meridian's for the same VMAF**, on every
  codec and encoder — it is the hardest content in the corpus by a wide margin.
- **The energy per minute barely moves with the content on the GPU** (NVENC baseline 0.13–0.14 Wh/min
  on all four contents) and moves modestly on the CPU: what changes with content is the bitrate you
  must pay for quality, not the encoder's power. Same "content over codec" shape as the decode side.
- **HEVC on x265 stays the dearest encode by far** (1.09 Wh/min, 2.6× x264) on sport as on the rest.

**2a. Recheck.** The main sweep's `h264 / gpu_tuned / 13000k` row read ΔW 32.5 W / 0.147 Wh/min against
49–52 W / 0.22 on both neighbours. Re-measured after the decode campaign (`run_football_recheck.py`,
three rows, own artifact): 49.9 / 48.5 / 50.6 W at 11/13/15 Mbps — the original was a one-off
artefact. The main artifact is left as measured; the recheck rows are their own dataset.

**2b. Ceiling extension.** On the frozen ladder VMAF 92 was unreachable in 5 of 9 cells (AV1 topped
out at 91.6 at 7.5 Mbps, HEVC-GPU at 91.4 at 10 Mbps). Per Tania's rule (extend upward only after
scoring the real VMAF, additively, separate artifact): AV1 9/11/13 Mbps and HEVC 12/14/16 Mbps, all
three profiles, 18 rows 🟢, rescored to v0.6.1 and merged
(`encode_parity_football_2026-09-03_merged_final.json`, 102 rows); the table above is from the merge.

## 3. Decode side — ten devices, n=3 (00:15 → 05:55)

Realtime 150 s panel ×3 (batch `FOOTBALL_RT`) and the four iso-bitrate 20-min loops at 9.2 Mbps ×3
at 1080 s windows (batch `FOOTBALL_ISO`), all ten devices in parallel, Apple TV on HDMI_2. Fire TV,
Gen 2 and Bbox measured **without an HDMI sink** (`hdmi_input: null`) — their rows are the no-sink
regime and do not compare with screen-attached rows (JOURNAL S73 (11)). One incident: the C2 panel
dropped to standby at ≈ 03:54 (its own auto-off, ~4 h after the last remote/SSAP input), which paused
the Apple TV's VLC and lost the C2's HEVC rep-2 row; both cells were re-run at 05:15 with the panel
woken (§3c).

**3a. Realtime panel, football vs BBB on the same boxes** (mean W during playback, n=3; BBB from the
screened n=3 batch of 2026-09-03 01:xx):

| box (sink) | H.264 W / ΔW | HEVC W / ΔW | AV1 W / ΔW | vs BBB |
|---|---|---|---|---|
| Google TV Streamer (HDMI_1) | 2.05 / +0.72 | 2.02 / +0.77 | 2.00 / +0.76 | −0.04…−0.07 W: **the harder content costs the GTV nothing** at matched VMAF |
| Xiaomi Gen 3 (HDMI_4) | 2.67 / +0.70 | 2.66 / +0.69 | 2.73 / +0.76 | AV1 +0.30 W and HEVC +0.16 W over BBB, H.264 −0.09: Gen 3's modern-codec advantage shrinks on sport |
| Roku (HDMI_3) | 2.18 / +0.37 | 2.24 / +0.42 | 2.27 / +0.46 | — |
| Apple TV, VLC (HDMI_2) | 5.62 / +2.37 | 5.60 / +2.34 | 6.95 / **+3.68** | software AV1 +1.3 W over its hardware pair (BBB: +1.2) |
| Pi 400 (sw decode) | 4.63 / +1.50 | 5.92 / +2.83 | 5.36 / +2.18 | — |
| Pi 5 (sw decode) | 4.45 / +1.32 | 5.51 / +2.33 | 4.86 / +1.73 | — |
| Fire TV (no sink) | 1.16 / +0.09 | 1.14 / +0.16 | 1.15 / +0.13 | −0.77 W vs its screened BBB rows = exactly the no-sink control |
| Xiaomi Gen 2 (no sink) | 2.61 / +0.73 | 2.54 / +0.62 | 2.55 / +0.62 | −0.34…−0.42 W vs screened BBB = the no-sink control |
| Bbox (no sink) | 6.03 / +0.13 | 5.98 / +0.18 | 7.31 / **+1.48** | software AV1 |
| LG C2 native | 53.4 / +6.2 | 52.3 / +0.0 | 52.1 / −0.7 | panel-dominated, differential only (CIs ±2.7 W) |

**3b. Iso-bitrate loops, all four codecs at 9.2 Mbps** (ΔW, n=3, 18-min windows):

| box | H.264 | HEVC | AV1 | VP9 | reading |
|---|---|---|---|---|---|
| Google TV Streamer | +0.76 | +0.77 | +0.79 | +0.87 | flat; VP9 dearest by 0.1 W |
| Xiaomi Gen 3 | +0.65 | +0.47 | +0.49 | +0.68 | HEVC/AV1 0.2 W cheaper than H.264/VP9 |
| Roku | +0.36 | +0.43 | +0.48 | +0.50 | all hardware; H.264 cheapest |
| Apple TV (VLC) | +1.54 † | +1.84 † | +3.79 | +3.16 | hardware pair vs software pair, +1.3–2.2 W |
| Pi 400 | +1.66 | +2.71 | +2.19 | +1.64 | software: HEVC dearest, VP9 ≈ H.264 |
| Pi 5 | +1.43 | +2.73 | +1.92 | +1.58 | same ordering as the Pi 400 |
| Fire TV (no sink) | +0.13 | +0.13 | +0.10 | +0.13 | no-sink regime |
| Xiaomi Gen 2 (no sink) | +0.78 | +0.67 | +0.76 | +0.73 | no-sink regime |
| Bbox (no sink) | +0.27 | +0.07 | +1.47 | +0.07 | software AV1; the rest inside its idle noise |
| LG C2 native | +6.28 | +0.93 ‡ | +4.88 | +4.79 | panel-dominated |

† one rep each replaced/added by the 05:15 re-runs (§3c); ‡ n=2 until the re-run.

**3c. Re-runs** (queued after the encode recheck, panel woken first): `loop_footballiso_h265` on the
Apple TV + C2, and one more `loop_footballiso_h264` rep on the Apple TV (its H.264 cell had one 🔴 rep
from an elevated tvOS home-screen baseline). Results (05:15–05:50, appended to the same batch): Apple TV HEVC re-run **alive to the
end, 5.64 W during playback** (its two clean reps: 5.70 / 5.70 W) but on a **5.20 W baseline** — the
tvOS home screen's ambient previews again (the box's known noise class: rested floor 3.0–3.1 W, promos
and previews 4–6 W) — so its ΔW (+0.44) is not usable; the C2 HEVC re-run completed (ΔW −0.42,
panel-dominated like its siblings), so that cell is n=3 again. The extra Apple TV H.264 rep followed.
**Lesson for the Apple TV, restated:** absolute playback watts are the comparable lens on this box
(5.6–5.7 W H.264/HEVC, 6.9–7.5 W AV1, 7.9 W VP9, all reps within 0.1 W); ΔW over a tvOS baseline is
only as good as what the home screen happened to be showing.

## 4. Where the football rows now live (nothing of Tania's touched)

| dataset | file |
|---|---|
| encode sweep, raw (v1 + v0 scores) | `results/calibration/_staging/encode_parity_football_2026-09-03.json` (84 rows) |
| encode sweep, final (v0 primary) | `…/encode_parity_football_2026-09-03_final.json` |
| ceiling extension / recheck | `…/encode_parity_football_ceiling_ext_2026-09-04.json`, `…/encode_parity_football_recheck_2026-09-04.json` |
| merged final (sweep + ext) | `…/encode_parity_football_2026-09-03_merged_final.json` (102 rows) |
| iso-VMAF table | `docs/smpte_2026/football_iso_vmaf_table.csv` |
| consolidated dataset, versioned | `docs/smpte_2026/consolidated_encode_dataset_2026-09-04.csv` = Tania's 569 rows + 150 football rows (`football_iso_bitrate_sweep_2026-09-03`, `football_abr_ladder_typical_2026-09-03`, `football_bitrate_ceiling_ext_2026-09-04`, `football_h264_gputuned_recheck_2026-09-04`, `football_iso_quality_interpolated_2026-09-03`); adopting it as canonical is Tania's call |
| decode rows | `/decode/batches` → `FOOTBALL_RT_BATCH`, `FOOTBALL_ISO_BATCH` (ids in JOURNAL); `results/decode/2026-09-04_*.json` |
| clips | `streams/football_*`, `streams/footballiso_*`, `streams/football_manifest.json`; masters in `test_content/` |

## 5. Caveats carried

Lab-internal source (no publication of the pictures; measurements fine). One content, one excerpt.
Encode rows share the S53 harness's three known integrity gaps (`smpte_2026/CLEAN_SWEEP.md`). Decode:
Fire TV / Gen 2 / Bbox are no-sink rows until the HDMI dummy plugs are fitted; C2 rows are
panel-dominated; the Apple TV is VLC, not the native player; Pis are pure decode (`-f null`), no display
path. The panel's 4-hour auto-off is a standing hazard for overnight Apple TV / C2 rows — disable it on
the C2 (General › Power › Auto Power Off) or keep-alive it from the rig.
