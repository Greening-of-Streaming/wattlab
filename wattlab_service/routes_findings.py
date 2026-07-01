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

import analytics
import feedback as feedback_mod
import findings as findings_mod
import settings as cfg
import version
from audience import tier as resolve_tier
from capabilities import (
    requires, can, PUBLIC_PAGE, CREATE_FINDING, FEEDBACK_SUBMIT, FEEDBACK_MODERATE,
)
from persist import load_result
from ui import _BACK, _BASE_STYLES, _CARBON_JS, _RESULT_JS


def _client_ip(request: Request) -> str:
    """Origin IP the same way audience.tier resolves it (nginx X-Real-IP,
    falling back to the socket peer). Used only to derive the pseudonymous
    feedback rate-limit token — never stored raw."""
    return request.headers.get("x-real-ip") or (
        request.client.host if request.client else ""
    )


def _member_email(request: Request) -> str | None:
    """Signed-in member email, or None. Lazy import keeps auth off the hot path."""
    try:
        import auth as _auth
        return _auth.member_email_from_request(request)
    except Exception:
        return None

router = APIRouter()


# --- CR-054: Findings catalog (one worked example, no nav promotion) ---
# Feature-flagged via settings.findings_enabled. When False, the route
# returns 404 (undiscoverable). No links to /findings/* exist anywhere
# in OWL until CR-055 ships the catalog index with explicit lab review.
# Rollback path: flip settings.findings_enabled to False — single bool.

_CONFIDENCE_DOT   = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
_CONFIDENCE_LABEL = {"green": "Repeatable", "yellow": "Indicative", "red": "Below noise floor"}

# review_status is a SEPARATE editorial axis from the statistical confidence dot
# (see findings.py). Rendered as a text pill with its own icon/vocabulary so the
# two never read as the same traffic-light — a reviewer must be able to tell
# "statistically repeatable" from "signed off by a lab committee" at a glance.
_REVIEW_STATUS_PILL = {
    # status: (icon, label, css-var for accent colour)
    "draft":       ("✎", "Draft — unreviewed", "--warn"),
    "for-comment": ("💬", "Open for comment",   "--accent"),
    "validated":   ("✓", "Lab-validated",       "--accent"),
}


# Editorial impact/actionability (2026-07-01 lab call): a THIRD axis, separate
# from the confidence dot and the review-status pill. Rendered as a compact
# filled-diamond marker whose main job is to SORT the catalog (strongest first)
# for the dribble rollout — deliberately small so the row stays uncluttered.
_IMPACT_LABEL = {3: "Actionable — can change a setting/setup",
                 2: "Original finding, action is conditional/strategic",
                 1: "Explanatory measurement with a learning"}


def _impact_marker_html(impact) -> str:
    if not impact:
        return ""
    filled = "◆" * impact
    empty = "◇" * (3 - impact)
    label = _IMPACT_LABEL.get(impact, "")
    return (
        f'<span class="impact-marker" title="Impact {impact}/3 — {html_lib.escape(label)}">'
        f'{filled}{empty}</span>'
    )


def _review_status_pill_html(review_status: str) -> str:
    """A small text pill for the editorial review status. Deliberately not a
    coloured dot — that vocabulary belongs to statistical confidence."""
    icon, label, colour_var = _REVIEW_STATUS_PILL.get(
        review_status, _REVIEW_STATUS_PILL["draft"]
    )
    return (
        f'<span class="review-pill review-pill-{html_lib.escape(review_status)}" '
        f'style="border-color:var({colour_var});color:var({colour_var})">'
        f'{icon} {html_lib.escape(label)}</span>'
    )


# --- Moderated feedback / "Ask OWL" box (2026-07-01 lab call) --------------
# One submission box serves both "comment on this finding" (slug set) and
# "ask a question" (slug None). It is read-only-in, write-only-out: the public
# page shows the box, never other people's notes. Submissions go to the private
# Lab queue at /findings/feedback/queue. A hidden honeypot field + a server-side
# per-subnet rate limit stand in for a third-party CAPTCHA.

