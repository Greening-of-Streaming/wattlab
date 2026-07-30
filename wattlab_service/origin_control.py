"""
origin_control.py — OWL owns the decode-rig clip origin (CR-072).

The Range-correct origin (`decode_bench/origin.py`, port 8123) must be a
persistent, OWL-owned process — not system nginx (can't be attributed) and
not cron/setsid (systemd cgroup cleanup kills detached children). Spawning
it as a child of the persistent `wattlab.service` gives free reboot
persistence AND the phase-2 hook: OWL can stop it to measure a serve
window, then restart it, attributing the delta.

Idempotent: if something already listens on 8123, we don't spawn (dev boxes,
manual runs). Restarted automatically if the child dies while we're up.
"""
import subprocess
import time
import urllib.request
from pathlib import Path

ORIGIN_PY = Path("/home/gos/wattlab/decode_bench/origin.py")
PORT = 8123

_proc: subprocess.Popen | None = None


def _listening() -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/status", timeout=2).read()
        return True
    except Exception:
        return False


def start() -> str:
    """Ensure the origin is up. Returns a short status string for the log."""
    global _proc
    if _listening():
        return "origin: already serving on :%d" % PORT
    if not ORIGIN_PY.exists():
        return "origin: %s missing — not started" % ORIGIN_PY
    _proc = subprocess.Popen(
        ["/usr/bin/python3", str(ORIGIN_PY), str(PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        cwd=str(ORIGIN_PY.parent))
    for _ in range(15):
        if _listening():
            return "origin: started (pid %d) on :%d" % (_proc.pid, PORT)
        time.sleep(0.3)
    return "origin: spawned but not yet answering on :%d" % PORT


def stop() -> None:
    """Phase-2 hook: stop the origin to measure a serve window in isolation."""
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except Exception:
            _proc.kill()
    _proc = None


def status() -> dict:
    return {"listening": _listening(),
            "pid": (_proc.pid if _proc and _proc.poll() is None else None)}
