"""
Tests for the 2026-07-01 lab-call findings changes:
  - review_status editorial axis on the finding schema (separate from confidence)
  - moderated feedback / "Ask OWL" submission (anonymous POST → private Lab queue)

The feedback store is redirected to a tmp dir (autouse fixture) so tests never
touch results/_feedback. Anonymous is spoofed with x-real-ip=8.8.8.8 (TestClient
is loopback = Lab otherwise); the moderation queue must reject that.
"""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import analytics
import feedback
import findings
import settings as cfg
import main as main_mod


client = TestClient(main_mod.app)

_ANON = {"x-real-ip": "8.8.8.8"}                 # public IP → Anonymous tier
_LAB = {"x-real-ip": "127.0.0.1"}                # loopback → Lab tier
_FINDINGS_DIR = Path(findings.__file__).resolve().parent.parent / "docs" / "findings"


@pytest.fixture(autouse=True)
def _isolate_feedback(tmp_path, monkeypatch):
    """Point the feedback store at a tmp dir and reset the rate-limit table so
    tests are independent and never write to the real results/_feedback."""
    monkeypatch.setattr(feedback, "FEEDBACK_DIR", tmp_path / "_feedback")
    feedback._rate.clear()
    feedback._count_cache["t"] = -1.0
    yield
    feedback._rate.clear()
    feedback._count_cache["t"] = -1.0


def _enable(monkeypatch, enabled: bool):
    """Force findings_enabled without writing to the live settings.json —
    same non-destructive pattern the other findings tests use (patch cfg.load)."""
    real = cfg.load()

    def _patched():
        d = dict(real)
        d["findings_enabled"] = enabled
        return d

    monkeypatch.setattr(cfg, "load", _patched)


@pytest.fixture
def findings_on(monkeypatch):
    """Ensure the findings feature is enabled for the duration of a test."""
    _enable(monkeypatch, True)
    yield


# --- review_status schema axis --------------------------------------------

def test_editorial_axes_default_when_absent():
    """A finding with no review_status / impact fields → draft, unscored."""
    slug = "zzz-axis-defaults"
    p = _write_temp_finding(slug, "# no review_status or impact")
    try:
        f = findings.load(slug)
        assert f is not None
        assert f.review_status == "draft"
        assert f.impact is None
    finally:
        p.unlink(missing_ok=True)
        findings._CACHE.pop(slug, None)


def _write_temp_finding(slug: str, extra_lines: str) -> Path:
    """Clone the AV1 finding under a unique slug, then inject `extra_lines` into
    the frontmatter. Strips the source's own editorial-axis lines first so the
    test controls them exactly (no duplicate YAML keys)."""
    base = (_FINDINGS_DIR / "av1-hw-sw-vmaf-tradeoff.md").read_text(encoding="utf-8")
    base = base.replace("slug: av1-hw-sw-vmaf-tradeoff", f"slug: {slug}")
    base = re.sub(r"^(review_status|impact):.*\n", "", base, flags=re.M)
    base = base.replace("confidence: green", f"confidence: green\n{extra_lines}")
    p = _FINDINGS_DIR / f"{slug}.md"
    p.write_text(base, encoding="utf-8")
    return p


def test_valid_review_status_loads():
    slug = "zzz-review-status-valid"
    p = _write_temp_finding(slug, "review_status: for-comment")
    try:
        f = findings.load(slug)
        assert f is not None and f.review_status == "for-comment"
    finally:
        p.unlink(missing_ok=True)
        findings._CACHE.pop(slug, None)


def test_bad_review_status_fails_loudly():
    slug = "zzz-review-status-bogus"
    p = _write_temp_finding(slug, "review_status: definitely-not-valid")
    try:
        with pytest.raises(findings.FindingError):
            findings.load(slug)
    finally:
        p.unlink(missing_ok=True)
        findings._CACHE.pop(slug, None)


