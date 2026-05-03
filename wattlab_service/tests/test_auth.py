"""
Unit tests for `auth.py` — magic-link tokens, session cookies, allowlist.

Mirrors the test pattern set by tests/test_carbon.py / test_audience.py:
plain `def test_x()`, no classes, no FastAPI client. The auth module is
pure functions over strings and dicts, so a duck-typed request stub is
all we need.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import pytest

import auth


# --- Magic-link token round-trip --------------------------------------------

def test_issue_and_verify_magic_token_returns_normalised_email():
    t = auth.issue_magic_token("Member@Example.Org")
    assert auth.verify_magic_token(t) == "member@example.org"


def test_issue_magic_token_is_unique_per_call():
    """Same email twice must mint two different tokens (nonce in payload)."""
    a = auth.issue_magic_token("a@example.org")
    b = auth.issue_magic_token("a@example.org")
    assert a != b


def test_verify_magic_token_rejects_garbage():
    assert auth.verify_magic_token("") is None
    assert auth.verify_magic_token("not-a-token") is None
    assert auth.verify_magic_token("a.b") is None  # malformed b64
    assert auth.verify_magic_token("a.b.c") is None  # too many dots


def test_verify_magic_token_rejects_tampered_signature():
    t = auth.issue_magic_token("a@example.org")
    body, sig = t.rsplit(".", 1)
    bogus = body + "." + ("A" * len(sig))
    assert auth.verify_magic_token(bogus) is None


def test_verify_magic_token_rejects_tampered_payload():
    t = auth.issue_magic_token("a@example.org")
    body, sig = t.rsplit(".", 1)
    # Change one character in the body — signature won't match
    bogus = body[:-1] + ("X" if body[-1] != "X" else "Y") + "." + sig
    assert auth.verify_magic_token(bogus) is None


def test_verify_magic_token_rejects_expired():
    t = auth.issue_magic_token("a@example.org", ttl_s=-1)  # already expired
    assert auth.verify_magic_token(t) is None


# --- Session cookie round-trip ----------------------------------------------

def test_session_cookie_round_trip():
    c = auth.make_session_cookie_value("Foo@Bar.com")
    assert auth.email_from_session_cookie(c) == "foo@bar.com"


def test_session_cookie_rejects_garbage():
    assert auth.email_from_session_cookie("") is None
    assert auth.email_from_session_cookie("not-a-cookie") is None


def test_session_cookie_rejects_expired():
    c = auth.make_session_cookie_value("a@example.org", ttl_s=-1)
    assert auth.email_from_session_cookie(c) is None


# --- Cross-rejection between magic links and session cookies ---------------
#
# The two payload shapes share a signing key and wire format. The `purpose`
# field (`p:"login"` on magic links, absent on session cookies) keeps them
# from being confused. Pin both directions.


def test_session_cookie_cannot_be_used_as_magic_link():
    c = auth.make_session_cookie_value("a@example.org")
    assert auth.verify_magic_token(c) is None


def test_magic_link_cannot_be_used_as_session_cookie():
    t = auth.issue_magic_token("a@example.org")
    assert auth.email_from_session_cookie(t) is None


# --- Allowlist --------------------------------------------------------------

def test_is_member_normalises_case_and_whitespace(monkeypatch):
    monkeypatch.setattr(auth, "_members", {"foo@bar.com"})
    assert auth.is_member("foo@bar.com") is True
    assert auth.is_member("FOO@BAR.COM") is True
    assert auth.is_member("  Foo@Bar.com  ") is True
    assert auth.is_member("other@bar.com") is False


def test_is_member_rejects_empty(monkeypatch):
    monkeypatch.setattr(auth, "_members", {"foo@bar.com"})
    assert auth.is_member("") is False
    assert auth.is_member(None) is False  # type: ignore[arg-type]


def test_load_members_handles_missing_file(tmp_path):
    """A fresh checkout without data/members.json must still boot — the
    module logs and falls back to an empty allowlist."""
    members = auth._load_members(tmp_path / "no-such.json")
    assert members == set()


def test_load_members_handles_malformed_json(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not valid json")
    members = auth._load_members(p)
    assert members == set()


def test_load_members_lowercases_and_strips(tmp_path):
    p = tmp_path / "members.json"
    p.write_text(json.dumps({"members": ["  Alice@Example.org  ", "bob@example.org", ""]}))
    members = auth._load_members(p)
    assert members == {"alice@example.org", "bob@example.org"}


# --- Request helper ---------------------------------------------------------

@dataclass
class StubRequest:
    cookies: dict


def test_member_email_from_request_with_valid_cookie(monkeypatch):
    monkeypatch.setattr(auth, "_members", {"a@example.org"})
    cookie = auth.make_session_cookie_value("a@example.org")
    req = StubRequest(cookies={auth.SESSION_COOKIE_NAME: cookie})
    assert auth.member_email_from_request(req) == "a@example.org"


def test_member_email_from_request_rejects_non_member_cookie(monkeypatch):
    """Cookie validates but email isn't on the allowlist (e.g. ex-member).
    Returns None — the audience tier falls back to Anonymous."""
    monkeypatch.setattr(auth, "_members", {"a@example.org"})
    cookie = auth.make_session_cookie_value("ex@example.org")
    req = StubRequest(cookies={auth.SESSION_COOKIE_NAME: cookie})
    assert auth.member_email_from_request(req) is None


def test_member_email_from_request_no_cookie_returns_none():
    req = StubRequest(cookies={})
    assert auth.member_email_from_request(req) is None


def test_member_email_from_request_tampered_cookie_returns_none(monkeypatch):
    monkeypatch.setattr(auth, "_members", {"a@example.org"})
    cookie = auth.make_session_cookie_value("a@example.org")
    req = StubRequest(cookies={auth.SESSION_COOKIE_NAME: cookie[:-3] + "AAA"})
    assert auth.member_email_from_request(req) is None
