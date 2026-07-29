"""
pytest configuration: make `wattlab_service/` importable as the source root
so tests can do `import carbon`, `import settings as cfg`, etc. without
having to mess with PYTHONPATH at the shell.

Run tests from anywhere with:
    pytest wattlab_service/tests/
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _isolate_lab_session_flag(tmp_path, monkeypatch):
    """The lab-session flag is live box state (/tmp/owl-lab-session, raised by
    bin/lab-session-on). Point every test at a per-test path so a real lab
    session on the host can't fail the anonymous/member enqueue tests — that
    happened for real on 2026-07-29. test_lab_session.py re-patches with its
    own flag path on top of this."""
    import queue_control
    monkeypatch.setattr(queue_control, "LAB_SESSION_FLAG",
                        tmp_path / "owl-lab-session")


@pytest.fixture(autouse=True)
def _reset_rolling_idle_floor():
    """CR-070: sample_baseline stamps power.LAST_W_BASE (the rolling idle
    floor for the pre-job guard) on every call — including calls with faked
    watts inside tests. Reset per test so one test's fake baseline can't arm
    the queue worker's guard, or grow baseline dicts extra provenance keys,
    in another. Tests that want the guard active set LAST_W_BASE explicitly."""
    import power
    power.LAST_W_BASE = None
    yield
