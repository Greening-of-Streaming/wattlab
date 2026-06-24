"""
Findings catalog routes — CR-054/055/056 (+ the S37 scoped source carve-out).

/findings (catalog), /findings/{slug} (one finding), and
/findings/source/… (cited-result JSON, visitor_key=None for published
sources only). Deliberately chrome-less pages (S41 decision) — they build
their own shells from ui.py pieces. Feature-flagged via settings
`findings_enabled`. Phase 3 per-feature route module.
"""
import html as html_lib
import io
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

import findings as findings_mod
import settings as cfg
import version
from capabilities import requires, PUBLIC_PAGE
from persist import load_result
from ui import _BACK, _BASE_STYLES, _CARBON_JS, _RESULT_JS

router = APIRouter()


# --- CR-054: Findings catalog (one worked example, no nav promotion) ---
# Feature-flagged via settings.findings_enabled. When False, the route
# returns 404 (undiscoverable). No links to /findings/* exist anywhere
# in OWL until CR-055 ships the catalog index with explicit lab review.
# Rollback path: flip settings.findings_enabled to False — single bool.

_CONFIDENCE_DOT   = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
_CONFIDENCE_LABEL = {"green": "Repeatable", "yellow": "Indicative", "red": "Below noise floor"}


def _finding_page_html(f, public_base_url: str) -> str:
    """Render a finding page at live-run fidelity.

    Server-side renders the publication shell (headline, citation block,
    scope, caveats, analysis prose). The source measurement card is
    hydrated client-side by fetching the persisted result JSON and
    calling the existing shared renderer (window.wlRenderVideoCard /
    wlRenderLLMCard / wlRenderImageCard / wlRenderRagCard) — the same
    component used by live runs and the /results expand-row, so visitors
    see the measurement at live-run fidelity, not a thin summary.

    See CR-054 maintainability invariants — this is the ONE renderer
    that backs every finding page. New findings = new .md files, never
    new Python.
    """
    e = html_lib.escape
    conf_dot   = _CONFIDENCE_DOT.get(f.confidence, "·")
    conf_label = _CONFIDENCE_LABEL.get(f.confidence, "")

    canonical_url = f"{public_base_url.rstrip('/')}/findings/{f.slug}"

    cite_text = (
        f"OWL Finding: {f.headline}\n"
        f"  measured {f.first_measured}"
        + (f", refined {f.last_refined}" if f.last_refined != f.first_measured else "")
        + f"\n  {canonical_url}\n"
        f"  Greening of Streaming — wattlab.greeningofstreaming.org"
    )

    supersedes_html = ""
    if f.supersedes:
        supersedes_html = (
            f'<div style="background:var(--accent-soft);padding:0.5rem 0.75rem;'
            f'border-left:3px solid var(--accent);margin-bottom:1rem;font-size:0.85rem">'
            f'Supersedes earlier reading: '
            f'<a href="/findings/{e(f.supersedes)}" style="color:var(--accent)">{e(f.supersedes)}</a>'
            f'</div>'
        )

    embed_blocks = []
    for i, rid in enumerate(f.source_result_ids):
        type_ = rid.split("/", 1)[0]
        embed_blocks.append(
            f'<div class="finding-embed" id="finding-embed-{i}" '
            f'data-result-id="{e(rid)}" data-type="{e(type_)}" '
            f'style="margin:1rem 0">'
            f'<div class="loading" style="color:var(--text-3);'
            f'font-family:monospace;font-size:0.8rem">'
            f'Loading measurement {e(rid)}…</div></div>'
        )
    embeds_html = "\n".join(embed_blocks)

    caveats_html = ""
    if f.caveats:
        caveats_html = (
            '<section style="margin-top:1.25rem">'
            '<h3 style="margin-bottom:0.4rem;color:var(--warn);font-size:0.8rem;'
            'text-transform:uppercase;letter-spacing:0.06em;font-weight:600">Caveats</h3>'
            '<ul style="margin:0;padding-left:1.25rem">'
            + "".join(
                f'<li style="margin:0.3rem 0;color:var(--text-2);font-size:0.9rem">{e(c)}</li>'
                for c in f.caveats
            )
            + '</ul></section>'
        )

    tags_html = ""
    if f.tags:
        chips = "".join(
            f'<span style="display:inline-block;padding:0.1rem 0.45rem;'
            f'border:1px solid var(--border);border-radius:3px;'
            f'font-size:0.68rem;color:var(--text-3);margin:0 0.25rem 0.25rem 0;'
            f'font-family:monospace">{e(t)}</span>'
            for t in f.tags
        )
        tags_html = f'<div style="margin-top:0.75rem">{chips}</div>'

    methodology_link = ""
    if f.methodology_ref:
        # methodology_ref like 'docs/wattlab_traffic_light_confidence.md' — show as label,
        # link to /methodology page for now (docs/ files aren't served raw).
        methodology_link = (
            f'<div style="margin-top:1rem;font-family:monospace;font-size:0.78rem;color:var(--text-3)">'
            f'<a href="/methodology" style="color:var(--accent)">Methodology →</a>'
            f' <span style="color:var(--text-5)">({e(f.methodology_ref)})</span>'
            f'</div>'
        )

    raw_links = "".join(
        f'<div>raw measurement: <a href="{e(findings_mod.result_download_url(rid))}" '
        f'style="color:var(--text-3)">{e(rid)}</a></div>'
        for rid in f.source_result_ids
    )

    body_html = findings_mod.md_to_html(f.body_md)

    # JS that hydrates each embedded measurement via the shared renderer.
    # Uses the same wlRender{Type}Card dispatch as the /results expand-row.
    # Fetches are awaited sequentially — nginx caps concurrent connections
    # per IP at 3 (limit_conn wattlab_conn 3 on `location /`), so a finding
    # citing 6 result_ids would 429 half its embeds if these fired in
    # parallel. Sequential is slow but visible: the per-embed "Loading…"
    # text gives clear progression and matches the lab-look fidelity goal.
    hydrate_js = """
<script>
// Calibration sweeps (parity.py) are not single measurements — they are a
// fingerprinted matrix of encodes (codec x profile x bitrate x clip). There is
// no per-job card to reuse, so this renderer summarises the artifact: what ran,
// on what hardware, and how to get the raw rows. Defensive against missing keys.
window.wlRenderCalibrationCard = function(o){
  const d = (o && o.result) || {};
  const fp = d.fingerprint || {};
  const proto = d.protocol || {};
  const rows = Array.isArray(d.rows) ? d.rows : [];
  const codecs = [...new Set(rows.map(r => r.codec).filter(Boolean))].sort();
  const clips = (proto.clips || [...new Set(rows.map(r => r.clip).filter(Boolean))]);
  const profiles = [...new Set(rows.map(r => r.profile).filter(Boolean))].sort();
  const esc = s => String(s == null ? '' : s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
  const kpi = (v, l) => '<div class="kpi"><div class="val">' + esc(v) + '</div><div class="lbl">' + esc(l) + '</div></div>';
  const gpu = (fp.gpu && fp.gpu.name) || '—';
  const cpu = (fp.cpu && fp.cpu.model) || '—';
  return '<div class="result-card">'
    + '<div class="headline">Encode-parity calibration sweep — ' + rows.length + ' encodes'
    + (d.complete ? '' : ' (incomplete)') + '</div>'
    + '<div class="kpi-row">'
    + kpi(rows.length, 'rows (codec x profile x bitrate x clip)')
    + kpi(codecs.join(' / ') || '—', 'codecs')
    + kpi(clips.length, 'sources')
    + kpi(profiles.join(' / ') || '—', 'encode profiles')
    + '</div>'
    + '<div class="prev-note">' + esc(gpu) + ' (NVENC) · ' + esc(cpu)
    + ' · ' + esc(proto.scale || '1080p') + ' · ' + esc(d.generated_at || '') + '</div>'
    + '<div class="conf-badge">Matrix artifact — download the raw rows below for per-encode Wh/min, VMAF, bitrate and confidence.</div>'
    + '</div>';
};
(async function hydrateFindingEmbeds(){
  const els = document.querySelectorAll('.finding-embed');
  const renderers = {
    video: window.wlRenderVideoCard,
    llm: window.wlRenderLLMCard,
    image: window.wlRenderImageCard,
    rag: window.wlRenderRAGCard,
    calibration: window.wlRenderCalibrationCard,
    enhance: window.wlRenderEnhanceCard
  };
  for (const el of els) {
    const rid = el.dataset.resultId;
    const type = el.dataset.type;
    const jobId = rid.split('/')[1].split('_').slice(-1)[0];
    const renderer = renderers[type];
    if (!renderer) {
      el.querySelector('.loading').textContent = 'no renderer for type=' + type;
      continue;
    }
    try {
      // Scoped CR-026 carve-out: finding sources are lab-measured
      // (visitor_key=None) and the generic /results endpoint would 404 them
      // for any non-Lab visitor. /findings/source/* serves the same data
      // unfiltered, but only for results a published finding actually cites.
      const r = await fetch('/findings/source/' + type + '/' + jobId + '/download.json');
      if (!r.ok) {
        el.querySelector('.loading').textContent =
          'could not load ' + rid + ' (HTTP ' + r.status + ')';
        continue;
      }
      const data = await r.json();
      el.innerHTML = renderer({result: data, isPrev: true, savedAt: data.saved_at});
    } catch(e) {
      el.querySelector('.loading').textContent = 'error: ' + e.message;
    }
  }
})();
</script>
"""

    return (
        '<!DOCTYPE html><html><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{e(f.headline[:80])} — OWL Finding</title>'
        f'<meta name="description" content="{e(f.claim_short)}">'
        f'{_BASE_STYLES}'
        '<style>'
          '.finding-wrap{max-width:880px;margin:1.5rem auto;padding:0 1rem;color:var(--text);background:var(--bg)}'
          '.finding-hero{border-bottom:1px solid var(--border);padding-bottom:0.85rem;margin-bottom:1rem}'
          '.finding-headline{font-size:1.25rem;line-height:1.4;margin:0 0 0.4rem 0;color:var(--text);font-weight:600}'
          '.finding-meta{color:var(--text-3);font-family:monospace;font-size:0.78rem}'
          '.finding-claim{background:var(--panel);padding:0.65rem 0.85rem;border-left:3px solid var(--accent);font-family:monospace;font-size:0.85rem;margin:0.85rem 0;color:var(--text-2);overflow-x:auto}'
          '.finding-scope{font-family:monospace;font-size:0.75rem;color:var(--text-4);margin:0.6rem 0;line-height:1.5}'
          '.cite-box{background:var(--panel-2);border:1px solid var(--border);padding:0.5rem 0.7rem;font-family:monospace;font-size:0.75rem;color:var(--text-3);white-space:pre-wrap;margin:0.85rem 0;position:relative}'
          '.cite-copy-btn{position:absolute;top:0.3rem;right:0.3rem;background:var(--panel);border:1px solid var(--border-3);color:var(--accent);padding:0.1rem 0.45rem;font-family:monospace;font-size:0.7rem;cursor:pointer}'
          '.cite-copy-btn:hover{background:var(--accent-soft)}'
          '.section-label{font-size:0.75rem;color:var(--text-3);text-transform:uppercase;letter-spacing:0.06em;margin:1.25rem 0 0.4rem 0;font-weight:600}'
          '.finding-prose h2{font-size:0.9rem;color:var(--accent);margin:1.25rem 0 0.4rem 0;text-transform:uppercase;letter-spacing:0.06em;font-weight:600}'
          '.finding-prose h3{font-size:0.9rem;color:var(--text-2);margin:1rem 0 0.3rem 0;font-weight:600}'
          '.finding-prose p{margin:0.55rem 0;color:var(--text);line-height:1.6}'
          '.finding-prose ul{margin:0.4rem 0;padding-left:1.25rem}'
          '.finding-prose li{margin:0.3rem 0;color:var(--text);line-height:1.55}'
          '.finding-prose code{background:var(--panel);padding:0.08rem 0.3rem;font-size:0.85em;color:var(--accent)}'
          '.finding-prose strong{color:var(--text)}'
          '.finding-footer{margin-top:1.5rem;padding-top:0.85rem;border-top:1px solid var(--border);font-size:0.72rem;color:var(--text-4);font-family:monospace;line-height:1.7}'
          '.finding-footer a{color:var(--text-3);text-decoration:underline}'
          # Embedded source-measurement cards reuse the shared wl-result.js
          # renderers, whose classes are styled per page — same rules as
          # /demo's _DEMO_STYLES card block, sans the f-string brace doubling.
          '.result-card{border:1px solid var(--border-2);padding:1.5rem;margin-top:1.5rem}'
          '.result-card .headline{font-size:1rem;color:var(--text);line-height:1.6;margin-bottom:1rem}'
          '.kpi-row{display:flex;gap:1.5rem;flex-wrap:wrap;margin-bottom:1rem}'
          '.kpi{flex:1;min-width:120px}'
          '.kpi .val{font-family:monospace;font-size:1.4rem;color:var(--accent)}'
          '.kpi .lbl{font-size:0.72rem;color:var(--text-4);margin-top:0.2rem}'
          '.conf-badge{display:inline-block;font-size:0.75rem;color:var(--text-3);margin-top:0.5rem}'
          '.prev-note{color:var(--text-5);font-size:0.75rem;font-family:monospace;margin-top:0.5rem}'
        '</style>'
        '</head><body style="background:var(--bg)">'
        f'<div class="finding-wrap">'
          # Breadcrumb back-nav — same palette as the site-wide _BACK chrome,
          # but routes to the findings catalog (the finding's natural parent)
          # as well as Home, so a finding page is no longer a dead-end.
          f'<div style="margin-bottom:1.25rem;font-size:0.82rem;color:var(--text-3)">'
            f'<a href="/" style="color:var(--text-3);text-decoration:none" '
            f'onmouseover="this.style.color=\'#00ff99\'" onmouseout="this.style.color=\'#777\'">'
            f'<img src="/static/owl.svg" alt="OWL" '
            f'style="height:18px;width:18px;vertical-align:middle;margin-right:0.3rem">OWL</a>'
            f'<span style="color:var(--text-5);margin:0 0.5rem">/</span>'
            f'<a href="/findings" style="color:var(--text-3);text-decoration:none" '
            f'onmouseover="this.style.color=\'#00ff99\'" onmouseout="this.style.color=\'#777\'">'
            f'&larr; All findings</a>'
          f'</div>'
          f'{supersedes_html}'
          f'<section class="finding-hero">'
            f'<h1 class="finding-headline">{e(f.headline)}</h1>'
            f'<div class="finding-meta">'
              f'<span style="color:var(--accent)">{conf_dot}</span> {e(conf_label)} · '
              f'measured {e(f.first_measured)}'
              + ('' if f.last_refined == f.first_measured
                 else f' · refined {e(f.last_refined)}')
              + f' · v{f.version}'
            f'</div>'
          f'</section>'
          f'<div class="finding-claim">{e(f.claim_short)}</div>'
          f'<div class="finding-scope">SCOPE: {e(f.scope)}</div>'
          f'<div class="cite-box">'
            f'<button class="cite-copy-btn" '
            f'onclick="navigator.clipboard.writeText(this.parentElement.querySelector(\'.cite-text\').textContent).then(()=>{{this.textContent=\'copied\'}})">copy</button>'
            f'<span class="cite-text">{e(cite_text)}</span>'
          f'</div>'
          f'<div class="section-label">Source measurement</div>'
          f'{embeds_html}'
          f'{caveats_html}'
          f'<section class="finding-prose" style="margin-top:1.25rem">{body_html}</section>'
          f'{methodology_link}'
          f'{tags_html}'
          f'<div class="finding-footer">'
            f'<div>permalink: <a href="/findings/{e(f.slug)}">{e(canonical_url)}</a></div>'
            f'{raw_links}'
            f'<div style="margin-top:0.5rem;color:var(--text-5)">'
            f'OWL · Greening of Streaming · {version.version_string()}'
            f'</div>'
          f'</div>'
        f'</div>'
        # _CARBON_JS defines window.wlCarbonStrip, which the card renderers
        # call inline; without it the embedded measurement renders but the
        # carbon strip throws "wlCarbonStrip is not defined" in the console
        # and breaks the card's bottom block.
        f'{_CARBON_JS}'
        f'{_RESULT_JS}'
        f'{hydrate_js}'
        f'</body></html>'
    )


