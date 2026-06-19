"""
Transcode-budget calculator — DEMO (CR-003 × CR-045 V2 exploration).

A conference-facing "what fits in your energy budget?" page. The energy budget
is the dominant input; the constraint controls (VMAF floor, codec, content
complexity, output unit) decide which delivery recipes *qualify*, and the budget
scales each qualifying recipe into hours of throughput. That unifies the two
operator questions:
  - "given X Wh, how much video can I push?" (the headline), and
  - "what are my options?" (Dom's framing — the ranked recipe bars).

⚠ ILLUSTRATIVE DATA. Every Wh/min and bitrate here is hand-authored placeholder
shaped to tell the *expected* story (hardware encodes cost far less energy; CPU
AV1 is the most energy-hungry encode; higher VMAF and higher content complexity
both cost more; ASIC is the projected floor). NOTHING on this page is measured.
The fixture's schema IS the contract a real calibration table will fill — see
_demo_fixture(): per (device, codec) we need, across a VMAF-target grid and per
content-complexity column, the bitrate that hits the floor and the resulting
Wh per minute of source (summed over the ABR ladder), plus a max-achievable
VMAF ceiling. Swap _demo_fixture() for a loader over the measured artifact and
the page is real.

Reversible: this whole module + its one line in main.py's include loop are the
only places that touch the topic. No measurement-spine code, no settings, no
persistence, no schema change.
"""
import glob
import json
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

import ui
import audience
import budget_data
from capabilities import requires, can, PUBLIC_PAGE, VARIANCE_RUN

router = APIRouter()

# VMAF floors the slider snaps to. Discrete + measured-only is the honest move:
# we never silently interpolate a quality the calibration didn't actually hit.
_VMAF_TARGETS = [88, 90, 92, 94, 96]
# Bitrate / energy multipliers vs the VMAF-92 anchor — steep at the top end to
# show diminishing returns (the last few VMAF points cost a lot of bits/energy).
_BR_VMAF_MULT = [0.60, 0.78, 1.00, 1.45, 2.40]
_WH_VMAF_MULT = [0.70, 0.85, 1.00, 1.30, 1.80]
# High-complexity content (Meridian) vs low (BBB): more bits to push, more
# compute to find them.
_COMPLEXITY = {"low": {"br": 1.0, "wh": 1.0}, "high": {"br": 1.7, "wh": 1.5}}
# Single top rendition as a fraction of the full ABR ladder's cost.
_SINGLE_FRACTION = 0.55


