# Clean-protocol re-run — plan, rationale, status

Working notes for `run_clean_sweep.py`, written while drafting Section 3
(Methodology) of the SMPTE paper. Captures the measurement-integrity gaps
found in the existing encode-parity dataset, the fix, and where things stand
as of **2026-09-06** (scoped up to n=3 over four contents; awaiting a slot).

## Why this exists

While writing Section 3.5 (Measurement Integrity), three questions came up
about the harness that actually produced the paper's dataset
(`wattlab_service/parity.py`, used for every `s53_*` / `readysetgo_*` row in
`consolidated_encode_dataset.csv`). Checking the code directly (not assuming)
turned up three real gaps:

1. **"Wait for idle" between rows is a flat sleep, not an active check.**
   `parity.run_campaign()` does `await asyncio.sleep(campaign.cooldown_s)`
   between every row. Checked the actual artifacts on disk — the canonical
   240-row dataset, its bitrate-ceiling extension, and the ReadySetGo sweep
   all recorded `cooldown_s: 10` in their own `protocol` block. Ten seconds,
   unconditionally, never checked against actual power. This is *different*
   from OWL's live `/video` page, which uses a real active-probe dispatcher
   (`power.cooldown_between_runs`) that polls until power reconverges to a
   reference floor — `parity.py` simply never calls it.

2. **A contamination flag the codebase already computes is silently dropped.**
   `video.measure_baseline()` returns `baseline_elevated` (CR-070: is this
   baseline above the rolling idle floor + tolerance?) and
   `baseline_reference_w`. `parity._measure_recipe()`'s returned row dict
   keeps only the scalar `w_base` and never carries these two fields through.
   Confirmed empirically: 0 of the 240+84+33 real rows checked carry the
   field at all, so even a genuinely contaminated row would never show it.

3. **OS page-cache warm-start bias is real and untreated.**
   `Campaign.recipes()` iterates clip → codec → bitrate → profile → rep, so
   every row for one clip (60–84 of them) runs consecutively before the next
   clip starts. After the first read, that clip's bytes sit in page cache
   (GoS1 has 61GB RAM) for the rest of the block. No `drop_caches`, `sync`,
   `posix_fadvise`, or read-order shuffling exists anywhere in the codebase —
   confirmed by grep, twice. Net effect: the *first* row measured for each
   clip is a plausible cold-read outlier; every row after it for that same
   clip is warm. IQR outlier filtering (per source/codec/implementation
   group, on spread) isn't designed to catch this specifically.

Also confirmed while investigating (context, not itself a defect): only a
**30-second excerpt** of each master clip is ever measured, not the full
clip despite filenames like `meridian_120s.mp4` — and within that fixed
window, the clip is re-encoded back-to-back as many times as it takes
(`n_encodes`) to reach the harness's 20s minimum measurement window. Energy
is normalized as Wh per minute of content encoded (`wh_per_min_video`,
already time-based and loop-count-safe) — separate from the three gaps
above, and **not** touched by `run_clean_sweep.py` (see Scope below).

## The fix — `run_clean_sweep.py`

Self-contained script, same pattern as the existing
`run_sport_clip_sweep.py`: imports `parity` / `video` / `power` / `gpu` /
`settings` **read-only**, never calls `parity.run_campaign()` (that's the
flat-sleep loop being replaced), drives its own loop instead.

- **Real wait-for-idle**: calls `power.cooldown_between_runs()` — the *same*
  dispatcher OWL's live `/video` page already uses — with each row's own
  measured `w_base` as the next row's reference floor. Reads the live
  `cooldown_idle_tolerance_w` / `_settle_polls` / `_max_wait_s` settings
  (read-only), so it inherits whatever OWL is actually tuned to.
- **Contamination flag kept**: `baseline_elevated` / `baseline_reference_w`
  are persisted into every row instead of being dropped.
