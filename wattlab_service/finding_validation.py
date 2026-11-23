"""
finding_validation.py — CR-086 — who checked a finding against its data, and when.

The second rung of the review ladder (machine-draft → lab-checked): a lab member
compares a finding with its stored results and records that here. It never makes
a finding group-validated; only a WattLab meeting does that.

Lab tier is decided by network address, so the page cannot know the person: the
name comes from the signed-in member email or is typed in. It is an attestation
among colleagues on the lab network, not authentication.

Storage is an append-only JSONL log (`results/_feedback/lab_validations.jsonl`),
one event per validate or withdraw, so a withdrawn validation stays on record.
Names are shown only on the lab network.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime

import paths

LOG_DIR = paths.REPO_ROOT / "results" / "_feedback"
LOG_FILE = LOG_DIR / "lab_validations.jsonl"
NAME_MAX = 80
UNNAMED = "unnamed lab user"

_lock = threading.Lock()


class ValidationError(ValueError):
    """Bad input. Routes map it to 400."""


def _events() -> list[dict]:
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue        # a torn last line from a crash is skipped, not fatal
    return out


def _replay(events: list[dict]) -> dict[str, dict]:
    cur: dict[str, dict] = {}
    for ev in events:
        slug = ev.get("slug")
        if ev.get("action") == "validate":
            cur[slug] = {"by": ev.get("by", UNNAMED), "at": ev.get("at", "")}
        elif ev.get("action") == "withdraw":
            cur.pop(slug, None)
    return cur


def current() -> dict[str, dict]:
    """slug → {"by", "at"} for every validation still standing."""
    return _replay(_events())


def _clean(name: str) -> str:
    return " ".join((name or "").split())[:NAME_MAX]


def _append(slug: str, action: str, by: str) -> dict:
    ev = {"at": datetime.now().astimezone().isoformat(timespec="seconds"),
          "slug": slug, "action": action, "by": by}
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def validate(slug: str, by: str) -> dict:
    """Record a validation. A finding already validated keeps its first record."""
    by = _clean(by)
    if not by:
        raise ValidationError("Please enter your name.")
    with _lock:
        existing = current().get(slug)
        if existing:
            return existing
        ev = _append(slug, "validate", by)
    return {"by": ev["by"], "at": ev["at"]}


def withdraw(slug: str, by: str) -> None:
    with _lock:
        if slug in current():
            _append(slug, "withdraw", _clean(by) or UNNAMED)
