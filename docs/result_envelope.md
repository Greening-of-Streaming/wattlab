# OWL Result Envelope — the mode → renderer contract

Phase 4 of the 2026-06 refactor (`docs/architecture_review_2026-06.md`).
This file is the **single catalogue** of every persisted result shape and who
consumes it. The 2026-05/06 regression class (S37 demo-tour bug, S39
image-compare bugs) was always the same failure: a result mode known to its
writer but not to one of its consumers. The contract:

> **Adding or changing a `mode` means updating three places: the writer, the
> two dispatch tables below, and this file.**

1. `persist._SUMMARISERS` — `job_type × mode → summariser` (loud fallback:
   an unregistered mode summarises through the single-run shape and stamps
   `"unrecognised_mode": <mode>` on the summary).
2. `static/wl-result.js` — the `wlRender*Card` renderer for the type
   (soft-fail: `_wlBadRecord(kind, r)` echoes the offending mode).

## Common envelope

Every result JSON under `results/{type}/{date}_{job_id}.json` carries:

| field | source | notes |
|---|---|---|
| `job_id`, `saved_at` | `persist.save_result` | |
| `envelope_version` | `persist.save_result` | **1** since 2026-08-17 (CR-031 §1 pre-work / CR-073); absent on disk = 0. Bump on any shape change and note it here. v1 = decode raw samples single-stored in `runs[]`; `batch_id` field. |
| `batch_id` | the runner (`rem`, `decode`) | optional group id — several jobs queued as one campaign; collate via `persist.list_batch` (`/prepare-rem/csv/batch/{id}`, `/decode/batch/{id}`). None/absent = solo. |
| `mode` | the runner | dispatch key — see inventory below |
| `version`, `build` | `persist` ← `version.py` | build stamp |
| `gpu_hardware` | `persist` ← `gpu.BACKEND` | CR-060 |
| `power_hardware` | `persist` ← `power.stamp()` | CR-031 §2; dual-meter runs (CR-065) add `meters: 2, topology: "daisy_chain", stagger_s` |
| `energy{}` per run/side | measurement module | `w_base, w_task, delta_w, delta_e_wh, delta_t_s, poll_count, confidence{}, baseline_samples_w[], task_samples_w[], co2e{}` |
| `energy.meters{}` | `power.meters_summary()` | **optional**, CR-065 dual-meter only. `inner{w_base,w_task,delta_w}, outer{… + baseline_samples_w[], task_samples_w[]}, combine_method, delta_w_combined` — top-level `delta_w`/`delta_e_wh` ARE the combined figures; `w_base`/`w_task`/`*_samples_w` keep their historical meaning (inner/primary meter). A dropped secondary stream persists as `meters: {degraded: true}` instead — the run is honest single-meter data. Renderers may ignore the whole block. |
| `confidence{}` | `confidence.confidence()` | `flag` 🟢🟡🔴, `label`, `method` (`ci`/`ci2`/`variance` — `ci2` = CR-065 per-meter combine) |

## Mode inventory

### `video` (writer: `video.py`, orchestration: `routes_video.run_job`)

| mode | shape | summariser | JS renderer |
|---|---|---|---|
| `single` (also legacy absent → `?`) | `result{energy,thermals,…}` | `_sum_video_single` | `wlRenderVideoCard` else-branch (`_wlVideoSingleRich`) |
| `both` | `cpu{}, gpu{}, analysis{}` | `_sum_video_both` | `wlRenderVideoCard` (`_wlVideoBothRich`) |
| `all_codecs` | `codecs{h264{cpu,gpu},…}, analysis{}` | `_sum_video_codecs` | `wlRenderVideoCard` (`_wlVideoAllCodecsRich`) |
| `codecs_cpu` / `codecs_gpu` | `codecs{…[side]}, analysis{}, side` | `_sum_video_codecs` | `wlRenderCodecsSingle` |

Since 2026-07-07 `wlRenderVideoCard` IS the former /video fresh-run rich
renderer family (thermals, PPT, Baseline/Task/Polls, ffmpeg `<details>`,
per-codec collapsibles) — the /video page's `renderResult` delegates to it,
so fresh runs, prev-row expansion, findings embeds and /demo all render the
identical card. The rich CSS self-injects from wl-result.js (`.wl-rich`
namespace, `#wl-rich-css`); consumer pages carry no copy.

### `llm` (writers: `llm.py` + `routes_llm`/`routes_rag` orchestration; **rag persists under `results/llm/`**)