def _findings_catalog_rows_html(items, link_class: str = "") -> str:
    """Render a list of findings as catalog rows. Shared between the
    `/findings` index page and the /demo Findings step preview, so the
    row layout never diverges. Each row: confidence dot + headline link
    + version/date on the right + claim_short snippet underneath.

    `items` is a list of Finding objects (use findings_mod.list_all() or
    a sliced preview). Empty list → returns an empty string so callers
    can compose their own empty-state copy.
    """
    if not items:
        return ""
    e = html_lib.escape
    rows = []
    for f in items:
        dot = _CONFIDENCE_DOT.get(f.confidence, "·")
        date_label = e(f.last_refined)
        if f.last_refined != f.first_measured:
            date_label = f"{e(f.last_refined)} <span style=\"color:var(--text-5)\">(first {e(f.first_measured)})</span>"
        rows.append(
            f'<a class="finding-row {link_class}" href="/findings/{e(f.slug)}">'
              f'<div class="finding-row-top">'
                f'<span class="finding-row-dot">{dot}</span>'
                f'<span class="finding-row-headline">{e(f.headline)}</span>'
                f'<span class="finding-row-date">v{f.version} · {date_label}</span>'
              f'</div>'
              f'<div class="finding-row-claim">{e(f.claim_short)}</div>'
            f'</a>'
        )
    return "\n".join(rows)


