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
import time
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

import decode_run
import queue_control
import rig
import ui
from capabilities import requires, RIG_CONTROL
from runtime import job_status as _job_status

router = APIRouter()


def _refuse(e: rig.RigError) -> JSONResponse:
    return JSONResponse({"error": e.reason}, status_code=e.status)


@router.get("/decode", response_class=HTMLResponse,
            dependencies=[Depends(requires(RIG_CONTROL))])
async def decode_page(request: Request):
    options = "".join(
        f'<option value="{k}">{r["label"]}</option>'
        for k, r in decode_run.RECIPES.items())
    return ui.render_page(request, "Decode Rig", styles=_STYLES,
                          body=_BODY.replace("{RECIPE_OPTIONS}", options),
                          tail=_JS)


@router.post("/decode/run", dependencies=[Depends(requires(RIG_CONTROL))])
async def decode_run_start(request: Request, payload: dict):
    key = (payload or {}).get("recipe")
    if key not in decode_run.RECIPES:
        return JSONResponse({"error": f"unknown recipe {key!r}"}, status_code=400)
    recipe = decode_run.RECIPES[key]
    job_id = str(uuid.uuid4())[:8]

    async def coro(job_id=job_id, key=key):
        await decode_run.run_decode_job(job_id, key)

    position = queue_control.enqueue(job_id, "decode", recipe["label"], coro,
                                     request=request, page="/decode")
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."},
                            status_code=429)
    return {"job_id": job_id, "queue_position": position}


@router.get("/decode/job/{job_id}",
            dependencies=[Depends(requires(RIG_CONTROL))])
async def decode_job_status(job_id: str):
    s = _job_status(job_id)
    if s.get("phase_started"):
        s["phase_elapsed_s"] = round(time.monotonic() - s["phase_started"], 1)
        s.pop("phase_started", None)
    return s


@router.get("/decode/status.json",
            dependencies=[Depends(requires(RIG_CONTROL))])
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
.rig-strip { display:flex; flex-wrap:wrap; gap:1.1rem; align-items:flex-start;
             margin-bottom:1rem; }
.rig-col { flex:2 1 32rem; min-width:0; }
.rig-aside { flex:1 1 15rem; }
.rig-connector { width:2px; height:1.05rem; background:var(--border-3);
                 margin-left:2.2rem; }
.rig-stripbox { border:1px dashed var(--border-3); border-radius:6px;
                padding:1.25rem 0.8rem 0.8rem; position:relative; }
.rig-striplabel { position:absolute; top:-0.65rem; left:0.9rem;
                  background:var(--bg); padding:0 0.45rem;
                  color:var(--text-4); font-size:0.72rem; }