def _demo_fixture() -> dict:
    """Hand-authored illustrative recipe table. Anchors are @ VMAF-92, low
    complexity, full 4-rung ladder, per minute of source.

    The three nested dicts are the only "data" — everything else is generated
    so the shape (and the real-calibration contract) stays obvious."""
    # Wh per minute of source (full ladder). On CPU, codec choice swings energy
    # hugely (SVT-AV1 is slow); on hardware, codec barely moves the encode cost.
    wh = {
        "cpu":  {"h264": 1.20, "h265": 2.40, "av1": 3.60},
        "gpu":  {"h264": 0.42, "h265": 0.50, "av1": 0.62},
        "asic": {"h264": 0.16, "h265": 0.18, "av1": 0.22},
    }
    # Bitrate (kbps) of the 1080p rung needed to hit VMAF 92. Hardware encoders
    # need a touch more bitrate for the same quality.
    br = {
        "cpu":  {"h264": 6000, "h265": 3500, "av1": 2500},
        "gpu":  {"h264": 7500, "h265": 4400, "av1": 3200},
        "asic": {"h264": 7800, "h265": 4600, "av1": 3300},
    }
    # Max VMAF the recipe can actually reach (floors above this disqualify it).
    maxv = {
        "cpu":  {"h264": 95, "h265": 98, "av1": 98},
        "gpu":  {"h264": 93, "h265": 97, "av1": 96},
        "asic": {"h264": 93, "h265": 97, "av1": 96},
    }
    # Devices are generic HARDWARE CLASSES, not specific models (Dom 2026-06-18):
    # listing every card would run to hundreds; generic by default, with named
    # models available as a comparison listing (a sponsorship option for GoS).
    dev_label = {
        "cpu":  "CPU · general-purpose cores",
        "gpu":  "GPU · hardware encoder",
        "asic": "ASIC / FPGA · dedicated encoder",
    }
    dev_avail = {"cpu": (True, False), "gpu": (True, False), "asic": (False, True)}
    codec_label = {"h264": "H.264", "h265": "H.265", "av1": "AV1"}

    recipes = []
    for dev in ("cpu", "gpu", "asic"):
        available, projected = dev_avail[dev]
        for codec in ("h264", "h265", "av1"):
            base_wh, base_br = wh[dev][codec], br[dev][codec]
            recipes.append({
                "device": dev,
                "device_label": dev_label[dev],
                "codec": codec,
                "codec_label": codec_label[codec],
                "max_vmaf": maxv[dev][codec],
                "available": available,
                "projected": projected,
                "wh_low":  [round(base_wh * m * _COMPLEXITY["low"]["wh"], 3) for m in _WH_VMAF_MULT],
                "wh_high": [round(base_wh * m * _COMPLEXITY["high"]["wh"], 3) for m in _WH_VMAF_MULT],
                "br_low":  [round(base_br * m * _COMPLEXITY["low"]["br"]) for m in _BR_VMAF_MULT],
                "br_high": [round(base_br * m * _COMPLEXITY["high"]["br"]) for m in _BR_VMAF_MULT],
            })
    return {
        "meta": {
            "illustrative": True,
            "ladder": "4-rung ABR (1080p / 720p / 540p / 360p)",
            "unit": "Wh per minute of source · full ladder",
            "clip_low": "Meridian (soft live-action — low SI/TI)",
            "clip_high": "Big Buck Bunny (sharp 3D animation — high SI/TI)",
            "single_fraction": _SINGLE_FRACTION,
        },
        "vmaf_targets": _VMAF_TARGETS,
        "recipes": recipes,
        # Generic classes shown by default; each expands to example hardware.
        # Named models are an optional comparison listing (GoS sponsorship).
        "classes": [
            {"key": "cpu", "label": "CPU · general-purpose cores",
             "spec": "software encode on x86 / ARM cores",
             "examples": ["8-core desktop", "24-core workstation (GoS1 bench)", "64-core server"]},
            {"key": "gpu", "label": "GPU · hardware encoder",
             "spec": "fixed-function encode blocks (NVENC / AMF / QSV class)",
             "examples": ["consumer GPU", "datacenter GPU", "integrated GPU"]},
            {"key": "asic", "label": "ASIC / FPGA · dedicated encoder",
             "spec": "dedicated transcode silicon (projected — not yet on the bench)",
             "examples": ["ASIC transcode card", "FPGA transcode card", "transcode appliance"]},
        ],
        "sponsorship_note": ("Classes are generic by default. A specific named card or CPU "
                             "can be measured and listed alongside its class — a comparison "
                             "listing GoS can offer to vendors."),
    }


