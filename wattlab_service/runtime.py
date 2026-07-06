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
import logging
import time
from pathlib import Path

from power import get_power_watts, read_sensors_dict

log = logging.getLogger(__name__)

# Mirrors queue_control.PAUSE_FLAG. When the queue is paused, an operator/tool
# owns the box (e.g. the encode-parity harness measuring from a separate
# process) — the 5s meter poll backs off so it does not contend for the P110's
# exclusive KLAP session. Local path check avoids an import cycle.
_PAUSE_FLAG = Path("/tmp/owl-paused")

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

# CR-067: monotonic timestamp of the last SUCCESSFUL watts poll (NTP-immune, so
# an NTP step can't make the meter look fresh or stale). None until the first
# success. `watts_age_s()` turns it into a staleness signal for /live + /healthz
# — without it a dead Tapo path freezes `watts` at its last value with nothing
# to distinguish "settled idle" from "meter died 20 minutes ago".
_watts_ok_monotonic: float | None = None


def watts_age_s():
    """Seconds since the last successful watts poll, or None if never polled.
    Cheap (arithmetic on a cached monotonic stamp) — safe to call per request."""
    if _watts_ok_monotonic is None:
        return None
    return round(time.monotonic() - _watts_ok_monotonic, 1)


async def power_poller():
    global _watts_ok_monotonic
    while True:
        try:
            # Back off the meter while paused so a separate measuring process
            # (encode-parity harness) owns the P110 without KLAP-session ping-pong.
            if not _PAUSE_FLAG.exists():
                power_cache["watts"] = await get_power_watts()
                _watts_ok_monotonic = time.monotonic()
        except Exception:
            # Keep the stale value, but leave the timestamp untouched so
            # watts_age_s() grows and /healthz can flag a dead meter path.
            log.debug("power_poller: watts read failed, keeping stale value",
                      exc_info=True)
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
    return {**(jobs.get(job_id) or _recover_from_disk(job_id)),
            "watts": power_cache["watts"]}


def _recover_from_disk(job_id: str) -> dict:
    """Restart resilience (owner reports 2026-06-12, ×2): a service restart
    wipes the in-memory jobs dict, so any page left open polling its job got
    `not_found` forever and the progress widget never resolved — even though
    the result had persisted. If a stored result exists for the id, answer
    `done` with it; only truly unknown ids stay not_found. Fail-soft."""
    import json
    from persist import RESULTS_DIR
    try:
        if job_id and job_id.replace("-", "").isalnum():
            for p in RESULTS_DIR.glob(f"*/*_{job_id}.json"):
                return {"status": "done", "stage": "done",
                        "recovered_from_disk": True,
                        "result": json.loads(p.read_text())}
    except Exception:
        pass
    return {"status": "not_found"}
