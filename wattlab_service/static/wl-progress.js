// Extracted from main.py (Phase 1, 2026-06-10) — see ARCHITECTURE.md.
// Requires window.WL_CFG (loaded via /ui-config.js before this file).
// Defensive fallback: if that fetch failed (e.g. a proxy 429), degrade to
// generic wording instead of throwing and killing every poll loop below.
window.WL_CFG = window.WL_CFG || {baseline_s: '\u2014', cooldown_s: '\u2014',
  cooldown_label: 'Cooldown', cooldown_paren: '', rest_label: 'Rest',
  idle_label: 'Idle', llm_rest_s: '\u2014', meter_name: 'power meter',
  show_wait_detail: true, idle_tolerance_w: 3, urls: {}};
var WL_CFG = window.WL_CFG;
function wlFmt(v, dec) { if (v === null || v === undefined) return '—'; return Number(v).toFixed(dec ?? 2); }
function wlFormatElapsed(ms) {
    const s = Math.floor(ms / 1000);
    if (s < 60) return s + 's';
    return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
}
function wlStageList(stages, cur) {
    return stages.map(function(lbl, i) {
        var s = i < cur ? 'done' : i === cur ? 'active' : 'pending';
        var ic = s === 'done' ? '✓' : s === 'active' ? '▶' : '·';
        var col = s === 'done' ? '#00ff99' : s === 'active' ? '#ffaa00' : '#333';
        return '<div style="display:flex;align-items:center;gap:0.6rem;font-size:0.82rem;margin-bottom:0.3rem">'
             + '<span style="color:' + col + ';width:1rem">' + ic + '</span>'
             + '<span style="color:' + col + '">' + lbl + '</span></div>';
    }).join('');
}
// Single source for the live "waiting for the idle floor" readout. Shown only
// while the active-probe cooldown is running (power.wait_for_thermal_floor sets
// cooldown_waited_s on the job); absent => a fixed Rest(Xs) sleep, no live line.
// Rendered by wlRenderProgress whenever the caller passes cooldownData, so
// every poll loop gets it for free; the wording can't drift between pages.
// Gated lab-wide by the cooldown_show_wait_detail setting (via WL_CFG).
function wlCooldownLine(data) {
    if (WL_CFG.show_wait_detail === false) return '';
    if (!data || data.cooldown_waited_s == null) return '';
    // Compact one-liner (the long form used to wrap): target = floor + the
    // idle tolerance, folded into a single number.
    var tol = Number(WL_CFG.idle_tolerance_w);
    if (isNaN(tol)) tol = 3;
    var tgt = data.cooldown_reference_w != null
        ? '≤ ' + (Number(data.cooldown_reference_w) + tol).toFixed(1) + ' W' : '?';
    var cw  = data.cooldown_w != null ? Number(data.cooldown_w).toFixed(1) : '?';
    return '<div style="color:var(--warn);font-size:0.72rem;margin-top:0.4rem">'
         + '⏳ Idle wait ' + Number(data.cooldown_waited_s).toFixed(0)
         + 's · ' + cw + ' W → target ' + tgt + '</div>';
}
// CR-019 — widget targets default to '#status' for back-compat with the
// main pages (/video /llm /image /rag), but accept opts.target so /demo
// can route the same widget to its per-step containers (#video-status,
// #llm-status, #image-status, #rag-status).
function _wlTarget(opts) {
    var id = (opts && opts.target) || 'status';
    return document.getElementById(id);
}
function wlRenderProgress(opts) {
    var w = opts.watts;
    var wHtml = w != null
        ? '<div style="font-size:2.5rem;color:var(--accent);font-family:monospace;font-weight:bold;margin:0.75rem 0 0">'
          + w.toFixed(1) + ' W</div>'
          + '<div style="color:var(--text-3);font-size:0.72rem;letter-spacing:0.04em;margin-bottom:0.5rem">live wall power · ' + WL_CFG.meter_name + '</div>'
        : '';
    var elHtml = opts.elapsed != null
        ? '<div style="color:var(--text-4);font-size:0.78rem;margin-top:0.4rem">Elapsed: ' + wlFormatElapsed(opts.elapsed) + '</div>'
        : '';
    // CR-035 — encode progress bar. Renders above the stage list when the
    // server has streamed a `progress_pct` (video jobs only). Caption
    // underneath shows %, encode speed (e.g. "2.1x"), and ETA. Hidden on
    // any workload that doesn't surface a percentage — same widget,
    // workload-agnostic field.
    var pbHtml = '';
    if (opts.progressPct != null && !isNaN(opts.progressPct)) {
        var pct = Math.max(0, Math.min(100, parseFloat(opts.progressPct)));
        var captionParts = [pct.toFixed(1) + '%'];
        if (opts.encodeSpeed) captionParts.push(opts.encodeSpeed);
        if (opts.etaS != null && !isNaN(opts.etaS) && opts.etaS > 0) {
            captionParts.push('ETA ' + wlFormatElapsed(opts.etaS * 1000));
        }
        pbHtml =
            '<div style="margin-bottom:0.85rem">'
          + '<div style="height:6px;background:var(--panel);border:1px solid var(--border-2);'
          + 'overflow:hidden">'
          + '<div style="height:100%;width:' + pct + '%;background:var(--accent);'
          + 'transition:width 0.4s ease-out"></div>'
          + '</div>'
          + '<div style="color:var(--text-4);font-size:0.7rem;margin-top:0.3rem;'
          + 'font-family:monospace;letter-spacing:0.04em">'
          + captionParts.join(' · ')
          + '</div>'
          + '</div>';
    }
    var t = _wlTarget(opts);
    if (!t) return;
    t.innerHTML =
        '<div style="border:1px solid var(--border);padding:1.5rem">'
        + '<div style="color:var(--warn);font-size:0.9rem;margin-bottom:0.75rem">'
        + (opts.header || 'Measuring — do not close this tab') + '</div>'
        + pbHtml
        + (opts.stagesHtml || '')
        + wHtml + elHtml
        + (opts.extraHtml || '')
        + (opts.cooldownData ? wlCooldownLine(opts.cooldownData) : '')
        + '</div>';
}
function wlRenderQueued(pos, opts) {
    var t = _wlTarget(opts);
    if (!t) return;
    t.innerHTML =
        '<div style="border:1px solid var(--border-3);padding:1.5rem">'
        + '<div style="color:var(--warn);font-size:0.9rem;margin-bottom:0.75rem">⏱ Queued — position ' + pos + '</div>'
        + '<div style="color:var(--text-3);font-size:0.82rem">Another measurement is running. Your job will start automatically.</div>'
        + '</div>';
}
// (Idle-wait timeout dialog helpers wlCooldownDialog/Close/Decide live in
// _CARBON_JS — bundled on every page incl. /llm/compare & /rag/compare, which
// don't load _PROGRESS_JS. Keeping them here caused a ReferenceError in those
// pages' poll loops that froze the progress on the submit message.)
// Shared per-workload stage labels — referenced from main pages and
// from /demo's poll loops, so the stage list can't drift between them.
// Static expected-duration suffix (e.g. "Baseline (10s)", "Cooldown (90s)")
// is baked at module load via the .replace() chain below — keeps the
// visitor oriented during long quiet stages without a live timer (which
// would imply more precision than the static expectation actually has).
var WL_VIDEO_STAGES = ['Baseline (' + WL_CFG.baseline_s + 's)', 'Encoding', WL_CFG.cooldown_label, 'Complete'];
var WL_LLM_STAGES   = ['Baseline (' + WL_CFG.baseline_s + 's)', 'Inference running', 'Complete'];
var WL_IMAGE_STAGES = ['Baseline (' + WL_CFG.baseline_s + 's)', 'Generating image', 'Complete'];
var WL_RAG_STAGES   = ['Baseline poll (' + WL_CFG.baseline_s + 's)', 'Inference running', 'Complete'];
// No cooldown step: a single enhance run's measured pass is its LAST pass, so
// it skips the trailing cooldown (same rule as the compare's ffmpeg pass).
// Normalize = the conditional lossless pre-conversion (VFR/odd-pixel-format
// inputs only) — runs BEFORE the baseline so it never enters the energy
// figure; it ends with an idle wait back to the pre-normalize floor (the
// toggle-aware label, same as the compare flow's inter-pass step). Clean
// inputs pass straight through both stages.
var WL_ENHANCE_STAGES = ['Normalize', WL_CFG.idle_label, 'Baseline (' + WL_CFG.baseline_s + 's)', 'Transcoding', 'Probe'];
// Enhance compare flow: two measured passes, each followed by an idle/cooldown
// step. WL_CFG.idle_label is the toggle-aware label baked above ("Wait for Idle"
// when wait-for-idle is on, else "Idle").
var WL_CMP_STAGES = ['AI / ML enhance', WL_CFG.idle_label, 'Traditional (ffmpeg)', 'Analyse'];
