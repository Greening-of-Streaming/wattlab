"""CR-085 autonomy Phase 4 — peer job API (signing, routes, caller stub, import,
offline greying)."""
import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi import Request
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

def test_peer_routes_need_signature_and_a_peer_address(monkeypatch):
    assert client.get("/peer/info", headers=LAB).status_code == 403          # no signature
    assert client.get("/peer/info", headers={**ANON, peer.HEADER: peer.sign("GET", "/peer/info")}).status_code == 403
    # A peer on another network (e.g. Tailscale 100.64/10 — not "private") is
    # admitted because its address is the host of its registered url.
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": {**PEER_HOST, "url": "http://100.101.1.2:8000"}})
    peer._SRC_CACHE["ts"] = 0
    ts = {"x-real-ip": "100.101.1.2"}
    assert client.get("/peer/info", headers={**ts, peer.HEADER: peer.sign("GET", "/peer/info")}).status_code == 200
    assert client.get("/peer/info", headers={"x-real-ip": "100.101.9.9",
                      peer.HEADER: peer.sign("GET", "/peer/info")}).status_code == 403
    peer._SRC_CACHE["ts"] = 0
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


def test_home_demo_queue_name_the_local_machine(monkeypatch):
    """Owner 2026-10-07: GoS2's home page said "GoS1"."""
    monkeypatch.setattr(hosts, "local_label", lambda: "GoS2")
    base = hosts.local_host()
    monkeypatch.setattr(hosts, "local_host", lambda: {**base, "id": "gos2", "label": "GoS2",
                                                       "chip": "Apple M6", "machine": "Mac mini"})
    for page in ("/", "/demo", "/queue-status"):
        t = client.get(page, headers=LAB).text
        assert "GoS2" in t and "GoS1" not in t, page
        assert "{OWL_ME}" not in t and "__OWL_ME__" not in t, page
    assert "GoS2 is a Mac mini (Apple M6)." in client.get("/demo", headers=LAB).text


# --- /decode remote control (owner 2026-10-07: one rig owner) -------------------

def test_peer_info_reports_rig():
    d = client.get("/peer/info", headers=_signed("GET", "/peer/info")).json()
    assert d["rig"] is True                                   # test settings: run_rig_poller default on


def test_owner_dispatches_decode_in_process_with_visitor_tier():
    p = "/peer/decode/status.json?_owl_tier=lab"
    r = client.get(p, headers=_signed("GET", p))
    assert r.status_code == 200 and isinstance(r.json(), dict)
    # unsigned → refused; the proxy is allowlisted to /decode
    assert client.get("/peer/decode/status.json", headers=LAB).status_code == 403


def test_owner_maps_non_lab_visitor_to_public_identity(monkeypatch):
    p = "/peer/decode/device/pi5/power?_owl_tier=anonymous"
    body = b'{"on": true}'
    r = client.post(p, content=body, headers={**_signed("POST", p, body), "content-type": "application/json"})
    assert r.status_code in (403, 404)                       # RIG_CONTROL refused for a non-Lab visitor


def _no_rig(monkeypatch, owner=True):
    import routes_decode, settings as cfg
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda: {**real(), "run_rig_poller": False})
    monkeypatch.setattr(peer, "rig_owner", lambda: ({**PEER_HOST, "id": "gos1", "label": "GoS1"} if owner else None))
    calls = []
    def fake_forward(h, method, path, body=b"", content_type=None, timeout=60):
        calls.append((method, path, body, content_type))
        if "status.json" in path:
            return 200, "application/json", b'{"devices": {}}'
        if path.startswith("/peer/decode/?") :
            return 200, "text/html; charset=utf-8", b"<html><body class=x><h1>Decode Rig</h1></body></html>"
        return 200, "application/json", b'{"job_id": "abc", "queue_position": 1}'
    monkeypatch.setattr(peer, "forward", fake_forward)
    return calls


def test_node_without_rig_forwards_api_and_pages(monkeypatch):
    calls = _no_rig(monkeypatch)
    assert client.get("/decode/status.json", headers=LAB).json() == {"devices": {}}
    m, path, _, _ = calls[-1]
    assert m == "GET" and path.startswith("/peer/decode/status.json?") and "_owl_tier=lab" in path
    r = client.post("/decode/run", headers=LAB, data={"template": "x"})
    assert r.json()["job_id"] == "abc" and calls[-1][0] == "POST" and calls[-1][1].startswith("/peer/decode/run?")
    assert "multipart" in (calls[-1][3] or "") or "urlencoded" in (calls[-1][3] or "")
    page = client.get("/decode", headers=LAB).text
    assert "The decode rig is wired to <b>GoS1</b>" in page and "<h1>Decode Rig</h1>" in page


