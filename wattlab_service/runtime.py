"""
Shared request-time runtime state — Phase 3 of the 2026-06 refactor
(ARCHITECTURE.md). The per-feature route modules and main.py all read job
state and live telemetry from here, so no feature module ever imports main.

Contents:
  jobs         — the (deliberately free-form, see review risk #3) job dict.
                 Mutated in place everywhere; never reassign it.
  power_cache  — live wall-power + thermals, filled by the two pollers below.
  job_status() — the shared /<feature>/job/{id} response shape.
"""
import asyncio

from power import get_power_watts, read_sensors_dict

jobs: dict = {}

# --- Live telemetry cache ---
# Two background loops populate this (started from main.py's startup hook).
# All /power, /live, and the live-polling UI read from here, so multiple
# browser sessions don't each hammer the P110 or shell-out to `sensors`
# independently.
#   watts         — Tapo P110 wall-power, polled every 5s
#   cpu_tctl      — Ryzen Tctl (°C), polled every 2s
#   gpu_junction  — GPU junction temp (°C), polled every 2s
#   gpu_ppt_w     — GPU self-reported package power (W), polled every 2s
power_cache: dict = {
    "watts": None,
    "cpu_tctl": None,
    "gpu_junction": None,
    "gpu_ppt_w": None,
}


async def power_poller():
    while True:
        try:
            power_cache["watts"] = await get_power_watts()
        except Exception:
            pass  # keep stale value on transient errors
        await asyncio.sleep(5)


async def sensors_poller():
    """Cheap subprocess call into lm-sensors; 2s cadence so temperature changes
    during a workload are visible in near-real-time on the live badge."""
    loop = asyncio.get_event_loop()
    while True:
        try:
            d = await loop.run_in_executor(None, read_sensors_dict)
            power_cache.update(d)
        except Exception:
            pass
        await asyncio.sleep(2)


def job_status(job_id: str) -> dict:
    return {**jobs.get(job_id, {"status": "not_found"}),
            "watts": power_cache["watts"]}
