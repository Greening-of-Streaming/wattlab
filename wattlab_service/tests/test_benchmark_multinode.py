"""Benchmarks across OWL nodes (2026-10-09): host-stamped run files, replicated
once final, launchable on one node or several in parallel (shared group_id),
listed with a host filter and compared side by side."""
import json

import pytest
from fastapi.testclient import TestClient

import benchmark
import benchmark_compare
import hosts
import main
import peer
import persist
import queue_control
import replication

client = TestClient(main.app)
LAB = {"x-real-ip": "127.0.0.1"}
PEER_HOST = {"enabled": True, "label": "GoS2", "chip": "Apple M6", "driver": "peer",
             "url": "http://10.0.0.9:8000", "meters": ["10.0.0.1"], "engines": {}}


def _signed(method, path, body=b""):
    return {**LAB, peer.HEADER: peer.sign(method, path, body), "content-type": "application/json"}


def _settings(**over):
    s = {"bench_video_reps": 2, "bench_sources": ["meridian_120s"], "variance_runs": 0,
         "bench_run_video": True, "bench_run_llm": False, "bench_run_rag": False,
         "bench_run_image": False}
    s.update(over)
    return s


def _run_file(tmp_path, bid, host=None, status="done", group_id=None, steps=None,
              created="2026-10-06T10:00:00"):
    d = {"benchmark_run_id": bid, "job_id": bid, "status": status, "created_at": created,
         "saved_at": created, "group_id": group_id, "steps": steps or [], "total_steps": 0}
    if host:
        d["host"] = {"id": host, "label": host.upper().replace("GOS", "GoS")}
    (tmp_path / "benchmark").mkdir(exist_ok=True)
    (tmp_path / "benchmark" / f"{created[:10]}_{bid}.json").write_text(json.dumps(d))
    return d


# --- stamps + config ------------------------------------------------------------

