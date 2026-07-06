"""
CR-066 · reflected-input hardening on the magic-link auth flow.

These exercise the routes over HTTP (TestClient = Lab tier, but the auth
pages are PUBLIC_PAGE so they render for everyone). They pin the two
vulnerabilities the 2026-07 audit found: reflected XSS via `error`/`next`/
`email`, and open redirect via `next` on /auth/verify.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import auth
import main
from routes_auth import _safe_next


# --- _safe_next unit coverage ----------------------------------------------

def test_safe_next_allows_local_paths():
    assert _safe_next("/enhance-run") == "/enhance-run"
    assert _safe_next("/rag/compare?model=x&mode=y") == "/rag/compare?model=x&mode=y"


def test_safe_next_rejects_open_redirect_forms():
    assert _safe_next("https://evil.com") == "/"
    assert _safe_next("//evil.com") == "/"            # protocol-relative
    assert _safe_next("/\\evil.com") == "/"           # backslash trick
    assert _safe_next("/foo\\bar") == "/"             # embedded backslash
    assert _safe_next("javascript:alert(1)") == "/"   # scheme, no leading slash
    assert _safe_next("") == "/"
    assert _safe_next("relative/path") == "/"


def test_safe_next_rejects_control_chars():
    assert _safe_next("/foo\r\nSet-Cookie: x=y") == "/"
    assert _safe_next("/foo bar") == "/"              # space could break an attribute


# --- reflected XSS ----------------------------------------------------------

def test_sign_in_error_is_escaped():
    client = TestClient(main.app)
    r = client.get("/auth/sign-in", params={"error": "<script>alert(1)</script>"})
    assert r.status_code == 200
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_sign_in_next_attribute_cannot_break_out():
    client = TestClient(main.app)
    # A legit-looking but hostile next: tries to break out of value="...".
    r = client.get("/auth/sign-in", params={"next": '"><script>alert(1)</script>'})
    assert r.status_code == 200
    # Hostile next is not a local path → collapses to "/", and even the quote
    # is escaped, so no attribute breakout survives.
    assert '"><script>' not in r.text
    assert 'value="/"' in r.text


def test_sign_in_next_local_path_is_preserved():
    client = TestClient(main.app)
    r = client.get("/auth/sign-in", params={"next": "/enhance-run"})
    assert 'value="/enhance-run"' in r.text


def test_sign_in_submit_reflects_email_escaped(monkeypatch):
    monkeypatch.setattr(auth, "is_member", lambda e: False)  # non-member: no email sent
    client = TestClient(main.app)
    r = client.post("/auth/sign-in",
                    data={"email": "<b>x</b>@evil.com", "next": "/"})
    assert r.status_code == 200
    assert "<b>x</b>@evil.com" not in r.text
    assert "&lt;b&gt;x&lt;/b&gt;@evil.com" in r.text


# --- open redirect ----------------------------------------------------------

def test_verify_rejects_external_next_on_success(monkeypatch):
    monkeypatch.setattr(auth, "is_member", lambda e: True)
    token = auth.issue_magic_token("member@example.org")
    client = TestClient(main.app)
    r = client.get("/auth/verify",
                   params={"t": token, "next": "https://evil.com"},
                   follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/"          # NOT https://evil.com
    assert "owl_session" in r.headers.get("set-cookie", "")  # still signed in


def test_verify_preserves_local_next_on_success(monkeypatch):
    monkeypatch.setattr(auth, "is_member", lambda e: True)
    token = auth.issue_magic_token("member@example.org")
    client = TestClient(main.app)
    r = client.get("/auth/verify",
                   params={"t": token, "next": "/enhance-run"},
                   follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/enhance-run"


def test_verify_invalid_token_keeps_next_local(monkeypatch):
    client = TestClient(main.app)
    r = client.get("/auth/verify",
                   params={"t": "garbage", "next": "https://evil.com"},
                   follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("/auth/sign-in")
    assert "evil.com" not in loc                 # external next dropped, error param safe


# --- sign-out still works with its new PUBLIC_PAGE gate ---------------------

def test_sign_out_clears_cookie(monkeypatch):
    client = TestClient(main.app)
    r = client.post("/auth/sign-out", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/"
    # delete_cookie emits a Set-Cookie that expires owl_session
    assert "owl_session" in r.headers.get("set-cookie", "")