| mode | shape | summariser | JS renderer |
|---|---|---|---|
| `single` | `energy{}, inference{}` | `_sum_llm_single` | `wlRenderLLMCard` else-branch |
| `both` | `cpu{}, gpu{}, analysis{}` | `_sum_llm_both` | `wlRenderLLMCard` |
| `batch` | `runs[], aggregate{}` | `_sum_llm_batch` | `wlRenderLLMCard` (via `r.summary`) |
| `all` | `tasks{T1,T2,T3}` | `_sum_llm_all` | curated /demo views |
| `all_both` | `cpu{T*}, gpu{T*}` | `_sum_llm_all_both` | curated /demo views |
| `compare_models` | `models[], model_errors[]` | single-style (no top-level energy) | `wlRenderComparePanel` |
| `rag` | `energy{}, inference{}, rag_mode` | `_sum_llm_rag` | `wlRenderRAGCard` |
| `rag_compare` | `results{baseline,rag,rag_blended,rag_large}` | `_sum_llm_rag_compare` | `wlRenderRAGCard` |
| `rag_compare_models` | `models[], model_errors[]` | single-style | `wlRenderComparePanel` |

### `image` (writer: `image_gen.py`, orchestration: `routes_image`)

| mode | shape | summariser | JS renderer |
|---|---|---|---|
| `cpu` / `gpu` (mode = device) | `energy{}, generation{}` | `_sum_image_single` | `wlRenderImageCard` else-branch |
| `both` | `cpu{}, gpu{}` | `_sum_image_both` | `wlRenderImageCard` |
| `compare_models` | `models[]` (+ legacy `small`/`large` aliases) | `_sum_image_compare_models` | `wlRenderImageCard` N-way path |

### `benchmark` (writer: `benchmark.py`)

Self-describing manifest: `steps[{kind, status, result_ref{type, job_id}}]`.
Summariser: `_sum_benchmark`. Views: `routes_benchmark` + `wl-bench-hydrate.js`.

### `enhance` (writer: `pixop.run_enhance_*`, orchestration: `routes_enhance`)

| mode | shape | summariser | JS renderer |
|---|---|---|---|
| `enhance` | `result{energy{}, transcode{}, stream{}, realtime{}, vqa?, source_vqa?, preset_args?, preset_origin, input_stream?}` | `_sum_enhance_single` (CR-064) | `renderResultHtml` (inline in routes_enhance.py; also the prev-runs expand) |
| `enhance_compare` | `ml{result{…, vqa?, preset_args?, preset_origin}}, ffmpeg{result{…, vqa?}}, source_vqa?, input_stream?, source_complexity, comparison{ab_quality}` | `_sum_enhance_compare` (CR-064) | `renderCompareHtml` (ditto) |

`vqa` / `source_vqa` are **nullable** NR quality stamps (CompressedVQA-HDR —
Sun et al., arXiv:2507.11900, Apache 2.0): `{score, model, duration_s}` from
`pixop.probe_vqa_nr`, a terminal post-lock pass shelling out to the sandbox at
`vqa_dir` (`/srv/data/owl/vqa-eval`). Fail-soft: a missing sandbox / timeout /
parse failure just omits the score — never blocks the run (`preflight().vqa_ok`
is informational only). `comparison.quality` stays `"TBD"`: the NR score is a
learned within-run indicator, not a ground-truth verdict.

