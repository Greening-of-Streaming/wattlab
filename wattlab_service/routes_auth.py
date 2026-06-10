"""
Auth routes — CR-001 magic-link sign-in/verify/sign-out, plus the shared
mini-shell (_auth_page_shell) and capability gate page (_gate_page_html).

These pages deliberately stay OFF the standard chrome (no nav, footer,
queue badge on a sign-in page); _auth_page_shell is their own single
shell. The CapabilityError exception handler stays in main.py (app-level
concern) and renders _gate_page_html from here.

Phase 3 per-feature route module — never import main.
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import audience
import auth
import email_send
from capabilities import requires, CapabilityError, PUBLIC_PAGE
from ui import JOIN_GOS_URL, OWL_CONTACT_EMAIL, _BASE_STYLES

router = APIRouter()


# --- CR-001 magic-link auth -------------------------------------------------
#
# Three routes: GET /auth/sign-in (form), POST /auth/sign-in (issue + email),
# GET /auth/verify (consume token, set session cookie), POST /auth/sign-out.
#
# Anti-enumeration: POST /auth/sign-in always returns the same "check your
# email" page whether or not the address is in the allowlist. Real members
# get an email; non-members get nothing. Visitors can't probe the member list
# by submitting addresses one by one.

def _auth_page_shell(title: str, body_html: str,
                     subtitle: str = "Greening of Streaming · Member sign-in") -> str:
    """Minimal stand-alone styled page for the auth flow. Mirrors the gate
    page so members signing in for the first time see the OWL palette.
    `subtitle` overridable so the capability gate page (see
    _capability_error_handler) can re-use the same shell with its own line."""
    return f"""<!DOCTYPE html>
<html>
<head>
  <link rel="icon" type="image/svg+xml" href="/static/owl.svg">
  <title>{title}</title>
  {_BASE_STYLES}
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:monospace;background:var(--bg);color:var(--text);
         display:flex;flex-direction:column;align-items:center;
         justify-content:center;min-height:100vh;gap:0;padding:2rem 1rem}}
    .wrap{{max-width:480px;width:100%;text-align:center}}
    h1{{color:var(--accent);font-size:1.4rem;margin-bottom:0.25rem}}
    p.sub{{color:var(--text-4);font-size:0.8rem;margin-bottom:1.5rem}}
    p.body{{color:var(--text-2);font-size:0.9rem;line-height:1.5;margin:1rem 0}}
    p.err{{color:var(--err);font-size:0.85rem;margin-bottom:1rem}}
    input[type=email]{{background:var(--panel);border:1px solid var(--border-3);
           color:var(--text);font-family:monospace;font-size:1rem;
           padding:0.6rem 1rem;width:280px;text-align:center}}
    input[type=email]:focus{{border-color:var(--accent);outline:none}}
    button{{background:var(--accent);color:#000;border:none;
            font-family:monospace;font-size:1rem;padding:0.6rem 2rem;
            cursor:pointer;margin-top:0.75rem}}
    button:hover{{background:var(--accent-hover)}}
    form{{display:flex;flex-direction:column;align-items:center;gap:0}}
    a{{color:var(--accent)}}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>OWL</h1>
    <p class="sub">{subtitle}</p>
    {body_html}
  </div>
