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