- **Cache eviction**: `posix_fadvise(DONTNEED)` on the clip immediately
  before every row's first read (no root needed, touches only that file's
  cached pages). Every row now starts cold identically. Run order stays
  deterministic on purpose — eviction fixes the actual asymmetry directly,
  so reordering on top of it isn't needed (documented in the script header).

**Guarantees — nothing here touches the live service:**
`wattlab_service/parity.py`, `video.py`, `power.py`, `gpu.py`, and
`settings.json` are never edited, only imported. Output goes only to
`results/calibration/_staging/` (never `results/calibration/` directly —
that's the glob `/video/budget` reads its "latest artifact" from, and S70
and S71 both hit that exact footgun with their own extension files). Uses
the same `/tmp/owl-paused` + `/tmp/owl-lab-session` + `/tmp/gos-measure.lock`
coordination every other standalone campaign script uses, so it backs off
the live poller cleanly and restores it on exit (including on failure).

## Scope (revised 2026-09-06 — Tania)

**n=3 per point**, over **four contents**: Meridian, BBB, ReadySetGo and
football. Raised from the original n=1 to meet the WattLab call's primary-data
bar (2026-09-03); ReadySetGo stays in despite the 5 s-source looping caveat,
which goes into the paper's limitations rather than taking the clip out.

| Clip | 1080p sweep ladder | Profiles (sweep) | Profiles (ladder rungs) |
|---|---|---|---|
| Meridian, BBB, ReadySetGo | matched: H.264 ×7 / H.265 ×7 / AV1 ×6 | cpu, gpu_baseline, gpu_tuned | cpu, gpu_baseline |
| football | ceiling-extended: H.264 ×7 / H.265 ×10 / AV1 ×9 | cpu, gpu_baseline, gpu_tuned | cpu, gpu_baseline |

**1062 rows total** — 354 per pass (774 sweep + 288 ladder across the three
passes), confirmed via `--print-only`. Football carries the taller ladder from
the start because its H.265/AV1 VMAF targets sat above the matched ladder's top
in the 2026-09-03 leg, which is what produced the empty `bitrate_kbps_at_target`
cells there; extending up front keeps every iso-quality target interior to the
measured range.

**Replicates are whole passes, not back-to-back repeats.** `parity.Campaign.
recipes()` yields `rep` innermost, i.e. three consecutive measurements of the
same recipe — which share thermal state and a warm page cache, and so
understate exactly the run-to-run spread n=3 exists to measure. The script
therefore builds the campaign with `reps=1` and repeats the whole matrix
(`expand_passes()`), so replicate k of any point is ~6.5 h from replicate k+1.
Side benefit: an interrupted run always leaves complete passes.

**The task definition is unchanged from the published dataset** (Tania's call,
2026-09-06, after checking what the published rows actually do). A 30 s
excerpt, encoded back-to-back until the window reaches 20 s of wall clock,
5-poll baseline, energy normalised per minute of content. Worth stating
plainly in Section 3, because "30 s excerpt, 20 s window, run once" is only
two-thirds right: `reps=1` meant one *row* per recipe, but within that row the
excerpt was **encoded 1–13 times** — the window is wall-clock, and NVENC is
~8× realtime where libx265 is ~1.7×, so a GPU row encodes 150–210 s of content
and a CPU H.265 row 30–60 s, inside windows of similar length. Only 7 of the
canonical 240 rows did a single pass. `wh_per_min_video` divides by the content
actually encoded, so the published numbers are right — but the tasks are
neither equal-length nor a fixed amount of content, and Section 3 should say so.

**VMAF is scored under v0.6.1**, the consolidated dataset's convention, through
an in-process settings override rather than the live service's v1 default — so
these rows need no `bin/rescore-*-v0.py` pass afterwards. It is a terminal pass
after the measurement window closes and touches no energy number. Everything
else reads live settings, including the recalibration of 2026-09-05 04:03
(n=20, on an idle box, `w_base_mean` 78.36 W): `variance_pct` 1.49 → 2.19,
gpu 1.25 → 2.87, idle drift 1.12 → 1.9. Traffic lights on these rows will
therefore be more conservative than the 2026-06 rows; raw baseline and task
samples are persisted per row, so any of it can be recomputed later.

