# WattLab Service Overview and Video Encoding Report

Generated: 2026-05-07

This is a brief, structured map of the `wattlab_service` project and a detailed inventory of its video encoding tasks. The service powers a web UI for running workloads on the GoS1 lab server and measuring device-side energy use above idle baseline.

## 1. Service Structure

### Purpose

WattLab measures real server-side energy for selected workloads:

| Workload | What is measured | Main code |
|---|---|---|
| Video transcoding | CPU/GPU encode time, wall-power delta, Wh, output size, CPU/GPU thermals | `wattlab_service/video.py`, routed from `wattlab_service/main.py` |
| LLM inference | Wh, mWh/token, tokens/sec, CPU/GPU comparison, batch mode | `wattlab_service/llm.py` |
| RAG energy test | Retrieval-augmented vs baseline LLM energy paths | `wattlab_service/rag.py` |
| Image generation | Wh/image for Stable Diffusion Turbo models, CPU/GPU/model comparison | `wattlab_service/image_gen.py` |
| Live telemetry | P110 wall power, CPU temperature, GPU junction temperature, GPU PPT | `wattlab_service/power.py`, live cache in `wattlab_service/main.py` |
| Carbon enrichment | gCO2e from live/static grid intensity, attached to saved results | `wattlab_service/carbon.py`, called by `wattlab_service/persist.py` |
| Result storage/export | JSON persistence, summary lists, CSV flattening | `wattlab_service/persist.py` |
| Runtime settings | Baseline duration, cooldowns, confidence thresholds, bitrate targets | `wattlab_service/settings.py`, `/settings` in `wattlab_service/main.py` |
| Preloaded video sources | Netflix Meridian full and 2-minute extract registry | `wattlab_service/sources.py` |

### Runtime Flow

1. `wattlab_service/main.py` creates the FastAPI app, renders the HTML pages, exposes JSON endpoints, and owns the in-memory job queue.
2. The home page links to `/video`, `/image`, `/llm`, `/rag`, `/settings`, `/methodology`, and `/queue-status`.
3. A submitted workload is wrapped as a queued job. `queue_worker()` runs one job at a time and updates `jobs[job_id]` with stage/status/result.
4. Measurement modules take a baseline, run the workload, poll power once per second, compute delta energy, attach confidence, and return a structured result.
5. `persist.save_result()` writes `results/{job_type}/{date}_{job_id}.json` under `/home/gos/wattlab/results` and enriches each `energy` block with CO2e.

### Measurement Protocol

Common pattern across workload modules:

1. Measure idle baseline for `baseline_polls` one-second polls.
2. Run the task while polling Tapo P110 power once per second.
3. Compute:
   - `w_base`: mean baseline W
   - `w_task`: mean task W
   - `delta_w = w_task - w_base`
   - `delta_e_wh = delta_w * duration_seconds / 3600`
4. Classify confidence using configured variance and poll-count thresholds.
5. Save the result with scope text: device layer only; network, CDN, and CPE excluded.

### Important Operational Details

| Area | Behavior |
|---|---|
| Authentication | Optional password gate from `/home/gos/wattlab/.env`, using `WATTLAB_GATE_PASSWORD`. |
| Queueing | FIFO queue, max depth 8 including running job. External pause supported by `/tmp/owl-paused`. |
| Locking | Measurement modules write `/tmp/gos-measure.lock` while a workload is active. |
| Focus mode | Video/image measurement stops selected systemd background timers before a run and restarts them afterward. |
| Live telemetry | Two background pollers cache P110 power every 5s and `lm-sensors` CPU/GPU values every 2s. `/live` feeds UI badges. |
| Local-only writes | `/settings` write access and variance calibration require a private/loopback client address. |
| Uploaded videos | Accepted suffixes: `.mp4`, `.mov`, `.mkv`, `.avi`, `.webm`, `.ts`; max size 1 GB. Uploads land in `/tmp/wattlab_uploads`. |

## 2. Video Encoding Coverage

