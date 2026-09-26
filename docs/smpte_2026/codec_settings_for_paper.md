# Codec presets & encoder settings — text for the SMPTE paper (§3.3)

Prepared 2026-09-18 in answer to the proof-readers' comment that Table 2 gives rate
control / GOP / profile / B-frames but no preset, which limits reproducibility.

**Provenance — every statement below is verified, not recalled:**
- Command lines are the `ffmpeg_cmd` field stored verbatim in every row of
  `results/calibration/encode_parity_nvenc_24c_2026-06-20.json` (and its extensions).
- Library versions and *effective* defaults were read back out of the encoders
  themselves on 2026-09-18, by running the same binary
  (`/usr/local/bin/ffmpeg-master`, unchanged since 2026-05-07) at 1080p and capturing
  the x264 SEI options string, the `x265 [info]` config dump, and the `Svt [config]`
  banner. NVENC defaults are from `ffmpeg -h encoder=*_nvenc` on the same binary.

---

## 1. The headline (and why the answer is short)

**No `-preset` was passed on any row.** Every one of the six configurations ran at its
library/wrapper default, with only the *normalised* parameters overridden (GOP, profile,
B-frames, rate-control mode, output resolution, audio). That is the actual normalisation
rule, and it is a defensible one — but it must be stated, because "default" is a
different point on each encoder's dial, and on SVT-AV1 it is a notably fast one.

So the paper does not need a preset-selection rationale. It needs (a) the defaults named
explicitly with versions, (b) one sentence saying why defaults, (c) one sentence
disclosing that the ranking is operating-point dependent.

---

## 2. Drop-in extension to Table 2

Add two columns (Preset / Tuning). Everything here is measured, not assumed.

| Codec / Impl. | Encoder (version) | Preset as run | Tuning | Notes on the default |
|---|---|---|---|---|
| AVC / CPU | libx264, core 165 | `medium` (ffmpeg default; not overridden) | none | ref=3, subme=7, me=hex, trellis=1, rc-lookahead=40, mb-tree on, AQ 1:1.00 |
| AVC / GPU | h264_nvenc | `p4` (NVENC default) | `hq` (default) | single-pass; rc-lookahead 0; spatial/temporal AQ off |
| HEVC / CPU | libx265, 4.1+241-cfee9638 | `medium` (x265 default; not overridden) | none | rd=3, subme=2, me=hex, ref=3, b-adapt=2, lookahead 20, AQ mode 2, cu-tree on |
| HEVC / GPU | hevc_nvenc | `p4` (NVENC default) | `hq` (default) | single-pass; rc-lookahead 0; spatial/temporal AQ off |
| AV1 / CPU | libsvtav1, SVT-AV1 v4.1.0-7-gb486d839 | **`preset 8`** (SVT default; not overridden) | `PSNR` (SVT default) | random-access pred. structure, mini-GOP 16, AQ mode 2 |
| AV1 / GPU | av1_nvenc | `p4` (NVENC default) | `hq` (default) | single-pass; rc-lookahead 0; spatial/temporal AQ off |

Software/hardware toolchain (one line under the table, or in §3.1):

> All encodes used FFmpeg `N-124403-g28ecb07e55` (2026-05-07) with x264 core 165,
> x265 4.1+241-cfee9638 and SVT-AV1 v4.1.0-7-gb486d839; NVENC encodes ran on an NVIDIA
> RTX 5080 (Blackwell), driver 610.43.02. CPU encodes used the encoders' automatic
> thread detection on 24 logical cores (no `-threads` cap); all encodes ran at elevated
> scheduling priority (`nice -n -5`).

---

## 3. Suggested §3.3 prose (~140 words — the justification)

> Presets were deliberately left at each encoder's own default rather than equalised to
> a nominal "same speed" point across libraries: preset scales are not comparable
> between x264, x265, SVT-AV1 and NVENC, so any cross-encoder alignment would itself be
> an arbitrary choice. Defaults are also the operating point an implementer reaches
> first, and are the point the OWL platform ships for its public measurements. Only the
> parameters that must match for the comparison to be meaningful were overridden — GOP
> length, profile, B-frame count, rate-control mode, output resolution and audio.
>
> We note that this places SVT-AV1 at preset 8 of 0–13, i.e. towards the fast end of its
> dial, whereas x264 and x265 sit mid-dial at `medium`; AV1's CPU energy figures should
> be read accordingly. Encoder speed setting is the dominant lever on encoding energy,
> and codec ranking by energy is operating-point dependent: in a separate measurement on
> the same platform, moving the software encoders to slower presets changed the
> energy multiplier between codecs by several-fold. The results below therefore
> characterise these codecs *at their default operating points*, not at their
> energy-optimal ones.

---

## 4. Three corrections to make in the existing Table 2 / text

