"""
/decode — client-decode rig power console (Stage 1 of the decode-on-device
feature; the recipe-run panel is Stage 2 and lands behind the same page).

Lab-only end to end (RIG_CONTROL, like /settings): every button here switches
a real mains relay. Tiles: optional Shelly master, the shared 4K monitor
(off needs a JS confirm — it may be in use as a Mac screen extension), and the
three playback devices with the red/orange/green state machine from rig.py.

Page JS polls /decode/status.json every 2.5 s; layout is flex-wrap so the
tiles stack single-column on a phone. All rig state/IO lives in rig.py —
this module is routes + HTML only.
"""
import datetime
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

import audience
import decode_run
import persist
import queue_control
import rig
import ui
import uploads
from capabilities import (requires, can, LIVE_TELEMETRY, PUBLIC_PAGE,
                          RESULTS_DOWNLOAD, RIG_CONTROL)
from runtime import job_status as _job_status

router = APIRouter()

_UPLOAD_EXTS = {".mp4", ".mkv", ".mov", ".m4v", ".webm"}

# Same shared upload store as /enhance-run and /prepare-rem: retention-
# prefixed names, free-space eviction, periodic sweep. The dir sits inside
# the :8123-served streams tree so the GTV can play uploads by URL.
uploads.register_dir(decode_run.STREAMS / decode_run.UPLOADS_SUBDIR)


def _refuse(e: rig.RigError) -> JSONResponse:
    return JSONResponse({"error": e.reason}, status_code=e.status)


