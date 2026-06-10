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

# Phase 2 (2026-06-10): shared page chrome (design tokens, header/auth chip,
# footer, lock badges, static-bundle script tags) lives in ui.py — new/converted
# pages render through ui.render_page(); the rest import the pieces by name so
# their templates are unchanged until each converts.
import runtime
import ui
from ui import (_AUTH_CHIP_STYLES, _auth_chip_html, _HEADER_STYLES, _header_html,
                _tier_indicator_html, _LOCK_STYLES, _lock_badge_html, _lock_class,
                _disabled_attr, _LOGO, _BACK, _QUEUE_BADGE, _WL_ASSET_V, _UI_CFG_TAG,
                _LIVE_JS, _CARBON_JS, _PROGRESS_JS, _RESULT_JS, _BENCH_HYDRATE_JS,
                _BETA_CHIP, _METHODOLOGY_LINK, _ISSUES_LINK, _BASE_STYLES, _FOOTER,
                _CONF_HELP_WIDGET,
                POSITION_PAPER_URL, GOS_URL, JOIN_GOS_URL, OWL_CONTACT_EMAIL,
                GOS_LOGO_URL, GITHUB_REPO_URL, GITHUB_ISSUES_URL, ECO2MIX_URL,
                ELECTRICITYMAPS_URL, EMBER_URL, CHARTJS_URL)

config = dotenv_values("/home/gos/wattlab/.env")
app = FastAPI()

# Phase 3: per-feature route modules. Each owns its routes + page template +
# run_*_job orchestration; main.py assembles them. They import shared state
# from runtime.py and chrome from ui.py — never from main.
import routes_enhance
import routes_benchmark
import routes_findings
import routes_image
import routes_llm
import routes_video
import routes_rag
from routes_findings import _findings_catalog_rows_html, _FINDINGS_CATALOG_CSS
app.include_router(routes_enhance.router)
app.include_router(routes_benchmark.router)
app.include_router(routes_findings.router)
app.include_router(routes_image.router)
app.include_router(routes_llm.router)
app.include_router(routes_video.router)
app.include_router(routes_rag.router)
# benchmark.py drives compare jobs through these main-level names — keep them
# pointing at the feature modules (measurement modules stay byte-identical).
run_rag_compare_models_job = routes_rag.run_rag_compare_models_job
run_llm_compare_models_job = routes_llm.run_llm_compare_models_job
run_job = routes_video.run_job
video_preview_cmd = routes_video.video_preview_cmd

# Serve bundled assets (owl logo, favicon) from wattlab_service/static/.
app.mount("/static", StaticFiles(directory="static"), name="static")



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


jobs = runtime.jobs                  # shared job dict — mutated in place, never reassigned
_power_cache = runtime.power_cache   # live telemetry cache (see runtime.py)
power_poller = runtime.power_poller
sensors_poller = runtime.sensors_poller

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
_model_date_line = ui._model_date_line


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

# CR-037 — tether the AI pages to streaming. Each AI page gets a one-line
# streaming-anchored framing band plus a shared "how to read AI energy in a
# streaming context" expander drawn from the Language Lab AI position paper
# (Jan 2026). Reframing only — no new measurement. Centralised here so the five
# framing principles read identically on /llm, /image and /rag and can't drift
# from the paper (CR-037 watch-out). Built with plain `+` concatenation, not an
# f-string, so the URL splice can't be mistaken for an undefined name.
_ai_streaming_band = ui._ai_streaming_band
_ai_intro          = ui._ai_intro
_ui_cfg            = ui._ui_cfg
_bake_durations    = ui._bake_durations


@app.get("/ui-config.js", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def ui_config_js():
    """window.WL_CFG for the static JS bundles — resolved per request so
    settings/meter changes reach the browser without a service restart."""
    body = "window.WL_CFG = " + json.dumps(_ui_cfg()) + ";"
    # max-age=5 (not no-store): pages include this tag up to twice (_PROGRESS_JS
    # + _CARBON_JS) and poll loops re-render around it — a short private cache
    # collapses those into one fetch per page-load window, which matters under
    # nginx's per-IP connection cap (S41: first-ever 429 on the homepage).
    # 5 s staleness on settings copy is fine; the old failure mode was a full
    # service restart.
    return Response(body, media_type="application/javascript",
                    headers={"Cache-Control": "private, max-age=5"})

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
    return ui.render_page(request, "GoS", back=False, styles=f"""
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
""", body=f"""
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
""")

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


# CR-019 — every job-status response carries the live wall-power reading
# alongside the worker-state fields. The shared `wlRenderProgress` widget
# consumes `data.watts` to drive the big 2.5rem live readout, which is
# the proof-of-reality moment for the visitor on /demo. Injected once
# here so all four job-status endpoints stay symmetric.
_job_status = runtime.job_status


@app.get("/queue", dependencies=[Depends(requires(QUEUE_VIEW))])
async def queue_status_endpoint():
    return queue_control.snapshot()


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
    return ui.render_page(request, "Settings", head=f"    {chart_js}\n", styles=f"""
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
""", body=f"""
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
    {toggle_field("cooldown_show_wait_detail", s.get('cooldown_show_wait_detail', True),
                  "Show the live idle-wait readout (\u23f3 waited \u00b7 current W \u00b7 target) in the progress "
                  "widget on every page during cooldowns. Display only \u2014 cooldown behaviour is unchanged.")}

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
        const bool_fields = ['cooldown_wait_for_idle','cooldown_show_wait_detail'];
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
""")


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

_DEMO_STYLES = f"""
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
"""

_DEMO_HTML = f"""
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
        cooldownData: data,
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
        cooldownData: data,
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
        cooldownData: data,
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
      cooldownData: j,
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
"""

@app.get("/queue-status", response_class=HTMLResponse, dependencies=[Depends(requires(QUEUE_VIEW))])
async def queue_page(request: Request):
    # Only Lab (BENCHMARK_RUN) may cancel — gate the button so anonymous
    # viewers (QUEUE_VIEW is Anonymous-allowed) don't see a control they can't use.
    can_cancel = "true" if can(audience.tier(request), BENCHMARK_RUN) else "false"
    return ui.render_page(request, "Queue", head=(
        '    <meta http-equiv="refresh" content="4">\n'
        f'    <script>window.CAN_CANCEL={can_cancel};</script>\n'
    ), styles="""
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
""", tail=_PROGRESS_JS, body="""
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
""")


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
    return (ui.render_page(request, "Guided Tour · Greening of Streaming",
                           styles=_DEMO_STYLES, body=_DEMO_HTML)
            .replace("{BASELINE_POLLS}",     str(s.get("baseline_polls",     "—")))
            .replace("{VIDEO_COOLDOWN_S}",   str(s.get("video_cooldown_s",   "—")))
            .replace("{CONF_GREEN_X}",       str(s.get("variance_green_x",   "—")))
            .replace("{CONF_YELLOW_X}",      str(s.get("variance_yellow_x",  "—")))
            .replace("{CONF_GREEN_POLLS}",   str(s.get("conf_green_polls",   "—")))
            .replace("{CONF_YELLOW_POLLS}",  str(s.get("conf_yellow_polls",  "—")))
            .replace("{BETA_CHIP}",          _BETA_CHIP)
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


_gpu_display_name   = ui._gpu_display_name
_gpu_hw_row         = ui._gpu_hw_row
_gpu_video_encoders = ui._gpu_video_encoders
_gpu_enc            = ui._gpu_enc
_gpu_runtime        = ui._gpu_runtime


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
