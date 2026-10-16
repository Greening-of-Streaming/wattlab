"""
TEMPORARY — /findings redesign preview for the Marketing Lab (2026-10-16).

Hidden preview of the redesigned findings catalog, built around what the
industry asks rather than how OWL is organised: a "where the watts go" chart up
front, six reader questions as the menu, plain-language headlines over the
technical claim, search + filters, and an "Early signals" shelf for findings
below the n=3 bar. Served under the same unguessable, noindexed prefix as
routes_mockups.py.

Reads, never writes:
  docs/findings/taxonomy.yaml             — controlled vocabulary (questions, facets, synonyms)
  docs/findings_drafts/plain_overlay.yaml — per-slug plain headline, question, tags, n_runs;
                                            `draft: true` pulls a finding from docs/findings_drafts/
Live finding files are untouched; the overlay moves into frontmatter in Phase 2.

DELETE THIS MODULE (and its main.py registration) when the redesign ships.
"""
import html as html_lib
import io
import json
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

import findings as findings_mod
import ui
from capabilities import requires, PUBLIC_PAGE
from persist import load_result
from routes_mockups import _PREFIX, _NOINDEX

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TAXONOMY_PATH = _REPO_ROOT / "docs" / "findings" / "taxonomy.yaml"
_OVERLAY_PATH = _REPO_ROOT / "docs" / "findings_drafts" / "plain_overlay.yaml"

_DEFAULT_MIN_N = 3          # WattLab call 2026-09-03: n=3 to leave the room
_CHIP_FACETS = ("where", "lever", "hardware", "codec")

_CONF_PLAIN = {
    "green":  ("🟢", "Solid", "clear of measurement noise"),
    "yellow": ("🟡", "Indicative", "direction clear, size less certain"),
    "red":    ("🔴", "Unconfirmed", "within measurement noise"),
}

# "Where the watts go" — every bar is a number from a finding's stored result,
# linked to that finding. Kept here (not computed) so the chart is reviewed
# like copy; the finding pages carry the CIs and provenance.
_WATTS = [
    ("What draws power while watching", [
        ("TV screen (55-inch OLED)", 52.80, "total", "tv-screen-draws-20x-the-streaming-box",
         "LG C2 panel, HD SDR, Filmmaker mode: 52.80 ±0.10 W, n=3"),
        ("Streaming box feeding it", 1.93, "total", "tv-screen-draws-20x-the-streaming-box",
         "Google TV Streamer, same rows: 1.93 ±0.01 W, n=3"),
    ]),
    ("What one choice adds", [
        ("Vivid picture mode instead of Standard", 20.36, "add", "tv-picture-mode-outweighs-streaming-choices",
         "Football: 73.05 W vs 52.69 W, 95 % CI +19.9 to +20.8 W, n=3"),
        ("HDR instead of SDR, at the screen", 3.92, "add", "hdr-costs-the-screen-4k-costs-the-box",
         "Panel +3.92 W (+7.4 %), HD Filmmaker, n=3; the box +0.01 W"),
        ("4K instead of HD, at the box", 0.41, "add", "hdr-costs-the-screen-4k-costs-the-box",
         "Google TV Streamer +0.41 W (+21 %), n=3; the screen +0.05 W"),
        ("128× the bitrate, at the box", 0.44, "add", "bitrate-barely-moves-box-playback-power",
         "Google TV Streamer, 0.25 → 32 Mb/s: +0.44 W (+26 %), n=3"),
    ]),
]

