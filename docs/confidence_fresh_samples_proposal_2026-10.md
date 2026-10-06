# Proposal — count fresh samples, not polls, in the confidence SE

**Status:** proposal for Tania's review (2026-10-06). No code changed. Owner asked for it after the P110
refresh investigation; it also closes item #14 of `docs/methodology_vs_code_2026-08-19.md`.

## The problem in one paragraph

OWL polls each Tapo P110 every 1 s, and `confidence.py` treats every poll as an independent sample: the
standard error of ΔW uses the **poll counts** (`n_base`, `n_task`) in both its terms
(`_se_one_meter`: SE = max(calibrated, per-run), each ∝ 1/√n). But a plug only produces a new reading when it
refreshes. Between refreshes it returns the same value again, byte for byte. Those stale repeats add no
information, yet each one is counted, so the SE is too small and the CI too narrow. The **mean is not biased**:
a repeated reading carries the same value the plug was already reporting.

## How often plugs refresh (measured 2026-10-06)

Wobbling load (wall power changes continuously, so every refresh shows), 0.25 s polls, OWL's own API call.
Details and raw data: `docs/dual_meter_pretest_findings.md` § Follow-up 2026-10-06.

| Plug | Firmware / variant | Refresh period |
|---|---|---|
| GoS1 inner `.91` | 1.3.1, earthed | 1.0 s (tested at ~147 W) |
| GoS1 outer `.159` | 1.4.0, earthed | 1.5 s |
| GoS2 outer `.22` | 1.4.8, earthed | 1.5 s at 7 and 33 W |
| GoS2 inner (lab-G1 and lab-G3) | 1.3.1, earthless | **2.0 s below ~12 W**; 1.0 s above ~20 W (~10 % skipped) |
| Earthed 1.3.1 below 12 W | — | **untested** (earthed plugs on order) |

So at 1 s polls a meter delivers one fresh sample per poll (1.3.1 at high power), 0.67 (1.4.x), or 0.5
(earthless 1.3.1 at low power).

## Proposed correction

1. Per meter and per window (baseline, task), **collapse runs of byte-identical consecutive readings** before
   computing n and the standard deviation: `n_fresh` replaces `n` in both SE terms. At mW resolution a true
   repeat is very rare, so the run-collapse is a good proxy for refresh boundaries.
2. Keep the 🟢/🟡 **poll-count gates on poll counts**. They are a task-duration proxy (CR-065), not a sample count.
3. Store `n_fresh_base` / `n_fresh_task` per meter in the `confidence` block so every flag is auditable.
4. Recompute from stored raw samples. Every result since persistence began carries them, so no
   re-measurement is needed. Re-flag, and list any changed flag.

Optional, for discussion: the dual-meter combine `SE = √(SE₁² + SE₂²)/2` assumes the two meters' errors are
independent. Both meters watch the same load, so part of their noise is shared, and that also understates the
SE. A conservative alternative is `(SE₁ + SE₂)/2`.

## Expected impact (computed 2026-10-06 on all of that day's stored results, no code change)

| Node | Results | Fresh/polls, baseline | Fresh/polls, task | SE corrected ÷ current | Flags changed |
|---|---|---|---|---|---|
| GoS1 | 5 | 1.00 | 1.00 | median 1.15 (1.03–1.17) | 0 |
| GoS2 | 62 | **0.55** | 0.97 | median 1.02 (0.73–1.46) | 0 |

For server workloads the correction changes little, because ΔW (20–300 W) is huge next to the SE. The SE can
move either way: dropping repeats changes the per-run standard deviation as well as n. The risk is concentrated
where **ΔW is small and the load is low**, which is the **`/decode` rig**: boxes at ~1–3 W, ΔW of 0.1–1 W,
plugs on fw 1.3.1 (variant per plug unknown). There, CIs may be up to √2 too narrow and some 🟢 flags may not
hold. That audit is a separate open item (`CHANGE_REQUESTS.md` § Deferred items, top entry).

## Questions for Tania

1. Is collapsing identical consecutive readings an acceptable proxy for "fresh sample", or should we model the
   refresh period per firmware explicitly?
2. Correlated-meter SE: keep √(SE₁²+SE₂²)/2, or move to the conservative (SE₁+SE₂)/2?
3. Should a changed flag on an already-published finding trigger a public correction note, in line with the
   2026-08-17 publication rule?
