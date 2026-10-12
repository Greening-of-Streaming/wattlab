# OWL capabilities for a VVC / AV2 talk (ACM MHV 2027 scoping)

*Read-only survey, 2026-10-12. No measurements were run and no config was changed. The only things executed
were `-version`/`-encoders` queries and a few 2–10-frame `testsrc` encodes into the scratchpad, to read
library versions and check VVC mux/decode. Each item is tagged **[checked]** (code, binary or stored result
read today) or **[inferred]** (docs, specs, or my own judgement, not verified on the device).*

## 1. Encode path

- **What a job is [checked].** `/video` jobs come from `video.PRESETS`: six ffmpeg recipes (libx264 / libx265 /
  libsvtav1 on the CPU; h264/hevc/av1_nvenc on the GPU). Each is ABR at the bitrate set in settings, scaled to 1080p,
  with a pinned GOP and AAC 128k. Every binary goes through `ffmpeg_bin` = `/usr/local/bin/ffmpeg-master`.
  `video.transcode()` runs the command under `nice -n -5`. There is no timeout.
- **Custom command [checked].** Members and above can replace a preset with a free-form string
  (`CUSTOM_PROMPT` capability). `apply_custom_cmd()` fills in `{input}`/`{output}` and splits the string with
  shlex. It only swaps a leading bare `ffmpeg` for `ffmpeg_bin`, so any argv[0] would execute (the binary is not
  validated, which is a hardening note in its own right). On `/video`, though, `run_single()` always appends
  `-progress pipe:1 -nostats`, writes the output to `<job>_out.mp4`, and then ffprobes it and optionally scores it
  with VMAF. A non-ffmpeg encoder such as vvencapp, EncoderApp or avmenc would fail on those flags. **In practice
  `/video` is ffmpeg-only, while any encoder that ffmpeg-master wraps (libvvenc included) works there today.**
- **`parity.py` harness (Lab, CLI via `bin/run-encode-parity`) [checked].** Calls `video.transcode(cmd)` with no
  progress callback, i.e. a plain `subprocess.run`. Any binary therefore works, but the command builders,
  `CPU_ENCODER` and the VMAF/ffprobe tail all assume ffmpeg and a container output.
- **20 s minimum window [checked].** This exists only in `parity._measure_recipe` (`min_task_s=20`): the encode
  is repeated back to back inside one baseline+task window until ≥20 s of wall clock has passed. The loop checks
  only after each encode finishes, so **a slow encoder runs exactly once and the window is that encode's full
  duration, however long.** Energy is normalised per content-second encoded (`wh_per_min_video`). `/video` itself
  has no minimum and no repeats: one encode, one window.
- **Max duration / timeout [checked].** There is none in `transcode()`, in `parity`, or in the queue worker
  (`queue_control`). A job runs until it ends or the service restarts, and a restart kills it (CLAUDE.md: never
  restart mid-job). **[inferred] consequences for VTM/AVM-speed encoders:** the baseline is taken once before
  the task, so over multi-hour windows idle-floor or ambient drift goes uncorrected. The fix is to trim clips with
  `Campaign.duration_s` (seconds of content, not 120 s) and report Wh per frame. A single-threaded reference
  encoder adds only one core's ΔW above the ~79 W floor. The CI copes with that over a long window, but the
  operating point has to be stated, and running N instances in parallel is a separate operating point.

## 2. Host (GoS1) decode

- **[checked]** The only built-in host-decode measurement is the `/prepare-rem` "decode split" (`rem_prep.
  build_decode_cmd` → `ffmpeg -i src [-vf scale] -an -f null -`). It runs **as fast as possible, unpaced**, as
  part of the REM-prep flow: encode = transcode − decode. It is not a standalone, user-selectable decode job.
- Paced host decode (`-re`), dav1d/vvdec CLIs, and a generic "decode this file" mode **do not exist**. Doing any
  of that today means an ad hoc script reusing `video.measure_baseline` / `poll_during_task`, the same pattern as
  `parity.py`.
- On the rig, `ffmpeg -re … -f null -` paced pure-decode rows exist for the **Pis** only (§3).

## 3. Client rig: launch path and VVC/AV2 plausibility

Rig registry is `rig.py` `RIG`; drivers live in `decode_bench/bench.py`; templates in `decode_run.py`; clips are
served by `origin.py` on GoS1 `:8123`.

