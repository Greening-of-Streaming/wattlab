# Decode audit, step 1 — P110 stale repeats at box power (2026-10-06)

**Status:** read-only audit; no stored result or finding changed. Owner request (`CHANGE_REQUESTS.md`
§ Deferred items, top entry). Script, output and per-run table:
`/srv/data/owl/campaign_2026-10-06_decode_audit/{audit.py,audit_out.txt,audit_rows.json}`.

**Method.** For all **2,381 decode runs** (1,034 stored results) that carry raw samples: collapse runs of
byte-identical consecutive readings ("fresh samples") and recompute the flag with OWL's `confidence.confidence()`
and today's settings, (a) on all polls, which reproduces the current method (2,342/2,381 stored flags reproduced;
the rest predate settings changes), and (b) on fresh samples only. The difference between (a) and (b) is
purely the correction proposed in `docs/confidence_fresh_samples_proposal_2026-10.md`.

## 1. Every rig plug holds each reading ~2 s at box power

| Meter (all fw 1.3.1) | Box | Runs | Box W (median) | Fresh share base / task | Mean hold |
|---|---|---|---|---|---|
| `.155` | Bbox 4K | 459 | 6.2 | 0.55 / 0.53 | 1.9–2.0 s |
| `.36` | Google TV | 432 | 1.3 | 0.48 / 0.45 | 2.1–2.3 s |
| `.146` | Fire TV Stick (and Pi 5) | 251 (+105) | 1.5 (3.2) | 0.47 / 0.44 | 2.1–2.3 s |
| `.31`, `.33`, `.1`, `.184`, `.113`, `.169`, `.170` | Pi 400, Xiaomi ×2, Apple TV, Pi 5, Roku, W5 | 25–169 each | 1.8–3.8 | 0.46–0.55 | 1.9–2.4 s |
| `.71` | **LG C2 panel** | 146 | **49.9** | **0.99 / 1.00** | **1.0 s** |

This matches the 2026-10-06 wobble-load finding exactly: fw 1.3.1 refreshes every **2 s below ~12 W** and every
1 s at higher power (the C2 at 50 W). It holds across plugs from both MAC batches (`bc:07:1d…`, `b8:fb:b3…`),
so it is unlikely to be specific to the earthless variant. The earthed-plug test on arrival will settle that.

## 2. Effect on flags

- SE on fresh samples vs all polls: **median ×1.20**, p90 ×1.38, max ×1.90.
- **42 of 2,381 flags change (1.8 %)**: 27 🟢→🟡, 14 🟡→🔴, 1 🔴→🟡. These are small-ΔW rows (median |ΔW| 0.15 W,
  range 0.04–0.96 W): Fire TV 17, Bbox 12, Google TV 7, Apple TV 5, Xiaomi 1.

## 3. Published findings and SMPTE

- **106 runs** behind the published decode findings were audited. **One** changed:
  `d507b5ad` Bbox `bbb_h265_loop`, ΔW +0.112 W, 🟡→🔴. It sits in a source job of
  `stb-decode-and-play-content-over-codec`, but that finding **excludes the Bbox from its claim** ("its cells are
  inside its own noise"). The cited Google TV and Fire TV long-window rows stay 🟢. **No published claim changes.**
- **SMPTE 2026 tables:** server-side *encode* datasets (GoS1 at ~75–300 W, inner meter refreshing every 1 s), not
  decode. No decode job is cited in them, so they are outside this issue. Their outer meter (fw 1.4.0, 1.5 s) is
  the older, already-known item #14 in `methodology_vs_code`, which the fresh-sample proposal also covers.

## 4. What stays open

- Adopting the correction in `confidence.py` (Tania's call: `docs/confidence_fresh_samples_proposal_2026-10.md`).
  Once adopted, re-flag the 42 runs in stored results.
- Observation for the same review: the calibrated SE term uses the **server's** idle CV (`variance_idle_pct`,
  calibrated on GoS1 at ~78 W) scaled by `max(w_base, 1 W)` for a 1–3 W box. The per-run term dominates on
  decode rows, but the calibrated floor was never meant for this load range.
- Earthed P110 at fw 1.3.1 below 12 W (plugs on order).
