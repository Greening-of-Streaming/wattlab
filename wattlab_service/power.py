"""
power.py — pluggable power + telemetry interface for WattLab.

Currently backed by one or two Tapo P110 smart plugs polled via local Wi-Fi
API (wall power) plus lm-sensors (CPU + GPU temperatures and GPU PPT).

CR-065 dual-meter: with a second plug daisy-chained (wall → outer → inner →
server) and `TAPO_P110_IP_2` set, the shared samplers below poll both meters
on staggered 1s schedules — the P110's local value only refreshes every
~1–1.5s, so two independently-clocked meters ≈ double the fresh-sample rate
(measured 2.5×, see docs/dual_meter_pretest_findings.md). The INNER plug
(`TAPO_P110_IP`) measures the server alone and is always the primary: every
absolute W figure comes from it, and with `TAPO_P110_IP_2` unset behavior is
exactly single-meter. The outer plug additionally sees the inner plug's
self-draw (~0.7 W), which cancels in the per-meter ΔW combine (confidence
"ci2") — raw samples from the two meters are never interleaved into one
stream.

⚠ KLAP sessions are exclusive per device: a fresh handshake invalidates other
sessions on that plug. Device handles are therefore cached per meter and
rebuilt on error — and nothing outside this process may poll a registered
meter concurrently (bin/probe-dual-meter requires the service stopped).

To swap in a different power source (PDU, IPMI, another smart plug brand):
  replace _read_meter_watts() — keep the same signature and return type
  (the fuller PowerBackend protocol is CR-031 §2, deliberately deferred).
"""

import asyncio
import json
import subprocess
import time
from dotenv import dotenv_values
from tapo import ApiClient

import gpu

_config = dotenv_values("/home/gos/wattlab/.env")

# Cached device handles, one per meter IP (KLAP sessions are exclusive — see
# module docstring). The per-IP lock prevents two coroutines (e.g. the runtime
# telemetry poller and a measurement sampler) from double-handshaking or
# interleaving requests on one handle.
_DEVICE_CACHE: dict = {}
_DEVICE_LOCKS: dict = {}


def _meter_ips() -> list:
    """Registered meter IPs. Index 0 = primary = INNER plug (measures the
    server alone). A second entry exists only when `TAPO_P110_IP_2` is set."""
    ips = [(_config.get("TAPO_P110_IP") or "").strip()]
    ip2 = (_config.get("TAPO_P110_IP_2") or "").strip()
    if ip2:
        ips.append(ip2)
    return [ip for ip in ips if ip]


def meter_count() -> int:
    return len(_meter_ips())


async def _read_meter_watts(idx: int = 0, retries: int = 3) -> float:
    """Read one meter (full mW precision), via a cached device handle.
    On any error the handle is dropped and rebuilt on the next attempt —
    the standard recovery for a KLAP session invalidated elsewhere."""
    ip = _meter_ips()[idx]
    lock = _DEVICE_LOCKS.setdefault(ip, asyncio.Lock())
    for attempt in range(retries):
        try:
            async with lock:
                device = _DEVICE_CACHE.get(ip)
                if device is None:
                    client = ApiClient(_config["TAPO_EMAIL"], _config["TAPO_PASSWORD"])
                    device = await client.p110(ip)
                    _DEVICE_CACHE[ip] = device
                result = await device.get_energy_usage()
            return result.current_power / 1000
        except Exception:
            _DEVICE_CACHE.pop(ip, None)
            if attempt == retries - 1:
                raise
            await asyncio.sleep(1)


async def get_power_watts() -> float:
    """Return current system power draw in watts (primary/inner meter).
    Retries 3× on transient errors. Semantics unchanged by CR-065 — cooldown,
    thermal-floor waits and the runtime telemetry poller all stay on this."""
    return await _read_meter_watts(0)


# Back-compat alias — the amdgpu chip resolver now lives on the AMD GPU
# backend (gpu.py). Kept here so existing imports `from power import
# amdgpu_chip` keep working.
amdgpu_chip = gpu.AmdBackend._amdgpu_chip