def test_node_without_rig_applies_its_own_gates_before_forwarding(monkeypatch):
    calls = _no_rig(monkeypatch)
    r = client.post("/decode/run", headers=ANON, data={"template": "x"})
    assert r.status_code in (403, 404) and not calls           # refused locally, never forwarded
    client.get("/decode/status.json", headers=ANON)            # public read → forwarded as anonymous
    assert "_owl_tier=anonymous" in calls[-1][1]


def test_node_without_rig_owner_offline(monkeypatch):
    _no_rig(monkeypatch, owner=False)
    assert client.get("/decode/status.json", headers=LAB).status_code == 503
    r = client.get("/decode", headers=LAB)
    assert r.status_code == 503 and "offline" in r.text and "lock-block" in r.text


def test_replication_carries_decode_results(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    p = persist.import_result("decode", {"job_id": "d1", "saved_at": "2026-10-07T01:00:00", "host": {"id": "gos1"}})
    assert p.parent.name == "decode"


# --- macOS temperatures (owl-temps) ------------------------------------------------

def test_apple_die_temp_takes_hottest_tdie(monkeypatch, tmp_path):
    import power, settings as cfg
    fake = tmp_path / "owl-temps"
    fake.write_text('#!/bin/sh\necho \'{"PMU tdie1": 28.5, "PMU tdie7": 31.2, "PMU tdev1": 40.0, "NAND CH0 temp": 50}\'\n')
    fake.chmod(0o755)
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda: {**real(), "apple_temps_bin": str(fake)})
    assert power._apple_die_temp() == 31.2
    monkeypatch.setattr(cfg, "load", lambda: {**real(), "apple_temps_bin": str(tmp_path / "missing")})
    assert power._apple_die_temp() is None                   # fail-soft


def test_sensors_poller_skips_during_measurement(monkeypatch, tmp_path):
    import runtime, settings as cfg
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda: {**real(), "sensors_poll_s": 30, "sensors_skip_during_measure": True})
    reads = []
    monkeypatch.setattr(runtime, "read_sensors_dict", lambda: reads.append(1) or {"cpu_tctl": 30.0})
    lock = __import__("pathlib").Path("/tmp/gos-measure.lock")
    existed = lock.exists()
    async def one_cycle():
        t = asyncio.create_task(runtime.sensors_poller())
        await asyncio.sleep(0.05); t.cancel()
    try:
        lock.write_text("test")
        asyncio.run(one_cycle())
        assert reads == []                                    # locked → no poll
        lock.unlink()
        asyncio.run(one_cycle())
        assert reads == [1]
    finally:
        if existed and not lock.exists():
            lock.write_text("restored")
        elif not existed:
            lock.unlink(missing_ok=True)


# --- machine switch (owner 2026-10-07) ------------------------------------------

def test_nodes_json_lab_sees_lan_peers_with_online_state(monkeypatch):
    monkeypatch.setattr(hosts, "all_remote", lambda: {
        "gos2": dict(PEER_HOST), "gos3": {**PEER_HOST, "label": "GoS3", "url": "http://10.0.0.10:8000"},
        "sshbox": {"enabled": True, "label": "Old", "ssh": "x@y"}})            # ssh driver: no pages
    monkeypatch.setattr(peer, "info", lambda h, max_age=20: {"rig": False} if h["id"] == "gos2" else None)
    n = client.get("/nodes.json", headers=LAB).json()["nodes"]
    assert [x["id"] for x in n] == ["gos1", "gos2", "gos3"]
    assert n[0]["self"] and n[1]["online"] and n[1]["url"] == "http://10.0.0.9:8000/" and not n[2]["online"]


def test_nodes_json_public_only_sees_public_urls(monkeypatch):
    monkeypatch.setattr(hosts, "all_remote", lambda: {
        "gos2": dict(PEER_HOST), "gos3": {**PEER_HOST, "label": "GoS3", "public_url": "https://gos3.example.org"}})
    monkeypatch.setattr(peer, "info", lambda h, max_age=20: {})
    n = client.get("/nodes.json", headers=ANON).json()["nodes"]
    assert [x["id"] for x in n] == ["gos1", "gos3"] and n[1]["url"] == "https://gos3.example.org/"


def test_home_page_has_registry_driven_switch():
    t = client.get("/", headers=LAB).text
    assert 'id="node-switch"' in t and "fetch('/nodes.json')" in t


