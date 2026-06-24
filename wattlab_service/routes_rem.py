"""
/prepare-rem — "Prepare REM Files" page (REM↔OWL integration, 2026-06-23 spec).

Lab-only hidden page that drives rem_prep.py: pick a source (OWL's pristine
masters incl. the 4K versions, or an upload), a codec/resolution/target-VMAF,
and OWL encodes to that quality then wraps it in a timer/marker structure for
REM device-playback experiments. The generated file gets BOTH a Lab download
and an un-gated unguessable SHARE link (so Simon can fetch it off-LAN).

Phase-3 per-feature module: routes + the run_rem_job wrapper live here;
measurement/assembly in rem_prep.py. Shared state from runtime.py, chrome from
ui.py — never import main.
"""
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import audience
import gpu
import queue_control
import rem_prep
import settings as cfg
import sources
import ui
import uploads
from capabilities import (requires, can, PREPARE_REM, PUBLIC_PAGE,
                          SETTINGS_WRITE, WORKING_NAV)
from persist import save_result
from routes_video import _video_source_picker_html
from runtime import jobs, job_status as _job_status
from ui import _PROGRESS_JS, _disabled_attr, _lock_badge_html, _lock_class

router = APIRouter()

_CODECS = ("h264", "h265", "av1")
_UPLOAD_EXTS = {".mov", ".mp4", ".mkv", ".m4v", ".y4m", ".webm"}

# Make the REM upload dir visible to global "short of space" eviction (no mkdir
# here — register the path; uploads._all_dirs() filters to existing dirs).
uploads.register_dir(
    Path(cfg.load().get("rem_output_dir", "/srv/data/owl/rem_out")) / "_uploads")


def _truthy(v: str) -> bool:
    return str(v).lower() in ("true", "1", "on", "yes")


def _native_height(source_key: str, upload_name: str) -> int | None:
    """Probed native height of the chosen source (for the 'native' resolution
    option). None if it can't be resolved."""
    try:
        if upload_name:
            _, up_dir, _ = rem_prep.rem_dirs()
            props = rem_prep._probe_props(up_dir / Path(upload_name).name)
            return props.get("height")
        if source_key:
            info = sources.get_source_info(source_key)
            res = (info or {}).get("resolution", "")
            if "x" in res:
                return int(res.split("x")[1])
    except Exception:
        pass
    return None


# --- Job wrapper (mirror routes_enhance.run_enhance_job) --------------------
async def run_rem_job(job_id: str, source_key: str | None, upload_name: str | None,
                      codec: str, device: str, height: int,
                      target_vmaf: float | None, metered: bool):
    try:
        jobs[job_id].update({"status": "running", "stage": "starting"})
        result = await rem_prep.run_rem_prep_job(
            job_id, jobs=jobs, source_key=source_key, upload_name=upload_name,
            codec=codec, device=device, height=height,
            target_vmaf=target_vmaf, metered=metered)
        save_result("rem", job_id, result)
        jobs[job_id].update({"status": "done", "stage": "done", "result": result})
    except Exception as e:
        jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}
    finally:
        # proc → delete now; evict/keep → touch (recency/TTL from run end).
        if upload_name:
            _, up_dir, _ = rem_prep.rem_dirs()
            uploads.cleanup_after_job(up_dir, upload_name)


# --- Page -------------------------------------------------------------------
# Viewable by Member+ (so a collaborator can see what the tool does and grab a
# share link), but every control is DISABLED unless the visitor is Lab — the run/
# upload/delete endpoints enforce PREPARE_REM (Lab) server-side regardless.
@router.get("/prepare-rem", response_class=HTMLResponse,
            dependencies=[Depends(requires(WORKING_NAV))])
