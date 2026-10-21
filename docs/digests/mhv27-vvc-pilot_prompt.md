# MHV'27 VVC pilot — run prompt (revised 2026-10-22 00:30)

MHV'27 VVC pilot on **GoS1 + GoS2**. Measurement session: runs are allowed this time.

## Context

We submit a talk abstract to ACM Mile-High Video 2027 by **Sat 24 Oct 13:59 Paris**. I need one night of VVC
pilot data, encode and decode, to quote in the abstract as Early Insight.

Read first: CLAUDE.md, JOURNAL.md (top index), docs/digests/mhv27-owl-capabilities.md,
docs/smpte_2026/CLEAN_SWEEP.md + run_clean_sweep.py (the harness to copy), docs/smpte_2026/codec_settings_for_paper.md
(how operating points were read back last time), and the two-node driver
`/srv/data/owl/campaign_2026-10-12_encode_sensitivity/driver.py` (how GoS2 was driven last week).

Follow all existing measurement rules: /bench-preflight, focus mode, exclusive lock, active wait-for-idle, never
restart the service mid-job, no pytest or heavy work on a node while it measures. Raise the Lab-session flag on
**both** nodes (`bin/lab-session-on`; GoS2 has its own) so visitors can't run jobs; lower both at the end. Do not
touch other campaigns, the 42 P110-refresh rows, `settings.json`, or the uncommitted work already in the tree
(`docs/enhance_bitrate_2026-10/`, the M6 draft finding). **No installs on GoS2** (its idle floor is tracked
per install).

**Deadline:** digest committed by **Fri 23 Oct 10:00 Paris**. If the full grid won't fit, cut it (fewer bitrates
first, then fewer repeats, never below n=3) and say what was cut.

## Facts already checked (2026-10-22, don't re-derive)

- The SMPTE paper is **#4951** (#4941 is the Pouli et al. companion). "SMPTE runs" below = the 4951 encode rows,
  clean protocol = `clean_iso_bitrate_sweep_2026` in `docs/smpte_2026/clean_sweep_2026-09-06.csv`.
- `meridian_120s.mp4` is **H.264 8-bit 4:2:0 SDR, 3840×2160, 59.94 fps**. The 30 s window = the first 30 s
  (`parity.ensure_clip(..., 30)`), 1798 frames. 10-bit encodes from an 8-bit source: the abstract must say so.
  (A true HDR10 Meridian master exists in `test_content/meridian_hdr/`, but it's a different 60 s window and PQ,
  where VMAF v0.6.1 isn't valid. Don't use it here.)
- ffmpeg-master `N-124403-g28ecb07e55` has libvvenc 1.15.0-dev (yuv420p10le only, presets faster…slower,
  default medium, **QPA on by default**) and the native `vvc` decoder (no hwaccel except vaapi).
- **libvvenc ignores `-g`.** A test with `-g 120` gave keyframes every 56 frames (its `-period` default is 1 s).
  Set the intra period with `-period 2` or `-vvenc-params IntraPeriod=120`, then **verify the real keyframe
  interval with ffprobe**. vvenc may force a multiple of its GOP size (32), e.g. 128; if so, state the value used.
- Speed: libvvenc medium did 11 fps on a 640×360 testsrc2 on 24 threads. *Inferred* at 1080p Meridian:
  ~1–2 fps, i.e. 15–30 min per 30 s encode, so **4–8 h for a 5-point × n=3 VVC grid**. The timing pilot decides.
- VMAF: the live setting is `vmaf_model = v1` (vmaf_v1.0.16). SMPTE used **v0.6.1**, so pin v0 per call
  (pass a settings override to `quality.compute_vmaf`); never edit settings.json. The scoring binary
  (`ffmpeg-score-20260717`) decodes VVC. 10-bit distorted vs 8-bit reference scores fine, but add an explicit
  `format=yuv420p10le` on the reference side so the conversion isn't left to ffmpeg's auto-negotiation.
- SMPTE ladders **do not bracket VMAF 92** on Meridian 1080p: HEVC's lowest rung (1500k) already scores 92.6.
  SVT-AV1 crosses 92 at ~1.2 Mb/s actual, and its VBR undershoots the target by about a third. Lower rungs are
  needed (scout below).
- `parity.run_campaign()` uses a flat 10 s sleep between rows, drops `baseline_elevated`, and doesn't evict the
  page cache. **Use `run_clean_sweep.py`'s loop** (real `power.cooldown_between_runs`, `baseline_elevated` kept,
  `posix_fadvise` eviction, output to `results/calibration/_staging/`). parity.py only supplies the codec and the
  command builder.
- **GoS2 (Apple M6)** = Homebrew ffmpeg 9.0.2: x265, SVT-AV1, native vvc decoder, libdav1d, libvmaf. **No
  libvvenc.** VideoToolbox has no VVC (or AV1) encoder, and `VTIsHardwareDecodeSupported` returns **true for
  HEVC and AV1, false for VVC**. So the M6 GPU can't encode or decode VVC. GoS2's role is the decode leg
  (Apple silicon, ~1–3 W idle, so paced decode resolves there in a way it can't on GoS1's ~79 W floor), run
  **in parallel** with the GoS1 encode grid.
- OWL's `/video` custom command can't do a null-sink decode (it appends `-progress` and forces an mp4 output),
  so GoS2 decode is an ad hoc script run on GoS2 from its own repo checkout (`~/wattlab`, same commit), using
  its `video.measure_baseline` / `poll_during_task` and its own meters (inner lab-G3 `.11`, outer lab-G2 `.22`).
  Pause GoS2's sensors poller during windows and hold GoS2's own lock.
