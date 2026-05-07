"""CR-026 — visitor-scoped persistence tests.

Covers:
- save_result records visitor_key on the JSON
- list_results filters by visitor_key (None = unfiltered, for Lab)
- load_result returns None on visitor_key mismatch
- pre-CR-026 records (no visitor_key field) are invisible to non-Lab callers
"""
import json
from pathlib import Path

import pytest

import persist


@pytest.fixture
def tmp_results(monkeypatch, tmp_path):
    """Point persist at a temp dir for the duration of one test."""
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    return tmp_path


def _strip_co2e(payload):
    """Tests don't care about the CO2e enrichment that walk_and_enrich
    bolts on; strip it for clarity."""
    return {k: v for k, v in payload.items() if k != "co2e"}


def test_save_result_persists_visitor_key(tmp_results):
    persist.save_result("video", "abc123", {"foo": "bar"},
                        visitor_key="m:user@example.com")
    [out] = list(tmp_results.glob("video/*.json"))
    data = json.loads(out.read_text())
    assert data["visitor_key"] == "m:user@example.com"
    assert data["job_id"] == "abc123"
    assert data["foo"] == "bar"


def test_save_result_lab_records_none(tmp_results):
    persist.save_result("video", "lab42", {"foo": "bar"}, visitor_key=None)
    [out] = list(tmp_results.glob("video/*.json"))
    data = json.loads(out.read_text())
    assert data["visitor_key"] is None


def test_list_results_unfiltered_returns_all(tmp_results):
    persist.save_result("video", "anon01", {}, visitor_key="a:1.1.1.1")
    persist.save_result("video", "memb01", {}, visitor_key="m:foo@bar.com")
    persist.save_result("video", "lab01",  {}, visitor_key=None)
    out = persist.list_results("video", visitor_key=None)
    job_ids = {r["job_id"] for r in out}
    assert job_ids == {"anon01", "memb01", "lab01"}


def test_list_results_member_sees_only_own(tmp_results):
    persist.save_result("video", "self01", {}, visitor_key="m:me@x.com")
    persist.save_result("video", "self02", {}, visitor_key="m:me@x.com")
    persist.save_result("video", "other",  {}, visitor_key="m:other@x.com")
    persist.save_result("video", "anon",   {}, visitor_key="a:9.9.9.9")
    out = persist.list_results("video", visitor_key="m:me@x.com")
    job_ids = {r["job_id"] for r in out}
    assert job_ids == {"self01", "self02"}


def test_list_results_anonymous_sees_only_own_ip(tmp_results):
    persist.save_result("video", "self01", {}, visitor_key="a:1.2.3.4")
    persist.save_result("video", "other",  {}, visitor_key="a:5.6.7.8")
    out = persist.list_results("video", visitor_key="a:1.2.3.4")
    assert {r["job_id"] for r in out} == {"self01"}


def test_load_result_visitor_match(tmp_results):
    persist.save_result("video", "j1", {"k": "v"}, visitor_key="m:owner@x.com")
    out = persist.load_result("video", "j1", visitor_key="m:owner@x.com")
    assert out is not None
    assert out["k"] == "v"


def test_load_result_visitor_mismatch_returns_none(tmp_results):
    persist.save_result("video", "j1", {"k": "v"}, visitor_key="m:owner@x.com")
    out = persist.load_result("video", "j1", visitor_key="m:intruder@x.com")
    assert out is None


def test_load_result_lab_bypasses_filter(tmp_results):
    """Lab passes None → must see everything regardless of saved key."""
    persist.save_result("video", "j1", {"k": "v"}, visitor_key="m:any@x.com")
    out = persist.load_result("video", "j1", visitor_key=None)
    assert out is not None
    assert out["k"] == "v"


def test_pre_cr026_records_invisible_to_non_lab(tmp_results):
    """Records written before CR-026 have no visitor_key field. Non-Lab
    callers must not see them — only Lab (visitor_key=None) does."""
    out_dir = tmp_results / "video"
    out_dir.mkdir()
    legacy = out_dir / "2026-04-01_legacy.json"
    legacy.write_text(json.dumps({"job_id": "legacy", "saved_at": "2026-04-01T10:00:00"}))

    # Lab sees it (None == "no filter")
    listed_lab = persist.list_results("video", visitor_key=None)
    assert {r["job_id"] for r in listed_lab} == {"legacy"}

    # Member can't see it
    listed_member = persist.list_results("video", visitor_key="m:any@x.com")
    assert listed_member == []

    # Anonymous can't see it either
    listed_anon = persist.list_results("video", visitor_key="a:1.1.1.1")
    assert listed_anon == []

    # Direct fetch — Member gets None
    assert persist.load_result("video", "legacy", visitor_key="m:any@x.com") is None
    # Lab gets the record
    legacy_loaded = persist.load_result("video", "legacy", visitor_key=None)
    assert legacy_loaded is not None
    assert legacy_loaded["job_id"] == "legacy"


def test_save_result_falls_back_to_queue_context(tmp_results, monkeypatch):
    """When save_result is called without an explicit visitor_key (e.g.
    from inside a workload module that doesn't thread it), it picks up
    the worker's current_visitor_key from queue_control."""
    import queue_control
    monkeypatch.setattr(queue_control, "current_visitor_key", "m:ambient@x.com")
    persist.save_result("video", "ambient01", {})
    [out] = list(tmp_results.glob("video/*.json"))
    data = json.loads(out.read_text())
    assert data["visitor_key"] == "m:ambient@x.com"