_FEEDBACK_CSS = (
    '<style>'
      '.fb-box{margin-top:1.5rem;border:1px solid var(--border);border-left:3px solid var(--border-3);'
        'background:var(--panel-2);padding:0.9rem 1rem}'
      '.fb-box h3{margin:0 0 0.3rem 0;font-size:0.8rem;text-transform:uppercase;letter-spacing:0.06em;'
        'color:var(--text-3);font-weight:600}'
      '.fb-box .fb-intro{color:var(--text-4);font-size:0.78rem;font-family:monospace;line-height:1.5;'
        'margin:0 0 0.6rem 0}'
      '.fb-form{display:flex;flex-direction:column;gap:0.5rem}'
      '.fb-form select,.fb-form textarea{background:var(--panel);border:1px solid var(--border-3);'
        'color:var(--text);font-family:monospace;font-size:0.82rem;padding:0.4rem 0.5rem;border-radius:3px}'
      '.fb-form textarea{min-height:5rem;resize:vertical}'
      # Honeypot: pulled off-screen, hidden from assistive tech. A human never
      # sees or fills it; a naive bot will — filled → silently dropped.
      '.fb-hp{position:absolute;left:-10000px;width:1px;height:1px;overflow:hidden}'
      '.fb-form button{align-self:flex-start;background:var(--panel);border:1px solid var(--accent);'
        'color:var(--accent);font-family:monospace;font-size:0.8rem;padding:0.35rem 0.8rem;'
        'border-radius:3px;cursor:pointer}'
      '.fb-form button:hover:not(:disabled){background:var(--accent-soft)}'
      '.fb-form button:disabled{opacity:0.5;cursor:default}'
      '.fb-status{font-family:monospace;font-size:0.76rem;color:var(--text-3);min-height:1em}'
    '</style>'
)

_FEEDBACK_JS = """
<script>
async function wlSubmitFeedback(ev){
  ev.preventDefault();
  const form = ev.target;
  const status = form.querySelector('.fb-status');
  const btn = form.querySelector('button[type=submit]');
  btn.disabled = true; status.textContent = 'sending…';
  try{
    const r = await fetch('/findings/feedback', {method:'POST', body:new FormData(form)});
    let j = {}; try { j = await r.json(); } catch(e) {}
    if (r.ok && j.ok){
      form.reset();
      status.textContent = 'Thanks — the lab will review this. (Not shown publicly.)';
    } else {
      status.textContent = (j && j.error) ? j.error : ('could not send (HTTP ' + r.status + ')');
      btn.disabled = false;
    }
  } catch(e){
    status.textContent = 'network error — please try again';
    btn.disabled = false;
  }
  return false;
}
</script>
"""


