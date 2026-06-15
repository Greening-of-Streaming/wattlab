"""
/privacy — public privacy notice (GDPR Art. 13 transparency).

A plain content page that states what OWL actually does with data: anonymous
aggregate visit counts (no cookies, no stored IPs — see analytics.py), the one
strictly-necessary auth cookie (owl_session, members only — auth.py), the
pseudonymised handling of visitor IPs, and the result data a visitor generates
by running a job. Kept in sync with analytics.py / auth.py / persist.py BY HAND
— if data handling changes, this page must change.
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse

import ui
from capabilities import requires, PUBLIC_PAGE

router = APIRouter()


_STYLES = """
    * { box-sizing: border-box; }
    body { font-family: monospace; background: var(--bg); color: var(--text);
           max-width: 720px; margin: 0 auto; padding: 2rem 1.25rem; line-height: 1.7; }
    h1 { color: var(--accent); font-size: 1.4rem; margin-bottom: 0.25rem; }
    .sub { color: var(--text-4); font-size: 0.8rem; margin-bottom: 2rem; }
    h2 { color: var(--text-2); font-size: 1rem; margin: 2rem 0 0.5rem; }
    p, li { color: var(--text-3); font-size: 0.88rem; }
    ul { padding-left: 1.25rem; }
    li { margin-bottom: 0.4rem; }
    a { color: var(--accent); }
    code { color: var(--text-2); background: var(--panel); padding: 0.05rem 0.3rem; }
    .key { color: var(--accent); }
"""


def _body() -> str:
    contact = ui.OWL_CONTACT_EMAIL
    return f"""
    <h1>Privacy</h1>
    <div class="sub">How OWL (Online WattLab) handles your data &middot; GDPR notice</div>

    <p>OWL is a measurement bench run by <a href="{ui.GOS_URL}" target="_blank"
       rel="noopener">Greening of Streaming</a> (GoS), a French non-profit
       (association loi 1901), which is the data controller for this site. We
       collect as little as possible and store nothing that identifies you that
       we don&rsquo;t genuinely need.</p>

    <h2>What we collect</h2>
    <ul>
      <li><span class="key">Anonymous visit counts.</span> We count page views in
          aggregate &mdash; per day, per page, by audience type (anonymous /
          member / lab). These counts contain <strong>no IP address, no cookie and
          no device identifier</strong>, so they cannot be traced to you. As
          genuinely anonymous statistics they fall outside the GDPR (Recital 26).</li>
      <li><span class="key">Results you generate.</span> If you run a measurement
          (a transcode, an inference, etc.), the energy result is stored so you
          and the operators can review it. It records the workload and its
          measured energy &mdash; not who you are.</li>
      <li><span class="key">Members&rsquo; email address.</span> If you sign in as a
          GoS member, your email is held in the member allowlist and used solely
          to authenticate you and scope you to your own results.</li>
    </ul>

    <h2>IP addresses</h2>
    <p>Your IP address is used transiently to tell apart local/lab, member and
       public requests, and &mdash; for anonymous visitors who run a job &mdash; to
       group your results so only you see them. We <strong>do not store your raw
       IP</strong>: it is truncated to its network and then one-way hashed under a
       server secret before anything is written to disk, leaving a token that
       cannot be reversed to your address. Our web server keeps no access log.</p>

    <h2>Cookies</h2>
    <p>OWL sets <strong>no tracking or analytics cookies</strong>. The only cookie
       is <code>owl_session</code>, set <em>only</em> if you sign in as a member;
       it is strictly necessary to keep you signed in and needs no consent banner.</p>

    <h2>Retention &amp; your rights</h2>
    <p>Aggregate counts and stored results are kept while they remain useful to
       the project; member emails are kept for the duration of membership. Under
       the GDPR you may ask us to access, correct or erase the limited personal
       data we hold (a member email, or results linked to it). Anonymous counts
       hold nothing to act on.</p>

    <h2>Contact</h2>
    <p>Data-protection requests: <a href="mailto:{contact}">{contact}</a>. For how
       the measurements themselves work, see the
       <a href="/methodology">methodology</a>.</p>
"""


@router.get("/privacy", response_class=HTMLResponse,
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def privacy_page(request: Request):
    return ui.render_page(request, "Privacy", styles=_STYLES, body=_body())
