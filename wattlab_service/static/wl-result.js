// Extracted from main.py (Phase 1, 2026-06-10) — see ARCHITECTURE.md.
(function(){
  // Local fmt — independent of /demo's `fmt` so the helpers work on any
  // page. Number formatting only; nulls render as em-dash.
  function _f(v, dp){
    if (v === null || v === undefined) return '—';
    if (typeof v === 'number' && !isFinite(v)) return '—';
    return Number(v).toFixed(dp);
  }
  function _ago(iso){
    if (!iso) return 'recently';
    var diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (!isFinite(diff) || diff < 0) return 'recently';
    if (diff < 60)    return Math.floor(diff) + 's ago';
    if (diff < 3600)  return Math.floor(diff/60) + 'm ago';
    if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
    return Math.floor(diff/86400) + 'd ago';
  }
  function _prevNote(isPrev, savedAt){
    return isPrev
      ? '<p class="prev-note">↩ Previous run · ' + _ago(savedAt) + '</p>'
      : '';
  }
  function _promptBlock(prompt, taskLabel, label){
    if (!prompt) return '';
    var lbl = label || (taskLabel ? taskLabel : 'Prompt');
    return '<div style="font-size:0.78rem;color:var(--text-3);font-style:italic;'
         + 'margin-bottom:0.85rem;border-left:2px solid var(--border-2);'
         + 'padding-left:0.7rem">'
         + '<span style="color:var(--text-4);font-style:normal">' + lbl + ':</span> '
         + '"' + prompt + '"</div>';
  }

  // CR-038 — shared efficiency-winner verdict for compare-mode results.
  // Takes a list of {label, energy, durationS?, qualityNote?} sub-runs and
  // returns a single-line HTML banner with the winner + its margin vs the
  // next-best (N=2 mode) or vs the spread (N≥3 mode), or
  // "tied within noise" when the margin is <5%. Hidden (empty string) for
  // fewer than 2 valid sub-runs.
  //
  // Energy-anchored: --accent green for the winner. This is a
  // 🟢-direct framing per the data-quality vocabulary CR-036
  // established, so we keep the green palette here in deliberate
  // contrast to the amber carbon strip below.
  //
  // Quality caveats are appended only when the caller supplies one via
  // best.qualityNote — the helper does not invent quality scoring
  // (that's CR-039 territory).
  //
  // Caller picks the unit. LLM/RAG pass mWh/token; image passes Wh/image;
  // video passes Wh. The ratio is unit-agnostic, the verdict reads
  // naturally in whatever unit the result card displays.
  window.wlEfficiencyVerdict = function(subRuns, opts){
    var s = (subRuns || []).filter(function(x){
      return x && x.label != null
          && typeof x.energy === 'number' && isFinite(x.energy) && x.energy > 0;
    });
    if (s.length < 2) return '';
    s = s.slice().sort(function(a, b){ return a.energy - b.energy; });
    var best = s[0], next = s[1];
    var ratio = next.energy / best.energy;
    var marginPct = (ratio - 1) * 100;
    var unit = (opts && opts.unit) || 'Wh';
    var fmtN = function(v){
      if (v <= 0)      return '0';
      if (v < 0.001)   return v.toExponential(2);
      if (v < 0.01)    return v.toFixed(4);
      if (v < 1)       return v.toFixed(3);
      if (v < 100)     return v.toFixed(2);
      return v.toFixed(1);
    };
    var ratioStr = ratio >= 1.5 ? ratio.toFixed(1) + '×' : ratio.toFixed(2) + '×';
    var verdict;
    if (marginPct < 5) {
      verdict = 'Tied within noise · '
              + '<span style="color:var(--accent);font-weight:bold">' + best.label + '</span>'
              + ' and ' + next.label + ' both ≈ '
              + fmtN(best.energy) + ' ' + unit;
    } else if (s.length === 2) {
      verdict = 'Most efficient: '
              + '<span style="color:var(--accent);font-weight:bold">' + best.label + '</span> '
              + '· ' + fmtN(best.energy) + ' ' + unit
              + ' · ' + ratioStr + ' less than ' + next.label;
    } else {
      var worst = s[s.length - 1];
      var spread = worst.energy / best.energy;
      var spreadStr = spread >= 1.5 ? spread.toFixed(1) + '×' : spread.toFixed(2) + '×';
      verdict = 'Most efficient: '
              + '<span style="color:var(--accent);font-weight:bold">' + best.label + '</span> '
              + '· ' + fmtN(best.energy) + ' ' + unit
              + ' · best of ' + s.length + ' · spread '
              + spreadStr + ' across all sub-runs';
    }
    var qualityClause = '';
    if (best.qualityNote) {
      qualityClause = '<span style="color:var(--text-4);margin-left:0.5rem;'
                    + 'font-style:italic">— ' + best.qualityNote + '</span>';
    }
    return '<div style="font-family:monospace;font-size:0.85rem;color:var(--text-2);'
         + 'padding:0.55rem 0.75rem;background:rgba(0,255,153,0.05);'
         + 'border-left:3px solid var(--accent);margin-bottom:0.85rem">'
         + '⚡ ' + verdict + qualityClause
         + '</div>';
  };

  // Loud-ish soft-fail (Phase 4 contract, docs/result_envelope.md): when a
  // record reaches a card renderer that can't make sense of it, say WHICH
  // mode it carried — a generic note hides mode→renderer mismatches.
  function _wlBadRecord(kind, r){
    var m = (r && r.mode) ? ' (mode: ' + r.mode + ')' : '';
    return '<p class="progress-note" style="color:var(--text-3)">'
         + kind + ' result format not recognised' + m + ' — run a new measurement.</p>';
  }

  // ─── Video ───────────────────────────────────────────────────────────────
  // Single-device codec sweep card (modes codecs_cpu / codecs_gpu). One shared
  // helper used by BOTH the /video fresh-run renderResult and the prev-row /
  // cross-page wlRenderVideoCard, so the card can't drift between the two.
  window.wlRenderCodecsSingle = function(r){
    var codecs = r.codecs || {};
    var a = r.analysis || {};
    var side = r.side || (r.mode === 'codecs_gpu' ? 'gpu' : 'cpu');
    var sideLbl = side.toUpperCase();
    var devLbl = side === 'gpu' ? 'GPU (hardware)' : 'CPU (software)';
    var codecOrder = [['h264','H.264'],['h265','H.265'],['av1','AV1']];
    var rows = '', subRuns = [], bestVmaf = null, bestVmafLbl = null;
    codecOrder.forEach(function(co){
      var key = co[0], lbl = co[1];
      var c = codecs[key]; if (!c) return;
      var sub = c[side]; if (!sub || !sub.energy) return;
      var e = sub.energy;
      var conf = (e.confidence && e.confidence.flag) || '';
      var isEff  = a.most_efficient && a.most_efficient.codec === key;
      var isFast = a.fastest && a.fastest.codec === key;
      if (sub.vmaf != null && (bestVmaf == null || sub.vmaf > bestVmaf)) {
        bestVmaf = sub.vmaf; bestVmafLbl = lbl;
      }
      rows += '<tr>'
        + '<td style="text-align:left;color:var(--text);padding:0.3rem 0.5rem">'
        + lbl + (isEff ? ' ✓' : '') + (isFast ? ' 🏁' : '') + '</td>'
        + '<td style="text-align:right;padding:0.3rem 0.5rem">' + _f(e.delta_t_s,1) + 's</td>'
        + '<td style="text-align:right;color:' + (isEff?'var(--accent)':'var(--text-3)')
        + ';padding:0.3rem 0.5rem">' + _f(e.delta_e_wh,4) + ' Wh</td>'
        + '<td style="text-align:right;color:var(--text-3);padding:0.3rem 0.5rem">' + _f(sub.output_size_mb,2) + ' MB</td>'
        + '<td style="text-align:right;color:var(--text-3);padding:0.3rem 0.5rem">' + _f(sub.vmaf,1) + '</td>'
        + '<td style="text-align:center;padding:0.3rem 0.5rem">' + conf + '</td>'
        + '</tr>';
      if (e.co2e) subRuns.push({label: sub.preset_label || (lbl+' '+sideLbl),
                                grams: e.co2e.grams, deltaWh: e.delta_e_wh, durationS: e.delta_t_s});
    });
    var bestE = null, bestLabel = null;
    if (a.most_efficient && a.most_efficient.codec) {
      var mc = (codecs[a.most_efficient.codec] || {})[side];
      if (mc && mc.energy) { bestE = mc.energy; bestLabel = a.most_efficient.label; }
    }
    var stripWh = bestE ? bestE.delta_e_wh : null;
    var stripDur = bestE ? bestE.delta_t_s : null;
    var stripSavedG = bestE && bestE.co2e && bestE.co2e.intensity ? bestE.co2e.intensity.g_per_kwh : null;
    var stripLabel = (bestLabel || 'Most efficient') + ' · most efficient codec on ' + sideLbl;
    var parts = [];
    if (a.most_efficient) parts.push('<span>⚡ Most efficient: <span style="color:var(--accent)">'
        + a.most_efficient.label + ' (' + a.most_efficient.delta_e_wh + ' Wh)</span></span>');
    if (a.fastest) parts.push('<span>🏁 Fastest: <span style="color:var(--accent)">'
        + a.fastest.label + ' (' + a.fastest.delta_t_s + 's)</span></span>');
    if (bestVmafLbl) parts.push('<span>🎯 Best quality: <span style="color:var(--accent)">'
        + bestVmafLbl + ' (' + _f(bestVmaf,1) + ' VMAF)</span></span>');
    var highlights = parts.length
      ? '<div style="display:flex;gap:1.5rem;flex-wrap:wrap;font-size:0.85rem;margin-bottom:0.75rem">'
        + parts.join('') + '</div>'
      : '';
    return '<div class="result-card">'
      + '<h2 style="margin-bottom:0.5rem">Codecs on ' + devLbl + ' — Energy & Quality</h2>'
      + highlights
      + '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;font-family:monospace;margin-bottom:0.5rem">'
      + '<thead><tr style="color:var(--text-4);font-size:0.7rem;text-transform:uppercase;letter-spacing:0.05em">'
      + '<th style="text-align:left;padding:0.3rem 0.5rem 0.5rem 0">Codec</th>'
      + '<th style="text-align:right;padding:0.3rem 0.5rem">Time</th>'
      + '<th style="text-align:right;padding:0.3rem 0.5rem">Energy</th>'
      + '<th style="text-align:right;padding:0.3rem 0.5rem">Output</th>'
      + '<th style="text-align:right;padding:0.3rem 0.5rem">VMAF</th>'
      + '<th style="text-align:center;padding:0.3rem 0.5rem">Conf</th>'
      + '</tr></thead><tbody>' + rows + '</tbody></table>'
      + '<div style="font-size:0.7rem;color:var(--text-5);margin-bottom:0.5rem">'
      + '✓ most efficient · 🏁 fastest · same source + target bitrate · VMAF = perceptual quality 0–100 (higher better)</div>'
      + (stripWh != null ? wlCarbonStrip(stripWh, stripLabel, stripDur, stripSavedG, subRuns) : '')
      + '<p class="scope-note">Device layer only (GoS1). Network, CDN, CPE excluded.</p>'
      + '</div>';
  };

  window.wlRenderVideoCard = function(opts){
    var r = (opts && opts.result) || {};
    var html = _prevNote(opts && opts.isPrev, opts && opts.savedAt);
    if (r.mode === 'all_codecs') {
      // 3 codecs × 2 sides = 6 sub-runs. Compact matrix + carbon strip.
      // The /video page renders a richer per-codec collapsible breakdown
      // for fresh runs; this lifted helper is the prev-row / cross-page
      // version, so it sticks to the matrix.
      var codecs = r.codecs || {};
      var a = r.analysis || {};
      var codecOrder = [['h264','H.264'],['h265','H.265'],['av1','AV1']];
      var rows = '';
      var subRuns = [];
      var bestE = null, bestLabel = null;
      codecOrder.forEach(function(co){
        var key = co[0], lbl = co[1];
        var c = codecs[key];
        if (!c) return;
        var ca = c.analysis || {};
        ['cpu','gpu'].forEach(function(side){
          var sub = c[side];
          if (!sub || !sub.energy) return;
          var e = sub.energy;
          var sideLbl = side.toUpperCase();
          var isWinner = ca.energy_winner === sideLbl;
          var isFastest = ca.speed_winner === sideLbl;
          var conf = (e.confidence && e.confidence.flag) || '';
          rows += '<tr>'
                + '<td style="text-align:left;color:var(--text);padding:0.3rem 0.5rem">'
                + lbl + ' ' + sideLbl + '</td>'
                + '<td style="text-align:right;padding:0.3rem 0.5rem">'
                + _f(e.delta_t_s,1) + 's' + (isFastest ? ' 🏁' : '') + '</td>'
                + '<td style="text-align:right;color:' + (isWinner?'var(--accent)':'var(--text-3)')
                + ';padding:0.3rem 0.5rem">'
                + _f(e.delta_e_wh,4) + ' Wh' + (isWinner ? ' ✓' : '') + '</td>'
                + '<td style="text-align:right;color:var(--text-3);padding:0.3rem 0.5rem">'
                + _f(sub.output_size_mb,2) + ' MB</td>'
                + '<td style="text-align:right;color:var(--text-3);padding:0.3rem 0.5rem">'
                + _f(sub.vmaf,1) + '</td>'
                + '<td style="text-align:center;padding:0.3rem 0.5rem">' + conf + '</td>'
                + '</tr>';
          if (e.co2e) {
            subRuns.push({label: sub.preset_label || (lbl + ' ' + sideLbl),
                          grams: e.co2e.grams,
                          deltaWh: e.delta_e_wh,
                          durationS: e.delta_t_s});
          }
        });
      });
      // Strip uses the most-efficient sub-run's energy as the headline.
      if (a.most_efficient && a.most_efficient.codec && a.most_efficient.side) {
        var mc = (codecs[a.most_efficient.codec] || {})[a.most_efficient.side];
        if (mc && mc.energy) { bestE = mc.energy; bestLabel = a.most_efficient.label; }
      }
      var stripWh = bestE ? bestE.delta_e_wh : null;
      var stripDur = bestE ? bestE.delta_t_s : null;
      var stripSavedG = bestE && bestE.co2e && bestE.co2e.intensity
        ? bestE.co2e.intensity.g_per_kwh : null;
      var stripLabel = (bestLabel || 'Most efficient')
        + ' · most efficient codec across all comparisons';
      // Highlights — mirrors /video's fresh-run renderAllCodecs framing
      // since analysis.finding is empty for all_codecs results.
      var highlightsHtml = '';
      if (a.most_efficient || a.fastest) {
        var partsH = [];
        if (a.most_efficient) {
          partsH.push('<span>⚡ Most efficient: <span style="color:var(--accent)">'
                    + a.most_efficient.label + ' (' + a.most_efficient.delta_e_wh + ' Wh)</span></span>');
        }
        if (a.fastest) {
          partsH.push('<span>🏁 Fastest: <span style="color:var(--accent)">'
                    + a.fastest.label + ' (' + a.fastest.delta_t_s + 's)</span></span>');
        }
        highlightsHtml = '<div style="display:flex;gap:1.5rem;flex-wrap:wrap;'
                       + 'font-size:0.85rem;margin-bottom:0.75rem">'
                       + partsH.join('') + '</div>';
      }
      html += '<div class="result-card">'
            + (a.finding ? '<p class="headline">' + a.finding + '</p>' : '')
            + highlightsHtml
            + '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;'
            + 'font-family:monospace;margin-bottom:0.5rem">'
            + '<thead><tr style="color:var(--text-4);font-size:0.7rem;'
            + 'text-transform:uppercase;letter-spacing:0.05em">'
            + '<th style="text-align:left;padding:0.3rem 0.5rem 0.5rem 0">Codec · side</th>'
            + '<th style="text-align:right;padding:0.3rem 0.5rem">Time</th>'
            + '<th style="text-align:right;padding:0.3rem 0.5rem">Energy</th>'
            + '<th style="text-align:right;padding:0.3rem 0.5rem">Output</th>'
            + '<th style="text-align:right;padding:0.3rem 0.5rem">VMAF</th>'
            + '<th style="text-align:center;padding:0.3rem 0.5rem">Conf</th>'
            + '</tr></thead>'
            + '<tbody>' + rows + '</tbody>'
            + '</table>'
            + '<div style="font-size:0.7rem;color:var(--text-5);margin-bottom:0.5rem">'
            + '✓ energy winner per codec · 🏁 speed winner per codec</div>'
            + (stripWh != null
                ? wlCarbonStrip(stripWh, stripLabel, stripDur, stripSavedG, subRuns)
                : '')
            + '<p class="scope-note">Device layer only (GoS1). Network, CDN, CPE excluded.</p>'
            + '</div>';
      return html;
    }
    if (r.mode === 'codecs_cpu' || r.mode === 'codecs_gpu') {
      return html + window.wlRenderCodecsSingle(r);
    }
    if (r.mode === 'both') {
      var cpu = r.cpu || {}, gpu = r.gpu || {}, a = r.analysis || {};
      var ce = cpu.energy, ge = gpu.energy;
      if (!ce || !ge) return html + '<p style="color:var(--text-3)">Comparison result missing energy block.</p>';
      var winner = a.energy_winner;
      var bestE = (ce.delta_e_wh <= ge.delta_e_wh) ? ce : ge;
      var bestSide = (ce.delta_e_wh <= ge.delta_e_wh) ? 'CPU' : 'GPU';
      var bestSavedG = bestE.co2e && bestE.co2e.intensity ? bestE.co2e.intensity.g_per_kwh : null;
      var stripLabel = (cpu.preset_label || 'Video transcode') + ' · best of CPU vs GPU (' + bestSide + ')';
      var subRuns = [
        {label: (cpu.preset_label || 'CPU') + ' · CPU', e: ce},
        {label: (gpu.preset_label || 'GPU') + ' · GPU', e: ge}
      ].filter(function(s){ return s.e && s.e.co2e; }).map(function(s){
        return {label: s.label, grams: s.e.co2e.grams,
                deltaWh: s.e.delta_e_wh, durationS: s.e.delta_t_s};
      });
      html += '<div class="result-card">'
            + '<p class="headline">' + (a.finding || '') + '</p>'
            + '<div class="kpi-row">'
            +   '<div class="kpi"><div class="val">' + _f(ce.delta_e_wh,4) + ' Wh</div>'
            +     '<div class="lbl">CPU energy ' + (winner==='CPU'?'✓ winner':'') + '</div></div>'
            +   '<div class="kpi"><div class="val">' + _f(ge.delta_e_wh,4) + ' Wh</div>'
            +     '<div class="lbl">GPU energy ' + (winner==='GPU'?'✓ winner':'') + '</div></div>'
            +   '<div class="kpi"><div class="val">' + ce.delta_t_s + 's / ' + ge.delta_t_s + 's</div>'
            +     '<div class="lbl">Encode time CPU / GPU</div></div>'
            + '</div>'
            + '<div class="conf-badge">' + (ce.confidence && ce.confidence.flag) + ' CPU · '
            + (ge.confidence && ge.confidence.flag) + ' GPU · ' + (a.confidence_note || '') + '</div>'
            + (a.quality_note ? '<div class="conf-badge" style="color:var(--accent)">◆ ' + a.quality_note + '</div>' : '')
            + wlCarbonStrip(bestE.delta_e_wh, stripLabel, bestE.delta_t_s, bestSavedG, subRuns)
            + '<p class="scope-note">Device layer only (GoS1). Network, CDN, CPE excluded.</p>'
            + '</div>';
    } else {
      var res = r.result || r;
      var e = res.energy;
      if (!e) return html + _wlBadRecord('Video', r);
      var savedG = e.co2e && e.co2e.intensity ? e.co2e.intensity.g_per_kwh : null;
      html += '<div class="result-card">'
            + '<p class="headline">' + (res.preset_label || 'Video') + ': '
            + e.delta_e_wh + ' Wh · ' + e.delta_t_s + 's</p>'
            + '<div class="kpi-row">'
            +   '<div class="kpi"><div class="val">' + e.delta_e_wh + ' Wh</div><div class="lbl">Energy delta</div></div>'
            +   '<div class="kpi"><div class="val">' + e.delta_w + ' W</div><div class="lbl">Power delta</div></div>'
            +   '<div class="kpi"><div class="val">' + e.delta_t_s + 's</div><div class="lbl">Duration</div></div>'
            + '</div>'
            + '<div class="conf-badge">' + e.confidence.flag + ' ' + e.confidence.label + '</div>'
            + wlCarbonStrip(e.delta_e_wh, res.preset_label || 'Video transcode', e.delta_t_s, savedG)
            + '</div>';
    }
    return html;
  };

  // ─── LLM ─────────────────────────────────────────────────────────────────
  // Compact panel for the N-model compare results (llm compare_models +
  // rag_compare_models). The standalone /llm/compare & /rag/compare pages have
  // their own rich renderers; this is the shared read-only view used when a
  // stored compare result is embedded (e.g. the benchmark detail page).
  function wlRenderComparePanel(r){
    var models = r.models || [];
    var prompt = r.full_prompt || r.prompt || r.question || '';
    var expected = r.expected || '';
    var cheapest = r.cheapest_correct_key || null;
    var pass = (r.panel_pass_rate != null) ? Math.round(r.panel_pass_rate * 100) + '%' : '—';
    var rows = models.map(function(e){
      e = e || {};
      var conf = (e.confidence && e.confidence.flag) || '';
      var win = (cheapest && e.model_key === cheapest);
      var mwh = (e.mwh_per_token != null && e.delta_e_wh != null && e.delta_e_wh > 0) ? _f(e.mwh_per_token, 3) : '—';
      return '<tr' + (win ? ' style="background:var(--accent-soft)"' : '') + '>'
        + '<td style="text-align:left;padding:0.3rem 0.5rem;color:' + (win ? 'var(--accent)' : 'var(--text)') + '">' + (e.model_label || e.model_key || '?') + (win ? ' ★' : '') + '</td>'
        + '<td style="text-align:center;padding:0.3rem 0.5rem">' + (e.correct ? '<span style="color:var(--accent)">✓</span>' : '<span style="color:var(--err)">✗</span>') + '</td>'
        + '<td style="text-align:center;padding:0.3rem 0.5rem">' + conf + '</td>'
        + '<td style="text-align:right;padding:0.3rem 0.5rem;color:var(--text-3)">' + (e.output_tokens != null ? e.output_tokens : '—') + '</td>'
        + '<td style="text-align:right;padding:0.3rem 0.5rem;color:var(--text-3)">' + mwh + '</td>'
        + '<td style="text-align:right;padding:0.3rem 0.5rem;color:var(--text-3)">' + (e.delta_e_wh != null ? _f(e.delta_e_wh, 4) : '—') + '</td></tr>';
    }).join('');
    var errs = (r.model_errors || []).map(function(f){
      return '<div style="color:var(--err);font-size:0.72rem;font-family:monospace">⚠ ' + (f.model_key || '?') + ': ' + (f.error || '') + '</div>';
    }).join('');
    return '<div class="result-card">'
      + (prompt ? '<div style="font-family:monospace;font-size:0.78rem;color:var(--text-3);margin-bottom:0.4rem">Prompt: ' + prompt + (expected ? ' · expected: <b>' + expected + '</b>' : '') + '</div>' : '')
      + '<div style="font-size:0.78rem;color:var(--text-4);margin-bottom:0.5rem">panel pass rate: ' + pass + (cheapest ? ' · cheapest correct: <span style="color:var(--accent)">' + cheapest + '</span>' : '') + '</div>'
      + '<table style="width:100%;border-collapse:collapse;font-size:0.8rem;font-family:monospace">'
      + '<thead><tr style="color:var(--text-4);font-size:0.7rem;text-transform:uppercase">'
      + '<th style="text-align:left;padding:0.3rem 0.5rem">Model</th><th style="padding:0.3rem 0.5rem">OK</th><th style="padding:0.3rem 0.5rem">Conf</th>'
      + '<th style="text-align:right;padding:0.3rem 0.5rem">Tokens</th><th style="text-align:right;padding:0.3rem 0.5rem">mWh/tok</th><th style="text-align:right;padding:0.3rem 0.5rem">ΔE Wh</th></tr></thead>'
      + '<tbody>' + rows + '</tbody></table>' + errs + wlCooldownSummary(r.cooldowns) + '</div>';
  }

  window.wlRenderLLMCard = function(opts){
    var r = (opts && opts.result) || {};
    var html = _prevNote(opts && opts.isPrev, opts && opts.savedAt);
    if (r.mode === 'compare_models') return html + wlRenderComparePanel(r);
    if (r.mode === 'both') {
      var ce = r.cpu && r.cpu.energy, ge = r.gpu && r.gpu.energy;
      var ci = r.cpu && r.cpu.inference, gi = r.gpu && r.gpu.inference;
      var a = r.analysis || {};
      var bestE = (ce && ge) ? (ce.delta_e_wh <= ge.delta_e_wh ? ce : ge) : (ce || ge);
      var bestSavedG = bestE && bestE.co2e && bestE.co2e.intensity ? bestE.co2e.intensity.g_per_kwh : null;
      var subRuns = [
        {label: (r.model_label || '') + ' · CPU', e: ce},
        {label: (r.model_label || '') + ' · GPU', e: ge}
      ].filter(function(s){ return s.e && s.e.co2e; }).map(function(s){
        return {label: s.label, grams: s.e.co2e.grams,
                deltaWh: s.e.delta_e_wh, durationS: s.e.delta_t_s};
      });
      // CR-038 — efficiency verdict above the side-by-side KPI columns.
      // mWh/token is the comparable unit visitors see in the cells below.
      var llmVerdictHtml = wlEfficiencyVerdict([
        ce ? {label: 'CPU', energy: ce.mwh_per_token} : null,
        ge ? {label: 'GPU', energy: ge.mwh_per_token} : null
      ], {unit: 'mWh/token'});
      html += '<div class="result-card">'
            + '<p class="headline">' + (a.finding || '') + '</p>'
            + _promptBlock(r.prompt, r.task_label)
            + llmVerdictHtml
            + '<div style="display:flex;gap:1.5rem;flex-wrap:wrap;margin-bottom:1rem">'
            +   '<div style="flex:1;min-width:180px">'
            +     '<div style="color:var(--text-4);font-size:0.72rem;text-transform:uppercase;'
            +     'letter-spacing:0.05em;margin-bottom:0.5rem">CPU</div>'
            +     '<div class="kpi-row">'
            +       '<div class="kpi"><div class="val">' + _f(ce && ce.mwh_per_token,4) + '</div><div class="lbl">mWh/token</div></div>'
            +       '<div class="kpi"><div class="val">' + _f(ci && ci.tokens_per_sec,1) + '</div><div class="lbl">tok/s</div></div>'
            +     '</div>'
            +   '</div>'
            +   '<div style="flex:1;min-width:180px">'
            +     '<div style="color:var(--text-4);font-size:0.72rem;text-transform:uppercase;'
            +     'letter-spacing:0.05em;margin-bottom:0.5rem">GPU</div>'
            +     '<div class="kpi-row">'
            +       '<div class="kpi"><div class="val">' + _f(ge && ge.mwh_per_token,4) + '</div><div class="lbl">mWh/token</div></div>'
            +       '<div class="kpi"><div class="val">' + _f(gi && gi.tokens_per_sec,1) + '</div><div class="lbl">tok/s</div></div>'
            +     '</div>'
            +   '</div>'
            + '</div>'
            + '<div class="conf-badge">' + (ce ? ce.confidence.flag : '') + ' CPU · '
            + (ge ? ge.confidence.flag : '') + ' GPU · ' + (r.model_label || '') + '</div>'
            + (bestE
                ? wlCarbonStrip(bestE.delta_e_wh, (r.model_label || '') + ' · best of CPU vs GPU',
                                bestE.delta_t_s, bestSavedG, subRuns)
                : '')
            + '<p class="scope-note">Device layer only (GoS1). No amortised training cost.</p>'
            + '</div>';
    } else {
      // single or batch summary
      var e = r.energy;
      var inf = r.inference;
      if (!e && r.runs && r.runs.length) {
        e = r.runs[r.runs.length-1].energy;
        inf = r.runs[r.runs.length-1].inference;
      }
      if (!e && r.summary) {
        e = { mwh_per_token: r.summary.mwh_per_token_mean,
              delta_e_wh: r.summary.delta_e_wh_mean,
              confidence: {flag:'—', label:'see runs'},
              delta_w: null, delta_t_s: null };
        inf = { tokens_per_sec: r.summary.tokens_per_sec_mean,
                output_tokens: '—', response: '' };
      }
      if (!e) return html + _wlBadRecord('LLM', r);
      // Use JS-side escape pair for U+1F321 (thermometer) so the Python
      // source stays ASCII-safe; raw emoji round-trips as a Python
      // surrogate pair which can't UTF-8-encode in the response.
      var modeNote = r.warm ? '\uD83C\uDF21 Warm' : '\u2744 Cold';
      var savedG = e.co2e && e.co2e.intensity ? e.co2e.intensity.g_per_kwh : null;
      var stripLabel = (r.model_label || '') + (r.task_label ? ' · ' + r.task_label : '');
      html += '<div class="result-card">'
            + _promptBlock(r.prompt, r.task_label)
            + '<div class="kpi-row">'
            +   '<div class="kpi"><div class="val">' + _f(e.mwh_per_token,4) + '</div><div class="lbl">mWh / token</div></div>'
            +   '<div class="kpi"><div class="val">' + _f(inf && inf.tokens_per_sec,1) + '</div><div class="lbl">tokens / sec</div></div>'
            +   '<div class="kpi"><div class="val">' + _f(e.delta_e_wh,4) + ' Wh</div><div class="lbl">total energy</div></div>'
            +   '<div class="kpi"><div class="val">' + (inf ? inf.output_tokens : '—') + '</div><div class="lbl">output tokens</div></div>'
            + '</div>'
            + '<div class="conf-badge">' + e.confidence.flag + ' ' + e.confidence.label + ' · '
            + (r.model_label || '') + ' · ' + modeNote + '</div>'
            + (e.video_relative ? '<div style="margin-top:0.5rem;font-size:0.78rem;color:var(--text-3)">This run ' + e.video_relative.text + '</div>' : '')
            + (inf && inf.response ? '<div class="response-preview">' + inf.response + '</div>' : '')
            + wlCarbonStrip(e.delta_e_wh, stripLabel, e.delta_t_s, savedG)
            + '<p class="scope-note">Device layer only (GoS1). No amortised training cost.</p>'
            + '</div>';
    }
    return html;
  };

  // ─── RAG ─────────────────────────────────────────────────────────────────
  window.wlRenderRAGCard = function(opts){
    var r = (opts && opts.result) || {};
    var html = _prevNote(opts && opts.isPrev, opts && opts.savedAt);
    if (r.mode === 'rag_compare_models') return html + wlRenderComparePanel(r);
    var modes  = ['baseline', 'rag', 'rag_blended', 'rag_large'];
    var labels = {baseline: 'No retrieval', rag: 'RAG', rag_blended: 'RAG Blended', rag_large: 'RAG Large'};
    var results = r.results || {};
    var modelLine = r.model_label
      ? '<div style="font-family:monospace;font-size:0.78rem;color:var(--text-3);margin-bottom:0.6rem">'
        + 'Model: ' + r.model_label + (r.model_params ? ' · ' + r.model_params : '') + '</div>'
      : '';
    var questionLine = r.question
      ? '<div style="font-size:0.78rem;color:var(--text-3);font-style:italic;margin-bottom:1rem;'
        + 'border-left:2px solid var(--border-2);padding-left:0.7rem">'
        + '<span style="color:var(--text-4);font-style:normal">Question:</span> "' + r.question + '"</div>'
      : '';
    var cols = '';
    var bestE = null, bestLbl = null;
    modes.forEach(function(m){
      var res = results[m];
      if (!res) return;
      var e = res.energy || {}, inf = res.inference || {};
      var inTok = inf.input_tokens != null ? inf.input_tokens : '—';
      var outTok = inf.output_tokens != null ? inf.output_tokens : '—';
      var retMs = res.retrieval_ms > 0 ? _f(res.retrieval_ms, 0) + ' ms retrieval' : 'no retrieval';
      if (e.delta_e_wh != null && (bestE == null || e.delta_e_wh < bestE.delta_e_wh)) {
        bestE = e; bestLbl = labels[m];
      }
      cols += '<div style="flex:1;min-width:130px;border-left:2px solid #1a1a1a;padding-left:0.75rem">'
            +   '<div style="font-family:monospace;font-size:0.78rem;color:var(--text-3);margin-bottom:0.5rem">'
            +     labels[m] + '</div>'
            +   '<div class="kpi" style="margin-bottom:0.4rem">'
            +     '<div class="val">' + _f(e.mwh_per_token, 3) + '</div>'
            +     '<div class="lbl">mWh / token</div>'
            +   '</div>'
            +   '<div style="font-size:0.75rem;color:var(--text-4);line-height:1.8">'
            +     _f(inf.tokens_per_sec, 1) + ' tok/s<br>'
            +     inTok + ' in · ' + outTok + ' out tokens<br>'
            +     retMs + '<br>'
            +     (e.confidence
                    ? '<span class="conf-badge">' + e.confidence.flag + ' ' + e.confidence.label + '</span>'
                    : '')
            +   '</div>'
            + '</div>';
    });
    var stripSavedG = bestE && bestE.co2e && bestE.co2e.intensity ? bestE.co2e.intensity.g_per_kwh : null;
    var subRuns = modes.map(function(m){
      var res = results[m];
      if (!res || !res.energy || !res.energy.co2e) return null;
      return {label: labels[m], grams: res.energy.co2e.grams,
              deltaWh: res.energy.delta_e_wh, durationS: res.energy.delta_t_s};
    }).filter(function(s){ return s != null; });
    var stripHtml = bestE
      ? wlCarbonStrip(bestE.delta_e_wh,
                      (r.model_label || 'RAG') + ' · best of 3 modes (' + bestLbl + ')',
                      bestE.delta_t_s, stripSavedG, subRuns)
      : '';
    // CR-038 — efficiency verdict from the per-mode mWh/token numbers.
    // 3 sub-runs (baseline / RAG / RAG-Large) — the verdict will report
    // "best of 3 · spread N×" when there's real divergence; "tied" when
    // retrieval cost is within noise of baseline.
    var ragVerdictHtml = wlEfficiencyVerdict(modes.map(function(m){
      var res = results[m];
      if (!res || !res.energy) return null;
      return {label: labels[m], energy: res.energy.mwh_per_token};
    }).filter(function(x){ return x != null; }), {unit: 'mWh/token'});
    html += '<div class="result-card">'
          + modelLine
          + questionLine
          + ragVerdictHtml
          + '<div style="display:flex;gap:1rem;flex-wrap:wrap">' + cols + '</div>'
          + stripHtml
          + '<p class="scope-note" style="margin-top:1rem">'
          + 'Input tokens show how much context the model processes per mode — '
          + 'retrieval grows the prompt significantly.<br>'
          + 'Device layer only. Network excluded.'
          + '</p>'
          + '</div>';
    return html;
  };

  // ─── Prev-row click-to-expand (CR-034 Phase B / CR-013) ──────────────────
  // Lazy-loads the full persisted result, renders through the matching
  // shared helper above, and toggles the expand container. Multiple rows
  // can be open at once (state lives on the container's data-attrs).
  // jobType is the URL path segment (`/results/<jobType>/<jobId>/...`);
  // cardKind picks the renderer (defaults to jobType — RAG runs persist
  // under `llm/` so the caller passes `'rag'` explicitly).
  window.wlExpandPrevRow = function(jobType, jobId, savedAt, cardKind){
    var kind = cardKind || jobType;
    var elId = 'expand-' + jobId;
    var el = document.getElementById(elId);
    if (!el) return;
    if (el.dataset.expanded === '1') {
      el.style.display = 'none';
      el.dataset.expanded = '0';
      _wlSetChev(jobId, '▸');
      return;
    }
    if (el.dataset.loaded === '1') {
      el.style.display = 'block';
      el.dataset.expanded = '1';
      _wlSetChev(jobId, '▾');
      return;
    }
    el.style.display = 'block';
    el.dataset.expanded = '1';
    _wlSetChev(jobId, '▾');
    el.innerHTML = '<div style="color:var(--text-4);font-size:0.78rem;'
                 + 'padding:0.75rem;font-family:monospace">Loading full result…</div>';
    fetch('/results/' + jobType + '/' + jobId + '/download.json')
      .then(function(r){ if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function(j){
        var renderers = {
          video: window.wlRenderVideoCard,
          llm:   window.wlRenderLLMCard,
          rag:   window.wlRenderRAGCard,
          image: window.wlRenderImageCard,
          enhance: window.wlRenderEnhanceCard
        };
        var renderer = renderers[kind];
        if (!renderer) {
          el.innerHTML = '<div style="color:var(--err);padding:0.75rem">'
                       + 'Unknown result type: ' + kind + '</div>';
          return;
        }
        el.innerHTML = renderer({result: j, isPrev: true, savedAt: savedAt});
        el.dataset.loaded = '1';
      })
      .catch(function(e){
        el.innerHTML = '<div style="color:var(--err);padding:0.75rem">'
                     + 'Failed to load result: ' + (e.message || e) + '</div>';
        el.dataset.expanded = '0';
        _wlSetChev(jobId, '▸');
      });
  };
  function _wlSetChev(jobId, glyph){
    var c = document.getElementById('chev-' + jobId);
    if (c) c.textContent = glyph;
  }

  // ─── Image ───────────────────────────────────────────────────────────────
  window.wlRenderImageCard = function(opts){
    var r = (opts && opts.result) || {};
    var html = _prevNote(opts && opts.isPrev, opts && opts.savedAt);
    if (r.mode === 'compare_models') {
      // N-way render path (CR-050 follow-up). r.models is the canonical
      // list of per-model results; legacy r.small/r.large stay populated
      // (set by the runner to first/last of r.models) so older stored
      // results without r.models still render via the fallback below.
      var ac = r.analysis || {};
      var models = (r.models && r.models.length) ? r.models : (function(){
        // Legacy 2-model fallback for old stored results.
        var legacy = [];
        if (r.small) legacy.push(r.small);
        if (r.large) legacy.push(r.large);
        return legacy;
      })();
      if (!models.length) return html + '<p class="progress-note" style="color:var(--text-3)">Compare result has no per-model data — run a new measurement.</p>';
      var perModel = models.map(function(m){
        var e = m.energy || {}, g = m.generation || {};
        return {
          label:    g.model_label || m.model_key || '?',
          modelKey: m.model_key || '?',
          whPerImage: e.wh_per_image || e.delta_e_wh,
          deltaT:   e.delta_t_s,
          b64:      g.b64_png,
          conf:     e.confidence || {},
          energy:   e,
        };
      });
      var validE = perModel.filter(function(m){ return m.whPerImage != null; });
      var bestM  = validE.slice().sort(function(a,b){ return a.whPerImage - b.whPerImage; })[0];
      var bestSavedG = bestM && bestM.energy.co2e && bestM.energy.co2e.intensity
        ? bestM.energy.co2e.intensity.g_per_kwh : null;
      var subRunsCM = perModel.filter(function(m){ return m.energy && m.energy.co2e; })
        .map(function(m){ return {label: m.label, grams: m.energy.co2e.grams,
                                   deltaWh: m.energy.delta_e_wh, durationS: m.energy.delta_t_s}; });
      var imgsCM = perModel.map(function(m){
        if (!m.b64) return '';
        return '<div style="flex:1 1 140px;min-width:130px">'
             + '<div style="color:var(--text-4);font-size:0.7rem;margin-bottom:0.4rem">' + m.label + '</div>'
             + '<img src="data:image/png;base64,' + m.b64 + '" '
             + 'style="max-width:100%;border:1px solid var(--border);display:block"></div>';
      }).join('');
      var imgCMVerdictHtml = wlEfficiencyVerdict(
        perModel.map(function(m){ return m.whPerImage != null ? {label: m.label, energy: m.whPerImage} : null; }),
        {unit: 'Wh/image'}
      );
      var kpiHtml = '<div class="kpi-row" style="flex-wrap:wrap">'
        + perModel.map(function(m){
            return '<div class="kpi"><div class="val">' + _f(m.whPerImage, 4) + ' Wh</div>'
                 + '<div class="lbl">' + m.label + ' / image</div></div>';
          }).join('')
        + '</div>';
      var confHtml = perModel.filter(function(m){ return m.conf && m.conf.flag; })
        .map(function(m){ return m.conf.flag + ' ' + m.label; }).join(' · ');
      // Surface models that failed to load/run so a panel of N doesn't silently
      // render as N-1 with no explanation (mirrors wlRenderComparePanel). E.g.
      // SDXL-Lightning is a UNet-only checkpoint with no model_index.json.
      var errsCM = (r.model_errors || []).map(function(f){
        return '<div style="color:var(--err);font-size:0.72rem;font-family:monospace">⚠ '
             + (f.model_label || f.model_key || '?') + ': ' + (f.error || 'failed to run') + '</div>';
      }).join('');
      html += '<div class="result-card">'
            + '<p class="headline">' + (ac.finding || '') + '</p>'
            + _promptBlock(r.full_prompt, null, 'Prompt')
            + imgCMVerdictHtml
            + kpiHtml
            + (confHtml ? '<div class="conf-badge">' + confHtml + '</div>' : '')
            + '<div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-top:1rem">' + imgsCM + '</div>'
            + (bestM && bestM.energy
                ? wlCarbonStrip(bestM.energy.delta_e_wh,
                                'Image · cheapest of ' + perModel.length + ' models (' + bestM.label + ')',
                                bestM.energy.delta_t_s, bestSavedG, subRunsCM)
                : '')
            + (errsCM ? '<div style="margin-top:0.6rem">' + errsCM + '</div>' : '')
            + wlCooldownSummary(r.cooldowns)
            + '<p class="scope-note">Device layer only (GoS1). No amortised training cost.</p>'
            + '</div>';
      return html;
    }
    if (r.mode === 'both') {
      var ce = r.cpu && r.cpu.energy, ge = r.gpu && r.gpu.energy;
      var cg = r.cpu && r.cpu.generation, gg = r.gpu && r.gpu.generation;
      var a = r.analysis || {};
      var cpuWh = ce && (ce.wh_per_image || ce.delta_e_wh);
      var gpuWh = ge && (ge.wh_per_image || ge.delta_e_wh);
      var bestE = (ce && ge && ce.delta_e_wh != null && ge.delta_e_wh != null)
        ? (ce.delta_e_wh <= ge.delta_e_wh ? ce : ge)
        : (ce || ge);
      var bestSavedG = bestE && bestE.co2e && bestE.co2e.intensity ? bestE.co2e.intensity.g_per_kwh : null;
      var subRuns = [
        {label: 'CPU · image gen', e: ce},
        {label: 'GPU · image gen', e: ge}
      ].filter(function(s){ return s.e && s.e.co2e; }).map(function(s){
        return {label: s.label, grams: s.e.co2e.grams,
                deltaWh: s.e.delta_e_wh, durationS: s.e.delta_t_s};
      });
      var imgs = '';
      if (cg && cg.b64_png) imgs += '<div style="flex:1;min-width:150px">'
        + '<div style="color:var(--text-4);font-size:0.7rem;margin-bottom:0.4rem">CPU</div>'
        + '<img src="data:image/png;base64,' + cg.b64_png + '" '
        + 'style="max-width:100%;border:1px solid var(--border);display:block"></div>';
      if (gg && gg.b64_png) imgs += '<div style="flex:1;min-width:150px">'
        + '<div style="color:var(--text-4);font-size:0.7rem;margin-bottom:0.4rem">GPU</div>'
        + '<img src="data:image/png;base64,' + gg.b64_png + '" '
        + 'style="max-width:100%;border:1px solid var(--border);display:block"></div>';
      // CR-038 — efficiency verdict above the CPU/GPU KPI row.
      var imgBothVerdictHtml = wlEfficiencyVerdict([
        cpuWh != null ? {label: 'CPU', energy: cpuWh} : null,
        gpuWh != null ? {label: 'GPU', energy: gpuWh} : null
      ], {unit: 'Wh/image'});
      html += '<div class="result-card">'
            + '<p class="headline">' + (a.finding || '') + '</p>'
            + _promptBlock(r.full_prompt, null, 'Prompt')
            + imgBothVerdictHtml
            + '<div class="kpi-row">'
            +   '<div class="kpi"><div class="val">' + _f(cpuWh,4) + ' Wh</div><div class="lbl">CPU / image</div></div>'
            +   '<div class="kpi"><div class="val">' + _f(gpuWh,4) + ' Wh</div><div class="lbl">GPU / image</div></div>'
            +   '<div class="kpi"><div class="val">' + _f(cg && cg.gen_s,1) + 's / '
            +     _f(gg && (gg.gen_s_per_image || gg.gen_s),1) + 's</div>'
            +     '<div class="lbl">time CPU / GPU</div></div>'
            + '</div>'
            + (ce ? '<div class="conf-badge">' + ce.confidence.flag + ' CPU · '
                  + (ge ? ge.confidence.flag + ' GPU' : '') + '</div>' : '')
            + '<div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-top:1rem">' + imgs + '</div>'
            + (bestE
                ? wlCarbonStrip(bestE.delta_e_wh, 'Image · best of CPU vs GPU',
                                bestE.delta_t_s, bestSavedG, subRuns)
                : '')
            + '</div>';
    } else {
      var e = r.energy;
      var gen = r.generation;
      if (!e) return html + _wlBadRecord('Image', r);
      var wh = e.wh_per_image || e.delta_e_wh;
      var savedG = e.co2e && e.co2e.intensity ? e.co2e.intensity.g_per_kwh : null;
      var imgHtml = gen && gen.b64_png
        ? '<img src="data:image/png;base64,' + gen.b64_png + '" '
          + 'style="max-width:100%;border:1px solid var(--border);display:block;margin-top:1rem">'
        : '';
      html += '<div class="result-card">'
            + _promptBlock(r.full_prompt, null, 'Prompt')
            + '<div class="kpi-row">'
            +   '<div class="kpi"><div class="val">' + _f(wh,4) + ' Wh</div><div class="lbl">energy / image</div></div>'
            +   '<div class="kpi"><div class="val">' + _f(gen && gen.total_s,1) + 's</div><div class="lbl">generation time</div></div>'
            +   '<div class="kpi"><div class="val">' + _f(e.delta_w,1) + ' W</div><div class="lbl">delta above idle</div></div>'
            + '</div>'
            + '<div class="conf-badge">' + e.confidence.flag + ' ' + e.confidence.label + '</div>'
            + (e.video_relative ? '<div style="margin-top:0.5rem;font-size:0.78rem;color:var(--text-3)">This run ' + e.video_relative.text + '</div>' : '')
            + imgHtml
            + wlCarbonStrip(wh, (r.model_label || 'Image generation') + ' · single', e.delta_t_s, savedG)
            + '</div>';
    }
    return html;
  };

  // ─── Enhance (/enhance-run · Pixop pipeline) ──────────────────────────────
  // Compact card for enhance results — findings cite these (S48 sweet-spot
  // sweep) and /results lists them. Unlike image/llm, the enhance envelope
  // nests its payload under `.result`, so normalise first.
  window.wlRenderEnhanceCard = function(opts){
    var r = (opts && opts.result) || {};
    var html = _prevNote(opts && opts.isPrev, opts && opts.savedAt);
    if (r.mode === 'enhance_compare') {
      // AI-vs-ffmpeg-filter compare run: top-level envelope with `ml` and
      // `ffmpeg` sub-envelopes plus a precomputed `comparison` block.
      var cp = r.comparison || {};
      var mlR = (r.ml && r.ml.result) || {};
      var ffR = (r.ffmpeg && r.ffmpeg.result) || {};
      var mlC = mlR.energy && mlR.energy.confidence;
      var ffC = ffR.energy && ffR.energy.confidence;
      var fLbl = r.ff_filter || 'ffmpeg';
      var q = '';
      if (mlR.vqa && mlR.vqa.score != null && ffR.vqa && ffR.vqa.score != null) {
        q = '<div style="margin-top:0.5rem;font-size:0.78rem;color:var(--text-3)">'
          + 'Quality (' + (mlR.vqa.model || 'NR-VQA') + '): AI ' + _f(mlR.vqa.score, 2)
          + ' vs ' + fLbl + ' ' + _f(ffR.vqa.score, 2)
          + (r.source_vqa && r.source_vqa.score != null
              ? ' · source ' + _f(r.source_vqa.score, 2) : '')
          + '</div>';
      }
      html += '<div class="result-card">'
            + '<p class="headline">AI upscale vs ' + fLbl + ' — '
            +   (r.input_name || '?') + ' → ' + (r.target_res || '?') + '</p>'
            + '<div class="kpi-row">'
            +   '<div class="kpi"><div class="val">' + _f(cp.ml_delta_e_wh, 2) + ' Wh</div><div class="lbl">AI pipeline</div></div>'
            +   '<div class="kpi"><div class="val">' + _f(cp.ff_delta_e_wh, 2) + ' Wh</div><div class="lbl">' + fLbl + '</div></div>'
            +   '<div class="kpi"><div class="val">' + _f(cp.energy_ratio, 1) + '×</div><div class="lbl">energy ratio</div></div>'
            + '</div>'
            + ((mlC || ffC)
                ? '<div class="conf-badge">'
                  + (mlC ? mlC.flag + ' AI' : '') + (mlC && ffC ? ' · ' : '')
                  + (ffC ? ffC.flag + ' ' + fLbl : '') + '</div>' : '')
            + q
            + (cp.quality_note
                ? '<div style="margin-top:0.4rem;font-size:0.72rem;color:var(--text-4)">'
                  + cp.quality_note + '</div>' : '')
            + '</div>';
      return html;
    }
    var d = r.result || r;
    var e = d.energy;
    if (!e) return html + _wlBadRecord('Enhance', r);
    var savedG = e.co2e && e.co2e.intensity ? e.co2e.intensity.g_per_kwh : null;
    var io = (d.input_name || '?') + ' → ' + (d.output_name || '?');
    var st = d.stream || {};
    var outFmt = (st.width && st.height ? st.width + '×' + st.height : '')
               + (st.codec ? ' ' + st.codec : '')
               + (d.output_size_mb != null ? ' · ' + _f(d.output_size_mb, 0) + ' MB' : '');
    var vqaHtml = '';
    if (d.vqa && d.vqa.score != null) {
      var src = d.source_vqa && d.source_vqa.score != null ? d.source_vqa.score : null;
      var delta = src != null ? d.vqa.score - src : null;
      vqaHtml = '<div style="margin-top:0.5rem;font-size:0.78rem;color:var(--text-3)">'
              + 'Quality (' + (d.vqa.model || 'NR-VQA') + '): '
              + (src != null ? _f(src, 2) + ' → ' : '')
              + _f(d.vqa.score, 2)
              + (delta != null ? ' (Δ ' + (delta >= 0 ? '+' : '') + _f(delta, 2) + ')' : '')
              + '</div>';
    }
    html += '<div class="result-card">'
          + '<p class="headline">' + (d.preset_label || 'Enhancement run') + '</p>'
          + '<div style="font-size:0.78rem;color:var(--text-3);font-family:monospace;'
          +   'margin-bottom:0.85rem">' + io
          +   (outFmt ? '<br>output: ' + outFmt : '') + '</div>'
          + '<div class="kpi-row">'
          +   '<div class="kpi"><div class="val">' + _f(e.delta_e_wh, 2) + ' Wh</div><div class="lbl">energy</div></div>'
          +   '<div class="kpi"><div class="val">' + _f(e.delta_t_s, 0) + 's</div><div class="lbl">duration</div></div>'
          +   '<div class="kpi"><div class="val">' + _f(e.delta_w, 1) + ' W</div><div class="lbl">delta above idle</div></div>'
          + '</div>'
          + (e.confidence ? '<div class="conf-badge">' + e.confidence.flag + ' '
                          + e.confidence.label + '</div>' : '')
          + vqaHtml
          + wlCarbonStrip(e.delta_e_wh, (d.preset_label || 'Enhance') + ' · single', e.delta_t_s, savedG)
          + '</div>';
    return html;
  };
})();
