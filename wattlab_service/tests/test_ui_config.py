"""
Phase 1 (2026-06-10) — /ui-config.js + static JS bundle guards.

The five shared JS bundles (_LIVE_JS, _CARBON_JS, _PROGRESS_JS, _RESULT_JS,
_BENCH_HYDRATE_JS) are real files under static/, and the settings-driven copy
they used to get via import-time token baking now arrives at request time as
window.WL_CFG (served by /ui-config.js). These tests pin the three properties
the move bought:

1. the config is resolved per request — a settings flip shows up in the next
   response with no module reload (the old "restart for the label fix" class);
2. the bundles on disk carry no leftover {TOKEN} / __TOKEN__ placeholders;
3. rendered pages carry no unresolved tokens and reference only bundles that
   exist and are servable.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import settings

client = TestClient(main.app)
LAB = {"x-real-ip": "127.0.0.1"}
STATIC_DIR = Path(main.__file__).parent / "static"

PAGES = ["/", "/video", "/llm", "/image", "/rag", "/llm/compare", "/rag/compare",
         "/demo", "/queue", "/findings", "/benchmark", "/methodology", "/carbon"]


def _settings(monkeypatch, **over):
    base = {"cooldown_wait_for_idle": True, "video_cooldown_s": 10,
            "baseline_polls": 10, "llm_rest_s": 3}
    base.update(over)
    monkeypatch.setattr(settings, "load", lambda: base)


# ── /ui-config.js endpoint ──────────────────────────────────────────────────

def test_ui_config_is_js_with_expected_keys():
    r = client.get("/ui-config.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert r.headers.get("cache-control") == "private, max-age=5"
    assert r.text.startswith("window.WL_CFG = ")
    for key in ("baseline_s", "cooldown_label", "rest_label", "idle_label",
                "meter_name", "urls", "show_wait_detail", "idle_tolerance_w"):
        assert f'"{key}"' in r.text


def test_ui_config_tracks_settings_without_restart(monkeypatch):
    """The whole point of the move: flip the wait-for-idle toggle and the very
    next response changes wording — no module reload, no service restart."""
    _settings(monkeypatch, cooldown_wait_for_idle=True)
    assert '"cooldown_label": "Cooldown (\\u2192 idle)"' in client.get("/ui-config.js").text \
        or "Cooldown (→ idle)" in client.get("/ui-config.js").text
    _settings(monkeypatch, cooldown_wait_for_idle=False, video_cooldown_s=42)
    assert "Cooldown (42s)" in client.get("/ui-config.js").text


# ── bundle integrity on disk ────────────────────────────────────────────────

BUNDLES = ["wl-live.js", "wl-carbon.js", "wl-progress.js", "wl-result.js",
           "wl-bench-hydrate.js"]


@pytest.mark.parametrize("name", BUNDLES)
def test_bundle_exists_and_has_no_leftover_tokens(name):
    f = STATIC_DIR / name
    assert f.is_file(), f"static/{name} missing"
    js = f.read_text()
    assert not re.findall(r"\{[A-Z_]+\}", js), f"unresolved {{TOKEN}} left in {name}"
    assert not re.findall(r"__[A-Z_]+__", js), f"unresolved __TOKEN__ left in {name}"
    assert "<script" not in js, f"{name} still carries a <script> wrapper"


@pytest.mark.parametrize("name", BUNDLES)
def test_bundle_is_servable(name):
    assert client.get(f"/static/{name}").status_code == 200


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_cooldown_line_respects_wait_detail_toggle():
    """wlCooldownLine is the single live idle-wait readout (rendered by
    wlRenderProgress via opts.cooldownData on every page). It must honour the
    cooldown_show_wait_detail setting arriving through WL_CFG, and fold the
    target into one number (floor + tolerance) — the old two-part form
    ("58.0W+3W") is what made the line wrap."""
    harness = """
    global.window = global;
    global.document = {getElementById: () => null, querySelectorAll: () => []};
    global.WL_CFG = {show_wait_detail: true, idle_tolerance_w: 3.0,
                     meter_name: 'x', cooldown_label: 'c', idle_label: 'i', baseline_s: '10'};
    """ + (STATIC_DIR / "wl-progress.js").read_text() + """
    const data = {cooldown_waited_s: 12, cooldown_w: 65.2, cooldown_reference_w: 58.0};
    const on = wlCooldownLine(data);
    if (!on.includes('12s') || !on.includes('65.2')) throw new Error('missing live numbers: ' + on);
    if (!on.includes('61.0')) throw new Error('target must fold floor+tolerance into one number: ' + on);
    WL_CFG.show_wait_detail = false;
    if (wlCooldownLine(data) !== '') throw new Error('toggle off must suppress the line');
    console.log('ok');
    """
    r = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("name", sorted(p.name for p in STATIC_DIR.glob("*.js")))
def test_bundle_parses_as_javascript(name):
    """The check the in-Python-string era never had: a syntax error in a shared
    bundle (the S38 frozen-progress class) fails the suite, not the browser."""
    r = subprocess.run(["node", "--check", str(STATIC_DIR / name)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"{name} is not valid JS:\n{r.stderr}"


# ── rendered pages ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", PAGES)
def test_page_renders_with_no_unresolved_tokens(path):
    """Golden-transition guard: every page 200s and ships no raw wording token
    ({BASELINE_S}, {COOLDOWN_LABEL}, …) that the old import-time bake would
    have substituted."""
    r = client.get(path, headers=LAB)
    assert r.status_code == 200, f"{path} -> {r.status_code}"
    leftover = re.findall(
        r"\{(?:BASELINE_S|COOLDOWN_S|COOLDOWN_LABEL|COOLDOWN_PAREN|REST_LABEL"
        r"|IDLE_LABEL|LLM_REST_S|METER_NAME|PROGRESS_JS|CARBON_JS)\}", r.text)
    assert not leftover, f"{path} ships unresolved tokens: {set(leftover)}"


@pytest.mark.parametrize("path", PAGES)
def test_page_references_only_existing_bundles(path):
    html = client.get(path, headers=LAB).text
    for src in re.findall(r'<script src="/static/([^"?]+)', html):
        assert (STATIC_DIR / src).is_file(), f"{path} references missing /static/{src}"


# ── Slim public nav (2026-07-07 anon-experience redesign) ────────────────────

def test_public_nav_on_all_tiers():
    """Every render_page page carries the compact nav; before this an
    anonymous visitor could not reach /video or /video/budget without
    typing the URL."""
    from fastapi.testclient import TestClient
    import main
    c = TestClient(main.app)
    for path, headers in (("/video", {"x-real-ip": "8.8.8.8"}),
                          ("/demo", {"x-real-ip": "8.8.8.8"}),
                          ("/settings", {"x-real-ip": "127.0.0.1"})):
        t = c.get(path, headers=headers).text
        for href in ('href="/demo"', 'href="/video"',
                     'href="/video/budget"', 'href="/methodology"'):
            assert href in t, f"{path} nav missing {href}"
        assert 'href="/enhance-run"' not in t or path == "/settings", \
            f"{path} must not advertise the member-gated enhance page"


def test_public_nav_findings_follows_flag(monkeypatch):
    """The nav's Findings link and the footer link share _findings_on() —
    flag off removes both (no dead links; /findings 404s when disabled)."""
    from fastapi.testclient import TestClient
    import main, ui
    import settings as cfg
    c = TestClient(main.app)
    t = c.get("/video", headers={"x-real-ip": "8.8.8.8"}).text
    assert 'href="/findings"' in t   # flag is on in live settings
    real_load = cfg.load
    def off():
        d = real_load(); d["findings_enabled"] = False; return d
    monkeypatch.setattr(ui.cfg, "load", off)
    t = c.get("/video", headers={"x-real-ip": "8.8.8.8"}).text
    assert 'href="/findings"' not in t
