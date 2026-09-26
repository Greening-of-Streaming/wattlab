# Review — `SMPTE_MTS_2026_energy_vs_bitrate.docx`

**Reviewed:** 2026-09-21 · **Draft reviewed:** file dated 2026-09-18 12:40 (Tania)
**Prompted by:** proof-reader comment that the codec table gives rate control / GOP /
profile / B-frames but no preset or tuning, which limits reproducibility.
**Companion note:** `codec_settings_for_paper.md` in this folder holds the paste-ready
table, prose and command appendix for item A. This file is the full review.

**Provenance rule applied throughout.** Nothing below is recalled or inferred. Command
lines are the `ffmpeg_cmd` strings stored verbatim in the campaign artifacts under
`results/calibration/`; library versions and *effective* defaults were read back out of
the encoders on 2026-09-18 by running the same binary that produced the dataset
(`/usr/local/bin/ffmpeg-master`, mtime 2026-05-07, unchanged since before the campaign)
at 1080p and capturing the x264 SEI options string, the `x265 [info]` config dump and the
`Svt [config]` banner; NVENC defaults are from `ffmpeg -h encoder=*_nvenc` on that binary.
The bench was idle when probed (79.2 W, queue empty, no locks held) — nothing was
contaminated.

Severity key: **[BLOCKER]** would be caught in review · **[FIX]** factually wrong as
written · **[ADD]** missing, needed for reproducibility · **[NIT]** editorial.

---

## A. The preset gap — §3.3 *Codecs and Implementations* / Table 2 **[BLOCKER]**

This also resolves the existing Word comment on Table 2's caption
(*"To verify on GoS1"*, Tania, 2026-09-01).

**The finding is simpler than expected: no `-preset` was passed on any row.** All six
configurations ran at their library/wrapper default, with only the *normalised*
parameters overridden (GOP, profile, B-frames, rate-control mode, output resolution,
audio). That is the real normalisation rule and it is defensible, but it has to be
stated, because "default" is a different point on each encoder's dial — and on SVT-AV1
it is a notably fast one.

So the paper does not owe the reader a preset-selection rationale. It owes three things:
the defaults named with versions, one sentence on why defaults, and one sentence
disclosing that the ranking is operating-point dependent.

### A1. Two columns to add to Table 2 **[ADD]**

| Codec / Impl. | Encoder (version) | Preset as run | Tuning | What that default is |
|---|---|---|---|---|
| AVC / CPU | libx264, core 165 | `medium` (ffmpeg default, not overridden) | none | ref=3, subme=7, me=hex, trellis=1, rc-lookahead=40, mb-tree on, AQ 1:1.00 |
| AVC / GPU | h264_nvenc | `p4` (NVENC default) | `hq` (default) | single-pass, rc-lookahead 0, spatial/temporal AQ off |
| HEVC / CPU | libx265, 4.1+241-cfee9638 | `medium` (x265 default, not overridden) | none | rd=3, subme=2, me=hex, ref=3, b-adapt=2, lookahead 20, AQ mode 2, cu-tree on |
| HEVC / GPU | hevc_nvenc | `p4` (NVENC default) | `hq` (default) | single-pass, rc-lookahead 0, spatial/temporal AQ off |
| AV1 / CPU | libsvtav1, SVT-AV1 v4.1.0-7-gb486d839 | **`preset 8`** (SVT default, not overridden) | `PSNR` (SVT default) | random-access prediction structure, mini-GOP 16, AQ mode 2 |
| AV1 / GPU | av1_nvenc | `p4` (NVENC default) | `hq` (default) | single-pass, rc-lookahead 0, spatial/temporal AQ off |

### A2. Toolchain line to add under Table 2 or in §3.1 **[ADD]**

> All encodes used FFmpeg `N-124403-g28ecb07e55` (2026-05-07) with x264 core 165,
> x265 4.1+241-cfee9638 and SVT-AV1 v4.1.0-7-gb486d839; NVENC encodes ran on an NVIDIA
> RTX 5080 (Blackwell), driver 610.43.02. CPU encodes used the encoders' automatic thread
> detection on 24 logical cores (no `-threads` cap); all encodes ran at elevated
> scheduling priority (`nice -n -5`).

### A3. Justification paragraph for §3.3 **[ADD]** (~140 words, drop-in)

> Presets were deliberately left at each encoder's own default rather than equalised to a
> nominal "same speed" point across libraries: preset scales are not comparable between
> x264, x265, SVT-AV1 and NVENC, so any cross-encoder alignment would itself be an
> arbitrary choice. Defaults are also the operating point an implementer reaches first,
> and the point the OWL platform ships for its public measurements. Only the parameters
> that must match for the comparison to be meaningful were overridden — GOP length,
> profile, B-frame count, rate-control mode, output resolution and audio.
>
> We note that this places SVT-AV1 at preset 8 of 0–13, towards the fast end of its dial,
> whereas x264 and x265 sit mid-dial at `medium`; AV1's CPU energy figures should be read
> accordingly. Encoder speed setting is the dominant lever on encoding energy, and codec
> ranking by energy is operating-point dependent. The results below therefore
> characterise these codecs *at their default operating points*, not at their
> energy-optimal ones.

