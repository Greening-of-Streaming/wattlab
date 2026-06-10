"""
Tests for the Lab-only delete-result feature (dev cleanup of test runs):
persist.delete_result + the DELETE /results/{type}/{id} endpoint logic.

The auth gate (SETTINGS_WRITE / Lab) is enforced by FastAPI's dependency, which
the loopback Lab user passes and the (Anonymous) TestClient does not; that's
covered by the shared capability tests. Here we pin the file-level behaviour and
the endpoint's type-validation / not-found handling by calling it directly.
"""
import asyncio
import json

import persist
import main
import routes_results


def test_delete_result_removes_json(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    d = tmp_path / "llm"
    d.mkdir()
    p = d / "2026-06-02_abc12345.json"
    p.write_text(json.dumps({"job_id": "abc12345", "mode": "compare_models"}))
    assert persist.delete_result("llm", "abc12345") is True
    assert not p.exists()


def test_delete_result_missing_returns_false(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    (tmp_path / "llm").mkdir()
    assert persist.delete_result("llm", "nope") is False


def test_delete_result_no_dir_returns_false(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    assert persist.delete_result("video", "whatever") is False


def test_endpoint_deletes(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    # main imported delete_result by name — point it at the patched persist fn
    monkeypatch.setattr(routes_results, "delete_result", persist.delete_result)
    d = tmp_path / "image"
    d.mkdir()
    (d / "2026-06-02_img99.json").write_text("{}")
    out = asyncio.run(main.results_delete("image", "img99"))
    assert out == {"ok": True, "deleted": "img99"}


def test_endpoint_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(routes_results, "delete_result", persist.delete_result)
    (tmp_path / "image").mkdir()
    resp = asyncio.run(main.results_delete("image", "ghost"))
    assert getattr(resp, "status_code", None) == 404


def test_endpoint_invalid_type():
    resp = asyncio.run(main.results_delete("bogus", "x"))
    assert getattr(resp, "status_code", None) == 400
