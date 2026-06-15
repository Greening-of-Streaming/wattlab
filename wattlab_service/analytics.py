"""
analytics.py — privacy-by-design visit accounting (no cookies, no stored IPs).

Two jobs, both engineered so OWL never persists a piece of personal data it
doesn't have to:

  1. Aggregate visit counts. ``record_visit()`` increments a (day → tier → path)
     counter. No IP, no cookie, no User-Agent — nothing that could single out an
     individual. The counts are therefore anonymous statistical data and sit
     OUTSIDE the GDPR entirely (Recital 26). The hidden Lab-only ``/audience``
     page reads them back; ``/privacy`` documents them.

  2. IP pseudonymisation for the rest of the app. ``hash_ip()`` turns a visitor
     IP into a keyed, truncated, non-reversible token. ``queue_control.visitor_key``
     uses it so the per-visitor result scoping (CR-026) keeps working WITHOUT a
     raw address ever reaching disk. The IP is first truncated to its /24 (v4) or
     /48 (v6) network (CNIL-recommended for analytics), then HMAC-SHA256'd under
     the server secret and truncated to 16 hex chars.

Nothing in this module writes an IP, a User-Agent, or a cookie anywhere.
"""
import hashlib
import hmac
import ipaddress
import json
import os
import threading
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values

_REPO_ROOT = Path("/home/gos/wattlab")
_ENV = dotenv_values(_REPO_ROOT / ".env")


# --- IP pseudonymisation ----------------------------------------------------
#
# Reuse the same server secret the magic-link signer uses (auth.py) as the HMAC
# key. Different input domain (truncated IP vs token payload), so there is no
# cross-purpose leakage. If unset (dev), fall back to a process-random key:
# that makes the token unstable across restarts, which only loosens CR-026
# scoping (acceptable) while keeping at-rest tokens non-reversible.
def _resolve_salt() -> bytes:
    s = _ENV.get("OWL_AUTH_SECRET") or os.environ.get("OWL_AUTH_SECRET")
    if s:
        return s.encode("utf-8")
    return os.urandom(32)


_SALT = _resolve_salt()


def _truncate_ip(ip_str: str) -> str | None:
    """Drop host bits: IPv4 → /24 network, IPv6 → /48 network. Returns the
    network address as a string, or None for empty/malformed input."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return None
    prefix = 24 if addr.version == 4 else 48
    net = ipaddress.ip_network(f"{addr}/{prefix}", strict=False)
    return str(net.network_address)


def hash_ip(ip_str: str) -> str:
    """Keyed, truncated, non-reversible token for an IP.

    Returns '' for empty/malformed input (callers treat that as an unknown
    visitor). The raw address never leaves this function — only its /24 (or
    /48) network is hashed, so the token identifies at most a subnet, and only
    to a holder of the server secret.
    """
    if not ip_str:
        return ""
    truncated = _truncate_ip(ip_str)
    if truncated is None:
        return ""
    return hmac.new(_SALT, truncated.encode("ascii"), hashlib.sha256).hexdigest()[:16]


# --- Aggregate visit counter ------------------------------------------------

ANALYTICS_DIR = _REPO_ROOT / "results" / "_analytics"
VISITS_FILE = ANALYTICS_DIR / "visits.json"

# Single-worker service, but a threadpool-dispatched call could still race the
# read-modify-write. Cheap to guard; keeps the JSON consistent.
_lock = threading.Lock()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _load() -> dict:
    try:
        return json.loads(VISITS_FILE.read_text())
    except Exception:
        return {"first_recorded": None, "by_day": {}}


def record_visit(path: str, tier_name: str) -> None:
    """Increment the (day → tier → path) counter for one page view.

    Anonymous aggregate only — no IP, no cookie, no UA. Best-effort: a kill
    switch (``analytics_enabled`` in settings) and a blanket except mean this
    never raises into the request path.
    """
    try:
        import settings as _cfg
        if not _cfg.load().get("analytics_enabled", True):
            return
        with _lock:
            data = _load()
            if not data.get("first_recorded"):
                data["first_recorded"] = datetime.now().isoformat(timespec="seconds")
            day = data.setdefault("by_day", {}).setdefault(_today(), {})
            bucket = day.setdefault(tier_name, {})
            bucket[path] = bucket.get(path, 0) + 1
            bucket["__total__"] = bucket.get("__total__", 0) + 1
            ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
            tmp = VISITS_FILE.parent / (VISITS_FILE.name + ".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(VISITS_FILE)
    except Exception:
        pass


def summary() -> dict:
    """Roll the raw counter up for the /audience dashboard:
    grand/per-tier totals, a newest-first per-day table, and top paths."""
    data = _load()
    by_day = data.get("by_day", {})
    totals = {"anonymous": 0, "member": 0, "lab": 0}
    days = []
    for day in sorted(by_day.keys(), reverse=True):
        tiers = by_day[day]
        row = {"day": day, "tiers": {}}
        for tname, paths in tiers.items():
            t = paths.get("__total__", 0)
            row["tiers"][tname] = t
            if tname in totals:
                totals[tname] += t
        days.append(row)
    path_counts: dict[str, int] = {}
    for tiers in by_day.values():
        for paths in tiers.values():
            for p, n in paths.items():
                if p == "__total__":
                    continue
                path_counts[p] = path_counts.get(p, 0) + n
    top_paths = sorted(path_counts.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "first_recorded": data.get("first_recorded"),
        "totals": totals,
        "grand_total": sum(totals.values()),
        "days": days,
        "top_paths": top_paths,
    }
