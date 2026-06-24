"""
uploads.py — one shared file-upload store + lifecycle for every OWL page.

Factored out of the per-page ad-hoc upload handling (/video deleted immediately
off /tmp; /enhance-run had a 2-way keep/ephemeral prefix on the pixop dir;
/prepare-rem had none). All pages now go through this module.

RETENTION (the uploader's choice, default = evict):
  - "evict"  remove WHEN SHORT OF SPACE — kept until the disk is under pressure,
             then the oldest evict-class uploads are deleted first (backstop TTL too).
  - "proc"   remove IMMEDIATELY after the consuming job finishes.
  - "keep"   keep on OWL — never auto-removed.

Retention is encoded in the FILENAME PREFIX (`<ret>_<feature>_<uuid8>_<stem><ext>`),
not in a directory — it is a per-file property, it survives restarts with no
side-state, and "short of space" eviction can weigh every upload dir together.
The physical directory still differs per feature where it must (/enhance-run
uploads MUST live in the pixop docker-mount input dir), so callers pass `dest_dir`;
the naming / eviction / cleanup / sweep LOGIC is shared.

Legacy `/enhance-run` names (`upload_keep_` / `upload_`) are still recognised, so
files already on disk keep being swept correctly.

No FastAPI imports — pure storage logic, unit-testable. Routes keep their own
ext/size validation + error wording; this module owns naming + lifecycle.
"""
from __future__ import annotations

import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Iterable, Optional

import settings as cfg

RETENTIONS = ("evict", "proc", "keep")
DEFAULT_RETENTION = "evict"
RETENTION_LABELS = {
    "evict": "Remove when short of space",
    "proc": "Remove immediately after processing",
    "keep": "Keep on OWL",
}
RETENTION_HELP = {
    "evict": "Kept until the disk is low, then the oldest are removed first.",
    "proc": "Deleted as soon as this run finishes.",
    "keep": "Never removed automatically.",
}

# Legacy /enhance-run prefixes → retention class.
_LEGACY = {"upload_keep_": "keep", "upload_": "evict"}

# Upload dirs that "short of space" eviction may scan. shared_dir() is always
# included; features with their own dir (enhance pixop input, rem _uploads)
# call register_dir() at import.
_REGISTERED: set[Path] = set()


