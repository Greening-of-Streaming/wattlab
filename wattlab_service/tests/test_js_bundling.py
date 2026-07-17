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


def test_video_rich_renderer_single_source():
    """2026-07-07 renderer unification: the rich video card lives ONLY in
    wl-result.js (wlRenderVideoCard + _wlVideoSingleRich/_wlVideoBothRich/
    _wlVideoAllCodecsRich, CSS self-injected under .wl-rich). The /video
    page must delegate — a re-grown inline renderSingle/renderBoth would
    reopen the fresh-vs-stored drift this closed."""
    bundle = (STATIC_DIR / "wl-result.js").read_text()
    assert bundle.count("window.wlRenderVideoCard =") == 1
    for fn in ("_wlVideoSingleRich", "_wlVideoBothRich", "_wlVideoAllCodecsRich",
               "_wlEnsureRichStyles"):
        assert f"function {fn}(" in bundle, f"wl-result.js lost {fn}"
    assert "Energy Report — " in bundle          # the rich single card marker
    video_html = client.get("/video", headers=LAB).text
    for fn in ("function renderSingle", "function renderBoth",
               "function renderAllCodecs"):
        assert fn not in video_html, f"/video regrew an inline {fn}"
    assert "wlRenderVideoCard(" in video_html    # fresh path delegates


def test_video_stage_lists_single_source():
    """2026-07-17: /demo's tour poll ran its own 4-stage video list with no
    'vmaf' index — the multi-minute VMAF pass rendered as "Baseline". The
    preset-keyed stage lists + stage→index maps now live ONLY in
    wl-progress.js (WL_VIDEO_PRESET_STAGES / WL_VIDEO_PRESET_IDX); /video and
    /demo must reference them, never define local copies."""
    bundle = (STATIC_DIR / "wl-progress.js").read_text()
    assert "WL_VIDEO_PRESET_STAGES" in bundle
    assert "WL_VIDEO_PRESET_IDX" in bundle
    assert bundle.count("VMAF (quality)") >= 4      # both/all/codecs_cpu/codecs_gpu
    assert "function wlVmafLine(" in bundle
    # every comparison map must know the vmaf stage
    for m in ("_WL_V_BOTH_IDX", "_WL_V_ALL_IDX",
              "_WL_V_CODECS_CPU_IDX", "_WL_V_CODECS_GPU_IDX"):
        block = bundle.split(m + " = ", 1)[1].split("};", 1)[0]
        assert "vmaf:" in block, f"{m} lost its vmaf index"

    video_html = client.get("/video", headers=LAB).text
    assert "WL_VIDEO_PRESET_STAGES" in video_html
    assert "const _BOTH_STAGES" not in video_html, "/video regrew a local stage list"

    demo_html = client.get("/demo", headers=LAB).text
    assert "WL_VIDEO_PRESET_STAGES.both" in demo_html
    assert "WL_VIDEO_PRESET_IDX.both" in demo_html
    assert "wlVmafLine(" in demo_html
    assert "const VIDEO_STAGE_IDX" not in demo_html, "/demo regrew a local stage map"
