"""
CR-001 magic-link auth — token issuance, session cookies, member allowlist.

Two distinct signed payloads, both HMAC-SHA256 over a JSON body:

  Magic-link token  — short-lived (15 min default), single-purpose.
                      Payload: {"e": <email>, "p": "login", "x": <epoch_exp>,
                                "n": <nonce>}
                      Wire form: <b64url-payload>.<b64url-sig>
                      Embedded in /auth/verify?t=...

  Session cookie    — long-lived (30 days default), set after a successful
                      magic-link verify. Payload: {"e": <email>,
                                                   "x": <epoch_exp>}
                      Cookie name: owl_session

Same signing key (OWL_AUTH_SECRET in .env) for both, with `purpose` field
inside the magic-link payload so a stolen-then-replayed cookie can't be
mistaken for a magic link or vice versa.

The signing key falls back to a one-shot generated value at process start if
unset — fine for development (cookies invalidate on restart) but a noisy
warning logs so production deployments notice and set the env var. Not
auto-persisting because shipping a "secret" file we'd accidentally read on
startup makes secret-rotation harder than just setting the env var.

Member allowlist lives in data/members.json (gitignored), path overridable
via OWL_MEMBERS_FILE. Loaded at import time, re-loadable via reload_members()
so the owner can edit the file without bouncing the service.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values

log = logging.getLogger(__name__)


# --- Signing key ------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV = dotenv_values(_REPO_ROOT / ".env")


def _resolve_secret() -> bytes:
    s = _ENV.get("OWL_AUTH_SECRET") or os.environ.get("OWL_AUTH_SECRET")
    if s:
        return s.encode("utf-8")
    log.warning(
        "OWL_AUTH_SECRET not set — using ephemeral key. "
        "Sessions will invalidate on every restart. Set in .env to fix."
    )
    return secrets.token_bytes(32)


_SECRET = _resolve_secret()


# --- Member allowlist -------------------------------------------------------

_DEFAULT_MEMBERS_FILE = _REPO_ROOT / "data" / "members.json"
_members: set[str] = set()


def _load_members(path: Path) -> set[str]:
    """Read a members.json file; return lowercased emails. Tolerant of a
    missing file (empty allowlist, log once) so a fresh checkout boots."""
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        log.warning("Members file not found at %s — allowlist empty", path)
        return set()
    except json.JSONDecodeError as e:
        log.error("Members file %s is malformed: %s — allowlist empty", path, e)
        return set()
    raw = data.get("members") or []
    return {e.strip().lower() for e in raw if isinstance(e, str) and e.strip()}


def reload_members() -> int:
    """Re-read the allowlist from disk. Returns the new count."""
    global _members
    path = Path(
        _ENV.get("OWL_MEMBERS_FILE")
        or os.environ.get("OWL_MEMBERS_FILE")
        or _DEFAULT_MEMBERS_FILE
    )
    _members = _load_members(path)
    log.info("Loaded %d member(s) from %s", len(_members), path)
    return len(_members)


reload_members()


def is_member(email: str) -> bool:
    if not email:
        return False
    return email.strip().lower() in _members


def list_members() -> list[str]:
    """Current allowlist as a sorted list. Reads in-memory state, not disk."""
    return sorted(_members)


def _members_file_path() -> Path:
    return Path(
        _ENV.get("OWL_MEMBERS_FILE")
        or os.environ.get("OWL_MEMBERS_FILE")
        or _DEFAULT_MEMBERS_FILE
    )


def write_members(emails) -> int:
    """Replace the allowlist. Accepts an iterable of strings or one newline-
    separated string. Lowercases, strips, dedupes, sorts; keeps only entries
    containing '@'. Atomic rewrite that preserves any sibling fields (e.g.
    `_comment`); calls reload_members(). Returns the new count."""
    if isinstance(emails, str):
        emails = emails.splitlines()
    cleaned = sorted({
        e.strip().lower()
        for e in emails
        if isinstance(e, str) and "@" in e.strip()
    })
    path = _members_file_path()
    try:
        existing = json.loads(path.read_text())
        if not isinstance(existing, dict):
            existing = {}
    except (FileNotFoundError, json.JSONDecodeError):
        existing = {}
    existing["members"] = cleaned
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(existing, indent=2) + "\n")
    tmp.replace(path)
    return reload_members()


# --- Token primitives -------------------------------------------------------
#
# Wire format: base64url(payload_json) + "." + base64url(hmac_sha256(payload_b64))
# All fields short-named (e/p/x/n) to keep URL length sane.


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body_b64 = _b64u(body)
    sig = hmac.new(_SECRET, body_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{body_b64}.{_b64u(sig)}"


def _verify(token: str) -> Optional[dict]:
    """Return payload dict if signature + expiry check; None otherwise."""
    if not token or "." not in token:
        return None
    body_b64, sig_b64 = token.rsplit(".", 1)
    expected = hmac.new(_SECRET, body_b64.encode("ascii"), hashlib.sha256).digest()
    try:
        got = _b64u_decode(sig_b64)
    except Exception:
        return None
    if not hmac.compare_digest(expected, got):
        return None
    try:
        payload = json.loads(_b64u_decode(body_b64))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("x")
    if not isinstance(exp, (int, float)) or time.time() > exp:
        return None
    return payload


# --- Magic-link tokens ------------------------------------------------------

MAGIC_LINK_TTL_SECONDS = 15 * 60


def issue_magic_token(email: str, ttl_s: int = MAGIC_LINK_TTL_SECONDS) -> str:
    """Sign a single-purpose login token. Caller is responsible for sending
    it to the user (email/SMS/etc.) — we just mint it.

    The nonce isn't checked against any server-side store (no DB), so this
    token is technically usable until expiry rather than strictly one-shot.
    Acceptable for the threat model: 15 min window, signed, only a known
    member email can do anything with it post-verify.
    """
    payload = {
        "e": email.strip().lower(),
        "p": "login",
        "x": int(time.time()) + int(ttl_s),
        "n": secrets.token_urlsafe(8),
    }
    return _sign(payload)


def verify_magic_token(token: str) -> Optional[str]:
    """Return the email if `token` is a valid, unexpired login token, else None."""
    payload = _verify(token)
    if payload is None:
        return None
    if payload.get("p") != "login":
        return None
    email = payload.get("e")
    return email if isinstance(email, str) and email else None


# --- Session cookie ---------------------------------------------------------

SESSION_COOKIE_NAME = "owl_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600


def make_session_cookie_value(email: str, ttl_s: int = SESSION_TTL_SECONDS) -> str:
    payload = {"e": email.strip().lower(), "x": int(time.time()) + int(ttl_s)}
    return _sign(payload)


def email_from_session_cookie(cookie_value: str) -> Optional[str]:
    """Return the email if `cookie_value` is a valid, unexpired session, else None.
    Note: does NOT check membership — caller does that, since a previously-valid
    session for a since-removed member should still parse cleanly so we can
    return Anonymous, not 500."""
    payload = _verify(cookie_value)
    if payload is None:
        return None
    # Distinguish from a magic-link token: magic links carry "p":"login";
    # session cookies have no "p" field. Reject anything with the wrong purpose.
    if payload.get("p") is not None:
        return None
    email = payload.get("e")
    return email if isinstance(email, str) and email else None


# --- Request helper ---------------------------------------------------------

def member_email_from_request(request) -> Optional[str]:
    """End-to-end: extract session cookie, verify signature/expiry, check
    allowlist. Returns the email if the request is from a current member,
    else None. `request` is duck-typed (anything with .cookies dict-access)
    so this is testable without FastAPI."""
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie:
        return None
    email = email_from_session_cookie(cookie)
    if email is None or not is_member(email):
        return None
    return email