_STYLES = """
  body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text);
         max-width: 980px; margin: 0 auto; padding: 2rem; }
  h1 { font-family: monospace; color: var(--accent); font-size: 1.6rem; margin: 0 0 0.6rem; }
  h2 { font-family: monospace; color: var(--accent); font-size: 1.05rem; margin: 2.5rem 0 0.9rem; }
  .fx-preview { color: var(--text-4); font-family: monospace; font-size: 0.72rem; margin: 0 0 1.25rem;
    border-left: 2px solid var(--warn); padding-left: 0.6rem }
  .fx-preview b { color: var(--warn); font-weight: normal }
  .fx-lede { color: var(--text-2); line-height: 1.75; max-width: 680px; margin: 0 0 0.5rem; font-size: 1rem }
  .fx-proof { color: var(--text-3); font-size: 0.82rem; margin: 0 0 1.75rem }
  .fx-fig { border: 1px solid var(--border); background: var(--panel-2); padding: 1.2rem 1.25rem 1rem;
    display: flex; flex-direction: column; gap: 0.6rem }
  .fx-fig-title { font-size: 1.05rem; font-weight: 600; color: var(--text) }
  .fx-fig-sub { font-size: 0.8rem; color: var(--text-3) }
  .fx-legend { display: flex; gap: 1rem; flex-wrap: wrap; font-size: 0.75rem; color: var(--text-3) }
  .fx-legend i { display: inline-block; width: 11px; height: 11px; border-radius: 2px; margin-right: 0.35rem;
    vertical-align: -1px }
  .fx-chart { overflow-x: auto }
  .fx-chart svg { display: block; width: 100%; min-width: 640px; height: auto }
  .fx-chart text { fill: var(--text-2); font-size: 12.5px; font-family: system-ui, -apple-system, sans-serif }
  .fx-chart .grp { fill: var(--text-4); font-family: monospace; font-size: 10.5px; letter-spacing: 0.06em }
  .fx-chart .val { fill: var(--text); font-family: monospace; font-size: 12px; font-weight: bold }
  .fx-chart .axis { fill: var(--text-4); font-family: monospace; font-size: 10.5px }
  .fx-chart .grid { stroke: var(--border); stroke-width: 1 }
  .fx-chart .b-total { fill: var(--accent) }
  .fx-chart .b-add { fill: var(--text-4) }
  .fx-chart a:hover .bar, .fx-chart a:focus .bar { opacity: 0.75 }
  .fx-chart a:hover text.lbl { fill: var(--accent) }
  .fx-fig-note { font-size: 0.82rem; color: var(--text-2); line-height: 1.6; margin: 0.2rem 0 0 }
  .fx-fig-cap { font-size: 0.72rem; color: var(--text-4); line-height: 1.5; margin: 0 }
  .fx-themes { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 0.6rem }
  .fx-theme { text-align: left; background: var(--panel-2); border: 1px solid var(--border);
    border-left: 3px solid var(--border-3); color: var(--text); padding: 0.8rem 0.9rem; cursor: pointer;
    font: inherit; line-height: 1.4; display: flex; flex-direction: column; justify-content: flex-start; gap: 0.25rem }
  .fx-theme:hover { border-left-color: var(--accent) }
  .fx-theme:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }
  .fx-theme[aria-pressed="true"] { border-color: var(--accent-soft); border-left-color: var(--accent);
    background: var(--panel) }
  .fx-theme b { font-size: 0.93rem }
  .fx-theme span { color: var(--text-4); font-family: monospace; font-size: 0.7rem; letter-spacing: 0.04em }
  .fx-theme .fx-n { color: var(--accent) }
  .fx-tools { display: flex; flex-direction: column; gap: 0.5rem; margin: 1.25rem 0 0.5rem }
  .fx-search { width: 100%; box-sizing: border-box; background: var(--panel-2); color: var(--text);
    border: 1px solid var(--border-3); padding: 0.65rem 0.8rem; font-size: 0.95rem; font-family: inherit }
  .fx-search:focus { outline: none; border-color: var(--accent) }
  details.fx-filters > summary { cursor: pointer; color: var(--text-3); font-size: 0.82rem; font-family: monospace }
  .fx-facets { display: flex; flex-direction: column; gap: 0.45rem; padding: 0.75rem 0 0.25rem }
  .fx-facet { display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: baseline }
  .fx-facet-label { color: var(--text-4); font-family: monospace; font-size: 0.7rem; min-width: 10rem }
  .fx-chip { background: none; border: 1px solid var(--border-3); color: var(--text-2); padding: 0.15rem 0.6rem;
    font-size: 0.75rem; cursor: pointer; border-radius: 999px; font-family: inherit }
  .fx-chip:hover { border-color: var(--accent) }
  .fx-chip[aria-pressed="true"] { background: var(--accent-soft); border-color: var(--accent); color: var(--accent) }
  .fx-chip small { color: var(--text-4); margin-left: 0.25rem }
  .fx-status { color: var(--text-3); font-size: 0.8rem; margin: 0.25rem 0; font-family: monospace }
  .fx-status button { background: none; border: none; color: var(--accent); cursor: pointer; font: inherit;
    text-decoration: underline; padding: 0 }
  .fx-list { display: flex; flex-direction: column; gap: 0.6rem }
  .fx-card { border: 1px solid var(--border); border-left: 3px solid var(--accent); background: var(--panel-2);
    padding: 0.95rem 1.05rem; display: flex; flex-direction: column; gap: 0.5rem }
  .fx-card.early { border-left-color: var(--border-3) }
  .fx-q { color: var(--text-4); font-family: monospace; font-size: 0.68rem; letter-spacing: 0.05em;
    text-transform: uppercase }
  .fx-card h3 { margin: 0; font-size: 1.04rem; line-height: 1.45; font-weight: 600 }
  .fx-card h3 a { color: var(--text); text-decoration: none }
  .fx-card h3 a:hover { color: var(--accent) }
  .fx-meta { display: flex; flex-wrap: wrap; gap: 0.35rem 0.9rem; align-items: baseline; font-size: 0.78rem }
  .fx-pill { border: 1px solid var(--border-3); padding: 0.05rem 0.55rem; border-radius: 999px; color: var(--text-2);
    white-space: nowrap }
  .fx-draft { border-color: var(--warn); color: var(--warn) }
  .fx-key { color: var(--accent); font-family: monospace; font-weight: bold; font-size: 0.88rem }
  .fx-nchip { color: var(--text-4); font-family: monospace; font-size: 0.74rem }
  .fx-summary { color: var(--text-2); font-size: 0.88rem; line-height: 1.65; margin: 0 }
  .fx-foot { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 0.5rem; font-size: 0.75rem;
    color: var(--text-4) }
  .fx-foot a { color: var(--accent); text-decoration: none }
  details.fx-early { margin-top: 2.25rem; border-top: 1px solid var(--border); padding-top: 1rem }
  details.fx-early > summary { cursor: pointer; color: var(--text-2); font-size: 0.95rem }
  details.fx-early > summary b { color: var(--text) }
  .fx-early-note { color: var(--text-3); font-size: 0.82rem; line-height: 1.6; max-width: 660px; margin: 0.6rem 0 0.9rem }
  .fx-empty { color: var(--text-3); font-size: 0.85rem; padding: 0.5rem 0 }
  .fx-detail h1 { font-family: system-ui, -apple-system, sans-serif; color: var(--text); font-size: 1.5rem;
    line-height: 1.4; margin: 0.5rem 0 0.75rem }
  .fx-detail h2 { margin-top: 2rem }
  .fx-detail p, .fx-detail li { color: var(--text-2); line-height: 1.7; font-size: 0.9rem }
  .fx-detail table { border-collapse: collapse; font-size: 0.82rem; margin: 0.5rem 0 }
  .fx-detail th, .fx-detail td { border-bottom: 1px solid var(--border); padding: 0.35rem 0.6rem; text-align: left }
  .fx-wide { overflow-x: auto }
  .fx-box { border: 1px solid var(--border); background: var(--panel-2); padding: 0.85rem 1rem; margin: 0.5rem 0 }
  .fx-box .fx-key { font-size: 1.1rem }
  .fx-mono { font-family: monospace; font-size: 0.78rem; color: var(--text-3); line-height: 1.6 }
  .fx-detail a { color: var(--accent) }
  .fx-draft-banner { border: 1px solid var(--warn); color: var(--warn); padding: 0.55rem 0.85rem;
    font-size: 0.8rem; line-height: 1.5; margin: 0.5rem 0 1rem }
  @media (max-width: 600px) {
    body { padding: 1rem; }
    .fx-facet-label { min-width: 100%; }
  }
"""