async def prepare_rem_page(request: Request):
    s = cfg.load()
    gpu_ok = getattr(gpu.BACKEND, "available", False)
    is_lab = can(audience.tier(request), PREPARE_REM)
    # ' disabled' for non-Lab; combined with {GPU_DISABLED} where relevant.
    dis = _disabled_attr(request, PREPARE_REM)
    banner = ("" if is_lab else
              '<div class="lab-req">🔒 Read-only preview — you must be in '
              '<b>Lab mode</b> (on the GoS1 LAN / loopback) to generate files. '
              'The controls below are disabled.</div>')
    body = (_PREPARE_REM_HTML
            .replace("{LOCK_BADGE}", _lock_badge_html(request, PREPARE_REM, "Lab only"))
            .replace("{LOCK_CLASS}", _lock_class(request, PREPARE_REM))
            .replace("{LAB_BANNER}", banner)
            .replace("{DISABLED}", dis)
            .replace("{RETENTION_PICKER}", ui.upload_retention_radios(disabled=dis))
            .replace("{SOURCE_PICKER}", _video_source_picker_html())
            .replace("{TARGET_VMAF}", str(s.get("rem_target_vmaf", 92)))
            .replace("{GPU_DISABLED}", "" if (gpu_ok and is_lab) else " disabled")
            .replace("{GPU_NAME}", getattr(gpu.BACKEND, "name", "GPU"))
            .replace("{VIDEO_S}", str(s.get("rem_video_s", 390)))
            .replace("{TIMER_S}", str(s.get("rem_timer_s", 60)))
            .replace("{MARKER_S}", str(s.get("rem_marker_s", 30)))
            .replace("{TAIL_S}", str(s.get("rem_tail_s", 60))))
    return ui.render_page(request, "Prepare REM Files",
                          styles=_PREPARE_REM_STYLES, body=body, tail=_PROGRESS_JS)


# --- Upload (Lab; the page is Lab-only so no Member caps) -------------------
@router.post("/prepare-rem/upload", dependencies=[Depends(requires(PREPARE_REM))])
async def prepare_rem_upload(request: Request, file: UploadFile = File(...),
                             retention: str = Form(uploads.DEFAULT_RETENTION)):
    orig = Path(file.filename or "clip").name
    ext = Path(orig).suffix.lower()
    if ext not in _UPLOAD_EXTS:
        return JSONResponse(
            {"error": f"Unsupported container '{ext or '(none)'}' — use one of: "
                      + ", ".join(sorted(_UPLOAD_EXTS))}, status_code=400)
    blob = await file.read()
    _, up_dir, _ = rem_prep.rem_dirs()
    saved = uploads.save(blob, orig, retention=retention, feature="rem", dest_dir=up_dir)
    props = rem_prep._probe_props(saved["path"])
    return {"name": saved["name"], "retention": saved["retention"],
            "width": props.get("width"), "height": props.get("height"),
            "fps": props.get("fps")}


# --- Run --------------------------------------------------------------------
@router.post("/prepare-rem/run", dependencies=[Depends(requires(PREPARE_REM))])
async def prepare_rem_run(request: Request,
                          source_key: str = Form(""),
                          upload_name: str = Form(""),
                          codec: str = Form("h264"),
                          device: str = Form("cpu"),
                          height: str = Form("1080"),
                          target_vmaf: str = Form(""),
                          produce_only: str = Form("")):
    if codec not in _CODECS:
        return JSONResponse({"error": f"Unknown codec '{codec}'"}, status_code=400)
    if device not in ("cpu", "gpu"):
        return JSONResponse({"error": f"Unknown encoder '{device}'"}, status_code=400)
    if device == "gpu" and not getattr(gpu.BACKEND, "available", False):
        return JSONResponse({"error": "No GPU encoder available on this box"},
                            status_code=409)
    if not source_key and not upload_name:
        return JSONResponse({"error": "Pick a source or upload a clip"}, status_code=400)

    try:
        h = int(height)
    except ValueError:
        h = 0
    if h <= 0:  # "native"
        h = _native_height(source_key, upload_name) or 1080
    tv = None
    if target_vmaf.strip():
        try:
            tv = float(target_vmaf)
        except ValueError:
            return JSONResponse({"error": "target VMAF must be a number"}, status_code=400)

    metered = not _truthy(produce_only)
    # Backstop sweep of stale evict-class uploads on every run start.
    _, up_dir, _ = rem_prep.rem_dirs()
    uploads.sweep(up_dir)
    job_id = str(uuid.uuid4())[:8]
    label = (f"REM prep — {rem_prep.CODEC_LABEL.get(codec, codec)} {h}p "
             f"{device}" + ("" if metered else " · produce-only"))

    async def coro():
        await run_rem_job(job_id, source_key or None, upload_name or None,
                          codec, device, h, tv, metered)

    position = queue_control.enqueue(job_id, "rem", label, coro,
                                     request=request, page="/prepare-rem")
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


