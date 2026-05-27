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


def amdgpu_chip(data: dict) -> "str | None":
    """Pick the discrete GPU's chip key out of a parsed `sensors -j` dict.

    `sensors` names amdgpu chips by PCI address (`amdgpu-pci-0400`, …) and
    that address shifts whenever PCIe enumeration changes — adding the S24
    NVMe data disk moved it `amdgpu-pci-0300` → `amdgpu-pci-0400`, which
    silently broke the old hardcoded lookups (GPU temp/PPT showed "—"). The
    discrete RX 7800 XT is the only amdgpu chip that reports a `junction`
    temperature (the integrated Radeon on the Ryzen exposes just `edge` +
    `PPT`), so resolve by that rather than by a fixed bus address.
    """
    return next((k for k, v in data.items()
                 if k.startswith('amdgpu') and isinstance(v, dict) and 'junction' in v),
                None)


def read_sensors_dict() -> dict:
    """One-shot read of lm-sensors: CPU Tctl, GPU junction temp, GPU PPT (W).
    Returns None for any value that can't be parsed. Safe to call frequently
    (subprocess is ~10ms). The single source of truth — the per-measurement
    modules' `read_sensors()` wrappers delegate here.
    """
    try:
        result = subprocess.run(['sensors', '-j'], capture_output=True, text=True)
        data = json.loads(result.stdout)
        gpu = amdgpu_chip(data)
        cpu = data.get('k10temp-pci-00c3', {}).get('Tctl', {}).get('temp1_input')
        gpu_junc = data.get(gpu, {}).get('junction', {}).get('temp2_input')
        gpu_ppt = data.get(gpu, {}).get('PPT', {}).get('power1_average')
        return {
            "cpu_tctl": cpu,
            "gpu_junction": gpu_junc,
            "gpu_ppt_w": gpu_ppt,
        }
    except Exception:
        return {"cpu_tctl": None, "gpu_junction": None, "gpu_ppt_w": None}


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