# --- unsupported GPU presets (owner 2026-10-07: AV1 GPU on the M6) ---------------

def test_video_page_greys_presets_without_a_hardware_encoder(monkeypatch):
    import gpu
    monkeypatch.setattr(gpu, "supports", lambda c: c != "av1")
    t = client.get("/video", headers=LAB).text
    for k in ("av1_gpu", "av1_both"):
        card = t[t.index(f'id="preset-{k}"'):][:400]
        assert 'aria-disabled="true"' in card and "No hardware AV1 encoder" in card and "selectPreset" not in card
    assert "selectPreset('h265_gpu')" in t and "selectPreset('av1_cpu')" in t


def test_video_routes_refuse_unsupported_gpu_preset(monkeypatch):
    import gpu
    monkeypatch.setattr(gpu, "supports", lambda c: c != "av1")
    r = client.post("/video/use-source", headers=LAB, data={"source_key": "meridian_120s", "preset": "av1_both"})
    assert r.status_code == 400 and "No hardware AV1 encoder" in r.json()["error"]
    monkeypatch.setattr(gpu, "supports", lambda c: True)
    t = client.get("/video", headers=LAB).text
    assert "selectPreset('av1_both')" in t                       # GoS1 (NVENC) unchanged


# --- relative idle tolerance (owner 2026-10-07) -------------------------------------

def test_idle_tolerance_is_relative_with_a_floor():
    import power
    s = {}
    assert abs(power.idle_tolerance_w(78.0, s) - 3.12) < 1e-9      # GoS1 ≈ the old fixed 3 W
    assert power.idle_tolerance_w(1.5, s) == 0.5                    # GoS2: the floor, not 3 W
    assert power.idle_tolerance_w(None, s) == 0.5
    assert power.idle_tolerance_w(78.0, {"cooldown_idle_tolerance_mode": "absolute",
                                         "cooldown_idle_tolerance_w": 3.0}) == 3.0
    assert power.idle_tolerance_w(200.0, {"cooldown_idle_tolerance_pct": 2.0}) == 4.0


# --- member gateway: gos2.wattlab… served through GoS1 (owner 2026-10-07) --------

GW_HOST = "gos2.wattlab.greeningofstreaming.org"


def _gateway(monkeypatch):
    import settings as cfg
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda: {**real(), "gateway_hosts": {GW_HOST: "gos2"}})
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": dict(PEER_HOST)})
    calls = []
    def fake_forward(h, method, path, body=b"", content_type=None, timeout=60):
        calls.append((method, path, body, content_type))
        return 200, "text/html; charset=utf-8", "<html><body>Online WattLab · GoS2</body></html>".encode()
    monkeypatch.setattr(peer, "forward", fake_forward)
    return calls


def test_gateway_anonymous_gets_greyed_page_and_peer_sees_nothing(monkeypatch):
    calls = _gateway(monkeypatch)
    r = client.get("/video", headers={**ANON, "host": GW_HOST})
    assert r.status_code == 200 and "members only" in r.text and "noindex" in r.text
    assert r.headers.get("x-robots-tag", "").startswith("noindex") and calls == []
    assert "Disallow: /" in client.get("/robots.txt", headers={**ANON, "host": GW_HOST}).text
    assert calls == []


def test_gateway_member_is_forwarded_with_verified_identity(monkeypatch):
    import auth
    calls = _gateway(monkeypatch)
    monkeypatch.setattr(auth, "member_email_from_request", lambda req: "ben@example.org")
    r = client.post("/video/use-source?x=1", headers={**ANON, "host": GW_HOST},
                    data={"source_key": "meridian_120s", "preset": "cpu"})
    assert r.status_code == 200 and "GoS2" in r.text
    m, path, body, ctype = calls[-1]
    assert m == "POST" and path.startswith("/peer/view/video/use-source?") and "x=1" in path
    assert "_owl_tier=member" in path and "_owl_member=ben%40example.org" in path
    assert b"meridian_120s" in body and "urlencoded" in ctype


def test_gateway_lab_forwarded_as_lab_and_offline_is_greyed(monkeypatch):
    calls = _gateway(monkeypatch)
    client.get("/", headers={**LAB, "host": GW_HOST})
    assert calls[-1][1].startswith("/peer/view/?") and "_owl_tier=lab" in calls[-1][1]
    def boom(*a, **k): raise OSError("down")
    monkeypatch.setattr(peer, "forward", boom)
    r = client.get("/", headers={**LAB, "host": GW_HOST})
    assert r.status_code == 503 and "offline" in r.text