@router.get("/prepare-rem/job/{job_id}", dependencies=[Depends(requires(PREPARE_REM))])
async def prepare_rem_job_status(job_id: str):
    return _job_status(job_id)


# --- Downloads --------------------------------------------------------------
@router.get("/prepare-rem/output/{name}", dependencies=[Depends(requires(PREPARE_REM))])
async def prepare_rem_output(name: str):
    """Lab download / in-page preview of a generated REM file. Basename
    allow-list — no traversal."""
    out_dir, _, _ = rem_prep.rem_dirs()
    if Path(name).name != name:
        return HTMLResponse("not found", status_code=404)
    path = out_dir / name
    if not path.is_file():
        return HTMLResponse("not found", status_code=404)
    return FileResponse(path, media_type="video/mp4", filename=name)


@router.get("/rem-file/{token}", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def prepare_rem_share(token: str):
    """Un-gated shareable direct download (the ForTania pattern): a remote
    collaborator with the unguessable token fetches the deliverable without
    LAN/SSH. The page itself stays Lab-only; only this per-file link is public."""
    if not re.fullmatch(r"[0-9a-f]{16,64}", token):
        return HTMLResponse("not found", status_code=404)
    path = rem_prep.resolve_share_token(token)
    if path is None:
        return HTMLResponse("not found", status_code=404)
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.delete("/prepare-rem/input/{name}", dependencies=[Depends(requires(SETTINGS_WRITE))])
async def prepare_rem_input_delete(name: str):
    """Lab-only — delete an uploaded clip. Uploads only; basename allow-list."""
    if Path(name).name != name or not uploads.is_owl_upload(name):
        return JSONResponse({"ok": False, "error": "Only uploaded clips can be deleted"},
                            status_code=400)
    _, up_dir, _ = rem_prep.rem_dirs()
    path = up_dir / name
    if not path.is_file():
        return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
    path.unlink(missing_ok=True)
    return {"ok": True, "deleted": name}


# --- Page template ----------------------------------------------------------
_PREPARE_REM_STYLES = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: monospace; background: var(--bg); color: var(--text);
           max-width: 900px; margin: 0 auto; padding: 2rem 1rem; }
    h1 { color: var(--accent); font-size: 1.4rem; margin-bottom: 0.25rem; }
    .subtitle { color: var(--text-3); font-size: 0.82rem; margin-bottom: 1.25rem; }
    .lead { color: var(--text-3); font-size: 0.83rem; line-height: 1.6;
            border-left: 2px solid var(--accent); padding-left: 0.9rem; margin-bottom: 1.5rem; }
    h2 { font-size: 0.95rem; color: var(--text-2); margin: 1.5rem 0 0.6rem; }
    .row { display: flex; flex-wrap: wrap; gap: 1.5rem; margin-bottom: 0.5rem; }
    .field { display: flex; flex-direction: column; gap: 0.3rem; }
    label.f { color: var(--text-4); font-size: 0.7rem; text-transform: uppercase;
              letter-spacing: 0.05em; }
    select, input[type=number], input[type=file] { font-family: monospace;
            background: var(--bg-2, #141414); color: var(--text);
            border: 1px solid var(--border-3); padding: 0.4rem 0.5rem; font-size: 0.85rem; }
    .radios label { margin-right: 1rem; font-size: 0.85rem; color: var(--text-2); }
    button { font-family: monospace; cursor: pointer; }
    .run-btn { background: var(--accent); color: #0a0a0a; border: none; font-weight: bold;
               padding: 0.6rem 2rem; font-size: 0.95rem; margin-top: 1rem; }
    .run-btn:hover { background: var(--accent-hover); }
    .run-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .secondary { background: transparent; color: var(--accent);
                 border: 1px solid var(--accent); padding: 0.4rem 0.9rem; font-size: 0.8rem; }
    .note { color: var(--text-5); font-size: 0.72rem; line-height: 1.5; margin-top: 0.3rem; }
    #result { margin-top: 1.5rem; }
    .card { border: 1px solid var(--border-3); padding: 1rem; margin-top: 1rem; }
    .card h3 { color: var(--accent); font-size: 1rem; margin-bottom: 0.5rem; }
    .kv { display: grid; grid-template-columns: max-content 1fr; gap: 0.25rem 1rem;
          font-size: 0.82rem; margin-bottom: 0.75rem; }
    .kv .k { color: var(--text-4); }
    .kv .v { color: var(--text-2); }
    .dl a { color: var(--accent); text-decoration: none; border: 1px solid var(--accent);
            padding: 0.35rem 0.8rem; font-size: 0.8rem; margin-right: 0.5rem;
            display: inline-block; margin-top: 0.4rem; }
    .share { background: rgba(0,255,153,0.06); border: 1px solid var(--border-3);
             padding: 0.6rem; margin-top: 0.6rem; font-size: 0.78rem; }
    .share input { width: 100%; margin-top: 0.3rem; }
    video { width: 100%; max-width: 640px; margin-top: 0.6rem;
            border: 1px solid var(--border-3); background: #000; }
    .warn { color: var(--warn); }
    .err { color: #ff6b6b; font-size: 0.85rem; }
    .lab-req { border: 1px solid var(--warn); background: rgba(255,170,0,0.07);
               color: var(--warn); font-size: 0.82rem; line-height: 1.55;
               padding: 0.6rem 0.8rem; margin-bottom: 1.25rem; }
    table.iters { border-collapse: collapse; font-size: 0.76rem; margin-top: 0.5rem; }
    table.iters td, table.iters th { border: 1px solid var(--border-3);
            padding: 0.2rem 0.55rem; text-align: right; }
"""

_PREPARE_REM_HTML = """
<h1>Prepare REM Files {LOCK_BADGE}</h1>
<div class="subtitle">REM↔OWL integration · device-playback test-file generator</div>
<div class="lead">
  Encode a source to a constant <b>target quality (VMAF)</b> — bitrate is the free
  variable — then wrap it in a timer + black/white/black marker structure REM uses to
  delimit the playback analysis window:
  <code>[{TIMER_S}s timer][{MARKER_S}s black][{MARKER_S}s white][{MARKER_S}s black][{VIDEO_S}s video][{TAIL_S}s black]</code>
  ≈ 10&nbsp;min, 4:2:0 8-bit, constant audio. The bitrate search runs on a 2-min excerpt
  (fast), then one full encode confirms VMAF on the deliverable. Each file gets a Lab
  download and an un-gated <b>share link</b> for collaborators.
</div>

{LAB_BANNER}

<div class="{LOCK_CLASS}">
  <h2>1 · Source</h2>
  {SOURCE_PICKER}
  <div class="row" style="margin-top:0.75rem">
    <div class="field">
      <label class="f">…or upload</label>
      <input type="file" id="upFile" accept="video/*"{DISABLED}>
    </div>
    <div class="field" style="justify-content:flex-end">
      <button class="secondary" id="upBtn" onclick="doUpload()"{DISABLED}>Upload</button>
    </div>
    <div class="field" style="justify-content:flex-end">
      <span class="note" id="upStatus"></span>
    </div>
  </div>
  {RETENTION_PICKER}

  <h2>2 · Output</h2>
  <div class="row">
    <div class="field">
      <label class="f">Codec</label>
      <div class="radios">
        <label><input type="radio" name="codec" value="h264" checked{DISABLED}> H.264</label>
        <label><input type="radio" name="codec" value="h265"{DISABLED}> H.265</label>
        <label><input type="radio" name="codec" value="av1"{DISABLED}> AV1</label>
      </div>
    </div>
    <div class="field">
      <label class="f">Encoder</label>
      <select id="device"{DISABLED}>
        <option value="cpu" selected>Software (reproducible)</option>
        <option value="gpu"{GPU_DISABLED}>Hardware · {GPU_NAME} (faster)</option>
      </select>
    </div>
    <div class="field">
      <label class="f">Resolution</label>
      <select id="height"{DISABLED}>
        <option value="2160">2160p (4K)</option>
        <option value="1080" selected>1080p</option>
        <option value="720">720p</option>
        <option value="0">native (source)</option>
      </select>
    </div>
    <div class="field">
      <label class="f">Target VMAF</label>
      <input type="number" id="vmaf" min="50" max="100" step="0.5" value="{TARGET_VMAF}" style="width:6rem"{DISABLED}>
    </div>
  </div>
  <div class="row">
    <div class="field">
      <label><input type="checkbox" id="produceOnly"{DISABLED}> Produce only (skip energy measurement — faster)</label>
      <span class="note">Software 4K AV1 can run well past 20&nbsp;min and locks the queue. Produce-only still hits the target VMAF and assembles the file, but reports no energy.</span>
    </div>
  </div>

  <button class="run-btn" id="runBtn" onclick="runRem()"{DISABLED}>Generate REM file</button>
</div>

<div id="progress"></div>
<div id="result"></div>

<script>
let uploadedName = null;

async function doUpload() {
  const f = document.getElementById('upFile').files[0];
  const st = document.getElementById('upStatus');
  if (!f) { st.textContent = 'pick a file first'; return; }
  st.textContent = 'uploading…';
  const fd = new FormData(); fd.append('file', f);
  const ret = document.querySelector('input[name=retention]:checked');
  fd.append('retention', ret ? ret.value : 'evict');
  try {
    const r = await fetch('/prepare-rem/upload', {method:'POST', body:fd});
    const j = await r.json();
    if (!r.ok) { st.innerHTML = '<span class="err">'+(j.error||'upload failed')+'</span>'; return; }
    uploadedName = j.name;
    document.querySelectorAll('input[name=source]').forEach(el => el.checked = false);
    st.textContent = '✓ ' + j.name + ' (' + (j.width||'?') + '×' + (j.height||'?') + ')';
  } catch(e) { st.innerHTML = '<span class="err">'+e+'</span>'; }
}

function selectSource(key) { uploadedName = null;
  document.getElementById('upStatus').textContent = ''; }

function selectedSource() {
  const r = document.querySelector('input[name=source]:checked');
  return r ? r.value : '';
}

async function runRem() {
  const btn = document.getElementById('runBtn');
  const res = document.getElementById('result');
  const sk = selectedSource();
  if (!sk && !uploadedName) { res.innerHTML = '<div class="err">Pick a source or upload a clip.</div>'; return; }
  const fd = new FormData();
  fd.append('source_key', uploadedName ? '' : sk);
  fd.append('upload_name', uploadedName || '');
  fd.append('codec', document.querySelector('input[name=codec]:checked').value);
  fd.append('device', document.getElementById('device').value);
  fd.append('height', document.getElementById('height').value);
  fd.append('target_vmaf', document.getElementById('vmaf').value);
  fd.append('produce_only', document.getElementById('produceOnly').checked ? 'true' : 'false');
  btn.disabled = true; res.innerHTML = '';
  try {
    const r = await fetch('/prepare-rem/run', {method:'POST', body:fd});
    const j = await r.json();
    if (!r.ok) { res.innerHTML = '<div class="err">'+(j.error||'failed')+'</div>'; btn.disabled = false; return; }
    pollJob(j.job_id);
  } catch(e) { res.innerHTML = '<div class="err">'+e+'</div>'; btn.disabled = false; }
}

function iterTable(iters) {
  if (!iters || !iters.length) return '';
  let rows = iters.map(it =>
    '<tr><td>'+it.bps+'k</td><td>'+(it.vmaf==null?'—':it.vmaf)+'</td><td>'+
    (it.delta==null?'':(it.delta>0?'+':'')+it.delta)+'</td></tr>').join('');
  return '<table class="iters"><thead><tr><th>bitrate</th><th>VMAF</th><th>Δtarget</th></tr></thead><tbody>'+rows+'</tbody></table>';
}

function renderResult(d) {
  const o = d.output || {};
  const en = d.energy;
  const pixWarn = o.pix_fmt_ok === false
    ? '<div class="warn">⚠ output is '+((o.stream||{}).pix_fmt||'?')+', not yuv420p — may not play on all TVs</div>' : '';
  let energyHtml = '';
  if (en) {
    energyHtml = '<div class="k">Encode energy</div><div class="v">'+en.delta_e_wh+
      ' Wh · ΔW '+en.delta_w+' W · '+(en.confidence||{}).flag+' ('+en.poll_count+' polls)</div>';
  } else {
    energyHtml = '<div class="k">Encode energy</div><div class="v">— (produce-only)</div>';
  }
  const conv = d.converged ? '✓ converged' : '⚠ best-effort (not within tolerance)';
  document.getElementById('result').innerHTML =
    '<div class="card"><h3>'+ o.filename +'</h3>'+
    '<div class="kv">'+
      '<div class="k">Source</div><div class="v">'+ (d.source||{}).label +'</div>'+
      '<div class="k">Recipe</div><div class="v">'+ d.codec_label +' · '+ d.device +' · '+ d.height +'p</div>'+
      '<div class="k">Target VMAF</div><div class="v">'+ d.target_vmaf +' → achieved '+ (d.achieved_vmaf==null?'?':d.achieved_vmaf) +' · '+ conv +'</div>'+
      '<div class="k">Bitrate</div><div class="v">'+ d.achieved_bitrate_kbps +' kbps</div>'+
      '<div class="k">File</div><div class="v">'+ (o.size_mb||'?') +' MB · concat '+ (o.concat_method||'?') +'</div>'+
      energyHtml +
    '</div>'+
    pixWarn +
    iterTable((d.search||{}).iterations) +
    '<div class="dl">'+
      '<a href="'+ o.download_url +'" download>⬇ Download (Lab)</a>'+
    '</div>'+
    '<div class="share">Direct download (share with Simon — works off-LAN):'+
      '<input type="text" readonly onclick="this.select()" value="'+ location.origin + o.share_url +'"></div>'+
    '<video controls preload="metadata" src="'+ o.download_url +'"></video>'+
    '</div>';
}

function pollJob(jobId) {
  const prog = document.getElementById('progress');
  const btn = document.getElementById('runBtn');
  const tick = async () => {
    try {
      const r = await fetch('/prepare-rem/job/'+jobId);
      const j = await r.json();
      const stage = j.stage || j.status || '…';
      let extra = '';
      if (j.iter_done != null) extra = ' · search '+j.iter_done+'/'+j.iter_max;
      if (j.progress_pct != null) extra += ' · '+j.progress_pct+'%';
      prog.innerHTML = '<div class="note">⏳ '+stage+extra+
        (j.watts!=null ? ' · '+j.watts.toFixed(1)+' W' : '')+'</div>';
      if (j.status === 'done' && j.result) {
        prog.innerHTML = ''; btn.disabled = false; renderResult(j.result); return;
      }
      if (j.status === 'error') {
        prog.innerHTML = '<div class="err">✗ '+(j.error||'error')+'</div>'; btn.disabled = false; return;
      }
      setTimeout(tick, 2000);
    } catch(e) { prog.innerHTML = '<div class="err">'+e+'</div>'; btn.disabled = false; }
  };
  tick();
}
</script>
"""
