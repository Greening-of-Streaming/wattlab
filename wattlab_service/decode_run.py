"""
decode_run.py — Stage 2 of /decode: curated decode recipes run from the page.

A recipe references a rig device by name; run_decode_job() powers it up if
needed, stages clips (Pis decode from /dev/shm — tmpfs, wiped every power
cycle), materialises a bench config with the CURRENT plug/serial addresses
from rig.RIG, and shells out to the proven July harness
(/srv/data/owl/decode-bench/bench.py) rather than reimplementing its
protocol. Progress comes from parsing the harness's phase log lines; every
phase has a known duration, so the page can draw honest time-based bars.

While the harness samples its meter at 1.5 s, the plug (and the monitor
context plug, when used) is registered in rig.PAUSED_PLUGS so the rig poller
never contends for the KLAP session mid-row. The device tile shows a
"job running" badge (rig busy flag) and refuses power ops for the duration.

Results land via persist.save_result("decode", ...) in the S58 decode
envelope shape, so the standard results machinery applies.
"""
import asyncio
import json
import logging
import re
import subprocess
import time
from pathlib import Path

import rig
from persist import save_result
from runtime import jobs

log = logging.getLogger(__name__)

BENCH_DIR = Path("/srv/data/owl/decode-bench")
BENCH = BENCH_DIR / "bench.py"
STREAMS = BENCH_DIR / "streams"

# --- Curated recipes ---------------------------------------------------------
# Adapted from the July campaign configs; device/meter addresses come from
# rig.RIG at materialisation time, never hardcoded here.
RECIPES: dict = {
    "gtv_smoke": {
        "label": "Google TV smoke — BBB H.264, one 90 s row",
        "device": "gtv",
        "monitor_context": True,
        "bench": {
            "cadence_s": 1.5, "baseline_samples": 20, "settle_s": 15,
            "startup_skip_s": 10, "window_s": 90, "gap_s": 5,
            "runs": [{"name": "bbb_h264_smoke",
                      "url": "http://192.168.1.62:8123/bbb_h264_6min.mp4"}],
        },
    },
    "pi5_h264_rt": {
        "label": "Pi 5 — BBB H.264 realtime, headless (July replication row)",
        "device": "pi5",
        "stage_clips": ["bbb_h264_6min.mp4"],
        "bench": {
            "cadence_s": 1.5, "baseline_samples": 20, "settle_s": 15,
            "startup_skip_s": 8, "window_s": 150, "gap_s": 5,
            "runs": [{"name": "bbb_h264_rt_ui",
                      "cmd": ("ffmpeg -nostdin -re -i "
                              "/dev/shm/decode/bbb_h264_6min.mp4 -an -f null - "),
                      "stop_cmd": "pkill -f 'ffmpeg.*bbb_h264'"}],
        },
    },
}


def recipe_phases(recipe: dict) -> list:
    """[(phase, seconds), ...] per run — drives the page's progress bars."""
    b = recipe["bench"]
    return [("settle", b["settle_s"]),
            ("baseline", round(b["baseline_samples"] * b["cadence_s"])),
            ("starting", b["startup_skip_s"]),
            ("sampling", b["window_s"]),
            ("finishing", 5)]


# Harness log line → phase name. Checked in order; first hit wins.
_PHASE_PATTERNS = [
    (re.compile(r": settle "), "settle"),
    (re.compile(r": baseline "), "baseline"),
    (re.compile(r": started — sampling|: started - sampling"), "sampling"),
    (re.compile(r": base=.*task=.*dW="), "finishing"),
]


def _materialize(job_id: str, key: str) -> Path:
    """Write a bench config for this run with live rig addresses."""
    recipe = RECIPES[key]
    dev_cfg = rig.RIG["devices"][recipe["device"]]
    cfg = dict(recipe["bench"])
    cfg["name"] = f"ui-{key}-{job_id}"
    cfg["meter_ip"] = dev_cfg["plug_ip"]
    if recipe.get("monitor_context"):
        cfg["monitor_meter_ip"] = rig.RIG["monitor"]["plug_ip"]
    if dev_cfg["kind"] == "adb":
        cfg["device"] = {"type": "adb", "serial": dev_cfg["target"],
                         "player": "com.brouken.player"}
    else:
        user, host = dev_cfg["target"].split("@", 1)
        cfg["device"] = {"type": "ssh", "host": host, "user": user}
    path = Path(f"/tmp/owl-decode-{job_id}.json")
    path.write_text(json.dumps(cfg, indent=1))
    return path