1. **AV1 / CPU rate control is VBR, not ABR.** SVT-AV1's own config banner reports
   `BRC mode / target bitrate: VBR / <n>` for `-b:v`. x264 reports `rc=abr` and x265
   reports `ABR-<n> kbps`, so those two rows are correct as written. Suggest:
   "one-pass VBR (`-b:v`)" for the AV1/CPU row, and adding "one-pass" to the AVC/HEVC
   CPU rows for symmetry.
2. **"B-frames: n/a" for AV1 needs a footnote.** It is true that no `-bf` was passed,
   but it reads as "no bi-prediction", which is wrong: SVT-AV1 used its random-access
   hierarchical prediction structure with a 16-frame mini-GOP. Suggested footnote:
   *"AV1 has no `-bf` equivalent; SVT-AV1 used its default random-access hierarchical
   prediction structure (mini-GOP 16). av1_nvenc was run without B-frames."*
3. **`av1_nvenc` profile "n/a" is correct** — that encoder exposes no `-profile` option
   in this FFmpeg build — worth saying so in a footnote rather than leaving a blank.

Internal note (does not affect this paper): `docs/vp9_oneoff_2026-08.md` and the
`preset10_default` profile label in `consolidated_encode_dataset_*.csv`
(`vp9_vs_trio_sweep_2026-08-17` rows only) both state SVT-AV1's default preset as 10.
On this build it is **8**. The SMPTE paper's rows are unaffected (they are the
`cpu` / `gpu_baseline` profiles), but the claim should not be carried across.

---

## 5. Two points a reviewer will raise that are *not* about presets

1. **The GPU rows are a full GPU pipeline, the CPU rows a full CPU pipeline.** GPU rows
   decode and scale on the GPU (`-hwaccel cuda -hwaccel_output_format cuda`,
   `scale_cuda`); CPU rows decode and scale on the CPU (`scale=-2:1080`). The reported
   GPU energy therefore includes GPU decode and scaling, and the CPU energy includes CPU
   decode and scaling. This is the realistic deployment comparison, but it is not
   "encoder vs encoder in isolation" and should be stated in one sentence in §3.3.
2. **NVENC was not run at its fastest.** `p4` is mid-dial (p1–p7). A quality-tuned NVENC
   arm (`-preset p7 -tune hq -multipass 2 -spatial-aq 1 -temporal-aq 1 -aq-strength 8
   -rc-lookahead 32 -b_ref_mode middle`) was measured across the same sweep and is
   present in the dataset as the `gpu_tuned` profile. One sentence saying it exists and
   was excluded from the reported comparison pre-empts the "you compared software-medium
   against hardware-fastest" objection.

---

## 6. Suggested appendix — the six command templates, verbatim

These are the stored command lines, with paths elided. Twelve lines, and they make the
whole configuration section unambiguous.

```
# AVC / CPU
ffmpeg -y -i IN -c:v libx264   -b:v Nk -g 120 -profile:v high -bf 2 \
  -x264-params scenecut=0:open_gop=0 -vf scale=-2:1080 -c:a aac -b:a 128k OUT

# HEVC / CPU
ffmpeg -y -i IN -c:v libx265   -b:v Nk -g 120 -profile:v main -bf 2 \
  -x265-params scenecut=0:open-gop=0 -vf scale=-2:1080 -c:a aac -b:a 128k OUT

# AV1 / CPU
ffmpeg -y -i IN -c:v libsvtav1 -b:v Nk -g 120 -profile:v main \
  -svtav1-params scd=0 -vf scale=-2:1080 -c:a aac -b:a 128k OUT

# AVC / GPU
ffmpeg -y -hwaccel cuda -hwaccel_output_format cuda -i IN -vf scale_cuda=-2:1080 \
  -c:v h264_nvenc -b:v Nk -g 120 -profile:v high -bf 2 -rc cbr -c:a aac -b:a 128k OUT

# HEVC / GPU
ffmpeg -y -hwaccel cuda -hwaccel_output_format cuda -i IN -vf scale_cuda=-2:1080 \
  -c:v hevc_nvenc -b:v Nk -g 120 -profile:v main -bf 2 -rc cbr -c:a aac -b:a 128k OUT

# AV1 / GPU
ffmpeg -y -hwaccel cuda -hwaccel_output_format cuda -i IN -vf scale_cuda=-2:1080 \
  -c:v av1_nvenc  -b:v Nk -g 120 -rc cbr -c:a aac -b:a 128k OUT
```

Worth adding after the block: *"`scenecut=0` / `open_gop=0` / `scd=0` pin a closed,
fixed 120-frame GOP on all three software encoders, so GOP structure does not vary with
content."* That detail is currently implicit in the "GOP 120" column and is exactly the
kind of thing a reproducer would otherwise get wrong.