### Inputs

Video jobs can use either:

| Source type | Code path | Details |
|---|---|---|
| Upload | `POST /video/upload` | Browser upload to `/tmp/wattlab_uploads/{job_id}_in{suffix}`. Deleted after the job. |
| Preloaded source | `POST /video/use-source` | Registry in `wattlab_service/sources.py`; current keys are `meridian_4k` and `meridian_120s`. |

### Preset Matrix

Default bitrates come from `wattlab_service/settings.py` and can be changed from `/settings`. Custom ffmpeg commands on the video page override the preset command for that run.

| UI/API preset | Encodes run | Codec path | Default target | Function path |
|---|---:|---|---:|---|
| `cpu` | 1 | H.264 via `libx264` CPU | 4000 kbps | `run_video_measurement(..., "cpu")` |
| `gpu` | 1 | H.264 via `h264_vaapi` GPU | 4000 kbps | `run_video_measurement(..., "gpu")` |
| `both` | 2 | H.264 CPU then H.264 GPU | 4000 kbps | `run_both_measurement("cpu", "gpu")` |
| `h265_cpu` | 1 | H.265/HEVC via `libx265` CPU | 2000 kbps | `run_video_measurement(..., "h265_cpu")` |
| `h265_gpu` | 1 | H.265/HEVC via `hevc_vaapi` GPU | 2000 kbps | `run_video_measurement(..., "h265_gpu")` |
| `h265_both` | 2 | H.265 CPU then H.265 GPU | 2000 kbps | `run_both_measurement("h265_cpu", "h265_gpu")` |
| `av1_cpu` | 1 | AV1 via `libsvtav1` CPU | 1500 kbps | `run_video_measurement(..., "av1_cpu")` |
| `av1_gpu` | 1 | AV1 via `av1_vaapi` GPU | 1500 kbps | `run_video_measurement(..., "av1_gpu")` |
| `av1_both` | 2 | AV1 CPU then AV1 GPU | 1500 kbps | `run_both_measurement("av1_cpu", "av1_gpu")` |
| `all_codecs` | 6 | H.264, H.265, AV1, each CPU+GPU | per codec | `run_all_measurement()` |

### Commands Used by Presets

Every actual encode is executed by `transcode()` with this process prefix:

```bash
nice -n -5 <ffmpeg command below>
```

`nice -n -5` is not an ffmpeg option. It asks the OS to run ffmpeg with higher CPU scheduling priority.

#### H.264 CPU: `cpu`

```bash
ffmpeg -y -i {input} \
  -c:v libx264 -b:v 4000k \
  -vf scale=-2:1080 \
  -c:a aac -b:a 128k \
  {output}
```

Meaning: decode input in software, scale video to 1080p high while preserving aspect ratio with an even width, encode H.264 with x264 at the configured ABR target, encode audio as AAC at 128 kbps, write MP4 output.

#### H.264 GPU: `gpu`

```bash
ffmpeg -y \
  -hwaccel vaapi -hwaccel_output_format vaapi \
  -extra_hw_frames 32 \
  -vaapi_device /dev/dri/renderD128 \
  -i {input} \
  -vf scale_vaapi=w=-2:h=1080:format=nv12 \
  -c:v h264_vaapi -b:v 4000k \
  -c:a aac -b:a 128k \
  {output}
```

Meaning: use VAAPI hardware decode and keep decoded frames in VAAPI hardware surfaces, scale on the GPU to 1080p/NV12, encode H.264 with the VAAPI encoder at the configured ABR target, encode audio as AAC at 128 kbps.

#### H.265 CPU: `h265_cpu`

```bash
ffmpeg -y -i {input} \
  -c:v libx265 -b:v 2000k \
  -vf scale=-2:1080 \
  -c:a aac -b:a 128k \
  {output}
```

Meaning: same CPU pipeline as H.264 CPU, but the video encoder is x265/HEVC and the default bitrate target is lower.

#### H.265 GPU: `h265_gpu`

