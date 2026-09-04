"""
Lab-session reservations (CR-083) — a courtesy calendar for the box and the rig.

The immediate toggle (bin/lab-session-on|off, POST /lab-session/toggle) is
untouched: queue_control.LAB_SESSION_FLAG stays the single source of truth for
"is a session active NOW". This module adds *reservations* — a start time, an
expected duration and a short comment ("Tania — encode sweep re-run") — kept in
data/lab_reservations.json (gitignored, like members.json), and a ticker that
turns a due reservation into the active session by raising that same flag, and
lowers it again when the duration elapses.

Ownership rules, so a reservation never fights the hand controls:

- A reservation becomes active at most once. When its start time arrives it
  raises the flag if the flag is down and records that it OWNS the flag (the
  flag file's content is `reservation:<id>`). If a hand-started session is
  already up, the reservation is active by courtesy and owns nothing.
- While active, a missing flag means someone ended the session by hand: the
  reservation is finished and removed — it never re-raises.
- At its end (start + duration, extendable) the flag is lowered only if the
  reservation owns it. Hand-started sessions are never lowered by the ticker.
- Overlaps are refused with the existing reservation shown, never replaced.

Times are stored as ISO-8601 with the local UTC offset; naive inputs (the
`datetime-local` form field) are read as the server's local time (Europe/Paris
on GoS1). No import of main.py; queue_control is the only sibling dependency.
"""

import asyncio
import json
import logging
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import queue_control

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
RESERVATIONS_FILE = _REPO_ROOT / "data" / "lab_reservations.json"

MIN_DURATION_MIN = 5
MAX_DURATION_MIN = 24 * 60          # an all-nighter is ~12 h; a day is the cap
MAX_COMMENT_CHARS = 40              # CR-083 said "20-character"; its own examples run to 27
PAST_GRACE = timedelta(minutes=5)   # "starts now" typed a few minutes ago is fine
MAX_AHEAD = timedelta(days=60)
TICK_S = 15                         # ticker cadence; the UI also ticks on demand

_FLAG_PREFIX = "reservation:"


class ReservationError(ValueError):
    """Refused reservation — message is safe to show verbatim."""


class ReservationOverlap(ReservationError):
    def __init__(self, existing: dict):
        self.existing = existing
        super().__init__(
            "Overlaps an existing reservation: "
            f"{start_label(parse_start(existing['start']))} "
            f"({duration_label(existing['duration_min'])}) — "
            f"{existing.get('comment', '')}")


# --- Time helpers -----------------------------------------------------------

_TZ = None


def _local_tz():
    """The host's zone as a real ZoneInfo (Europe/Paris on GoS1) so a naive
    form time on the far side of a DST switch gets that date's offset — the
    fixed-offset tzinfo `datetime.now().astimezone()` hands back would stamp
    today's offset on it. Fallback: that fixed offset."""
    global _TZ
    if _TZ is None:
        try:
            from zoneinfo import ZoneInfo
            link = os.readlink("/etc/localtime")
            _TZ = ZoneInfo(link.split("zoneinfo/", 1)[1])
        except Exception:
            _TZ = datetime.now().astimezone().tzinfo
    return _TZ


def now_local() -> datetime:
    return datetime.now(_local_tz()).replace(microsecond=0)


def parse_start(value: str) -> datetime:
    """Accept the `datetime-local` form value (naive, minute precision) or any
    ISO-8601 string; naive → server local time. Raises ReservationError."""
    s = (value or "").strip()
    if not s:
        raise ReservationError("A start time is required.")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ReservationError(f"Unreadable start time: {s!r}.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_local_tz())
    return dt.replace(microsecond=0)


def end_of(r: dict) -> datetime:
    return parse_start(r["start"]) + timedelta(minutes=int(r["duration_min"]))


def start_label(dt: datetime, *, now: Optional[datetime] = None) -> str:
    """'today 18:00' / 'tomorrow 18:00' / 'Sun 07 Sep 18:00'."""
    now = now or now_local()
    d = dt.astimezone(_local_tz())
    if d.date() == now.date():
        return f"today {d:%H:%M}"
    if d.date() == (now + timedelta(days=1)).date():
        return f"tomorrow {d:%H:%M}"
    return f"{d:%a %d %b %H:%M}"


def duration_label(minutes: int) -> str:
    minutes = int(minutes)
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} h {m:02d}"
    if h:
        return f"{h} h"
    return f"{m} min"


def _overlaps(a_start: datetime, a_end: datetime, b: dict) -> bool:
    b_start = parse_start(b["start"])
    return a_start < end_of(b) and b_start < a_end


# --- Storage ----------------------------------------------------------------

