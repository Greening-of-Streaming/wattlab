#!/usr/bin/env python3
"""CR-077: device-onboarding idle-settle characterization tool.

Triggered by a live incident (2026-08-27): the Apple TV's decode campaign
silently corrupted its own baselines for about an hour because the rig's
generic settle/baseline protocol (5 s settle, 20-sample baseline — tuned
against the Android boxes' fast post-`stop` return to idle) was applied to
a device that needed 5x longer, and nobody had *measured* the mismatch —
only guessed at it (see `rig.py`'s own comment on `expected_boot_s` /
`boot_threshold_w`: "placeholders until the first live verification").

What this does, once per new device (or any time a device's behaviour is in
doubt), NOT on every campaign run:
  1. Boot phase — power on, poll the plug + `rig.probe_ready` until ready;
     records the boot power/time trace (candidate `expected_boot_s` /
     `boot_threshold_w`).
  2. Decay phase, N reps — run a short representative task via the SAME
     driver classes the rig actually uses (`bench.DRIVERS`, built from a
     real `decode_run._materialize()` config — no reimplementing adb/ssh/
     webos/pyatv control), stop it, then poll the plug at fine cadence for
     a generous fixed observation window. That raw curve is ground truth.
  3. Verdict — replay `idle_wait.wait_for_stable` (self-stability mode,
     the EXACT primitive both `decode_bench.wait_for_stable_idle` and
     GoS1's own CR-070 pre-job guard use) against each recorded curve to
     see when it WOULD have declared "settled", and compares that against
     the curve's true final floor. If the guard's early declaration turns
     out to sit outside tolerance of the true floor in any rep — the Apple
     TV failure mode — the tool recommends a `min_settle_s` /
     `min_baseline_samples` floor (the mechanism `decode_run.py` already
     applies per-device); otherwise it says the guard alone is enough.

Generalized on purpose: the curve-analysis functions (`detect_true_floor`,
`replay_guard_convergence`, `verdict_for_curve`) are pure — they take a
list of (t, w) samples and know nothing about adb/ssh/pyatv/Tapo. The only
hardware-specific piece is `RigDeviceSampler`, which satisfies a 4-method
protocol (`power_on`, `wait_ready`, `run_task_then_stop`, `read_w`). A
future onboarding target that ISN'T a rig device — a second GoS1-class
server (read_w = the P110 already used for CR-070; run_task_then_stop = an
encode or LLM job), or OWL moved to a cloud host (read_w = whatever power/
cost proxy that platform offers) — reuses the same analysis by writing a
new class with those four methods, not by rewriting this file.

Usage:
  python3 onboard_device.py --device atv --template loop_bbbiso_h264 \\
      --reps 3 --hold-s 20 --obs-s 90 --out /srv/data/owl/onboard_atv.md

Advisory only: prints/writes the recommendation, never edits rig.py.
"""
import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/gos/wattlab/wattlab_service")
import decode_run  # noqa: E402
import idle_wait  # noqa: E402
import rig  # noqa: E402
from bench import DRIVERS  # noqa: E402  (decode_bench/ is this script's own dir)


# --- Pure curve analysis (no hardware, unit-testable) ------------------------

def detect_true_floor(samples: list, tail_frac: float = 0.25) -> float:
    """Ground-truth idle floor: median of the last `tail_frac` of the curve.
    Assumes the observation window was long enough to actually flatten —
    the report prints the whole curve so a human can check that visually."""
    n = max(1, round(len(samples) * tail_frac))
    return statistics.median(w for _, w in samples[-n:])


def detect_true_settle_time(samples: list, floor_w: float, tolerance_w: float) -> float | None:
    """First t after which EVERY remaining sample stays within tolerance of
    the true floor — i.e. the last time the curve permanently entered the
    band. None if it never does (observation window too short)."""
    for i in range(len(samples)):
        if all(abs(w - floor_w) <= tolerance_w for _, w in samples[i:]):
            return samples[i][0]
    return None


def replay_guard_convergence(samples: list, tolerance_w: float, settle_polls: int) -> float | None:
    """Self-stability replay of idle_wait's own rule (reference_w=None):
    settled when the last `settle_polls` readings span <= tolerance_w.
    Returns the time it WOULD have declared settled, or None if it never
    would within the recorded window (this is the guard's actual decision
    procedure, run offline against a fixed curve — not a live poll)."""
    window = []
    for t, w in samples:
        window.append(w)
        if len(window) > settle_polls:
            window.pop(0)
        if len(window) == settle_polls and (max(window) - min(window)) <= tolerance_w:
            return t
    return None


