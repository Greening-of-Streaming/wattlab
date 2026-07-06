"""
CR-067 · observability & durability floor.

Covers the app-side pieces: no-PII-in-logs on the magic-link sender, watts
staleness signal, and the /healthz + /live health fields. (Backup manifest,
sudoers, and the external monitor are owner-infra, out of scope here.)
"""
import logging

from fastapi.testclient import TestClient

import email_send
import main
import runtime

_LAB = {"x-real-ip": "127.0.0.1"}  # LIVE_TELEMETRY is Lab/loopback-gated


# --- no-PII-in-logs (the hard-ordering item before any logging pass) --------

def test_redact_email_keeps_domain_drops_localpart():
    assert email_send._redact_email("alice@example.org") == "a***@example.org"
    assert email_send._redact_email("bob@gos.fr") == "b***@gos.fr"
    assert email_send._redact_email("notanemail") == "***"
    assert email_send._redact_email("") == "***"


def test_dry_run_does_not_log_full_email_or_link(monkeypatch, caplog):
    monkeypatch.setattr(email_send, "_ENV", {})  # no password → dry run, no LOG_LINK
    with caplog.at_level(logging.INFO, logger="email_send"):
        ok = email_send.send_magic_link("alice@example.org",
                                        "https://owl.example/auth/verify?t=SECRET")
    assert ok is True
    blob = " ".join(r.message for r in caplog.records)
    assert "DRY RUN" in blob
    assert "alice@example.org" not in blob      # full address never logged
    assert "SECRET" not in blob                 # the link (a credential) suppressed
    assert "a***@example.org" in blob           # redacted form is fine


def test_dry_run_link_included_only_with_explicit_optin(monkeypatch, caplog):
    monkeypatch.setattr(email_send, "_ENV", {"OWL_SMTP_LOG_LINK": "1"})
    with caplog.at_level(logging.INFO, logger="email_send"):
        email_send.send_magic_link("alice@example.org",
                                   "https://owl.example/auth/verify?t=SECRET")
    blob = " ".join(r.message for r in caplog.records)
    assert "SECRET" in blob                     # opt-in surfaces it for local debug
    assert "alice@example.org" not in blob      # address still redacted


# --- watts staleness --------------------------------------------------------

def test_watts_age_none_before_first_poll(monkeypatch):
    monkeypatch.setattr(runtime, "_watts_ok_monotonic", None)
    assert runtime.watts_age_s() is None


def test_watts_age_positive_after_poll(monkeypatch):
    import time
    monkeypatch.setattr(runtime, "_watts_ok_monotonic", time.monotonic() - 3.0)
    age = runtime.watts_age_s()
    assert age is not None and 2.5 <= age <= 5.0


# --- /healthz + /live -------------------------------------------------------

def test_healthz_is_public_and_cheap(monkeypatch):
    monkeypatch.setattr(runtime, "_watts_ok_monotonic", None)
    # No _LAB header: /healthz must answer for an anonymous external monitor.
    r = TestClient(main.app).get("/healthz")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert "watts_age_s" in j and "watts_fresh" in j
    assert "queue_depth" in j and "paused" in j


def test_healthz_flags_stale_meter(monkeypatch):
    import time
    monkeypatch.setattr(runtime, "_watts_ok_monotonic", time.monotonic() - 120)
    monkeypatch.setattr(main.queue_control, "paused", lambda: False)
    j = TestClient(main.app).get("/healthz").json()
    assert j["watts_fresh"] is False            # 120s old, not paused → stale


def test_healthz_not_stale_when_paused(monkeypatch):
    import time
    monkeypatch.setattr(runtime, "_watts_ok_monotonic", time.monotonic() - 120)
    monkeypatch.setattr(main.queue_control, "paused", lambda: True)
    j = TestClient(main.app).get("/healthz").json()
    assert j["watts_fresh"] is True             # staleness expected while paused


def test_live_includes_watts_age(monkeypatch):
    import time
    monkeypatch.setattr(runtime, "_watts_ok_monotonic", time.monotonic() - 1.0)
    j = TestClient(main.app).get("/live", headers=_LAB).json()
    assert "watts_age_s" in j and j["watts_age_s"] is not None
