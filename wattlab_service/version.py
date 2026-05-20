"""OWL version + build provenance.

Resolved once at import — the build can't change while the process runs, and a
restart picks up new code. Resolution order:
  1. a committed/generated version.json (containers without .git — CR-031),
  2. live git (short SHA, commit date, dirty flag),
  3. a "dev" fallback.
All fail-soft; never blocks startup.

Important for OWL: the service runs straight from the working tree, so
uncommitted edits go live on restart. The `dirty` flag (rendered as `-local`)
keeps the stamp honest when that's the case.
"""
import json
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_VERSION_FILE = _ROOT / "VERSION"
_VERSION_JSON = _ROOT / "version.json"


def _semver() -> str:
    try:
        return _VERSION_FILE.read_text().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _git(*args) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(_ROOT), *args],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
    except Exception:
        return ""


def _resolve() -> dict:
    # 1. generated version.json (container-friendly; no .git needed)
    try:
        data = json.loads(_VERSION_JSON.read_text())
        if data.get("sha"):
            data.setdefault("version", _semver())
            return data
    except (OSError, json.JSONDecodeError):
        pass
    # 2. live git
    sha = _git("rev-parse", "--short", "HEAD")
    if sha:
        return {
            "version": _semver(),
            "sha": sha,
            "dirty": bool(_git("status", "--porcelain")),
            "built_at": _git("show", "-s", "--format=%cs", "HEAD") or None,
        }
    # 3. fallback
    return {"version": _semver(), "sha": "unknown", "dirty": False, "built_at": None}


_INFO = _resolve()


def version_dict() -> dict:
    """Stable dict for stamping result files (CR provenance)."""
    return dict(_INFO)


def version_string() -> str:
    """One-line human stamp, e.g. 'OWL v0.4.0 · a1b2c3d · 2026-05-21' (+ ' -local'
    when the running tree has uncommitted changes)."""
    v = _INFO
    parts = [f"OWL v{v.get('version', '0.0.0')}", v.get("sha") or "unknown"]
    if v.get("built_at"):
        parts.append(v["built_at"])
    s = " · ".join(parts)
    if v.get("dirty"):
        s += " -local"
    return s