</body>
</html>"""


def _gate_page_html(request: Request, exc: CapabilityError) -> str:
    """Friendly HTML for a 403 from the capability table. The message is keyed
    off the *required* tier (the policy), not the capability string, so adding
    a new gated page needs no change here. See _capability_error_handler."""
    current  = audience.tier(request)
    required = exc.required_tier
    contact = (
        '<p class="body" style="font-size:0.8rem;color:var(--text-4);margin-top:1.5rem">'
        f'Need help? Email <a href="mailto:{OWL_CONTACT_EMAIL}">{OWL_CONTACT_EMAIL}</a>.</p>'
    )
    if required >= audience.Tier.Lab:
        # Lab is granted by network origin (LAN/loopback), never by sign-in —
        # so don't offer a sign-in CTA that can't possibly help.
        subtitle = "Greening of Streaming · Lab console"
        body = (
            '<p class="body">This page is part of the WattLab instrument console '
            'and is restricted to operators on the lab network.</p>'
            f'{contact}'
        )
        return _auth_page_shell("Lab access only · OWL", body, subtitle=subtitle)

    # Member-tier page (the common case: /enhance-run, /benchmark, etc.).
    nxt = request.url.path + (("?" + request.url.query) if request.url.query else "")
    nxt_q = quote(nxt, safe="")
    if current >= audience.Tier.Member:
        # Signed in but still short — defensive; shouldn't normally happen.
        lead = "Your member account doesn't have access to this page."
        cta = ""
    else:
        lead = "You need to be signed in as a GoS member to view this page."
        cta = (
            f'<p class="body"><a href="/auth/sign-in?next={nxt_q}">'
            'Sign in with your member email &rarr;</a></p>'
            '<p class="body" style="font-size:0.8rem;color:var(--text-4)">'
            f'Not a GoS member yet? <a href="{JOIN_GOS_URL}">Join GoS</a> · or '
            '<a href="/">browse OWL anonymously</a>.</p>'
        )
    body = f'<p class="body">{lead}</p>{cta}{contact}'
    return _auth_page_shell("Members only · OWL", body)


@router.get("/auth/sign-in", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def auth_sign_in_page(next: str = "/", error: str = ""):
    err_html = f'<p class="err">{error}</p>' if error else ''
    body = f"""
    {err_html}
    <p class="body">Enter the email address that's on the GoS member list.
       We'll send you a one-click sign-in link.</p>
    <form method="post" action="/auth/sign-in">
      <input type="hidden" name="next" value="{next}">
      <input type="email" name="email" placeholder="you@example.org"
             autocomplete="email" autofocus required>
      <button type="submit">Send sign-in link</button>
    </form>
    <p class="body" style="font-size:0.8rem;color:var(--text-4);margin-top:2rem">
      Not a GoS member yet?
      <a href="{JOIN_GOS_URL}">Join GoS</a> · or
      <a href="/">browse OWL anonymously</a>.</p>
    """
    return _auth_page_shell("Sign in · OWL", body)


@router.post("/auth/sign-in", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def auth_sign_in_submit(request: Request, email: str = Form(...), next: str = Form("/")):
    email_norm = email.strip().lower()
    # Anti-enumeration: behave identically for member and non-member emails.
    # Only members get an email; everyone else gets the same UI feedback.
    if auth.is_member(email_norm):
        token = auth.issue_magic_token(email_norm)
        # Build absolute URL for the email body. Honour X-Forwarded-Proto so
        # nginx-fronted HTTPS works.
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("x-forwarded-host") or request.url.netloc
        link = f"{scheme}://{host}/auth/verify?t={token}&next={next}"
        email_send.send_magic_link(email_norm, link)
    body = f"""
    <p class="body">If <strong>{email_norm}</strong> is a registered GoS member,
       a sign-in link is on its way to that inbox now.</p>
    <p class="body" style="font-size:0.85rem;color:var(--text-4)">
       The link is valid for 15 minutes. Check your spam folder if it doesn't
       arrive within a minute.</p>
    <p class="body" style="margin-top:2rem">
      <a href="/auth/sign-in?next={next}">← Try a different email</a> ·
      <a href="/">Continue to OWL</a></p>
    """
    return _auth_page_shell("Check your email · OWL", body)


@router.get("/auth/verify", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def auth_verify(t: str = "", next: str = "/"):
    email = auth.verify_magic_token(t) if t else None
    if email is None:
        return RedirectResponse(
            url=f"/auth/sign-in?next={next}&error=Sign-in+link+invalid+or+expired.",
            status_code=302,
        )
    if not auth.is_member(email):
        # Possible if a member was removed from the allowlist between issue
        # and verify. Fail closed — fresh sign-in won't help, but the user
        # gets a clean message rather than a silent landing.
        return RedirectResponse(
            url=f"/auth/sign-in?next={next}&error=Email+not+on+the+member+list.",
            status_code=302,
        )
    cookie = auth.make_session_cookie_value(email)
    response = RedirectResponse(url=next or "/", status_code=302)
    response.set_cookie(
        auth.SESSION_COOKIE_NAME, cookie,
        max_age=auth.SESSION_TTL_SECONDS,
        httponly=True, samesite="lax",
        secure=False,  # nginx fronts HTTPS; the cookie travels HTTP between nginx and uvicorn
    )
    return response


@router.post("/auth/sign-out")
async def auth_sign_out():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(auth.SESSION_COOKIE_NAME)
    return response
