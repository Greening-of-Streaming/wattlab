# SMPTE 2026 paper — data artifacts

Working directory for datasets and derived tables backing the SMPTE paper.
Nothing here is served by OWL; these are frozen citation artifacts.

## Contents

- `consolidated_encode_dataset.md` / `.csv` — the canonical consolidated encode dataset
  (schema, provenance rules, nine `dataset` values; 569 rows incl. the ReadySetGo leg).
- `CLEAN_SWEEP.md` — plan/rationale/status for the clean-protocol re-run; documents three
  measurement-integrity gaps in the harness (flat 10 s wait-for-idle, dropped contamination
  flag, no cache mitigation).
- `run_clean_sweep.py` — the self-contained clean-protocol re-run (Meridian, BBB, ReadySetGo).
- `run_sport_clip_sweep.py` — SMPTE-only encode-parity campaign for the ReadySetGo sport clip
  (caveat-9 matched content; does not touch `parity.py`).
- `finalize_readysetgo_v0.py` — rescores the ReadySetGo sweep to VMAF v0.6.1 (v1 kept as `vmaf_v1_bonus`).
- `append_readysetgo_to_consolidated.py` — one-shot fold of the ReadySetGo rows into the consolidated CSV.
- `make_iso_vmaf_table.py` / `iso_vmaf_table.csv` — iso-quality (matched-VMAF) view of the
  encode-parity campaign: per clip × codec × profile, the interpolated bitrate needed to hit
  each VMAF target (88/90/92/94/96) and the Wh/min at that bitrate.
- `make_readysetgo_iso_vmaf_table.py` / `readysetgo_iso_vmaf_table.csv` — the same iso-VMAF
  interpolation, standalone for the ReadySetGo sweep.
- `SMPTE_2026_paper_skeleton.docx`, `SMPTE_2026_paper_skeleton_section3.docx` — paper skeleton drafts (Tania).

## Provenance

- Source dataset: the canonical 240-row consolidated encode dataset plus its bitrate-ceiling
  extension (and the 2026-08-28/29 ReadySetGo leg) — see `consolidated_encode_dataset.md`.
  All rows measured on GoS1 (Ryzen 9 7900 / RTX 5080), Tapo P110 dual-meter protocol; the
  original S53 artifact (`results/calibration/encode_parity_nvenc_24c_2026-06-20.json`, 207 rows)
  is one of its inputs. `CLEAN_SWEEP.md` documents three measurement-integrity gaps in the
  harness that produced these rows. Raw sweep also downloadable at `/video/budget/data.csv`.
- Only the 1080p sweep rows feed the curves (ladder rungs are fixed-bitrate and
  excluded), matching the live `/video/budget` derivation
  (`/methodology#energy-budget`).
- Unlike the budget page, all three profiles are emitted (cpu, gpu_baseline,
  gpu_tuned) — the page collapses GPU to the shipped choice per codec.

## Caveats for the paper

- **VMAF v0.6.1** (default model) throughout — the campaign predates OWL's v1
  adoption (S55). Internally consistent; do not mix with v1-stamped scores.
- Iso-VMAF values are **interpolated between measured sweep points**, not
  independently measured at the target quality — state this in methodology.
- An empty `bitrate_kbps_at_target` means the target exceeds the best VMAF the
  sweep reached for that combo (`max_measured_vmaf` column), not "zero cost".
- Where the **lowest** measured bitrate already beats the target (common on
  Meridian, the low-complexity clip), the value clamps to that lowest sweep
  point — so identical rows across targets 88–92 mean "floor of the sweep",
  and the true iso-quality bitrate may be lower than shown.