```bash
ffmpeg -y \
  -hwaccel vaapi -hwaccel_output_format vaapi \
  -extra_hw_frames 32 \
  -vaapi_device /dev/dri/renderD128 \
  -i {input} \
  -vf scale_vaapi=w=-2:h=1080:format=nv12 \
  -c:v hevc_vaapi -b:v 2000k \
  -c:a aac -b:a 128k \
  {output}
```

Meaning: same full VAAPI pipeline as H.264 GPU, but using the VAAPI HEVC encoder.

#### AV1 CPU: `av1_cpu`

```bash
ffmpeg -y -i {input} \
  -c:v libsvtav1 -b:v 1500k \
  -vf scale=-2:1080 \
  -c:a aac -b:a 128k \
  {output}
```

Meaning: same CPU pipeline as H.264/H.265 CPU, but using the SVT-AV1 encoder wrapper.

#### AV1 GPU: `av1_gpu`

```bash
ffmpeg -y \
  -hwaccel vaapi -hwaccel_output_format vaapi \
  -extra_hw_frames 32 \
  -vaapi_device /dev/dri/renderD128 \
  -i {input} \
  -vf scale_vaapi=w=-2:h=1080:format=nv12 \
  -c:v av1_vaapi -b:v 1500k \
  -c:a aac -b:a 128k \
  {output}
```

Meaning: same full VAAPI pipeline as the other GPU presets, but using the VAAPI AV1 encoder.

### Comparison Modes

| Mode | Sequence | Baseline behavior | Rest behavior | Output |
|---|---|---|---|---|
| Single preset | baseline -> encode | one baseline before the run | none | one result under `result` |
| `both`, `h265_both`, `av1_both` | CPU baseline -> CPU encode -> rest -> GPU baseline -> GPU encode | separate baseline for CPU and GPU | `video_cooldown_s` between CPU/GPU | `cpu`, `gpu`, and pair analysis |
| `all_codecs` | H.264 CPU/GPU -> H.265 CPU/GPU -> AV1 CPU/GPU | separate baseline before every side | `video_cooldown_s` between each side and codec pair | per-codec pair analysis plus cross-codec fastest/lowest-energy summary |

### CPU/GPU Command Equivalence

The current presets are already aligned at the task level:

| Dimension | CPU presets | GPU presets | Equivalent? | Notes |
|---|---|---|---|---|
| Source input | `{input}` | `{input}` | Yes | Same source file or upload. |
| Output container | `{output}` MP4 path | `{output}` MP4 path | Yes | The extension is `.mp4` in `run_single()`. |
| Output height | `scale=-2:1080` | `scale_vaapi=w=-2:h=1080:format=nv12` | Yes, intent | Both target 1080p and preserve aspect ratio with even width. CPU uses software `scale`; GPU uses VAAPI scale. |
| Video rate-control target | `-b:v <codec bitrate>` | `-b:v <codec bitrate>` | Yes, intent | Same bitrate value per codec. Encoder implementations may hit the target differently. |
| Audio codec/bitrate | `-c:a aac -b:a 128k` | `-c:a aac -b:a 128k` | Yes | Audio path is not hardware accelerated in either command. |
| Video encoder | software encoder | VAAPI hardware encoder | No, by design | This is the variable under test. |
| Decode path | software/default decode | `-hwaccel vaapi -hwaccel_output_format vaapi` | No, by design | GPU presets measure full hardware decode + scale + encode, not GPU encode alone. |
| Pixel format | implicit from software filter/encoder | explicit `format=nv12` in VAAPI filter | Mostly | For stricter comparability, CPU commands could explicitly add `format=yuv420p` after scale. NV12 and yuv420p are both 8-bit 4:2:0, but memory layout differs. |
| Encoder defaults | libx264/libx265/libsvtav1 defaults | VAAPI encoder defaults | No | Preset/speed/quality defaults differ. Same bitrate does not guarantee same perceptual quality. |

