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
// ── /video preset-keyed stage lists + server-stage→index maps ─────────────
// Lifted from /video's inline poll code (2026-07-17, VMAF-v1 session) after
// /demo's tour poll was caught running its OWN 4-stage list: 'vmaf' had no
// index there, so the multi-minute VMAF scoring pass rendered as "Baseline".
// ONE definition now — /video's renderProgress and /demo's pollVideo both
// read these. Labels bake from WL_CFG at load (the same serve-time wording
// the old inline lists took via the BASELINE_S / REST_LABEL page tokens).
var _WL_V_SINGLE = ['Baseline (' + WL_CFG.baseline_s + 's)', 'Encode', 'Done'];
var _WL_V_SINGLE_IDX = {starting:0, baseline:0, cpu_encode:1, gpu_encode:1,
                        h265_cpu_encode:1, h265_gpu_encode:1,
                        av1_cpu_encode:1, av1_gpu_encode:1, done:2};
var _WL_V_BOTH = ['Baseline (' + WL_CFG.baseline_s + 's)', 'CPU encode', WL_CFG.rest_label,
                  'Baseline 2 (' + WL_CFG.baseline_s + 's)', 'GPU encode', 'VMAF (quality)', 'Done'];
var _WL_V_BOTH_IDX = {starting:0, baseline:0, cpu_encode:1, rest:2,
                      baseline_2:3, gpu_encode:4, vmaf:5, done:6};
var _WL_V_ALL = ['H.264 CPU', WL_CFG.rest_label, 'H.264 GPU', WL_CFG.rest_label,
                 'H.265 CPU', WL_CFG.rest_label, 'H.265 GPU', WL_CFG.rest_label,
                 'AV1 CPU', WL_CFG.rest_label, 'AV1 GPU', 'VMAF (quality)', 'Done'];
var _WL_V_ALL_IDX = {starting:0,
    h264_cpu_baseline:0, h264_cpu_encode:0,
    h264_rest:1,
    h264_gpu_baseline:2, h264_gpu_encode:2,
    h264_inter_rest:3,
    h265_cpu_baseline:4, h265_cpu_encode:4,
    h265_rest:5,
    h265_gpu_baseline:6, h265_gpu_encode:6,
    h265_inter_rest:7,
    av1_cpu_baseline:8, av1_cpu_encode:8,
    av1_rest:9,
    av1_gpu_baseline:10, av1_gpu_encode:10,
    vmaf:11,
    done:12};
var _WL_V_CODECS_CPU = ['H.264 CPU', WL_CFG.rest_label, 'H.265 CPU', WL_CFG.rest_label,
                        'AV1 CPU', 'VMAF (quality)', 'Done'];
var _WL_V_CODECS_GPU = ['H.264 GPU', WL_CFG.rest_label, 'H.265 GPU', WL_CFG.rest_label,
                        'AV1 GPU', 'VMAF (quality)', 'Done'];
var _WL_V_CODECS_CPU_IDX = {starting:0,
    h264_cpu_baseline:0, h264_cpu_encode:0,
    h265_cpu_rest:1,
    h265_cpu_baseline:2, h265_cpu_encode:2,
    av1_cpu_rest:3,
    av1_cpu_baseline:4, av1_cpu_encode:4,
    vmaf:5, done:6};
var _WL_V_CODECS_GPU_IDX = {starting:0,
    h264_gpu_baseline:0, h264_gpu_encode:0,
    h265_gpu_rest:1,
    h265_gpu_baseline:2, h265_gpu_encode:2,
    av1_gpu_rest:3,
    av1_gpu_baseline:4, av1_gpu_encode:4,
    vmaf:5, done:6};
var WL_VIDEO_PRESET_STAGES = {
    cpu: _WL_V_SINGLE, gpu: _WL_V_SINGLE,
    h265_cpu: _WL_V_SINGLE, h265_gpu: _WL_V_SINGLE,
    av1_cpu: _WL_V_SINGLE, av1_gpu: _WL_V_SINGLE,
    both: _WL_V_BOTH, h265_both: _WL_V_BOTH, av1_both: _WL_V_BOTH,
    all_codecs: _WL_V_ALL,
    codecs_cpu: _WL_V_CODECS_CPU, codecs_gpu: _WL_V_CODECS_GPU
};
var WL_VIDEO_PRESET_IDX = {
    cpu: _WL_V_SINGLE_IDX, gpu: _WL_V_SINGLE_IDX,
    h265_cpu: _WL_V_SINGLE_IDX, h265_gpu: _WL_V_SINGLE_IDX,
    av1_cpu: _WL_V_SINGLE_IDX, av1_gpu: _WL_V_SINGLE_IDX,
    both: _WL_V_BOTH_IDX, h265_both: _WL_V_BOTH_IDX, av1_both: _WL_V_BOTH_IDX,
    all_codecs: _WL_V_ALL_IDX,
    codecs_cpu: _WL_V_CODECS_CPU_IDX, codecs_gpu: _WL_V_CODECS_GPU_IDX
};
// VMAF (CR-044) doesn't pipe ffmpeg progress, but the server surfaces
// vmaf_done / vmaf_total so the widget can still show "N of M".
function wlVmafLine(serverStage, data) {
    if (serverStage !== 'vmaf' || !data || !data.vmaf_total) return '';
    return '<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.4rem">'
         + 'VMAF · ' + (data.vmaf_done || 0) + ' of ' + data.vmaf_total
         + ' encode' + (data.vmaf_total > 1 ? 's' : '') + ' scored</div>';
}

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