# --- Meter identity / provenance --------------------------------------------
#
# The physical power source today is a Tapo P110 smart plug polled at 1 Hz over
# the LAN (full mW precision per poll). These constants describe the meter for
# result provenance (stamped by persist alongside gpu_hardware) and for UI copy
# — the power-measurement analogue of gpu.BACKEND.name / gpu.stamp(). Swapping
# to a PDU/IPMI backend (CR-031 §2) updates these in one place; until then they
# are static. A `meter_display_name` setting can override the name for display.
METER_NAME = "Tapo P110"          # meter model shown in UI / stamped on results
METER_KIND = "smart_plug"         # smart_plug | pdu | ipmi | synthetic
METER_RESOLUTION_S = 1.0          # OWL polls at this cadence (CR-031: PDUs may be coarser)


def meter_display_name() -> str:
    """Meter name for UI copy. Settings `meter_display_name` override wins
    (rename/prettify on a swap); otherwise the built-in METER_NAME. Mirrors
    main._gpu_display_name(). Settings imported lazily to avoid an import cycle."""
    try:
        import settings as _cfg
        return _cfg.load().get("meter_display_name") or METER_NAME
    except Exception:
        return METER_NAME


def stamp() -> dict:
    """Provenance stamp for results — the power-measurement analogue of
    gpu.stamp(). Records which meter produced the energy figures and its
    polling resolution, so a future PDU/IPMI swap is never silently compared
    against Tapo runs. Stamped by persist.save_result() next to gpu_hardware.
    Dual-meter runs (CR-065) additionally record the configuration facts —
    measured fresh-sample rates live in docs/dual_meter_pretest_findings.md,
    not here, so the stamp never asserts performance it didn't measure."""
    out = {
        "name": meter_display_name(),
        "kind": METER_KIND,
        "resolution_s": METER_RESOLUTION_S,
    }
    if meter_count() >= 2:
        out["meters"] = meter_count()
        out["topology"] = "daisy_chain"
        out["stagger_s"] = METER_RESOLUTION_S / 2
    return out


def meter_cadence_label() -> str:
    """Serve-time wording for how often power is sampled — the cadence
    analogue of meter_display_name(), consumed via the {METER_CADENCE} token.
    Deliberately claims per-meter cadence, never \"0.5-second intervals\":
    the P110's internal value refreshes slower than the stagger grid (see
    docs/dual_meter_pretest_findings.md)."""
    if meter_count() >= 2:
        return "1-second intervals on each of two staggered meters"
    return "1-second intervals"


def meter_topology_row() -> str:
    """Hardware-disclosure table row describing the dual-meter daisy-chain —
    empty on a single-meter setup. Consumed via the {METER_TOPOLOGY_ROW}
    token on /methodology. States the integrity caveat rather than hiding it:
    the outer meter does not measure the server alone."""
    if meter_count() < 2:
        return ""
    return ("<tr><td>Meter topology</td><td>Two daisy-chained meters "
            "(wall &rarr; outer &rarr; inner &rarr; server), polls staggered "
            "0.5&thinsp;s. Absolute watts come from the inner meter only; the "
            "outer meter also sees the inner plug&rsquo;s self-draw (~0.7 W), "
            "which cancels in the per-meter &Delta;W combine (confidence "
            "method <code>ci2</code>).</td></tr>")


# --- Shared measurement samplers (CR-065) ------------------------------------
#
# ONE implementation of the baseline / during-task polling loops, replacing the
# four near-identical copies that lived in video / llm / image_gen / rag
# (pixop borrows video's). The module-level wrappers there now delegate here,
# keeping their exact legacy signatures and return shapes — existing tests
# that monkeypatch e.g. `video.measure_baseline` are untouched.
#
# `read_watts` is passed in BY THE WRAPPER so it resolves the calling module's
# own `get_power_watts` binding (monkeypatch seam) — it is always the primary
# meter. The secondary meter, when registered, is polled on a parallel task
# staggered by half the interval, via _read_meter_watts(1) directly. Secondary
# failure NEVER fails a run: the stream is marked degraded, the run continues
# primary-only, and the result records meters as degraded instead of silently
# presenting itself as dual-meter.

class TaskReadings(list):
    """Legacy-shaped readings list (each module's historical record format)
    with the dual-meter sidecar riding along as attributes, so every existing
    call site that iterates/serialises the list keeps working unchanged."""
    samples_w_2 = None      # secondary-meter watts (rounded), or None
    degraded = False        # True when the secondary stream dropped mid-run


async def _poll_secondary_baseline(polls: int, interval: float):
    """`polls` staggered reads of the secondary meter. Returns (samples, degraded)."""
    samples = []
    try:
        await asyncio.sleep(interval / 2)
        for _ in range(polls):
            samples.append(round(await _read_meter_watts(1, retries=2), 2))
            await asyncio.sleep(interval)
    except Exception:
        return samples, True
    return samples, False