def test_gateway_off_without_setting(monkeypatch):
    calls = _gateway(monkeypatch)
    import settings as cfg
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda: {**real(), "gateway_hosts": {}})
    t = client.get("/", headers={**ANON, "host": GW_HOST}).text
    assert "members only" not in t and calls == []


def test_peer_view_dispatches_under_the_vouched_identity():
    import audience
    seen = {}
    @main.app.get("/_test_whoami")
    async def whoami(request: Request):
        import auth
        return {"tier": audience.tier(request).name, "email": auth.member_email_from_request(request)}
    try:
        p = "/peer/view/_test_whoami?_owl_tier=member&_owl_member=ben%40example.org"
        d = client.get(p, headers=_signed("GET", p)).json()
        assert d == {"tier": "Member", "email": "ben@example.org"}
        p = "/peer/view/_test_whoami?_owl_tier=root"
        assert client.get(p, headers=_signed("GET", p)).json()["tier"] == "Anonymous"
        p = "/peer/view/_test_whoami"
        assert client.get(p, headers=_signed("GET", p)).json()["tier"] == "Anonymous"
        assert audience.PEER_VISITOR.get() is None                    # reset after dispatch
    finally:
        main.app.router.routes[:] = [r for r in main.app.router.routes if getattr(r, "path", "") != "/_test_whoami"]


def test_peer_view_refuses_peer_api_and_lab_only_for_members():
    p = "/peer/view/peer/info?_owl_tier=lab"
    assert client.get(p, headers=_signed("GET", p)).status_code == 404
    p = "/peer/view/settings?_owl_tier=member&_owl_member=a%40b.org"
    body = b'{"baseline_polls": 7}'
    r = client.post(p, content=body, headers={**_signed("POST", p, body), "content-type": "application/json"})
    assert r.status_code in (403, 404)                                # SETTINGS_WRITE is Lab-only


def test_nodes_json_member_only_peer_is_locked_for_anonymous(monkeypatch):
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": {**PEER_HOST, "public_url": "https://" + GW_HOST,
                                                               "public_tier": "member"}})
    monkeypatch.setattr(peer, "info", lambda h, max_age=20: {})
    n = client.get("/nodes.json", headers=ANON).json()["nodes"]
    assert n[1]["locked"] is True and n[1]["url"] is None
    t = client.get("/", headers=ANON).text
    assert "· members</span>" in t


def test_session_cookie_scoped_to_configured_domain(monkeypatch):
    import auth, settings as cfg
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda: {**real(), "session_cookie_domain": "wattlab.greeningofstreaming.org"})
    monkeypatch.setattr(auth, "is_member", lambda e: True)
    tok = auth.issue_magic_token("ben@example.org")
    r = client.get(f"/auth/verify?t={tok}", headers={**ANON, "host": "gos2.wattlab.greeningofstreaming.org"},
                   follow_redirects=False)
    assert "Domain=wattlab.greeningofstreaming.org" in r.headers.get("set-cookie", "")
    # a gateway name outside wattlab.… (e.g. gos2.greeningofstreaming.org) → host-only cookie
    tok = auth.issue_magic_token("ben@example.org")
    r = client.get(f"/auth/verify?t={tok}", headers={**ANON, "host": "gos2.greeningofstreaming.org"},
                   follow_redirects=False)
    sc = r.headers.get("set-cookie", "")
    assert "owl_session=" in sc and "Domain=" not in sc


def test_switch_keeps_visitor_on_the_kind_of_address_they_arrived_on(monkeypatch):
    """Owner 2026-10-07: a Lab visitor on the public name was switched to raw LAN addresses."""
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": {**PEER_HOST, "public_url": "https://" + GW_HOST,
                                                               "public_tier": "member"}})
    monkeypatch.setattr(peer, "info", lambda h, max_age=20: {})
    pub = client.get("/nodes.json", headers={**LAB, "host": "wattlab.greeningofstreaming.org"}).json()["nodes"]
    assert pub[1]["url"] == f"https://{GW_HOST}/"
    lan = client.get("/nodes.json", headers={**LAB, "host": "192.168.1.62:8000"}).json()["nodes"]
    assert lan[1]["url"] == "http://10.0.0.9:8000/"
    p = "/peer/view/nodes.json?_owl_tier=lab"                      # through the gateway → public names
    d = client.get(p, headers=_signed("GET", p)).json()["nodes"]
    assert d[1]["url"] == f"https://{GW_HOST}/"