def test_valid_impact_loads():
    slug = "zzz-impact-valid"
    p = _write_temp_finding(slug, "impact: 3")
    try:
        f = findings.load(slug)
        assert f is not None and f.impact == 3
    finally:
        p.unlink(missing_ok=True)
        findings._CACHE.pop(slug, None)


def test_bad_impact_fails_loudly():
    slug = "zzz-impact-bogus"
    p = _write_temp_finding(slug, "impact: 5")   # 0 and >3 are invalid
    try:
        with pytest.raises(findings.FindingError):
            findings.load(slug)
    finally:
        p.unlink(missing_ok=True)
        findings._CACHE.pop(slug, None)


def test_catalog_sorted_strongest_first(findings_on):
    """Impact-3 findings must all sort ahead of impact-2 findings."""
    body = client.get("/findings").text
    i_high = body.index('href="/findings/gpu-boost-overclocks-fixed-function-nvenc"')  # impact 3
    i_low = body.index('href="/findings/av1-hw-sw-vmaf-tradeoff"')                     # impact 2
    assert i_high < i_low


def test_impact_marker_renders(findings_on):
    body = client.get("/findings").text
    assert "impact-marker" in body and "◆" in body


def test_review_pill_renders_on_pages(findings_on):
    """Both the catalog and a detail page carry the editorial review pill,
    distinct from the confidence dot."""
    cat = client.get("/findings")
    assert cat.status_code == 200
    assert "review-pill" in cat.text
    detail = client.get("/findings/av1-hw-sw-vmaf-tradeoff")
    assert detail.status_code == 200
    assert "review-pill" in detail.text
    # the two axes are labelled independently
    assert "review status" in detail.text.lower()


# --- feedback submission ---------------------------------------------------

def test_anonymous_can_submit_and_no_raw_ip_stored(findings_on):
    r = client.post("/findings/feedback",
                    data={"slug": "av1-hw-sw-vmaf-tradeoff",
                          "kind": "comment", "body": "great work"},
                    headers=_ANON)
    assert r.status_code == 200 and r.json().get("ok") is True

    recs = feedback.list_all()
    assert len(recs) == 1
    rec = recs[0]
    assert rec["body"] == "great work"
    assert rec["slug"] == "av1-hw-sw-vmaf-tradeoff"
    assert rec["status"] == "open"
    # pseudonymised token present, raw IP absent — anywhere in the record
    assert rec["visitor_token"] == analytics.hash_ip("8.8.8.8")
    assert "8.8.8.8" not in __import__("json").dumps(rec)


def test_general_ask_owl_has_no_slug(findings_on):
    r = client.post("/findings/feedback",
                    data={"kind": "question", "body": "can you measure X?"},
                    headers=_ANON)
    assert r.status_code == 200
    recs = feedback.list_all()
    assert len(recs) == 1 and recs[0]["slug"] is None


def test_honeypot_silently_drops(findings_on):
    r = client.post("/findings/feedback",
                    data={"kind": "comment", "body": "spam",
                          "website": "http://spammer.example"},
                    headers=_ANON)
    # looks like success to the bot…
    assert r.status_code == 200 and r.json().get("ok") is True
    # …but nothing is stored
    assert feedback.list_all() == []


def test_unknown_slug_rejected(findings_on):
    r = client.post("/findings/feedback",
                    data={"slug": "no-such-finding", "kind": "comment", "body": "x"},
                    headers=_ANON)
    assert r.status_code == 400
    assert feedback.list_all() == []


def test_empty_body_rejected(findings_on):
    r = client.post("/findings/feedback",
                    data={"kind": "comment", "body": "   "},
                    headers=_ANON)
    assert r.status_code == 400


def test_rate_limit_trips(findings_on):
    ok = 0
    limited = 0
    for _ in range(feedback._RATE_MAX + 3):
        r = client.post("/findings/feedback",
                        data={"kind": "comment", "body": "note"},
                        headers={"x-real-ip": "9.9.9.9"})
        if r.status_code == 200:
            ok += 1
        elif r.status_code == 429:
            limited += 1
    assert ok == feedback._RATE_MAX
    assert limited >= 1


