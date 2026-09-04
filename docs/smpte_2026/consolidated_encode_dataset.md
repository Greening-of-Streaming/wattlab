# Consolidated encode dataset — what this is

*Built 2026-08-28 for the SMPTE paper, extended same day with isolated Kranjska runs
recovered from the live-app results store, extended again 2026-08-28/29 with a
resolution/aspect/frame-rate-matched sport clip (ReadySetGo — see below and caveat 9).
Combines OWL's encode-power + VMAF campaigns into one tidy CSV
(`consolidated_encode_dataset.csv`, 569 rows) so the analysis doesn't have to stitch
source locations by hand. Every row is traceable back to a stored result artifact —
nothing here is a fresh measurement.*

## The nine datasets, concatenated (`dataset` column)

| `dataset` value | What it answers | Codecs | Sequences | Rate control | Rows |
|---|---|---|---|---|---|
| `s53_iso_bitrate_sweep` | **Iso-bitrate**: at this target bitrate, what VMAF/energy? | H.264, H.265, AV1 | BBB, Meridian, Kranjska | fixed target, up to 11 points/codec | 168 |
| `s53_abr_ladder_typical` | **Typical operational points**: real ABR-ladder rungs (720p/540p/480p/360p) at fixed per-resolution bitrates | H.264, H.265, AV1 | BBB, Meridian, Kranjska | fixed, per-rung | 72 |
| `s53_iso_quality_interpolated` | **Iso-quality**: bitrate/energy needed to hit VMAF 88/90/92/94/96 | H.264, H.265, AV1 | BBB, Meridian, Kranjska | *interpolated*, not measured | 135 |
| `frozen_amd_typical_use_2026-05-22` | Single typical-ABR point per codec, pre-GPU-swap hardware | H.264, H.265, AV1 | Meridian only | fixed, 1 point/codec | 6 |
| `vp9_vs_trio_sweep_2026-08-17` | Iso-bitrate, 4th codec, two operating points each (OWL-default vs Jan Ozer's everything-slow) | H.264, H.265, AV1, **VP9** | BBB, Meridian | fixed target, 2 bitrates | 36 |
| `kranjska_isolated_video_ui_runs_2026-06` | **Typical-use bitrate on Kranjska**, current NVENC hw — the sport-tier point `frozen_amd_typical_use` is missing, recovered from ad hoc live-app jobs, not a designed campaign | H.264, H.265, AV1 | Kranjska only (120s + full 6:40) | fixed, same 3 bitrates as the AMD finding | 23 |
| `readysetgo_iso_bitrate_sweep_2026-08-28` | **Iso-bitrate** on the resolution/aspect/frame-rate-matched sport clip — same bitrate points as `s53_iso_bitrate_sweep` | H.264, H.265, AV1 | ReadySetGo | fixed target, matches BBB/Meridian's ladder exactly | 60 |
| `readysetgo_abr_ladder_typical_2026-08-28` | Typical ABR-ladder rungs on ReadySetGo | H.264, H.265, AV1 | ReadySetGo | fixed, per-rung | 24 |
| `readysetgo_iso_quality_interpolated_2026-08-28` | Iso-quality on ReadySetGo — bitrate/energy for VMAF 88/90/92/94/96 | H.264, H.265, AV1 | ReadySetGo | *interpolated*, not measured | 45 |

Every row also carries `hardware` and `vmaf_version` explicitly — **read those two columns
before comparing rows across datasets.** They are not all the same.

## Provenance, dataset by dataset

### `s53_iso_bitrate_sweep` + `s53_abr_ladder_typical`
Source: `results/calibration/encode_parity_nvenc_24c_2026-06-20_plus_ext.json` — the
original S53 campaign **plus a 2026-08-28 supplemental run**, merged. Base: 207 rows
(2026-06-20, GoS1: Ryzen 9 7900 / RTX 5080 NVENC, `ffmpeg N-124403`). Extension: 33 rows
added 2026-08-28 to close the VMAF 94/96 iso-quality gaps that were still inside a
defensible streaming bitrate range (see "The 2026-08-28 extension" below) — merged file
is **240 rows, all 🟢**. `profile=cpu` rows are `libx264`/`libx265`/`libsvtav1`;
`gpu_baseline`/`gpu_tuned` are NVENC (baseline = OWL's live args; tuned = + quality-knob
bundle, see below). `rung=sweep` (168 rows, 1080p) is the iso-bitrate data; `rung=ladder`
(72 rows, cpu + gpu_baseline only, unchanged by the extension) is the fixed lower-rung ABR
ladder — the closest thing to a measured "typical operating point" table. Method write-up:
`docs/encode_parity_calibration_2026-06.md` — **but read numbers from the CSV/JSON, not
that doc's §9 prose tables**, which were written against an even earlier, smaller, 2-clip
partial artifact (`..._2026-06-18.json`) before Kranjska was added. The original 06-20
file (207 rows) and the 08-28-only extension (33 rows) are both kept on disk unmodified —
`..._2026-06-20.json` and `_staging/..._2026-08-28_bitrate_ext.json` respectively — the
`_plus_ext` file is the one to use; it's also what `/video/budget` now serves as "latest."

#### The 2026-08-28 extension — what it added and a mid-run correction
30 rows extending Meridian+BBB (H.264 →13/15 Mbps, H.265 →8.5/10 Mbps, AV1 →7.5 Mbps) plus
3 optional rows extending Kranjska AV1 →13 Mbps — all chosen to stay inside a defensible
"premium/live-tier" streaming bitrate ceiling (H.264/H.265) or AV1's realistic ~7-8 Mbps
top (see chat: VMAF 96 for AV1 at 1080p was deliberately left unchased as unrealistic
regardless of bitrate). Kranjska's H.264/H.265 ladder was deliberately left untouched —
it already exceeds realistic streaming bitrates from the original campaign.
**Mid-run correction:** the harness scores VMAF using the live service's current default,
which has been **v1** since S55 (2026-07-17) — not the v0.6.1 the rest of this dataset
uses. The first pass came back on the wrong scale. Fixed by re-encoding all 33 rows
(same deterministic ffmpeg commands, no re-measurement needed) and rescoring under an
**in-process** `vmaf_model=v0` override (`bin/rescore-bitrate-ext-v0.py`) that never
touched the live `settings.json`, so it had zero effect on concurrent visitor scoring.
Each extension row keeps both: `vmaf` is the v0.6.1 rescore (the number used everywhere
in this file); `vmaf_v1_bonus` is the original v1 score, kept for reference only — do not
mix it into any v0.6.1 comparison. **Result: 12 of the 33 targeted VMAF-94 gaps closed**
(everything realistic to close, closed); the remaining gaps are VMAF-96 (an honest ceiling
at realistic bitrates, not a data gap) plus Kranjska H.265-GPU's 94/96 (left alone by
design). Scripts: `bin/run-bitrate-ceiling-ext.py`, `bin/rescore-bitrate-ext-v0.py`,
`bin/merge-bitrate-ext.py` — all still on disk if this needs re-running or auditing.

