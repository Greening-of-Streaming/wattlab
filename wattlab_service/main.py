"""
OWL app assembly — Phase 3 of the 2026-06 refactor (ARCHITECTURE.md).

main.py owns: the FastAPI app, middleware, the capability-gate exception
handler, startup (queue worker + telemetry pollers), the home page, the
live-telemetry JSON endpoints, /ui-config.js, and the queue endpoints/page.

Everything feature-shaped lives in a routes_*.py module (one flat module
per feature, each an APIRouter). Shared state is in runtime.py, shared
page chrome + serve-time UI copy in ui.py. Feature modules never import
main; benchmark.py and the tests reach a few orchestration callables
through the main-level aliases kept at the bottom of the assembly block.
"""
import asyncio
import json
import subprocess
from pathlib import Path

from fastapi import FastAPI, Form, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from dotenv import dotenv_values

import analytics
import audience
import carbon
import queue_control
import rag as rag_module
import runtime
import ui
from capabilities import (
    requires, can, CapabilityError,
    PUBLIC_PAGE, QUEUE_VIEW, LIVE_TELEMETRY, WORKING_NAV,
    SETTINGS_WRITE, BENCHMARK_RUN,
)
from power import meter_display_name
from video import LOCK_FILE

config = dotenv_values("/home/gos/wattlab/.env")
app = FastAPI()

# Phase 3: per-feature route modules. Each owns its routes + page template +
# run_*_job orchestration; main.py assembles them. They import shared state
# from runtime.py and chrome from ui.py — never from main.
import routes_audience
import routes_auth
import routes_benchmark
import routes_budget   # DEMO — transcode-budget calculator (CR-003 × CR-045 V2); illustrative data
import routes_demo
import routes_enhance
import routes_findings
import routes_image
import routes_llm
import routes_methodology
import routes_mockups   # TEMPORARY — Marketing Lab landing mockups, delete with the module
import routes_privacy
import routes_rag
import routes_results
import routes_settings
import routes_video

for _feature in (routes_audience, routes_auth, routes_benchmark, routes_budget, routes_demo,
                 routes_enhance, routes_findings, routes_image, routes_llm,
                 routes_methodology, routes_mockups, routes_privacy, routes_rag,
                 routes_results, routes_settings, routes_video):
    app.include_router(_feature.router)

# Serve bundled assets (owl logo, favicon, wl-*.js bundles) from
# wattlab_service/static/.
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Compatibility aliases ---------------------------------------------------
# benchmark.py drives its video/llm/rag steps through these main-level names
# (it stays byte-identical per the refactor's measurement-module rule), and
# several tests pin templates/helpers via the main module. Keep these pointing
# at the owning modules; they are aliases, not copies.
jobs = runtime.jobs                  # shared job dict — mutated in place, never reassigned
_power_cache = runtime.power_cache   # live telemetry cache (see runtime.py)
_ui_cfg         = ui._ui_cfg
_bake_durations = ui._bake_durations
_gpu_enc        = ui._gpu_enc
_gpu_runtime    = ui._gpu_runtime
run_job                    = routes_video.run_job
video_preview_cmd          = routes_video.video_preview_cmd
run_llm_compare_models_job = routes_llm.run_llm_compare_models_job
run_rag_compare_models_job = routes_rag.run_rag_compare_models_job
results_delete             = routes_results.results_delete
_DEMO_HTML        = routes_demo._DEMO_HTML
_METHODOLOGY_HTML = routes_methodology._METHODOLOGY_HTML
# Test-pinned external URLs (single source: ui.py)
from ui import (POSITION_PAPER_URL, GOS_URL, JOIN_GOS_URL, OWL_CONTACT_EMAIL,
                GOS_LOGO_URL, GITHUB_REPO_URL, GITHUB_ISSUES_URL, ECO2MIX_URL,
                ELECTRICITYMAPS_URL, EMBER_URL, CHARTJS_URL)
from ui import _PROGRESS_JS


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


