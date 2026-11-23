"""CR-087 — the findings feed the GoS website copies (routes_findings_feed.py)."""
import pytest
from fastapi.testclient import TestClient

import finding_validation
import routes_findings_feed as feed_mod
import settings as cfg
from main import app

client = TestClient(app)
_ANON = {"x-real-ip": "8.8.8.8"}
_LAB = {"x-real-ip": "127.0.0.1"}
_PREVIEW = "/preview-c5d9b3be/findings"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(finding_validation, "LOG_DIR", tmp_path)
    monkeypatch.setattr(finding_validation, "LOG_FILE", tmp_path / "lab_validations.jsonl")
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda *a, **k: {**real(*a, **k), "findings_enabled": True})


def _feed():
    r = client.get("/findings.json", headers=_ANON)
    assert r.status_code == 200
    return r.json()


def test_feed_is_public_json_with_a_stable_shape():
    r = client.get("/findings.json", headers=_ANON)
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers["access-control-allow-origin"] == "*"
    d = r.json()
    assert d["schema_version"] == 1 and d["count"] == len(d["findings"]) > 0
    for i, f in enumerate(d["findings"], 1):
        assert f["sort_order"] == i
        assert f["headline"] and f["why_it_matters"]
        assert f["confidence"] in ("green", "yellow", "red")


def test_only_reviewed_findings_cross_over():
    d = _feed()
    assert {f["review_status"] for f in d["findings"]} <= {"lab-checked", "group-validated"}
    slugs = {f["slug"] for f in d["findings"]}
    assert "tv-screen-draws-20x-the-streaming-box" not in slugs        # still a machine draft
    assert "looped-excerpt-measures-as-continuous" not in slugs        # published, but machine-draft


def test_early_signals_carry_no_headline_number():
    for f in _feed()["findings"]:
        if f["early_signal"]:
            assert f["key_number"] == "" and f["summary"] == "", f["slug"]


def test_lab_validation_publishes_a_draft_and_names_stay_home():
    client.post(f"{_PREVIEW}/tv-screen-draws-20x-the-streaming-box/lab-validation",
                json={"action": "validate", "name": "Ben Schwarz"}, headers=_LAB)
    d = client.get("/findings.json", headers=_ANON)
    item = next(f for f in d.json()["findings"] if f["slug"] == "tv-screen-draws-20x-the-streaming-box")
    assert item["review_status"] == "lab-checked" and item["url"] is None   # no public page yet
    assert "Ben Schwarz" not in d.text


def test_published_findings_link_to_their_public_page():
    for f in _feed()["findings"]:
        if f["url"]:
            assert f["url"] == f"{feed_mod.DEFAULT_PUBLIC_URL}/findings/{f['slug']}"
            assert "preview" not in f["url"]


def test_feed_follows_the_findings_rollback_flag(monkeypatch):
    monkeypatch.setattr(cfg, "load", lambda *a, **k: {"findings_enabled": False})
    assert client.get("/findings.json", headers=_ANON).status_code == 404