### `s53_iso_quality_interpolated`
Source: `docs/smpte_2026/iso_vmaf_table.csv` (already built for this paper, generator
`make_iso_vmaf_table.py`), derived from the merged `_plus_ext` artifact above. For each
clip × codec × profile, the bitrate/Wh-per-minute **linearly interpolated** between the
measured sweep points to hit VMAF targets 88/90/92/94/96. **Not an independent
measurement** — see caveats. An empty `target_kbps`/`wh_per_min` means the target VMAF
exceeded what the sweep reached (`notes` column states the max measured VMAF instead).
**Post-extension: 21 of 135 cells empty** (down from 33 before the 08-28 extension) — all
21 are VMAF-96 except Kranjska H.265-GPU, which is still short of 94 too (left alone; its
ladder already exceeds realistic streaming bitrate — see the extension section above).

### `frozen_amd_typical_use_2026-05-22`
Source: `docs/findings/abr-all-codecs-meridian-120s.md`, stored result `video/e18a9d57`.
One 120 s Meridian run, six encodes, each codec at **one** literature-typical ABR bitrate
(H.264 4 Mbps / H.265 2 Mbps / AV1 1.5 Mbps) — n=1. **This predates the 2026-05-29 GPU swap**
(AMD RX 7800 XT, not the RTX 5080) — frozen baseline, `docs/gpu_swap_amd_baseline.md`. Included
because it's the only place OWL states single "typical" bitrates per codec with a citation,
but it is a different GPU generation from every other row in this file — do not average
it in with the NVENC rows.