def load() -> list[dict]:
    """Tolerant read: missing or corrupt file → []. Sorted by start."""
    try:
        raw = json.loads(RESERVATIONS_FILE.read_text())
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        log.warning("lab_reservations: unreadable %s — treating as empty",
                    RESERVATIONS_FILE, exc_info=True)
        return []
    items = raw.get("reservations", []) if isinstance(raw, dict) else raw
    good = []
    for r in items if isinstance(items, list) else []:
        try:
            parse_start(r["start"]); int(r["duration_min"]); r["id"]
        except (KeyError, TypeError, ValueError, ReservationError):
            continue
        good.append(r)
    good.sort(key=lambda r: parse_start(r["start"]))
    return good


def _save(items: list[dict]) -> None:
    RESERVATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = RESERVATIONS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"reservations": items}, indent=2))
    os.replace(tmp, RESERVATIONS_FILE)


# --- Flag ownership ---------------------------------------------------------

def flag_owner() -> Optional[str]:
    """Reservation id written into the flag file by this module, else None
    (flag down, or raised by hand — touch leaves it empty)."""
    try:
        text = queue_control.LAB_SESSION_FLAG.read_text().strip()
    except OSError:
        return None
    if not text.startswith(_FLAG_PREFIX):
        return None
    return text[len(_FLAG_PREFIX):] or None


def _raise_flag(rid: str) -> None:
    queue_control.LAB_SESSION_FLAG.write_text(f"{_FLAG_PREFIX}{rid}\n")


def _lower_flag_if_owned(rid: str) -> bool:
    if flag_owner() == rid:
        queue_control.LAB_SESSION_FLAG.unlink(missing_ok=True)
        return True
    return False


# --- Mutations --------------------------------------------------------------

def add(start: str | datetime, duration_min: int | str, comment: str,
        *, now: Optional[datetime] = None) -> dict:
    now = now or now_local()
    start_dt = start if isinstance(start, datetime) else parse_start(start)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=_local_tz())
    try:
        minutes = int(duration_min)
    except (TypeError, ValueError):
        raise ReservationError("Duration must be a whole number of minutes.")
    if not MIN_DURATION_MIN <= minutes <= MAX_DURATION_MIN:
        raise ReservationError(
            f"Duration must be between {MIN_DURATION_MIN} min and "
            f"{MAX_DURATION_MIN // 60} h.")
    text = " ".join((comment or "").split())
    if not text:
        raise ReservationError("A short comment is required (who, what).")
    if len(text) > MAX_COMMENT_CHARS:
        raise ReservationError(
            f"Comment is {len(text)} characters — keep it to {MAX_COMMENT_CHARS}.")
    if start_dt < now - PAST_GRACE:
        raise ReservationError("Start time is in the past.")
    if start_dt > now + MAX_AHEAD:
        raise ReservationError("Start time is more than 60 days ahead.")
    end_dt = start_dt + timedelta(minutes=minutes)
    items = load()
    for other in items:
        if _overlaps(start_dt, end_dt, other):
            raise ReservationOverlap(other)
    rec = {
        "id": "r" + secrets.token_hex(4),
        "start": start_dt.isoformat(),
        "duration_min": minutes,
        "comment": text,
        "created": now.isoformat(),
        "started": None,
        "owns_flag": False,
    }
    items.append(rec)
    items.sort(key=lambda r: parse_start(r["start"]))
    _save(items)
    return rec


def remove(rid: str) -> bool:
    """Delete a reservation. Deleting the ACTIVE one that owns the flag ends
    its session (the flag comes down) — that is the ✕ on a running slot."""
    items = load()
    keep = [r for r in items if r["id"] != rid]
    if len(keep) == len(items):
        return False
    _lower_flag_if_owned(rid)
    _save(keep)
    return True


def extend(rid: str, minutes: int | str, *, now: Optional[datetime] = None) -> dict:
    """Push a reservation's end back by `minutes` (active or upcoming);
    refused if the new end would run into the next reservation."""
    now = now or now_local()
    try:
        extra = int(minutes)
    except (TypeError, ValueError):
        raise ReservationError("Extension must be a whole number of minutes.")
    if extra <= 0:
        raise ReservationError("Extension must be positive.")
    items = load()
    for r in items:
        if r["id"] == rid:
            new_total = int(r["duration_min"]) + extra
            if new_total > MAX_DURATION_MIN:
                raise ReservationError(
                    f"Would exceed the {MAX_DURATION_MIN // 60} h cap.")
            start_dt = parse_start(r["start"])
            new_end = start_dt + timedelta(minutes=new_total)
            for other in items:
                if other is not r and _overlaps(start_dt, new_end, other):
                    raise ReservationOverlap(other)
            r["duration_min"] = new_total
            _save(items)
            return r
    raise ReservationError("No such reservation.")


