"""
Guards against a class of bug where a page's JS calls a shared helper that lives
in a bundle the page doesn't include — a runtime ReferenceError that silently
breaks the poll loop (e.g. the frozen /llm/compare progress, 2026-06-02).

Phase 1 (2026-06-10): the shared bundles are real files under static/, pulled
in via <script src="/static/wl-*.js">. A page's effective JS is therefore the
HTML plus every static bundle it references — the corpus these checks run on.
If a page CALLS wlCooldownDialog / wlCooldownSummary, its corpus must DEFINE it.
"""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

PAGES = ["/llm/compare", "/rag/compare", "/rag", "/image", "/video", "/enhance-run"]
# Fetch as Lab so member-gated pages (e.g. /enhance-run) are still inspectable;
# the public pages render identically for Lab.
LAB = {"x-real-ip": "127.0.0.1"}

STATIC_DIR = Path(main.__file__).parent / "static"


def _effective_js(path: str) -> str:
    """Page HTML + the content of every /static/*.js bundle it references —
    what the browser actually executes."""
    html = client.get(path, headers=LAB).text
    corpus = [html]
    for src in re.findall(r'<script src="/static/([^"?]+)', html):
        f = STATIC_DIR / src
        assert f.is_file(), f"{path} references /static/{src} but the file does not exist"
        corpus.append(f.read_text())
    return "\n".join(corpus)


@pytest.mark.parametrize("path", PAGES)
def test_cooldown_dialog_defined_where_called(path):
    js = _effective_js(path)
    if "wlCooldownDialog(" in js:
        assert "window.wlCooldownDialog =" in js, f"{path} calls wlCooldownDialog but never defines it"
        assert "window.wlCooldownDialogClose =" in js, f"{path} calls the dialog but lacks wlCooldownDialogClose"


@pytest.mark.parametrize("path", PAGES)
def test_cooldown_summary_defined_where_called(path):
    js = _effective_js(path)
    if "wlCooldownSummary(" in js:
        assert "window.wlCooldownSummary =" in js, f"{path} calls wlCooldownSummary but never defines it"


@pytest.mark.parametrize("path", PAGES)
def test_wl_cfg_loaded_before_bundles_that_need_it(path):
    """wl-progress.js builds its stage labels from window.WL_CFG at load time;
    wl-carbon.js reads WL_CFG.urls. Any page shipping those bundles must load
    /ui-config.js first (document order = execution order for plain scripts)."""
    html = client.get(path, headers=LAB).text
    for bundle in ("wl-progress.js", "wl-carbon.js"):
        pos = html.find(bundle)
        if pos == -1:
            continue
        cfg_pos = html.find('src="/ui-config.js"')
        assert cfg_pos != -1, f"{path} ships {bundle} but never loads /ui-config.js"
        assert cfg_pos < pos, f"{path} loads {bundle} before /ui-config.js"