The practical interpretation is: WattLab compares equivalent output intent, not bit-identical encoder settings. That is usually the right comparison for energy measurement: "produce a 1080p H.264/H.265/AV1 file at the same target bitrate from the same source", changing the implementation from CPU software to GPU VAAPI.

For a stricter apples-to-apples command set, explicitly document the shared intent and only vary the hardware-specific parts:

| Shared intent | Value |
|---|---|
| Input | same `{input}` |
| Output height | 1080p |
| Aspect ratio | preserve; derived width divisible by 2 |
| Pixel format class | 8-bit 4:2:0 |
| Audio | AAC, 128 kbps |
| H.264 target | 4000 kbps |
| H.265 target | 2000 kbps |
| AV1 target | 1500 kbps |

#### H.264 CPU vs GPU

| Part | CPU command | GPU command | Comparison |
|---|---|---|---|
| Decode | default software decode from `-i {input}` | `-hwaccel vaapi -hwaccel_output_format vaapi ... -i {input}` | Different by design. GPU keeps frames in hardware surfaces. |
| Scale | `-vf scale=-2:1080` | `-vf scale_vaapi=w=-2:h=1080:format=nv12` | Same resize intent; different filter implementation and explicit GPU pixel format. |
| Video encoder | `-c:v libx264` | `-c:v h264_vaapi` | Same codec family, different encoder implementation. |
| Video bitrate | `-b:v 4000k` | `-b:v 4000k` | Equivalent configured target. |
| Audio | `-c:a aac -b:a 128k` | `-c:a aac -b:a 128k` | Equivalent. |

Current task equivalence: good. The main caveat is quality equivalence: x264 and `h264_vaapi` do not share the same compression efficiency or defaults at the same bitrate.

#### H.265 CPU vs GPU

| Part | CPU command | GPU command | Comparison |
|---|---|---|---|
| Decode | default software decode from `-i {input}` | `-hwaccel vaapi -hwaccel_output_format vaapi ... -i {input}` | Different by design. |
| Scale | `-vf scale=-2:1080` | `-vf scale_vaapi=w=-2:h=1080:format=nv12` | Same resize intent; different implementation. |
| Video encoder | `-c:v libx265` | `-c:v hevc_vaapi` | Same codec family, different encoder implementation. |
| Video bitrate | `-b:v 2000k` | `-b:v 2000k` | Equivalent configured target. |
| Audio | `-c:a aac -b:a 128k` | `-c:a aac -b:a 128k` | Equivalent. |

Current task equivalence: good at target-bitrate/resolution level. Same caveat: x265 and `hevc_vaapi` will not necessarily deliver the same visual quality at 2000 kbps.

#### AV1 CPU vs GPU

| Part | CPU command | GPU command | Comparison |
|---|---|---|---|
| Decode | default software decode from `-i {input}` | `-hwaccel vaapi -hwaccel_output_format vaapi ... -i {input}` | Different by design. |
| Scale | `-vf scale=-2:1080` | `-vf scale_vaapi=w=-2:h=1080:format=nv12` | Same resize intent; different implementation. |
| Video encoder | `-c:v libsvtav1` | `-c:v av1_vaapi` | Same codec family, different encoder implementation. |
| Video bitrate | `-b:v 1500k` | `-b:v 1500k` | Equivalent configured target. |
| Audio | `-c:a aac -b:a 128k` | `-c:a aac -b:a 128k` | Equivalent. |

Current task equivalence: good at target-bitrate/resolution level. AV1 CPU/GPU equivalence is especially implementation-dependent because SVT-AV1 and hardware AV1 encoders have very different speed/quality trade-offs.

### Recommended Equivalence Wording

Use this wording when presenting results:

> CPU and GPU runs use the same source, output resolution, codec family, audio settings, and target bitrate. The changed variable is the implementation path: software decode/scale/encode on CPU versus VAAPI hardware decode/scale/encode on GPU. Because software and hardware encoders have different internals and defaults, equal bitrate is an equal workload target, not a guarantee of equal visual quality.

