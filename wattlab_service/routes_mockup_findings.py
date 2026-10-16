"""
TEMPORARY — /findings redesign mockup for the Marketing Lab (2026-10-16).

Hidden preview of the redesigned findings catalog: plain-language headlines,
a reader-question theme menu, facet chips + free-text search, and an
"Early signals" shelf for findings below the n=3 bar. Served under the same
unguessable, noindexed prefix as routes_mockups.py.

Reads two DRAFT files and never writes anything:
  docs/findings/taxonomy.yaml             — controlled vocabulary (facets/values/synonyms)
  docs/findings_drafts/plain_overlay.yaml — per-slug plain headline, theme, tags, n_runs
Live finding files are untouched; the overlay moves into frontmatter in Phase 2.

DELETE THIS MODULE (and its main.py registration) when the redesign ships.
"""
import html as html_lib
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

import findings as findings_mod
import ui
from capabilities import requires, PUBLIC_PAGE
from routes_mockups import _PREFIX, _NOINDEX, _MOCK_STYLES

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

_WATERMARK = (
    '<div class="fx-watermark">MOCKUP &middot; /findings redesign preview for the Marketing Lab '
    '&mdash; not linked from the live site. Findings, numbers and links are real; plain headlines, '
    'themes, tags and n counts are DRAFTS (docs/findings_drafts/plain_overlay.yaml) awaiting edit.</div>'
)

_STYLES = """
  body { max-width: 980px; }
  .fx-watermark { border:1px dashed var(--warn); color:var(--warn); padding:0.6rem 1rem;
    font-family:monospace; font-size:0.72rem; margin:0 0 1.75rem; line-height:1.6 }
  .fx-hero p { color:var(--text-2); line-height:1.7; max-width:640px; margin:0.5rem 0 }
  .fx-hero .fx-count { color:var(--text-3); font-size:0.85rem }
  .fx-themes { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
    gap:0.6rem; margin:1.5rem 0 1rem }
  .fx-theme { text-align:left; background:var(--panel-2); border:1px solid var(--border);
    border-left:3px solid var(--border-3); color:var(--text); padding:0.75rem 0.85rem;
    cursor:pointer; font:inherit; line-height:1.4; display:flex; flex-direction:column;
    justify-content:flex-start }
  .fx-theme:hover { border-left-color:var(--accent) }
  .fx-theme[aria-pressed="true"] { border-color:var(--accent-soft); border-left-color:var(--accent);
    background:var(--panel) }
  .fx-theme b { display:block; font-size:0.9rem; margin-bottom:0.25rem }
  .fx-theme span { color:var(--text-3); font-size:0.78rem }
  .fx-theme .fx-n { color:var(--accent); font-family:monospace; font-size:0.75rem; margin-top:0.35rem;
    display:block }
  .fx-search { width:100%; box-sizing:border-box; background:var(--panel-2); color:var(--text);
    border:1px solid var(--border-3); padding:0.65rem 0.8rem; font-size:0.95rem; margin:0.5rem 0 0.75rem }
  .fx-search:focus { outline:none; border-color:var(--accent) }
  .fx-facets { display:flex; flex-direction:column; gap:0.4rem; margin-bottom:1.25rem }
  .fx-facet { display:flex; flex-wrap:wrap; gap:0.35rem; align-items:baseline }
  .fx-facet-label { color:var(--text-4); font-family:monospace; font-size:0.7rem; min-width:9.5rem }
  .fx-chip { background:none; border:1px solid var(--border-3); color:var(--text-2); padding:0.15rem 0.6rem;
    font-size:0.75rem; cursor:pointer; border-radius:999px; font-family:inherit }
  .fx-chip:hover { border-color:var(--accent) }
  .fx-chip[aria-pressed="true"] { background:var(--accent-soft); border-color:var(--accent); color:var(--accent) }
  .fx-chip small { color:var(--text-4); margin-left:0.2rem }
  .fx-status { color:var(--text-3); font-size:0.8rem; margin:0 0 0.5rem; font-family:monospace }
  .fx-status button { background:none; border:none; color:var(--accent); cursor:pointer; font:inherit;
    text-decoration:underline; padding:0 }
  .fx-card { border:1px solid var(--border); border-left:3px solid var(--accent); background:var(--panel-2);
    padding:0.9rem 1rem; margin:0.6rem 0 }
  .fx-card.early { border-left-color:var(--border-3) }
  .fx-card h3 { margin:0 0 0.45rem; font-size:1.02rem; line-height:1.45; font-weight:600 }
  .fx-card h3 a { color:var(--text); text-decoration:none }
  .fx-card h3 a:hover { color:var(--accent) }
  .fx-meta { display:flex; flex-wrap:wrap; gap:0.4rem 0.9rem; align-items:baseline; font-size:0.78rem;
    margin-bottom:0.5rem }
  .fx-pill { border:1px solid var(--border-3); padding:0.05rem 0.5rem; border-radius:999px; color:var(--text-2) }
  .fx-key { color:var(--accent); font-family:monospace; font-weight:bold; font-size:0.85rem }
  .fx-nchip { color:var(--text-4); font-family:monospace }
  .fx-summary { color:var(--text-2); font-size:0.86rem; line-height:1.6; margin:0 0 0.5rem }
  .fx-tech { color:var(--text-4); font-family:monospace; font-size:0.72rem; line-height:1.5; margin:0 0 0.4rem }
  .fx-foot { display:flex; flex-wrap:wrap; justify-content:space-between; gap:0.5rem; font-size:0.75rem;
    color:var(--text-4) }
  .fx-foot a { color:var(--accent); text-decoration:none }
  .fx-tags { display:flex; flex-wrap:wrap; gap:0.3rem }
  .fx-tag { color:var(--text-4); border:1px solid var(--border); padding:0 0.4rem; font-size:0.68rem }
  details.fx-early { margin-top:2rem; border-top:1px solid var(--border); padding-top:1rem }
  details.fx-early summary { cursor:pointer; color:var(--text-2); font-size:0.95rem }
  details.fx-early summary b { color:var(--text) }
  .fx-early-note { color:var(--text-3); font-size:0.8rem; line-height:1.6; max-width:640px; margin:0.6rem 0 }
  .fx-empty { color:var(--text-3); font-size:0.85rem; padding:0.75rem 0 }
  .fx-detail h1 { font-family:system-ui,-apple-system,sans-serif; color:var(--text); font-size:1.45rem;
    line-height:1.4; margin:0.5rem 0 0.75rem }
  .fx-detail h2 { margin-top:1.75rem }
  .fx-detail p, .fx-detail li { color:var(--text-2); line-height:1.7; font-size:0.9rem }
  .fx-box { border:1px solid var(--border); background:var(--panel-2); padding:0.8rem 1rem; margin:0.5rem 0 }
  .fx-box .fx-key { font-size:1.1rem }
  .fx-mono { font-family:monospace; font-size:0.78rem; color:var(--text-3); line-height:1.6 }
  .fx-detail a { color:var(--accent) }
  @media (max-width: 600px) {
    body { padding: 1rem; }
    .fx-themes { grid-template-columns:1fr 1fr; }
    .fx-facet-label { min-width:100%; }
  }
"""

