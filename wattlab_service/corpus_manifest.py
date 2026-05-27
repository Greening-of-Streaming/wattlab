"""CR-051 — RAG corpus manifest + audit log.

Tracks the provenance of every PDF in `corpus/papers/`:

  origin:    "Lab" | "Member"
  added_by:  "Lab" or a Member email
  added_at:  ISO-8601 UTC timestamp
  size_bytes:int
  title:     optional, from PDF metadata or user-provided

Storage:
  corpus/manifest.json   — current state, single source of truth
  corpus/audit.log       — append-only event log (one JSON line per upload/delete)

`/rag/corpus-list` reads the manifest to render origin + age tags + per-row
"can I delete this?" flags. Upload/delete endpoints write to it.

Self-healing: `ensure_entry(filename)` is called on every read of an existing
PDF that has no manifest row (e.g. someone drops a PDF into corpus/papers/
out-of-band). These get stamped origin="Lab", added_by="Lab", added_at=mtime.
The manifest is never the gating reality — the file system is — but for the
files that DO exist it answers the audit questions.
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import settings as cfg

MANIFEST_FILENAME = "manifest.json"
AUDIT_FILENAME    = "audit.log"


def _corpus_root() -> Path:
    """Parent of corpus_path so manifest + audit sit alongside `papers/`."""
    return Path(cfg.load()["rag_corpus_path"]).parent


def _manifest_path() -> Path:
    return _corpus_root() / MANIFEST_FILENAME


def _audit_path() -> Path:
    return _corpus_root() / AUDIT_FILENAME


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _papers_dir() -> Path:
    return Path(cfg.load()["rag_corpus_path"])


# --- Manifest ---------------------------------------------------------------

def load_manifest() -> dict:
    """Returns {filename: meta_dict}. Empty dict if manifest missing."""
    p = _manifest_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def save_manifest(data: dict) -> None:
    p = _manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True))


def ensure_entry(filename: str) -> dict:
    """Make sure the manifest has an entry for `filename`. If it's already
    listed, return it. If the file exists on disk but has no entry yet
    (someone dropped a PDF in out-of-band), stamp it as origin="Lab" using
    the file's mtime as added_at. If the file doesn't exist, return {} —
    callers should treat that as "unknown".
    """
    m = load_manifest()
    if filename in m:
        return m[filename]
    path = _papers_dir() / filename
    if not path.exists():
        return {}
    try:
        st = path.stat()
        added_at = datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        size = st.st_size
    except Exception:
        added_at = _utcnow_iso()
        size = 0
    entry = {
        "origin":      "Lab",
        "added_by":    "Lab",
        "added_at":    added_at,
        "size_bytes":  size,
        "title":       None,
    }
    m[filename] = entry
    save_manifest(m)
    return entry


def record_upload(filename: str, added_by: str, origin: str = "Member",
                   size_bytes: int = 0, title: str = None) -> dict:
    """Adds an entry and appends an audit event."""
    m = load_manifest()
    entry = {
        "origin":     origin,
        "added_by":   added_by,
        "added_at":   _utcnow_iso(),
        "size_bytes": size_bytes,
        "title":      title,
    }
    m[filename] = entry
    save_manifest(m)
    _append_audit({"ts": entry["added_at"], "event": "upload",
                    "actor": added_by, "tier": origin,
                    "filename": filename, "size_bytes": size_bytes})
    return entry


def record_delete(filename: str, actor: str, tier: str) -> None:
    """Removes the entry and appends an audit event."""
    m = load_manifest()
    if filename in m:
        del m[filename]
        save_manifest(m)
    _append_audit({"ts": _utcnow_iso(), "event": "delete",
                    "actor": actor, "tier": tier,
                    "filename": filename})


def _append_audit(event: dict) -> None:
    p = _audit_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(event) + "\n")


def read_audit(limit: int = 200) -> list:
    """Tail the audit log. Most recent last (file order)."""
    p = _audit_path()
    if not p.exists():
        return []
    events = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    return events[-limit:]


# --- Ownership / authorisation helpers --------------------------------------

def can_delete(filename: str, visitor_tier_name: str, visitor_email: str | None) -> bool:
    """Lab can delete any; Member can delete entries they uploaded.
    Anonymous never. Self-heals missing entries first (treats them as Lab).
    """
    if visitor_tier_name == "Lab":
        return True
    if visitor_tier_name != "Member" or not visitor_email:
        return False
    entry = ensure_entry(filename)
    return entry.get("added_by", "").lower() == visitor_email.lower()


def member_usage(visitor_email: str) -> dict:
    """{file_count, total_bytes} for a Member's existing uploads.
    Counted against rag_member_doc_count_cap / rag_member_total_mb_cap.
    """
    if not visitor_email:
        return {"file_count": 0, "total_bytes": 0}
    m = load_manifest()
    target = visitor_email.lower()
    count = 0
    total = 0
    for entry in m.values():
        if (entry.get("added_by") or "").lower() == target:
            count += 1
            total += int(entry.get("size_bytes") or 0)
    return {"file_count": count, "total_bytes": total}


# --- Filename sanitisation --------------------------------------------------

_SAFE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def sanitise_filename(name: str) -> str:
    """Strip path components, restrict to [A-Za-z0-9._-]. Ensures .pdf ext.
    Used on every uploaded filename so the upload endpoint can never write
    outside corpus/papers/ even if the client lies about Content-Disposition.
    """
    base = os.path.basename(name or "")
    safe = "".join(c if c in _SAFE_CHARS else "_" for c in base)
    safe = safe.strip("._")  # don't allow hidden / extension-only files
    if not safe:
        safe = f"upload_{int(time.time())}.pdf"
    if not safe.lower().endswith(".pdf"):
        safe = safe + ".pdf"
    return safe


def unique_filename(name: str) -> str:
    """If `name` already exists in corpus/papers/, suffix `-2`, `-3` etc.
    until the path is free. Prevents the upload endpoint from silently
    overwriting an existing doc.
    """
    papers = _papers_dir()
    target = papers / name
    if not target.exists():
        return name
    stem = target.stem
    ext  = target.suffix
    i = 2
    while True:
        candidate = f"{stem}-{i}{ext}"
        if not (papers / candidate).exists():
            return candidate
        i += 1


# --- Migration --------------------------------------------------------------

def migrate_existing_corpus() -> int:
    """One-shot: ensure every PDF in corpus/papers/ has a Lab-origin entry.
    Returns the count of new entries stamped. Safe to re-run (idempotent).
    """
    papers = _papers_dir()
    if not papers.exists():
        return 0
    m = load_manifest()
    added = 0
    for pdf_path in papers.rglob("*.pdf"):
        try:
            rel = str(pdf_path.relative_to(papers))
        except ValueError:
            rel = pdf_path.name
        if rel in m:
            continue
        try:
            st = pdf_path.stat()
            added_at = datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            size = st.st_size
        except Exception:
            added_at = _utcnow_iso()
            size = 0
        m[rel] = {
            "origin":     "Lab",
            "added_by":   "Lab",
            "added_at":   added_at,
            "size_bytes": size,
            "title":      None,
        }
        added += 1
    if added > 0:
        save_manifest(m)
    return added