async def _poll_secondary_task(stop_event: asyncio.Event, interval: float):
    """Staggered secondary-meter reads until stop_event. Returns (samples, degraded)."""
    samples = []
    try:
        await asyncio.sleep(interval / 2)
        while not stop_event.is_set():
            samples.append(round(await _read_meter_watts(1, retries=2), 2))
            await asyncio.sleep(interval)
    except Exception:
        return samples, True
    return samples, False


# CR-070 — rolling idle-floor reference. The most recent baseline mean any
# module measured; sample_baseline() stamps it on every run. The queue worker
# uses it as the floor for the pre-job idle guard ("the next job may not start
# hotter than the last one did"). Deliberately updated on EVERY baseline,
# clean or elevated: a floor that legitimately rose (hardware change, warmer
# room) self-corrects after one flagged job instead of locking all later jobs
# into the max wait.
LAST_W_BASE: float | None = None


async def sample_baseline(polls: int, *, read_watts, read_sensors=None,
                          interval: float = None) -> dict:
    """Shared baseline sampler. Returns
        {w_base, samples_w, sensor_readings?, baseline_samples_w_2?, meter2_degraded?}
    where the *_2 keys appear only on a dual-meter run. `w_base` and
    `samples_w` are always the primary meter — identical to the legacy loops.

    CR-070: when a previous baseline exists (LAST_W_BASE), the result also
    carries {baseline_reference_w, baseline_elevated} — the sanity flag for a
    baseline captured above the rolling idle floor + tolerance. Persisted with
    the raw samples so a hot start is queryable, never silently accepted."""
    global LAST_W_BASE
    reference_w = LAST_W_BASE
    interval = METER_RESOLUTION_S if interval is None else interval
    second = asyncio.create_task(_poll_secondary_baseline(polls, interval)) \
        if meter_count() >= 2 else None
    power_readings = []
    sensor_readings = []
    try:
        for _ in range(polls):
            power_readings.append(await read_watts())
            if read_sensors is not None:
                sensor_readings.append(read_sensors())
            await asyncio.sleep(interval)
    except BaseException:
        if second is not None:
            second.cancel()
        raise
    out = {
        "w_base": round(sum(power_readings) / len(power_readings), 2),
        "samples_w": [round(w, 2) for w in power_readings],
    }
    if reference_w is not None:
        try:
            import settings as _settings
            tol = float(_settings.load().get("cooldown_idle_tolerance_w", 3.0))
        except Exception:
            tol = 3.0
        out["baseline_reference_w"] = round(reference_w, 2)
        out["baseline_elevated"] = bool(out["w_base"] > reference_w + tol)
    LAST_W_BASE = out["w_base"]
    if read_sensors is not None:
        out["sensor_readings"] = sensor_readings
    if second is not None:
        samples_2, degraded = await second
        if degraded or len(samples_2) < 2:
            out["meter2_degraded"] = True
        else:
            out["baseline_samples_w_2"] = samples_2
    return out


async def sample_task(stop_event: asyncio.Event, *, read_watts,
                      read_sensors=None, tuples: bool = False,
                      interval: float = None) -> TaskReadings:
    """Shared during-task sampler. Returns the calling module's legacy record
    shape — dicts {t, watts, **sensors} (video/pixop style) or (t, watts)
    tuples (llm/rag/image style) — as a TaskReadings list carrying the
    secondary meter's samples as a sidecar."""
    interval = METER_RESOLUTION_S if interval is None else interval
    second = asyncio.create_task(_poll_secondary_task(stop_event, interval)) \
        if meter_count() >= 2 else None
    readings = TaskReadings()
    try:
        while not stop_event.is_set():
            watts = await read_watts()
            if tuples:
                readings.append((time.time(), watts))
            else:
                sensors = read_sensors() if read_sensors is not None else {}
                readings.append({"t": time.time(), "watts": watts, **sensors})
            await asyncio.sleep(interval)
    except BaseException:
        if second is not None:
            second.cancel()
        raise
    if second is not None:
        samples_2, degraded = await second
        if degraded or len(samples_2) < 2:
            readings.degraded = True
        else:
            readings.samples_w_2 = samples_2
    return readings