# Shared CSS for finding-row presentation; used by `/findings` and the
# /demo Findings step. Loading it twice is harmless (same selectors).
_FINDINGS_CATALOG_CSS = (
    '<style>'
      '.finding-row{display:block;text-decoration:none;color:inherit;'
        'border:1px solid var(--border);border-left:3px solid var(--border-3);'
        'padding:0.7rem 0.85rem;margin:0.5rem 0;background:var(--panel-2);'
        'transition:border-color 0.15s,background 0.15s}'
      '.finding-row:hover{border-color:var(--accent-soft);'
        'border-left-color:var(--accent);background:var(--panel)}'
      '.finding-row-top{display:flex;align-items:baseline;gap:0.5rem;'
        'flex-wrap:wrap}'
      '.finding-row-dot{flex:0 0 auto;font-size:0.85rem}'
      '.finding-row-headline{flex:1;color:var(--text);font-size:0.92rem;'
        'line-height:1.45;font-weight:500;min-width:200px}'
      '.finding-row-date{flex:0 0 auto;color:var(--text-4);font-family:monospace;'
        'font-size:0.72rem;white-space:nowrap}'
      '.finding-row-claim{margin-top:0.35rem;color:var(--text-3);'
        'font-family:monospace;font-size:0.76rem;line-height:1.5;'
        'padding-left:1.5rem}'
    '</style>'
)


