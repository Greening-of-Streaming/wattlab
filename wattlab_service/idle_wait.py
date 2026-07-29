"""
idle_wait.py — the shared stable-idle wait (convergence, 2026-07-30).

One implementation for both measurement stacks:

  · GoS1 bench — power.wait_for_thermal_floor (CR-070 pre-job guard and the
    active-probe cooldowns) delegates here in REFERENCE mode: settle when a
    reading sits at/below reference_w + tolerance_w for settle_polls
    consecutive polls. Asymmetric on purpose — cooler than the captured
    floor counts as settled (see the rationale comment that lived in
    power.wait_for_thermal_floor since CR-070).

  · decode rig — decode_bench/bench.py's pre-baseline guard runs
    SELF-STABILITY mode (reference_w=None): a freshly booted device has no
    prior floor, so settle when the last settle_polls readings span
    ≤ tolerance_w.

The caller injects the meter read (async callable → watts), an optional
per-sample callback (live UI fields), and an optional skip probe (the
operator's "Run job anyway"). Return shape is wait_for_thermal_floor's
historical contract: {waited_s, final_w, settled, readings, reference_w,
tolerance_w} plus "skipped": True when the skip probe fired.
"""
import asyncio
import time


async def wait_for_stable(read_w, *, tolerance_w, settle_polls, max_wait_s,
                          reference_w=None, poll_interval_s=1.0,
                          on_sample=None, should_skip=None) -> dict:
    t0 = time.time()
    consecutive = 0
    readings = []

    def _result(settled: bool, final_w=None, skipped: bool = False) -> dict:
        out = {"waited_s": round(time.time() - t0, 2),
               "final_w": (final_w if final_w is not None
                           else (readings[-1] if readings else None)),
               "settled": settled,
               "readings": readings,
               "reference_w": reference_w,
               "tolerance_w": tolerance_w}
        if skipped:
            out["skipped"] = True
        return out

    while True:
        elapsed = time.time() - t0
        if elapsed >= max_wait_s:
            return _result(False)
        if should_skip is not None and should_skip():
            return _result(False, skipped=True)
        w = await read_w()
        readings.append(round(w, 2))
        if on_sample is not None:
            on_sample(round(w, 2), round(elapsed, 1))
        if reference_w is not None:
            if w <= reference_w + tolerance_w:
                consecutive += 1
                if consecutive >= settle_polls:
                    return _result(True, final_w=round(w, 2))
            else:
                consecutive = 0
        else:
            tail = readings[-settle_polls:]
            if len(tail) == settle_polls and max(tail) - min(tail) <= tolerance_w:
                return _result(True, final_w=round(w, 2))
        await asyncio.sleep(poll_interval_s)