_STYLES = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: monospace; background: var(--bg); color: var(--text);
           max-width: 980px; margin: 0 auto; padding: 2rem 1rem; }
    h1 { color: var(--accent); margin-bottom: 0.25rem; font-size: 1.45rem; }
    .subtitle { color: var(--text-3); font-size: 0.82rem; margin-bottom: 1.25rem;
                letter-spacing: 0.04em; }
    .demo-band { background: rgba(255,170,0,0.08); border: 1px solid #aa7700;
                 color: #ffcc66; padding: 0.7rem 1rem; margin-bottom: 1.5rem;
                 font-size: 0.82rem; line-height: 1.5; border-radius: 4px; }
    .measured-band { background: rgba(0,255,153,0.07); border: 1px solid #00995e;
                 color: #8fffd0; padding: 0.7rem 1rem; margin-bottom: 1.5rem;
                 font-size: 0.82rem; line-height: 1.5; border-radius: 4px; }
    .budget-box { text-align: center; margin: 1.5rem 0 1rem; }
    .budget-box label { display: block; color: var(--text-3); font-size: 0.78rem;
                        text-transform: uppercase; letter-spacing: 0.08em;
                        margin-bottom: 0.4rem; }
    .budget-box input { font-family: monospace; font-size: 2.6rem; font-weight: 700;
                        background: transparent; border: none; border-bottom: 2px solid var(--accent);
                        color: var(--accent); text-align: center; width: 8ch; padding: 0.1rem; }
    .budget-box .unit { color: var(--text-3); font-size: 1.4rem; margin-left: 0.3rem; }
    .controls { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
                gap: 1rem 1.5rem; padding: 1rem 1.2rem; border: 1px solid var(--border);
                border-radius: 6px; margin-bottom: 1.5rem; }
    .ctl label.h { display: block; color: var(--text-4); font-size: 0.66rem;
                   text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.45rem; }
    .ctl input[type=range] { width: 100%; accent-color: var(--accent); }
    .vmaf-read { color: var(--accent); font-weight: 700; font-size: 1.1rem; }
    .seg { display: inline-flex; border: 1px solid var(--border-2); border-radius: 4px; overflow: hidden; }
    .seg button { font-family: monospace; background: transparent; color: var(--text-3);
                  border: none; padding: 0.3rem 0.7rem; cursor: pointer; font-size: 0.76rem; }
    .seg button.on { background: var(--accent); color: #001a10; font-weight: 700; }
    .seg button:disabled { color: var(--text-4); cursor: not-allowed; opacity: 0.5; }
    .chk { display: block; color: var(--text-2); font-size: 0.82rem; margin-bottom: 0.3rem; cursor: pointer; }
    .chk input { accent-color: var(--accent); margin-right: 0.4rem; }
    .codec-axis { display: flex; align-items: center; flex-wrap: wrap; gap: 0.25rem 1.1rem;
                  margin-bottom: 1.5rem; padding: 0 0.2rem; }
    .codec-axis .h { display: block; width: 100%; color: var(--text-4); font-size: 0.66rem;
                     text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.3rem; }
    .codec-axis .chk { display: inline-flex; align-items: center; margin-bottom: 0; }
    .codec-hint { color: var(--text-5); font-size: 0.72rem; font-style: italic; }
    .headline { font-size: 1.05rem; line-height: 1.5; border-left: 2px solid var(--accent);
                padding: 0.6rem 0 0.6rem 0.9rem; margin-bottom: 1.4rem; color: var(--text); }
    .headline b { color: var(--accent); }
    .bars { display: flex; flex-direction: column; gap: 0.55rem; margin-bottom: 1.5rem; }
    .bar-row { display: grid; grid-template-columns: 200px 1fr; gap: 0.8rem; align-items: center; }
    .bar-row .name { font-size: 0.78rem; color: var(--text-2); }
    .bar-row .name small { display: block; color: var(--text-4); font-size: 0.66rem; }
    .bar-track { background: rgba(255,255,255,0.04); border-radius: 3px; height: 30px; position: relative; }
    .bar-fill { background: var(--accent); height: 100%; border-radius: 3px; min-width: 2px;
                transition: width 0.25s ease; display: flex; align-items: center; overflow: hidden; }
    .bar-fill span { color: #001a10; font-size: 0.72rem; font-weight: 700; padding-left: 0.5rem; white-space: nowrap; }
    .bar-lbl-out { position: absolute; top: 0; line-height: 30px; color: var(--text-2);
                   font-size: 0.72rem; font-weight: 700; white-space: nowrap; }
    .bar-row.projected .bar-fill { background: repeating-linear-gradient(45deg,#0a5,#0a5 6px,#084 6px,#084 12px); }
    .bar-row.projected .name, .bar-row.dq .name { color: var(--text-4); }
    .bar-row.dq .bar-track { background: rgba(255,255,255,0.02); }
    .bar-row.dq .reason { color: #cc6666; font-size: 0.72rem; padding-left: 0.5rem; line-height: 30px; }
    .sec { color: var(--text-3); font-size: 0.85rem; margin: 0.5rem 0 0.4rem; }
    .class-help { color: var(--text-4); font-size: 0.74rem; margin-bottom: 0.7rem; line-height: 1.5; }
    .classes { display: flex; flex-direction: column; gap: 0.5rem; margin-bottom: 0.8rem; }
    details.cls { border: 1px solid var(--border); border-radius: 5px; padding: 0.5rem 0.8rem; }
    details.cls summary { cursor: pointer; color: var(--text-2); font-size: 0.82rem; }
    details.cls summary small { display: block; color: var(--text-4); font-size: 0.68rem; margin-top: 0.15rem; }
    details.cls ul { list-style: none; margin: 0.5rem 0 0.1rem 0.4rem; }
    details.cls li { color: var(--text-3); font-size: 0.76rem; padding: 0.15rem 0; }
    details.cls li.named { color: var(--accent); font-style: italic; }
    .sponsor { color: var(--text-4); font-size: 0.74rem; line-height: 1.5; font-style: italic;
               margin-bottom: 1.2rem; }
    .footer-note { color: var(--text-4); font-size: 0.76rem; line-height: 1.6;
                   border-left: 2px solid var(--border-2); padding-left: 0.9rem; margin-top: 2.5rem; }
"""


def _band(fix: dict) -> str:
    """The data-provenance banner — illustrative vs measured."""
    meta = fix.get("meta", {})
    if meta.get("illustrative", True):
        return """
<div class="demo-band">
  <strong>Illustrative demo.</strong> Every figure below is a hand-authored placeholder
  shaped to show the expected pattern &mdash; <em>nothing here is measured yet</em>. The real
  page will read a calibration table measured under OWL's standard
  <a href="/methodology#energy-budget" style="color:#ffcc66">methodology</a>, re-runnable whenever the encode
  hardware changes (ASIC / FPGA shown as a projected class).
</div>"""
    hw = meta.get("hardware", "this bench")
    when = (meta.get("measured_on") or "")[:10]
    return f"""
<div class="measured-band">
  <strong>Measured.</strong> CPU &amp; GPU figures measured on {hw} ({when}) under OWL's
  <a href="/methodology#energy-budget" style="color:#66ffcc">methodology</a> &mdash;
  <strong>1080p single rendition</strong> (not a full ABR ladder), per minute of source.
  Curves interpolate the measured VMAF-vs-bitrate points; the ASIC / FPGA class remains a
  <em>projected</em> placeholder until that hardware is on the bench.
</div>"""


def _body(fix: dict) -> str:
    fix_json = json.dumps(fix)
    return f"""
<h1>Transcode budget &middot; what fits in your energy budget?</h1>
<div class="subtitle">CR-003 (iso-energy) &times; CR-045 V2 (target VMAF) &middot; companion to <a href="/video" style="color:var(--accent)">/video</a></div>
{_band(fix)}

<div class="budget-box">
  <label for="budget">energy budget</label>
  <input id="budget" type="number" min="1" step="10" value="1000" />
  <span class="unit">Wh</span>
</div>

<div class="controls">
  <div class="ctl">
    <label class="h">quality floor (VMAF, non-negotiable)</label>
    <input id="vmaf" type="range" min="0" max="4" step="1" value="2" />
    <div>&ge; <span id="vmafRead" class="vmaf-read">92</span></div>
  </div>
  <div class="ctl">
    <label class="h">spatial complexity</label>
    <div class="seg" id="complexity">
      <button data-v="low" class="on">Low &middot; Meridian</button>
      <button data-v="high">High &middot; BBB</button>
    </div>
  </div>
  <div class="ctl">
    <label class="h">temporal complexity</label>
    <div class="seg">
      <button class="on">Standard</button>
      <button disabled title="sports clip — not implemented yet">High &middot; sport (soon)</button>
    </div>
  </div>
  <div class="ctl">
    <label class="h">output unit</label>
    <div class="seg" id="unit">
      <button data-v="ladder" class="on">Full ABR ladder</button>
      <button data-v="single">1080p only</button>
    </div>
  </div>
</div>

<div class="codec-axis">
  <label class="h">compare codecs</label>
  <label class="chk"><input type="checkbox" class="codec" value="h264" checked /> H.264</label>
  <label class="chk"><input type="checkbox" class="codec" value="h265" checked /> H.265</label>
  <label class="chk"><input type="checkbox" class="codec" value="av1" checked /> AV1</label>
  <span class="codec-hint">a comparison axis, not a constraint &mdash; toggle to see codecs side by side</span>
</div>

<div id="headline" class="headline"></div>
<div id="bars" class="bars"></div>

<h2 class="sec">Device classes</h2>
<div class="class-help">Generic hardware classes &mdash; click a class to see example hardware. Specific named models can be measured and listed as a comparison.</div>
<div id="classes" class="classes"></div>
<div id="sponsor" class="sponsor"></div>

<div class="footer-note" id="footnote"></div>

<script>
const FIX = {fix_json};
const state = {{ budget: 1000, vmafIdx: 2, complexity: 'low', unit: 'ladder',
                 codecs: {{ h264: true, h265: true, av1: true }} }};

const fmtH = h => h >= 100 ? Math.round(h) : h >= 10 ? h.toFixed(1) : h.toFixed(2);
function unitName() {{
  if (state.unit === 'single') return '1080p rendition';
  if (FIX.meta.illustrative === false) return FIX.meta.have_ladder ? 'full ABR ladder' : '1080p rendition';
  return 'full ladder';
}}

function recipeCalc(r) {{
  const i = state.vmafIdx;
  const floor = FIX.vmaf_targets[i];
  const whArr = state.complexity === 'low' ? r.wh_low : r.wh_high;
  const brArr = state.complexity === 'low' ? r.br_low : r.br_high;
  const br = brArr[i], whBase = whArr[i];
  // Reachable for THIS complexity: the ceiling clears the floor AND the measured
  // curve actually produced a point (null = target not hit for this content).
  const qualifies = floor <= r.max_vmaf && br != null && whBase != null;
  let wh = null;
  if (qualifies) {{
    if (FIX.meta.illustrative === false) {{
      // Measured: whBase is the 1080p top rung. Full ladder ADDS the measured lower
      // rungs (fixed-bitrate); single = top rung only.
      const add = (state.complexity === 'low' ? r.ladder_add_low : r.ladder_add_high) || 0;
      wh = whBase + (state.unit === 'ladder' ? add : 0);
    }} else {{
      // Illustrative: the fixture anchor IS the full ladder; single is a fraction.
      const unitF = state.unit === 'single' ? (FIX.meta.single_fraction == null ? 1 : FIX.meta.single_fraction) : 1;
      wh = whBase * unitF;
    }}
  }}
  const hours = qualifies && state.budget > 0 && wh > 0 ? state.budget / wh / 60 : 0;
  return {{ floor, qualifies, wh, br, hours }};
}}

function render() {{
  const floor = FIX.vmaf_targets[state.vmafIdx];
  document.getElementById('vmafRead').textContent = floor;

  const rows = FIX.recipes
    .filter(r => state.codecs[r.codec])
    .map(r => ({{ r, c: recipeCalc(r) }}));

  // rank: qualifying & available by hours desc, then projected, then disqualified
  const rank = x => (!x.c.qualifies ? 2 : x.r.projected ? 1 : 0);
  rows.sort((a, b) => rank(a) - rank(b) || b.c.hours - a.c.hours);

  const maxHours = Math.max(1, ...rows.filter(x => x.c.qualifies).map(x => x.c.hours));

  // headline = best qualifying *available* recipe
  const best = rows.find(x => x.c.qualifies && x.r.available);
  const hl = document.getElementById('headline');
  if (best) {{
    hl.innerHTML = `<b>${{state.budget}} Wh</b> buys you about <b>${{fmtH(best.c.hours)}} hours</b> of `
      + `VMAF-${{floor}} video &mdash; on <b>${{best.r.device_label}}</b> with ${{best.r.codec_label}} `
      + `(${{best.c.wh.toFixed(2)}} Wh/min, ${{unitName()}}).`;
  }} else {{
    hl.innerHTML = `No <em>available</em> encoder can reach VMAF ${{floor}} for this content `
      + `&mdash; loosen the floor or wait for the projected hardware.`;
  }}

  const bars = rows.map(({{ r, c }}) => {{
    const cls = !c.qualifies ? 'dq' : r.projected ? 'projected' : '';
    const name = `<div class="name">${{r.device_label}}<small>${{r.codec_label}}`
      + (r.projected ? ' · projected' : '') + `</small></div>`;
    if (!c.qualifies) {{
      return `<div class="bar-row dq">${{name}}<div class="reason">can't reach VMAF ${{c.floor}} `
        + `(max about ${{r.max_vmaf}})</div></div>`;
    }}
    const w = Math.max(2, (c.hours / maxHours) * 100);
    const lbl = `${{fmtH(c.hours)}} h · ${{c.wh.toFixed(2)}} Wh/min · ${{c.br}} kbps`;
    // Label inside the fill (dark on accent) only when the bar is wide enough to
    // hold it; otherwise outside, right of the fill (light on the dark track) so it
    // never becomes dark-text-on-dark-background on the shorter bars.
    const inside = w >= 45;
    const fill = `<div class="bar-fill" style="width:${{w}}%">${{inside ? `<span>${{lbl}}</span>` : ''}}</div>`;
    const out = inside ? '' : `<span class="bar-lbl-out" style="left:calc(${{w}}% + 6px)">${{lbl}}</span>`;
    return `<div class="bar-row ${{cls}}">${{name}}<div class="bar-track">${{fill}}${{out}}</div></div>`;
  }}).join('');
  document.getElementById('bars').innerHTML = bars;
}}

document.getElementById('budget').addEventListener('input', e => {{
  state.budget = parseFloat(e.target.value) || 0; render();
}});
document.getElementById('vmaf').addEventListener('input', e => {{
  state.vmafIdx = parseInt(e.target.value, 10); render();
}});
document.querySelectorAll('.codec').forEach(cb => cb.addEventListener('change', e => {{
  state.codecs[e.target.value] = e.target.checked; render();
}}));
function segWire(id, key) {{
  const seg = document.getElementById(id);
  seg.querySelectorAll('button[data-v]').forEach(b => b.addEventListener('click', () => {{
    seg.querySelectorAll('button').forEach(x => x.classList.remove('on'));
    b.classList.add('on'); state[key] = b.dataset.v; render();
  }}));
}}
segWire('complexity', 'complexity');
segWire('unit', 'unit');
// Measured but ladder not yet run → the ABR-ladder unit isn't available; disable it.
if (FIX.meta.illustrative === false && !FIX.meta.have_ladder) {{
  const seg = document.getElementById('unit');
  const lad = seg.querySelector('button[data-v="ladder"]');
  const sng = seg.querySelector('button[data-v="single"]');
  if (lad && sng) {{
    lad.disabled = true; lad.title = 'full ABR ladder not measured yet';
    lad.classList.remove('on'); sng.classList.add('on'); state.unit = 'single';
  }}
}}

// Device classes — generic by default, click to reveal example hardware.
document.getElementById('classes').innerHTML = FIX.classes.map((cl, i) => `
  <details class="cls"${{i === 0 ? ' open' : ''}}>
    <summary><b>${{cl.label}}</b><small>${{cl.spec}}</small></summary>
    <ul>${{cl.examples.map(e => `<li>${{e}}</li>`).join('')}}
      <li class="named">+ specific named model (comparison listing)</li></ul>
  </details>`).join('');
document.getElementById('sponsor').textContent = FIX.sponsorship_note;

const _measured = FIX.meta.illustrative === false;
document.getElementById('footnote').innerHTML =
  `Unit: ${{FIX.meta.unit}} &mdash; ${{FIX.meta.ladder}}. Content: `
  + `${{FIX.meta.clip_low}} vs ${{FIX.meta.clip_high}}. `
  + (_measured
      ? `Wh/min and bitrate are interpolated from the measured VMAF-vs-bitrate points; a target above a `
        + `recipe's measured ceiling shows as "can't reach". GPU figures use the better of the baseline / `
        + `tuned NVENC config per codec. `
      : `"1080p only" is about ${{Math.round((FIX.meta.single_fraction || 0) * 100)}}% of the ladder's cost. `
        + `Wh/min and bitrate come from a (here illustrative) calibration table. `)
  + `Hours = budget &divide; (Wh/min) &divide; 60, computed live. Single-stream only &mdash; ASIC parallel-stream `
  + `density is a separate axis not shown.`;

render();
</script>
"""


@router.get("/video/budget", response_class=HTMLResponse,
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def budget_page(request: Request):
    demo = _demo_fixture()
    # Prefer a measured calibration artifact; fall back to the illustrative fixture.
    # The projected ASIC rows + class metadata carry over either way (no ASIC data).
    asic_recipes = [r for r in demo["recipes"] if r["device"] == "asic"]
    try:
        fix = budget_data.measured_fixture(
            demo["vmaf_targets"], asic_recipes, demo["classes"], demo["sponsorship_note"])
    except Exception:
        fix = None
    if not fix:
        fix = demo
    title = "Transcode budget" if not fix["meta"].get("illustrative", True) else "Transcode budget (demo)"
    return ui.render_page(request, title, styles=_STYLES, body=_body(fix))


# ---------------------------------------------------------------------------
# /video/budget/reconfigure — Lab-only re-calibration (NetInt-ready).
# Reuses the proven bin/run-encode-parity harness, launched detached with a
# pause/un-pause wrapper so it owns the meter without the queue/lock plumbing.
# ---------------------------------------------------------------------------
_REPO = Path(__file__).resolve().parent.parent
_RUN_MARKER = Path("/tmp/owl-reconfigure-running")


def _latest_artifact_any() -> dict | None:
    files = [f for f in glob.glob(budget_data.ARTIFACT_GLOB) if not f.endswith("_DRY.json")]
    if not files:
        return None
    newest = max(files, key=os.path.getmtime)
    try:
        return json.loads(Path(newest).read_text())
    except Exception:
        return None


def _reconfigure_status() -> dict:
    a = _latest_artifact_any() or {}
    fp = a.get("fingerprint", {})
    return {
        "running": _RUN_MARKER.exists(),
        "have_data": bool(a),
        "complete": a.get("complete", False),
        "rows": len(a.get("rows", [])),
        "expected": a.get("protocol", {}).get("expected_rows"),
        "generated_at": a.get("generated_at"),
        "hardware": (f"{(fp.get('cpu') or {}).get('model', '?')} · "
                     f"{(fp.get('gpu') or {}).get('name', '?')}") if fp else None,
    }


@router.get("/video/budget/reconfigure/status",
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def reconfigure_status(request: Request):
    return JSONResponse(_reconfigure_status())


@router.post("/video/budget/reconfigure/run",
             dependencies=[Depends(requires(VARIANCE_RUN))])
async def reconfigure_run(request: Request):
    if _RUN_MARKER.exists():
        return JSONResponse({"error": "A calibration run is already in progress."},
                            status_code=409)
    # Detached wrapper: mark running, pause the queue (poller backs off → meter
    # free), run the proven harness, then un-pause and clear the marker — whatever
    # the outcome. Fixed command, no user input.
    script = (
        f'touch {_RUN_MARKER}; touch /tmp/owl-paused; '
        f'python3 -u {_REPO}/bin/run-encode-parity --full > /tmp/parity_reconfigure.log 2>&1; '
        f'rm -f /tmp/owl-paused; rm -f {_RUN_MARKER}'
    )
    subprocess.Popen(["bash", "-c", script], start_new_session=True,
                     cwd=str(_REPO), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return JSONResponse({"ok": True, "started": True})


def _reconfigure_body(local: bool, st: dict) -> str:
    if st["have_data"]:
        pct = f"{st['rows']}/{st['expected']}" if st["expected"] else str(st["rows"])
        status_html = (
            f"<div class='rc-status'><b>Current calibration:</b> {st['hardware'] or '—'}<br>"
            f"measured {(st['generated_at'] or '')[:16]} · {pct} rows · "
            f"{'complete ✓' if st['complete'] else 'INCOMPLETE'}</div>")
    else:
        status_html = ("<div class='rc-status'>No measured calibration yet — "
                       "<a href='/video/budget' style='color:var(--accent)'>/video/budget</a> "
                       "is showing illustrative data.</div>")
    controls = (
        "<button id='runBtn' onclick='startRun()'>▶ Run full calibration</button>"
        "<div class='rc-note'>Sweeps 90 encodes (3 codecs × CPU/GPU baseline+tuned × 5 bitrates "
        "× BBB + Meridian), ~80 min. <b>Pauses the queue</b> for the duration (UI stays up) and "
        "needs the box otherwise idle. On completion <code>/video/budget</code> updates automatically. "
        "Re-run when the encode hardware changes (e.g. NetInt ASIC cards).</div>"
        "<div id='rcMsg'></div>"
        if local else
        "<div class='rc-note'>Running a calibration requires lab access.</div>")
    return f"""
    <h1>Re-calibrate transcode budget</h1>
    <div class="subtitle">Lab tool · feeds <a href="/video/budget" style="color:var(--accent)">/video/budget</a>
      · method: <a href="/methodology#energy-budget" style="color:var(--accent)">/methodology</a></div>
    {status_html}
    {controls}
    <script>
    async function poll() {{
      const s = await (await fetch('/video/budget/reconfigure/status')).json();
      const btn = document.getElementById('runBtn');
      if (s.running) {{
        if (btn) {{ btn.disabled = true; btn.textContent = '⏳ Running…'; }}
        document.getElementById('rcMsg').innerHTML =
          `<span style="color:var(--accent)">Calibration running — ${{s.rows}}/${{s.expected || '?'}} encodes done.</span>`;
      }} else if (btn && btn.disabled) {{
        document.getElementById('rcMsg').innerHTML =
          '<span style="color:var(--accent)">✓ Done — /video/budget now reflects the new run.</span>';
        btn.disabled = false; btn.textContent = '▶ Run full calibration';
      }}
    }}
    async function startRun() {{
      const r = await fetch('/video/budget/reconfigure/run', {{method: 'POST'}});
      if (r.status === 409) {{ document.getElementById('rcMsg').textContent = 'Already running.'; return; }}
      poll();
    }}
    setInterval(poll, 5000); poll();
    </script>
    <style>
      .rc-status {{ border:1px solid var(--border); border-radius:6px; padding:0.8rem 1rem;
                    margin:1rem 0; font-size:0.85rem; line-height:1.6; }}
      #runBtn {{ background:var(--accent); color:#001a10; border:none; padding:0.6rem 1.4rem;
                 font-family:monospace; font-size:0.95rem; cursor:pointer; border-radius:4px; }}
      #runBtn:disabled {{ background:var(--border-2); color:var(--text-3); cursor:default; }}
      .rc-note {{ color:var(--text-4); font-size:0.78rem; line-height:1.6; margin-top:0.8rem; }}
      #rcMsg {{ margin-top:0.8rem; font-size:0.85rem; }}
    </style>
    """


@router.get("/video/budget/reconfigure", response_class=HTMLResponse,
            dependencies=[Depends(requires(PUBLIC_PAGE))])
async def reconfigure_page(request: Request):
    local = can(audience.tier(request), VARIANCE_RUN)
    return ui.render_page(request, "Re-calibrate transcode budget",
                          styles=_STYLES, body=_reconfigure_body(local, _reconfigure_status()))
