"""
Unit tests for `email_send.py` — Gmail SMTP magic-link sender.

Three slices:
  - dry-run mode (when OWL_SMTP_PASSWORD is unset, or OWL_SMTP_DRY_RUN=1):
    no SMTP call, returns True, logs the link.
  - message construction: subject / from / to / both text+html bodies.
  - SMTP failure path: send_magic_link returns False, doesn't raise.

We never hit a real SMTP server — failures are simulated with monkeypatch.
"""
from __future__ import annotations

import logging

import pytest

import email_send


# --- Dry-run mode -----------------------------------------------------------

def test_dry_run_when_password_unset(monkeypatch, caplog):
    """No password → dry run, even if OWL_SMTP_DRY_RUN isn't set explicitly."""
    monkeypatch.setattr(email_send, "_ENV", {})
    monkeypatch.delenv("OWL_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("OWL_SMTP_DRY_RUN", raising=False)
    with caplog.at_level(logging.INFO, logger="email_send"):
        ok = email_send.send_magic_link("user@example.org",
                                        "https://owl.example/auth/verify?t=ABC")
    assert ok is True
    assert any("DRY RUN" in r.message for r in caplog.records)


def test_dry_run_explicit_flag(monkeypatch, caplog):
    """OWL_SMTP_DRY_RUN=1 forces dry run even if a password is configured."""
    monkeypatch.setattr(email_send, "_ENV",
                        {"OWL_SMTP_PASSWORD": "fake", "OWL_SMTP_DRY_RUN": "1"})
    with caplog.at_level(logging.INFO, logger="email_send"):
        ok = email_send.send_magic_link("user@example.org",
                                        "https://owl.example/auth/verify?t=ABC")
    assert ok is True
    assert any("DRY RUN" in r.message for r in caplog.records)


# --- Message construction ---------------------------------------------------

def test_build_message_includes_subject_from_to():
    msg = email_send._build_message("user@example.org",
                                    "https://owl.example/auth/verify?t=XYZ")
    assert msg["Subject"] == "Sign in to OWL"
    assert "greeningofstreaming@gmail.com" in msg["From"]
    assert msg["To"] == "user@example.org"


def test_build_message_has_both_text_and_html_bodies():
    """RFC requires multipart/alternative with both bodies; spam filters
    penalise text-less HTML and vice-versa. Pin that both are present."""
    msg = email_send._build_message("user@example.org", "https://owl/auth/verify?t=XYZ")
    text = msg.get_body(("plain",))
    html = msg.get_body(("html",))
    assert text is not None
    assert html is not None
    assert "https://owl/auth/verify?t=XYZ" in text.get_content()
    assert "https://owl/auth/verify?t=XYZ" in html.get_content()


def test_build_message_text_body_mentions_15_minutes():
    """Token TTL is 15 min — copy must say so. If MAGIC_LINK_TTL_SECONDS
    changes, this test should fail and force a copy update."""
    msg = email_send._build_message("user@example.org", "https://owl/auth/verify?t=XYZ")
    text = msg.get_body(("plain",)).get_content()
    assert "15 minutes" in text


# --- SMTP failure path ------------------------------------------------------

def test_send_returns_false_on_smtp_failure(monkeypatch):
    """Configure non-dry-run mode and simulate an SMTP failure. send must
    return False, not raise — caller surfaces the same generic UI either way."""
    monkeypatch.setattr(email_send, "_ENV", {"OWL_SMTP_PASSWORD": "fake"})
    monkeypatch.delenv("OWL_SMTP_DRY_RUN", raising=False)

    class BoomSMTP:
        def __init__(self, *a, **kw): raise OSError("connection refused")
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(email_send.smtplib, "SMTP_SSL", BoomSMTP)
    ok = email_send.send_magic_link("user@example.org", "https://owl/auth/verify?t=XYZ")
    assert ok is False


def test_send_real_path_calls_login_and_send_message(monkeypatch):
    """Configure non-dry-run mode and capture the SMTP calls. Make sure we
    log in with the configured user/password and call send_message exactly
    once with the built message."""
    monkeypatch.setattr(email_send, "_ENV",
                        {"OWL_SMTP_PASSWORD": "app-password",
                         "OWL_SMTP_USER": "greeningofstreaming@gmail.com"})
    monkeypatch.delenv("OWL_SMTP_DRY_RUN", raising=False)
    monkeypatch.setattr(email_send, "SMTP_USER", "greeningofstreaming@gmail.com")

    calls = {"login": None, "send_count": 0, "host": None, "port": None}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls["host"] = host
            calls["port"] = port
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, user, password):
            calls["login"] = (user, password)
        def send_message(self, msg):
            calls["send_count"] += 1
            calls["sent_subject"] = msg["Subject"]

    monkeypatch.setattr(email_send.smtplib, "SMTP_SSL", FakeSMTP)
    ok = email_send.send_magic_link("user@example.org", "https://owl/auth/verify?t=XYZ")
    assert ok is True
    assert calls["login"] == ("greeningofstreaming@gmail.com", "app-password")
    assert calls["send_count"] == 1
    assert calls["sent_subject"] == "Sign in to OWL"
