"""
TEMPORARY — Marketing Lab landing-page mockups (2026-06, anonymous-landing
audit follow-up). Three illustrative alternatives for the Anonymous landing
experience, served at an unguessable prefix so they can be shared with the
Marketing Lab without being discoverable from the live site (same approach
as the ForTania hidden download link). Not linked from any page, noindexed,
zero JS, read-only — they reuse live data (power cache, findings catalog)
but trigger nothing.

DELETE THIS MODULE (and its main.py registration) once the Marketing Lab
has picked a direction; the chosen scenario gets built properly as a CR.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

import findings as findings_mod
import runtime
import ui
from capabilities import requires, PUBLIC_PAGE
from power import meter_display_name
from routes_findings import _findings_catalog_rows_html, _FINDINGS_CATALOG_CSS
from ui import JOIN_GOS_URL

router = APIRouter()

# Unguessable, fixed path segment (rotating it is just an edit here).
_PREFIX = "/preview-c5d9b3be"

_NOINDEX = '    <meta name="robots" content="noindex, nofollow">\n'

_WATERMARK = (
    '<div style="border:1px dashed var(--warn);color:var(--warn);padding:0.6rem 1rem;'
    'font-family:monospace;font-size:0.75rem;margin:0 0 1.75rem;line-height:1.6">'
    'MOCKUP &middot; temporary preview for the Marketing Lab &mdash; not linked from the '
    'live site, may be removed at any time. Numbers and findings shown are real and live; '
    'layout and wording are illustrative drafts.</div>'
)

# Draft identity sentence — the audit's gap §3.1. Flagged inline so nobody
# mistakes it for approved copy.
_IDENTITY_DRAFT = (
    '<p style="color:var(--text-2);line-height:1.8;max-width:560px;margin-bottom:0.4rem">'
    '<strong>Greening of Streaming</strong> is a member-funded non-profit of '
    'streaming-industry engineers. <strong>OWL</strong> (Online WattLab) is our public '
    'measurement bench: real energy numbers, measured on real hardware, free to cite.</p>'
    '<p style="color:var(--warn);font-family:monospace;font-size:0.68rem;margin-bottom:1.5rem">'
    '[DRAFT wording &mdash; final sentence to be approved by Marketing]</p>'
)

_MOCK_STYLES = """
  body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg);
         color: var(--text); max-width: 840px; margin: 0 auto; padding: 2rem; }
  h1 { font-family: monospace; color: var(--accent); font-size: 1.5rem; margin-bottom: 0.25rem; }
  h2 { font-family: monospace; color: var(--accent); font-size: 1.05rem; margin: 2rem 0 0.75rem; }
  .watts { font-size: 4.5rem; color: var(--accent); font-weight: bold; font-family: monospace;
           margin: 1.25rem 0 0.25rem; }
  .watts-label { font-size: 0.8rem; color: var(--text-3); margin-bottom: 1.5rem; }
  .cta-row { display: flex; gap: 0.75rem; flex-wrap: wrap; margin: 1.75rem 0; }
  .cta-row a { text-decoration: none; padding: 0.55rem 1.4rem; font-size: 0.9rem;
               font-family: monospace; display: inline-block; line-height: 1.3; }
  .cta-primary { background: var(--accent); color: #0a0a0a; font-weight: bold; }
  .cta-primary:hover { background: var(--accent-hover); }
  .cta-secondary { color: var(--accent); border: 1px solid var(--accent); }
  .cta-secondary:hover { background: var(--accent-soft); }
  .cta-tertiary { color: var(--text-3); border: 1px solid var(--border-3); }
  .scenario-note { border-left: 2px solid var(--border-3); padding-left: 1rem;
                   color: var(--text-3); font-size: 0.8rem; line-height: 1.6;
                   margin-top: 2.5rem; max-width: 560px; }
  .mock-list a { color: var(--accent); text-decoration: none; }
  .mock-list li { margin-bottom: 1.1rem; line-height: 1.65; color: var(--text-2); }
"""


def _watts_snapshot() -> str:
    w = runtime.power_cache.get("watts")
    return f"{w:.1f} W" if w is not None else "— W"


def _top_findings_html(n: int = 3) -> str:
    items = findings_mod.list_all()
    items.sort(key=lambda f: f.last_refined, reverse=True)
    if not items:
        return '<p style="color:var(--text-3)">No findings published yet.</p>'
    return _FINDINGS_CATALOG_CSS + _findings_catalog_rows_html(items[:n])


def _mock_page(request: Request, title: str, body: str) -> HTMLResponse:
    return HTMLResponse(ui.render_page(
        request, f"[MOCKUP] {title}", _WATERMARK + body,
        styles=_MOCK_STYLES, head=_NOINDEX, back=False))


@router.get(_PREFIX, response_class=HTMLResponse,
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def mockups_index(request: Request):
    body = f"""
<h1>Anonymous landing — scenarios</h1>
<p style="color:var(--text-3);font-size:0.85rem;margin-bottom:1.5rem">
  Companion to the 2026-06 anonymous-landing audit (<span style="font-family:monospace">
  docs/anon_landing_audit_2026-06.md</span>). Three ways the front door could work for
  visitors who arrive from the GoS website or LinkedIn and don't yet know GoS or OWL.</p>
<ul class="mock-list" style="list-style:none">
  <li><a href="{_PREFIX}/scenario-a">Scenario A — Polished tour (status quo + fixes)</a><br>
      <span style="color:var(--text-3);font-size:0.82rem">Keep the Guided Tour as the landing;
      add a one-line identity statement. Cheapest; weakest fit for 60-second social traffic.</span></li>
  <li><a href="{_PREFIX}/scenario-b">Scenario B — Findings-first landing</a><br>
      <span style="color:var(--text-3);font-size:0.82rem">Lead with live power + citable findings;
      tour one click away. Best front door for both audiences; a new surface to maintain.</span></li>
  <li><a href="{_PREFIX}/scenario-c">Scenario C — Per-finding campaign pages</a><br>
      <span style="color:var(--text-3);font-size:0.82rem">Each LinkedIn post deep-links one finding,
      dressed with a who-we-are band. One finding = one post; homepage unchanged.</span></li>
</ul>
<p style="color:var(--text-3);font-size:0.82rem;line-height:1.6;max-width:560px">
  B and C combine naturally (B fixes the front door, C gives the lab a posting engine).
  The current live landing is the <a href="/demo" style="color:var(--accent)">Guided Tour</a>.</p>
"""
    return _mock_page(request, "Landing scenarios", body)


@router.get(_PREFIX + "/scenario-a", response_class=HTMLResponse,
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def mockup_scenario_a(request: Request):
    body = f"""
<h1>Scenario A — Polished tour</h1>
<p style="color:var(--text-3);font-size:0.85rem;max-width:560px;line-height:1.65">
  The Guided Tour stays as the anonymous landing. The stale-copy and mobile fixes have
  already shipped; the only addition is an identity statement so a stranger knows whose
  numbers these are. Below: the Welcome hero, before and after.</p>

<h2>Today</h2>
<div style="border:1px solid var(--border);padding:1.25rem;max-width:600px">
  <h1 style="margin-bottom:0.25rem">OWL</h1>
  <p style="color:var(--text-3);font-size:0.85rem">Greening of Streaming &middot; Live energy measurement &middot; GoS1</p>
</div>

<h2>With the identity line</h2>
<div style="border:1px solid var(--accent);padding:1.25rem;max-width:600px">
  <h1 style="margin-bottom:0.25rem">OWL</h1>
  <p style="color:var(--text-3);font-size:0.85rem;margin-bottom:0.9rem">Online WattLab &middot; live energy measurement</p>
  {_IDENTITY_DRAFT}
</div>

<div class="cta-row">
  <a class="cta-secondary" href="/demo">Open the live Guided Tour &rarr;</a>
  <a class="cta-tertiary" href="{_PREFIX}">&larr; All scenarios</a>
</div>
<div class="scenario-note">
  Pro: cheapest option; the tour already serves the patient professional visitor well.<br>
  Con: social-media traffic still enters a 7-step linear path with the findings at step 7.
</div>
"""
    return _mock_page(request, "Scenario A", body)


@router.get(_PREFIX + "/scenario-b", response_class=HTMLResponse,
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def mockup_scenario_b(request: Request):
    body = f"""
<div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:1rem">
  <img src="/static/owl.svg" alt="" style="height:56px;width:56px">
  <div>
    <h1 style="margin:0">OWL</h1>
    <span style="color:var(--text-4);font-size:0.72rem;font-family:monospace;letter-spacing:0.04em">
      Online WattLab &middot; live energy measurement</span>
  </div>
</div>

{_IDENTITY_DRAFT}

<div class="watts">{_watts_snapshot()}</div>
<div class="watts-label">GoS1 current power draw &middot; {meter_display_name()} &middot; device layer only
  <span style="color:var(--text-5)">(snapshot at page load &mdash; the real page would update live)</span></div>

<h2>What we've learned so far</h2>
{_top_findings_html()}
<p style="margin-top:0.6rem;font-size:0.82rem">
  <a href="/findings" style="color:var(--accent);text-decoration:none">See all findings &rarr;</a></p>

<h2>See it measured, live</h2>
<p style="color:var(--text-3);font-size:0.85rem;max-width:560px;line-height:1.65">
  Every number above comes from a stored measurement on this machine &mdash; a wall-plug
  meter, an idle baseline, a task, and a confidence interval. You can watch one happen.</p>
<div class="cta-row">
  <a class="cta-primary" href="/demo">Take the guided tour &rarr;</a>
  <a class="cta-secondary" href="/methodology">Read the methodology</a>
  <a class="cta-tertiary" href="{JOIN_GOS_URL}" target="_blank" rel="noopener">Join GoS &nearr;</a>
  <a class="cta-tertiary" href="/auth/sign-in">Member? Sign in</a>
</div>

<div class="scenario-note">
  Scenario B &mdash; findings-first landing. Pro: leads with the most credible, shareable
  asset and fits a 60-second visit; the tour stays one click away. Con: a new surface to
  maintain; needs Marketing's call on hierarchy (findings vs live demo vs membership).
  <br><a href="{_PREFIX}" style="color:var(--accent)">&larr; All scenarios</a>
</div>
"""
    return _mock_page(request, "Scenario B", body)


@router.get(_PREFIX + "/scenario-c", response_class=HTMLResponse,
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def mockup_scenario_c(request: Request):
    items = findings_mod.list_all()
    items.sort(key=lambda f: f.last_refined, reverse=True)
    newest = items[0] if items else None
    finding_html = (
        _FINDINGS_CATALOG_CSS + _findings_catalog_rows_html([newest])
        + f'<p style="margin-top:0.6rem;font-size:0.82rem">'
          f'<a href="/findings/{newest.slug}" style="color:var(--accent);text-decoration:none">'
          f'Read the full finding (methodology, stored result, caveats) &rarr;</a></p>'
        if newest else '<p style="color:var(--text-3)">No findings published yet.</p>'
    )
    headline = newest.headline if newest else "OWL finding"
    body = f"""
<h1>Scenario C — Per-finding campaign page</h1>
<p style="color:var(--text-3);font-size:0.85rem;max-width:560px;line-height:1.65;margin-bottom:1.5rem">
  Each LinkedIn post links straight to ONE finding page. The finding page gains the
  who-we-are band below (shown to visitors arriving without context) and proper link-preview
  metadata. One finding = one post = a natural publishing cadence. Mock of the assembled page:</p>

<div style="border:1px solid var(--border);padding:1.5rem;max-width:640px">
  <div style="border-left:2px solid var(--accent);padding-left:0.85rem;margin-bottom:1.25rem">
    <span style="color:var(--text-4);font-size:0.68rem;letter-spacing:0.06em;text-transform:uppercase;
                 font-family:monospace">New here?</span>
    {_IDENTITY_DRAFT}
    <a href="/demo" style="color:var(--accent);font-size:0.82rem;text-decoration:none">
      Watch a measurement happen live &rarr;</a>
  </div>
  {finding_html}
</div>

<h2>What the LinkedIn preview would look like</h2>
<p style="color:var(--text-3);font-size:0.82rem;max-width:560px;line-height:1.6">
  Today OWL pages have no link-preview metadata, so a shared link renders bare. With
  OpenGraph tags (engineering side is trivial), the post card becomes:</p>
<div style="border:1px solid var(--border-3);max-width:480px;font-family:system-ui">
  <div style="background:#050505;border-bottom:1px solid var(--border-3);padding:2.2rem 1rem;
              display:flex;align-items:center;justify-content:center;gap:0.9rem">
    <img src="/static/owl.svg" alt="" style="height:48px;width:48px">
    <div style="font-family:monospace;color:var(--accent);font-size:1rem;max-width:300px">
      [share image &mdash; design to be supplied by Marketing]</div>
  </div>
  <div style="padding:0.7rem 0.9rem;background:var(--panel)">
    <div style="color:var(--text);font-size:0.85rem;font-weight:600;line-height:1.4">{headline}</div>
    <div style="color:var(--text-3);font-size:0.75rem;margin-top:0.3rem">
      Measured, not estimated &mdash; OWL, the Greening of Streaming energy bench</div>
    <div style="color:var(--text-5);font-size:0.7rem;margin-top:0.3rem">wattlab.greeningofstreaming.org</div>
  </div>
</div>

<div class="scenario-note">
  Pro: deep links outperform homepage links on social; the homepage stays untouched.
  Con: the front door itself stays tour-shaped for cold traffic from the GoS website.
  <br><a href="{_PREFIX}" style="color:var(--accent)">&larr; All scenarios</a>
</div>
"""
    return _mock_page(request, "Scenario C", body)