# Live filtering. Plain string (not an f-string): braces are JS's. Reads the
# server-rendered cards' data-* attributes; the URL query mirrors the state so
# a filtered view can be shared.
_JS = """
(function () {
  var params = new URLSearchParams(location.search);
  var state = {
    theme: params.get('theme') || '',
    tags: (params.get('tags') || '').split(',').filter(Boolean),
    q: params.get('q') || ''
  };
  var cards = Array.prototype.slice.call(document.querySelectorAll('.fx-card'));
  var themeBtns = document.querySelectorAll('.fx-theme');
  var chips = document.querySelectorAll('.fx-chip');
  var search = document.getElementById('fx-q');
  var status = document.getElementById('fx-status');
  var statusText = document.getElementById('fx-status-text');
  var mainEmpty = document.getElementById('fx-main-empty');
  var earlyCount = document.getElementById('fx-early-count');
  var filters = document.getElementById('fx-filters');
  search.value = state.q;
  if (state.tags.length) filters.open = true;

  function matches(card, ignoreTheme) {
    if (!ignoreTheme && state.theme && card.dataset.theme !== state.theme) return false;
    var tags = card.dataset.tags.split(' ');
    for (var i = 0; i < state.tags.length; i++) {
      if (tags.indexOf(state.tags[i]) < 0) return false;
    }
    var words = state.q.toLowerCase().split(/\\s+/).filter(Boolean);
    for (var j = 0; j < words.length; j++) {
      if (card.dataset.text.indexOf(words[j]) < 0) return false;
    }
    return true;
  }

  function apply() {
    var shownMain = 0, shownEarly = 0;
    cards.forEach(function (c) {
      var ok = matches(c, false);
      c.hidden = !ok;
      if (ok) { if (c.classList.contains('early')) shownEarly++; else shownMain++; }
    });
    themeBtns.forEach(function (b) {
      var t = b.dataset.theme;
      b.setAttribute('aria-pressed', String(t === state.theme));
      var n = cards.filter(function (c) { return c.dataset.theme === t && matches(c, true); }).length;
      var el = b.querySelector('.fx-n');
      if (el) el.textContent = n + (n === 1 ? ' finding' : ' findings');
    });
    chips.forEach(function (ch) {
      ch.setAttribute('aria-pressed', String(state.tags.indexOf(ch.dataset.tag) >= 0));
    });
    mainEmpty.hidden = shownMain > 0;
    earlyCount.textContent = shownEarly;
    var filtered = state.theme || state.tags.length || state.q;
    status.hidden = !filtered;
    if (filtered) {
      statusText.textContent = (shownMain + shownEarly) + ' of ' + cards.length + ' findings match \\u00b7 ';
    }
    var p = new URLSearchParams(location.search);
    ['theme', 'tags', 'q'].forEach(function (k) { p.delete(k); });
    if (state.theme) p.set('theme', state.theme);
    if (state.tags.length) p.set('tags', state.tags.join(','));
    if (state.q) p.set('q', state.q);
    var qs = p.toString();
    history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
  }

  themeBtns.forEach(function (b) {
    b.addEventListener('click', function () {
      state.theme = (state.theme === b.dataset.theme) ? '' : b.dataset.theme;
      apply();
    });
  });
  chips.forEach(function (ch) {
    ch.addEventListener('click', function () {
      var i = state.tags.indexOf(ch.dataset.tag);
      if (i >= 0) state.tags.splice(i, 1); else state.tags.push(ch.dataset.tag);
      apply();
    });
  });
  search.addEventListener('input', function () { state.q = search.value.trim(); apply(); });
  document.getElementById('fx-clear').addEventListener('click', function () {
    state = { theme: '', tags: [], q: '' }; search.value = ''; apply();
  });
  apply();
})();
"""


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _tag_label(taxonomy: dict, tag: str) -> str:
    facet, _, key = tag.partition(":")
    return (taxonomy.get(facet, {}).get("values", {}).get(key, {}) or {}).get("label", key)