def _findings_catalog_page_html() -> str:
    """CR-056 — Server-side render of /findings catalog index.

    Lists every finding under docs/findings/ as a row (confidence dot +
    headline + version/date + claim_short). Sorted by last_refined desc
    so newest-or-refined findings rise. Empty-catalog state is honest —
    'no findings yet' rather than scaffolding for one that never lands.
    """
    e = html_lib.escape
    items = findings_mod.list_all()
    items.sort(key=lambda f: f.last_refined, reverse=True)

    rows_html = _findings_catalog_rows_html(items)
    if not items:
        body_inner = (
            '<p style="color:var(--text-3);font-size:0.85rem;'
            'border-left:2px solid var(--border-3);padding-left:1rem">'
            'No findings published yet. As OWL measurements accumulate, '
            'curated findings will land here.</p>'
        )
    else:
        body_inner = rows_html

    return (
        '<!DOCTYPE html><html><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>OWL — Findings (Beta)</title>'
        '<meta name="description" content="OWL findings — citable energy measurements from the Greening of Streaming bench.">'
        f'{_BASE_STYLES}'
        f'{_FINDINGS_CATALOG_CSS}'
        '<style>'
          '.findings-wrap{max-width:880px;margin:1.5rem auto;padding:0 1rem;color:var(--text);background:var(--bg)}'
          '.findings-hero{border-bottom:1px solid var(--border);padding-bottom:0.85rem;margin-bottom:1rem}'
          '.findings-title{font-size:1.25rem;line-height:1.4;margin:0 0 0.4rem 0;color:var(--accent);font-weight:600}'
          '.findings-beta{display:inline-block;margin-left:0.5rem;vertical-align:middle;'
            'font-family:monospace;font-size:0.62rem;font-weight:600;letter-spacing:0.04em;'
            'text-transform:uppercase;color:var(--warn);border:1px solid var(--border-3);'
            'background:rgba(255,170,0,0.06);padding:0.15rem 0.45rem;border-radius:2px}'
          '.findings-tagline{color:var(--text-3);font-family:monospace;font-size:0.78rem;line-height:1.55}'
          '.findings-footer{margin-top:1.5rem;padding-top:0.85rem;border-top:1px solid var(--border);font-size:0.72rem;color:var(--text-4);font-family:monospace}'
        '</style>'
        '</head><body style="background:var(--bg)">'
        '<div class="findings-wrap">'
          f'{_BACK}'
          '<section class="findings-hero">'
            '<h1 class="findings-title">OWL Findings'
            '<span class="findings-beta">Beta · under development</span></h1>'
            '<div class="findings-tagline">'
              'Curated, citable measurements from the Greening of Streaming bench. '
              'Each finding links to its source measurement at live-run fidelity, with '
              'scope, methodology, and a copy-paste citation.'
            '</div>'
          '</section>'
          f'{body_inner}'
          '<div class="findings-footer">'
            f'OWL · Greening of Streaming · {e(str(len(items)))} '
            f'finding{"s" if len(items) != 1 else ""} · {version.version_string()}'
          '</div>'
        '</div>'
        '</body></html>'
    )