### `vp9_vs_trio_sweep_2026-08-17`
Source: `results/diagnostics/encode_parity_nvenc_24c_2026-08-17.json` (108 raw rows, n=3
reps per cell), transcribed here from the pre-aggregated, already-reviewed tables in
`docs/vp9_oneoff_2026-08.md` §5.1 (mean of n=3, sd ≤5%, all 🟢). VP9 (`libvpx-vp9`) has no
GPU path on this box (no NVENC/VAAPI VP9 on NVIDIA or AMD) — software-only, which is also
true of the H.264/H.265/AV1 rows re-measured alongside it here (this campaign didn't touch
NVENC). Two operating points per encoder: `medium`/`preset10_default` = OWL/S53's usual
point; `slow`/`preset3`/`cpu-used1-2` = Jan Ozer's "everything-slow" set (see §4.2 of that
doc). **VMAF v1** (`vmaf_v1.0.16_3d0h`) — not the v0.6.1 used everywhere else in this file.

### `kranjska_isolated_video_ui_runs_2026-06`
Not a designed campaign — five one-off jobs run through the live `/video` UI (2026-06-19
through 06-29), found by grepping every stored result for "kranjska" and keeping the ones
that are encodes (the great majority of Kranjska hits are decode/playback rows from the
rig, out of scope here). Recovered because three of them land on **exactly the same fixed
bitrates** as `frozen_amd_typical_use_2026-05-22` (H.264 4000 / H.265 2000 / AV1 1500
kbps) — so this is that finding's missing sport-tier row, on current NVENC hardware:

- **`2026-06-20_1efc7e0d`** (GPU-only), **`2026-06-20_62bf87ae`** and **`2026-06-29_c017beb2`**
  (both `all_codecs`, CPU+GPU) — all read the **canonical** `kranjska_dh_120s.mp4`. VMAF and
  achieved bitrate repeat exactly within a codec across these three jobs (fixed-CBR NVENC/x264
  encodes are deterministic given identical input+settings) — only `delta_e_wh` differs, so
  read these as **3 independent GPU-energy reps and 2 independent CPU-energy reps** at each
  bitrate, not 3 independent quality measurements.
- **`2026-06-19_f2c2ac40`** — **flagged, do not pool.** It reads a *different* source file,
  `kranjska_dh_120s.webm` (a pre-canonicalisation master), not the `.mp4` every other row
  uses. Same codec (H.264) and identical bitrate (4000 kbps) but VMAF lands at 46–47, a
  ~23-point gap from the 69–70 the `.mp4`-sourced rows score at the same setting — almost
  certainly the webm ancestor was already-lossy. Kept in the CSV (`notes` column marks it
  `*** ANOMALOUS ***`) so it's visible rather than silently dropped, but exclude it from any
  average.
- **`2026-06-29_36879b34`** — the **full 6:40 clip**, not the 120s extract, at the same three
  bitrates. Different content window (`clip=kranjska_full`), so don't average it in with the
  120s reps above; it's its own row, useful mainly as a longer-duration sanity check.

**The headline this recovers:** at the *same* "typical use" bitrates that produce VMAF 92–94
on Meridian and BBB, Kranjska lands at **VMAF 47–70** — H.264 highest (~70), H.265 lowest
(~50–58), AV1 in between (~50–54) at its comparatively starved 1500 kbps. That's the sport-tier
content-complexity effect the S53 sweep's own methodology note already flags (`parity.py`:
"ladder tops out BELOW the VMAF-92 target" for Kranjska) — this is the concrete number for it.
**Caveat:** none of these rows went through the S53 harness's repeat-to-≥20s-window energy
trick, so every GPU row here carries 🟡 confidence (short single-pass window), same underlying
issue the harness was built to fix — treat energy numbers as indicative, not to the same
standard as the `s53_*` datasets' 🟢 rows.

