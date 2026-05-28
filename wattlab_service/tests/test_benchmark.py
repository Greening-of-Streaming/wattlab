"""
Unit tests for CR-061 — in-app overnight benchmark.

What's covered (no hardware, no real measurements):
  - build_plan: registry × settings → ordered steps; video fan-out; retire case
    (disable a measure) and add case (inject a registry entry).
  - manifest schema round-trip (JSON-serializable, schema_version present).
  - cancel honored: a flipped cancel flag skips the remaining steps, marks the
    run cancelled, and the partial manifest is persisted.
  - capability gating: BENCHMARK_RUN is Lab-only; /benchmark is gated.
  - results viewer tolerates a retired/unknown step kind.
"""
import asyncio
import json

import benchmark
import capabilities
from audience import Tier


# ── build_plan ──────────────────────────────────────────────────────────────

def _settings(**over):
    # variance is gated by variance_runs > 0 (not a bench_run_* flag)
    s = {"bench_video_reps": 5, "bench_sources": ["meridian_120s", "bbb_120s"],
         "variance_runs": 10, "bench_run_video": True, "bench_run_llm": True,
         "bench_run_rag": True, "bench_run_image": True}
    s.update(over)
    return s


def test_build_plan_default_shape():
    plan = benchmark.build_plan(_settings())
    # 1 variance + (2 sources × 5 reps) video + 3 AI = 14
    assert len(plan) == 14
    assert plan[0]["id"] == "variance"
    assert sum(1 for p in plan if p["id"] == "video_all_codecs") == 10
    # video fan-out carries source + rep params
    vids = [p for p in plan if p["id"] == "video_all_codecs"]
    assert {v["params"]["source_key"] for v in vids} == {"meridian_120s", "bbb_120s"}
    assert max(v["params"]["rep"] for v in vids) == 5


def test_build_plan_reps_and_sources_scale():
    plan = benchmark.build_plan(_settings(bench_video_reps=2, bench_sources=["meridian_120s"]))
    assert sum(1 for p in plan if p["id"] == "video_all_codecs") == 2  # 1 source × 2 reps


def test_build_plan_retire_case():
    # Disabling a measure drops its steps — the "retire" path, no code change.
    plan = benchmark.build_plan(_settings(bench_run_llm=False, bench_run_rag=False))
    ids = {p["id"] for p in plan}
    assert "llm_compare" not in ids and "rag_compare" not in ids
    assert "video_all_codecs" in ids  # others unaffected


def test_variance_runs_zero_skips_variance():
    # The "0 to skip" slider semantics — variance gated on variance_runs > 0.
    plan = benchmark.build_plan(_settings(variance_runs=0))
    assert all(p["id"] != "variance" for p in plan)


def test_variance_runs_positive_includes_variance():
    plan = benchmark.build_plan(_settings(variance_runs=4))
    assert plan[0]["id"] == "variance"


def test_build_plan_add_case(monkeypatch):
    # Adding a registry entry + ORDER slot makes it appear — the "add" path.
    async def _noop(step, jobs, sub_id, s):
        return None
    new = benchmark.Measure("new_thing", "new", "New measure", None, "bench_run_new", _noop)
    monkeypatch.setattr(benchmark, "MEASURES", {**benchmark.MEASURES, "new_thing": new})
    monkeypatch.setattr(benchmark, "ORDER", benchmark.ORDER + ["new_thing"])
    plan = benchmark.build_plan(_settings(bench_run_new=True))
    assert plan[-1]["id"] == "new_thing"
    assert plan[-1]["kind"] == "new"


def test_build_plan_skips_unknown_in_order(monkeypatch):
    monkeypatch.setattr(benchmark, "ORDER", benchmark.ORDER + ["does_not_exist"])
    plan = benchmark.build_plan(_settings())
    assert all(p["id"] != "does_not_exist" for p in plan)


# ── manifest ────────────────────────────────────────────────────────────────

def test_manifest_round_trip():
    plan = benchmark.build_plan(_settings())
    m = benchmark.init_manifest("abcd1234", plan, benchmark._config(_settings()))
    blob = json.dumps(m)            # must be serializable
    back = json.loads(blob)
    assert back["schema_version"] == 1
    assert back["benchmark_run_id"] == "abcd1234"
    assert back["status"] == "queued"
    assert back["total_steps"] == len(plan)
    assert all(st["status"] == "pending" and st["result_ref"] is None for st in back["steps"])


# ── cancel honored ──────────────────────────────────────────────────────────