def _feedback_box_html(slug: str | None = None) -> str:
    """The public submission box. `slug` set → 'comment on this finding';
    None → general 'Ask OWL' box (catalog page)."""
    e = html_lib.escape
    slug_val = e(slug) if slug else ""
    if slug:
        heading = "Comment or question"
        intro = ("Spotted an error, or want us to measure something? Every note goes "
                 "to the lab for review — it is not published on this page.")
        comment_label = "Comment on this finding"
    else:
        heading = "Ask OWL"
        intro = ("Want us to measure something, or have a question about the method? "
                 "Send it to the lab — we read every one. Not published here.")
        comment_label = "General comment"
    return (
        '<section class="fb-box">'
          f'<h3>{heading}</h3>'
          f'<p class="fb-intro">{intro}</p>'
          '<form class="fb-form" onsubmit="return wlSubmitFeedback(event)">'
            f'<input type="hidden" name="slug" value="{slug_val}">'
            # Honeypot — must stay empty. Bots that autofill every field trip it.
            '<div class="fb-hp" aria-hidden="true">'
              '<label>Website<input type="text" name="website" tabindex="-1" autocomplete="off"></label>'
            '</div>'
            '<select name="kind" aria-label="Kind of note">'
              f'<option value="comment">{comment_label}</option>'
              '<option value="question">Ask a question</option>'
            '</select>'
            '<textarea name="body" maxlength="4000" required '
              'placeholder="Your comment or question…"></textarea>'
            '<button type="submit">Send to the lab</button>'
            '<span class="fb-status" role="status"></span>'
          '</form>'
        '</section>'
    )


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
(async function hydrateFindingEmbeds(){
  const els = document.querySelectorAll('.finding-embed');
  const renderers = {
    video: window.wlRenderVideoCard,
    llm: window.wlRenderLLMCard,
    image: window.wlRenderImageCard,
    rag: window.wlRenderRAGCard,
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
          '.finding-review{margin-top:0.55rem;display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap}'
          '.finding-review-note{color:var(--text-5);font-size:0.72rem;font-family:monospace}'
          '.review-pill{display:inline-block;font-family:monospace;font-size:0.7rem;font-weight:600;'
            'letter-spacing:0.03em;padding:0.15rem 0.5rem;border:1px solid var(--border-3);'
            'border-radius:3px;background:var(--panel-2);white-space:nowrap}'
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
        f'{_FEEDBACK_CSS}'
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
            f'<div class="finding-review">{_review_status_pill_html(f.review_status)}'
              f'<span class="finding-review-note">'
              f'Statistical confidence (dot) and editorial review status (pill) are '
              f'independent — see methodology.</span></div>'
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
          f'{_feedback_box_html(f.slug)}'
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
        f'{_FEEDBACK_JS}'
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
                f'{_impact_marker_html(f.impact)}'
                f'<span class="finding-row-headline">{e(f.headline)}</span>'
                f'{_review_status_pill_html(f.review_status)}'
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
      '.impact-marker{flex:0 0 auto;font-size:0.72rem;letter-spacing:0.05em;color:var(--accent);'
        'cursor:help;font-family:monospace}'
      '.finding-row-headline{flex:1;color:var(--text);font-size:0.92rem;'
        'line-height:1.45;font-weight:500;min-width:200px}'
      '.finding-row-date{flex:0 0 auto;color:var(--text-4);font-family:monospace;'
        'font-size:0.72rem;white-space:nowrap}'
      '.finding-row-claim{margin-top:0.35rem;color:var(--text-3);'
        'font-family:monospace;font-size:0.76rem;line-height:1.5;'
        'padding-left:1.5rem}'
      # Editorial review-status pill — a separate axis from the confidence dot.
      '.review-pill{flex:0 0 auto;display:inline-block;font-family:monospace;'
        'font-size:0.64rem;font-weight:600;letter-spacing:0.03em;padding:0.1rem 0.4rem;'
        'border:1px solid var(--border-3);border-radius:3px;background:var(--panel-2);'
        'white-space:nowrap}'
    '</style>'
)


def _findings_catalog_page_html(can_draft: bool = False,
                                can_moderate: bool = False,
                                open_feedback: int = 0) -> str:
    """CR-056 — Server-side render of /findings catalog index.

    Lists every finding under docs/findings/ as a row (confidence dot +
    headline + version/date + claim_short). Sorted by last_refined desc
    so newest-or-refined findings rise. Empty-catalog state is honest —
    'no findings yet' rather than scaffolding for one that never lands.

    `can_draft` (Lab only) reveals the LLM-assisted "Draft a finding"
    entry-point. It's a render-mode predicate, not a gate — the /findings/draft
    routes enforce CREATE_FINDING themselves. `can_moderate` (Lab only) reveals
    the private feedback-queue link + open-note count.
    """
    e = html_lib.escape
    items = findings_mod.list_all()
    # Strongest first: impact desc, then most-recently-refined. Unscored (None)
    # sinks to the bottom. This ordering is the "dribble strongest-first" rollout.
    items.sort(key=lambda f: (f.impact or 0, f.last_refined), reverse=True)

    ctas = []
    if can_draft:
        ctas.append(
            '<a class="findings-draft-cta" href="/findings/draft">'
            '✎ Draft a finding<span class="findings-draft-tag">Lab · AI-assisted</span></a>'
        )
    if can_moderate:
        ctas.append(
            '<a class="findings-draft-cta" href="/findings/feedback/queue">'
            f'✉ Feedback queue<span class="findings-draft-tag">Lab · '
            f'{e(str(open_feedback))} open</span></a>'
        )
    draft_cta = "".join(ctas)

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
        f'{_FEEDBACK_CSS}'
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
          '.findings-draft-cta{display:inline-flex;align-items:center;gap:0.5rem;margin-top:0.7rem;'
            'font-family:monospace;font-size:0.78rem;color:var(--accent);text-decoration:none;'
            'border:1px solid var(--border-3);border-radius:4px;padding:0.3rem 0.6rem}'
          '.findings-draft-cta:hover{background:rgba(0,255,153,0.06)}'
          '.findings-draft-tag{font-size:0.6rem;letter-spacing:0.04em;text-transform:uppercase;'
            'color:var(--text-4)}'
        '</style>'
        '</head><body style="background:var(--bg)">'
        '<div class="findings-wrap">'
          f'{_BACK}'
          '<section class="findings-hero">'
            '<h1 class="findings-title">OWL Findings'
            '<span class="findings-beta">Beta · under development</span></h1>'
            '<div class="findings-tagline">'
              'Early measurements from the Greening of Streaming bench, published for '
              'comment — not yet lab-validated. Each finding links to its source '
              'measurement at live-run fidelity, with scope, methodology, and a '
              'copy-paste citation. Tell us where we are wrong.'
            '</div>'
            f'{draft_cta}'
          '</section>'
          f'{body_inner}'
          f'{_feedback_box_html(None)}'
          '<div class="findings-footer">'
            f'OWL · Greening of Streaming · {e(str(len(items)))} '
            f'finding{"s" if len(items) != 1 else ""} · {version.version_string()}'
          '</div>'
        '</div>'
        f'{_FEEDBACK_JS}'
        '</body></html>'
    )


def _feedback_queue_html(items) -> str:
    """Lab-only moderation queue. Lists every submission (open first), with
    resolve / reopen controls. Private page — never linked publicly."""
    e = html_lib.escape
    open_items = [r for r in items if r.get("status") != "resolved"]
    done_items = [r for r in items if r.get("status") == "resolved"]

    def _row(r):
        rid = e(str(r.get("id", "")))
        slug = r.get("slug")
        target = (f'<a href="/findings/{e(slug)}" style="color:var(--accent)">{e(slug)}</a>'
                  if slug else '<span style="color:var(--text-5)">general</span>')
        resolved = r.get("status") == "resolved"
        member = e(r.get("member_email") or "")
        member_html = (f' · <span style="color:var(--text-3)">{member}</span>' if member else '')
        btn = (
            f'<button class="fbq-btn" onclick="wlFbStatus(\'{rid}\',\'open\')">reopen</button>'
            if resolved else
            f'<button class="fbq-btn" onclick="wlFbStatus(\'{rid}\',\'resolved\')">resolve</button>'
        )
        return (
            f'<div class="fbq-row{" fbq-done" if resolved else ""}" id="fbq-{rid}">'
              f'<div class="fbq-meta">'
                f'<span class="fbq-kind">{e(str(r.get("kind","")))}</span> · {target} · '
                f'{e(str(r.get("submitted_at","")))}'
                f'<span class="fbq-token"> · {e(str(r.get("visitor_token") or "—"))}</span>'
                f'{member_html}'
              f'</div>'
              f'<div class="fbq-body">{e(str(r.get("body","")))}</div>'
              f'<div class="fbq-actions">{btn}<span class="fbq-status"></span></div>'
            f'</div>'
        )

    open_html = "".join(_row(r) for r in open_items) or \
        '<p style="color:var(--text-4);font-family:monospace;font-size:0.8rem">No open notes.</p>'
    done_html = "".join(_row(r) for r in done_items)
    done_section = (
        '<h2 style="font-size:0.8rem;text-transform:uppercase;letter-spacing:0.06em;'
        'color:var(--text-4);margin:1.5rem 0 0.5rem 0">Resolved</h2>' + done_html
        if done_items else ''
    )

    return (
        '<!DOCTYPE html><html><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>OWL — Findings feedback queue (Lab)</title>'
        f'{_BASE_STYLES}'
        '<style>'
          '.fbq-wrap{max-width:880px;margin:1.5rem auto;padding:0 1rem;color:var(--text)}'
          '.fbq-row{border:1px solid var(--border);border-left:3px solid var(--accent);'
            'background:var(--panel-2);padding:0.7rem 0.85rem;margin:0.5rem 0}'
          '.fbq-done{border-left-color:var(--border-3);opacity:0.6}'
          '.fbq-meta{font-family:monospace;font-size:0.72rem;color:var(--text-4)}'
          '.fbq-kind{color:var(--accent);text-transform:uppercase}'
          '.fbq-token{color:var(--text-5)}'
          '.fbq-body{margin:0.5rem 0;color:var(--text);font-size:0.9rem;line-height:1.5;white-space:pre-wrap}'
          '.fbq-actions{display:flex;gap:0.6rem;align-items:center}'
          '.fbq-btn{background:var(--panel);border:1px solid var(--border-3);color:var(--accent);'
            'font-family:monospace;font-size:0.75rem;padding:0.25rem 0.7rem;border-radius:3px;cursor:pointer}'
          '.fbq-btn:hover{background:var(--accent-soft)}'
          '.fbq-status{font-family:monospace;font-size:0.72rem;color:var(--text-4)}'
        '</style>'
        '</head><body style="background:var(--bg)">'
        '<div class="fbq-wrap">'
          f'{_BACK}'
          '<h1 style="font-size:1.2rem;color:var(--accent);font-weight:600">'
            'Findings feedback queue'
            '<span style="font-family:monospace;font-size:0.65rem;color:var(--text-4);'
            'margin-left:0.5rem">LAB · PRIVATE</span></h1>'
          '<p style="color:var(--text-4);font-family:monospace;font-size:0.76rem;line-height:1.5">'
            'Anonymous comments and questions from the public findings pages. Not shown publicly. '
            'The token is the pseudonymised /24-subnet hash — no raw IP is stored.</p>'
          f'{open_html}'
          f'{done_section}'
        '</div>'
        '<script>'
        'async function wlFbStatus(id, status){'
          'const row = document.getElementById("fbq-"+id);'
          'const st = row.querySelector(".fbq-status"); st.textContent = "…";'
          'const fd = new FormData(); fd.append("status", status);'
          'try{'
            'const r = await fetch("/findings/feedback/"+id+"/status", {method:"POST", body:fd});'
            'if(r.ok){ location.reload(); } else { st.textContent = "error "+r.status; }'
          '}catch(e){ st.textContent = "network error"; }'
        '}'
        '</script>'
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
    t = resolve_tier(request)
    can_draft = can(t, CREATE_FINDING)
    can_moderate = can(t, FEEDBACK_MODERATE)
    open_feedback = feedback_mod.open_count() if can_moderate else 0
    return HTMLResponse(
        _findings_catalog_page_html(can_draft, can_moderate, open_feedback)
    )


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
    if job_type not in ("video", "llm", "image", "enhance"):
        return JSONResponse({"error": "Invalid type"}, status_code=400)
    # Set of (type, token) the published catalog cites, with token normalised
    # the same way the embed JS / result_download_url do (bare job_id = last
    # underscore-separated segment), so date-prefixed legacy ids match too.
    cited = set()
    for f in findings_mod.list_all():
        for rid in f.source_result_ids:
            if "/" not in rid:
                continue
            t, tail = rid.split("/", 1)
            cited.add((t, tail.split("_")[-1]))
    if (job_type, job_id.split("_")[-1]) not in cited:
        return JSONResponse({"error": "Not a cited finding source"}, status_code=404)
    data = load_result(job_type, job_id, visitor_key=None)
    if not data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    content = json.dumps(data, indent=2)
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="application/json",
    )


# --- Moderated feedback (2026-07-01 lab call) ------------------------------
# One anonymous POST endpoint backs both the per-finding "comment" box and the
# general "Ask OWL" box. Submissions go to the PRIVATE Lab queue; the public
# page never renders them. Abuse defence without a third-party CAPTCHA:
#   - honeypot form field ("website") → filled means bot → silently dropped
#   - per-subnet-token rate limit (feedback.rate_ok)
#   - server-side length cap + kind whitelist (feedback.submit)

@router.post("/findings/feedback",
         dependencies=[Depends(requires(FEEDBACK_SUBMIT))])
async def submit_feedback(request: Request):
    """Accept an anonymous comment/question against a finding (or general).
    Same findings_enabled flag as the pages — off → the whole feature 404s."""
    if not cfg.load().get("findings_enabled", False):
        return JSONResponse({"error": "not found"}, status_code=404)
    form = await request.form()

    # Honeypot: a human never sees this field. If it is filled, pretend success
    # (so the bot doesn't learn it tripped a filter) but store nothing.
    if (form.get("website") or "").strip():
        return JSONResponse({"ok": True})

    ip = _client_ip(request)
    if not feedback_mod.rate_ok(analytics.hash_ip(ip)):
        return JSONResponse(
            {"error": "Too many submissions — please try again later."},
            status_code=429,
        )

    # Global daily ceiling — the backstop the per-subnet limit can't provide
    # against a distributed flood. Over the cap we ACCEPT-and-DROP (looks like
    # success) so an attacker can't probe the threshold; a real user hitting it
    # is vanishingly unlikely on a research bench.
    if not feedback_mod.under_daily_cap():
        return JSONResponse({"ok": True})

    slug = (form.get("slug") or "").strip() or None
    if slug is not None:
        # Only accept notes tied to a finding that actually exists — don't let
        # arbitrary slugs seed junk records. A malformed finding counts as absent.
        try:
            exists = findings_mod.load(slug) is not None
        except findings_mod.FindingError:
            exists = False
        if not exists:
            return JSONResponse({"error": "unknown finding"}, status_code=400)

    try:
        feedback_mod.submit(
            slug=slug,
            kind=(form.get("kind") or ""),
            body=(form.get("body") or ""),
            visitor_ip=ip,
            member_email=_member_email(request),
        )
    except feedback_mod.FeedbackError as ex:
        return JSONResponse({"error": str(ex)}, status_code=400)
    return JSONResponse({"ok": True})


@router.get("/findings/feedback/queue", response_class=HTMLResponse,
         dependencies=[Depends(requires(FEEDBACK_MODERATE))])
async def feedback_queue_page(request: Request):
    """Lab-only private moderation queue."""
    if not cfg.load().get("findings_enabled", False):
        return HTMLResponse("Not found", status_code=404)
    return HTMLResponse(_feedback_queue_html(feedback_mod.list_all()))


@router.post("/findings/feedback/{rec_id}/status",
         dependencies=[Depends(requires(FEEDBACK_MODERATE))])
async def feedback_set_status(rec_id: str, request: Request):
    """Lab-only — resolve/reopen one submission."""
    form = await request.form()
    status = (form.get("status") or "").strip()
    try:
        ok = feedback_mod.set_status(rec_id, status)
    except feedback_mod.FeedbackError as ex:
        return JSONResponse({"error": str(ex)}, status_code=400)
    if not ok:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"ok": True})