def _search_text(f, ov: dict, taxonomy: dict) -> str:
    """Everything a visitor might type: plain + technical wording, tag labels
    and their synonyms (so "STB" finds "set-top box")."""
    parts = [f.slug, f.headline, f.claim_short, ov.get("plain_headline", ""),
             ov.get("plain_summary", ""), ov.get("key_number", "")]
    theme = taxonomy.get("theme", {}).get("values", {}).get(ov.get("theme", ""), {})
    parts += [theme.get("label", ""), theme.get("question", "")] + list(theme.get("synonyms", []))
    for tag in ov.get("tags", []):
        facet, _, key = tag.partition(":")
        v = taxonomy.get(facet, {}).get("values", {}).get(key, {}) or {}
        parts += [v.get("label", key)] + list(v.get("synonyms", []))
    return " ".join(str(p) for p in parts).lower()


def _entries(min_n: int):
    """(finding, overlay, is_early, is_draft) — every published finding plus
    the drafts the overlay names, newest first. A published finding with no
    overlay entry falls back to its technical headline."""
    overlay = _load_yaml(_OVERLAY_PATH)
    items = [(f, False) for f in findings_mod.list_all()]
    for slug, ov in overlay.items():
        if (ov or {}).get("draft"):
            try:
                d = findings_mod.load_draft(slug)
            except findings_mod.FindingError:
                d = None
            if d is not None:
                items.append((d, True))
    items.sort(key=lambda x: x[0].last_refined, reverse=True)
    out = []
    for f, is_draft in items:
        ov = overlay.get(f.slug) or {}
        n = ov.get("n_runs")
        out.append((f, ov, n is None or int(n) < min_n, is_draft))
    return out


