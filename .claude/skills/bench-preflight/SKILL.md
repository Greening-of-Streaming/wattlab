---
name: bench-preflight
description: Measurement-integrity checklist to run BEFORE any powered measurement on GoS1 or the portable rigs — service/queue state, KLAP meter exclusivity, idle-floor sanity, ambient, focus mode, meter roles. Use before launching a probe, calibration, campaign, or any bin/probe-* script, or when the user says "preflight", "are we clear to measure", or types /bench-preflight.
argument-hint: [what you're about to measure]
---

# Bench preflight (WattLab / OWL)

Run down this list before any powered run. Target: $ARGUMENTS

## 0. Do you even need a re-baseline?

Pure-software refactors are energy-imperceptible — only encode-param / kernel / affinity /
binary / clock changes confound measurement. If the change since the last baseline is
software-only, say so and skip the re-baseline, not the preflight.

## 1. Service + queue state

- `curl -s http://127.0.0.1:8000/live` — queue_depth must be 0; never measure alongside a queued job.
- Staging/maintenance flag: check `/tmp/owl-maintenance` (stage-on does NOT auto-lower it).
- Demo lock off unless this IS the demo.

## 2. Meter access — KLAP sessions are exclusive per device

- Standalone probes (`bin/probe-*`, decode-bench with a GoS1-registered plug) need the wattlab
  service **stopped** first — the P110 KLAP session can't be shared. Restart it after.
- In-harness runs go through the queue and the shared sampler instead — never both at once.
- Roles: inner `.91` (fw 1.3.1, ≥1 Hz) = primary, provides w_base + samples; outer `.159`
  (fw 1.4.0, 1.5 s) = second meter; headline ΔW = ci2 per-meter combine. Never claim "0.5 s
  intervals"; **never fw-update a meter casually** (fw is measurement setup — re-probe after any change).

## 3. Baseline sanity

- Expected GoS1 idle floor: **~79 W display-blanked / ~101 W active display** (post-5080, basement).
  A first baseline well above that = something's still hot; wait, don't measure into it.
- Queued jobs are guarded by CR-070 (rolling `power.LAST_W_BASE` floor); **manual/bench runs get
  no guard** — check the floor yourself. Hot baselines under-count ΔW (they never inflate, but
  they still bias).

## 4. Ambient + focus

- Variance calibration is ambient-sensitive (2–6× swing in heat waves). Don't calibrate — and
  don't trust fresh 🟢/🟡 boundaries — under anomalous ambient; basement normal only.
- In-harness runs handle focus mode + `/tmp/gos-measure.lock` themselves. Manual bench work on
  GoS1: confirm the background timers (sysstat-collect, anacron, fwupd-refresh, apt-daily*,
  man-db, motd-news, update-notifier-download) aren't about to fire mid-window.

## 5. GPU runs specifically

- Boost clocks overclock fixed-function NVENC (finding `gpu-boost-overclocks-fixed-function-nvenc`) —
  comparative encode rows need the clock pin, or the caveat.
- Between VMAF-scored passes, remember GPU scoring heats the GPU (CPU scoring stays cleaner).

Report the checklist outcome (pass / what's blocking) before starting the run.
