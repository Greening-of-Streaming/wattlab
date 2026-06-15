"""
/audience — hidden Lab-only visit dashboard (NOT linked in any nav).

Reads analytics.summary() — the anonymous (day → tier → path) counters — and
renders them. Gated to Lab via SETTINGS_WRITE so the counts (including the
operator's own lab/LAN browsing, broken out as its own column) never reach a
public visitor. There is no personal data here to expose: the counters carry no
IP, cookie or UA. See analytics.py and /privacy.
"""
import html

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse

import analytics
import ui
from capabilities import requires, SETTINGS_WRITE

router = APIRouter()


_STYLES = """
    * { box-sizing: border-box; }
    body { font-family: monospace; background: var(--bg); color: var(--text);
           max-width: 760px; margin: 0 auto; padding: 2rem 1.25rem; }
    h1 { color: var(--accent); font-size: 1.3rem; margin-bottom: 0.25rem; }
    .sub { color: var(--text-4); font-size: 0.78rem; margin-bottom: 1.75rem; line-height: 1.6; }
    .cards { display: flex; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 2rem; }
    .card { border: 1px solid var(--border); padding: 0.9rem 1.1rem; min-width: 8rem; }
    .card .n { font-size: 1.9rem; color: var(--accent); font-weight: bold; }
    .card.anon .n { color: var(--accent); }
    .card.lab .n { color: var(--text-3); }
    .card .lbl { font-size: 0.68rem; color: var(--text-4); text-transform: uppercase;
                 letter-spacing: 0.06em; margin-top: 0.2rem; }
    h2 { color: var(--text-2); font-size: 0.95rem; margin: 1.75rem 0 0.6rem; }
    table { border-collapse: collapse; width: 100%; font-size: 0.82rem; }
    th, td { text-align: right; padding: 0.35rem 0.7rem; border-bottom: 1px solid var(--panel); }
    th:first-child, td:first-child { text-align: left; }
    th { color: var(--text-4); font-weight: normal; font-size: 0.72rem;
         text-transform: uppercase; letter-spacing: 0.05em; }
    td { color: var(--text-3); }
    td.anon { color: var(--accent); }
    .empty { color: var(--text-5); font-size: 0.85rem; padding: 1.5rem 0; }
    .note { color: var(--text-5); font-size: 0.72rem; margin-top: 1.5rem; line-height: 1.6; }
"""


def _body(s: dict) -> str:
    t = s["totals"]
    cards = f"""
    <div class="cards">
      <div class="card anon"><div class="n">{t['anonymous']}</div><div class="lbl">Anonymous (public)</div></div>
      <div class="card"><div class="n">{t['member']}</div><div class="lbl">Member</div></div>
      <div class="card lab"><div class="n">{t['lab']}</div><div class="lbl">Lab / LAN (you)</div></div>
      <div class="card"><div class="n">{s['grand_total']}</div><div class="lbl">All page views</div></div>
    </div>"""

    if not s["days"]:
        return cards + '<p class="empty">No visits recorded yet.</p>'

    rows = ""
    for d in s["days"]:
        ti = d["tiers"]
        rows += (f"<tr><td>{d['day']}</td>"
                 f"<td class='anon'>{ti.get('anonymous', 0)}</td>"
                 f"<td>{ti.get('member', 0)}</td>"
                 f"<td>{ti.get('lab', 0)}</td></tr>")
    by_day = f"""
    <h2>By day</h2>
    <table>
      <tr><th>Day</th><th>Anonymous</th><th>Member</th><th>Lab</th></tr>
      {rows}
    </table>"""

    top = ""
    for path, n in s["top_paths"][:20]:
        top += f"<tr><td>{html.escape(path)}</td><td>{n}</td></tr>"
    top_paths = f"""
    <h2>Top pages (all tiers)</h2>
    <table>
      <tr><th>Path</th><th>Views</th></tr>
      {top}
    </table>"""

    first = s.get("first_recorded") or "—"
    return cards + by_day + top_paths + (
        f'<p class="note">Counting since {first}. These figures carry no IP, '
        f'cookie or device identifier &mdash; they are anonymous aggregates '
        f'(see <a href="/privacy" style="color:var(--text-3)">privacy</a>). '
        f'&ldquo;Anonymous&rdquo; is external public traffic; &ldquo;Lab&rdquo; is '
        f'your own LAN / tunnel browsing.</p>')


@router.get("/audience", response_class=HTMLResponse,
            dependencies=[Depends(requires(SETTINGS_WRITE))])
async def audience_page(request: Request):
    return ui.render_page(request, "Audience", styles=_STYLES, body=_body(analytics.summary()))
