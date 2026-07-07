"""Guided-tour pinned results (`demo_pinned_results` + /demo/last).

The tour's step panels pre-load via /demo/last/{type} (the CR-026
carve-out). Pins make that curation explicit: the operator names the
job_id each step shows, so a benchmark flooding results/ can never
empty a tour step again. Contract under test:

- pin-first for every type; a dangling pin falls back to latest-matching
- `enhance` is pin-ONLY (results/enhance holds member uploads — "latest"
  could leak a private job): no pin or dangling pin → 404, never a listing
- `rag` is a pseudo-type: results/llm/ record with mode == "rag_compare"
- pins deliberately bypass CR-026 visitor scoping (visitor_key=None load)
"""
import pytest
from fastapi.testclient import TestClient

import main
import persist
import settings as cfg

client = TestClient(main.app)

ANON = {"x-real-ip": "8.8.8.8"}


@pytest.fixture
def tmp_results(monkeypatch, tmp_path):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def pin(monkeypatch):
    """Set demo_pinned_results for one test; returns the setter."""
    def _set(pins):
        real_load = cfg.load
        def pinned_load():
            d = real_load()
            d["demo_pinned_results"] = pins
            return d
        monkeypatch.setattr(cfg, "load", pinned_load)
    return _set


def test_enhance_no_pin_404_even_with_records(tmp_results, pin):
    persist.save_result("enhance", "priv01", {"mode": "enhance"},
                        visitor_key="m:someone@example.com")
    pin({})
    r = client.get("/demo/last/enhance", headers=ANON)
    assert r.status_code == 404


def test_enhance_pin_served_bypassing_visitor_scope(tmp_results, pin):
    # Member-scoped record: the pin is the operator's promise it's public.
    persist.save_result("enhance", "show01", {"mode": "enhance"},
                        visitor_key="m:someone@example.com")
    pin({"enhance": "show01"})
    r = client.get("/demo/last/enhance", headers=ANON)
    assert r.status_code == 200
    assert r.json()["job_id"] == "show01"


def test_enhance_dangling_pin_404_never_lists(tmp_results, pin):
    persist.save_result("enhance", "priv01", {"mode": "enhance"},
                        visitor_key="m:someone@example.com")
    pin({"enhance": "deleted99"})
    r = client.get("/demo/last/enhance", headers=ANON)
    assert r.status_code == 404


def test_video_pin_beats_latest(tmp_results, pin):
    persist.save_result("video", "old01", {"mode": "both"}, visitor_key=None)
    persist.save_result("video", "new01", {"mode": "both"}, visitor_key=None)
    pin({"video": "old01"})
    r = client.get("/demo/last/video", headers=ANON)
    assert r.status_code == 200
    assert r.json()["job_id"] == "old01"


def test_video_unpinned_falls_back_to_latest(tmp_results, pin):
    persist.save_result("video", "only01", {"mode": "both"}, visitor_key=None)
    pin({})
    r = client.get("/demo/last/video", headers=ANON)
    assert r.status_code == 200
    assert r.json()["job_id"] == "only01"


def test_video_dangling_pin_falls_back(tmp_results, pin):
    persist.save_result("video", "only01", {"mode": "both"}, visitor_key=None)
    pin({"video": "gone99"})
    r = client.get("/demo/last/video", headers=ANON)
    assert r.status_code == 200
    assert r.json()["job_id"] == "only01"


def test_rag_pseudo_type_filters_mode(tmp_results, pin):
    # results/llm/ holds mixed shapes; /demo/last/rag must pick the
    # rag_compare one even when a plain single is newer.
    persist.save_result("llm", "ragc01", {"mode": "rag_compare"},
                        visitor_key=None)
    persist.save_result("llm", "single01", {"mode": "single"},
                        visitor_key=None)
    pin({})
    r = client.get("/demo/last/rag", headers=ANON)
    assert r.status_code == 200
    assert r.json()["job_id"] == "ragc01"


def test_rag_pin_served_from_llm_dir(tmp_results, pin):
    persist.save_result("llm", "ragold", {"mode": "rag_compare"},
                        visitor_key=None)
    persist.save_result("llm", "ragnew", {"mode": "rag_compare"},
                        visitor_key=None)
    pin({"rag": "ragold"})
    r = client.get("/demo/last/rag", headers=ANON)
    assert r.status_code == 200
    assert r.json()["job_id"] == "ragold"


def test_invalid_type_still_400(tmp_results, pin):
    pin({})
    r = client.get("/demo/last/benchmark", headers=ANON)
    assert r.status_code == 400
