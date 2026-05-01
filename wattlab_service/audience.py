"""
Audience tier resolution — single source of truth for "who is this request?".

Three tiers, in ascending privilege:
  Anonymous (0) — anyone past the gate password (today) / unauthenticated visitor (post-CR-001)
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


def tier(request: Request) -> Tier:
    """Resolve the audience tier for a request.

    Order of precedence:
      1. Member identity — magic-link cookie. Reserved for CR-001; no code
         path produces Member today.
      2. Lab — origin IP (X-Real-IP header from nginx, falling back to
         request.client.host) is loopback or RFC1918 private.
      3. Anonymous — everything else.
    """
    # CR-001 hook: when magic-link auth ships, check for the member cookie
    # here and return Tier.Member if valid. Until then, this branch is empty.

    ip_str = request.headers.get("x-real-ip") or (
        request.client.host if request.client else ""
    )
    if _is_loopback_or_private(ip_str):
        return Tier.Lab

    return Tier.Anonymous