def _detail_url(slug: str, min_n: int) -> str:
    q = "" if min_n == _DEFAULT_MIN_N else f"?min_n={min_n}"
    return f"{_PREFIX}/findings/{html_lib.escape(slug)}{q}"


def _card_html(f, ov: dict, early: bool, is_draft: bool, taxonomy: dict, min_n: int) -> str:
    e = html_lib.escape
    dot, word, meaning = _CONF_PLAIN.get(f.confidence, ("·", "", ""))
    headline = ov.get("plain_headline") or f.headline
    n = ov.get("n_runs")
    n_txt = f"n={n}" if n is not None else "n not yet stated"
    detail = _detail_url(f.slug, min_n)
    theme = taxonomy.get("theme", {}).get("values", {}).get(ov.get("theme", ""), {})
    draft = '<span class="fx-pill fx-draft">Draft &middot; awaiting lab review</span>' if is_draft else ""
    if early:
        meta = (f'{draft}<span class="fx-pill">Early signal &middot; {e(n_txt)}</span>'
                f'<span class="fx-nchip">not yet repeated {min_n}&times;, so no headline number</span>')
    else:
        meta = (f'{draft}<span class="fx-pill" title="{e(meaning)}">{dot} {e(word)}</span>'
                f'<span class="fx-key">{e(ov.get("key_number", ""))}</span>'
                f'<span class="fx-nchip">{e(ov.get("n_note") or n_txt)}</span>')
    summary = ov.get("plain_summary", "")
    return (
        f'<article class="fx-card{" early" if early else ""}" data-theme="{e(ov.get("theme", ""))}" '
        f'data-tags="{e(" ".join(ov.get("tags", [])))}" data-text="{e(_search_text(f, ov, taxonomy))}">'
        f'<span class="fx-q">{e(theme.get("label", ""))}</span>'
        f'<h3><a href="{detail}">{e(headline)}</a></h3>'
        f'<div class="fx-meta">{meta}</div>'
        + (f'<p class="fx-summary">{e(summary)}</p>' if summary and not early else "")
        + f'<div class="fx-foot"><span>Measured {e(f.first_measured)}'
        f'{"" if f.last_refined == f.first_measured else " &middot; updated " + e(f.last_refined)}</span>'
        f'<a href="{detail}">See the science &rarr;</a></div>'
        f'</article>'
    )