# Page + read surfaces are PUBLIC (guided-tour material — the rig, its live
# state and past results are the story); every switch/run/upload endpoint
# stays RIG_CONTROL (Lab). Same split as /prepare-rem's view-vs-act.
@router.get("/decode", response_class=HTMLResponse,
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def decode_page(request: Request):
    import json as _json
    is_lab = can(audience.tier(request), RIG_CONTROL)
    if is_lab:
        rig.touch_activity("/decode visit")   # idle auto-off: operator is here
    options = "".join(
        f'<option value="{k}">{r["label"]}</option>'
        for k, r in decode_run.TEMPLATES.items())
    tpl_devices = _json.dumps({k: r.get("devices")
                               for k, r in decode_run.TEMPLATES.items()})
    banner = ("" if is_lab else
              '<div class="rig-note" style="border:1px solid var(--border-3);'
              'border-radius:4px;padding:0.5rem 0.8rem;margin-bottom:1rem">'
              '🔒 <b>Read-only view.</b> Switching devices and running '
              'measurements needs <b>Lab mode</b> (LAN / SSH tunnel) — '
              'browsing live state and past runs is open to everyone.</div>')
    body = (_BODY.replace("{RECIPE_OPTIONS}", options)
                 .replace("{LAB_BANNER}", banner))
    return ui.render_page(request, "Decode Rig", styles=_STYLES, body=body,
                          tail=(_JS.replace("{IS_LAB}",
                                            "true" if is_lab else "false")
                                   .replace("{TPL_DEVICES}", tpl_devices)))


@router.get("/decode/runs.json",
            dependencies=[Depends(requires(RESULTS_DOWNLOAD))])
async def decode_recent_runs(limit: int = 8):
    """Compact recent-runs list for the page (and the guided tour): headline
    ΔW per device row, mode, template — newest first."""
    import json as _json
    out = []
    res_dir = persist.RESULTS_DIR / "decode"
    if res_dir.exists():
        files = sorted(res_dir.glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files[:max(1, min(int(limit), 25))]:
            try:
                d = _json.loads(f.read_text())
            except Exception:
                continue
            rows = [{"device": r.get("device"), "run": r.get("run"),
                     "delta_w": r.get("delta_w"),
                     "flag": (r.get("confidence") or {}).get("flag"),
                     "screen_w": r.get("context_task_w")}
                    for r in (d.get("runs") or [])
                    if isinstance(r, dict) and "delta_w" in r]
            out.append({"job_id": d.get("job_id"),
                        "saved_at": d.get("saved_at"),
                        "mode": d.get("mode"),
                        "label": d.get("template_label") or d.get("recipe")
                                 or d.get("mode"),
                        "protocol_version":
                            (d.get("protocol") or {}).get("protocol_version"),
                        "rows": rows})
    return {"runs": out}


@router.post("/decode/run", dependencies=[Depends(requires(RIG_CONTROL))])
async def decode_run_start(request: Request, payload: dict):
    p = payload or {}
    tpl_key = p.get("template")
    mode = p.get("mode", "headless")
    devices = p.get("devices") or []
    calibrate = bool(p.get("calibrate", True))
    upload_name = None
    if tpl_key == "upload":
        upload_name = p.get("upload_name") or ""
        if uploads.resolve(decode_run.STREAMS / decode_run.UPLOADS_SUBDIR,
                           upload_name) is None:
            return JSONResponse({"error": "upload a clip first"},
                                status_code=400)
    elif tpl_key not in decode_run.TEMPLATES:
        return JSONResponse({"error": f"unknown template {tpl_key!r}"},
                            status_code=400)
    if mode not in decode_run.MODES:
        return JSONResponse({"error": f"unknown mode {mode!r}"}, status_code=400)
    bad = [d for d in devices if d not in rig.RIG["devices"]]
    if bad or not devices:
        return JSONResponse({"error": f"bad device selection {devices!r}"},
                            status_code=400)
    allowed = (decode_run.TEMPLATES.get(tpl_key) or {}).get("devices")
    if allowed:
        wrong = [d for d in devices if d not in allowed]
        if wrong:
            return JSONResponse(
                {"error": f"this template only runs on: "
                          + ", ".join(rig.RIG['devices'][d]['label']
                                      for d in allowed)}, status_code=400)
    if mode == "screen" and len(devices) != 1:
        return JSONResponse({"error": "screen mode is exclusive — pick "
                                      "exactly one device"}, status_code=400)
    cadence_s = p.get("cadence_s")
    if cadence_s is not None:
        try:
            cadence_s = float(cadence_s)
        except (TypeError, ValueError):
            return JSONResponse({"error": "bad cadence"}, status_code=400)
        if not 1.0 <= cadence_s <= 10.0:
            return JSONResponse({"error": "cadence must be 1–10 s"},
                                status_code=400)
    # Tester-set duration (loop recipes): the whole endpoint is RIG_CONTROL
    # (Lab-only), so allow the full 30 s–1 h range.
    window_s = p.get("window_s")
    if window_s is not None:
        try:
            window_s = int(window_s)
        except (TypeError, ValueError):
            return JSONResponse({"error": "bad window_s"}, status_code=400)
        if not 30 <= window_s <= 3600:
            return JSONResponse({"error": "window_s must be 30–3600 s"},
                                status_code=400)
    try:
        tpl = decode_run.resolve_template(tpl_key, upload_name)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    job_id = str(uuid.uuid4())[:8]
    label = (f"decode {mode} — {tpl['label']} on "
             + ", ".join(rig.RIG['devices'][d]['label'] for d in devices))

    async def coro(job_id=job_id):
        await decode_run.run_decode_job(job_id, tpl_key, devices, mode,
                                        calibrate, upload_name, cadence_s,
                                        window_s)

    rig.touch_activity(f"decode job {job_id} queued")
    position = queue_control.enqueue(job_id, "decode", label, coro,
                                     request=request, page="/decode")
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."},
                            status_code=429)
    return {"job_id": job_id, "queue_position": position}


@router.get("/decode/job/{job_id}",
            dependencies=[Depends(requires(RESULTS_DOWNLOAD))])
async def decode_job_status(job_id: str):
    s = _job_status(job_id)
    now = time.monotonic()
    devs = s.get("devices")
    if isinstance(devs, dict):
        out = {}
        for name, sub in devs.items():
            sub = dict(sub)
            if sub.get("phase_started"):
                sub["phase_elapsed_s"] = round(now - sub["phase_started"], 1)
            sub.pop("phase_started", None)
            out[name] = sub
        s = {**s, "devices": out}
    return s


@router.get("/decode/status.json",
            dependencies=[Depends(requires(LIVE_TELEMETRY))])
async def decode_status():
    return rig.status_payload()


@router.post("/decode/device/{name}/power",
             dependencies=[Depends(requires(RIG_CONTROL))])
async def decode_device_power(name: str, payload: dict):
    action = (payload or {}).get("action")
    try:
        if action == "on":
            await rig.device_on(name)
        elif action == "off":
            await rig.device_off(name)
        elif action == "cycle":
            await rig.device_cycle(name)
        else:
            return JSONResponse({"error": f"unknown action {action!r}"},
                                status_code=400)
    except rig.RigError as e:
        return _refuse(e)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    return {"ok": True}


@router.post("/decode/upload", dependencies=[Depends(requires(RIG_CONTROL))])
async def decode_upload(request: Request, file: UploadFile = File(...),
                        retention: str = Form(uploads.DEFAULT_RETENTION)):
    orig = Path(file.filename or "clip").name
    ext = Path(orig).suffix.lower()
    if ext not in _UPLOAD_EXTS:
        return JSONResponse(
            {"error": f"Unsupported container '{ext or '(none)'}' — use one "
                      f"of: " + ", ".join(sorted(_UPLOAD_EXTS))},
            status_code=400)
    blob = await file.read()
    saved = uploads.save(blob, orig, retention=retention, feature="decode",
                         dest_dir=decode_run.STREAMS / decode_run.UPLOADS_SUBDIR)
    return {"name": saved["name"], "size_mb": saved["size_mb"],
            "retention": saved["retention"]}


@router.get("/decode/result/{job_id}/lem.csv",
            dependencies=[Depends(requires(RESULTS_DOWNLOAD))])
async def decode_result_lem_csv(job_id: str):
    """Raw run data as a LEM-style combined CSV: timestamp,alias,power_w —
    the exact shape LEM writes (and REM ingests). Aliases are the rig device
    names plus 'monitor' for the screen's context meter; baseline and window
    samples are both included, chronologically. Needs per-sample timestamps
    (runs from 2026-07-30 on)."""
    data = persist.load_result("decode", job_id)
    if not data:
        return PlainTextResponse("unknown decode result", status_code=404)
    lines = []

    def _iso(t):
        return datetime.datetime.fromtimestamp(
            t, tz=datetime.timezone.utc).isoformat(timespec="milliseconds")

    def _emit(alias, ts, ws):
        for t, w in zip(ts or [], ws or []):
            lines.append((t, f"{_iso(t)},{alias},{w}"))

    for name, section in (data.get("devices") or {}).items():
        for row in section.get("rows", []):
            _emit(name, row.get("raw_baseline_t"), row.get("raw_baseline_w"))
            _emit(name, row.get("raw_task_t"), row.get("raw_task_w"))
            _emit("monitor", row.get("raw_context_baseline_t"),
                  row.get("raw_context_baseline_w"))
            _emit("monitor", row.get("raw_context_t"), row.get("raw_context_w"))
    if not lines:
        return PlainTextResponse(
            "this run has no per-sample timestamps (pre-2026-07-30 protocol) "
            "— re-run to get a LEM-style export", status_code=404)
    lines.sort(key=lambda x: x[0])
    csv = "timestamp,alias,power_w\n" + "\n".join(l for _, l in lines) + "\n"
    return PlainTextResponse(csv, media_type="text/csv", headers={
        "Content-Disposition":
            f'attachment; filename="decode_{job_id}_lem.csv"'})


@router.post("/decode/device/{name}/screen",
             dependencies=[Depends(requires(RIG_CONTROL))])
async def decode_claim_screen(name: str):
    try:
        await rig.claim_screen(name)
    except rig.RigError as e:
        return _refuse(e)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    return {"ok": True}


@router.post("/decode/device/{name}/adb-repair",
             dependencies=[Depends(requires(RIG_CONTROL))])
async def decode_adb_repair(name: str):
    """Unauthorised adb box: claim the screen + ONE reconnect so the "Allow
    USB debugging?" prompt is visible; returns the host fingerprint to match."""
    try:
        return {"ok": True, **(await rig.adb_repair(name))}
    except rig.RigError as e:
        return _refuse(e)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@router.post("/decode/monitor/power",
             dependencies=[Depends(requires(RIG_CONTROL))])
async def decode_monitor_power(payload: dict):
    try:
        await rig.monitor_power(bool((payload or {}).get("on")))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    return {"ok": True}


@router.post("/decode/master/power",
             dependencies=[Depends(requires(RIG_CONTROL))])
async def decode_master_power(payload: dict):
    try:
        await rig.master_power(bool((payload or {}).get("on")))
    except rig.RigError as e:
        return _refuse(e)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    return {"ok": True}


# --- Page --------------------------------------------------------------------

_STYLES = """
body { font-family: monospace; background: var(--bg); color: var(--text);
       margin: 0; padding: 1.2rem; }
.rig-wrap { max-width: 62rem; margin: 0 auto; }
.rig-wrap h2 { color: var(--accent); letter-spacing: 0.04em; }
/* ── Bench schematic ─────────────────────────────────────────────── */
.rig-bench { position:relative; display:grid; margin-bottom:1rem;
             grid-template-columns:6.5rem minmax(15rem,22rem) 1fr;
             grid-template-areas: "rail devices screen" "strip strip screen";
             gap:0.9rem 2.6rem; align-items:start; }
#rig-wires { position:absolute; inset:0; width:100%; height:100%;
             pointer-events:none; z-index:0; }
.rig-rail { grid-area:rail; position:relative; z-index:1;
            padding-top:0.2rem; }
.rig-gos1 { border:1px solid var(--border-3); border-radius:4px;
            background:var(--panel); padding:0.4rem 0.55rem;
            font-size:0.8rem; color:var(--text-2); display:inline-block; }
.rig-gos1 span { color:var(--text-4); font-size:0.68rem; }
.rail-conn { font-size:0.68rem; color:var(--text-4);
             font-family:monospace; }
.rig-screenzone { grid-area:screen; position:relative; z-index:1;
                  align-self:center; }
.rig-screen { max-width:19rem; }
.rig-shape { color:var(--text-3); line-height:0; margin-bottom:0.35rem; }
.rig-shape svg { display:block; }
.rig-shape .scr-fill { fill:transparent; transition:fill 0.6s; }
.rig-shape.lit .scr-fill { fill:var(--accent-soft); }
.rig-chips { display:flex; gap:0.4rem; flex-wrap:wrap; margin:0.3rem 0; }
.rig-devshape { float:right; color:var(--text-4); line-height:0;
                margin:0.1rem 0 0.3rem 0.6rem; }
.rig-silicon { color:var(--text-4); font-size:0.7rem;
               font-family:monospace; margin-bottom:0.2rem; }
.rig-stripbar { grid-area:strip; position:relative; z-index:1;
                border:1px dashed var(--border-3); border-radius:6px;
                background:var(--panel-2);
                padding:0.45rem 0.9rem; display:flex; flex-wrap:wrap;
                gap:0.8rem; align-items:center; font-size:0.8rem;
                color:var(--text-3); }
@keyframes wireflow { to { stroke-dashoffset:-14; } }
.wire { stroke:var(--border-3); stroke-width:1.5; fill:none; }
.wire.owner { stroke:var(--accent); stroke-width:2.5;
              stroke-dasharray:8 6; animation:wireflow 1.2s linear infinite; }
.wire.power { stroke:var(--text-5); stroke-width:1; stroke-dasharray:2 4; }
@media (max-width:700px) {
  .rig-bench { display:flex; flex-direction:column; gap:0.9rem; }
  #rig-wires, .rig-rail { display:none; }
  .rig-screen { max-width:none; }
}
.rig-agg { font-size:0.85rem; color:var(--text-3); margin:0.3rem 0 0.9rem; }
.rig-tiles { grid-area:devices; display:flex; flex-direction:column;
             gap:0.9rem; position:relative; z-index:1; }
.rig-tile { border:1px solid var(--border-3); border-radius:6px;
            padding:0.8rem 0.9rem; min-width:15rem;
            background:var(--panel); font-size:0.9rem; }
.rig-tile h3 { margin:0 0 0.45rem; font-size:0.95rem; display:flex;
               align-items:center; gap:0.5rem; color:var(--text); }
.rig-dot { display:inline-block; width:0.75rem; height:0.75rem;
           border-radius:50%; background:var(--border-3); flex:none; }
.rig-dot.red { background:var(--err); }
.rig-dot.orange { background:var(--warn); animation:rigpulse 1.4s infinite; }
.rig-dot.green { background:var(--accent); }
.rig-dot.grey { background:var(--text-5); }
@keyframes rigpulse { 50% { opacity:0.35; } }
.rig-w { font-size:1.25rem; font-weight:600; margin:0.15rem 0;
         color:var(--text); }
.rig-detail { color:var(--text-3); font-size:0.78rem; min-height:1.1rem; }
.rig-bar { height:0.45rem; background:var(--panel-2); border-radius:3px;
           border:1px solid var(--border-2); overflow:hidden; margin:0.4rem 0; }
.rig-bar > div { height:100%; background:var(--warn); transition:width 1s linear; }
.rig-btn { background:none; border:1px solid var(--border-3);
           color:var(--text-2); font-family:inherit; font-size:0.82rem;
           padding:0.35rem 0.9rem; border-radius:4px; cursor:pointer;
           margin-top:0.5rem; }
.rig-btn:hover { border-color:var(--accent); color:var(--accent); }
.rig-btn:disabled { opacity:0.35; cursor:default; }
.rig-btn.warn { border-color:var(--warn); color:var(--warn); }
.rig-note { font-size:0.78rem; color:var(--text-3); margin-top:1.1rem;
            line-height:1.5; }
.rig-badge { font-size:0.68rem; border:1px solid var(--border-3);
             border-radius:3px; padding:0 0.35rem; color:var(--text-3); }
.rig-badge.blink { animation:rigpulse 0.8s infinite; color:var(--warn);
                   border-color:var(--warn); }
.rig-err { color:var(--err); font-size:0.8rem; min-height:1.1rem;
           margin:0.4rem 0; }
.rig-run { border:1px solid var(--border-3); border-radius:6px;
           padding:0.8rem 0.9rem; margin-top:1rem; background:var(--panel); }
.rig-run h3 { margin:0 0 0.5rem; font-size:0.95rem; color:var(--text); }
.rig-runrow { display:flex; flex-wrap:wrap; gap:0.6rem; align-items:center; }
.rig-runrow select { background:var(--panel-2); color:var(--text);
                     border:1px solid var(--border-3); border-radius:4px;
                     font-family:inherit; font-size:0.85rem;
                     padding:0.35rem 0.5rem; max-width:100%; }
.rig-runrow .rig-btn { margin-top:0; }
.rig-stage { display:flex; align-items:center; gap:0.55rem;
             font-size:0.82rem; margin-bottom:0.25rem; }
.rig-progress { display:flex; flex-wrap:wrap; gap:0.9rem; }
.rig-progress .rig-tile { flex:1 1 13rem; }
.rig-rows { display:block; overflow-x:auto; max-width:100%; }
.rig-rows td { padding:0.15rem 0.8rem 0.15rem 0; font-size:0.84rem;
               color:var(--text-2); white-space:nowrap; }
"""

_BODY = """
<div class="rig-wrap">
  <h2>Decode rig <span class="rig-badge">Lab</span></h2>
  {LAB_BANNER}
  <div class="rig-agg" id="rig-agg">connecting…</div>
  <div class="rig-err" id="rig-err"></div>

  <div class="rig-bench" id="rig-bench">
    <svg id="rig-wires" aria-hidden="true"></svg>
    <div class="rig-rail" id="rig-rail">
      <div class="rig-gos1">GoS1<br><span>(control)</span></div>
      <div id="rail-links"></div>
    </div>
    <div class="rig-tiles" id="rig-tiles"></div>
    <div class="rig-screenzone">
      <div class="rig-tile rig-screen" id="tile-monitor">
        <div class="rig-shape" id="screen-shape"></div>
        <h3><span class="rig-dot" id="dot-monitor"></span>Shared screen</h3>
        <div class="rig-detail" id="screen-panel"></div>
        <div class="rig-w" id="w-monitor">—</div>
        <div class="rig-detail" id="d-monitor"></div>
        <div class="rig-chips"><span class="rig-badge" id="screen-plug">🔌 Lab-E</span>
          <span class="rig-badge">not on strip</span></div>
        <button class="rig-btn" id="btn-monitor" onclick="monitorToggle()">…</button>
      </div>
    </div>
    <div class="rig-stripbar" id="rig-stripbar">
      <span>⏚ power strip</span>
      <span class="rig-detail" id="strip-plugs"></span>
      <span class="rig-detail" id="strip-meter" style="display:none"></span>
      <button class="rig-btn" id="btn-master" style="display:none;margin:0"
              onclick="masterToggle()">…</button>
    </div>
  </div>

  <div class="rig-run">
    <h3>Run</h3>
    <div class="rig-runrow">
      <label><input type="radio" name="mode" value="headless" checked
             onchange="modeChanged()"> headless — parallel</label>
      <label><input type="radio" name="mode" value="screen"
             onchange="modeChanged()"> on screen — exclusive</label>
    </div>
    <div class="rig-runrow" id="dev-picks" style="margin-top:0.4rem">
      <!-- device checkboxes built dynamically from live status (buildDevPicks) -->
      <span id="dev-checkboxes" class="rig-detail">loading devices…</span>
      <label id="cal-wrap" style="display:none">
        <input type="checkbox" id="calibrate" checked>
        marker head (5 s black·white·black in-clip)</label>
      <label style="display:flex;align-items:center;gap:0.4rem">
        poll <input type="range" id="cadence" min="1" max="10" step="1"
                    value="1" style="width:7rem"
                    oninput="document.getElementById('cadence-v').textContent=this.value+' s'">
        <span id="cadence-v" class="rig-detail">1 s</span></label>
      <label id="dur-wrap" style="display:none;align-items:center;gap:0.4rem">
        duration <select id="duration">
          <option value="30">30 s</option>
          <option value="60">1 min</option>
          <option value="150">2.5 min</option>
          <option value="300" selected>5 min</option>
          <option value="600">10 min</option>
          <option value="1200">20 min</option>
          <option value="1800">30 min</option>
          <option value="3540">~60 min</option>
        </select></label>
    </div>
    <div class="rig-runrow" style="margin-top:0.4rem">
      <select id="recipe" onchange="tplChanged()">{RECIPE_OPTIONS}</select>
      <button class="rig-btn" id="btn-run" onclick="runRecipe()">Run</button>
    </div>
    <div class="rig-runrow" style="margin-top:0.4rem;font-size:0.8rem">
      <input type="file" id="up-file" accept=".mp4,.mkv,.mov,.m4v,.webm"
             style="font-size:0.75rem;max-width:16rem">
      <label><input type="radio" name="up-ret" value="evict" checked> evict</label>
      <label><input type="radio" name="up-ret" value="proc"> keep-until-processed</label>
      <label><input type="radio" name="up-ret" value="keep"> keep</label>
      <button class="rig-btn" id="btn-upload" onclick="uploadClip()">Upload</button>
      <span class="rig-detail" id="up-status"></span>
    </div>
    <div class="rig-detail" style="margin-top:0.3rem" id="run-hint">Headless:
      selected devices measure in parallel (each on its own meter); GTV rows
      are indicative (Android always renders). Screen mode claims the monitor
      and meters it as context.</div>
    <div id="run-status" style="margin-top:0.7rem"></div>
  </div>

  <div class="rig-run" style="margin-top:1rem">
    <h3>Recent runs</h3>
    <div id="recent-runs" class="rig-note" style="margin-top:0.2rem">loading…</div>
  </div>

  <div class="rig-run" style="margin-top:1rem">
    <h3>Open items <span class="rig-badge">2026-07-30 (overnight)</span></h3>
    <div class="rig-note" style="margin-top:0.2rem">
    <b>Landed overnight:</b> clip upload (shared retention rules) · decode
    parameters in /settings (Decode rig section) · shared stable-idle guard
    (same idle_wait loop as GoS1's pre-job guard; rows stamp protocol v3) ·
    per-sample timestamps · automated marker segmentation (shown under
    results) · ⬇ LEM-style CSV export per run · screen-row skip absorbs the
    1080p re-sync · harness versioned in wattlab/decode_bench/.<br>
    <b>Still open:</b><br>
    · Pi 400 headless ΔW vs July (+1.57 vs +1.25 W) — deliberate n≥2 recheck<br>
    · LG C2 OLED integration (CEC input claiming + webOS control; meter on
      Lab-C once the router moves to a dumb socket)<br>
    · uploaded clips: markers need h264/hevc/av1 sources (NVENC-matched);
      other codecs run un-marked<br>
    <b>Known quirks:</b> cold-panel first claim may need a second claim ·
    claim takes 10–20 s by design · deploys never run while the queue is busy ·
    marker-row headline ΔW includes the 15 s head (quote segmented values).
    </div>
  </div>

  <div class="rig-note">
    Boxes are <b>off by default</b>. The screen auto-switches to the single
    powered device — run one box at a time for display work. “Off” is always a
    graceful shutdown (SSH/ADB) before the relay cut. The monitor has its own
    wall socket — cutting the strip never darkens the screen. Boot
    expectations: Pi 5 ≈ 29 s; Pi 400 and Google TV get measured on first use.
  </div>
  <div class="rig-note">
    <b>Connectivity (transparency).</b> Every device is on Ethernet via the bench
    switch except the <b>Fire TV Stick, which is Wi-Fi only</b> (no Ethernet port).
    Link quality is not the concern — the Bbox Wi-Fi 7 access point sits a few metres
    away, likely better than the bench Ethernet — but the stick powers its own radio,
    so its device-total W includes a Wi-Fi share the Ethernet boxes don't carry. That
    share is not separately measurable on this rig; treat it as a stated caveat on any
    cross-device comparison, not a correction we apply.
  </div>
</div>
"""

_JS = """
<script>
var IS_LAB = {IS_LAB};
var TPL_DEVICES = {TPL_DEVICES};   // template → allowed device list (or null)
var RIG_LAST = null;

function tplChanged() {
  var tpl = document.getElementById('recipe').value;
  // Loop recipes carry a tester-set duration; other templates have a fixed
  // window baked in, so the picker only shows for loop_* recipes.
  document.getElementById('dur-wrap').style.display =
    tpl.indexOf('loop_') === 0 ? 'flex' : 'none';
  var allowed = TPL_DEVICES[document.getElementById('recipe').value] || null;
  DEVICE_NAMES.forEach(function(d){
    var cb = document.getElementById('dev-' + d);
    if (allowed) {
      var ok = allowed.indexOf(d) >= 0;
      cb.disabled = !ok;
      cb.checked = ok && (cb.checked || allowed.length === 1);
      if (!ok) cb.checked = false;
    } else {
      cb.disabled = false;
    }
  });
}

function dotClass(dev) {
  if (dev.state === 'ready' || dev.state === 'busy') return 'green';
  if (dev.state === 'off') return 'red';
  if (dev.state === 'stuck') return 'red';
  if (dev.state === 'unpowered' || dev.state === 'unreachable') return 'grey';
  return 'orange';   // powering / booting / stopping
}

function fmtW(w) { return (w === null || w === undefined) ? '—' : w.toFixed(w < 10 ? 2 : 1) + ' W'; }

// Inline SVG silhouettes per device class — thin-stroke lab style.
var SHAPES = {
  sbc: '<svg width="52" height="30" viewBox="0 0 52 30" fill="none" stroke="currentColor" stroke-width="1.3">'
     + '<rect x="1.5" y="4" width="49" height="22" rx="2"/>'
     + '<g stroke-width="1"><line x1="6" y1="4" x2="6" y2="1"/><line x1="10" y1="4" x2="10" y2="1"/>'
     + '<line x1="14" y1="4" x2="14" y2="1"/><line x1="18" y1="4" x2="18" y2="1"/>'
     + '<line x1="22" y1="4" x2="22" y2="1"/><line x1="26" y1="4" x2="26" y2="1"/></g>'
     + '<rect x="35" y="9" width="10" height="12" rx="1"/>'
     + '<rect x="6" y="12" width="7" height="7"/><line x1="46" y1="14" x2="50.5" y2="14"/></svg>',
  stb: '<svg width="52" height="30" viewBox="0 0 52 30" fill="none" stroke="currentColor" stroke-width="1.3">'
     + '<rect x="3" y="9" width="46" height="13" rx="6"/>'
     + '<circle cx="42" cy="15.5" r="1.6" fill="currentColor" stroke="none"/>'
     + '<line x1="10" y1="22" x2="10" y2="26"/><line x1="42" y1="22" x2="42" y2="26"/></svg>',
  tv:  '<svg width="52" height="30" viewBox="0 0 52 30" fill="none" stroke="currentColor" stroke-width="1.3">'
     + '<rect x="4" y="2" width="44" height="21" rx="1.5"/>'
     + '<line x1="20" y1="26" x2="32" y2="26"/><line x1="26" y1="23" x2="26" y2="26"/></svg>'
};
var SCREEN_SHAPE =
    '<svg width="132" height="88" viewBox="0 0 132 88" fill="none" stroke="currentColor" stroke-width="1.5">'
  + '<rect x="4" y="4" width="124" height="70" rx="2"/>'
  + '<rect class="scr-fill" x="8" y="8" width="116" height="62"/>'
  + '<line x1="50" y1="82" x2="82" y2="82"/><line x1="66" y1="74" x2="66" y2="82"/></svg>';

function deviceTile(name, dev, screenOwner, screenSettling) {
  var pct = null;
  if ((dev.state === 'booting' || dev.state === 'powering') && dev.elapsed_s != null)
    pct = Math.min(97, 100 * dev.elapsed_s / dev.expected_s);
  var busy = dev.busy ? ' <span class="rig-badge">job running</span>' : '';
  var stuck = dev.state === 'stuck' ? ' <span class="rig-badge" style="color:#ffaa00">stuck</span>' : '';
  var screen = screenOwner === name
    ? ' <span class="rig-badge' + (screenSettling ? ' blink' : '') + '">📺 screen'
      + (screenSettling ? '…' : '') + '</span>' : '';
  var h = '<div class="rig-tile" id="devcard-' + name + '">'
        + '<span class="rig-devshape">' + (SHAPES[dev.device_class] || SHAPES.stb) + '</span>'
        + '<h3><span class="rig-dot ' + dotClass(dev) + '"></span>'
        + dev.label + busy + stuck + screen + '</h3>'
        + '<div class="rig-silicon">' + (dev.silicon || '')
        + (dev.network === 'wifi'
           ? ' · <span title="The only Wi-Fi-only device on the rig (no Ethernet port). '
             + 'Its device-total W includes powering its own radio — the Ethernet boxes '
             + 'carry no such share. State this next to any cross-device comparison.">📶 Wi-Fi only</span>'
           : '') + '</div>'
        + '<div class="rig-w">⚡ ' + fmtW(dev.watts)
        + ' <span class="rig-badge">🔌 ' + dev.plug_name + '</span></div>';
  if (pct !== null)
    h += '<div class="rig-bar"><div style="width:' + pct.toFixed(0) + '%"></div></div>'
       + '<div class="rig-detail">' + Math.round(dev.elapsed_s) + ' / ~' + dev.expected_s + ' s — ' + (dev.detail || '') + '</div>';
  else
    h += '<div class="rig-detail">' + (dev.state + (dev.detail ? ' · ' + dev.detail : '')) + '</div>';

  if (IS_LAB) {
    if (dev.state === 'off')
      h += '<button class="rig-btn" onclick="devPower(\\'' + name + '\\',\\'on\\')">On</button>';
    else if (dev.state === 'ready') {
      h += '<button class="rig-btn" onclick="devPower(\\'' + name + '\\',\\'off\\')">Off</button>';
      if (screenOwner !== name && !dev.busy)
        h += ' <button class="rig-btn" onclick="post(\\'/decode/device/' + name
           + '/screen\\', {})">Claim screen</button>';
    }
    else if (dev.state === 'stuck') {
      h += '<button class="rig-btn warn" onclick="devPower(\\'' + name + '\\',\\'cycle\\')">Power-cycle</button>'
         + ' <button class="rig-btn" onclick="devPower(\\'' + name + '\\',\\'off\\')">Force off</button>';
      // A stuck box is powered but its probe fails — often an on-screen prompt
      // (adb "Allow USB debugging?", 2026-08-15) that only the TV can show.
      if (dev.conn !== 'webos' && screenOwner !== name)
        h += ' <button class="rig-btn" onclick="post(\\'/decode/device/' + name
           + '/screen\\', {})">Claim screen</button>';
      if (dev.adb_auth === 'unauthorized')
        h += ' <button class="rig-btn warn" title="Needs someone AT the rig with this box\\'s remote — '
           + 'the accept step cannot be done remotely" onclick="adbRepair(\\'' + name
           + '\\')">Repair ADB (on-site)</button>';
    }
    else if (dev.state === 'booting' || dev.state === 'powering')
      h += '<button class="rig-btn" onclick="devPower(\\'' + name + '\\',\\'off\\')">Cancel</button>';
  }
  h += '</div>';
  return h;
}

function fmtDur(sec) {
  if (sec === null || sec === undefined) return '—';
  var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return h > 0 ? (h + ' h ' + (m < 10 ? '0' : '') + m + ' m') : (m + ' m');
}

function render(s) {
  RIG_LAST = s;
  var agg = 'total ' + fmtW(s.total_w);
  if (s.saving_note) agg = s.saving_note;
  if (s.age_s !== null && s.age_s > 30) agg += ' · ⚠ data ' + Math.round(s.age_s) + 's old';
  var io = s.idle_off;
  if (io) {
    if (!io.enabled) agg += ' · idle auto-off disabled';
    else if (io.armed) agg += ' · auto-off in ' + fmtDur(io.off_in_s)
                              + (io.hold_active ? ' (bench.py hold active)' : '');
    else agg += ' · idle auto-off ' + io.hours + ' h';
  }
  document.getElementById('rig-agg').textContent = agg;

  // Strip bar (replaces the old master tile) — plugs list + Shelly meter +
  // the master/All-off button with unchanged semantics.
  var m = s.master;
  var plugNames = [];
  for (var dn0 in s.devices) plugNames.push(s.devices[dn0].plug_name);
  document.getElementById('strip-plugs').textContent = plugNames.join(' · ');
  var meterEl = document.getElementById('strip-meter');
  var btn = document.getElementById('btn-master');
  if (m.configured) {
    meterEl.style.display = '';
    meterEl.textContent = 'Shelly meter ' +
      ((m.apower_w == null) ? '—' : m.apower_w.toFixed(1) + ' W')
      + (!m.reachable ? ' (not answering)' : '');
    if (IS_LAB) {
      btn.style.display = '';
      if (!m.switchable) {
        var anyUp = false;
        for (var dn in s.devices) {
          var st = s.devices[dn].state;
          if (st !== 'off' && st !== 'unpowered' && st !== 'unreachable') anyUp = true;
        }
        btn.textContent = 'All off';
        btn.disabled = !anyUp;
        btn.title = anyUp ? 'Graceful shutdown of every powered box, then relays off'
                          : 'Nothing is powered';
      } else {
        btn.textContent = m.on ? 'Rig off' : 'Rig on';
        btn.disabled = !m.reachable;
        btn.title = '';
      }
    }
  } else { meterEl.style.display = 'none'; btn.style.display = 'none'; }

  // Screen card
  var mon = s.monitor;
  document.getElementById('dot-monitor').className =
    'rig-dot ' + (!mon.reachable ? 'grey' : (mon.on ? 'green' : 'red'));
  document.getElementById('screen-panel').textContent = mon.panel || '';
  if (mon.plug_name)
    document.getElementById('screen-plug').textContent = '🔌 ' + mon.plug_name;
  document.getElementById('w-monitor').textContent = '⚡ ' + fmtW(mon.watts);
  var showing = s.screen_owner && s.devices[s.screen_owner]
    ? s.devices[s.screen_owner].label : null;
  document.getElementById('d-monitor').textContent =
    !mon.reachable ? 'not answering'
      : (showing ? 'showing: ' + showing + (s.screen_settling ? ' …' : '')
        : (mon.in_use_hint ? 'displaying — may be in use (Mac?)'
          : (mon.on ? 'powered · no owner' : 'off')));
  document.getElementById('screen-shape').className =
    'rig-shape' + (mon.in_use_hint ? ' lit' : '');
  var mb = document.getElementById('btn-monitor');
  mb.textContent = mon.on ? 'Off' : 'On';
  mb.disabled = !mon.reachable;

  buildDevPicks(s.devices);

  // Device cards + control rail
  var tiles = '', rail = '';
  for (var name in s.devices) {
    tiles += deviceTile(name, s.devices[name], s.screen_owner, s.screen_settling);
    rail += '<div class="rail-conn" id="rail-' + name + '">──' +
            (s.devices[name].conn || '?') + '─▸</div>';
  }
  document.getElementById('rig-tiles').innerHTML = tiles;
  document.getElementById('rail-links').innerHTML = rail;
  drawWires(s);
}

// ── Wire overlay ──────────────────────────────────────────────────
// Recomputed from live card positions every render/resize: HDMI wire per
// powered device to the screen (owner's lit + animated), dashed power drop
// per device to the strip bar, control stubs from the rail.
function drawWires(s) {
  var svg = document.getElementById('rig-wires');
  var bench = document.getElementById('rig-bench');
  if (!svg || !bench || window.innerWidth <= 700) { if (svg) svg.innerHTML = ''; return; }
  var b = bench.getBoundingClientRect();
  var scr = document.getElementById('tile-monitor').getBoundingClientRect();
  var strip = document.getElementById('rig-stripbar').getBoundingClientRect();
  var paths = '';
  var names = Object.keys(s.devices || {});
  for (var i = 0; i < names.length; i++) {
    var name = names[i];
    var card = document.getElementById('devcard-' + name);
    var railLbl = document.getElementById('rail-' + name);
    if (!card) continue;
    var c = card.getBoundingClientRect();
    var st = s.devices[name].state;
    var up = st !== 'off' && st !== 'unpowered' && st !== 'unreachable';
    // control stub: rail label sits mid-card (position it), line to card left
    if (railLbl) {
      railLbl.style.position = 'absolute';
      railLbl.style.top = (c.top - b.top + c.height / 2 - 8) + 'px';
      railLbl.style.left = '0';
    }
    // HDMI wire: card right edge → screen left edge (staggered entry)
    var x1 = c.right - b.left, y1 = c.top - b.top + c.height / 2;
    var x2 = scr.left - b.left, y2 = scr.top - b.top + 18 + i * 22;
    var midx = x1 + (x2 - x1) * 0.55;
    var cls = 'wire' + (s.screen_owner === name ? ' owner' : '');
    var op = up ? '1' : '0.25';
    paths += '<path class="' + cls + '" opacity="' + op + '" d="M' + x1 + ' ' + y1
           + ' H' + midx + ' V' + y2 + ' H' + x2 + '"/>';
    // power drop: card bottom → strip bar top
    var px = c.left - b.left + 24;
    paths += '<path class="wire power" d="M' + px + ' ' + (c.bottom - b.top)
           + ' V' + (strip.top - b.top) + '"/>';
  }
  svg.setAttribute('viewBox', '0 0 ' + b.width + ' ' + b.height);
  svg.innerHTML = paths;
}
window.addEventListener('resize', function(){ if (RIG_LAST) drawWires(RIG_LAST); });

function err(msg) {
  document.getElementById('rig-err').textContent = msg || '';
  if (msg) setTimeout(function(){ err(''); }, 6000);
}

async function post(url, body) {
  try {
    var r = await fetch(url, {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    var j = await r.json();
    if (!r.ok) err(j.error || ('HTTP ' + r.status));
  } catch (e) { err(String(e)); }
  tick();
}

async function adbRepair(name) {
  if (!confirm('Repair ADB needs a person AT the rig holding this box\\'s remote control: '
             + 'the box will show an "Allow USB debugging?" prompt on the shared TV that can only '
             + 'be accepted with the remote — there is no remote-over-network way to do it.\\n\\n'
             + 'Are you (or someone you can talk to) physically at the rig now?')) return;
  var r = await fetch('/decode/device/' + name + '/adb-repair', {method:'POST',
              headers:{'Content-Type':'application/json'}, body:'{}'});
  var j = await r.json();
  if (!r.ok || j.error) { alert('Repair failed: ' + (j.error || r.status)); return; }
  if (j.adb_auth === 'device') { alert('Authorised — the box will show ready on the next poll.'); return; }
  alert('The TV is now on this box\\'s input and its "Allow USB debugging?" prompt has been '
      + 'sent ONCE. Whoever is at the rig, on the box\\'s remote: tick "Always allow from this '
      + 'computer", then OK. (Do NOT click Repair again while waiting — each click queues another '
      + 'prompt to accept.)\\n\\n'
      + 'Fingerprint to expect: ' + (j.fingerprint || '(unknown)')
      + (j.screen_error ? '\\n\\n(screen claim failed: ' + j.screen_error + ')' : '')
      + '\\n\\nNo prompt? On the box: Developer options → toggle USB debugging off/on, then Repair again.');
}

function devPower(name, action) {
  if (action === 'off' && RIG_LAST && RIG_LAST.devices[name].busy) return;
  post('/decode/device/' + name + '/power', {action: action});
}

function monitorToggle() {
  var on = RIG_LAST && RIG_LAST.monitor.on;
  if (on) {
    var hint = RIG_LAST.monitor.in_use_hint
      ? 'The monitor is DISPLAYING something (possibly a Mac screen extension). '
      : '';
    if (!confirm(hint + 'Cut power to the monitor?')) return;
  }
  post('/decode/monitor/power', {on: !on});
}

function masterToggle() {
  var m = RIG_LAST && RIG_LAST.master;
  if (m && !m.switchable) {
    if (!confirm('Gracefully shut down every powered box?')) return;
    post('/decode/master/power', {on: false});
    return;
  }
  var on = m && m.on;
  if (on && !confirm('Master off cuts the strip: the three Lab plugs go '
                     + 'unreachable until master returns. Continue?')) return;
  post('/decode/master/power', {on: !on});
}

document.getElementById('screen-shape').innerHTML = SCREEN_SHAPE;

async function tick() {
  try {
    var r = await fetch('/decode/status.json');
    if (r.ok) render(await r.json());
  } catch (e) {}
}
tick();
setInterval(tick, 2500);

// Read-only (non-Lab): controls off, monitor/master buttons hidden.
if (!IS_LAB) {
  document.getElementById('btn-run').disabled = true;
  document.getElementById('btn-run').textContent = 'Run (Lab only)';
  document.getElementById('btn-upload').disabled = true;
  document.getElementById('btn-monitor').style.display = 'none';
  document.getElementById('btn-master').style.display = 'none';
}

// --- Recent runs ---
function fmtDW(v) { return (v >= 0 ? '+' : '') + v + ' W'; }
async function loadRecent() {
  try {
    var r = await fetch('/decode/runs.json');
    if (!r.ok) return;
    var j = await r.json();
    var el = document.getElementById('recent-runs');
    if (!j.runs.length) { el.textContent = 'no runs yet'; return; }
    var h = '<table class="rig-rows">';
    for (var i = 0; i < j.runs.length; i++) {
      var run = j.runs[i];
      var when = (run.saved_at || '').replace('T', ' ').slice(0, 16);
      var rows = run.rows.map(function(x){
        return (DEV_LABELS[x.device] || x.device || '') + ' ' + fmtDW(x.delta_w)
             + ' ' + (x.flag || '');
      }).join(' · ');
      h += '<tr><td>' + when + '</td><td>' + (run.label || '') + '</td>'
         + '<td><span class="rig-badge">' + (run.mode || '') + ' v'
         + (run.protocol_version || '?') + '</span></td>'
         + '<td>' + rows + '</td>'
         + '<td><a href="/decode?job=' + run.job_id + '" style="color:var(--accent)">card</a>'
         + ' <a href="/decode/result/' + run.job_id + '/lem.csv" style="color:var(--accent)">csv</a>'
         + ' <a href="/results/decode/' + run.job_id + '/download.json" style="color:var(--accent)">full json</a></td></tr>';
    }
    el.innerHTML = h + '</table>';
  } catch (e) {}
}
loadRecent();

// Re-attach to a job after reload/service restart: /decode?job=<id>
// (queue-status ↩ Resume points here; results also recover from disk).
var _qjob = new URLSearchParams(location.search).get('job');
if (_qjob) { if (IS_LAB) document.getElementById('btn-run').disabled = true; pollJob(_qjob); }

// --- Runs (v2: mode + device fan-out) ---
var PHASE_LABELS = {device:'Power device', staging:'Stage clips',
                    settle:'Settle', baseline:'Baseline',
                    starting:'Start playback', sampling:'Sampling',
                    finishing:'Confidence', done:'Done', error:'Error'};
var DEV_LABELS = {pi5:'Pi 5', pi400:'Pi 400', gtv:'Google TV', bbox:'Bbox 4K'};
// Device selection list — populated from live status so the run panel always
// matches the real bench (buildDevPicks); no hardcoded device names.
var DEVICE_NAMES = [];

function buildDevPicks(devices) {
  var names = Object.keys(devices);
  if (names.join() === DEVICE_NAMES.join()) return;   // unchanged
  DEVICE_NAMES = names;
  var el = document.getElementById('dev-checkboxes');
  if (!el) return;
  el.innerHTML = names.map(function(d, i){
    var lbl = devices[d].label || DEV_LABELS[d] || d;
    return '<label style="margin-right:0.7rem"><input type="checkbox" id="dev-'
      + d + '"' + (i < 2 ? ' checked' : '') + ' onchange="devPicked(this)"> '
      + lbl + '</label>';
  }).join('');
}

function screenMode() {
  return document.querySelector('input[name=mode]:checked').value === 'screen';
}

function modeChanged() {
  document.getElementById('cal-wrap').style.display = screenMode() ? '' : 'none';
  if (screenMode()) {  // collapse to a single selection
    var first = true;
    DEVICE_NAMES.forEach(function(d){
      var cb = document.getElementById('dev-' + d);
      if (cb.checked && !first) cb.checked = false;
      if (cb.checked) first = false;
    });
  }
}

function devPicked(box) {
  // Screen mode is exclusive: checking one box unchecks the others.
  if (screenMode() && box.checked) {
    DEVICE_NAMES.forEach(function(d){
      var cb = document.getElementById('dev-' + d);
      if (cb !== box) cb.checked = false;
    });
  }
}

function stageRow(icon, color, label, extra) {
  return '<div class="rig-stage"><span style="color:' + color + ';width:1rem">'
       + icon + '</span><span style="color:' + color + '">' + label + '</span>'
       + (extra || '') + '</div>';
}

function deviceProgress(name, sub, j) {
  var h = '<div class="rig-tile" style="min-width:13rem"><h3>'
        + (DEV_LABELS[name] || name) + '</h3>';
  if (sub.stage === 'error') {
    h += '<div class="rig-err">✗ ' + (sub.detail || 'failed') + '</div></div>';
    return h;
  }
  var names = ['device', 'staging'].concat((j.phases || []).map(function(p){ return p[0]; }));
  var cur = names.indexOf(sub.stage);
  if (sub.stage === 'done') cur = names.length;
  if (sub.live_w != null || sub.monitor_w != null) {
    h += '<div class="rig-w">';
    if (sub.live_w != null)
      h += '<span title="device / box">⚡ ' + fmtW(sub.live_w) + '</span>';
    if (sub.monitor_w != null)
      h += '<span style="margin-left:0.9rem" title="TV / screen">📺 '
         + fmtW(sub.monitor_w) + '</span>';
    h += '</div>';
  }
  if (sub.row && j.row_n > 1)
    h += '<div class="rig-detail">row ' + sub.row + ' / ' + j.row_n + '</div>';
  for (var i = 0; i < names.length; i++) {
    var n = names[i], lbl = PHASE_LABELS[n] || n;
    if (i < cur) h += stageRow('✓', 'var(--accent)', lbl);
    else if (i === cur) {
      var extra = '';
      var ph = (j.phases || []).filter(function(p){ return p[0] === n; })[0];
      if (ph && sub.phase_elapsed_s != null) {
        var pct = Math.min(98, 100 * sub.phase_elapsed_s / ph[1]);
        extra = '<span class="rig-detail" style="margin-left:0.5rem">'
              + Math.round(sub.phase_elapsed_s) + '/' + ph[1] + 's</span>'
              + '<span style="flex:1;max-width:8rem;margin-left:0.5rem" class="rig-bar">'
              + '<span style="display:block;height:100%;width:' + pct.toFixed(0)
              + '%;background:var(--warn)"></span></span>';
      }
      h += stageRow('▶', 'var(--warn)', lbl, extra);
    } else h += stageRow('·', 'var(--text-5)', lbl);
  }
  if (sub.stage === 'done') h += stageRow('✓', 'var(--accent)', 'Done');
  if (sub.detail) h += '<div class="rig-detail">' + sub.detail + '</div>';
  return h + '</div>';
}

function resultTable(result) {
  var rows = (result && result.runs) || [];
  if (!rows.length) return '';
  var h = '<table class="rig-rows">';
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    if (r.error) { h += '<tr><td>' + (DEV_LABELS[r.device] || r.device) + ' ' + r.run
                      + '</td><td colspan=3>✗ ' + r.error + '</td></tr>'; continue; }
    var flag = (r.confidence && r.confidence.flag) || '';
    var dwh = (r.window_s != null)
      ? '<td>Δ' + (r.delta_w * r.window_s / 3600).toFixed(4) + ' Wh · total '
        + (r.wh_window_device_total != null ? r.wh_window_device_total : '—')
        + ' Wh</td>' : '<td></td>';
    var scr = (r.context_task_w != null)
      ? '<td>screen ' + r.context_task_w + ' W'
        + (r.context_delta_w != null
           ? ' (Δ' + (r.context_delta_w >= 0 ? '+' : '') + r.context_delta_w + ')' : '')
        + (r.context_wh_window != null ? ' · ' + r.context_wh_window + ' Wh' : '')
        + '</td>' : '';
    h += '<tr><td>' + (DEV_LABELS[r.device] || r.device) + '</td><td>' + r.run + '</td>'
       + '<td>base ' + r.w_base + ' W</td><td>task ' + r.w_task + ' W</td>'
       + '<td><b>ΔW ' + (r.delta_w >= 0 ? '+' : '') + r.delta_w + '</b> ' + flag + '</td>'
       + dwh + scr + '</tr>';
    var seg = r.screen_marker_segments;
    if (seg)
      h += '<tr><td></td><td colspan=5 class="rig-detail" style="font-size:0.76rem">'
         + '↳ screen segmented: black ' + seg.black_w + ' W · white ' + seg.white_w
         + ' W · content ' + seg.content_w + ' W (marker swing '
         + seg.marker_swing_w + ' W)</td></tr>';
  }
  return h + '</table>';
}

function renderJob(j) {
  var el = document.getElementById('run-status');
  if (j.status === 'error') {
    el.innerHTML = '<div class="rig-err">✗ ' + (j.error || 'failed') + '</div>';
    return true;
  }
  if (j.status === 'not_found') {
    el.innerHTML = '<div class="rig-err">✗ job lost — the service restarted '
                 + 'mid-run and no result reached disk. Re-run the recipe.</div>';
    return true;
  }
  if (j.stage === 'queued') {
    el.innerHTML = stageRow('…', 'var(--warn)',
      'queued — position ' + (j.queue_position || '?')); return false;
  }
  var h = '<div class="rig-progress">';
  var devs = j.devices || {};
  for (var name in devs) h += deviceProgress(name, devs[name], j);
  h += '</div>';
  if (j.status === 'done') {
    h += stageRow('✓', 'var(--accent)', 'done — result saved',
      CUR_JOB ? ' <a href="/decode/result/' + CUR_JOB + '/lem.csv" '
              + 'style="color:var(--accent);font-size:0.78rem;margin-left:0.6rem">'
              + '⬇ raw samples (LEM CSV)</a>'
              + ' <a href="/results/decode/' + CUR_JOB + '/download.json" '
              + 'style="color:var(--accent);font-size:0.78rem;margin-left:0.6rem">'
              + '⬇ full result (JSON)</a>' : '');
    if (j.partial_errors)
      h += '<div class="rig-err">partial: ' + JSON.stringify(j.partial_errors) + '</div>';
    h += resultTable(j.result);
    el.innerHTML = h;
    return true;
  }
  el.innerHTML = h;
  return false;
}

var CUR_JOB = null;
async function pollJob(id) {
  CUR_JOB = id;
  try {
    var r = await fetch('/decode/job/' + id);
    var j = await r.json();
    if (renderJob(j)) { document.getElementById('btn-run').disabled = false; return; }
  } catch (e) {}
  setTimeout(function(){ pollJob(id); }, 2000);
}

var UPLOADED = null;
async function uploadClip() {
  var f = document.getElementById('up-file').files[0];
  if (!f) { err('choose a file first'); return; }
  var st = document.getElementById('up-status');
  st.textContent = 'uploading…';
  document.getElementById('btn-upload').disabled = true;
  try {
    var form = new FormData();
    form.append('file', f);
    form.append('retention',
      document.querySelector('input[name=up-ret]:checked').value);
    var r = await fetch('/decode/upload', {method: 'POST', body: form});
    var j = await r.json();
    if (!r.ok) { err(j.error || ('HTTP ' + r.status)); st.textContent = ''; }
    else {
      UPLOADED = j.name;
      st.textContent = '✓ ' + j.name + ' (' + j.size_mb + ' MB)';
      var sel = document.getElementById('recipe');
      var opt = sel.querySelector('option[value=upload]');
      if (!opt) { opt = document.createElement('option');
                  opt.value = 'upload'; sel.appendChild(opt); }
      opt.textContent = 'uploaded clip — ' + f.name;
      sel.value = 'upload';
    }
  } catch (e) { err(String(e)); }
  document.getElementById('btn-upload').disabled = false;
}

async function runRecipe() {
  var mode = document.querySelector('input[name=mode]:checked').value;
  var devices = DEVICE_NAMES.filter(function(d){
    return document.getElementById('dev-' + d).checked; });
  if (!devices.length) { err('pick at least one device'); return; }
  if (mode === 'screen' && devices.length !== 1) {
    err('screen mode is exclusive — pick exactly one device'); return; }
  var tpl = document.getElementById('recipe').value;
  if (tpl === 'upload' && !UPLOADED) { err('upload a clip first'); return; }
  var cad = parseInt(document.getElementById('cadence').value, 10);
  if (mode === 'screen' && document.getElementById('calibrate').checked && cad > 1)
    err('note: marker segments carry ~5/' + cad + ' samples at this cadence');
  var body = {template: tpl, mode: mode, devices: devices,
              upload_name: tpl === 'upload' ? UPLOADED : undefined,
              cadence_s: cad,
              calibrate: document.getElementById('calibrate').checked};
  if (tpl.indexOf('loop_') === 0)
    body.window_s = parseInt(document.getElementById('duration').value, 10);
  document.getElementById('btn-run').disabled = true;
  try {
    var r = await fetch('/decode/run', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)});
    var j = await r.json();
    if (!r.ok) { err(j.error || ('HTTP ' + r.status));
                 document.getElementById('btn-run').disabled = false; return; }
    pollJob(j.job_id);
  } catch (e) { err(String(e)); document.getElementById('btn-run').disabled = false; }
}
</script>
"""