If visual-quality equivalence becomes a requirement, add an objective quality gate after each run, for example VMAF/SSIM/PSNR against the same source, and tune CPU/GPU encoder-specific settings until the metric is matched. That would change the experiment from "same target bitrate" to "same target quality".

### Custom Commands

The video page accepts custom ffmpeg command strings. The placeholders `{input}` and `{output}` are substituted at runtime and then split with `shlex.split()`. For single-preset runs, `custom_cmd` replaces the preset command. For CPU/GPU comparison modes, `custom_cmd_cpu` and `custom_cmd_gpu` can independently replace the CPU and GPU preset commands.

The service still wraps custom commands with `nice -n -5`, still measures power the same way, and still expects the command to produce the configured output path if output size should be reported.

### Variance Calibration Commands

Variance calibration is a separate lab-only workflow under `/variance/run`. It runs H.264 CPU and H.265 GPU repeatedly on Meridian full source, then stores coefficients of variation in settings.

Default CPU calibration command:

```bash
ffmpeg -y -i {input} -c:v libx264 -crf 23 \
  -vf scale=-2:1080 -c:a aac -b:a 128k {output}
```

Default GPU calibration command:

```bash
ffmpeg -y -hwaccel vaapi -hwaccel_output_format vaapi \
  -extra_hw_frames 32 \
  -vaapi_device /dev/dri/renderD128 -i {input} \
  -vf scale_vaapi=w=-2:h=1080:format=nv12 \
  -c:v hevc_vaapi -qp 28 -c:a aac -b:a 128k {output}
```

These are not the normal ABR presets: they use `-crf 23` for x264 and `-qp 28` for VAAPI HEVC to calibrate repeatability/noise.

## 3. ffmpeg Parameter Reference

The official FFmpeg documentation describes ffmpeg as a pipeline of demuxers, decoders, filters, encoders, and muxers; WattLab's presets are all transcoding pipelines because they decode input, resize it, re-encode video, re-encode audio, and write a new MP4 file.

| Parameter | Used in | WattLab meaning | FFmpeg documentation basis |
|---|---|---|---|
| `-y` | all commands | overwrite output file without prompting | Global ffmpeg overwrite option. |
| `-i {input}` | all commands | input file to demux/decode | ffmpeg reads inputs from `-i` URLs. |
| `{output}` | all commands | output URL/path; here usually MP4 | Anything not parsed as an option is treated as an output URL. |
| `-c:v <encoder>` | all commands | select the video encoder for the output video stream | `-c` / `-codec` selects encoder/decoder, stream specifier `:v` applies to video. |
| `-c:a aac` | all commands | encode output audio as AAC | same `-c` option, stream specifier `:a` applies to audio. |
| `-b:v 4000k`, `2000k`, `1500k` | normal presets | target video bitrate; WattLab labels this ABR | `-b:v` is the video bitrate option; encoder wrappers map `b`/`bit_rate` to target bitrate. |
| `-b:a 128k` | all commands | target audio bitrate | audio stream bitrate through same bitrate option family. |
| `-vf scale=-2:1080` | CPU presets | software video filter: output height 1080; width derived from aspect ratio and rounded to an even value | `-vf` creates a simple video filtergraph; `scale` supports expressions and `-n` dimensions for divisibility. |
| `-hwaccel vaapi` | GPU presets | request VAAPI hardware-accelerated decode | ffmpeg lists `vaapi` as a hardware acceleration method. |
| `-hwaccel_output_format vaapi` | GPU presets | keep decoded frames as VAAPI hardware frames | used with hardware acceleration to keep frames in hardware format for downstream hardware processing. |
| `-extra_hw_frames 32` | GPU presets | allocate extra hardware frame buffering for the VAAPI pipeline | ffmpeg hardware-frame option; relevant because VAAPI encoders use hardware frames. |
| `-vaapi_device /dev/dri/renderD128` | GPU presets | select the AMD DRM render node used by VAAPI | VAAPI devices can be DRM render nodes such as `/dev/dri/renderD128`. |
| `-vf scale_vaapi=w=-2:h=1080:format=nv12` | GPU presets | GPU-side scale to 1080p, even width, NV12 pixel format | VAAPI filter path; output stays suitable for VAAPI encoders. |
| `libx264` | H.264 CPU | software H.264 encoder wrapper for x264 | FFmpeg codec docs: libx264 wrapper, including bitrate option mapping. |
| `libx265` | H.265 CPU | software HEVC encoder wrapper for x265 | FFmpeg codec docs: libx265 wrapper. |
| `libsvtav1` | AV1 CPU | software AV1 encoder wrapper for SVT-AV1 | FFmpeg codec docs: SVT-AV1 encoder wrapper. |
| `h264_vaapi` | H.264 GPU | VAAPI H.264 hardware encoder | FFmpeg VAAPI encoder docs list `h264_vaapi`. |
| `hevc_vaapi` | H.265 GPU | VAAPI HEVC hardware encoder | FFmpeg VAAPI encoder docs list `hevc_vaapi`. |
| `av1_vaapi` | AV1 GPU | VAAPI AV1 hardware encoder | FFmpeg VAAPI encoder docs list `av1_vaapi`. |
| `-crf 23` | variance CPU command only | x264 constant quality mode instead of ABR | x264 wrapper exposes CRF as a rate-control option. |
| `-qp 28` | variance GPU command only | constant quantizer parameter instead of ABR | VAAPI encoders expose quantizer/global-quality style controls and CQP rate-control modes. |

