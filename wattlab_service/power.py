"""
power.py — pluggable power + telemetry interface for WattLab.

Currently backed by a Tapo P110 smart plug polled via local Wi-Fi API
(wall power) plus lm-sensors (CPU + GPU temperatures and GPU PPT).

To swap in a different power source (PDU, IPMI, another smart plug brand):
  replace get_power_watts() — keep the same signature and return type.
  Everything else (polling loops, baseline measurement, energy maths)
  lives in the individual measurement modules and needs no changes.
"""

import asyncio
import json
import subprocess
from dotenv import dotenv_values
from tapo import ApiClient

import gpu

_config = dotenv_values("/home/gos/wattlab/.env")


async def get_power_watts() -> float:
    """Return current system power draw in watts. Retries 3× on transient errors."""
    for attempt in range(3):
        try:
            client = ApiClient(_config["TAPO_EMAIL"], _config["TAPO_PASSWORD"])
            device = await client.p110(_config["TAPO_P110_IP"])
            result = await device.get_energy_usage()
            return result.current_power / 1000
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(1)


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
    against Tapo runs. Stamped by persist.save_result() next to gpu_hardware."""
    return {
        "name": meter_display_name(),
        "kind": METER_KIND,
        "resolution_s": METER_RESOLUTION_S,
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
    """Block until N consecutive P110 readings are within ±tolerance_w of
    reference_w, then return. Max-wait cap prevents the loop hanging on a
    hot day where the floor itself has drifted up.

    Updates jobs[job_id] with cooldown_w + cooldown_waited_s on every poll
    so the UI can show live progress.

    Returns {'waited_s', 'final_w', 'settled' (bool), 'readings'}.
    """
    import asyncio, time
    t0 = time.time()
    consecutive = 0
    readings = []
    while True:
        elapsed = time.time() - t0
        if elapsed >= max_wait_s:
            return {"waited_s": round(elapsed, 2),
                    "final_w": readings[-1] if readings else None,
                    "settled": False,
                    "readings": readings,
                    "reference_w": reference_w,
                    "tolerance_w": tolerance_w}
        w = await get_power_watts()
        readings.append(round(w, 2))
        if jobs is not None and job_id is not None:
            jobs[job_id]["cooldown_w"] = round(w, 2)
            jobs[job_id]["cooldown_waited_s"] = round(elapsed, 1)
            jobs[job_id]["cooldown_reference_w"] = reference_w
        # Asymmetric settle: "at or below floor" counts as settled, "above
        # floor by > tolerance" does not. A reading at or below the captured
        # reference means residual heat has dissipated — there's no reason
        # to wait for power to come back UP to a match. Without this, runs
        # where the system genuinely cooled below the captured reference
        # (focus mode reducing background load, ambient drop, VRAM freed
        # since the reference was captured) blocked forever and timed out.
        if w <= reference_w + tolerance_w:
            consecutive += 1
            if consecutive >= settle_polls:
                return {"waited_s": round(time.time() - t0, 2),
                        "final_w": round(w, 2),
                        "settled": True,
                        "readings": readings,
                        "reference_w": reference_w,
                        "tolerance_w": tolerance_w}
        else:
            consecutive = 0
        await asyncio.sleep(poll_interval_s)


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
                                respect_toggle=True, allow_dialog=False) -> dict:
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
    while True:
        _stage(stage)
        cd = await wait_for_thermal_floor(
            reference_w, tolerance_w=tol, poll_interval_s=1.0,
            settle_polls=settle_polls, max_wait_s=max_wait,
            jobs=jobs, job_id=job_id,
        )
        total_waited += cd["waited_s"]
        if cd["settled"]:
            _clear_live_cooldown_fields(jobs, job_id)
            return {"method": "idle", "waited_s": round(total_waited, 2),
                    "settled": True, "final_w": cd["final_w"], "timed_out": False}

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