CR-064 provenance fields (all nullable, never drive behaviour):
`preset_args` = the exact expanded token list; `preset_origin` =
`generated | staged` (generated = the 2×3 combo matrix under
`presets/generated/`, derived from the colour templates); `input_stream` =
ffprobe facts about the source (codec/res/pix_fmt/colour-transfer/`hdr`).
Enhance results browse like every other type: `/results/enhance/list` +
`download.json` / `download.csv` (`persist._enhance_rows`, one CSV row per
measured pass). The /enhance-run page renders its own prev-runs section with
the inline `renderResultHtml`/`renderCompareHtml`; `wl-result.js` also maps
`enhance → wlRenderEnhanceCard` in the `wlExpandPrevRow` registry for
cross-page embeds (findings, /demo's pinned Video-Enhancement step).

### `decode` (writers: `decode_run.run_decode_job` via the queue — `ui_headless`/`ui_screen`; `bin/import-decode-bench-results` — external import `decode_panel`)

| mode | shape | summariser | JS renderer |
|---|---|---|---|
| `ui_headless` / `ui_screen` | `template, template_label, calibrate, batch_id?, devices{name: {label, kind, meter{}, rows[scalars only since v1], display_caveat?, log_tail?}}, runs[{...row, device}], protocol{harness, launched_from, parallel, window_s (actually run), pacing, marker_head?, protocol_version, cadence_s, …}` — each `runs[]` row: `w_base, w_task, delta_w, window_s, n_base, n_task, confidence{}, provenance{decoders_allocated, screenshot, playback_state_midwindow, play_presses_after_launch, keep_awake}, alive_at_window_end, context_* (screen mode), raw_baseline_w/t[], raw_task_w/t[], raw_context_*[], idle_guard, error?/error_where?` | `_sum_decode_panel` (fallback) | `/decode` inline `renderJob`; `wlRenderDecodeCard` (findings) |
| `decode_panel` | `device{}, power_hardware{}, protocol{}, runs[{name, codec, decode_path: sw\|hw, regime: realtime\|full_speed, content, player, energy{}}], discarded[]?, measured_on, report` | `_sum_decode_panel` | `wlRenderDecodeCard` |

**2026-09-03 addendum** (`decode_run.py` / `bench.py` / `decode_sync.py`) — `ui_*` `runs[]` rows may also carry:
`sync` (rendezvous record) · `start_cmd_epoch` · `playing_epoch` · `raw_content_clock` (per-poll `[t, pos_s, state, dt]`) ·
`content_clock` (summary) · `screen_marker_segments` · `screen_marker_loops` · `hdmi_input` (screen-map slot, or `null` = no sink).
`protocol{}` gains `sync_start`, `content_clock`, `looped_marker`, `screen_device`, `regime_note`.

**v0 → v1 (2026-08-17):** pre-v1 `ui_*` files carry the raw sample arrays twice (`devices[].rows`
AND `runs[]`); v1 stores them once in `runs[]`. Readers (`lem.csv`, `decode_batch`) read `runs[]`
first and fall back to `devices[].rows`. Pre-v1 `protocol.window_s` is the template default (150) —
read `runs[].window_s` for the window actually run. Campaign collation: `decode_batch.matrix`.

Client-device decode-energy panels from the decode-bench rig (Google TV `dec0de06`,
Raspberry Pi 5 `dec0de05`, Pi 400 `dec0de04` — 2026-07-28/29; harness
`/srv/data/owl/decode-bench/bench.py`, narrative `docs/pi_decode_energy_2026-07.md`).
Each `runs[].energy{}` is contract-shaped (w_base/w_task/delta_w/delta_e_wh/poll_count/
confidence{}/raw sample arrays). Imported envelopes carry `import_note` and no
`gpu_hardware`/`owl_version` stamp (not produced by GoS1's queue). `discarded[]` keeps
contaminated rows visible with reasons instead of deleting them. Findings source
allowlist includes `decode` (`routes_findings.py`).

### `rem` (writer: `rem_prep.py` via `routes_rem` — `/prepare-rem`, S-2026-06-23/26)

| mode | shape | summariser | JS renderer |
|---|---|---|---|
| `rem_prep` (single) / batch (`batch_id` shared by the multi-codec checkbox jobs) | source (master or upload), codec, target VMAF **or** fixed bitrate, resolution, the two-stage encode (bitrate search on a 2-min excerpt seeded from parity curves → one full 6.5-min confirming encode), `energy{}` for the clean video encode only (markers/timer/concat assembled outside the window), output file name + un-gated share token (`/rem-file/{token}`, index in `<rem_output_dir>/share_tokens.json`), `vmaf` (v1, provenance-stamped) | `_rem_rows` / `_REM_FIELDNAMES` (per-file + per-batch CSV via `persist.rem_batch_csv`) | `/prepare-rem` page only |

Files live under `results/rem/`; the deliverable video under `settings.rem_output_dir` (`/srv/data/owl/rem_out`,
NOT /tmp). Metered figure = a full transcode (decode+scale+encode); `energy_split{transcode_wh, decode_wh, encode_wh}` = transcode minus a
null-sink decode probe (approximation, overlap noted in the file's `note`). `results/network/` and `results/training/` on disk are legacy experiment folders with no
current writer.

## Consumers (the blast-radius list)

A mode/shape change fans out to, in order of how quickly the break is noticed:

1. Fresh-result JS card (`static/wl-result.js` `wlRender*Card`)
2. Previous-runs expansion (same renderers, `isPrev` path)
3. `/demo` pre-load (`routes_results.demo_last_result` — **pin-first** via
   `demo_pinned_results` in settings, then **mode-filters** per step; `rag`
   is a pseudo-type over `results/llm/` and `enhance` is pin-ONLY. S37 bug 1
   was compare records leaking into the single renderer)
4. `persist._summarise` (the `/results/{type}/list` rows)
5. CSV export rows (`persist._video_rows` / `_image_rows` / llm rows)
6. Findings embeds (`routes_findings` source carve-out + `wl-result.js`)
7. Benchmark detail view (`routes_benchmark` + `wl-bench-hydrate.js`)

## Cooldown stamp-key variants (known, deferred)

Two shapes exist on disk (S39 audit):

- `"cooldowns": [{method, waited_s, settled, timed_out}, …]` — list, one per
  inter-run cooldown. Stamped by the compare orchestrations.
- `"cooldown": {…}` — single dict, stamped by the measurement modules'
  CPU-vs-GPU paths (`llm.py`, `image_gen.py`, `video.py` both-modes,
  `pixop.py`).

`wlCooldownSummary` accepts both (normalises a dict to a one-item list).
Writer unification is **deferred** because the singular writers live inside
measurement modules, which Phases 0–4 must not touch (energy-imperceptibility
audit rule). Unify to the `cooldowns` list the next time those modules are
edited for a measurement reason.

## jobs dict (in-flight records, `runtime.jobs`)

Not persisted; free-form by historical accident (review risk #3). Common keys:
`status` (`queued|running|done|error|cancelled`), `stage` (free string; the
stage strips key off it), `result`, `error`, `progress_pct`, cooldown live
fields (`cooldown_*`), `current_model_idx`. A formal `JobRecord` shape is the
remaining Phase-4 item — fix when next touched.
