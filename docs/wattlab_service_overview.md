# WattLab Service Overview — SUPERSEDED

**Superseded 2026-06-11.** This document described the pre-refactor monolith (single `main.py`, the retired `WATTLAB_GATE_PASSWORD` auth, hardcoded VAAPI/AMD encode paths) and is no longer accurate.

- Module map + request/job flows: see [`ARCHITECTURE.md`](../ARCHITECTURE.md)
- Result contract (job_type × mode → renderer): see [`result_envelope.md`](result_envelope.md)

The original AMD-era content (ffmpeg command inventory + parameter glossary) is preserved in git history (`git log -- docs/wattlab_service_overview.md`); the frozen AMD baseline measurements live in [`gpu_swap_amd_baseline.md`](gpu_swap_amd_baseline.md).