def test_new_run_file_names_its_machine(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    m = benchmark.create_run("st1", _settings(), group_id="g1")
    assert m["host"]["id"] == hosts.local_host()["id"]
    assert "vendor" in m["gpu_hardware"] and "name" in m["power_hardware"]
    assert m["group_id"] == "g1"


def test_group_member_runs_the_launchers_plan():
    cfg_ = benchmark._config(_settings(bench_video_reps=3, bench_sources=["bbb_120s"]))
    mine = _settings(bench_video_reps=9, bench_sources=["x"], bench_run_llm=True, variance_runs=4)
    plan = benchmark.build_plan(benchmark.settings_for(cfg_, mine))
    assert [st["id"] for st in plan] == ["video_all_codecs"] * 3
    assert {st["params"]["source_key"] for st in plan} == {"bbb_120s"}
    assert benchmark.settings_for(None, mine) is mine


# --- export + replication ---------------------------------------------------------

def test_only_finished_runs_are_exported(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    _run_file(tmp_path, "fin1", status="done")
    _run_file(tmp_path, "run1", status="running")
    idx = client.get("/peer/results/benchmark", headers=_signed("GET", "/peer/results/benchmark")).json()
    assert [r["job_id"] for r in idx["results"]] == ["fin1"]


def test_run_that_finished_after_its_start_day_still_exports(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    d = _run_file(tmp_path, "late1", created="2026-10-06T23:00:00")
    d["saved_at"] = "2026-10-08T05:00:00"
    (tmp_path / "benchmark" / "2026-10-06_late1.json").write_text(json.dumps(d))
    q = "/peer/results/benchmark?since=2026-10-07T12:00:00"
    idx = client.get(q, headers=_signed("GET", q)).json()
    assert [r["job_id"] for r in idx["results"]] == ["late1"]


def test_legacy_hostless_run_exports_as_this_node(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    _run_file(tmp_path, "old1")
    d = client.get("/peer/results/benchmark/old1",
                   headers=_signed("GET", "/peer/results/benchmark/old1")).json()
    assert d["host"]["id"] == hosts.local_host()["id"] and d["host_inferred"] is True


def test_replication_pulls_peer_runs_last_and_keeps_their_host(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    assert replication.TYPES[-1] == "benchmark"
    env = {"benchmark_run_id": "gos2-b1", "job_id": "gos2-b1", "status": "done",
           "created_at": "2026-10-06T22:00:00", "saved_at": "2026-10-07T06:00:00",
           "host": {"id": "gos2", "label": "GoS2"}, "steps": []}
    def fake_call(h, method, path, payload=None, timeout=15):
        if path.startswith("/peer/results/benchmark/"):
            return env
        if path.startswith("/peer/results/benchmark"):
            return {"results": [{"job_id": "gos2-b1", "saved_at": env["saved_at"]}]}
        return {"results": []}
    monkeypatch.setattr(peer, "call", fake_call)
    monkeypatch.setattr(peer, "online", lambda h: True)
    assert replication.pull_once("gos2", PEER_HOST)["benchmark"] == 1
    # filed under its START date, like a locally written run
    assert (tmp_path / "benchmark" / "2026-10-06_gos2-b1.json").exists()
    runs = persist.list_results("benchmark", limit=10, visitor_key=None)
    assert runs[0]["host_id"] == "gos2"


# --- launch -----------------------------------------------------------------------

@pytest.fixture
def no_queue(monkeypatch, tmp_path):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    queued = []
    monkeypatch.setattr(queue_control, "enqueue",
                        lambda jid, t, label, coro, request=None: (queued.append((jid, label)), 1)[1])
    return queued


def test_default_launch_is_this_node_only(no_queue, monkeypatch):
    monkeypatch.setattr(peer, "call", lambda *a, **k: pytest.fail("no peer call expected"))
    r = client.post("/benchmark/run", headers=LAB)
    d = r.json()
    assert r.status_code == 200 and d["group_id"] is None and len(d["runs"]) == 1
    assert d["job_id"] == d["runs"][0]["job_id"]


def test_parallel_launch_shares_a_group_and_skips_offline_peer(no_queue, monkeypatch):
    me = hosts.local_host()["id"]
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": dict(PEER_HOST),
                                                      "gos3": {**PEER_HOST, "label": "GoS3"}})
    monkeypatch.setattr(peer, "online", lambda h: h["id"] == "gos2")
    sent = []
    def fake_call(h, method, path, payload=None, timeout=15):
        sent.append((h["id"], path, payload))
        return {"job_id": "gos2-abcd1234", "queue_position": 1}
    monkeypatch.setattr(peer, "call", fake_call)
    r = client.post("/benchmark/run", headers=LAB, json={"targets": [me, "gos2", "gos3"]})
    d = r.json()
    assert r.status_code == 200 and d["group_id"]
    assert [x["host"] for x in d["runs"]][1:] == ["GoS2"]
    assert d["skipped"] == [{"host": "GoS3", "reason": "offline"}]
    (hid, path, payload), = [c for c in sent if c[1] == "/peer/jobs"]
    assert path == "/peer/jobs" and payload["type"] == "benchmark"
    assert payload["params"]["group_id"] == d["group_id"] and "enabled" in payload["params"]["config"]
    local = benchmark.load_manifest(d["runs"][0]["job_id"])
    assert local["group_id"] == d["group_id"]


def test_peer_accepts_a_benchmark_job(no_queue):
    cfg_ = benchmark._config(_settings())
    body = json.dumps({"type": "benchmark", "params": {"config": cfg_, "group_id": "g9"}}).encode()
    r = client.post("/peer/jobs", content=body, headers=_signed("POST", "/peer/jobs", body))
    assert r.status_code == 200
    m = benchmark.load_manifest(r.json()["job_id"])
    assert m["group_id"] == "g9" and m["config"]["enabled"] == ["video_all_codecs"]


# --- read side --------------------------------------------------------------------

def test_list_labels_filters_and_groups_by_host(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    _run_file(tmp_path, "a1", host="gos1", group_id="gg")
    _run_file(tmp_path, "b1", host="gos2", group_id="gg")
    _run_file(tmp_path, "b2", host="gos2", created="2026-10-07T10:00:00")
    html = client.get("/benchmark", headers=LAB).text
    assert "Parallel run gg" in html and "/benchmark/compare?ids=" in html
    assert 'class="host-badge">GoS2<' in html
    only = client.get("/benchmark?host=gos1", headers=LAB).text
    assert "Benchmark a1" in only and "Benchmark b2" not in only


def test_compare_never_pools_and_reports_n(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    (tmp_path / "video").mkdir()
    def vid(jid, e):
        (tmp_path / "video" / f"2026-10-06_{jid}.json").write_text(json.dumps(
            {"job_id": jid, "mode": "all_codecs",
             "codecs": {"h264": {"cpu": {"energy": {"delta_e_wh": e}}}}}))
        return {"index": 0, "id": "video_all_codecs", "kind": "video",
                "params": {"source_key": "m"}, "status": "done",
                "result_ref": {"type": "video", "job_id": jid}}
    a = _run_file(tmp_path, "a1", host="gos1", steps=[vid("v1", 1.0), vid("v2", 3.0)])
    b = _run_file(tmp_path, "b1", host="gos2", steps=[vid("v3", 0.5),
                  {"kind": "video", "params": {"source_key": "m"},
                   "result_ref": {"type": "video", "job_id": "notyet"}}])
    tb = benchmark_compare.table([a, b])
    row, = tb["rows"]
    assert row["metric"] == "video · m · h264 · CPU"
    assert row["cells"][0] == {"n": 2, "mean": 2.0, "sd": pytest.approx(1.41421, rel=1e-4)}
    assert row["cells"][1]["n"] == 1 and row["cells"][1]["mean"] == 0.5
    assert [c["missing"] for c in tb["columns"]] == [0, 1]
    html = client.get("/benchmark/compare?ids=a1,b1", headers=LAB).text
    assert "never pooled" in html and "n=2" in html


def test_peer_without_benchmark_export_does_not_block_other_types(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    def fake_call(h, method, path, payload=None, timeout=15):
        if path.startswith("/peer/results/benchmark"):
            raise RuntimeError("HTTP 400 bad type")       # peer on older code
        return {"results": []}
    monkeypatch.setattr(peer, "call", fake_call)
    monkeypatch.setattr(peer, "online", lambda h: True)
    out = replication.pull_once("gos2", PEER_HOST)
    assert out["video"] == 0 and "benchmark_error" in out
    assert (tmp_path / "_replication" / "gos2.json").exists()


# --- busy nodes (owner 2026-10-10) -------------------------------------------------

ANON = {"x-real-ip": "8.8.8.8"}


@pytest.fixture
def bench_running(monkeypatch):
    monkeypatch.setattr(queue_control, "benchmark_state",
                        lambda: {"job_id": "b1", "status": "running", "stage": "step 2/9", "label": "x"})


def _peer_state(monkeypatch, info):
    monkeypatch.setattr(hosts, "all_remote", lambda: {"gos2": {**PEER_HOST, "public_url": "https://gos2.example/"}})
    monkeypatch.setattr(peer, "cached", lambda h: info)


def test_busy_node_refuses_visitor_runs_and_names_the_free_one(bench_running, monkeypatch):
    _peer_state(monkeypatch, {"benchmark": None})
    with pytest.raises(queue_control.BenchmarkBusy):
        queue_control.enqueue("j1", "video", "v", None, request=_req(ANON))
    import bench_cluster
    msg = bench_cluster.busy_message(_req(LAB))
    assert "running a benchmark" in msg and "GoS2 is free: http://10.0.0.9:8000/" in msg


def test_all_nodes_busy_is_a_lab_session_everywhere(bench_running, monkeypatch):
    _peer_state(monkeypatch, {"benchmark": {"job_id": "gos2-x", "status": "running"}})
    import bench_cluster
    assert "Every OWL machine" in bench_cluster.busy_message(None)
    html = client.get("/benchmark", headers=LAB).text
    assert "every OWL machine is benchmarking" in html


def test_idle_node_stays_open_and_shows_the_peers_benchmark(monkeypatch):
    _peer_state(monkeypatch, {"benchmark": {"job_id": "gos2-x", "status": "running", "stage": "step 1/4"}})
    monkeypatch.setattr(queue_control, "benchmark_state", lambda: None)
    html = client.get("/settings", headers=LAB).text
    assert "Benchmark running on <b>GoS2</b>" in html and "open for runs" in html
    assert 'class="bench-node" value="gos2"' in html and 'data-host="gos2"' in html   # cancel from here


def test_lab_is_never_refused_by_a_benchmark(bench_running, monkeypatch):
    monkeypatch.setattr(queue_control, "_jobs", {})
    pos = queue_control.enqueue("jlab", "video", "v", None, request=None)
    assert pos is not None
    queue_control.cancel_pending("jlab")


def test_peer_publishes_benchmark_state_and_cancels_it(bench_running, monkeypatch):
    d = client.get("/peer/info", headers=_signed("GET", "/peer/info")).json()
    assert d["benchmark"]["job_id"] == "b1"
    import routes_benchmark, runtime
    runtime.jobs["b9"] = {"type": "benchmark"}
    monkeypatch.setattr(routes_benchmark, "cancel_local", lambda j: "cancelling")
    r = client.post("/peer/jobs/b9/cancel", headers=_signed("POST", "/peer/jobs/b9/cancel"))
    assert r.json() == {"cancelled": True, "state": "cancelling"}
    runtime.jobs.pop("b9", None)


def test_cancel_on_another_node_goes_through_the_peer_api(monkeypatch):
    _peer_state(monkeypatch, None)
    calls = []
    monkeypatch.setattr(peer, "call", lambda h, m, p, payload=None, timeout=15:
                        (calls.append(p), {"cancelled": True, "state": "cancelling"})[1])
    r = client.post("/benchmark/cancel", headers=LAB, data={"job_id": "gos2-x", "host": "gos2"})
    assert r.json() == {"ok": True, "state": "cancelling"} and calls == ["/peer/jobs/gos2-x/cancel"]


def _req(headers):
    from starlette.requests import Request
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"",
                    "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
                    "client": (headers.get("x-real-ip", "127.0.0.1"), 1)})


def test_group_uses_launchers_calibration_count_and_respects_node_opt_outs():
    cfg_ = benchmark._config(_settings(variance_runs=30, bench_run_rag=True, bench_run_llm=True))
    node = _settings(variance_runs=5, bench_run_rag=False, bench_run_llm=True)
    s = benchmark.settings_for(cfg_, node)
    assert s["variance_runs"] == 30
    ids = [st["id"] for st in benchmark.build_plan(s)]
    assert ids[0] == "variance" and "llm_compare" in ids and "rag_compare" not in ids