**Not in scope for this run** (separate, later items — not forgotten, just
not bundled in):
- The bitrate-ceiling extension beyond `MATCHED_BITRATES` for the three
  non-football clips (already folded into the ladder used here).
- The per-1,000-encoded-frames normalization question left as a TODO in the
  paper draft's Section 3.4 — orthogonal to this run's data-collection fixes.

## Time estimate

Anchored to real numbers: the actual ReadySetGo campaign logged
**4596.7s / 84 rows = 54.7s/row** under the *old* flat-10s-cooldown protocol,
and the 426 rows on disk give a measured encode speed per path (median
wall-clock per 30 s encode: NVENC 3.6–4.0 s, libx264 8.6 s, SVT-AV1 9.5 s,
libx265 17.6 s — `ENCODE_S_PER_30S` in the script). Each row is that path's
fill of the ≥20 s window, plus ~20 s of baseline/VMAF/probe overhead and a
~20 s budget for the genuine settle-verified wait (the old flat sleep was
10 s; cache eviction adds <1 s/row).

**1062 rows ≈ 19.4 hours** at ~66 s/row — **~6.5 h per pass**. One pass fits an
overnight window; the three do not, so the run is designed to be split
(`--resume`).

## How to run it

```bash
# 1. Sanity-check scope/row-count/estimate — no encoding, safe anytime
python docs/smpte_2026/run_clean_sweep.py --print-only

# 2. Exercise the full pipeline with a synthetic power source — real ffmpeg
#    encodes still happen (only the wattage is fake), so this is NOT free
#    time-wise; use a tiny ad-hoc Campaign for a quick mechanics check
#    rather than the full 252-row scope. (Note: dry mode does not exercise
#    the real active-wait branch — see the code comment on why.)

# 3. The real thing — needs the meter idle/exclusive (bench-preflight
#    conditions). Run detached so it survives a dropped SSH session:
nohup python docs/smpte_2026/run_clean_sweep.py --run > clean_sweep.log 2>&1 &
disown
tail -f clean_sweep.log

# 4. Continue on a later evening — same artifact, rows already measured are
#    skipped, any row that stored an error is re-measured:
nohup python docs/smpte_2026/run_clean_sweep.py --run \
      --resume results/calibration/_staging/encode_parity_CLEAN_nvenc_24c_<date>.json \
      >> clean_sweep.log 2>&1 &
disown
```

Checkpoints to `results/calibration/_staging/encode_parity_CLEAN_<fingerprint>_<date>.json`
after every row, so a crash or dropped session mid-run leaves a valid partial
artifact, same convention as `parity.run_campaign()`. On completion, restores
`/tmp/owl-paused` / `/tmp/owl-lab-session` / `/tmp/gos-measure.lock` even on
failure (`finally` block).

## Status (2026-09-02 — superseded, kept for the record)

- `run_clean_sweep.py` written and smoke-tested: `--print-only` confirms 252
  rows (180 sweep + 72 ladder); two small `--dry` runs (1 and 2 synthetic
  rows, using an ad-hoc small `parity.Campaign` rather than the full scope)
  confirmed cache-eviction flag populates, `baseline_elevated` correctly
  resolves from row 2 onward, checkpointing/artifact-writing works, cleanup
  leaves no stray files.
