# SMPTE 2026 paper — data artifacts

Working directory for datasets and derived tables backing the SMPTE paper.
Nothing here is served by OWL; these are frozen citation artifacts.

## Contents

- `make_iso_vmaf_table.py` — generator; re-run to rebuild the CSV from the
  latest complete calibration artifact.
- `iso_vmaf_table.csv` — iso-quality (matched-VMAF) view of the encode-parity
  campaign: per clip × codec × profile, the interpolated bitrate needed to hit
  each VMAF target (88/90/92/94/96) and the Wh/min at that bitrate.

## Provenance

- Source dataset: `results/calibration/encode_parity_nvenc_24c_2026-06-20.json`
  (207 rows, complete, all 🟢) — the S53 encode-parity campaign, measured
  2026-06-20 on GoS1 (Ryzen 9 7900 / RTX 5080), Tapo P110 dual-meter protocol.
  Raw sweep also downloadable at `/video/budget/data.csv`.
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