# Live filtering. Plain string (not an f-string): braces are JS's. Reads the
# server-rendered cards' data-* attributes; URL query mirrors the state so a
# filtered view can be shared.
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
  var mainEmpty = document.getElementById('fx-main-empty');
  var earlyCount = document.getElementById('fx-early-count');
  search.value = state.q;

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
      var n = cards.filter(function (c) {
        return (!t || c.dataset.theme === t) && matches(c, true);
      }).length;
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
      status.firstChild.textContent = (shownMain + shownEarly) + ' of ' + cards.length + ' findings match \\u00b7 ';
    }
    var p = new URLSearchParams(location.search);
    ['theme', 'tags', 'q'].forEach(function (k) { p.delete(k); });
    if (state.theme) p.set('theme', state.theme);
    if (state.tags.length) p.set('tags', state.tags.join(','));
    if (state.q) p.set('q', state.q);
    var qs = p.toString();
    history.replaceState(null, '', location.pathname + (qs ? '?' + qs : ''));
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
             ov.get("plain_summary", "")]
    theme = taxonomy.get("theme", {}).get("values", {}).get(ov.get("theme", ""), {})
    parts += [theme.get("label", "")] + list(theme.get("synonyms", []))
    for tag in ov.get("tags", []):
        facet, _, key = tag.partition(":")
        v = taxonomy.get(facet, {}).get("values", {}).get(key, {}) or {}
        parts += [v.get("label", key)] + list(v.get("synonyms", []))
    return " ".join(str(p) for p in parts).lower()


def _entries(min_n: int):
    """(finding, overlay, is_early) for every published finding, newest first.
    A finding with no overlay entry yet falls back to its technical headline."""
    overlay = _load_yaml(_OVERLAY_PATH)
    items = findings_mod.list_all()
    items.sort(key=lambda f: f.last_refined, reverse=True)
    out = []
    for f in items:
        ov = overlay.get(f.slug) or {}
        n = ov.get("n_runs")
        early = n is None or int(n) < min_n
        out.append((f, ov, early))
    return out