def verdict_for_curve(samples: list, tolerance_w: float, settle_polls: int) -> dict:
    """One rep's analysis: true floor/settle time vs what the guard would
    have declared, and whether that declaration was a false-early settle
    (declared "stable" while the box was still on its way down)."""
    floor_w = detect_true_floor(samples)
    true_settle_s = detect_true_settle_time(samples, floor_w, tolerance_w)
    guard_settle_s = replay_guard_convergence(samples, tolerance_w, settle_polls)
    # False-early-settle: the guard declared victory strictly before the
    # curve actually, permanently entered the tolerance band.
    false_early = (guard_settle_s is not None and true_settle_s is not None
                   and guard_settle_s < true_settle_s)
    return {"floor_w": round(floor_w, 3),
            "true_settle_s": true_settle_s,
            "guard_settle_s": guard_settle_s,
            "false_early_settle": false_early,
            "max_w": round(max(w for _, w in samples), 3),
            "min_w": round(min(w for _, w in samples), 3),
            "n": len(samples)}


def recommend(verdicts: list, tolerance_w: float, cadence_s: float) -> dict:
    """Roll N reps' verdicts into one recommendation. min_settle_s covers
    the worst-case true settle time seen (+1 cadence margin); idle_w is the
    mean floor; any false-early-settle rep means the guard alone is not
    trustworthy for this device."""
    floors = [v["floor_w"] for v in verdicts]
    true_settles = [v["true_settle_s"] for v in verdicts if v["true_settle_s"] is not None]
    guard_ok = not any(v["false_early_settle"] for v in verdicts)
    min_settle_s = (max(true_settles) + cadence_s) if true_settles else None
    return {"idle_w": round(statistics.mean(floors), 2) if floors else None,
            "idle_w_range": (round(min(floors), 2), round(max(floors), 2)) if floors else None,
            "guard_alone_sufficient": guard_ok and true_settles,
            "min_settle_s": round(min_settle_s) if min_settle_s else None,
            "min_baseline_samples": round((min_settle_s or 0) * 0.6 / cadence_s) if min_settle_s else None,
            "reps_with_data": len(true_settles), "reps_total": len(verdicts)}


# --- Hardware-specific sampler (rig devices) ---------------------------------

class RigDeviceSampler:
    """Drives one rig.py device via the SAME control path the service uses:
    rig.device_on/probe_ready for power, decode_run._materialize + bench's
    own DRIVERS classes for prepare/start/stop — no reimplementation of
    adb/ssh/webos/pyatv control."""

    def __init__(self, name: str, template: str):
        self.name = name
        self.dev_cfg = rig.RIG["devices"][name]
        self.template = template

    async def power_on(self):
        if rig.rig_cache["devices"][self.name]["state"] in ("off", "unpowered", "unreachable"):
            await rig.device_on(self.name)

    async def wait_ready(self, timeout_s: float) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout_s:
            if await asyncio.to_thread(rig.probe_ready, self.dev_cfg):
                return True
            await asyncio.sleep(2)
        return False

    async def read_w(self) -> float:
        return (await rig.plug_status(self.dev_cfg["plug_ip"]))["watts"]

    def _driver(self, window_s: int):
        job_id = f"onboard-{int(time.time())}"
        p = decode_run._materialize(job_id, self.template, self.name, "headless",
                                    False, window_s=window_s)
        try:
            import json
            cfg = json.loads(p.read_text())
        finally:
            p.unlink()
        driver = DRIVERS[cfg["device"]["type"]](cfg["device"])
        run = cfg["runs"][0]
        return driver, run

    async def run_task_then_stop(self, hold_s: float):
        """Real prepare -> start -> hold -> stop, via the actual driver."""
        driver, run = await asyncio.to_thread(self._driver, max(30, int(hold_s) + 10))
        await asyncio.to_thread(driver.prepare, run)
        await asyncio.to_thread(driver.start, run)
        await asyncio.sleep(hold_s)
        await asyncio.to_thread(driver.stop, run)


# --- Orchestration ------------------------------------------------------------

async def sample_for(sampler, seconds: float, cadence_s: float) -> list:
    t0 = time.monotonic()
    out = []
    while time.monotonic() - t0 < seconds:
        w = await sampler.read_w()
        out.append((round(time.monotonic() - t0, 2), round(w, 3)))
        await asyncio.sleep(cadence_s)
    return out


