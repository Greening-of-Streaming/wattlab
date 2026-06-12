# Dual-meter pre-test findings (CR-065 Phase 1)

Captured 2026-06-11. Question: do two daisy-chained Tapo P110s, polled on
staggered 1s schedules, actually deliver ~2× the fresh-sample rate of one
meter — and is the chain statistically clean enough to combine per-meter ΔW?

**Verdict: GATE PASSED — fresh-sample gain 2.5× (gate was ≥1.5×). Proceed
to Phase 2 integration.** Two bonus discoveries below (unequal plug refresh
rates; KLAP session exclusivity) materially shape the integration.

## Background

Analysis of the 30 most recent stored results (2026-06-10/11) showed 22.5%
of consecutive 1s power samples byte-identical at 10 mW resolution —
impossible as real collisions, so the P110's local-API `current_power` was
inferred to refresh only every ~1.3–1.6s. (The published "5s" refresh
figure refers to the app/cloud path, not the local API.) Hypothesis: a second,
independently clocked meter in series roughly doubles fresh samples.

## Setup

- Topology (owner-confirmed): **wall → existing P110 `.159` (outer) →
  new P110 `.91` "GoS1b-server" (inner) → GoS1.** Inner measures the server
  alone; outer additionally sees the inner plug's self-draw.
- Probe: `bin/probe-dual-meter` — per-meter asyncio task, 1.0s period,
  0.5s stagger, raw mW (unrounded), cached KLAP handles. wattlab service
  **stopped** for the run (see KLAP discovery). Load = looped
  `libx264 -preset medium` encode of `meridian_4k.mp4` (plain subprocess).
- Protocol: 180s idle → 240s CPU load → 180s idle. 601–602 polls/meter,
  zero errors, zero schedule overruns.
- Raw data: `results/diagnostics/dual_meter_20260611_170005_raw.csv` (+
  `_summary.json`; rollup line in `results/diagnostics/history.jsonl`).
  ⚠ Label caveat: the run predates the topology confirmation, so the CSV/JSON
  `meter` column is physically swapped — file "inner" = `.159` = physical
  OUTER, file "outer" = `.91` = physical INNER. This doc uses physical labels.

## Results vs gate criteria

| Gate | Threshold | Measured | Verdict |
|---|---|---|---|
| Fresh-sample gain | ≥ ~1.5× | **2.50×** (1.665 vs 0.665 fresh/s, idle) | ✅ |
| Offset stability | idle std ≲ 0.5 W; idle→load shift ≲ ~1 W | mean offset SE 0.14 W; shift −0.84 W (see notes) | ✅ with notes |
| Per-meter ΔW agreement | within combined CI | 78.79 W vs 79.63 W (1.1%, ~1.3 SE) | ✅ |
| Latency p95 ≪ 0.5s slot | ≪ 500 ms | 40 ms / 41 ms; max 84 ms; 0 overruns | ✅ |

### (a) Fresh-sample gain — and the plugs are NOT equal samplers

| Meter | dup rate | plateau histogram | fresh/s | implied refresh |
|---|---|---|---|---|
| outer `.159` (existing, older unit) | 33.4% | perfect alternating {1: 200, 2: 201} | 0.665 | **exactly 1.5s** |
| inner `.91` (new unit) | **0.0%** | {1: 601} — zero dups in 601 polls | 1.0 | **≤1.0s** |

The existing plug's 1,2,1,2 plateau pattern against a drift-free 1s poll
grid pins its internal refresh at exactly 1.5s (⅓ of polls stale — matching
the 22.5% seen in stored results, where request latency stretched the
effective poll period). The new unit never repeated a value: its refresh is
at least 1 Hz and possibly faster — polling it quicker than 1s may yield
more still (untested; Phase 2 keeps 1s).

**Root cause — firmware, not wear: CONFIRMED by controlled experiment
(2026-06-12).** Both units are P110 hw 1.0; the SLOW unit runs the NEWER
firmware — 1.4.0 (Build 251020) vs the fast unit's 1.3.1 (Build 240621).
A third (sacrificial) P110 shipping the same 1.3.1, metering an independent
~69 W load (screen + MacBook), was measured for 10 min at 1 Hz, updated to
1.4.0 via the Tapo app, and measured again — single-variable test:

| | fw 1.3.1 before | fw 1.4.0 after |
|---|---|---|
| dup rate | **0.0%** (600 polls, plateaus {1: 600}) | **33.44%** (plateaus {1: 199, 2: 200}) |
| implied refresh | ≥1 Hz | exactly 1.5 s |
| latency p50/p95 | 26.6 / 43.5 ms | 28.5 / 42.3 ms |

33.44% matches the production outer plug's rate exactly; latency is
unchanged — 1.4.0 purely slows the metering refresh. Raw data:
`results/diagnostics/p110_fw_fw131_before_20260612_001410.{csv,json}` /
`p110_fw_fw140_after_20260612_004223.{csv,json}`.

