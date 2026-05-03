"""
Unit tests for `audience.py`.

Mirrors the test pattern set by tests/test_carbon.py (S16): plain `def test_x()`,
no classes, no FastAPI test client — a stub Request is enough.

What's covered:
  - _is_loopback_or_private() across the IP space (loopback, RFC1918, public, malformed)
  - tier() resolution from x-real-ip header (nginx path) and request.client.host (direct)
  - Header takes precedence over client.host (matches nginx reverse-proxy reality)
  - The "Member is unreachable until CR-001" invariant — pinned as a regression
"""
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

import audience
from audience import Tier


# --- Stub Request -----------------------------------------------------------
#
# We don't need FastAPI's full Request object to test the header / client.host
# resolution path — a duck-typed stub is enough and keeps tests fast.

@dataclass
class StubRequest:
    headers: dict
    client: SimpleNamespace | None
    cookies: dict


def make_request(x_real_ip: str | None = None, client_host: str | None = None,
                 cookies: dict | None = None) -> StubRequest:
    headers = {}
    if x_real_ip is not None:
        headers["x-real-ip"] = x_real_ip
    client = SimpleNamespace(host=client_host) if client_host is not None else None
    return StubRequest(headers=headers, client=client, cookies=cookies or {})


# --- _is_loopback_or_private ------------------------------------------------

@pytest.mark.parametrize("ip", ["127.0.0.1", "127.5.5.5", "::1"])
def test_loopback_addresses_are_recognised(ip):
    assert audience._is_loopback_or_private(ip) is True


@pytest.mark.parametrize("ip", ["192.168.1.62", "10.0.0.5", "172.16.0.5", "172.31.255.254"])
def test_rfc1918_addresses_are_recognised(ip):
    assert audience._is_loopback_or_private(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "172.32.0.1"])
def test_public_addresses_are_rejected(ip):
    """172.32.0.1 is just outside RFC1918 (172.16/12 ends at 172.31). Pin it."""
    assert audience._is_loopback_or_private(ip) is False


@pytest.mark.parametrize("garbage", ["", "not-an-ip", "999.999.999.999", None])
def test_malformed_input_does_not_raise(garbage):
    """Garbled X-Real-IP headers are routine. Return False, never raise."""
    assert audience._is_loopback_or_private(garbage) is False


# --- tier() -----------------------------------------------------------------

def test_tier_loopback_via_client_host_is_lab():
    req = make_request(client_host="127.0.0.1")
    assert audience.tier(req) == Tier.Lab


def test_tier_private_via_client_host_is_lab():
    req = make_request(client_host="192.168.1.62")
    assert audience.tier(req) == Tier.Lab


def test_tier_public_via_client_host_is_anonymous():
    req = make_request(client_host="8.8.8.8")
    assert audience.tier(req) == Tier.Anonymous


def test_tier_x_real_ip_takes_precedence_over_client_host():
    """When nginx is in front, client.host is the proxy's IP (loopback) but
    the real client is in x-real-ip. Header must win."""
    req = make_request(x_real_ip="8.8.8.8", client_host="127.0.0.1")
    assert audience.tier(req) == Tier.Anonymous


def test_tier_x_real_ip_loopback_overrides_public_client_host():
    """Inverse case: SSH tunnel from outside back to localhost. Header is
    loopback (real source), client.host might be anything. Lab wins."""
    req = make_request(x_real_ip="127.0.0.1", client_host="8.8.8.8")
    assert audience.tier(req) == Tier.Lab


def test_tier_no_client_falls_back_to_anonymous():
    """Edge case: ASGI scope where request.client is None."""
    req = StubRequest(headers={}, client=None, cookies={})
    assert audience.tier(req) == Tier.Anonymous


def test_tier_garbled_header_falls_through_to_client_host():
    """Bogus x-real-ip should not poison resolution — fall through.
    Today's behaviour: garbled header causes _is_loopback_or_private to
    return False, then we return Anonymous (no fall-through to client.host
    because the chain `header or client.host` short-circuits on truthy).
    Pin this so any future change to the chain is intentional."""
    req = make_request(x_real_ip="garbage", client_host="127.0.0.1")
    assert audience.tier(req) == Tier.Anonymous


# --- Member tier (CR-001) ---------------------------------------------------
#
# Member is reachable iff:
#   - session cookie validates (signature + expiry)
#   - the email it carries is on the allowlist (auth.is_member)
#   - the request didn't already resolve to Lab (Lab beats Member, by design)


def _make_session_cookie_for(email: str) -> dict:
    import auth
    return {auth.SESSION_COOKIE_NAME: auth.make_session_cookie_value(email)}


def test_member_tier_with_valid_cookie_for_allowlisted_email(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "_members", {"member@example.org"})
    cookies = _make_session_cookie_for("member@example.org")
    req = make_request(x_real_ip="8.8.8.8", cookies=cookies)
    assert audience.tier(req) == Tier.Member


def test_member_tier_rejects_cookie_for_non_allowlisted_email(monkeypatch):
    """A previously-issued cookie for someone since-removed from the allowlist
    must NOT grant Member. Falls back to Anonymous on a public IP."""
    import auth
    monkeypatch.setattr(auth, "_members", {"member@example.org"})
    cookies = _make_session_cookie_for("ex-member@example.org")
    req = make_request(x_real_ip="8.8.8.8", cookies=cookies)
    assert audience.tier(req) == Tier.Anonymous


def test_member_tier_rejects_tampered_cookie(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "_members", {"member@example.org"})
    cookies = _make_session_cookie_for("member@example.org")
    cookies[auth.SESSION_COOKIE_NAME] = cookies[auth.SESSION_COOKIE_NAME][:-3] + "AAA"
    req = make_request(x_real_ip="8.8.8.8", cookies=cookies)
    assert audience.tier(req) == Tier.Anonymous


def test_lab_beats_member(monkeypatch):
    """A member SSH-tunnelling from outside back to localhost should resolve
    Lab, not Member, so they keep full Lab privileges without separately
    signing in. Pinned because it's a deliberate design choice (Lab > Member)."""
    import auth
    monkeypatch.setattr(auth, "_members", {"member@example.org"})
    cookies = _make_session_cookie_for("member@example.org")
    req = make_request(x_real_ip="127.0.0.1", cookies=cookies)
    assert audience.tier(req) == Tier.Lab


def test_no_cookie_with_public_ip_is_anonymous():
    req = make_request(x_real_ip="8.8.8.8", cookies={})
    assert audience.tier(req) == Tier.Anonymous


# --- Tier ordering invariant ------------------------------------------------

def test_tier_ordering_is_anonymous_lt_member_lt_lab():
    """capabilities.can() relies on this ordering for the >= predicate.
    Pin it so an accidental enum reorder is caught immediately."""
    assert Tier.Anonymous < Tier.Member < Tier.Lab
    assert int(Tier.Anonymous) == 0
    assert int(Tier.Member) == 1
    assert int(Tier.Lab) == 2