def _watts_chart_html(min_n: int) -> str:
    """Server-rendered horizontal bars on one linear watt scale, each row a
    link to the finding it comes from."""
    e = html_lib.escape
    W, label_w, right, row_h, top, vmax = 760, 300, 72, 34, 22, 80.0
    plot_w = W - label_w - right
    x = lambda v: label_w + v / vmax * plot_w
    parts, y = [], top
    for gi, (group, rows) in enumerate(_WATTS):
        if gi:
            y += 12
        parts.append(f'<text class="grp" x="0" y="{y + 12}">{e(group.upper())}</text>')
        y += 24
        for label, w, kind, slug, detail in rows:
            bh, by = 16, y + (row_h - 16) / 2 - 4
            bw = max(3.0, x(w) - label_w)
            val = f'{"+" if kind == "add" else ""}{w:.2f} W' if w < 1 else f'{"+" if kind == "add" else ""}{w:.1f} W'
            path = (f"M{label_w},{by:.1f} h{bw - 4:.1f} a4,4 0 0 1 4,4 v{bh - 8} a4,4 0 0 1 -4,4 "
                    f"h{-(bw - 4):.1f} z")
            parts.append(
                f'<a href="{_detail_url(slug, min_n)}"><title>{e(label)}: {e(val)}. {e(detail)}</title>'
                f'<rect x="0" y="{y - 4}" width="{W}" height="{row_h}" fill="transparent"/>'
                f'<text class="lbl" x="{label_w - 12}" y="{by + bh - 3.5:.1f}" text-anchor="end">{e(label)}</text>'
                f'<path class="bar {"b-total" if kind == "total" else "b-add"}" d="{path}"/>'
                f'<text class="val" x="{label_w + bw + 8:.1f}" y="{by + bh - 3.5:.1f}">{e(val)}</text></a>')
            y += row_h
    h = y + 26
    grid = "".join(
        f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top - 4}" y2="{h - 22}"/>'
        f'<text class="axis" x="{x(t):.1f}" y="{h - 6}" text-anchor="middle">{t} W</text>'
        for t in (0, 20, 40, 60, 80))
    aria = ("Bar chart of watts while watching: TV screen 52.8 W, streaming box 1.9 W; "
            "Vivid picture mode adds 20.4 W, HDR adds 3.9 W at the screen, 4K adds 0.41 W at the box, "
            "128 times the bitrate adds 0.44 W at the box.")
    return (f'<svg viewBox="0 0 {W} {h}" role="img" aria-label="{e(aria)}">{grid}{"".join(parts)}</svg>')


