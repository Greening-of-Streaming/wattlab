"""CR-085 autonomy Phase 4 — peer job API (signing, routes, caller stub, import,
offline greying)."""
import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

import auth
import hosts
import main
import peer
import persist
import runtime

client = TestClient(main.app)
LAB = {"x-real-ip": "127.0.0.1"}
ANON = {"x-real-ip": "8.8.8.8"}


def _signed(method, path, body=b""):
    return {**LAB, peer.HEADER: peer.sign(method, path, body), "content-type": "application/json"}


# --- signing ----------------------------------------------------------------------

def test_sign_verify_replay_and_tamper():
    h = peer.sign("POST", "/peer/jobs", b'{"a":1}')
    assert peer.verify("POST", "/peer/jobs", b'{"a":1}', h)
    assert not peer.verify("POST", "/peer/jobs", b'{"a":1}', h)          # single use
    h2 = peer.sign("POST", "/peer/jobs", b'{"a":1}')
    assert not peer.verify("POST", "/peer/jobs", b'{"a":2}', h2)         # body bound
    assert not peer.verify("GET", "/peer/jobs", b'{"a":1}', peer.sign("POST", "/peer/jobs", b'{"a":1}'))


def test_stale_timestamp_rejected(monkeypatch):
    h = peer.sign("GET", "/peer/info")
    monkeypatch.setattr(peer.time, "time", lambda: time.time_ns() / 1e9 + 120)
    assert not peer.verify("GET", "/peer/info", b"", h)


def test_ephemeral_secret_refuses_peer(monkeypatch):
    monkeypatch.setattr(auth, "SECRET_IS_EPHEMERAL", True)
    with pytest.raises(peer.PeerAuthError):
        peer.sign("GET", "/peer/info")


# --- callee routes ----------------------------------------------------------------

def test_peer_routes_need_signature_and_lab():
    assert client.get("/peer/info", headers=LAB).status_code == 403          # no signature
    assert client.get("/peer/info", headers={**ANON, peer.HEADER: peer.sign("GET", "/peer/info")}).status_code == 403
    r = client.get("/peer/info", headers=_signed("GET", "/peer/info"))
    assert r.status_code == 200
    d = r.json()
    assert d["host"]["id"] and "cpu" in d["engines"] and "queue_depth" in d


def test_peer_submit_rejects_unknown_type():
    body = json.dumps({"type": "nope", "params": {}}).encode()
    r = client.post("/peer/jobs", content=body, headers=_signed("POST", "/peer/jobs", body))
    assert r.status_code == 400


def test_peer_result_fetch_and_index(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    persist.save_result("llm", "pr1", {"mode": "single", "energy": {}}, visitor_key=None)
    r = client.get("/peer/results/llm/pr1", headers=_signed("GET", "/peer/results/llm/pr1"))
    assert r.status_code == 200 and r.json()["job_id"] == "pr1"
    r = client.get("/peer/results/llm?since=2000-01-01", headers=_signed("GET", "/peer/results/llm?since=2000-01-01"))
    assert [x["job_id"] for x in r.json()["results"]] == ["pr1"]
    bad = client.get("/peer/results/llm/..x", headers=_signed("GET", "/peer/results/llm/..x"))
    assert bad.status_code == 404


# --- caller side ------------------------------------------------------------------

PEER_HOST = {"enabled": True, "label": "GoS2", "chip": "Apple M6", "driver": "peer",
             "url": "http://10.0.0.9:8000", "meters": ["10.0.0.1"], "engines": {}}


def test_import_result_is_verbatim(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    env = {"job_id": "gos2-abc12345", "saved_at": "2026-10-06T01:02:03",
           "host": {"id": "gos2", "label": "GoS2", "remote": False}, "owl_version": {"sha": "x"}}
    p = persist.import_result("video", env)
    assert p.name == "2026-10-06_gos2-abc12345.json" and json.loads(p.read_text()) == env
    with pytest.raises(ValueError):
        persist.import_result("video", {"job_id": "../x", "host": {"id": "g"}})
    with pytest.raises(ValueError):
        persist.import_result("video", {"job_id": "nohost"})


def test_video_remote_peer_driver_submits_and_mirrors(monkeypatch):
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": dict(PEER_HOST)})
    monkeypatch.setattr(peer, "info", lambda h, max_age=20: {"engines": {}})
    calls = []
    def fake_call(h, method, path, payload=None, timeout=15):
        calls.append((method, path, payload))
        return {"job_id": "gos2-11111111", "queue_position": 1}
    monkeypatch.setattr(peer, "call", fake_call)
    monkeypatch.setattr(peer, "follow", lambda *a, **k: asyncio.sleep(0))
    r = client.post("/video/remote", headers=LAB, data={
        "source_key": "meridian_120s", "host": "gos2", "codec": "h264", "engine": "hw"})
    assert r.status_code == 200 and r.json()["job_id"] == "gos2-11111111"
    assert calls[0][1] == "/peer/jobs" and calls[0][2]["params"]["engine"] == "gpu"
    runtime.jobs["gos2-11111111"]["peer_watts"] = 27.5
    st = runtime.job_status("gos2-11111111")
    assert st["watts"] == 27.5 and st["watts_host"] == "GoS2"
    runtime.jobs.pop("gos2-11111111", None)


def test_offline_peer_is_greyed_and_refused(monkeypatch):
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": dict(PEER_HOST)})
    monkeypatch.setattr(peer, "info", lambda h, max_age=20: None)
    for page in ("/video", "/image", "/llm"):
        html = client.get(page, headers=LAB).text
        assert "GoS2 is offline" in html, page
    r = client.post("/video/remote", headers=LAB, data={
        "source_key": "meridian_120s", "host": "gos2", "codec": "h264", "engine": "both"})
    assert r.status_code == 503


def test_follow_imports_result_and_marks_done(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    env = {"job_id": "gos2-22222222", "saved_at": "2026-10-06T01:00:00", "host": {"id": "gos2"}}
    seq = iter([{"status": "running", "stage": "gpu_encode", "watts": 30.1},
                {"status": "done", "stage": "done", "watts": 2.0}])
    def fake_call(h, method, path, payload=None, timeout=15):
        return env if path.startswith("/peer/results/") else next(seq)
    monkeypatch.setattr(peer, "call", fake_call)
    async def no_sleep(_): return None
    monkeypatch.setattr(peer.asyncio, "sleep", no_sleep)
    jobs = {"gos2-22222222": {"peer_host": "GoS2"}}
    asyncio.run(peer.follow(PEER_HOST, "gos2-22222222", "video", jobs))
    assert jobs["gos2-22222222"]["status"] == "done"
    assert (tmp_path / "video" / "2026-10-06_gos2-22222222.json").exists()