### A4. Appendix of verbatim command templates **[ADD]**

Twelve lines that make the whole configuration section unambiguous. Full block is in
`codec_settings_for_paper.md` §6. Add after it:

> `scenecut=0` / `open_gop=0` / `scd=0` pin a closed, fixed 120-frame GOP on all three
> software encoders, so GOP structure does not vary with content.

That detail is currently implicit in Table 2's "GOP 120" column and is exactly what a
reproducer would otherwise get wrong.

---

## B. Factual corrections

### B1. §3.3 / Table 2 — AV1 / CPU rate control is **VBR**, not ABR **[FIX]**

SVT-AV1's own config banner reports `BRC mode / target bitrate: VBR / <n>` when given
`-b:v`. x264 reports `rc=abr` and x265 reports `ABR-<n> kbps`, so those two rows are
correct as written.

- **Current:** AV1 / CPU · "ABR (`-b:v`)"
- **Suggested:** "one-pass VBR (`-b:v`)", and add "one-pass" to the AVC/HEVC CPU rows for
  symmetry.

### B2. §3.3 / Table 2 — "B-frames: n/a" for AV1 needs a footnote **[FIX]**

True that no `-bf` was passed, but as written it reads as "no bi-prediction", which is
wrong: SVT-AV1 used its default random-access hierarchical prediction structure with a
16-frame mini-GOP.

- **Suggested footnote:** *"AV1 has no `-bf` equivalent; SVT-AV1 used its default
  random-access hierarchical prediction structure (mini-GOP 16). `av1_nvenc` was run
  without B-frames."*

### B3. §3.3 / Table 2 — AV1 / GPU profile "n/a" is right, but say why **[NIT]**

`av1_nvenc` exposes no `-profile` option at all in this FFmpeg build. Better as an
explicit footnote than a blank cell, which reads as an omission.

### B4. §3.1, §5.1 and §6 — companion-paper citation is the wrong number **[FIX]**

The companion paper (Schwarz et al.) is **[27]**. **[26]** is Afzal et al., *A Survey on
Energy Consumption and Environmental Impact of Video Streaming*. §2.3 gets this right;
three other places do not.

| Where | Current | Should be |
|---|---|---|
| §3.1, "…can be found in the companion paper by Schwarz et al. **[26]**" | [26] | **[27]** |
| §5.1 Limitations, "Our companion paper (Schwarz et al. **[26]**) demonstrates…" | [26] | **[27]** |
| §6 Conclusion, "…interact across the full delivery chain **[26]**" | [26] | **[27]** |

### B5. §3 opening — wrong forward reference to the research questions **[FIX]**

- **Current:** "…used to answer the questions outlined in Section 2."
- The three questions are posed in the **Introduction (§1)**; §2 is Related Work.
- **Suggested:** "…outlined in Section 1."

### B6. §4.1 — broken cross-reference **[FIX]**

§4.1 opens with the literal string **"Error! Reference source not found."** where the
Figure 1 cross-reference should resolve. Needs the field updated before circulation.

---

## C. Reproducibility items that are *not* about presets

### C1. §3.2 / Table 1 — only the first **30 s** of each clip was encoded **[BLOCKER]**

Table 1's duration column gives the master length (120 s Meridian, 120 s BBB, 35 s
Football, 35 s ReadySetGo). Every measured row encoded a **30-second excerpt** trimmed
from the head of the master (`ffmpeg -t 30 -c copy`, `duration_s: 30` recorded in the
`protocol` block of every artifact on disk, all four clips, every leg of the campaign).

This does not affect the reported figures — energy and time are normalised per 1000
frames — but a reproducer following Table 1 would encode 120 s of Meridian and get
different absolute numbers, and would not know the excerpt is the head rather than a
representative sample.

- **Suggested:** add an "Encoded excerpt" column, or a footnote: *"All measurements
  encode the first 30 s of each sequence; Table 1 reports the full master duration."*

### C2. §3.2 / Table 1 — column header says "Duration (frames)", values are in seconds **[NIT]**

Values read "35 s", "120 s". Either relabel the column "Duration" or give frame counts
(Meridian 7248, BBB 7200, Football 2100, ReadySetGo 2100 at master length; ~1800 frames
for the 30 s encoded excerpt at 60 fps).

### C3. §3.3 — the GPU rows are a full GPU pipeline, the CPU rows a full CPU pipeline **[ADD]**

GPU rows decode and scale on the GPU (`-hwaccel cuda -hwaccel_output_format cuda`,
`scale_cuda=-2:1080`); CPU rows decode and scale on the CPU (`scale=-2:1080`). The
reported GPU energy therefore includes GPU decode and scaling, and the CPU energy
includes CPU decode and scaling.

This is the realistic deployment comparison and is the right call, but it is not "encoder
versus encoder in isolation", and the 2.2–6.6× GPU reduction headline will be read that
way unless stated. One sentence in §3.3 closes it. Reviewers who know NVENC will ask.