def meters_summary(baseline: dict, readings, task_samples_w: list):
    """Build the optional `energy.meters` block for a dual-meter run.

    Returns None on a single-meter run (energy block unchanged from
    pre-CR-065), {"degraded": True} when the secondary stream dropped (the
    result is honest single-meter data and must say so), or the full block:
    per-meter w_base/w_task/ΔW, the outer meter's raw samples, and the
    combined ΔW (simple mean — each meter's ΔW is computed against its OWN
    baseline, so the inner-plug self-draw seen by the outer meter cancels).
    `baseline_samples_w`/`task_samples_w` at the energy-block top level keep
    their exact historical meaning: the primary/inner meter."""
    baseline = baseline or {}
    b2 = baseline.get("baseline_samples_w_2")
    t2 = getattr(readings, "samples_w_2", None)
    degraded = bool(baseline.get("meter2_degraded")) or \
        bool(getattr(readings, "degraded", False))
    if not (b2 or t2 or degraded):
        return None
    if degraded or not b2 or not t2:
        return {"degraded": True}
    b1 = baseline.get("baseline_samples_w") or baseline.get("samples_w") or []
    if not b1 or not task_samples_w:
        return {"degraded": True}
    w_base_1 = sum(b1) / len(b1)
    w_task_1 = sum(task_samples_w) / len(task_samples_w)
    w_base_2 = sum(b2) / len(b2)
    w_task_2 = sum(t2) / len(t2)
    d1 = w_task_1 - w_base_1
    d2 = w_task_2 - w_base_2
    return {
        "inner": {"w_base": round(w_base_1, 2), "w_task": round(w_task_1, 2),
                  "delta_w": round(d1, 2)},
        "outer": {"w_base": round(w_base_2, 2), "w_task": round(w_task_2, 2),
                  "delta_w": round(d2, 2),
                  "baseline_samples_w": b2, "task_samples_w": t2},
        "combine_method": "mean",
        "delta_w_combined": round((d1 + d2) / 2, 2),
    }


def read_sensors_dict() -> dict:
    """One-shot read of telemetry: CPU Tctl (lm-sensors) + GPU temp/power
    (delegated to the resolved GPU backend — AMD via sensors amdgpu, NVIDIA
    via nvidia-smi). Returns None for any value that can't be parsed. Safe to
    call frequently. The single source of truth — the per-measurement modules'
    `read_sensors()` wrappers delegate here.

    The GPU half is vendor-agnostic: `gpu.read_gpu_sensors()` returns the same
    `{gpu_junction, gpu_ppt_w}` shape regardless of the installed card, so a
    GPU swap needs no change here (see gpu.py / CR-060).
    """
    cpu = None
    try:
        result = subprocess.run(['sensors', '-j'], capture_output=True, text=True)
        data = json.loads(result.stdout)
        cpu = data.get('k10temp-pci-00c3', {}).get('Tctl', {}).get('temp1_input')
    except Exception:
        cpu = None
    g = gpu.read_gpu_sensors()
    return {
        "cpu_tctl": cpu,
        "gpu_junction": g.get("gpu_junction"),
        "gpu_ppt_w": g.get("gpu_ppt_w"),
    }


# CR-050 follow-up — active-probe thermal floor wait. Used between models in
# the /llm/compare, /rag/compare, /image/compare flows to ensure each model's
# baseline measurement starts on a cold system, not on the cooldown ramp of
# the previous (possibly verbose) model. Replaces the fixed llm_rest_s sleep,
# which was insufficient for fast-finishing-but-heavy models like Qwen3 1.7B
# (647 tokens / 5.4 s left the GPU at >125 W well past the 10 s rest).
async def wait_for_thermal_floor(reference_w: float,
                                  tolerance_w: float = 3.0,
                                  poll_interval_s: float = 1.0,
                                  settle_polls: int = 3,
                                  max_wait_s: int = 120,
                                  jobs: dict = None,
                                  job_id: str = None) -> dict:
    """Block until N consecutive P110 readings are at/below reference_w +
    tolerance_w, then return (asymmetric settle — cooler than the captured
    floor counts; the rationale note now lives in idle_wait.py). Max-wait
    cap prevents the loop hanging on a hot day where the floor drifted up.

    Since 2026-07-30 this delegates to idle_wait.wait_for_stable — the SAME
    loop the decode rig's pre-baseline guard runs (self-stability mode) —
    so the two measurement stacks share one settle implementation. This
    wrapper contributes the OWL specifics: the P110 read, the live
    jobs[job_id] cooldown_* fields, and the CR-070 operator-skip probe
    (Lab-gated /job/{id}/cooldown-skip; picked up on the next 1 Hz poll).

    Returns {'waited_s', 'final_w', 'settled' (bool), 'readings', ...} —
    contract unchanged.
    """
    import idle_wait

    def _on_sample(w: float, elapsed: float) -> None:
        if jobs is not None and job_id is not None:
            jobs[job_id]["cooldown_w"] = w
            jobs[job_id]["cooldown_waited_s"] = elapsed
            jobs[job_id]["cooldown_reference_w"] = reference_w

    def _should_skip() -> bool:
        return (jobs is not None and job_id is not None
                and bool((jobs.get(job_id) or {}).pop("cooldown_skip", None)))

    return await idle_wait.wait_for_stable(
        get_power_watts, reference_w=reference_w, tolerance_w=tolerance_w,
        settle_polls=settle_polls, max_wait_s=max_wait_s,
        poll_interval_s=poll_interval_s,
        on_sample=_on_sample, should_skip=_should_skip)