def _card_html(f, ov: dict, early: bool, taxonomy: dict, min_n: int) -> str:
    e = html_lib.escape
    dot, word, meaning = _CONF_PLAIN.get(f.confidence, ("·", "", ""))
    headline = ov.get("plain_headline") or f.headline
    n = ov.get("n_runs")
    n_txt = f"n={n}" if n is not None else "n not yet stated"
    detail = f"{_PREFIX}/findings/{e(f.slug)}?min_n={min_n}"
    if early:
        meta = (f'<span class="fx-pill">Early signal &middot; {e(n_txt)}</span>'
                f'<span class="fx-nchip">below the n={min_n} bar &mdash; no headline number until repeated</span>')
    else:
        meta = (f'<span class="fx-pill" title="{e(meaning)}">{dot} {e(word)} &middot; {e(meaning)}</span>'
                f'<span class="fx-key">{e(ov.get("key_number", ""))}</span>'
                f'<span class="fx-nchip">{e(ov.get("n_note") or n_txt)}</span>')
    tags = "".join(f'<span class="fx-tag">{e(_tag_label(taxonomy, t))}</span>'
                   for t in ov.get("tags", []))
    summary = ov.get("plain_summary", "")
    return (
        f'<article class="fx-card{" early" if early else ""}" data-theme="{e(ov.get("theme", ""))}" '
        f'data-tags="{e(" ".join(ov.get("tags", [])))}" data-text="{e(_search_text(f, ov, taxonomy))}">'
        f'<h3><a href="{detail}">{e(headline)}</a></h3>'
        f'<div class="fx-meta">{meta}</div>'
        + (f'<p class="fx-summary">{e(summary)}</p>' if summary and not early else "")
        + f'<p class="fx-tech">Technical claim: {e(f.headline)}</p>'
        f'<div class="fx-foot"><div class="fx-tags">{tags}</div>'
        f'<span>Measured {e(f.first_measured)} &middot; v{f.version} &middot; '
        f'<a href="{detail}">See the science &rarr;</a></span></div>'
        f'</article>'
    )


def _catalog_html(min_n: int) -> str:
    e = html_lib.escape
    taxonomy = _load_yaml(_TAXONOMY_PATH)
    entries = _entries(min_n)
    main = [x for x in entries if not x[2]]
    early = [x for x in entries if x[2]]

    themes = taxonomy.get("theme", {}).get("values", {})
    theme_btns = "".join(
        f'<button type="button" class="fx-theme" data-theme="{e(k)}" aria-pressed="false">'
        f'<b>{e(v.get("label", k))}</b><span>{e(v.get("question", ""))}</span>'
        f'<span class="fx-n"></span></button>'
        for k, v in themes.items())

    used: dict[str, int] = {}
    for _, ov, _ in entries:
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

    main_cards = "".join(_card_html(f, ov, False, taxonomy, min_n) for f, ov, _ in main)
    early_cards = "".join(_card_html(f, ov, True, taxonomy, min_n) for f, ov, _ in early)
    toggle = (f'<a href="?min_n=1" style="color:var(--accent)">see the page with every finding on the main shelf</a>'
              if min_n > 1 else
              f'<a href="?min_n={_DEFAULT_MIN_N}" style="color:var(--accent)">back to the n={_DEFAULT_MIN_N} bar</a>')

    return f"""
<div class="fx-hero">
  <h1>What we've measured</h1>
  <p>OWL is the open measurement bench of <strong>Greening of Streaming</strong>, a member-funded
     non-profit. Each finding below is one claim we measured ourselves, on real hardware, at the wall
     socket &mdash; with its confidence, its limits and the raw data behind it.</p>
  <p class="fx-count">{len(main)} findings repeated at least {min_n}&times; &middot; {len(early)} early signals
     &middot; every one linked to its stored measurement. <span style="color:var(--text-4)">[mockup: {toggle}]</span></p>
</div>
<div class="fx-themes">{theme_btns}</div>
<input id="fx-q" class="fx-search" type="search" placeholder="Search findings — e.g. AV1, set-top box, AI, graphics card"
       aria-label="Search findings">
<div class="fx-facets">{"".join(facet_rows)}</div>
<p id="fx-status" class="fx-status" hidden><span></span><button type="button" id="fx-clear">clear filters</button></p>
<section aria-label="Findings">{main_cards}
  <p id="fx-main-empty" class="fx-empty" hidden>No repeated findings match &mdash; check the early signals below.</p>
</section>
<details class="fx-early">
  <summary><b>Early signals</b> (<span id="fx-early-count">{len(early)}</span>) &mdash; measured, but not yet repeated {min_n}&times;</summary>
  <p class="fx-early-note">These are real, published measurements, but each rests on fewer than {min_n} repeats.
     We show what we saw and why it matters &mdash; not a headline number &mdash; until the result is repeated.
     The full numbers, limits and raw data are one click away.</p>
  {early_cards}
</details>
<script>{_JS}</script>
"""