def _catalog_html(min_n: int) -> str:
    e = html_lib.escape
    taxonomy = _load_yaml(_TAXONOMY_PATH)
    entries = _entries(min_n)
    main = [x for x in entries if not x[2]]
    early = [x for x in entries if x[2]]

    themes = taxonomy.get("theme", {}).get("values", {})
    theme_btns = "".join(
        f'<button type="button" class="fx-theme" data-theme="{e(k)}" aria-pressed="false">'
        f'<b>{e(v.get("question", v.get("label", k)))}</b>'
        f'<span>{e(v.get("label", k).upper())} &middot; <span class="fx-n"></span></span></button>'
        for k, v in themes.items())

    used: dict[str, int] = {}
    for _, ov, _, _ in entries:
        for t in ov.get("tags", []):
            used[t] = used.get(t, 0) + 1
    facet_rows = []
    for facet in _CHIP_FACETS:
        spec = taxonomy.get(facet, {})
        chips = "".join(
            f'<button type="button" class="fx-chip" data-tag="{e(facet)}:{e(k)}" aria-pressed="false" '
            f'title="{e(v.get("definition", ""))}">{e(v.get("label", k))}'
            f'<small>{used[facet + ":" + k]}</small></button>'
            for k, v in spec.get("values", {}).items() if used.get(f"{facet}:{k}"))
        if chips:
            facet_rows.append(f'<div class="fx-facet"><span class="fx-facet-label">'
                              f'{e(spec.get("label", facet))}</span>{chips}</div>')

    cards = lambda xs: "".join(_card_html(f, ov, er, dr, taxonomy, min_n) for f, ov, er, dr in xs)
    n_drafts = sum(1 for x in entries if x[3])

    return f"""
<p class="fx-preview"><b>Preview</b> of the redesigned findings page, for discussion &middot;
   {n_drafts} findings marked Draft are awaiting lab review &middot; numbers link to the stored measurements</p>
<h1>What we've measured</h1>
<p class="fx-lede">OWL is the open measurement lab of <strong>Greening of Streaming</strong>, a member-funded
   non-profit. We measure real streaming hardware at the wall socket, repeat every test, and publish the
   confidence and the raw data behind each result.</p>
<p class="fx-proof">{len(main)} findings repeated at least {min_n}&times; &middot; {len(early)} early signals
   &middot; every one linked to its stored measurement</p>

<section class="fx-fig" aria-labelledby="fx-watts">
  <div class="fx-fig-title" id="fx-watts">Where the watts go when you watch</div>
  <div class="fx-fig-sub">Watts at the wall while playing video on one 55-inch OLED TV and the box feeding it.
     A watt drawn for an hour is a watt-hour, so each bar is also the energy per hour of viewing.</div>
  <div class="fx-legend" aria-hidden="true"><span><i style="background:var(--accent)"></i>Total draw</span>
     <span><i style="background:var(--text-4)"></i>Extra draw from one choice</span></div>
  <div class="fx-chart">{_watts_chart_html(min_n)}</div>
  <p class="fx-fig-note">The screen dominates, the TV's own picture setting outweighs every streaming choice, and
     4K, HDR and bitrate cost far less at the box than the debate suggests. Select a bar for the finding behind it.</p>
  <p class="fx-fig-cap">All values n=3, measured October 2026. One TV and one box: this shows the scale,
     not a market average. Network and data-centre energy are not included.</p>
</section>

<h2>Browse by question</h2>
<div class="fx-themes">{theme_btns}</div>
<div class="fx-tools">
  <input id="fx-q" class="fx-search" type="search" aria-label="Search findings"
         placeholder="Search findings, e.g. 4K, set-top box, AV1, picture mode, AI">
  <details class="fx-filters" id="fx-filters"><summary>Filter by device, format or lever</summary>
    <div class="fx-facets">{"".join(facet_rows)}</div></details>
  <p id="fx-status" class="fx-status" hidden><span id="fx-status-text"></span><button type="button" id="fx-clear">clear filters</button></p>
</div>
<section class="fx-list" aria-label="Findings">{cards(main)}
  <p id="fx-main-empty" class="fx-empty" hidden>No repeated findings match. Try the early signals below.</p>
</section>
<details class="fx-early">
  <summary><b>Early signals</b> (<span id="fx-early-count">{len(early)}</span>): measured, but not yet repeated {min_n}&times;</summary>
  <p class="fx-early-note">These are real, published measurements, but each rests on fewer than {min_n} repeats.
     We show what we saw and why it matters, without a headline number, until the result is repeated.
     The numbers, limits and raw data are one click away.</p>
  <div class="fx-list">{cards(early)}</div>
</details>
<script>{_JS}</script>
"""


def _source_url(rid: str, is_draft: bool) -> str:
    if not is_draft:
        return findings_mod.result_download_url(rid)
    type_, token = rid.split("/", 1)
    return f"{_PREFIX}/findings/source/{type_}/{token.split('_')[-1]}/download.json"