### C4. §3.3 — NVENC was not run at its fastest, and there is evidence **[ADD]**

`p4` is mid-dial (p1–p7). A quality-tuned NVENC arm — `-preset p7 -tune hq -multipass 2
-spatial-aq 1 -temporal-aq 1 -aq-strength 8 -rc-lookahead 32 -b_ref_mode middle` — was
measured across the same sweep and is present in the dataset as the `gpu_tuned` profile
(394 rows in the consolidated CSV). One sentence saying it exists and was excluded from
the reported comparison pre-empts the "you compared software-medium against
hardware-fastest" objection outright.

### C5. §3.4 — **n is never stated anywhere in the paper** **[BLOCKER]**

The dataset the results appear to draw from (`clean_iso_bitrate_sweep_2026-09-06`) carries
**three repetitions per condition**, which meets the primary-data bar agreed on the
WattLab call of 2026-09-03 (n=3 minimum for anything that leaves the room). The paper
simply does not say so, and GoS's own publication rule is that n and CI are stated.

- **Suggested, in §3.4:** *"Each clip × codec × hardware-profile × bitrate condition was
  measured in three independent repetitions (n = 3); reported values are the mean across
  repetitions."* Add the CI or spread treatment alongside it.

### C6. §3.4 / §4 — name the dataset artifact **[ADD]**

Three consolidated CSVs exist in this folder with different dates (`_2026-09-04`,
`_2026-09-07`, `_2026-09-08`, plus an undated original). The paper should cite exactly
one, by filename, date and row count, so the figures can be regenerated. The reported
Football HEVC values (CPU 0.241 vs GPU 0.036 Wh/1000 frames, §4.1) are consistent in
magnitude with the `clean_iso_bitrate_sweep_2026-09-06` rows — **please confirm that is
the leg used**, because it matters for C7.

### C7. §3.1 / §3.4 — the wait-for-idle claim is true only for the clean-sweep leg ⚠ **[BLOCKER if C6 says otherwise]**

§3.1 states the platform "waits for wall power to reconverge to the measured idle floor
between runs rather than sleeping a fixed interval", and §3.4 repeats it. That is correct
for the **2026-09-06 clean sweep**, which calls the active wait-for-idle dispatcher.

It is **not** correct for the earlier legs (`s53_*`, `readysetgo_*_2026-08-28`,
`football_*_2026-09-03/04`), which recorded `cooldown_s: 10` — a flat, unconditional
10-second sleep, never checked against actual power. That gap is documented in
`CLEAN_SWEEP.md` §"Why this exists", item 1, and is precisely why the clean sweep was run.

If any reported figure comes from a pre-clean-sweep leg, §3.1 and §3.4 overstate the
protocol for that figure. Worth confirming before submission — this is the kind of claim
a methodology reviewer checks.

---

## D. Unsupported assertions that have stored evidence — §5.1 *Limitations* **[ADD]**

Two claims currently stand without a citation, and both have artifacts on disk. Citing
them turns a hedge into a result:

1. *"preliminary tests using an AMD GPU on the same server suggest that the relative
   ordering and observations remain unchanged"* → `docs/gpu_swap_amd_baseline.md`
   (frozen AMD RX 7800 XT-era data, pre-2026-05-29 GPU swap).
2. *"limited tests performed using different GPU settings and clock optimizations did not
   seem to change overall conclusions, albeit affecting the absolute measurements
   slightly"* → `results/calibration/gpu_clock_sweep_2026-06-20.json`, catalogued as the
   finding `gpu-boost-overclocks-fixed-function-nvenc` (v2, prior-art positioned).

---

## E. Open items for Tania

1. **C6/C7** — confirm which consolidated CSV and which campaign leg(s) the figures come
   from. Everything in C7 hinges on it.
2. **Existing Word comment id=7** (*"Add citations to contents"*, on the §3.2 heading) —
   Table 1 already carries source and licence for all four sequences; is the comment
   asking for formal bibliography entries for the content itself (UVG/Mercat et al. is
   already [reference-worthy], Netflix Open Content and Blender are not conventionally
   cited)? Not resolved here.
3. **§3.5 is promised but does not exist** — the §3 opening says *"Section 3.5 presents
   the statistical treatment applied to the resulting measurements"*, and §4.3 refers to
   *"the variance-decomposition method described in Section 3.4"*, but Methodology ends at
   §3.4 (Experimental Design) and neither section describes the decomposition. Table 3's
   caption falls back on *"described above"*. This is one missing subsection causing three
   dangling references — and it is where C5's n statement belongs. **[BLOCKER]**

---

## F. Internal note — does not affect this paper

`docs/vp9_oneoff_2026-08.md` (§2 operating-points table) and the `preset10_default`
profile label in `consolidated_encode_dataset_*.csv` (`vp9_vs_trio_sweep_2026-08-17` rows
only) both record SVT-AV1's library default as **preset 10**. On the build used
throughout, it is **preset 8** — verified from the encoder's own banner. The SMPTE
paper's rows are unaffected, since they are the `cpu` / `gpu_baseline` profiles, but the
claim should not be carried across into the paper or the LinkedIn thread.
