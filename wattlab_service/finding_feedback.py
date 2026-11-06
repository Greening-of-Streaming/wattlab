"""
finding_feedback.py — CR-086 — community signals on findings (👍 / ❓) and the
findings-page layout vote.

WattLab call 2026-11-05 (Dom's proposal, group consensus): each finding gets a
thumbs-up ("makes sense to me") and a question mark ("I don't get this"), and
no thumbs-down. Many 👍 make a finding a candidate for group validation; many
❓ send it back to technical review. **Signals rank the review agenda; they never
change a finding's review_status** — only a WattLab meeting does that.

Storage is an append-only JSONL log (`results/_feedback/votes.jsonl`): one
event per click, replayed to get current state. Flat file on purpose (CR-031's
database question is deferred); this module is the only reader and writer.

Privacy, same stance as analytics.py — no cookies, no raw IP, no User-Agent:
  - The voter key is `analytics.hash_ip()` of the visitor's IP (truncated to
    /24 or /48, then HMAC'd).
  - Behind one NAT (a conference Wi-Fi, an office) everyone shares that key, so
    the page may also send a random device id it keeps in localStorage, created
    only when the visitor first votes. That id is HMAC'd under the same server
    secret before it touches disk, and replaces the IP key for de-duplication.
    The rate limit always applies per IP key.
  - The tier (anonymous / member / lab) is stored so the review queue can weigh
    Lab and Member signals apart from anonymous ones.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import time
from collections import deque
from datetime import datetime

import analytics
import paths

FEEDBACK_DIR = paths.REPO_ROOT / "results" / "_feedback"
FEEDBACK_FILE = FEEDBACK_DIR / "votes.jsonl"

FINDING_KINDS = ("up", "question")
VARIANT_KIND = "pick"
COMMENT_MAX = 280
# Per hashed /24 network, not per person: a conference audience behind one NAT
# (the MTS QR-code idea) shares a key, so the cap is generous. Signals only rank
# the Lab review agenda and the queue splits them by tier, so the residual risk
# of a stuffed count is a reordered agenda, not a changed finding.
RATE_LIMIT = 300           # events per IP key …
RATE_WINDOW_S = 3600       # … per hour

_DEVICE_RE = re.compile(r"^[0-9a-f]{32}$")
_TARGET_RE = re.compile(r"^(finding|variant):[a-z0-9][a-z0-9-]{0,80}$")

_lock = threading.Lock()
_recent: dict[str, deque] = {}


class FeedbackError(ValueError):
    """Bad input (unknown kind, malformed target). Routes map it to 400."""


class RateLimited(Exception):
    """Too many events from one IP key in the window. Routes map it to 429."""


def voter_key(ip_key: str, device: str | None) -> str:
    """The de-duplication key. A well-formed device id wins (keyed hash, so
    the raw id never reaches disk); otherwise the hashed IP."""
    if device and _DEVICE_RE.match(device):
        return "d:" + hmac.new(analytics._SALT, device.encode("ascii"), hashlib.sha256).hexdigest()[:16]
    return "i:" + (ip_key or "unknown")


def _load_events() -> list[dict]:
    try:
        lines = FEEDBACK_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue        # a torn last line from a crash is skipped, not fatal
    return out


def _state(events: list[dict]) -> dict[tuple[str, str, str], dict]:
    """(target, kind, voter) → latest event, for events still switched on."""
    cur: dict[tuple[str, str, str], dict] = {}
    for ev in events:
        k = (ev.get("target"), ev.get("kind"), ev.get("voter"))
        if ev.get("on"):
            cur[k] = ev
        else:
            cur.pop(k, None)
    return cur


def _check_rate(ip_key: str) -> None:
    now = time.monotonic()
    q = _recent.setdefault(ip_key or "unknown", deque())
    while q and now - q[0] > RATE_WINDOW_S:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise RateLimited()
    q.append(now)


def _append(events: list[dict]) -> None:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_FILE.open("a", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")


def _event(target: str, kind: str, voter: str, tier: str, on: bool, comment: str = "") -> dict:
    ev = {"ts": datetime.now().isoformat(timespec="seconds"), "target": target,
          "kind": kind, "voter": voter, "tier": tier, "on": on}
    if comment:
        ev["comment"] = comment
    return ev


def toggle_finding(slug: str, kind: str, *, ip_key: str, device: str | None,
                   tier: str, comment: str = "") -> dict:
    """Flip one visitor's 👍 or ❓ on a finding. A ❓ sent with a comment while
    already on keeps it on and records the new comment instead of toggling off.
    Returns {"on": bool, "counts": {...}} for the finding."""
    if kind not in FINDING_KINDS:
        raise FeedbackError(f"kind must be one of {FINDING_KINDS}")
    target = f"finding:{slug}"
    if not _TARGET_RE.match(target):
        raise FeedbackError("bad finding slug")
    comment = " ".join((comment or "").split())[:COMMENT_MAX] if kind == "question" else ""
    voter = voter_key(ip_key, device)
    with _lock:
        _check_rate(ip_key)
        cur = _state(_load_events())
        was_on = (target, kind, voter) in cur
        on = True if (comment and kind == "question") else not was_on
        _append([_event(target, kind, voter, tier, on, comment)])
        cur = _state(_load_events())
    return {"on": on, "counts": _counts_for(cur, target)}


def pick_variant(variant: str, allowed: tuple[str, ...], *, ip_key: str,
                 device: str | None, tier: str) -> dict:
    """One layout pick per visitor: choosing a variant switches off their
    previous pick; choosing the same one again withdraws it."""
    if variant not in allowed:
        raise FeedbackError(f"variant must be one of {allowed}")
    voter = voter_key(ip_key, device)
    with _lock:
        _check_rate(ip_key)
        cur = _state(_load_events())
        mine = [t for (t, k, v) in cur if k == VARIANT_KIND and v == voter]
        target = f"variant:{variant}"
        evs = [_event(t, VARIANT_KIND, voter, tier, False) for t in mine]
        if target not in mine:
            evs.append(_event(target, VARIANT_KIND, voter, tier, True))
        _append(evs)
        cur = _state(_load_events())
    return {"picked": variant if target not in mine else None,
            "counts": {a: sum(1 for (t, k, _) in cur if t == f"variant:{a}" and k == VARIANT_KIND)
                       for a in allowed}}


def _counts_for(cur: dict, target: str) -> dict:
    return {kind: sum(1 for (t, k, _) in cur if t == target and k == kind) for kind in FINDING_KINDS}


def tally() -> dict:
    """Everything the pages and the Lab review queue need, from one replay:
    {"findings": {slug: {"up": {tier: n}, "question": {tier: n}, "comments": [...]}},
     "variants": {key: {tier: n}}}. Comments are newest first and include
    only ❓ votes still switched on."""
    cur = _state(_load_events())
    findings: dict[str, dict] = {}
    variants: dict[str, dict] = {}
    for (target, kind, _), ev in cur.items():
        if not target:
            continue
        typ, _, key = target.partition(":")
        tier = ev.get("tier", "anonymous")
        if typ == "finding" and kind in FINDING_KINDS:
            f = findings.setdefault(key, {"up": {}, "question": {}, "comments": []})
            f[kind][tier] = f[kind].get(tier, 0) + 1
            if kind == "question" and ev.get("comment"):
                f["comments"].append({"ts": ev["ts"], "tier": tier, "text": ev["comment"]})
        elif typ == "variant" and kind == VARIANT_KIND:
            v = variants.setdefault(key, {})
            v[tier] = v.get(tier, 0) + 1
    for f in findings.values():
        f["comments"].sort(key=lambda c: c["ts"], reverse=True)
    return {"findings": findings, "variants": variants}
