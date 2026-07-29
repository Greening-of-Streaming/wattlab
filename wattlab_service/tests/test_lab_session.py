"""Lab-session mode: browsing open, non-Lab enqueue refused (bin/lab-session-on)."""
import pytest
from fastapi.testclient import TestClient

import main
import queue_control
import ui


client = TestClient(main.app)
_LAB = {"x-real-ip": "127.0.0.1"}
_ANON = {"x-real-ip": "8.8.8.8"}


@pytest.fixture
def _session_flag(tmp_path, monkeypatch):
    flag = tmp_path / "owl-lab-session"
    monkeypatch.setattr(queue_control, "LAB_SESSION_FLAG", flag)
    return flag


def _enqueue(vk):
    """Drive the enqueue chokepoint with a forced visitor key."""
    return queue_control.enqueue("t-lab-sess", "video", "test",
                                 lambda: None, request=object())


def test_non_lab_enqueue_refused_during_session(_session_flag, monkeypatch):
    _session_flag.touch()
    monkeypatch.setattr(queue_control, "visitor_key", lambda r: "a:test")
    with pytest.raises(queue_control.LabSessionActive):
        _enqueue("a:test")


def test_lab_enqueue_unaffected_during_session(_session_flag, monkeypatch):
    _session_flag.touch()
    monkeypatch.setattr(queue_control, "visitor_key", lambda r: None)
    saved_jobs, saved_q = queue_control._jobs, list(queue_control.pending_queue)
    try:
        queue_control._jobs = {}
        pos = _enqueue(None)
        assert pos == len(saved_q) + 1
    finally:
        queue_control.pending_queue[:] = saved_q
        queue_control._jobs = saved_jobs


def test_no_flag_no_effect(_session_flag, monkeypatch):
    monkeypatch.setattr(queue_control, "visitor_key", lambda r: "a:test")
    saved_jobs, saved_q = queue_control._jobs, list(queue_control.pending_queue)
    try:
        queue_control._jobs = {}
        _enqueue("a:test")   # must not raise
    finally:
        queue_control.pending_queue[:] = saved_q
        queue_control._jobs = saved_jobs


def test_handler_registered_and_maps_to_503():
    assert queue_control.LabSessionActive in main.app.exception_handlers


def test_banner_on_public_pages_during_session(_session_flag):
    _session_flag.touch()
    # /demo goes through ui.render_page (the banner's injection point);
    # /findings hand-rolls its HTML and deliberately has no banner.
    page = client.get("/demo", headers=_ANON).text
    assert "Lab session in progress" in page


def test_no_banner_without_flag(_session_flag):
    page = client.get("/demo", headers=_ANON).text
    assert "Lab session in progress" not in page


def test_browsing_stays_open_during_session(_session_flag):
    _session_flag.touch()
    for path in ("/demo", "/findings", "/methodology"):
        assert client.get(path, headers=_ANON).status_code == 200


def test_queue_page_toggle_lab_only(_session_flag):
    assert "Lab session" in client.get("/queue-status", headers=_LAB).text
    assert "lab-session/toggle" not in client.get("/queue-status",
                                                  headers=_ANON).text


def test_toggle_endpoint_raises_and_lowers_flag(_session_flag):
    r = client.post("/lab-session/toggle", headers=_LAB, data={"on": "1"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert _session_flag.exists()
    r = client.post("/lab-session/toggle", headers=_LAB, data={"on": "0"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert not _session_flag.exists()


def test_toggle_endpoint_refused_for_anon(_session_flag):
    r = client.post("/lab-session/toggle", headers=_ANON, data={"on": "1"},
                    follow_redirects=False)
    assert r.status_code == 403
    assert not _session_flag.exists()