def _stage_clips_sync(dev_cfg: dict, clips: list) -> None:
    target = dev_cfg["target"]
    subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                    target, "mkdir -p /dev/shm/decode"],
                   check=True, timeout=20)
    for clip in clips:
        subprocess.run(["scp", "-o", "BatchMode=yes",
                        str(STREAMS / clip), f"{target}:/dev/shm/decode/"],
                       check=True, timeout=120)


async def _wait_ready(name: str, job: dict, timeout_s: float) -> None:
    dev = rig.rig_cache["devices"][name]
    if dev["state"] == "off":
        await rig.device_on(name)
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        if dev["state"] == "ready":
            return
        if dev["state"] in ("stuck", "unreachable", "unpowered"):
            raise RuntimeError(f"device {name} is {dev['state']}")
        job["detail"] = f"device {dev['state']}"
        await asyncio.sleep(3)
    raise RuntimeError(f"device {name} not ready after {int(timeout_s)}s")


def _paused_ips(cfg: dict) -> set:
    ips = {cfg["meter_ip"]}
    if cfg.get("monitor_meter_ip"):
        ips.add(cfg["monitor_meter_ip"])
    return ips


async def run_decode_job(job_id: str, key: str) -> None:
    recipe = RECIPES[key]
    name = recipe["device"]
    dev_cfg = rig.RIG["devices"][name]
    d = rig.rig_cache["devices"][name]
    job = jobs[job_id]
    phases = recipe_phases(recipe)
    job.update({"status": "running", "stage": "device",
                "recipe": key, "device": name,
                "phases": phases, "row": None, "row_n": len(recipe["bench"]["runs"]),
                "phase_started": None, "detail": ""})
    cfg_path = result_path = None
    paused: set = set()
    try:
        await _wait_ready(name, job, 3 * dev_cfg["expected_boot_s"] + 45)

        if recipe.get("stage_clips"):
            job.update({"stage": "staging", "detail": "copying clips to /dev/shm"})
            await asyncio.to_thread(_stage_clips_sync, dev_cfg,
                                    recipe["stage_clips"])

        cfg_path = _materialize(job_id, key)
        cfg = json.loads(cfg_path.read_text())
        result_path = BENCH_DIR / "results" / f"{cfg['name']}.json"

        d["busy"] = True
        paused = _paused_ips(cfg)
        rig.PAUSED_PLUGS |= paused
        job.update({"stage": "settle", "phase_started": time.monotonic()})

        proc = await asyncio.create_subprocess_exec(
            "python3", str(BENCH), str(cfg_path), cwd=str(BENCH_DIR),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        lines = []
        row_i = 0
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode(errors="replace").rstrip()
            lines.append(line)
            for pat, phase in _PHASE_PATTERNS:
                if pat.search(line):
                    if phase == "settle":
                        row_i += 1
                    job.update({"stage": phase, "row": row_i,
                                "phase_started": time.monotonic(),
                                "detail": line.split("] ")[-1][:120]})
                    break
        rc = await proc.wait()
        if rc != 0 or not result_path.exists():
            raise RuntimeError(
                f"bench.py exit {rc}: {' | '.join(lines[-3:])[:300]}")

        bench_out = json.loads(result_path.read_text())
        envelope = {
            "mode": "ui_recipe",
            "recipe": key,
            "device": {"name": dev_cfg["label"], "rig_name": name,
                       "kind": dev_cfg["kind"]},
            "power_hardware": {"meter": "Tapo P110",
                               "meter_ip": cfg["meter_ip"], "fw": "1.3.1",
                               "cadence_s": cfg["cadence_s"]},
            "protocol": {"harness": "decode-bench bench.py (July 2026 protocol)",
                         "launched_from": "/decode",
                         **bench_out.get("protocol", {})},
            "runs": bench_out.get("rows", []),
        }
        save_result("decode", job_id, envelope)
        job.update({"status": "done", "stage": "done", "result": envelope,
                    "detail": ""})
    except Exception as e:
        log.warning("decode job %s failed: %s", job_id, e)
        job.update({"status": "error", "stage": "error", "error": str(e)})
    finally:
        d["busy"] = False
        rig.PAUSED_PLUGS -= paused
        if cfg_path:
            cfg_path.unlink(missing_ok=True)
