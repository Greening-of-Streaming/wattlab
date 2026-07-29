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
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

import rig
import ui
from capabilities import requires, RIG_CONTROL

router = APIRouter()


def _refuse(e: rig.RigError) -> JSONResponse:
    return JSONResponse({"error": e.reason}, status_code=e.status)


@router.get("/decode", response_class=HTMLResponse,
            dependencies=[Depends(requires(RIG_CONTROL))])
async def decode_page(request: Request):
    return ui.render_page(request, "Decode Rig",
                          styles=_STYLES, body=_BODY, tail=_JS)


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
.rig-wrap { max-width: 62rem; margin: 0 auto; }
.rig-strip { display:flex; flex-wrap:wrap; gap:0.8rem; align-items:stretch;
             margin-bottom:1rem; }
.rig-agg { font-size:0.85rem; color:var(--muted,#9aa); margin:0.3rem 0 0.9rem; }
.rig-tiles { display:flex; flex-wrap:wrap; gap:0.9rem; }
.rig-tile { border:1px solid #2a2f36; border-radius:6px; padding:0.8rem 0.9rem;
            min-width:15rem; flex:1 1 15rem; background:#101418;
            font-size:0.9rem; }
.rig-tile h3 { margin:0 0 0.45rem; font-size:0.95rem; display:flex;
               align-items:center; gap:0.5rem; }
.rig-dot { display:inline-block; width:0.75rem; height:0.75rem;
           border-radius:50%; background:#444; flex:none; }
.rig-dot.red { background:#e14b4b; }
.rig-dot.orange { background:#ffaa00; animation:rigpulse 1.4s infinite; }
.rig-dot.green { background:#00d98a; }
.rig-dot.grey { background:#3a4048; }
@keyframes rigpulse { 50% { opacity:0.35; } }
.rig-w { font-size:1.25rem; font-weight:600; margin:0.15rem 0; }
.rig-detail { color:var(--muted,#9aa); font-size:0.78rem; min-height:1.1rem; }
.rig-bar { height:0.45rem; background:#1c2127; border-radius:3px;
           overflow:hidden; margin:0.4rem 0; }
.rig-bar > div { height:100%; background:#ffaa00; transition:width 1s linear; }
.rig-btn { background:none; border:1px solid #3a4048; color:#cfd6dd;
           font-family:inherit; font-size:0.82rem; padding:0.35rem 0.9rem;
           border-radius:4px; cursor:pointer; margin-top:0.5rem; }
.rig-btn:hover { border-color:#00d98a; }
.rig-btn:disabled { opacity:0.35; cursor:default; }
.rig-btn.warn { border-color:#7a5500; color:#ffaa00; }
.rig-note { font-size:0.78rem; color:var(--muted,#9aa); margin-top:1.1rem;
            line-height:1.5; }
.rig-badge { font-size:0.68rem; border:1px solid #3a4048; border-radius:3px;
             padding:0 0.35rem; color:var(--muted,#9aa); }
.rig-err { color:#e14b4b; font-size:0.8rem; min-height:1.1rem; margin:0.4rem 0; }
"""

_BODY = """
<div class="rig-wrap">
  <h2>Decode rig <span class="rig-badge">Lab</span></h2>
  <div class="rig-agg" id="rig-agg">connecting…</div>
  <div class="rig-err" id="rig-err"></div>

  <div class="rig-strip">
    <div class="rig-tile" id="tile-master" style="display:none">
      <h3><span class="rig-dot" id="dot-master"></span>Master (Shelly)</h3>
      <div class="rig-w" id="w-master">—</div>
      <div class="rig-detail" id="d-master"></div>
      <button class="rig-btn" id="btn-master" onclick="masterToggle()">…</button>
    </div>
    <div class="rig-tile" id="tile-monitor">
      <h3><span class="rig-dot" id="dot-monitor"></span>Monitor <span
          class="rig-badge">Lab-E</span></h3>
      <div class="rig-w" id="w-monitor">—</div>
      <div class="rig-detail" id="d-monitor"></div>
      <button class="rig-btn" id="btn-monitor" onclick="monitorToggle()">…</button>
    </div>
  </div>

  <div class="rig-tiles" id="rig-tiles"></div>

  <div class="rig-note">
    Boxes are <b>off by default</b>. The screen auto-switches to the single
    powered device — run one box at a time for display work. “Off” is always a
    graceful shutdown (SSH/ADB) before the relay cut. Boot expectations:
    Pi 5 ≈ 29 s; Pi 400 and Google TV get measured on first use.
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
  if (m.configured) {
    tile.style.display = '';
    var dot = document.getElementById('dot-master');
    var btn = document.getElementById('btn-master');
    document.getElementById('w-master').textContent = fmtW(m.apower_w);
    if (!m.switchable) {
      // Metering-only Shelly (Plug PM): strip total, no relay to drive.
      dot.className = 'rig-dot ' + (!m.reachable ? 'grey' : 'green');
      document.getElementById('d-master').textContent =
        !m.reachable ? 'not answering'
          : 'strip meter (no relay) — Tapo overhead visible when boxes are off';
      btn.style.display = 'none';
    } else {
      btn.style.display = '';
      dot.className = 'rig-dot ' + (!m.reachable ? 'grey' : (m.on ? 'green' : 'red'));
      document.getElementById('d-master').textContent =
        !m.reachable ? 'not answering' : (m.on ? 'strip live' : 'rig cold');
      btn.textContent = m.on ? 'Rig off' : 'Rig on';
      btn.disabled = !m.reachable;
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
  var on = RIG_LAST && RIG_LAST.master.on;
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
</script>
"""
