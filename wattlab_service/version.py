"""OWL version + build provenance.

Resolved once at import — the build can't change while the process runs, and a
restart picks up new code. Resolution order:
  1. a committed/generated version.json (containers without .git — CR-031),
  2. live git — the version AUTO-DERIVES from `git describe --tags` so it
     advances on its own: exactly on a tag → "1.0.0"; N commits past it →
     "1.0.0+N". You bump the base by *tagging* (annotated), never by editing a
     file. SHA, commit date, and the dirty flag come from git too.
  3. the VERSION file as a fallback base (shallow clone / no tags reachable).
All fail-soft; never blocks startup.

Important for OWL: the service runs straight from the working tree, so
uncommitted edits go live on restart. The `dirty` flag (rendered as `-local`)
keeps the stamp honest — but it deliberately IGNORES settings.json, which is
intentionally-always-modified live runtime state (see the settings-json-is-live
-state rule); otherwise every build would falsely read `-local`.
"""
import json
import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_VERSION_FILE = _ROOT / "VERSION"
_VERSION_JSON = _ROOT / "version.json"

# Paths whose modification does NOT make the build "dirty" — live state that is
# git-tracked but never committed with code (settings-json-is-live-state).
_IGNORE_DIRTY = {"settings.json"}

# git describe --long form: "<tag>-<ahead>-g<sha>", e.g. "v1.0.0-127-g42b4198".
_DESCRIBE_RE = re.compile(r"^(?P<tag>.+)-(?P<ahead>\d+)-g[0-9a-f]+$")


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


def _describe_version() -> str:
    """Derive the semver from the nearest tag via `git describe --tags --long`.
    'v1.0.0-0-g…' → '1.0.0' (on the tag); 'v1.0.0-5-g…' → '1.0.0+5'. Empty on
    no-tag / no-git so the caller falls back to the VERSION file."""
    out = _git("describe", "--tags", "--long", "--always")
    m = _DESCRIBE_RE.match(out)
    if not m:
        return ""
    base = m.group("tag").lstrip("v")
    ahead = int(m.group("ahead"))
    return base if ahead == 0 else f"{base}+{ahead}"


def _dirty() -> bool:
    """Uncommitted *code* in the working tree — ignoring live-state files that
    are tracked but never committed with features (settings.json)."""
    for line in _git("status", "--porcelain").splitlines():
        path = line[3:].strip()          # strip the 'XY ' status prefix
        if " -> " in path:               # rename: take the destination
            path = path.split(" -> ", 1)[1]
        if path and path not in _IGNORE_DIRTY:
            return True
    return False


def _resolve() -> dict:
    # 1. generated version.json (container-friendly; no .git needed)
    try:
        data = json.loads(_VERSION_JSON.read_text())
        if data.get("sha"):
            data.setdefault("version", _semver())
            return data
    except (OSError, json.JSONDecodeError):
        pass
    # 2. live git — version auto-derives from the nearest tag
    sha = _git("rev-parse", "--short", "HEAD")
    if sha:
        return {
            "version": _describe_version() or _semver(),
            "sha": sha,
            "dirty": _dirty(),
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
