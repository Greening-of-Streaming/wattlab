"""
CR-064 — Lab queue controls (/queue/cancel-current + /queue/empty) and the
/settings navigation pass (anchor index + collapsed bulky sections).

Cancel-current is workload-aware: enhance = docker kill on the per-job
container name; benchmark = the existing cooperative flag; everything else
is REFUSED (an asyncio cancel would orphan the tool subprocess and release
the measurement lock onto a contaminated baseline).
"""
import main
import pixop
import queue_control
from runtime import jobs

from fastapi.testclient import TestClient

client = TestClient(main.app)

ANON = {"x-real-ip": "8.8.8.8"}
LAB = {"x-real-ip": "127.0.0.1"}


# --- gating -------------------------------------------------------------------

def test_queue_actions_forbidden_for_anonymous():
    assert client.post("/queue/cancel-current", headers=ANON).status_code == 403
    assert client.post("/queue/empty", headers=ANON).status_code == 403


# --- cancel-current -------------------------------------------------------------

def test_cancel_current_nothing_running(monkeypatch):
    monkeypatch.setattr(queue_control, "current_job_id", None)
    r = client.post("/queue/cancel-current", headers=LAB)
    assert r.status_code == 409


def test_cancel_current_enhance_docker_kills_by_name(monkeypatch):
    monkeypatch.setattr(queue_control, "current_job_id", "e1")
    jobs["e1"] = {"type": "enhance", "status": "running"}
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        class R:
            returncode = 0
            stdout = stderr = ""
        return R()

    monkeypatch.setattr(main.subprocess, "run", fake_run)
    r = client.post("/queue/cancel-current", headers=LAB)
    assert r.status_code == 200
    assert r.json()["method"] == "docker_kill"
    assert seen["cmd"] == ["docker", "kill", "owl_enhance_e1"]
    assert jobs["e1"]["cancel_requested"] is True
    del jobs["e1"]


def test_cancel_current_benchmark_sets_cooperative_flag(monkeypatch):
    monkeypatch.setattr(queue_control, "current_job_id", "b1")
    jobs["b1"] = {"type": "benchmark", "status": "running"}
    r = client.post("/queue/cancel-current", headers=LAB)
    assert r.status_code == 200
    assert r.json()["method"] == "cooperative"
    assert jobs["b1"]["cancel_requested"] is True
    del jobs["b1"]


def test_cancel_current_refuses_uncancellable_workloads(monkeypatch):
    monkeypatch.setattr(queue_control, "current_job_id", "v1")
    jobs["v1"] = {"type": "video", "status": "running"}
    r = client.post("/queue/cancel-current", headers=LAB)
    assert r.status_code == 409
    assert "can't be cancelled" in r.json()["error"]
    assert "cancel_requested" not in jobs["v1"]   # strictly nothing happened
    del jobs["v1"]


# --- empty ---------------------------------------------------------------------

def test_queue_empty_drains_pending(monkeypatch):
    monkeypatch.setattr(queue_control, "_jobs", {})
    queue_control.pending_queue.clear()

    async def _noop():
        return None
    queue_control._jobs["q1"] = {"status": "queued"}
    queue_control.pending_queue.append(
        {"job_id": "q1", "type": "video", "label": "x", "coro_fn": _noop,
         "visitor_key": None})
    r = client.post("/queue/empty", headers=LAB)
    assert r.status_code == 200
    assert r.json()["drained"] == 1
    assert queue_control.pending_queue == []
    assert queue_control._jobs["q1"]["status"] == "error"
    queue_control.pending_queue.clear()


# --- pixop: per-job container name ----------------------------------------------

def test_build_docker_cmd_names_container_per_job(tmp_path, monkeypatch):
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "p.args").write_text("-c hevc")
    monkeypatch.setattr(pixop, "config", lambda: {
        "image_tag": "pixop/live:test", "workdir": str(tmp_path),
        "license_path": str(tmp_path / "license.jwt"), "presets": [],
        "cooldown_s": 1, "docker_timeout_s": 60, "baseline_polls": 2,
    })
    cmd = pixop.build_docker_cmd("c.mov", "p.args", "o.mp4", job_id="ab12")
    i = cmd.index("--name")
    assert cmd[i + 1] == "owl_enhance_ab12"
    # No job_id → unnamed (back-compat for direct callers).
    assert "--name" not in pixop.build_docker_cmd("c.mov", "p.args", "o.mp4")


# --- pages -----------------------------------------------------------------------

def test_queue_status_page_has_lab_controls():
    r = client.get("/queue-status", headers=LAB)
    assert r.status_code == 200
    assert "cancelCurrent" in r.text
    assert "emptyQueue" in r.text


def test_settings_page_nav_and_collapsed_sections():
    r = client.get("/settings", headers=LAB)
    assert r.status_code == 200
    assert 'class="toc-bar"' in r.text
    # Anchor targets exist for every index link.
    for sid in ("s-measurement", "s-cooldown", "s-staging", "s-encoding",
                "s-confidence", "s-variance", "s-benchmark", "s-members",
                "s-tiers", "s-models"):
        assert f'id="{sid}"' in r.text
    # Bulky panels are default-collapsed.
    assert "Model enable/disable matrix" in r.text
    assert "Magic-link allowlist" in r.text


# --- pause toggle (owner ask 2026-06-11 — flag predated the UI) ----------------

def test_queue_pause_forbidden_for_anonymous():
    assert client.post("/queue/pause?on=true", headers=ANON).status_code == 403


def test_queue_pause_toggle_roundtrip(monkeypatch, tmp_path):
    flag = tmp_path / "owl-paused"
    monkeypatch.setattr(queue_control, "PAUSE_FLAG", str(flag))
    r = client.post("/queue/pause?on=true", headers=LAB)
    assert r.status_code == 200 and r.json()["paused"] is True
    assert flag.exists()
    # snapshot reflects it (drives the page banner)
    assert client.get("/queue").json()["paused"] is True
    r = client.post("/queue/pause?on=false", headers=LAB)
    assert r.json()["paused"] is False
    assert not flag.exists()
    assert client.get("/queue").json()["paused"] is False


def test_queue_status_page_has_pause_toggle():
    r = client.get("/queue-status", headers=LAB)
    assert r.status_code == 200
    assert "togglePause" in r.text
    assert "Disable queue" in r.text and "Enable queue" in r.text