def _detail_html(slug: str, min_n: int) -> str | None:
    e = html_lib.escape
    taxonomy = _load_yaml(_TAXONOMY_PATH)
    entries = {f.slug: (f, ov, early) for f, ov, early in _entries(min_n)}
    if slug not in entries:
        return None
    f, ov, early = entries[slug]
    dot, word, meaning = _CONF_PLAIN.get(f.confidence, ("·", "", ""))
    theme = taxonomy.get("theme", {}).get("values", {}).get(ov.get("theme", ""), {})
    n = ov.get("n_runs")
    back = f'{_PREFIX}/findings?min_n={min_n}'

    if early:
        badge = (f'<span class="fx-pill">Early signal &middot; n={e(str(n))}</span> '
                 f'<span class="fx-nchip">below the n={min_n} bar</span>')
    else:
        badge = (f'<span class="fx-pill">{dot} {e(word)} &middot; {e(meaning)}</span> '
                 f'<span class="fx-key">{e(ov.get("key_number", ""))}</span>')

    caveats = "".join(f"<li>{findings_mod.md_to_html(c)}</li>" for c in f.caveats)
    sources = "".join(
        f'<li><a href="{e(findings_mod.result_download_url(r))}">{e(r)}</a> (JSON)</li>'
        for r in f.source_result_ids)
    related = ""
    for r in f.related_findings or []:
        if r in entries:
            rf, rov, _ = entries[r]
            related += (f'<li><a href="{_PREFIX}/findings/{e(r)}?min_n={min_n}">'
                        f'{e(rov.get("plain_headline") or rf.headline)}</a></li>')
    tags = " ".join(f'<span class="fx-tag">{e(_tag_label(taxonomy, t))}</span>' for t in ov.get("tags", []))

    return f"""
<div class="fx-detail">
<p class="fx-mono"><a href="{back}">&larr; All findings</a> &middot; {e(theme.get("label", ""))}</p>
<h1>{e(ov.get("plain_headline") or f.headline)}</h1>
<div class="fx-meta">{badge}</div>

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

<h2>What this covers &mdash; and doesn't</h2>
<p>{e(f.scope)}</p>
{f"<h2>Limitations</h2><ul>{caveats}</ul>" if caveats else ""}

<h2>Raw data</h2>
<ul>{sources}</ul>
<p class="fx-mono">Method: <a href="{e(f.methodology_ref)}">{e(f.methodology_ref)}</a> &middot;
   Today's live page (with embedded measurement cards): <a href="/findings/{e(f.slug)}">/findings/{e(f.slug)}</a></p>

<details><summary style="cursor:pointer;color:var(--text-2);margin-top:1.5rem">Full analysis</summary>
{findings_mod.md_to_html(f.body_md)}
</details>

{f"<h2>Related findings</h2><ul>{related}</ul>" if related else ""}
<p style="margin-top:1.5rem">{tags}</p>
</div>
"""


def _page(request: Request, title: str, body: str) -> HTMLResponse:
    return HTMLResponse(ui.render_page(
        request, f"[MOCKUP] {title}", _WATERMARK + body,
        styles=_MOCK_STYLES + _STYLES, head=_NOINDEX, back=False))


def _min_n(request: Request) -> int:
    try:
        return max(1, int(request.query_params.get("min_n", _DEFAULT_MIN_N)))
    except ValueError:
        return _DEFAULT_MIN_N


@router.get(_PREFIX + "/findings", response_class=HTMLResponse,
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def mockup_findings_catalog(request: Request):
    return _page(request, "Findings", _catalog_html(_min_n(request)))


@router.get(_PREFIX + "/findings/{slug}", response_class=HTMLResponse,
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def mockup_finding_detail(request: Request, slug: str):
    body = _detail_html(slug, _min_n(request))
    if body is None:
        return HTMLResponse("Not found", status_code=404)
    return _page(request, "Finding", body)