- **Not yet done**: an actual `--run`. Needs the meter genuinely idle — checked
  2026-09-02 evening and it wasn't (a decode-rig campaign was running, queue
  depth 1; GoS1's own power draw was at idle regardless, but `run_clean_sweep.
  py`'s preflight correctly refuses to start while queue_depth != 0). Tania is
  checking with Ben and running it 2026-09-03 instead.
- **After the run**: folding the new artifact into
  `consolidated_encode_dataset.csv` (or deciding whether it *replaces* the
  existing sweep rows rather than sitting alongside them) is a deliberate,
  reviewed follow-up step — not automatic, same convention as every other
  campaign script in this folder.

## Status (2026-09-06)

- Scoped up to **n=3 × four contents = 1062 rows** (above); football's
  ceiling-extended ladder folded in; replicates run as whole passes; VMAF
  scored v0.6.1 in-run; `--resume` added so the ~19.4 h can be split across
  evenings.
- Re-verified 2026-09-06: `--print-only` reports 1062 rows / 3 passes /
  ~19.4 h; all four 30 s trims build clean (`ensure_clip`, `-c copy`,
  30.03–30.05 s each); a 2-pass synthetic-power run exercised pass ordering,
  the kept `baseline_elevated` / `baseline_reference_w` / `cache_evicted`
  fields, v0.6.1 stamping (`vmaf_v0.6.1`), per-row checkpointing,
  resume-skips-measured-rows, resume-re-runs-error-rows, and resume of a
  finished artifact as a no-op.
- Box state at that check: queue depth 0, not paused, no lab-session flag, no
  measurement lock, `/queue-status` calendar empty.
## Status (2026-09-07) — passes 1 and 2 are DONE

- **Ran 2026-09-06 21:50 → 09-07 06:53**, two passes, **708/708 rows in 9.06 h**
  (46 s/row, against a 12.9 h estimate). All 🟢, zero errors, VMAF on every row,
  `cache_evicted: True` throughout. Cooldowns settled in a median **4.3 s**
  (max 15.5 s, **zero timeouts**) — the active wait-for-idle doing its job.
  Artifact: `results/calibration/_staging/encode_parity_CLEAN_nvenc_24c_2026-09-06.json`.
- **The contamination flag proved causal.** Ten rows tripped `baseline_elevated`
  (baselines 84.6–103.6 W against ~80–82 W references) and were exactly the rows
  that failed to reproduce: pass-to-pass spread **24.0 % median** against **1.8 %**
  for the 344 clean pairs, with 8 of 10 reading low — the direction an inflated
  `w_base` predicts. Re-measured 09-07 with `--redo-flagged`: every baseline back
  to 78.7–81.8 W, nine of ten values moved up toward their twin, gap **24 % → 3.0 %
  median, 45 % → 6.5 % max**. The originals are kept in the artifact's
  `superseded_rows`, so that comparison stays reproducible.
- **Dataset now**: 708 rows + 10 superseded, zero flagged, zero errors, all 🟢.
  Pass-to-pass agreement median **1.9 %**, p90 5.6 %, max 13.4 %; 87 % of recipes
  within 5 %, 98 % within 10 %.
- **Open**: VMAF is not bit-identical across passes on 39 of 354 recipes, all of
  them `av1 / cpu` (SVT-AV1 is the only non-deterministic encoder here). Trivial
  except `readysetgo / av1 / cpu / 2800k`, 84.26 vs 83.00. Pass 3 will say which
  is the outlier.
- **Still to do**: **pass 3** —
  `--run --resume <artifact> --passes 3` (~6.5 h), which skips all 708 measured
  rows and adds the 354 rep-2 ones. Then the deliberate fold into
  `consolidated_encode_dataset.csv`.

## Section 3 status (for reference)

Section 3.1–3.5 of `SMPTE_2026_paper_skeleton_section3.docx` (a separate
copy — the original skeleton is owned by Tania, no write access from this
session) already reflect the dataset's *current* state, including the
gaps above stated honestly (3.5's fixed-run-order / no-page-cache-mitigation
language, the empty-confidence caveat on iso-quality rows). If the clean
sweep's rows end up replacing the current dataset, that section will need a
pass to update the methodology description accordingly (the "10s flat sleep"
and "no cache mitigation" language would no longer be accurate).
