"""CR-085 autonomy Phase 1 — OWL boots anywhere."""
import os
import re
import subprocess
import sys
from pathlib import Path

import paths

SVC = Path(__file__).resolve().parent.parent


def test_no_hardcoded_repo_path_outside_paths_module():
    offenders = []
    for f in SVC.glob("*.py"):
        if f.name in ("paths.py", "env.py"):
            continue
        for n, line in enumerate(f.read_text().splitlines(), 1):
            code = line.split("#", 1)[0]
            if "/home/gos/wattlab" in code and not code.strip().startswith(('"', "'")):
                offenders.append(f"{f.name}:{n}")
    assert not offenders, offenders


def test_repo_root_is_the_checkout():
    assert paths.REPO_ROOT == SVC.parent
    assert paths.repo("settings.json").name == "settings.json"


def test_owl_root_override_relocates_everything(tmp_path):
    code = ("import paths, persist, settings, sources;"
            "print(paths.REPO_ROOT, persist.RESULTS_DIR, settings.SETTINGS_FILE)")
    out = subprocess.run([sys.executable, "-c", code], cwd=SVC, capture_output=True, text=True,
                         env={**os.environ, "OWL_ROOT": str(tmp_path)}).stdout.split()
    assert out == [str(tmp_path), str(tmp_path / "results"), str(tmp_path / "settings.json")]


def test_process_env_wins_over_dotenv(monkeypatch, tmp_path):
    import env
    f = tmp_path / ".env"
    f.write_text("TAPO_P110_IP=1.1.1.1\nOTHER=x\n")
    monkeypatch.setattr(paths, "ENV_FILE", f)
    monkeypatch.setenv("TAPO_P110_IP", "2.2.2.2")
    monkeypatch.setenv("OWL_AUTH_SECRET", "s")
    v = env.load()
    assert v["TAPO_P110_IP"] == "2.2.2.2" and v["OTHER"] == "x" and v["OWL_AUTH_SECRET"] == "s"


def test_startup_flags_default_on():
    import settings
    for k in ("run_rig_poller", "run_origin", "run_carbon_poller", "run_rag_check", "run_sensors_poller"):
        assert settings.DEFAULTS[k] is True


def test_every_module_imports():
    """Regression (Phase 1 sweep): an inserted import above `from __future__`
    broke parity.py, which no other test imports. Import every module."""
    failures = []
    for f in sorted(SVC.glob("*.py")):
        r = subprocess.run([sys.executable, "-c", f"import {f.stem}"], cwd=SVC,
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            failures.append(f"{f.stem}: {r.stderr.strip().splitlines()[-1][:160]}")
    assert not failures, failures


def test_startup_hook_runs():
    """Regression: the startup hook referenced an un-imported `cfg`. Run it with
    every host service disabled so nothing touches devices."""
    import asyncio, main, settings, queue_control, lab_reservations, runtime
    flags = {k: False for k in ("run_rig_poller", "run_origin", "run_carbon_poller",
                                "run_rag_check", "run_sensors_poller")}
    orig = settings.load
    settings.load = lambda: {**orig(), **flags}
    started = []
    async def noop(*a, **k):
        return None
    try:
        saved = (queue_control.start, runtime.power_poller, lab_reservations.ticker)
        queue_control.start = lambda *a: started.append("queue")
        runtime.power_poller = noop
        lab_reservations.ticker = noop
        async def go():
            await main.startup()
            await asyncio.sleep(0)
        asyncio.run(go())
    finally:
        queue_control.start, runtime.power_poller, lab_reservations.ticker = saved
        settings.load = orig
    assert started == ["queue"]