**Second 1.4.0 hazard — local-API lockout.** Immediately after the update
the plug returned 403 Forbidden on the local API ("Make sure Third-Party
Compatibility is turned on… Me > Third-Party Services") until the setting
was toggled off/on in the app. Had the inner meter auto-updated, every OWL
measurement would have FAILED until that app toggle — not just degraded.

⚠ Operational rules: firmware auto-update is OFF on the inner/primary plug
(owner, 2026-06-11) and meter firmware is part of the measurement setup —
after ANY deliberate plug update, re-run `bin/probe-dual-meter` (or the fw
probe) and re-check duplicate rates before trusting fresh-sample arithmetic.
Follow-up measured (2026-06-12): **fw 1.4.6 (Build 260309, adds MWh
units) is equally slow** — 33.39% dups, plateaus {1: 200, 2: 200}, same
~69 W load (`results/diagnostics/p110_fw_fw146_20260612_010802.{csv,json}`).
Caveat: measured on a DIFFERENT P110 hardware variant (owner-spotted:
EU sells two form factors; the 1.4.6 unit has no earth prong). The variants
report identical `model`/`hw_ver` but distinct `hw_id`/`oem_id`
(earthless `2FB30EF5…`/`18BDC6C7…` vs earthed `CFA3B64E…`/`5CCAC70B…`)
and run separate firmware tracks — which is why the app can call a 1.4.0
plug "up-to-date" while offering 1.4.6 to another. Net picture: every
post-2024 firmware measured on either variant refreshes at exactly 1.5 s;
only 1.3.1 (Jun 2024) samples at ≥1 Hz. The inner meter's 1.3.1 is
effectively irreplaceable — keep auto-update off.

Consequence: even **single-meter** operation improves by 1.5× just by making
the new plug primary — done 2026-06-11 (`.env` swap, `TAPO_P110_IP=.91`).
The dual-meter combined rate is 2.5× the old single-meter rate.

### (b) Inner-plug self-draw (outer − inner, physical labels)

- idle1: **+0.654 W** (n=180 binned diffs, SE 0.14) — consistent with one
  P110's relay+Wi-Fi self-draw; owner confirmed wiring independently.
- idle2: +1.13 W (post-load thermal recovery contaminates this window —
  inner std 8.45 W vs 3.16 W in idle1; treat as noisy, not drift).
- load: −0.19 W (SE 0.34) — the −0.84 W idle→load shift implies a small
  cross-meter gain mismatch (~0.5% at 155 W) opposing the self-draw, and/or
  staleness asymmetry during ramps. Within the ~1 W gate.
- Per-bin diff std (1.9–5.5 W) is dominated by refresh-window misalignment
  (each meter averages a different internal window), NOT offset instability —
  the mean is tight. This is why Phase 2 must combine per-meter ΔW, never
  interleave raw samples from both meters into one stream.

### (c) Cross-meter agreement

ΔW(load − idle1): inner 79.63 W, outer 78.79 W — 1.1% apart, ~1.3 SE:
statistically compatible. 1s-binned load-segment correlation 0.816 (limited
by the outer plug's 1.5s staleness, not by disagreement). The chain gives a
free, continuous cross-calibration check — a lone miscalibrated meter would
show up here.

### (d) Latency / sessions

p50 ≈ 27–30 ms, p95 ≈ 40 ms, max 84 ms per meter; zero overruns; zero
mid-run rebuilds with the service stopped. The 0.5s stagger held.

**KLAP sessions are exclusive per device** (smoke-test discovery): every
fresh handshake invalidates existing sessions on that plug. The live
service's 5s telemetry poller (new client per call) killed the probe's
cached session on `.159` within seconds — 6/30 polls lost, latency thrashed —
until the service was stopped. Phase 2 implications: cached handles MUST
rebuild on 403/`SessionTimeout`, and once the service itself holds cached
handles, nothing else may poll a registered meter out-of-band (the probe and
the service cannot share a plug concurrently).

## Decisions taken

1. **Primary meter = `.91` (new, inner)** — measures GoS1 alone, refreshes
   ≥1 Hz. `.env` swapped 2026-06-11. ⚠ Measurement epoch note: absolute W
   now comes from a different physical unit; cross-meter agreement is ~1%
   (idle offset −0.65 W vs the old meter's readings). The measured quantity
   (GoS1 alone) is unchanged.
2. **Gate passed → Phase 2 proceeds** per the CR-065 plan: meter registry +
   cached handles, shared sampler, per-meter ΔW combine (`method: "ci2"`),
   honest cadence copy ("fresh samples/s", never "0.5-second intervals").
3. Run a variance recalibration after Phase 2 lands (primary meter changed
   units; recal is hygiene — normal ambient only).