def test_submit_404_when_feature_disabled(monkeypatch):
    _enable(monkeypatch, False)
    r = client.post("/findings/feedback",
                    data={"kind": "comment", "body": "x"}, headers=_ANON)
    assert r.status_code == 404


# --- moderation queue is Lab-only ------------------------------------------

def test_queue_is_lab_only(findings_on):
    # Anonymous (public IP) → 403
    r_anon = client.get("/findings/feedback/queue", headers=_ANON)
    assert r_anon.status_code == 403
    # Lab (loopback) → 200
    r_lab = client.get("/findings/feedback/queue", headers=_LAB)
    assert r_lab.status_code == 200


def test_resolve_flow(findings_on):
    client.post("/findings/feedback",
                data={"kind": "comment", "body": "resolve me"}, headers=_ANON)
    rid = feedback.list_all()[0]["id"]
    # anonymous cannot moderate
    r_anon = client.post(f"/findings/feedback/{rid}/status",
                         data={"status": "resolved"}, headers=_ANON)
    assert r_anon.status_code == 403
    # Lab can
    r_lab = client.post(f"/findings/feedback/{rid}/status",
                        data={"status": "resolved"}, headers=_LAB)
    assert r_lab.status_code == 200
    assert feedback.list_all()[0]["status"] == "resolved"
    assert feedback.open_count() == 0


# --- anti-flood hardening --------------------------------------------------

def test_global_daily_cap_silently_drops(findings_on, monkeypatch):
    """Over the per-day ceiling, submissions are accepted-looking but dropped —
    the backstop the per-subnet limit can't give against a distributed flood."""
    monkeypatch.setattr(feedback, "_MAX_PER_DAY", 2)
    # three distinct subnets so the per-SUBNET rate limit is not what bites
    for i, ip in enumerate(("11.0.0.1", "12.0.0.1", "13.0.0.1")):
        r = client.post("/findings/feedback",
                        data={"kind": "comment", "body": f"n{i}"},
                        headers={"x-real-ip": ip})
        assert r.status_code == 200 and r.json().get("ok") is True
    # only the first two were actually stored
    assert len(feedback.list_all()) == 2


def test_list_all_caps_scan(monkeypatch):
    monkeypatch.setattr(feedback, "_MAX_SCAN", 2)
    for _ in range(4):
        feedback.submit(slug=None, kind="comment", body="x")
    assert len(feedback.list_all()) == 2


def test_open_count_caches_then_rescans_after_ttl(findings_on):
    assert feedback.open_count(now=1000.0) == 0
    feedback.submit(slug=None, kind="comment", body="a")   # invalidates cache
    assert feedback.open_count(now=1001.0) == 1
    # a second open record written straight to disk (no cache invalidation)
    (feedback.FEEDBACK_DIR / "2026-07-01_deadbeef0001.json").write_text(
        json.dumps({"id": "deadbeef0001", "status": "open",
                    "submitted_at": "2026-07-01T00:00:00"}))
    assert feedback.open_count(now=1005.0) == 1    # within TTL → cached
    assert feedback.open_count(now=1099.0) == 2    # past TTL → rescanned


# --- Lab notification badge (top-right chip) -------------------------------

def test_lab_feedback_badge_shows_and_clears(findings_on):
    # assert on the ELEMENT, not the always-present CSS rule (.lab-fb-badge)
    marker = 'class="lab-fb-badge"'
    # clean queue → no badge on a Lab page
    assert marker not in client.get("/privacy", headers=_LAB).text
    rid = feedback.submit(slug=None, kind="question", body="notify me")
    # Lab sees the red badge…
    assert marker in client.get("/privacy", headers=_LAB).text
    # …anonymous never does
    assert marker not in client.get("/privacy", headers=_ANON).text
    # resolving clears it (state-driven, not permanent)
    feedback.set_status(rid, "resolved")
    assert marker not in client.get("/privacy", headers=_LAB).text