### `readysetgo_iso_bitrate_sweep_2026-08-28` + `readysetgo_abr_ladder_typical_2026-08-28` + `readysetgo_iso_quality_interpolated_2026-08-28`
Source: `results/calibration/_staging/encode_parity_readysetgo_2026-08-28_final.json`
(84 rows, GoS1: Ryzen 9 7900 / RTX 5080 NVENC, `ffmpeg N-124403`, same rig/software as
every other 2026-08 row in this file). Run through `docs/smpte_2026/run_sport_clip_sweep.py`
— a self-contained script that does not touch `wattlab_service/parity.py`, `/video/budget`,
or any other live-serving *code path* (injects the clip into `parity.CLIPS` in-process
only). **Uses the exact same per-codec bitrate ladder as
`s53_iso_bitrate_sweep`/`s53_abr_ladder_typical`** (`MATCHED_BITRATES` in that script,
frozen independently of `parity.FULL_BITRATES` so it can't drift). 84/84 rows, all 🟢,
`complete=True`, 4596.7s wall-clock.

**Caught a second live-site regression (2026-08-29, same class as the S70 one).** The
sweep's raw/rescored/final JSON artifacts were first written straight to
`results/calibration/` alongside the canonical `_plus_ext.json` file — matching every
other campaign's own convention, but `budget_data.latest_artifact_path()` picks "newest
complete `encode_parity_*.json` by mtime" for `/video/budget`, with no clip-set filter.
For roughly the time between the sweep finishing and this being caught, `/video/budget`
and `data.csv` were serving the 84-row ReadySetGo-only artifact instead of the 240-row
canonical one. Fixed by moving both files into `results/calibration/_staging/` (out of
`ARTIFACT_GLOB`'s reach, same fix S70 used for its own stray extension file) and
verified: `latest_artifact_path()` back to the `_plus_ext.json` file, `data.csv` back to
240 rows (84 bbb + 84 meridian + 72 kranjska, zero readysetgo). **Lesson for next time:**
any encode-parity artifact that lands in `results/calibration/` directly is live-serving
surface by construction of that glob, regardless of what the script that produced it
touches — write new/experimental artifacts to `_staging/` from the start, not as an
after-the-fact fix.

**Mid-run correction (same bug class as the 2026-08-28 bitrate-ceiling extension, see
above).** The sweep scored VMAF under the live service's then-current default
(`vmaf_model=v1`), not the v0.6.1 every other row in this file uses. Fixed the same way:
re-encoded all 84 rows' stored `ffmpeg_cmd` (deterministic CBR encode, no re-measurement)
and rescored under an in-process `vmaf_model=v0` override
(`bin/rescore-readysetgo-v0.py`) that never touched the live `settings.json`. `vmaf` in
the CSV is the v0.6.1 rescore; the original v1 score is kept in the artifact under
`vmaf_v1_bonus` (not carried into the CSV — no other row in this file carries it either).
Field-renaming step: `docs/smpte_2026/finalize_readysetgo_v0.py`.

**The result this campaign was run to get: does the matched ladder need extending to
reach VMAF 92, the way BBB/Meridian needed the 08-28 ceiling extension for 94/96?**
**No.** `docs/smpte_2026/readysetgo_iso_vmaf_table.csv` (generated by
`make_readysetgo_iso_vmaf_table.py`, the standalone analogue of `make_iso_vmaf_table.py`)
has **zero empty cells** — every one of the 9 codec×profile combinations reaches VMAF 96,
let alone 92, within the existing matched ladder (e.g. h264/cpu hits 93.98 at 6000 kbps,
already past the 4500 kbps rung below it; av1/cpu hits 92.46 at 4000 kbps). No extension
campaign is needed for this content — unlike BBB/Meridian, ReadySetGo's ladder already
brackets the full 88–96 target range for every codec and profile.

**Content characterisation — measured, not assumed.** Ran `pixop.probe_siti()` (the same
ITU-T P.910 SI/TI tool `/enhance-run` uses, terminal-only, no energy impact) on the
30s reference clip: **SI≈38.5, TI≈40.4** (full-clip pass). That's a genuinely different
complexity profile from Kranjska (SI≈101/TI≈45 — extreme on *both* axes): ReadySetGo is
high-*temporal* (fast horse-race motion, comparable TI to Kranjska) but only
moderate-*spatial* (SI close to BBB's 33, well below Kranjska's 101). Read this as a
cleaner, less confounded "sport" tier than Kranjska for a content-complexity axis, precisely
*because* it isolates high motion without also stacking extreme spatial detail — see caveat 9.

**Clip preparation** (2026-08-28, see chat log): sourced as `ReadySetGo_3840x2160_120fps_
420_10bit_YUV.yuv` — decoded and verified as genuine `yuv420p10le`, 3840×2160, 120fps
(not the "8bit"/implied-60fps guess it arrived under), 600 frames = 5.0s, confirmed
limited/TV-range (10-bit legal-white ceiling pinned at 944 across the whole clip, opposite
of KartingTime's full-range master — see below). Converted with:
`select='not(mod(n\,2))',setpts=N/(60*TB)` for an exact 2:1 frame-drop to 60fps (no
blending — matches BBB/Meridian's frame rate and halves `parity.py`'s fixed-120-frame GOP
back to the same 2.0s GOP duration the other clips get), `zscale=in_range=limited:
range=full` to stretch to full range (Tania's call, matching how BBB/Meridian/KartingTime
are treated), `format=yuv420p` for the 10-bit→8-bit reduction (chroma was already 4:2:0),
tagged `bt709` (Tania's call on primaries — genuinely unresolvable from pixel stats alone).
Looped to 2100 frames/35.0s so `ensure_clip()`'s `-t 30` trims to an exact 30.000s window
with margin. Final master: `test_content/readysetgo_30s_looped.mp4` (CRF14, ~205 Mbps,
`yuvj420p`/`color_range=pc`/bt709 — the `yuvj420p` tag is ffmpeg's canonicalisation of
"8-bit 4:2:0 + full range," not a different format from BBB/Meridian's plain `yuv420p`).
**Content, confirmed (Tania, 2026-08-29):** the horse-racing starting-gate scene under
"Türkiye Jokey Kulübü" signage is `ReadySetGo`, sequence 5 of 16 in the **Ultra Video
Group (UVG) dataset** (Tampere University) — see full citation and license below.
A second candidate clip, KartingTime (also sourced 2026-08-28, converted full-range /
8-bit / 60fps-native / bt709), was prepped alongside this one but is **not** wired into
any dataset here — see chat log 2026-08-28 if it's needed later.

## Caveats to carry into the paper

1. **Two VMAF model versions in one file.** `s53_*` and `frozen_amd_*` rows are **VMAF
   v0.6.1** (OWL's default model pre-S55). `vp9_vs_trio_sweep_2026-08-17` is **VMAF v1**.
   Never compare a VMAF number across that boundary — compress/energy comparisons are fine,
   quality-score comparisons are not.
2. **Two GPU generations.** `frozen_amd_typical_use_2026-05-22` is AMD RX 7800 XT
   (VAAPI). Every other GPU row is RTX 5080 (NVENC), measured after the 2026-05-29 swap.
   AV1 in particular: the AMD `av1_vaapi` behaviour (from `av1-hw-sw-vmaf-tradeoff.md`) is
   explicitly *not* the same encoder as NVENC AV1.
3. **Iso-quality rows are interpolated, not measured.** `s53_iso_quality_interpolated`
   bitrates/energy are linear interpolation between real sweep points (`notes` names the
   two bracketing points as `sweep_points`). Treat as "expected," and if the paper needs a
   truly-measured iso-quality point, that's an unshipped CR-045 V2 feature (see below) —
   you'd need to run a targeted bitrate search, not read it off this table.
4. **Achieved ≠ target bitrate.** `s53_*` rows report `achieved_kbps` from the actual
   encoded output (one-pass ABR misses its target, especially on short clips) — use
   `achieved_kbps` for rate-quality curves, `target_kbps` only to identify the sweep point.
   The VP9 sweep also missed its targets by up to +46% (see `docs/vp9_oneoff_2026-08.md` §5.1
   caveat 4) — `achieved_kbps` is given for those rows too, use it the same way.
5. **Content-complexity labels were corrected 2026-06-19.** BBB is the *high*-complexity
   clip (SI≈33/TI≈6), Meridian is *low* (SI≈13/TI≈2) — the opposite of their earlier
   reputations, which is why some older OWL prose (and the `abr-all-codecs-meridian-120s`
   finding's own caveats) call Meridian "high complexity." The `complexity` column here uses
   the corrected, SI/TI-measured labels. Kranjska (see below) is the outlier: high on *both*
   axes.
6. **n and repeat structure differ by dataset.** `s53_*` rows are single measurement points
   (n_encodes handles the repeat-to-20s-window energy trick within one row, not statistical
   replication — `n=1` day-to-day). `vp9_vs_trio_sweep_2026-08-17` rows are genuine n=3
   across separate reps (sd reported in the source doc, not carried into this CSV — pull it
   from `docs/vp9_oneoff_2026-08.md` §5.1 if you need error bars on those rows specifically).
   `frozen_amd_typical_use_2026-05-22` is n=1.
7. **NVENC "tuned" profile is a rejected config, not a recommendation.** `gpu_tuned` rows
   exist to show what a quality-knob bundle costs/buys (§9.3 of the methodology doc found it
   mostly *not* worth it — lowers VMAF for H.264/AV1, only helps H.265 at low bitrate, costs
   1.6–2.8× the energy). Don't read `gpu_tuned` as "the better GPU setting" — `gpu_baseline`
   is what OWL's live `/video` page actually ships.
8. **The Kranjska isolated runs are weaker evidence than everything else in this file.**
   They're recovered ad hoc jobs, not a designed campaign: no repeat-to-window energy
   protocol (GPU rows are 🟡, not 🟢), n=1–3 per point depending on how many of the five
   jobs happen to cover it, and one of the five (`f2c2ac40`) reads a different source file
   entirely — see its dataset section above before using it.
9. **Kranjska is not resolution/aspect/frame-rate-matched to BBB/Meridian — flagged by
   Tania 2026-08-28, resolved same day/next day with ReadySetGo.** Every `s53_*` dataset
   lists Kranjska as a "sequence" alongside BBB/Meridian, but it runs at its native
   1920×1440 (4:3), 30fps, while BBB/Meridian are 3840×2160 (16:9), 59.94/60fps. That's
   three axes differing at once — pixel count (~1/3), aspect ratio (not a crop, a
   different frame), and frame rate — not just "lower res." OWL's own encode energy is
   pixel-throughput-bound (`docs/input_sensitivity_findings.md`), and VMAF-at-fixed-bitrate
   is resolution-sensitive too, so any bitrate/VMAF/energy gap between Kranjska and
   BBB/Meridian in the `s53_*` tables is confounded — some of it is content complexity,
   some is format. **Do not present Kranjska as a resolution-matched third leg of a
   controlled content-complexity comparison.** It stands on its own as the native-format
   complexity extreme (SI≈101/TI≈45).
   **ReadySetGo (`readysetgo_*_2026-08-28` datasets, above) is the matched clip this
   caveat asked for:** 3840×2160 (16:9), 60fps (decimated 2:1 from a 120fps native master,
   not a native 60fps capture — see its provenance section for why that's still a fair
   match: same displayed frame rate and GOP duration as BBB/Meridian, no blended frames),
   8-bit 4:2:0, full-range, bt709 — same format axes as BBB/Meridian on every axis that
   matters for pixel-throughput-bound energy and VMAF-at-fixed-bitrate comparisons. Its
   measured SI≈38.5/TI≈40.4 is a cleaner "sport" tier than Kranjska for a controlled
   content-complexity comparison specifically because it isolates high temporal motion
   without also stacking Kranjska's extreme spatial detail. **Use ReadySetGo, not
   Kranjska, as the third leg of any format-matched "codec × content tier" claim; keep
   Kranjska as a separate, additional complexity-extreme data point, not part of that
   controlled comparison.**

## Is CR-045 blocking this?

**No.** CR-045 is a UI feature — a radio toggle on OWL's live `/video` all-codecs comparison
page so a visitor can pick "Same bitrate / Typical use / Constant quality" and get a
framed, visitor-facing answer without touching raw data. It has not shipped, but the
*data* it would toggle between already exists and is what this CSV assembles by hand:
`s53_iso_bitrate_sweep` **is** "same bitrate" mode; `s53_iso_quality_interpolated` **is**
the "constant quality" (V2, target-VMAF) mode's answer, just computed offline instead of
through a live binary-search UI control.

The one place CR-045 not shipping actually matters for the paper: its proposed "Typical
use" bitrate set (H.264 6000 / H.265 3500 / AV1 2500 kbps) is explicitly **provisional** —
"Tania to confirm against Bitmovin/Netflix tier guidance" is still open in
`CHANGE_REQUESTS.md`. Treat those three numbers as a draft, not a citable OWL-confirmed
figure. What *is* solidly measured for "typical operating points" is
`s53_abr_ladder_typical` (72 rows above) and the single AMD-era point in
`frozen_amd_typical_use_2026-05-22` — cite those instead, or state your own operating
points explicitly (which is the house style anyway — see `docs/vp9_oneoff_2026-08.md`'s
"operating points — state them, they are the result").

## What is Kranjska?

`kranjska_120s` is a 120 s extract of **downhill mountain-bike POV footage from Kranjska
Gora** (a resort town in Slovenia — the clip is mountain biking, not skiing, despite the
name association), sourced from Wikimedia Commons
(`Downhill_bike_park_Kranjska_Gora.webm`, © Maks Berc, CC BY 3.0). 1920×1440, 30fps.

It's OWL's **"sport" content tier** — measured SI≈101 / TI≈45 (ITU-T P.910), the highest
spatial *and* temporal complexity source on the bench, well above BBB (SI≈33/TI≈6, spatial
only) and Meridian (SI≈13/TI≈2, easy). It was added to the encode-parity campaign
specifically so the 3-sequence sweep spans the full complexity range operators actually
see — cinematic/talking-head (Meridian), animated/high-detail (BBB), and fast-motion
handheld action (Kranjska) — rather than judging codec behaviour off one or two easy clips.
It's also used on the decode side (`docs/vp9_oneoff_2026-08.md` §5.2, `decode_batch.py`)
as the highest-motion of the three iso-bitrate decode test contents.

## What is ReadySetGo?

`readysetgo_30s` is a 30 s (looped from a 5 s master, see its provenance section above)
extract of `ReadySetGo` — horse-racing starting-gate footage (Türkiye Jokey Kulübü),
sequence 5 of 16 in the **Ultra Video Group (UVG) dataset**, Tampere University,
native 3840×2160/120fps/10-bit/4:2:0/limited-range, converted here to match BBB/Meridian's
format (60fps, 8-bit, full-range, bt709 — see conversion details above). **License:
Creative Commons BY-NC (non-commercial, attribution required)** — narrower than
Kranjska's CC BY 3.0 (which permits commercial use); fine for this research paper, but
don't redistribute the source video itself outside a non-commercial context. **Citation:**
A. Mercat, M. Viitanen, and J. Vanne, "UVG dataset: 50/120fps 4K sequences for video codec
analysis and development," in *Proc. ACM Multimedia Syst. Conf.*, Istanbul, Turkey,
Jun. 2020. Dataset page: `ultravideo.fi/dataset.html`.

Measured SI≈38.5/TI≈40.4 (ITU-T P.910, `pixop.probe_siti()`) — OWL's format-matched
**sport tier**: high temporal motion (fast horse-race panning, TI comparable to
Kranjska's 45) without Kranjska's extreme spatial detail (SI 38.5 vs 101, closer to
BBB's 33). It's the clip caveat 9 (below) asks for: same resolution/aspect/frame-rate as
BBB/Meridian, so any bitrate/VMAF/energy gap against them is real content-complexity
signal, not confounded by format differences the way Kranjska's comparisons are.

## Files

- `consolidated_encode_dataset.csv` — the 569-row combined table described above.
- `iso_vmaf_table.csv` + `make_iso_vmaf_table.py` — pre-existing, feeds the
  `s53_iso_quality_interpolated` rows (BBB/Meridian/Kranjska, from the live canonical
  artifact — do not point this at ReadySetGo, see below).
- `readysetgo_iso_vmaf_table.csv` + `make_readysetgo_iso_vmaf_table.py` — the standalone
  ReadySetGo analogue, reading `encode_parity_readysetgo_2026-08-28_final.json` directly
  (never the live `/video/budget` artifact). Feeds `readysetgo_iso_quality_interpolated_2026-08-28`.
- `run_sport_clip_sweep.py` — the self-contained campaign script that produced the raw
  ReadySetGo sweep. `finalize_readysetgo_v0.py` — the vmaf v1→v0.6.1 field-rename step
  (mirrors `bin/merge-bitrate-ext.py`). `append_readysetgo_to_consolidated.py` — the
  one-shot script that appended the three `readysetgo_*` dataset blocks into the CSV.
- Raw sources: `results/calibration/encode_parity_nvenc_24c_2026-06-20.json`,
  `results/diagnostics/encode_parity_nvenc_24c_2026-08-17.json`,
  `video/e18a9d57.json` (via `docs/findings/abr-all-codecs-meridian-120s.md`),
  `results/video/2026-06-19_f2c2ac40.json`, `results/video/2026-06-20_1efc7e0d.json`,
  `results/video/2026-06-20_62bf87ae.json`, `results/video/2026-06-29_36879b34.json`,
  `results/video/2026-06-29_c017beb2.json`,
  `results/calibration/_staging/encode_parity_readysetgo_2026-08-28.json` (raw, v1-scored) →
  `..._final.json` (v0.6.1-rescored, the one the CSV rows above cite). **Both in
  `_staging/`, not `results/calibration/` directly** — see the regression note above.

---

## Addendum 2026-09-04 — the football sports tier (versioned copy, Tania's file untouched)

*Added by Ben's overnight session 2026-09-03/04 (CR-081). Nothing above was edited; the rows live in a
**new versioned file**, `consolidated_encode_dataset_2026-09-04.csv` = this file's 569 rows + 129 football
rows. Adopting it as the canonical file is Tania's call.*

Three new `dataset` values, mirroring the ReadySetGo ones:

| `dataset` value | Rows | Source |
|---|---|---|
| `football_iso_bitrate_sweep_2026-09-03` | 60 | `results/calibration/_staging/encode_parity_football_2026-09-03_final.json` |
| `football_abr_ladder_typical_2026-09-03` | 24 | same |
| `football_iso_quality_interpolated_2026-09-03` | 45 | `docs/smpte_2026/football_iso_vmaf_table.csv` |

**Clip:** `football_30s` — Panasonic's "Barcelona Football" 4K demo as re-uploaded to YouTube
(3840×2160@60 SDR AV1 as served), 50–85 s excerpt re-wrapped as 4K60 H.264 High ~40 Mbps limited-range
bt709 (`test_content/football_35s.mp4`; `ensure_clip()` trims the 30 s window). **Lab-internal only:**
© Panasonic, third-party upload, no citable licence — the measurements are usable, the pictures are
never shown or redistributed outside the lab (owner's decision 2026-09-03). Broadcast-style coverage
(long-lens follow pans, cuts); SI ~48.3 / TI ~10.3 (ffmpeg `siti` on the 1080p 30 s trim) — much higher
spatial detail than ReadySetGo (SI ~38.5) at a fraction of its temporal activity (TI ~40.4).

**Protocol:** identical to the ReadySetGo leg — `run_football_clip_sweep.py` is a constants-only clone of
`run_sport_clip_sweep.py` (84 rows, frozen BBB/Meridian ladder, 30 s, 5-poll baseline, 10 s cooldown,
S53 harness — so it carries the same three integrity gaps `CLEAN_SWEEP.md` documents), ran 22:58–00:09,
all 84 rows 🟢. Scored live under VMAF v1, then rescored under v0.6.1 (`bin/rescore-football-v0.py`,
`finalize_football_v0.py`) so `vmaf` matches the dataset convention; v1 kept as `vmaf_v1_bonus`.

**One row flagged for a recheck:** `h264 / gpu_tuned / 13000k` measured ΔW 32.5 W / 0.147 Wh/min against
49–52 W / 0.22 on both neighbours (still 🟢 by the harness's own test). A separate three-row re-measure
(`run_football_recheck.py` → `encode_parity_football_recheck_<date>.json`) runs after the decode
campaign; the main artifact is left as measured.
