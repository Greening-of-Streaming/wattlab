"""
Video-enhancement routes — /video-enhance (CR-042 placeholder) and the
hidden /enhance-run partner-transcode harness (CR-063, Pixop).

Phase 3 of the 2026-06 refactor: per-feature route module. Orchestration
(run_enhance_job / run_enhance_compare_job) lives here with its routes;
measurement stays in pixop.py. Shared state comes from runtime.py, page
chrome from ui.py — never import main.
"""
import asyncio
import html as html_lib
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import audience
import pixop
import queue_control
import ui
from capabilities import requires, can, ENHANCE_RUN, PUBLIC_PAGE
from persist import save_result
from runtime import jobs, job_status as _job_status
from ui import _PROGRESS_JS, _lock_badge_html, _lock_class

router = APIRouter()


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


@router.get("/video-enhance/asset/{name}",
         dependencies=[Depends(requires(PUBLIC_PAGE))])
async def video_enhance_asset(name: str):
    path = _VIDEO_ENHANCE_ASSETS.get(name)
    if path is None or not path.exists():
        return HTMLResponse(_VIDEO_ENHANCE_404, status_code=404)
    return FileResponse(path, media_type="video/mp4")


# Plain string (not f-string) so JS object literals don't need escaping;
# Python-side placeholders are explicit `{NAME}` tokens replaced once at
# render time, same pattern /methodology and /queue-status use.
_VIDEO_ENHANCE_STYLES = """
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
"""

_VIDEO_ENHANCE_HTML = """
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
"""


@router.get("/video-enhance", response_class=HTMLResponse,
         dependencies=[Depends(requires(PUBLIC_PAGE))])
async def video_enhance_page(request: Request):
    return (ui.render_page(request, "Video Enhancement (placeholder)",
                           styles=_VIDEO_ENHANCE_STYLES,
                           body=_VIDEO_ENHANCE_HTML)
            .replace("{PROGRESS_JS}",      _PROGRESS_JS))


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


_ENHANCE_RUN_STYLES = """
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
"""

_ENHANCE_RUN_HTML = """
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
        cooldownData: data,
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
        cooldownData: data,
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
"""


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


@router.get("/enhance-run", response_class=HTMLResponse,
         dependencies=[Depends(requires(ENHANCE_RUN))])
async def enhance_run_page(request: Request):
    pf = pixop.preflight()
    can_run = can(audience.tier(request), ENHANCE_RUN)
    run_enabled = can_run and pf["ok_transcode"]
    st_enabled = can_run and pf["ok_selftest"]
    comparable = {p: pixop.ffmpeg_comparable(p) for p in pf["presets"]}
    return (ui.render_page(request,
                           "UNDER DEVELOPMENT · Video enhancement (GoS only)",
                           styles=_ENHANCE_RUN_STYLES, body=_ENHANCE_RUN_HTML)
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
            .replace("{PROGRESS_JS}",      _PROGRESS_JS))


@router.post("/enhance-run/self-test", dependencies=[Depends(requires(ENHANCE_RUN))])
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


@router.post("/enhance-run/start", dependencies=[Depends(requires(ENHANCE_RUN))])
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


@router.post("/enhance-run/start-compare", dependencies=[Depends(requires(ENHANCE_RUN))])
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


@router.get("/enhance-run/job/{job_id}", dependencies=[Depends(requires(ENHANCE_RUN))])
async def enhance_job_status(job_id: str):
    return _job_status(job_id)


@router.get("/enhance-run/output/{name}", dependencies=[Depends(requires(ENHANCE_RUN))])
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


@router.get("/enhance-run/input/{name}", dependencies=[Depends(requires(ENHANCE_RUN))])
async def enhance_input(name: str):
    """Serve a staged input clip for in-page preview. Lab-only; basename allow-list."""
    inp, _, _ = pixop._workdir_paths(pixop.config())
    if Path(name).name != name:
        return HTMLResponse("not found", status_code=404)
    path = inp / name
    if not path.exists() or not path.is_file():
        return HTMLResponse("not found", status_code=404)
    return FileResponse(path, media_type="video/mp4", filename=name)
