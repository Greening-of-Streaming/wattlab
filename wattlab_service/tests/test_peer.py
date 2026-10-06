"""CR-085 autonomy Phase 4 — peer job API (signing, routes, caller stub, import,
offline greying)."""
import asyncio
import json
import time
from pathlib import Path

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


def test_pre_v2_results_export_with_inferred_host(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    (tmp_path / "video").mkdir()
    (tmp_path / "video" / "2026-05-01_old1.json").write_text(json.dumps(
        {"job_id": "old1", "saved_at": "2026-05-01T10:00:00", "mode": "single"}))
    idx = client.get("/peer/results/video", headers=_signed("GET", "/peer/results/video")).json()
    assert [r["job_id"] for r in idx["results"]] == ["old1"]
    d = client.get("/peer/results/video/old1", headers=_signed("GET", "/peer/results/video/old1")).json()
    assert d["host"]["id"] == "gos1" and d["host_inferred"] is True


def test_replication_pulls_new_and_skips_existing(tmp_path, monkeypatch):
    import replication
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    envs = {"gos2-a": {"job_id": "gos2-a", "saved_at": "2026-10-06T01:00:00", "host": {"id": "gos2"}},
            "gos2-b": {"job_id": "gos2-b", "saved_at": "2026-10-06T02:00:00", "host": {"id": "gos2"}}}
    def fake_call(h, method, path, payload=None, timeout=15):
        if path.startswith("/peer/results/video?") or path == "/peer/results/video":
            return {"results": [{"job_id": k, "saved_at": v["saved_at"]} for k, v in envs.items()]}
        if path.startswith("/peer/results/video/"):
            return envs[path.rsplit("/", 1)[1]]
        return {"results": []}
    monkeypatch.setattr(peer, "call", fake_call)
    monkeypatch.setattr(peer, "online", lambda h: True)
    assert replication.pull_once("gos2", PEER_HOST)["video"] == 2
    assert replication.pull_once("gos2", PEER_HOST)["video"] == 0          # idempotent
    assert len(list((tmp_path / "video").glob("*.json"))) == 2
    monkeypatch.setattr(peer, "online", lambda h: False)
    assert replication.pull_once("gos2", PEER_HOST) == {"offline": True}


def test_all_codecs_skips_unsupported_gpu_codec(monkeypatch):
    import video
    async def fake_single(inp, jid, preset, base, jobs=None):
        return {"preset_label": preset, "output_size_mb": 1,
                "energy": {"delta_e_wh": 1.0, "delta_t_s": 10, "delta_w": 5, "confidence": {"flag": "🟢"}},
                "thermals": {"cpu_peak": None, "gpu_peak": None, "gpu_ppt_mean_w": None}}
    async def fake_base(polls=5): return {"w_base": 5.0}
    async def fake_cd(**k): return {"method": "fixed", "waited_s": 0}
    async def fake_vmaf(*a, **k): return None
    monkeypatch.setattr(video, "run_single", fake_single)
    monkeypatch.setattr(video, "measure_baseline", fake_base)
    monkeypatch.setattr(video, "cooldown_between_runs", fake_cd)
    monkeypatch.setattr(video, "_attach_vmaf", fake_vmaf, raising=False)
    monkeypatch.setattr(video, "focus_mode_enter", lambda: [])
    monkeypatch.setattr(video, "focus_mode_exit", lambda s: None)
    monkeypatch.setattr(video.gpu, "supports", lambda c: c != "av1")
    r = asyncio.run(video.run_all_measurement(Path("/dev/null"), "t-av1", jobs=None))
    av1 = r["codecs"]["av1"]
    assert "gpu" not in av1 and "No hardware AV1" in av1["gpu_unavailable"]
    assert r["analysis"]["most_efficient"] is not None


def test_members_replicate_in_allowlist_format(tmp_path, monkeypatch):
    import replication
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    mf = tmp_path / "members.json"
    monkeypatch.setattr(auth, "_members_file_path", lambda: mf)
    monkeypatch.setenv("OWL_MEMBERS_FILE", str(mf))
    monkeypatch.setattr(peer, "online", lambda h: True)
    def fake_call(h, method, path, payload=None, timeout=15):
        return {"members": ["a@x.org"]} if path == "/peer/members" else {"results": []}
    monkeypatch.setattr(peer, "call", fake_call)
    try:
        out = replication.pull_once("gos1", {**PEER_HOST, "members_source": True})
        assert "members_error" not in out
        assert auth._load_members(mf) == {"a@x.org"}
    finally:
        monkeypatch.undo(); auth.reload_members()


def test_pages_name_the_local_machine(monkeypatch):
    monkeypatch.setattr(hosts, "local_label", lambda: "GoS2")
    for page in ("/video", "/llm", "/rag", "/settings"):
        t = client.get(page, headers=LAB).text
        assert "OWL · GoS2" in t and "OWL · GoS1" not in t, page


def test_other_machine_runs_render_as_machine_tiles(monkeypatch):
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": dict(PEER_HOST)})
    monkeypatch.setattr(peer, "info", lambda h, max_age=20: {
        "engines": {"cpu": {"label": "CPU (software)", "codecs": ["h264"]}},
        "llm_models": ["qwen3:4b"], "mlx_models": [], "image_models": ["sd-turbo"]})
    for page in ("/video", "/llm", "/image"):
        t = client.get(page, headers=LAB).text
        assert "function owlRunTiles" in t and "owlRunTiles('" in t, page
        assert '"label": "GoS2"' in t and "owlPairRun" not in t, page


def test_image_page_routes_session_results_to_shared_renderer():
    t = client.get("/image", headers=LAB).text
    assert "j.result.mode === 'session'" in t and "wlMachineResult('image', j.result)" in t