# ---------------------------------------------------------------------------
# Directory registry
# ---------------------------------------------------------------------------
def shared_dir() -> Path:
    """The shared upload dir for features with no special storage need
    (/video, /prepare-rem). On the 4 TB data disk, never /tmp."""
    d = Path(cfg.load().get("uploads_dir", "/srv/data/owl/uploads"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def register_dir(path) -> None:
    """Register a feature-specific upload dir (e.g. the pixop input dir) so
    global eviction can consider its evict-class files too."""
    _REGISTERED.add(Path(path))


def _all_dirs() -> set[Path]:
    dirs = set(_REGISTERED)
    try:
        dirs.add(shared_dir())
    except Exception:
        pass
    return {d for d in dirs if d.exists()}


# ---------------------------------------------------------------------------
# Naming + retention parsing
# ---------------------------------------------------------------------------
def make_name(orig_filename: str, retention: str, feature: str) -> str:
    """`<ret>_<feature>_<uuid8>_<safe_stem><ext>`. Falls back to the default
    retention for an unknown value."""
    if retention not in RETENTIONS:
        retention = DEFAULT_RETENTION
    stem = Path(orig_filename or "clip").stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]", "_", stem)[:48] or "clip"
    ext = Path(orig_filename or "").suffix.lower()
    feat = re.sub(r"[^a-z0-9]", "", feature.lower())[:12] or "x"
    return f"{retention}_{feat}_{uuid.uuid4().hex[:8]}_{safe_stem}{ext}"


def retention_of(name: str) -> Optional[str]:
    """Retention class of an upload filename, or None if it isn't an OWL upload
    (e.g. a curated staged clip). Recognises legacy enhance names."""
    for ret in RETENTIONS:
        if name.startswith(ret + "_"):
            return ret
    for prefix, ret in _LEGACY.items():        # legacy: longest first via dict order
        if name.startswith(prefix):
            return ret
    return None


def is_owl_upload(name: str) -> bool:
    return retention_of(name) is not None


def is_immediate(name: str) -> bool:
    return retention_of(name) == "proc"


def is_kept(name: str) -> bool:
    return retention_of(name) == "keep"


# ---------------------------------------------------------------------------
# Disk space + eviction ("remove when short of space")
# ---------------------------------------------------------------------------
def free_gb(path) -> float:
    """Free GB on the filesystem holding `path` (or its nearest existing parent)."""
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(p).free / 1e9
    except Exception:
        return float("inf")


def evict_until_free(target_dir, min_gb: float) -> list[str]:
    """Delete oldest evict-class uploads (across ALL registered dirs) until the
    filesystem holding `target_dir` has >= min_gb free. Never touches keep/proc
    files or non-uploads. Returns the names deleted."""
    deleted: list[str] = []
    if min_gb is None or free_gb(target_dir) >= min_gb:
        return deleted
    cands: list[Path] = []
    for d in _all_dirs() | {Path(target_dir)}:
        if not d.exists():
            continue
        for p in d.iterdir():
            if p.is_file() and retention_of(p.name) == "evict":
                cands.append(p)
    cands.sort(key=lambda p: p.stat().st_mtime)   # oldest first
    for p in cands:
        if free_gb(target_dir) >= min_gb:
            break
        try:
            p.unlink(missing_ok=True)
            deleted.append(p.name)
        except Exception:
            pass
    return deleted


# ---------------------------------------------------------------------------
# Save + resolve
# ---------------------------------------------------------------------------
def save(blob: bytes, orig_filename: str, *, retention: str, feature: str,
         dest_dir, min_free_gb: Optional[float] = None) -> dict:
    """Write `blob` into `dest_dir` with a retention-prefixed name, evicting
    oldest evict-class uploads first if the disk is short. Returns
    {name, path, size_mb, retention}. Ext/size validation stays in the route
    (per-feature wording); this owns naming + space + the write."""
    if retention not in RETENTIONS:
        retention = DEFAULT_RETENTION
    if min_free_gb is None:
        min_free_gb = float(cfg.load().get("uploads_min_free_gb", 20))
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    evicted = evict_until_free(dest_dir, min_free_gb)
    name = make_name(orig_filename, retention, feature)
    path = dest_dir / name
    path.write_bytes(blob)
    return {"name": name, "path": path,
            "size_mb": round(len(blob) / 1024 / 1024, 2),
            "retention": retention, "evicted": evicted}


def resolve(dest_dir, name: str) -> Optional[Path]:
    """Resolve a basename to a path inside dest_dir (no traversal), or None."""
    if Path(name).name != name:
        return None
    p = Path(dest_dir) / name
    return p if p.is_file() else None


# ---------------------------------------------------------------------------
# Post-job cleanup + periodic sweep
# ---------------------------------------------------------------------------
def cleanup_after_job(dest_dir, name: str) -> None:
    """Called when the consuming job ends. `proc` → delete now; `evict`/`keep`
    → touch mtime so eviction recency / the TTL backstop counts from the run
    (keeps the result-card source preview working in-session). Non-uploads
    (curated staged clips) are never touched. Fail-soft."""
    ret = retention_of(name)
    if ret is None:
        return
    try:
        path = Path(dest_dir) / Path(name).name
        if not path.is_file():
            return
        if ret == "proc":
            path.unlink(missing_ok=True)
        else:
            path.touch()
    except Exception:
        pass


def sweep(dest_dir, *, ttl_h: Optional[float] = None,
          extra_prefixes: Iterable[str] = ()) -> list[str]:
    """Backstop sweep: delete evict-class uploads (incl. legacy `upload_`
    non-keep) older than `ttl_h`, plus any `extra_prefixes` files older than
    `ttl_h` (enhance passes `normalized_`). NEVER touches keep/proc. Returns
    swept names. Fail-soft."""
    if ttl_h is None:
        ttl_h = float(cfg.load().get("uploads_evict_ttl_h", 72))
    dest_dir = Path(dest_dir)
    cutoff = time.time() - float(ttl_h) * 3600
    extra = tuple(extra_prefixes)
    swept: list[str] = []
    try:
        for p in dest_dir.iterdir():
            if not p.is_file() or p.stat().st_mtime >= cutoff:
                continue
            if retention_of(p.name) == "evict" or any(p.name.startswith(x) for x in extra):
                p.unlink(missing_ok=True)
                swept.append(p.name)
    except Exception:
        pass
    return swept
