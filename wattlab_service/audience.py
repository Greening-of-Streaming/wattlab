"""
Audience tier resolution — single source of truth for "who is this request?".

Three tiers, in ascending privilege:
  Anonymous (0) — unauthenticated visitor (no owl_session cookie)
  Member    (1) — authenticated GoS member (defined-but-unreachable until CR-001 magic-link auth lands)
  Lab       (2) — request originating on the LAN / loopback / SSH-tunnelled to localhost

`tier(request)` is the only public resolver. Routes never inspect cookies or
client.host directly — they ask `audience.tier(request)` and `capabilities.can(...)`.

Until CR-001 ships magic-link auth, the Member branch is unreachable: every
request resolves to either Anonymous (public) or Lab (loopback/private). The
hook is in place so CR-001 only edits this file, not every route.

This module deliberately has zero project-internal imports — it is the bottom
of the dependency graph for the access spine.
"""

from enum import IntEnum
import ipaddress

from fastapi import Request


class Tier(IntEnum):
    Anonymous = 0
    Member = 1
    Lab = 2


def _is_loopback_or_private(ip_str: str) -> bool:
    """True for loopback (127.0.0.0/8, ::1) and RFC1918 private ranges.

    Pure helper — no Request dependency, easy to unit-test against
    string IPs. Returns False for empty / malformed input rather than
    raising, since both come up routinely (no header, garbled proxy data).
    """
    if not ip_str:
        return False
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private


# Peers whose X-Real-IP header we believe: the local nginx (loopback) — and
# Starlette's TestClient, whose client.host is this literal (a real ASGI server
# always reports an IP, so it can never match in production).
_TRUSTED_PROXY_HOSTS = {"testclient"}


def client_ip(request) -> str:
    """The visitor's IP. X-Real-IP is honoured only when the direct peer is a
    trusted proxy (loopback nginx); anyone reaching :8000 directly is judged by
    their own socket address, so the header can't be spoofed to claim Lab."""
    host = request.client.host if getattr(request, "client", None) else ""
    trusted = host in _TRUSTED_PROXY_HOSTS
    if not trusted:
        try:
            trusted = ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
    if trusted:
        hdr = request.headers.get("x-real-ip") if request.headers else None
        if hdr:
            return hdr
    return host


# CR-085 member gateway (owner 2026-10-07): when GoS1 forwards a member's or a
# Lab visitor's request to GoS2 over the signed peer link, GoS2 dispatches it
# in-process (routes_peer._dispatch) with the identity GoS1 verified held here.
# Only that dispatcher sets it; a client can never set a ContextVar, so this is
# not a spoofable header. Unset (None) everywhere else → tier() as before.
import contextvars
PEER_VISITOR: "contextvars.ContextVar[dict | None]" = contextvars.ContextVar("owl_peer_visitor", default=None)


def tier(request: Request) -> Tier:
    """Resolve the audience tier for a request.

    Order of precedence:
      1. Lab — origin IP (X-Real-IP header from nginx, falling back to
         request.client.host) is loopback or RFC1918 private. Lab beats
         Member: a member SSH-tunnelling to localhost gets the full Lab
         experience without having to also sign in.
      2. Member — valid `owl_session` cookie whose email is in the allowlist.
      3. Anonymous — everything else.
    """
    pv = PEER_VISITOR.get()
    if pv is not None:
        return {"lab": Tier.Lab, "member": Tier.Member}.get(pv.get("tier"), Tier.Anonymous)
    ip_str = client_ip(request)
    if _is_loopback_or_private(ip_str):
        return Tier.Lab

    # CR-001: signed session cookie + allowlisted email → Member.
    # auth is imported lazily so a misconfigured auth module can't break
    # request routing for the Anonymous/Lab paths.
    try:
        import auth as _auth
        if _auth.member_email_from_request(request) is not None:
            return Tier.Member
    except Exception:
        pass

    return Tier.Anonymous