@router.get("/findings", response_class=HTMLResponse,
         dependencies=[Depends(requires(PUBLIC_PAGE))])
async def findings_catalog_page(request: Request):
    """CR-056 — catalog index. Same `findings_enabled` flag as the
    individual /findings/<slug> route — flipping it false makes the
    whole feature disappear (route 404 + /video beta link gone +
    /demo step falls back to session-echo)."""
    s = cfg.load()
    if not s.get("findings_enabled", False):
        return HTMLResponse("Not found", status_code=404)
    return HTMLResponse(_findings_catalog_page_html())


@router.get("/findings/{slug}", response_class=HTMLResponse,
         dependencies=[Depends(requires(PUBLIC_PAGE))])
async def finding_page(slug: str, request: Request):
    """CR-054 — render one finding by slug. Feature-flagged; returns 404
    when settings.findings_enabled is False. No nav links point here yet
    (no catalog page until CR-055); reachable only by direct URL during
    the lab-review window."""
    s = cfg.load()
    if not s.get("findings_enabled", False):
        return HTMLResponse("Not found", status_code=404)
    try:
        f = findings_mod.load(slug)
    except findings_mod.FindingError as ex:
        # Malformed finding file — surface clearly so editors can fix.
        return HTMLResponse(
            f"<pre style='color:#ff4400;padding:1rem'>Finding {html_lib.escape(slug)} "
            f"failed to load: {html_lib.escape(str(ex))}</pre>",
            status_code=500,
        )
    if f is None:
        return HTMLResponse("Not found", status_code=404)

    # Canonical URL — prefer the live host; fall back to a relative-friendly default.
    host = request.headers.get("host", "")
    scheme = "https" if "greeningofstreaming.org" in host else "http"
    public_base = f"{scheme}://{host}" if host else ""
    return HTMLResponse(_finding_page_html(f, public_base))


