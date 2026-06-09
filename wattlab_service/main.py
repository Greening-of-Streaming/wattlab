import asyncio
import os
import io
import json
import html as html_lib
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from fastapi import FastAPI, File, UploadFile, Form, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from dotenv import dotenv_values
from power import get_power_watts, read_sensors_dict, CooldownCancelled, meter_display_name
import gpu
import video as vid
from video import run_video_measurement, run_both_measurement, run_all_measurement, run_codecs_single_measurement, run_video_measurement_path, run_both_measurement_path, UPLOAD_DIR, LOCK_FILE
from sources import get_all_sources, get_grouped_sources, PRELOADED
from llm import run_llm_measurement, run_llm_batch_measurement, run_llm_both_measurement, MODELS, TASKS, COMPARE_PROMPTS, grade as llm_grade
from persist import save_result, list_results, load_result, to_csv, delete_result
from image_gen import (run_image_measurement, run_image_both_measurement,
                        run_image_compare_models_measurement, IMAGE_MODELS,
                        IMAGE_STEPS_CPU, IMAGE_STEPS_GPU, GPU_BATCH_SIZE)
import rag as rag_module
import model_catalog
import corpus_manifest
import settings as cfg
import carbon
import queue_control
import audience
import auth
import curated
import email_send
import findings as findings_mod
import version
from capabilities import (
    requires, can, gate, CapabilityError,
    PUBLIC_PAGE, QUEUE_VIEW, RESULTS_DOWNLOAD, LIVE_TELEMETRY,
    VIDEO_RUN, LLM_RUN, IMAGE_RUN, RAG_RUN, CUSTOM_UPLOAD, WORKING_NAV,
    CUSTOM_PROMPT, BATCH_COMPARE, RAG_CORPUS_UPLOAD, RAG_CORPUS_DELETE_OWN, RESULTS_EXPORT_CSV,
    BENCHMARK_VIEW,
    SETTINGS_READ_FULL, SETTINGS_WRITE, VARIANCE_RUN, BENCHMARK_RUN, ENHANCE_RUN,
)
import benchmark
import pixop

config = dotenv_values("/home/gos/wattlab/.env")
app = FastAPI()

# Serve bundled assets (owl logo, favicon) from wattlab_service/static/.
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── External links — single source of truth ─────────────────────────────────
# Every externally-hosted URL the UI points at lives here, so a changed link is
# a one-line edit. Referenced three ways, depending on the template mechanism:
#   • HTML f-strings (_LOGO, _DEMO_HTML, auth body)              → {CONST}
#   • JS string builders (carbon strip, chart_js)               → ' + CONST + '
#   • plain templates rendered via .replace() (_METHODOLOGY_HTML) → {TOKEN}, baked
#     in the route's .replace() chain
# The Language Lab AI position paper is a filesusr.com asset that can move —
# keep it here, never inline.
POSITION_PAPER_URL  = "https://555e2619-4a3d-4f25-8303-8fb567f350a1.filesusr.com/ugd/ecf0e7_a46203016e4e40c7aa638232bce16486.pdf"
GOS_URL             = "https://greeningofstreaming.org"
JOIN_GOS_URL        = "https://www.greeningofstreaming.org/membership"
OWL_CONTACT_EMAIL   = "owl@greeningofstreaming.org"
GOS_LOGO_URL        = "https://static.wixstatic.com/media/b1006e_f5e9aff607cf4133abf7089207dc3cab~mv2.png"
GITHUB_REPO_URL     = "https://github.com/greeningofstreaming/wattlab"
GITHUB_ISSUES_URL   = "https://github.com/greeningofstreaming/wattlab/issues"
ECO2MIX_URL         = "https://www.rte-france.com/eco2mix"
ELECTRICITYMAPS_URL = "https://www.electricitymaps.com"
EMBER_URL           = "https://ember-energy.org"
CHARTJS_URL         = "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"


# CR-015 — auto-lower maintenance flag on Lab-tier inactivity.
# When `/tmp/owl-maintenance` exists (staging mode raised by `stage-on`),
# any Lab-tier request bumps the flag's mtime. The owl-maintenance-watchdog
# systemd timer fires every minute and runs `stage-off` if the mtime is
# older than `max_idle_mins`. This way the operator extends the window
# simply by *using* the LAN URL or SSH tunnel — no manual heartbeat
# command required.
#
# Cap-table-only contract: gates on SETTINGS_WRITE rather than a raw tier
# compare. The two are equivalent today (Lab-only) but will track if the
# policy ever moves.
_MAINTENANCE_FLAG = Path("/tmp/owl-maintenance")


@app.middleware("http")
async def _maintenance_keepalive(request: Request, call_next):
    if _MAINTENANCE_FLAG.exists():
        try:
            if can(audience.tier(request), SETTINGS_WRITE):
                _MAINTENANCE_FLAG.touch()
        except Exception:
            # Never let the keepalive crash a real request.
            pass
    return await call_next(request)

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


@app.exception_handler(CapabilityError)
async def _capability_error_handler(request: Request, exc: CapabilityError):
    """Central presentation layer for every capability 403. Browser
    navigations (Accept: text/html) get the styled gate page above; fetch/API
    callers keep the JSON contract ({"detail":"requires <cap>"}) the
    front-end JS already understands. The policy itself stays in
    capabilities.py — this only decides how the denial is *shown*."""
    if "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(status_code=exc.status_code,
                            content=_gate_page_html(request, exc))
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/auth/sign-in", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
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


@app.post("/auth/sign-in", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
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


@app.get("/auth/verify", dependencies=[Depends(requires(PUBLIC_PAGE))])
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


@app.post("/auth/sign-out")
async def auth_sign_out():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(auth.SESSION_COOKIE_NAME)
    return response


# --- Auth chip (tier-aware top-right widget) -------------------------------
#
# Rendered on every page the visitor can land on (today: `/` and `/demo`,
# more pages in CR-001 part C). Three states:
#
#   Anonymous → "Sign in" link → /auth/sign-in
#   Member    → "<email> · Sign out" form
#   Lab       → "▣ Lab" pill (auth is by IP, no sign-out makes sense)
#
# CSS lives in a string constant so any page that wants the chip just
# concatenates _AUTH_CHIP_STYLES into its own <style> block. (Could move
# to _BASE_STYLES later when more pages opt in.)

_AUTH_CHIP_STYLES = (
    ".auth-chip{position:fixed;top:0.6rem;right:0.75rem;z-index:100;"
    "font-family:monospace;font-size:0.72rem;color:var(--text-4);"
    "background:rgba(15,15,15,0.92);border:1px solid var(--border-2);"
    "padding:0.3rem 0.7rem;border-radius:2px;display:flex;gap:0.45rem;"
    "align-items:center}"
    ".auth-chip a,.auth-chip button{color:var(--accent);background:none;"
    "border:none;padding:0;font-family:monospace;font-size:inherit;"
    "cursor:pointer;text-decoration:none}"
    ".auth-chip a:hover,.auth-chip button:hover{text-decoration:underline}"
    ".auth-chip .auth-email{color:var(--text-3)}"
    ".auth-chip.lab{border-color:var(--accent);color:var(--accent)}"
    # CR-021 — Anonymous CTA variant. The chip is a status indicator for
    # Member/Lab but a sign-up *call to action* for Anonymous. On wide
    # displays (conference booths) the recessive 0.72 rem chip was easy
    # to miss; this variant reads as a button: filled accent background,
    # 0.85 rem font, key glyph for affordance. Member/Lab keep the
    # recessive look. The link inside inherits the inverted colour so
    # it doesn't double-style.
    ".auth-chip.cta{background:var(--accent);border-color:var(--accent);"
    "color:var(--bg);font-size:0.85rem;padding:0.4rem 0.85rem}"
    ".auth-chip.cta a{color:var(--bg);font-weight:bold}"
    ".auth-chip.cta a:hover{text-decoration:underline}"
)


def _auth_chip_html(request: Request) -> str:
    """Tier-aware sign-in widget. Pure HTML, no script — safe to inject
    into any page template via .replace('{AUTH_CHIP}', ...)."""
    t = audience.tier(request)
    if t == audience.Tier.Lab:
        return '<div class="auth-chip lab" title="Authenticated by LAN/loopback IP">▣ Lab</div>'
    if t == audience.Tier.Member:
        email = auth.member_email_from_request(request) or ""
        return (
            '<div class="auth-chip">'
            f'<span class="auth-email">{email}</span>'
            '<span style="color:var(--text-5)">·</span>'
            '<form method="post" action="/auth/sign-out" style="display:inline">'
            '<button type="submit">Sign out</button>'
            '</form>'
            '</div>'
        )
    # Anonymous — CR-021 prominent CTA variant. Members-only features
    # are visible-but-locked across the surface; the chip is the entry
    # point that turns those locks into unlocked features.
    return '<div class="auth-chip cta"><a href="/auth/sign-in">⚿ Sign in</a></div>'


# Page chrome — auth chip + back link. Mirrors `_FOOTER` so any page can
# concatenate `_HEADER_STYLES` into its <style> block and call
# `_header_html(request)` near the top of <body>. Standard pages already
# inline the chip and back link individually; `/queue-status` and
# `/methodology` use this helper directly.
_HEADER_STYLES = _AUTH_CHIP_STYLES


def _header_html(request: Request) -> str:
    return _auth_chip_html(request) + _BACK


# CR-027 — early tier framing on /demo Welcome step.
#
# The /demo Findings step already shows the full Public/Member/Lab matrix
# (capability table, CR-001 part B/2 + this CR's three-column refresh), but
# visitors complete most of the tour before they get there. This indicator
# answers "what tier am I?" up front, in plain language, with a link to
# either upgrade (Anonymous) or read the full matrix (Member/Lab).
#
# Server-rendered, no JS. Different surface from the corner auth chip:
# the chip is a status indicator + sign-in button; this is a one-line
# explanation embedded inline in the Welcome step's reading flow.
def _tier_indicator_html(request: Request) -> str:
    t = audience.tier(request)
    base_style = (
        'display:inline-block;font-family:monospace;font-size:0.78rem;'
        'padding:0.4rem 0.85rem;margin-bottom:1.25rem;'
        'border:1px solid var(--border-2);background:var(--panel-2);'
        'color:var(--text-3);line-height:1.5'
    )
    if t == audience.Tier.Lab:
        return (
            f'<div style="{base_style};border-color:var(--accent);color:var(--accent)">'
            "▣ You're on the GoS1 lab network — "
            '<span style="color:var(--text-3)">'
            'Lab tier · all access (settings, calibration, custom inputs)</span>'
            '</div>'
        )
    if t == audience.Tier.Member:
        return (
            f'<div style="{base_style}">'
            '◆ <span style="color:var(--accent)">Signed in as a GoS member</span> · '
            'you can drive the engine with custom prompts, custom ffmpeg commands, '
            'all-codecs sweeps, your own corpus and uploads. '
            '<a href="#step-6" onclick="goStep(6);return false;" '
            'style="color:var(--text-3);border-bottom:1px solid var(--border)">'
            'See the full capability matrix &rarr;</a></div>'
        )
    # Anonymous — frame the tour as the public surface, with a clear path
    # to unlock the rest.
    return (
        f'<div style="{base_style}">'
        '○ <span style="color:var(--text-2)">You\'re browsing as Anonymous</span> · '
        'curated demo runs, live measurement, full methodology — same numbers '
        'as members see. '
        '<a href="/auth/sign-in" style="color:var(--accent);'
        'border-bottom:1px solid var(--accent)">Sign in</a> '
        'to unlock custom inputs and uploads, or '
        '<a href="#step-6" onclick="goStep(6);return false;" '
        'style="color:var(--text-3);border-bottom:1px solid var(--border)">'
        'see what changes &rarr;</a></div>'
    )


# CR-001 part C2c — capability lock badge + dim treatment.
#
# Member-tier inputs (custom prompts, custom ffmpeg, all-codecs sweeps,
# batch / compare modes, RAG corpus upload) render visible-but-disabled
# for Anonymous, with the badge above as the GoS membership pitch.
# The locks ARE the pitch — see `/demo` capability matrix for the same
# product copy.
#
# Pure HTML / CSS, no script. Pages that opt in concatenate `_LOCK_STYLES`
# into their <style> block, then call `_lock_badge_html()` per locked
# control and add the `_lock_class()` to the parent block.

_LOCK_STYLES = (
    ".lock-badge{display:inline-flex;align-items:center;gap:0.35rem;"
    "border:1px solid var(--border-3);background:rgba(255,170,0,0.05);"
    "color:var(--warn);font-family:monospace;font-size:0.7rem;"
    "padding:0.2rem 0.55rem;text-decoration:none;border-radius:2px;"
    "margin-bottom:0.5rem}"
    ".lock-badge:hover{border-color:var(--warn);text-decoration:none}"
    ".lock-block{opacity:0.55;filter:saturate(0.5)}"
    ".lock-block input,.lock-block textarea,.lock-block button,"
    ".lock-block select,.lock-block label{cursor:not-allowed!important}"
)


def _lock_badge_html(request: Request, capability: str,
                      label: str = "Members only") -> str:
    """Return a 🔒 Members only · Join GoS pitch badge if `request` lacks
    `capability`; '' if the tier already has it. Pair with `_lock_class()`
    on the parent block so the dim/disabled treatment lands in the same
    place. The badge links to greeningofstreaming.org/membership."""
    if can(audience.tier(request), capability):
        return ""
    return (
        f'<a href="{JOIN_GOS_URL}" target="_blank" rel="noopener noreferrer" '
        f'class="lock-badge" title="{label} — join GoS to unlock">'
        f'🔒 {label} · Join GoS ↗</a>'
    )


def _lock_class(request: Request, capability: str) -> str:
    """Returns 'lock-block' (dim + not-allowed cursor) when the request
    lacks `capability`; '' when it has it. Drop into a class= attribute
    next to the lock badge."""
    return "" if can(audience.tier(request), capability) else "lock-block"


def _disabled_attr(request: Request, capability: str) -> str:
    """Returns ' disabled' when `request` lacks `capability`, else ''.
    Use on inputs/buttons inside a lock-block so they can't be focused
    or clicked. The runtime gate (`gate(request, ...)`) is the actual
    enforcement — this is just the polite UX layer."""
    return "" if can(audience.tier(request), capability) else " disabled"


jobs = {}

# --- Live telemetry cache ---
# Two background loops populate this. All /power, /live, and the live-polling
# UI read from here, so multiple browser sessions don't each hammer the P110
# or shell-out to `sensors` independently.
#   watts         — Tapo P110 wall-power, polled every 5s
#   cpu_tctl      — Ryzen Tctl (°C), polled every 2s
#   gpu_junction  — RX 7800 XT junction temp (°C), polled every 2s
#   gpu_ppt_w     — GPU self-reported Package Power Tracking (W), polled every 2s
_power_cache: dict = {
    "watts": None,
    "cpu_tctl": None,
    "gpu_junction": None,
    "gpu_ppt_w": None,
}

async def power_poller():
    while True:
        try:
            _power_cache["watts"] = await get_power_watts()
        except Exception:
            pass  # keep stale value on transient errors
        await asyncio.sleep(5)

async def sensors_poller():
    """Cheap subprocess call into lm-sensors; 2s cadence so temperature changes
    during a workload are visible in near-real-time on the live badge."""
    loop = asyncio.get_event_loop()
    while True:
        try:
            d = await loop.run_in_executor(None, read_sensors_dict)
            _power_cache.update(d)
        except Exception:
            pass
        await asyncio.sleep(2)

# --- Queue ---
# Queue state, enqueue chokepoint, and worker live in queue_control.py.
# CR-001 (per-tier rate limits) and CR-001b (demo lock) plug into the
# enqueue chokepoint via the optional `request` parameter.


@app.on_event("startup")
async def startup():
    queue_control.start(jobs, LOCK_FILE)
    asyncio.create_task(power_poller())
    asyncio.create_task(sensors_poller())
    asyncio.create_task(carbon.poller(zones=[carbon.HOME_ZONE]))
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, rag_module.check_index)

_LOGO = (
    f'<a href="{GOS_URL}" target="_blank"'
    f' style="display:inline-flex;align-items:center;gap:0.6rem;'
    f'text-decoration:none;margin-bottom:1.5rem;opacity:0.75;'
    f'transition:opacity 0.2s" onmouseover="this.style.opacity=1"'
    f' onmouseout="this.style.opacity=0.75">'
    f'<img src="{GOS_LOGO_URL}" alt="Greening of Streaming"'
    f' height="32" style="display:block">'
    f'<span style="color:var(--text-4);font-size:0.72rem;font-family:monospace">'
    f'greeningofstreaming.org</span></a>'
)
def _model_date_line(v: dict) -> str:
    """CR-054 — render the release + training-cutoff line under a model card.

    Used by /llm and /rag model selectors so test designers know what era of
    data the model could have seen. Truncates to YYYY-MM for the visible
    label; full source note is in the title attribute (tooltip).
    """
    rel = (v.get("released") or "")[:7]               # YYYY-MM
    cut = (v.get("training_cutoff") or "")[:7]        # YYYY-MM
    src = (v.get("dates_source") or "").replace('"', '&quot;')
    if not rel and not cut:
        return ('<p style="color:var(--text-5);font-size:0.65rem;margin-top:0.15rem;font-style:italic">'
                'dates not catalogued</p>')
    rel_str = rel if rel else "—"
    cut_str = cut if cut else "—"
    return (f'<p title="{src}" style="color:var(--text-5);font-size:0.65rem;margin-top:0.15rem">'
            f'released {rel_str} · cutoff {cut_str}</p>')


def _models_section_html(s: dict, local: bool) -> str:
    """CR-050 — render the Models section on /settings.
    Three panels (LLM, RAG, Image), each showing every model the catalog
    found, with checkboxes preselected from the per-surface enabled list
    in settings. Anonymous viewers see disabled checkboxes (read-only).
    """
    enabled_keys = {
        "llm_enabled_models":   set(s.get("llm_enabled_models")   or []),
        "rag_enabled_models":   set(s.get("rag_enabled_models")   or []),
        "image_enabled_models": set(s.get("image_enabled_models") or []),
    }
    available = {
        "llm_enabled_models":   model_catalog.available_llm_models(),
        "rag_enabled_models":   model_catalog.available_llm_models(),  # shared catalog
        "image_enabled_models": model_catalog.available_image_models(),
    }
    # CUDA-only models (e.g. FLUX NF4) are shown but flagged; on a non-NVIDIA
    # GPU they can't run, so they're rendered disabled + "unavailable" (and
    # enabled_image_models() drops them from the runner) — see backend_allows().
    gpu_vendor = model_catalog.active_gpu_vendor()
    labels = {
        "llm_enabled_models":   ("LLM models",   "Drives /llm and /llm/compare. Source: <code>ollama list</code>."),
        "rag_enabled_models":   ("RAG models",   "Drives /rag and /rag/compare. Same Ollama catalog as LLM; can be a different subset."),
        "image_enabled_models": ("Image models", "Drives /image. Source: HuggingFace cache scan."),
    }

    def panel(surface_key: str) -> str:
        title, desc = labels[surface_key]
        avail = available[surface_key]
        enabled = enabled_keys[surface_key]
        # Empty enabled list = all available enabled (per the catalog convention).
        all_on = not enabled
        rows = []
        for k, v in avail.items():
            # cuda_only models can't run on a non-NVIDIA GPU: force them
            # disabled + unchecked so the UI never implies they're active.
            cuda_only = bool(v.get("cuda_only"))
            blocked = cuda_only and gpu_vendor != "nvidia"
            checked = "checked" if ((all_on or k in enabled) and not blocked) else ""
            disabled = "disabled" if (not local or blocked) else ""
            extras = []
            if v.get("params"):
                extras.append(v["params"])
            if v.get("size"):
                extras.append(v["size"])
            extra_str = " · ".join(extras)
            badge = ""
            if cuda_only:
                badge = (
                    '<span style="font-size:0.62rem;font-weight:bold;letter-spacing:0.03em;'
                    'padding:0.05rem 0.4rem;border-radius:3px;background:var(--accent-soft);'
                    'color:var(--accent);border:1px solid var(--accent)">CUDA-only</span>'
                )
                if blocked:
                    badge += (
                        f'<span style="font-size:0.66rem;color:var(--warn);margin-left:0.4rem">'
                        f'unavailable on {gpu_vendor.upper()} GPU</span>'
                    )
            rows.append(
                f'<label style="display:flex;align-items:center;gap:0.6rem;'
                f'padding:0.35rem 0.5rem;border-bottom:1px solid var(--panel-2);'
                f'cursor:{"pointer" if (local and not blocked) else "default"};font-size:0.85rem;'
                f'opacity:{"0.55" if blocked else "1"}">'
                f'<input type="checkbox" class="model-toggle" data-surface="{surface_key}" '
                f'data-key="{k}" {checked} {disabled} '
                f'style="accent-color:var(--accent);margin:0">'
                f'<span style="color:var(--text-2);flex:1">{v.get("label", k)} '
                f'<span style="color:var(--text-5);font-size:0.75rem">'
                f'({extra_str})</span> {badge}</span>'
                f'<code style="color:var(--text-4);font-size:0.72rem">{k}</code>'
                f'</label>'
            )
        if not rows:
            rows = ['<div style="color:var(--text-5);font-size:0.8rem;padding:0.5rem">'
                    'No models detected in catalog.</div>']
        return (
            f'<div style="border:1px solid var(--border-3);padding:0.85rem 1rem;'
            f'margin-bottom:0.75rem;background:var(--panel-2)">'
            f'<div style="color:var(--text-2);font-size:0.85rem;font-weight:bold;'
            f'margin-bottom:0.2rem">{title}</div>'
            f'<div style="color:var(--text-5);font-size:0.72rem;margin-bottom:0.5rem">{desc}</div>'
            f'{"".join(rows)}'
            f'</div>'
        )

    edit_hint = (
        ' Tick to enable a model on the surface; untick to hide it. Empty selection = all available enabled.'
        if local else ' Display-only — sign in as Lab to edit.'
    )

    return (
        f'<div class="section">Models (CR-050)</div>'
        f'<div style="color:var(--text-4);font-size:0.75rem;line-height:1.6;margin-bottom:0.75rem">'
        f'Auto-discovered from <code>ollama list</code> and the HuggingFace cache (60 s TTL).'
        f' To add a new LLM: <code>ollama pull &lt;name&gt;</code> on the server.'
        f' To add an image model: download into <code>~/.cache/huggingface</code>.'
        f' Reload this page to see new entries.{edit_hint}'
        f'</div>'
        f'{panel("llm_enabled_models")}'
        f'{panel("rag_enabled_models")}'
        f'{panel("image_enabled_models")}'
    )


_BACK = (
    '<a href="/" style="display:inline-flex;align-items:center;gap:0.55rem;'
    'color:var(--text-3);text-decoration:none;font-size:0.82rem;margin-bottom:1.5rem;'
    'transition:color 0.2s" onmouseover="this.style.color=\'#00ff99\'"'
    ' onmouseout="this.style.color=\'#777\'">'
    '<img src="/static/owl.svg" alt="OWL" '
    'style="height:26px;width:26px;display:block;flex-shrink:0">'
    '<span style="font-weight:bold;letter-spacing:0.02em">OWL</span>'
    '<span style="color:var(--text-5);margin-left:0.35rem">&nbsp;&nbsp;&larr; Home</span>'
    '</a>'
)

# Floating badge: shows watts + CPU + GPU temps + queue depth on every page.
# Values are filled in by the shared _LIVE_JS poller below via data-live hooks.
_QUEUE_BADGE = (
    '<div id="gos-qbadge" style="position:fixed;bottom:1rem;right:1rem;'
    'font-family:monospace;font-size:0.72rem;background:var(--panel);border:1px solid var(--border-2);'
    'padding:0.3rem 0.6rem;max-width:calc(100vw - 2rem)">'
    '<a href="/queue-status" style="color:var(--text-3);text-decoration:none;white-space:nowrap">'
    '<span data-live="watts">—</span>'
    ' · CPU <span data-live="cpu_tctl">—</span>'
    ' · GPU <span data-live="gpu_junction">—</span>'
    '<span data-live="queue_depth"></span>'
    '<span data-live="paused"></span>'
    '</a></div>'
)

# Phase 1 (2026-06-10): the shared JS bundles are real files under static/ —
# lintable, diffable, cacheable (version-sha cache-buster). Settings/meter
# copy reaches them per request via /ui-config.js (window.WL_CFG), so copy
# changes no longer need a service restart. See ARCHITECTURE.md.
_WL_ASSET_V = version.version_dict().get("sha") or "dev"
_UI_CFG_TAG = '<script src="/ui-config.js"></script>'

# Shared live-telemetry poller (static/wl-live.js): one /live fetch every 3s
# updates every element carrying a data-live="<key>" attribute; formatters
# live in the FMT table in that file.
_LIVE_JS = f'<script src="/static/wl-live.js?v={_WL_ASSET_V}"></script>'

# Shared carbon UI helpers. Two globals defined: `wlCarbonRow(energy)` for
# the inline CO2e line under any Energy (ΔE) row; `wlCarbonStrip(wh, label)`
# for the per-report "if this had run elsewhere" comparison strip. Both
# render explicit "live" / "estimated" badges so visitors know which data
# source they're looking at — single source of truth for that distinction.
# All carbon logic (fallback ladder, intensity table, polling) lives in
# carbon.py; this is the UI projection only.
# static/wl-carbon.js needs WL_CFG (the source URLs), so the config tag rides
# along. A page that includes /ui-config.js twice (here + _PROGRESS_JS) is
# harmless — same idempotent assignment, one cached fetch.
_CARBON_JS = (_UI_CFG_TAG
              + f'<script src="/static/wl-carbon.js?v={_WL_ASSET_V}"></script>')

# Small "BETA" chip used next to h1 on AI-workload pages and Guided Tour
# steps 2/3/4 (LLM, image, RAG). Single source of truth so the framing copy
# stays consistent: video is production-grade, AI workloads are exploratory.
_BETA_CHIP = (
    '<span style="font-size:0.55rem;letter-spacing:0.08em;'
    'color:var(--text-5);border:1px solid var(--border-3);padding:0.1rem 0.35rem;'
    'border-radius:2px;vertical-align:middle;margin-left:0.5rem;'
    'font-family:monospace">BETA</span>'
)

# CR-037 — tether the AI pages to streaming. Each AI page gets a one-line
# streaming-anchored framing band plus a shared "how to read AI energy in a
# streaming context" expander drawn from the Language Lab AI position paper
# (Jan 2026). Reframing only — no new measurement. Centralised here so the five
# framing principles read identically on /llm, /image and /rag and can't drift
# from the paper (CR-037 watch-out). Built with plain `+` concatenation, not an
# f-string, so the URL splice can't be mistaken for an undefined name.
_AI_BAND_COPY = {
    "image": ("AI-generated frames are the <strong>personalisation axis</strong>: "
              "per-viewer generated content breaks the cached-edge / multicast "
              "model and pushes delivery back to expensive unicast."),
    "llm":   ("Chat-style LLMs have <strong>limited direct use</strong> in streaming "
              "workflows (which lean on small specialised models) — this tab measures "
              "the expensive end of the spectrum as an upper bound, not the typical case."),
    "rag":   ("A controlled look at a <strong>retrieval / context layer</strong> — a "
              "meta-demo run over GoS&rsquo;s own ~100 papers, not generic Q&amp;A."),
}


def _ai_streaming_band(kind):
    """One-line streaming-context framing band for an AI page (CR-037)."""
    copy = _AI_BAND_COPY.get(kind, "")
    return (
        '<div style="margin-bottom:1rem;font-size:0.8rem;line-height:1.55;'
        'color:var(--text-3);border-left:2px solid var(--accent);padding-left:0.85rem">'
        '<span style="color:var(--text-4);font-size:0.7rem;letter-spacing:0.06em;'
        'text-transform:uppercase">In a streaming context</span><br>' + copy
        + ' <a href="' + POSITION_PAPER_URL + '" target="_blank" rel="noopener" '
        'style="color:var(--accent);text-decoration:none;white-space:nowrap">'
        'Language Lab AI paper ↗</a></div>'
    )


_AI_ABOUT_DETAILS = (
    '<details style="margin-bottom:1.5rem;border-left:2px solid #222;padding-left:1rem">'
    '<summary style="cursor:pointer;color:var(--text-3);font-size:0.82rem;'
    'list-style:none;outline:none">ⓘ How to read AI energy in a streaming context '
    '<span style="color:var(--text-4);font-size:0.72rem">(click to expand)</span></summary>'
    '<div style="color:var(--text-3);font-size:0.82rem;line-height:1.6;margin-top:0.75rem">'
    'Framing from the Greening of Streaming '
    '<a href="' + POSITION_PAPER_URL + '" target="_blank" rel="noopener" '
    'style="color:var(--accent);text-decoration:none">Language Lab AI position paper</a> '
    '(Jan 2026), <em>&ldquo;Distinguishing Impact from Innovation&rdquo;</em>:'
    '<ul style="margin:0.6rem 0 0 1.1rem;padding:0;line-height:1.7">'
    '<li><strong>AI is neither inherently sustainable nor unsustainable</strong> — type, '
    'size and deployment context decide net impact.</li>'
    '<li><strong>The type of AI matters enormously</strong> — small specialised CNNs '
    '(per-title encoding, scene classification, super-resolution) are orders of magnitude '
    'cheaper than general-purpose LLMs and diffusion models. Streaming mostly uses the '
    'former; these tabs measure the latter.</li>'
    '<li><strong>Data volume &ne; energy consumption.</strong></li>'
    '<li>OWL measures the energy AI <strong>adds</strong> — not the infrastructure energy '
    'AI <strong>avoids</strong> through better compression, caching or routing. Both halves '
    'are needed for net impact; OWL has the first.</li>'
    '<li><strong>Inference cost only</strong> — no amortised training cost.</li>'
    '<li>Watch for <strong>rebound effects</strong>: efficiency gains can be offset by '
    'expanded use (more variations, more personalisation).</li>'
    '</ul></div></details>'
)


def _ai_intro(kind):
    """CR-037 streaming-framing band + shared 'about' expander for an AI page."""
    return _ai_streaming_band(kind) + _AI_ABOUT_DETAILS


# Footer links — methodology + GitHub issue tracker. Methodology added 2026-05-08
# for universal access from every page; was previously only reachable via the
# /demo Confidence step or by typing /methodology directly.
_METHODOLOGY_LINK = (
    '<div style="margin-top:0.75rem;font-family:monospace;font-size:0.72rem;color:var(--text-5)">'
    'Full measurement protocol &middot; confidence framework &middot; scope statements: '
    '<a href="/methodology" '
    'style="color:var(--text-3);text-decoration:none;border-bottom:1px solid var(--border)">'
    'Methodology &rarr;</a></div>'
)
_ISSUES_LINK = (
    '<div style="margin-top:0.75rem;font-family:monospace;font-size:0.72rem;color:var(--text-5)">'
    'Spotted a bug or have a feature request? '
    f'<a href="{GITHUB_ISSUES_URL}" target="_blank" rel="noopener" '
    'style="color:var(--text-3);text-decoration:none;border-bottom:1px solid var(--border)">'
    'Open an issue on GitHub &rarr;</a></div>'
)

# Single source of truth for content colors, panel/border tones, and base
# readability rules. CSS variables defined in :root cascade globally, so any
# inline `style="color:var(--text-3)"` resolves correctly regardless of where
# this <style> block sits in the document. Injected via _FOOTER (every page
# that uses the standard footer) and via the gate page directly.
_BASE_STYLES = (
    '<style>'
    ':root{'
    # backgrounds
    '--bg:#0a0a0a;'
    '--panel:#111;'
    '--panel-2:#0d0d0d;'
    # borders (light → dark)
    '--border:#222;'
    '--border-2:#1a1a1a;'
    '--border-3:#333;'
    # text — text-3 is the new "secondary" default. All values were chosen
    # for WCAG AA contrast on --bg (≥4.5:1) except --text-5 which is for
    # purely decorative non-content (separators, faint hints).
    '--text:#e0e0e0;'      # primary body         (~13:1, AAA)
    '--text-2:#bbb;'       # bright secondary     (~9.7:1, AAA)
    '--text-3:#8a8a8a;'    # default secondary    (~6.6:1, AA)
    '--text-4:#707070;'    # tertiary / muted     (~4.7:1, AA)
    '--text-5:#5a5a5a;'    # faint decorative     (~3.5:1)
    # accents — already pass, just consolidated
    '--accent:#00ff99;'
    '--accent-hover:#00dd88;'
    '--accent-soft:#00ff9922;'
    '--warn:#ffaa00;'
    '--err:#ff4400;'
    '}'
    # global readability
    'body{font-size:14px;line-height:1.55}'
    '@media(max-width:600px){'
    'body{font-size:15px;line-height:1.6}'
    # bump the smallest fonts on mobile so muted text stays above ~12px
    '.sub,.subtitle,.scope,.label,.elapsed,.t-lbl{font-size:0.85rem!important}'
    '}'
    '</style>'
)

_FOOTER = (
    f'{_BASE_STYLES}'
    f'<footer style="margin-top:3rem;padding-top:1rem;border-top:1px solid var(--panel)">'
    f'{_LOGO}{_METHODOLOGY_LINK}{_ISSUES_LINK}'
    f'<div style="margin-top:0.75rem;color:var(--text-5);font-size:0.68rem;'
    f'font-family:monospace">{version.version_string()}</div>'
    f'</footer>'
    f'{_QUEUE_BADGE}{_LIVE_JS}{_CARBON_JS}'
)

# Confidence flag popover — inject into any page that shows .conf-badge elements.
# Plain string (not f-string) so JS curly braces need no escaping.
_CONF_HELP_WIDGET = (
    '<div id="conf-pop" style="display:none;position:fixed;z-index:9999;background:var(--panel);'
    'border:1px solid var(--border);padding:1rem 1.25rem;max-width:300px;font-size:0.8rem;'
    'line-height:1.7;box-shadow:0 4px 24px #000a">'
    '<div style="font-family:monospace;color:var(--text-5);font-size:0.65rem;text-transform:uppercase;'
    'letter-spacing:0.06em;margin-bottom:0.75rem">Confidence flag</div>'
    '<div style="margin-bottom:0.5rem">'
    '<span style="font-family:monospace">🟢 Repeatable</span>'
    '<span style="color:var(--text-3);display:block;font-size:0.75rem;padding-left:1.4rem">'
    '≥95% confident the task draws above idle, with enough task polls to confirm. '
    'Reliable enough to cite.</span></div>'
    '<div style="margin-bottom:0.5rem">'
    '<span style="font-family:monospace">🟡 Early insight</span>'
    '<span style="color:var(--text-3);display:block;font-size:0.75rem;padding-left:1.4rem">'
    '≥80% confident above idle, or too few polls for green. Directional, needs a longer run.</span></div>'
    '<div>'
    '<span style="font-family:monospace">🔴 Need more data</span>'
    '<span style="color:var(--text-3);display:block;font-size:0.75rem;padding-left:1.4rem">'
    'Not yet distinguishable from idle. Don\'t cite yet.</span></div>'
    '<div style="color:var(--text-5);font-size:0.7rem;margin-top:0.75rem;font-family:monospace">'
    'confidence = Φ(ΔW / SE), SE from this run\'s noise + the calibrated idle floor · '
    '<a href="/methodology" style="color:var(--text-3)">methodology</a></div>'
    '</div>'
    '<script>(function(){'
    'var s=document.createElement("style");'
    's.textContent=".conf-badge{cursor:pointer}";'
    'document.head.appendChild(s);'
    'var pop=document.getElementById("conf-pop");'
    'document.addEventListener("click",function(e){'
    'var b=e.target.closest(".conf-badge");'
    'if(b){e.stopPropagation();'
    'var r=b.getBoundingClientRect();'
    'pop.style.left=Math.min(r.left,window.innerWidth-320)+"px";'
    'pop.style.top=(r.bottom+6)+"px";'
    'pop.style.display=pop.style.display==="none"?"block":"none";'
    '}else if(!pop.contains(e.target)){pop.style.display="none";}'
    '});'
    '})();</script>'
)

# Shared progress utilities + WL_*_STAGES stage labels — injected into every
# test page (static/wl-progress.js). Stage wording (toggle-aware cooldown
# labels, meter name) is built in the browser from WL_CFG, resolved per
# request — the old import-time bake (and its restart-to-refresh constraint)
# is gone.
_PROGRESS_JS = (_UI_CFG_TAG
                + f'<script src="/static/wl-progress.js?v={_WL_ASSET_V}"></script>')

def _ui_cfg() -> dict:
    """Settings-driven UI copy, resolved per request — the single source for
    cooldown/rest wording (toggle-aware) on both sides: served to the browser
    as window.WL_CFG via /ui-config.js (consumed by static/wl-progress.js and
    wl-carbon.js), and substituted into page HTML by _bake_durations().

    `cooldown_paren` is the toggle-aware parenthetical ("(→ idle)" vs "(10s)")
    every cooldown label must build from — never bake a bare "{COOLDOWN_S}s"
    into a cooldown label; that's how the fixed "(10s)" survived the
    wait-for-idle switch on /image + /llm/compare (S39)."""
    s = cfg.load()
    cd = str(s.get("video_cooldown_s", "\u2014"))
    idle_on = bool(s.get("cooldown_wait_for_idle", True))
    cooldown_paren = "(\u2192 idle)" if idle_on else f"({cd}s)"
    return {
        "baseline_s": str(s.get("baseline_polls", "\u2014")),
        "cooldown_s": cd,
        "llm_rest_s": str(s.get("llm_rest_s", "\u2014")),
        "cooldown_paren": cooldown_paren,
        "cooldown_label": f"Cooldown {cooldown_paren}",
        "rest_label": "Rest (\u2192 idle)" if idle_on else f"Rest ({cd}s)",
        "idle_label": "Wait for Idle" if idle_on else "Idle",
        "meter_name": meter_display_name(),
        # Registry/source URLs for wl-carbon.js links — constants above stay
        # the single source; the browser gets them through WL_CFG.
        "urls": {
            "eco2mix": ECO2MIX_URL,
            "electricitymaps": ELECTRICITYMAPS_URL,
            "position_paper": POSITION_PAPER_URL,
            "ember": EMBER_URL,
        },
    }


def _bake_durations(template: str) -> str:
    """Substitute the _ui_cfg() wording tokens into a page-HTML template.
    Serve-time (called inside page handlers): settings changes apply on the
    next request — no service restart needed."""
    c = _ui_cfg()
    return (template
            .replace("{REST_LABEL}", c["rest_label"])
            .replace("{COOLDOWN_LABEL}", c["cooldown_label"])
            .replace("{COOLDOWN_PAREN}", c["cooldown_paren"])
            .replace("{IDLE_LABEL}", c["idle_label"])
            .replace("{BASELINE_S}", c["baseline_s"])
            .replace("{COOLDOWN_S}", c["cooldown_s"])
            .replace("{LLM_REST_S}", c["llm_rest_s"]))


@app.get("/ui-config.js", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def ui_config_js():
    """window.WL_CFG for the static JS bundles — resolved per request so
    settings/meter changes reach the browser without a service restart."""
    body = "window.WL_CFG = " + json.dumps(_ui_cfg()) + ";"
    return Response(body, media_type="application/javascript",
                    headers={"Cache-Control": "no-store"})



# CR-034 Phase A \u2014 shared compact-result-card helpers.
#
# Lifted from /demo's bespoke renderers so the four workload result cards
# (video, llm, rag, image) live in a single source of truth. /demo's
# wrappers call into these; CR-034 Phase B (prev-row click-to-expand on
# /video /llm /rag /image) reuses the same helpers to render expanded
# rows. Future drift-bug class \u2014 when a polish item ships on the main
# pages but not /demo (CR-019 lifecycle, CR-030 drift note) \u2014 is closed
# at the architectural level.
#
# Contract: every helper takes `{result, isPrev, savedAt}` and RETURNS an
# HTML string. No DOM mutation inside \u2014 callers decide where to render.
# Confidence flag, prompt blockquote, carbon strip (with sub-runs +
# drift note + projection toggle + EV equivalence), scope clarifier are
# all standard surface; pages can't accidentally drop one when they
# render through these helpers.
_RESULT_JS = f'<script src="/static/wl-result.js?v={_WL_ASSET_V}"></script>'

# --- Home ---

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def index(request: Request):
    # CR-001: Anonymous visitors land on the Guided Tour — more guidance,
    # capability matrix as the GoS sales pitch. Member/Lab land on the
    # working nav grid. Same URL, two distinct experiences. /demo already
    # exists as the visitor environment, so this is a single redirect.
    # CR-026: gates on the WORKING_NAV cap rather than a raw tier compare,
    # so the home-page UX branch follows the cap-table-as-policy contract.
    if not can(audience.tier(request), WORKING_NAV):
        return RedirectResponse(url="/demo", status_code=302)

    watts = _power_cache["watts"]
    watts_str = f"{watts:.1f}" if watts is not None else "—"
    return f"""<!DOCTYPE html>
<html>
<head>
    <link rel="icon" type="image/svg+xml" href="/static/owl.svg">
  <title>OWL — GoS</title>
    <style>
        {_AUTH_CHIP_STYLES}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: monospace; background: var(--bg); color: var(--text);
               display: flex; flex-direction: column; align-items: center;
               justify-content: center; min-height: 100vh; padding: 2rem 1rem; }}
        .hero-mark {{ display: flex; align-items: center; gap: 0.75rem;
                      margin-bottom: 1.5rem; }}
        .hero-mark img {{ height: 72px; width: 72px; display: block; }}
        .hero-mark .name {{ font-size: 1.4rem; color: var(--accent);
                            font-weight: bold; letter-spacing: 0.05em; }}
        .hero-mark .tagline {{ display: block; color: var(--text-4); font-size: 0.72rem;
                               letter-spacing: 0.04em; margin-top: 0.15rem; }}
        .watts {{ font-size: 6rem; color: var(--accent); font-weight: bold; }}
        .label {{ font-size: 1.2rem; color: var(--text-3); margin-top: 1rem; }}
        .scope {{ font-size: 0.8rem; color: var(--text-4); margin-top: 0.5rem; }}
        .temps {{ margin-top: 1.25rem; display: flex; gap: 1.5rem;
                  font-size: 0.95rem; color: var(--text-3); }}
        .temps .t-val {{ color: var(--text-2); font-weight: bold; }}
        .temps .t-lbl {{ color: var(--text-3); font-size: 0.7rem; letter-spacing: 0.05em;
                         text-transform: uppercase; display: block; margin-top: 0.2rem; }}
        .nav {{ margin-top: 3rem; display: flex; flex-direction: column; align-items: center;
                gap: 1.25rem; width: 100%; max-width: 600px; }}
        .nav-label {{ font-size: 0.65rem; color: var(--text-5); letter-spacing: 0.1em;
                      text-transform: uppercase; margin-bottom: -0.5rem; }}
        .nav-tour a {{ color: #0a0a0a; background: var(--accent); text-decoration: none;
                       padding: 0.6rem 2.5rem; font-size: 1rem; font-weight: bold;
                       display: inline-block; }}
        .nav-tour a:hover {{ background: var(--accent-hover); }}
        .nav-video a {{ color: var(--accent); text-decoration: none;
                        border: 1px solid var(--accent); padding: 0.55rem 2rem;
                        font-size: 1rem; display: inline-block; }}
        .nav-video a:hover {{ background: #00ff9922; }}
        .nav-beta-note {{ font-size: 0.72rem; color: var(--text-5); text-align: center;
                          line-height: 1.55; max-width: 460px; margin-top: -0.5rem; }}
        .nav-ai {{ display: flex; gap: 0.6rem; flex-wrap: wrap; justify-content: center; }}
        .nav-ai a {{ color: var(--text-3); text-decoration: none;
                     border: 1px solid var(--border-2); padding: 0.4rem 1rem;
                     font-size: 0.85rem; display: inline-flex; align-items: baseline;
                     gap: 0.45rem; }}
        .nav-ai a:hover {{ color: var(--text-2); border-color: var(--text-4); }}
        .beta-tag {{ font-size: 0.55rem; letter-spacing: 0.08em; color: var(--text-5);
                     border: 1px solid var(--border-3); padding: 0.05rem 0.3rem;
                     border-radius: 2px; }}
        .nav-util {{ display: flex; gap: 0.5rem; flex-wrap: wrap; justify-content: center; }}
        .nav-util a {{ color: var(--text-4); text-decoration: none;
                       border: 1px solid var(--border-2); padding: 0.3rem 0.75rem;
                       font-size: 0.75rem; }}
        .nav-util a:hover {{ color: var(--text-3); border-color: var(--text-5); }}
    </style>
</head>
<body>
    {_auth_chip_html(request)}
    <div class="hero-mark">
        <img src="/static/owl.svg" alt="OWL">
        <div>
            <div class="name">OWL</div>
            <span class="tagline">Online WattLab · GoS1</span>
        </div>
    </div>
    <div class="watts"><span data-live="watts">{watts_str} W</span></div>
    <div class="label">GoS1 live telemetry</div>
    <div class="scope">Device layer only · {meter_display_name()} + lm-sensors · updates every 3s</div>
    <div class="temps">
        <div>
            <span class="t-val" data-live="cpu_tctl">—</span>
            <span class="t-lbl">CPU Tctl</span>
        </div>
        <div>
            <span class="t-val" data-live="gpu_junction">—</span>
            <span class="t-lbl">GPU junction</span>
        </div>
        <div>
            <span class="t-val" data-live="gpu_ppt_w">—</span>
            <span class="t-lbl">GPU PPT</span>
        </div>
    </div>
    <div class="nav">
        <div class="nav-tour"><a href="/demo">◆ Guided Tour</a></div>
        <div class="nav-video"><a href="/video">▶ Video transcode</a></div>
        <div class="nav-label">Beta · exploratory</div>
        <div class="nav-beta-note">
            Energy / quality / faithfulness tradeoffs we're investigating.<br>
            Less mature than video — signal can be below the P110 floor; interpret with care.
        </div>
        <div class="nav-ai">
            <a href="/image">Image generation <span class="beta-tag">BETA</span></a>
            <a href="/llm">LLM inference <span class="beta-tag">BETA</span></a>
            <a href="/rag">RAG energy test <span class="beta-tag">BETA</span></a>
            <a href="/video-enhance">Video enhancement <span class="beta-tag">Concept demo</span></a>
        </div>
        <div class="nav-util">
            <a href="/queue-status">⏱ Queue</a>
            <a href="/benchmark">📊 Benchmarks</a>
            <a href="/settings">⚙ Settings</a>
            <a href="/methodology">📐 Methodology</a>
        </div>
    </div>
    {_FOOTER}
</body>
</html>"""

@app.get("/power", dependencies=[Depends(requires(LIVE_TELEMETRY))])
async def power_json():
    return {"watts": _power_cache["watts"], "scope": "device_only", "source": "tapo_p110"}


@app.get("/live", dependencies=[Depends(requires(LIVE_TELEMETRY))])
async def live_json():
    """Bundled live telemetry for the shared UI poller. One round-trip for
    everything that updates in real-time on any page: watts, temps, GPU PPT,
    queue depth, pause state. Values may be None if a source is temporarily
    unavailable."""
    return {
        "watts":        _power_cache["watts"],
        "cpu_tctl":     _power_cache["cpu_tctl"],
        "gpu_junction": _power_cache["gpu_junction"],
        "gpu_ppt_w":    _power_cache["gpu_ppt_w"],
        "queue_depth":  queue_control.depth(),
        "paused":       queue_control.paused(),
    }


@app.get("/carbon", dependencies=[Depends(requires(LIVE_TELEMETRY))])
async def carbon_json():
    """Diagnostic + UI feed for the carbon module. Returns the home-zone
    intensity (live or static fallback) and the comparison-cities table.
    Used by the shared `wlCarbonStrip` JS helper to render the per-result
    "if this had run elsewhere" comparison strip."""
    return carbon.status()

# --- Video page ---

def _video_source_picker_html() -> str:
    """CR-047 — render the /video Source picker from
    `sources.get_grouped_sources()`. Pre-CR-047 the radios were a
    hardcoded HTML block alongside `sources.PRELOADED`; this drives them
    off the schema so adding a variant only requires editing sources.py.
    Each parent gets a small dim header (name + license), variants under
    it as radios with the same density / border style as the upload row.
    """
    label_style = (
        "display:flex;align-items:flex-start;gap:0.75rem;"
        "border:1px solid var(--border-3);padding:0.75rem;cursor:pointer"
    )
    radio_style = "margin-top:0.2rem;accent-color:var(--accent)"
    title_style = "color:var(--text);font-size:0.85rem"
    desc_style = "color:var(--text-3);font-size:0.75rem"
    header_style = (
        "color:var(--text-4);font-size:0.7rem;text-transform:uppercase;"
        "letter-spacing:0.05em;padding:0.5rem 0 0.15rem;"
        "display:flex;align-items:center;gap:0.5rem"
    )
    thumb_style = (
        "height:32px;width:auto;border-radius:2px;"
        "border:1px solid var(--border-3);flex-shrink:0"
    )
    # Subtle hyperlink style — inherit the dim header colour, dotted underline
    # so the link is discoverable without shouting (full underline would read
    # as link-soup against the deliberately quiet header row).
    link_style = "color:inherit;text-decoration:none;border-bottom:1px dotted var(--border-3)"
    parts = []
    for src in get_grouped_sources():
        lic = src.get("license")
        suffix = f" · {lic}" if lic else ""
        thumb = src.get("vignette")
        thumb_html = (f'<img src="{thumb}" alt="" style="{thumb_style}">'
                      if thumb else "")
        url = src.get("source_url")
        label = f'{src["name"]}{suffix}'
        # External link → new tab + noopener so the picker keeps its state.
        # No url → plain <span> (e.g. the in-house GoS promo has no canonical
        # external page to link to).
        label_html = (
            f'<a href="{url}" target="_blank" rel="noopener" '
            f'title="Canonical source · {url}" style="{link_style}">{label}</a>'
            if url else f'<span>{label}</span>'
        )
        parts.append(
            f'<div style="{header_style}">'
            f'{thumb_html}{label_html}'
            f'</div>'
        )
        for v in src["variants"]:
            key = v["key"]
            parts.append(
                f'<label style="{label_style}">'
                f'<input type="radio" name="source" value="{key}" '
                f'onchange="selectSource(\'{key}\')" '
                f'style="{radio_style}">'
                f'<div>'
                f'<div style="{title_style}">{v["variant_label"]}</div>'
                f'<div style="{desc_style}">{v["description"]}</div>'
                f'</div>'
                f'</label>'
            )
    return "".join(parts)


@app.get("/video", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def video_page(request: Request):
    # CR-001 part C2c — custom ffmpeg edits were Lab-only by UI before
    # CR-001 had a notion of Member tier. Now they key on CUSTOM_PROMPT
    # (Member+), matching the runtime gate in /video/use-source. The
    # all_codecs preset and custom-cmd textareas show as locked for
    # Anonymous with a "Members only · Join GoS" badge.
    can_custom_cmd    = can(audience.tier(request), CUSTOM_PROMPT)
    can_batch_compare = can(audience.tier(request), BATCH_COMPARE)
    can_upload        = can(audience.tier(request), CUSTOM_UPLOAD)
    lk_cmd_class      = _lock_class(request, CUSTOM_PROMPT)
    lk_cmd_badge      = _lock_badge_html(request, CUSTOM_PROMPT, "Custom ffmpeg — Members only")
    lk_batch_class    = _lock_class(request, BATCH_COMPARE)
    lk_batch_badge    = _lock_badge_html(request, BATCH_COMPARE, "All-codecs sweep — Members only")
    lk_upload_class   = _lock_class(request, CUSTOM_UPLOAD)
    lk_upload_badge   = _lock_badge_html(request, CUSTOM_UPLOAD, "Upload — Members only")
    upload_disabled   = _disabled_attr(request, CUSTOM_UPLOAD)
    queue_depth = queue_control.depth()
    busy_banner = (f'<div style="background:var(--border-3);color:var(--warn);padding:0.75rem 1rem;'
                   f'margin-bottom:1rem;font-size:0.85rem">'
                   f'⏱ {queue_depth} job{"s" if queue_depth != 1 else ""} in queue — '
                   f'yours will be added and run automatically.</div>') \
        if queue_depth > 0 else ""
    source_picker_html = _video_source_picker_html()
    # CR-054 — discreet beta link to the AV1 hw-vs-sw VMAF finding (the
    # worked example). Gated on `findings_enabled` so the same flag that
    # rolls back the /findings route also removes this link. When CR-055
    # (catalog index) ships, this can repoint at /findings with a video
    # filter; for now it deep-links to the one finding that exists.
    findings_beta_html = ""
    if cfg.load().get("findings_enabled", False):
        findings_beta_html = (
            '<div style="margin-bottom:1rem;font-size:0.78rem;color:var(--text-3);'
            'border-left:2px solid var(--accent-soft);padding-left:0.75rem">'
            '<span style="font-size:0.55rem;letter-spacing:0.08em;color:var(--text-5);'
            'border:1px solid var(--border-3);padding:0.1rem 0.35rem;'
            'text-transform:uppercase;margin-right:0.4rem">beta</span>'
            'Some initial findings: '
            '<a href="/findings" '
            'style="color:var(--accent);text-decoration:none">'
            'browse the OWL findings catalog →</a>'
            '</div>'
        )

    return _bake_durations(f"""<!DOCTYPE html>
<html>
<head>
    <link rel="icon" type="image/svg+xml" href="/static/owl.svg">
  <title>OWL — Video Test</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: monospace; background: var(--bg); color: var(--text);
               max-width: 780px; margin: 0 auto; padding: 2rem; }}
        h1 {{ color: var(--accent); margin-bottom: 0.25rem; font-size: 1.6rem; }}
        .subtitle {{ color: var(--text-3); font-size: 0.8rem; margin-bottom: 1.5rem; }}
        .info {{ color: var(--text-3); font-size: 0.82rem; margin-bottom: 1.5rem;
                 border-left: 2px solid #222; padding-left: 1rem; line-height: 1.6; }}
        .presets {{ display: flex; gap: 0.75rem; margin-bottom: 1.5rem; }}
        .preset {{ border: 1px solid var(--border-3); padding: 1rem; cursor: pointer;
                   flex: 1; transition: border-color 0.15s; }}
        .preset:hover {{ border-color: #00ff9966; }}
        .preset.selected {{ border-color: var(--accent); background: #00ff9911; }}
        .preset h3 {{ color: var(--accent); font-size: 0.9rem; margin-bottom: 0.4rem; }}
        .preset p {{ color: var(--text-4); font-size: 0.78rem; line-height: 1.5; }}
        .preset .badge {{ display: inline-block; background: #00ff9922;
                          color: var(--accent); font-size: 0.7rem;
                          padding: 0.1rem 0.4rem; margin-bottom: 0.4rem; }}
        .pdesc {{ margin-top: 0.4rem; }}
        .pdesc summary {{ color: var(--text-4); font-size: 0.7rem; cursor: pointer; list-style: none; }}
        .pdesc summary::-webkit-details-marker {{ display: none; }}
        .pdesc summary::before {{ content: '▸ '; }}
        details[open].pdesc summary::before {{ content: '▾ '; }}
        .pdesc[open] {{ color: var(--text-3); font-size: 0.72rem; line-height: 1.5; padding-top: 0.3rem; }}
        input[type=file] {{ color: var(--text-2); margin-bottom: 1rem; width: 100%; }}
        button {{ background: var(--accent); color: #000; border: none;
                  padding: 0.75rem 2rem; cursor: pointer;
                  font-family: monospace; font-size: 1rem; }}
        button:disabled {{ background: var(--border); color: var(--text-3); cursor: not-allowed; }}
        button:hover:not(:disabled) {{ background: var(--accent-hover); }}
        #status {{ margin-top: 1.5rem; }}

        /* Progress styles */
        .progress-box {{ border: 1px solid var(--border); padding: 1.5rem; }}
        .progress-header {{ color: var(--warn); font-size: 0.9rem; margin-bottom: 1.25rem; }}
        .stages {{ display: flex; flex-direction: column; gap: 0.5rem; margin-bottom: 1.25rem; }}
        .stage {{ display: flex; align-items: center; gap: 0.75rem; font-size: 0.82rem; }}
        .stage-icon {{ width: 1.2rem; text-align: center; flex-shrink: 0; }}
        .stage-label {{ color: var(--text-4); }}
        .stage.done .stage-label {{ color: var(--accent); }}
        .stage.active .stage-label {{ color: var(--warn); }}
        .stage.active .stage-icon {{ animation: pulse 1s infinite; }}
        @keyframes pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.3; }} }}
        .progress-footer {{ display: flex; justify-content: space-between;
                            color: var(--text-4); font-size: 0.78rem; border-top: 1px solid var(--panel);
                            padding-top: 0.75rem; }}
        .elapsed {{ color: var(--text-3); }}

        /* Report styles */
        .report h2 {{ color: var(--accent); font-size: 1.1rem; margin-bottom: 1rem;
                      padding-bottom: 0.5rem; border-bottom: 1px solid var(--border); }}
        .cols {{ display: flex; gap: 1rem; margin-bottom: 1rem; }}
        .col {{ flex: 1; border: 1px solid var(--border); padding: 1rem; }}
        .col h3 {{ color: var(--accent); font-size: 0.85rem; margin-bottom: 0.4rem; }}
        .col .sub {{ color: var(--text-3); font-size: 0.75rem; margin-bottom: 0.75rem; }}
        .metric {{ display: flex; justify-content: space-between;
                   padding: 0.3rem 0; border-bottom: 1px solid var(--panel); font-size: 0.82rem; }}
        .metric:last-child {{ border-bottom: none; }}
        .val {{ color: var(--accent); }}
        .section-title {{ color: var(--text-4); font-size: 0.72rem; text-transform: uppercase;
                          letter-spacing: 0.05em; margin: 0.75rem 0 0.4rem; }}
        .analysis-box {{ border: 1px solid #00ff9944; padding: 1rem;
                         margin-bottom: 1rem; background: #00ff9908; }}
        .analysis-box h3 {{ color: var(--accent); font-size: 0.85rem; margin-bottom: 0.5rem; }}
        .finding {{ color: var(--text-2); font-size: 0.85rem; line-height: 1.7; }}
        .conf-note {{ color: var(--text-4); font-size: 0.78rem; margin-top: 0.5rem; }}
        .scope-note {{ color: var(--text-5); font-size: 0.72rem; margin-top: 1rem; }}
        .single-report {{ border: 1px solid var(--border); padding: 1.5rem; }}
        a.back {{ color: var(--text-3); text-decoration: none; font-size: 0.82rem;
                  display: inline-block; margin-top: 1.5rem; }}
        a.back:hover {{ color: var(--accent); }}
        {_LOCK_STYLES}
    </style>
</head>
<body>
    {_BACK}
    {busy_banner}
    <h1>Video Transcode Energy Test</h1>
    <div class="subtitle">Greening of Streaming · OWL · GoS1</div>

    <div style="margin-bottom:1rem;font-size:0.78rem;color:var(--text-3)">
        First time here? <a href="/demo" style="color:var(--accent);text-decoration:none">Try the Guided Tour →</a>
    </div>

    {findings_beta_html}

    <details style="margin-bottom:1.5rem;border-left:2px solid #222;padding-left:1rem">
        <summary style="cursor:pointer;color:var(--text-3);font-size:0.82rem;list-style:none;outline:none">
            ⓘ About this test <span style="color:var(--text-4);font-size:0.72rem">(click to expand)</span>
        </summary>
        <div style="color:var(--text-3);font-size:0.82rem;line-height:1.6;margin-top:0.75rem">
            Transcode a source video and measure the server's wall-power draw during the encode.<br>
            Accepted: MP4, MOV, MKV, AVI, WebM, TS · Max 1GB.<br>
            Baseline measured 10s before each run · P110 + thermals at 1s intervals.<br>
            All GPU presets use the full VAAPI pipeline (hardware decode + encode + scale) — representative of live encoding workflows.<br>
            Rate control is ABR (constant bitrate target) across all 6 presets so CPU and GPU receive identical tasks.<br>
            Scope: device layer only — network, CDN, and client devices (CPE) excluded.
        </div>
    </details>

    <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                letter-spacing:0.05em;margin-bottom:0.5rem">H.264</div>
    <div class="presets" style="margin-bottom:0.75rem">
        <div class="preset" id="preset-cpu" onclick="selectPreset('cpu')">
            <h3>H.264 CPU</h3>
            <p class="pspec">libx264 · ABR · 1080p</p>
            <details class="pdesc"><summary>details</summary>Software encode across all 24 cores.</details>
        </div>
        <div class="preset" id="preset-gpu" onclick="selectPreset('gpu')">
            <h3>H.264 GPU</h3>
            <p class="pspec">{_gpu_enc('h264')} · ABR · 1080p · full pipeline</p>
            <details class="pdesc"><summary>details</summary>Hardware decode + encode. Full GPU pipeline — representative of live encoding.</details>
        </div>
        <div class="preset selected" id="preset-both" onclick="selectPreset('both')">
            <h3>H.264 Both</h3>
            <p class="pspec">CPU then GPU · same file</p>
            <details class="pdesc"><summary>details</summary>Side-by-side energy + thermal report with analysis.</details>
        </div>
    </div>
    <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                letter-spacing:0.05em;margin-bottom:0.5rem">H.265</div>
    <div class="presets" style="margin-bottom:0.75rem">
        <div class="preset" id="preset-h265_cpu" onclick="selectPreset('h265_cpu')">
            <h3>H.265 CPU</h3>
            <p class="pspec">libx265 · ABR · 1080p</p>
            <details class="pdesc"><summary>details</summary>Software HEVC encode.</details>
        </div>
        <div class="preset" id="preset-h265_gpu" onclick="selectPreset('h265_gpu')">
            <h3>H.265 GPU</h3>
            <p class="pspec">{_gpu_enc('h265')} · ABR · 1080p · full pipeline</p>
            <details class="pdesc"><summary>details</summary>Hardware decode + encode. Full GPU pipeline.</details>
        </div>
        <div class="preset" id="preset-h265_both" onclick="selectPreset('h265_both')">
            <h3>H.265 Both</h3>
            <p class="pspec">CPU then GPU · same file</p>
            <details class="pdesc"><summary>details</summary>Side-by-side H.265 CPU vs GPU comparison.</details>
        </div>
    </div>
    <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                letter-spacing:0.05em;margin-bottom:0.5rem">AV1</div>
    <div class="presets" style="margin-bottom:1.5rem">
        <div class="preset" id="preset-av1_cpu" onclick="selectPreset('av1_cpu')">
            <h3>AV1 CPU</h3>
            <p class="pspec">libsvtav1 · ABR · 1080p</p>
            <details class="pdesc"><summary>details</summary>SVT-AV1 software encode.</details>
        </div>
        <div class="preset" id="preset-av1_gpu" onclick="selectPreset('av1_gpu')">
            <h3>AV1 GPU</h3>
            <p class="pspec">{_gpu_enc('av1')} · ABR · 1080p · full pipeline</p>
            <details class="pdesc"><summary>details</summary>Hardware decode + AV1 encode on the GPU's dedicated AV1 engine.</details>
        </div>
        <div class="preset" id="preset-av1_both" onclick="selectPreset('av1_both')">
            <h3>AV1 Both</h3>
            <p class="pspec">CPU then GPU · same file</p>
            <details class="pdesc"><summary>details</summary>Side-by-side AV1 CPU vs GPU comparison.</details>
        </div>
    </div>

    {lk_batch_badge}
    <div class="{lk_batch_class}" style="border:1px solid #00ff9933;padding:0.9rem 1rem;margin-bottom:0.6rem;
                display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.5rem"
         id="preset-codecs_cpu" onclick="if(CAN_BATCH_COMPARE) selectPreset('codecs_cpu')">
        <div>
            <div style="color:var(--accent);font-size:0.9rem;font-weight:bold">Compare codecs · CPU (software)</div>
            <div style="color:var(--text-3);font-size:0.75rem;margin-top:0.2rem">H.264 · H.265 · AV1 on CPU · same source · same target bitrate — which codec is cheapest in software</div>
        </div>
        <div style="color:var(--text-4);font-size:0.75rem">~3× longer · locks queue</div>
    </div>
    <div class="{lk_batch_class}" style="border:1px solid #00ff9933;padding:0.9rem 1rem;margin-bottom:0.6rem;
                display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.5rem"
         id="preset-codecs_gpu" onclick="if(CAN_BATCH_COMPARE) selectPreset('codecs_gpu')">
        <div>
            <div style="color:var(--accent);font-size:0.9rem;font-weight:bold">Compare codecs · GPU (hardware)</div>
            <div style="color:var(--text-3);font-size:0.75rem;margin-top:0.2rem">H.264 · H.265 · AV1 on GPU · same source · same target bitrate — which codec is cheapest in hardware</div>
        </div>
        <div style="color:var(--text-4);font-size:0.75rem">~3× longer · locks queue</div>
    </div>
    <div class="{lk_batch_class}" style="border:1px solid #00ff9933;padding:0.9rem 1rem;margin-bottom:1.5rem;
                display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.5rem"
         id="preset-all_codecs" onclick="if(CAN_BATCH_COMPARE) selectPreset('all_codecs')">
        <div>
            <div style="color:var(--accent);font-size:0.9rem;font-weight:bold">Compare all (CPU vs GPU)</div>
            <div style="color:var(--text-3);font-size:0.75rem;margin-top:0.2rem">H.264 · H.265 · AV1 · CPU + GPU · same source · same target bitrate — full matrix</div>
        </div>
        <div style="color:var(--text-4);font-size:0.75rem">~6× longer · locks queue</div>
    </div>

    <div style="margin-bottom:1.5rem">
        <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                    letter-spacing:0.05em;margin-bottom:0.75rem">Source</div>
        <div style="display:flex;flex-direction:column;gap:0.5rem">
            <label style="display:flex;align-items:flex-start;gap:0.75rem;
                          border:1px solid var(--border-3);padding:0.75rem;cursor:pointer"
                   id="src-upload-label">
                <input type="radio" name="source" value="upload" checked
                       onchange="selectSource('upload')"
                       style="margin-top:0.2rem;accent-color:var(--accent)">
                <div>
                    <div style="color:var(--text);font-size:0.85rem">Upload a file</div>
                    <div style="color:var(--text-3);font-size:0.75rem">MP4, MOV, MKV, AVI, WebM, TS · Max 1GB</div>
                </div>
            </label>
            {source_picker_html}
        </div>
    </div>

    <div id="cmd-preview-area" class="{lk_cmd_class}" style="margin-bottom:1.5rem;display:none">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:0.5rem">
            <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                        letter-spacing:0.05em">ffmpeg command</div>
            <div>{lk_cmd_badge}</div>
        </div>
        <div id="cmd-preview-box"></div>
    </div>

    <div id="upload-area" class="{lk_upload_class}">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:0.5rem">
            <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                        letter-spacing:0.05em">Upload your own</div>
            <div>{lk_upload_badge}</div>
        </div>
        <input type="file" id="fileInput" accept=".mp4,.mov,.mkv,.avi,.webm,.ts"{upload_disabled}>
    </div>
    <button id="runBtn" onclick="uploadAndRun()"{upload_disabled}>Upload & Measure</button>

    <div id="status"></div>
    <div id="prev-runs" style="margin-top:2rem;border-top:1px solid var(--panel);padding-top:1.5rem"></div>

    <script>
    // CR-001 part C2c — capability flags from server. CAN_CUSTOM_CMD
    // mirrors the CUSTOM_PROMPT cap the /video/use-source route gates on;
    // CAN_BATCH_COMPARE mirrors the BATCH_COMPARE gate for all_codecs.
    const CAN_CUSTOM_CMD = {'true' if can_custom_cmd else 'false'};
    const CAN_BATCH_COMPARE = {'true' if can_batch_compare else 'false'};
    // IS_LAN kept as an alias so _cmdBox() reads naturally — same
    // editable-textarea-vs-readonly-div decision, just resolved against
    // the right capability now.
    const IS_LAN = CAN_CUSTOM_CMD;
    let selectedPreset = 'both';
    let selectedSource = 'upload';
    let customCmds = {{}};   // {{single: str}} or {{cpu: str, gpu: str}}

    function selectSource(src) {{
        selectedSource = src;
        document.getElementById('upload-area').style.display =
            src === 'upload' ? 'block' : 'none';
        document.getElementById('runBtn').textContent =
            src === 'upload' ? 'Upload & Measure' : 'Run Measurement';
    }}

    function _cmdBox(id, value, forceReadonly=false) {{
        if (IS_LAN && !forceReadonly) {{
            return '<textarea id="' + id + '" rows="3" spellcheck="false" '
                + 'style="width:100%;background:var(--panel-2);border:1px solid var(--border-2);'
                + 'color:var(--text-2);font-family:monospace;font-size:0.72rem;'
                + 'padding:0.5rem;resize:vertical;line-height:1.5">'
                + value + '</textarea>';
        }} else {{
            return '<div style="background:var(--panel-2);border:1px solid var(--border-2);'
                + 'padding:0.5rem;font-family:monospace;font-size:0.72rem;'
                + 'color:var(--text-3);word-break:break-all;line-height:1.5">' + value + '</div>';
        }}
    }}

    async function fetchCmdPreview(preset) {{
        const area = document.getElementById('cmd-preview-area');
        const box  = document.getElementById('cmd-preview-box');
        try {{
            const resp = await fetch('/video/preview-cmd?preset=' + preset);
            const data = await resp.json();
            if (data.mode === 'all_codecs') {{
                customCmds = {{}};
                const labels = {{cpu:'H.264 CPU',gpu:'H.264 GPU',h265_cpu:'H.265 CPU',h265_gpu:'H.265 GPU',av1_cpu:'AV1 CPU',av1_gpu:'AV1 GPU'}};
                box.innerHTML = Object.entries(data.cmds).map(([k,v]) =>
                    '<div style="color:var(--text-4);font-size:0.7rem;margin:0.4rem 0 0.2rem">' + (labels[k]||k) + '</div>'
                    + _cmdBox('cmd_'+k, v, true)
                ).join('');
            }} else if (data.mode === 'both') {{
                customCmds = {{cpu: data.cpu_cmd, gpu: data.gpu_cmd}};
                box.innerHTML =
                    '<div style="color:var(--text-4);font-size:0.7rem;margin-bottom:0.3rem">CPU</div>'
                    + _cmdBox('cmd_cpu', data.cpu_cmd)
                    + '<div style="color:var(--text-4);font-size:0.7rem;margin:0.5rem 0 0.3rem">GPU</div>'
                    + _cmdBox('cmd_gpu', data.gpu_cmd);
            }} else {{
                customCmds = {{single: data.cmd}};
                box.innerHTML = _cmdBox('cmd_single', data.cmd);
            }}
            area.style.display = 'block';
        }} catch(e) {{
            box.innerHTML = '<div style="color:var(--text-3);font-size:0.72rem">Could not load preview</div>';
            area.style.display = 'block';
        }}
    }}

    function _getCustomCmds() {{
        if (selectedPreset === 'both') {{
            const cpu = document.getElementById('cmd_cpu');
            const gpu = document.getElementById('cmd_gpu');
            return {{
                custom_cmd_cpu: cpu ? cpu.value : '',
                custom_cmd_gpu: gpu ? gpu.value : '',
            }};
        }} else {{
            const el = document.getElementById('cmd_single');
            return {{ custom_cmd: el ? el.value : '' }};
        }}
    }}
    let progressTimer = null;
    let elapsedTimer = null;
    let startTime = null;

    const _SINGLE = ['Baseline ({{BASELINE_S}}s)', 'Encode', 'Done'];
    const _SINGLE_MAP = {{'starting':0, 'baseline':0, 'cpu_encode':1, 'gpu_encode':1,
                          'h265_cpu_encode':1, 'h265_gpu_encode':1, 'av1_cpu_encode':1, 'done':2}};
    const _BOTH_STAGES = ['Baseline ({{BASELINE_S}}s)', 'CPU encode', '{{REST_LABEL}}', 'Baseline 2 ({{BASELINE_S}}s)', 'GPU encode', 'VMAF (quality)', 'Done'];
    const _BOTH_MAP = {{'starting':0, 'baseline':0, 'cpu_encode':1, 'rest':2,
                        'baseline_2':3, 'gpu_encode':4, 'vmaf':5, 'done':6}};
    const _ALL_STAGES = ['H.264 CPU','{{REST_LABEL}}','H.264 GPU','{{REST_LABEL}}','H.265 CPU','{{REST_LABEL}}','H.265 GPU','{{REST_LABEL}}','AV1 CPU','{{REST_LABEL}}','AV1 GPU','VMAF (quality)','Done'];
    const _ALL_MAP = {{'starting':0,
        'h264_cpu_baseline':0,'h264_cpu_encode':0,
        'h264_rest':1,
        'h264_gpu_baseline':2,'h264_gpu_encode':2,
        'h264_inter_rest':3,
        'h265_cpu_baseline':4,'h265_cpu_encode':4,
        'h265_rest':5,
        'h265_gpu_baseline':6,'h265_gpu_encode':6,
        'h265_inter_rest':7,
        'av1_cpu_baseline':8,'av1_cpu_encode':8,
        'av1_rest':9,
        'av1_gpu_baseline':10,'av1_gpu_encode':10,
        'vmaf':11,
        'done':12}};
    // Single-device codec sweeps (3 codecs on one device).
    const _CODECS_CPU_STAGES = ['H.264 CPU','{{REST_LABEL}}','H.265 CPU','{{REST_LABEL}}','AV1 CPU','VMAF (quality)','Done'];
    const _CODECS_GPU_STAGES = ['H.264 GPU','{{REST_LABEL}}','H.265 GPU','{{REST_LABEL}}','AV1 GPU','VMAF (quality)','Done'];
    const _CODECS_CPU_MAP = {{'starting':0,
        'h264_cpu_baseline':0,'h264_cpu_encode':0,
        'h265_cpu_rest':1,
        'h265_cpu_baseline':2,'h265_cpu_encode':2,
        'av1_cpu_rest':3,
        'av1_cpu_baseline':4,'av1_cpu_encode':4,
        'vmaf':5,'done':6}};
    const _CODECS_GPU_MAP = {{'starting':0,
        'h264_gpu_baseline':0,'h264_gpu_encode':0,
        'h265_gpu_rest':1,
        'h265_gpu_baseline':2,'h265_gpu_encode':2,
        'av1_gpu_rest':3,
        'av1_gpu_baseline':4,'av1_gpu_encode':4,
        'vmaf':5,'done':6}};
    const STAGES = {{
        cpu:        _SINGLE,
        gpu:        _SINGLE,
        h265_cpu:   _SINGLE,
        h265_gpu:   _SINGLE,
        av1_cpu:    _SINGLE,
        av1_gpu:    _SINGLE,
        both:       _BOTH_STAGES,
        h265_both:  _BOTH_STAGES,
        av1_both:   _BOTH_STAGES,
        all_codecs: _ALL_STAGES,
        codecs_cpu: _CODECS_CPU_STAGES,
        codecs_gpu: _CODECS_GPU_STAGES,
    }};

    const STAGE_MAP = {{
        cpu:        _SINGLE_MAP,
        gpu:        _SINGLE_MAP,
        h265_cpu:   _SINGLE_MAP,
        h265_gpu:   _SINGLE_MAP,
        av1_cpu:    _SINGLE_MAP,
        av1_gpu:    _SINGLE_MAP,
        both:       _BOTH_MAP,
        h265_both:  _BOTH_MAP,
        av1_both:   _BOTH_MAP,
        all_codecs: _ALL_MAP,
        codecs_cpu: _CODECS_CPU_MAP,
        codecs_gpu: _CODECS_GPU_MAP,
    }};

    function selectPreset(key) {{
        selectedPreset = key;
        document.querySelectorAll('.preset').forEach(el => el.classList.remove('selected'));
        // reset the batch-sweep box highlights (all-codecs + the two single-device sweeps)
        const BATCH_BOXES = ['all_codecs', 'codecs_cpu', 'codecs_gpu'];
        BATCH_BOXES.forEach(k => {{
            const b = document.getElementById('preset-' + k);
            if (b) b.style.borderColor = '#00ff9933';
        }});
        const el = document.getElementById('preset-' + key);
        if (el) {{
            el.classList.add('selected');
            if (BATCH_BOXES.includes(key)) el.style.borderColor = '#00ff99';
        }}
        fetchCmdPreview(key);
    }}

    // CR-035 \u2014 optional 5th arg `data` carries the full /video/job/<id>
    // dict so we can pluck the encode-progress fields. Old callers that
    // pass a literal stage string just don't populate the bar.
    function renderProgress(jobId, mode, serverStage, watts, data) {{
        const stages = STAGES[mode];
        const stageMap = STAGE_MAP[mode];
        const currentStage = stageMap[serverStage] !== undefined ? stageMap[serverStage] : 0;
        // VMAF (CR-044) doesn't pipe ffmpeg progress, but the server surfaces
        // vmaf_done / vmaf_total so we can still show "N of M".
        let vmafLine = '';
        if (serverStage === 'vmaf' && data && data.vmaf_total) {{
            vmafLine = '<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.4rem">'
                     + 'VMAF \xb7 ' + (data.vmaf_done || 0) + ' of ' + data.vmaf_total
                     + ' encode' + (data.vmaf_total > 1 ? 's' : '') + ' scored</div>';
        }}
        // Idle-wait cooldown readout \u2014 shared single source (wlCooldownLine in
        // _PROGRESS_JS). cooldown_waited_s is set ONLY by the active-probe path
        // (power.wait_for_thermal_floor), so the line shows only during a real
        // wait-for-idle; absent => the fixed Rest(Xs) the static label implies.
        let cdLine = wlCooldownLine(data);
        wlRenderProgress({{
            header: 'Running measurement \u2014 do not close this tab',
            stagesHtml: wlStageList(stages, currentStage),
            watts: watts,
            elapsed: startTime ? Date.now() - startTime : null,
            progressPct: data && data.progress_pct,
            etaS:        data && data.eta_s,
            encodeSpeed: data && data.encode_speed,
            extraHtml: vmafLine + cdLine + '<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.4rem">Job: ' + jobId + '</div>',
        }});
    }}

    function stopProgress() {{
        if (progressTimer) {{ clearInterval(progressTimer); progressTimer = null; }}
    }}

    async function uploadAndRun() {{
        const btn = document.getElementById('runBtn');
        btn.disabled = true;
        const status = document.getElementById('status');

        let resp;
        let isUpload = false;
        try {{
            const cmds = _getCustomCmds();
            if (selectedSource === 'upload') {{
                isUpload = true;
                const file = document.getElementById('fileInput').files[0];
                if (!file) {{ alert('Please select a file first'); btn.disabled = false; return; }}
                if (file.size > 1024 * 1024 * 1024) {{ alert('File too large (max 1GB)'); btn.disabled = false; return; }}
                status.innerHTML = '<div style="color:var(--warn)">Uploading ' + file.name + '...</div>';
                const form = new FormData();
                form.append('file', file);
                form.append('preset', selectedPreset);
                for (const [k, v] of Object.entries(cmds)) form.append(k, v);
                resp = await fetch('/video/upload', {{ method: 'POST', body: form }});
            }} else {{
                status.innerHTML = '<div style="color:var(--warn)">Starting measurement on ' + selectedSource + '...</div>';
                const form = new FormData();
                form.append('source_key', selectedSource);
                form.append('preset', selectedPreset);
                for (const [k, v] of Object.entries(cmds)) form.append(k, v);
                resp = await fetch('/video/use-source', {{ method: 'POST', body: form }});
            }}

            let data;
            try {{
                data = await resp.json();
            }} catch(_) {{
                const hint = isUpload && resp.status === 413
                    ? ' — file too large for server (nginx limit)'
                    : '';
                status.innerHTML = '<div style="color:var(--err)">Failed (HTTP ' + resp.status + ')' + hint + '.</div>';
                btn.disabled = false;
                return;
            }}
            if (data.job_id) {{
                startTime = Date.now();
                renderProgress(data.job_id, selectedPreset, 'starting');
                pollJob(data.job_id, selectedPreset);
            }} else {{
                status.innerHTML = '<div style="color:var(--err)">Error: ' + JSON.stringify(data) + '</div>';
                btn.disabled = false;
            }}
        }} catch(e) {{
            status.innerHTML = '<div style="color:var(--err)">Failed: ' + e + '</div>';
            btn.disabled = false;
        }}
    }}

    async function pollJob(jobId, mode) {{
        try {{
            const [resp, powerR] = await Promise.all([
                fetch('/video/job/' + jobId),
                fetch('/power').catch(() => null),
            ]);
            const data = await resp.json();
            const watts = powerR ? (await powerR.json().catch(()=>({{}}))).watts ?? null : null;
            if (data.status === 'done') {{
                stopProgress();
                renderResult(data.result, jobId);
                document.getElementById('runBtn').disabled = false;
            }} else if (data.status === 'error') {{
                stopProgress();
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + data.error + '</div>';
                document.getElementById('runBtn').disabled = false;
            }} else if (data.stage === 'queued') {{
                renderQueued(data.queue_position);
                setTimeout(() => pollJob(jobId, mode), 3000);
            }} else {{
                renderProgress(jobId, mode, data.stage || "starting", watts, data);
                // Poll fast during an idle-wait cooldown so the "waiting Xs for
                // floor" readout actually shows — GPU rests settle in a few
                // seconds and were slipping between the 5s polls. Normal cadence
                // otherwise (encodes are long).
                const _st = data.stage || '';
                const _inCooldown = data.cooldown_waited_s != null &&
                    (_st.indexOf('rest') !== -1 || _st.indexOf('cooldown') !== -1);
                setTimeout(() => pollJob(jobId, mode), _inCooldown ? 1000 : 2000);
            }}
        }} catch(e) {{
            setTimeout(() => pollJob(jobId, mode), 5000);
        }}
    }}

    function renderQueued(position) {{ wlRenderQueued(position); }}

    function metricRow(label, val, unit='') {{
        return `<div class="metric"><span>${{label}}</span>
                <span class="val">${{val}}${{unit ? ' ' + unit : ''}}</span></div>`;
    }}

    function renderSingle(r) {{
        const e = r.energy;
        const t = r.thermals;
        const pptNote = t.gpu_ppt_mean_w
            ? metricRow('GPU PPT mean / peak', t.gpu_ppt_mean_w + ' / ' + t.gpu_ppt_peak_w, 'W')
              + '<div style="color:var(--text-4);font-size:0.72rem;padding:0.1rem 0 0.6rem 1rem">'
              + 'GPU self-reported power (PPT). P110 ΔW above is the full system delta — includes CPU, RAM, drives.'
              + '</div>'
            : '';
        const cmdNote = r.transcode && r.transcode.ffmpeg_cmd
            ? '<details style="margin-top:0.75rem"><summary style="color:var(--text-5);font-size:0.72rem;cursor:pointer">ffmpeg command</summary>'
              + '<div style="color:var(--text-3);font-size:0.7rem;font-family:monospace;word-break:break-all;margin-top:0.4rem;padding:0.5rem;background:var(--panel-2);border:1px solid var(--border-2)">'
              + r.transcode.ffmpeg_cmd + '</div></details>'
            : '';
        return `
        <div class="single-report">
            <h2>Energy Report — ${{r.preset_label}}</h2>
            <div class="section-title">Encode</div>
            ${{metricRow('Preset', r.preset_detail)}}
            ${{metricRow('Duration', e.delta_t_s, 's')}}
            ${{metricRow('Output size', r.output_size_mb, 'MB')}}
            ${{cmdNote}}
            <div class="section-title">Power (P110)</div>
            ${{metricRow('Baseline', e.w_base, 'W')}}
            ${{metricRow('Task mean', e.w_task, 'W')}}
            ${{metricRow('Delta (ΔW)', e.delta_w, 'W')}}
            ${{metricRow('Energy (ΔE)', e.delta_e_wh, 'Wh')}}
            ${{wlCarbonRow(e)}}
            ${{metricRow('Polls', e.poll_count)}}
            <div class="section-title">Thermals</div>
            ${{metricRow('CPU base → peak', t.cpu_base + ' → ' + t.cpu_peak, '°C')}}
            ${{metricRow('GPU base → peak', t.gpu_base + ' → ' + t.gpu_peak, '°C')}}
            ${{pptNote}}
            <div class="conf-badge" style="margin-top:0.75rem">${{e.confidence.flag}} ${{e.confidence.label}}</div>
            ${{e.confidence.hint ? '<div style="margin-top:0.35rem;color:var(--text-3);font-size:0.72rem">' + e.confidence.hint + '</div>' : ''}}
            ${{wlCarbonStrip(e.delta_e_wh, r.preset_label, e.delta_t_s, e.co2e && e.co2e.intensity ? e.co2e.intensity.g_per_kwh : null)}}
        </div>`;
    }}

    function renderBoth(r) {{
        const cpu = r.cpu;
        const gpu = r.gpu;
        const a = r.analysis;

        function col(res) {{
            const e = res.energy;
            const t = res.thermals;
            // Side is CPU unless the preset key is a GPU variant. The bare
            // 'cpu'/'gpu' keys are H.264 only; H.265/AV1 use h265_/av1_ prefixes,
            // so a literal `=== 'cpu'` mismarked every non-H.264 comparison and
            // both columns inherited the GPU winner's flag.
            const side = res.preset_key.indexOf('gpu') !== -1 ? 'GPU' : 'CPU';
            const isEnergyWinner = a.energy_winner === side;
            const isSpeedWinner  = a.speed_winner  === side;
            const pptNote = t.gpu_ppt_mean_w
                ? metricRow('GPU PPT mean', t.gpu_ppt_mean_w, 'W')
                  + '<div style="color:var(--text-4);font-size:0.72rem;padding:0.1rem 0 0.6rem 1rem">'
                  + 'GPU self-reported · P110 ΔW is full system delta.'
                  + '</div>'
                : '';
            const cmdNote = res.transcode && res.transcode.ffmpeg_cmd
                ? '<details style="margin-top:0.5rem"><summary style="color:var(--text-5);font-size:0.7rem;cursor:pointer">ffmpeg command</summary>'
                  + '<div style="color:var(--text-3);font-size:0.68rem;font-family:monospace;word-break:break-all;margin-top:0.3rem;padding:0.4rem;background:var(--panel-2);border:1px solid var(--border-2)">'
                  + res.transcode.ffmpeg_cmd + '</div></details>'
                : '';
            return `<div class="col">
                <h3>${{res.preset_label}}</h3>
                <div class="sub">${{res.preset_detail}}</div>
                <div class="section-title">Encode</div>
                ${{metricRow('Duration', e.delta_t_s + (isSpeedWinner ? ' \U0001F3C1' : ''), 's')}}
                ${{metricRow('Output size', res.output_size_mb, 'MB')}}
                ${{metricRow('VMAF', res.vmaf != null ? res.vmaf : '—')}}
                ${{cmdNote}}
                <div class="section-title">Power (P110)</div>
                ${{metricRow('Baseline', e.w_base, 'W')}}
                ${{metricRow('Task mean', e.w_task, 'W')}}
                ${{metricRow('Peak delta', e.delta_w, 'W')}}
                ${{metricRow('Energy (ΔE)', e.delta_e_wh + (isEnergyWinner ? ' ✓' : ''), 'Wh')}}
                ${{wlCarbonRow(e)}}
                ${{metricRow('Polls', e.poll_count)}}
                <div class="section-title">Thermals</div>
                ${{metricRow('CPU base → peak', t.cpu_base + ' → ' + t.cpu_peak, '°C')}}
                ${{metricRow('GPU base → peak', t.gpu_base + ' → ' + t.gpu_peak, '°C')}}
                ${{pptNote}}
                <div class="conf-badge" style="margin-top:0.75rem;font-size:0.8rem">
                    ${{e.confidence.flag}} ${{e.confidence.label}}
                </div>
                ${{e.confidence.hint ? '<div style="margin-top:0.3rem;color:var(--text-3);font-size:0.7rem">' + e.confidence.hint + '</div>' : ''}}
            </div>`;
        }}

        // Carbon strip for the comparison report uses the lower of the two
        // energy figures (the more efficient option) — that's the headline
        // number for "given this is the best result here, here's how it'd
        // play out elsewhere".
        const cpuWh = (cpu.energy && cpu.energy.delta_e_wh) || null;
        const gpuWh = (gpu.energy && gpu.energy.delta_e_wh) || null;
        const stripWh = (cpuWh != null && gpuWh != null)
            ? Math.min(cpuWh, gpuWh)
            : (cpuWh != null ? cpuWh : gpuWh);
        // Label is the *winner's* preset, but explicitly framed as "best of
        // CPU vs GPU" so the visitor reads the carbon number as the most-
        // efficient mode of a comparison rather than the only mode tested.
        // The page above the strip already lists both per-device columns;
        // this just stops the strip from misleading on its own.
        const _winnerLbl = (cpuWh != null && gpuWh != null)
            ? (cpuWh <= gpuWh ? cpu.preset_label : gpu.preset_label)
            : (cpuWh != null ? cpu.preset_label : gpu.preset_label);
        const stripLbl = (cpuWh != null && gpuWh != null)
            ? (_winnerLbl + ' · best of CPU vs GPU')
            : _winnerLbl;
        // Saved intensity for the drift note — pull from the winning
        // side's energy.co2e block. Both sides share the same /carbon
        // snapshot at save time, so either would work.
        const _winnerE = (cpuWh != null && gpuWh != null)
            ? (cpuWh <= gpuWh ? cpu.energy : gpu.energy)
            : (cpuWh != null ? cpu.energy : gpu.energy);
        const _stripSavedG = _winnerE && _winnerE.co2e && _winnerE.co2e.intensity
            ? _winnerE.co2e.intensity.g_per_kwh : null;
        const _stripDur = _winnerE ? _winnerE.delta_t_s : null;
        // CR-032 — sub-runs for the carbon strip's per-mode breakdown.
        const _subRuns = [cpu, gpu].filter(s => s && s.energy && s.energy.co2e).map(s => ({{
            label: s.preset_label,
            grams: s.energy.co2e.grams,
            deltaWh: s.energy.delta_e_wh,
            durationS: s.energy.delta_t_s
        }}));
        return `
        <div class="report">
            <h2>Comparison Report</h2>
            <div class="analysis-box">
                <h3>Finding</h3>
                <div class="finding">${{a.finding}}</div>
                <div class="conf-note">${{a.confidence_note}}</div>
                ${{a.quality_note ? '<div class="conf-note" style="color:var(--accent)">◆ ' + a.quality_note + '</div>' : ''}}
            </div>
            <div class="cols">
                ${{col(cpu)}}
                ${{col(gpu)}}
            </div>
            ${{wlCarbonStrip(stripWh, stripLbl, _stripDur, _stripSavedG, _subRuns)}}
            <div class="scope-note">${{r.scope}}</div>
        </div>`;
    }}

    function renderAllCodecs(r) {{
        const codecs = r.codecs;
        const a = r.analysis;
        const codecOrder = [['h264','H.264'],['h265','H.265'],['av1','AV1']];
        const fmt = v => v != null ? v : '—';

        // Summary matrix table
        let tableRows = codecOrder.map(([key, label]) => {{
            const cd = codecs[key];
            if (!cd) return '';
            const ce = cd.cpu.energy, ge = cd.gpu.energy;
            const ca = cd.analysis;
            const ew = ca.energy_winner, sw = ca.speed_winner;
            const cpuWin = (ew==='CPU'?'✓':'') + (sw==='CPU'?' \U0001F3C1':'');
            const gpuWin = (ew==='GPU'?'✓':'') + (sw==='GPU'?' \U0001F3C1':'');
            // Headers right-align, so data cells must too — otherwise the
            // numeric columns drift left of their headers and visitors can't
            // read off CPU vs GPU at a glance.
            return `<tr>
                <td style="color:var(--text);font-weight:bold;text-align:left">${{label}}</td>
                <td style="text-align:right">${{fmt(ce.delta_t_s)}}s</td>
                <td style="color:${{ew==='CPU'?'#00ff99':'#888'}};text-align:right">${{fmt(ce.delta_e_wh)}} Wh ${{cpuWin}}</td>
                <td style="color:var(--text-3);font-size:0.75rem;text-align:right">${{fmt(cd.cpu.output_size_mb)}} MB</td>
                <td style="color:var(--text-3);font-size:0.75rem;text-align:right">${{fmt(cd.cpu.vmaf)}}</td>
                <td style="text-align:right">${{fmt(ge.delta_t_s)}}s</td>
                <td style="color:${{ew==='GPU'?'#00ff99':'#888'}};text-align:right">${{fmt(ge.delta_e_wh)}} Wh ${{gpuWin}}</td>
                <td style="color:var(--text-3);font-size:0.75rem;text-align:right">${{fmt(cd.gpu.output_size_mb)}} MB</td>
                <td style="color:var(--text-3);font-size:0.75rem;text-align:right">${{fmt(cd.gpu.vmaf)}}</td>
                <td class="conf-badge" style="font-size:0.78rem;text-align:center">${{ce.confidence.flag}} ${{ge.confidence.flag}}</td>
            </tr>`;
        }}).join('');

        const bestE = a.most_efficient;
        const bestS = a.fastest;
        const highlights = `
            <div style="display:flex;gap:1.5rem;flex-wrap:wrap;margin-top:0.75rem;font-size:0.82rem">
                <span>⚡ Most efficient: <span style="color:var(--accent)">${{bestE ? bestE.label + ' (' + bestE.delta_e_wh + ' Wh)' : '—'}}</span></span>
                <span>\U0001F3C1 Fastest: <span style="color:var(--accent)">${{bestS ? bestS.label + ' (' + bestS.delta_t_s + 's)' : '—'}}</span></span>
            </div>`;

        // Per-codec collapsible detail
        const details = codecOrder.map(([key, label]) => {{
            const cd = codecs[key];
            if (!cd) return '';
            function miniCol(res, tag) {{
                const e = res.energy, t = res.thermals;
                return `<div style="flex:1;min-width:180px">
                    <div style="color:var(--text-3);font-size:0.72rem;margin-bottom:0.4rem">${{tag}}</div>
                    ${{metricRow('Duration', e.delta_t_s, 's')}}
                    ${{metricRow('Output size', res.output_size_mb, 'MB')}}
                    ${{metricRow('VMAF', res.vmaf != null ? res.vmaf : '—')}}
                    ${{metricRow('Baseline', e.w_base, 'W')}}
                    ${{metricRow('ΔW', e.delta_w, 'W')}}
                    ${{metricRow('ΔE', e.delta_e_wh, 'Wh')}}
                    ${{wlCarbonRow(e)}}
                    ${{metricRow('Polls', e.poll_count)}}
                    ${{metricRow('CPU peak', t.cpu_peak, '°C')}}
                    ${{metricRow('GPU peak', t.gpu_peak, '°C')}}
                    <div class="conf-badge" style="margin-top:0.5rem;font-size:0.78rem">${{e.confidence.flag}} ${{e.confidence.label}}</div>
                    ${{e.confidence.hint ? '<div style="color:var(--text-3);font-size:0.7rem;margin-top:0.2rem">' + e.confidence.hint + '</div>' : ''}}
                </div>`;
            }}
            return `<details style="margin-top:0.5rem;border:1px solid var(--border-2);padding:0.75rem">
                <summary style="color:var(--text-3);font-size:0.8rem;cursor:pointer;list-style:none">
                    <span style="color:var(--accent)">${{label}}</span> — ${{cd.analysis.finding.slice(0,80)}}…
                </summary>
                <div style="display:flex;gap:1.5rem;flex-wrap:wrap;margin-top:0.75rem">
                    ${{miniCol(cd.cpu, cd.cpu.preset_label)}}
                    ${{miniCol(cd.gpu, cd.gpu.preset_label)}}
                </div>
            </details>`;
        }}).join('');

        // Strip uses the most-efficient codec/device's energy as the headline.
        // Label explicitly frames it as "most efficient of all codecs" so the
        // visitor can't read the carbon figure as if it were the only codec
        // tested — the matrix above the strip lists every codec/device pair.
        const stripWh = bestE && bestE.delta_e_wh != null ? bestE.delta_e_wh : null;
        const stripLbl = bestE
            ? (bestE.label + ' · most efficient codec across all comparisons')
            : 'Most efficient codec';
        // Winner's energy block — used for duration and saved-intensity drift
        // note. bestE carries codec/side; the full energy block lives in
        // r.codecs[codec][side].energy. All sub-runs share the same /carbon
        // snapshot at save time, so any of them would do for savedG.
        const _winE = (bestE && r.codecs && r.codecs[bestE.codec]
                       && r.codecs[bestE.codec][bestE.side])
            ? r.codecs[bestE.codec][bestE.side].energy : null;
        const _stripDur = _winE ? _winE.delta_t_s : null;
        const _stripSavedG = _winE && _winE.co2e && _winE.co2e.intensity
            ? _winE.co2e.intensity.g_per_kwh : null;
        // CR-032 — sub-runs for the carbon strip's per-mode breakdown
        // (6 cells: H.264/H.265/AV1 × CPU/GPU). Each cell carries its own
        // co2e snapshot, so the strip's details block surfaces all 6 instead
        // of eliding 5/6 of the work the visitor just ran.
        const _subRuns = [];
        codecOrder.forEach(([key, label]) => {{
            const cd = codecs[key];
            if (!cd) return;
            ['cpu','gpu'].forEach(side => {{
                const sub = cd[side];
                if (sub && sub.energy && sub.energy.co2e) {{
                    _subRuns.push({{
                        label: sub.preset_label || (label + ' ' + side.toUpperCase()),
                        grams: sub.energy.co2e.grams,
                        deltaWh: sub.energy.delta_e_wh,
                        durationS: sub.energy.delta_t_s
                    }});
                }}
            }});
        }});
        return `
        <div class="report">
            <h2>All Codecs — Energy &amp; Speed Matrix</h2>
            <table style="width:100%;border-collapse:collapse;font-size:0.82rem;margin-bottom:0.5rem">
                <thead><tr style="color:var(--text-4);font-size:0.72rem;text-transform:uppercase;letter-spacing:0.05em">
                    <th style="text-align:left;padding:0.3rem 0.5rem 0.5rem 0">Codec</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">CPU time</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">CPU energy</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">CPU out</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">CPU VMAF</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">GPU time</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">GPU energy</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">GPU out</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">GPU VMAF</th>
                    <th style="text-align:center;padding:0.3rem 0.5rem">Conf</th>
                </tr></thead>
                <tbody style="font-family:monospace">${{tableRows}}</tbody>
            </table>
            <div style="font-size:0.7rem;color:var(--text-5);margin-bottom:0.25rem">✓ energy winner · \U0001F3C1 speed winner · CPU out / GPU out should match — confirms same bitrate target · VMAF = perceptual quality 0–100 (higher better)</div>
            ${{highlights}}
            <div style="margin-top:1rem;color:var(--text-3);font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em">Per-codec detail</div>
            ${{details}}
            ${{wlCarbonStrip(stripWh, stripLbl, _stripDur, _stripSavedG, _subRuns)}}
            <div class="scope-note">${{r.scope}}</div>
        </div>`;
    }}

    function downloadLinks(jobId) {{
        const base = '/results/video/' + jobId;
        return `<div style="margin-top:1rem;display:flex;gap:0.75rem">
            <a href="${{base}}/download.json" download
               style="color:var(--accent);font-size:0.8rem;border:1px solid #00ff9944;
                      padding:0.3rem 0.75rem;text-decoration:none">↓ JSON</a>
            <a href="${{base}}/download.csv" download
               style="color:var(--accent);font-size:0.8rem;border:1px solid #00ff9944;
                      padding:0.3rem 0.75rem;text-decoration:none">↓ CSV</a>
            <a href="${{base}}/reproduce.zip" download
               style="color:var(--accent);font-size:0.8rem;border:1px solid #00ff9944;
                      padding:0.3rem 0.75rem;text-decoration:none">↓ Reproduce this</a>
        </div>`;
    }}

    function renderResult(r, jobId) {{
        const el = document.getElementById('status');
        const elapsed = startTime ? wlFormatElapsed(Date.now() - startTime) : '';
        const elapsedNote = elapsed ? `<div style="color:var(--text-4);font-size:0.78rem;margin-bottom:1rem">
            Total elapsed: ${{elapsed}}</div>` : '';
        const links = jobId ? downloadLinks(jobId) : '';
        let html;
        if (r.mode === 'both') {{
            html = renderBoth(r) + links;
        }} else if (r.mode === 'all_codecs') {{
            html = renderAllCodecs(r) + links;
        }} else if (r.mode === 'codecs_cpu' || r.mode === 'codecs_gpu') {{
            html = window.wlRenderCodecsSingle(r) + links;
        }} else {{
            html = renderSingle(r.result) + links;
        }}
        el.innerHTML = elapsedNote + html;
        loadPrevRuns();
    }}

    async function loadPrevRuns() {{
        try {{
            const resp = await fetch('/results/video/list');
            const runs = await resp.json();
            renderPrevRuns(runs);
        }} catch(e) {{}}
    }}

    function renderPrevRuns(runs) {{
        const el = document.getElementById('prev-runs');
        if (!runs || runs.length === 0) {{
            el.innerHTML = '<div style="color:var(--text-5);font-size:0.8rem">No previous runs.</div>';
            return;
        }}
        const rows = runs.map(r => {{
            const date = r.saved_at ? r.saved_at.slice(0,16).replace('T',' ') : '—';
            let summary, codec;
            if (r.mode === 'both') {{
                codec = [r.cpu_preset, r.gpu_preset].filter(Boolean).join(' vs ');
                summary = `CPU ${{r.cpu_delta_e_wh}} Wh ${{r.cpu_confidence ? '<span class="conf-badge">'+r.cpu_confidence+'</span>' : ''}} · GPU ${{r.gpu_delta_e_wh}} Wh ${{r.gpu_confidence ? '<span class="conf-badge">'+r.gpu_confidence+'</span>' : ''}}`;
            }} else if (r.mode === 'all_codecs') {{
                codec = 'H.264 · H.265 · AV1 — all codecs (CPU vs GPU)';
                summary = `Best: ${{r.most_efficient||'—'}} (${{r.best_delta_e_wh||'—'}} Wh) · Fastest: ${{r.fastest||'—'}} ${{r.all_green ? '<span class="conf-badge">🟢</span>' : ''}}`;
            }} else if (r.mode === 'codecs_cpu' || r.mode === 'codecs_gpu') {{
                const dev = r.mode === 'codecs_gpu' ? 'GPU (hardware)' : 'CPU (software)';
                codec = `H.264 · H.265 · AV1 — ${{dev}}`;
                summary = `Best: ${{r.most_efficient||'—'}} (${{r.best_delta_e_wh||'—'}} Wh) · Fastest: ${{r.fastest||'—'}} ${{r.all_green ? '<span class="conf-badge">🟢</span>' : ''}}`;
            }} else {{
                codec = r.preset || '';
                summary = `${{r.delta_e_wh}} Wh ${{r.confidence ? '<span class="conf-badge">'+r.confidence+'</span>' : ''}}`;
            }}
            const base = '/results/video/' + r.job_id;
            const savedAt = r.saved_at || '';
            return `<div style="border-bottom:1px solid var(--panel);padding:0.6rem 0">
                <div style="display:flex;justify-content:space-between;align-items:baseline">
                    <span style="color:var(--text);font-size:0.82rem">${{date}}</span>
                    <span style="color:var(--text-3);font-size:0.75rem;font-family:monospace">${{r.job_id}}</span>
                </div>
                <div style="color:var(--text-3);font-size:0.75rem;margin:0.1rem 0">${{codec}}</div>
                <div style="color:var(--accent);font-size:0.8rem;margin:0.2rem 0">${{summary}}</div>
                <div style="display:flex;gap:0.75rem;margin-top:0.3rem;align-items:center">
                    <a href="javascript:void(0)"
                       onclick="wlExpandPrevRow('video','${{r.job_id}}','${{savedAt}}')"
                       style="color:var(--text-3);font-size:0.75rem;text-decoration:none;cursor:pointer">
                       <span id="chev-${{r.job_id}}">▸</span> Show full result</a>
                    <a href="${{base}}/download.json" download
                       style="color:var(--text-5);font-size:0.75rem;text-decoration:none">↓ JSON</a>
                    <a href="${{base}}/download.csv" download
                       style="color:var(--text-5);font-size:0.75rem;text-decoration:none">↓ CSV</a>
                </div>
                <div id="expand-${{r.job_id}}" style="display:none;margin-top:0.6rem"></div>
            </div>`;
        }}).join('');
        el.innerHTML = `<div style="color:var(--text-4);font-size:0.72rem;text-transform:uppercase;
            letter-spacing:0.05em;margin-bottom:0.75rem">Previous runs</div>${{rows}}`;
    }}

    loadPrevRuns();
    fetchCmdPreview(selectedPreset);
    const _resumeJob = new URLSearchParams(location.search).get('job');
    if (_resumeJob) {{ pollJob(_resumeJob, 'both'); }}
    </script>
    {_PROGRESS_JS}
    {_RESULT_JS}
    {_CONF_HELP_WIDGET}
    {_FOOTER}
</body>
</html>""")


# --- CR-042 · Pixop placeholder (video enhancement demo) -------------------
#
# Self-contained placeholder for ML-based video enhancement (denoise,
# super-resolution, frame interpolation). Pre-meeting tactical for the
# 2026-05-13 Pixop demo. Reversibility constraint: this block + the home-
# page tile insertion + the FileResponse import are the only places that
# touch the topic. No measurement-spine code, no settings, no persistence,
# no capability, no schema change. Revert deletes this block and the home
# additions; nothing else.

_VIDEO_ENHANCE_ASSETS = {
    "meridian_120s.mp4":      Path("/home/gos/wattlab/test_content/meridian_120s.mp4"),
    "meridian_120s_lowq.mp4": Path("/home/gos/wattlab/test_content/meridian_120s_lowq.mp4"),
}


# Lab-styled 404 body — small HTML page so a browser visit shows a
# recognisable "not found" rather than a JSON dump. Same 404 status
# code; `<video>` consumers still treat it as a load failure, so no
# behaviour change there.
_VIDEO_ENHANCE_404 = (
    '<!DOCTYPE html><html><head>'
    '<link rel="icon" type="image/svg+xml" href="/static/owl.svg">'
    '<title>OWL — 404 Not Found</title>'
    '<style>body{font-family:monospace;background:#0a0a0a;color:#e0e0e0;'
    'max-width:480px;margin:0 auto;padding:4rem 2rem;text-align:center;'
    'line-height:1.6}h1{color:#00ff99;font-size:1.2rem;margin-bottom:0.5rem}'
    'p{color:#8a8a8a;font-size:0.85rem;margin-bottom:1.5rem}'
    'code{color:#ffaa00}a{color:#00ff99;text-decoration:none}</style>'
    '</head><body>'
    '<h1>404 · Not found</h1>'
    '<p>No asset by that name on the <code>/video-enhance/asset/</code> endpoint.<br>'
    'Allowlist: <code>meridian_120s.mp4</code>, <code>meridian_120s_lowq.mp4</code>.</p>'
    '<p><a href="/video-enhance">← Video enhancement (placeholder)</a> · '
    '<a href="/">Home</a></p>'
    '</body></html>'
)


@app.get("/video-enhance/asset/{name}",
         dependencies=[Depends(requires(PUBLIC_PAGE))])
async def video_enhance_asset(name: str):
    path = _VIDEO_ENHANCE_ASSETS.get(name)
    if path is None or not path.exists():
        return HTMLResponse(_VIDEO_ENHANCE_404, status_code=404)
    return FileResponse(path, media_type="video/mp4")


# Plain string (not f-string) so JS object literals don't need escaping;
# Python-side placeholders are explicit `{NAME}` tokens replaced once at
# render time, same pattern /methodology and /queue-status use.
_VIDEO_ENHANCE_HTML = """<!DOCTYPE html>
<html>
<head>
  <link rel="icon" type="image/svg+xml" href="/static/owl.svg">
  <title>OWL — Video Enhancement (placeholder)</title>
  <style>
    {AUTH_CHIP_STYLES}
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: monospace; background: var(--bg); color: var(--text);
           max-width: 780px; margin: 0 auto; padding: 2rem 1rem; }
    h1 { color: var(--warn); margin-bottom: 0.25rem; font-size: 1.45rem;
         letter-spacing: 0.01em; }
    .subtitle { color: var(--text-3); font-size: 0.82rem; margin-bottom: 1.5rem;
                letter-spacing: 0.04em; }
    .back { display: inline-block; color: var(--text-4); text-decoration: none;
            font-size: 0.82rem; margin-bottom: 1.25rem; }
    .back:hover { color: var(--accent); }
    .placeholder-band { background: rgba(255,170,0,0.06);
                        border-left: 3px solid var(--warn); padding: 0.85rem 1rem;
                        margin-bottom: 1.75rem; color: var(--text-2);
                        font-size: 0.85rem; line-height: 1.65; }
    .placeholder-band .lead { color: var(--warn); font-size: 0.95rem;
                              font-weight: bold; display: block;
                              margin-bottom: 0.4rem; letter-spacing: 0.02em; }
    .vid-wrap { background: var(--panel); border: 1px solid var(--border-2);
                padding: 0.45rem; margin-bottom: 0.85rem; }
    .vid-wrap video { width: 100%; display: block; background: #000; }
    .vid-caption { color: var(--text-4); font-size: 0.74rem;
                   margin-top: 0.4rem; font-family: monospace; }
    .section-label { color: var(--text-3); font-size: 0.85rem;
                     margin: 1.5rem 0 0.65rem; letter-spacing: 0.02em; }
    .options { display: flex; gap: 0.6rem; flex-wrap: wrap;
               margin-bottom: 1.25rem; }
    .enhance-chip { flex: 1; min-width: 210px; background: var(--panel);
                    border: 1px solid var(--border-3); color: var(--text-2);
                    padding: 0.75rem 0.9rem; font-family: monospace;
                    cursor: pointer; font-size: 0.85rem; line-height: 1.45;
                    text-align: left; transition: border-color 0.15s; }
    .enhance-chip:hover:not(.disabled) { border-color: var(--warn);
                                         color: var(--text); }
    .enhance-chip .chip-label { color: var(--accent); font-weight: bold;
                                display: block; margin-bottom: 0.25rem; }
    .enhance-chip .chip-meta { color: var(--text-4); font-size: 0.72rem; }
    .enhance-chip.disabled { opacity: 0.45; cursor: not-allowed; }
    #enhance-status { margin-bottom: 1.5rem; }
    .result-card { display: none; border: 1px solid var(--warn);
                   padding: 1rem 1.15rem; margin-bottom: 1.25rem;
                   background: rgba(255,170,0,0.025); }
    .result-card .rc-header { color: var(--warn); font-size: 0.7rem;
                              letter-spacing: 0.08em; text-transform: uppercase;
                              margin-bottom: 0.55rem; }
    .result-card .rc-kpi { display: flex; gap: 1.6rem; flex-wrap: wrap;
                           margin-bottom: 0.75rem; }
    .result-card .rc-kpi > div { display: flex; flex-direction: column;
                                 gap: 0.18rem; }
    .result-card .rc-kpi .val { color: var(--accent); font-size: 1.2rem;
                                font-family: monospace; }
    .result-card .rc-kpi .lbl { color: var(--text-4); font-size: 0.66rem;
                                letter-spacing: 0.05em; text-transform: uppercase; }
    .result-card .illustrative-tag { color: var(--warn); font-size: 0.65rem;
                                     font-weight: normal; letter-spacing: 0.04em; }
    .result-card .rc-note { color: var(--text-4); font-size: 0.72rem;
                            margin: 0.4rem 0 0.4rem; font-family: monospace;
                            line-height: 1.55; }
    .footer-note { color: var(--text-4); font-size: 0.78rem; line-height: 1.65;
                   border-left: 2px solid var(--border-2);
                   padding-left: 0.9rem; margin-top: 2.5rem; }
    .footer-note a { color: var(--text-3); }
  </style>
</head>
<body>
{AUTH_CHIP}
<a href="/" class="back">&larr; Home</a>

<h1>Video Enhancement</h1>
<div class="subtitle">Placeholder &middot; illustrative values, not measured</div>

<div class="placeholder-band">
  <span class="lead">&#9888; This page is a placeholder.</span>
  Where a partner using small specialised ML models &mdash; for example denoise,
  super-resolution, or frame interpolation &mdash; would slot into the OWL
  measurement chain. The numbers below are <strong>illustrative</strong> and not
  produced by a real measurement run on this server. If this category lands as a
  real OWL measurement, every figure here would be replaced by a P110-polled
  delta with a variance-based confidence flag, just like every other workload.
</div>

<div class="section-label">Input video</div>
<div class="vid-wrap">
  <video controls preload="metadata" muted>
    <source src="/video-enhance/asset/meridian_120s_lowq.mp4" type="video/mp4">
  </video>
  <div class="vid-caption">Input &middot; 720p &times; ~1.5 Mbps H.264 (Meridian-120s, degraded for the demo)</div>
</div>

<div class="section-label">Pick a (placeholder) enhancement</div>
<div class="options">
  <button class="enhance-chip" onclick="startEnhance('denoise')">
    <span class="chip-label">Denoise</span>
    <span class="chip-meta">small CNN &middot; ~5M params</span>
  </button>
  <button class="enhance-chip" onclick="startEnhance('superres')">
    <span class="chip-label">Super-resolution</span>
    <span class="chip-meta">medium CNN &middot; ~25M params &middot; 720p &rarr; 1080p</span>
  </button>
  <button class="enhance-chip" onclick="startEnhance('interp')">
    <span class="chip-label">Frame interpolation</span>
    <span class="chip-meta">specialised model &middot; 25 &rarr; 50 fps</span>
  </button>
</div>

<div id="enhance-status"></div>

<div id="result-card" class="result-card"></div>

<div id="after-viewer" style="display:none">
  <div class="section-label">Enhanced output</div>
  <div class="vid-wrap">
    <video controls preload="metadata" muted>
      <source src="/video-enhance/asset/meridian_120s.mp4" type="video/mp4">
    </video>
    <div class="vid-caption" id="after-caption">Output &middot; enhanced (illustrative)</div>
  </div>
</div>

<div class="footer-note">
  If a workload like this becomes a real OWL measurement, it inherits the
  standard protocol: P110 polling at 1&nbsp;Hz, focus mode, variance-based
  confidence flag. See <a href="/methodology">/methodology</a> for the
  measurement framework. The illustrative ranges chosen for this placeholder
  sit inside the position paper's small-specialised-CNN envelope &mdash; OWL
  does not yet measure this category directly.
</div>

{PROGRESS_JS}
{FOOTER}

<script>
// Illustrative parameter table. Energy ranges chosen to sit inside the
// Language Lab AI position paper's "small specialised CNN" envelope on a
// 120s clip. Peak ΔW is a plausible shape for these models on a Ryzen 9
// 7900 / RX 7800 XT. Everything here is for the placeholder UI only; the
// real measurement would land here when the workload runs locally.
var ENHANCE_OPTIONS = {
  denoise:  { label: 'Denoise · small CNN',             durationS: 4.0,
              energyWh: 0.03, peakDeltaW: 9,
              caption: 'Output · denoised (illustrative — full-quality master shown for comparison)' },
  superres: { label: 'Super-resolution · medium CNN',   durationS: 5.0,
              energyWh: 0.18, peakDeltaW: 22,
              caption: 'Output · 1080p super-resolved (illustrative — full-quality master shown for comparison)' },
  interp:   { label: 'Frame interpolation · specialised model', durationS: 7.0,
              energyWh: 0.45, peakDeltaW: 34,
              caption: 'Output · 50 fps interpolated (illustrative — full-quality master shown for comparison)' }
};
var FAKE_BASELINE_W = 53.5;
var STAGES = ['Baseline (illustrative)', 'Inference running', 'Cooldown', 'Complete'];

var fakeTimer = null;
var fakeStart = null;

function startEnhance(key) {
  if (fakeTimer) { clearInterval(fakeTimer); fakeTimer = null; }
  var cfg = ENHANCE_OPTIONS[key];
  if (!cfg) return;
  fakeStart = Date.now();
  document.getElementById('result-card').style.display = 'none';
  document.getElementById('after-viewer').style.display = 'none';
  document.querySelectorAll('.enhance-chip').forEach(function(b){ b.classList.add('disabled'); });
  var totalMs = cfg.durationS * 1000;

  function tick() {
    var elapsed = Date.now() - fakeStart;
    var pct = Math.min(100, (elapsed / totalMs) * 100);
    var stageIdx = pct < 22 ? 0 : pct < 88 ? 1 : pct < 100 ? 2 : 3;
    // Synthesised watts: baseline + a sin-shaped peak during inference.
    var w = FAKE_BASELINE_W + (Math.random() - 0.5) * 0.6;
    if (pct >= 22 && pct < 88) {
      var phase = (pct - 22) / 66;
      w += cfg.peakDeltaW * Math.sin(phase * Math.PI);
    }
    if (window.wlRenderProgress) {
      wlRenderProgress({
        target:      'enhance-status',
        header:      'Running placeholder · illustrative measurement (no real workload)',
        stagesHtml:  (window.wlStageList ? wlStageList(STAGES, stageIdx) : ''),
        watts:       w,
        elapsed:     elapsed,
        progressPct: pct
      });
    }
    if (elapsed >= totalMs) {
      clearInterval(fakeTimer); fakeTimer = null;
      showResult(key);
    }
  }
  tick();
  fakeTimer = setInterval(tick, 250);
}

function showResult(key) {
  var cfg = ENHANCE_OPTIONS[key];
  var wh   = cfg.energyWh;
  var durS = cfg.durationS;
  // Average ΔW over a sin-shaped peak across the inference phase ≈ 2/π × peak ≈ 0.64;
  // we round to ×0.55 for the placeholder.
  var dwAvg = cfg.peakDeltaW * 0.55;

  document.getElementById('enhance-status').innerHTML = '';
  document.querySelectorAll('.enhance-chip').forEach(function(b){ b.classList.remove('disabled'); });

  var stripHtml = (window.wlCarbonStrip)
    ? wlCarbonStrip(wh, cfg.label + ' · illustrative', durS, null)
    : '';

  var card = document.getElementById('result-card');
  card.innerHTML = ''
    + '<div class="rc-header">Result &middot; ' + cfg.label
    + ' <span class="illustrative-tag">&middot; illustrative values, not measured</span></div>'
    + '<div class="rc-kpi">'
    +   '<div><span class="val">' + durS.toFixed(1) + ' s</span>'
    +       '<span class="lbl">Duration · illustrative</span></div>'
    +   '<div><span class="val">' + dwAvg.toFixed(1) + ' W</span>'
    +       '<span class="lbl">&Delta;W mean · illustrative</span></div>'
    +   '<div><span class="val">' + wh.toFixed(3) + ' Wh</span>'
    +       '<span class="lbl">&Delta;E · illustrative</span></div>'
    + '</div>'
    + '<div class="rc-note">'
    + 'Position-paper envelope for small specialised CNNs in this size class. A real measurement, '
    + 'when the workload runs locally, would land somewhere in this range and carry a 🟢/🟡/🔴 '
    + 'confidence flag derived from the measured noise floor.'
    + '</div>'
    + stripHtml;
  card.style.display = 'block';

  var afterV = document.getElementById('after-viewer');
  afterV.style.display = 'block';
  var capEl = document.getElementById('after-caption');
  if (capEl) capEl.textContent = cfg.caption;

  setTimeout(function(){
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, 80);
}
</script>
</body>
</html>"""


@app.get("/video-enhance", response_class=HTMLResponse,
         dependencies=[Depends(requires(PUBLIC_PAGE))])
async def video_enhance_page(request: Request):
    return (_VIDEO_ENHANCE_HTML
            .replace("{AUTH_CHIP_STYLES}", _AUTH_CHIP_STYLES)
            .replace("{AUTH_CHIP}",        _auth_chip_html(request))
            .replace("{PROGRESS_JS}",      _PROGRESS_JS)
            .replace("{FOOTER}",           _FOOTER))


# ── Hidden Lab-only "partner GPU transcode/upscale" measurement (Pixop) ──────
# Reachable by URL only — NOT in the nav grid — until Pixop green-lights a public
# launch. Vendor-neutral copy (never prints "Pixop"/"NVEncC"). The real measured
# run wraps the pixop/live docker image in OWL's harness (pixop.py); it lights up
# once a preset .args + an input clip are staged in the OWL workdir. A no-license
# `--check-device` self-test proves the docker+GPU plumbing today.

def _enhance_options_html(items: list) -> str:
    return "".join(f'<option value="{html_lib.escape(x)}">{html_lib.escape(x)}</option>'
                   for x in items)


def _enhance_preset_options_html(presets: list) -> str:
    """Preset <option>s with a plain-language description (derived from the
    actual preset flags) in brackets after the filename."""
    out = []
    for p in presets:
        desc = pixop.describe_preset(p)
        label = f"{p}  ({desc})" if desc else p
        out.append(f'<option value="{html_lib.escape(p)}">{html_lib.escape(label)}</option>')
    return "".join(out)


_ENHANCE_RUN_HTML = """<!DOCTYPE html>
<html>
<head>
  <link rel="icon" type="image/svg+xml" href="/static/owl.svg">
  <title>UNDER DEVELOPMENT — Video enhancement (GoS only)</title>
  <style>
    {AUTH_CHIP_STYLES}
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: monospace; background: var(--bg); color: var(--text);
           max-width: 820px; margin: 0 auto; padding: 2rem 1rem; }
    h1 { color: var(--accent); margin-bottom: 0.25rem; font-size: 1.45rem; }
    .subtitle { color: var(--text-3); font-size: 0.82rem; margin-bottom: 1.25rem;
                letter-spacing: 0.04em; }
    .back { display: inline-block; color: var(--text-4); text-decoration: none;
            font-size: 0.82rem; margin-bottom: 1.0rem; }
    .back:hover { color: var(--accent); }
    .lead-band { background: rgba(0,255,153,0.05); border-left: 3px solid var(--accent);
                 padding: 0.8rem 1rem; margin-bottom: 1.25rem; color: var(--text-2);
                 font-size: 0.84rem; line-height: 1.6; }
    .cfg-band { padding: 0.7rem 1rem; margin-bottom: 1.25rem; font-size: 0.8rem;
                line-height: 1.55; border-left: 3px solid var(--warn);
                background: rgba(255,170,0,0.05); color: var(--text-2); }
    .cfg-band.ok { border-left-color: var(--accent); background: rgba(0,255,153,0.04); }
    .cfg-band ul { margin: 0.35rem 0 0 1.1rem; }
    .cfg-band code { color: var(--text-3); }
    .panel { border: 1px solid var(--border-2); padding: 1rem 1.15rem;
             margin-bottom: 1.25rem; background: var(--panel); }
    .panel.lock-block { opacity: 0.5; }
    .row { display: flex; gap: 0.8rem; flex-wrap: wrap; align-items: flex-end;
           margin-bottom: 0.75rem; }
    .row > div { display: flex; flex-direction: column; gap: 0.25rem; }
    label { color: var(--text-4); font-size: 0.68rem; letter-spacing: 0.05em;
            text-transform: uppercase; }
    select { background: var(--bg); color: var(--text); border: 1px solid var(--border-3);
             font-family: monospace; padding: 0.45rem 0.5rem; min-width: 230px; }
    button { background: var(--accent); color: #061a10; border: none; font-family: monospace;
             font-weight: bold; padding: 0.55rem 1.1rem; cursor: pointer; font-size: 0.85rem; }
    button.secondary { background: transparent; color: var(--text-2);
                       border: 1px solid var(--border-3); font-weight: normal; }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    .lock-badge { display: inline-block; color: var(--warn); text-decoration: none;
                  font-size: 0.78rem; margin-left: 0.5rem; }
    #status { margin-bottom: 1.25rem; }
    pre { white-space: pre-wrap; word-break: break-word; background: var(--bg);
          border: 1px solid var(--border-2); padding: 0.75rem; font-size: 0.74rem;
          color: var(--text-3); max-height: 320px; overflow: auto; }
    .result-card { display: none; border: 1px solid var(--accent); padding: 1rem 1.15rem;
                   margin-bottom: 1.25rem; background: rgba(0,255,153,0.025); }
    .rc-header { color: var(--accent); font-size: 0.7rem; letter-spacing: 0.08em;
                 text-transform: uppercase; margin-bottom: 0.6rem; }
    .rc-kpi { display: flex; gap: 1.6rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
    .rc-kpi > div { display: flex; flex-direction: column; gap: 0.18rem; }
    .rc-kpi .val { color: var(--accent); font-size: 1.2rem; }
    .rc-kpi .lbl { color: var(--text-4); font-size: 0.66rem; letter-spacing: 0.05em;
                   text-transform: uppercase; }
    .metric { display: flex; justify-content: space-between; gap: 1rem;
              padding: 0.25rem 0; border-bottom: 1px solid var(--border); font-size: 0.8rem; }
    .metric .val { color: var(--text-2); }
    details { margin-top: 0.75rem; font-size: 0.78rem; color: var(--text-4); }
    .footer-note { color: var(--text-4); font-size: 0.78rem; line-height: 1.6;
                   border-left: 2px solid var(--border-2); padding-left: 0.9rem;
                   margin-top: 2.5rem; }
  </style>
</head>
<body>
{AUTH_CHIP}
<a href="/" class="back">&larr; Home</a>

<h1><span style="color:var(--warn)">UNDER DEVELOPMENT</span> Video enhancement <span style="color:var(--warn)">GoS ONLY</span> <span style="font-size:0.7rem;color:var(--warn)">&middot; Lab</span></h1>
<div class="subtitle">Hidden &middot; partner GPU transcode / upscale &middot; energy measurement</div>

<div class="lead-band">
  Measures the <strong>energy cost</strong> of a partner GPU transcode/upscale pass
  (e.g. SD&nbsp;&rarr;&nbsp;HD with ×2 super-resolution + HDR passthrough) on the
  GoS1 RTX&nbsp;5080. The transcode runs in a vendor container; OWL wraps it in the
  standard harness &mdash; focus mode, P110 polling at 1&nbsp;Hz, ΔWh with a
  confidence flag. Device layer only; network / CDN / CPE excluded.
</div>

{CFG_BAND}

<div class="panel {LOCK_CLASS}">
  <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.75rem">
    <span style="color:var(--text-3);font-size:0.82rem">Run a measured enhancement</span>
    {LOCK_BADGE}
  </div>
  <div class="row">
    <div>
      <label for="inSel">Input clip</label>
      <select id="inSel" onchange="updateInputPreview()"{DISABLED}>{INPUT_OPTIONS}</select>
    </div>
    <div>
      <label for="preSel">Preset (.args)</label>
      <select id="preSel" onchange="updateCompareGate()"{DISABLED}>{PRESET_OPTIONS}</select>
    </div>
    <div>
      <button id="runBtn" onclick="startRun()"{RUN_DISABLED}>Run &amp; measure</button>
    </div>
  </div>
  <label style="display:flex;align-items:center;gap:0.45rem;color:var(--text-2);font-size:0.8rem;margin-bottom:0.5rem;cursor:pointer">
    <input type="checkbox" id="liveTog"{RUN_DISABLED}> Serve as Live — pace input at 1× realtime
  </label>
  <div style="color:var(--text-4);font-size:0.72rem;margin-bottom:0.75rem">
    Feeds the encoder at 1× (the linear/live profile) so ΔW reads as sustained per-channel
    power. Best on Live-capable presets (the FHD ones); the ×2→4K SR can't sustain 1× on
    one GPU and will report "fell behind."
  </div>
  <div style="border-top:1px solid var(--border-2);margin:0.25rem 0 0.75rem"></div>
  <div class="row">
    <div>
      <label for="ffSel">Traditional filter (ffmpeg)</label>
      <select id="ffSel"{DISABLED}>
        <option value="lanczos">lanczos (detail-preserving)</option>
        <option value="bicubic">bicubic</option>
      </select>
    </div>
    <div>
      <button class="secondary" id="cmpBtn" onclick="startCompare()"{RUN_DISABLED}>Compare vs traditional (ffmpeg)</button>
    </div>
  </div>
  <div id="cmp-note" style="color:var(--text-4);font-size:0.72rem;margin-bottom:0.75rem">
    Runs the selected preset's AI upscale <em>and</em> a plain ffmpeg scale at the same
    resolution &amp; bitrate, back-to-back, then compares energy &amp; file size side by side
    with three viewers (source / AI / traditional). <strong>Always paced at Live&nbsp;1×</strong>
    so ΔW is measured over the full clip (a batch ffmpeg pass is too short for a reliable
    confidence flag). A final Analyse pass adds an AI↔ffmpeg PSNR/SSIM difference and SI/TI
    complexity (source vs both outputs). Absolute quality is yours to judge &mdash; no
    ground-truth reference.<span id="cmp-gate" style="color:var(--warn)"></span>
  </div>
  <div id="input-preview" style="display:none;margin-bottom:0.75rem">
    <div style="color:var(--text-4);font-size:0.68rem;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:0.3rem">Input preview</div>
    <video id="inVid" controls preload="metadata" muted style="width:100%;max-height:320px;background:#000"></video>
  </div>
  <button class="secondary" id="stBtn" onclick="selfTest()"{ST_DISABLED}>Run self-test (--check-device)</button>
  <div style="color:var(--text-4);font-size:0.72rem;margin-top:0.5rem">
    Self-test proves docker + GPU + image plumbing without measuring energy.
  </div>
</div>

<div id="status"></div>
<div id="result-card" class="result-card"></div>
<div id="selftest-out"></div>

<div class="footer-note">
  A partner GPU transcode is measured with the same protocol as every other OWL
  workload &mdash; see <a href="/methodology">/methodology</a>. Energy is the
  headline; perceptual quality of super-resolution has no native ground-truth
  reference, so it is not asserted here.
</div>

{PROGRESS_JS}
{FOOTER}

<script>
function _enhStageIdx(stage) {
  var m = {baseline:0, transcoding:1, cooldown:2, probe:3, done:4};
  return m[stage] != null ? m[stage] : 0;
}
function updateInputPreview() {
  var sel = document.getElementById('inSel');
  var wrap = document.getElementById('input-preview');
  var vid = document.getElementById('inVid');
  if (!sel || !sel.value) { wrap.style.display = 'none'; return; }
  vid.src = '/enhance-run/input/' + encodeURIComponent(sel.value);
  wrap.style.display = 'block';
}
async function startRun() {
  var input = document.getElementById('inSel').value;
  var preset = document.getElementById('preSel').value;
  if (!input || !preset) return;
  document.getElementById('runBtn').disabled = true;
  document.getElementById('result-card').style.display = 'none';
  document.getElementById('selftest-out').innerHTML = '';
  // Measurement hygiene: pause any in-page video so the browser doesn't keep
  // GoS1 serving bytes (disk/network/CPU) during the baseline + run window.
  // (Decode is client-side, but the FileResponse fetch is not.)
  document.querySelectorAll('video').forEach(function(v){ try { v.pause(); } catch(e) {} });
  var form = new FormData();
  form.append('input_name', input);
  form.append('preset_name', preset);
  form.append('live', document.getElementById('liveTog').checked ? 'true' : 'false');
  try {
    var resp = await fetch('/enhance-run/start', { method:'POST', body:form });
    var data = await resp.json();
    if (!resp.ok) {
      document.getElementById('status').innerHTML =
        '<div style="color:var(--err)">' + (data.error || 'Failed')
        + (data.reasons ? ' — ' + data.reasons.join('; ') : '') + '</div>';
      document.getElementById('runBtn').disabled = false;
      return;
    }
    pollJob(data.job_id);
  } catch(e) {
    document.getElementById('status').innerHTML = '<div style="color:var(--err)">' + e + '</div>';
    document.getElementById('runBtn').disabled = false;
  }
}
async function pollJob(jobId) {
  try {
    var [resp, powerR] = await Promise.all([
      fetch('/enhance-run/job/' + jobId),
      fetch('/power').catch(function(){ return null; }),
    ]);
    var data = await resp.json();
    var watts = powerR ? ((await powerR.json().catch(function(){return {};})).watts ?? null) : null;
    if (data.status === 'done') {
      document.getElementById('status').innerHTML = '';
      renderResult(data.result);
      document.getElementById('runBtn').disabled = false;
    } else if (data.status === 'error') {
      document.getElementById('status').innerHTML =
        '<div style="color:var(--err)">Error: ' + data.error + '</div>';
      document.getElementById('runBtn').disabled = false;
    } else if (data.stage === 'queued') {
      wlRenderQueued(data.queue_position);
      setTimeout(function(){ pollJob(jobId); }, 3000);
    } else {
      var idx = _enhStageIdx(data.stage || 'baseline');
      wlRenderProgress({
        header: 'Measuring — do not close this tab',
        stagesHtml: wlStageList(WL_ENHANCE_STAGES, idx),
        watts: watts,
      });
      var inCooldown = (data.stage || '').indexOf('cooldown') !== -1 && data.cooldown_waited_s != null;
      setTimeout(function(){ pollJob(jobId); }, inCooldown ? 1000 : 2000);
    }
  } catch(e) {
    setTimeout(function(){ pollJob(jobId); }, 5000);
  }
}
function _row(label, val, unit) {
  return '<div class="metric"><span>' + label + '</span><span class="val">'
       + val + (unit ? ' ' + unit : '') + '</span></div>';
}
function renderResult(meas) {
  var r = meas.result || {};
  var e = r.energy || {};
  var t = r.transcode || {};
  var s = r.stream || {};
  var conf = e.confidence || {};
  var card = document.getElementById('result-card');
  var streamRows = '';
  if (s && s.codec) {
    streamRows += _row('Output', (s.width||'?') + '×' + (s.height||'?') + ' · ' + s.codec
                  + (s.pix_fmt ? ' · ' + s.pix_fmt : ''), '');
    if (s.bit_rate_bps) streamRows += _row('Output bitrate', (s.bit_rate_bps/1e6).toFixed(1), 'Mbps');
  }
  if (r.output_size_mb != null) streamRows += _row('Output size', r.output_size_mb, 'MB');
  var failHtml = t.success === false
    ? '<div style="color:var(--err);font-size:0.8rem;margin:0.4rem 0">Transcode failed (rc '
      + t.returncode + ') — ' + (t.stderr_tail || '').slice(-300) + '</div>'
    : '';
  // Output viewer — only when the run produced a file (success + name on disk).
  var outHtml = '';
  if (r.output_name && t.success !== false) {
    var url = '/enhance-run/output/' + encodeURIComponent(r.output_name);
    outHtml =
        '<div style="margin-top:0.85rem">'
      + '<div style="display:flex;gap:0.8rem;align-items:center;margin-bottom:0.4rem">'
      +   '<a href="' + url + '" download style="color:var(--accent)">⬇ Download output</a>'
      +   '<span style="color:var(--text-4);font-size:0.72rem">' + r.output_name + '</span>'
      + '</div>'
      + '<video controls preload="metadata" style="width:100%;background:#000" src="' + url + '"></video>'
      + '<div style="color:var(--text-4);font-size:0.7rem;margin-top:0.3rem">'
      +   'HEVC 10-bit / HDR may not play inline in every browser — use Download if the player is blank.'
      + '</div></div>';
  }
  // Realtime / Live feasibility verdict.
  var rt = r.realtime;
  var rtHtml = '';
  if (rt && rt.verdict && rt.verdict !== 'unknown') {
    if (rt.live) {
      // 1x-paced run: did the box sustain realtime (no back-pressure)?
      var lmap = {
        live_sustained: ['▶ Live 1× — sustained realtime', 'var(--accent)'],
        live_behind:    ['■ Live 1× — fell behind (can\\'t sustain on this GPU)', 'var(--warn)']
      };
      var lv = lmap[rt.verdict] || ['', 'var(--text-3)'];
      rtHtml = '<div style="font-size:0.88rem;color:' + lv[1] + ';margin-bottom:0.2rem">' + lv[0] + '</div>'
             + '<div style="color:var(--text-4);font-size:0.7rem;margin-bottom:0.7rem">'
             + 'paced at 1× · ΔW below = live average power, linear content'
             + (rt.rtf_wall != null ? ' · ran ' + rt.rtf_wall + '× content time' : '') + '</div>';
    } else {
      var vmap = {
        live:     ['▶ Live-capable',                      'var(--accent)'],
        marginal: ['▷ Marginal — realtime, no headroom',  'var(--warn)'],
        file:     ['■ File / batch only',                 'var(--text-3)']
      };
      var v = vmap[rt.verdict] || ['', 'var(--text-3)'];
      var detail = (rt.rtf_steady != null ? rt.rtf_steady + '× realtime' : '')
        + (rt.encode_fps != null && rt.source_fps != null
            ? ' (' + rt.encode_fps + ' fps enc vs ' + rt.source_fps + ' fps source)' : '');
      rtHtml = '<div style="font-size:0.88rem;color:' + v[1] + ';margin-bottom:0.2rem">'
             + v[0] + (detail ? ' · ' + detail : '') + '</div>'
             + (rt.rtf_wall != null
                 ? '<div style="color:var(--text-4);font-size:0.7rem;margin-bottom:0.7rem">wall-clock '
                   + rt.rtf_wall + '× incl. cold start</div>'
                 : '<div style="margin-bottom:0.5rem"></div>');
    }
  }
  card.innerHTML =
      '<div class="rc-header">Result · ' + (r.preset_label || 'Partner GPU transcode') + '</div>'
    + failHtml
    + rtHtml
    + '<div class="rc-kpi">'
    +   '<div><span class="val">' + wlFmt(e.delta_t_s, 1) + ' s</span><span class="lbl">Duration</span></div>'
    +   '<div><span class="val">' + wlFmt(e.delta_w, 1) + ' W</span><span class="lbl">ΔW mean</span></div>'
    +   '<div><span class="val">' + wlFmt(e.delta_e_wh, 4) + ' Wh</span><span class="lbl">ΔE</span></div>'
    +   '<div><span class="val">' + (conf.flag || '') + ' ' + (conf.label || '') + '</span><span class="lbl">Confidence</span></div>'
    + '</div>'
    + (streamRows ? '<div style="margin-top:0.5rem">' + streamRows + '</div>' : '')
    + outHtml
    + (window.wlCarbonStrip ? wlCarbonStrip(e.delta_e_wh,
          (r.preset_label || 'Partner GPU transcode'), e.delta_t_s,
          (e.co2e && e.co2e.intensity ? e.co2e.intensity.g_per_kwh : null)) : '')
    + '<details><summary>preset · ' + (r.preset_detail || '') + '</summary>'
    +   '<pre>' + (t.docker_cmd || '') + '</pre></details>';
  card.style.display = 'block';
}
async function selfTest() {
  var btn = document.getElementById('stBtn');
  btn.disabled = true;
  document.getElementById('selftest-out').innerHTML =
    '<div style="color:var(--warn);font-size:0.82rem;margin-bottom:0.5rem">Running --check-device…</div>';
  try {
    var resp = await fetch('/enhance-run/self-test', { method:'POST' });
    var d = await resp.json();
    var head = d.ok ? '<span style="color:var(--accent)">✓ plumbing OK</span>'
                    : '<span style="color:var(--err)">✗ ' + (d.error || ('rc ' + d.returncode)) + '</span>';
    document.getElementById('selftest-out').innerHTML =
      '<div style="font-size:0.82rem;margin-bottom:0.4rem">' + head
      + ' <span style="color:var(--text-4)">· ' + (d.duration_s ?? '?') + 's · ' + (d.image_tag||'') + '</span></div>'
      + '<pre>' + ((d.stdout_tail || '') + '\\n' + (d.stderr_tail || '')).trim() + '</pre>';
  } catch(e) {
    document.getElementById('selftest-out').innerHTML = '<div style="color:var(--err)">' + e + '</div>';
  } finally {
    btn.disabled = false;
  }
}
// ── Compare: AI/ML upscale vs traditional ffmpeg upscale ──────────────────
var PRESET_COMPARABLE = {PRESET_COMPARABLE_JSON};
var RUN_ENABLED = {RUN_ENABLED_JS};
// WL_CMP_STAGES is baked into _PROGRESS_JS (toggle-aware idle label). Map the
// coarse stage + fine substage onto its 5 positions. Only the FIRST pass cools
// down (to separate it from the ffmpeg pass); the ffmpeg pass has no trailing
// cooldown — nothing is measured after it — so there's no second idle step.
//   0 AI/ML enhance · 1 idle · 2 Traditional (ffmpeg) · 3 Analyse · 4 Done
function _cmpStageIdx(stage, substage) {
  if (stage === 'done') return 4;
  if (stage === 'analyse') return 3;
  if (stage === 'ffmpeg') return 2;
  return substage === 'cooldown' ? 1 : 0;   // 'ml' / starting
}
function updateCompareGate() {
  var pre = document.getElementById('preSel');
  var btn = document.getElementById('cmpBtn');
  var gate = document.getElementById('cmp-gate');
  if (!pre || !btn) return;
  var ok = PRESET_COMPARABLE[pre.value] !== false;
  btn.disabled = !(RUN_ENABLED && ok);
  gate.textContent = (RUN_ENABLED && !ok)
    ? ' · This preset does SDR→HDR — no apples-to-apples ffmpeg baseline, so compare is disabled for it.'
    : '';
}
async function startCompare() {
  var input = document.getElementById('inSel').value;
  var preset = document.getElementById('preSel').value;
  var ff = document.getElementById('ffSel').value;
  if (!input || !preset) return;
  document.getElementById('cmpBtn').disabled = true;
  document.getElementById('runBtn').disabled = true;
  document.getElementById('result-card').style.display = 'none';
  document.getElementById('selftest-out').innerHTML = '';
  document.querySelectorAll('video').forEach(function(v){ try { v.pause(); } catch(e) {} });
  var form = new FormData();
  form.append('input_name', input);
  form.append('preset_name', preset);
  form.append('live', 'true');   // compare always paces at 1× — see below
  form.append('ff_filter', ff);
  try {
    var resp = await fetch('/enhance-run/start-compare', { method:'POST', body:form });
    var data = await resp.json();
    if (!resp.ok) {
      document.getElementById('status').innerHTML =
        '<div style="color:var(--err)">' + (data.error || 'Failed')
        + (data.reasons ? ' — ' + data.reasons.join('; ') : '') + '</div>';
      document.getElementById('runBtn').disabled = false;
      updateCompareGate();
      return;
    }
    pollCompare(data.job_id);
  } catch(e) {
    document.getElementById('status').innerHTML = '<div style="color:var(--err)">' + e + '</div>';
    document.getElementById('runBtn').disabled = false;
    updateCompareGate();
  }
}
async function pollCompare(jobId) {
  try {
    var [resp, powerR] = await Promise.all([
      fetch('/enhance-run/job/' + jobId),
      fetch('/power').catch(function(){ return null; }),
    ]);
    var data = await resp.json();
    var watts = powerR ? ((await powerR.json().catch(function(){return {};})).watts ?? null) : null;
    if (data.status === 'done') {
      document.getElementById('status').innerHTML = '';
      renderCompare(data.result);
      document.getElementById('runBtn').disabled = false;
      updateCompareGate();
    } else if (data.status === 'error') {
      document.getElementById('status').innerHTML =
        '<div style="color:var(--err)">Error: ' + data.error + '</div>';
      document.getElementById('runBtn').disabled = false;
      updateCompareGate();
    } else if (data.stage === 'queued') {
      wlRenderQueued(data.queue_position);
      setTimeout(function(){ pollCompare(jobId); }, 3000);
    } else {
      var idx = _cmpStageIdx(data.stage || 'ml', data.substage || '');
      wlRenderProgress({
        header: 'Comparing — do not close this tab',
        stagesHtml: wlStageList(WL_CMP_STAGES, idx),
        watts: watts,
        extraHtml: wlCooldownLine(data),
      });
      var inCooldown = (data.substage || '') === 'cooldown' && data.cooldown_waited_s != null;
      setTimeout(function(){ pollCompare(jobId); }, inCooldown ? 1000 : 2000);
    }
  } catch(e) {
    setTimeout(function(){ pollCompare(jobId); }, 5000);
  }
}
function _midTrunc(s) {
  s = s || '';
  return s.length > 19 ? s.slice(0, 8) + '...' + s.slice(-8) : s;
}
function _vidCell(title, src, name) {
  var short = _midTrunc(name);
  var media = src
    ? '<video controls preload="metadata" muted style="width:100%;background:#000" src="' + src + '"></video>'
      + '<div style="margin-top:0.25rem"><a href="' + src + '" download title="' + (name || '') + '" style="color:var(--accent);font-size:0.72rem">⬇ ' + (short || 'download') + '</a></div>'
    : '<div style="width:100%;aspect-ratio:16/9;background:#000;display:flex;align-items:center;justify-content:center;color:var(--text-4);font-size:0.72rem">no output</div>'
      + (name ? '<div title="' + name + '" style="color:var(--text-4);font-size:0.7rem;margin-top:0.25rem">' + short + '</div>' : '');
  return '<div style="flex:1;min-width:220px">'
    + '<div style="color:var(--text-4);font-size:0.68rem;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:0.3rem">' + title + '</div>'
    + media + '</div>';
}
// Resulting-file complexity comparison (SI/TI + frame-size stats from the
// terminal probe), source vs both outputs. Renders only rows with ≥1 value.
function _cxTable(srccx, mlcx, ffcx) {
  if (!srccx && !mlcx && !ffcx) return '';
  var rows = [
    ['Spatial info (SI) mean', 'si_mean', ''],
    ['SI max', 'si_max', ''],
    ['Temporal info (TI) mean', 'ti_mean', ''],
    ['TI max', 'ti_max', ''],
    ['Mean frame size', 'mean_kb', ' KB'],
    ['Max frame size', 'max_kb', ' KB'],
    ['I-frame mean', 'i_mean_kb', ' KB'],
    ['P-frame mean', 'p_mean_kb', ' KB'],
    ['B-frame mean', 'b_mean_kb', ' KB'],
    ['Keyframes', 'keyframes', ''],
  ];
  function cell(cx, key, unit) {
    var v = cx ? cx[key] : null;
    return '<td style="text-align:right;color:var(--text-2)">' + (v == null ? '—' : (v + (unit || ''))) + '</td>';
  }
  var body = rows.map(function(r) {
    var any = [srccx, mlcx, ffcx].some(function(cx){ return cx && cx[r[1]] != null; });
    if (!any) return '';
    return '<tr><td style="padding:0.2rem 0;color:var(--text-3)">' + r[0] + '</td>'
         + cell(srccx, r[1], r[2]) + cell(mlcx, r[1], r[2]) + cell(ffcx, r[1], r[2]) + '</tr>';
  }).join('');
  if (!body) return '';
  function th(t){ return '<th style="text-align:right;color:var(--text-4);font-weight:normal;font-size:0.66rem">' + t + '</th>'; }
  return '<div style="color:var(--text-4);font-size:0.66rem;letter-spacing:0.05em;text-transform:uppercase;margin:0.8rem 0 0.3rem">'
       +   'Resulting-file complexity · terminal probe, no energy impact</div>'
       + '<table style="width:100%;border-collapse:collapse;font-size:0.78rem">'
       +   '<thead><tr><th></th>' + th('Source') + th('AI') + th('ffmpeg') + '</tr></thead>'
       +   '<tbody>' + body + '</tbody></table>'
       + '<div style="color:var(--text-4);font-size:0.7rem;margin-top:0.3rem">'
       +   'SI/TI = ITU-T P.910 spatial / temporal information; higher SI ≈ more fine detail. '
       +   'AI &gt; ffmpeg ≈ source ⇒ the AI injected detail the resize did not.</div>';
}
function renderCompare(meas) {
  var card = document.getElementById('result-card');
  var ml = meas.ml || {}, ff = meas.ffmpeg || {};
  var mlr = ml.result || {}, ffr = ff.result || {};
  var mle = mlr.energy || {}, ffe = ffr.energy || {};
  var c = meas.comparison || {};
  var inUrl = '/enhance-run/input/' + encodeURIComponent(meas.input_name);
  var mlUrl = (mlr.output_name && (mlr.transcode || {}).success !== false)
      ? '/enhance-run/output/' + encodeURIComponent(mlr.output_name) : null;
  var ffUrl = (ffr.output_name && (ffr.transcode || {}).success !== false)
      ? '/enhance-run/output/' + encodeURIComponent(ffr.output_name) : null;

  function side(lbl, e, r) {
    var conf = e.confidence || {};
    return _row(lbl + ' energy', wlFmt(e.delta_e_wh, 4) + ' Wh · ' + wlFmt(e.delta_w, 1)
              + ' W · ' + wlFmt(e.delta_t_s, 1) + ' s', '')
         + _row(lbl + ' file size', (r.output_size_mb != null ? r.output_size_mb + ' MB' : '—'), '')
         + _row(lbl + ' quality', (c.quality || 'TBD'), '')
         + _row(lbl + ' confidence', (conf.flag || '') + ' ' + (conf.label || ''), '');
  }

  var ratioRow = (c.energy_ratio != null)
    ? '<div class="rc-kpi"><div><span class="val">' + c.energy_ratio + '×</span><span class="lbl">AI energy ÷ ffmpeg</span></div>'
      + (c.size_ratio != null ? '<div><span class="val">' + c.size_ratio + '×</span><span class="lbl">AI size ÷ ffmpeg</span></div>' : '')
      + '<div><span class="val">' + (c.quality || 'TBD') + '</span><span class="lbl">Quality metric</span></div></div>'
    : '';

  var fail = '';
  if ((mlr.transcode || {}).success === false)
    fail += '<div style="color:var(--err);font-size:0.78rem">AI pass failed (rc ' + mlr.transcode.returncode + ')</div>';
  if ((ffr.transcode || {}).success === false)
    fail += '<div style="color:var(--err);font-size:0.78rem">ffmpeg pass failed (rc ' + ffr.transcode.returncode + ')</div>';

  card.innerHTML =
      '<div class="rc-header">Compare · AI vs traditional upscale' + (meas.live ? ' · Live 1×' : '')
        + (meas.target_res ? ' · ' + meas.target_res : '') + '</div>'
    + fail
    + ratioRow
    + '<div style="display:flex;gap:0.8rem;flex-wrap:wrap;margin:0.6rem 0 0.4rem">'
    +   _vidCell('Source', inUrl, meas.input_name)
    +   _vidCell('AI / ML upscale', mlUrl, mlr.output_name || '')
    +   _vidCell('ffmpeg ' + (meas.ff_filter || ''), ffUrl, ffr.output_name || '')
    + '</div>'
    + '<div style="color:var(--text-4);font-size:0.7rem;margin-bottom:0.6rem">HEVC 10-bit / HDR may not play inline — use the ⬇ links if a player is blank.</div>'
    + '<div>' + side('AI', mle, mlr) + side('ffmpeg', ffe, ffr) + '</div>'
    + (function(){
        var ab = c.ab_quality;
        if (!ab) return '';
        var psnr = ab.identical ? '∞ (identical)' : (ab.psnr_db != null ? ab.psnr_db + ' dB' : '—');
        return '<div style="margin-top:0.5rem">'
             + _row('AI ↔ ffmpeg PSNR', psnr, '')
             + _row('AI ↔ ffmpeg SSIM', (ab.ssim != null ? ab.ssim : '—'), '')
             + '</div>'
             + '<div style="color:var(--text-4);font-size:0.7rem;margin-top:0.2rem">'
             + 'Difference between the two outputs (same resolution) — higher = more alike; not a quality ranking.</div>';
      })()
    + _cxTable(meas.source_complexity, mlr.complexity, ffr.complexity)
    + '<div style="color:var(--text-4);font-size:0.74rem;margin-top:0.6rem;border-left:2px solid var(--border-2);padding-left:0.7rem">'
    +   (c.quality_note || '') + '</div>'
    + '<details><summary>commands</summary><pre>'
    +   'AI:     ' + ((mlr.transcode || {}).docker_cmd || '') + '\\n\\n'
    +   'ffmpeg: ' + ((ffr.transcode || {}).docker_cmd || '') + '</pre></details>';
  card.style.display = 'block';
}
// Show the input preview for the initially-selected clip (Lab + configured).
updateInputPreview();
updateCompareGate();
</script>
</body>
</html>"""


def _enhance_cfg_band(pf: dict) -> str:
    if pf["ok_transcode"]:
        return ('<div class="cfg-band ok">&#10003; Configured &middot; '
                f'{len(pf["inputs"])} input(s), {len(pf["presets"])} preset(s) staged &middot; '
                f'image <code>{html_lib.escape(pf["image_tag"])}</code> present.</div>')
    items = "".join(f"<li>{html_lib.escape(r)}</li>" for r in pf["reasons"])
    selftest = ("Self-test is available." if pf["ok_selftest"]
                else "Self-test needs the docker image.")
    return ('<div class="cfg-band">&#9888; Not yet runnable &mdash; staging incomplete. '
            f'Run is disabled until resolved:<ul>{items}</ul>{selftest}</div>')


@app.get("/enhance-run", response_class=HTMLResponse,
         dependencies=[Depends(requires(ENHANCE_RUN))])
async def enhance_run_page(request: Request):
    pf = pixop.preflight()
    can_run = can(audience.tier(request), ENHANCE_RUN)
    run_enabled = can_run and pf["ok_transcode"]
    st_enabled = can_run and pf["ok_selftest"]
    comparable = {p: pixop.ffmpeg_comparable(p) for p in pf["presets"]}
    return (_ENHANCE_RUN_HTML
            .replace("{AUTH_CHIP_STYLES}", _AUTH_CHIP_STYLES)
            .replace("{AUTH_CHIP}",        _auth_chip_html(request))
            .replace("{CFG_BAND}",         _enhance_cfg_band(pf))
            .replace("{LOCK_BADGE}",       _lock_badge_html(request, ENHANCE_RUN, "Members only"))
            .replace("{LOCK_CLASS}",       _lock_class(request, ENHANCE_RUN))
            .replace("{DISABLED}",         "" if run_enabled else " disabled")
            .replace("{RUN_DISABLED}",     "" if run_enabled else " disabled")
            .replace("{ST_DISABLED}",      "" if st_enabled else " disabled")
            .replace("{INPUT_OPTIONS}",    _enhance_options_html(pf["inputs"]))
            .replace("{PRESET_OPTIONS}",   _enhance_preset_options_html(pf["presets"]))
            .replace("{PRESET_COMPARABLE_JSON}", json.dumps(comparable))
            .replace("{RUN_ENABLED_JS}",   "true" if run_enabled else "false")
            .replace("{PROGRESS_JS}",      _PROGRESS_JS)
            .replace("{FOOTER}",           _FOOTER))


@app.post("/enhance-run/self-test", dependencies=[Depends(requires(ENHANCE_RUN))])
async def enhance_self_test():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, pixop.self_test)


async def run_enhance_job(job_id: str, input_name: str, preset_name: str,
                          live: bool = False):
    try:
        jobs[job_id].update({"status": "running", "stage": "starting"})
        result = await pixop.run_enhance_measurement(input_name, preset_name, job_id,
                                                     jobs, live=live)
        save_result("enhance", job_id, result)
        jobs[job_id].update({"status": "done", "stage": "done", "result": result})
    except Exception as e:
        jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}


@app.post("/enhance-run/start", dependencies=[Depends(requires(ENHANCE_RUN))])
async def enhance_run_start(request: Request,
                            input_name: str = Form(...),
                            preset_name: str = Form(...),
                            live: str = Form("false")):
    pf = pixop.preflight()
    if not pf["ok_transcode"]:
        return JSONResponse({"error": "Partner transcode not configured",
                             "reasons": pf["reasons"]}, status_code=409)
    if input_name not in pf["inputs"] or preset_name not in pf["presets"]:
        return JSONResponse({"error": "Unknown input or preset"}, status_code=400)
    is_live = str(live).lower() in ("true", "1", "on", "yes")
    job_id = str(uuid.uuid4())[:8]
    label = f"Enhance — {preset_name}" + (" · Live 1×" if is_live else "")

    async def coro():
        await run_enhance_job(job_id, input_name, preset_name, live=is_live)

    position = queue_control.enqueue(job_id, "enhance", label, coro,
                                     request=request, page="/enhance-run")
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


async def run_enhance_compare_job(job_id: str, input_name: str, preset_name: str,
                                  live: bool = False, ff_filter: str = "lanczos"):
    try:
        jobs[job_id].update({"status": "running", "stage": "starting"})
        result = await pixop.run_enhance_compare_measurement(
            input_name, preset_name, job_id, jobs, live=live, ff_filter=ff_filter)
        save_result("enhance", job_id, result)
        jobs[job_id].update({"status": "done", "stage": "done", "result": result})
    except Exception as e:
        jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}


@app.post("/enhance-run/start-compare", dependencies=[Depends(requires(ENHANCE_RUN))])
async def enhance_run_start_compare(request: Request,
                                    input_name: str = Form(...),
                                    preset_name: str = Form(...),
                                    live: str = Form("false"),
                                    ff_filter: str = Form("lanczos")):
    pf = pixop.preflight()
    if not pf["ok_transcode"]:
        return JSONResponse({"error": "Partner transcode not configured",
                             "reasons": pf["reasons"]}, status_code=409)
    if input_name not in pf["inputs"] or preset_name not in pf["presets"]:
        return JSONResponse({"error": "Unknown input or preset"}, status_code=400)
    if not pixop.ffmpeg_comparable(preset_name):
        return JSONResponse({"error": "This preset does an SDR→HDR conversion — "
                             "no apples-to-apples ffmpeg baseline"}, status_code=400)
    ff = ff_filter if ff_filter in ("lanczos", "bicubic") else "lanczos"
    is_live = str(live).lower() in ("true", "1", "on", "yes")
    job_id = str(uuid.uuid4())[:8]
    label = (f"Enhance compare — {preset_name} vs ffmpeg {ff}"
             + (" · Live 1×" if is_live else ""))

    async def coro():
        await run_enhance_compare_job(job_id, input_name, preset_name,
                                      live=is_live, ff_filter=ff)

    position = queue_control.enqueue(job_id, "enhance", label, coro,
                                     request=request, page="/enhance-run")
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


@app.get("/enhance-run/job/{job_id}", dependencies=[Depends(requires(ENHANCE_RUN))])
async def enhance_job_status(job_id: str):
    return _job_status(job_id)


@app.get("/enhance-run/output/{name}", dependencies=[Depends(requires(ENHANCE_RUN))])
async def enhance_output(name: str):
    """Serve a measured enhance output for download/preview. Lab-only (same cap
    as the run). Basename-only allow-list — no path traversal."""
    _, out, _ = pixop._workdir_paths(pixop.config())
    if Path(name).name != name:
        return HTMLResponse("not found", status_code=404)
    path = out / name
    if not path.exists() or not path.is_file():
        return HTMLResponse("not found", status_code=404)
    return FileResponse(path, media_type="video/mp4", filename=name)


@app.get("/enhance-run/input/{name}", dependencies=[Depends(requires(ENHANCE_RUN))])
async def enhance_input(name: str):
    """Serve a staged input clip for in-page preview. Lab-only; basename allow-list."""
    inp, _, _ = pixop._workdir_paths(pixop.config())
    if Path(name).name != name:
        return HTMLResponse("not found", status_code=404)
    path = inp / name
    if not path.exists() or not path.is_file():
        return HTMLResponse("not found", status_code=404)
    return FileResponse(path, media_type="video/mp4", filename=name)


# --- Job runner ---

async def run_job(job_id: str, input_path: Path, preset: str, delete_after: bool = True,
                  custom_cmd: str = None, custom_cmd_cpu: str = None, custom_cmd_gpu: str = None,
                  source_key: str = None):
    try:
        jobs[job_id].update({"status": "running", "stage": "starting"})
        _BOTH_PRESETS = {
            "both":      ("cpu",      "gpu"),
            "h265_both": ("h265_cpu", "h265_gpu"),
            "av1_both":  ("av1_cpu",  "av1_gpu"),
        }
        if preset == "all_codecs":
            result = await run_all_measurement(input_path, job_id, jobs)
        elif preset in ("codecs_cpu", "codecs_gpu"):
            result = await run_codecs_single_measurement(
                input_path, job_id, jobs, side=preset.split("_", 1)[1])
        elif preset in _BOTH_PRESETS:
            p_cpu, p_gpu = _BOTH_PRESETS[preset]
            result = await run_both_measurement(input_path, job_id, jobs,
                                                custom_cmd_cpu=custom_cmd_cpu,
                                                custom_cmd_gpu=custom_cmd_gpu,
                                                preset_cpu=p_cpu, preset_gpu=p_gpu)
        else:
            result = await run_video_measurement(input_path, job_id, preset, jobs,
                                                 custom_cmd=custom_cmd)
        # CR-047 follow-up — stamp the variant + parent ids on the result so
        # historical jobs stay filterable as the source schema evolves. Only
        # set when the job came from a preloaded source (not /video/upload).
        if source_key:
            entry = PRELOADED.get(source_key) or {}
            result["source"] = {"key": source_key,
                                "parent": entry.get("_parent")}
        save_result("video", job_id, result)
        jobs[job_id].update({"status": "done", "stage": "done", "result": result})
    except Exception as e:
        jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}
    finally:
        if delete_after:
            input_path.unlink(missing_ok=True)


@app.post("/video/use-source", dependencies=[Depends(requires(VIDEO_RUN))])
async def use_preloaded_source(
    request: Request,
    source_key: str = Form(...),
    preset: str = Form("both"),
    custom_cmd: str = Form(None),
    custom_cmd_cpu: str = Form(None),
    custom_cmd_gpu: str = Form(None),
):
    if preset not in ("cpu", "gpu", "both", "h265_cpu", "h265_gpu", "h265_both", "av1_cpu", "av1_gpu", "av1_both", "all_codecs", "codecs_cpu", "codecs_gpu"):
        return JSONResponse({"error": "Invalid preset"}, status_code=400)
    # CR-001 capability dispatch: all-codecs sweep is BATCH_COMPARE; any
    # custom ffmpeg arg is CUSTOM_PROMPT.
    if preset in ("all_codecs", "codecs_cpu", "codecs_gpu"):
        gate(request, BATCH_COMPARE)
    if any((custom_cmd, custom_cmd_cpu, custom_cmd_gpu)):
        gate(request, CUSTOM_PROMPT)

    source = PRELOADED.get(source_key)
    if not source or not source["path"].exists():
        return JSONResponse({"error": f"Source '{source_key}' not found"}, status_code=404)

    job_id = str(uuid.uuid4())[:8]
    label = f"Video — {preset} · {source['label']}"

    async def coro():
        await run_job(job_id, source["path"], preset, False,
                      custom_cmd=custom_cmd,
                      custom_cmd_cpu=custom_cmd_cpu,
                      custom_cmd_gpu=custom_cmd_gpu,
                      source_key=source_key)

    position = queue_control.enqueue(job_id, "video", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}

@app.post("/video/upload", dependencies=[Depends(requires(CUSTOM_UPLOAD))])
async def upload_video(
    request: Request,
    file: UploadFile = File(...),
    preset: str = Form("both"),
    custom_cmd: str = Form(None),
    custom_cmd_cpu: str = Form(None),
    custom_cmd_gpu: str = Form(None),
):
    if preset not in ("cpu", "gpu", "both", "h265_cpu", "h265_gpu", "h265_both", "av1_cpu", "av1_gpu", "av1_both", "all_codecs", "codecs_cpu", "codecs_gpu"):
        return JSONResponse({"error": "Invalid preset"}, status_code=400)
    # CR-001 capability dispatch — same shape as /video/use-source.
    if preset in ("all_codecs", "codecs_cpu", "codecs_gpu"):
        gate(request, BATCH_COMPARE)
    if any((custom_cmd, custom_cmd_cpu, custom_cmd_gpu)):
        gate(request, CUSTOM_PROMPT)

    allowed = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".ts"}
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed:
        return JSONResponse({"error": f"File type {suffix} not allowed"}, status_code=400)

    # CR-001 part D / CR-026 — upload size cap. CR-026 moved CUSTOM_UPLOAD
    # to Member tier, so Anonymous can't reach this code path; the per-tier
    # branch collapses to the Member cap. The `upload_size_anonymous_mb`
    # setting is left in place for future scope (e.g. re-enabling bounded
    # Anonymous uploads with a different policy).
    # Pre-check via Content-Length so we 413 before reading the body when
    # nginx hands us the header; fall back to length-after-read otherwise.
    s = cfg.load()
    max_mb = s["upload_size_member_mb"]
    max_bytes = max_mb * 1024 * 1024
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > max_bytes:
        return JSONResponse({"error": f"Upload too large (max {max_mb} MB for your tier)"}, status_code=413)

    contents = await file.read()
    if len(contents) > max_bytes:
        return JSONResponse({"error": f"Upload too large (max {max_mb} MB for your tier)"}, status_code=413)

    job_id = str(uuid.uuid4())[:8]
    input_path = UPLOAD_DIR / f"{job_id}_in{suffix}"
    input_path.write_bytes(contents)
    label = f"Video — {preset} · {file.filename}"

    async def coro():
        await run_job(job_id, input_path, preset, True,
                      custom_cmd=custom_cmd,
                      custom_cmd_cpu=custom_cmd_cpu,
                      custom_cmd_gpu=custom_cmd_gpu)

    position = queue_control.enqueue(job_id, "video", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


@app.get("/video/sources", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def video_sources():
    return get_all_sources()


@app.get("/video/preview-cmd", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def video_preview_cmd(preset: str = "both"):
    from video import PRESETS, build_preset_cmd
    placeholder_in = Path("{input}")
    placeholder_out = Path("{output}")
    _BOTH_MAP = {"both": ("cpu","gpu"), "h265_both": ("h265_cpu","h265_gpu"), "av1_both": ("av1_cpu","av1_gpu")}
    if preset == "all_codecs":
        pairs = [("cpu","gpu"),("h265_cpu","h265_gpu"),("av1_cpu","av1_gpu")]
        cmds = {}
        for cpu_k, gpu_k in pairs:
            cmds[cpu_k] = " ".join(build_preset_cmd(cpu_k, placeholder_in, placeholder_out))
            cmds[gpu_k] = " ".join(build_preset_cmd(gpu_k, placeholder_in, placeholder_out))
        return {"mode": "all_codecs", "cmds": cmds}
    elif preset in ("codecs_cpu", "codecs_gpu"):
        # Single-device codec sweep — 3 read-only cmds. Reuses the all_codecs
        # preview shape so fetchCmdPreview's label map renders them.
        side = preset.split("_", 1)[1]
        keys = {"cpu": ["cpu", "h265_cpu", "av1_cpu"],
                "gpu": ["gpu", "h265_gpu", "av1_gpu"]}[side]
        cmds = {k: " ".join(build_preset_cmd(k, placeholder_in, placeholder_out))
                for k in keys}
        return {"mode": "all_codecs", "cmds": cmds}
    elif preset in _BOTH_MAP:
        p_cpu, p_gpu = _BOTH_MAP[preset]
        cpu_cmd = " ".join(build_preset_cmd(p_cpu, placeholder_in, placeholder_out))
        gpu_cmd = " ".join(build_preset_cmd(p_gpu, placeholder_in, placeholder_out))
        return {"mode": "both", "cpu_cmd": cpu_cmd, "gpu_cmd": gpu_cmd}
    elif preset in PRESETS:
        cmd = " ".join(build_preset_cmd(preset, placeholder_in, placeholder_out))
        return {"mode": "single", "cmd": cmd}
    else:
        return JSONResponse({"error": "Unknown preset"}, status_code=400)


@app.post("/variance/run", dependencies=[Depends(requires(VARIANCE_RUN))])
async def variance_run(request: Request):
    from video import run_variance_calibration
    if int(cfg.load().get("variance_runs", 0)) <= 0:
        return JSONResponse(
            {"error": "Variance Runs is 0 — calibration disabled. Set it to ≥2 to run."},
            status_code=400)
    job_id = str(uuid.uuid4())[:8]
    label = "Variance calibration — system offline"

    async def coro():
        try:
            jobs[job_id].update({"status": "running", "stage": "starting"})
            result = await run_variance_calibration(job_id, jobs)
            jobs[job_id].update({"status": "done", "stage": "done", "result": result})
        except Exception as e:
            jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}

    position = queue_control.enqueue(job_id, "variance", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


@app.post("/benchmark/run", dependencies=[Depends(requires(BENCHMARK_RUN))])
async def benchmark_run(request: Request):
    """CR-061 — launch the in-app overnight benchmark as one queue job."""
    bid = str(uuid.uuid4())[:8]
    benchmark.create_run(bid, cfg.load())   # pre-create queued manifest
    label = "Overnight benchmark"

    async def coro():
        try:
            jobs[bid].update({"status": "running", "stage": "starting"})
            result = await benchmark.run_benchmark_job(bid, jobs, cfg.load())
            jobs[bid].update({"status": "done", "stage": "done", "result": result})
        except Exception as e:
            jobs[bid] = {**jobs.get(bid, {}), "status": "error",
                         "stage": "error", "error": str(e)}

    position = queue_control.enqueue(bid, "benchmark", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": bid, "queue_position": position}


@app.post("/benchmark/cancel", dependencies=[Depends(requires(BENCHMARK_RUN))])
async def benchmark_cancel(request: Request, job_id: str = Form(...)):
    """Cancel a benchmark run. Running → cooperative flag (lands after the
    current step); queued-but-not-started → drop from queue + mark cancelled."""
    job_id = (job_id or "").strip()
    if queue_control.current_job_id == job_id:
        if job_id in jobs:
            jobs[job_id]["cancel_requested"] = True
        return {"ok": True, "state": "cancelling"}
    if queue_control.cancel_pending(job_id):
        if job_id in jobs:
            jobs[job_id].update({"status": "cancelled", "stage": "cancelled"})
        benchmark.cancel_queued(job_id)
        return {"ok": True, "state": "cancelled_before_start"}
    return JSONResponse({"ok": False, "state": "not_found"}, status_code=404)


@app.post("/job/{job_id}/cooldown-decision", dependencies=[Depends(requires(BENCHMARK_RUN))])
async def cooldown_decision(job_id: str, decision: str = Form(...)):
    """Resolve the idle-wait timeout dialog for an attended Lab run.

    power.cooldown_between_runs parks the job at stage 'awaiting_cooldown_decision'
    and polls jobs[job_id]['cooldown_decision']; this writes it. Gated to Lab
    (BENCHMARK_RUN) — the dialog is only ever offered to Lab runs. 'wait' is only
    accepted while it's still in the offered options (bounded re-waits)."""
    decision = (decision or "").strip()
    j = jobs.get(job_id)
    if not j:
        return JSONResponse({"ok": False, "error": "unknown job"}, status_code=404)
    if j.get("stage") != "awaiting_cooldown_decision":
        return JSONResponse({"ok": False, "error": "job is not awaiting a cooldown decision"},
                            status_code=409)
    allowed = j.get("cooldown_decision_options") or ["run", "cancel"]
    if decision not in allowed:
        return JSONResponse({"ok": False, "error": f"decision must be one of {allowed}"},
                            status_code=400)
    j["cooldown_decision"] = decision
    return {"ok": True, "decision": decision}


@app.get("/precalibration/data", dependencies=[Depends(requires(SETTINGS_READ_FULL))])
async def precalibration_data():
    """Return the latest thermal-recovery probe data as JSON.

    Source: results/diagnostics/recovery_<timestamp>_summary.csv (one row per
    distance × workload). Generated by `bin/probe-thermal-recovery`. The
    summary CSV is enough for the recovery-curve chart; the matching
    `_<timestamp>.csv` (raw per-poll readings) is referenced for download.
    """
    import csv as csv_mod
    diag_dir = Path("/home/gos/wattlab/results/diagnostics")
    if not diag_dir.exists():
        return {"available": False, "reason": "no diagnostics directory"}
    summaries = sorted(diag_dir.glob("recovery_*_summary.csv"))
    if not summaries:
        return {"available": False, "reason": "no probe data yet"}
    latest = summaries[-1]
    raw = latest.with_name(latest.stem.replace("_summary", "") + ".csv")
    points = []
    with latest.open() as f:
        for row in csv_mod.DictReader(f):
            points.append({
                "distance_s": int(row["distance_s"]),
                "workload":   row["workload"],
                "encode_s":   float(row["encode_s"]),
                "n_polls":    int(row["n_polls"]),
                "mean_w":     float(row["mean_w"]),
                "std_w":      float(row["std_w"]),
                "cv_pct":     float(row["cv_pct"]),
                "min_w":      float(row["min_w"]),
                "max_w":      float(row["max_w"]),
            })
    return {
        "available": True,
        "source_summary": str(latest),
        "source_raw":     str(raw) if raw.exists() else None,
        "generated_at":   datetime.fromtimestamp(latest.stat().st_mtime)
                                  .isoformat(timespec="seconds"),
        "points": points,
    }


# --- LLM job runner ---

async def run_llm_job(job_id: str, model_key: str, task_key: str,
                      repeats: int = 1, warm: bool = False, prompt: str = None,
                      device: str = "gpu"):
    try:
        jobs[job_id].update({"status": "running", "stage": "baseline", "partial_response": ""})
        if device == "both":
            result = await run_llm_both_measurement(
                model_key, task_key, jobs, job_id, warm, prompt)
        elif repeats > 1:
            result = await run_llm_batch_measurement(
                model_key, task_key, repeats, warm, prompt, jobs, job_id)
        else:
            result = await run_llm_measurement(
                model_key, task_key, jobs, job_id, warm, prompt, device)
        save_result("llm", job_id, result)
        jobs[job_id].update({"status": "done", "stage": "done", "result": result})
    except Exception as e:
        jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}

@app.get("/llm", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def llm_page(request: Request):
    # CR-001 part C2c — capability flags drive the lock-badge UI.
    # Anonymous sees the same controls dim/disabled with a "Members only ·
    # Join GoS" badge; the runtime gates in /llm/run already enforce the
    # rule — this is the visible product copy.
    can_custom_prompt = can(audience.tier(request), CUSTOM_PROMPT)
    can_batch_compare = can(audience.tier(request), BATCH_COMPARE)
    lk_prompt_class   = _lock_class(request, CUSTOM_PROMPT)
    lk_prompt_badge   = _lock_badge_html(request, CUSTOM_PROMPT, "Edit prompt — Members only")
    lk_batch_class    = _lock_class(request, BATCH_COMPARE)
    lk_batch_badge    = _lock_badge_html(request, BATCH_COMPARE, "Batch / compare — Members only")
    dis_prompt        = _disabled_attr(request, CUSTOM_PROMPT)
    dis_batch         = _disabled_attr(request, BATCH_COMPARE)

    models_html = "".join([
        f'''<div class="preset" id="model-{k}" onclick="selectModel('{k}')">
            <h3>{v["label"]}</h3>
            <p style="color:var(--text-3);font-size:0.75rem">{v["params"]} · {v["size"]}</p>
            {_model_date_line(v)}
        </div>'''
        for k, v in MODELS.items()
    ])

    tasks_html = "".join([
        f'''<label style="display:flex;gap:0.75rem;border:1px solid var(--border-3);
                     padding:0.75rem;cursor:pointer;margin-bottom:0.5rem">
            <input type="radio" name="task" value="{k}"
                   {"checked" if k == "T1" else ""}
                   onchange="selectedTask='{k}'; document.getElementById('promptText').value=defaultPrompts['{k}']||''"
                   style="accent-color:var(--accent);margin-top:0.2rem">
            <div>
                <div style="color:var(--text);font-size:0.85rem">{v["label"]}</div>
                <div style="color:var(--text-3);font-size:0.75rem">{v["prompt"][:80]}...</div>
            </div>
        </label>'''
        for k, v in TASKS.items()
    ])

    import json as _json
    tasks_js = _json.dumps({k: v["prompt"] for k, v in TASKS.items()})

    return _bake_durations(f"""<!DOCTYPE html>
<html>
<head>
    <link rel="icon" type="image/svg+xml" href="/static/owl.svg">
  <title>OWL — LLM Inference Test</title>
    <style>
        * {{ box-sizing:border-box; margin:0; padding:0; }}
        body {{ font-family:monospace; background:var(--bg); color:var(--text);
               max-width:780px; margin:0 auto; padding:2rem; }}
        h1 {{ color:var(--accent); margin-bottom:0.25rem; font-size:1.6rem; }}
        .subtitle {{ color:var(--text-3); font-size:0.8rem; margin-bottom:1.5rem; }}
        .info {{ color:var(--text-3); font-size:0.82rem; margin-bottom:1.5rem;
                 border-left:2px solid #222; padding-left:1rem; line-height:1.6; }}
        .presets {{ display:flex; gap:0.75rem; margin-bottom:1.5rem; }}
        .preset {{ border:1px solid var(--border-3); padding:1rem; cursor:pointer; flex:1; }}
        .preset:hover {{ border-color:#00ff9966; }}
        .preset.selected {{ border-color:var(--accent); background:#00ff9911; }}
        .preset h3 {{ color:var(--accent); font-size:0.9rem; margin-bottom:0.4rem; }}
        .section-label {{ color:var(--text-3); font-size:0.75rem; text-transform:uppercase;
                          letter-spacing:0.05em; margin-bottom:0.75rem; }}
        button {{ background:var(--accent); color:#000; border:none; padding:0.75rem 2rem;
                  cursor:pointer; font-family:monospace; font-size:1rem; margin-top:1rem; }}
        button:disabled {{ background:var(--border); color:var(--text-3); cursor:not-allowed; }}
        button:hover:not(:disabled) {{ background:var(--accent-hover); }}
        #status {{ margin-top:1.5rem; }}
        .result-box {{ border:1px solid var(--border); padding:1.5rem; }}
        .result-box h2 {{ color:var(--accent); font-size:1.1rem; margin-bottom:1rem;
                          padding-bottom:0.5rem; border-bottom:1px solid var(--border); }}
        .metric {{ display:flex; justify-content:space-between;
                   padding:0.3rem 0; border-bottom:1px solid var(--panel); font-size:0.82rem; }}
        .val {{ color:var(--accent); }}
        .section-title {{ color:var(--text-4); font-size:0.72rem; text-transform:uppercase;
                          letter-spacing:0.05em; margin:0.75rem 0 0.4rem; }}
        .response-box {{ background:var(--panel); padding:1rem; margin-top:0.75rem;
                         font-size:0.8rem; color:var(--text-2); line-height:1.6;
                         border-left:2px solid #00ff9944; max-height:500px;
                         overflow-y:auto; white-space:pre-wrap; }}
        .scope-note {{ color:var(--text-5); font-size:0.72rem; margin-top:1rem; }}
        .progress-box {{ border:1px solid var(--border); padding:1.5rem; }}
        .progress-header {{ color:var(--warn); font-size:0.9rem; margin-bottom:1rem; }}
        .stage {{ display:flex; align-items:center; gap:0.75rem;
                  font-size:0.82rem; margin-bottom:0.4rem; }}
        .stage.active .stage-label {{ color:var(--warn); }}
        .stage.done .stage-label {{ color:var(--accent); }}
        .stage.pending .stage-label {{ color:var(--text-5); }}
        a.back {{ color:var(--text-3); text-decoration:none; font-size:0.82rem;
                  display:inline-block; margin-top:1.5rem; }}
        a.back:hover {{ color:var(--accent); }}
        {_LOCK_STYLES}
    </style>
</head>
<body>
    {_BACK}
    <h1>LLM Inference Energy Test {_BETA_CHIP}</h1>
    <div class="subtitle">Greening of Streaming · OWL · GoS1</div>

    <div style="margin-bottom:1.5rem;padding:0.85rem 1rem;border:1px solid var(--accent);
                background:var(--accent-soft);font-size:0.85rem;line-height:1.5">
        <span style="color:var(--accent);font-weight:bold">NEW</span> &middot;
        <a href="/llm/compare" style="color:var(--accent);text-decoration:none;
                                       border-bottom:1px solid var(--accent)">Compare {len(MODELS)} models on one prompt &rarr; energy per correct answer &nearr;</a>
        <span style="color:var(--text-3)"> &nbsp;CR-048 hybrid: 3-prompt showcase + member &ldquo;Try your own&rdquo;.</span>
    </div>

    {_ai_intro('llm')}

    <div style="margin-bottom:1rem;font-size:0.78rem;color:var(--text-3)">
        First time here? <a href="/demo" style="color:var(--accent);text-decoration:none">Try the Guided Tour →</a>
    </div>

    <details style="margin-bottom:1.5rem;border-left:2px solid #222;padding-left:1rem">
        <summary style="cursor:pointer;color:var(--text-3);font-size:0.82rem;list-style:none;outline:none">
            ⓘ About this test <span style="color:var(--text-4);font-size:0.72rem">(click to expand)</span>
        </summary>
        <div style="color:var(--text-3);font-size:0.82rem;line-height:1.6;margin-top:0.75rem">
            Run a language model on a fixed prompt and measure energy per token.<br>
            Models span small → large: TinyLlama 1.1B · Mistral 7B · Gemma 3 12B. CPU + ROCm GPU (via Ollama).<br>
            Cold mode unloads the model first; warm mode reuses a loaded model. Batch mode runs N inferences with a rest between.<br>
            Primary metric: <strong style="color:var(--text-2)">mWh per output token</strong> · P110 polled at 1s intervals.<br>
            Scope: device layer only — no amortised training cost included.
        </div>
    </details>

    <div class="section-label">Model</div>
    <div class="presets">{models_html}</div>

    <div class="section-label">Task</div>
    {tasks_html}

    {lk_prompt_badge}
    <div id="prompt-editor" class="{lk_prompt_class}" style="margin-bottom:1.5rem">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:0.4rem">
            <div style="color:var(--text-2);font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em">✎ Edit prompt</div>
            <button onclick="resetPrompt()"{dis_prompt} style="background:none;border:none;color:var(--text-3);
                font-size:0.75rem;cursor:pointer;padding:0;font-family:monospace">Reset to default</button>
        </div>
        <textarea id="promptText" rows="3"{dis_prompt}
            style="width:100%;background:#0f0f0f;border:1px solid var(--border-3);border-left:2px solid #00ff9966;
                   color:var(--text-2);font-family:monospace;font-size:0.8rem;padding:0.75rem;
                   resize:vertical;line-height:1.5"></textarea>
    </div>

    <div style="display:flex;gap:2rem;margin-bottom:1.5rem;flex-wrap:wrap">
        <div>
            <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                        letter-spacing:0.05em;margin-bottom:0.5rem">Backend</div>
            <div style="display:flex;gap:0.75rem">
                <label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="device" value="gpu" checked
                           onchange="selectedDevice='gpu'" style="accent-color:var(--accent)"> GPU
                </label>
                <label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="device" value="cpu"
                           onchange="selectedDevice='cpu'" style="accent-color:var(--accent)"> CPU
                </label>
                <label class="{lk_batch_class}" style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="device" value="both"{dis_batch}
                           onchange="selectedDevice='both'" style="accent-color:var(--accent)"> Both ⚡
                </label>
            </div>
            <div style="color:var(--text-5);font-size:0.72rem;margin-top:0.3rem">
                Both: CPU then GPU with new baseline — full side-by-side comparison
            </div>
        </div>
        <div>
            <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                        letter-spacing:0.05em;margin-bottom:0.5rem">Mode</div>
            <div style="display:flex;gap:0.75rem">
                <label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="warmMode" value="cold" checked
                           onchange="selectedWarm=false" style="accent-color:var(--accent)"> Cold
                </label>
                <label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="warmMode" value="warm"
                           onchange="selectedWarm=true" style="accent-color:var(--accent)"> Warm
                </label>
            </div>
            <div style="color:var(--text-5);font-size:0.72rem;margin-top:0.3rem">
                Cold: unload model before baseline · Warm: model stays loaded
            </div>
        </div>
        <div>
            <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                        letter-spacing:0.05em;margin-bottom:0.5rem">Repeats</div>
            <div style="display:flex;gap:0.75rem">
                <label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="repeats" value="1" checked
                           onchange="selectedRepeats=1" style="accent-color:var(--accent)"> 1×
                </label>
                <label class="{lk_batch_class}" style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="repeats" value="3"{dis_batch}
                           onchange="selectedRepeats=3" style="accent-color:var(--accent)"> 3×
                </label>
                <label class="{lk_batch_class}" style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="repeats" value="5"{dis_batch}
                           onchange="selectedRepeats=5" style="accent-color:var(--accent)"> 5×
                </label>
            </div>
            <div style="color:var(--text-5);font-size:0.72rem;margin-top:0.3rem">
                Batch: load once, 10s rest between runs
            </div>
        </div>
    </div>

    {lk_batch_badge}
    <div style="display:flex;gap:0.75rem;flex-wrap:wrap">
        <button id="runBtn" onclick="runInference()">Run Measurement</button>
        <button id="runAllBtn" class="{lk_batch_class}" onclick="runAllTasks()"{dis_batch}
            style="background:var(--bg);border:1px solid #00ff9966;color:var(--accent);
                   padding:0.65rem 1.25rem;font-family:monospace;font-size:0.85rem;cursor:pointer">
            Run All Tasks (T1+T2+T3)
        </button>
    </div>
    <div id="status"></div>
    <div id="prev-runs" style="margin-top:2rem;border-top:1px solid var(--panel);padding-top:1.5rem"></div>

    <script>
    // CR-001 part C2c — capability flags from the server.
    // CAN_CUSTOM_PROMPT false → JS never posts `prompt=`, server uses
    // the canonical task prompt. Stops Anonymous from tripping the
    // runtime CUSTOM_PROMPT gate just because the textarea is pre-filled.
    const CAN_CUSTOM_PROMPT = {('true' if can_custom_prompt else 'false')};
    const CAN_BATCH_COMPARE = {('true' if can_batch_compare else 'false')};

    let selectedModel = 'tinyllama';
    let selectedTask = 'T1';
    let selectedWarm = false;
    let selectedRepeats = 1;
    let selectedDevice = 'gpu';
    let startTime = null;
    let streamTimer = null;

    const defaultPrompts = {tasks_js};

    // Select first model by default and populate prompt
    document.getElementById('model-tinyllama').classList.add('selected');
    document.getElementById('promptText').value = defaultPrompts['T1'] || '';

    function selectModel(key) {{
        selectedModel = key;
        document.querySelectorAll('.preset').forEach(el => el.classList.remove('selected'));
        document.getElementById('model-' + key).classList.add('selected');
    }}

    function resetPrompt() {{
        document.getElementById('promptText').value = defaultPrompts[selectedTask] || '';
    }}

    function renderProgress(stage, watts) {{
        const isBoth = stage.startsWith('baseline_cpu') || stage.startsWith('cpu_') ||
                       stage.startsWith('baseline_gpu') || stage.startsWith('gpu_') ||
                       stage === 'cooldown';
        const displayStage = stage.startsWith('inference_') ? 'inference' :
                             stage.startsWith('rest_') ? 'rest' :
                             stage.startsWith('cpu_inference') ? 'cpu_inference' :
                             stage.startsWith('gpu_inference') ? 'gpu_inference' : stage;
        const stageLabel = stage.startsWith('inference_') ? 'Running inference (' + stage.replace('inference_','').replace('_',' ') + ')' :
                           stage.startsWith('rest_') ? 'Resting between runs\u2026' : null;
        const stages = isBoth ? [
            ['baseline_cpu', 'Measuring CPU baseline ({{BASELINE_S}}s)'],
            ['cpu_inference', 'CPU inference (num_gpu=0)'],
            ['cooldown', 'Cooldown between runs {{COOLDOWN_PAREN}}'],
            ['baseline_gpu', 'Measuring GPU baseline ({{BASELINE_S}}s)'],
            ['gpu_inference', 'GPU inference (ROCm)'],
            ['done', 'Done'],
        ] : [
            ['baseline', 'Measuring baseline ({{BASELINE_S}}s)'],
            ['inference', stageLabel || 'Running inference'],
            ['rest', 'Resting between runs\u2026 ({{LLM_REST_S}}s)'],
            ['done', 'Done'],
        ].filter(([k]) => k !== 'rest' || displayStage === 'rest');
        const stageIdx = stages.findIndex(([k]) => k === displayStage);
        wlRenderProgress({{
            header: 'Running \u2014 do not close this tab',
            stagesHtml: wlStageList(stages.map(([k,l]) => l), stageIdx < 0 ? 0 : stageIdx),
            watts: watts,
            elapsed: startTime ? Date.now() - startTime : null,
            extraHtml: '<div id="stream-preview" style="margin-top:0.75rem;background:var(--panel);'
                + 'padding:0.75rem;font-size:0.78rem;color:var(--text-3);line-height:1.6;'
                + 'min-height:2rem;border-left:2px solid #00ff9933;max-height:120px;'
                + 'overflow-y:auto;white-space:pre-wrap"></div>',
        }});
    }}

    async function runInference() {{
        const btn = document.getElementById('runBtn');
        btn.disabled = true;
        startTime = Date.now();

        const form = new FormData();
        form.append('model_key', selectedModel);
        form.append('task_key', selectedTask);
        form.append('repeats', selectedRepeats);
        form.append('warm', selectedWarm ? 'true' : 'false');
        form.append('device', selectedDevice);
        const promptVal = document.getElementById('promptText').value.trim();
        if (promptVal && CAN_CUSTOM_PROMPT) form.append('prompt', promptVal);

        try {{
            const resp = await fetch('/llm/run', {{method:'POST', body:form}});
            const data = await resp.json();
            if (data.job_id) {{
                renderProgress('baseline');
                pollLLM(data.job_id);
            }} else {{
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + JSON.stringify(data) + '</div>';
                btn.disabled = false;
            }}
        }} catch(e) {{
            document.getElementById('status').innerHTML =
                '<div style="color:var(--err)">Failed: ' + e + '</div>';
            btn.disabled = false;
        }}
    }}

    async function pollLLM(jobId) {{
        try {{
            const [resp, powerR] = await Promise.all([
                fetch('/llm/job/' + jobId),
                fetch('/power').catch(() => null),
            ]);
            const data = await resp.json();
            const watts = powerR ? (await powerR.json().catch(()=>({{}}))).watts ?? null : null;
            if (data.status === 'done') {{
                if (streamTimer) {{ clearTimeout(streamTimer); streamTimer = null; }}
                renderLLMResult(data.result, jobId);
                document.getElementById('runBtn').disabled = false;
            }} else if (data.status === 'error') {{
                if (streamTimer) {{ clearTimeout(streamTimer); streamTimer = null; }}
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + data.error + '</div>';
                document.getElementById('runBtn').disabled = false;
            }} else if (data.stage === 'queued') {{
                wlRenderQueued(data.queue_position);
                streamTimer = setTimeout(() => pollLLM(jobId), 3000);
            }} else {{
                const stage = data.stage || 'baseline';
                renderProgress(stage, watts);
                if (stage.startsWith('inference') && data.partial_response) {{
                    const box = document.getElementById('stream-preview');
                    if (box) box.textContent = data.partial_response;
                }}
                const delay = stage.startsWith('inference') ? 500 : 5000;
                streamTimer = setTimeout(() => pollLLM(jobId), delay);
            }}
        }} catch(e) {{
            streamTimer = setTimeout(() => pollLLM(jobId), 5000);
        }}
    }}

    function renderLLMResult(r, jobId) {{
        const elapsed = startTime ? wlFormatElapsed(Date.now() - startTime) : '';
        const base = '/results/llm/' + jobId;
        const links = jobId ? `<div style="margin-top:1rem;display:flex;gap:0.75rem">
            <a href="${{base}}/download.json" download
               style="color:var(--accent);font-size:0.8rem;border:1px solid #00ff9944;
                      padding:0.3rem 0.75rem;text-decoration:none">↓ JSON</a>
            <a href="${{base}}/download.csv" download
               style="color:var(--accent);font-size:0.8rem;border:1px solid #00ff9944;
                      padding:0.3rem 0.75rem;text-decoration:none">↓ CSV</a>
        </div>` : '';
        const elapsedNote = elapsed ? `<div style="color:var(--text-4);font-size:0.78rem;margin-bottom:1rem">
            Total elapsed: ${{elapsed}}</div>` : '';

        let body;
        if (r.mode === 'both') {{
            body = renderLLMBoth(r);
        }} else if (r.mode === 'batch') {{
            body = renderLLMBatch(r);
        }} else if (r.mode === 'all') {{
            body = renderLLMAll(r);
        }} else if (r.mode === 'all_both') {{
            body = renderLLMAllBoth(r);
        }} else {{
            body = renderLLMSingle(r);
        }}
        document.getElementById('status').innerHTML = elapsedNote + body + links;
        loadPrevRuns();
    }}

    function renderLLMSingle(r) {{
        const e = r.energy;
        const i = r.inference;
        const t = r.thermals;
        const modeNote = r.warm ? '🌡 Warm (model pre-loaded)' : '❄ Cold (model unloaded before baseline)';
        return `<div class="result-box">
                <h2>Energy Report — ${{r.model_label}} · ${{r.task_label}}</h2>
                <div class="section-title">Inference</div>
                <div class="metric"><span>Model</span><span class="val">${{r.model_label}} (${{r.model_params}})</span></div>
                <div class="metric"><span>Task</span><span class="val">${{r.task_label}}</span></div>
                <div class="metric"><span>Mode</span><span class="val">${{modeNote}}</span></div>
                <div class="metric"><span>Output tokens</span><span class="val">${{i.output_tokens}}</span></div>
                <div class="metric"><span>Tokens/sec</span><span class="val">${{i.tokens_per_sec}}</span></div>
                <div class="metric"><span>Duration</span><span class="val">${{i.duration_s}}s</span></div>
                <div class="section-title">Power (P110)</div>
                <div class="metric"><span>Baseline</span><span class="val">${{e.w_base}} W</span></div>
                <div class="metric"><span>Task mean</span><span class="val">${{e.w_task}} W</span></div>
                <div class="metric"><span>Delta (ΔW)</span><span class="val">${{e.delta_w}} W</span></div>
                <div class="metric"><span>Energy (ΔE)</span><span class="val">${{e.delta_e_wh}} Wh</span></div>
                ${{wlCarbonRow(e)}}
                <div class="metric"><span>Energy/token</span>
                    <span class="val">${{e.mwh_per_token}} mWh/token</span></div>
                <div class="metric"><span>Polls</span><span class="val">${{e.poll_count}}</span></div>
                <div class="section-title">Thermals</div>
                <div class="metric"><span>CPU (start→end)</span>
                    <span class="val">${{t.cpu_base}}→${{t.cpu_end}}°C</span></div>
                <div class="metric"><span>GPU (start→end)</span>
                    <span class="val">${{t.gpu_base}}→${{t.gpu_end}}°C</span></div>
                <div class="conf-badge" style="margin-top:0.75rem">${{e.confidence.flag}} ${{e.confidence.label}}</div>
                ${{e.video_relative ? '<div style="font-size:0.78rem;color:var(--text-3);margin-top:0.5rem">This run ' + e.video_relative.text + '</div>' : ''}}
                <div class="section-title">Response preview</div>
                <div class="response-box">${{i.response}}</div>
                ${{wlCarbonStrip(e.delta_e_wh, r.model_label + ' · ' + r.task_label, e.delta_t_s, e.co2e && e.co2e.intensity ? e.co2e.intensity.g_per_kwh : null)}}
                <div class="scope-note">${{r.scope}}</div>
            </div>`;
    }}

    function renderLLMBatch(r) {{
        const agg = r.aggregate;
        const t = r.thermals;
        const modeNote = r.warm ? '🌡 Warm' : '❄ Cold';
        const runsRows = r.runs.map(run => {{
            const e = run.energy;
            const i = run.inference;
            return `<tr>
                <td style="color:var(--text-3)">${{run.run}}</td>
                <td>${{i.output_tokens}}</td>
                <td>${{i.tokens_per_sec}}</td>
                <td>${{e.delta_e_wh}} Wh</td>
                <td>${{e.mwh_per_token}} mWh/tok</td>
                <td class="conf-badge">${{e.confidence.flag}}</td>
            </tr>`;
        }}).join('');
        return `<div class="result-box">
                <h2>Batch Report — ${{r.model_label}} · ${{r.task_label}}</h2>
                <div class="section-title">Run parameters</div>
                <div class="metric"><span>Model</span><span class="val">${{r.model_label}} (${{r.model_params}})</span></div>
                <div class="metric"><span>Task</span><span class="val">${{r.task_label}}</span></div>
                <div class="metric"><span>Mode</span><span class="val">${{modeNote}} · ${{r.repeats}}× runs · 10s rest</span></div>
                <div class="section-title">Aggregate</div>
                <div class="metric"><span>Energy/token (mean)</span>
                    <span class="val">${{agg.mwh_per_token_mean}} mWh/token</span></div>
                <div class="metric"><span>Energy/token (σ)</span>
                    <span class="val">${{agg.mwh_per_token_stddev ?? '—'}}</span></div>
                <div class="metric"><span>Energy per run (mean)</span>
                    <span class="val">${{agg.delta_e_wh_mean}} Wh</span></div>
                <div class="metric"><span>Energy per run (σ)</span>
                    <span class="val">${{agg.delta_e_wh_stddev ?? '—'}}</span></div>
                <div class="metric"><span>Tokens/sec (mean)</span>
                    <span class="val">${{agg.tokens_per_sec_mean}}</span></div>
                <div class="section-title">Per-run breakdown</div>
                <table style="width:100%;border-collapse:collapse;font-size:0.78rem">
                    <thead><tr style="color:var(--text-4);text-align:left">
                        <th style="padding:0.3rem 0.5rem 0.3rem 0">#</th>
                        <th style="padding:0.3rem 0.5rem">Tokens</th>
                        <th style="padding:0.3rem 0.5rem">Tok/s</th>
                        <th style="padding:0.3rem 0.5rem">ΔE</th>
                        <th style="padding:0.3rem 0.5rem">mWh/tok</th>
                        <th style="padding:0.3rem 0.5rem">Conf</th>
                    </tr></thead>
                    <tbody style="color:var(--text-2)">${{runsRows}}</tbody>
                </table>
                <div class="section-title">Thermals</div>
                <div class="metric"><span>CPU (start→end)</span>
                    <span class="val">${{t.cpu_base}}→${{t.cpu_end}}°C</span></div>
                <div class="metric"><span>GPU (start→end)</span>
                    <span class="val">${{t.gpu_base}}→${{t.gpu_end}}°C</span></div>
                <div class="section-title">Response preview (last run)</div>
                <div class="response-box">${{r.runs[r.runs.length-1].inference.response}}</div>
                ${{wlCarbonStrip(agg.delta_e_wh_mean, r.model_label + ' · ' + r.task_label + ' (mean of ' + r.repeats + ')')}}
                <div class="scope-note">${{r.scope}}</div>
            </div>`;
    }}

    function renderLLMBoth(r) {{
        const a = r.analysis;
        const cpu = r.cpu, gpu = r.gpu;
        const ce = cpu.energy, ge = gpu.energy;
        const ci = cpu.inference, gi = gpu.inference;
        const winnerColor = (winner, side) => winner === side ? '#00ff99' : '#888';
        // Strip uses the lower (more efficient) of the two energies.
        const _stripWh = (ce.delta_e_wh != null && ge.delta_e_wh != null)
            ? Math.min(ce.delta_e_wh, ge.delta_e_wh)
            : (ce.delta_e_wh != null ? ce.delta_e_wh : ge.delta_e_wh);
        const _stripLbl = r.model_label + ' · ' + r.task_label
            + ' (' + (a.energy_winner ? a.energy_winner + ' wins' : 'best of CPU/GPU') + ')';
        // Winner's energy block — drift note + duration for the strip.
        const _winE = (ce.delta_e_wh != null && ge.delta_e_wh != null)
            ? (ce.delta_e_wh <= ge.delta_e_wh ? ce : ge)
            : (ce.delta_e_wh != null ? ce : ge);
        const _stripDur = _winE ? _winE.delta_t_s : null;
        const _stripSavedG = _winE && _winE.co2e && _winE.co2e.intensity
            ? _winE.co2e.intensity.g_per_kwh : null;
        // CR-032 — sub-runs for the carbon strip's per-mode breakdown.
        const _subRuns = [
            {{side: 'CPU', e: ce}},
            {{side: 'GPU', e: ge}}
        ].filter(s => s.e && s.e.co2e).map(s => ({{
            label: s.side + ' · ' + r.model_label,
            grams: s.e.co2e.grams,
            deltaWh: s.e.delta_e_wh,
            durationS: s.e.delta_t_s
        }}));
        // CR-038 — structured efficiency verdict, alongside a.finding prose.
        const _llmBothVerdict = wlEfficiencyVerdict([
          ce ? {{label: 'CPU', energy: ce.mwh_per_token}} : null,
          ge ? {{label: 'GPU', energy: ge.mwh_per_token}} : null
        ], {{unit: 'mWh/token'}});
        return `<div class="result-box">
            <h2>CPU vs GPU — ${{r.model_label}} · ${{r.task_label}}</h2>
            <div style="background:#0d1a0d;border:1px solid #00ff9933;
                        padding:1rem;margin-bottom:1.25rem;font-size:0.82rem;line-height:1.7">
              ${{a.finding}}
            </div>
            ${{_llmBothVerdict}}
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1.25rem">
              <div style="border:1px solid var(--border);padding:1rem">
                <div style="color:var(--text-3);font-size:0.72rem;margin-bottom:0.75rem">CPU (num_gpu=0 · Ryzen 9 7900)</div>
                <div class="metric"><span>Tokens/sec</span>
                  <span class="val" style="color:${{winnerColor(a.speed_winner,'CPU')}}">${{ci.tokens_per_sec}}</span></div>
                <div class="metric"><span>Duration</span><span class="val">${{ci.duration_s}}s</span></div>
                <div class="metric"><span>ΔE total</span>
                  <span class="val" style="color:${{winnerColor(a.energy_winner,'CPU')}}">${{ce.delta_e_wh}} Wh</span></div>
                ${{wlCarbonRow(ce)}}
                <div class="metric"><span>mWh/token</span>
                  <span class="val" style="color:${{winnerColor(a.mwh_winner,'CPU')}}">${{ce.mwh_per_token}}</span></div>
                <div class="metric"><span>ΔW</span><span class="val">${{ce.delta_w}} W</span></div>
                <div class="conf-badge" style="margin-top:0.5rem">${{ce.confidence.flag}} ${{ce.confidence.label}}</div>
              </div>
              <div style="border:1px solid var(--border);padding:1rem">
                <div style="color:var(--text-3);font-size:0.72rem;margin-bottom:0.75rem">GPU ({_gpu_runtime()} · {_gpu_display_name()})</div>
                <div class="metric"><span>Tokens/sec</span>
                  <span class="val" style="color:${{winnerColor(a.speed_winner,'GPU')}}">${{gi.tokens_per_sec}}</span></div>
                <div class="metric"><span>Duration</span><span class="val">${{gi.duration_s}}s</span></div>
                <div class="metric"><span>ΔE total</span>
                  <span class="val" style="color:${{winnerColor(a.energy_winner,'GPU')}}">${{ge.delta_e_wh}} Wh</span></div>
                ${{wlCarbonRow(ge)}}
                <div class="metric"><span>mWh/token</span>
                  <span class="val" style="color:${{winnerColor(a.mwh_winner,'GPU')}}">${{ge.mwh_per_token}}</span></div>
                <div class="metric"><span>ΔW</span><span class="val">${{ge.delta_w}} W</span></div>
                <div class="conf-badge" style="margin-top:0.5rem">${{ge.confidence.flag}} ${{ge.confidence.label}}</div>
              </div>
            </div>
            <div class="section-title">GPU response preview</div>
            <div class="response-box">${{gi.response}}</div>
            ${{wlCarbonStrip(_stripWh, _stripLbl, _stripDur, _stripSavedG, _subRuns)}}
            <div class="scope-note">${{r.scope}}</div>
        </div>`;
    }}

    function renderLLMAll(r) {{
        const taskLabels = {{'T1': 'Short factual', 'T2': 'Medium reasoning', 'T3': 'Long generation'}};
        const cards = Object.entries(r.tasks).map(([key, t]) => {{
            const e = t.energy;
            const i = t.inference;
            return `<div style="border:1px solid var(--border);padding:1rem;margin-bottom:0.75rem">
                <div style="color:var(--accent);font-size:0.78rem;margin-bottom:0.75rem">${{key}} — ${{taskLabels[key] || key}}</div>
                <div class="metric"><span>Output tokens</span><span class="val">${{i.output_tokens}}</span></div>
                <div class="metric"><span>Tokens/sec</span><span class="val">${{i.tokens_per_sec}}</span></div>
                <div class="metric"><span>Duration</span><span class="val">${{i.duration_s}}s</span></div>
                <div class="metric"><span>ΔE</span><span class="val">${{e.delta_e_wh}} Wh</span></div>
                ${{wlCarbonRow(e)}}
                <div class="metric"><span>mWh/token</span><span class="val">${{e.mwh_per_token}}</span></div>
                <div class="metric"><span>ΔW</span><span class="val">${{e.delta_w}} W</span></div>
                <div class="conf-badge" style="margin-top:0.5rem;font-size:0.82rem">${{e.confidence.flag}} ${{e.confidence.label}}</div>
                ${{e.video_relative ? '<div style="font-size:0.76rem;color:var(--text-3);margin-top:0.4rem">This run ' + e.video_relative.text + '</div>' : ''}}
                <div class="section-title" style="margin-top:0.75rem">Response preview</div>
                <div class="response-box">${{i.response}}</div>
            </div>`;
        }}).join('');
        // Headline Wh = T3 (long generation), the largest of the three tasks.
        const _t3e = r.tasks && r.tasks.T3 && r.tasks.T3.energy ? r.tasks.T3.energy : null;
        const _t3 = _t3e ? _t3e.delta_e_wh : null;
        const _t3Dur = _t3e ? _t3e.delta_t_s : null;
        const _t3SavedG = _t3e && _t3e.co2e && _t3e.co2e.intensity
            ? _t3e.co2e.intensity.g_per_kwh : null;
        // CR-032 — sub-runs across T1/T2/T3 so the strip details show every
        // task's CO2e snapshot, not only the T3 headline.
        const _subRuns = Object.entries(r.tasks || {{}})
            .filter(([k, t]) => t && t.energy && t.energy.co2e)
            .map(([k, t]) => ({{
                label: k + ' — ' + (taskLabels[k] || k),
                grams: t.energy.co2e.grams,
                deltaWh: t.energy.delta_e_wh,
                durationS: t.energy.delta_t_s
            }}));
        return `<div class="result-box">
            <h2>All Tasks — ${{r.model_label}} (${{r.model_params}})</h2>
            <div style="color:var(--text-3);font-size:0.78rem;margin-bottom:1rem">
                ${{r.warm ? '🌡 Warm' : '❄ Cold'}} · ${{r.device.toUpperCase()}} · 3 tasks
            </div>
            ${{cards}}
            ${{wlCarbonStrip(_t3, r.model_label + ' · T3 long generation', _t3Dur, _t3SavedG, _subRuns)}}
            <div class="scope-note">${{r.scope}}</div>
        </div>`;
    }}

    function renderLLMAllBoth(r) {{
        const taskLabels = {{'T1':'Short factual','T2':'Medium reasoning','T3':'Long generation'}};
        const winCol = (cpu_val, gpu_val, lower_is_better) => {{
            if (cpu_val == null || gpu_val == null) return ['#ccc','#ccc'];
            const cpuWins = lower_is_better ? cpu_val <= gpu_val : cpu_val >= gpu_val;
            return cpuWins ? ['#00ff99','#888'] : ['#888','#00ff99'];
        }};
        const rows = Object.keys(taskLabels).map(tk => {{
            const cpu = r.cpu[tk] || {{}};
            const gpu = r.gpu[tk] || {{}};
            const ce = cpu.energy || {{}};
            const ge = gpu.energy || {{}};
            const ci = cpu.inference || {{}};
            const gi = gpu.inference || {{}};
            const [cSpeedCol, gSpeedCol] = winCol(ci.tokens_per_sec, gi.tokens_per_sec, false);
            const [cECol, gECol] = winCol(ce.mwh_per_token, ge.mwh_per_token, true);
            return `<tr style="border-bottom:1px solid var(--panel)">
                <td style="padding:0.5rem 0.75rem 0.5rem 0;color:var(--text-3);font-size:0.78rem">${{tk}}<br><span style="font-size:0.7rem;color:var(--text-4)">${{taskLabels[tk]}}</span></td>
                <td style="padding:0.5rem 0.75rem;font-size:0.8rem;color:${{cSpeedCol}}">${{ci.tokens_per_sec ?? '—'}}</td>
                <td style="padding:0.5rem 0.75rem;font-size:0.8rem;color:${{gSpeedCol}}">${{gi.tokens_per_sec ?? '—'}}</td>
                <td style="padding:0.5rem 0.75rem;font-size:0.8rem;color:${{cECol}}">${{ce.mwh_per_token ?? '—'}}</td>
                <td style="padding:0.5rem 0.75rem;font-size:0.8rem;color:${{gECol}}">${{ge.mwh_per_token ?? '—'}}</td>
                <td class="conf-badge" style="padding:0.5rem 0;font-size:0.78rem">${{ce.confidence ? ce.confidence.flag : ''}} ${{ge.confidence ? ge.confidence.flag : ''}}</td>
            </tr>`;
        }}).join('');
        return `<div class="result-box">
            <h2>All Tasks CPU vs GPU — ${{r.model_label}} (${{r.model_params}})</h2>
            <div style="color:var(--text-3);font-size:0.78rem;margin-bottom:1rem">${{r.warm ? '🌡 Warm' : '❄ Cold'}} · 3 tasks × 2 backends</div>
            <table style="width:100%;border-collapse:collapse">
                <thead><tr style="color:var(--text-4);font-size:0.72rem;text-align:left;border-bottom:1px solid var(--border)">
                    <th style="padding:0.4rem 0.75rem 0.4rem 0">Task</th>
                    <th style="padding:0.4rem 0.75rem">CPU tok/s</th>
                    <th style="padding:0.4rem 0.75rem">GPU tok/s</th>
                    <th style="padding:0.4rem 0.75rem">CPU mWh/tok</th>
                    <th style="padding:0.4rem 0.75rem">GPU mWh/tok</th>
                    <th style="padding:0.4rem 0">Conf</th>
                </tr></thead>
                <tbody>${{rows}}</tbody>
            </table>
            <div class="scope-note" style="margin-top:1rem">${{r.scope}}</div>
        </div>`;
    }}

    async function runAllTasks() {{
        const btn = document.getElementById('runAllBtn');
        const runBtn = document.getElementById('runBtn');
        btn.disabled = true;
        runBtn.disabled = true;
        startTime = Date.now();

        const form = new FormData();
        form.append('model_key', selectedModel);
        form.append('warm', selectedWarm ? 'true' : 'false');
        form.append('device', selectedDevice);  // cpu / gpu / both all supported

        try {{
            const resp = await fetch('/llm/run-all', {{method:'POST', body:form}});
            const data = await resp.json();
            if (data.job_id) {{
                renderProgress('T1_baseline');
                pollLLMAll(data.job_id);
            }} else {{
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + JSON.stringify(data) + '</div>';
                btn.disabled = false; runBtn.disabled = false;
            }}
        }} catch(e) {{
            document.getElementById('status').innerHTML =
                '<div style="color:var(--err)">Failed: ' + e + '</div>';
            btn.disabled = false; runBtn.disabled = false;
        }}
    }}

    async function pollLLMAll(jobId) {{
        try {{
            const [resp, powerR] = await Promise.all([
                fetch('/llm/job/' + jobId),
                fetch('/power').catch(() => null),
            ]);
            const data = await resp.json();
            const watts = powerR ? (await powerR.json().catch(()=>({{}}))).watts ?? null : null;
            if (data.status === 'done') {{
                if (streamTimer) {{ clearTimeout(streamTimer); streamTimer = null; }}
                renderLLMResult(data.result, jobId);
                document.getElementById('runBtn').disabled = false;
                document.getElementById('runAllBtn').disabled = false;
            }} else if (data.status === 'error') {{
                if (streamTimer) {{ clearTimeout(streamTimer); streamTimer = null; }}
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + data.error + '</div>';
                document.getElementById('runBtn').disabled = false;
                document.getElementById('runAllBtn').disabled = false;
            }} else if (data.stage === 'queued') {{
                wlRenderQueued(data.queue_position);
                streamTimer = setTimeout(() => pollLLMAll(jobId), 3000);
            }} else {{
                const task = data.current_task || 'T1';
                const dev = data.current_device || '';
                const taskNums = {{'T1':1,'T2':2,'T3':3}};
                const taskNum = taskNums[task] || 1;
                const devBadge = dev ? ' (' + dev.toUpperCase() + ')' : '';
                const taskPips = ['T1','T2','T3'].map(k => {{
                    const s = k === task ? 'active' : taskNums[k] < taskNum ? 'done' : 'pending';
                    const color = s === 'done' ? '#00ff99' : s === 'active' ? '#ffaa00' : '#333';
                    return '<span style="border:1px solid ' + color + ';padding:0.2rem 0.5rem;font-size:0.78rem;color:' + color + '">' + k + '</span>';
                }}).join('');
                wlRenderProgress({{
                    header: 'Running All Tasks \u2014 do not close this tab',
                    stagesHtml: '<div style="display:flex;gap:0.5rem;margin-bottom:0.5rem">' + taskPips + '</div>'
                        + '<div style="color:var(--text-3);font-size:0.8rem;margin-bottom:0.25rem">' + task + devBadge + '</div>',
                    watts: watts,
                    elapsed: startTime ? Date.now() - startTime : null,
                }});
                streamTimer = setTimeout(() => pollLLMAll(jobId), 3000);
            }}
        }} catch(e) {{
            streamTimer = setTimeout(() => pollLLMAll(jobId), 5000);
        }}
    }}

    async function loadPrevRuns() {{
        try {{
            const resp = await fetch('/results/llm/list');
            const runs = await resp.json();
            renderPrevRuns(runs);
        }} catch(e) {{}}
    }}

    function renderPrevRuns(runs) {{
        const el = document.getElementById('prev-runs');
        if (!runs || runs.length === 0) {{
            el.innerHTML = '<div style="color:var(--text-5);font-size:0.8rem">No previous runs.</div>';
            return;
        }}
        const rows = runs.map(r => {{
            const date = r.saved_at ? r.saved_at.slice(0,16).replace('T',' ') : '—';
            const summary = `${{r.model||''}} · ${{r.task||''}} · ${{r.mwh_per_token}} mWh/tok · ${{r.tokens_per_sec}} tok/s ${{r.confidence ? '<span class="conf-badge">'+r.confidence+'</span>' : ''}}`;
            const base = '/results/llm/' + r.job_id;
            const savedAt = r.saved_at || '';
            return `<div style="border-bottom:1px solid var(--panel);padding:0.6rem 0">
                <div style="display:flex;justify-content:space-between;align-items:baseline">
                    <span style="color:var(--text);font-size:0.82rem">${{date}}</span>
                    <span style="color:var(--text-3);font-size:0.75rem;font-family:monospace">${{r.job_id}}</span>
                </div>
                <div style="color:var(--accent);font-size:0.8rem;margin:0.2rem 0">${{summary}}</div>
                <div style="display:flex;gap:0.75rem;margin-top:0.3rem;align-items:center">
                    <a href="javascript:void(0)"
                       onclick="wlExpandPrevRow('llm','${{r.job_id}}','${{savedAt}}')"
                       style="color:var(--text-3);font-size:0.75rem;text-decoration:none;cursor:pointer">
                       <span id="chev-${{r.job_id}}">▸</span> Show full result</a>
                    <a href="${{base}}/download.json" download
                       style="color:var(--text-5);font-size:0.75rem;text-decoration:none">↓ JSON</a>
                    <a href="${{base}}/download.csv" download
                       style="color:var(--text-5);font-size:0.75rem;text-decoration:none">↓ CSV</a>
                </div>
                <div id="expand-${{r.job_id}}" style="display:none;margin-top:0.6rem"></div>
            </div>`;
        }}).join('');
        el.innerHTML = `<div style="color:var(--text-4);font-size:0.72rem;text-transform:uppercase;
            letter-spacing:0.05em;margin-bottom:0.75rem">Previous runs</div>${{rows}}`;
    }}

    loadPrevRuns();
    const _resumeJob = new URLSearchParams(location.search).get('job');
    if (_resumeJob) {{ pollLLM(_resumeJob); }}
    </script>
    {_PROGRESS_JS}
    {_RESULT_JS}
    {_CONF_HELP_WIDGET}
    {_FOOTER}
</body>
</html>""")

@app.post("/llm/run", dependencies=[Depends(requires(LLM_RUN))])
async def llm_run(
    request: Request,
    model_key: str = Form(...),
    task_key: str = Form(...),
    repeats: int = Form(1),
    warm: bool = Form(False),
    prompt: str = Form(None),
    device: str = Form("gpu"),
):
    if model_key not in MODELS:
        return JSONResponse({"error": "Invalid model"}, status_code=400)
    if task_key not in TASKS:
        return JSONResponse({"error": "Invalid task"}, status_code=400)
    if device not in ("cpu", "gpu", "both"):
        return JSONResponse({"error": "device must be cpu, gpu, or both"}, status_code=400)
    if repeats not in (1, 3, 5):
        return JSONResponse({"error": "repeats must be 1, 3, or 5"}, status_code=400)

    effective_prompt = prompt.strip() if prompt and prompt.strip() else None
    # CR-001 capability dispatch: presence of free-form prompt or any
    # multi-run / cross-device request escalates the required capability.
    # Routes never compare tiers; they ask for the capability.
    if effective_prompt is not None:
        gate(request, CUSTOM_PROMPT)
    if repeats > 1 or device == "both":
        gate(request, BATCH_COMPARE)
    job_id = str(uuid.uuid4())[:8]
    device_label = "CPU vs GPU" if device == "both" else device.upper()
    label = f"LLM — {MODELS[model_key]['label']} · {TASKS[task_key]['label']} · {device_label}"

    async def coro():
        await run_llm_job(job_id, model_key, task_key, repeats, warm, effective_prompt, device)

    position = queue_control.enqueue(job_id, "llm", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


async def run_llm_all_job(job_id: str, model_key: str, warm: bool, device: str):
    try:
        devices = ["cpu", "gpu"] if device == "both" else [device]
        jobs[job_id].update({"status": "running", "stage": "baseline",
                             "current_task": "T1", "current_device": devices[0], "partial_response": ""})
        dev_results = {}
        for dev in devices:
            task_results = {}
            for task_key in ["T1", "T2", "T3"]:
                jobs[job_id]["current_task"] = task_key
                jobs[job_id]["current_device"] = dev
                result = await run_llm_measurement(
                    model_key, task_key, jobs, job_id, warm, None, dev)
                task_results[task_key] = result
            dev_results[dev] = task_results

        if device == "both":
            final = {
                "mode": "all_both",
                "model_key": model_key,
                "model_label": MODELS[model_key]["label"],
                "model_params": MODELS[model_key]["params"],
                "warm": warm,
                "device": device,
                "cpu": dev_results["cpu"],
                "gpu": dev_results["gpu"],
                "scope": "Device layer only (GoS1). Network and CPE excluded. No amortised training cost.",
            }
        else:
            final = {
                "mode": "all",
                "model_key": model_key,
                "model_label": MODELS[model_key]["label"],
                "model_params": MODELS[model_key]["params"],
                "warm": warm,
                "device": device,
                "tasks": dev_results[device],
                "scope": "Device layer only (GoS1). Network and CPE excluded. No amortised training cost.",
            }
        save_result("llm", job_id, final)
        jobs[job_id] = {"status": "done", "stage": "done", "result": final}
    except CooldownCancelled:
        jobs[job_id] = {"status": "cancelled", "stage": "cancelled",
                        "error": "Cancelled by operator during cooldown."}
    except Exception as e:
        jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}


@app.post("/llm/run-all", dependencies=[Depends(requires(BATCH_COMPARE))])
async def llm_run_all(
    request: Request,
    model_key: str = Form(...),
    warm: bool = Form(False),
    device: str = Form("gpu"),
):
    if model_key not in MODELS:
        return JSONResponse({"error": "Invalid model"}, status_code=400)
    if device not in ("cpu", "gpu", "both"):
        return JSONResponse({"error": "device must be cpu, gpu, or both"}, status_code=400)

    job_id = str(uuid.uuid4())[:8]
    label = f"LLM All Tasks — {MODELS[model_key]['label']} · {device.upper()}"

    async def coro():
        await run_llm_all_job(job_id, model_key, warm, device)

    position = queue_control.enqueue(job_id, "llm", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


# --- CR-048 · LLM compare-across-models ---
# One prompt × every model in llm.MODELS, graded against a user-supplied
# expected answer, ranked by energy of the correct answers. Headline metric
# is "Wh per correct answer" — mWh/token stays in the table as a supporting
# column because it rewards verbose models and so cannot be the headline.
# Panel = list(MODELS.keys()) so adding/swapping a model in llm.py is
# automatically reflected on /llm/compare without touching this file.

async def run_llm_compare_models_job(job_id: str, prompt: str, expected: str, device: str = "gpu"):
    """Sequentially run prompt across every model in MODELS, grade each, save aggregated result.

    Each model gets its own clean baseline (no cross-model contamination). Grading
    uses llm_grade — substring or leading-integer match, the same rule the
    2026-05-26 probe used to pick these showcase prompts.
    """
    panel = list(MODELS.keys())
    from power import cooldown_between_runs, CooldownCancelled
    from llm import unload_all_loaded_models
    try:
        jobs[job_id].update({
            "status": "running", "stage": "compare_models",
            "total_models": len(panel), "current_model_idx": 0,
            "partial_response": "",
        })
        # Clear any models left over from /llm interactive use before we even
        # measure model #1's baseline — otherwise the "cold reference" we
        # capture is itself contaminated by ~60 W of resident VRAM.
        unloaded = unload_all_loaded_models()
        if unloaded:
            await asyncio.sleep(2)
        rows = []
        floor_reference_w = None  # set after model #1 baseline; used to wait_for_thermal_floor
        cooldowns = []  # diagnostics: how long each inter-model wait took
        for idx, model_key in enumerate(panel, start=1):
            if idx > 1 and floor_reference_w is not None:
                # CRITICAL: unload every previously-run model before waiting.
                # Ollama's default keep_alive holds them in VRAM for ~5 min,
                # which inflates the apparent power floor by ~30-60 W per
                # resident model. Without this the thermal-floor wait can
                # never reach the cold reference and just times out.
                evicted = unload_all_loaded_models()
                jobs[job_id]["stage"] = "cooldown"
                jobs[job_id]["current_model_idx"] = idx
                jobs[job_id]["current_model"] = model_key
                jobs[job_id]["current_model_label"] = MODELS[model_key]["label"]
                # Brief wait for VRAM to actually free (Ollama unload is async).
                if evicted:
                    await asyncio.sleep(3)
                cd = await cooldown_between_runs(
                    fixed_seconds=cfg.load().get("llm_rest_s", 10),
                    reference_w=floor_reference_w,
                    stage="cooldown", jobs=jobs, job_id=job_id,
                    allow_dialog=True,
                )
                cd["evicted_before_wait"] = evicted
                cooldowns.append({"before_model": model_key, **cd})
            jobs[job_id]["current_model_idx"] = idx
            jobs[job_id]["current_model"] = model_key
            jobs[job_id]["current_model_label"] = MODELS[model_key]["label"]
            try:
                m_result = await run_llm_measurement(
                    model_key, "T1",
                    jobs, job_id, warm=False, prompt=prompt, device=device,
                )
                # Capture first model's baseline as the cold-system reference
                # for subsequent thermal-floor waits.
                if floor_reference_w is None:
                    floor_reference_w = (m_result.get("energy") or {}).get("w_base")
                inf = m_result.get("inference") or {}
                en = m_result.get("energy") or {}
                resp = inf.get("response", "") or ""
                ok = llm_grade(expected, resp)
                rows.append({
                    "model_key": model_key,
                    "model_label": MODELS[model_key]["label"],
                    "params": MODELS[model_key]["params"],
                    "response": resp,
                    "output_tokens": inf.get("output_tokens"),
                    "duration_s": inf.get("duration_s"),
                    "tokens_per_sec": inf.get("tokens_per_sec"),
                    "w_base": en.get("w_base"),
                    "w_task": en.get("w_task"),
                    "delta_w": en.get("delta_w"),
                    "delta_e_wh": en.get("delta_e_wh"),
                    "mwh_per_token": en.get("mwh_per_token"),
                    "confidence": en.get("confidence"),
                    "correct": ok,
                })
            except Exception as e:
                rows.append({"model_key": model_key,
                             "model_label": MODELS.get(model_key, {}).get("label", model_key),
                             "params": MODELS.get(model_key, {}).get("params", "?"),
                             "error": str(e), "correct": False})

        correct = [r for r in rows if r.get("correct") and (r.get("delta_e_wh") or 0) > 0]
        cheapest = min(correct, key=lambda r: r["delta_e_wh"]) if correct else None
        final = {
            "mode": "compare_models",
            "prompt": prompt,
            "expected": expected,
            "device": device,
            "models": rows,
            "cheapest_correct_key": cheapest["model_key"] if cheapest else None,
            "panel_pass_rate": round(len(correct) / len(rows), 3) if rows else 0,
            "floor_reference_w": floor_reference_w,
            "cooldowns": cooldowns,
            "scope": "Device layer only (GoS1). Network and CPE excluded. No amortised training cost.",
        }
        save_result("llm", job_id, final)
        jobs[job_id] = {"status": "done", "stage": "done", "result": final}
    except CooldownCancelled:
        jobs[job_id] = {"status": "cancelled", "stage": "cancelled",
                        "error": "Cancelled by operator during cooldown."}
    except Exception as e:
        jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}


@app.post("/llm/compare-models", dependencies=[Depends(requires(BATCH_COMPARE))])
async def llm_compare_models(
    request: Request,
    prompt: str = Form(...),
    expected: str = Form(...),
    device: str = Form("gpu"),
):
    """Member 'Try your own' for the compare-across-models card."""
    prompt = (prompt or "").strip()
    expected = (expected or "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt is required"}, status_code=400)
    if not expected:
        return JSONResponse({"error": "expected answer is required (grading needs ground truth)"},
                            status_code=400)
    if device not in ("cpu", "gpu"):
        return JSONResponse({"error": "device must be cpu or gpu"}, status_code=400)
    if len(prompt) > 2000:
        return JSONResponse({"error": "prompt too long (max 2000 chars)"}, status_code=400)

    job_id = str(uuid.uuid4())[:8]
    label = f"LLM Compare · {prompt[:50]}{'…' if len(prompt) > 50 else ''}"

    async def coro():
        await run_llm_compare_models_job(job_id, prompt, expected, device)

    position = queue_control.enqueue(job_id, "llm", label, coro, request=request,
                                     page="/llm/compare")
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


# Hardcoded showcase data from the 2026-05-26 probe (mean of 3 reps per cell).
# Wh on these cards is *estimated* (wall_s × 25 W / 3600) because the probe
# used direct Ollama API calls rather than the production P110 pipeline.
# Backfilling these three with real P110 runs via /llm/compare-models is a
# follow-up; the page renderer marks the source per row.
# Probe data: /tmp/llm_probe/results_20260526_174852.jsonl
#
# NOTE (2026-05-27 — S30 ladder refresh): the rows below reference the
# PREVIOUS panel — `mistral` (7B) and `gemma3:12b` were retired in favour
# of `qwen3:4b` and `mistral-nemo:12b`. Data preserved as a historical
# snapshot; a re-probe of the new 5-model panel via /llm/compare-models
# is the planned follow-up that will replace this dict.
_LLM_COMPARE_SHOWCASE = {
    't2_count': {
        'label': 'Strawberry (the meme)',
        'prompt': "How many times does the letter R appear in the word 'strawberry'? Output only the number.",
        'expected': '3',
        'tagline': 'The famous LLM-fails-at-letter-counting prompt. Classic tokenization trap.',
        'rows': [
            {'model': 'tinyllama',        'params': '1.1B', 'ok': False, 'ans': 'The program should output the number of occurrences of the letter "R" in the word "strawberry". It can be easily done by using a loop that…', 'tok': 159,  'wall': 1.49,  'wh_measured': -0.0003, 'flag': '🔴'},
            {'model': 'qwen3:1.7b',       'params': '1.7B', 'ok': True,  'ans': 'The word "strawberry" is spelled as: **S-T-R-A-W-B-E-R-R-Y**. \n\nBreaking it down letter by letter:\n- S, T, R, A, W, B, E, R, R, Y.\n\nCountin…',           'tok': 677,  'wall': 6.09,  'wh_measured':  0.1750, 'flag': '🟡'},
            {'model': 'qwen3:4b',         'params': '4B',   'ok': True,  'ans': '3',                                                                                                                                                  'tok': 1509, 'wall': 19.20, 'wh_measured':  1.1452, 'flag': '🟢'},
            {'model': 'qwen3:8b',         'params': '8B',   'ok': True,  'ans': '3',                                                                                                                                                  'tok': 467,  'wall': 11.05, 'wh_measured':  0.5834, 'flag': '🟢'},
            {'model': 'mistral-nemo:12b', 'params': '12B',  'ok': False, 'ans': 'The letter R appears 2 times in the word "strawberry".',                                                                                              'tok': 16,   'wall': 2.73,  'wh_measured':  0.0045, 'flag': '🔴'},
            {'model': 'phi4',             'params': '14B',  'ok': False, 'ans': '2',                                                                                                                                                  'tok': 2,    'wall': 2.15,  'wh_measured':  0.0027, 'flag': '🔴'},
            {'model': 'gpt-oss:20b',      'params': '20B',  'ok': True,  'ans': '3',                                                                                                                                                  'tok': 153,  'wall': 10.28, 'wh_measured':  0.2888, 'flag': '🟢'},
        ],
    },
    't1_logic': {
        'label': 'Logic (Carol)',
        'prompt': 'Alice is older than Bob. Bob is older than Carol. Who is youngest? Answer with one name.',
        'expected': 'Carol',
        'tagline': "All models that pass give the same one-word answer — energy varies, output doesn't.",
        'rows': [
            {'model': 'tinyllama',        'params': '1.1B', 'ok': False, 'ans': 'The youngest person in the given statement is not named, so no single name can be used to identify them. The answer with one name should be…',     'tok': 35,  'wall': 1.04, 'wh_measured':  0.0000, 'flag': '🔴'},
            {'model': 'qwen3:1.7b',       'params': '1.7B', 'ok': True,  'ans': 'Carol is the youngest. \n\n**Step-by-Step Explanation:**\n1. **Given Relationships:**\n   - Alice > Bob (Alice is older than Bob)\n   - Bob > Ca…',  'tok': 391, 'wall': 4.10, 'wh_measured':  0.0507, 'flag': '🟡'},
            {'model': 'qwen3:4b',         'params': '4B',   'ok': True,  'ans': 'Carol',                                                                                                                                            'tok': 717, 'wall': 10.00,'wh_measured':  0.4993, 'flag': '🟢'},
            {'model': 'qwen3:8b',         'params': '8B',   'ok': True,  'ans': 'Carol',                                                                                                                                            'tok': 200, 'wall': 6.25, 'wh_measured':  0.1739, 'flag': '🟡'},
            {'model': 'mistral-nemo:12b', 'params': '12B',  'ok': True,  'ans': 'Carol',                                                                                                                                            'tok': 3,   'wall': 2.34, 'wh_measured':  0.0066, 'flag': '🔴'},
            {'model': 'phi4',             'params': '14B',  'ok': True,  'ans': 'Carol is the youngest. Given that Alice is older than Bob and Bob is older than Carol, it follows that Carol is younger than both Alice and…',    'tok': 39,  'wall': 3.13, 'wh_measured':  0.0163, 'flag': '🔴'},
            {'model': 'gpt-oss:20b',      'params': '20B',  'ok': True,  'ans': 'Carol',                                                                                                                                            'tok': 44,  'wall': 7.30, 'wh_measured':  0.1320, 'flag': '🟡'},
        ],
    },
    't1_addition': {
        'label': 'Addition (50)',
        'prompt': 'What is 25 + 17 + 8? Output only the number.',
        'expected': '50',
        'tagline': "Three-term addition. Most models do it; some can't.",
        'rows': [
            {'model': 'tinyllama',        'params': '1.1B', 'ok': False, 'ans': 'The input string "25 + 17 + 8" is not understood by this program. Please try again or use different inputs to get a correct output.', 'tok': 35,  'wall': 1.03, 'wh_measured': -0.0016, 'flag': '🔴'},
            {'model': 'qwen3:1.7b',       'params': '1.7B', 'ok': True,  'ans': '50',                                                                                                                                  'tok': 295, 'wall': 3.44, 'wh_measured':  0.0463, 'flag': '🟡'},
            {'model': 'qwen3:4b',         'params': '4B',   'ok': True,  'ans': '50',                                                                                                                                  'tok': 583, 'wall': 8.39, 'wh_measured':  0.3507, 'flag': '🟡'},
            {'model': 'qwen3:8b',         'params': '8B',   'ok': True,  'ans': '50',                                                                                                                                  'tok': 295, 'wall': 7.92, 'wh_measured':  0.3098, 'flag': '🟡'},
            {'model': 'mistral-nemo:12b', 'params': '12B',  'ok': False, 'ans': '40',                                                                                                                                  'tok': 3,   'wall': 2.36, 'wh_measured':  0.0033, 'flag': '🔴'},
            {'model': 'phi4',             'params': '14B',  'ok': True,  'ans': '50',                                                                                                                                  'tok': 2,   'wall': 2.12, 'wh_measured':  0.0012, 'flag': '🔴'},
            {'model': 'gpt-oss:20b',      'params': '20B',  'ok': True,  'ans': '50',                                                                                                                                  'tok': 59,  'wall': 7.27, 'wh_measured':  0.1329, 'flag': '🟡'},
        ],
    },
}


@app.get("/llm/compare", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def llm_compare_page(request: Request):
    """Hybrid showcase + member 'Try your own' for energy-per-correct-answer.

    Anonymous: three hardcoded demo cards (probe data, estimated Wh).
    Member (BATCH_COMPARE): textarea + expected-answer input → runs on all 5
    models sequentially with P110 measurement, renders into the same card.
    """
    can_batch = can(audience.tier(request), BATCH_COMPARE)
    lk_batch_class = _lock_class(request, BATCH_COMPARE)
    lk_batch_badge = _lock_badge_html(request, BATCH_COMPARE,
                                      "Try your own prompt — Members only")
    dis_batch = _disabled_attr(request, BATCH_COMPARE)

    import json as _json
    showcase_js = _json.dumps(_LLM_COMPARE_SHOWCASE)
    panel_n     = len(MODELS)
    panel_list  = " &middot; ".join(f"{m['label']} ({m['params']})" for m in MODELS.values())
    # JS array of params strings, ordered by size — drives the bust-card
    # "bigger-was-wrong" detection. Derived from MODELS so adding a model
    # in llm.py extends this without an edit here.
    size_order_js = _json.dumps([m["params"] for m in MODELS.values()])

    return _bake_durations(f"""<!DOCTYPE html>
<html>
<head>
    <link rel="icon" type="image/svg+xml" href="/static/owl.svg">
    <title>OWL — LLM · Compare across models</title>
    <script src="{CHARTJS_URL}"></script>
    <script src="/static/wl-charts.js"></script>
    <style>
        *{{box-sizing:border-box;margin:0;padding:0}}
        body{{font-family:monospace;background:var(--bg);color:var(--text);
              max-width:920px;margin:0 auto;padding:2rem}}
        h1{{color:var(--accent);font-size:1.6rem;margin-bottom:0.25rem}}
        .subtitle{{color:var(--text-3);font-size:0.8rem;margin-bottom:1.5rem}}
        .demo-tabs{{display:flex;gap:0.5rem;margin-bottom:1.25rem;flex-wrap:wrap}}
        .demo-tabs button{{background:none;color:var(--text-3);border:1px solid var(--border-3);
                           padding:0.5rem 0.9rem;cursor:pointer;font-family:monospace;font-size:0.78rem;margin:0}}
        .demo-tabs button:hover{{border-color:var(--accent);color:var(--text)}}
        .demo-tabs button.active{{border-color:var(--accent);color:var(--accent);background:var(--accent-soft)}}
        .prompt-card{{border:1px solid var(--border);padding:1rem 1.25rem;margin-bottom:1.25rem;
                      background:var(--panel-2)}}
        .label-sm{{color:var(--text-5);font-size:0.65rem;text-transform:uppercase;
                   letter-spacing:0.06em;margin-bottom:0.5rem}}
        .prompt-text{{color:var(--text-2);font-size:0.95rem;line-height:1.5}}
        .prompt-meta{{margin-top:0.6rem;color:var(--text-3);font-size:0.78rem}}
        .prompt-meta b{{color:var(--accent)}}
        .hero{{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1.25rem}}
        @media(max-width:640px){{.hero{{grid-template-columns:1fr}}}}
        .hero-card{{border:1px solid var(--border);padding:1.1rem;background:var(--panel-2)}}
        .hero-card .big{{color:var(--accent);font-size:2rem;font-weight:bold;line-height:1.1}}
        .hero-card .sub{{color:var(--text-3);font-size:0.78rem;margin-top:0.4rem;line-height:1.5}}
        .hero-card.warn .big{{color:var(--warn);font-size:1rem;line-height:1.4}}
        .hero-card.warn{{border-color:var(--warn)}}
        table{{width:100%;border-collapse:collapse;font-size:0.8rem;margin-bottom:1.25rem}}
        th{{text-align:left;padding:0.5rem 0.6rem;color:var(--text-4);
            border-bottom:1px solid var(--border-3);font-weight:normal;
            text-transform:uppercase;letter-spacing:0.05em;font-size:0.68rem}}
        th.num,td.num{{text-align:right;font-variant-numeric:tabular-nums}}
        td{{padding:0.6rem;border-bottom:1px solid var(--border-2);vertical-align:middle}}
        tr.correct td.model,tr.correct td.answer{{color:var(--text)}}
        tr.wrong td.model,tr.wrong td.answer{{color:var(--text-4)}}
        tr.noisy td{{color:var(--text-4)!important}}
        tr.noisy td.model{{color:var(--text-3)!important;font-style:italic}}
        tr.noisy{{background:transparent!important}}
        td.answer{{max-width:340px}}
        .answer-wrap{{max-height:5.5em;overflow-y:auto;white-space:pre-wrap;word-break:break-word;
                      line-height:1.45;padding-right:0.25rem;scrollbar-width:thin;
                      scrollbar-color:var(--border-3) transparent}}
        .answer-wrap::-webkit-scrollbar{{width:6px}}
        .answer-wrap::-webkit-scrollbar-thumb{{background:var(--border-3);border-radius:3px}}
        tr.cheapest{{background:var(--accent-soft)}}
        tr.cheapest td.model{{color:var(--accent);font-weight:bold}}
        .pill{{display:inline-block;font-size:0.7rem;padding:0.1rem 0.45rem;border-radius:2px}}
        .pill.ok{{color:var(--accent);border:1px solid var(--accent)}}
        .pill.bad{{color:var(--err);border:1px solid var(--err)}}
        .answer-q{{color:var(--text-3);font-style:italic}}
        .crown{{color:var(--accent)}}
        .ratio{{color:var(--accent);font-weight:bold}}
        .headline{{border-left:3px solid var(--accent);padding:0.9rem 1.1rem;margin-bottom:1.5rem;
                   background:var(--panel-2);color:var(--text-2);line-height:1.7;font-size:0.88rem}}
        .headline b{{color:var(--accent)}}
        .try{{margin-top:2rem;padding-top:1.5rem;border-top:1px solid var(--border)}}
        .try h2{{color:var(--accent);font-size:1.05rem;margin-bottom:0.4rem}}
        .try .desc{{color:var(--text-3);font-size:0.82rem;margin-bottom:1rem;line-height:1.6}}
        textarea,input[type=text]{{width:100%;background:#0f0f0f;border:1px solid var(--border-3);
                                    border-left:2px solid #00ff9966;color:var(--text-2);
                                    font-family:monospace;font-size:0.85rem;padding:0.75rem;
                                    resize:vertical}}
        textarea:focus,input[type=text]:focus{{border-color:var(--accent);outline:none}}
        button.run{{background:var(--accent);color:#000;border:none;padding:0.75rem 2rem;
                    cursor:pointer;font-family:monospace;font-size:0.95rem;margin-top:0.85rem}}
        button.run:disabled{{background:var(--border);color:var(--text-3);cursor:not-allowed}}
        button.run:hover:not(:disabled){{background:var(--accent-hover)}}
        a.back{{color:var(--text-3);text-decoration:none;font-size:0.82rem;
                display:inline-block;margin-top:2rem}}
        a.back:hover{{color:var(--accent)}}
        details{{margin-top:1.5rem;color:var(--text-3);font-size:0.78rem;
                 border-top:1px solid var(--border);padding-top:1rem}}
        summary{{cursor:pointer;color:var(--text-3)}}
        summary:hover{{color:var(--accent)}}
        details p{{margin-top:0.5rem;line-height:1.6}}
        {_LOCK_STYLES}
    </style>
</head>
<body>
    {_BACK}<a href="/llm" style="color:var(--text-3);text-decoration:none;font-size:0.82rem;
        margin-left:0.75rem;margin-bottom:1.5rem;display:inline-block;
        vertical-align:middle;position:relative;top:-2px;transition:color 0.2s"
        onmouseover="this.style.color='#00ff99'" onmouseout="this.style.color='#777'">&larr; /llm</a>
    <h1>LLM &middot; Compare across models</h1>
    <div class="subtitle">Energy cost of correct answers. Device layer only (GoS1). Network and CPE excluded.</div>

    <div class="demo-tabs" id="tabs"></div>

    <div class="prompt-card">
        <div class="label-sm">Prompt</div>
        <div class="prompt-text" id="prompt-text"></div>
        <div class="prompt-meta">Expected: <b id="expected"></b> &middot; Panel: 5 models, mean of 3 reps each (2026-05-26 probe)</div>
    </div>

    <div class="hero">
        <div class="hero-card" id="hero-cheap">
            <div class="label-sm">Cheapest correct answer</div>
            <div class="big" id="hero-cheap-big"></div>
            <div class="sub" id="hero-cheap-sub"></div>
        </div>
        <div class="hero-card warn" id="hero-bust">
            <div class="label-sm">The size &ne; smarts finding</div>
            <div class="big" id="hero-bust-big"></div>
            <div class="sub" id="hero-bust-sub"></div>
        </div>
    </div>

    <div class="label-sm">Same prompt, all models &mdash; ranked by energy of a correct answer</div>
    <table>
        <thead>
            <tr><th>model</th><th>answer</th><th>&#10003;/&#10007;</th><th>conf</th>
                <th class="num">tokens</th><th class="num">wall</th>
                <th class="num">mWh/tok</th><th class="num">Wh</th>
                <th class="num">vs best</th></tr>
        </thead>
        <tbody id="rows"></tbody>
    </table>

    <div class="headline" id="headline"></div>

    <div id="charts-wrap" style="margin-bottom:1.5rem;display:none">
        <div class="label-sm">Energy vs model size (correct answers only) <span id="charts-source" style="color:var(--text-5)"></span></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
            <div style="border:1px solid var(--border);padding:0.75rem;background:var(--panel-2)">
                <div style="color:var(--text-3);font-size:0.7rem;text-align:center;margin-bottom:0.25rem">Total Wh per correct answer</div>
                <div style="position:relative;height:240px"><canvas id="chart-wh"></canvas></div>
            </div>
            <div style="border:1px solid var(--border);padding:0.75rem;background:var(--panel-2)">
                <div style="color:var(--text-3);font-size:0.7rem;text-align:center;margin-bottom:0.25rem">mWh per output token</div>
                <div style="position:relative;height:240px"><canvas id="chart-mwh"></canvas></div>
            </div>
        </div>
        <div id="charts-note" style="color:var(--text-5);font-size:0.72rem;margin-top:0.5rem;line-height:1.5"></div>
    </div>
    <div id="charts-hint" style="margin-bottom:1.5rem;color:var(--text-5);font-size:0.78rem;
         border-left:2px solid var(--border);padding-left:0.85rem;display:none">
        Energy-vs-size plot appears when at least 3 models answer correctly.
    </div>

    {lk_batch_badge}
    <div class="try {lk_batch_class}">
        <h2>Try your own prompt</h2>
        <div class="desc">
            Runs your prompt across all {panel_n} models sequentially with P110 power measurement.
            Each model gets its own clean baseline. Between models the runner actively polls power and waits for the system to return to within &plusmn;3 W of model #1's baseline (max 120 s cap) so heat from a verbose model can't contaminate the next reading. Total wall time depends on how hot each model leaves the GPU.
        </div>
        <div class="label-sm">Prompt</div>
        <textarea id="userPrompt" rows="3"{dis_batch}
            placeholder="e.g. What is 47 multiplied by 83? Output only the number."></textarea>
        <div class="label-sm" style="margin-top:0.85rem">Expected answer (used to grade &#10003;/&#10007;)</div>
        <input type="text" id="userExpected"{dis_batch}
            placeholder="e.g. 3901">
        <div class="label-sm" style="margin-top:0.5rem;color:var(--text-5)">
            Substring match, case-insensitive. For numeric answers, leading-integer match.
        </div>
        <button class="run" id="runBtn" onclick="runCompare()"{dis_batch}>Run on all {panel_n} models &rarr;</button>
        <div id="run-status" style="margin-top:1.25rem"></div>
    </div>

    <details>
        <summary>Methodology &amp; scope</summary>
        <p><b>What's measured (live runs):</b> {meter_display_name()} wall-power at 1 Hz, baseline before each model (10 polls), &Delta;W &times; &Delta;t &rarr; Wh, mWh/output_token, Traffic Light Confidence per the CR-028 CI model. Same protocol as the existing /llm endpoint.</p>
        <p><b>What's estimated (showcase cards):</b> Wh = wall_s &times; 25 W / 3600. The 25 W figure is a rough average power delta observed on GoS1 across Ollama 1B&ndash;20B models. Production P110 backfill of the three showcase cards is a follow-up (CR-048 phase 2).</p>
        <p><b>Why "Wh per correct answer" is the headline:</b> mWh/token rewards verbose models &mdash; a model that "thinks out loud" for 100 tokens to reach a 1-token answer looks more efficient per token than a model that answers in 1 token, even though it burned 100&times; the energy. The headline metric is the energy cost of <em>correctness</em>. mWh/token stays as a supporting column because it's the canonical inference-cost figure operators recognise.</p>
        <p><b>{panel_n}-model panel:</b> {panel_list}. All on GoS1 (Ryzen 9 7900 + RX 7800 XT, Ollama 0.20.2). Panel reflects the current <code>llm.MODELS</code> dict; the showcase tabs are frozen on the older 5-model probe and will be re-baselined when a fresh probe of the new panel runs.</p>
        <p><b>Grading:</b> Tolerant &mdash; substring match (case-insensitive) or leading-integer match. Same rule used by the 2026-05-26 probe to select these prompts.</p>
    </details>

    <a class="back" href="/llm">&larr; /llm (single-model lab)</a>

    <script>
    const SHOWCASE = {showcase_js};
    const CAN_BATCH = {('true' if can_batch else 'false')};
    const wh = w => Math.round((w * 25 / 3600) * 10000) / 10000;
    let pollTimer = null;
    let chartWh = null, chartMwh = null;
    // CR-050 follow-up — local ticker so the cooldown counter feels smooth
    // even though the server-side poll only writes a fresh cooldown_waited_s
    // every 1 s and the UI only polls /job/{id} every 2 s.
    let cooldownTicker = null;
    let cooldownState = null;
    let cooldownLog = [];   // finished inter-model waits, persisted across stages

    function stopCooldownTicker() {{
        if (cooldownTicker) {{ clearInterval(cooldownTicker); cooldownTicker = null; }}
        cooldownState = null;
    }}

    function renderRunStatus() {{
        const s = cooldownState;
        if (!s) return;
        const msg = s.stage === 'queued'
            ? 'In queue (position ' + (s.qpos || '?') + ')…'
            : (s.mi && s.mt
                ? 'Model ' + s.mi + '/' + s.mt + (s.ml ? ' — ' + s.ml : '') + ' · ' + s.stage
                : 'Running… ' + s.stage);
        const watts = s.watts != null ? ' · ' + Number(s.watts).toFixed(1) + ' W' : '';
        let cdInfo = '';
        if (s.stage === 'cooldown' && s.cdWaited != null) {{
            const liveS = s.cdWaited + (Date.now() - s.cdLocalStart) / 1000;
            const ref = s.cdRef != null ? Number(s.cdRef).toFixed(1) + 'W' : '?';
            cdInfo = ' · waiting ' + liveS.toFixed(1) + 's for floor (target ≤ ' + ref + ' +3W)';
        }}
        let logInfo = '';
        if (cooldownLog.length) {{
            logInfo = '<div style="color:var(--text-4);font-size:0.72rem;margin-top:0.25rem">'
                    + '⏳ Cooldowns done: '
                    + cooldownLog.map(function(w) {{ return Number(w).toFixed(0) + 's'; }}).join(' · ')
                    + '</div>';
        }}
        const el = document.getElementById('run-status');
        if (el) el.innerHTML =
            '<div style="color:var(--warn);font-size:0.85rem">' + msg + watts + cdInfo + '</div>' + logInfo;
    }}

    function paramsToNumeric(p) {{
        // "1.1B" -> 1.1, "12B" -> 12, "20B" -> 20
        return parseFloat(String(p).replace(/[^\\d.]/g, '')) || 0;
    }}

    function renderCharts(payload) {{
        const wrap = document.getElementById('charts-wrap');
        const hint = document.getElementById('charts-hint');
        const TRUSTED = new Set(['🟢','🟡']);
        // Plot only ✓ AND not 🔴 AND positive Wh — same filter the
        // 'cheapest correct' card uses; we don't want noisy points
        // distorting the energy-vs-size curve.
        const correct = payload.rows.filter(r => r.ok && TRUSTED.has(r.flag || '🟢') && r.whEst > 0);
        if (correct.length < 3) {{
            wrap.style.display = 'none';
            hint.style.display = '';
            if (chartWh) {{ chartWh.destroy(); chartWh = null; }}
            if (chartMwh) {{ chartMwh.destroy(); chartMwh = null; }}
            return;
        }}
        hint.style.display = 'none';
        wrap.style.display = '';

        document.getElementById('charts-source').textContent = '· ' + payload.sourceLabel;
        const wrong = payload.rows.filter(r => !r.ok);
        const noteParts = ['Plotting ' + correct.length + ' of ' + payload.rows.length + ' models that produced the correct answer.'];
        if (wrong.length) {{
            noteParts.push((wrong.length === 1 ? '1 model' : wrong.length + ' models') +
                           ' excluded for incorrect answers (' +
                           wrong.map(r => r.model.replace(':latest','')).join(', ') + ').');
        }}
        if ((payload.sourceLabel || '').toLowerCase().indexOf('estimated') >= 0) {{
            noteParts.push('Wh here is estimated from wall_s × ~25 W; live runs use direct P110 measurement.');
        }}
        document.getElementById('charts-note').textContent = noteParts.join(' ');

        const sorted = [...correct].sort((a,b) => paramsToNumeric(a.params) - paramsToNumeric(b.params));
        const whPoints = sorted.map(r => ({{x: paramsToNumeric(r.params), y: r.whEst}}));
        const mwhPoints = sorted.map(r => {{
            const tok = r.tok || 0;
            return {{x: paramsToNumeric(r.params), y: tok > 0 ? (r.whEst * 1000 / tok) : 0}};
        }});

        if (chartWh) {{ chartWh.destroy(); chartWh = null; }}
        chartWh = WlCharts.line({{
            canvas: document.getElementById('chart-wh'),
            datasets: [{{label: 'Wh per correct answer', points: whPoints, color: 'accent', tension: 0.15, pointRadius: 5}}],
            xLabel: 'parameters (B)', yLabel: 'Wh', yUnit: 'Wh',
        }});

        if (chartMwh) {{ chartMwh.destroy(); chartMwh = null; }}
        chartMwh = WlCharts.line({{
            canvas: document.getElementById('chart-mwh'),
            datasets: [{{label: 'mWh per output token', points: mwhPoints, color: 'warn', tension: 0.15, pointRadius: 5}}],
            xLabel: 'parameters (B)', yLabel: 'mWh/tok', yUnit: 'mWh/tok',
        }});
    }}

    const tabs = document.getElementById('tabs');
    const order = ['t2_count','t1_logic','t1_addition'];
    order.forEach(k => {{
        const b = document.createElement('button');
        b.textContent = SHOWCASE[k].label;
        b.id = 'tab-' + k;
        b.onclick = () => renderShowcase(k);
        tabs.appendChild(b);
    }});

    function renderShowcase(key) {{
        const d = SHOWCASE[key];
        order.forEach(k => document.getElementById('tab-'+k).classList.toggle('active', k === key));
        // Prefer per-row wh_measured (real P110 from showcase regeneration);
        // fall back to wall × 25 W estimate if a legacy row lacks it.
        const rows = d.rows.map(r => ({{...r, whEst: (r.wh_measured != null ? r.wh_measured : wh(r.wall))}}));
        renderCompareCard({{
            promptText: d.prompt, expected: d.expected,
            rows: rows, tagline: d.tagline, sourceLabel: 'Showcase (estimated)'
        }});
    }}

    function renderCompareCard(payload) {{
        document.getElementById('prompt-text').textContent = payload.promptText;
        document.getElementById('expected').textContent = payload.expected;

        const TRUSTED = new Set(['🟢','🟡']);
        const isTrust = r => TRUSTED.has(r.flag || '🟢');
        const correct = payload.rows.filter(r => r.ok).sort((a,b) => a.whEst - b.whEst);
        const wrong   = payload.rows.filter(r => !r.ok).sort((a,b) => a.whEst - b.whEst);
        const sorted  = [...correct, ...wrong];
        // 🔴 rows are visible in the table but excluded from the cheapest-correct
        // pick, the bust-card pick, and the chart — their delta_w sits inside the
        // baseline noise so a tiny Wh is just measurement noise, not efficiency.
        const trustedCorrect = correct.filter(r => isTrust(r) && r.whEst > 0);
        const cheapest = trustedCorrect[0] || null;

        if (cheapest) {{
            document.getElementById('hero-cheap-big').textContent = cheapest.whEst.toFixed(4) + ' Wh';
            document.getElementById('hero-cheap-sub').innerHTML =
                '<b style="color:var(--accent)">' + cheapest.model.replace(':latest','') + '</b> &middot; ' +
                cheapest.params + ' &middot; ' + cheapest.tok + ' tokens &middot; ' + cheapest.wall.toFixed(2) + 's';
        }} else {{
            document.getElementById('hero-cheap-big').textContent = '—';
            document.getElementById('hero-cheap-sub').textContent = 'No model in the panel got it right.';
        }}

        const sizeOrder = {size_order_js};
        const sIdx = p => sizeOrder.indexOf(p);
        let bustHead = '', bustDetail = '';
        const biggerWrong = payload.rows.filter(r => !r.ok && cheapest && sIdx(r.params) > sIdx(cheapest.params));
        if (biggerWrong.length) {{
            const bw = biggerWrong[biggerWrong.length-1];
            bustHead = bw.model.replace(':latest','') + ' (' + bw.params + ') was wrong; ' +
                       cheapest.model.replace(':latest','') + ' (' + cheapest.params + ') was right';
            bustDetail = 'A larger model (' + bw.params + ') failed at this prompt while a smaller one (' + cheapest.params + ') succeeded. More parameters did not buy more intelligence here.';
        }} else if (cheapest && trustedCorrect.length > 1) {{
            const priciest = trustedCorrect[trustedCorrect.length-1];
            const ratio = (priciest.whEst / cheapest.whEst).toFixed(1);
            bustHead = 'Same answer, ' + ratio + '&times; more energy';
            bustDetail = priciest.model.replace(':latest','') + ' (' + priciest.params + ') and ' + cheapest.model.replace(':latest','') + ' (' + cheapest.params + ') both answered correctly &mdash; but the larger model used ' + ratio + '&times; the energy for the identical output.';
        }} else {{
            bustHead = 'No size-vs-smarts split on this prompt';
            bustDetail = payload.tagline || '';
        }}
        document.getElementById('hero-bust-big').innerHTML = bustHead;
        document.getElementById('hero-bust-sub').innerHTML = bustDetail;

        const tbody = document.getElementById('rows');
        tbody.innerHTML = '';
        sorted.forEach(r => {{
            const tr = document.createElement('tr');
            const flag = r.flag || '🟢';
            const trusted = isTrust(r);
            tr.className = r.ok ? (trusted ? 'correct' : 'correct noisy') : 'wrong';
            if (r === cheapest) tr.classList.add('cheapest');
            // 🔴 rows: hide the ratio (it would compare noise to signal)
            const ratio = r.ok && trusted && cheapest ? (r.whEst / cheapest.whEst).toFixed(1) + '&times;' :
                          (r.ok && !trusted ? '<span title="noisy reading, see conf column">&mdash;</span>' : '&mdash;');
            const crown = (r === cheapest) ? ' <span class="crown">&#9733;</span>' : '';
            // A negative mWh/token means the task drew below the measured idle
            // floor — a sign-flipped noise artifact on a sub-floor model, and
            // always a 🔴 row. Show an em-dash (with a hover note) instead of a
            // misleading negative; the confidence column already carries the 🔴.
            const mwhTok = (r.tok > 0 && r.whEst > 0)
                ? (r.whEst * 1000 / r.tok).toFixed(2)
                : (r.whEst <= 0
                    ? '<span title="energy below measurement floor — not distinguishable from idle">&mdash;</span>'
                    : '&mdash;');
            tr.innerHTML =
                '<td class="model">' + escapeHTML(r.model.replace(':latest','')) +
                  ' <span style="color:var(--text-5);font-size:0.7rem">(' + r.params + ')</span>' + crown + '</td>' +
                '<td class="answer ' + (r.ok ? '' : 'answer-q') + '"><div class="answer-wrap">' + escapeHTML(String(r.ans)) + '</div></td>' +
                '<td>' + (r.ok ? '<span class="pill ok">&#10003;</span>' : '<span class="pill bad">&#10007;</span>') + '</td>' +
                '<td title="Traffic Light Confidence (CR-028) — 🟢 repeatable, 🟡 weak, 🔴 unreliable / contamination">' + flag + '</td>' +
                '<td class="num">' + (r.tok != null ? r.tok : '&mdash;') + '</td>' +
                '<td class="num">' + (r.wall != null ? r.wall.toFixed(2) + 's' : '&mdash;') + '</td>' +
                '<td class="num" style="color:var(--text-4)">' + mwhTok + '</td>' +
                '<td class="num">' + r.whEst.toFixed(4) + '</td>' +
                '<td class="num">' + ratio + '</td>';
            tbody.appendChild(tr);
        }});

        let h = '';
        if (cheapest) {{
            h = '<b>' + cheapest.model.replace(':latest','') + ' (' + cheapest.params + ')</b>' +
                ' produced the correct answer for <b>' + cheapest.whEst.toFixed(4) + ' Wh</b>.';
            if (trustedCorrect.length > 1) {{
                const priciest = trustedCorrect[trustedCorrect.length-1];
                const ratio = (priciest.whEst / cheapest.whEst).toFixed(1);
                h += ' The most expensive correct run (' + priciest.model.replace(':latest','') + ') used <span class="ratio">' + ratio + '&times; more energy</span> for the same answer.';
            }}
        }} else {{
            h = 'No model in the panel got this prompt right at all &mdash; try a different prompt or look at the showcase examples.';
        }}
        document.getElementById('headline').innerHTML =
            '<div class="label-sm">What this tells you</div>' + h +
            ' <span style="color:var(--text-5)">[' + payload.sourceLabel + ']</span>';

        renderCharts(payload);
    }}

    function escapeHTML(s) {{
        return String(s).replace(/[&<>"']/g, c => ({{
            '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
        }}[c]));
    }}

    async function runCompare() {{
        if (!CAN_BATCH) return;
        stopCooldownTicker();
        const prompt = document.getElementById('userPrompt').value.trim();
        const expected = document.getElementById('userExpected').value.trim();
        if (!prompt || !expected) {{
            document.getElementById('run-status').innerHTML =
                '<div style="color:var(--err);font-size:0.85rem">Both prompt and expected answer are required.</div>';
            return;
        }}
        const btn = document.getElementById('runBtn');
        btn.disabled = true;
        document.getElementById('run-status').innerHTML =
            '<div style="color:var(--warn);font-size:0.85rem">Queued &mdash; running across {panel_n} models with active-probe thermal floor wait between each&hellip;</div>';
        const form = new FormData();
        form.append('prompt', prompt);
        form.append('expected', expected);
        form.append('device', 'gpu');
        try {{
            const resp = await fetch('/llm/compare-models', {{method:'POST', body:form}});
            const data = await resp.json();
            if (data.job_id) {{
                pollCompare(data.job_id);
            }} else {{
                document.getElementById('run-status').innerHTML =
                    '<div style="color:var(--err)">' + (data.error || 'Error') + '</div>';
                btn.disabled = false;
            }}
        }} catch(e) {{
            document.getElementById('run-status').innerHTML =
                '<div style="color:var(--err)">Failed: ' + e + '</div>';
            btn.disabled = false;
        }}
    }}

    async function pollCompare(jobId) {{
        try {{
            const resp = await fetch('/llm/job/' + jobId);
            const data = await resp.json();
            if (data.status === 'done' && data.result) {{
                stopCooldownTicker();
                const r = data.result;
                const rows = (r.models || []).map(m => ({{
                    model: m.model_key, params: m.params, ok: !!m.correct,
                    ans: m.error ? '(error: ' + m.error + ')' : (m.response || '(empty)'),
                    tok: m.output_tokens || 0,
                    wall: m.duration_s || 0,
                    whEst: m.delta_e_wh || 0,
                    flag: (m.confidence || {{}}).flag || '🟢',
                }}));
                renderCompareCard({{
                    promptText: r.prompt, expected: r.expected,
                    rows: rows, tagline: '', sourceLabel: 'Live (P110 measured)'
                }});
                document.getElementById('run-status').innerHTML =
                    '<div style="color:var(--accent);font-size:0.85rem">&#10003; Done. Result rendered above. ' +
                    '<a href="/results/llm/' + jobId + '/download.json" style="color:var(--accent)">&darr; JSON</a></div>'
                    + wlCooldownSummary(r.cooldowns);
                document.getElementById('runBtn').disabled = false;
                document.querySelector('.prompt-card').scrollIntoView({{behavior:'smooth', block:'start'}});
            }} else if (data.status === 'error') {{
                stopCooldownTicker();
                document.getElementById('run-status').innerHTML =
                    '<div style="color:var(--err);font-size:0.85rem">Error: ' + (data.error || 'unknown') + '</div>';
                document.getElementById('runBtn').disabled = false;
            }} else {{
                const stage = data.stage || 'queued';
                if (stage === 'awaiting_cooldown_decision') {{
                    wlCooldownDialog(jobId, data.cooldown_decision_options);
                }} else {{ wlCooldownDialogClose(); }}
                const cdVal = data.cooldown_waited_s;
                const prev = cooldownState;
                const cdChanged = !prev || prev.cdWaited !== cdVal;
                // Reset the log at run start (model 1 / queued); record a finished
                // wait each time we leave the 'cooldown' stage so it persists.
                if (!data.current_model_idx || data.current_model_idx <= 1) cooldownLog = [];
                if (prev && prev.stage === 'cooldown' && stage !== 'cooldown' && prev.cdWaited != null) {{
                    cooldownLog.push(prev.cdWaited);
                }}
                cooldownState = {{
                    stage: stage,
                    qpos:  data.queue_position,
                    mi:    data.current_model_idx,
                    mt:    data.total_models,
                    ml:    data.current_model_label,
                    watts: data.watts,
                    cdWaited: cdVal,
                    cdRef:    data.cooldown_reference_w,
                    cdLocalStart: cdChanged ? Date.now() : (prev ? prev.cdLocalStart : Date.now()),
                }};
                // Start/stop the local 4 Hz ticker based on current stage,
                // so the displayed "waiting Xs" advances smoothly between
                // the server's 1 s P110 polls and the UI's 2 s job polls.
                if (stage === 'cooldown') {{
                    if (!cooldownTicker) cooldownTicker = setInterval(renderRunStatus, 250);
                }} else if (cooldownTicker) {{
                    clearInterval(cooldownTicker); cooldownTicker = null;
                }}
                renderRunStatus();
                pollTimer = setTimeout(() => pollCompare(jobId), 2000);
            }}
        }} catch(e) {{
            pollTimer = setTimeout(() => pollCompare(jobId), 4000);
        }}
    }}

    renderShowcase('t2_count');
    // Resume a queued/running compare job (↩ Resume from /queue-status).
    const _resumeJob = new URLSearchParams(location.search).get('job');
    if (_resumeJob) {{ var _rb = document.getElementById('runBtn'); if (_rb) _rb.disabled = true; pollCompare(_resumeJob); }}
    </script>
    {_FOOTER}
</body>
</html>""")


# CR-019 — every job-status response carries the live wall-power reading
# alongside the worker-state fields. The shared `wlRenderProgress` widget
# consumes `data.watts` to drive the big 2.5rem live readout, which is
# the proof-of-reality moment for the visitor on /demo. Injected once
# here so all four job-status endpoints stay symmetric.
def _job_status(job_id: str) -> dict:
    return {**jobs.get(job_id, {"status": "not_found"}),
            "watts": _power_cache["watts"]}


@app.get("/llm/job/{job_id}", dependencies=[Depends(requires(QUEUE_VIEW))])
async def llm_job_status(job_id: str):
    return _job_status(job_id)

@app.get("/video/job/{job_id}", dependencies=[Depends(requires(QUEUE_VIEW))])
async def job_status(job_id: str):
    return _job_status(job_id)

@app.get("/image/job/{job_id}", dependencies=[Depends(requires(QUEUE_VIEW))])
async def image_job_status(job_id: str):
    return _job_status(job_id)

@app.get("/queue", dependencies=[Depends(requires(QUEUE_VIEW))])
async def queue_status_endpoint():
    return queue_control.snapshot()


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
(async function hydrateFindingEmbeds(){
  const els = document.querySelectorAll('.finding-embed');
  const renderers = {
    video: window.wlRenderVideoCard,
    llm: window.wlRenderLLMCard,
    image: window.wlRenderImageCard,
    rag: window.wlRenderRAGCard
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


@app.get("/findings", response_class=HTMLResponse,
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


# ── CR-061 benchmark results view ───────────────────────────────────────────

_BENCH_STATUS_DOT = {"done": "🟢", "running": "🟡", "queued": "⚪",
                     "cancelled": "⚫", "error": "🔴"}

# Hydrate each step embed via the same /results/.../download.json + card
# renderer pattern the /findings embeds use. Dispatch on `kind` (so rag→RAG
# card) but fetch by the result_ref `type` (rag persists under results/llm/).
_BENCH_HYDRATE_JS = f'<script src="/static/wl-bench-hydrate.js?v={_WL_ASSET_V}"></script>'


def _benchmark_rows_html(runs: list) -> str:
    if not runs:
        return ('<p style="color:var(--text-3);font-family:monospace;font-size:0.85rem">'
                'No benchmark runs yet. Launch one from <a href="/settings" '
                'style="color:var(--accent)">/settings</a>.</p>')
    rows = []
    for r in runs:
        bid = r.get("benchmark_run_id") or r.get("job_id")
        status = r.get("status") or "?"
        dot = _BENCH_STATUS_DOT.get(status, "⚪")
        done, total = r.get("n_done", 0), r.get("total_steps", 0)
        err = r.get("n_error", 0)
        when = (r.get("started_at") or r.get("saved_at") or "")[:16].replace("T", " ")
        err_html = (f' · <span style="color:var(--err)">{err} err</span>') if err else ""
        rows.append(
            f'<a class="finding-row" href="/benchmark/{html_lib.escape(bid)}">'
            f'<div class="finding-row-top">'
            f'<span class="finding-row-dot">{dot}</span>'
            f'<span class="finding-row-headline">Benchmark {html_lib.escape(bid)} · '
            f'{html_lib.escape(status)}</span>'
            f'<span class="finding-row-date">{html_lib.escape(when)}</span></div>'
            f'<div class="finding-row-claim">{done}/{total} steps done{err_html}</div></a>'
        )
    return "".join(rows)


@app.get("/benchmark", response_class=HTMLResponse,
         dependencies=[Depends(requires(BENCHMARK_VIEW))])
async def benchmark_list_page():
    runs = list_results("benchmark", limit=50, visitor_key=None)
    body = (
        '<div class="finding-wrap">'
        '<h1 style="font-size:1.2rem;color:var(--text)">Benchmark runs</h1>'
        '<p style="color:var(--text-4);font-family:monospace;font-size:0.78rem">'
        'Full-pipeline overnight benchmarks (CR-061). Launch + cancel from '
        '<a href="/settings" style="color:var(--accent)">/settings</a>.</p>'
        f'{_benchmark_rows_html(runs)}'
        '</div>'
    )
    return HTMLResponse(
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Benchmark runs — OWL</title>'
        f'{_BASE_STYLES}'
        '<style>'
        '.finding-wrap{max-width:880px;margin:1.5rem auto;padding:0 1rem;color:var(--text);background:var(--bg)}'
        '.finding-row{display:block;border:1px solid var(--border);padding:0.6rem 0.8rem;margin:0.5rem 0;text-decoration:none;background:var(--panel)}'
        '.finding-row:hover{border-color:var(--accent)}'
        '.finding-row-top{display:flex;gap:0.5rem;align-items:baseline}'
        '.finding-row-dot{font-size:0.8rem}'
        '.finding-row-headline{color:var(--text);font-family:monospace;font-size:0.85rem;flex:1}'
        '.finding-row-date{color:var(--text-5);font-family:monospace;font-size:0.72rem}'
        '.finding-row-claim{color:var(--text-3);font-family:monospace;font-size:0.75rem;margin-top:0.3rem}'
        '</style></head><body style="background:var(--bg)">' + body + '</body></html>'
    )


@app.get("/benchmark/{bid}", response_class=HTMLResponse,
         dependencies=[Depends(requires(BENCHMARK_VIEW))])
async def benchmark_detail_page(bid: str):
    m = load_result("benchmark", bid, visitor_key=None)
    if not m:
        return HTMLResponse('<p style="font-family:monospace">Benchmark run not found. '
                            '<a href="/benchmark">← all runs</a></p>', status_code=404)
    status = m.get("status", "?")
    cfg_blob = m.get("config", {})
    steps_html = []
    for st in m.get("steps", []):
        dot = _BENCH_STATUS_DOT.get(st.get("status"), "⚪")
        label = html_lib.escape(st.get("label", st.get("id", "?")))
        sstatus = html_lib.escape(st.get("status", "?"))
        err = st.get("error")
        head = (f'<div style="font-family:monospace;font-size:0.82rem;margin:0.8rem 0 0.3rem">'
                f'{dot} <b>{label}</b> · <span style="color:var(--text-4)">{sstatus}</span>'
                + (f' · <span style="color:var(--err)">{html_lib.escape(str(err))}</span>' if err else '')
                + '</div>')
        ref = st.get("result_ref")
        if ref and ref.get("job_id"):
            head += (f'<div class="bench-embed" data-bid="{html_lib.escape(bid)}" '
                     f'data-type="{html_lib.escape(ref.get("type",""))}" '
                     f'data-kind="{html_lib.escape(st.get("kind",""))}" '
                     f'data-result-id="{html_lib.escape(ref.get("job_id"))}">'
                     f'<div class="loading" style="color:var(--text-5);font-family:monospace;'
                     f'font-size:0.75rem">Loading…</div></div>')
        steps_html.append(head)
    body = (
        '<div class="bench-wrap">'
        f'<p style="font-family:monospace;font-size:0.78rem"><a href="/benchmark" style="color:var(--accent)">← all runs</a></p>'
        f'<h1 style="font-size:1.2rem;color:var(--text)">{_BENCH_STATUS_DOT.get(status,"⚪")} Benchmark {html_lib.escape(bid)}</h1>'
        f'<div style="color:var(--text-4);font-family:monospace;font-size:0.76rem;line-height:1.6">'
        f'status: {html_lib.escape(status)} · {m.get("total_steps",0)} steps · '
        f'started {html_lib.escape((m.get("started_at") or "—")[:19].replace("T"," "))}'
        f'{(" · finished " + html_lib.escape((m.get("finished_at") or "")[:19].replace("T"," "))) if m.get("finished_at") else ""}<br>'
        f'config: reps={cfg_blob.get("video_reps")} · sources={html_lib.escape(", ".join(cfg_blob.get("sources",[])))} · '
        f'measures={html_lib.escape(", ".join(cfg_blob.get("enabled",[])))}</div>'
        + "".join(steps_html)
        + '</div>'
    )
    return HTMLResponse(
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Benchmark {html_lib.escape(bid)} — OWL</title>'
        f'{_BASE_STYLES}'
        '<style>.bench-wrap{max-width:900px;margin:1.5rem auto;padding:0 1rem;color:var(--text);background:var(--bg)}</style>'
        '</head><body style="background:var(--bg)">' + body
        + _CARBON_JS + _RESULT_JS + _BENCH_HYDRATE_JS
        + '</body></html>'
    )


@app.get("/benchmark/{bid}/result/{job_type}/{job_id}.json",
         dependencies=[Depends(requires(BENCHMARK_VIEW))])
async def benchmark_result_json(bid: str, job_type: str, job_id: str):
    """CR-061 — serve a benchmark step's result to anyone who can VIEW the
    benchmark (Member+). The generic /results/.../download.json is visitor-
    scoped (own-jobs only, CR-026), so a member can't load Lab-produced
    benchmark results through it. This loads unscoped, but ONLY for (type,
    job_id) pairs actually referenced by THIS manifest — so it can't be used
    to read another visitor's private results."""
    if job_type not in ("video", "llm", "image"):
        return JSONResponse({"error": "Invalid type"}, status_code=400)
    manifest = load_result("benchmark", bid, visitor_key=None)
    if not manifest:
        return JSONResponse({"error": "Not found"}, status_code=404)
    allowed = set()
    for st in manifest.get("steps", []):
        ref = st.get("result_ref")
        if ref and ref.get("job_id"):
            allowed.add((ref.get("type"), ref.get("job_id")))
    if (job_type, job_id) not in allowed:
        return JSONResponse({"error": "Not found"}, status_code=404)
    data = load_result(job_type, job_id, visitor_key=None)
    if not data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return StreamingResponse(
        io.BytesIO(json.dumps(data, indent=2).encode()),
        media_type="application/json",
    )


@app.get("/findings/{slug}", response_class=HTMLResponse,
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


# --- RAG page and endpoints ---

@app.get("/rag", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def rag_page(request: Request):
    # CR-001 part C2c — capability flags drive lock badges on the question
    # textarea (CUSTOM_PROMPT), the 3-mode compare button (BATCH_COMPARE),
    # and the corpus build/rebuild buttons (RAG_CORPUS_UPLOAD). The runtime
    # gates already enforce these — this is the visible product copy.
    can_custom_prompt = can(audience.tier(request), CUSTOM_PROMPT)
    can_batch_compare = can(audience.tier(request), BATCH_COMPARE)
    can_corpus_upload = can(audience.tier(request), RAG_CORPUS_UPLOAD)
    lk_q_class        = _lock_class(request, CUSTOM_PROMPT)
    lk_q_badge        = _lock_badge_html(request, CUSTOM_PROMPT, "Edit question — Members only")
    lk_batch_class    = _lock_class(request, BATCH_COMPARE)
    lk_batch_badge    = _lock_badge_html(request, BATCH_COMPARE, "Compare 4 modes — Members only")
    lk_corpus_class   = _lock_class(request, RAG_CORPUS_UPLOAD)
    lk_corpus_badge   = _lock_badge_html(request, RAG_CORPUS_UPLOAD, "Build / rebuild index — Members only")
    dis_q             = _disabled_attr(request, CUSTOM_PROMPT)
    dis_batch         = _disabled_attr(request, BATCH_COMPARE)
    dis_corpus        = _disabled_attr(request, RAG_CORPUS_UPLOAD)

    # CR-055 — RAG mode constants injected as JS so the frontend stays
    # in lock-step with the rag.py source of truth.
    import json as _json
    rag_modes_js        = _json.dumps(list(rag_module.COMPARE_MODES))
    rag_mode_labels_js  = _json.dumps(rag_module.MODE_LABELS)
    rag_short_labels_js = _json.dumps(rag_module.SHORT_MODE_LABELS)

    models_html = "".join([
        f'''<div class="preset" id="rmodel-{k}" onclick="selectRModel('{k}')">
            <h3>{v["label"]}</h3>
            <p style="color:var(--text-3);font-size:0.75rem">{v["params"]} · {v["size"]}</p>
            {_model_date_line(v)}
        </div>'''
        for k, v in rag_module.MODELS.items()
    ])

    queue_depth = queue_control.depth()
    busy_banner = (f'<div style="background:var(--border-3);color:var(--warn);padding:0.75rem 1rem;'
                   f'margin-bottom:1rem;font-size:0.85rem">'
                   f'⏱ {queue_depth} job{"s" if queue_depth != 1 else ""} in queue — '
                   f'yours will be added and run automatically.</div>') \
        if queue_depth > 0 else ""

    return _bake_durations(f"""<!DOCTYPE html>
<html>
<head>
    <link rel="icon" type="image/svg+xml" href="/static/owl.svg">
  <title>OWL — RAG Energy Test</title>
    <style>
        * {{ box-sizing:border-box; margin:0; padding:0; }}
        body {{ font-family:monospace; background:var(--bg); color:var(--text);
               max-width:780px; margin:0 auto; padding:2rem; }}
        h1 {{ color:var(--accent); margin-bottom:0.25rem; font-size:1.6rem; }}
        .subtitle {{ color:var(--text-3); font-size:0.8rem; margin-bottom:1.5rem; }}
        .info {{ color:var(--text-3); font-size:0.82rem; margin-bottom:1.5rem;
                 border-left:2px solid #222; padding-left:1rem; line-height:1.6; }}
        .presets {{ display:flex; gap:0.75rem; margin-bottom:1.5rem; }}
        .preset {{ border:1px solid var(--border-3); padding:1rem; cursor:pointer; flex:1; }}
        .preset:hover {{ border-color:#00ff9966; }}
        .preset.selected {{ border-color:var(--accent); background:#00ff9911; }}
        .preset h3 {{ color:var(--accent); font-size:0.9rem; margin-bottom:0.4rem; }}
        .section-label {{ color:var(--text-3); font-size:0.75rem; text-transform:uppercase;
                          letter-spacing:0.05em; margin-bottom:0.75rem; }}
        button {{ background:var(--accent); color:#000; border:none; padding:0.75rem 2rem;
                  cursor:pointer; font-family:monospace; font-size:1rem; margin-top:1rem; }}
        button:disabled {{ background:var(--border); color:var(--text-3); cursor:not-allowed; }}
        button:hover:not(:disabled) {{ background:var(--accent-hover); }}
        #status {{ margin-top:1.5rem; }}
        .result-box {{ border:1px solid var(--border); padding:1.5rem; }}
        .result-box h2 {{ color:var(--accent); font-size:1.1rem; margin-bottom:1rem;
                          padding-bottom:0.5rem; border-bottom:1px solid var(--border); }}
        .metric {{ display:flex; justify-content:space-between;
                   padding:0.3rem 0; border-bottom:1px solid var(--panel); font-size:0.82rem; }}
        .val {{ color:var(--accent); }}
        .section-title {{ color:var(--text-4); font-size:0.72rem; text-transform:uppercase;
                          letter-spacing:0.05em; margin:0.75rem 0 0.4rem; }}
        .response-box {{ background:var(--panel); padding:1rem; margin-top:0.75rem;
                         font-size:0.8rem; color:var(--text-2); line-height:1.6;
                         border-left:2px solid #00ff9944; max-height:500px;
                         overflow-y:auto; white-space:pre-wrap; }}
        .scope-note {{ color:var(--text-5); font-size:0.72rem; margin-top:1rem; }}
        .progress-box {{ border:1px solid var(--border); padding:1.5rem; }}
        .progress-header {{ color:var(--warn); font-size:0.9rem; margin-bottom:1rem; }}
        textarea {{ background:var(--panel); border:1px solid var(--border-3); color:var(--text);
                    font-family:monospace; font-size:0.88rem; padding:0.75rem;
                    width:100%; resize:vertical; line-height:1.5; }}
        textarea:focus {{ border-color:#00ff9966; outline:none; }}
        .mode-card {{ border:1px solid var(--border-3); padding:0.75rem 1rem; cursor:pointer;
                      flex:1; transition:border-color 0.15s; }}
        .mode-card:hover {{ border-color:#00ff9966; }}
        .mode-card.selected {{ border-color:var(--accent); background:#00ff9911; }}
        .mode-card h4 {{ color:var(--accent); font-size:0.85rem; margin-bottom:0.2rem; }}
        .mode-card p {{ color:var(--text-3); font-size:0.75rem; }}
        .index-bar {{ border:1px solid var(--border-2); padding:0.75rem 1rem;
                      font-size:0.8rem; color:var(--text-3); margin-bottom:1.5rem;
                      display:flex; align-items:center; justify-content:space-between; gap:1rem; }}
        .index-dot {{ width:8px; height:8px; border-radius:50%; flex-shrink:0; }}
        {_LOCK_STYLES}
    </style>
</head>
<body>
    {_BACK}
    {busy_banner}
    <h1>RAG Energy Test {_BETA_CHIP}</h1>
    <div class="subtitle">Greening of Streaming · OWL · GoS1</div>

    <div style="margin-bottom:1.5rem;padding:0.85rem 1rem;border:1px solid var(--accent);
                background:var(--accent-soft);font-size:0.85rem;line-height:1.5">
        <span style="color:var(--accent);font-weight:bold">NEW</span> &middot;
        <a href="/rag/compare" style="color:var(--accent);text-decoration:none;
                                       border-bottom:1px solid var(--accent)">Compare {len(rag_module.MODELS)} models on one question &rarr; energy per correct answer &nearr;</a>
        <span style="color:var(--text-3)"> &nbsp;CR-049 hybrid: BBC showcase + member &ldquo;Try your own question&rdquo;.</span>
    </div>

    {_ai_intro('rag')}

    <div style="margin-bottom:1rem;font-size:0.78rem;color:var(--text-3)">
        First time here? <a href="/demo" style="color:var(--accent);text-decoration:none">Try the Guided Tour →</a>
    </div>

    <details style="margin-bottom:1.5rem;border-left:2px solid #222;padding-left:1rem">
        <summary style="cursor:pointer;color:var(--text-3);font-size:0.82rem;list-style:none;outline:none">
            ⓘ About this test <span style="color:var(--text-4);font-size:0.72rem">(click to expand)</span>
        </summary>
        <div style="color:var(--text-3);font-size:0.82rem;line-height:1.6;margin-top:0.75rem">
            Retrieval-Augmented Generation (RAG) augments an LLM with chunks retrieved from a PDF corpus (ChromaDB + sentence-transformer embeddings).<br>
            Compare three modes: <strong style="color:var(--text-2)">baseline</strong> (no retrieval), <strong style="color:var(--text-2)">RAG</strong> (top 3 chunks, 4096 ctx), <strong style="color:var(--text-2)">RAG Large</strong> (top 8 chunks, 8192 ctx).<br>
            Use "Compare 4 modes" to run all three sequentially with fresh baselines — a side-by-side energy comparison for the same question.<br>
            Scope: device layer only — no network, no amortised training cost.
        </div>
    </details>

    <div class="index-bar">
        <div style="display:flex;align-items:center;gap:0.6rem">
            <div class="index-dot" id="index-dot" style="background:var(--border-3)"></div>
            <span id="index-status-text">Checking index…</span>
        </div>
        <div class="{lk_corpus_class}" style="display:flex;gap:0.5rem;align-items:center">
            {lk_corpus_badge}
            <button id="buildBtn" onclick="buildIndex(false)"{dis_corpus}
                    style="background:none;border:1px solid var(--border-3);color:var(--text-3);
                           font-size:0.75rem;padding:0.3rem 0.75rem;cursor:pointer;
                           font-family:monospace;margin-top:0">Build index</button>
            <button id="rebuildBtn" onclick="buildIndex(true)"{dis_corpus}
                    style="background:none;border:1px solid var(--border-3);color:var(--text-3);
                           font-size:0.75rem;padding:0.3rem 0.75rem;cursor:pointer;
                           font-family:monospace;margin-top:0">Rebuild</button>
        </div>
    </div>

    <dialog id="preview-dlg" style="border:1px solid var(--accent);background:var(--bg);
            color:var(--text);width:80vw;height:85vh;max-width:1100px;padding:0;margin:auto">
      <div style="display:flex;align-items:center;justify-content:space-between;
                  padding:0.5rem 0.85rem;background:var(--panel);border-bottom:1px solid var(--border)">
        <span id="preview-title" style="font-family:monospace;font-size:0.82rem;color:var(--text-2);
              overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-right:0.75rem">filename</span>
        <button onclick="document.getElementById('preview-dlg').close()"
                style="background:none;border:1px solid var(--border-3);color:var(--text-3);
                       font-size:0.85rem;padding:0.15rem 0.5rem;cursor:pointer;font-family:monospace"
                title="Close (Esc)">×</button>
      </div>
      <iframe id="preview-iframe" style="width:100%;height:calc(100% - 2.5rem);border:none;background:var(--panel-2)"></iframe>
    </dialog>

    <details id="corpus-browser" style="margin-bottom:1.5rem;border:1px solid var(--border);padding:0.5rem 0.9rem;font-size:0.82rem"
             ontoggle="if(this.open) loadCorpus();">
      <summary style="cursor:pointer;color:var(--text-2);list-style:none">
        <span id="corpus-summary-text">▸ Browse corpus documents</span>
      </summary>
      {("<div id='upload-form' style='margin-top:0.75rem;padding:0.6rem 0.75rem;border:1px dashed var(--border-3);background:var(--panel-2)'>"
        "<div style='color:var(--text-2);font-size:0.8rem;margin-bottom:0.4rem;font-weight:bold'>Upload a PDF to the corpus</div>"
        "<div style='color:var(--text-5);font-size:0.72rem;margin-bottom:0.4rem' id='upload-quota'>Loading quota…</div>"
        "<input type='file' id='upload-file' accept='application/pdf,.pdf,text/markdown,.md' "
        "style='font-family:monospace;font-size:0.78rem;color:var(--text-3);background:#0f0f0f;"
        "border:1px solid var(--border-3);padding:0.35rem;width:100%;margin-bottom:0.4rem'>"
        "<input type='text' id='upload-title' maxlength='200' "
        "placeholder='Optional note / qualifier (e.g. &quot;Internal GoS working document&quot;)' "
        "style='font-family:monospace;font-size:0.78rem;color:var(--text-3);background:#0f0f0f;"
        "border:1px solid var(--border-3);padding:0.35rem;width:100%;margin-bottom:0.5rem'>"
        "<button onclick='uploadDoc()' style='background:var(--accent);color:#000;border:none;"
        "padding:0.45rem 1rem;cursor:pointer;font-family:monospace;font-size:0.78rem'>Upload + index</button>"
        "<span id='upload-status' style='margin-left:0.75rem;color:var(--text-4);font-size:0.78rem'></span>"
        "</div>") if can_corpus_upload else ""}
      <div id="corpus-list" style="margin-top:0.6rem;color:var(--text-3);font-size:0.78rem;line-height:1.6">
        <p style="color:var(--text-4)">Loading…</p>
      </div>
    </details>

    <div class="section-label">Model</div>
    <div class="presets">{models_html}</div>

    <div class="section-label">Retrieval mode</div>
    <div class="presets" style="margin-bottom:1.5rem">
        <div class="mode-card selected" id="rmode-baseline" onclick="selectRMode('baseline')">
            <h4>Without RAG</h4>
            <p>No retrieval. Cold LLM inference only.</p>
        </div>
        <div class="mode-card" id="rmode-rag" onclick="selectRMode('rag')">
            <h4>RAG</h4>
            <p>Top 3 chunks · faithful (chunks only)</p>
        </div>
        <div class="mode-card" id="rmode-rag_blended" onclick="selectRMode('rag_blended')">
            <h4>RAG Blended</h4>
            <p>Top 3 chunks + training knowledge</p>
        </div>
        <div class="mode-card" id="rmode-rag_large" onclick="selectRMode('rag_large')">
            <h4>RAG Large</h4>
            <p>Top 8 chunks · 8192 ctx</p>
        </div>
    </div>

    <div class="section-label">Question</div>
    {lk_q_badge}
    <div class="{lk_q_class}">
      <textarea id="questionText" rows="3"{dis_q}
                placeholder="What is REM (Remote Energy Measurement)?"
                style="margin-bottom:0.5rem"></textarea>
    </div>
    <details style="margin-bottom:1.5rem;color:var(--text-3);font-size:0.78rem">
      <summary style="cursor:pointer;color:var(--text-2)">ⓘ Why this question, and how to read the answers</summary>
      <div style="padding:0.75rem 0;line-height:1.6">
        <p style="margin-bottom:0.5rem"><strong>"What is REM?"</strong> is corpus-grounded — the GoS REM whitepaper is in the index but unlikely in any model's training data. So the answer should come <em>from</em> retrieval, not from prior knowledge. Good test of whether RAG is working.</p>
        <p style="margin-bottom:0.5rem"><strong>What you'll see (2026-04-29 runs):</strong> all three model sizes retrieve the <em>same correct chunks</em>. But TinyLlama (1.1B) hallucinates "REM is a framework provided by the European Commission" — blending the GoS source with adjacent chunks. Gemma 3 (12B) and Phi-4 (14B) stay faithful and describe REM correctly as the GoS streaming-energy framework.</p>
        <p><strong>The headline:</strong> RAG retrieval ≠ RAG quality. Smaller models can't faithfully read what they retrieve. Hallucination rate is a third axis on the energy/quality tradeoff — alongside speed and accuracy.</p>
      </div>
    </details>

    {lk_batch_badge}
    <div style="display:flex;gap:0.75rem;flex-wrap:wrap">
        <button id="runBtn" onclick="startRag()">▶ Run single</button>
        <button id="compareBtn" class="{lk_batch_class}" onclick="startCompare()"{dis_batch}
                style="background:var(--panel);border:1px solid var(--accent);color:var(--accent)">
            ▶▶ Compare 4 modes
        </button>
    </div>

    <div id="status"></div>

    <div id="prev-runs" style="margin-top:2.5rem"></div>

    <script>
    // CR-001 part C2c — capability flags from server.
    // Anonymous: textarea is locked, JS posts an empty `question` so
    // /rag/run uses CANONICAL_RAG_QUESTION (curated.py); the BATCH_COMPARE
    // gate is enforced server-side, the disabled button is just polite UX.
    const CAN_CUSTOM_PROMPT = {('true' if can_custom_prompt else 'false')};
    const CAN_BATCH_COMPARE = {('true' if can_batch_compare else 'false')};

    let selectedRModel = 'tinyllama';
    let selectedRMode = 'baseline';
    let ragTimer = null;
    let ragStartTime = null;
    let compareTimer = null;

    function selectRModel(k) {{
        document.querySelectorAll('.presets .preset').forEach(el => el.classList.remove('selected'));
        const el = document.getElementById('rmodel-' + k);
        if (el) el.classList.add('selected');
        selectedRModel = k;
    }}
    function selectRMode(m) {{
        document.querySelectorAll('.mode-card').forEach(el => el.classList.remove('selected'));
        const el = document.getElementById('rmode-' + m);
        if (el) el.classList.add('selected');
        selectedRMode = m;
    }}
    selectRModel('tinyllama');

    function toggleAns(id) {{
        var el = document.getElementById(id);
        if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
    }}

    // Index status
    async function loadIndexStatus() {{
        try {{
            const r = await fetch('/rag/index-status');
            const d = await r.json();
            const dot = document.getElementById('index-dot');
            const txt = document.getElementById('index-status-text');
            if (d.status === 'ready') {{
                dot.style.background = '#00ff99';
                txt.textContent = 'Index ready · ' + d.doc_count + ' chunks';
            }} else if (d.status === 'building') {{
                dot.style.background = '#ffaa00';
                txt.textContent = 'Building index…';
                setTimeout(loadIndexStatus, 3000);
            }} else if (d.status === 'error') {{
                dot.style.background = '#ff4400';
                txt.textContent = 'Index error: ' + (d.error || 'unknown');
            }} else {{
                dot.style.background = '#555';
                txt.textContent = 'Index not built — click "Build index" to start';
            }}
        }} catch(e) {{
            document.getElementById('index-status-text').textContent = 'Could not check index';
        }}
    }}

    async function loadCorpus() {{
        const el = document.getElementById('corpus-list');
        const sumEl = document.getElementById('corpus-summary-text');
        const quotaEl = document.getElementById('upload-quota');
        try {{
            const r = await fetch('/rag/corpus-list');
            const d = await r.json();
            sumEl.textContent = '▾ Browse corpus documents — ' + d.total + ' PDFs (' + d.indexed + ' indexed)';
            // CR-051 — Member quota display (above upload form)
            if (quotaEl) {{
                const u = d.member_usage, c = d.caps || {{}};
                if (u && c.member_doc_count != null) {{
                    const mb = (u.total_bytes / 1024 / 1024).toFixed(1);
                    quotaEl.textContent = 'Your uploads: ' + u.file_count + '/' + c.member_doc_count
                        + ' files · ' + mb + ' / ' + c.member_total_mb + ' MB · '
                        + 'per-file cap: ' + c.per_file_mb + ' MB';
                }} else {{
                    quotaEl.textContent = 'Lab tier — uncapped. Per-file cap: ' + (c.per_file_mb || '?') + ' MB.';
                }}
            }}
            if (!d.docs || d.docs.length === 0) {{
                el.innerHTML = '<p style="color:var(--text-4)">No PDFs found in the corpus directory.</p>';
                return;
            }}
            // CR-051 — sort: Member-uploaded first (so they find their own quickly), then pending, then alpha.
            d.docs.sort((a,b) => {{
                const aM = (a.origin === 'Member') ? 0 : 1;
                const bM = (b.origin === 'Member') ? 0 : 1;
                return aM - bM || (a.indexed - b.indexed) || a.rel_path.localeCompare(b.rel_path);
            }});
            const rows = d.docs.map(doc => {{
                const flag = doc.indexed
                    ? '<span style="color:var(--accent)" title="indexed">●</span>'
                    : '<span style="color:var(--warn)" title="not yet indexed — rebuild">○</span>';
                const tag = doc.indexed ? 'indexed' : 'pending — rebuild to add';
                const sizeStr = doc.size_kb >= 1024
                    ? (doc.size_kb / 1024).toFixed(1) + ' MB'
                    : doc.size_kb + ' KB';
                const originChip = doc.origin === 'Member'
                    ? '<span style="color:var(--accent);border:1px solid var(--accent);font-size:0.65rem;padding:0 0.3rem;border-radius:2px">Member</span>'
                    : '<span style="color:var(--text-4);border:1px solid var(--border-3);font-size:0.65rem;padding:0 0.3rem;border-radius:2px">Lab</span>';
                const addedShort = (doc.added_at || '').slice(0, 10);  // YYYY-MM-DD
                const safeJsName = doc.rel_path.replace(/\\\\/g, "\\\\\\\\").replace(/'/g, "\\\\'");
                const viewBtn = '<button onclick="viewDoc(\\'' + safeJsName + '\\')" '
                    + 'style="background:none;border:1px solid var(--border-3);color:var(--text-3);'
                    + 'font-size:0.7rem;padding:0 0.4rem;cursor:pointer;font-family:monospace" title="Preview">👁</button>';
                const delBtn = doc.can_delete
                    ? '<button onclick="deleteDoc(\\'' + safeJsName + '\\')" '
                      + 'style="background:none;border:1px solid var(--border-3);color:var(--err);'
                      + 'font-size:0.7rem;padding:0 0.4rem;cursor:pointer;font-family:monospace" title="Delete this document">×</button>'
                    : '';
                // CR-051 — optional title shown inline after filename. Both
                // get individual `title` HTML attributes so a long-name OR a
                // long-note still surfaces fully on hover.
                const titleHtml = doc.title
                    ? '<span style="color:var(--text-5);font-style:italic" title="' + (doc.title.replace(/"/g, '&quot;')) + '"> · ' + doc.title + '</span>'
                    : '';
                return '<div style="display:flex;align-items:center;gap:0.5rem;padding:0.2rem 0;border-bottom:1px solid var(--border-2)">'
                    + '<span style="flex-shrink:0">' + flag + '</span>'
                    + '<span style="flex:1;font-family:monospace;font-size:0.75rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + doc.rel_path + '">'
                    + doc.rel_path + titleHtml + '</span>'
                    + '<span style="flex-shrink:0">' + originChip + '</span>'
                    + '<span style="flex-shrink:0;color:var(--text-5);font-size:0.7rem;width:5.5rem;text-align:right">' + addedShort + '</span>'
                    + '<span style="flex-shrink:0;color:var(--text-4);font-size:0.72rem;width:5rem;text-align:right">' + sizeStr + '</span>'
                    + '<span style="flex-shrink:0;color:var(--text-4);font-size:0.7rem;width:8rem;text-align:right">' + tag + '</span>'
                    + '<span style="flex-shrink:0;display:flex;gap:0.25rem">' + viewBtn + delBtn + '</span>'
                    + '</div>';
            }}).join('');
            el.innerHTML = '<div style="max-height:28rem;overflow-y:auto;padding-right:0.4rem">' + rows + '</div>'
                + '<p style="color:var(--text-4);font-size:0.72rem;margin-top:0.5rem">'
                + 'Origin: <span style="color:var(--accent)">Member</span> = uploaded via the form above (Members can delete their own). '
                + '<span style="color:var(--text-4)">Lab</span> = seeded by the GoS team. '
                + 'Names of Member uploaders are not shown publicly.</p>';
        }} catch(e) {{
            el.innerHTML = '<p style="color:var(--err)">Failed to load corpus: ' + e + '</p>';
        }}
    }}

    async function uploadDoc() {{
        const fileEl = document.getElementById('upload-file');
        const titleEl = document.getElementById('upload-title');
        const status = document.getElementById('upload-status');
        const file = fileEl.files[0];
        if (!file) {{ status.style.color = 'var(--err)'; status.textContent = 'pick a PDF first'; return; }}
        status.style.color = 'var(--warn)'; status.textContent = 'uploading…';
        const fd = new FormData();
        fd.append('file', file);
        const t = (titleEl.value || '').trim();
        if (t) fd.append('title', t);
        try {{
            const r = await fetch('/rag/upload', {{method: 'POST', body: fd}});
            const d = await r.json();
            if (!r.ok || d.error) {{
                status.style.color = 'var(--err)';
                status.textContent = d.error || ('HTTP ' + r.status);
                return;
            }}
            status.style.color = 'var(--accent)';
            const chunks = d.indexed && d.indexed.chunks_added;
            status.textContent = '✓ ' + d.filename + (chunks ? ' (' + chunks + ' chunks indexed)' : ' (indexing…)');
            fileEl.value = '';
            titleEl.value = '';
            // Refresh the corpus list to show the new entry.
            setTimeout(loadCorpus, 500);
        }} catch(e) {{
            status.style.color = 'var(--err)';
            status.textContent = 'failed: ' + e;
        }}
    }}

    function viewDoc(filename) {{
        const dlg = document.getElementById('preview-dlg');
        document.getElementById('preview-title').textContent = filename;
        document.getElementById('preview-iframe').src = '/rag/doc/' + encodeURIComponent(filename);
        dlg.showModal();
    }}

    async function deleteDoc(filename) {{
        if (!confirm('Delete "' + filename + '" from the corpus? This removes the PDF and its index chunks.')) return;
        try {{
            const r = await fetch('/rag/doc/' + encodeURIComponent(filename), {{method: 'DELETE'}});
            const d = await r.json();
            if (!r.ok || d.error) {{
                alert('Delete failed: ' + (d.error || ('HTTP ' + r.status)));
                return;
            }}
            loadCorpus();
        }} catch(e) {{
            alert('Delete failed: ' + e);
        }}
    }}

    async function buildIndex(rebuild) {{
        const btn = rebuild ? document.getElementById('rebuildBtn') : document.getElementById('buildBtn');
        btn.disabled = true;
        btn.textContent = 'Working…';
        document.getElementById('index-dot').style.background = '#ffaa00';
        document.getElementById('index-status-text').textContent = 'Building index…';
        try {{
            await fetch('/rag/build-index', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{rebuild: rebuild}})
            }});
        }} catch(e) {{}}
        btn.disabled = false;
        btn.textContent = rebuild ? 'Rebuild' : 'Build index';
        setTimeout(loadIndexStatus, 2000);
    }}

    async function startRag() {{
        const question = document.getElementById('questionText').value.trim();
        if (CAN_CUSTOM_PROMPT && !question) {{
            document.getElementById('status').innerHTML =
                '<div style="color:var(--err);font-size:0.85rem;margin-top:1rem">Please enter a question.</div>';
            return;
        }}
        document.getElementById('runBtn').disabled = true;
        ragStartTime = Date.now();
        const form = new FormData();
        form.append('model_key', selectedRModel);
        form.append('rag_mode', selectedRMode);
        if (CAN_CUSTOM_PROMPT && question) form.append('question', question);
        try {{
            const resp = await fetch('/rag/run', {{method:'POST', body:form}});
            const data = await resp.json();
            if (data.job_id) {{
                renderRagProgress('baseline');
                pollRag(data.job_id);
            }} else {{
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + JSON.stringify(data) + '</div>';
                document.getElementById('runBtn').disabled = false;
            }}
        }} catch(e) {{
            document.getElementById('status').innerHTML =
                '<div style="color:var(--err)">Failed: ' + e + '</div>';
            document.getElementById('runBtn').disabled = false;
        }}
    }}

    const RAG_STAGES = ['Baseline poll ({{BASELINE_S}}s)', 'Inference running', 'Complete'];
    const RAG_STAGE_IDX = {{baseline:0, inference:1, done:2}};

    // Single-mode renderRagProgress (used by pollRag below). The 3-mode
    // compare flow has its own renderCompareProgress further down \u2014 earlier
    // I dispatched compare/single inside this function, but single-mode
    // jobs never carry mode_index so the compare branch was dead code AND
    // its const RAG_MODE_LABELS collided with the per-mode label dict
    // injected from rag.py for renderCompareProgress. Reverted to original.
    function renderRagProgress(stage, watts) {{
        wlRenderProgress({{
            header: 'Measuring RAG energy \u2014 do not close this tab',
            stagesHtml: wlStageList(RAG_STAGES, RAG_STAGE_IDX[stage] ?? 0),
            watts: watts,
            elapsed: ragStartTime ? Date.now() - ragStartTime : null,
        }});
    }}

    async function pollRag(jobId) {{
        try {{
            const [resp, powerR] = await Promise.all([
                fetch('/rag/job/' + jobId),
                fetch('/power').catch(() => null),
            ]);
            const data = await resp.json();
            const watts = powerR ? (await powerR.json().catch(()=>({{}}))).watts ?? null : null;
            if (data.stage === 'done' && data.result) {{
                if (ragTimer) {{ clearTimeout(ragTimer); ragTimer = null; }}
                renderRagResult(data.result, jobId);
                document.getElementById('runBtn').disabled = false;
                loadPrevRuns();
            }} else if (data.stage === 'error' || data.error) {{
                if (ragTimer) {{ clearTimeout(ragTimer); ragTimer = null; }}
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + (data.error||'unknown') + '</div>';
                document.getElementById('runBtn').disabled = false;
            }} else if (data.stage === 'queued') {{
                wlRenderQueued(data.queue_position);
                ragTimer = setTimeout(() => pollRag(jobId), 3000);
            }} else {{
                if (data.stage === 'awaiting_cooldown_decision') {{
                    wlCooldownDialog(jobId, data.cooldown_decision_options);
                }} else {{ wlCooldownDialogClose(); }}
                renderRagProgress(data.stage || 'baseline', watts);
                ragTimer = setTimeout(() => pollRag(jobId), 2000);
            }}
        }} catch(e) {{
            ragTimer = setTimeout(() => pollRag(jobId), 5000);
        }}
    }}

    function renderRagResult(r, jobId) {{
        const e = r.energy || {{}};
        const inf = r.inference || {{}};
        const conf = e.confidence || {{}};
        const ragModeLabels = RAG_MODE_LABELS;
        const sourcesHtml = r.chunk_sources && r.chunk_sources.length
            ? r.chunk_sources.map(s => `<span style="font-size:0.72rem;color:var(--text-3);
                background:var(--panel);padding:0.2rem 0.4rem;margin-right:0.3rem">${{s}}</span>`).join('')
            : '<span style="color:var(--text-5);font-size:0.75rem">none</span>';
        const retrievalHtml = r.rag_mode !== 'baseline' ? `
            <div class="section-title">Retrieval</div>
            <div class="metric"><span>Chunks retrieved</span><span class="val">${{r.chunks_retrieved}} / ${{r.top_k}}</span></div>
            <div class="metric"><span>Embedding</span><span class="val">${{r.embedding_ms}} ms</span></div>
            <div class="metric"><span>Vector search</span><span class="val">${{r.retrieval_ms}} ms</span></div>
            <div class="metric"><span>Context window</span><span class="val">${{r.num_ctx}} tokens</span></div>
            <div class="section-title" style="margin-top:0.75rem">Sources</div>
            <div style="margin-bottom:0.5rem">${{sourcesHtml}}</div>
        ` : '';
        document.getElementById('status').innerHTML = `
            <div class="result-box">
                <h2>Result — ${{r.model_label}} · ${{ragModeLabels[r.rag_mode] || r.rag_mode}}</h2>
                <div class="section-title">Question</div>
                <div style="color:var(--text-2);font-size:0.82rem;margin-bottom:0.75rem">${{r.question}}</div>
                ${{retrievalHtml}}
                <div class="section-title">Inference</div>
                <div class="metric"><span>Output tokens</span><span class="val">${{inf.output_tokens}}</span></div>
                <div class="metric"><span>Tokens/sec</span><span class="val">${{inf.tokens_per_sec}}</span></div>
                <div class="metric"><span>Duration</span><span class="val">${{inf.duration_s}} s</span></div>
                <div class="section-title">Energy</div>
                <div class="metric"><span>Baseline</span><span class="val">${{e.w_base}} W</span></div>
                <div class="metric"><span>Task mean</span><span class="val">${{e.w_task}} W</span></div>
                <div class="metric"><span>ΔW</span><span class="val">${{e.delta_w}} W</span></div>
                <div class="metric"><span>ΔE</span><span class="val">${{e.delta_e_wh}} Wh</span></div>
                ${{wlCarbonRow(e)}}
                <div class="metric"><span>mWh/token</span><span class="val">${{e.mwh_per_token ?? '—'}}</span></div>
                <div class="metric"><span>Confidence</span>
                    <span class="val conf-badge">${{conf.flag||'—'}} ${{conf.label||''}}</span></div>
                <div class="section-title">Answer</div>
                <div class="response-box">${{inf.response}}</div>
                ${{wlCarbonStrip(e.delta_e_wh, r.model_label + ' · ' + (ragModeLabels[r.rag_mode] || r.rag_mode), e.delta_t_s, e.co2e && e.co2e.intensity ? e.co2e.intensity.g_per_kwh : null)}}
                <div class="scope-note">${{r.scope}}</div>
                <div style="display:flex;gap:0.5rem;margin-top:0.75rem">
                    <a href="/results/llm/${{jobId}}/download.json" download
                       style="color:var(--text-3);font-size:0.75rem;text-decoration:none">↓ JSON</a>
                    <a href="/results/llm/${{jobId}}/download.csv" download
                       style="color:var(--text-3);font-size:0.75rem;text-decoration:none">↓ CSV</a>
                </div>
            </div>`;
    }}

    // --- Compare 4 modes ---

    async function startCompare() {{
        if (!CAN_BATCH_COMPARE) return;   // button is disabled, this is a backstop
        const question = document.getElementById('questionText').value.trim();
        if (CAN_CUSTOM_PROMPT && !question) {{
            document.getElementById('status').innerHTML =
                '<div style="color:var(--err);font-size:0.85rem;margin-top:1rem">Please enter a question.</div>';
            return;
        }}
        document.getElementById('runBtn').disabled = true;
        document.getElementById('compareBtn').disabled = true;
        ragStartTime = Date.now();
        const form = new FormData();
        form.append('model_key', selectedRModel);
        if (CAN_CUSTOM_PROMPT && question) form.append('question', question);
        try {{
            const resp = await fetch('/rag/run-compare', {{method:'POST', body:form}});
            const data = await resp.json();
            if (data.job_id) {{
                renderCompareProgress({{}}, null, null);
                pollCompare(data.job_id);
            }} else {{
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + JSON.stringify(data) + '</div>';
                document.getElementById('runBtn').disabled = false;
                document.getElementById('compareBtn').disabled = false;
            }}
        }} catch(e) {{
            document.getElementById('status').innerHTML =
                '<div style="color:var(--err)">Failed: ' + e + '</div>';
            document.getElementById('runBtn').disabled = false;
            document.getElementById('compareBtn').disabled = false;
        }}
    }}

    // CR-055 — single source of truth (mirrors rag.COMPARE_MODES + LABELS).
    const RAG_COMPARE_MODES  = {rag_modes_js};
    const RAG_MODE_LABELS    = {rag_mode_labels_js};
    const RAG_SHORT_LABELS   = {rag_short_labels_js};

    function renderCompareProgress(partial, data, watts) {{
        const MODES = RAG_COMPARE_MODES;
        // CR-055 alignment — labels come from RAG_SHORT_LABELS (rag.py source of truth).
        data = data || {{}};
        const stage = data.stage;
        const currentMode = data.current_mode;
        const inCooldown = (stage === 'cooldown');
        const stagesHtml = MODES.map((m, i) => {{
            const done = partial && partial[m];
            const active = (m === currentMode) && !done && !inCooldown;
            const col = done ? '#00ff99' : active ? '#ffaa00' : '#333';
            const icon = done ? '✓' : active ? '▶' : '·';
            let extra = '';
            if (done) {{
                const e = partial[m].energy || {{}};
                extra = ' <span style="color:var(--text-3);font-size:0.75rem">\u2014 '
                    + (e.delta_w != null ? e.delta_w + ' W \xb7 ' : '')
                    + (e.mwh_per_token != null ? e.mwh_per_token + ' mWh/tok' : '')
                    + (e.confidence ? ' ' + e.confidence.flag : '')
                    + '</span>';
            }}
            return '<div style="display:flex;align-items:center;gap:0.6rem;font-size:0.82rem;margin-bottom:0.3rem">'
                + '<span style="color:' + col + ';width:1rem">' + icon + '</span>'
                + '<span style="color:' + col + '">' + (RAG_SHORT_LABELS[m] || m) + extra + '</span></div>';
        }}).join('');
        // CR-019/CR-050 \u2014 explicit cooldown row with live thermal-floor wait info.
        let cooldownHtml = '';
        if (inCooldown) {{
            const ref    = (data.cooldown_reference_w != null) ? Number(data.cooldown_reference_w).toFixed(1) + 'W' : '?';
            const cur    = (data.cooldown_w           != null) ? Number(data.cooldown_w).toFixed(1) + 'W' : '?';
            const waited = (data.cooldown_waited_s    != null) ? data.cooldown_waited_s + 's' : '?';
            cooldownHtml = '<div style="display:flex;align-items:center;gap:0.6rem;font-size:0.82rem;margin-bottom:0.3rem">'
                + '<span style="color:#ffaa00;width:1rem">\u23f1</span>'
                + '<span style="color:#ffaa00">Cooldown \u2014 waited ' + waited
                + ' \xb7 current ' + cur + ' (target \u2264 ' + ref + ' +3W)</span></div>';
        }}
        wlRenderProgress({{
            header: 'Comparing ' + MODES.length + ' modes \u2014 do not close this tab',
            stagesHtml: stagesHtml + cooldownHtml,
            watts: watts,
            elapsed: ragStartTime ? Date.now() - ragStartTime : null,
        }});
    }}

    async function pollCompare(jobId) {{
        try {{
            const [resp, powerR] = await Promise.all([
                fetch('/rag/job/' + jobId),
                fetch('/power').catch(() => null),
            ]);
            const data = await resp.json();
            const watts = powerR ? (await powerR.json().catch(()=>({{}}))).watts ?? null : null;
            if (data.stage === 'done' && data.result) {{
                if (compareTimer) {{ clearTimeout(compareTimer); compareTimer = null; }}
                renderCompareResult(data.result, jobId);
                document.getElementById('runBtn').disabled = false;
                document.getElementById('compareBtn').disabled = false;
                loadPrevRuns();
            }} else if (data.stage === 'error' || data.error) {{
                if (compareTimer) {{ clearTimeout(compareTimer); compareTimer = null; }}
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + (data.error||'unknown') + '</div>';
                document.getElementById('runBtn').disabled = false;
                document.getElementById('compareBtn').disabled = false;
            }} else if (data.stage === 'queued') {{
                wlRenderQueued(data.queue_position);
                compareTimer = setTimeout(() => pollCompare(jobId), 3000);
            }} else {{
                renderCompareProgress(data.partial_results || {{}}, data, watts);
                // CR-050 alignment — tighter cadence during cooldown so the
                // waited-Ns counter visibly advances between 1 s server polls.
                const next = data.stage === 'cooldown' ? 750 : 2000;
                compareTimer = setTimeout(() => pollCompare(jobId), next);
            }}
        }} catch(e) {{
            compareTimer = setTimeout(() => pollCompare(jobId), 5000);
        }}
    }}

    function renderCompareResult(r, jobId) {{
        const MODES = RAG_COMPARE_MODES;
        const MODE_LABELS = RAG_MODE_LABELS;
        // CR-055 \u2014 STRIPE colour per mode; baseline dark (no retrieval),
        // rag blue, rag_blended teal (blend = somewhere between), rag_large accent green.
        const STRIPE = {{baseline:'#444', rag:'#0088cc', rag_blended:'#00b3a4', rag_large:'#00ff99'}};
        const cards = MODES.map(m => {{
            const res = (r.results || {{}})[m];
            if (!res) return '';
            const e = res.energy || {{}};
            const inf = res.inference || {{}};
            const conf = e.confidence || {{}};
            const retrievalRow = m !== 'baseline'
                ? '<div style="color:var(--text-3);font-size:0.78rem;margin:0.4rem 0">'
                  + 'embed ' + res.embedding_ms + 'ms \xb7 search ' + res.retrieval_ms + 'ms \xb7 '
                  + res.chunks_retrieved + ' chunks</div>'
                : '<div style="color:var(--text-5);font-size:0.78rem;margin:0.4rem 0">No retrieval</div>';
            const answerId = 'ans-' + m + '-' + jobId;
            return '<div style="border:1px solid var(--border);border-left:3px solid ' + STRIPE[m] + ';padding:1.25rem;margin-bottom:0.75rem">'
                + '<div style="font-size:0.9rem;color:var(--text);margin-bottom:0.5rem">' + MODE_LABELS[m] + '</div>'
                + retrievalRow
                + '<div style="display:flex;gap:1.5rem;font-size:0.82rem;flex-wrap:wrap;margin-bottom:0.5rem">'
                + '<span>\u0394W <span style="color:var(--accent)">' + e.delta_w + ' W</span></span>'
                + '<span>\u0394E <span style="color:var(--accent)">' + e.delta_e_wh + ' Wh</span></span>'
                + '<span>mWh/tok <span style="color:var(--accent)">' + (e.mwh_per_token ?? '\u2014') + '</span></span>'
                + '<span>' + inf.tokens_per_sec + ' tok/s</span>'
                + '<span class="conf-badge">' + (conf.flag||'') + ' ' + (conf.label||'') + '</span>'
                + '</div>'
                + '<div style="font-size:0.75rem;color:var(--text-3);margin-bottom:0.4rem;cursor:pointer" '
                + 'data-id="' + answerId + '" onclick="toggleAns(this.dataset.id)">'
                + '\u25b6 Show / hide answer</div>'
                + '<div id="' + answerId + '" style="display:none;background:var(--panel);padding:0.75rem;'
                + 'font-size:0.78rem;color:var(--text-2);line-height:1.6;white-space:pre-wrap;max-height:300px;overflow-y:auto;'
                + 'border-left:2px solid ' + STRIPE[m] + '44">' + (inf.response || '') + '</div>'
                + '</div>';
        }}).join('');
        // Per-report carbon strip: use the lowest energy across the 3 modes
        // (the most efficient mode) so the "if this had run elsewhere"
        // comparison reflects the best-case carbon footprint of this run.
        const _stripWhArr = MODES
            .map(m => (r.results||{{}})[m] && r.results[m].energy ? r.results[m].energy.delta_e_wh : null)
            .filter(v => v != null);
        const _stripWh = _stripWhArr.length ? Math.min.apply(null, _stripWhArr) : null;
        const _stripLbl = r.model_label + ' \xb7 3-mode RAG comparison (best of)';
        // Find the winning mode's energy block for drift note + duration.
        let _winE = null;
        let _winWh = Infinity;
        MODES.forEach(m => {{
            const me = (r.results||{{}})[m] && r.results[m].energy;
            if (me && me.delta_e_wh != null && me.delta_e_wh < _winWh) {{
                _winE = me; _winWh = me.delta_e_wh;
            }}
        }});
        const _stripDur = _winE ? _winE.delta_t_s : null;
        const _stripSavedG = _winE && _winE.co2e && _winE.co2e.intensity
            ? _winE.co2e.intensity.g_per_kwh : null;
        // CR-032 \u2014 sub-runs across the 3 retrieval modes.
        const _subRuns = MODES
            .map(m => {{
                const res = (r.results||{{}})[m];
                if (!res || !res.energy || !res.energy.co2e) return null;
                return {{
                    label: MODE_LABELS[m],
                    grams: res.energy.co2e.grams,
                    deltaWh: res.energy.delta_e_wh,
                    durationS: res.energy.delta_t_s
                }};
            }})
            .filter(s => s != null);
        // CR-038 \u2014 structured efficiency verdict above the per-mode cards.
        const _ragVerdict = wlEfficiencyVerdict(MODES.map(m => {{
            const res = (r.results||{{}})[m];
            if (!res || !res.energy) return null;
            return {{label: MODE_LABELS[m], energy: res.energy.mwh_per_token}};
        }}).filter(x => x != null), {{unit: 'mWh/token'}});
        document.getElementById('status').innerHTML =
            '<div style="border:1px solid var(--border);padding:1.5rem">'
            + '<div style="color:var(--accent);font-size:1.1rem;margin-bottom:0.25rem">Comparison \u2014 ' + r.model_label + '</div>'
            + '<div style="color:var(--text-3);font-size:0.82rem;margin-bottom:1rem">' + r.question + '</div>'
            + _ragVerdict
            + cards
            + wlCarbonStrip(_stripWh, _stripLbl, _stripDur, _stripSavedG, _subRuns)
            + '<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.75rem">' + (r.scope||'') + '</div>'
            + '<div style="display:flex;gap:0.5rem;margin-top:0.75rem">'
            + '<a href="/results/llm/' + jobId + '/download.json" download style="color:var(--text-3);font-size:0.75rem;text-decoration:none">\u2193 JSON</a>'
            + '</div></div>';
    }}

    // --- Previous runs ---

    async function loadPrevRuns() {{
        try {{
            const resp = await fetch('/results/llm/list');
            const runs = await resp.json();
            const ragRuns = runs.filter(r => r.task && (r.task.startsWith('RAG/') || r.task === 'RAG compare (3 modes)'));
            renderPrevRuns(ragRuns);
        }} catch(e) {{}}
    }}

    function renderPrevRuns(runs) {{
        const el = document.getElementById('prev-runs');
        if (!runs || runs.length === 0) {{
            el.innerHTML = '<div style="color:var(--text-5);font-size:0.8rem">No previous RAG runs.</div>';
            return;
        }}
        const rows = runs.map(r => {{
            const date = r.saved_at ? r.saved_at.slice(0,16).replace('T',' ') : '\u2014';
            const summary = (r.model||'') + ' \xb7 ' + (r.task||'') + ' \xb7 ' + r.mwh_per_token + ' mWh/tok ' + (r.confidence ? '<span class="conf-badge">'+r.confidence+'</span>' : '');
            const base = '/results/llm/' + r.job_id;
            const savedAt = r.saved_at || '';
            // RAG persists under llm/ but renders with the RAG card; passing
            // jobType='llm' + cardKind='rag' to wlExpandPrevRow handles both.
            const isCompare = r.task === 'RAG compare (3 modes)';
            const cardKind = isCompare ? 'rag' : 'llm';
            return '<div style="border-bottom:1px solid var(--panel);padding:0.6rem 0">'
                + '<div style="display:flex;justify-content:space-between;align-items:baseline">'
                + '<span style="color:var(--text);font-size:0.82rem">' + date + '</span>'
                + '<span style="color:var(--text-3);font-size:0.75rem;font-family:monospace">' + r.job_id + '</span></div>'
                + '<div style="color:var(--accent);font-size:0.8rem;margin:0.2rem 0">' + summary + '</div>'
                + '<div style="display:flex;gap:0.75rem;margin-top:0.3rem;align-items:center">'
                + '<a href="javascript:void(0)" '
                + 'onclick="wlExpandPrevRow(\\\'llm\\\',\\\'' + r.job_id + '\\\',\\\'' + savedAt + '\\\',\\\'' + cardKind + '\\\')" '
                + 'style="color:var(--text-3);font-size:0.75rem;text-decoration:none;cursor:pointer">'
                + '<span id="chev-' + r.job_id + '">\u25b8</span> Show full result</a>'
                + '<a href="' + base + '/download.json" download style="color:var(--text-5);font-size:0.75rem;text-decoration:none">\u2193 JSON</a>'
                + '<a href="' + base + '/download.csv" download style="color:var(--text-5);font-size:0.75rem;text-decoration:none">\u2193 CSV</a>'
                + '</div>'
                + '<div id="expand-' + r.job_id + '" style="display:none;margin-top:0.6rem"></div>'
                + '</div>';
        }}).join('');
        el.innerHTML = '<div style="color:var(--text-4);font-size:0.72rem;text-transform:uppercase;'
            + 'letter-spacing:0.05em;margin-bottom:0.75rem">Previous RAG runs</div>' + rows;
    }}

    loadIndexStatus();
    loadPrevRuns();
    const _resumeJob = new URLSearchParams(location.search).get('job');
    if (_resumeJob) {{ pollRag(_resumeJob); }}
    </script>
    {_PROGRESS_JS}
    {_RESULT_JS}
    {_CONF_HELP_WIDGET}
    {_FOOTER}
</body>
</html>""")


@app.get("/rag/index-status", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def rag_index_status():
    return {
        "status": rag_module.index_status,
        "doc_count": rag_module.index_doc_count,
        "error": rag_module.index_error,
    }


@app.get("/rag/corpus-list", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def rag_corpus_list(request: Request):
    """CR-051 — enriched with manifest data + per-row can_delete flag.

    For each PDF, returns origin ("Lab"/"Member"), added_at, plus a boolean
    can_delete tailored to the requesting visitor (Lab: always, Member: own
    only, Anonymous: never). Member usage counters returned for the upload
    form to gate against rag_member_doc_count_cap / rag_member_total_mb_cap.
    """
    docs = rag_module.corpus_list()
    visitor_tier = audience.tier(request).name
    visitor_email = auth.member_email_from_request(request) if visitor_tier == "Member" else None
    manifest = corpus_manifest.load_manifest()
    enriched = []
    for d in docs:
        fn = d.get("rel_path") or d.get("name") or ""
        meta = manifest.get(fn) or corpus_manifest.ensure_entry(fn)
        origin = meta.get("origin", "Lab")
        can_del = corpus_manifest.can_delete(fn, visitor_tier, visitor_email)
        enriched.append({
            **d,
            "origin":      origin,                       # "Lab" | "Member"  (Anonymous never appears as owner)
            "added_at":    meta.get("added_at"),
            "title":       meta.get("title"),            # CR-051 — uploader's optional note/qualifier
            "can_delete":  can_del,
        })
    s = cfg.load()
    return {
        "docs": enriched,
        "total":   len(enriched),
        "indexed": sum(1 for d in enriched if d["indexed"]),
        "visitor_tier": visitor_tier,
        "member_usage": corpus_manifest.member_usage(visitor_email) if visitor_email else None,
        "caps": {
            "per_file_mb":         s["rag_upload_max_mb"],
            "member_doc_count":    s["rag_member_doc_count_cap"],
            "member_total_mb":     s["rag_member_total_mb_cap"],
        },
    }


@app.post("/rag/upload", dependencies=[Depends(requires(RAG_CORPUS_UPLOAD))])
async def rag_upload(request: Request, file: UploadFile = File(...),
                     title: str = Form(None)):
    """CR-051 — Member uploads a PDF to the corpus.

    Hardened upload path: filename sanitised, %PDF- magic-byte sniff, per-file
    size cap, per-Member doc count + total size caps. Lab is uncapped. On
    success the doc is incrementally added to the ChromaDB index (~3-8 s) so
    it's queryable immediately — no full rebuild needed.
    """
    s = cfg.load()
    visitor_tier  = audience.tier(request).name
    visitor_email = auth.member_email_from_request(request) if visitor_tier == "Member" else None
    if visitor_tier == "Member" and not visitor_email:
        return JSONResponse({"error": "session has no member email"}, status_code=403)

    # 1. Read + size-cap (read into memory; 50 MB is fine for RAM).
    max_bytes = int(s["rag_upload_max_mb"]) * 1024 * 1024
    blob = await file.read()
    if len(blob) > max_bytes:
        return JSONResponse({"error": f"file exceeds {s['rag_upload_max_mb']} MB cap "
                             f"({len(blob) // 1024 // 1024} MB)"}, status_code=413)
    if not blob:
        return JSONResponse({"error": "empty file"}, status_code=400)

    # 2. Format validation — dispatch on the sanitised extension.
    #    .pdf → require %PDF- magic header (defends against renamed binaries)
    #    .md  → require UTF-8 + no NUL bytes (defends against binary mislabel)
    # We sanitise the filename here (early) so the extension check is on the
    # same string the rest of the handler will use for everything else.
    pre_safe_name = corpus_manifest.sanitise_filename(file.filename or "upload.pdf")
    ext = pre_safe_name.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        if not blob.startswith(b"%PDF-"):
            return JSONResponse({"error": "not a PDF (missing %PDF- magic header)"},
                                status_code=400)
    elif ext == "md":
        if b"\x00" in blob[:1024]:
            return JSONResponse({"error": "markdown file appears to be binary (NUL bytes in first 1 KB)"},
                                status_code=400)
        try:
            blob.decode("utf-8")
        except UnicodeDecodeError:
            return JSONResponse({"error": "markdown must be UTF-8 encoded"},
                                status_code=400)
    else:
        return JSONResponse({"error": f"unsupported extension .{ext}; allowed: .pdf, .md"},
                            status_code=400)

    # 3. Per-Member quota (Lab uncapped).
    if visitor_tier == "Member":
        usage = corpus_manifest.member_usage(visitor_email)
        if usage["file_count"] >= int(s["rag_member_doc_count_cap"]):
            return JSONResponse({"error": f"member doc count cap reached "
                                 f"({usage['file_count']} / {s['rag_member_doc_count_cap']}) "
                                 f"— delete an old upload first"}, status_code=413)
        max_total = int(s["rag_member_total_mb_cap"]) * 1024 * 1024
        if usage["total_bytes"] + len(blob) > max_total:
            return JSONResponse({"error": f"member total size cap reached "
                                 f"({(usage['total_bytes'] + len(blob)) // 1024 // 1024} MB / "
                                 f"{s['rag_member_total_mb_cap']} MB)"}, status_code=413)

    # 4. Sanitise + write. Auto-suffix on collision so we never overwrite.
    # Re-uses pre_safe_name from step 2 (already extension-dispatched + sanitised).
    safe_name = corpus_manifest.unique_filename(pre_safe_name)
    papers_dir = Path(s["rag_corpus_path"])
    papers_dir.mkdir(parents=True, exist_ok=True)
    target = papers_dir / safe_name
    target.write_bytes(blob)

    # 5. Manifest + audit.
    origin = "Lab" if visitor_tier == "Lab" else "Member"
    actor  = visitor_email if visitor_email else "Lab"
    clean_title = (title or "").strip()[:200] or None   # cap at 200 chars
    corpus_manifest.record_upload(safe_name, added_by=actor, origin=origin,
                                   size_bytes=len(blob), title=clean_title)

    # 6. Incremental index in background (don't block the POST response).
    loop = asyncio.get_event_loop()
    fut = loop.run_in_executor(None, lambda: rag_module.add_doc_to_index(safe_name))
    try:
        idx_result = await asyncio.wait_for(fut, timeout=60)
    except asyncio.TimeoutError:
        idx_result = {"chunks_added": None, "indexed": "still indexing in background"}
    except Exception as e:
        idx_result = {"error": str(e)}
    return {"ok": True, "filename": safe_name, "size_bytes": len(blob),
            "origin": origin, "indexed": idx_result}


@app.get("/rag/doc/{filename:path}", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def rag_doc_view(filename: str):
    """CR-051 follow-up — direct view of a corpus document for the in-page
    preview iframe. Anonymous-readable since the corpus is already publicly
    queryable through /rag/run (so the content isn't private even without
    direct view). Path-traversal guards mirror the DELETE handler.
    """
    safe = os.path.basename(filename)
    if not safe or "/" in safe or ".." in safe:
        return JSONResponse({"error": "invalid filename"}, status_code=400)
    s = cfg.load()
    target = Path(s["rag_corpus_path"]) / safe
    if not target.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    ext = target.suffix.lower()
    media_type = {
        ".pdf": "application/pdf",
        ".md":  "text/markdown; charset=utf-8",
    }.get(ext, "application/octet-stream")
    return FileResponse(
        path=str(target),
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{safe}"'},
    )


@app.delete("/rag/doc/{filename:path}", dependencies=[Depends(requires(RAG_CORPUS_DELETE_OWN))])
async def rag_doc_delete(filename: str, request: Request):
    """CR-051 — Lab: delete any. Member: delete own (ownership in manifest).

    The capability dispatch is bespoke here because the rule mixes tier
    (Lab) with per-row ownership (Member). Routes don't normally compare
    tiers, but this is the cleanest expression of "Lab can do anything,
    Member can only act on their own rows" — the auth check sits in the
    handler because the row data is part of the auth decision.
    """
    visitor_tier  = audience.tier(request).name
    visitor_email = auth.member_email_from_request(request) if visitor_tier == "Member" else None
    if visitor_tier == "Anonymous":
        return JSONResponse({"error": "sign in required"}, status_code=401)
    # Strip path components defensively — the {filename:path} param could
    # otherwise be used to delete `../../etc/passwd` style targets.
    safe_name = os.path.basename(filename)
    if not safe_name or "/" in safe_name or ".." in safe_name:
        return JSONResponse({"error": "invalid filename"}, status_code=400)

    if not corpus_manifest.can_delete(safe_name, visitor_tier, visitor_email):
        return JSONResponse({"error": "not your document (or you're not a member)"},
                            status_code=403)

    s = cfg.load()
    target = Path(s["rag_corpus_path"]) / safe_name
    existed_on_disk = target.exists()
    try:
        if existed_on_disk:
            target.unlink()
    except Exception as e:
        return JSONResponse({"error": f"could not remove file: {e}"}, status_code=500)

    # Remove chunks from the index. Idempotent — safe if the doc was never
    # indexed (e.g. removed before build-index ran).
    try:
        rag_module.remove_doc_from_index(safe_name)
    except Exception:
        pass

    actor = visitor_email if visitor_email else "Lab"
    corpus_manifest.record_delete(safe_name, actor=actor, tier=visitor_tier)
    return {"ok": True, "filename": safe_name, "removed_from_disk": existed_on_disk}


@app.get("/rag/audit", dependencies=[Depends(requires(SETTINGS_READ_FULL))])
async def rag_audit():
    """CR-051 — Lab-only view of the corpus audit log (last 200 events)."""
    return {"events": corpus_manifest.read_audit(limit=200)}


@app.post("/rag/build-index", dependencies=[Depends(requires(RAG_CORPUS_UPLOAD))])
async def rag_build_index(request: Request):
    body = await request.json()
    rebuild = bool(body.get("rebuild", False))
    if rag_module.index_status == "building":
        return {"status": "already_building"}
    loop = asyncio.get_event_loop()
    asyncio.create_task(loop.run_in_executor(None, lambda: rag_module.build_index(rebuild)))
    return {"status": "started"}


@app.post("/rag/run", dependencies=[Depends(requires(RAG_RUN))])
async def rag_run(
    request: Request,
    model_key: str = Form(...),
    rag_mode: str = Form(...),
    question: str = Form(None),
):
    if model_key not in rag_module.MODELS:
        return JSONResponse({"error": "Invalid model"}, status_code=400)
    if rag_mode not in rag_module.TOP_K:
        return JSONResponse({"error": f"Invalid rag_mode (allowed: {list(rag_module.TOP_K.keys())})"}, status_code=400)
    # CR-001 capability dispatch — free-form question → CUSTOM_PROMPT;
    # absent → curated canonical (Anonymous-OK).
    effective_question = question.strip() if question and question.strip() else None
    if effective_question is not None:
        gate(request, CUSTOM_PROMPT)
    else:
        effective_question = curated.CANONICAL_RAG_QUESTION
    if rag_mode != "baseline" and rag_module.index_status != "ready":
        return JSONResponse({"error": "Index not ready — build it first"}, status_code=400)

    job_id = str(uuid.uuid4())[:8]
    label = f"RAG — {rag_module.MODELS[model_key]['label']} · {rag_module.SHORT_MODE_LABELS.get(rag_mode, rag_mode)}"

    async def coro():
        jobs[job_id]["stage"] = "baseline"
        result = await rag_module.run_rag_measurement(model_key, rag_mode, effective_question, jobs, job_id)
        save_result("llm", job_id, result)
        jobs[job_id] = {"stage": "done", "result": result}

    position = queue_control.enqueue(job_id, "rag", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


@app.get("/rag/job/{job_id}", dependencies=[Depends(requires(QUEUE_VIEW))])
async def rag_job_status(job_id: str):
    return _job_status(job_id)


async def run_rag_compare_job(job_id: str, model_key: str, question: str):
    """4-mode RAG compare (baseline / rag / rag_blended / rag_large) on a single model.

    CR-050 alignment (2026-05-27): now uses the same active-probe thermal-floor
    cooldown as /rag/compare-models and /llm/compare-models, and emits explicit
    `stage` transitions per mode so the shared `wlRenderProgress` widget
    can show "Mode 2/3 · baseline" + cooldown progress instead of staying
    frozen on "inference" through the entire cooldown gap.

    Cooldown reference = mode #1's baseline (cold reading captured first).
    """
    from power import cooldown_between_runs, CooldownCancelled
    partial_results = {}
    modes = rag_module.COMPARE_MODES   # single source of truth — see rag.py
    floor_reference_w = None
    cooldowns = []
    try:
        for i, rag_mode in enumerate(modes):
            jobs[job_id]["current_mode"]     = rag_mode
            jobs[job_id]["mode_index"]       = i
            jobs[job_id]["total_modes"]      = len(modes)
            jobs[job_id]["partial_results"]  = dict(partial_results)
            # Inter-mode cooldown — same pattern as the N-model compare flows:
            # actively wait for power to drop back to model #1's cold baseline
            # ±3 W. Otherwise a fast mode after a long one measures a
            # contaminated baseline and the confidence flag goes 🔴.
            if i > 0 and floor_reference_w is not None:
                jobs[job_id]["stage"] = "cooldown"
                cd = await cooldown_between_runs(
                    fixed_seconds=cfg.load().get("llm_rest_s", 10),
                    reference_w=floor_reference_w,
                    stage="cooldown", jobs=jobs, job_id=job_id,
                    allow_dialog=True,
                )
                cooldowns.append({"before_mode": rag_mode, **cd})
            result = await rag_module.run_rag_measurement(
                model_key, rag_mode, question, jobs, job_id)
            partial_results[rag_mode] = result
            jobs[job_id]["partial_results"] = dict(partial_results)
            if floor_reference_w is None:
                floor_reference_w = (result.get("energy") or {}).get("w_base")

        final = {
            "mode": "rag_compare",
            "model_key": model_key,
            "model_label": rag_module.MODELS[model_key]["label"],
            "model_params": rag_module.MODELS[model_key]["params"],
            "question": question,
            "results": partial_results,
            "floor_reference_w": floor_reference_w,
            "cooldowns": cooldowns,
            "scope": "Device layer only (GoS1). Network and CPE excluded. No amortised training cost.",
        }
        save_result("llm", job_id, final)
        jobs[job_id] = {"stage": "done", "result": final}
    except CooldownCancelled:
        jobs[job_id] = {"stage": "cancelled",
                        "error": "Cancelled by operator during cooldown."}
    except Exception as e:
        jobs[job_id] = {"stage": "error", "error": str(e)}


@app.post("/rag/run-compare", dependencies=[Depends(requires(RAG_RUN))])
async def rag_run_compare(
    request: Request,
    model_key: str = Form(...),
    question: str = Form(None),
):
    if model_key not in rag_module.MODELS:
        return JSONResponse({"error": "Invalid model"}, status_code=400)
    # CR-001 capability dispatch — free-form 3-mode compare with a custom
    # question is BATCH_COMPARE (it crosses both axes: free-form input AND
    # multi-mode sweep); absent question falls back to curated, Anonymous-OK.
    effective_question = question.strip() if question and question.strip() else None
    if effective_question is not None:
        gate(request, BATCH_COMPARE)
    else:
        effective_question = curated.CANONICAL_RAG_QUESTION
    if rag_module.index_status != "ready":
        return JSONResponse({"error": "Index not ready — build it first"}, status_code=400)

    job_id = str(uuid.uuid4())[:8]
    label = f"RAG Compare — {rag_module.MODELS[model_key]['label']} · 3 modes"

    async def coro():
        await run_rag_compare_job(job_id, model_key, effective_question)

    position = queue_control.enqueue(job_id, "rag", label, coro, request=request,
                                     page="/rag/compare")
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


# --- CR-049 · /rag compare-across-models (sibling of /llm/compare) ---
# One corpus-grounded question × all 4 panel models, graded against a
# user-supplied expected answer. Same energy-per-correct-answer headline
# as /llm/compare; here the wrong-answer story has an extra dimension —
# the model can be wrong because *retrieval* surfaced the wrong chunk,
# not because the model is bad. Probe at /tmp/rag_probe/.

async def run_rag_compare_models_job(job_id: str, question: str, expected: str):
    """Sequentially run question through RAG (top-3) across every model in rag.MODELS, grade, save.

    Panel = list(rag_module.MODELS.keys()) so adding/swapping a model in
    rag.py is automatically reflected on /rag/compare.
    """
    panel = list(rag_module.MODELS.keys())
    from power import cooldown_between_runs, CooldownCancelled
    from llm import unload_all_loaded_models
    try:
        jobs[job_id].update({
            "status": "running", "stage": "compare_models",
            "total_models": len(panel), "current_model_idx": 0,
            "partial_response": "",
        })
        # Clear VRAM before measuring model #1's cold reference (see /llm/compare).
        unloaded = unload_all_loaded_models()
        if unloaded:
            await asyncio.sleep(2)
        rows = []
        floor_reference_w = None
        cooldowns = []
        for idx, model_key in enumerate(panel, start=1):
            if idx > 1 and floor_reference_w is not None:
                # Same Ollama keep_alive issue as /llm/compare — unload every
                # previously-run model before waiting for the thermal floor,
                # else the wait times out chasing a floor that 11+ GB of
                # resident VRAM is permanently inflating.
                evicted = unload_all_loaded_models()
                jobs[job_id]["stage"] = "cooldown"
                jobs[job_id]["current_model_idx"] = idx
                jobs[job_id]["current_model"] = model_key
                jobs[job_id]["current_model_label"] = rag_module.MODELS[model_key]["label"]
                if evicted:
                    await asyncio.sleep(3)
                cd = await cooldown_between_runs(
                    fixed_seconds=cfg.load().get("llm_rest_s", 10),
                    reference_w=floor_reference_w,
                    stage="cooldown", jobs=jobs, job_id=job_id,
                    allow_dialog=True,
                )
                cd["evicted_before_wait"] = evicted
                cooldowns.append({"before_model": model_key, **cd})
            jobs[job_id]["current_model_idx"] = idx
            jobs[job_id]["current_model"] = model_key
            jobs[job_id]["current_model_label"] = rag_module.MODELS[model_key]["label"]
            try:
                m_result = await rag_module.run_rag_measurement(
                    model_key, "rag", question, jobs, job_id,
                )
                if floor_reference_w is None:
                    floor_reference_w = (m_result.get("energy") or {}).get("w_base")
                inf = m_result.get("inference") or {}
                en = m_result.get("energy") or {}
                resp = inf.get("response", "") or ""
                ok = llm_grade(expected, resp)
                rows.append({
                    "model_key": model_key,
                    "model_label": rag_module.MODELS[model_key]["label"],
                    "params": rag_module.MODELS[model_key]["params"],
                    "response": resp,
                    "output_tokens": inf.get("output_tokens"),
                    "duration_s": inf.get("duration_s"),
                    "tokens_per_sec": inf.get("tokens_per_sec"),
                    "delta_w": en.get("delta_w"),
                    "delta_e_wh": en.get("delta_e_wh"),
                    "mwh_per_token": en.get("mwh_per_token"),
                    "confidence": en.get("confidence"),
                    "chunks_retrieved": m_result.get("chunks_retrieved"),
                    "chunk_sources": m_result.get("chunk_sources"),
                    "correct": ok,
                })
            except Exception as e:
                rows.append({
                    "model_key": model_key,
                    "model_label": rag_module.MODELS.get(model_key, {}).get("label", model_key),
                    "params": rag_module.MODELS.get(model_key, {}).get("params", "?"),
                    "error": str(e), "correct": False,
                })

        correct = [r for r in rows if r.get("correct") and (r.get("delta_e_wh") or 0) > 0]
        cheapest = min(correct, key=lambda r: r["delta_e_wh"]) if correct else None
        final = {
            "mode": "rag_compare_models",
            "question": question,
            "expected": expected,
            "models": rows,
            "cheapest_correct_key": cheapest["model_key"] if cheapest else None,
            "panel_pass_rate": round(len(correct) / len(rows), 3) if rows else 0,
            "floor_reference_w": floor_reference_w,
            "cooldowns": cooldowns,
            "scope": "Device layer only (GoS1). Network and CPE excluded. No amortised training cost. Retrieval = top-3 chunks (rag mode).",
        }
        save_result("llm", job_id, final)
        jobs[job_id] = {"status": "done", "stage": "done", "result": final}
    except CooldownCancelled:
        jobs[job_id] = {"status": "cancelled", "stage": "cancelled",
                        "error": "Cancelled by operator during cooldown."}
    except Exception as e:
        jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}


@app.post("/rag/compare-models", dependencies=[Depends(requires(BATCH_COMPARE))])
async def rag_compare_models(
    request: Request,
    question: str = Form(...),
    expected: str = Form(...),
):
    """Member 'Try your own question' for the RAG energy-per-correct-answer card."""
    question = (question or "").strip()
    expected = (expected or "").strip()
    if not question:
        return JSONResponse({"error": "question is required"}, status_code=400)
    if not expected:
        return JSONResponse({"error": "expected answer is required (grading needs ground truth)"},
                            status_code=400)
    if len(question) > 2000:
        return JSONResponse({"error": "question too long (max 2000 chars)"}, status_code=400)
    if rag_module.index_status != "ready":
        return JSONResponse({"error": "Index not ready — build it first"}, status_code=400)

    job_id = str(uuid.uuid4())[:8]
    label = f"RAG Compare · {question[:50]}{'…' if len(question) > 50 else ''}"

    async def coro():
        await run_rag_compare_models_job(job_id, question, expected)

    position = queue_control.enqueue(job_id, "rag", label, coro, request=request,
                                     page="/rag/compare")
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


# Hardcoded showcase data from the 2026-05-26 RAG probe — 1 rep per cell,
# real P110 measurement (not estimated). The probe tried 3 corpus-grounded
# prompts × 4 models; only this BBC prompt had a 4/4 panel pass rate. The
# two IEA candidates failed across the panel because top-3 retrieval missed
# the right pages of the 250-page IEA report — a finding worth keeping for
# a future "retrieval-precision matters" demo, but not a clean showcase.
# Probe data: /tmp/rag_probe/results_20260526_223406.jsonl
#
# NOTE (2026-05-27 — S30 ladder refresh): the rows below reference the
# PREVIOUS panel — `mistral` (7B) and `gemma3:12b` were retired in favour
# of `qwen3:4b` and `mistral-nemo:12b`. Real-P110 measurements preserved
# as a historical snapshot; a re-probe of the new 5-model panel via
# /rag/compare-models is the planned follow-up that will replace this dict.
_RAG_COMPARE_SHOWCASE = {
    'rag_bbc_total': {
        'label': 'BBC Radio 2018 energy total',
        'prompt': "According to the BBC Radio energy footprint paper (WHP 393), what was the total mean energy consumption for the 2018 baseline of BBC radio? Output the value and unit, e.g. '325 GWh'.",
        'expected': '325 GWh',
        'tagline': 'Single corpus fact, single right answer. Retrieval surfaces BBC WHP 393 for every model; the energy spread is purely the cost of inference at different model sizes.',
        'source_paper': 'BBC WHP 393 — Energy Footprint of Radio Services',
        'rows': [
            {'model': 'tinyllama',        'params': '1.1B', 'ok': True, 'ans': 'The BBC Radio energy footprint paper (WHP 393) reported that in 2018, the total mean energy consumption for the BBC radio system was 325 GW…',   'tok': 236, 'wall': 1.56,  'wh_measured': 0.0080, 'flag': '🟡'},
            {'model': 'qwen3:1.7b',       'params': '1.7B', 'ok': True, 'ans': 'The total mean energy consumption for BBC radio services in 2018, as stated in the document, was **325 GWh** (Gigawatt-hours). This value i…',  'tok': 426, 'wall': 4.29,  'wh_measured': 0.1179, 'flag': '🟡'},
            {'model': 'qwen3:4b',         'params': '4B',   'ok': True, 'ans': 'Based on the provided excerpts from the BBC Energy Footprint report (WHP 393), the total mean energy consumption for BBC radio services in…',  'tok': 652, 'wall': 9.54,  'wh_measured': 0.4553, 'flag': '🟢'},
            {'model': 'qwen3:8b',         'params': '8B',   'ok': True, 'ans': 'The total mean energy consumption for the BBC Radio services in 2018 was **325 GWh**. This figure is explicitly stated in the document and…', 'tok': 438, 'wall': 10.86, 'wh_measured': 0.6035, 'flag': '🟢'},
            {'model': 'mistral-nemo:12b', 'params': '12B',  'ok': True, 'ans': 'According to the BBC Radio energy footprint paper (page 19), the total mean energy consumption for the 2018 baseline of BBC radio was 325 G…', 'tok': 39,  'wall': 4.90,  'wh_measured': 0.0740, 'flag': '🟡'},
            {'model': 'phi4',             'params': '14B',  'ok': True, 'ans': 'According to the BBC Radio energy footprint paper, the total mean energy consumption for the 2018 baseline of BBC radio services was 325 GW…','tok': 62,  'wall': 4.88,  'wh_measured': 0.0801, 'flag': '🟡'},
            {'model': 'gpt-oss:20b',      'params': '20B',  'ok': True, 'ans': '325 GWh',                                                                                                                                  'tok': 141, 'wall': 12.34, 'wh_measured': 0.3739, 'flag': '🟢'},
        ],
    },
}


@app.get("/rag/compare", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def rag_compare_page(request: Request):
    """Hybrid showcase + member 'Try your own question' for RAG energy-per-correct-answer.

    Anonymous: BBC showcase card (4 models, real P110 data from the probe).
    Member (BATCH_COMPARE): question + expected-answer inputs → runs across all
    4 RAG-panel models sequentially with P110 measurement, renders into the
    same card.
    """
    can_batch = can(audience.tier(request), BATCH_COMPARE)
    lk_batch_class = _lock_class(request, BATCH_COMPARE)
    lk_batch_badge = _lock_badge_html(request, BATCH_COMPARE,
                                      "Try your own question — Members only")
    dis_batch = _disabled_attr(request, BATCH_COMPARE)

    import json as _json
    showcase_js = _json.dumps(_RAG_COMPARE_SHOWCASE)
    panel_n     = len(rag_module.MODELS)
    panel_list  = " &middot; ".join(f"{m['label']} ({m['params']})" for m in rag_module.MODELS.values())
    size_order_js = _json.dumps([m["params"] for m in rag_module.MODELS.values()])

    return _bake_durations(f"""<!DOCTYPE html>
<html>
<head>
    <link rel="icon" type="image/svg+xml" href="/static/owl.svg">
    <title>OWL — RAG · Compare across models</title>
    <script src="{CHARTJS_URL}"></script>
    <script src="/static/wl-charts.js"></script>
    <style>
        *{{box-sizing:border-box;margin:0;padding:0}}
        body{{font-family:monospace;background:var(--bg);color:var(--text);
              max-width:920px;margin:0 auto;padding:2rem}}
        h1{{color:var(--accent);font-size:1.6rem;margin-bottom:0.25rem}}
        .subtitle{{color:var(--text-3);font-size:0.8rem;margin-bottom:1.5rem}}
        .demo-tabs{{display:flex;gap:0.5rem;margin-bottom:1.25rem;flex-wrap:wrap}}
        .demo-tabs button{{background:none;color:var(--text-3);border:1px solid var(--border-3);
                           padding:0.5rem 0.9rem;cursor:pointer;font-family:monospace;font-size:0.78rem;margin:0}}
        .demo-tabs button:hover{{border-color:var(--accent);color:var(--text)}}
        .demo-tabs button.active{{border-color:var(--accent);color:var(--accent);background:var(--accent-soft)}}
        .prompt-card{{border:1px solid var(--border);padding:1rem 1.25rem;margin-bottom:1.25rem;
                      background:var(--panel-2)}}
        .label-sm{{color:var(--text-5);font-size:0.65rem;text-transform:uppercase;
                   letter-spacing:0.06em;margin-bottom:0.5rem}}
        .prompt-text{{color:var(--text-2);font-size:0.95rem;line-height:1.5}}
        .prompt-meta{{margin-top:0.6rem;color:var(--text-3);font-size:0.78rem}}
        .prompt-meta b{{color:var(--accent)}}
        .hero{{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1.25rem}}
        @media(max-width:640px){{.hero{{grid-template-columns:1fr}}}}
        .hero-card{{border:1px solid var(--border);padding:1.1rem;background:var(--panel-2)}}
        .hero-card .big{{color:var(--accent);font-size:2rem;font-weight:bold;line-height:1.1}}
        .hero-card .sub{{color:var(--text-3);font-size:0.78rem;margin-top:0.4rem;line-height:1.5}}
        .hero-card.warn .big{{color:var(--warn);font-size:1rem;line-height:1.4}}
        .hero-card.warn{{border-color:var(--warn)}}
        table{{width:100%;border-collapse:collapse;font-size:0.8rem;margin-bottom:1.25rem}}
        th{{text-align:left;padding:0.5rem 0.6rem;color:var(--text-4);
            border-bottom:1px solid var(--border-3);font-weight:normal;
            text-transform:uppercase;letter-spacing:0.05em;font-size:0.68rem}}
        th.num,td.num{{text-align:right;font-variant-numeric:tabular-nums}}
        td{{padding:0.6rem;border-bottom:1px solid var(--border-2);vertical-align:middle}}
        tr.correct td.model,tr.correct td.answer{{color:var(--text)}}
        tr.wrong td.model,tr.wrong td.answer{{color:var(--text-4)}}
        tr.noisy td{{color:var(--text-4)!important}}
        tr.noisy td.model{{color:var(--text-3)!important;font-style:italic}}
        tr.noisy{{background:transparent!important}}
        td.answer{{max-width:340px}}
        .answer-wrap{{max-height:5.5em;overflow-y:auto;white-space:pre-wrap;word-break:break-word;
                      line-height:1.45;padding-right:0.25rem;scrollbar-width:thin;
                      scrollbar-color:var(--border-3) transparent}}
        .answer-wrap::-webkit-scrollbar{{width:6px}}
        .answer-wrap::-webkit-scrollbar-thumb{{background:var(--border-3);border-radius:3px}}
        tr.cheapest{{background:var(--accent-soft)}}
        tr.cheapest td.model{{color:var(--accent);font-weight:bold}}
        .pill{{display:inline-block;font-size:0.7rem;padding:0.1rem 0.45rem;border-radius:2px}}
        .pill.ok{{color:var(--accent);border:1px solid var(--accent)}}
        .pill.bad{{color:var(--err);border:1px solid var(--err)}}
        .answer-q{{color:var(--text-3);font-style:italic}}
        .crown{{color:var(--accent)}}
        .ratio{{color:var(--accent);font-weight:bold}}
        .headline{{border-left:3px solid var(--accent);padding:0.9rem 1.1rem;margin-bottom:1.5rem;
                   background:var(--panel-2);color:var(--text-2);line-height:1.7;font-size:0.88rem}}
        .headline b{{color:var(--accent)}}
        .try{{margin-top:2rem;padding-top:1.5rem;border-top:1px solid var(--border)}}
        .try h2{{color:var(--accent);font-size:1.05rem;margin-bottom:0.4rem}}
        .try .desc{{color:var(--text-3);font-size:0.82rem;margin-bottom:1rem;line-height:1.6}}
        textarea,input[type=text]{{width:100%;background:#0f0f0f;border:1px solid var(--border-3);
                                    border-left:2px solid #00ff9966;color:var(--text-2);
                                    font-family:monospace;font-size:0.85rem;padding:0.75rem;
                                    resize:vertical}}
        textarea:focus,input[type=text]:focus{{border-color:var(--accent);outline:none}}
        button.run{{background:var(--accent);color:#000;border:none;padding:0.75rem 2rem;
                    cursor:pointer;font-family:monospace;font-size:0.95rem;margin-top:0.85rem}}
        button.run:disabled{{background:var(--border);color:var(--text-3);cursor:not-allowed}}
        button.run:hover:not(:disabled){{background:var(--accent-hover)}}
        a.back{{color:var(--text-3);text-decoration:none;font-size:0.82rem;
                display:inline-block;margin-top:2rem}}
        a.back:hover{{color:var(--accent)}}
        details{{margin-top:1.5rem;color:var(--text-3);font-size:0.78rem;
                 border-top:1px solid var(--border);padding-top:1rem}}
        summary{{cursor:pointer;color:var(--text-3)}}
        summary:hover{{color:var(--accent)}}
        details p{{margin-top:0.5rem;line-height:1.6}}
        .upload-note{{margin-top:1rem;padding:0.75rem 1rem;border:1px dashed var(--border-3);
                      background:var(--panel-2);font-size:0.78rem;color:var(--text-3);line-height:1.5}}
        .upload-note b{{color:var(--text-2)}}
        {_LOCK_STYLES}
    </style>
</head>
<body>
    {_BACK}<a href="/rag" style="color:var(--text-3);text-decoration:none;font-size:0.82rem;
        margin-left:0.75rem;margin-bottom:1.5rem;display:inline-block;
        vertical-align:middle;position:relative;top:-2px;transition:color 0.2s"
        onmouseover="this.style.color='#00ff99'" onmouseout="this.style.color='#777'">&larr; /rag</a>
    <h1>RAG &middot; Compare across models</h1>
    <div class="subtitle">Energy cost of correct answers from the corpus. Device layer only (GoS1). Network and CPE excluded.</div>

    <div class="demo-tabs" id="tabs"></div>

    <div class="prompt-card">
        <div class="label-sm">Question</div>
        <div class="prompt-text" id="prompt-text"></div>
        <div class="prompt-meta">Expected: <b id="expected"></b> &middot; Retrieval: top-3 chunks &middot; Source: <span id="source-paper" style="color:var(--text-2)"></span></div>
    </div>

    <div class="hero">
        <div class="hero-card" id="hero-cheap">
            <div class="label-sm">Cheapest correct answer</div>
            <div class="big" id="hero-cheap-big"></div>
            <div class="sub" id="hero-cheap-sub"></div>
        </div>
        <div class="hero-card warn" id="hero-bust">
            <div class="label-sm">The size &ne; smarts finding</div>
            <div class="big" id="hero-bust-big"></div>
            <div class="sub" id="hero-bust-sub"></div>
        </div>
    </div>

    <div class="label-sm">Same question, all models &mdash; ranked by energy of a correct answer</div>
    <table>
        <thead>
            <tr><th>model</th><th>answer</th><th>&#10003;/&#10007;</th><th>conf</th>
                <th class="num">tokens</th><th class="num">wall</th>
                <th class="num">mWh/tok</th><th class="num">Wh</th>
                <th class="num">vs best</th></tr>
        </thead>
        <tbody id="rows"></tbody>
    </table>

    <div class="headline" id="headline"></div>

    <div id="charts-wrap" style="margin-bottom:1.5rem;display:none">
        <div class="label-sm">Energy vs model size (correct answers only) <span id="charts-source" style="color:var(--text-5)"></span></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
            <div style="border:1px solid var(--border);padding:0.75rem;background:var(--panel-2)">
                <div style="color:var(--text-3);font-size:0.7rem;text-align:center;margin-bottom:0.25rem">Total Wh per correct answer</div>
                <div style="position:relative;height:240px"><canvas id="chart-wh"></canvas></div>
            </div>
            <div style="border:1px solid var(--border);padding:0.75rem;background:var(--panel-2)">
                <div style="color:var(--text-3);font-size:0.7rem;text-align:center;margin-bottom:0.25rem">mWh per output token</div>
                <div style="position:relative;height:240px"><canvas id="chart-mwh"></canvas></div>
            </div>
        </div>
        <div id="charts-note" style="color:var(--text-5);font-size:0.72rem;margin-top:0.5rem;line-height:1.5"></div>
    </div>
    <div id="charts-hint" style="margin-bottom:1.5rem;color:var(--text-5);font-size:0.78rem;
         border-left:2px solid var(--border);padding-left:0.85rem;display:none">
        Energy-vs-size plot appears when at least 3 models answer correctly.
    </div>

    {lk_batch_badge}
    <div class="try {lk_batch_class}">
        <h2>Try your own question</h2>
        <div class="desc">
            Runs your question across all {panel_n} RAG-panel models sequentially with P110 power measurement.
            Each model retrieves the top 3 chunks from the corpus (94 papers) before answering. Between models the runner actively polls power and waits for the system to return to within &plusmn;3 W of model #1's baseline (max 120 s cap), so a verbose model's heat can't skew the next baseline.
        </div>
        <div class="label-sm">Question</div>
        <textarea id="userQuestion" rows="3"{dis_batch}
            placeholder="e.g. According to the IEA Energy and AI report, what is the projected global data centre electricity consumption in 2030, in TWh?"></textarea>
        <div class="label-sm" style="margin-top:0.85rem">Expected answer (used to grade &#10003;/&#10007;)</div>
        <input type="text" id="userExpected"{dis_batch}
            placeholder="e.g. 945">
        <div class="label-sm" style="margin-top:0.5rem;color:var(--text-5)">
            Substring match, case-insensitive (with a punctuation-stripped retry). For numeric answers, leading-integer match.
        </div>
        <button class="run" id="runBtn" onclick="runCompare()"{dis_batch}>Run on all {panel_n} models &rarr;</button>
        <div id="run-status" style="margin-top:1.25rem"></div>
        <div class="upload-note">
            <b>Want to ask about a document we don't have?</b> Document upload is coming in a future release.
            The current corpus is 94 curated papers covering streaming energy, network infrastructure, AI/data-centre energy,
            and policy. Until upload ships, the only path is to drop a PDF into the server's <code>corpus/papers/</code>
            directory and rebuild the index &mdash; ask the GoS team.
        </div>
    </div>

    <details>
        <summary>Methodology &amp; scope</summary>
        <p><b>What's measured:</b> {meter_display_name()} wall-power at 1 Hz, baseline before each model (10 polls), &Delta;W &times; &Delta;t &rarr; Wh, mWh/output_token, Traffic Light Confidence per the CR-028 CI model. Same protocol as the existing /rag endpoint.</p>
        <p><b>Why "Wh per correct answer" is the headline:</b> mWh/token rewards verbose models &mdash; a model that "thinks out loud" looks more efficient per token than a model that answers in 1 token, even when it burned 100&times; the energy. The headline metric is the energy cost of <em>correctness</em>. mWh/token stays as a supporting column because it's the canonical operator-facing figure.</p>
        <p><b>RAG-specific wrong-answer story:</b> A model can be wrong because retrieval gave it the wrong chunk (so the answer was generated from training memory, with no anchor), or because it was right but couldn't extract. The 2026-05-26 probe found two IEA prompts where all 4 models failed because top-3 retrieval missed the right pages of the 250-page IEA report &mdash; a finding the energy data makes vivid: you can burn watts producing wrong answers from bad retrieval.</p>
        <p><b>{panel_n}-model panel:</b> {panel_list}. All on GoS1 (Ryzen 9 7900 + RX 7800 XT, Ollama 0.20.2). Panel reflects the current <code>rag.MODELS</code> dict; the BBC showcase card is frozen on the older 4-model probe and will be re-baselined when a fresh probe of the new panel runs.</p>
        <p><b>Grading:</b> Same tolerant rule as /llm/compare &mdash; substring match (case-insensitive) or punctuation-stripped substring or leading-integer match.</p>
    </details>

    <a class="back" href="/rag">&larr; /rag (single-model + 3-mode compare)</a>

    <script>
    const SHOWCASE = {showcase_js};
    const CAN_BATCH = {('true' if can_batch else 'false')};
    const wh = w => Math.round((w * 25 / 3600) * 10000) / 10000;
    let pollTimer = null;
    let chartWh = null, chartMwh = null;
    // CR-050 follow-up — local ticker so the cooldown counter feels smooth
    // even though the server-side poll only writes a fresh cooldown_waited_s
    // every 1 s and the UI only polls /job/{id} every 2 s.
    let cooldownTicker = null;
    let cooldownState = null;
    let cooldownLog = [];   // finished inter-model waits, persisted across stages

    function stopCooldownTicker() {{
        if (cooldownTicker) {{ clearInterval(cooldownTicker); cooldownTicker = null; }}
        cooldownState = null;
    }}

    function renderRunStatus() {{
        const s = cooldownState;
        if (!s) return;
        const msg = s.stage === 'queued'
            ? 'In queue (position ' + (s.qpos || '?') + ')…'
            : (s.mi && s.mt
                ? 'Model ' + s.mi + '/' + s.mt + (s.ml ? ' — ' + s.ml : '') + ' · ' + s.stage
                : 'Running… ' + s.stage);
        const watts = s.watts != null ? ' · ' + Number(s.watts).toFixed(1) + ' W' : '';
        let cdInfo = '';
        if (s.stage === 'cooldown' && s.cdWaited != null) {{
            const liveS = s.cdWaited + (Date.now() - s.cdLocalStart) / 1000;
            const ref = s.cdRef != null ? Number(s.cdRef).toFixed(1) + 'W' : '?';
            cdInfo = ' · waiting ' + liveS.toFixed(1) + 's for floor (target ≤ ' + ref + ' +3W)';
        }}
        let logInfo = '';
        if (cooldownLog.length) {{
            logInfo = '<div style="color:var(--text-4);font-size:0.72rem;margin-top:0.25rem">'
                    + '⏳ Cooldowns done: '
                    + cooldownLog.map(function(w) {{ return Number(w).toFixed(0) + 's'; }}).join(' · ')
                    + '</div>';
        }}
        const el = document.getElementById('run-status');
        if (el) el.innerHTML =
            '<div style="color:var(--warn);font-size:0.85rem">' + msg + watts + cdInfo + '</div>' + logInfo;
    }}

    const tabs = document.getElementById('tabs');
    const order = Object.keys(SHOWCASE);
    order.forEach(k => {{
        const b = document.createElement('button');
        b.textContent = SHOWCASE[k].label;
        b.id = 'tab-' + k;
        b.onclick = () => renderShowcase(k);
        tabs.appendChild(b);
    }});

    function paramsToNumeric(p) {{
        return parseFloat(String(p).replace(/[^\\d.]/g, '')) || 0;
    }}

    function renderShowcase(key) {{
        const d = SHOWCASE[key];
        order.forEach(k => document.getElementById('tab-'+k).classList.toggle('active', k === key));
        // Showcase uses real measured Wh per row (probe data), not the wall × 25W estimate.
        // Prefer per-row wh_measured (real P110 from showcase regeneration);
        // fall back to legacy parallel array d.wh_measured[i] if a row lacks
        // its own value, then to wall × 25 W estimate.
        const measured = d.wh_measured || [];
        const rows = d.rows.map((r, i) => ({{...r, whEst: (r.wh_measured != null ? r.wh_measured
                                                            : (i < measured.length ? measured[i] : wh(r.wall)))}}));
        document.getElementById('source-paper').textContent = d.source_paper || '—';
        renderCompareCard({{
            promptText: d.prompt, expected: d.expected,
            rows: rows, tagline: d.tagline, sourceLabel: 'Showcase (P110 measured)',
        }});
    }}

    function renderCompareCard(payload) {{
        document.getElementById('prompt-text').textContent = payload.promptText;
        document.getElementById('expected').textContent = payload.expected;

        const TRUSTED = new Set(['🟢','🟡']);
        const isTrust = r => TRUSTED.has(r.flag || '🟢');
        const correct = payload.rows.filter(r => r.ok).sort((a,b) => a.whEst - b.whEst);
        const wrong   = payload.rows.filter(r => !r.ok).sort((a,b) => a.whEst - b.whEst);
        const sorted  = [...correct, ...wrong];
        // 🔴 rows are visible in the table but excluded from the cheapest-correct
        // pick, the bust-card pick, and the chart — their delta_w sits inside the
        // baseline noise so a tiny Wh is just measurement noise, not efficiency.
        const trustedCorrect = correct.filter(r => isTrust(r) && r.whEst > 0);
        const cheapest = trustedCorrect[0] || null;

        if (cheapest) {{
            document.getElementById('hero-cheap-big').textContent = cheapest.whEst.toFixed(4) + ' Wh';
            document.getElementById('hero-cheap-sub').innerHTML =
                '<b style="color:var(--accent)">' + cheapest.model.replace(':latest','') + '</b> &middot; ' +
                cheapest.params + ' &middot; ' + cheapest.tok + ' tokens &middot; ' + cheapest.wall.toFixed(2) + 's';
        }} else {{
            document.getElementById('hero-cheap-big').textContent = '—';
            document.getElementById('hero-cheap-sub').textContent = 'No model in the panel got it right — likely a retrieval miss.';
        }}

        const sizeOrder = {size_order_js};
        const sIdx = p => sizeOrder.indexOf(p);
        let bustHead = '', bustDetail = '';
        const biggerWrong = payload.rows.filter(r => !r.ok && cheapest && sIdx(r.params) > sIdx(cheapest.params));
        if (biggerWrong.length) {{
            const bw = biggerWrong[biggerWrong.length-1];
            bustHead = bw.model.replace(':latest','') + ' (' + bw.params + ') was wrong; ' +
                       cheapest.model.replace(':latest','') + ' (' + cheapest.params + ') was right';
            bustDetail = 'A larger model (' + bw.params + ') failed while a smaller one (' + cheapest.params + ') succeeded. On RAG, this often means the smaller model trusted the retrieved chunk while the larger one hallucinated past it.';
        }} else if (cheapest && trustedCorrect.length > 1) {{
            const priciest = trustedCorrect[trustedCorrect.length-1];
            const ratio = (priciest.whEst / cheapest.whEst).toFixed(1);
            bustHead = 'Same answer, ' + ratio + '&times; more energy';
            bustDetail = priciest.model.replace(':latest','') + ' (' + priciest.params + ') and ' + cheapest.model.replace(':latest','') + ' (' + cheapest.params + ') both retrieved the same chunks and answered correctly &mdash; the larger model used ' + ratio + '&times; the energy for the same output.';
        }} else {{
            bustHead = 'No size-vs-smarts split on this question';
            bustDetail = payload.tagline || '';
        }}
        document.getElementById('hero-bust-big').innerHTML = bustHead;
        document.getElementById('hero-bust-sub').innerHTML = bustDetail;

        const tbody = document.getElementById('rows');
        tbody.innerHTML = '';
        sorted.forEach(r => {{
            const tr = document.createElement('tr');
            const flag = r.flag || '🟢';
            const trusted = isTrust(r);
            tr.className = r.ok ? (trusted ? 'correct' : 'correct noisy') : 'wrong';
            if (r === cheapest) tr.classList.add('cheapest');
            // 🔴 rows: hide the ratio (it would compare noise to signal)
            const ratio = r.ok && trusted && cheapest ? (r.whEst / cheapest.whEst).toFixed(1) + '&times;' :
                          (r.ok && !trusted ? '<span title="noisy reading, see conf column">&mdash;</span>' : '&mdash;');
            const crown = (r === cheapest) ? ' <span class="crown">&#9733;</span>' : '';
            // A negative mWh/token means the task drew below the measured idle
            // floor — a sign-flipped noise artifact on a sub-floor model, and
            // always a 🔴 row. Show an em-dash (with a hover note) instead of a
            // misleading negative; the confidence column already carries the 🔴.
            const mwhTok = (r.tok > 0 && r.whEst > 0)
                ? (r.whEst * 1000 / r.tok).toFixed(2)
                : (r.whEst <= 0
                    ? '<span title="energy below measurement floor — not distinguishable from idle">&mdash;</span>'
                    : '&mdash;');
            tr.innerHTML =
                '<td class="model">' + escapeHTML(r.model.replace(':latest','')) +
                  ' <span style="color:var(--text-5);font-size:0.7rem">(' + r.params + ')</span>' + crown + '</td>' +
                '<td class="answer ' + (r.ok ? '' : 'answer-q') + '"><div class="answer-wrap">' + escapeHTML(String(r.ans)) + '</div></td>' +
                '<td>' + (r.ok ? '<span class="pill ok">&#10003;</span>' : '<span class="pill bad">&#10007;</span>') + '</td>' +
                '<td title="Traffic Light Confidence (CR-028) — 🟢 repeatable, 🟡 weak, 🔴 unreliable / contamination">' + flag + '</td>' +
                '<td class="num">' + (r.tok != null ? r.tok : '&mdash;') + '</td>' +
                '<td class="num">' + (r.wall != null ? r.wall.toFixed(2) + 's' : '&mdash;') + '</td>' +
                '<td class="num" style="color:var(--text-4)">' + mwhTok + '</td>' +
                '<td class="num">' + r.whEst.toFixed(4) + '</td>' +
                '<td class="num">' + ratio + '</td>';
            tbody.appendChild(tr);
        }});

        let h = '';
        if (cheapest) {{
            h = '<b>' + cheapest.model.replace(':latest','') + ' (' + cheapest.params + ')</b>' +
                ' produced the correct answer for <b>' + cheapest.whEst.toFixed(4) + ' Wh</b>.';
            if (trustedCorrect.length > 1) {{
                const priciest = trustedCorrect[trustedCorrect.length-1];
                const ratio = (priciest.whEst / cheapest.whEst).toFixed(1);
                h += ' The most expensive correct run (' + priciest.model.replace(':latest','') + ') used <span class="ratio">' + ratio + '&times; more energy</span> for the same answer.';
            }}
        }} else {{
            h = 'No model in the panel got this question right at all &mdash; check whether the retrieved chunks actually contained the answer (top-3 retrieval can miss in a long source).';
        }}
        document.getElementById('headline').innerHTML =
            '<div class="label-sm">What this tells you</div>' + h +
            ' <span style="color:var(--text-5)">[' + payload.sourceLabel + ']</span>';

        renderCharts(payload);
    }}

    function renderCharts(payload) {{
        const wrap = document.getElementById('charts-wrap');
        const hint = document.getElementById('charts-hint');
        const TRUSTED = new Set(['🟢','🟡']);
        // Plot only ✓ AND not 🔴 AND positive Wh — same filter the
        // 'cheapest correct' card uses; we don't want noisy points
        // distorting the energy-vs-size curve.
        const correct = payload.rows.filter(r => r.ok && TRUSTED.has(r.flag || '🟢') && r.whEst > 0);
        if (correct.length < 3) {{
            wrap.style.display = 'none';
            hint.style.display = '';
            if (chartWh) {{ chartWh.destroy(); chartWh = null; }}
            if (chartMwh) {{ chartMwh.destroy(); chartMwh = null; }}
            return;
        }}
        hint.style.display = 'none';
        wrap.style.display = '';

        document.getElementById('charts-source').textContent = '· ' + payload.sourceLabel;
        const wrong = payload.rows.filter(r => !r.ok);
        const noteParts = ['Plotting ' + correct.length + ' of ' + payload.rows.length + ' models that produced the correct answer.'];
        if (wrong.length) {{
            noteParts.push((wrong.length === 1 ? '1 model' : wrong.length + ' models') +
                           ' excluded for incorrect answers (' +
                           wrong.map(r => r.model.replace(':latest','')).join(', ') + ').');
        }}
        document.getElementById('charts-note').textContent = noteParts.join(' ');

        const sorted = [...correct].sort((a,b) => paramsToNumeric(a.params) - paramsToNumeric(b.params));
        const whPoints = sorted.map(r => ({{x: paramsToNumeric(r.params), y: r.whEst}}));
        const mwhPoints = sorted.map(r => {{
            const tok = r.tok || 0;
            return {{x: paramsToNumeric(r.params), y: tok > 0 ? (r.whEst * 1000 / tok) : 0}};
        }});

        if (chartWh) {{ chartWh.destroy(); chartWh = null; }}
        chartWh = WlCharts.line({{
            canvas: document.getElementById('chart-wh'),
            datasets: [{{label: 'Wh per correct answer', points: whPoints, color: 'accent', tension: 0.15, pointRadius: 5}}],
            xLabel: 'parameters (B)', yLabel: 'Wh', yUnit: 'Wh',
        }});

        if (chartMwh) {{ chartMwh.destroy(); chartMwh = null; }}
        chartMwh = WlCharts.line({{
            canvas: document.getElementById('chart-mwh'),
            datasets: [{{label: 'mWh per output token', points: mwhPoints, color: 'warn', tension: 0.15, pointRadius: 5}}],
            xLabel: 'parameters (B)', yLabel: 'mWh/tok', yUnit: 'mWh/tok',
        }});
    }}

    function escapeHTML(s) {{
        return String(s).replace(/[&<>"']/g, c => ({{
            '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
        }}[c]));
    }}

    async function runCompare() {{
        if (!CAN_BATCH) return;
        stopCooldownTicker();
        const question = document.getElementById('userQuestion').value.trim();
        const expected = document.getElementById('userExpected').value.trim();
        if (!question || !expected) {{
            document.getElementById('run-status').innerHTML =
                '<div style="color:var(--err);font-size:0.85rem">Both question and expected answer are required.</div>';
            return;
        }}
        const btn = document.getElementById('runBtn');
        btn.disabled = true;
        document.getElementById('run-status').innerHTML =
            '<div style="color:var(--warn);font-size:0.85rem">Queued &mdash; running across {panel_n} models with active-probe thermal floor wait between each&hellip;</div>';
        const form = new FormData();
        form.append('question', question);
        form.append('expected', expected);
        try {{
            const resp = await fetch('/rag/compare-models', {{method:'POST', body:form}});
            const data = await resp.json();
            if (data.job_id) {{
                pollCompare(data.job_id);
            }} else {{
                document.getElementById('run-status').innerHTML =
                    '<div style="color:var(--err)">' + (data.error || 'Error') + '</div>';
                btn.disabled = false;
            }}
        }} catch(e) {{
            document.getElementById('run-status').innerHTML =
                '<div style="color:var(--err)">Failed: ' + e + '</div>';
            btn.disabled = false;
        }}
    }}

    async function pollCompare(jobId) {{
        try {{
            const resp = await fetch('/rag/job/' + jobId);
            const data = await resp.json();
            if (data.status === 'done' && data.result) {{
                stopCooldownTicker();
                const r = data.result;
                const rows = (r.models || []).map(m => ({{
                    model: m.model_key, params: m.params, ok: !!m.correct,
                    ans: m.error ? '(error: ' + m.error + ')' : (m.response || '(empty)'),
                    tok: m.output_tokens || 0,
                    wall: m.duration_s || 0,
                    whEst: m.delta_e_wh || 0,
                    flag: (m.confidence || {{}}).flag || '🟢',
                }}));
                document.getElementById('source-paper').textContent = '(live run — corpus retrieval)';
                renderCompareCard({{
                    promptText: r.question, expected: r.expected,
                    rows: rows, tagline: '', sourceLabel: 'Live (P110 measured)',
                }});
                document.getElementById('run-status').innerHTML =
                    '<div style="color:var(--accent);font-size:0.85rem">&#10003; Done. Result rendered above. ' +
                    '<a href="/results/llm/' + jobId + '/download.json" style="color:var(--accent)">&darr; JSON</a></div>'
                    + wlCooldownSummary(r.cooldowns);
                document.getElementById('runBtn').disabled = false;
                document.querySelector('.prompt-card').scrollIntoView({{behavior:'smooth', block:'start'}});
            }} else if (data.status === 'error') {{
                stopCooldownTicker();
                document.getElementById('run-status').innerHTML =
                    '<div style="color:var(--err);font-size:0.85rem">Error: ' + (data.error || 'unknown') + '</div>';
                document.getElementById('runBtn').disabled = false;
            }} else {{
                const stage = data.stage || 'queued';
                if (stage === 'awaiting_cooldown_decision') {{
                    wlCooldownDialog(jobId, data.cooldown_decision_options);
                }} else {{ wlCooldownDialogClose(); }}
                const cdVal = data.cooldown_waited_s;
                const prev = cooldownState;
                const cdChanged = !prev || prev.cdWaited !== cdVal;
                // Reset the log at run start (model 1 / queued); record a finished
                // wait each time we leave the 'cooldown' stage so it persists.
                if (!data.current_model_idx || data.current_model_idx <= 1) cooldownLog = [];
                if (prev && prev.stage === 'cooldown' && stage !== 'cooldown' && prev.cdWaited != null) {{
                    cooldownLog.push(prev.cdWaited);
                }}
                cooldownState = {{
                    stage: stage,
                    qpos:  data.queue_position,
                    mi:    data.current_model_idx,
                    mt:    data.total_models,
                    ml:    data.current_model_label,
                    watts: data.watts,
                    cdWaited: cdVal,
                    cdRef:    data.cooldown_reference_w,
                    cdLocalStart: cdChanged ? Date.now() : (prev ? prev.cdLocalStart : Date.now()),
                }};
                // Start/stop the local 4 Hz ticker based on current stage,
                // so the displayed "waiting Xs" advances smoothly between
                // the server's 1 s P110 polls and the UI's 2 s job polls.
                if (stage === 'cooldown') {{
                    if (!cooldownTicker) cooldownTicker = setInterval(renderRunStatus, 250);
                }} else if (cooldownTicker) {{
                    clearInterval(cooldownTicker); cooldownTicker = null;
                }}
                renderRunStatus();
                pollTimer = setTimeout(() => pollCompare(jobId), 2000);
            }}
        }} catch(e) {{
            pollTimer = setTimeout(() => pollCompare(jobId), 4000);
        }}
    }}

    renderShowcase(order[0]);
    // Resume a queued/running compare job (↩ Resume from /queue-status).
    const _resumeJob = new URLSearchParams(location.search).get('job');
    if (_resumeJob) {{ var _rb = document.getElementById('runBtn'); if (_rb) _rb.disabled = true; pollCompare(_resumeJob); }}
    </script>
    {_FOOTER}
</body>
</html>""")


# --- Results: list, JSON download, CSV download ---

@app.get("/results/{job_type}/list", dependencies=[Depends(requires(RESULTS_DOWNLOAD))])
async def results_list(job_type: str, request: Request, limit: int = 10):
    if job_type not in ("video", "llm", "image"):
        return JSONResponse({"error": "Invalid type"}, status_code=400)
    # CR-026: own-jobs scope for non-Lab. Lab passes None → unfiltered.
    return list_results(job_type, limit=max(1, min(limit, 200)),
                        visitor_key=queue_control.visitor_key(request))


@app.delete("/results/{job_type}/{job_id}", dependencies=[Depends(requires(SETTINGS_WRITE))])
async def results_delete(job_type: str, job_id: str):
    """Lab-only — delete a stored result JSON (dev cleanup of test runs). Gated
    on SETTINGS_WRITE (Lab tier). CSV is generated on the fly, so the JSON is the
    only artifact to remove."""
    if job_type not in ("video", "llm", "image"):
        return JSONResponse({"ok": False, "error": "Invalid type"}, status_code=400)
    if delete_result(job_type, job_id):
        return {"ok": True, "deleted": job_id}
    return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)


# CR-026 carve-out for /demo's "show last result" panel.
#
# /demo's guided tour pre-loads the most recent persisted result for each
# workload so visitors land on a populated card rather than an empty page.
# CR-026's visitor scoping correctly hides cross-visitor jobs from
# Anonymous, but for /demo specifically we want the latest result to be
# visible regardless of who ran it — that's the whole point of the
# pre-loaded panel. This endpoint is the deliberate exception to the
# CR-026 default: returns the FULL latest result for the requested type
# (and optional task filter), unfiltered by visitor.
#
# Privacy note: the rendered /demo cards use energy figures, model
# labels, generated text, and produced images — all already meant to
# be illustrative. If a future Member workflow ever runs anything
# personally identifying, revisit the model (curated demo-pinned
# results, redacted shape, or a `is_demo` flag).
@app.get("/demo/last/{job_type}", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def demo_last_result(job_type: str, task_eq: str | None = None):
    """Latest persisted result for /demo's prev-runs panels, unfiltered
    by visitor (deliberate CR-026 carve-out for the demo surface).

    `job_type='llm'` defaults to *plain* LLM runs — RAG records that
    persist under results/llm/ (mode='rag', 'rag_compare') are excluded
    unless the caller passes `task_eq='RAG …'`. This is what makes
    /demo's LLM step show an actual LLM result instead of accidentally
    rendering a RAG compare in the wrong widget shape.
    """
    if job_type not in ("video", "llm", "image"):
        return JSONResponse({"error": "Invalid type"}, status_code=400)
    runs = list_results(job_type, limit=20, visitor_key=None)
    if task_eq:
        runs = [r for r in runs if r.get("task") == task_eq]
    elif job_type == "llm":
        # Plain-LLM default: only a genuine single inference. Compare/RAG
        # records (mode=compare_models, rag_compare_models, rag, rag_compare,
        # both, batch, all, …) persist under results/llm/ too but carry a
        # different card shape. Pre-loading one into /demo's single-run widget
        # rendered a "format not recognised" card and (pre-fix) trapped the
        # tour, since the single-run renderer bailed before revealing Next.
        # Filter on `mode` (more reliable than the `task` text — compare
        # records have task=None, so the old "RAG" prefix test let them pass).
        runs = [r for r in runs if r.get("mode", "single") == "single"]
    elif job_type == "image":
        # Same reasoning: the image step's single-run card only handles a
        # single cpu/gpu generation, not an N-way compare_models record.
        runs = [r for r in runs if r.get("mode", "cpu") in ("cpu", "gpu")]
    if not runs:
        return JSONResponse({"error": "no result"}, status_code=404)
    full = load_result(job_type, runs[0]["job_id"], visitor_key=None)
    if full is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return full


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
@app.get("/findings/source/{job_type}/{job_id}/download.json",
         dependencies=[Depends(requires(PUBLIC_PAGE))])
async def finding_source_result(job_type: str, job_id: str):
    if job_type not in ("video", "llm", "image"):
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

@app.get("/results/{job_type}/{job_id}/download.json", dependencies=[Depends(requires(RESULTS_DOWNLOAD))])
async def results_download_json(job_type: str, job_id: str, request: Request):
    if job_type not in ("video", "llm", "image"):
        return JSONResponse({"error": "Invalid type"}, status_code=400)
    data = load_result(job_type, job_id, visitor_key=queue_control.visitor_key(request))
    if not data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    content = json.dumps(data, indent=2)
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=wattlab_{job_type}_{job_id}.json"},
    )

@app.get("/results/{job_type}/{job_id}/download.csv", dependencies=[Depends(requires(RESULTS_DOWNLOAD))])
async def results_download_csv(job_type: str, job_id: str, request: Request):
    if job_type not in ("video", "llm", "image"):
        return JSONResponse({"error": "Invalid type"}, status_code=400)
    data = load_result(job_type, job_id, visitor_key=queue_control.visitor_key(request))
    if not data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    content = to_csv(job_type, data)
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=wattlab_{job_type}_{job_id}.csv"},
    )


@app.get("/results/{job_type}/{job_id}/reproduce.zip", dependencies=[Depends(requires(RESULTS_DOWNLOAD))])
async def results_reproduce_zip(job_type: str, job_id: str, request: Request):
    # CR-040 — video-only V1 (AI results are far less reproducible across GPU
    # driver / ROCm / cuDNN versions than a video encode is).
    if job_type != "video":
        return JSONResponse({"error": "Reproduce bundles are video-only in V1"}, status_code=400)
    data = load_result(job_type, job_id, visitor_key=queue_control.visitor_key(request))
    if not data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    import reproduce
    blob = reproduce.build_bundle(job_type, job_id, data, cfg.load().get("variance_pct"))
    if blob is None:
        return JSONResponse({"error": "No reproducible encode in this result"}, status_code=422)
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=owl_reproduce_{job_id}.zip"},
    )


# --- Settings ---

@app.get("/settings", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def settings_page(request: Request):
    s = cfg.load()
    local = can(audience.tier(request), SETTINGS_READ_FULL)

    def field(fid, val, min_, max_, unit, hint="", step=None):
        step_attr = f' step="{step}"' if step else ""
        if local:
            ctrl = (f'<input type="number" id="{fid}" min="{min_}" max="{max_}"{step_attr}'
                    f' value="{val}" style="background:var(--panel);border:1px solid var(--border-3);color:var(--text);'
                    f'font-family:monospace;font-size:0.9rem;padding:0.3rem 0.5rem;'
                    f'width:80px;text-align:right">')
        else:
            ctrl = f'<span style="font-family:monospace;color:var(--accent);font-size:0.95rem">{val}</span>'
        hint_html = f'<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.2rem">{hint}</div>' if hint else ""
        return (f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
                f'padding:0.5rem 0;border-bottom:1px solid var(--panel-2);gap:1rem">'
                f'<div><label style="color:var(--text-2);font-size:0.85rem">{fid.replace("_"," ").title()}</label>'
                f'{hint_html}</div>'
                f'<div style="display:flex;align-items:baseline;gap:0.5rem">'
                f'{ctrl}<span style="color:var(--text-3);font-size:0.8rem">{unit}</span>'
                f'</div></div>')

    def toggle_field(fid, val, hint="", onchange=""):
        oc = f' onchange="{onchange}"' if onchange else ""
        if local:
            checked = "checked" if val else ""
            ctrl = (f'<input type="checkbox" id="{fid}" {checked}{oc}'
                    f' style="width:18px;height:18px;accent-color:var(--accent);cursor:pointer">')
        else:
            ctrl = (f'<span style="font-family:monospace;color:var(--accent);font-size:0.95rem">'
                    f'{"ON" if val else "OFF"}</span>')
        hint_html = f'<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.2rem">{hint}</div>' if hint else ""
        return (f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
                f'padding:0.5rem 0;border-bottom:1px solid var(--panel-2);gap:1rem">'
                f'<div><label style="color:var(--text-2);font-size:0.85rem">{fid.replace("_"," ").title()}</label>'
                f'{hint_html}</div>'
                f'<div style="display:flex;align-items:baseline;gap:0.5rem">{ctrl}</div></div>')

    def slider_field(fid, val, min_, max_, step, unit, hint="", label=None):
        if local:
            ctrl = (f'<input type="range" id="{fid}" min="{min_}" max="{max_}" step="{step}"'
                    f' value="{val}"'
                    f' oninput="document.getElementById(\'{fid}_disp\').textContent=this.value"'
                    f' style="width:130px;accent-color:var(--accent);vertical-align:middle"> '
                    f'<span id="{fid}_disp" style="font-family:monospace;color:var(--accent);'
                    f'font-size:0.9rem;min-width:2.5rem;display:inline-block">{val}</span>')
        else:
            ctrl = f'<span style="font-family:monospace;color:var(--accent);font-size:0.95rem">{val}</span>'
        hint_html = f'<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.2rem">{hint}</div>' if hint else ""
        return (f'<div style="display:flex;justify-content:space-between;align-items:center;'
                f'padding:0.5rem 0;border-bottom:1px solid var(--panel-2);gap:1rem">'
                f'<div><label style="color:var(--text-2);font-size:0.85rem">{label or fid.replace("_"," ").title()}</label>'
                f'{hint_html}</div>'
                f'<div style="display:flex;align-items:center;gap:0.5rem">'
                f'{ctrl}<span style="color:var(--text-3);font-size:0.8rem">{unit}</span>'
                f'</div></div>')

    def textarea_field(fid, val, hint="", rows=3):
        if local:
            ctrl = (f'<textarea id="{fid}" rows="{rows}" spellcheck="false"'
                    f' style="width:100%;background:var(--panel-2);border:1px solid var(--border);'
                    f'color:var(--text-3);font-family:monospace;font-size:0.72rem;'
                    f'padding:0.4rem 0.5rem;resize:vertical;line-height:1.5">{val}</textarea>')
        else:
            ctrl = (f'<div style="background:var(--panel-2);border:1px solid var(--border-2);padding:0.4rem 0.5rem;'
                    f'font-family:monospace;font-size:0.72rem;color:var(--text-4);word-break:break-all;'
                    f'line-height:1.5">{val}</div>')
        hint_html = f'<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.2rem;margin-bottom:0.3rem">{hint}</div>' if hint else ""
        return (f'<div style="padding:0.5rem 0;border-bottom:1px solid var(--panel-2)">'
                f'<label style="color:var(--text-2);font-size:0.85rem">{fid.replace("_"," ").title()}</label>'
                f'{hint_html}{ctrl}</div>')

    def calib_field(fid, val, hint=""):
        disp = f"{val:.2f} %" if val is not None else "—"
        color = "#00ff99" if val is not None else "#333"
        hint_html = f'<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.1rem">{hint}</div>' if hint else ""
        return (f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
                f'padding:0.5rem 0;border-bottom:1px solid var(--panel-2);gap:1rem">'
                f'<div><label style="color:var(--text-4);font-size:0.85rem">{fid.replace("_"," ").title()}</label>'
                f'{hint_html}</div>'
                f'<div style="display:flex;align-items:baseline;gap:0.5rem">'
                f'<span style="font-family:monospace;color:{color};font-size:0.95rem">{disp}</span>'
                f'</div></div>')

    notice = ('' if local else
              '<div style="background:var(--panel);border-left:3px solid #555;padding:0.75rem 1rem;'
              'margin-bottom:1.5rem;font-size:0.82rem;color:var(--text-3)">'
              '🔒 Read-only — settings can only be modified from the lab network or SSH tunnel.'
              '</div>')
    save_block = ('<button onclick="saveSettings()" style="background:var(--accent);color:#000;border:none;'
                  'padding:0.75rem 2rem;cursor:pointer;font-family:monospace;font-size:1rem;margin-top:2rem">'
                  'Save Settings</button><div id="msg" style="margin-top:1rem;font-size:0.85rem"></div>'
                  if local else '')
    subtitle = 'OWL · GoS1 · Lab mode' if local else 'OWL · GoS1 · Read-only'

    chart_js = ('<script src="' + CHARTJS_URL + '"></script>'
                '<script src="/static/wl-charts.js"></script>'
                if local else '')
    return f"""<!DOCTYPE html>
<html>
<head>
    <link rel="icon" type="image/svg+xml" href="/static/owl.svg">
  <title>OWL — Settings</title>
    {chart_js}
    <style>
        * {{ box-sizing:border-box; margin:0; padding:0; }}
        body {{ font-family:monospace; background:var(--bg); color:var(--text);
               max-width:600px; margin:0 auto; padding:2rem; }}
        h1 {{ color:var(--accent); margin-bottom:0.25rem; font-size:1.6rem; }}
        .subtitle {{ color:var(--text-3); font-size:0.8rem; margin-bottom:2rem; }}
        .section {{ color:var(--text-4); font-size:0.72rem; text-transform:uppercase;
                    letter-spacing:0.05em; margin:1.5rem 0 0.75rem;
                    padding-bottom:0.4rem; border-bottom:1px solid var(--panel); }}
        input[type=number]:focus {{ border-color:var(--accent); outline:none; }}
        details.calib-details > summary {{ cursor:pointer; color:var(--accent);
            font-size:0.82rem; padding:0.5rem 0; list-style:none;
            border-top:1px dashed var(--panel-2); margin-top:0.75rem;
            padding-top:0.75rem; }}
        details.calib-details > summary::-webkit-details-marker {{ display:none; }}
        details.calib-details > summary::before {{ content:"▸ "; color:var(--text-4); }}
        details.calib-details[open] > summary::before {{ content:"▾ "; color:var(--text-4); }}
        details.calib-details .panel {{ background:var(--panel-2); border:1px solid var(--border-3);
            padding:0.75rem; margin-top:0.5rem; }}
    </style>
</head>
<body>
    {_BACK}
    <h1>Settings</h1>
    <div class="subtitle">{subtitle}</div>
    {notice}

    <div class="section">Measurement</div>
    {field("baseline_polls",    s['baseline_polls'],    5,  60,  "× 1s",   "baseline window duration")}
    {field("llm_unload_settle_s", s['llm_unload_settle_s'], 1, 30, "s",   "wait after model unload before baseline")}

    <div class="section">Cooldown between passes</div>
    {toggle_field("cooldown_wait_for_idle", s.get('cooldown_wait_for_idle', True),
                  "ON: wait for wall power to settle back to the idle floor before each next pass "
                  "(active-probe, the /rag /llm compare technique). OFF: use the fixed rest periods below. "
                  "Variance calibration always keeps its fixed protocol.", onchange="syncCooldownMode()")}
    {field("video_cooldown_s",  s['video_cooldown_s'],  10, 300, "s",      "fixed rest between CPU and GPU runs (used when wait-for-idle is OFF; also the fallback after an idle-wait timeout)")}
    {field("llm_rest_s",        s['llm_rest_s'],        5,  120, "s",      "fixed pause between LLM batch / compare runs (used when wait-for-idle is OFF; also the timeout fallback)")}
    {field("cooldown_idle_tolerance_w", s.get('cooldown_idle_tolerance_w', 3.0), 0.5, 20, "W", "idle-wait: settle when a reading is within this of the captured floor", step=0.5)}
    {field("cooldown_idle_settle_polls", s.get('cooldown_idle_settle_polls', 3), 1, 10, "polls", "idle-wait: consecutive in-band reads needed to confirm settle")}
    {field("cooldown_idle_max_wait_s", s.get('cooldown_idle_max_wait_s', 120), 10, 600, "s", "idle-wait: cap before timeout → dialog (Lab) or fixed fallback")}
    {field("cooldown_dialog_watchdog_s", s.get('cooldown_dialog_watchdog_s', 75), 15, 300, "s", "idle-wait timeout dialog: auto-apply the fallback if no operator answer within this")}

    <div class="section">Staging</div>
    {field("max_idle_mins",     s['max_idle_mins'],     5,  240, "min",    "auto-lower /tmp/owl-maintenance after this much Lab inactivity (CR-015 watchdog)")}

    <div class="section">Encoding targets</div>
    <div style="color:var(--text-4);font-size:0.75rem;line-height:1.6;margin-bottom:0.75rem">
      ABR target bitrate applied to both CPU and GPU presets for each codec — ensures apples-to-apples energy comparison. Custom ffmpeg commands on the video page override these.
    </div>
    {field("h264_bitrate_kbps", s['h264_bitrate_kbps'], 500, 20000, "kbps", f"H.264 target bitrate (libx264 + {_gpu_enc('h264')})", step=100)}
    {field("h265_bitrate_kbps", s['h265_bitrate_kbps'], 500, 20000, "kbps", f"H.265 target bitrate (libx265 + {_gpu_enc('h265')})", step=100)}
    {field("av1_bitrate_kbps",  s['av1_bitrate_kbps'],  500, 20000, "kbps", f"AV1 target bitrate (libsvtav1 + {_gpu_enc('av1')})", step=100)}

    <div class="section">Confidence thresholds — CI model (CR-028 Phase 2)</div>
    {field("conf_positive_green",  s.get('conf_positive_green', 0.95),  0.5, 0.999, "P", "🟢 min confidence_positive Φ(z) that task draws above idle", step=0.01)}
    {field("conf_positive_yellow", s.get('conf_positive_yellow', 0.80), 0.5, 0.999, "P", "🟡 min confidence_positive", step=0.01)}
    {field("conf_green_polls", s['conf_green_polls'],  1, 100, "polls", "🟢 minimum task polls (both models)")}
    {field("conf_yellow_polls",s['conf_yellow_polls'], 1, 50,  "polls", "🟡 minimum task polls (both models)")}
    {calib_field("variance_idle_pct",       s['variance_idle_pct'],       "calibrated idle noise floor — feeds the CI model (SE_calibrated)")}
    {calib_field("variance_idle_drift_pct", s.get('variance_idle_drift_pct'), "between-window drift CV — feeds SE_drift in the CI model")}
    {calib_field("variance_cpu_pct",        s['variance_cpu_pct'],        "run-level repeatability CV — NOT used in the single-run flag (reserved for aggregate layer)")}
    {calib_field("variance_gpu_pct",        s['variance_gpu_pct'],        "run-level repeatability CV — NOT used in the single-run flag (reserved for aggregate layer)")}
    <div class="section">Confidence thresholds — legacy variance model (fallback for results without raw samples)</div>
    {field("variance_pct",     s['variance_pct'],     0, 50,  "%",     "legacy composite variance — used only when a run has no raw samples", step=0.1)}
    {field("variance_green_x", s['variance_green_x'], 1, 20,  "× noise", "🟢 (legacy) ΔW must exceed this multiple of noise floor", step=0.5)}
    {field("variance_yellow_x",s['variance_yellow_x'],1, 10,  "× noise", "🟡 (legacy) ΔW must exceed this multiple of noise floor", step=0.5)}

    <div class="section">Variance calibration</div>
    <div style="color:var(--text-4);font-size:0.75rem;line-height:1.6;margin-bottom:0.75rem">
      Runs H.264 CPU then H.265 GPU on Meridian N times, sampling raw P110 readings throughout.
      Writes <strong>Variance Idle %</strong> (the idle noise floor) and <strong>Variance Idle Drift %</strong>
      (between-window drift) — these feed the <strong>live CI confidence model</strong> (SE_calibrated + SE_drift).
      Also records per-codec repeatability CVs (CPU/GPU ΔW), reserved for a future aggregate layer — not used in
      the single-run flag. The composite <strong>Variance %</strong> (mean of the three) now feeds only the
      <em>legacy</em> fallback for results saved without raw samples. Queue is blocked for the duration.
    </div>
    {slider_field("variance_runs",      s['variance_runs'],      0,  100, 2,  "runs",    "number of H264-CPU + H265-GPU run pairs · steps of 2 (a pair needs ≥2) · 0 disables calibration here and in the benchmark", label="Variance Runs (0 to skip)")}
    {slider_field("variance_cooldown_s",s['variance_cooldown_s'],10, 300, 10, "s",       "cooldown between each run pair")}
    <div style="padding:0.5rem 0;border-bottom:1px solid var(--panel-2)">
      <label style="color:var(--text-2);font-size:0.85rem">H.264 CPU command (derived)</label>
      <div style="color:var(--text-5);font-size:0.72rem;margin-top:0.2rem;margin-bottom:0.3rem">Mirrors the <code>/video</code> H.264 CPU preset · bitrate from <code>h264_bitrate_kbps</code> · {{input}}/{{output}} substituted at runtime</div>
      <div style="background:var(--panel-2);border:1px solid var(--border-2);padding:0.4rem 0.5rem;font-family:monospace;font-size:0.72rem;color:var(--text-4);word-break:break-all;line-height:1.5">{vid.variance_template("cpu", s)}</div>
    </div>
    <div style="padding:0.5rem 0;border-bottom:1px solid var(--panel-2)">
      <label style="color:var(--text-2);font-size:0.85rem">H.265 GPU command (derived)</label>
      <div style="color:var(--text-5);font-size:0.72rem;margin-top:0.2rem;margin-bottom:0.3rem">Mirrors the <code>/video</code> H.265 GPU preset · bitrate from <code>h265_bitrate_kbps</code> · {{input}}/{{output}} substituted at runtime</div>
      <div style="background:var(--panel-2);border:1px solid var(--border-2);padding:0.4rem 0.5rem;font-family:monospace;font-size:0.72rem;color:var(--text-4);word-break:break-all;line-height:1.5">{vid.variance_template("h265_gpu", s)}</div>
    </div>
    {'<button onclick="runVarianceCalibration()" id="varCalBtn" style="background:var(--border);color:var(--accent);border:1px solid #00ff9944;padding:0.5rem 1.25rem;cursor:pointer;font-family:monospace;font-size:0.85rem;margin-top:0.75rem">▶ Run variance calibration</button><div id="var-cal-msg" style="margin-top:0.5rem;font-size:0.82rem"></div>' if local else '<div style="color:var(--text-5);font-size:0.78rem;margin-top:0.5rem">Calibration requires lab access.</div>'}

    {('''<details class="calib-details" id="precalDetails">
      <summary>More calibration details</summary>
      <div class="panel">
        <div style="color:var(--text-4);font-size:0.72rem;line-height:1.6;margin-bottom:0.5rem">
          Thermal-recovery probe (<code>bin/probe-thermal-recovery</code>): for each distance d after a CPU and a GPU encode, samples N idle polls. Used to validate that <code>variance_cooldown_s</code> is long enough — the curve should flatten well below it.
        </div>
        <div id="precal-meta" style="color:var(--text-5);font-size:0.72rem;margin-bottom:0.5rem">Loading…</div>
        <div style="position:relative;height:260px"><canvas id="precalChart"></canvas></div>
        <div id="precal-stats" style="margin-top:0.75rem;font-size:0.78rem;color:var(--text-3);line-height:1.7"></div>
      </div>
    </details>''') if local else ''}

    <div class="section">Overnight benchmark</div>
    <div style="color:var(--text-4);font-size:0.75rem;line-height:1.6;margin-bottom:0.5rem">
      Full-pipeline benchmark (CR-061): variance calibration &rarr; video all-codecs &times; reps &times; sources &rarr; LLM/RAG/image compare panels.
      Runs as <strong>one queue job that blocks other runs</strong>; follow it on <a href="/queue-status" style="color:var(--accent)">/queue-status</a>, view results at <a href="/benchmark" style="color:var(--accent)">/benchmark</a>.
      <span style="color:var(--warn)">&#9888; calibration is ambient-sensitive &mdash; don't launch during a heat wave.</span>
      Which measures &amp; sources run is set by <code>bench_run_*</code> / <code>bench_sources</code> in settings.json.
    </div>
    {slider_field("bench_video_reps", s['bench_video_reps'], 1, 10, 1, "reps", "video all-codecs repeats per source")}
    {'<button onclick="runBenchmark()" id="benchBtn" style="background:var(--border);color:var(--accent);border:1px solid #00ff9944;padding:0.5rem 1.25rem;cursor:pointer;font-family:monospace;font-size:0.85rem;margin-top:0.75rem">&#9654; Run overnight benchmark</button> <button onclick="cancelBenchmark()" id="benchCancelBtn" style="background:var(--border);color:var(--err);border:1px solid var(--err);padding:0.5rem 1.25rem;cursor:pointer;font-family:monospace;font-size:0.85rem;margin-top:0.75rem">&#9632; Cancel</button><div id="bench-msg" style="margin-top:0.5rem;font-size:0.82rem"></div>' if local else '<div style="color:var(--text-5);font-size:0.78rem;margin-top:0.5rem">Benchmark requires lab access.</div>'}

    {('''<details class="calib-details" id="testdataDetails">
      <summary>Test data cleanup (Lab)</summary>
      <div class="panel">
        <div style="color:var(--text-4);font-size:0.75rem;line-height:1.6;margin-bottom:0.75rem">
          Delete stored result JSON for dev / test runs (CSV is generated on the fly, so removing the
          JSON removes the run entirely). Newest first, up to 50 per type. <span style="color:var(--warn)">No undo &mdash; deletes immediately.</span>
        </div>
        <div id="testdata-panel" style="font-size:0.8rem;color:var(--text-3)">loading&hellip;</div>
      </div>
    </details>''') if local else ''}

    {(f'''<div class="section">Members</div>
    <div style="color:var(--text-4);font-size:0.75rem;line-height:1.6;margin-bottom:0.75rem">
      Magic-link allowlist (<code>data/members.json</code>) — one email per line.
      Lowercased, stripped, deduped and sorted on save. Reloaded into the running service
      automatically; no restart needed. <span style="color:var(--text-3)">{len(auth.list_members())} email(s)</span>
    </div>
    {textarea_field("members", chr(10).join(auth.list_members()), "", rows=12)}''') if local else ''}

    <div class="section">Tier limits</div>
    <div style="color:var(--text-4);font-size:0.75rem;line-height:1.6;margin-bottom:0.75rem">
      CR-001 part D — concurrent-job caps and upload-size caps per audience
      tier. Anonymous keyed by IP, Member by email, Lab uncapped.
    </div>
    {field("queue_anonymous_cap",      s['queue_anonymous_cap'],      1, 10,   "jobs",  "concurrent (queued + running) Anonymous jobs per IP")}
    {field("queue_member_cap",         s['queue_member_cap'],         1, 20,   "jobs",  "concurrent jobs per Member email")}
    {field("upload_size_anonymous_mb", s['upload_size_anonymous_mb'], 10, 1024, "MB",    "Anonymous /video/upload byte cap")}
    {field("upload_size_member_mb",    s['upload_size_member_mb'],    100, 4096, "MB",   "Member /video/upload byte cap")}

    {_models_section_html(s, local)}

    {save_block}
    <script>
    function collectModelToggles(surfaceKey) {{
        return Array.from(
            document.querySelectorAll('.model-toggle[data-surface="' + surfaceKey + '"]:checked')
        ).map(el => el.dataset.key);
    }}
    function syncCooldownMode() {{
        // When wait-for-idle is ON, the fixed rest periods are greyed (the
        // idle tunables drive cooldown instead); when OFF, the idle tunables
        // are greyed. Mirrors power.cooldown_between_runs's strategy switch.
        var tog = document.getElementById('cooldown_wait_for_idle');
        if (!tog || tog.type !== 'checkbox') return;   // read-only view → no-op
        var on = tog.checked;
        function setDisabled(id, dis) {{
            var el = document.getElementById(id);
            if (el) {{ el.disabled = dis; el.style.opacity = dis ? '0.35' : '1'; }}
        }}
        setDisabled('video_cooldown_s', on);
        setDisabled('llm_rest_s', on);
        ['cooldown_idle_tolerance_w','cooldown_idle_settle_polls',
         'cooldown_idle_max_wait_s','cooldown_dialog_watchdog_s'].forEach(function(id) {{
            setDisabled(id, !on);
        }});
    }}
    document.addEventListener('DOMContentLoaded', syncCooldownMode);

    async function saveSettings() {{
        const num_fields = ['baseline_polls','video_cooldown_s','llm_rest_s','llm_unload_settle_s',
                            'cooldown_idle_tolerance_w','cooldown_idle_settle_polls',
                            'cooldown_idle_max_wait_s','cooldown_dialog_watchdog_s',
                            'h264_bitrate_kbps','h265_bitrate_kbps','av1_bitrate_kbps',
                            'variance_pct','variance_green_x','variance_yellow_x',
                            'conf_positive_green','conf_positive_yellow',
                            'conf_green_polls','conf_yellow_polls',
                            'variance_runs','variance_cooldown_s',
                            'queue_anonymous_cap','queue_member_cap',
                            'upload_size_anonymous_mb','upload_size_member_mb',
                            'bench_video_reps'];
        const bool_fields = ['cooldown_wait_for_idle'];
        const str_fields = ['members'];
        const list_fields = ['llm_enabled_models','rag_enabled_models','image_enabled_models'];
        const body = {{}};
        for (const f of num_fields) {{
            const el = document.getElementById(f);
            if (el) body[f] = parseFloat(el.value);
        }}
        for (const f of bool_fields) {{
            const el = document.getElementById(f);
            if (el) body[f] = el.checked;
        }}
        for (const f of str_fields) {{
            const el = document.getElementById(f);
            if (el) body[f] = el.value;
        }}
        for (const f of list_fields) {{
            if (document.querySelector('.model-toggle[data-surface="' + f + '"]')) {{
                body[f] = collectModelToggles(f);
            }}
        }}
        try {{
            const resp = await fetch('/settings', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(body),
            }});
            const data = await resp.json();
            if (data.ok) {{
                document.getElementById('msg').innerHTML =
                    '<span style="color:var(--accent)">✓ Saved.</span>';
            }} else {{
                document.getElementById('msg').innerHTML =
                    '<span style="color:var(--err)">Error: ' + JSON.stringify(data) + '</span>';
            }}
        }} catch(e) {{
            document.getElementById('msg').innerHTML =
                '<span style="color:var(--err)">Failed: ' + e + '</span>';
        }}
    }}

    async function runVarianceCalibration() {{
        const btn = document.getElementById('varCalBtn');
        const msg = document.getElementById('var-cal-msg');
        if (!btn) return;
        btn.disabled = true;
        msg.innerHTML = '<span style="color:var(--warn)">Saving settings…</span>';
        await saveSettings();
        msg.innerHTML = '<span style="color:var(--warn)">Queuing calibration job…</span>';
        try {{
            const resp = await fetch('/variance/run', {{method: 'POST'}});
            const data = await resp.json();
            if (data.job_id) {{
                msg.innerHTML = '<span style="color:var(--accent)">Job ' + data.job_id
                    + ' queued (position ' + data.queue_position + '). '
                    + '<a href="/queue-status" style="color:var(--accent)">View queue →</a>'
                    + '</span>';
            }} else {{
                msg.innerHTML = '<span style="color:var(--err)">Error: ' + JSON.stringify(data) + '</span>';
                btn.disabled = false;
            }}
        }} catch(e) {{
            msg.innerHTML = '<span style="color:var(--err)">Failed: ' + e + '</span>';
            btn.disabled = false;
        }}
    }}

    let _benchJobId = null;
    async function runBenchmark() {{
        const btn = document.getElementById('benchBtn');
        const msg = document.getElementById('bench-msg');
        if (!btn) return;
        btn.disabled = true;
        msg.innerHTML = '<span style="color:var(--warn)">Saving settings…</span>';
        await saveSettings();
        msg.innerHTML = '<span style="color:var(--warn)">Queuing benchmark…</span>';
        try {{
            const resp = await fetch('/benchmark/run', {{method: 'POST'}});
            const data = await resp.json();
            if (data.job_id) {{
                _benchJobId = data.job_id;
                msg.innerHTML = '<span style="color:var(--accent)">Benchmark ' + data.job_id
                    + ' queued (position ' + data.queue_position + '). '
                    + '<a href="/queue-status" style="color:var(--accent)">Follow on the queue →</a></span>';
            }} else {{
                msg.innerHTML = '<span style="color:var(--err)">Error: ' + JSON.stringify(data) + '</span>';
                btn.disabled = false;
            }}
        }} catch(e) {{
            msg.innerHTML = '<span style="color:var(--err)">Failed: ' + e + '</span>';
            btn.disabled = false;
        }}
    }}
    async function cancelBenchmark() {{
        const msg = document.getElementById('bench-msg');
        let jid = _benchJobId;
        if (!jid) {{
            // page may have reloaded — fall back to the running job if it's a benchmark
            try {{
                const q = await (await fetch('/queue')).json();
                if (q.running && q.running.type === 'benchmark') jid = q.running.job_id;
            }} catch(e) {{}}
        }}
        if (!jid) {{ msg.innerHTML = '<span style="color:var(--text-4)">No benchmark to cancel.</span>'; return; }}
        const form = new FormData(); form.append('job_id', jid);
        try {{
            const resp = await fetch('/benchmark/cancel', {{method: 'POST', body: form}});
            const data = await resp.json();
            msg.innerHTML = '<span style="color:var(--warn)">Cancel: ' + (data.state || JSON.stringify(data))
                + ' — takes effect after the current step.</span>';
            const b = document.getElementById('benchBtn'); if (b) b.disabled = false;
        }} catch(e) {{
            msg.innerHTML = '<span style="color:var(--err)">Cancel failed: ' + e + '</span>';
        }}
    }}

    let precalChartInstance = null;
    async function loadPrecalibration() {{
        const meta = document.getElementById('precal-meta');
        const stats = document.getElementById('precal-stats');
        if (precalChartInstance) return;  // already loaded
        try {{
            const resp = await fetch('/precalibration/data');
            const data = await resp.json();
            if (!data.available) {{
                meta.innerHTML = '<span style="color:var(--text-5)">No probe data yet — '
                    + 'run <code>bin/probe-thermal-recovery</code> from the shell to generate.</span>';
                return;
            }}
            const cpu = data.points.filter(p => p.workload === 'cpu');
            const gpu = data.points.filter(p => p.workload === 'gpu');
            precalChartInstance = WlCharts.line({{
                canvas: document.getElementById('precalChart'),
                xLabel: 'distance from encode end (s)',
                yLabel: 'mean idle watts (8-poll window)',
                yUnit:  'W',
                datasets: [
                    {{ label: 'post-CPU encode', color: 'cpu',
                       points: cpu.map(p => ({{x:p.distance_s, y:p.mean_w}})) }},
                    {{ label: 'post-GPU encode', color: 'gpu',
                       points: gpu.map(p => ({{x:p.distance_s, y:p.mean_w}})) }},
                ]
            }});
            // Quick stats: idle reached, recommended cooldown (last point where mean delta to floor < 1W)
            const meanW = arr => arr.reduce((s,p)=>s+p.mean_w,0)/arr.length;
            const settled = data.points.filter(p => p.distance_s >= 60);
            const floor = settled.length ? meanW(settled).toFixed(2) : 'n/a';
            // Recovery threshold: first distance where mean within 1W of the settled floor
            function recoveryAt(workload) {{
                const pts = data.points.filter(p => p.workload === workload).sort((a,b)=>a.distance_s-b.distance_s);
                const f = parseFloat(floor);
                for (const p of pts) {{ if (Math.abs(p.mean_w - f) < 1.0) return p.distance_s; }}
                return null;
            }}
            const cpuRec = recoveryAt('cpu'), gpuRec = recoveryAt('gpu');
            const fname = data.source_summary.split('/').pop();
            meta.innerHTML = 'source: <code>' + fname + '</code> · generated ' + data.generated_at;
            stats.innerHTML =
                '· settled idle (d ≥ 60s mean): <strong style="color:var(--accent)">' + floor + ' W</strong><br>' +
                '· post-CPU recovery to ±1W of floor: <strong>' + (cpuRec !== null ? cpuRec + 's' : 'not within 1W') + '</strong><br>' +
                '· post-GPU recovery to ±1W of floor: <strong>' + (gpuRec !== null ? gpuRec + 's' : 'not within 1W') + '</strong><br>' +
                '· n distances: ' + (new Set(data.points.map(p=>p.distance_s))).size;
        }} catch(e) {{
            meta.innerHTML = '<span style="color:var(--err)">Failed to load probe data: ' + e + '</span>';
        }}
    }}
    const _precalDetails = document.getElementById('precalDetails');
    if (_precalDetails) {{
        _precalDetails.addEventListener('toggle', () => {{
            if (_precalDetails.open) loadPrecalibration();
        }});
    }}

    // Lab-only test-data cleanup panel. Lists recent results per type and lets
    // a Lab user delete a run's stored JSON via DELETE /results/<type>/<id>.
    // Delete buttons carry the id in data-attrs (no inline-quote escaping).
    async function loadTestData() {{
        const panel = document.getElementById('testdata-panel');
        if (!panel) return;
        const types = [['llm', 'LLM / RAG'], ['image', 'Image'], ['video', 'Video']];
        let html = '';
        for (const pair of types) {{
            const t = pair[0], lbl = pair[1];
            let runs = [];
            try {{
                const resp = await fetch('/results/' + t + '/list?limit=50');
                runs = await resp.json();
                if (!Array.isArray(runs)) runs = [];
            }} catch(e) {{ runs = []; }}
            html += '<div style="margin:0.75rem 0 0.3rem;color:var(--text-2)">' + lbl
                  + ' <span style="color:var(--text-5)">(' + runs.length + ')</span></div>';
            if (!runs.length) {{ html += '<div style="color:var(--text-5);font-size:0.75rem">none</div>'; continue; }}
            html += runs.map(function(r) {{
                const date = (r.saved_at || '').slice(0, 16).replace('T', ' ');
                const mode = r.mode ? ' &middot; ' + r.mode : '';
                return '<div style="display:flex;justify-content:space-between;align-items:center;'
                     + 'padding:0.25rem 0;border-bottom:1px solid var(--panel-2);gap:0.5rem">'
                     + '<span style="color:var(--text-3);font-size:0.75rem;font-family:monospace">'
                     + date + ' &middot; ' + r.job_id + mode + '</span>'
                     + '<button class="td-del" data-type="' + t + '" data-id="' + r.job_id + '" '
                     + 'style="background:none;border:1px solid var(--err);color:var(--err);'
                     + 'font-size:0.72rem;padding:0.1rem 0.5rem;cursor:pointer">&#10005; delete</button>'
                     + '</div>';
            }}).join('');
        }}
        panel.innerHTML = html;
        panel.querySelectorAll('.td-del').forEach(function(b) {{
            b.onclick = function() {{ deleteTestResult(b.getAttribute('data-type'), b.getAttribute('data-id')); }};
        }});
    }}

    async function deleteTestResult(jobType, jobId) {{
        // No per-delete confirm by design — the collapsed dropdown is the guard
        // (Lab tool). Deletes immediately and refreshes the panel.
        try {{
            const resp = await fetch('/results/' + jobType + '/' + jobId, {{method: 'DELETE'}});
            const d = await resp.json().catch(function() {{ return {{}}; }});
            if (d && d.ok) loadTestData();          // refresh the panel in place
            else alert('Delete failed: ' + ((d && d.error) || resp.status));
        }} catch(e) {{ alert('Delete failed: ' + e); }}
    }}

    // Lazy-load the cleanup lists when the dropdown is first opened (and refresh
    // on each open). Keeps the panel out of the way until the Lab user wants it.
    const _tdDetails = document.getElementById('testdataDetails');
    if (_tdDetails) {{
        _tdDetails.addEventListener('toggle', function() {{ if (_tdDetails.open) loadTestData(); }});
    }}
    </script>
    {_FOOTER}
</body>
</html>"""


@app.post("/settings", dependencies=[Depends(requires(SETTINGS_WRITE))])
async def settings_save(request: Request, data: dict):
    members_raw = data.pop("members", None)
    member_count = auth.write_members(members_raw) if members_raw is not None else None
    saved = cfg.save(data)
    # CR-050 — invalidate catalog caches so per-surface enable changes
    # take effect on the next /llm /rag /image /compare render without
    # waiting for the 60 s TTL.
    model_catalog.refresh_all()
    return {"ok": True, "settings": saved, "member_count": member_count}


# --- Demo mode ---

_DEMO_HTML = f"""<!DOCTYPE html>
<html>
<head>
<link rel="icon" type="image/svg+xml" href="/static/owl.svg">
<title>OWL — Guided Tour · Greening of Streaming</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);
       color:var(--text);max-width:840px;margin:0 auto;padding:2rem}}
  h1{{font-family:monospace;color:var(--accent);font-size:1.5rem;margin-bottom:0.25rem}}
  h2{{font-family:monospace;color:var(--accent);font-size:1.1rem;margin-bottom:0.75rem}}
  .mono{{font-family:monospace}}
  .dim{{color:var(--text-3)}}
  .accent{{color:var(--accent)}}

  /* Step nav */
  .step-nav{{display:flex;align-items:center;gap:0.5rem;margin-bottom:2.5rem;
             font-family:monospace;font-size:0.78rem;color:var(--text-5)}}
  .step-nav .dot{{width:8px;height:8px;border-radius:50%;background:var(--border);
                  transition:background 0.3s}}
  .step-nav .dot.done{{background:#00ff9966}}
  .step-nav .dot.active{{background:var(--accent)}}
  .step-nav .label{{color:var(--text-3);font-size:0.72rem}}
  .step-nav .label.active{{color:var(--accent)}}

  /* Steps */
  .step{{display:none}}
  .step.active{{display:block}}

  /* Logo header */
  .page-header{{display:flex;justify-content:space-between;align-items:flex-start;
                margin-bottom:2rem}}

  /* Big metric */
  .big-metric{{font-family:monospace;font-size:3.5rem;color:var(--accent);
               font-weight:bold;line-height:1;margin:1rem 0}}
  .big-label{{color:var(--text-3);font-size:0.85rem;margin-bottom:2rem}}

  /* Methodology expander */
  details{{margin:1rem 0;border-left:2px solid #222;padding-left:1rem}}
  summary{{color:var(--text-4);font-size:0.8rem;cursor:pointer;list-style:none;
           padding:0.4rem 0;user-select:none}}
  summary::-webkit-details-marker{{display:none}}
  summary::before{{content:"▶  ";font-size:0.65rem}}
  details[open] summary::before{{content:"▼  "}}
  details p{{color:var(--text-3);font-size:0.82rem;line-height:1.7;margin-top:0.5rem}}
  details p+p{{margin-top:0.5rem}}

  /* Action buttons */
  .btn-row{{display:flex;gap:0.75rem;flex-wrap:wrap;margin-top:1.5rem}}
  .btn{{font-family:monospace;font-size:0.9rem;padding:0.65rem 1.5rem;
        cursor:pointer;border:none;transition:background 0.15s}}
  .btn-primary{{background:var(--accent);color:#000}}
  .btn-primary:hover{{background:var(--accent-hover)}}
  .btn-secondary{{background:transparent;color:var(--accent);
                  border:1px solid #00ff9944}}
  .btn-secondary:hover{{background:#00ff9911}}
  .btn:disabled{{background:#1a1a1a;color:var(--text-5);cursor:not-allowed;border:none}}

  /* Result card */
  .result-card{{border:1px solid var(--border-2);padding:1.5rem;margin-top:1.5rem}}
  .result-card .headline{{font-size:1rem;color:var(--text);line-height:1.6;
                           margin-bottom:1rem}}
  .kpi-row{{display:flex;gap:1.5rem;flex-wrap:wrap;margin-bottom:1rem}}
  .kpi{{flex:1;min-width:120px}}
  .kpi .val{{font-family:monospace;font-size:1.4rem;color:var(--accent)}}
  .kpi .lbl{{font-size:0.72rem;color:var(--text-4);margin-top:0.2rem}}
  .conf-badge{{display:inline-block;font-size:0.75rem;color:var(--text-3);
               margin-top:0.5rem}}
  .response-preview{{background:var(--panel-2);border-left:2px solid #00ff9933;
                     padding:0.75rem 1rem;margin-top:1rem;font-size:0.8rem;
                     color:var(--text-3);line-height:1.7;max-height:300px;
                     overflow-y:auto;white-space:pre-wrap;font-family:monospace}}
  .scope-note{{color:var(--text-5);font-size:0.72rem;margin-top:1rem;font-family:monospace}}
  .prev-note{{color:var(--text-5);font-size:0.75rem;font-family:monospace;
              margin-top:0.5rem}}
  .divider{{border:none;border-top:1px solid var(--panel);margin:1.5rem 0}}

  /* Three-band layout */
  .band{{margin-bottom:1.75rem;padding-bottom:1.75rem;border-bottom:1px solid var(--panel-2)}}
  .band-label{{color:var(--text-5);font-size:0.68rem;text-transform:uppercase;letter-spacing:0.08em;
               font-family:monospace;margin-bottom:0.6rem}}
  .limitation{{color:var(--text-5);font-size:0.75rem;margin-top:1rem;line-height:1.6;
               font-family:monospace;border-left:1px solid var(--border-2);padding-left:0.75rem}}

  /* Progress */
  .progress-note{{color:var(--warn);font-family:monospace;font-size:0.85rem;
                  margin-top:1rem}}
  .stream-box{{background:var(--panel-2);border-left:2px solid #00ff9922;
               padding:0.75rem 1rem;margin-top:0.75rem;font-size:0.78rem;
               color:var(--text-4);line-height:1.7;max-height:160px;overflow-y:auto;
               white-space:pre-wrap;font-family:monospace;min-height:2.5rem}}

  /* Summary table */
  .summary-table{{width:100%;border-collapse:collapse;font-family:monospace;
                  font-size:0.82rem;margin-top:1rem}}
  .summary-table td{{padding:0.5rem 0.75rem;border-bottom:1px solid var(--panel)}}
  .summary-table td:first-child{{color:var(--text-3);width:40%}}
  .summary-table td:last-child{{color:var(--accent)}}

  /* CR-001 capability matrix — Findings step. Locked rows are the
     GoS membership pitch; visual treatment must read as product copy,
     not as a punishment. CR-027: three columns ("Public" / "Member" /
     "Lab"), with the Member column accent-tinted so the eye lands there
     (Member sign-up is the conversion target; Lab is operator-only and
     visible mostly so visitors understand the access ladder). */
  .cap-matrix{{width:100%;border-collapse:collapse;margin:0.5rem 0 1.5rem;
               font-family:monospace;font-size:0.83rem}}
  .cap-matrix thead th{{padding:0.6rem 0.5rem;text-align:left;
                         border-bottom:1px solid var(--border-3);
                         color:var(--text-4);font-weight:normal;
                         font-size:0.72rem;letter-spacing:0.08em;
                         text-transform:uppercase}}
  .cap-matrix .cap-col-anon{{width:23%;color:var(--text-3)}}
  .cap-matrix .cap-col-member{{width:23%;color:var(--accent)}}
  .cap-matrix .cap-col-lab{{width:23%;color:var(--text-4)}}
  .cap-matrix tbody td{{padding:0.55rem 0.5rem;
                         border-bottom:1px solid var(--panel);
                         color:var(--text-3);line-height:1.5}}
  .cap-matrix tbody tr td:first-child{{color:var(--text-2);
                                         font-family:system-ui,sans-serif;
                                         font-size:0.88rem;width:31%}}
  .cap-matrix .cap-yes{{color:var(--accent);font-weight:bold}}
  .cap-matrix .cap-no{{color:var(--text-5)}}
  .cap-matrix .cap-partial{{color:var(--warn);font-size:0.78rem}}
  .cap-cta{{display:flex;gap:0.75rem;flex-wrap:wrap;margin-top:1.5rem;
            justify-content:center}}
  {{AUTH_CHIP_STYLES}}
</style>
</head>
<body>
    {{AUTH_CHIP}}
    {_BACK}
<div class="page-header">
  <div id="step-nav" class="step-nav">
    <span class="dot active" id="dot-0"></span>
    <span class="dot" id="dot-1"></span>
    <span class="dot" id="dot-2"></span>
    <span class="dot" id="dot-3"></span>
    <span class="dot" id="dot-4"></span>
    <span class="dot" id="dot-5"></span>
    <span class="dot" id="dot-6"></span>
    <span class="label active" id="nav-label">Welcome</span>
    <span id="step-counter" style="color:var(--text-5);font-size:0.7rem;margin-left:0.25rem">1 / 7</span>
  </div>
</div>

<!-- Step 0: Welcome -->
<div class="step active" id="step-0">
  <h1>OWL</h1>
  <p style="color:var(--text-3);font-size:0.85rem;margin-bottom:1.5rem">
    Greening of Streaming · Live energy measurement · GoS1</p>

  {{TIER_INDICATOR}}

  <p style="color:var(--text-2);line-height:1.8;max-width:560px">
    OWL measures the real energy cost of video transcoding and AI inference —
    using a calibrated smart plug, not estimates. Every number on this page
    comes from a live measurement on GoS1, a server in our lab in France.
  </p>

  <div class="big-metric" id="live-watts">— W</div>
  <div class="big-label">GoS1 current power draw · {{METER_NAME}} · device layer only</div>

  <details>
    <summary>What's being measured?</summary>
    <p>GoS1 is an AMD Ryzen 9 workstation with an {{GPU_DISPLAY_NAME}} GPU.
    Power is sampled at 1-second intervals via a {{METER_NAME}}
    connected to the mains supply. We measure the delta between idle
    baseline and task power — not estimated TDP or nameplate figures.</p>
    <p>Scope: device layer only. Network, CDN, and CPE are explicitly excluded.
    Amortised embodied carbon and training cost are not included in LLM measurements.</p>
  </details>

  <details>
    <summary>Why does this matter?</summary>
    <p>Streaming accounts for a significant and growing share of global internet
    traffic. Codec choice, inference model size, and hardware path all affect
    real energy use — but most published figures are estimates or averages.
    OWL produces primary measurement data that operators and researchers
    can reproduce and cite.</p>
  </details>

  <p style="margin-top:1.25rem;font-size:0.85rem;color:var(--text-3)">
    <a href="/methodology" style="color:var(--accent);text-decoration:none;border-bottom:1px solid var(--border-2);padding-bottom:1px">
      &rarr; Read the full measurement methodology</a>
    <span style="color:var(--text-5);margin-left:0.5rem">protocol, confidence framework, scope statements, calibration</span>
  </p>

  <div class="btn-row">
    <button class="btn btn-primary" onclick="goStep(1)">Start Tour →</button>
  </div>
</div>

<!-- Step 1: Video -->
<div class="step" id="step-1">
  <h1>Video Transcode</h1>

  <div class="band">
    <div class="band-label">What this shows</div>
    <p style="color:var(--text-2);line-height:1.8;max-width:560px">
      Whether transcoding to the same quality target uses more energy on CPU or GPU —
      and whether the faster path is also the more efficient one.
    </p>
  </div>

  <div class="band">
    <div class="band-label">What we're doing</div>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px;margin-bottom:0.75rem">
      Encoding a 4K clip (Meridian, Netflix Open Content, CC BY 4.0) to 1080p H.264 —
      once in software (libx264, CPU only) and once as a full GPU pipeline
      (hardware decode + encode via {{GPU_H264_ENC}}). Same source. Same quality target.
      P110 sampled every second throughout.
    </p>
    <details>
      <summary>How this is measured</summary>
      <p>{{BASELINE_POLLS}}s idle baseline before each run. {{VIDEO_COOLDOWN_S}}s thermal cooldown between CPU and GPU.
      Energy = ΔW × duration / 3600. Confidence 🟢 = ΔW &gt; {{CONF_GREEN_X}}× noise and ≥ {{CONF_GREEN_POLLS}} polls.</p>
      <p>Source: 812 MB, 4K. Encode time ~2–3 min CPU, ~90s GPU (full pipeline).
      Previous runs (partial pipeline): CPU 174s / 4.06 Wh · GPU 114s / 4.42 Wh.
      Full pipeline results pending first run.</p>
    </details>
  </div>

  <div>
    <div class="band-label">Result</div>
    <div id="video-action">
      <div id="video-btns" style="display:none">
        <!-- CR-033 — codec chips select which both-mode runs. Both chips use
             meridian_120s; preset switches between h265_both and av1_both.
             The run-button label updates to reflect the choice. -->
        <div class="btn-row" id="demo-codec-chips" style="margin-bottom:0.6rem;gap:0.4rem">
          <button type="button" class="demo-chip" id="demo-chip-h265"
                  data-codec="h265" data-codec-label="H.265"
                  onclick="selectDemoCodec('h265')"
                  style="padding:0.35rem 0.7rem;font-size:0.78rem;
                         background:var(--accent);color:var(--bg);
                         border:1px solid var(--accent);border-radius:3px;
                         font-family:inherit;cursor:pointer">
            H.265 (CPU vs GPU)
          </button>
          <button type="button" class="demo-chip" id="demo-chip-av1"
                  data-codec="av1" data-codec-label="AV1"
                  onclick="selectDemoCodec('av1')"
                  style="padding:0.35rem 0.7rem;font-size:0.78rem;
                         background:transparent;color:var(--text-3);
                         border:1px solid var(--border-3);border-radius:3px;
                         font-family:inherit;cursor:pointer">
            AV1 (CPU vs GPU)
          </button>
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" id="btn-run-video" onclick="runDemoVideo()">
            Run a standard transcode (H.265 CPU vs GPU on Meridian 2&thinsp;min · ~3&thinsp;min)</button>
        </div>
      </div>
      <div id="video-status"></div>
    </div>
    <p class="limitation">Scope: device layer only (GoS1). Network, CDN, and CPE not included.
    A faster encode does not automatically mean less energy — this measures total Wh, not rate.</p>
  </div>

  <div id="next-1" style="display:none;margin-top:2rem;padding-top:1.5rem;border-top:1px solid var(--panel)">
    <div style="margin-bottom:1.25rem;padding:0.85rem 1rem;border:1px dashed var(--border-3);
                background:var(--panel-2);font-size:0.78rem;color:var(--text-3);
                line-height:1.6;max-width:560px">
      <div style="color:var(--text-5);font-size:0.6rem;letter-spacing:0.1em;
                  text-transform:uppercase;margin-bottom:0.4rem">
        Entering beta · exploratory</div>
      That was the production-grade GoS measurement — video transcoding is what
      we report on with confidence. The next three steps cover exploratory AI
      workloads (LLM, image, RAG): less mature, signal can sit below the P110
      floor on small tasks, and quality / faithfulness matter alongside energy.
      Stop here if you only wanted the streaming-impact story.
    </div>
    <div class="btn-row">
      <button class="btn btn-secondary" onclick="goStep(0)">← Welcome</button>
      <button class="btn btn-primary" onclick="goStep(2)">Next: LLM inference →</button>
      <button class="btn btn-secondary" onclick="resetVideoStep()">Run a fresh transcode</button>
    </div>
  </div>
</div>

<!-- Step 2: LLM -->
<div class="step" id="step-2">
  <h1>LLM Inference {{BETA_CHIP}}</h1>

  <div class="band">
    <div class="band-label">What this shows</div>
    <p style="color:var(--text-2);line-height:1.8;max-width:560px">
      How much energy each generated token costs — and how model size
      translates into energy use per unit of output.
    </p>
  </div>

  <div class="band">
    <div class="band-label">What we're doing</div>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px;margin-bottom:0.75rem">
      Running a fixed prompt (T3 Long — network energy attribution briefing)
      through Mistral 7B cold: model unloaded before baseline so we capture
      the true first-request cost. GPU inference via Ollama ROCm.
    </p>
    <details>
      <summary>How this is measured</summary>
      <p>Model unloaded from VRAM. 3s settle. 10s idle baseline. Single inference run.
      P110 at 1s intervals. Primary metric: mWh per output token.</p>
      <p>Model: Mistral 7B (4.4 GB). Previous result: 0.94 mWh/tok, ~47 tok/s.</p>
    </details>
    <details>
      <summary>Why mWh per token?</summary>
      <p>Token count varies between models and prompts, so raw Wh figures aren't
      comparable. Energy per token lets us place TinyLlama (0.06 mWh/tok) and
      Mistral 7B (0.94 mWh/tok) on the same axis — a ~15× difference.</p>
    </details>
  </div>

  <div>
    <div class="band-label">Result</div>
    <div id="llm-action">
      <div class="btn-row" id="llm-btns" style="display:none">
        <button class="btn btn-primary" id="btn-run-llm" onclick="runDemoLLM()">
          Run a standard LLM generation (Mistral 7B · cold · T3 prompt · ~3&thinsp;min)</button>
      </div>
      <div id="llm-status"></div>
    </div>
    <p class="limitation">Scope: device layer only (GoS1). No amortised training cost included.
    mWh/token measures inference energy only — not the energy cost of training the model.</p>
  </div>

  <div id="next-2" style="display:none;margin-top:2rem;padding-top:1.5rem;border-top:1px solid var(--panel)">
    <div class="btn-row">
      <button class="btn btn-secondary" onclick="goStep(1)">← Video</button>
      <button class="btn btn-primary" onclick="goStep(3)">Next: Image generation →</button>
      <button class="btn btn-secondary" onclick="resetLLMStep()">Run a fresh LLM generation</button>
    </div>
  </div>
</div>

<!-- Step 3: Image generation -->
<div class="step" id="step-3">
  <h1>Image Generation {{BETA_CHIP}}</h1>

  <div class="band">
    <div class="band-label">What this shows</div>
    <p style="color:var(--text-2);line-height:1.8;max-width:560px">
      How much energy one AI-generated image costs — measured end to end on
      real hardware, not estimated from TDP or cloud benchmarks.
    </p>
  </div>

  <div class="band">
    <div class="band-label">What we're doing</div>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px;margin-bottom:0.75rem">
      Running SD-Turbo (stabilityai/sd-turbo, CPU, 8 steps, 512×512) with a
      randomly modified prompt — the colour modifier changes each run to prove
      the image is generated live, not replayed from cache.
    </p>
    <details>
      <summary>How this is measured</summary>
      <p>10s idle baseline. CPU diffusion run. P110 at 1s intervals.
      Metric: Wh per image = ΔW × generation_time / 3600.</p>
      <p>Previous result: 0.21 Wh/image, 12s, ~30W delta above idle.</p>
    </details>
  </div>

  <div>
    <div class="band-label">Result</div>
    <div id="image-btns" class="btn-row" style="display:none">
      <button class="btn btn-primary" onclick="runDemoImage()">Run a standard image generation (SD-Turbo · 512&times;512 · ~30&thinsp;s)</button>
    </div>
    <div id="image-status"></div>
    <p class="limitation">Scope: device layer only (GoS1). Network and storage excluded.
    This measures one image on one machine — not the energy cost of a hosted API call.</p>
  </div>

  <div id="next-3" style="display:none;margin-top:2rem;padding-top:1.5rem;border-top:1px solid var(--panel)">
    <div class="btn-row">
      <button class="btn btn-secondary" onclick="goStep(2)">← LLM</button>
      <button class="btn btn-primary" onclick="goStep(4)">Next: RAG →</button>
      <button class="btn btn-secondary" onclick="resetImageStep()">Run a fresh image generation</button>
    </div>
  </div>
</div>

<!-- Step 4: RAG -->
<div class="step" id="step-4">
  <h1>RAG Energy Cost {{BETA_CHIP}}</h1>

  <div class="band">
    <div class="band-label">What this shows</div>
    <p style="color:var(--text-2);line-height:1.8;max-width:560px">
      Whether retrieval-augmented generation (RAG) — searching a local corpus
      before answering — costs meaningfully more energy than plain inference,
      and see the difference in context size the model must process.
    </p>
  </div>

  <div class="band">
    <div class="band-label">What we're doing</div>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px;margin-bottom:0.75rem">
      Running three modes back-to-back on Mistral 7B: baseline (no retrieval),
      RAG (small corpus), and RAG Large (with re-ranking).
      Same question, same model, same hardware — only the retrieval pipeline changes.
    </p>
    <details>
      <summary>How this is measured</summary>
      <p>Each mode: 10s idle baseline, inference with P110 at 1s intervals.
      Metric: mWh per output token. ChromaDB embeddings via sentence-transformers.
      Corpus: academic papers on streaming energy.</p>
    </details>
  </div>

  <div>
    <div class="band-label">Result</div>
    <div id="rag-btns" class="btn-row" style="display:none">
      <button class="btn btn-primary" onclick="runDemoRAG()">Run a standard RAG energy test (Mistral 7B · 3-mode · ~10&thinsp;min)</button>
    </div>
    <div id="rag-status"></div>
    <p class="limitation">Scope: device layer only (GoS1). Network excluded.
    RAG retrieval adds overhead but the dominant cost remains token generation.</p>
  </div>

  <div id="next-4" style="display:none;margin-top:2rem;padding-top:1.5rem;border-top:1px solid var(--panel)">
    <div class="btn-row">
      <button class="btn btn-secondary" onclick="goStep(3)">← Image</button>
      <button class="btn btn-primary" onclick="goStep(5)">Next: How we flag confidence →</button>
      <button class="btn btn-secondary" onclick="resetRAGStep()">Run a fresh RAG energy test</button>
    </div>
  </div>
</div>

<!-- Step 5: Confidence -->
<div class="step" id="step-5">
  <h1>How We Flag Confidence</h1>

  <div class="band">
    <div class="band-label">The problem</div>
    <p style="color:var(--text-2);line-height:1.8;max-width:560px">
      Not every measurement we take is equally trustworthy.
      System noise — P110 quantisation, OS jitter, Wi-Fi polling variance — is real.
      A task that adds a small delta above baseline might be signal or artefact.
      We need a principled way to say which.
    </p>
  </div>

  <div class="band">
    <div class="band-label">The system</div>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px;margin-bottom:1rem">
      Every result carries a traffic light. As of CR-028 Phase 2 it's a <em>per-run
      confidence interval</em> — "can this run be told apart from idle?" — not a fixed
      watt rule.
      <code style="font-family:monospace;font-size:0.82rem;color:var(--text-3)">confidence = Φ(ΔW / SE), SE from this run's noise + the calibrated idle floor</code>
    </p>
    <div style="display:flex;flex-direction:column;gap:0.75rem;max-width:480px">
      <div style="border-left:2px solid #1a3a1a;padding:0.6rem 1rem">
        <div style="font-family:monospace;font-size:0.9rem">🟢 Repeatable</div>
        <div style="color:var(--text-3);font-size:0.82rem;margin-top:0.25rem">
          ≥95% confident above idle <em>and</em> ≥ {{CONF_GREEN_POLLS}} task polls. Reliable enough to cite.</div>
      </div>
      <div style="border-left:2px solid #3a3a00;padding:0.6rem 1rem">
        <div style="font-family:monospace;font-size:0.9rem">🟡 Early insight</div>
        <div style="color:var(--text-3);font-size:0.82rem;margin-top:0.25rem">
          ≥80% confident above idle <em>and</em> ≥ {{CONF_YELLOW_POLLS}} task polls. Directional, but needs a longer run
          before we'd stake a public claim on it.</div>
      </div>
      <div style="border-left:2px solid #2a0000;padding:0.6rem 1rem">
        <div style="font-family:monospace;font-size:0.9rem">🔴 Need more data</div>
        <div style="color:var(--text-3);font-size:0.82rem;margin-top:0.25rem">
          Not yet distinguishable from idle.
          We publish it anyway — but we won't cite it yet.</div>
      </div>
    </div>
  </div>

  <div class="band">
    <div class="band-label">Why a confidence interval?</div>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px;margin-bottom:0.75rem">
      Fixed thresholds (e.g. "5W = green") don't adapt to the machine's actual noise
      level. Instead we take this run's own baseline + task power samples, form a
      standard error on ΔW (worst case of the run's observed noise and the calibrated
      idle floor, plus a drift term), and turn ΔW into a one-sided confidence that the
      task draws above idle. A short run can't go green on a couple of lucky readings —
      it also needs enough task polls.
    </p>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px">
      On any result page, click a 🟢 🟡 🔴 badge for a quick reminder of the formula.
    </p>
  </div>

  <div class="btn-row" style="margin-top:0.5rem">
    <button class="btn btn-secondary" onclick="goStep(4)">← RAG</button>
    <button class="btn btn-primary" onclick="goStep(6)">See findings →</button>
  </div>
</div>

<!-- Step 6: Findings -->
<div class="step" id="step-6">
  <h1>Findings</h1>
  <p style="color:var(--text-3);font-size:0.85rem;margin-bottom:1.5rem">
    Greening of Streaming · OWL · GoS1</p>

  <div id="summary-content">
    {{FINDINGS_PANEL}}
  </div>

  <hr class="divider">

  <!-- CR-001 capability matrix; CR-027 three-column refresh.
       Same measurement quality across all three tiers — what changes is
       who shapes the inputs. Member is the conversion target (accent
       column), Lab is shown so visitors understand the full access ladder
       and see who runs the bench. Upload caps are wired to settings.json
       via the UPLOAD_MEMBER_MB placeholder so this table never silently drifts. -->
  <h2 style="margin-top:2rem;margin-bottom:0.5rem">Want to dig deeper?</h2>
  <p style="color:var(--text-3);font-size:0.85rem;margin-bottom:1.25rem;line-height:1.6">
    OWL has three access tiers. The numbers and methodology you've just
    seen are identical for all three — what changes is who can shape the
    inputs (custom prompts, custom ffmpeg, all-codecs sweeps, your own
    corpus, full settings access).
  </p>
  <table class="cap-matrix">
    <thead>
      <tr>
        <th></th>
        <th class="cap-col-anon">Public</th>
        <th class="cap-col-member">GoS member</th>
        <th class="cap-col-lab">Lab (operator)</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Pre-baked workloads, live wall-power &amp; CO<sub>2</sub>e</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
      </tr>
      <tr>
        <td>Guided tour, methodology, recent-run history</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
      </tr>
      <tr>
        <td>Custom video upload</td>
        <td class="cap-no">—</td>
        <td class="cap-yes">≤ {{UPLOAD_MEMBER_MB}} MB</td>
        <td class="cap-yes">no cap</td>
      </tr>
      <tr>
        <td>Custom prompts &amp; custom ffmpeg commands</td>
        <td class="cap-no">—</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
      </tr>
      <tr>
        <td>All-codecs sweeps, batch / compare-modes</td>
        <td class="cap-no">—</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
      </tr>
      <tr>
        <td>RAG corpus upload (your own PDFs)</td>
        <td class="cap-no">—</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
      </tr>
      <tr>
        <td>CSV / JSON export of your runs</td>
        <td class="cap-no">—</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
      </tr>
      <tr>
        <td>Edit settings, run variance calibration, full results view</td>
        <td class="cap-no">—</td>
        <td class="cap-no">—</td>
        <td class="cap-yes">✓</td>
      </tr>
    </tbody>
  </table>
  <p style="color:var(--text-5);font-size:0.72rem;margin-top:0.25rem;margin-bottom:1.25rem;
            font-family:monospace;line-height:1.5">
    Lab tier is granted automatically on the GoS1 LAN (loopback / 192.168.x).
    There's no public sign-up for Lab — it's the operator surface for the
    bench itself.
  </p>
  <div class="cap-cta">
    <a href="{JOIN_GOS_URL}" target="_blank"
       class="btn btn-primary" style="text-decoration:none;display:inline-block;line-height:1">
      Join GoS — unlock the middle column ↗</a>
    <a href="/auth/sign-in" class="btn btn-secondary"
       style="text-decoration:none;display:inline-block;line-height:1">
      Already a member? Sign in</a>
  </div>
  <p style="color:var(--text-5);font-size:0.72rem;margin-top:1rem;font-family:monospace;text-align:center">
    Same measurement quality on every tier. Members shape the inputs; everyone sees the results.
  </p>

  <hr class="divider">
  <div class="btn-row">
    <button class="btn btn-secondary" onclick="goStep(5)">← Confidence</button>
    <button class="btn btn-secondary" onclick="goStep(1)">↺ Start over</button>
    <a href="{GOS_URL}" target="_blank"
       class="btn btn-secondary" style="text-decoration:none;display:inline-block;line-height:1">
      greeningofstreaming.org ↗</a>
  </div>
  <p class="scope-note" style="margin-top:1.5rem">
    Scope: device layer only (GoS1). Network, CDN, CPE excluded.<br>
    LLM: no amortised training cost included.</p>
</div>

<script>
// ─── State ──────────────────────────────────────────────────────────────────
let currentStep = 0;
let videoResult = null;
let llmResult = null;
let imageResult = null;
let ragResult = null;
const stepLabels = ['Welcome', 'Video Transcode', 'LLM Inference', 'Image Generation', 'RAG', 'Confidence', 'Findings'];
let streamTimer = null;
let imageTimer = null;

// ─── Step navigation ─────────────────────────────────────────────────────────
function goStep(n) {{
  document.querySelectorAll('.step').forEach(el => el.classList.remove('active'));
  document.getElementById('step-' + n).classList.add('active');
  for (let i = 0; i < 7; i++) {{
    const dot = document.getElementById('dot-' + i);
    dot.className = 'dot' + (i < n ? ' done' : i === n ? ' active' : '');
  }}
  const lbl = document.getElementById('nav-label');
  lbl.textContent = stepLabels[n];
  lbl.className = 'label active';
  document.getElementById('step-counter').textContent = (n + 1) + ' / 7';
  currentStep = n;
  window.scrollTo(0, 0);
  // Tour navigation is NEVER gated on a pre-loaded result rendering. Reveal
  // the measurement step's Next button on entry so the visitor can always
  // advance — even when /demo/last/* returns a shape the single-run card
  // renderer doesn't recognise (a compare/RAG record), which previously left
  // renderLLMResult / renderDemoImageResult bailing out before revealNext and
  // trapped the tour on the LLM and Image steps. The pre-load below is
  // decorative: it populates the card but must not be able to block the tour.
  if (n >= 1 && n <= 4) revealNext(n);
  if (n === 1 && !videoResult) loadVideoStep();
  if (n === 2 && !llmResult) loadLLMStep();
  if (n === 3 && !imageResult) loadImageStep();
  if (n === 4 && !ragResult) loadRAGStep();
  if (n === 6) buildSummary();
}}

function revealNext(n) {{
  const el = document.getElementById('next-' + n);
  if (el) el.style.display = 'block';
}}

function loadVideoStep() {{
  document.getElementById('video-status').innerHTML = '<p class="progress-note" style="color:var(--text-3)">Loading last result…</p>';
  showPrevVideo();
}}
function loadLLMStep() {{
  document.getElementById('llm-status').innerHTML = '<p class="progress-note" style="color:var(--text-3)">Loading last result…</p>';
  showPrevLLM();
}}
function loadImageStep() {{
  document.getElementById('image-status').innerHTML = '<p class="progress-note" style="color:var(--text-3)">Loading last result…</p>';
  showPrevImage();
}}
function loadRAGStep() {{
  document.getElementById('rag-status').innerHTML = '<p class="progress-note" style="color:var(--text-3)">Loading last result…</p>';
  showPrevRAG();
}}

// ─── Live power ───────────────────────────────────────────────────────────────
async function refreshPower() {{
  try {{
    const resp = await fetch('/power');
    const data = await resp.json();
    document.getElementById('live-watts').textContent = data.watts.toFixed(1) + ' W';
  }} catch(e) {{}}
}}
refreshPower();
setInterval(refreshPower, 10000);

// ─── Helpers ─────────────────────────────────────────────────────────────────
function timeAgo(isoStr) {{
  if (!isoStr) return '';
  const diff = (Date.now() - new Date(isoStr)) / 1000;
  if (diff < 120) return 'just now';
  if (diff < 3600) return Math.floor(diff/60) + ' min ago';
  if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
  return Math.floor(diff/86400) + 'd ago';
}}

function fmt(v, dec=2) {{ return v != null ? Number(v).toFixed(dec) : '—'; }}

// ─── Previous run ─────────────────────────────────────────────────────────────
// CR-026 carve-out: /demo loads the latest result regardless of visitor
// via the dedicated /demo/last/{type} endpoint. Without this carve-out,
// Anonymous visitors land on an empty guided tour because their session
// has never produced a run.
async function showPrevVideo() {{
  document.getElementById('video-btns').style.display = 'none';
  try {{
    const resp = await fetch('/demo/last/video');
    if (resp.status === 404) {{
      document.getElementById('video-status').innerHTML =
        '<p class="progress-note" style="color:var(--text-3)">No previous run on file — run one below, or skip ahead.</p>';
      document.getElementById('video-btns').style.display = 'flex';
      revealNext(1);
      return;
    }}
    const full = await resp.json();
    videoResult = full;
    renderVideoResult(full, full.saved_at, true);
  }} catch(e) {{
    document.getElementById('video-btns').style.display = 'flex';
    document.getElementById('video-status').innerHTML =
      '<p class="progress-note" style="color:var(--err)">Error: ' + e + '</p>';
    revealNext(1);
  }}
}}

async function showPrevLLM() {{
  document.getElementById('llm-btns').style.display = 'none';
  try {{
    // RAG runs persist under results/llm/ too; exclude them server-side
    // by listing and filtering. The /demo/last/{type} endpoint returns
    // the first run that doesn't have task starting with "RAG".
    const resp = await fetch('/demo/last/llm');
    if (resp.status === 404) {{
      document.getElementById('llm-status').innerHTML =
        '<p class="progress-note" style="color:var(--text-3)">No previous run on file — run one below, or skip ahead.</p>';
      document.getElementById('llm-btns').style.display = 'flex';
      revealNext(2);
      return;
    }}
    const full = await resp.json();
    if ((full.task || '').startsWith('RAG')) {{
      // Most recent llm/ entry is a RAG run — fall back to "no run".
      document.getElementById('llm-status').innerHTML =
        '<p class="progress-note" style="color:var(--text-3)">No previous LLM run on file — run one below, or skip ahead.</p>';
      document.getElementById('llm-btns').style.display = 'flex';
      revealNext(2);
      return;
    }}
    llmResult = full;
    renderLLMResult(full, full.saved_at, true);
  }} catch(e) {{
    document.getElementById('llm-btns').style.display = 'flex';
    document.getElementById('llm-status').innerHTML =
      '<p class="progress-note" style="color:var(--err)">Error: ' + e + '</p>';
    revealNext(2);
  }}
}}


// ─── Run new video measurement ────────────────────────────────────────────────
//
// Predetermined demo job: H.265 CPU vs GPU on the 2-minute Meridian sample.
// Bounded (~2-3 min wall time including baselines + cooldowns), demonstrates
// the GPU advantage cleanly, and lets the visitor get to the result card
// while the demo session is still fresh in their head. The full-Meridian +
// both-codecs run that lived here previously was a 10-15 minute commitment,
// which broke the guided-tour flow on the public surface. CR-033 captures
// follow-up: offer a small set of curated demo jobs (e.g. H.265 CPU vs GPU,
// AV1 CPU vs GPU) for visitors who want to compare codec families.
// CR-033 — codec chip state for the demo step 1 video block. Default is
// H.265 (matches the canonical streaming workload + current expectations).
// AV1 is the alternate; both run on meridian_120s with the same shape.
let selectedDemoCodec = 'h265';

function selectDemoCodec(codec) {{
  selectedDemoCodec = codec;
  document.querySelectorAll('.demo-chip').forEach(el => {{
    const on = el.dataset.codec === codec;
    el.style.background = on ? 'var(--accent)' : 'transparent';
    el.style.color      = on ? 'var(--bg)'     : 'var(--text-3)';
    el.style.borderColor = on ? 'var(--accent)' : 'var(--border-3)';
  }});
  const btn = document.getElementById('btn-run-video');
  if (btn) {{
    const label = codec === 'av1' ? 'AV1' : 'H.265';
    btn.innerHTML = 'Run a standard transcode (' + label
      + ' CPU vs GPU on Meridian 2&thinsp;min · ~3&thinsp;min)';
  }}
}}

async function runDemoVideo() {{
  document.getElementById('video-btns').style.display = 'none';
  try {{
    // Show the progress widget immediately rather than a stale "Starting…"
    // line — pollVideo's first response is up to 5s away, so the empty
    // shell tells the visitor "yes, something is happening" right away.
    // Inside the try so that if wlRenderProgress (or any prerequisite
    // global) is undefined, the failure surfaces via showVideoError
    // instead of silently leaving the button hidden + page blank.
    wlRenderProgress({{
      target: 'video-status',
      header: 'Submitting video job…',
      stagesHtml: wlStageList(WL_VIDEO_STAGES, 0),
      elapsed: 0,
    }});
    const form = new FormData();
    form.append('source_key', 'meridian_120s');
    form.append('preset', selectedDemoCodec === 'av1' ? 'av1_both' : 'h265_both');
    const resp = await fetch('/video/use-source', {{method:'POST', body:form}});
    const data = await resp.json();
    if (data.job_id) {{
      pollVideo(data.job_id, Date.now());
    }} else {{
      showVideoError(JSON.stringify(data));
    }}
  }} catch(e) {{ showVideoError(e); }}
}}

function showVideoError(msg) {{
  document.getElementById('video-btns').style.display = 'flex';
  document.getElementById('video-status').innerHTML =
    '<p class="progress-note" style="color:var(--err)">Error: ' + msg + '</p>';
}}

// CR-019 — /demo's poll loops use the shared wlRenderProgress widget
// (with opts.target → per-step status div) so visitors see the same
// big live wall-power readout and stage list as the main pages.
const VIDEO_STAGE_IDX = {{
  starting: 0, baseline: 0, baseline_2: 0,
  cpu_encode: 1, gpu_encode: 1,
  rest: 2,
  done: 3,
}};

function pollVideo(jobId, t0) {{
  fetch('/video/job/' + jobId).then(r=>r.json()).then(data => {{
    if (data.status === 'done') {{
      videoResult = data.result;
      renderVideoResult(data.result, new Date().toISOString(), false);
    }} else if (data.status === 'error') {{
      showVideoError(data.error);
    }} else {{
      const stage = data.stage || '';
      const idx = VIDEO_STAGE_IDX[stage] ?? 0;
      // For *_both presets the four stages cycle once for CPU then again
      // for GPU (baseline → encode → rest → baseline_2 → encode again).
      // Without an explicit side label, the visitor sees the bar "go
      // around twice" with no idea why. This banner names which side is
      // currently running, mirroring the RAG mode-of-3 banner.
      const sideLabels = {{
        baseline:    'Side 1 of 2 — CPU encode (measuring baseline)',
        cpu_encode:  'Side 1 of 2 — CPU encode',
        rest:        'Cooldown — letting thermals settle before GPU',
        baseline_2:  'Side 2 of 2 — GPU encode (measuring baseline)',
        gpu_encode:  'Side 2 of 2 — GPU encode',
      }};
      const lbl = sideLabels[stage] || '';
      const sideLine = lbl
        ? '<div style="color:var(--accent);font-size:0.82rem;margin-top:0.6rem;font-weight:bold">' + lbl + '</div>'
        : '';
      wlRenderProgress({{
        target: 'video-status',
        stagesHtml: wlStageList(WL_VIDEO_STAGES, idx),
        watts: data.watts,
        elapsed: Date.now() - t0,
        progressPct: data.progress_pct,
        etaS:        data.eta_s,
        encodeSpeed: data.encode_speed,
        extraHtml: sideLine,
      }});
      setTimeout(() => pollVideo(jobId, t0), 5000);
    }}
  }}).catch(() => setTimeout(() => pollVideo(jobId, t0), 5000));
}}

// ─── Run new LLM measurement ──────────────────────────────────────────────────
async function runDemoLLM() {{
  document.getElementById('llm-btns').style.display = 'none';
  try {{
    // Render the progress widget immediately so the visitor sees the
    // shell rather than a stale text line during the up-to-5s gap before
    // pollLLM's first response. Inside the try so widget-render
    // failure surfaces via showLLMError rather than silently leaving
    // the button hidden + page blank.
    wlRenderProgress({{
      target: 'llm-status',
      header: 'Submitting LLM job…',
      stagesHtml: wlStageList(WL_LLM_STAGES, 0),
      elapsed: 0,
      extraHtml: '<div class="stream-box" id="stream-box" style="margin-top:0.75rem"></div>',
    }});
    const form = new FormData();
    form.append('model_key', 'qwen3:4b');
    form.append('task_key', 'T3');
    form.append('repeats', '1');
    form.append('warm', 'false');
    const resp = await fetch('/llm/run', {{method:'POST', body:form}});
    const data = await resp.json();
    if (data.job_id) {{
      pollLLM(data.job_id, Date.now());
    }} else {{
      showLLMError(JSON.stringify(data));
    }}
  }} catch(e) {{ showLLMError(e); }}
}}

function showLLMError(msg) {{
  document.getElementById('llm-btns').style.display = 'flex';
  document.getElementById('llm-status').innerHTML =
    '<p class="progress-note" style="color:var(--err)">Error: ' + msg + '</p>';
}}

function pollLLM(jobId, t0) {{
  fetch('/llm/job/' + jobId).then(r=>r.json()).then(data => {{
    if (data.status === 'done') {{
      if (streamTimer) {{ clearTimeout(streamTimer); streamTimer = null; }}
      llmResult = data.result;
      renderLLMResult(data.result, new Date().toISOString(), false);
    }} else if (data.status === 'error') {{
      if (streamTimer) {{ clearTimeout(streamTimer); streamTimer = null; }}
      showLLMError(data.error);
    }} else {{
      const stage = data.stage || '';
      const idx = stage === 'baseline' ? 0 : stage.startsWith('inference') ? 1 : 0;
      const partial = data.partial_response || '';
      const streamHtml = '<div class="stream-box" id="stream-box" style="margin-top:0.75rem">'
                       + partial + '</div>';
      wlRenderProgress({{
        target: 'llm-status',
        stagesHtml: wlStageList(WL_LLM_STAGES, idx),
        watts: data.watts,
        elapsed: Date.now() - t0,
        extraHtml: streamHtml,
      }});
      const delay = stage.startsWith('inference') ? 500 : 3000;
      streamTimer = setTimeout(() => pollLLM(jobId, t0), delay);
    }}
  }}).catch(() => {{ streamTimer = setTimeout(() => pollLLM(jobId, t0), 5000); }});
}}

// ─── Result renderers (CR-034 Phase A wrappers) ──────────────────────────────
// Cards are rendered by shared helpers in _RESULT_JS — the thin wrappers
// below only own the /demo lifecycle (button visibility + revealNext).
// Future polish items (drift note, carbon strip extensions, etc.) ship
// once and apply to all surfaces.
function renderVideoResult(r, savedAt, isPrev) {{
  document.getElementById('video-status').innerHTML =
    wlRenderVideoCard({{result: r, savedAt: savedAt, isPrev: isPrev}});
  document.getElementById('video-btns').style.display = 'none';
  revealNext(1);
}}

function renderLLMResult(r, savedAt, isPrev) {{
  const html = wlRenderLLMCard({{result: r, savedAt: savedAt, isPrev: isPrev}});
  // Shared helper guards on missing energy with a "format not recognised"
  // message; preserve the original behaviour of re-showing run buttons in
  // that case so visitors can retry from the buttons row rather than a
  // dead card.
  if (!r.energy && !(r.runs && r.runs.length) && !r.summary && r.mode !== 'both') {{
    document.getElementById('llm-btns').style.display = 'flex';
    document.getElementById('llm-status').innerHTML = html;
    revealNext(2);  // unrecognised shape ≠ trapped tour: still let them advance
    return;
  }}
  document.getElementById('llm-status').innerHTML = html;
  document.getElementById('llm-btns').style.display = 'none';
  revealNext(2);
}}

function resetVideoStep() {{
  videoResult = null;
  document.getElementById('video-btns').style.display = 'flex';
  document.getElementById('video-status').innerHTML = '';
  document.getElementById('next-1').style.display = 'none';
}}
function resetLLMStep() {{
  llmResult = null;
  document.getElementById('llm-btns').style.display = 'flex';
  document.getElementById('llm-status').innerHTML = '';
  document.getElementById('next-2').style.display = 'none';
}}
function resetImageStep() {{
  imageResult = null;
  document.getElementById('image-btns').style.display = 'flex';
  document.getElementById('image-status').innerHTML = '';
  document.getElementById('next-3').style.display = 'none';
}}
function resetRAGStep() {{
  ragResult = null;
  document.getElementById('rag-btns').style.display = 'flex';
  document.getElementById('rag-status').innerHTML = '';
  document.getElementById('next-4').style.display = 'none';
}}

// ─── RAG ─────────────────────────────────────────────────────────────────────
async function showPrevRAG() {{
  document.getElementById('rag-btns').style.display = 'none';
  try {{
    // Filter on the task field so we get the latest 3-mode-compare RAG
    // run, not just the latest llm/ entry (which might be a single LLM
    // inference). Same /demo carve-out endpoint as the other steps.
    const resp = await fetch('/demo/last/llm?task_eq=' +
      encodeURIComponent('RAG compare (3 modes)'));
    if (resp.status === 404) {{
      document.getElementById('rag-status').innerHTML =
        '<p class="progress-note" style="color:var(--text-3)">No previous 3-mode RAG comparison on file — run one below, or skip ahead.</p>';
      document.getElementById('rag-btns').style.display = 'flex';
      revealNext(4);
      return;
    }}
    const full = await resp.json();
    ragResult = full;
    renderRAGResult(full, full.saved_at, true);
  }} catch(e) {{
    document.getElementById('rag-btns').style.display = 'flex';
    document.getElementById('rag-status').innerHTML =
      '<p class="progress-note" style="color:var(--err)">Error: ' + e + '</p>';
    revealNext(4);
  }}
}}

async function runDemoRAG() {{
  document.getElementById('rag-btns').style.display = 'none';
  try {{
    wlRenderProgress({{
      target: 'rag-status',
      header: 'Submitting RAG comparison…',
      stagesHtml: wlStageList(WL_RAG_STAGES, 0),
      elapsed: 0,
    }});
    const form = new FormData();
    form.append('model_key', 'qwen3:4b');
    // No `question` field — server uses curated.CANONICAL_RAG_QUESTION,
    // which keeps the call Anonymous-OK (CR-001 capability dispatch).
    const resp = await fetch('/rag/run-compare', {{method:'POST', body:form}});
    const data = await resp.json();
    if (data.job_id) pollDemoRAG(data.job_id, Date.now());
    else document.getElementById('rag-status').innerHTML =
      '<p class="progress-note" style="color:var(--err)">' + JSON.stringify(data) + '</p>';
  }} catch(e) {{
    document.getElementById('rag-status').innerHTML =
      '<p class="progress-note" style="color:var(--err)">Error: ' + e + '</p>';
    document.getElementById('rag-btns').style.display = 'flex';
  }}
}}

function pollDemoRAG(jobId, t0) {{
  fetch('/rag/job/' + jobId).then(r=>r.json()).then(data => {{
    if (data.stage === 'done' && data.result) {{
      ragResult = data.result;
      renderRAGResult(data.result, new Date().toISOString(), false);
    }} else if (data.error) {{
      document.getElementById('rag-status').innerHTML =
        '<p class="progress-note" style="color:var(--err)">Error: ' + data.error + '</p>';
      document.getElementById('rag-btns').style.display = 'flex';
    }} else {{
      const stage = data.stage || '';
      const idx = stage.startsWith('baseline') ? 0 : stage.startsWith('inference') ? 1 : 0;
      // Friendly mode label so visitors see "No retrieval / RAG / RAG Large"
      // rolling through, plus a "1 of 3" position indicator. The server
      // sets jobs[id].current_mode to baseline|rag|rag_large|cooldown and
      // jobs[id].mode_index to 0|1|2 (set in run_rag_compare_job).
      const modeLabels = {{
        baseline: 'Mode 1 of 3 — No retrieval (control)',
        rag: 'Mode 2 of 3 — RAG (small corpus)',
        rag_large: 'Mode 3 of 3 — RAG Large (full corpus)',
        cooldown: 'Cooldown between modes — letting thermals settle',
      }};
      const cm = data.current_mode || '';
      const lbl = modeLabels[cm] || (cm ? cm : '');
      const modeLine = lbl
        ? '<div style="color:var(--accent);font-size:0.82rem;margin-top:0.6rem;font-weight:bold">' + lbl + '</div>'
        : '';
      wlRenderProgress({{
        target: 'rag-status',
        stagesHtml: wlStageList(WL_RAG_STAGES, idx),
        watts: data.watts,
        elapsed: Date.now() - t0,
        extraHtml: modeLine,
      }});
      setTimeout(() => pollDemoRAG(jobId, t0), 3000);
    }}
  }}).catch(() => setTimeout(() => pollDemoRAG(jobId, t0), 5000));
}}

function renderRAGResult(r, savedAt, isPrev) {{
  document.getElementById('rag-status').innerHTML =
    wlRenderRAGCard({{result: r, savedAt: savedAt, isPrev: isPrev}});
  document.getElementById('rag-btns').style.display = 'none';
  revealNext(4);
}}

// ─── Image ────────────────────────────────────────────────────────────────────
async function runDemoImage() {{
  document.getElementById('image-btns').style.display = 'none';
  try {{
    wlRenderProgress({{
      target: 'image-status',
      header: 'Submitting image job…',
      stagesHtml: wlStageList(WL_IMAGE_STAGES, 0),
      elapsed: 0,
    }});
    // No `prompt` field — server uses curated.CANONICAL_IMAGE_PROMPT, which
    // keeps the call Anonymous-OK (CR-001 capability dispatch).
    const resp = await fetch('/image/start', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
      body: '',
    }});
    const data = await resp.json();
    if (data.error) {{
      document.getElementById('image-btns').style.display = 'flex';
      document.getElementById('image-status').innerHTML =
        '<p class="progress-note" style="color:var(--err)">' + data.error + '</p>';
      return;
    }}
    pollDemoImage(data.job_id);
  }} catch(e) {{
    document.getElementById('image-btns').style.display = 'flex';
    document.getElementById('image-status').innerHTML =
      '<p class="progress-note" style="color:var(--err)">Error: ' + e + '</p>';
  }}
}}

async function pollDemoImage(jobId) {{
  if (!pollDemoImage._t0) pollDemoImage._t0 = Date.now();
  try {{
    const r = await fetch('/image/job/' + jobId);
    const j = await r.json();
    if (j.stage === 'queued') {{
      wlRenderQueued(j.queue_position, {{target: 'image-status'}});
      imageTimer = setTimeout(() => pollDemoImage(jobId), 3000);
      return;
    }}
    if (j.stage === 'done' && j.result) {{
      imageResult = j.result;
      pollDemoImage._t0 = null;
      renderDemoImageResult(j.result);
      return;
    }}
    if (j.error) {{
      pollDemoImage._t0 = null;
      document.getElementById('image-status').innerHTML =
        '<p class="progress-note" style="color:var(--err)">Error: ' + j.error + '</p>';
      document.getElementById('image-btns').style.display = 'flex';
      return;
    }}
    const idx = j.stage === 'generating' ? 1 : 0;
    wlRenderProgress({{
      target: 'image-status',
      stagesHtml: wlStageList(WL_IMAGE_STAGES, idx),
      watts: j.watts,
      elapsed: Date.now() - pollDemoImage._t0,
    }});
    imageTimer = setTimeout(() => pollDemoImage(jobId), 2000);
  }} catch(e) {{
    imageTimer = setTimeout(() => pollDemoImage(jobId), 3000);
  }}
}}

async function showPrevImage() {{
  document.getElementById('image-btns').style.display = 'none';
  try {{
    const resp = await fetch('/demo/last/image');
    if (resp.status === 404) {{
      document.getElementById('image-status').innerHTML =
        '<p class="progress-note" style="color:var(--text-3)">No previous run on file — run one below, or skip ahead.</p>';
      document.getElementById('image-btns').style.display = 'flex';
      revealNext(3);
      return;
    }}
    const full = await resp.json();
    imageResult = full;
    renderDemoImageResult(full);
  }} catch(e) {{
    document.getElementById('image-btns').style.display = 'flex';
    document.getElementById('image-status').innerHTML =
      '<p class="progress-note" style="color:var(--err)">Error: ' + e + '</p>';
    revealNext(3);
  }}
}}

function renderDemoImageResult(r) {{
  // Single-run path with no energy block: re-show the buttons row so
  // visitors can retry, and let the shared helper render the
  // "format not recognised" notice.
  if (r.mode !== 'both' && !r.energy) {{
    document.getElementById('image-btns').style.display = 'flex';
    document.getElementById('image-status').innerHTML =
      wlRenderImageCard({{result: r, isPrev: false}});
    revealNext(3);  // unrecognised shape ≠ trapped tour: still let them advance
    return;
  }}
  document.getElementById('image-status').innerHTML =
    wlRenderImageCard({{result: r, isPrev: false}});
  document.getElementById('image-btns').style.display = 'none';
  revealNext(3);
}}

// ─── Summary ─────────────────────────────────────────────────────────────────
function buildSummary() {{
  // CR-058 — when the findings catalog is on, the Findings step renders
  // the catalog preview server-side and buildSummary() must NOT overwrite
  // it. Flipping settings.findings_enabled to false makes the server stop
  // setting this global, restoring the original session-echo behaviour.
  if (window.OWL_FINDINGS_CATALOG_ENABLED) return;
  const el = document.getElementById('summary-content');
  let videoRows = '', llmRows = '', imageRows = '', ragRows = '';
  try {{

  // Video — the headline. GoS raison d'être.
  try {{
    if (videoResult && videoResult.mode === 'both') {{
      const a = videoResult.analysis || {{}};
      const ce = videoResult.cpu && videoResult.cpu.energy;
      const ge = videoResult.gpu && videoResult.gpu.energy;
      videoRows += `<tr><td>CPU energy</td><td>${{fmt(ce && ce.delta_e_wh,4)}} Wh ${{a.energy_winner==='CPU'?'✓':''}}</td></tr>`;
      videoRows += `<tr><td>GPU energy</td><td>${{fmt(ge && ge.delta_e_wh,4)}} Wh ${{a.energy_winner==='GPU'?'✓':''}}</td></tr>`;
      videoRows += `<tr><td>Finding</td><td style="color:var(--text-2);font-size:0.78rem">${{a.finding || a.energy_winner + ' used less energy'}}</td></tr>`;
    }} else if (videoResult) {{
      const e = videoResult.energy || (videoResult.result && videoResult.result.energy);
      videoRows += `<tr><td>Energy</td><td>${{fmt(e && e.delta_e_wh,4)}} Wh</td></tr>`;
    }} else {{
      videoRows += `<tr><td>Video</td><td style="color:var(--text-5)">— not run yet</td></tr>`;
    }}
  }} catch(err) {{ videoRows += `<tr><td>Video</td><td style="color:var(--text-3)">error: ${{err.message}}</td></tr>`; }}

  // LLM
  try {{
    if (llmResult && llmResult.mode === 'both') {{
      const a = llmResult.analysis || {{}};
      const ce = llmResult.cpu && llmResult.cpu.energy;
      const ge = llmResult.gpu && llmResult.gpu.energy;
      llmRows += `<tr><td>Model</td><td>${{llmResult.model_label || ''}}</td></tr>`;
      llmRows += `<tr><td>CPU mWh/token</td><td>${{fmt(ce && ce.mwh_per_token,4)}} ${{a.mwh_winner==='CPU'?'✓':''}}</td></tr>`;
      llmRows += `<tr><td>GPU mWh/token</td><td>${{fmt(ge && ge.mwh_per_token,4)}} ${{a.mwh_winner==='GPU'?'✓':''}}</td></tr>`;
    }} else if (llmResult) {{
      let e = llmResult.energy;
      let inf = llmResult.inference;
      if (!e && llmResult.runs && llmResult.runs.length) {{
        e = llmResult.runs[llmResult.runs.length-1].energy;
        inf = llmResult.runs[llmResult.runs.length-1].inference;
      }}
      if (!e && llmResult.summary) {{
        e = {{ mwh_per_token: llmResult.summary.mwh_per_token_mean }};
        inf = {{ tokens_per_sec: llmResult.summary.tokens_per_sec_mean }};
      }}
      llmRows += `<tr><td>Model</td><td>${{llmResult.model_label || ''}}</td></tr>`;
      llmRows += `<tr><td>Energy / token</td><td>${{fmt(e && e.mwh_per_token,4)}} mWh/token</td></tr>`;
      llmRows += `<tr><td>Speed</td><td>${{fmt(inf && inf.tokens_per_sec,1)}} tok/s</td></tr>`;
    }} else {{
      llmRows += `<tr><td>LLM</td><td style="color:var(--text-5)">— not run yet</td></tr>`;
    }}
  }} catch(err) {{ llmRows += `<tr><td>LLM</td><td style="color:var(--text-3)">error: ${{err.message}}</td></tr>`; }}

  // Image
  try {{
    if (imageResult && imageResult.mode === 'both') {{
      const a = imageResult.analysis || {{}};
      const ce = imageResult.cpu && imageResult.cpu.energy;
      const ge = imageResult.gpu && imageResult.gpu.energy;
      const cg = imageResult.cpu && imageResult.cpu.generation;
      const gg = imageResult.gpu && imageResult.gpu.generation;
      imageRows += `<tr><td>CPU Wh/image</td><td>${{fmt(ce && (ce.wh_per_image||ce.delta_e_wh),4)}} Wh ${{a.energy_winner==='cpu'?'✓':''}}</td></tr>`;
      imageRows += `<tr><td>GPU Wh/image</td><td>${{fmt(ge && (ge.wh_per_image||ge.delta_e_wh),4)}} Wh ${{a.energy_winner==='gpu'?'✓':''}}</td></tr>`;
      imageRows += `<tr><td>Time CPU/GPU</td><td>${{fmt(cg && cg.gen_s,1)}}s / ${{fmt(gg && (gg.gen_s_per_image||gg.gen_s),1)}}s</td></tr>`;
    }} else if (imageResult) {{
      const e = imageResult.energy;
      const gen = imageResult.generation;
      imageRows += `<tr><td>Wh / image</td><td>${{fmt(e && (e.wh_per_image||e.delta_e_wh),4)}} Wh</td></tr>`;
      imageRows += `<tr><td>Generation time</td><td>${{fmt(gen && gen.total_s,1)}}s</td></tr>`;
    }} else {{
      imageRows += `<tr><td>Image</td><td style="color:var(--text-5)">— not run yet</td></tr>`;
    }}
  }} catch(err) {{ imageRows += `<tr><td>Image</td><td style="color:var(--text-3)">error: ${{err.message}}</td></tr>`; }}

  // RAG
  try {{
    if (ragResult && ragResult.results) {{
      const bl = ragResult.results.baseline, rl = ragResult.results.rag_large;
      if (bl && rl) {{
        const overhead = bl.energy && rl.energy && bl.energy.mwh_per_token > 0
          ? (((rl.energy.mwh_per_token - bl.energy.mwh_per_token) / bl.energy.mwh_per_token) * 100).toFixed(1)
          : null;
        ragRows += `<tr><td>Without RAG mWh/tok</td><td>${{fmt(bl.energy && bl.energy.mwh_per_token,3)}}</td></tr>`;
        ragRows += `<tr><td>RAG Large mWh/tok</td><td>${{fmt(rl.energy && rl.energy.mwh_per_token,3)}}</td></tr>`;
        if (overhead !== null) ragRows += `<tr><td>RAG overhead</td><td>${{overhead}}%</td></tr>`;
      }}
    }} else {{
      ragRows += `<tr><td>RAG</td><td style="color:var(--text-5)">— not run yet</td></tr>`;
    }}
  }} catch(err) {{ ragRows += `<tr><td>RAG</td><td style="color:var(--text-3)">error: ${{err.message}}</td></tr>`; }}

  }} catch(outerErr) {{
    el.innerHTML = '<p style="color:var(--err);font-family:monospace;font-size:0.82rem">Summary error: ' + outerErr + '</p>';
    return;
  }}

  // Render: video as headline, AI workloads collapsed beneath.
  const collapseStyle = 'margin-top:0.75rem;border:1px solid var(--border);padding:0.5rem 0.9rem';
  const summaryStyle = 'cursor:pointer;color:var(--text-2);font-size:0.92rem;padding:0.25rem 0;list-style:none';
  const section = (title, rows) =>
    `<details style="${{collapseStyle}}">
       <summary style="${{summaryStyle}}">▸ ${{title}}</summary>
       <table class="summary-table" style="margin-top:0.5rem"><tbody>${{rows}}</tbody></table>
     </details>`;

  el.innerHTML = `
    <h2 style="color:var(--accent);font-size:1.05rem;margin-bottom:0.4rem">▶ Video transcoding</h2>
    <p style="color:var(--text-3);font-size:0.78rem;margin-bottom:0.75rem">
      The core GoS focus — streaming's largest controllable energy footprint.</p>
    <table class="summary-table"><tbody>${{videoRows}}</tbody></table>

    <p style="color:var(--text-3);font-size:0.78rem;margin-top:1.5rem;letter-spacing:0.04em">
      OTHER WORKLOADS MEASURED</p>
    ${{section('LLM inference', llmRows)}}
    ${{section('Image generation', imageRows)}}
    ${{section('RAG (retrieval-augmented inference)', ragRows)}}

    <p style="color:var(--text-3);font-size:0.82rem;line-height:1.7;margin-top:1.5rem;max-width:560px">
      These figures are from live measurements on GoS1, a server in France,
      using a calibrated smart plug. Not modelled. Not averaged.
      Reproducible by anyone with the same hardware.
    </p>`;
}}
</script>
    {_PROGRESS_JS}
    {_RESULT_JS}
    {_CONF_HELP_WIDGET}
    {_FOOTER}
</body>
</html>"""

@app.get("/image", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def image_page(request: Request):
    # CR-001 part C2c — capability flags drive the lock UI on the prompt
    # textarea (CUSTOM_PROMPT) and the Both / Compare-Models buttons
    # (BATCH_COMPARE). Anonymous sees the curated CANONICAL_IMAGE_PROMPT
    # rendered read-only with a lock badge; the runtime gate enforces.
    can_custom_prompt = can(audience.tier(request), CUSTOM_PROMPT)
    can_batch_compare = can(audience.tier(request), BATCH_COMPARE)
    lk_prompt_class   = _lock_class(request, CUSTOM_PROMPT)
    lk_prompt_badge   = _lock_badge_html(request, CUSTOM_PROMPT, "Edit prompt — Members only")
    lk_batch_class    = _lock_class(request, BATCH_COMPARE)
    lk_batch_badge    = _lock_badge_html(request, BATCH_COMPARE, "CPU vs GPU compare — Members only")
    dis_prompt        = _disabled_attr(request, CUSTOM_PROMPT)
    dis_batch         = _disabled_attr(request, BATCH_COMPARE)
    # Anonymous default = canonical curated prompt; Member/Lab default = today's
    # original copy. Avoids "user types nothing → server rejects empty".
    default_prompt    = ("a lone wind turbine in an open landscape"
                          if can_custom_prompt else curated.CANONICAL_IMAGE_PROMPT)

    queue_depth = queue_control.depth()
    busy_banner = (f'<div style="background:var(--border-3);color:var(--warn);padding:0.75rem 1rem;'
                   f'margin-bottom:1rem;font-size:0.85rem">'
                   f'⏱ {queue_depth} job{"s" if queue_depth != 1 else ""} in queue — '
                   f'yours will be added and run automatically.</div>') \
        if queue_depth > 0 else ""

    # CR-050 — build the model selector dynamically from IMAGE_MODELS so
    # adding a model on /settings is enough; no hardcoded HTML to drift.
    default_model_key = "sd-turbo" if "sd-turbo" in IMAGE_MODELS else (
        next(iter(IMAGE_MODELS.keys()), "sd-turbo"))
    image_model_cards = "".join([
        f'<div class="preset{" selected" if k == default_model_key else ""}" '
        f'id="mdl-{k}" data-model="{k}" data-cpu-ok="{"true" if v.get("cpu_ok") else "false"}" '
        f'onclick="selectModelKey(\'{k}\')" '
        f'style="border:1px solid {"var(--accent)" if k == default_model_key else "var(--border-3)"};'
        f'{"background:#00ff9911;" if k == default_model_key else ""}'
        f'padding:0.75rem 1rem;cursor:pointer;flex:1 1 170px;min-width:160px">'
        f'<div style="color:{"var(--accent)" if k == default_model_key else "var(--text-2)"};'
        f'font-size:0.85rem;font-weight:bold">{v.get("label", k)}</div>'
        f'<div style="color:var(--text-3);font-size:0.72rem">{v.get("params","?")} params · '
        f'{v.get("size_px",512)}×{v.get("size_px",512)} · {"CPU + GPU" if v.get("cpu_ok") else "GPU only"}</div>'
        f'</div>'
        for k, v in IMAGE_MODELS.items()
    ]) or '<div style="color:var(--text-5);font-size:0.85rem">No image models enabled — see /settings.</div>'
    # Compare Models button: enabled when at least 2 image models exist.
    # The runner iterates every enabled model — disable the ones you don't
    # want by unchecking them in /settings.
    compare_available = len(IMAGE_MODELS) >= 2
    compare_label = f"Compare all {len(IMAGE_MODELS)} models (GPU) ⚡"
    # Pre-compute the stage progression for the compare-models run so JS
    # can render an accurate progress dot strip for N models without
    # guessing the stage names.
    import json as _json2
    compare_stages_js  = ["m1_baseline", "m1_generating"]
    compare_labels_extra = {}
    for i, (k, v) in enumerate(IMAGE_MODELS.items(), start=1):
        b = f"m{i}_baseline"
        g = f"m{i}_generating"
        if i > 1:
            # Unique per-gap cooldown key — a repeated literal 'cooldown' made
            # the strip collapse every inter-model cooldown onto the first one
            # (JS indexOf returns the first match), so the indicator snapped
            # backward on each later cooldown. The runner still emits the generic
            # 'cooldown' stage; pollJob maps it to cooldown_<idx> via
            # current_model_idx, so the substring cooldown-detection paths are
            # untouched. Label uses the shared toggle-aware {COOLDOWN_PAREN}.
            cd_key = f"cooldown_{i}"
            compare_stages_js += [cd_key, b, g]
            compare_labels_extra[cd_key] = f"Cooldown before {v.get('label', k)} {{COOLDOWN_PAREN}}"
        compare_labels_extra[b] = f"{v.get('label', k)} — baseline ({{BASELINE_S}}s)"
        compare_labels_extra[g] = f"{v.get('label', k)} — generating (GPU batch)"
    compare_stages_js += ["done"]
    compare_stages_inject = _json2.dumps(compare_stages_js)
    compare_labels_inject = _json2.dumps(compare_labels_extra)

    # CR-026: scope to own-jobs for non-Lab. Lab passes None → unfiltered.
    prev_runs = list_results("image", limit=5,
                             visitor_key=queue_control.visitor_key(request))
    prev_html = ""
    if prev_runs:
        prev_html = '<div class="prev-runs"><h3>Previous runs</h3>'
        for r in prev_runs:
            fp = r.get("full_prompt", "")
            date_str = (r.get("saved_at") or "")[:16].replace("T", " ")
            saved_at = r.get("saved_at") or ""
            mode = r.get("mode", "cpu")
            # CR-034 Phase B / CR-013 — click-to-expand toggle. Lazy-loads the
            # full result via /results/image/<id>/download.json and renders
            # through window.wlRenderImageCard from _RESULT_JS.
            expand_link = (
                f'<a href="javascript:void(0)" '
                f'onclick="wlExpandPrevRow(\'image\',\'{r["job_id"]}\',\'{saved_at}\')" '
                f'style="color:var(--text-3);font-size:0.72rem;text-decoration:none;'
                f'margin-right:0.75rem;cursor:pointer">'
                f'<span id="chev-{r["job_id"]}">▸</span> Show full result</a>'
            )
            downloads = (
                expand_link
                + f'<a href="/results/image/{r["job_id"]}/download.json" download '
                f'style="color:var(--text-5);font-size:0.72rem;text-decoration:none;margin-right:0.75rem">↓ JSON</a>'
                f'<a href="/results/image/{r["job_id"]}/download.csv" download '
                f'style="color:var(--text-5);font-size:0.72rem;text-decoration:none">↓ CSV</a>'
            )
            expand_div = f'<div id="expand-{r["job_id"]}" style="display:none;margin-top:0.6rem"></div>'
            if mode == "both":
                def _side_html(label, s):
                    img = (f'<img src="data:image/png;base64,{s["b64_png"]}" '
                           f'style="width:64px;height:64px;object-fit:cover;margin-right:0.5rem">'
                           if s.get("b64_png") else "")
                    conf = s.get("confidence", {})
                    return (f'<div style="display:flex;align-items:center;margin-top:0.4rem">'
                            f'{img}<span style="color:var(--text-3);font-size:0.78rem">'
                            f'<span style="color:var(--text-2)">{label}</span> &nbsp;·&nbsp; '
                            f'{conf.get("flag","")} {conf.get("label","")} &nbsp;·&nbsp; '
                            f'{s.get("delta_e_wh","?")} Wh &nbsp;·&nbsp; {s.get("delta_t_s","?")}s'
                            f'</span></div>')
                model_lbl = r.get("model_label") or ""
                model_tag = f' &nbsp;·&nbsp; {model_lbl}' if model_lbl else ""
                prev_html += f"""<div class="prev-item" style="flex-direction:column;align-items:flex-start">
                  <span class="prev-meta">{date_str} &nbsp;·&nbsp; CPU vs GPU{model_tag}</span>
                  {_side_html("CPU", r.get("cpu", {}))}
                  {_side_html("GPU", r.get("gpu", {}))}
                  <div class="prev-prompt" style="color:var(--text-3);font-size:0.75rem;margin-top:0.3rem">{fp[:80]}</div>
                  <div style="margin-top:0.3rem">{downloads}</div>
                  {expand_div}
                </div>"""
            elif mode == "compare_models":
                def _mdl_html(s):
                    # Per-model run dict is flattened on save: the energy/generation
                    # fields live as siblings of the model_label, not nested.
                    img = (f'<img src="data:image/png;base64,{s["b64_png"]}" '
                           f'style="width:64px;height:64px;object-fit:cover;margin-right:0.5rem">'
                           if s.get("b64_png") else "")
                    conf = s.get("confidence", {}) or {}
                    lbl = s.get("model_label") or s.get("model_key", "?")
                    px = s.get("size_px", "?")
                    return (f'<div style="display:flex;align-items:center;margin-top:0.4rem">'
                            f'{img}<span style="color:var(--text-3);font-size:0.78rem">'
                            f'<span style="color:var(--text-2)">{lbl} ({px}px)</span> &nbsp;·&nbsp; '
                            f'{conf.get("flag","")} {conf.get("label","")} &nbsp;·&nbsp; '
                            f'{s.get("wh_per_image","?")} Wh/img &nbsp;·&nbsp; {s.get("delta_t_s","?")}s'
                            f'</span></div>')
                # New schema: r["models"] is a list of per-model summary dicts
                # (already flattened by persist._summarise — size_px / delta_t_s
                # naming, not raw generation/energy). Legacy schema
                # (pre-2026-05-27): r["small"] + r["large"] only.
                model_list = r.get("models") or []
                if model_list:
                    rows_html = "".join(_mdl_html(m) for m in model_list)
                    n_label = f"Compare {len(model_list)} models (GPU)"
                else:
                    rows_html = _mdl_html(r.get("small", {})) + _mdl_html(r.get("large", {}))
                    n_label = "Compare models (GPU)"
                prev_html += f"""<div class="prev-item" style="flex-direction:column;align-items:flex-start">
                  <span class="prev-meta">{date_str} &nbsp;·&nbsp; {n_label}</span>
                  {rows_html}
                  <div class="prev-prompt" style="color:var(--text-3);font-size:0.75rem;margin-top:0.3rem">{fp[:80]}</div>
                  <div style="margin-top:0.3rem">{downloads}</div>
                  {expand_div}
                </div>"""
            else:
                conf = r.get("confidence", {})
                img_tag = (f'<img src="data:image/png;base64,{r["b64_png"]}" '
                           f'style="width:80px;height:80px;object-fit:cover;vertical-align:middle;margin-right:0.75rem">'
                           if r.get("b64_png") else "")
                mode_label = {"cpu": "CPU", "gpu": "GPU"}.get(mode, mode)
                prev_html += f"""<div class="prev-item" style="flex-direction:column;align-items:flex-start">
                  <div style="display:flex;align-items:flex-start;width:100%">
                    {img_tag}
                    <div>
                      <span class="prev-meta">
                        {date_str} &nbsp;·&nbsp; {mode_label}
                        &nbsp;·&nbsp; <span class="conf-badge">{conf.get("flag","")} {conf.get("label","")}</span>
                        &nbsp;·&nbsp; {r.get("delta_e_wh","?")} Wh/image
                        &nbsp;·&nbsp; {r.get("delta_t_s","?")}s
                      </span>
                      <div class="prev-prompt" style="color:var(--text-3);font-size:0.75rem;margin-top:0.3rem">{fp[:80]}</div>
                      <div style="margin-top:0.3rem">{downloads}</div>
                    </div>
                  </div>
                  {expand_div}
                </div>"""
        prev_html += "</div>"

    return _bake_durations(f"""<!DOCTYPE html>
<html>
<head>
    <link rel="icon" type="image/svg+xml" href="/static/owl.svg">
  <title>OWL — Image Generation Test</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: monospace; background: var(--bg); color: var(--text);
               max-width: 780px; margin: 0 auto; padding: 2rem; }}
        h1 {{ color: var(--accent); margin-bottom: 0.25rem; font-size: 1.6rem; }}
        .subtitle {{ color: var(--text-3); font-size: 0.8rem; margin-bottom: 1.5rem; }}
        .info {{ color: var(--text-3); font-size: 0.82rem; margin-bottom: 1.5rem;
                 border-left: 2px solid #222; padding-left: 1rem; line-height: 1.6; }}
        textarea {{ width: 100%; background: var(--panel); color: var(--text); border: 1px solid var(--border-3);
                    padding: 0.75rem; font-family: monospace; font-size: 0.9rem;
                    resize: vertical; margin-bottom: 1rem; }}
        button {{ background: var(--accent); color: #000; border: none;
                  padding: 0.75rem 2rem; cursor: pointer;
                  font-family: monospace; font-size: 1rem; }}
        button:disabled {{ background: var(--border); color: var(--text-3); cursor: not-allowed; }}
        button:hover:not(:disabled) {{ background: var(--accent-hover); }}
        #status {{ margin-top: 1.5rem; }}
        .progress-box {{ border: 1px solid var(--border); padding: 1.5rem; }}
        .progress-header {{ color: var(--warn); font-size: 0.9rem; margin-bottom: 1.25rem; }}
        .stages {{ display: flex; flex-direction: column; gap: 0.5rem; margin-bottom: 1.25rem; }}
        .stage {{ display: flex; align-items: center; gap: 0.75rem; font-size: 0.82rem; }}
        .stage-icon {{ width: 1.2rem; text-align: center; flex-shrink: 0; }}
        .live-watts {{ font-size: 2rem; color: var(--accent); font-weight: bold; margin-top: 0.5rem; }}
        .result-box {{ border: 1px solid #00ff9944; padding: 1.5rem; margin-top: 1.5rem; }}
        .result-box h2 {{ color: var(--accent); font-size: 1.1rem; margin-bottom: 1.25rem; }}
        .kpis {{ display: flex; gap: 1.5rem; flex-wrap: wrap; margin-bottom: 1.25rem; }}
        .kpi {{ display: flex; flex-direction: column; gap: 0.25rem; }}
        .kpi .val {{ font-size: 1.4rem; color: var(--accent); font-weight: bold; }}
        .kpi .lbl {{ font-size: 0.72rem; color: var(--text-3); }}
        .conf-badge {{ display: inline-block; border: 1px solid var(--border-3); padding: 0.25rem 0.75rem;
                       font-size: 0.8rem; color: var(--text-2); margin-bottom: 1rem; }}
        .scope-note {{ color: var(--text-5); font-size: 0.75rem; margin-top: 1rem; }}
        .prev-runs {{ margin-top: 2rem; border-top: 1px solid var(--border-2); padding-top: 1.5rem; }}
        .prev-runs h3 {{ color: var(--text-4); font-size: 0.85rem; margin-bottom: 1rem; }}
        .prev-item {{ padding: 0.75rem 0; border-bottom: 1px solid var(--panel);
                      display: flex; align-items: flex-start; flex-wrap: wrap; }}
        .prev-meta {{ color: var(--text-3); font-size: 0.78rem; }}
        .image-preview {{ margin-top: 1.25rem; }}
        .image-preview img {{ max-width: 100%; border: 1px solid var(--border); display: block; }}
        .image-caption {{ color: var(--text-4); font-size: 0.75rem; margin-top: 0.5rem; font-style: italic; }}
        .back {{ color: var(--text-3); font-size: 0.8rem; margin-bottom: 1.5rem; display: block; }}
        .back:hover {{ color: var(--accent); }}
        {_LOCK_STYLES}
    </style>
</head>
<body>
    {_BACK}
    {busy_banner}
    <h1>Image Generation Test {_BETA_CHIP}</h1>
    <div class="subtitle">SD-Turbo (~1B) · SDXL-Turbo (~3.5B) · 512×512 · {_gpu_runtime()} fp16 on {_gpu_display_name()}</div>

    {_ai_intro('image')}

    <div style="margin-bottom:1rem;font-size:0.78rem;color:var(--text-3)">
        First time here? <a href="/demo" style="color:var(--accent);text-decoration:none">Try the Guided Tour →</a>
    </div>

    <details style="margin-bottom:1.5rem;border-left:2px solid #222;padding-left:1rem">
        <summary style="cursor:pointer;color:var(--text-3);font-size:0.82rem;list-style:none;outline:none">
            ⓘ About this test <span style="color:var(--text-4);font-size:0.72rem">(click to expand)</span>
        </summary>
        <div style="color:var(--text-3);font-size:0.82rem;line-height:1.6;margin-top:0.75rem">
            Measures the wall-power cost of generating one AI image from text.<br>
            <strong style="color:var(--text-2)">SD-Turbo</strong>: CPU {IMAGE_STEPS_CPU} steps (~12s) or GPU batch of {GPU_BATCH_SIZE} × {IMAGE_STEPS_GPU} steps (~10s). Note: solo-mode GPU over-samples (native is 1–4 steps) to keep runtime above the P110 polling floor.<br>
            <strong style="color:var(--text-2)">SDXL-Turbo</strong>: GPU only, 4 steps (native), batch of 15 (~10s).<br>
            <strong style="color:var(--text-2)">Compare Models ⚡</strong>: both run at 4 steps (native for each), 512×512, same seed — SD-Turbo batch 30, SDXL-Turbo batch 15. Model size is the only variable.<br>
            Each run appends a random colour/mood modifier — live proof the image is generated, not replayed.
        </div>
    </details>

    <label style="color:var(--text-3);font-size:0.8rem;display:block;margin-bottom:0.4rem">Model</label>
    <div id="model-row" style="display:flex;gap:0.75rem;margin-bottom:1.2rem;flex-wrap:wrap">
      {image_model_cards}
    </div>

    <label style="color:var(--text-3);font-size:0.8rem;display:block;margin-bottom:0.4rem">Prompt</label>
    {lk_prompt_badge}
    <div class="{lk_prompt_class}">
      <textarea id="prompt" rows="3"{dis_prompt}>{default_prompt}</textarea>
    </div>
    <div style="color:var(--text-3);font-size:0.75rem;margin-bottom:1.2rem">
        A random colour/mood modifier is appended per run (e.g. "bathed in emerald light").
    </div>

    <div style="margin-bottom:1.25rem">
      <span style="color:var(--text-3);font-size:0.8rem;margin-right:1rem">Backend:</span>
      <label style="font-size:0.85rem;margin-right:1.2rem;cursor:pointer" id="lbl-cpu">
        <input type="radio" name="img-device" value="cpu" checked onchange="selectedDevice=this.value"> CPU
      </label>
      <label style="font-size:0.85rem;margin-right:1.2rem;cursor:pointer">
        <input type="radio" name="img-device" value="gpu" onchange="selectedDevice=this.value"> GPU
      </label>
      <label class="{lk_batch_class}" style="font-size:0.85rem;cursor:pointer" id="lbl-both">
        <input type="radio" name="img-device" value="both"{dis_batch} onchange="selectedDevice=this.value"> Both ⚡
      </label>
    </div>
    {lk_batch_badge}

    <div style="display:flex;gap:0.75rem;flex-wrap:wrap">
      <button id="run-btn" onclick="startMeasurement()">Generate &amp; Measure</button>
      {("<button id='compare-btn' class='" + lk_batch_class + "' onclick='startCompareModels()'" + dis_batch +
        " style='background:var(--bg);border:1px solid var(--accent);color:var(--accent);"
        "padding:0.75rem 1.5rem;font-family:monospace;font-size:0.95rem;cursor:pointer'>" +
        compare_label + "</button>") if compare_available else
       ("<button disabled title='Compare requires at least 2 image models enabled in /settings' "
        "style='background:var(--border);color:var(--text-3);border:1px solid var(--border-3);"
        "padding:0.75rem 1.5rem;font-family:monospace;font-size:0.95rem;cursor:not-allowed'>"
        "Compare Models — needs ≥ 2 image models enabled</button>")}
    </div>
    <div id="status"></div>
    {prev_html}
    </div>

<script>
const CPU_STAGES = ['baseline','generating','done'];
const GPU_STAGES = ['baseline','generating','done'];
const BOTH_STAGES = ['cpu_baseline','cpu_generating','cooldown','gpu_baseline','gpu_generating','done'];
const COMPARE_STAGES = {compare_stages_inject};
const STAGE_LABELS = {{
  'baseline': 'Measuring baseline power ({{BASELINE_S}}s)',
  'generating': 'Generating image',
  'cpu_baseline': 'CPU — measuring baseline ({{BASELINE_S}}s)',
  'cpu_generating': 'CPU — generating image',
  'cooldown': 'Cooldown between passes {{COOLDOWN_PAREN}}',
  'gpu_baseline': 'GPU — measuring baseline ({{BASELINE_S}}s)',
  'gpu_generating': 'GPU — generating images (batch)',
  'done': 'Complete',
}};
// CR-050 follow-up — N-way compare-models stage labels injected from the server
// (one m<i>_baseline / m<i>_generating pair per enabled image model).
Object.assign(STAGE_LABELS, {compare_labels_inject});
// CR-001 part C2c — capability flags from server.
// Anonymous: textarea is locked at the canonical prompt; JS omits
// `prompt=` from the body so /image/start uses the curated default
// without tripping the CUSTOM_PROMPT gate.
const CAN_CUSTOM_PROMPT = {('true' if can_custom_prompt else 'false')};
const CAN_BATCH_COMPARE = {('true' if can_batch_compare else 'false')};

let pollTimer = null;
let selectedDevice = 'cpu';
let selectedModelKey = '{default_model_key}';
let imgStartTime = null;

// CR-050 — generic over N image models. Cards carry data-model and
// data-cpu-ok; CPU + Both radios enable based on the active model's
// cpu_ok metadata. GPU-only models force backend=gpu.
function selectModelKey(k) {{
  selectedModelKey = k;
  let cpuOk = false;
  document.querySelectorAll('#model-row .preset').forEach(card => {{
    const active = card.dataset.model === k;
    card.style.borderColor = active ? '#00ff99' : '#333';
    card.style.background = active ? '#00ff9911' : 'transparent';
    if (card.children[0]) card.children[0].style.color = active ? '#00ff99' : '#aaa';
    if (active) cpuOk = card.dataset.cpuOk === 'true';
  }});
  const cpuIn  = document.querySelector('input[name="img-device"][value="cpu"]');
  const bothIn = document.querySelector('input[name="img-device"][value="both"]');
  if (cpuOk) {{
    cpuIn.disabled = false;
    bothIn.disabled = false;
    document.getElementById('lbl-cpu').style.opacity = '1';
    document.getElementById('lbl-both').style.opacity = '1';
  }} else {{
    cpuIn.disabled = true;
    bothIn.disabled = true;
    document.getElementById('lbl-cpu').style.opacity = '0.35';
    document.getElementById('lbl-both').style.opacity = '0.35';
    const gpuIn = document.querySelector('input[name="img-device"][value="gpu"]');
    gpuIn.checked = true;
    selectedDevice = 'gpu';
  }}
}}

function fmt(v, dp=2) {{
  if (v === null || v === undefined) return '—';
  return Number(v).toFixed(dp);
}}

async function startMeasurement() {{
  const prompt = document.getElementById('prompt').value.trim();
  if (CAN_CUSTOM_PROMPT && !prompt) {{ alert('Enter a prompt'); return; }}

  document.getElementById('run-btn').disabled = true;
  document.getElementById('compare-btn').disabled = true;
  document.getElementById('status').innerHTML = '';

  let body = 'device=' + encodeURIComponent(selectedDevice)
           + '&model_key=' + encodeURIComponent(selectedModelKey);
  if (CAN_CUSTOM_PROMPT && prompt) body += '&prompt=' + encodeURIComponent(prompt);
  const resp = await fetch('/image/start', {{
    method: 'POST',
    headers: {{'Content-Type':'application/x-www-form-urlencoded'}},
    body: body,
  }});
  const data = await resp.json();
  if (data.error) {{
    alert(data.error);
    document.getElementById('run-btn').disabled = false;
    document.getElementById('compare-btn').disabled = false;
    return;
  }}
  const jobId = data.job_id;

  imgStartTime = Date.now();
  renderProgress('baseline', null, null);
  pollTimer = setInterval(() => pollJob(jobId), 1500);
}}

async function startCompareModels() {{
  if (!CAN_BATCH_COMPARE) return;   // button is disabled, this is a backstop
  const prompt = document.getElementById('prompt').value.trim();
  if (CAN_CUSTOM_PROMPT && !prompt) {{ alert('Enter a prompt'); return; }}

  // Compare Models is GPU-only (SDXL-Turbo can't run on CPU). Flip the
  // backend radio to GPU so the page state reflects what's about to run —
  // otherwise the radio stays on CPU/Both while the progress widget shows
  // GPU stages, which reads as a contradiction.
  const gpuRadio = document.querySelector('input[name="img-device"][value="gpu"]');
  if (gpuRadio && !gpuRadio.checked) {{
    gpuRadio.checked = true;
    selectedDevice = 'gpu';
  }}

  document.getElementById('run-btn').disabled = true;
  document.getElementById('compare-btn').disabled = true;
  document.getElementById('status').innerHTML = '';

  let body = 'device=compare_models'
           + '&model_key=sd-turbo';   // ignored by server for compare_models
  if (CAN_CUSTOM_PROMPT && prompt) body += '&prompt=' + encodeURIComponent(prompt);
  const resp = await fetch('/image/start', {{
    method: 'POST',
    headers: {{'Content-Type':'application/x-www-form-urlencoded'}},
    body: body,
  }});
  const data = await resp.json();
  if (data.error) {{
    alert(data.error);
    document.getElementById('run-btn').disabled = false;
    document.getElementById('compare-btn').disabled = false;
    return;
  }}
  const jobId = data.job_id;

  imgStartTime = Date.now();
  renderProgress('m1_baseline', null, null);
  pollTimer = setInterval(() => pollJob(jobId), 1500);
}}

async function pollJob(jobId) {{
  const r = await fetch('/image/job/' + jobId);
  const j = await r.json();

  if (j.stage === 'queued') {{ wlRenderQueued(j.queue_position); return; }}

  if (j.stage === 'awaiting_cooldown_decision') {{
    wlCooldownDialog(jobId, j.cooldown_decision_options);
  }} else {{ wlCooldownDialogClose(); }}

  const powerR = await fetch('/power');
  const powerJ = await powerR.json().catch(() => ({{}}));
  // The compare runner emits a generic 'cooldown' stage; the progress strip
  // carries a unique cooldown_<idx> key per gap (so repeated cooldowns don't
  // collapse onto the first). current_model_idx is the model the cooldown
  // precedes, which is exactly the index the strip key was built with.
  let _dispStage = j.stage;
  if (_dispStage === 'cooldown' && j.current_model_idx) {{
    _dispStage = 'cooldown_' + j.current_model_idx;
  }}
  renderProgress(_dispStage, j.result, powerJ.watts ?? null);

  if (j.stage === 'done' && j.result) {{
    clearInterval(pollTimer);
    if (j.result.mode === 'both') renderImageBoth(j.result);
    else if (j.result.mode === 'compare_models') {{
      // Use the shared N-aware card (reads r.models) — the legacy
      // renderCompareModels only knew r.small/r.large, so a 3-model run
      // showed just 2. Same renderer as the prev-row / demo expand paths.
      document.getElementById('status').innerHTML =
        wlRenderImageCard({{result: j.result, isPrev: false}});
    }}
    else renderResult(j.result);
    document.getElementById('run-btn').disabled = false;
    document.getElementById('compare-btn').disabled = false;
  }}
  if (j.error) {{
    clearInterval(pollTimer);
    document.getElementById('status').innerHTML =
      '<p style="color:var(--err)">Error: ' + j.error + '</p>';
    document.getElementById('run-btn').disabled = false;
    document.getElementById('compare-btn').disabled = false;
  }}
}}

function renderProgress(stage, result, watts) {{
  const isCompare = COMPARE_STAGES.includes(stage) && stage !== 'done';
  const isBoth = !isCompare && BOTH_STAGES.includes(stage) && stage !== 'done';
  const stageKeys = isCompare ? COMPARE_STAGES : (isBoth ? BOTH_STAGES : CPU_STAGES);
  const stageIdx = stageKeys.indexOf(stage);
  wlRenderProgress({{
    header: '\u26a1 Measuring\u2026 do not close this tab',
    stagesHtml: wlStageList(stageKeys.map(s => STAGE_LABELS[s] || s), stageIdx),
    watts: watts,
    elapsed: imgStartTime ? Date.now() - imgStartTime : null,
  }});
}}

function _imageCard(label, pass_r, isWinner) {{
  const e = pass_r.energy;
  const gen = pass_r.generation;
  const borderCol = isWinner ? '#00ff9966' : '#222';
  const imgHtml = gen.b64_png
    ? `<div style="margin-top:0.75rem"><img src="data:image/png;base64,${{gen.b64_png}}" style="max-width:180px;border:1px solid var(--border)"></div>`
    : '';
  return `<div style="border:1px solid ${{borderCol}};padding:1rem;flex:1;min-width:220px">
    <div style="color:${{isWinner?'#00ff99':'#777'}};font-size:0.85rem;font-weight:bold;margin-bottom:0.75rem">${{label}}${{isWinner?' 🏆':''}}</div>
    <div class="kpis">
      <div class="kpi"><div class="val" style="font-size:1.15rem">${{fmt(e.wh_per_image,4)}} Wh</div><div class="lbl">per image</div></div>
      <div class="kpi"><div class="val" style="font-size:1.15rem">${{fmt(gen.gen_s_per_image,1)}} s</div><div class="lbl">gen/image</div></div>
      <div class="kpi"><div class="val" style="font-size:1.1rem">${{fmt(e.delta_w,1)}} W</div><div class="lbl">delta W</div></div>
      <div class="kpi"><div class="val" style="font-size:1.1rem">${{e.poll_count}}</div><div class="lbl">polls</div></div>
    </div>
    <div style="font-size:0.78rem;color:var(--text-3);margin-top:0.5rem"><span class="conf-badge">${{e.confidence.flag}} ${{e.confidence.label}}</span> · ${{gen.batch_size}}×${{gen.steps}} steps</div>
    ${{imgHtml}}
  </div>`;
}}

function renderImageBoth(r) {{
  const a = r.analysis;
  const cpuWinsEnergy = a.energy_winner === 'cpu';
  const gpuWinsEnergy = a.energy_winner === 'gpu';
  const _stripWh = (r.cpu && r.cpu.energy && r.gpu && r.gpu.energy)
    ? Math.min(r.cpu.energy.delta_e_wh, r.gpu.energy.delta_e_wh)
    : ((r.cpu && r.cpu.energy && r.cpu.energy.delta_e_wh) || (r.gpu && r.gpu.energy && r.gpu.energy.delta_e_wh));
  const _winE = (r.cpu && r.cpu.energy && r.gpu && r.gpu.energy)
    ? (r.cpu.energy.delta_e_wh <= r.gpu.energy.delta_e_wh ? r.cpu.energy : r.gpu.energy)
    : ((r.cpu && r.cpu.energy) || (r.gpu && r.gpu.energy));
  const _stripDur = _winE ? _winE.delta_t_s : null;
  const _stripSavedG = _winE && _winE.co2e && _winE.co2e.intensity
    ? _winE.co2e.intensity.g_per_kwh : null;
  // CR-032 — sub-runs across the two devices.
  const _subRuns = [
    {{label: 'CPU · Ryzen 9 7900',  e: r.cpu  && r.cpu.energy}},
    {{label: 'GPU · {_gpu_display_name()}',    e: r.gpu  && r.gpu.energy}}
  ].filter(s => s.e && s.e.co2e).map(s => ({{
    label: s.label,
    grams: s.e.co2e.grams,
    deltaWh: s.e.delta_e_wh,
    durationS: s.e.delta_t_s
  }}));
  // CR-038 — structured efficiency verdict above the per-device cards.
  const _imgBothVerdict = wlEfficiencyVerdict([
    r.cpu && r.cpu.energy ? {{label: 'CPU', energy: (r.cpu.energy.wh_per_image || r.cpu.energy.delta_e_wh)}} : null,
    r.gpu && r.gpu.energy ? {{label: 'GPU', energy: (r.gpu.energy.wh_per_image || r.gpu.energy.delta_e_wh)}} : null
  ], {{unit: 'Wh/image'}});
  document.getElementById('status').innerHTML = `
    <div class="result-box">
      <h2>CPU vs GPU — Image Generation</h2>
      <div style="background:var(--panel);border:1px solid var(--border-3);padding:0.75rem 1rem;margin-bottom:1.25rem;font-size:0.85rem;color:var(--text-2)">
        ${{a.finding}}
      </div>
      ${{_imgBothVerdict}}
      <div style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1rem">
        ${{_imageCard('CPU · Ryzen 9 7900', r.cpu, cpuWinsEnergy)}}
        ${{_imageCard('GPU · {_gpu_display_name()}', r.gpu, gpuWinsEnergy)}}
      </div>
      <div style="font-size:0.75rem;color:var(--text-4);margin-top:0.5rem">
        Prompt: "${{r.full_prompt}}" · modifier: <em>${{r.modifier}}</em>
      </div>
      ${{wlCarbonStrip(_stripWh, 'Image gen · most efficient device', _stripDur, _stripSavedG, _subRuns)}}
      <p class="scope-note">${{r.scope}}</p>
    </div>`;
}}

function _modelCard(side_r) {{
  const e = side_r.energy;
  const gen = side_r.generation;
  const imgHtml = gen.b64_png
    ? `<div style="margin-top:0.75rem"><img src="data:image/png;base64,${{gen.b64_png}}" style="max-width:100%;border:1px solid var(--border)"></div>`
    : '';
  return `<div style="border:1px solid var(--border);padding:1rem;flex:1;min-width:260px">
    <div style="color:var(--accent);font-size:0.9rem;font-weight:bold;margin-bottom:0.25rem">${{gen.model_label}}</div>
    <div style="color:var(--text-3);font-size:0.72rem;margin-bottom:0.75rem">${{gen.model}} · ${{gen.size}}px · ${{gen.steps}} steps × batch ${{gen.batch_size}}</div>
    <div class="kpis">
      <div class="kpi"><div class="val" style="font-size:1.2rem">${{fmt(e.wh_per_image,4)}} Wh</div><div class="lbl">per image</div></div>
      <div class="kpi"><div class="val" style="font-size:1.2rem">${{fmt(gen.gen_s_per_image,1)}} s</div><div class="lbl">gen/image</div></div>
      <div class="kpi"><div class="val" style="font-size:1.1rem">${{fmt(e.delta_w,1)}} W</div><div class="lbl">delta W</div></div>
      <div class="kpi"><div class="val" style="font-size:1.1rem">${{e.poll_count}}</div><div class="lbl">polls</div></div>
    </div>
    <div class="conf-badge" style="font-size:0.78rem;color:var(--text-3);margin-top:0.5rem">${{e.confidence.flag}} ${{e.confidence.label}}</div>
    ${{imgHtml}}
  </div>`;
}}

function renderCompareModels(r) {{
  // Legacy 2-model renderer retired (2026-06-02): it only read r.small/r.large,
  // so a 3-model compare showed just 2 cards. Delegate to the shared N-aware
  // card so this can't drift again. Kept as a shim for any stray caller.
  document.getElementById('status').innerHTML =
    wlRenderImageCard({{result: r, isPrev: false}});
}}

function renderResult(r) {{
  const e = r.energy;
  const gen = r.generation;
  const batch = gen.batch_size || 1;
  const batchNote = batch > 1 ? ` (batch of ${{batch}})` : '';
  const imgHtml = gen.b64_png
    ? `<div class="image-preview">
         <img src="data:image/png;base64,${{gen.b64_png}}" alt="Generated image">
         <div class="image-caption">"${{r.full_prompt}}"</div>
       </div>`
    : '';
  document.getElementById('status').innerHTML = `
    <div class="result-box">
      <h2>Result</h2>
      <div class="kpis">
        <div class="kpi">
          <div class="val">${{fmt(e.wh_per_image,4)}} Wh</div>
          <div class="lbl">energy / image</div>
        </div>
        <div class="kpi">
          <div class="val">${{fmt(e.delta_w,1)}} W</div>
          <div class="lbl">delta above idle</div>
        </div>
        <div class="kpi">
          <div class="val">${{fmt(gen.gen_s_per_image,1)}} s</div>
          <div class="lbl">gen time / image${{batchNote}}</div>
        </div>
        <div class="kpi">
          <div class="val">${{fmt(gen.load_s,1)}} s</div>
          <div class="lbl">model load</div>
        </div>
        <div class="kpi">
          <div class="val">${{e.poll_count}}</div>
          <div class="lbl">P110 polls</div>
        </div>
      </div>
      <div class="conf-badge">${{e.confidence.flag}} ${{e.confidence.label}}</div>
      ${{e.video_relative ? '<div style="font-size:0.78rem;color:var(--text-3);margin-top:0.5rem">This run ' + e.video_relative.text + '</div>' : ''}}
      ${{imgHtml}}
      <div class="modifier-note" style="color:var(--text-4);font-size:0.75rem;margin-top:0.75rem">
        Modifier applied this run: "<em>${{r.modifier}}</em>"
      </div>
      ${{wlCarbonStrip(e.delta_e_wh, 'Image generation total run', e.delta_t_s, e.co2e && e.co2e.intensity ? e.co2e.intensity.g_per_kwh : null)}}
      <p class="scope-note">${{r.scope}}</p>
    </div>`;
}}
const _resumeJob = new URLSearchParams(location.search).get('job');
if (_resumeJob) {{ document.getElementById('run-btn').disabled = true; pollTimer = setInterval(() => pollJob(_resumeJob), 1500); }}
</script>
    {_PROGRESS_JS}
    {_RESULT_JS}
    {_CONF_HELP_WIDGET}
    {_FOOTER}
</body>
</html>""")


@app.post("/image/start", dependencies=[Depends(requires(IMAGE_RUN))])
async def image_start(request: Request,
                      prompt: str = Form(None),
                      device: str = Form("cpu"),
                      model_key: str = Form("sd-turbo")):
    if device not in ("cpu", "gpu", "both", "compare_models"):
        device = "cpu"
    if model_key not in IMAGE_MODELS:
        return JSONResponse({"error": f"Unknown model: {model_key}"}, status_code=400)
    # CR-001 capability dispatch:
    #   prompt provided (free-form) → CUSTOM_PROMPT
    #   prompt absent                → curated canonical, Anonymous-OK
    #   device in {'both','compare_models'} → BATCH_COMPARE
    effective_prompt = prompt.strip() if prompt and prompt.strip() else None
    if effective_prompt is not None:
        gate(request, CUSTOM_PROMPT)
    else:
        effective_prompt = curated.CANONICAL_IMAGE_PROMPT
    if device in ("both", "compare_models"):
        gate(request, BATCH_COMPARE)
    prompt = effective_prompt
    cfg_m = IMAGE_MODELS[model_key]
    if device in ("cpu", "both") and not cfg_m["cpu_ok"]:
        return JSONResponse(
            {"error": f"{cfg_m['label']} is GPU-only — pick GPU or Compare Models."},
            status_code=400,
        )
    job_id = uuid.uuid4().hex[:8]
    if device == "compare_models":
        label = f"Image (compare SD/SDXL-Turbo) — {prompt[:35]}"
    else:
        label = f"Image ({cfg_m['label']} · {device.upper()}) — {prompt[:35]}"

    async def coro():
        try:
            if device == "compare_models":
                result = await run_image_compare_models_measurement(prompt, job_id, jobs)
            elif device == "both":
                result = await run_image_both_measurement(
                    prompt, job_id, jobs, model_key=model_key)
            else:
                result = await run_image_measurement(
                    prompt, job_id, jobs, device=device, model_key=model_key)
            save_result("image", job_id, result)
            jobs[job_id]["result"] = result
        except CooldownCancelled:
            jobs[job_id]["stage"] = "cancelled"
            jobs[job_id]["error"] = "Cancelled by operator during cooldown."
            LOCK_FILE.unlink(missing_ok=True)
        except Exception as e:
            jobs[job_id]["error"] = str(e)
            LOCK_FILE.unlink(missing_ok=True)

    position = queue_control.enqueue(job_id, "image", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


@app.get("/queue-status", response_class=HTMLResponse, dependencies=[Depends(requires(QUEUE_VIEW))])
async def queue_page(request: Request):
    # Only Lab (BENCHMARK_RUN) may cancel — gate the button so anonymous
    # viewers (QUEUE_VIEW is Anonymous-allowed) don't see a control they can't use.
    can_cancel = "true" if can(audience.tier(request), BENCHMARK_RUN) else "false"
    return """<!DOCTYPE html>
<html>
<head>
    <link rel="icon" type="image/svg+xml" href="/static/owl.svg">
  <title>OWL — Queue</title>
    <meta http-equiv="refresh" content="4">
    <script>window.CAN_CANCEL=""" + can_cancel + """;</script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: monospace; background: var(--bg); color: var(--text);
               max-width: 620px; margin: 0 auto; padding: 2rem; }
        h1 { color: var(--accent); font-size: 1.3rem; margin-bottom: 0.25rem; }
        .sub { color: var(--text-4); font-size: 0.78rem; margin-bottom: 2rem; }
        .empty { color: var(--text-5); font-size: 0.85rem; padding: 1.5rem 0; }
        .card { border: 1px solid var(--border); padding: 1rem 1.25rem; margin-bottom: 0.75rem; }
        .card.running { border-color: #00ff9966; }
        .card.waiting { border-color: var(--text-5); }
        .badge { display: inline-block; font-size: 0.7rem; padding: 0.15rem 0.5rem;
                 margin-bottom: 0.5rem; }
        .badge.run { background: #00ff9922; color: var(--accent); }
        .badge.wait { background: #22222299; color: var(--text-3); }
        .label { font-size: 0.9rem; color: var(--text-2); margin-bottom: 0.25rem; }
        .stage { font-size: 0.75rem; color: var(--text-3); }
        .back { color: var(--text-4); font-size: 0.78rem; text-decoration: none;
                display: block; margin-bottom: 1.5rem; }
        .back:hover { color: var(--accent); }
        .depth { font-size: 2.5rem; color: var(--accent); font-weight: bold; }
        .depth-lbl { color: var(--text-4); font-size: 0.75rem; margin-bottom: 2rem; }
""" + _HEADER_STYLES + """
    </style>
</head>
<body>
""" + _header_html(request) + """
    <h1>Queue</h1>
    <div class="sub">Auto-refreshes every 4s</div>
    <div id="pause-banner"></div>
    <div id="content"><p class="empty">Loading…</p></div>
<script>
function resumeLink(type, jobId, page) {
    if (!type || !jobId || type === 'variance') return '';
    // page (set at enqueue for sub-pages like /llm/compare, /rag/compare) wins;
    // otherwise default to /<type>. Without this, compare jobs resumed onto the
    // base page (/rag, /llm) and lost the rich compare progress.
    const base = page || ('/' + type);
    return ' <a href="' + base + '?job=' + jobId + '" style="color:var(--accent);font-size:0.75rem;' +
           'text-decoration:none;margin-left:0.75rem">↩ Resume</a>';
}
async function load() {
    const r = await fetch('/queue');
    const q = await r.json();
    const banner = document.getElementById('pause-banner');
    banner.innerHTML = q.paused
        ? '<div style="background:#442200;color:var(--warn);padding:0.75rem 1rem;'
        + 'margin-bottom:1rem;font-size:0.85rem;border:1px solid var(--warn)">'
        + '⏸ Queue paused — new jobs will wait until <code>/tmp/owl-paused</code>'
        + ' is removed. Running job (if any) continues normally.'
        + '</div>'
        : '';
    const el = document.getElementById('content');
    if (q.depth === 0) {
        el.innerHTML = '<div class="depth">0</div><div class="depth-lbl">jobs in queue — GoS1 is idle</div>';
        return;
    }
    let html = '<div class="depth">' + q.depth + '</div>' +
               '<div class="depth-lbl">job' + (q.depth !== 1 ? 's' : '') + ' in queue</div>';
    if (q.running) {
        let runHtml = '<div class="card running">' +
                '<span class="badge run">▶ RUNNING</span>' +
                resumeLink(q.running.type, q.running.job_id, q.running.resume_page) +
                '<div class="label">' + (q.running.label || q.running.job_id) + '</div>' +
                '<div class="stage">stage: ' + (q.running.stage || '…') + '</div>';
        if (q.running.type === 'benchmark' && window.CAN_CANCEL) {
            runHtml += '<button data-bid="' + q.running.job_id + '" onclick="cancelBench(this.dataset.bid)" ' +
                'style="margin-top:0.5rem;background:transparent;color:var(--err);' +
                'border:1px solid var(--err);padding:0.3rem 0.9rem;cursor:pointer;' +
                'font-family:monospace;font-size:0.78rem">■ Cancel benchmark</button>' +
                '<div style="color:var(--text-5);font-size:0.7rem;margin-top:0.3rem">' +
                'cancel takes effect after the current step</div>';
        }
        html += runHtml + '</div>';
    }
    (q.pending || []).forEach((j, i) => {
        html += '<div class="card waiting">' +
                '<span class="badge wait"># ' + j.position + '</span>' +
                resumeLink(j.type, j.job_id, j.resume_page) +
                '<div class="label">' + j.label + '</div>' +
                '<div class="stage">waiting</div></div>';
    });
    el.innerHTML = html;
}
async function cancelBench(jid) {
    if (!confirm('Cancel the running benchmark? It stops after the current step finishes.')) return;
    const form = new FormData(); form.append('job_id', jid);
    try { await fetch('/benchmark/cancel', {method:'POST', body: form}); } catch(e) {}
    load();
}
load();
</script>
""" + _FOOTER + _PROGRESS_JS + """
</body>
</html>"""


@app.get("/demo", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def demo_page(request: Request):
    # CR-002: confidence numbers and baseline/cooldown windows in the Guided
    # Tour are injected from settings.json at request time, so the tour can
    # never silently contradict the running config (same pattern as
    # /methodology — see methodology_page below).
    # CR-001: AUTH_CHIP placeholder renders the tier-aware sign-in widget.
    # CR-027: TIER_INDICATOR + upload-cap placeholders so the Welcome-step
    # tier framing and the Findings-step capability matrix stay in sync
    # with settings.json (no silent drift if caps change).
    s = cfg.load()
    member_cap_mb = s.get("upload_size_member_mb", "—")
    # CR-058 — Findings step terminus. When findings_enabled is true,
    # the Findings step (step 7) shows the curated catalog (top entries
    # + "See all findings" link) instead of echoing the visitor's just-
    # finished session runs. The original session-echo buildSummary() JS
    # early-returns when window.OWL_FINDINGS_CATALOG_ENABLED is set, so
    # flipping the flag back to false fully restores the prior behaviour.
    findings_panel_html = (
        '<p style="color:var(--text-3);font-size:0.85rem">Loading results…</p>'
    )
    if s.get("findings_enabled", False):
        catalog_items = findings_mod.list_all()
        catalog_items.sort(key=lambda f: f.last_refined, reverse=True)
        preview = catalog_items[:3]
        rows_html = _findings_catalog_rows_html(preview)
        if not preview:
            rows_html = (
                '<p style="color:var(--text-3);font-size:0.85rem;'
                'border-left:2px solid var(--border-3);padding-left:1rem">'
                'No findings published yet.</p>'
            )
        findings_panel_html = (
            f'{_FINDINGS_CATALOG_CSS}'
            '<p style="color:var(--text-3);font-size:0.85rem;line-height:1.55;margin-bottom:0.85rem">'
              "From OWL's body of evidence — citable findings backed by stored measurements:"
            '</p>'
            f'{rows_html}'
            '<div style="margin-top:0.85rem;font-size:0.82rem">'
              '<a href="/findings" style="color:var(--accent);text-decoration:none">'
              f'See all findings ({len(catalog_items)}) →</a>'
            '</div>'
            '<script>window.OWL_FINDINGS_CATALOG_ENABLED = true;</script>'
        )
    return (_DEMO_HTML
            .replace("{BASELINE_POLLS}",     str(s.get("baseline_polls",     "—")))
            .replace("{VIDEO_COOLDOWN_S}",   str(s.get("video_cooldown_s",   "—")))
            .replace("{CONF_GREEN_X}",       str(s.get("variance_green_x",   "—")))
            .replace("{CONF_YELLOW_X}",      str(s.get("variance_yellow_x",  "—")))
            .replace("{CONF_GREEN_POLLS}",   str(s.get("conf_green_polls",   "—")))
            .replace("{CONF_YELLOW_POLLS}",  str(s.get("conf_yellow_polls",  "—")))
            .replace("{BETA_CHIP}",          _BETA_CHIP)
            .replace("{AUTH_CHIP_STYLES}",   _AUTH_CHIP_STYLES)
            .replace("{AUTH_CHIP}",          _auth_chip_html(request))
            .replace("{TIER_INDICATOR}",     _tier_indicator_html(request))
            .replace("{UPLOAD_MEMBER_MB}",   str(member_cap_mb))
            .replace("{GPU_H264_ENC}",       _gpu_enc("h264"))
            .replace("{GPU_DISPLAY_NAME}",   _gpu_display_name())
            .replace("{METER_NAME}",         meter_display_name())
            .replace("{FINDINGS_PANEL}",     findings_panel_html))


_METHODOLOGY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="icon" type="image/svg+xml" href="/static/owl.svg">
<title>OWL Measurement Methodology</title>
<style>
  :root {
    --bg: #0a0a0a;
    --surface: #141414;
    --surface-hover: #1a1a1a;
    --border: #2a2a2a;
    --text: #e0e0e0;
    --text-dim: #888;
    --accent: #00ff99;
    --accent-dim: rgba(0,255,153,0.15);
    --warning: #ffaa00;
    --red: #ff4444;
    --mono: 'SF Mono', 'Cascadia Code', 'Fira Code', Consolas, monospace;
    --sans: 'Inter', system-ui, -apple-system, sans-serif;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-size: 15px;
    line-height: 1.7;
    padding: 0;
  }

  /* ── Header bar (matches other OWL pages) ── */
  .topbar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 24px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
  }
  .topbar img { height: 32px; border-radius: 50%; }
  .topbar .title {
    font-family: var(--mono);
    font-size: 14px;
    color: var(--accent);
    letter-spacing: 0.5px;
  }
  .topbar .back {
    margin-left: auto;
    color: var(--text-dim);
    text-decoration: none;
    font-size: 13px;
    font-family: var(--mono);
  }
  .topbar .back:hover { color: var(--accent); }

  /* ── Main content ── */
  .content {
    max-width: 780px;
    margin: 0 auto;
    padding: 40px 24px 80px;
  }

  h1 {
    font-family: var(--mono);
    font-size: 22px;
    color: var(--accent);
    margin-bottom: 6px;
    letter-spacing: 0.5px;
  }
  .subtitle {
    color: var(--text-dim);
    font-size: 13px;
    font-family: var(--mono);
    margin-bottom: 36px;
  }

  h2 {
    font-family: var(--mono);
    font-size: 15px;
    color: var(--accent);
    margin-top: 40px;
    margin-bottom: 16px;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--border);
    letter-spacing: 0.3px;
  }

  h3 {
    font-family: var(--sans);
    font-size: 14px;
    font-weight: 600;
    color: var(--text);
    margin-top: 24px;
    margin-bottom: 8px;
  }

  p { margin-bottom: 14px; }

  /* ── Scope banner ── */
  .scope-banner {
    background: var(--accent-dim);
    border: 1px solid rgba(0,255,153,0.3);
    border-radius: 6px;
    padding: 16px 20px;
    margin-bottom: 32px;
    font-family: var(--mono);
    font-size: 13px;
    line-height: 1.6;
    color: var(--accent);
  }
  .scope-banner strong { color: #fff; }

  /* ── Protocol steps ── */
  .protocol-steps {
    counter-reset: step;
    list-style: none;
    padding: 0;
    margin: 16px 0 20px;
  }
  .protocol-steps li {
    counter-increment: step;
    position: relative;
    padding: 12px 16px 12px 52px;
    margin-bottom: 8px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 5px;
    font-size: 14px;
    line-height: 1.5;
  }
  .protocol-steps li::before {
    content: counter(step);
    position: absolute;
    left: 16px;
    top: 12px;
    width: 24px;
    height: 24px;
    background: var(--accent-dim);
    border: 1px solid rgba(0,255,153,0.3);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--mono);
    font-size: 12px;
    color: var(--accent);
    font-weight: 600;
  }
  .protocol-steps li code {
    font-family: var(--mono);
    font-size: 12px;
    background: rgba(255,255,255,0.06);
    padding: 1px 5px;
    border-radius: 3px;
    color: var(--accent);
  }

  /* ── Confidence table ── */
  .confidence-table {
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0 20px;
    font-size: 14px;
  }
  .confidence-table th {
    text-align: left;
    font-family: var(--mono);
    font-size: 12px;
    color: var(--text-dim);
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .confidence-table td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }
  .confidence-table tr:last-child td { border-bottom: none; }
  .badge { font-size: 16px; }

  /* ── Hardware spec table ── */
  .hw-table {
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0 20px;
    font-size: 14px;
  }
  .hw-table td {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }
  .hw-table td:first-child {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--text-dim);
    width: 160px;
    white-space: nowrap;
  }

  /* ── Info callout ── */
  .callout {
    background: var(--surface);
    border-left: 3px solid var(--warning);
    padding: 14px 18px;
    margin: 16px 0 20px;
    border-radius: 0 5px 5px 0;
    font-size: 14px;
  }
  .callout.green { border-left-color: var(--accent); }

  /* ── Formula block ── */
  .formula {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 16px 20px;
    margin: 14px 0 20px;
    font-family: var(--mono);
    font-size: 13px;
    line-height: 1.8;
    color: var(--text);
    overflow-x: auto;
  }
  .formula .label {
    color: var(--text-dim);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    display: block;
    margin-bottom: 4px;
  }
  .formula .var { color: var(--accent); }

  /* ── Open questions ── */
  .open-q {
    padding: 10px 16px;
    margin-bottom: 6px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 5px;
    font-size: 14px;
    display: flex;
    gap: 10px;
    align-items: baseline;
  }
  .open-q .marker {
    color: var(--warning);
    font-family: var(--mono);
    font-size: 12px;
    flex-shrink: 0;
  }

  /* ── Section links (bottom nav) ── */
  .section-nav {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 12px 0 28px;
  }
  .section-nav a {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--accent);
    text-decoration: none;
    padding: 5px 10px;
    background: var(--accent-dim);
    border: 1px solid rgba(0,255,153,0.2);
    border-radius: 4px;
  }
  .section-nav a:hover {
    background: rgba(0,255,153,0.25);
  }

  /* ── Timestamp footer ── */
  .footer-note {
    margin-top: 48px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
    color: var(--text-dim);
    font-family: var(--mono);
    font-size: 11px;
    line-height: 1.6;
  }

  /* ── Home link (top + bottom) — matches `_BACK` used on other pages ── */
  .home-link {
    display: inline-block;
    color: var(--text-3);
    text-decoration: none;
    font-family: var(--mono);
    font-size: 13px;
  }
  .home-link:hover { color: var(--accent); }
  .home-link.top    { margin-bottom: 24px; }
  .home-link.bottom { margin-top: 32px; }

  /* ── Responsive ── */
  @media (max-width: 600px) {
    .content { padding: 24px 16px 60px; }
    h1 { font-size: 18px; }
    .protocol-steps li { padding-left: 44px; }
    .hw-table td:first-child { width: 120px; }
  }
{AUTH_CHIP_STYLES}
</style>
<script src="{CHARTJS_URL}"></script>
<script src="/static/wl-charts.js"></script>
</head>
<body>
{AUTH_CHIP}

<!-- Top bar -->
<div class="topbar">
  <a href="/" title="OWL home" style="display:inline-flex;align-items:center;gap:0.5rem;text-decoration:none">
    <img src="/static/owl.svg" alt="OWL" style="height:32px;width:32px;border-radius:0;flex-shrink:0">
  </a>
  <a href="{GOS_URL}" target="_blank" title="Greening of Streaming">
    <img src="{GOS_LOGO_URL}" alt="GoS">
  </a>
  <span class="title">OWL · Methodology</span>
  <a href="/" class="back">&larr; Home</a>
</div>

<div class="content">

  <a href="/" class="home-link top">&larr; Home</a>

  <h1>OWL Measurement Methodology</h1>
  <p class="subtitle">How OWL measures the energy cost of compute tasks &mdash; and what it doesn&rsquo;t measure.</p>

  <div style="margin: -18px 0 32px; font-family: var(--mono); font-size: 12px; display: flex; gap: 18px; flex-wrap: wrap;">
    <a href="{GITHUB_REPO_URL}" target="_blank" rel="noopener"
       style="color: var(--accent); text-decoration: none; border-bottom: 1px solid rgba(0,255,153,0.3);">
      Source on GitHub &rarr;
    </a>
    <a href="{GITHUB_ISSUES_URL}" target="_blank" rel="noopener"
       style="color: var(--warning); text-decoration: none; border-bottom: 1px solid rgba(255,170,0,0.3);">
      Report an issue / feature request &rarr;
    </a>
  </div>

  <div class="section-nav">
    <a href="#scope">Scope</a>
    <a href="#principle">Principle</a>
    <a href="#protocol">Protocol</a>
    <a href="#energy">Energy maths</a>
    <a href="#confidence">Confidence</a>
    <a href="#diagnostics">Diagnostics</a>
    <a href="#hardware">Hardware</a>
    <a href="#tests">Test types</a>
    <a href="#limits">Limitations</a>
    <a href="#carbon">CO&#x2082;e</a>
    <a href="#open">Open questions</a>
  </div>

  <h2 id="scope">Scope</h2>

  <div class="scope-banner">
    <strong>Device layer only.</strong><br>
    All measurements cover the GoS1 server: CPU, GPU, RAM, storage, fans, motherboard.<br>
    Network, CDN, client devices (CPE), and production/storage infrastructure are explicitly excluded.<br>
    LLM measurements do not include amortised training cost.
  </div>

  <p>OWL measures what happens inside one machine when it performs a real task. This is intentionally narrow. The energy cost of streaming is distributed across data centres, networks, and consumer devices &mdash; each with different measurement challenges and attribution problems. We start with the layer we can measure directly, at the wall, with no modelling assumptions.</p>

  <p>This scoping decision means OWL results are <em>not</em> lifecycle assessments and should not be cited as total-cost-of-delivery figures. They answer a specific question: how much additional energy does this server draw to perform this task, above its idle baseline?</p>

  <h2 id="principle">Measurement Principle</h2>

  <p>OWL uses <strong>wall-power delta measurement</strong>: the difference between what the server draws at idle and what it draws under load, captured by an external smart plug.</p>

  <div class="callout green">
    The plug measures the entire system &mdash; not a model, not a software estimate, not a per-component reading. If the CPU fan spins faster, the PSU runs less efficiently, or the GPU draws from the 12V rail, it&rsquo;s all in the number.
  </div>

  <p>This follows the GoS <strong>REM (Remote Energy Measurement)</strong> approach: real devices, real workloads, measured externally, at polling intervals short enough to capture the task&rsquo;s energy profile.</p>

  <h2 id="protocol">Measurement Protocol</h2>

  <p>Every test in OWL &mdash; video, LLM, image generation, RAG &mdash; follows the same core protocol:</p>

  <ol class="protocol-steps">
    <li>
      <strong>Focus mode.</strong> Suppress background system tasks (apt, cron, man-db, fwupd, etc.) that would introduce energy noise. Managed via <code>systemctl stop</code> with dedicated sudoers rules.
    </li>
    <li>
      <strong>Model unload</strong> (LLM/RAG only). Send <code>keep_alive=0</code> to Ollama and wait 3 seconds for GPU memory release. Ensures a cold start when cold-inference mode is selected.
    </li>
    <li>
      <strong>Baseline capture.</strong> Poll the {METER_NAME} at 1-second intervals for a configurable period (currently <code>{BASELINE_POLLS}</code> polls &mdash; configurable in Settings). The mean of these readings becomes W<sub>base</sub> &mdash; the server&rsquo;s idle power draw.
    </li>
    <li>
      <strong>Lock.</strong> Acquire <code>/tmp/gos-measure.lock</code> to prevent concurrent measurements from overlapping. A FIFO queue manages waiting jobs.
    </li>
    <li>
      <strong>Execute task.</strong> Run the actual workload (ffmpeg, Ollama inference, SD-Turbo diffusion) while continuing to poll the P110 at 1-second intervals. Thermal sensors (CPU Tctl, GPU junction, GPU PPT) are read in parallel.
    </li>
    <li>
      <strong>Compute energy.</strong> Calculate delta power, total energy, and per-unit metrics (see formulas below).
    </li>
    <li>
      <strong>Persist.</strong> Write the full result to a JSON file &mdash; parameters, energy report, raw poll data, thermal readings, confidence flag. Every result is reproducible and exportable.
    </li>
    <li>
      <strong>Focus exit.</strong> Restart suppressed system timers in parallel (via ThreadPoolExecutor) to minimise downtime.
    </li>
  </ol>

  <p>Between sequential runs (e.g., CPU vs GPU comparison), a configurable cooldown (currently <code>{VIDEO_COOLDOWN_S}</code> seconds &mdash; configurable in Settings) allows the system to return to thermal equilibrium.</p>

  <h2 id="energy">Energy Calculation</h2>

  <div class="formula">
    <span class="label">Delta power (average above idle)</span>
    <span class="var">&Delta;W</span> = mean(<span class="var">W<sub>polls</sub></span>) &minus; <span class="var">W<sub>base</sub></span>
  </div>

  <div class="formula">
    <span class="label">Total energy consumed by task</span>
    <span class="var">&Delta;E</span> = <span class="var">&Delta;W</span> &times; (<span class="var">&Delta;t</span> / 3600) &nbsp; [Wh]
    <br><br>
    where <span class="var">&Delta;t</span> = task duration in seconds
  </div>

  <div class="formula">
    <span class="label">Per-token energy (LLM / RAG)</span>
    <span class="var">E<sub>token</sub></span> = <span class="var">&Delta;E</span> / <span class="var">N<sub>tokens</sub></span> &nbsp; [mWh/token]
  </div>

  <div class="formula">
    <span class="label">Per-image energy (image generation)</span>
    <span class="var">E<sub>image</sub></span> = <span class="var">&Delta;E</span> / <span class="var">N<sub>images</sub></span> &nbsp; [Wh/image]
  </div>

  <p>All formulas use wall-power from the P110 (system-level), not component-level readings. The GPU&rsquo;s self-reported power (its vendor sensor &mdash; <code>amdgpu</code> PPT or <code>nvidia-smi</code> power draw) is captured for reference but is not used in the primary energy calculation &mdash; it covers only the GPU die/board, not the full system delta (CPU, RAM, drives, fans, PSU losses).</p>

  <h2 id="confidence">Confidence Framework</h2>

  <p>Every OWL result carries a traffic-light confidence flag. Under the CR-028 Phase 2 model (designed with Tania Pouli), the flag answers one defensible question per run: <strong>can this run be distinguished from idle?</strong> It is a per-run confidence interval, not a fixed-watt rule of thumb.</p>

  <p>We keep the raw per-poll power samples from both the baseline window and the task window, form a standard error on the measured power increase &Delta;W, then convert &Delta;W into a one-sided confidence that the task really draws above idle:</p>

  <div class="formula">
    <span class="label">Standard error &mdash; conservative (worst case of the calibrated and per-run estimates, plus drift)</span>
    SE<sub>final</sub> = max(SE<sub>calibrated</sub>, SE<sub>per-run</sub>) + SE<sub>drift</sub><br>
    SE<sub>calibrated</sub> = (<span class="var">variance_idle_pct</span>/100 &middot; W<sub>base</sub>) &times; &radic;(1/n<sub>base</sub> + 1/n<sub>task</sub>)<br>
    SE<sub>per-run</sub> = &radic;(&sigma;&sup2;<sub>base</sub>/n<sub>base</sub> + &sigma;&sup2;<sub>task</sub>/n<sub>task</sub>)<br>
    SE<sub>drift</sub> = (<span class="var">variance_idle_drift_pct</span>/100) &middot; W<sub>base</sub>
    <span class="label" style="margin-top:0.6rem">Confidence the task draws above idle</span>
    <span class="var">confidence<sub>positive</sub></span> = &Phi;(&Delta;W / SE<sub>final</sub>)
  </div>

  <table class="confidence-table">
    <tr>
      <th>Flag</th>
      <th>Meaning</th>
      <th>Criteria (defaults)</th>
    </tr>
    <tr>
      <td><span class="badge">&#x1F7E2;</span></td>
      <td><strong>Repeatable</strong> &mdash; the task is almost certainly above idle, with enough samples to be reliable.</td>
      <td>confidence<sub>positive</sub> &ge; 95% and &ge; <code>{CONF_GREEN_POLLS}</code> task polls</td>
    </tr>
    <tr>
      <td><span class="badge">&#x1F7E1;</span></td>
      <td><strong>Early insight</strong> &mdash; directional evidence; a longer run would strengthen it.</td>
      <td>confidence<sub>positive</sub> &ge; 80% and &ge; <code>{CONF_YELLOW_POLLS}</code> task polls</td>
    </tr>
    <tr>
      <td><span class="badge">&#x1F534;</span></td>
      <td><strong>Need more data</strong> &mdash; cannot yet be distinguished from idle.</td>
      <td>below the yellow threshold</td>
    </tr>
  </table>

  <div class="callout green">
    <strong>Why a confidence interval, not a fixed-watt rule?</strong> The flag uses this run&rsquo;s own observed noise (<code>SE<sub>per-run</sub></code>), takes the worst case against a calibrated idle floor (<code>SE<sub>calibrated</sub></code>), and adds a drift term for the time gap between the baseline and task windows &mdash; so it reflects real signal quality on the day, not an assumed noise floor. The minimum task-sample counts remain because 1&nbsp;s power samples are autocorrelated: a very short task should not turn green on one or two lucky readings.
  </div>

  <div class="callout">
    <strong>Inputs (CR-028 Phase 2, &ldquo;option C&rdquo;).</strong> The single-run flag uses only <code>variance_idle_pct</code> as the calibrated idle noise floor. The per-codec calibration CVs (<code>variance_cpu_pct</code> / <code>variance_gpu_pct</code>) are run-to-run repeatability measures, reserved for a future aggregate-confidence layer rather than mixed into the single-run formula. The first pass uses raw sample counts and a 1.96 (95%) critical value; an autocorrelation correction (effective sample count) and a Student-t critical value are documented future refinements.
  </div>

  <div class="callout">
    <strong>Legacy results.</strong> Results saved before raw per-poll samples were persisted fall back to the earlier variance-threshold flag (&Delta;W against a multiple of <code>variance_pct</code> &times; W<sub>base</sub>), so historical runs keep their badge.
  </div>

  <div class="callout">
    <strong>P110 and total system noise:</strong> The Tapo P110 smart plug exposes power readings at <strong>1&nbsp;W resolution via its local API</strong> (the path OWL currently uses, chosen for portability and the Python <code>tapo</code> library&rsquo;s reliability). The underlying instrument is more precise &mdash; <strong>~1&nbsp;mW resolution via direct device read</strong> &mdash; so future versions could lower the hardware noise floor by ~3 orders of magnitude if needed. In practice, however, the dominant noise sources are OS background processes (apt, cron, systemd timers) and thermal drift between runs, not hardware quantisation. Focus mode suppresses the worst offenders, but residual variance remains. The variance calibration process measures this combined noise empirically and stores it as the reference for all confidence calculations.
  </div>

  <p>The confidence framework follows GoS&rsquo;s broader principle: <em>if it can&rsquo;t be measured, it shouldn&rsquo;t be asserted.</em> A &#x1F534; result is not a failure &mdash; it&rsquo;s an honest signal that the measurement instrument isn&rsquo;t sensitive enough for that task. Publishing it transparently is more useful than hiding it.</p>

  <h3 style="margin-top:1.25rem">Calibration integrity</h3>
  <p>The variance calibration runner (<code>/variance/run</code>) executes <code>{VARIANCE_RUNS}</code> pairs of H.264&nbsp;CPU + H.265&nbsp;GPU encodes with <code>{VARIANCE_COOLDOWN_S}</code>&thinsp;seconds between them, and computes three coefficients of variation: <strong>idle</strong> (raw P110 baseline readings, captures system noise), <strong>CPU</strong> (run-to-run reproducibility of the CPU encode &Delta;W), <strong>GPU</strong> (same for GPU). Their mean becomes <code>variance_pct</code>.</p>
  <p>The runner is hardened against silent encode failures: every <code>ffmpeg</code> invocation&rsquo;s exit code is checked, only successful encodes contribute &Delta;W, and per-side failure counters are tracked. <strong>If &ge;50% of either side fails, the runner refuses to update settings</strong> &mdash; the result JSON is still returned (with <code>cpu_failed</code>, <code>gpu_failed</code>, <code>failure_stderr</code>, <code>abort_reason</code> fields) for forensics, but <code>variance_pct</code> stays unchanged on disk. This protects against the failure mode where partial-encode &Delta;W values contaminate the calibration without the operator noticing.</p>

  <h2 id="diagnostics">Diagnostics &amp; Pre-calibration</h2>

  <p>Two layers of measurement-discipline tooling sit alongside the calibration:</p>

  <h3>Thermal-recovery probe</h3>
  <p>Before trusting a calibration result, the system needs to know that <code>variance_cooldown_s</code> is long enough &mdash; the idle samples taken between encodes must come from a thermally recovered system, not from the tail of the previous workload. The <code>bin/probe-thermal-recovery</code> diagnostic characterises this empirically. For a sequence of distances <em>d</em> after each of a CPU and a GPU encode (defaults: 0, 2, 5, 8, 12, 18, 25, 35, 50, 70, 95, 120 seconds), the probe samples idle power for 8 polls and writes the mean / std / CV to a CSV under <code>results/diagnostics/</code>.</p>
  <figure id="recoveryFig" style="margin:18px 0 22px;padding:14px 16px;background:var(--surface);border:1px solid var(--border);border-radius:6px">
    <div style="position:relative;height:280px"><canvas id="recoveryChart"></canvas></div>
    <figcaption id="recoveryCap" style="margin-top:10px;font-size:12px;color:var(--text-dim);line-height:1.6">Recovery curve from the latest probe run.</figcaption>
  </figure>
  <script>
  (function () {
    var data = {RECOVERY_CHART_DATA};
    var fig = document.getElementById('recoveryFig');
    if (!data || !window.WlCharts) { if (fig) fig.style.display = 'none'; return; }
    var cpu = data.points.filter(function (p) { return p.workload === 'cpu'; }).map(function (p) { return {x: p.distance_s, y: p.mean_w}; });
    var gpu = data.points.filter(function (p) { return p.workload === 'gpu'; }).map(function (p) { return {x: p.distance_s, y: p.mean_w}; });
    WlCharts.line({
      canvas: document.getElementById('recoveryChart'),
      xLabel: 'seconds after the encode ends',
      yLabel: 'mean idle power (8-poll window)',
      yUnit:  'W',
      datasets: [
        { label: 'after a CPU encode', color: 'cpu', points: cpu },
        { label: 'after a GPU encode', color: 'gpu', points: gpu },
        { label: 'configured cooldown (' + data.cooldown + 's)', color: 'warn', borderDash: [5, 4], pointRadius: 0,
          points: [{x: data.cooldown, y: data.yLo}, {x: data.cooldown, y: data.yHi}] }
      ]
    });
    var cap = document.getElementById('recoveryCap');
    if (cap) cap.innerHTML = 'Source: <code>' + data.source + '</code> &middot; generated ' + data.generatedAt +
      '. Idle power drops back to &approx;' + data.floor + '&nbsp;W within roughly 5&nbsp;s of either encode ending and stays flat; the dashed line marks the configured ' + data.cooldown + '&nbsp;s cooldown &mdash; comfortably past recovery.';
  })();
  </script>

  <p>On the GoS1 hardware the recovery is fast (see chart above): post-CPU and post-GPU baselines converge to the settled idle floor by <em>d&nbsp;=&nbsp;5&ndash;8&thinsp;s</em> with within-window CV around 1&ndash;2.5%. So the configured cooldown of <code>{VARIANCE_COOLDOWN_S}</code>&thinsp;seconds is comfortably more than necessary &mdash; useful as a margin, not as a correction.</p>
  <p>The same curve is also on the Settings page (lab access), where it refreshes live from the probe endpoint. Each probe run overwrites nothing &mdash; it leaves a fresh timestamped CSV pair under <code>results/diagnostics/</code> so historical curves can be diffed if hardware or thermal conditions change.</p>

  <h3>Why the probe matters</h3>
  <p>The probe was the seam that exposed the <code>scale_vaapi</code> leak (the GPU encode failed within 90 seconds of starting the diagnostic) and the silent-failure path in the calibration loop. Generalisable lesson: <em>measurement code should fail loudly, not interpolate around brokenness.</em> The probe predates being a first-class server feature, so its on-server execution is currently CLI-only; a queue-aware <code>/precalibration/run</code> endpoint with an in-page &ldquo;Re-run&rdquo; button is captured as a follow-up.</p>

  <h2 id="hardware">Hardware Disclosure</h2>

  <p>All results are tied to specific hardware. Different CPUs, GPUs, RAM configurations, and PSU efficiencies will produce different numbers. OWL results should always be cited with their hardware context.</p>

  <table class="hw-table">
    <tr><td>Server</td><td>GoS1 &mdash; custom build, Ubuntu 24, kernel 6.17</td></tr>
    <tr><td>CPU</td><td>AMD Ryzen 9 7900, 24 cores (12C/24T), 65W TDP</td></tr>
    <tr><td>GPU</td><td>{GPU_HW}</td></tr>
    <tr><td>RAM</td><td>61 GB DDR5</td></tr>
    <tr><td>Storage</td><td>500 GB NVMe SSD (OS + working set) + 4 TB NVMe SSD (test media &amp; result archive, mounted <code>/srv/data</code>)</td></tr>
    <tr><td>Idle power</td><td>~79W at the wall (settled, display-blanked). The mid-2026 RTX 5080 swap raised idle ~+20W over the prior AMD 7800 XT (~57&ndash;59W) &mdash; intrinsic to the larger card, not a fault. The 5080 idle is display-state-sensitive: a blanked desktop sits at ~79W, an active (non-blanked) desktop ~101W; GoS1 blanks ~15&nbsp;min after the last input, so the like-for-like figure is ~79W</td></tr>
    <tr><td>Measurement</td><td>{METER_NAME}, 1-second polling via local API (tapo 0.8.12)</td></tr>
    <tr><td>Video</td><td>ffmpeg current master build (<code>/usr/local/bin/ffmpeg-master</code> &mdash; ships the NVENC encoders + <code>scale_cuda</code> filter) &mdash; libx264, libx265, libsvtav1 (CPU); {VIDEO_GPU_ENCODERS}</td></tr>
    <tr><td>LLM</td><td>Ollama 0.20.2 &mdash; ladder of TinyLlama 1.1B, Qwen3 1.7B/4B/8B, Mistral-NeMo 12B, Phi-4 14B, GPT-OSS 20B (CPU + CUDA GPU); Qwen3 4B is the canonical RAG model</td></tr>
    <tr><td>Image</td><td>PyTorch + diffusers &mdash; SD-Turbo (~1B), SDXL-Turbo (~3.5B, GPU only); CPU + CUDA GPU</td></tr>
  </table>

  <div class="callout">
    <strong>Hardware change &mdash; GPU swap (mid-2026).</strong> GoS1&rsquo;s GPU was replaced from an AMD Radeon RX&nbsp;7800&nbsp;XT (VAAPI + ROCm) with an NVIDIA RTX&nbsp;5080 (NVENC + CUDA). OWL&rsquo;s vendor-abstraction layer auto-detected the new card with no code change, and results are stamped with the GPU they ran on. The driver was tooling reach (CUDA-only partner workloads), not energy &mdash; and the swap has a real methodology consequence worth stating plainly: <strong>idle power rose ~+20W at the wall</strong> (~57&ndash;59W &rarr; ~79W), intrinsic to the larger card. Per-encode NVENC is more efficient than VAAPI at matched bitrate (measured n=10: H.264 &minus;42%, H.265 &minus;22%, AV1 &minus;25% energy), but the higher idle floor means the swap is only <em>net</em> energy-positive for H.264-heavy, near-saturated duty cycles; for H.265 the idle penalty is never repaid by transcode alone. We therefore treat the 5080 as a <strong>capability / quality / speed upgrade, not a same-workload energy win</strong>. The frozen pre-swap AMD baseline is preserved for comparison.
  </div>

  <h2 id="tests">Test Types</h2>

  <h3>Video transcoding</h3>
  <p>Transcode a source file (default: Netflix Meridian 4K, CC BY 4.0) to a target codec and 1080p. Measures the energy cost of the full encode pipeline &mdash; decode, colour-space conversion, scale, encode. Supports CPU vs GPU comparison: both paths are run sequentially with a cooldown between them, and results are presented side by side.</p>
  <p>Six presets across three codecs: <strong>H.264</strong> (libx264 / {GPU_H264_ENC}, 4000 kbps), <strong>H.265</strong> (libx265 / {GPU_H265_ENC}, 2000 kbps), <strong>AV1</strong> (libsvtav1 / {GPU_AV1_ENC}, 1500 kbps). A seventh <strong>Compare all codecs</strong> preset runs all six in sequence and produces a cross-codec energy matrix. (Encoder names track the installed GPU &mdash; the live list is in the Hardware Disclosure table above.)</p>
  <p>All presets use <strong>ABR (Average Bit Rate)</strong> rate control at a shared per-codec bitrate target, so CPU and GPU receive the identical encoding task &mdash; output file sizes match across devices as confirmation. All GPU presets use the <strong>full hardware pipeline</strong>: hardware decode (<code>-hwaccel cuda</code>) + <code>scale_cuda</code> + hardware encode, with frames GPU-resident throughout. This represents real live-encoding workflows (Harmonic, Ateme); an earlier partial pipeline (CPU decode + GPU encode) has been replaced because it was unrepresentative and bottlenecked on CPU decode overhead.</p>
  <p>The ffmpeg command used for each run is logged in the result JSON, editable from the page (signed-in GoS members and lab access), and reproduced in the result card for full transparency.</p>
  <p><strong>Perceptual quality (VMAF).</strong> Comparison runs (CPU vs GPU, or all codecs) also report <strong>VMAF</strong> &mdash; Netflix&rsquo;s perceptual quality metric (0&ndash;100, higher is better) &mdash; so the energy figures sit next to a quality figure rather than an unstated assumption that the encodes are equivalent. It is computed at the delivered 1080p, comparing each encoded output against the source downscaled to 1080p (the distorted side is cropped to strip hardware-encoder padding, never upscaled). VMAF runs <em>after</em> the measurement window closes, so its compute cost is excluded from the reported energy. It is a quality cross-check, not a primary GoS measurement.</p>

  <div class="callout">
    <strong>Open item (narrower than before):</strong> With ABR, the bitrate target is now equal across devices. GOP structure and profile level are not yet explicitly controlled and may differ between CPU and GPU encoder defaults &mdash; a working session with the measurement team is planned to confirm apples-to-apples output at the profile/GOP level. A second benchmark family at each codec&rsquo;s natural operating point (CRF for CPU, QP for GPU) is also on the roadmap.
  </div>

  <h3>AI workloads <span style="color:var(--text-dim);font-weight:400;font-size:13px">— beta, exploratory</span></h3>
  <p>Video transcoding is OWL&rsquo;s core benchmark. Three AI workloads run alongside it on the same protocol and confidence framework, but they are explicitly <strong>beta</strong> &mdash; useful for relative comparisons, with headline numbers still being hardened (see Open Questions). In brief:</p>
  <ul style="margin: 12px 0 18px 20px; font-size: 14px; line-height: 1.7;">
    <li><strong>LLM inference</strong> &mdash; mWh/token across a model ladder (TinyLlama&nbsp;1.1B, Qwen3&nbsp;1.7B/4B/8B, Mistral-NeMo&nbsp;12B, Phi-4&nbsp;14B, up to GPT-OSS&nbsp;20B), cold or warm, CPU or GPU, with an optional batch mode. Prompts are saved in the result JSON; output streams word-by-word as live-run proof.</li>
    <li><strong>Image generation</strong> &mdash; Wh/image for the SD-Turbo (~1B) and SDXL-Turbo (~3.5B) distilled diffusion models, CPU or GPU, with a Compare-Models mode that fixes prompt, seed and resolution so model size is the only variable.</li>
    <li><strong>RAG</strong> &mdash; the energy delta of retrieval: baseline (no retrieval) vs RAG with 3 context chunks vs 8, retrieved from a document corpus via ChromaDB + sentence-transformer embeddings, compared side by side.</li>
  </ul>

  <p><strong>Framing (GoS Language Lab position paper, Jan 2026):</strong> AI in streaming is <strong>neither inherently sustainable nor unsustainable</strong> &mdash; type, size and deployment decide net impact. The type matters enormously: streaming leans on <strong>small specialised CNNs</strong> (per-title encoding, scene classification, super-resolution) that are orders of magnitude cheaper than the general-purpose LLMs and diffusion models these tabs measure as an upper bound. OWL measures the energy AI <strong>adds</strong> (inference only); it does not measure the infrastructure energy AI <strong>avoids</strong> through better compression, caching or routing &mdash; both halves are needed for net impact, and OWL has the first. Each AI result is also shown as a multiple of a real video encode (the pinned canonical H.265&nbsp;GPU encode of Meridian-120s) so the number stays anchored to a streaming workload rather than floating free. Full framing: <a href="{POSITION_PAPER_URL}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none">Language Lab AI position paper &rarr;</a>.</p>

  <h2 id="limits">Known Limitations</h2>

  <div class="open-q"><span class="marker">&#9658;</span><span><strong>P110 temporal resolution.</strong> 1-second polling means tasks shorter than ~5 seconds produce few data points. Very fast models (e.g., TinyLlama single inference at 1&ndash;4 seconds) are at the edge of measurability. Batching mitigates this but changes what&rsquo;s being measured (batch cost, not single-inference cost). The same constraint puts a floor on any artificially-shortened encode: a workload that finishes in 3&ndash;4 seconds yields only 3&ndash;4 P110 polls, and the resulting per-run &Delta;W mean becomes noisy enough to inflate the coefficient of variation independently of any real measurement issue.</span></div>

  <div class="open-q"><span class="marker">&#9658;</span><span><strong>P110 power resolution.</strong> The Tapo P110 instrument itself reports at <strong>1&nbsp;mW</strong> resolution via direct device read, but its <strong>public HTTP API exposes only 1&nbsp;W</strong> &mdash; and the public API is what this deployment polls. The effective ~&plusmn;1&nbsp;W noise floor is therefore an API-shape limit, not a hardware limit: low-delta tasks (e.g., idle audio processing, lightweight network operations) cannot be reliably measured against it. A future direct-device path would unlock ~1000&times; finer resolution from the same plug.</span></div>

  <div class="open-q"><span class="marker">&#9658;</span><span><strong>Single server.</strong> All results are from one machine. Generalisability to other hardware configurations is unknown without cross-platform measurement.</span></div>

  <div class="open-q"><span class="marker">&#9658;</span><span><strong>Baseline drift.</strong> The server&rsquo;s idle power drifts with thermal state, background processes, and &mdash; since the RTX 5080 swap &mdash; GPU display power state: a blanked vs active desktop alone moves the wall figure by ~20W (~79W &rarr; ~101W). The per-run baseline capture (re-measured immediately before each task) mitigates this, but it introduces variance between runs taken at different times.</span></div>

  <div class="open-q"><span class="marker">&#9658;</span><span><strong>PSU efficiency curve.</strong> Wall power includes PSU conversion losses, which are non-linear (PSUs are less efficient at low and very high loads). Two tasks that consume the same <em>internal</em> power may report different wall-power deltas depending on where they sit on the PSU efficiency curve.</span></div>

  <h2 id="carbon">From energy to CO<sub>2</sub>e &mdash; for reference only</h2>

  <p><strong>OWL is a power meter, not a carbon calculator.</strong> The number OWL produces and stands behind is <strong>energy</strong> &mdash; watts at the wall and watt-hours per task, measured directly by the P110. Everything else on this page is about getting that energy number right. We lead with power because it is what we can measure at the wall with no modelling assumptions; carbon is one modelling layer removed.</p>

  <p>Every result <em>also</em> carries a gCO<sub>2</sub>e figure, but only as a downstream convenience: we multiply the measured energy by a grid carbon-intensity factor (Wh &times; gCO<sub>2</sub>e/kWh) so the energy can be read against everyday activities. That makes it a <strong>reference estimate, never a GoS measurement.</strong> Carbon attribution &mdash; allocation, boundaries, double-counting, marginal vs average intensity &mdash; is a hard problem that GoS deliberately leaves to the bodies whose job it is. This follows the GoS principle directly: <em>&ldquo;if it can&rsquo;t be measured, it shouldn&rsquo;t be asserted&rdquo;</em> &mdash; and what OWL measures directly is energy. Read the energy figure as the result; the CO<sub>2</sub>e is a footnote.</p>

  <p style="background:rgba(255,170,0,0.06);border-left:3px solid var(--warning);padding:0.65rem 0.85rem">
    <strong style="color:var(--accent)">🟢 Direct</strong> = the energy figure (P110 polling at the wall, validated method, GoS primary measurement &mdash; this is what we cite). <strong style="color:var(--warning)">🟡 Indicative</strong> = the gCO<sub>2</sub>e figure (Wh &times; third-party grid intensity &mdash; context, not citable as GoS data). Vocabulary follows the Greening of Streaming <a href="{POSITION_PAPER_URL}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none">Language Lab AI position paper (Jan 2026)</a>, which proposes this 🟢/🟡/🔴 traffic-light for the entire ICT-energy-measurement landscape and rates IEA top-down energy figures as 🟡 Amber. OWL applies the same framework to its own outputs &mdash; every result-card carbon block carries the 🟡 chip; the energy headline retains the green palette.
  </p>
  <p>For what it&rsquo;s worth, the intensity used is lifecycle-basis (IPCC AR6 factors): the live French grid mix via <a href="{ECO2MIX_URL}" style="color:var(--accent);text-decoration:none">Eco2mix</a> when reachable, ElectricityMaps as a backup, and <a href="{EMBER_URL}" style="color:var(--accent);text-decoration:none">Ember</a> annual country means as the fallback (also used for the stable comparison cities). The value and which source produced it are recorded in every result JSON and CSV export (CSV header carries a leading comment marking the carbon columns indicative). A result&rsquo;s carbon dropdown also shows the same energy on a few past French grids for context. Module status &mdash; live cache, source, age, fallback &mdash; is at <a href="/carbon" style="color:var(--accent);text-decoration:none">/carbon</a>.</p>

  <h2 id="open">Open Questions</h2>

  <p>These are questions OWL has surfaced but not yet answered. They are published here in the interest of transparency.</p>

  <div class="open-q"><span class="marker">?</span><span><strong>Confidence thresholds.</strong> The live flag is the CR-028 Phase 2 confidence interval described above; its positive-confidence cut-points (95% / 80%) and minimum poll counts are still set by judgement, and the first pass uses a 1.96 critical value with raw sample counts. A working session with the measurement team is planned to ground these &mdash; and to add the autocorrelation (effective-<em>n</em>) and Student-<em>t</em> refinements &mdash; against repeated calibration runs across workloads and thermal states. (The legacy 5&times; / 2&times; variance multipliers now apply only to pre-CI historical results.)</span></div>

  <div class="open-q"><span class="marker">?</span><span><strong>Transcoding profile/GOP equivalence.</strong> ABR rate control now gives CPU and GPU the same bitrate target, and output file sizes match as confirmation. GOP structure and profile level are still default-per-encoder and have not been explicitly normalised. A working session is planned to confirm apples-to-apples at that level, and to add a second benchmark family at each codec&rsquo;s natural operating point (CRF for CPU, QP for GPU).</span></div>

  <div class="open-q"><span class="marker">?</span><span><strong>AI-workload questions (beta).</strong> LLM: does mWh/token drift across a batch (thermal saturation, memory pressure)? Image / RAG: how much of each energy delta is fixed overhead (model load, embedding lookup) vs. work that scales with output or context length? Secondary to the video benchmark; not yet investigated in depth.</span></div>

  <div class="open-q"><span class="marker">?</span><span><strong>Cross-platform comparability.</strong> How should results from different hardware be compared? Normalisation by TDP? By performance tier? By workload-equivalent output quality?</span></div>

  <div class="footer-note">
    OWL is built and maintained by <a href="{GOS_URL}" style="color:var(--accent);text-decoration:none;">Greening of Streaming</a>, a French NGO (loi 1901).<br>
    Methodology version 0.5 &middot; last updated 2026-06-09 &middot; Feedback: bs@ctoic.net<br>
    Source: <a href="{GITHUB_REPO_URL}" style="color:var(--accent);text-decoration:none;">github.com/greeningofstreaming/wattlab</a>
  </div>

  <a href="/" class="home-link bottom">&larr; Home</a>

</div>
</body>
</html>"""


def _recovery_chart_payload(cooldown_s):
    """Latest thermal-recovery probe summary, trimmed to what the static
    /methodology chart needs (points + settled floor + provenance), or None
    if no probe data is on disk. Unlike /precalibration/data this carries no
    auth — it's a frozen snapshot baked into a public page at render time,
    re-read from the CSV on each request."""
    import csv as csv_mod
    diag_dir = Path("/home/gos/wattlab/results/diagnostics")
    summaries = sorted(diag_dir.glob("recovery_*_summary.csv")) if diag_dir.exists() else []
    if not summaries:
        return None
    latest = summaries[-1]
    pts = []
    try:
        with latest.open() as f:
            for row in csv_mod.DictReader(f):
                pts.append({"distance_s": int(row["distance_s"]),
                            "workload":   row["workload"],
                            "mean_w":     round(float(row["mean_w"]), 2)})
    except (OSError, KeyError, ValueError):
        return None
    if not pts:
        return None
    ys      = [p["mean_w"] for p in pts]
    settled = [p["mean_w"] for p in pts if p["distance_s"] >= 60]
    floor   = round(sum(settled) / len(settled), 1) if settled else round(min(ys), 1)
    return {
        "points":      pts,
        "cooldown":    cooldown_s,
        "floor":       floor,
        "yLo":         round(min(ys), 1),
        "yHi":         round(max(ys), 1),
        "source":      latest.name,
        "generatedAt": datetime.fromtimestamp(latest.stat().st_mtime).isoformat(timespec="seconds"),
    }


def _gpu_display_name() -> str:
    """Card name for UI copy. Settings `gpu_display_name` (a curated string like
    'AMD Radeon RX 7800 XT, 16GB VRAM') wins if set; otherwise the auto-detected
    name from gpu.BACKEND. A reboot alone is always correct (detection); the
    override only exists to prettify the messy lspci string (CR-060)."""
    return cfg.load().get("gpu_display_name") or gpu.BACKEND.name


def _gpu_hw_row() -> str:
    """Hardware-Disclosure GPU cell: '<name>, <ENCODE> + <RUNTIME>'."""
    enc = {"amd": "VAAPI + ROCm", "nvidia": "NVENC + CUDA"}.get(gpu.BACKEND.vendor, "CPU only")
    return f"{_gpu_display_name()}, {enc}"


def _gpu_video_encoders() -> str:
    """Hardware-Disclosure Video cell GPU-encoder list, vendor-resolved."""
    if gpu.BACKEND.vendor == "none":
        return "(no discrete GPU — CPU encode only)"
    encs = ", ".join(gpu.BACKEND.ffmpeg_encoder(c) for c in ("h264", "h265", "av1"))
    pipe = "full VAAPI pipeline" if gpu.BACKEND.vendor == "amd" else "full NVENC/CUDA pipeline"
    return f"{encs} (GPU, {pipe})"


def _gpu_enc(codec: str) -> str:
    """GPU encoder name for `codec` (h264/h265/av1) for UI copy — vendor-
    resolved via gpu.BACKEND so preset/settings labels track the installed
    card and never hardcode a vendor. Safe when no discrete GPU is present."""
    if gpu.BACKEND.vendor == "none":
        return "GPU encode unavailable"
    return gpu.BACKEND.ffmpeg_encoder(codec)


def _gpu_runtime() -> str:
    """AI-runtime label for UI copy: ROCm (AMD) / CUDA (Nvidia) / CPU."""
    return {"amd": "ROCm", "nvidia": "CUDA"}.get(gpu.BACKEND.vendor, "CPU")


@app.get("/methodology", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def methodology_page(request: Request):
    # Inject live settings into placeholder fields so the methodology page
    # can never silently drift from the actual configuration in settings.json.
    # See CR-002 for context — `baseline_polls`, `video_cooldown_s`, and the
    # confidence thresholds (variance multipliers + poll counts) were
    # previously hard-coded in the prose and table, and contradicted the
    # running config any time settings were changed.
    s = cfg.load()
    recovery = _recovery_chart_payload(s.get("variance_cooldown_s", 40))
    return (_METHODOLOGY_HTML
            .replace("{AUTH_CHIP_STYLES}",   _AUTH_CHIP_STYLES)
            .replace("{AUTH_CHIP}",          _auth_chip_html(request))
            .replace("{BASELINE_POLLS}",     str(s.get("baseline_polls",     "—")))
            .replace("{VIDEO_COOLDOWN_S}",   str(s.get("video_cooldown_s",   "—")))
            .replace("{CONF_GREEN_X}",       str(s.get("variance_green_x",   "—")))
            .replace("{CONF_YELLOW_X}",      str(s.get("variance_yellow_x",  "—")))
            .replace("{CONF_GREEN_POLLS}",   str(s.get("conf_green_polls",   "—")))
            .replace("{CONF_YELLOW_POLLS}",  str(s.get("conf_yellow_polls",  "—")))
            .replace("{VARIANCE_RUNS}",      str(s.get("variance_runs",      "—")))
            .replace("{VARIANCE_COOLDOWN_S}",str(s.get("variance_cooldown_s","—")))
            .replace("{GPU_HW}",             _gpu_hw_row())
            .replace("{VIDEO_GPU_ENCODERS}", _gpu_video_encoders())
            .replace("{GPU_H264_ENC}",       _gpu_enc("h264"))
            .replace("{GPU_H265_ENC}",       _gpu_enc("h265"))
            .replace("{GPU_AV1_ENC}",        _gpu_enc("av1"))
            .replace("{METER_NAME}",         meter_display_name())
            .replace("{RECOVERY_CHART_DATA}", json.dumps(recovery))
            .replace("{POSITION_PAPER_URL}",  POSITION_PAPER_URL)
            .replace("{GOS_URL}",             GOS_URL)
            .replace("{GOS_LOGO_URL}",        GOS_LOGO_URL)
            .replace("{GITHUB_REPO_URL}",     GITHUB_REPO_URL)
            .replace("{GITHUB_ISSUES_URL}",   GITHUB_ISSUES_URL)
            .replace("{ECO2MIX_URL}",         ECO2MIX_URL)
            .replace("{EMBER_URL}",           EMBER_URL)
            .replace("{CHARTJS_URL}",         CHARTJS_URL))
