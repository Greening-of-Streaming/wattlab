"""
feedback.py — moderated public feedback on findings (2026-07-01 Policy/Language
Lab call).

Anonymous visitors submit a comment or a question against a published finding.
The submission lands in a PRIVATE Lab-only queue — it is NEVER rendered on the
public page. A lab member reviews and resolves/closes each note. This is the
"findings for comment" rollout: publish early, invite correction, keep the
moderation loop closed.

Design choices (see the plan / lab call):
  - No public comment thread → no public spam surface, no third-party moderation.
  - No third-party CAPTCHA → nothing shipped to Google/Cloudflare, consistent with
    OWL's "no raw IP, no cookies, no access log" privacy posture. Abuse is held
    off with a hidden honeypot field (handled in the route) + a coarse per-subnet
    rate limit here.

Privacy: a record stores the submitted text, the pseudonymised visitor token from
`analytics.hash_ip()` (a keyed hash of the /24 subnet — never a raw IP), and an
optional member email when the submitter is signed in. Documented on /privacy.

Storage mirrors analytics.py: flat JSON under results/_feedback/, atomic writes,
a threading.Lock for the read-modify-write. This is a private moderation queue,
NOT part of the findings catalog — findings stay pure git markdown (CR-054 inv 7).
"""
import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import analytics

_REPO_ROOT = Path("/home/gos/wattlab")
FEEDBACK_DIR = _REPO_ROOT / "results" / "_feedback"

MAX_BODY_CHARS = 4000
VALID_KINDS = {"comment", "question"}
VALID_STATUS = {"open", "resolved"}
_ID_RE = re.compile(r"^[0-9a-f]{6,32}$")

# Coarse per-visitor-token rate limit — process-local, best-effort. The single
# worker means this dict is authoritative; a restart resets it (fine — it only
# throttles bursts, it is not a security boundary).
_RATE_MAX = 5
_RATE_WINDOW_S = 3600
_rate_lock = threading.Lock()
_rate: dict[str, list[float]] = {}

_lock = threading.Lock()


class FeedbackError(Exception):
    """Invalid submission (bad kind, empty/too-long body, bad status)."""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def rate_ok(visitor_token: str, now: float | None = None) -> bool:
    """True (and records a hit) if this visitor token is under the submission
    rate limit. An empty token (unknown/malformed IP) shares one bucket so it
    can't be used to bypass the limit."""
    now = time.time() if now is None else now
    key = visitor_token or "_unknown"
    with _rate_lock:
        hits = [t for t in _rate.get(key, []) if now - t < _RATE_WINDOW_S]
        if len(hits) >= _RATE_MAX:
            _rate[key] = hits
            return False
        hits.append(now)
        _rate[key] = hits
        return True


def submit(*, slug: str | None, kind: str, body: str,
           visitor_ip: str = "", member_email: str | None = None) -> str:
    """Persist one feedback submission; return its record id.

    Raises FeedbackError on invalid input. The raw IP is pseudonymised via
    analytics.hash_ip() before anything touches disk — no raw address is stored.
    """
    kind = (kind or "").strip()
    if kind not in VALID_KINDS:
        raise FeedbackError(f"kind must be one of {sorted(VALID_KINDS)}")
    body = (body or "").strip()
    if not body:
        raise FeedbackError("empty submission")
    if len(body) > MAX_BODY_CHARS:
        raise FeedbackError(f"too long (max {MAX_BODY_CHARS} characters)")

    rec_id = uuid.uuid4().hex[:12]
    rec = {
        "id": rec_id,
        "slug": (slug or None),
        "kind": kind,
        "body": body,
        "visitor_token": analytics.hash_ip(visitor_ip),   # keyed subnet hash, never a raw IP
        "member_email": member_email,
        "status": "open",
        "submitted_at": _now_iso(),
        "resolved_at": None,
    }
    with _lock:
        FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{datetime.now().strftime('%Y-%m-%d')}_{rec_id}.json"
        path = FEEDBACK_DIR / name
        tmp = path.parent / (name + ".tmp")
        tmp.write_text(json.dumps(rec, indent=2))
        tmp.replace(path)
    return rec_id


def list_all(status: str | None = None) -> list[dict]:
    """Every feedback record, newest first. Optional status filter."""
    if not FEEDBACK_DIR.exists():
        return []
    out: list[dict] = []
    for p in FEEDBACK_DIR.glob("*.json"):
        try:
            rec = json.loads(p.read_text())
        except Exception:
            continue
        if status and rec.get("status") != status:
            continue
        out.append(rec)
    out.sort(key=lambda r: r.get("submitted_at", ""), reverse=True)
    return out


def set_status(rec_id: str, status: str) -> bool:
    """Mark a submission resolved/open. Returns True if a record was updated."""
    if status not in VALID_STATUS:
        raise FeedbackError(f"status must be one of {sorted(VALID_STATUS)}")
    if not _ID_RE.match(rec_id or ""):
        return False
    with _lock:
        for p in FEEDBACK_DIR.glob(f"*_{rec_id}.json"):
            try:
                rec = json.loads(p.read_text())
            except Exception:
                continue
            rec["status"] = status
            rec["resolved_at"] = _now_iso() if status == "resolved" else None
            tmp = p.parent / (p.name + ".tmp")
            tmp.write_text(json.dumps(rec, indent=2))
            tmp.replace(p)
            return True
    return False


def open_count() -> int:
    """Number of unresolved submissions — for the Lab-only catalog badge."""
    return len(list_all(status="open"))