- **Meter caveat:** GoS2's and the Pi's P110s are fw 1.3.1 (earthless), which refresh every **2 s below ~12 W**
  while OWL polls at 1 s. For rows on those meters, compute SE/CI on fresh (de-duplicated) samples, as in
  `docs/decode_p110_refresh_audit_2026-10-06.md`, and state the caveat.

## 0. Prep (GoS1, before any measurement)

1. Add a `vvc` codec to parity.py (`libvvenc`, intra-period handling as above) plus an opt-in 10-bit output
   option (default unchanged, so existing campaigns are untouched). Minimal, tested, own commit. Run the tests
   **now**, before any node measures.
2. **Unmeasured scout** on the 30 s window, same commands as the grid: x265 and SVT-AV1 at ~6 low-to-mid
   bitrates each (fast), and libvvenc at 2 bitrates. One of the libvvenc runs is the **timing pilot**: report
   wall time, CPU utilisation / thread count and projected grid time before launching. Score VMAF v0.6.1. From
   this, pick 4–5 rungs per codec that bracket VMAF 92 (*inferred* starting points: HEVC ~600–2000k, AV1
   targets ~800–2800k, VVC ~400–1500k).
3. Keep the scout encode nearest VMAF 92 per codec as **the decode stream** (record its actual bitrate and
   VMAF). This removes the encode→decode dependency, so GoS2 can start decoding while GoS1 runs the grid.
   Copy the three streams to GoS2 outside any window and check sha256 on both sides.

## A. Encode (GoS1, CPU only)

1. Content: Meridian, the 30 s window above. If time allows after everything else, add Football.
2. Everything 10-bit: one shared filter chain (`scale=-2:1080,format=yuv420p10le`) for all three encoders.
   libx265 Main10, libsvtav1 10-bit, libvvenc. GOP 120 (2 s; vvenc as verified above) and audio as SMPTE
   (AAC 128k). Default presets (x265 medium, SVT-AV1 preset 8, vvenc medium) and default threading. Record the
   exact operating point **read back from each encoder's log**: preset, rate-control mode and pass count, GOP /
   intra period, AQ/QPA, threads. Note: these 10-bit HEVC/AV1 rows are new measurements, not comparable 1:1 with
   the 8-bit 4951 rows.
3. Grid: the scout rungs, n=3 per point. VMAF v0.6.1 outside the energy window, on the actual output bitrate.
4. Report Wh/1000 frames (plus Wh/min of content, for 4951 comparability), mean ΔW, encode time, VMAF, actual
   bitrate, and the per-run confidence flag. Interpolate bitrate and energy at VMAF 92 per codec, as in 4951
   (`make_iso_vmaf_table.py` method), with 95 % intervals (bootstrap over reps or propagated t-CIs, and state
   which).

## B. Decode (GoS2 in parallel with A, then GoS1 after A)

Ad hoc script reusing `measure_baseline` / `poll_during_task` (parity.py pattern). Not an OWL mode yet. Same
script on both nodes. Record each node's ffmpeg version (they differ: master N-124403 vs 9.0.2).

1. Streams: the three decode streams from step 0.3, 10-bit 1080p.
2. Decoders: native `vvc`, native `hevc`, `libdav1d` on both nodes. **GoS2 adds two hardware arms:**
   HEVC and AV1 via `-hwaccel videotoolbox`, with the frames downloaded to system memory (state that). VVC has no
   hardware path on the M6, and that contrast is the point.
3. Two regimes, n=3 each:
   (a) as fast as possible: `-an -f null -`, with `-stream_loop` so the window is ≥ 20 s.
   (b) paced: `-re … -an -f null -` (the 30 s clip is already ≥ 20 s).
   Default threads. If time allows, add `-threads 1` AFAP as a weak-device proxy.
4. Report Wh/1000 frames, ΔW and the confidence flag. Capture ffmpeg `speed=` per run (not recorded today),
   so real-time-ness is on file.
5. Expect GoS1 paced decode to sit near or below its confidence floor. Report the flags honestly. A red flag is
   a result, not a failure.

## C. Stretch, time-boxed to 2 h, only if A and B are done

Power the Pi 5 on via the rig (it's off; idle-off is on, so release it afterwards). Stage a static aarch64 ffmpeg
build with the native VVC decoder in `/dev/shm` (don't replace the system ffmpeg; treat the download as untrusted).
Run the B streams paced on the Pi, n=3, with the meter caveat above. Record the ffmpeg version and `speed=`. If
it can't sustain real time, that's the finding: report it, don't tune around it.

## Output

`docs/digests/mhv27-vvc-pilot.md` + a per-run CSV + the generating scripts, in that folder, committed by name
(never settings.json). Push only on Ben's OK: the repo is public, and main currently carries 5 unpushed commits
that would go out with it. The digest contains:

- Versions (ffmpeg-master hash, ffmpeg 9.0.2 on GoS2, libvvenc, x265, SVT-AV1, dav1d) and operating points.
- Encode summary: at matched bitrate and at VMAF 92, VVC vs HEVC vs AV1 energy ratios and bitrate savings, with
  95 % intervals.
- Decode summary: Wh/1000 frames and ΔW per node × decoder × regime, plus `speed=`.
- One figure: energy per 1000 frames vs VMAF, three codecs, with error bars. Plus a decode bar chart (both nodes)
  if B produced confident rows.
- A Traffic Light status on each finding, and a short "what this does not show" list: two hosts, one clip, CPU
  encode only, 8-bit source → 10-bit, defaults (incl. vvenc QPA on), P110 refresh caveat on the GoS2/Pi rows.
- What was cut from the grid, and why.

Mark anything inferred rather than measured.