class CooldownCancelled(Exception):
    """Raised by cooldown_between_runs() when the operator picks 'Cancel' in the
    idle-wait timeout dialog. Job runners catch this to abort the run cleanly."""
    pass


# --- Unified cooldown dispatcher ------------------------------------------------
# SINGLE source of truth for every inter-pass cooldown in OWL. Each call site
# (video / llm / rag / image compares + batch) routes through here instead of an
# inline asyncio.sleep() or a direct wait_for_thermal_floor() call, so the
# fixed-vs-idle strategy is decided in exactly one place and is tunable from
# /settings. Variance calibration calls with respect_toggle=False so it always
# keeps its fixed protocol regardless of the toggle.
def _clear_live_cooldown_fields(jobs, job_id):
    """Drop the live idle-wait readout fields once a cooldown concludes, so
    wlCooldownLine (rendered by wlRenderProgress on every page) self-expires
    instead of showing a stale 'Idle wait Ns' through later stages."""
    if jobs is not None and job_id is not None and job_id in jobs:
        for k in ("cooldown_waited_s", "cooldown_w"):
            jobs[job_id].pop(k, None)


async def cooldown_between_runs(*, fixed_seconds, reference_w=None,
                                stage="cooldown", jobs=None, job_id=None,
                                respect_toggle=True, allow_dialog=False,
                                skippable=False) -> dict:
    """Cool down between two measurement passes.

    Strategy is chosen by the `cooldown_wait_for_idle` setting:
      • toggle OFF, or no reference_w, or respect_toggle=False
            → fixed asyncio.sleep(fixed_seconds).            method="fixed"
      • toggle ON
            → active-probe wait_for_thermal_floor() to reference_w.
              settle              → method="idle",          settled=True
              timeout, interactive→ park job: Wait again (≤3) / Run anyway /
                                    Cancel, with a cooldown_dialog_watchdog_s
                                    watchdog that auto-applies the default.
              timeout, otherwise  → ONE fixed_seconds fallback sleep, proceed.
                                    method="idle+fallback",  settled=False

    CR-070: skippable=True (pre-job idle guard only) advertises a live "Run
    job anyway" affordance on the job dict (cooldown_skippable, value = the
    job id so wlCooldownLine can address the skip endpoint). An operator skip
    ends the wait immediately → method="idle+skipped", settled=False.

    Forced-through runs carry settled=False + timed_out=True so a result is never
    silently treated as cleanly-spaced. Returns a dict meant to be persisted into
    the result's energy block: {method, waited_s, settled, final_w, timed_out}.
    """
    import asyncio
    import settings as _settings
    s = _settings.load()

    def _stage(st):
        if jobs is not None and job_id is not None:
            jobs[job_id]["stage"] = st

    use_idle = (respect_toggle
                and bool(s.get("cooldown_wait_for_idle", True))
                and reference_w is not None)

    if not use_idle:
        _stage(stage)
        if jobs is not None and job_id is not None:
            jobs[job_id]["cooldown_fixed_s"] = fixed_seconds
        await asyncio.sleep(fixed_seconds)
        return {"method": "fixed", "waited_s": float(fixed_seconds),
                "settled": True, "final_w": None, "timed_out": False}

    tol = float(s.get("cooldown_idle_tolerance_w", 3.0))
    settle_polls = int(s.get("cooldown_idle_settle_polls", 3))
    max_wait = int(s.get("cooldown_idle_max_wait_s", 120))
    watchdog_s = int(s.get("cooldown_dialog_watchdog_s", 75))

    total_waited = 0.0
    re_waits = 0
    MAX_RE_WAITS = 3
    if skippable and jobs is not None and job_id is not None and job_id in jobs:
        jobs[job_id]["cooldown_skippable"] = job_id
    try:
        while True:
            _stage(stage)
            cd = await wait_for_thermal_floor(
                reference_w, tolerance_w=tol, poll_interval_s=1.0,
                settle_polls=settle_polls, max_wait_s=max_wait,
                jobs=jobs, job_id=job_id,
            )
            total_waited += cd["waited_s"]
            if cd.get("skipped"):
                _clear_live_cooldown_fields(jobs, job_id)
                return {"method": "idle+skipped",
                        "waited_s": round(total_waited, 2),
                        "settled": False, "final_w": cd["final_w"],
                        "timed_out": False}
            if cd["settled"]:
                _clear_live_cooldown_fields(jobs, job_id)
                return {"method": "idle", "waited_s": round(total_waited, 2),
                        "settled": True, "final_w": cd["final_w"],
                        "timed_out": False}

            # --- idle-wait timed out ---
            # Offer the dialog only when the call site opted in (allow_dialog — set
            # at the compare-flow sites where nothing is held across the cooldown so
            # a Cancel unwinds cleanly) AND the run is an attended Lab one
            # (interactive_eligible, read off the job dict — set at enqueue,
            # overridden False by batch/benchmark). No call site threads a tier flag
            # through the measurement functions.
            interactive = bool(allow_dialog and jobs is not None and job_id is not None
                               and jobs.get(job_id, {}).get("interactive_eligible"))
            decision = "fallback"
            if interactive and jobs is not None and job_id is not None:
                decision = await _await_cooldown_decision(
                    jobs, job_id,
                    allow_wait_again=(re_waits < MAX_RE_WAITS),
                    watchdog_s=watchdog_s,
                )

            if decision == "wait" and re_waits < MAX_RE_WAITS:
                re_waits += 1
                continue
            if decision == "cancel":
                raise CooldownCancelled()
            if decision == "run":
                # Operator chose to proceed NOW — no extra sleep.
                _clear_live_cooldown_fields(jobs, job_id)
                return {"method": "idle", "waited_s": round(total_waited, 2),
                        "settled": False, "final_w": cd["final_w"], "timed_out": True}
            # 'fallback' — non-interactive default or watchdog expiry: one fixed
            # sleep guarantees a minimum gap, then proceed.
            _stage(stage)
            if jobs is not None and job_id is not None:
                jobs[job_id]["cooldown_fixed_s"] = fixed_seconds
            await asyncio.sleep(fixed_seconds)
            total_waited += fixed_seconds
            _clear_live_cooldown_fields(jobs, job_id)
            return {"method": "idle+fallback", "waited_s": round(total_waited, 2),
                    "settled": False, "final_w": cd["final_w"], "timed_out": True}
    finally:
        # Withdraw the skip affordance however the wait concluded; drop a skip
        # that raced in after the wait already resolved.
        if jobs is not None and job_id is not None and job_id in jobs:
            jobs[job_id].pop("cooldown_skippable", None)
            jobs[job_id].pop("cooldown_skip", None)


async def _await_cooldown_decision(jobs, job_id, *, allow_wait_again, watchdog_s):
    """Park the job awaiting an operator click on the idle-wait timeout dialog.
    The POST /job/{id}/cooldown-decision endpoint writes
    jobs[job_id]['cooldown_decision']. Returns 'wait' | 'run' | 'cancel', or
    'fallback' if no answer arrives within watchdog_s."""
    import asyncio, time
    jobs[job_id]["cooldown_decision"] = None
    jobs[job_id]["cooldown_decision_options"] = (
        ["wait", "run", "cancel"] if allow_wait_again else ["run", "cancel"]
    )
    jobs[job_id]["stage"] = "awaiting_cooldown_decision"
    t0 = time.time()
    try:
        while time.time() - t0 < watchdog_s:
            d = jobs[job_id].get("cooldown_decision")
            if d in ("wait", "run", "cancel"):
                return d
            await asyncio.sleep(0.5)
        return "fallback"
    finally:
        jobs[job_id]["cooldown_decision"] = None
        jobs[job_id].pop("cooldown_decision_options", None)