.rig-agg { font-size:0.85rem; color:var(--text-3); margin:0.3rem 0 0.9rem; }
.rig-tiles { display:flex; flex-wrap:wrap; gap:0.9rem; }
.rig-tile { border:1px solid var(--border-3); border-radius:6px;
            padding:0.8rem 0.9rem; min-width:15rem; flex:1 1 15rem;
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
.rig-rows td { padding:0.15rem 0.8rem 0.15rem 0; font-size:0.84rem;
               color:var(--text-2); }
"""

_BODY = """
<div class="rig-wrap">
  <h2>Decode rig <span class="rig-badge">Lab</span></h2>
  <div class="rig-agg" id="rig-agg">connecting…</div>
  <div class="rig-err" id="rig-err"></div>

  <div class="rig-strip">
    <div class="rig-col">
      <div class="rig-tile" id="tile-master" style="display:none">
        <h3><span class="rig-dot" id="dot-master"></span>Master (Shelly)
            <span class="rig-badge">strip</span></h3>
        <div class="rig-w" id="w-master">—</div>
        <div class="rig-detail" id="d-master"></div>
        <button class="rig-btn" id="btn-master" onclick="masterToggle()">…</button>
      </div>
      <div class="rig-connector" id="rig-connector" style="display:none"></div>
      <div class="rig-stripbox">
        <span class="rig-striplabel">⏚ power strip — Lab-A · Lab-B · Lab-D</span>
        <div class="rig-tiles" id="rig-tiles"></div>
      </div>
    </div>
    <div class="rig-tile rig-aside" id="tile-monitor">
      <h3><span class="rig-dot" id="dot-monitor"></span>Monitor <span
          class="rig-badge">Lab-E</span> <span class="rig-badge">not on strip</span></h3>
      <div class="rig-w" id="w-monitor">—</div>
      <div class="rig-detail" id="d-monitor"></div>
      <button class="rig-btn" id="btn-monitor" onclick="monitorToggle()">…</button>
    </div>
  </div>

  <div class="rig-run">
    <h3>Run a recipe</h3>
    <div class="rig-runrow">
      <select id="recipe">{RECIPE_OPTIONS}</select>
      <button class="rig-btn" id="btn-run" onclick="runRecipe()">Run</button>
    </div>
    <div class="rig-detail" style="margin-top:0.3rem">Powers the device if
      needed, stages clips, then runs the July decode protocol (settle →
      baseline → play → confidence). Runs queue behind any measurement in
      progress.</div>
    <div id="run-status" style="margin-top:0.7rem"></div>
  </div>

  <div class="rig-note">
    Boxes are <b>off by default</b>. The screen auto-switches to the single
    powered device — run one box at a time for display work. “Off” is always a
    graceful shutdown (SSH/ADB) before the relay cut. The monitor has its own
    wall socket — cutting the strip never darkens the screen. Boot
    expectations: Pi 5 ≈ 29 s; Pi 400 and Google TV get measured on first use.
  </div>
</div>
"""

_JS = """
<script>
var RIG_LAST = null;

function dotClass(dev) {
  if (dev.state === 'ready' || dev.state === 'busy') return 'green';
  if (dev.state === 'off') return 'red';
  if (dev.state === 'stuck') return 'red';
  if (dev.state === 'unpowered' || dev.state === 'unreachable') return 'grey';
  return 'orange';   // powering / booting / stopping
}

function fmtW(w) { return (w === null || w === undefined) ? '—' : w.toFixed(w < 10 ? 2 : 1) + ' W'; }

function deviceTile(name, dev) {
  var pct = null;
  if ((dev.state === 'booting' || dev.state === 'powering') && dev.elapsed_s != null)
    pct = Math.min(97, 100 * dev.elapsed_s / dev.expected_s);
  var busy = dev.busy ? ' <span class="rig-badge">job running</span>' : '';
  var stuck = dev.state === 'stuck' ? ' <span class="rig-badge" style="color:#ffaa00">stuck</span>' : '';
  var h = '<div class="rig-tile"><h3><span class="rig-dot ' + dotClass(dev) + '"></span>'
        + dev.label + ' <span class="rig-badge">' + dev.plug_name + '</span>' + busy + stuck + '</h3>'
        + '<div class="rig-w">' + fmtW(dev.watts) + '</div>';
  if (pct !== null)
    h += '<div class="rig-bar"><div style="width:' + pct.toFixed(0) + '%"></div></div>'
       + '<div class="rig-detail">' + Math.round(dev.elapsed_s) + ' / ~' + dev.expected_s + ' s — ' + (dev.detail || '') + '</div>';
  else
    h += '<div class="rig-detail">' + (dev.state + (dev.detail ? ' · ' + dev.detail : '')) + '</div>';

  if (dev.state === 'off')
    h += '<button class="rig-btn" onclick="devPower(\\'' + name + '\\',\\'on\\')">On</button>';
  else if (dev.state === 'ready')
    h += '<button class="rig-btn" onclick="devPower(\\'' + name + '\\',\\'off\\')">Off</button>';
  else if (dev.state === 'stuck')
    h += '<button class="rig-btn warn" onclick="devPower(\\'' + name + '\\',\\'cycle\\')">Power-cycle</button>'
       + ' <button class="rig-btn" onclick="devPower(\\'' + name + '\\',\\'off\\')">Force off</button>';
  else if (dev.state === 'booting' || dev.state === 'powering')
    h += '<button class="rig-btn" onclick="devPower(\\'' + name + '\\',\\'off\\')">Cancel</button>';
  h += '</div>';
  return h;
}

function render(s) {
  RIG_LAST = s;
  var agg = 'total ' + fmtW(s.total_w);
  if (s.saving_note) agg = s.saving_note;
  if (s.age_s !== null && s.age_s > 30) agg += ' · ⚠ data ' + Math.round(s.age_s) + 's old';
  document.getElementById('rig-agg').textContent = agg;

  var m = s.master;
  var tile = document.getElementById('tile-master');
  document.getElementById('rig-connector').style.display = m.configured ? '' : 'none';
  if (m.configured) {
    tile.style.display = '';
    var dot = document.getElementById('dot-master');
    var btn = document.getElementById('btn-master');
    document.getElementById('w-master').textContent = fmtW(m.apower_w);
    if (!m.switchable) {
      // Metering-only Shelly (Plug PM): strip total + a SOFTWARE master —
      // "All off" gracefully stops every powered box. A relay-equipped
      // Shelly at the same IP upgrades this to a true strip switch.
      var anyUp = false;
      for (var dn in s.devices) {
        var st = s.devices[dn].state;
        if (st !== 'off' && st !== 'unpowered' && st !== 'unreachable') anyUp = true;
      }
      dot.className = 'rig-dot ' + (!m.reachable ? 'grey' : 'green');
      document.getElementById('d-master').textContent =
        !m.reachable ? 'not answering'
          : 'strip meter (no relay) — All off gracefully stops every powered box';
      btn.textContent = 'All off';
      btn.disabled = !anyUp;
      btn.title = anyUp ? 'Graceful shutdown of every powered box, then relays off'
                        : 'Nothing is powered';
    } else {
      dot.className = 'rig-dot ' + (!m.reachable ? 'grey' : (m.on ? 'green' : 'red'));
      document.getElementById('d-master').textContent =
        !m.reachable ? 'not answering' : (m.on ? 'strip live' : 'rig cold');
      btn.textContent = m.on ? 'Rig off' : 'Rig on';
      btn.disabled = !m.reachable;
      btn.title = '';
    }
  } else tile.style.display = 'none';

  var mon = s.monitor;
  document.getElementById('dot-monitor').className =
    'rig-dot ' + (!mon.reachable ? 'grey' : (mon.on ? 'green' : 'red'));
  document.getElementById('w-monitor').textContent = fmtW(mon.watts);
  document.getElementById('d-monitor').textContent =
    !mon.reachable ? 'not answering'
      : (mon.in_use_hint ? 'displaying — may be in use' : (mon.on ? 'powered' : 'off'));
  var mb = document.getElementById('btn-monitor');
  mb.textContent = mon.on ? 'Off' : 'On';
  mb.disabled = !mon.reachable;

  var tiles = '';
  for (var name in s.devices) tiles += deviceTile(name, s.devices[name]);
  document.getElementById('rig-tiles').innerHTML = tiles;
}

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

async function tick() {
  try {
    var r = await fetch('/decode/status.json');
    if (r.ok) render(await r.json());
  } catch (e) {}
}
tick();
setInterval(tick, 2500);

// --- Recipe runs ---
var PHASE_LABELS = {settle:'Settle', baseline:'Baseline', starting:'Start playback',
                    sampling:'Sampling', finishing:'Confidence'};

function stageRow(icon, color, label, extra) {
  return '<div class="rig-stage"><span style="color:' + color + ';width:1rem">'
       + icon + '</span><span style="color:' + color + '">' + label + '</span>'
       + (extra || '') + '</div>';
}

function renderJob(j) {
  var el = document.getElementById('run-status');
  if (j.status === 'error') {
    el.innerHTML = '<div class="rig-err">✗ ' + (j.error || 'failed') + '</div>';
    return true;
  }
  if (j.stage === 'queued') {
    el.innerHTML = stageRow('…', 'var(--warn)',
      'queued — position ' + (j.queue_position || '?')); return false;
  }
  var h = '';
  if (j.row && j.row_n > 1) h += '<div class="rig-detail">row ' + j.row + ' / ' + j.row_n + '</div>';
  if (j.status === 'done') {
    h += stageRow('✓', 'var(--accent)', 'done — result saved');
    var rows = (j.result && j.result.runs) || [];
    if (rows.length) {
      h += '<table class="rig-rows">';
      for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        if (r.error) { h += '<tr><td>' + r.run + '</td><td colspan=3>✗ ' + r.error + '</td></tr>'; continue; }
        var flag = (r.confidence && r.confidence.flag) || '';
        h += '<tr><td>' + r.run + '</td><td>base ' + r.w_base + ' W</td>'
           + '<td>task ' + r.w_task + ' W</td><td><b>ΔW ' + (r.delta_w >= 0 ? '+' : '')
           + r.delta_w + '</b> ' + flag + '</td></tr>';
      }
      h += '</table>';
    }
    el.innerHTML = h;
    return true;
  }
  // running: walk phases
  var names = ['device', 'staging'].concat((j.phases || []).map(function(p){ return p[0]; }));
  var labels = {device: 'Power device', staging: 'Stage clips'};
  var cur = names.indexOf(j.stage);
  for (var i = 0; i < names.length; i++) {
    var n = names[i], lbl = labels[n] || PHASE_LABELS[n] || n;
    if (i < cur) h += stageRow('✓', 'var(--accent)', lbl);
    else if (i === cur) {
      var extra = '';
      var ph = (j.phases || []).filter(function(p){ return p[0] === n; })[0];
      if (ph && j.phase_elapsed_s != null) {
        var pct = Math.min(98, 100 * j.phase_elapsed_s / ph[1]);
        extra = '<span class="rig-detail" style="margin-left:0.5rem">'
              + Math.round(j.phase_elapsed_s) + ' / ~' + ph[1] + ' s</span>'
              + '<span style="flex:1;max-width:10rem;margin-left:0.6rem" class="rig-bar">'
              + '<span style="display:block;height:100%;width:' + pct.toFixed(0)
              + '%;background:var(--warn)"></span></span>';
      }
      h += stageRow('▶', 'var(--warn)', lbl, extra);
    } else h += stageRow('·', 'var(--text-5)', lbl);
  }
  if (j.detail) h += '<div class="rig-detail">' + j.detail + '</div>';
  el.innerHTML = h;
  return false;
}

async function pollJob(id) {
  try {
    var r = await fetch('/decode/job/' + id);
    var j = await r.json();
    if (renderJob(j)) { document.getElementById('btn-run').disabled = false; return; }
  } catch (e) {}
  setTimeout(function(){ pollJob(id); }, 2000);
}

async function runRecipe() {
  var key = document.getElementById('recipe').value;
  document.getElementById('btn-run').disabled = true;
  try {
    var r = await fetch('/decode/run', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({recipe:key})});
    var j = await r.json();
    if (!r.ok) { err(j.error || ('HTTP ' + r.status));
                 document.getElementById('btn-run').disabled = false; return; }
    pollJob(j.job_id);
  } catch (e) { err(String(e)); document.getElementById('btn-run').disabled = false; }
}
</script>
"""