def _detail_html(slug: str, min_n: int) -> str | None:
    e = html_lib.escape
    taxonomy = _load_yaml(_TAXONOMY_PATH)
    entries = {f.slug: (f, ov, early, dr) for f, ov, early, dr in _entries(min_n)}
    if slug not in entries:
        return None
    f, ov, early, is_draft = entries[slug]
    dot, word, meaning = _CONF_PLAIN.get(f.confidence, ("·", "", ""))
    theme = taxonomy.get("theme", {}).get("values", {}).get(ov.get("theme", ""), {})
    n = ov.get("n_runs")
    back = f'{_PREFIX}/findings' + ("" if min_n == _DEFAULT_MIN_N else f"?min_n={min_n}")

    if early:
        badge = (f'<span class="fx-pill">Early signal &middot; n={e(str(n))}</span> '
                 f'<span class="fx-nchip">not yet repeated {min_n}&times;</span>')
    else:
        badge = (f'<span class="fx-pill">{dot} {e(word)} &middot; {e(meaning)}</span> '
                 f'<span class="fx-key">{e(ov.get("key_number", ""))}</span>')
    draft_banner = ('<p class="fx-draft-banner">Draft finding, awaiting lab review. The measurements are '
                    'stored and linked below; the wording may still change before publication.</p>'
                    if is_draft else "")

    caveats = [c for c in f.caveats if not c.startswith("DRAFT pending")]
    caveats_html = "".join(f"<li>{findings_mod.md_to_html(c)}</li>" for c in caveats)
    sources = "".join(
        f'<li><a href="{e(_source_url(r, is_draft))}">{e(r)}</a> (JSON)</li>' for r in f.source_result_ids)
    related = ""
    for r in f.related_findings or []:
        if r in entries:
            rf, rov, _, _ = entries[r]
            related += f'<li><a href="{_detail_url(r, min_n)}">{e(rov.get("plain_headline") or rf.headline)}</a></li>'
    live = ("" if is_draft else
            f' &middot; Current live page: <a href="/findings/{e(f.slug)}">/findings/{e(f.slug)}</a>')

    return f"""
<p class="fx-preview"><b>Preview</b> of the redesigned findings page, for discussion</p>
<div class="fx-detail">
<p class="fx-mono"><a href="{back}">&larr; All findings</a> &middot; {e(theme.get("question", ""))}</p>
<h1>{e(ov.get("plain_headline") or f.headline)}</h1>
{draft_banner}<div class="fx-meta">{badge}</div>

<h2>What this means</h2>
<p>{e(ov.get("plain_summary", ""))}</p>

<h2>The numbers</h2>
<div class="fx-box">
  <p class="fx-mono" style="color:var(--text-2)">{e(f.claim_short)}</p>
  <p class="fx-mono">Repeats: {e(ov.get("n_note") or f"n={n}")} &middot; Confidence: {dot} {e(word)}
     &middot; Measured {e(f.first_measured)}, last refined {e(f.last_refined)} (v{f.version})</p>
</div>

<h2>Technical claim</h2>
<p>{e(f.headline)}</p>

<h2>What this covers, and what it doesn't</h2>
<p>{e(f.scope)}</p>
{f"<h2>Limitations</h2><ul>{caveats_html}</ul>" if caveats_html else ""}

<h2>Raw data</h2>
<ul>{sources}</ul>
<p class="fx-mono">How we measure and rate confidence: <a href="/methodology">Methodology</a>{live}</p>

<details><summary style="cursor:pointer;color:var(--text-2);margin-top:1.5rem">Full analysis</summary>
<div class="fx-wide">{findings_mod.md_to_html(f.body_md)}</div>
</details>

{f"<h2>Related findings</h2><ul>{related}</ul>" if related else ""}
</div>
"""


def _page(request: Request, title: str, body: str) -> HTMLResponse:
    return HTMLResponse(ui.render_page(request, title, body, styles=_STYLES, head=_NOINDEX, back=False))


def _min_n(request: Request) -> int:
    try:
        return max(1, int(request.query_params.get("min_n", _DEFAULT_MIN_N)))
    except ValueError:
        return _DEFAULT_MIN_N


@router.get(_PREFIX + "/findings", response_class=HTMLResponse,
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def mockup_findings_catalog(request: Request):
    return _page(request, "Findings (preview)", _catalog_html(_min_n(request)))


@router.get(_PREFIX + "/findings/source/{job_type}/{job_id}/download.json",
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def mockup_draft_source(job_type: str, job_id: str):
    """Raw data for the drafts this preview shows. Scoped like the live
    /findings/source carve-out: only results a previewed draft cites."""
    cited = set()
    for f, _, _, is_draft in _entries(_DEFAULT_MIN_N):
        if is_draft:
            for rid in f.source_result_ids:
                t, tail = rid.split("/", 1)
                cited.add((t, tail.split("_")[-1]))
    if (job_type, job_id.split("_")[-1]) not in cited:
        return JSONResponse({"error": "Not a cited draft source"}, status_code=404)
    data = load_result(job_type, job_id, visitor_key=None)
    if not data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return StreamingResponse(io.BytesIO(json.dumps(data, indent=2).encode()), media_type="application/json")


@router.get(_PREFIX + "/findings/{slug}", response_class=HTMLResponse,
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def mockup_finding_detail(request: Request, slug: str):
    body = _detail_html(slug, _min_n(request))
    if body is None:
        return HTMLResponse("Not found", status_code=404)
    return _page(request, "Finding (preview)", body)