@app.middleware("http")
async def _record_visit(request: Request, call_next):
    """Anonymous aggregate visit counting (analytics.py). Records a page view
    only for successful HTML GETs — the content-type gate naturally excludes
    /static, /live polling, JSON endpoints and redirects. No IP/cookie/UA is
    stored; only (day → tier → path) counts. Best-effort, never blocks a
    request. Kill switch: settings `analytics_enabled`."""
    response = await call_next(request)
    try:
        if (request.method == "GET" and response.status_code == 200
                and "text/html" in response.headers.get("content-type", "")):
            analytics.record_visit(request.url.path, audience.tier(request).name.lower())
    except Exception:
        pass
    return response


@app.exception_handler(CapabilityError)
async def _capability_error_handler(request: Request, exc: CapabilityError):
    """Central presentation layer for every capability 403. Browser
    navigations (Accept: text/html) get the styled gate page (routes_auth);
    fetch/API callers keep the JSON contract ({"detail":"requires <cap>"})
    the front-end JS already understands. The policy itself stays in
    capabilities.py — this only decides how the denial is *shown*."""
    if "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(status_code=exc.status_code,
                            content=routes_auth._gate_page_html(request, exc))
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# --- Queue ---
# Queue state, enqueue chokepoint, and worker live in queue_control.py.
# CR-001 (per-tier rate limits) and CR-001b (demo lock) plug into the
# enqueue chokepoint via the optional `request` parameter.


@app.on_event("startup")
async def startup():
    # Stale-lock recovery: every measurement runs inside this (single-worker)
    # process, so a lock file existing at startup can only be a leftover from
    # a kill mid-job (e.g. a service restart that hit systemd's stop timeout —
    # twice on 2026-06-10). Without this, self-test and lock-respecting paths
    # stay wedged until someone removes it by hand.
    LOCK_FILE.unlink(missing_ok=True)
    queue_control.start(jobs, LOCK_FILE)
    asyncio.create_task(runtime.power_poller())
    asyncio.create_task(runtime.sensors_poller())
    asyncio.create_task(carbon.poller(zones=[carbon.HOME_ZONE]))
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, rag_module.check_index)


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
        <div class="nav-video"><a href="/enhance-run">✦ ML Video Enhancement</a></div>
        <div class="nav-label">Beta · exploratory</div>
        <div class="nav-beta-note">
            Energy / quality / faithfulness tradeoffs we're investigating.<br>
            Less mature than video — signal can be below the P110 floor; interpret with care.
        </div>
        <div class="nav-ai">
            <a href="/image">Image generation <span class="beta-tag">BETA</span></a>
            <a href="/llm">LLM inference <span class="beta-tag">BETA</span></a>
            <a href="/rag">RAG energy test <span class="beta-tag">BETA</span></a>
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


# --- CR-064 — Lab queue controls (cancel-current / empty), on /queue-status.
# Cancel-current is workload-aware and HONEST about its limits: enhance runs
# die via `docker kill` on the per-job container name (the run concludes
# through its normal failed-transcode plumbing — lock/focus released in
# order); benchmark uses its existing cooperative flag (stops after the
# current step). Everything else is refused with a 409 — an asyncio cancel
# would orphan the encoder subprocess AND release the measurement lock,
# contaminating the next baseline, so we don't fake it.

@app.post("/queue/empty", dependencies=[Depends(requires(SETTINGS_WRITE))])
async def queue_empty():
    drained = queue_control.empty_pending()
    return {"ok": True, "drained": len(drained), "job_ids": drained}


@app.post("/queue/pause", dependencies=[Depends(requires(SETTINGS_WRITE))])
async def queue_pause(on: bool):
    """Lab toggle for the worker's PAUSE_FLAG (owner ask 2026-06-11 — the
    flag predates the UI; it was only settable by external tools). In-flight
    jobs always finish; pausing only stops NEW jobs being picked up."""
    return {"ok": True, "paused": queue_control.set_paused(on)}


