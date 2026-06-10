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
import routes_settings
import routes_results
import routes_demo
import routes_methodology
import routes_rag
from routes_findings import _findings_catalog_rows_html, _FINDINGS_CATALOG_CSS
app.include_router(routes_enhance.router)
app.include_router(routes_benchmark.router)
app.include_router(routes_findings.router)
app.include_router(routes_image.router)
app.include_router(routes_llm.router)
app.include_router(routes_video.router)
app.include_router(routes_settings.router)
app.include_router(routes_results.router)
app.include_router(routes_demo.router)
app.include_router(routes_methodology.router)
# tests pin the methodology template + gpu helpers through main
_METHODOLOGY_HTML = routes_methodology._METHODOLOGY_HTML
_gpu_enc     = ui._gpu_enc
_gpu_runtime = ui._gpu_runtime
# tests pin the demo template through main
_DEMO_HTML = routes_demo._DEMO_HTML
# tests call this handler directly (test_delete_result)
results_delete = routes_results.results_delete
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
_ui_cfg         = ui._ui_cfg
_bake_durations = ui._bake_durations


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


@app.get("/queue", dependencies=[Depends(requires(QUEUE_VIEW))])
async def queue_status_endpoint():
    return queue_control.snapshot()


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
