"""
paths.py — the ONE place OWL's filesystem roots are resolved (CR-031 §3 pre-work
item 1, done for CR-085 / docs/gos2_autonomy_plan.md Phase 1).

REPO_ROOT defaults to the checkout this file lives in (…/wattlab), so GoS1
(/home/gos/wattlab) and GoS2 (/Users/gos/wattlab) both work unchanged;
`OWL_ROOT` overrides it. Data that lives outside the checkout (bulk test
content, results archives, model caches) is reached through settings or the
repo's symlinks, never through a hard-coded host path in code.

Guard test (tests/test_paths.py): no module may contain the literal
"/home/gos/wattlab" except via this module.
"""
import os
from pathlib import Path

REPO_ROOT = Path(os.environ.get("OWL_ROOT") or Path(__file__).resolve().parent.parent)
ENV_FILE = Path(os.environ.get("OWL_ENV_FILE") or REPO_ROOT / ".env")


def repo(*parts) -> Path:
    """Path under the repo root, e.g. repo("test_content", "bbb_120s.mp4")."""
    return REPO_ROOT.joinpath(*parts)