def test_cancel_skips_remaining_and_persists(monkeypatch):
    calls = []
    bid = "cancel01"
    jobs = {bid: {"stage": "queued"}}

    async def first(step, jobs_, sub_id, s):
        calls.append(step["id"])
        jobs_[bid]["cancel_requested"] = True   # request cancel after step 1
        return None

    async def later(step, jobs_, sub_id, s):
        calls.append(step["id"])
        return None

    M = {
        "a": benchmark.Measure("a", "x", "A", None, "on", first),
        "b": benchmark.Measure("b", "x", "B", None, "on", later),
        "c": benchmark.Measure("c", "x", "C", None, "on", later),
    }
    monkeypatch.setattr(benchmark, "MEASURES", M)
    monkeypatch.setattr(benchmark, "ORDER", ["a", "b", "c"])
    monkeypatch.setattr(benchmark, "load_manifest", lambda b: None)
    captured = {}
    monkeypatch.setattr(benchmark, "_persist", lambda m: captured.update(m=m))

    res = asyncio.run(benchmark.run_benchmark_job(bid, jobs, {"on": True}))

    assert res["status"] == "cancelled"
    assert calls == ["a"]                       # b and c never executed
    m = captured["m"]
    assert m["status"] == "cancelled"
    assert m["steps"][0]["status"] == "done"
    assert m["steps"][1]["status"] == "skipped"
    assert m["steps"][2]["status"] == "skipped"


def test_completes_when_not_cancelled(monkeypatch):
    bid = "ok01"
    jobs = {bid: {"stage": "queued"}}

    async def ok(step, jobs_, sub_id, s):
        return {"type": "video", "job_id": sub_id}

    M = {"a": benchmark.Measure("a", "video", "A", "video", "on", ok)}
    monkeypatch.setattr(benchmark, "MEASURES", M)
    monkeypatch.setattr(benchmark, "ORDER", ["a"])
    monkeypatch.setattr(benchmark, "load_manifest", lambda b: None)
    captured = {}
    monkeypatch.setattr(benchmark, "_persist", lambda m: captured.update(m=m))

    res = asyncio.run(benchmark.run_benchmark_job(bid, jobs, {"on": True}))
    assert res["status"] == "done"
    assert captured["m"]["steps"][0]["status"] == "done"
    assert captured["m"]["steps"][0]["result_ref"]["type"] == "video"


def test_nonfatal_error_does_not_abort(monkeypatch):
    bid = "err01"
    jobs = {bid: {"stage": "queued"}}

    async def boom(step, jobs_, sub_id, s):
        raise RuntimeError("ollama down")

    async def ok(step, jobs_, sub_id, s):
        return None

    M = {"a": benchmark.Measure("a", "x", "A", None, "on", boom, fatal=False),
         "b": benchmark.Measure("b", "x", "B", None, "on", ok)}
    monkeypatch.setattr(benchmark, "MEASURES", M)
    monkeypatch.setattr(benchmark, "ORDER", ["a", "b"])
    monkeypatch.setattr(benchmark, "load_manifest", lambda b: None)
    captured = {}
    monkeypatch.setattr(benchmark, "_persist", lambda m: captured.update(m=m))

    res = asyncio.run(benchmark.run_benchmark_job(bid, jobs, {"on": True}))
    assert res["status"] == "done"               # non-fatal: run still completes
    assert captured["m"]["steps"][0]["status"] == "error"
    assert "ollama down" in captured["m"]["steps"][0]["error"]
    assert captured["m"]["steps"][1]["status"] == "done"


# ── capability gating ───────────────────────────────────────────────────────

def test_benchmark_run_is_lab_only():
    assert capabilities.can(Tier.Lab, capabilities.BENCHMARK_RUN) is True
    assert capabilities.can(Tier.Member, capabilities.BENCHMARK_RUN) is False
    assert capabilities.can(Tier.Anonymous, capabilities.BENCHMARK_RUN) is False


# ── pages: gating + viewer tolerance ────────────────────────────────────────

def test_benchmark_list_gated():
    from fastapi.testclient import TestClient
    import main
    c = TestClient(main.app)
    assert c.get("/benchmark").status_code == 403                       # anonymous
    assert c.get("/benchmark", headers={"x-real-ip": "127.0.0.1"}).status_code == 200  # lab


def test_detail_tolerates_unknown_kind(monkeypatch, tmp_path):
    import persist
    import main
    from fastapi.testclient import TestClient
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    plan = benchmark.build_plan(_settings(bench_video_reps=1, bench_sources=["meridian_120s"],
                                          bench_run_llm=False, bench_run_rag=False, bench_run_image=False))
    m = benchmark.init_manifest("view01", plan, benchmark._config(_settings()))
    # inject a retired/unknown-kind step the current renderer set won't know
    m["steps"].append({"index": 99, "id": "retired_x", "kind": "retired_x",
                       "label": "Retired measure", "status": "done", "result_ref": None,
                       "started_at": None, "finished_at": None, "error": None})
    m["status"] = "done"
    benchmark._persist(m)
    c = TestClient(main.app)
    resp = c.get("/benchmark/view01", headers={"x-real-ip": "127.0.0.1"})
    assert resp.status_code == 200
    assert "Retired measure" in resp.text   # rendered, didn't crash on unknown kind