| Device (driver) | How a clip plays today [checked] | VVC | AV2 |
|---|---|---|---|
| Pi 5, Pi 400 (`ssh`) | Clip staged to `/dev/shm/decode/`, then `ffmpeg -nostdin -re -i … -an -f null -` (paced pure decode), or `mpv --fs` for a display arm. The command string is free-form per run. | **Plausible.** Stock Bookworm ffmpeg 5.1 has no VVC decoder [inferred from docs; Pis were off, not checked]. Building ffmpeg ≥7.1 (native VVC decoder) or vvdec from source and pointing the cmd at it fits the harness unchanged. Real-time at 1080p is **unknown**. | **AFAP only, probably.** avmdec builds as plain C [inferred]. It is a reference decoder, so expect far below real time. Wh-per-file rows yes, playback rows no. |
| Google TV, Fire TV 4K, Bbox, Xiaomi Gen 2/3 (`adb`); W5 parked | VIEW intent → **Just Player** (`com.brouken.player`, 0.196 / GTV 0.212-legacy), `--ei position 0`, PLAYING checked, keep-awake + CEC pins | **No hardware decoder** on MT8696 / Marvell Berlin / S905X4 / S905X5M [inferred, SoC specs]. Just Player uses MediaCodec, so it cannot play VVC. A sideloaded VLC-Android nightly built with vvdec, or a custom player, is **unknown/untested**. Software decode on these ARM cores at 1080p is likely below real time, the same trap as W5/Bbox AV1. | **No** (no players, no hardware) [inferred]. |
| Apple TV 4K 2017, A10X (`atv`, pyatv) | Companion `launch_app` → VLC for tvOS x-callback stream URL. AirPlay `play_url` is dead on tvOS 18+. | **No** with stock VLC [inferred]. A custom VLCKit build with vvdec is weeks of work with an uncertain outcome (GoS is in the Apple Developer Program via LEM). | **No.** |
| Roku Express 4K (`roku`, ECP) | Dom's GoS channel 775528 via ECP launch + playlist rewrite | **No.** Closed platform, platform decoders only. | **No.** |
| LG C2 (`webos`) | `launch_url` in the built-in browser (rows are panel-dominated) | **No** [inferred]. | **No.** |

## 4. Playback validity (presented frame rate)

- **[checked] Not sampled automatically.** `bench.py` gates on PLAYING state (adb/ECP/pyatv), mid-window
  screenshot (adb), logcat decoder names (`CCodec`/`OMX`; Fire TV emits none), end-of-window liveness, and a
  flat trace. None of these measure presented fps. A row can pass every gate at 1.3–5 fps (W5 AV1, Bbox AV1;
  CR-078 addendum).
- **Ad hoc [checked, from memory + JOURNAL]:** on Android, `dumpsys SurfaceFlinger --latency '<Just Player
  SurfaceView layer>'` works on the **Bbox**. It returns 0 frames on the **GTV/Fire TV** (MediaTek sideband
  path), so those need eyes on the panel. Apple TV and Roku can be checked by eye only. On the Pis, `ffmpeg -re`
  rows have no presented fps (null sink), and real-time-ness must come from ffmpeg's `speed=` line, which is not
  recorded today. The gate is proposed in CR-078 and not built.
- For VVC/AV2 software decode, an automatic fps gate is a **prerequisite** for any client row.

## 5. Installed software

**GoS1 host [checked today]:**