@app.post("/queue/cancel-current", dependencies=[Depends(requires(SETTINGS_WRITE))])
async def queue_cancel_current():
    jid = queue_control.current_job_id
    if not jid:
        return JSONResponse({"ok": False, "error": "Nothing is running"},
                            status_code=409)
    j = jobs.get(jid) or {}
    jtype = j.get("type")
    if jtype == "enhance":
        j["cancel_requested"] = True   # covers the pre-container phases too
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(None, lambda: subprocess.run(
            ["docker", "kill", f"owl_enhance_{jid}"],
            capture_output=True, text=True, timeout=20))
        method = "docker_kill" if r.returncode == 0 else "flag"
        return {"ok": True, "job_id": jid, "method": method}
    if jtype == "benchmark":
        j["cancel_requested"] = True
        return {"ok": True, "job_id": jid, "method": "cooperative",
                "note": "stops after the current step"}
    return JSONResponse(
        {"ok": False, "error": f"'{jtype}' runs can't be cancelled mid-run — "
         "they're bounded by their own timeouts. (Killing the coroutine would "
         "orphan the running tool and contaminate the next baseline.)"},
        status_code=409)


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
        + '⏸ Queue paused — new jobs wait until it is re-enabled (the toggle'
        + ' below, or removing <code>/tmp/owl-paused</code>).'
        + ' Running job (if any) continues normally.'
        + '</div>'
        : '';
    if (window.CAN_CANCEL) {
        // Lab toggle for the same PAUSE_FLAG external tools use (one state).
        banner.innerHTML += '<button onclick="togglePause(' + (!q.paused) + ')" '
            + 'style="margin-bottom:1rem;background:transparent;'
            + 'color:' + (q.paused ? 'var(--accent)' : 'var(--warn)') + ';'
            + 'border:1px solid currentColor;padding:0.3rem 0.9rem;cursor:pointer;'
            + 'font-family:monospace;font-size:0.78rem">'
            + (q.paused ? '▶ Enable queue' : '⏸ Disable queue (running job finishes)')
            + '</button>';
    }
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
        if (window.CAN_CANCEL) {
            // CR-064 — workload-aware: enhance = docker kill, benchmark =
            // cooperative (after current step); others are refused server-side
            // with the reason, surfaced verbatim below.
            const note = q.running.type === 'benchmark' ? 'takes effect after the current step'
                       : q.running.type === 'enhance' ? 'kills the partner container; run lands as cancelled'
                       : 'this workload may not be cancellable — the server will say';
            runHtml += '<button onclick="cancelCurrent()" ' +
                'style="margin-top:0.5rem;background:transparent;color:var(--err);' +
                'border:1px solid var(--err);padding:0.3rem 0.9rem;cursor:pointer;' +
                'font-family:monospace;font-size:0.78rem">■ Cancel current run</button>' +
                '<div style="color:var(--text-5);font-size:0.7rem;margin-top:0.3rem">' + note + '</div>' +
                '<div id="cancel-note" style="color:var(--warn);font-size:0.74rem;margin-top:0.3rem"></div>';
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
    if (window.CAN_CANCEL && (q.pending || []).length) {
        html += '<button onclick="emptyQueue()" ' +
            'style="margin-top:0.5rem;background:transparent;color:var(--warn);' +
            'border:1px solid var(--warn);padding:0.3rem 0.9rem;cursor:pointer;' +
            'font-family:monospace;font-size:0.78rem">⌫ Empty queue (' + q.pending.length + ' waiting)</button>';
    }
    el.innerHTML = html;
}
async function cancelCurrent() {
    if (!confirm('Cancel the currently running job?')) return;
    try {
        const r = await fetch('/queue/cancel-current', {method:'POST'});
        const d = await r.json();
        if (!d.ok) {
            const n = document.getElementById('cancel-note');
            if (n) n.textContent = d.error || 'Cancel refused';
            return;
        }
    } catch(e) {}
    load();
}
async function emptyQueue() {
    if (!confirm('Remove ALL waiting jobs from the queue? The running job is not affected.')) return;
    try { await fetch('/queue/empty', {method:'POST'}); } catch(e) {}
    load();
}
async function togglePause(on) {
    try { await fetch('/queue/pause?on=' + on, {method:'POST'}); } catch(e) {}
    load();
}
load();
</script>
""")