### Official Documentation Links

- FFmpeg documentation index: https://ffmpeg.org/documentation.html
- ffmpeg command-line tool documentation: https://ffmpeg.org/ffmpeg.html
- FFmpeg codec/encoder documentation: https://ffmpeg.org/ffmpeg-codecs.html
- FFmpeg filter documentation: https://ffmpeg.org/ffmpeg-filters.html
- Combined ffmpeg-all documentation, useful for VAAPI sections: https://ffmpeg.org/ffmpeg-all.html

Relevant official doc points checked for this report:

- `ffmpeg` reads from `-i` inputs and writes to output URLs; option order matters and options apply to the next input/output file.
- Transcoding means decoding and encoding again, often with filters such as resize.
- `-c:v` and `-c:a` use stream specifiers to apply codecs to video/audio streams.
- `-b:v` sets a video bitrate; codec docs describe encoder bitrate options such as `b` / `bit_rate`.
- `-hwaccel vaapi` selects VAAPI hardware acceleration.
- FFmpeg's VAAPI encoder documentation lists shared VAAPI options and the codec-specific encoders used here: `av1_vaapi`, `h264_vaapi`, and `hevc_vaapi`.
- The `scale` filter supports expression-based sizing and `-n` dimensions; WattLab uses `-2` to keep the derived width divisible by 2, which many video encoders require.

## 4. Code Reference Map

| Topic | File/location |
|---|---|
| FastAPI app, pages, queue, endpoints | `wattlab_service/main.py` |
| Home navigation and live telemetry endpoints | `wattlab_service/main.py` around `/`, `/power`, `/live`, `/carbon` |
| Video page and API endpoints | `wattlab_service/main.py` around `/video`, `/video/upload`, `/video/use-source`, `/video/preview-cmd` |
| Video preset definitions | `wattlab_service/video.py`, `PRESETS` |
| Video measurement implementation | `wattlab_service/video.py`, `measure_baseline()`, `poll_during_task()`, `run_single()`, `run_video_measurement()`, `run_both_measurement()`, `run_all_measurement()` |
| Variance calibration | `wattlab_service/video.py`, `run_variance_calibration()` |
| Bitrate and confidence defaults | `wattlab_service/settings.py`, `DEFAULTS` |
| Power meter and sensor access | `wattlab_service/power.py` |
| Preloaded source registry | `wattlab_service/sources.py` |
| Result persistence and CSV export | `wattlab_service/persist.py` |
