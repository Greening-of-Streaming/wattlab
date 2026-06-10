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
| `mode` | the runner | dispatch key — see inventory below |
| `version`, `build` | `persist` ← `version.py` | build stamp |
| `gpu_hardware` | `persist` ← `gpu.BACKEND` | CR-060 |
| `power_hardware` | `persist` ← `power.stamp()` | CR-031 §2 |
| `energy{}` per run/side | measurement module | `w_base, w_task, delta_w, delta_e_wh, delta_t_s, poll_count, confidence{}, baseline_samples_w[], task_samples_w[], co2e{}` |
| `confidence{}` | `confidence.confidence()` | `flag` 🟢🟡🔴, `label`, `method` (`ci`/`variance`) |

## Mode inventory

### `video` (writer: `video.py`, orchestration: `routes_video.run_job`)

| mode | shape | summariser | JS renderer |
|---|---|---|---|
| `single` (also legacy absent → `?`) | `result{energy,thermals,…}` | `_sum_video_single` | `wlRenderVideoCard` else-branch |
| `both` | `cpu{}, gpu{}, analysis{}` | `_sum_video_both` | `wlRenderVideoCard` |
| `all_codecs` | `codecs{h264{cpu,gpu},…}, analysis{}` | `_sum_video_codecs` | `wlRenderVideoCard` |
| `codecs_cpu` / `codecs_gpu` | `codecs{…[side]}, analysis{}, side` | `_sum_video_codecs` | `wlRenderCodecsSingle` |

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
| `enhance` | `result{energy{}, transcode{}, stream{}, realtime{}, vqa?, source_vqa?}` | **none — stamps `unrecognised_mode`** (pre-existing gap, CR candidate) | `renderResult` (inline in routes_enhance.py) |
| `enhance_compare` | `ml{result{…, vqa?}}, ffmpeg{result{…, vqa?}}, source_vqa?, source_complexity, comparison{ab_quality}` | same gap | `renderCompare` (inline in routes_enhance.py) |

`vqa` / `source_vqa` are **nullable** NR quality stamps (CompressedVQA-HDR —
Sun et al., arXiv:2507.11900, Apache 2.0): `{score, model, duration_s}` from
`pixop.probe_vqa_nr`, a terminal post-lock pass shelling out to the sandbox at
`vqa_dir` (`/srv/data/owl/vqa-eval`). Fail-soft: a missing sandbox / timeout /
parse failure just omits the score — never blocks the run (`preflight().vqa_ok`
is informational only). `comparison.quality` stays `"TBD"`: the NR score is a
learned within-run indicator, not a ground-truth verdict.

## Consumers (the blast-radius list)

A mode/shape change fans out to, in order of how quickly the break is noticed:

1. Fresh-result JS card (`static/wl-result.js` `wlRender*Card`)
2. Previous-runs expansion (same renderers, `isPrev` path)
3. `/demo` pre-load (`routes_results.demo_last_result` — **mode-filters** per
   step; S37 bug 1 was compare records leaking into the single renderer)
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