# --- The state machine ------------------------------------------------------

def tick(now: Optional[datetime] = None) -> dict:
    """Advance reservations against the clock and the flag file. Idempotent;
    cheap (one small JSON read, a write only on change). Returns what it did:
    {"raised": [ids], "lowered": [ids], "finished": [ids]}."""
    now = now or now_local()
    out = {"raised": [], "lowered": [], "finished": []}
    items = load()
    keep, changed = [], False
    flag_up = queue_control.LAB_SESSION_FLAG.exists()
    for r in items:
        rid = r["id"]
        start_dt = parse_start(r["start"])
        end_dt = start_dt + timedelta(minutes=int(r["duration_min"]))
        if r.get("started"):
            if now >= end_dt:
                if r.get("owns_flag") and _lower_flag_if_owned(rid):
                    out["lowered"].append(rid)
                    flag_up = False
                out["finished"].append(rid)
                changed = True
                continue
            if not flag_up:
                # Ended by hand (toggle / bin/lab-session-off): finished, no re-raise.
                out["finished"].append(rid)
                changed = True
                continue
            keep.append(r)
            continue
        if now >= end_dt:
            # Never activated (service was down for its whole slot) — drop.
            out["finished"].append(rid)
            changed = True
            continue
        if start_dt <= now:
            r["started"] = now.isoformat()
            if flag_up:
                r["owns_flag"] = False          # courtesy: a hand session is on
            else:
                _raise_flag(rid)
                r["owns_flag"] = True
                flag_up = True
                out["raised"].append(rid)
            changed = True
        keep.append(r)
    if changed:
        _save(keep)
        if out["raised"] or out["lowered"] or out["finished"]:
            log.info("lab_reservations tick: raised=%s lowered=%s finished=%s",
                     out["raised"], out["lowered"], out["finished"])
    return out


async def ticker(interval_s: float = TICK_S):
    """Background loop started from main.py's startup. Fail-soft: a bad tick
    is logged and the loop carries on."""
    while True:
        try:
            tick()
        except Exception:
            log.exception("lab_reservations ticker failed")
        await asyncio.sleep(interval_s)


# --- Read side --------------------------------------------------------------

def active(now: Optional[datetime] = None) -> Optional[dict]:
    """The reservation that is active right now (started, not past its end),
    or None. Read-only — call tick() first when freshness matters."""
    now = now or now_local()
    for r in load():
        if r.get("started") and now < end_of(r):
            return r
    return None


def active_summary(now: Optional[datetime] = None) -> Optional[dict]:
    """The active reservation as the UI describes it (end_label, comment,
    owns_flag, …) or None — what the site banner and /decode notice show."""
    now = now or now_local()
    r = active(now)
    return _describe(r, now) if r else None


def _describe(r: dict, now: datetime) -> dict:
    start_dt = parse_start(r["start"])
    end_dt = end_of(r)
    same_day = end_dt.astimezone(_local_tz()).date() == now.date()
    return {
        "id": r["id"],
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "duration_min": int(r["duration_min"]),
        "comment": r.get("comment", ""),
        "started": r.get("started"),
        "owns_flag": bool(r.get("owns_flag")),
        "start_label": start_label(start_dt, now=now),
        "end_label": (f"{end_dt.astimezone(_local_tz()):%H:%M}" if same_day
                      else start_label(end_dt, now=now)),
        "duration_label": duration_label(r["duration_min"]),
        "starts_in_s": max(0, int((start_dt - now).total_seconds())),
        "remaining_s": max(0, int((end_dt - now).total_seconds())),
    }


def snapshot(now: Optional[datetime] = None) -> dict:
    """What the UI shows: the active reservation (if any), the upcoming list,
    and whether the flag is up at all (a hand-started session shows as active
    with no reservation)."""
    now = now or now_local()
    items = load()
    act, upcoming = None, []
    for r in items:
        d = _describe(r, now)
        if r.get("started") and now < end_of(r):
            act = d
        elif not r.get("started"):
            upcoming.append(d)
    return {
        "now": now.isoformat(),
        "flag_up": queue_control.LAB_SESSION_FLAG.exists(),
        "flag_owner": flag_owner(),
        "active": act,
        "upcoming": upcoming,
        "limits": {"min_duration_min": MIN_DURATION_MIN,
                   "max_duration_min": MAX_DURATION_MIN,
                   "max_comment_chars": MAX_COMMENT_CHARS},
    }
