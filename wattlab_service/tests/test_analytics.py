"""
Unit tests for analytics.py — the privacy-by-design visit counter + IP
pseudonymisation. Plain `def test_x()`, no FastAPI client (mirrors
test_audience.py). The counter is redirected to a tmp file via monkeypatch so
tests never touch the live results tree.
"""
import importlib

import pytest

import analytics


# --- hash_ip: pseudonymisation invariants ----------------------------------

def test_hash_ip_is_not_the_raw_address():
    h = analytics.hash_ip("77.207.134.206")
    assert h
    assert "77.207" not in h
    assert "." not in h          # token is hex, never an address
    assert len(h) == 16


def test_hash_ip_is_stable_for_the_same_ip():
    assert analytics.hash_ip("8.8.8.8") == analytics.hash_ip("8.8.8.8")


def test_hash_ip_differs_across_subnets():
    assert analytics.hash_ip("8.8.8.8") != analytics.hash_ip("1.1.1.1")


def test_hash_ip_truncates_to_24_so_same_subnet_collapses():
    # /24 truncation: .5 and .200 share a network → same token (CNIL-style).
    assert analytics.hash_ip("203.0.113.5") == analytics.hash_ip("203.0.113.200")
    # different /24 → different token.
    assert analytics.hash_ip("203.0.113.5") != analytics.hash_ip("203.0.114.5")


def test_hash_ip_handles_ipv6():
    h = analytics.hash_ip("2001:db8::1")
    assert h and len(h) == 16
    # same /48 collapses
    assert analytics.hash_ip("2001:db8::1") == analytics.hash_ip("2001:db8::ffff")


@pytest.mark.parametrize("bad", ["", "not-an-ip", "999.999.999.999"])
def test_hash_ip_empty_or_malformed_returns_blank(bad):
    assert analytics.hash_ip(bad) == ""


# --- record_visit / summary: anonymous aggregate counter --------------------

@pytest.fixture
def tmp_counter(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics, "ANALYTICS_DIR", tmp_path)
    monkeypatch.setattr(analytics, "VISITS_FILE", tmp_path / "visits.json")
    return tmp_path


def test_record_visit_counts_by_tier_and_path(tmp_counter):
    analytics.record_visit("/llm", "anonymous")
    analytics.record_visit("/llm", "anonymous")
    analytics.record_visit("/demo", "anonymous")
    analytics.record_visit("/settings", "lab")

    s = analytics.summary()
    assert s["totals"]["anonymous"] == 3
    assert s["totals"]["lab"] == 1
    assert s["grand_total"] == 4
    assert dict(s["top_paths"])["/llm"] == 2
    assert s["first_recorded"] is not None


def test_record_visit_stores_no_ip(tmp_counter):
    analytics.record_visit("/video", "anonymous")
    raw = (tmp_counter / "visits.json").read_text()
    # The counter file must contain paths/tiers but never an address.
    assert "/video" in raw
    assert "anonymous" in raw
    for token in ("77.207", "8.8.8.8", "x-real-ip", "client"):
        assert token not in raw


def test_record_visit_respects_kill_switch(tmp_counter, monkeypatch):
    import settings
    monkeypatch.setattr(settings, "load", lambda: {"analytics_enabled": False})
    analytics.record_visit("/llm", "anonymous")
    assert analytics.summary()["grand_total"] == 0


def test_summary_empty_is_well_formed(tmp_counter):
    s = analytics.summary()
    assert s["grand_total"] == 0
    assert s["days"] == []
    assert s["totals"] == {"anonymous": 0, "member": 0, "lab": 0}
