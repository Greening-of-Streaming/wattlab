# Clean-protocol re-run — plan, rationale, status

Working notes for `run_clean_sweep.py`, written while drafting Section 3
(Methodology) of the SMPTE paper. Captures the measurement-integrity gaps
found in the existing encode-parity dataset, the fix, and where things stand
as of 2026-09-02 (Ben running it tonight).

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

## Scope

Same design as the existing dataset, **n=1 per point** (deliberately — real
repeat replication, e.g. n=3, is a separate, larger decision, not bundled
into this fix). Same matched ladder ReadySetGo was already swept at
(`MATCHED_BITRATES`, the post-ceiling-extension ladder — H.264 7 points /
H.265 7 / AV1 6), applied identically to all three contents this time:

| Clip | Codecs | Profiles (1080p sweep) | Profiles (ABR-ladder rungs) |
|---|---|---|---|
| Meridian, BBB, ReadySetGo | H.264, H.265, AV1 | cpu, gpu_baseline, gpu_tuned | cpu, gpu_baseline |

**252 rows total** (180 sweep + 72 ladder), confirmed via `--print-only`.

**Not in scope for this run** (separate, later items — not forgotten, just
not bundled in):
- Real statistical replication (n>1). This run stays n=1, same as before.
- The bitrate-ceiling extension beyond `MATCHED_BITRATES` (already folded
  into the ladder used here, so no separate extension pass is needed).
- The per-1,000-encoded-frames normalization question left as a TODO in the
  paper draft's Section 3.4 — orthogonal to this run's data-collection fixes.

## Time estimate

Anchored to a real number: the actual ReadySetGo campaign logged
**4596.7s / 84 rows = 54.7s/row** under the *old* flat-10s-cooldown
protocol. Budgeting **+~10s/row** for a genuine settle-verified wait instead
of an unverified flat sleep (cache eviction itself adds <1s/row, negligible)
gives **~65s/row**, so:

**252 rows × ~65s ≈ 4.5 hours**, unattended. Fits one overnight run.

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
```

Checkpoints to `results/calibration/_staging/encode_parity_CLEAN_<fingerprint>_<date>.json`
after every row, so a crash or dropped session mid-run leaves a valid partial
artifact, same convention as `parity.run_campaign()`. On completion, restores
`/tmp/owl-paused` / `/tmp/owl-lab-session` / `/tmp/gos-measure.lock` even on
failure (`finally` block).

## Status (2026-09-02)

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

## Section 3 status (for reference)

Section 3.1–3.5 of `SMPTE_2026_paper_skeleton_section3.docx` (a separate
copy — the original skeleton is owned by Tania, no write access from this
session) already reflect the dataset's *current* state, including the
gaps above stated honestly (3.5's fixed-run-order / no-page-cache-mitigation
language, the empty-confidence caveat on iso-quality rows). If the clean
sweep's rows end up replacing the current dataset, that section will need a
pass to update the methodology description accordingly (the "10s flat sleep"
and "no cache mitigation" language would no longer be accurate).