# Deep fix for the recurring findings-embed 404 (e.g. "could not load
# video/2328a8ab (HTTP 404)").
#
# A published finding cites lab-measured source results, which carry
# visitor_key=None (or the owner's key). The generic
# /results/.../download.json applies CR-026 own-jobs scoping, so a non-Lab
# caller (Anonymous 'a:<ip>' / Member 'm:<email>') never matches the lab
# record and ALWAYS gets a 404 — for every embed, on every visit. Earlier
# fixes chased the job_id parsing and the markdown ids; the real wall is the
# visitor filter, which is why it kept coming back.
#
# This endpoint is the structural fix: it loads with visitor_key=None (like
# the /demo/last carve-out), but ONLY for a result that a published finding
# actually cites — so it is a *scoped* exception, not a general CR-026 bypass.
# A finding source is published-by-definition and must be visible to every
# visitor regardless of who measured it.
@router.get("/findings/source/{job_type}/{job_id}/download.json",
         dependencies=[Depends(requires(PUBLIC_PAGE))])
async def finding_source_result(job_type: str, job_id: str):
    # `calibration` is the fingerprint-keyed sweep artifact (parity.py), not a
    # per-job result — it is loaded by file path below, not via load_result.
    if job_type not in ("video", "llm", "image", "enhance", "calibration"):
        return JSONResponse({"error": "Invalid type"}, status_code=400)
    # Map (type, token) → full cited id, with token normalised the same way the
    # embed JS / result_download_url do (bare job_id = last underscore-separated
    # segment), so date-prefixed legacy ids match too. We keep the FULL id so a
    # calibration filename (underscores throughout) can be resolved unambiguously.
    cited: dict[tuple[str, str], str] = {}
    for f in findings_mod.list_all():
        for rid in f.source_result_ids:
            if "/" not in rid:
                continue
            t, tail = rid.split("/", 1)
            cited[(t, tail.split("_")[-1])] = rid
    full_id = cited.get((job_type, job_id.split("_")[-1]))
    if full_id is None:
        return JSONResponse({"error": "Not a cited finding source"}, status_code=404)
    if job_type == "calibration":
        # Resolve by the full cited id (not the truncated job_id) — the date
        # tail alone could glob-match a sibling sweep on the same day.
        path = findings_mod.resolve_result_path(full_id)
        data = json.loads(path.read_text(encoding="utf-8")) if path else None
    else:
        data = load_result(job_type, job_id, visitor_key=None)
    if not data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    content = json.dumps(data, indent=2)
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="application/json",
    )