| Component | `/usr/local/bin/ffmpeg-master` (OWL's binary) | `/usr/bin/ffmpeg` (apt) |
|---|---|---|
| ffmpeg | N-124403-g28ecb07e55 (2026-05-07 static build) | 6.1.1-3ubuntu5 |
| **VVC encode** | **libvvenc 1.15.0-dev** (`yuv420p10le` only, presets faster…slower) | none |
| **VVC decode** | **native `vvc` decoder** (+ `vvc_qsv`) | none |
| x264 | built in, version string not read (no SEI in test encode) | libx264 0.164.3108 |
| x265 | 4.1+241 | 3.5 |
| SVT-AV1 | v4.1.0-7 | 1.7.0 |
| libaom | v3.13.3 | 3.8.2 |
| dav1d | git `aa45047` | 1.4.1 |
| NVENC | h264/hevc/av1_nvenc (RTX 5080, driver 610.43.02) | same |

- Smoke test [checked]: 10 frames libvvenc → MP4 (`vvc1` tag) → decoded with the native decoder. **VVC already
  runs end to end through the ffmpeg path**, VMAF tail included [inferred for VMAF; decode itself checked].
- **Absent on GoS1 [checked, `command -v` + `find`]:** vvencapp, vvdecapp, VTM (EncoderApp/DecoderApp), HM
  (TAppEncoder/Decoder), AVM (avmenc/avmdec), dav2d, aomenc/aomdec, standalone x264/x265/SvtAv1EncApp/dav1d CLIs,
  mpv, vlc.
- **Pis [inferred, NOT checked: both were powered off, and I did not wake them]:** Raspberry Pi OS Bookworm
  64-bit with the distro ffmpeg 5.1 (+rpt patches), mpv, and dav1d via ffmpeg (`docs/pi_decode_energy_2026-07.md`).
  No VVC/AV2 tooling. Decode envelopes do not record the Pi's ffmpeg version, which is a provenance gap.

## 6. Throughput and bookings

- **Queue model [checked]:** single worker, one job at a time, exclusive hardware lock (`/tmp/gos-measure.lock`).
  Lab is uncapped; Members get 4 queued, Anonymous 1. A Lab session flag (with CR-083 reservations) blocks visitors.
  Rig `/decode` batches run one `bench.py` per device in parallel within one job.
- **Volume, 2026-08-01 → 10-12 [checked, file counts]:** about 1,000 decode envelopes, 288 video, 90 image and
  68 LLM results. Runs happened on 41 of 73 days, with a median of about 18 result files per active day and up to
  about 180 on all-night campaign days.
- **Booked through January [checked]:** `data/lab_reservations.json` is empty, and no CR carries a dated
  Oct–Jan campaign. Open items that will want rig/host time are all **unscheduled**:
  - Decode P110-refresh re-flag of 42 rows (waiting on Tania's decision).
  - Earthed-P110 wobble test, on arrival.
  - CR-079: ladder × resolution sweep (owner: "more important").
  - CR-078 and CR-080.
  - GoS2 idle re-measure after installs.

  Decode publication carries the P110-refresh caveat until that is resolved.

## 7. Gaps and rough effort

These estimates are my judgement, not measured. They assume one engineer familiar with the repo, and exclude
campaign wall-clock and Tania's review.

**(a) VVC encode + decode**

| Item | Effort |
|---|---|
| Host encode via libvvenc in `parity.py` (add a `vvc` codec, norm args, bitrates; 10-bit output caveat) | 2–4 h |
| Same as a `/video` preset (PRESETS, `hosts.codec_of_preset`, cards, envelope doc, tests) | 1–2 d (optional; custom cmd works today for one-offs) |
| VTM reference encode: build, plus a non-ffmpeg wrapper (YUV staging outside the window, `.266` → remux for VMAF, per-frame Wh) | 1–2 d, plus the long run times |
| Host decode harness, paced (`-re`) and AFAP, ffmpeg-vvc and vvdec | 0.5–1 d as a script; 2–3 d as an OWL mode |
| Pi decode: build ffmpeg ≥7.1 / vvdec on both Pis, VVC stream family, `decode_run` templates | 1–1.5 d |
| Presented-fps / real-time gate (Pi: record `speed=`; Bbox: SurfaceFlinger) | 1 d |
| Android: feasibility test of a VVC-capable sideloaded player | 1 d to answer yes or no; a custom build is 1–2 wk, uncertain |
| Apple TV / Roku / C2 | not feasible in this window |

**(b) AV2 encode + decode**

| Item | Effort |
|---|---|
| Confirm the AV2 spec / AVM release tag to pin (status not checked here) | 1 h |
| Build AVM (avmenc/avmdec) on GoS1 | 2–4 h |
| Encode wrapper (shares the VTM non-ffmpeg wrapper; output → VMAF needs an AV2-capable decoder → avmdec to YUV) | +0.5–1 d on top of VTM's |
| Host decode, AFAP Wh per file (avmdec) | 0.5 d (with the VVC decode harness) |
| Pi decode: AVM build on aarch64, AFAP rows only | 0.5–1 d |
| Client STB playback | **no path** (no players, no hardware) |

**Cross-cutting [inferred]:**
- Reference encoders (VTM, AVM) are likely seconds to minutes per 1080p frame. At the n=3 bar, plan short clips
  (a few seconds) and possibly sub-1080p rungs.
- Run a timing pilot before committing to a campaign grid (not run here, per the read-only constraint).
- State the operating point (preset, threads) for every claim.
