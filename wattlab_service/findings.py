"""
findings.py — CR-054 — Findings catalog loader and validator.

Findings are editorial markdown files at `docs/findings/<slug>.md` with YAML
frontmatter. Each finding points at one or more stored result_ids; rendered
pages embed the source measurement(s) via the existing live-run renderers.

See `CHANGE_REQUESTS.md` CR-054 for the schema contract and the
maintainability invariants. Summary of the contract this module enforces:
  - one loader (this file)
  - validate-on-load with clear errors
  - source_result_ids must exist on disk (or load raises FindingError)
  - findings are editorial markdown, not code (no Python change per finding)
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT     = Path(__file__).resolve().parent.parent
_FINDINGS_DIR  = _REPO_ROOT / "docs" / "findings"
_RESULTS_DIR   = _REPO_ROOT / "results"

_VALID_CONFIDENCE = {"green", "yellow", "red"}
_REQUIRED_FIELDS  = {
    "slug", "version", "first_measured", "last_refined",
    "headline", "claim_short", "confidence", "scope",
    "methodology_ref", "source_result_ids",
}
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")


class FindingError(Exception):
    """Malformed finding file, or references a missing result."""


@dataclass
class Finding:
    slug: str
    version: int
    first_measured: str
    last_refined: str
    headline: str
    claim_short: str
    confidence: str             # green | yellow | red
    scope: str
    methodology_ref: str
    source_result_ids: list[str]
    related_findings: list[str] = field(default_factory=list)
    supersedes: str | None = None
    tags: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    body_md: str = ""
    source_path: str = ""       # diagnostic only


# Memoised by file mtime so editorial edits show up without a restart.
_CACHE: dict[str, tuple[float, Finding]] = {}


def load(slug: str) -> Finding | None:
    """Load a finding by slug. Returns None if missing; raises FindingError
    if the file exists but is malformed or refers to a missing result."""
    if not _SLUG_RE.match(slug):
        return None
    path = _FINDINGS_DIR / f"{slug}.md"
    if not path.exists():
        return None

    mtime = path.stat().st_mtime
    cached = _CACHE.get(slug)
    if cached and cached[0] == mtime:
        return cached[1]

    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text, path)
    _validate(meta, path)

    f = Finding(
        slug              = str(meta["slug"]),
        version           = int(meta["version"]),
        first_measured    = _str_date(meta["first_measured"]),
        last_refined      = _str_date(meta["last_refined"]),
        headline          = str(meta["headline"]),
        claim_short       = str(meta["claim_short"]),
        confidence        = str(meta["confidence"]),
        scope             = str(meta["scope"]),
        methodology_ref   = str(meta["methodology_ref"]),
        source_result_ids = [str(x) for x in meta["source_result_ids"]],
        related_findings  = [str(x) for x in (meta.get("related_findings") or [])],
        supersedes        = (str(meta["supersedes"]) if meta.get("supersedes") else None),
        tags              = [str(x) for x in (meta.get("tags") or [])],
        caveats           = [str(x) for x in (meta.get("caveats") or [])],
        body_md           = body.strip(),
        source_path       = str(path),
    )
    if f.slug != slug:
        raise FindingError(
            f"{path.name}: frontmatter slug={f.slug!r} disagrees with filename {slug!r}"
        )

    _CACHE[slug] = (mtime, f)
    return f


def list_all() -> list[Finding]:
    """Every valid finding under docs/findings/. Malformed files are
    skipped silently; test_findings_references.py catches them in CI."""
    if not _FINDINGS_DIR.exists():
        return []
    out: list[Finding] = []
    for p in sorted(_FINDINGS_DIR.glob("*.md")):
        try:
            f = load(p.stem)
            if f is not None:
                out.append(f)
        except FindingError:
            continue
    return out


def resolve_result_path(result_id: str) -> Path | None:
    """Return the actual file path for a stored `<type>/<token>` id, or None.
    Token can be a job_id or `<date>_<job_id>` — we glob on it."""
    if "/" not in result_id:
        return None
    type_, token = result_id.split("/", 1)
    type_dir = _RESULTS_DIR / type_
    if not type_dir.exists():
        return None
    matches = sorted(type_dir.glob(f"*{token}*.json"))
    return matches[0] if matches else None


def result_download_url(result_id: str) -> str:
    """Map a `<type>/<token>` source_result_id to the existing OWL endpoint
    `/results/<type>/<job_id>/download.json`. The endpoint accepts the bare
    job_id (last underscore-separated piece of the filename)."""
    type_, token = result_id.split("/", 1)
    # `token` is usually just `<job_id>`; if a date prefix is present (legacy
    # IDs), strip it. The download endpoint accepts the bare job_id.
    job_id = token.split("_")[-1]
    return f"/results/{type_}/{job_id}/download.json"


# --- private helpers -------------------------------------------------------

def _split_frontmatter(text: str, path: Path) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        raise FindingError(f"{path.name}: missing YAML frontmatter (expected '---' fences)")
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        raise FindingError(f"{path.name}: frontmatter is not a mapping (got {type(meta).__name__})")
    return meta, m.group(2)


def _validate(meta: dict, path: Path) -> None:
    missing = _REQUIRED_FIELDS - meta.keys()
    if missing:
        raise FindingError(f"{path.name}: missing required fields {sorted(missing)}")
    if meta["confidence"] not in _VALID_CONFIDENCE:
        raise FindingError(
            f"{path.name}: confidence={meta['confidence']!r} not in {sorted(_VALID_CONFIDENCE)}"
        )
    if not isinstance(meta["source_result_ids"], list) or not meta["source_result_ids"]:
        raise FindingError(f"{path.name}: source_result_ids must be a non-empty list")
    for k in ("first_measured", "last_refined"):
        v = meta[k]
        ok = (isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", v)) or hasattr(v, "isoformat")
        if not ok:
            raise FindingError(f"{path.name}: {k}={v!r} not a valid YYYY-MM-DD")
    for rid in meta["source_result_ids"]:
        if resolve_result_path(str(rid)) is None:
            raise FindingError(
                f"{path.name}: source_result_id {rid!r} resolves to no file under results/"
            )


def _str_date(v: Any) -> str:
    """YAML auto-parses bare dates as datetime.date; normalise to YYYY-MM-DD."""
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    return str(v)[:10]


# --- minimal markdown → HTML ----------------------------------------------
# Intentionally tiny — CR-054 invariant 8 says "no new build steps / template
# engine". Findings are dense lab publications, not Medium articles. Supports:
#   - paragraphs (blank-line separated)
#   - # H2 and ## H3 headings
#   - - bullet lists
#   - **bold**, *italic*, `inline code`, [text](url)
# Everything else is HTML-escaped and passes through.

_RE_INLINE_CODE = re.compile(r"`([^`]+)`")
_RE_LINK        = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+|/[^\s)]+|docs/[^\s)]+)\)")
_RE_BOLD        = re.compile(r"\*\*([^*]+)\*\*")
_RE_ITALIC      = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")


def md_to_html(text: str) -> str:
    if not text:
        return ""
    lines = text.split("\n")
    out: list[str] = []
    para: list[str] = []
    in_list = False

    def flush_para() -> None:
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for ln in lines:
        s = ln.rstrip()
        if not s:
            flush_para()
            close_list()
            continue
        if s.startswith("# "):
            flush_para(); close_list()
            out.append(f"<h2>{_inline(s[2:])}</h2>")
        elif s.startswith("## "):
            flush_para(); close_list()
            out.append(f"<h3>{_inline(s[3:])}</h3>")
        elif s.startswith("- "):
            flush_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(s[2:])}</li>")
        else:
            close_list()
            para.append(s)
    flush_para()
    close_list()
    return "\n".join(out)


def _inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = _RE_INLINE_CODE.sub(r"<code>\1</code>", s)
    s = _RE_LINK.sub(r'<a href="\2">\1</a>', s)
    s = _RE_BOLD.sub(r"<strong>\1</strong>", s)
    s = _RE_ITALIC.sub(r"<em>\1</em>", s)
    return s