async def characterize(sampler, reps: int, hold_s: float, obs_s: float,
                       cadence_s: float, tolerance_w: float, settle_polls: int,
                       boot_timeout_s: float = 120, boot_settle_s: float = 45):
    print(f"[boot] powering on {sampler.name}...", flush=True)
    t0 = time.monotonic()
    await sampler.power_on()
    boot_curve = []
    ready = False
    while time.monotonic() - t0 < boot_timeout_s:
        w = await sampler.read_w()
        boot_curve.append((round(time.monotonic() - t0, 2), round(w, 3)))
        if await asyncio.to_thread(rig.probe_ready, sampler.dev_cfg):
            ready = True
            break
        await asyncio.sleep(cadence_s)
    boot_s = boot_curve[-1][0] if boot_curve else None
    print(f"[boot] ready={ready} after {boot_s}s, {len(boot_curve)} samples", flush=True)

    # 2026-08-27: found live against the Pi 5 — starting rep 1 right at
    # boot-ready mixes lingering post-boot settling into the FIRST decay
    # rep, inflating its true_settle_s with something that isn't the
    # post-stop property this tool is trying to measure (Pi 5 rep 1 showed
    # a spurious ~39 s "decay" that was actually still-cooling-from-boot;
    # reps 2-3, run after this same buffer would have elapsed naturally,
    # settled in <1 s). A boot-settle buffer before rep 1 keeps every rep
    # measuring the same thing: decay from a genuinely warmed-up state.
    if ready and boot_settle_s > 0:
        print(f"[boot] warm-up buffer {boot_settle_s}s before rep 1...", flush=True)
        await asyncio.sleep(boot_settle_s)

    reps_curves, verdicts = [], []
    for rep in range(1, reps + 1):
        print(f"[rep {rep}/{reps}] run {hold_s}s then stop, observe {obs_s}s @{cadence_s}s...", flush=True)
        await sampler.run_task_then_stop(hold_s)
        curve = await sample_for(sampler, obs_s, cadence_s)
        v = verdict_for_curve(curve, tolerance_w, settle_polls)
        print(f"[rep {rep}/{reps}] floor {v['floor_w']}W  true_settle {v['true_settle_s']}s  "
              f"guard_settle {v['guard_settle_s']}s  false_early={v['false_early_settle']}", flush=True)
        reps_curves.append(curve)
        verdicts.append(v)

    rec = recommend(verdicts, tolerance_w, cadence_s)
    return {"boot_curve": boot_curve, "boot_ready": ready, "boot_s": boot_s,
            "reps_curves": reps_curves, "verdicts": verdicts, "recommendation": rec}


def render_report(name: str, result: dict, tolerance_w: float, settle_polls: int) -> str:
    rec = result["recommendation"]
    lines = [f"# Device onboarding: {name}", "",
             f"Boot: ready={result['boot_ready']} after {result['boot_s']}s "
             f"({len(result['boot_curve'])} samples).", "",
             "## Decay reps"]
    for i, v in enumerate(result["verdicts"], 1):
        lines.append(f"- rep {i}: floor {v['floor_w']} W (range {v['min_w']}-{v['max_w']} W, "
                     f"n={v['n']}) — true settle at {v['true_settle_s']}s, guard would declare "
                     f"settled at {v['guard_settle_s']}s"
                     f"{' **← FALSE EARLY SETTLE**' if v['false_early_settle'] else ''}")
    lines += ["", "## Recommendation",
             f"- `idle_w`: {rec['idle_w']} (range {rec['idle_w_range']})",
             f"- Guard alone sufficient (tolerance {tolerance_w} W, settle_polls {settle_polls})? "
             f"**{'YES' if rec['guard_alone_sufficient'] else 'NO'}**"]
    if not rec["guard_alone_sufficient"]:
        lines += [f"- Recommended `min_settle_s`: **{rec['min_settle_s']}**",
                 f"- Recommended `min_baseline_samples`: **{rec['min_baseline_samples']}**",
                 "- Paste into the device's `rig.py` entry (see the Apple TV entry, 2026-08-27, "
                 "for the comment style expected next to these numbers)."]
    else:
        lines.append("- No `min_settle_s`/`min_baseline_samples` override needed.")
    lines += ["", "## Raw curves (t_s, watts)"]
    lines.append("boot: " + " ".join(f"{t}:{w}" for t, w in result["boot_curve"]))
    for i, curve in enumerate(result["reps_curves"], 1):
        lines.append(f"rep {i}: " + " ".join(f"{t}:{w}" for t, w in curve))
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--device", required=True, help="a name in rig.RIG['devices']")
    p.add_argument("--template", default="bbb_h264_smoke")
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--hold-s", type=float, default=20, help="how long to let the task run before stopping it")
    p.add_argument("--obs-s", type=float, default=90, help="how long to watch the decay afterward")
    p.add_argument("--cadence-s", type=float, default=1.0)
    p.add_argument("--tolerance-w", type=float, default=0.5, help="matches decode_idle_tolerance_w default")
    p.add_argument("--settle-polls", type=int, default=4, help="matches decode_idle_settle_polls default")
    p.add_argument("--boot-settle-s", type=float, default=45,
                  help="warm-up buffer after boot-ready, before rep 1 (avoids mixing "
                       "post-boot settling into the first decay measurement)")
    p.add_argument("--out", default=None)
    a = p.parse_args()
    sampler = RigDeviceSampler(a.device, a.template)
    result = asyncio.run(characterize(sampler, a.reps, a.hold_s, a.obs_s, a.cadence_s,
                                      a.tolerance_w, a.settle_polls,
                                      boot_settle_s=a.boot_settle_s))
    report = render_report(a.device, result, a.tolerance_w, a.settle_polls)
    print("\n" + report)
    if a.out:
        Path(a.out).write_text(report)
        print(f"report -> {a.out}")


if __name__ == "__main__":
    main()
