// Extracted from main.py (Phase 1, 2026-06-10) — see ARCHITECTURE.md.
// Requires window.WL_CFG (loaded via /ui-config.js before this file).
// Defensive fallback: if that fetch failed (e.g. a proxy 429), degrade to
// generic wording instead of throwing and killing every poll loop below.
window.WL_CFG = window.WL_CFG || {baseline_s: '\u2014', cooldown_s: '\u2014',
  cooldown_label: 'Cooldown', cooldown_paren: '', rest_label: 'Rest',
  idle_label: 'Idle', llm_rest_s: '\u2014', meter_name: 'power meter',
  show_wait_detail: true, idle_tolerance_w: 3, urls: {}};
var WL_CFG = window.WL_CFG;
(function(){
  var _zonesPromise = null;
  function loadZones(){
    if (_zonesPromise) return _zonesPromise;
    _zonesPromise = fetch('/carbon').then(function(r){return r.json();})
      .catch(function(){ _zonesPromise = null; return null; });
    return _zonesPromise;
  }
  // Warm the cache on every page that loads the footer.
  loadZones();

  function fmtG(v){
    if (v == null) return '—';
    if (v < 1)   return v.toFixed(3);
    if (v < 100) return v.toFixed(2);
    return v.toFixed(1);
  }
  // Auto-switch unit for mass — keeps ~2 significant figures readable across
  // many orders of magnitude. A tiny transcode in France (~0.0004 g) shows
  // as "0.40 mg" instead of "0.000 g". Returned string includes the unit.
  // When grams <= 0 we return em-dash: ΔE either rounded to 0 Wh or went
  // sub-baseline (short task + 1Hz polling can land 2 polls below idle by
  // chance — same measurement-floor situation, opposite sign of noise).
  // Newly persisted results have grams clamped server-side; the <= 0 check
  // here is defensive for older results already on disk.
  function fmtMass(g){
    if (g == null) return '—';
    if (g <= 0)    return '—';
    var ag = Math.abs(g);
    if (ag >= 1e6)      return (g/1e6).toFixed(2)  + ' t';   // tonnes — large continuous projections
    if (ag >= 1000)     return (g/1000).toFixed(2) + ' kg';
    if (ag >= 1)        return g.toFixed(2)        + ' g';
    if (ag >= 0.001)    return (g*1000).toFixed(2) + ' mg';
    if (ag >= 1e-6)     return (g*1e6).toFixed(2)  + ' µg';
    return g.toExponential(2) + ' g';
  }
  // Energy formatter — auto-switches Wh/kWh/MWh/GWh so projected runs
  // (1 day / 1 month / 1 year continuous) don't show as "131400 Wh" when
  // "131 kWh" is more legible. Returns the value-with-unit as a single
  // string; callers should NOT append ' Wh' themselves (unlike fmtG).
  function fmtEnergy(wh){
    if (wh == null) return '—';
    var aw = Math.abs(wh);
    if (aw >= 1e9)   return (wh/1e9).toFixed(2)  + ' GWh';
    if (aw >= 1e6)   return (wh/1e6).toFixed(2)  + ' MWh';
    if (aw >= 1e4)   return (wh/1000).toFixed(1) + ' kWh';
    if (aw >= 1000)  return (wh/1000).toFixed(2) + ' kWh';
    if (aw >= 100)   return wh.toFixed(1)        + ' Wh';
    if (aw >= 1)     return wh.toFixed(2)        + ' Wh';
    return wh.toFixed(3) + ' Wh';
  }
  // Tooltip for mass cells. Spells out the unit relationship and shows the
  // exact value in scientific notation, so visitors can never confuse µg
  // (microgram, 1e-6 g) with mg (milligram, 1e-3 g) — a 1000× difference
  // that is easy to misread in speech and at a glance. The U+00B5 µ glyph
  // is used consistently throughout this widget; the tooltip names it
  // explicitly so screen readers and copy-paste consumers get the same.
  function massTitle(g){
    if (g == null || g <= 0) return '';
    return 'CO₂e mass · 1 mg = 1000 µg = 1e-3 g · '
         + 'this value: ' + g.toExponential(3) + ' g';
  }
  // Tooltip attached to "below measurement floor" displays — same wording
  // wherever the floor is hit, single source of truth.
  var BELOW_FLOOR_TOOLTIP =
    'ΔE rounded to 0 Wh — the task was too short or too efficient '
    + 'to register above the P110 ~1W × 1s poll noise floor. '
    + 'Try batch mode for reliable µ-scale readings.';
  // EV-distance equivalence — relatable physical-world comparator for the
  // CO2e block. ~50 g CO2e/km is a typical European EV operational
  // intensity on a lifecycle grid mix (Transport & Environment 2024 fleet
  // average). Imprecise on purpose; the point is "give visitors a feel for
  // the magnitude in something they understand."
  // Floor: below ~10 mm of EV driving the comparator reads as too cute and
  // undermines credibility — visitors who care about µg-scale carbon read
  // the µg figure directly. 0.0005 g ÷ 50 g/km = 10 mm.
  var EV_G_PER_KM = 50;
  var EV_FLOOR_GRAMS = 0.0005;  // 10 mm — below this, suppress the row.
  function fmtEvDistance(grams){
    if (grams == null || grams <= 0) return '';
    if (grams < EV_FLOOR_GRAMS)      return '';
    var km = grams / EV_G_PER_KM;
    if (km >= 1)     return km.toFixed(2) + ' km';
    if (km >= 0.001) return (km * 1000).toFixed(1) + ' m';
    return (km * 1e6).toFixed(0) + ' mm';
  }
  function fmtAge(s){
    if (s == null) return '';
    if (s < 90)   return Math.round(s) + 's ago';
    if (s < 5400) return Math.round(s/60) + 'm ago';
    return Math.round(s/3600) + 'h ago';
  }
  function liveBadge(){
    return '<span title="ElectricityMaps real-time grid intensity" style="color:var(--accent);'
         + 'font-size:0.6rem;font-family:monospace;letter-spacing:0.06em;padding:0.05rem 0.3rem;'
         + 'border:1px solid var(--accent);border-radius:2px;margin-left:0.4rem">LIVE</span>';
  }
  function estBadge(){
    return '<span title="Ember 2025 annual mean — fallback when live data is unavailable" '
         + 'style="color:var(--text-4);font-size:0.6rem;font-family:monospace;letter-spacing:0.06em;'
         + 'padding:0.05rem 0.3rem;border:1px solid var(--border-3);border-radius:2px;margin-left:0.4rem">EST</span>';
  }

  // Inline CO2e row, mirroring the look of metricRow(). Reads energy.co2e
  // baked in by persist.save_result() → carbon.walk_and_enrich(). For older
  // results without enrichment, returns empty string (no broken row).
  // When grams === 0 (ΔE below P110 floor), surfaces "below measurement
  // floor" with a tooltip rather than rendering a misleading "0 g".
  // CR-036 — the inline carbon row under each ΔE picks up the same 🟡
  // INDICATIVE language as the strip. The "(est.)" suffix is replaced
  // by an amber chip, and the mass cell is amber-tinted to match the
  // strip headline. Below-floor branch keeps the muted-grey treatment
  // since the value itself is the absence of a measurable signal.
  var INDICATIVE_INLINE_CHIP =
      '<span style="color:var(--warn);font-family:monospace;font-size:0.58rem;'
    + 'letter-spacing:0.06em;text-transform:uppercase;border:1px solid rgba(255,170,0,0.55);'
    + 'padding:0.02rem 0.28rem;border-radius:2px;margin-left:0.35rem;vertical-align:middle" '
    + 'title="Indicative — Wh × third-party grid intensity. Not a GoS primary '
    + 'measurement. See /methodology for the basis.">🟡 indicative</span>';
  window.wlCarbonRow = function(energy){
    if (!energy || !energy.co2e || !energy.co2e.intensity) return '';
    var c = energy.co2e;
    var i = c.intensity;
    var live = i.source === 'live';
    if (c.grams <= 0) {
      return '<div class="metric" title="' + BELOW_FLOOR_TOOLTIP + '">'
           + '<span>CO₂e' + INDICATIVE_INLINE_CHIP + '</span>'
           + '<span class="val" style="color:var(--text-4)">— '
           + '<span style="color:var(--text-5);font-size:0.7rem;font-family:monospace;'
           + 'margin-left:0.5rem;font-weight:normal">below measurement floor</span>'
           + '</span></div>';
    }
    var freshness = live
      ? (i.zone_label + ' · ' + i.g_per_kwh + ' g/kWh · ' + fmtAge(i.age_s))
      : (i.zone_label + ' · ' + i.g_per_kwh + ' g/kWh · ' + (i.year ? i.year + ' mean' : 'annual mean'));
    return '<div class="metric"><span>CO₂e' + INDICATIVE_INLINE_CHIP + '</span>'
         + '<span class="val" style="color:var(--warn)" '
         + 'title="' + massTitle(c.grams) + '">' + fmtMass(c.grams)
         + (live ? liveBadge() : estBadge())
         + '<span style="color:var(--text-4);font-size:0.7rem;font-family:monospace;'
         + 'margin-left:0.5rem;font-weight:normal">' + freshness + '</span>'
         + '</span></div>';
  };

  // 24/7 continuous-service projection. When durationS is provided, an
  // opt-in toggle multiplies the displayed energy + carbon by the ratio of
  // a chosen window to the run's actual duration. Makes "this single job ×
  // time" → real-impact intuitions tangible without forcing the visitor to
  // do the arithmetic. Toggle state lives in the URL hash (#continuous=1d)
  // so the projection is shareable. Default 'off' = as-measured (×1). The
  // toggle is hidden when durationS is missing — compare-mode strips don't
  // pass it (which mode's duration would we project?), so the projection
  // simply isn't offered there in V1.
  var CONTINUOUS_SECONDS = {'1h': 3600, '1d': 86400, '1mo': 2628000, '1y': 31536000};
  var CONTINUOUS_LABELS  = {'off':'as-measured','1h':'1 hour','1d':'1 day','1mo':'1 month','1y':'1 year'};
  var CONTINUOUS_KEYS    = ['off','1h','1d','1mo','1y'];
  function continuousMul(key, durationS){
    if (key === 'off' || !durationS || durationS <= 0) return 1;
    var s = CONTINUOUS_SECONDS[key];
    return s ? s / durationS : 1;
  }
  function readContinuousHash(){
    var m = (window.location.hash || '').match(/continuous=(off|1h|1d|1mo|1y)/);
    return m ? m[1] : 'off';
  }
  function writeContinuousHash(key){
    var h = (window.location.hash || '').replace(/^#/, '');
    var parts = h.split('&').filter(function(p){ return p && !/^continuous=/.test(p); });
    if (key && key !== 'off') parts.push('continuous=' + key);
    var newHash = parts.length ? '#' + parts.join('&') : window.location.pathname;
    // history.replaceState avoids the scroll-to-anchor jump that direct
    // location.hash mutation triggers when the strip lives mid-page.
    var url = window.location.pathname + window.location.search
            + (parts.length ? '#' + parts.join('&') : '');
    window.history.replaceState(null, '', url);
  }

  // Comparison strip — one block per report, shows the same Wh figure across
  // home + comparison zones. Home is live (with static fallback); other
  // zones are static so values don't drift between page loads. Returns a
  // placeholder synchronously and fills it in once /carbon resolves.
  // Optional durationS enables the 24/7 projection toggle.
  // Optional savedIntensityG is the home-zone g/kWh that prevailed when
  // the run was saved (from energy.co2e.intensity.g_per_kwh in the result
  // JSON). When it diverges materially from the current live intensity,
  // the strip surfaces a drift note so the visitor understands why the
  // headline number here can differ from the per-column inline numbers
  // above (which are frozen at save time).
  // CR-032: optional `subRuns` argument for compare-mode strips.
  //   subRuns = [{label, grams, deltaWh, durationS}, ...]
  //   - grams       : saved-snapshot CO2e (energy.co2e.grams)
  //   - deltaWh     : per-sub-run measured Wh (energy.delta_e_wh)
  //   - durationS   : per-sub-run wall-time (energy.delta_t_s) — used so
  //                   the 24/7 projection multiplier scales each sub-run by
  //                   its own duration, not the headline's
  // Single-run callers pass null/undefined and behave unchanged.
  // Idle-wait timeout dialog (attended Lab runs). Here in _CARBON_JS (IIFE → must
  // attach to window) so it's available on every page the poll loops run on,
  // including /llm/compare & /rag/compare which don't load _PROGRESS_JS.
  var _wlCdShown = false;
  window.wlCooldownDialogClose = function(){
    var ov = document.getElementById('wl-cd-overlay');
    if (ov) ov.remove();
    _wlCdShown = false;
  };
  window.wlCooldownDecide = function(jobId, decision){
    var body = new URLSearchParams();
    body.append('decision', decision);
    fetch('/job/' + jobId + '/cooldown-decision', {method: 'POST', body: body}).catch(function(){});
    window.wlCooldownDialogClose();
  };
  window.wlCooldownDialog = function(jobId, options){
    if (_wlCdShown) return;
    _wlCdShown = true;
    options = (options && options.length) ? options : ['run', 'cancel'];
    var labels = {wait: '⟳ Wait again', run: '▶ Run anyway', cancel: '✕ Cancel run'};
    var colors = {wait: 'var(--accent)', run: 'var(--warn)', cancel: 'var(--err)'};
    var ov = document.createElement('div');
    ov.id = 'wl-cd-overlay';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center';
    var box = document.createElement('div');
    box.style.cssText = 'background:var(--bg);border:1px solid var(--warn);max-width:440px;padding:1.5rem;font-family:monospace';
    var title = document.createElement('div');
    title.style.cssText = 'color:var(--warn);font-size:1rem;margin-bottom:0.6rem';
    title.textContent = 'Cooldown did not reach the idle floor';
    var msg = document.createElement('div');
    msg.style.cssText = 'color:var(--text-3);font-size:0.82rem;line-height:1.5;margin-bottom:1rem';
    msg.textContent = 'Power has not settled back to the idle floor within the max wait. Run anyway proceeds now and records the next run as not cleanly spaced (settled:false). If unanswered, it auto-proceeds (one fixed rest, then run) after the watchdog.';
    var row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:0.5rem;flex-wrap:wrap';
    options.forEach(function(o){
      var b = document.createElement('button');
      b.textContent = labels[o] || o;
      b.style.cssText = 'font-family:monospace;font-size:0.85rem;padding:0.5rem 0.9rem;cursor:pointer;background:var(--panel);border:1px solid ' + (colors[o] || 'var(--border)') + ';color:' + (colors[o] || 'var(--text)');
      b.onclick = function(){ window.wlCooldownDecide(jobId, o); };
      row.appendChild(b);
    });
    box.appendChild(title); box.appendChild(msg); box.appendChild(row);
    ov.appendChild(box);
    document.body.appendChild(ov);
  };

  // Compact summary of the inter-run cooldowns stamped on a result
  // (r.cooldowns = [{method, waited_s, settled, timed_out}, …]). Generic across
  // llm / rag / image / video compares. Returns '' when absent (old results).
  // Lives in _CARBON_JS so it's available on every page wlCarbonStrip is.
  // Stamp-key variants (docs/result_envelope.md): the measurement modules'
  // CPU-vs-GPU paths stamp a single dict under "cooldown" — accept that
  // shape too, so callers can pass r.cooldowns || r.cooldown.
  window.wlCooldownSummary = function(cooldowns){
    if (!cooldowns) return '';
    if (!Array.isArray(cooldowns)) cooldowns = [cooldowns];
    if (!cooldowns.length) return '';
    var parts = cooldowns.map(function(c){
      var s = (c && c.waited_s != null) ? Number(c.waited_s).toFixed(0) + 's' : '?';
      var m = (c && c.method === 'fixed') ? 'fixed' : (c && c.settled ? 'idle' : 'idle\u2192fallback');
      return s + ' (' + m + ')';
    });
    return '<div style="color:var(--text-4);font-size:0.72rem;margin-top:0.5rem">'
         + '\u23f3 Cooldowns between runs: ' + parts.join(' \u00b7 ') + '</div>';
  };

  window.wlCarbonStrip = function(wh, label, durationS, savedIntensityG, subRuns){
    if (wh == null || isNaN(wh)) return '';
    var elId = 'carbon-strip-' + Math.random().toString(36).slice(2,9);
    // CR-036 — amber-tinted outer border + warn-coloured top edge so the
    // whole block reads as "indicative third-party data" before the
    // visitor reads a single number inside. Border alpha is intentionally
    // light (--warn at ~25%) so the strip stays a lab block, not a
    // marketing banner. Energy results above keep the accent-green
    // chrome; the contrast is the signal.
    var html = '<div id="' + elId + '" class="carbon-strip" '
             + 'style="margin:0.75rem 0;padding:0.7rem 0.85rem;background:var(--panel-2);'
             + 'border:1px solid rgba(255,170,0,0.30);border-top:2px solid rgba(255,170,0,0.45);'
             + 'font-size:0.78rem">'
             + '<div style="color:var(--text-4);font-size:0.7rem">'
             + 'CO₂e — loading grid intensity…</div></div>';
    var dur = (durationS != null && !isNaN(durationS) && durationS > 0)
            ? parseFloat(durationS) : null;
    var savedG = (savedIntensityG != null && !isNaN(savedIntensityG))
            ? parseFloat(savedIntensityG) : null;
    var subs = Array.isArray(subRuns) ? subRuns.filter(function(s){
      return s && s.label != null && s.grams != null && !isNaN(s.grams);
    }) : null;
    if (subs && subs.length === 0) subs = null;
    setTimeout(function(){ _renderStrip(elId, parseFloat(wh), label || '', dur, savedG, subs); }, 0);
    return html;
  };

  async function _renderStrip(elId, wh, label, durationS, savedIntensityG, subRuns){
    var el = document.getElementById(elId);
    if (!el) return;
    var d = await loadZones();
    if (!d) {
      el.innerHTML = '<div style="color:var(--text-4);font-size:0.72rem">'
                   + 'CO₂e comparison unavailable.</div>';
      return;
    }
    var canProject = durationS != null && durationS > 0;
    // ΔE rounded to 0 — comparing 0 g across grids is meaningless, so render
    // a clean placeholder instead of a "0 µg" row for every city.
    if (wh === 0) {
      el.innerHTML =
          '<div title="' + BELOW_FLOOR_TOOLTIP + '" '
        + 'style="display:flex;align-items:baseline;flex-wrap:wrap;gap:0.4rem 0.75rem">'
        + '<span style="color:var(--text-4);font-size:0.7rem;letter-spacing:0.04em;'
        + 'text-transform:uppercase">CO₂e</span>'
        + '<span style="color:var(--text-3);font-size:0.85rem;'
        + 'font-family:monospace;line-height:1">—</span>'
        + '<span style="color:var(--text-4);font-size:0.72rem;font-family:monospace">'
        + 'below P110 measurement floor</span>'
        + '</div>'
        + '<div style="color:var(--text-5);font-size:0.7rem;font-family:monospace;margin-top:0.3rem">'
        + 'ΔE rounded to 0 Wh; task too short or too efficient to lift power above ~1 W × 1 s poll noise. '
        + 'Try batch mode for reliable µ-scale readings.'
        + '</div>';
      return;
    }
    // Continuous-service projection state — read from URL hash so links
    // share the projection. Multiplier scales the displayed Wh + every
    // grams calc; original `wh` is preserved for the recursive re-render
    // on toggle change.
    var continuousKey = canProject ? readContinuousHash() : 'off';
    var mul           = continuousMul(continuousKey, durationS);
    var displayWh     = wh * mul;

    var home    = d.home_zone;
    var homeI   = d.home_intensity || {};
    var zones   = d.comparison_zones || [];
    var statics = d.static_table || {};
    var history = (d.historical_table || []).filter(function(h){ return h.zone === home; });

    // Headline: home-zone gCO2e — the number visitors should walk away with.
    var homeIntensity = homeI.g_per_kwh;
    var homeGrams = (homeIntensity != null) ? (displayWh / 1000) * homeIntensity : null;

    // Drift note — when the home-zone live intensity at page-load time
    // differs ≥1% from the intensity that was live when the result was
    // saved, surface the gap so visitors don't read the strip headline as
    // contradicting the per-column inline rows above. Both sources of
    // truth coexist — the inline rows are an audit trail (what was the
    // grid when we measured?), the strip headline is the "right now"
    // framing (what does this look like on today's grid?).
    var driftNoteHtml = '';
    var _homeIsLive = (homeI.source === 'live');
    if (_homeIsLive && savedIntensityG != null && homeIntensity != null
        && homeIntensity > 0 && savedIntensityG > 0) {
      var driftPct = (homeIntensity - savedIntensityG) / savedIntensityG;
      if (Math.abs(driftPct) >= 0.01) {
        var driftDir = driftPct > 0 ? 'up' : 'down';
        var driftAbs = (Math.abs(driftPct) * 100).toFixed(1) + '%';
        driftNoteHtml =
            '<div style="margin-top:0.3rem;color:var(--text-5);font-size:0.66rem;'
          + 'font-family:monospace;font-style:italic;line-height:1.4" '
          + 'title="Per-column CO₂e rows above are frozen at the moment '
          + 'this result was saved. The strip headline here is recomputed '
          + 'on every page load using current live grid data. Both are '
          + 'correct for their respective timestamps.">'
          + 'Grid moved ' + driftAbs + ' ' + driftDir + ' since this run was saved · '
          + 'saved at ' + savedIntensityG + ' g/kWh, current ' + homeIntensity + ' g/kWh · '
          + 'rows above show the saved snapshot, headline shows live now'
          + '</div>';
      }
    }
    var homeLive = (homeI.source === 'live');
    var homeFreshness = homeLive
      ? fmtAge(homeI.age_s)
      : (homeI.year ? (homeI.year + ' mean') : 'annual mean');
    // Projection-aware subtitle. When the toggle is on, prepend a "projected"
    // marker so visitors don't read the projected Wh as the measured Wh.
    var projectionPrefix = (continuousKey !== 'off')
      ? ('Projected over ' + CONTINUOUS_LABELS[continuousKey] + ' continuous · ')
      : '';
    var headlineSubtitle = projectionPrefix
      + (label ? (label + ' · ') : '')
      + fmtEnergy(displayWh);

    // Provider line, only meaningful for LIVE rows.
    var providerStr = '';
    if (homeLive) {
      var prov = homeI.provider || 'live';
      providerStr = ' · ' + prov;
    }

    // CR-036 — top-of-strip "indicative only" framing. Replaces the prior
    // "High-level CO₂e estimate" caption with an explicit 🟡 chip + a
    // one-line basis statement, anchored to the data-quality framework
    // the Language Lab AI position paper (Jan 2026) proposes:
    //   🟢 Direct measurement — the energy block above.
    //   🟡 Indicative — third-party grid factors × live mix; this block.
    // Single line, monospace, amber — communicates the asymmetry without
    // recoloring the actual values (which would hurt readability). The
    // tooltip carries the long form so the visible chrome stays compact.
    var estimateCaption =
        '<div style="margin-bottom:0.45rem;display:flex;align-items:baseline;'
      + 'flex-wrap:wrap;gap:0.45rem">'
      + '<span style="color:var(--warn);font-family:monospace;font-size:0.62rem;'
      + 'letter-spacing:0.08em;text-transform:uppercase;'
      + 'border:1px solid rgba(255,170,0,0.55);padding:0.1rem 0.4rem;'
      + 'border-radius:2px" '
      + 'title="🟢 Direct measurement = the energy figure above (P110 polling, '
      + 'validated method). 🟡 Indicative = this carbon block — Wh × grid '
      + 'intensity from third-party sources (IPCC AR6 lifecycle factors × the '
      + 'live or recent grid mix). Not a GoS primary measurement; provided '
      + 'for context, not for citation. See /methodology.">'
      + '🟡 Indicative'
      + '</span>'
      + '<span style="color:var(--text-4);font-size:0.7rem;font-family:monospace;'
      + 'letter-spacing:0.02em">'
      + 'Third-party grid factors · use phase only · '
      + '<a href="/methodology" style="color:var(--text-3);text-decoration:none;'
      + 'border-bottom:1px solid var(--border-3)">methodology</a>'
      + '</span>'
      + '</div>';

    // EV-distance equivalence — a relatable physical-world comparator.
    // Suppressed if homeGrams is null/0 (already covered by the headline).
    var evHtml = '';
    if (homeGrams != null && homeGrams > 0) {
      var evDist = fmtEvDistance(homeGrams);
      if (evDist) {
        evHtml =
            '<div style="color:var(--text-4);font-size:0.7rem;font-family:monospace;'
          + 'margin-top:0.15rem" '
          + 'title="Typical European EV at ~50 g CO2e/km (Transport & Environment '
          + '2024 fleet average). Relatable scale, not precise.">'
          + '≈ ' + evDist + ' driving a typical EV'
          + '</div>';
      }
    }

    // 24/7 continuous-projection toggle. Hidden when no run duration is
    // known (compare-mode strips). Sits just above the EV line because both
    // are "what does this mean in tangible terms" affordances; together
    // they answer "this single run × time = real impact" without the
    // visitor doing the arithmetic. State persists in the URL hash so a
    // shared link reproduces the projection.
    var toggleHtml = '';
    if (canProject) {
      var optHtml = CONTINUOUS_KEYS.map(function(k){
        return '<option value="' + k + '"'
             + (k === continuousKey ? ' selected' : '')
             + '>' + CONTINUOUS_LABELS[k] + '</option>';
      }).join('');
      toggleHtml =
          '<div style="margin-top:0.4rem;font-family:monospace;font-size:0.7rem;'
        + 'color:var(--text-4)" '
        + 'title="Project this run as if the workload ran continuously for '
        + 'the chosen window (e.g. live-stream encoding, model serving). '
        + 'Off = as-measured. Multiplies the displayed Wh + every gCO₂e '
        + 'figure by window-seconds ÷ run-seconds.">'
        + 'Continuous projection: '
        + '<select data-continuous-toggle '
        + 'style="background:var(--panel);color:var(--text-2);border:1px solid var(--border-3);'
        + 'font-family:monospace;font-size:0.7rem;padding:0.1rem 0.3rem;margin-left:0.2rem">'
        + optHtml
        + '</select>'
        + '</div>';
    }

    // CR-036 — headline mass takes the --warn palette (carbon = amber across
    // the strip). Energy retains --accent (green) on the result card above,
    // so the contrast itself is the 🟢-direct vs 🟡-indicative signal.
    var headlineHtml =
        '<div style="display:flex;align-items:baseline;flex-wrap:wrap;gap:0.4rem 0.75rem;'
      + 'margin-bottom:0.3rem">'
      + '<span style="color:var(--text-4);font-size:0.7rem;letter-spacing:0.04em;'
      + 'text-transform:uppercase">CO₂e</span>'
      + '<span style="color:var(--warn);font-size:0.85rem;font-family:monospace;'
      + 'line-height:1"' + (homeGrams != null ? ' title="' + massTitle(homeGrams) + '"' : '') + '>'
      + (homeGrams != null ? fmtMass(homeGrams) : '—') + '</span>'
      + (homeLive ? liveBadge() : estBadge())
      + '<span style="color:var(--text-4);font-size:0.72rem;font-family:monospace">'
      + 'in ' + (homeI.zone_label || home) + '</span>'
      + '</div>'
      + '<div style="color:var(--text-4);font-size:0.72rem;font-family:monospace">'
      + headlineSubtitle + ' · grid intensity '
      + (homeIntensity != null
          ? (homeIntensity + ' g/kWh · ' + homeFreshness + providerStr)
          : 'unknown')
      + '</div>'
      + driftNoteHtml
      + toggleHtml
      + evHtml;

    // CR-032 (two-column variant, refined) — for compare-mode strips:
    //   * Header + reference row (per-side data) render in side-by-side
    //     columns at the top of <details>, where each column is narrow but
    //     the data per side genuinely differs.
    //   * Comparison rows ("on other grids") and historical rows render
    //     full-width below — the intensities are the same for both sides,
    //     only the gram totals differ, so we render one row per zone with
    //     two mass cells side-by-side. Avoids the truncation problem of
    //     fitting full row content into a 280-px column.
    //
    // For single-run, one block with all sections — back-compat.
    //
    // buildSideBlock now takes `compactMode`: when true, emits only the
    // header + reference (compare-mode column); when false (single-run),
    // emits the full set including comparison + historical.
    function buildSideBlock(sideDisplayWh, sideLabel, isWinner, includeHeader, compactMode) {
      var sideHomeGrams = (homeIntensity != null)
        ? (sideDisplayWh / 1000) * homeIntensity : null;

      // ── Mini per-side header (compare-mode only) ──
      var sideHeader = '';
      if (includeHeader) {
        var bestTag = isWinner
          ? '<span style="margin-left:0.4rem;font-size:0.6rem;letter-spacing:0.06em;'
            + 'padding:0.05rem 0.3rem;border:1px solid var(--accent);color:var(--accent);'
            + 'border-radius:2px;font-family:monospace">BEST</span>'
          : '';
        sideHeader =
            '<div style="margin-bottom:0.4rem;padding-bottom:0.4rem;'
          + 'border-bottom:1px solid var(--border-2)">'
          + '<div style="display:flex;align-items:baseline;flex-wrap:wrap;gap:0.4rem 0.6rem">'
          + '<span style="color:var(--text);font-size:0.85rem;font-family:monospace;'
          + 'font-weight:bold"' + (sideHomeGrams != null ? ' title="' + massTitle(sideHomeGrams) + '"' : '') + '>'
          + (sideHomeGrams != null ? fmtMass(sideHomeGrams) : '—') + '</span>'
          + bestTag
          + '</div>'
          + '<div style="color:var(--text-3);font-size:0.72rem;font-family:monospace;'
          + 'margin-top:0.15rem">' + sideLabel + ' · ' + fmtEnergy(sideDisplayWh) + '</div>'
          + '</div>';
      }

      // ── Per-side reference row (FR REF) ──
      // Row layout: label · mass · intensity. Trailing "·  YYYY mean" is
      // dropped — the section heading above already says "Ember 2025
      // annual means" so the suffix is redundant and was forcing the row
      // wider than the parent column could accommodate.
      var sideRefRow = '';
      var sideDivergence = '';
      if (homeLive) {
        var refStaticS = statics[home];
        var refIntensityS = refStaticS && refStaticS.g_per_kwh;
        if (refIntensityS != null) {
          var refYearS  = refStaticS.year;
          var refLabelS = refStaticS.label || home;
          var refGramsS = (sideDisplayWh / 1000) * refIntensityS;
          sideRefRow =
              '<div style="display:flex;align-items:baseline;justify-content:space-between;'
            + 'gap:0.5rem;padding:0.35rem 0.4rem;font-family:monospace;'
            + 'background:var(--panel);border-left:2px solid var(--border-3)">'
            + '<span style="color:var(--text-2);flex:1;min-width:0;overflow:hidden;'
            + 'text-overflow:ellipsis">' + refLabelS
            + '<span title="Ember annual mean — reference baseline for the home zone" '
            + 'style="color:var(--text-4);font-size:0.6rem;font-family:monospace;letter-spacing:0.06em;'
            + 'padding:0.05rem 0.3rem;border:1px solid var(--border-3);border-radius:2px;'
            + 'margin-left:0.4rem">REF</span></span>'
            + '<span style="color:var(--text);white-space:nowrap;font-weight:bold;'
            + 'min-width:70px;text-align:right" title="' + massTitle(refGramsS) + '">'
            + fmtMass(refGramsS) + '</span>'
            + '<span style="color:var(--text-5);font-size:0.7rem;white-space:nowrap;'
            + 'min-width:60px;text-align:right" '
            + 'title="' + refIntensityS + ' g/kWh · ' + (refYearS ? refYearS + ' annual mean' : 'annual mean') + '">'
            + refIntensityS + ' g/kWh'
            + '</span>'
            + '</div>';
          if (homeIntensity != null && refIntensityS > 0) {
            var devS = (homeIntensity - refIntensityS) / refIntensityS;
            if (Math.abs(devS) >= 0.25) {
              var pctStrS = (Math.abs(devS) * 100).toFixed(0) + '%';
              var dirS = devS < 0 ? 'cleaner than' : 'dirtier than';
              sideDivergence =
                  '<div style="padding:0.2rem 0.5rem 0.5rem;color:var(--text-3);'
                + 'font-size:0.72rem;font-style:italic">'
                + 'Today’s grid is ~' + pctStrS + ' ' + dirS + ' the '
                + (refYearS ? refYearS + ' ' : '') + 'mean for this zone.'
                + '</div>';
            }
          }
        }
      }
      var sideRefBlock = sideRefRow
        ? ('<div style="color:var(--text-5);font-size:0.65rem;letter-spacing:0.04em;'
           + 'text-transform:uppercase;margin-bottom:0.3rem">'
           + 'For reference — typical for this zone</div>'
           + sideRefRow + sideDivergence + '<div style="height:0.5rem"></div>')
        : '';

      // ── Other-grids comparison rows (per-side) ──
      // "× home" suffix is shortened to "×" + the section heading below
      // ("Same X kWh, on other grids (Ember 2025 annual means)") provides
      // the year context, so the trailing "· 2025 mean" per row is dropped.
      // Full text is preserved in tooltips for accessibility.
      var sideComparisonRows = zones.filter(function(z){ return z !== home; }).map(function(z){
        var s2 = statics[z] || {};
        var intensity = s2.g_per_kwh;
        var year      = s2.year;
        var label_    = s2.label || z;
        if (intensity == null) return '';
        var grams = (sideDisplayWh / 1000) * intensity;
        var ratio = (sideHomeGrams && sideHomeGrams > 0) ? (grams / sideHomeGrams) : null;
        var ratioStr = ratio != null
          ? (ratio >= 1.5 ? ratio.toFixed(1) + '×' : ratio.toFixed(2) + '×')
          : '';
        var ratioTitle = ratio != null
          ? (ratio.toFixed(2) + '× the home-zone CO₂e for the same energy')
          : '';
        return '<div style="display:flex;align-items:baseline;justify-content:space-between;'
             + 'gap:0.4rem;padding:0.3rem 0.4rem;font-family:monospace">'
             + '<span style="color:var(--text-2);flex:1;min-width:0;overflow:hidden;'
             + 'text-overflow:ellipsis;white-space:nowrap" title="' + label_ + '">' + label_ + '</span>'
             + '<span style="color:var(--text);white-space:nowrap;font-weight:bold;'
             + 'min-width:70px;text-align:right" title="' + massTitle(grams) + '">'
             + fmtMass(grams) + '</span>'
             + '<span style="color:var(--text-4);font-size:0.7rem;white-space:nowrap;'
             + 'min-width:42px;text-align:right" title="' + ratioTitle + '">' + ratioStr + '</span>'
             + '<span style="color:var(--text-5);font-size:0.7rem;white-space:nowrap;'
             + 'min-width:60px;text-align:right" '
             + 'title="' + intensity + ' g/kWh · ' + (year ? year + ' annual mean' : 'annual mean') + '">'
             + intensity + ' g/kWh'
             + '</span>'
             + '</div>';
      }).join('');
      var sideComparisonBlock =
          '<div style="color:var(--text-5);font-size:0.65rem;letter-spacing:0.04em;'
        + 'text-transform:uppercase;margin-bottom:0.3rem">'
        + 'Same ' + fmtEnergy(sideDisplayWh) + ', on other grids (Ember 2025 annual means)</div>'
        + sideComparisonRows;

      // ── Historical rows (per-side, FR-only) ──
      // "· monthly mean" suffix dropped — the section heading already says
      // "monthly means". Per-row label is the date itself which carries the
      // temporal context.
      var sideHistoricalRows = '';
      if (history.length > 0) {
        var sideHistRows = history.map(function(h){
          var grams = (sideDisplayWh / 1000) * h.g_per_kwh;
          var ratio = (sideHomeGrams && sideHomeGrams > 0) ? (grams / sideHomeGrams) : null;
          var ratioStr = ratio != null
            ? (ratio >= 1.5 ? ratio.toFixed(1) + '×' : ratio.toFixed(2) + '×')
            : '';
          var ratioTitle = ratio != null
            ? (ratio.toFixed(2) + '× today\'s home-zone CO₂e for the same energy')
            : '';
          var noteHtml = h.note
            ? '<div style="color:var(--text-5);font-size:0.68rem;'
            + 'padding:0 0.4rem 0.3rem 0.4rem;font-style:italic">'
            + h.note + '</div>'
            : '';
          return '<div style="display:flex;align-items:baseline;justify-content:space-between;'
               + 'gap:0.4rem;padding:0.3rem 0.4rem;font-family:monospace">'
               + '<span style="color:var(--text-2);flex:1;min-width:0;overflow:hidden;'
               + 'text-overflow:ellipsis;white-space:nowrap" title="' + h.label + '">' + h.label + '</span>'
               + '<span style="color:var(--text);white-space:nowrap;font-weight:bold;'
               + 'min-width:70px;text-align:right" title="' + massTitle(grams) + '">'
               + fmtMass(grams) + '</span>'
               + '<span style="color:var(--text-4);font-size:0.7rem;white-space:nowrap;'
               + 'min-width:42px;text-align:right" title="' + ratioTitle + '">' + ratioStr + '</span>'
               + '<span style="color:var(--text-5);font-size:0.7rem;white-space:nowrap;'
               + 'min-width:60px;text-align:right" '
               + 'title="' + h.g_per_kwh + ' g/kWh · monthly mean">'
               + h.g_per_kwh + ' g/kWh'
               + '</span>'
               + '</div>'
               + noteHtml;
        }).join('');
        sideHistoricalRows =
            '<div style="margin-top:0.6rem;padding-top:0.5rem;border-top:1px solid var(--border-2)">'
          + '<div style="color:var(--text-5);font-size:0.65rem;letter-spacing:0.04em;'
          + 'text-transform:uppercase;margin-bottom:0.3rem">'
          + 'Through history — same ' + fmtEnergy(sideDisplayWh) + ' on this zone’s past grids</div>'
          + sideHistRows
          + '<div style="color:var(--text-5);font-size:0.66rem;padding:0.4rem 0.4rem 0;'
          + 'font-style:italic;line-height:1.5">'
          + 'Same lifecycle methodology as the live number above (Eco2mix consolidated '
          + '× IPCC AR6 factors). Curated dates illustrate the range of grid '
          + 'evolution; not exhaustive.'
          + '</div>'
          + '</div>';
      }

      // In compactMode (compare-mode columns), only the per-side bits
      // (header + reference). The shared comparison + historical sections
      // render full-width below the columns via buildSharedRows.
      if (compactMode) return sideHeader + sideRefBlock;
      return sideHeader + sideRefBlock + sideComparisonBlock + sideHistoricalRows;
    }

    // ── Shared comparison + historical rows for compare-mode ──
    // Renders one row per zone (or date) with N mass cells side-by-side —
    // one per sub-run. Intensities are identical for both sides, so they
    // appear once at the right; mass cells are stacked left-to-right and
    // each tagged with which side it belongs to via tooltip + small caption.
    function buildSharedRows(sortedSubsRaw, zonesList, isHistorical) {
      // Compute each sub-run's projected Wh + label up front.
      var subs = sortedSubsRaw.map(function(s){
        var sDur = (s.durationS != null && !isNaN(s.durationS) && s.durationS > 0)
                   ? parseFloat(s.durationS) : null;
        var sMul = (sDur != null) ? continuousMul(continuousKey, sDur) : 1;
        var sideWh = (s.deltaWh != null && !isNaN(s.deltaWh))
                     ? parseFloat(s.deltaWh) * sMul : 0;
        return {label: s.label, displayWh: sideWh};
      });
      // Column-header row above the data — labels each mass cell so
      // visitors don't have to remember which side is which.
      var headerCells = subs.map(function(s){
        return '<span style="flex:0 0 80px;text-align:right;color:var(--text-5);'
             + 'font-size:0.62rem;letter-spacing:0.06em;text-transform:uppercase">'
             + s.label.split('·')[0].trim().split(' ')[0] // first token, e.g. "SDXL-Turbo" or "CPU"
             + '</span>';
      }).join('');
      var headerRow =
          '<div style="display:flex;align-items:baseline;gap:0.4rem;padding:0 0.4rem 0.25rem">'
        + '<span style="flex:1;min-width:0"></span>'
        + headerCells
        + '<span style="flex:0 0 42px"></span>'
        + '<span style="flex:0 0 60px"></span>'
        + '</div>';
      // Per-zone (or per-date) row.
      var rows = zonesList.map(function(item){
        var intensity = item.intensity;
        var label_    = item.label;
        var note      = item.note || '';
        if (intensity == null) return '';
        // One mass cell per sub-run.
        var massCells = subs.map(function(s){
          var grams = (s.displayWh / 1000) * intensity;
          return '<span title="' + s.label + ': ' + massTitle(grams) + '" '
               + 'style="flex:0 0 80px;text-align:right;color:var(--text);'
               + 'white-space:nowrap;font-weight:bold">'
               + fmtMass(grams) + '</span>';
        }).join('');
        // Ratio is the same for every sub-run (mass_x / mass_home reduces
        // to intensity_x / intensity_home), so render once.
        var ratioBase = isHistorical ? homeIntensity : homeIntensity;
        var ratio = (ratioBase > 0 && intensity != null) ? (intensity / ratioBase) : null;
        var ratioStr = ratio != null
          ? (ratio >= 1.5 ? ratio.toFixed(1) + '×' : ratio.toFixed(2) + '×')
          : '';
        var ratioTitle = ratio != null
          ? (isHistorical
              ? (ratio.toFixed(2) + '× the current home-zone intensity')
              : (ratio.toFixed(2) + '× the home-zone intensity'))
          : '';
        var noteHtml = note
          ? '<div style="color:var(--text-5);font-size:0.68rem;'
          + 'padding:0 0.4rem 0.3rem 0.4rem;font-style:italic">' + note + '</div>'
          : '';
        return '<div style="display:flex;align-items:baseline;gap:0.4rem;'
             + 'padding:0.3rem 0.4rem;font-family:monospace">'
             + '<span style="color:var(--text-2);flex:1;min-width:0;'
             + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap" '
             + 'title="' + label_ + '">' + label_ + '</span>'
             + massCells
             + '<span style="color:var(--text-4);font-size:0.7rem;'
             + 'flex:0 0 42px;text-align:right" title="' + ratioTitle + '">' + ratioStr + '</span>'
             + '<span style="color:var(--text-5);font-size:0.7rem;'
             + 'flex:0 0 60px;text-align:right" '
             + 'title="' + intensity + ' g/kWh">'
             + intensity + ' g/kWh'
             + '</span>'
             + '</div>'
             + noteHtml;
      }).join('');
      return headerRow + rows;
    }

    // Compare-mode detection. Two distinct layouts:
    //   * N=2 (CPU vs GPU, small vs large): two narrow side columns
    //     (header + reference) + shared two-mass rows below.
    //   * N≥3 (all_codecs sweep): a single per-mode breakdown ladder,
    //     plus a single comparison + historical section against the
    //     winner's energy. The two-mass-cell row layout doesn't scale
    //     past 2 sub-runs — six mass cells per row eats the city label
    //     and confuses the codec-side header (H.265/AV1/H.264 each
    //     appear twice for CPU and GPU, with no easy way to disambiguate).
    var compareMode = Array.isArray(subRuns) && subRuns.length >= 2;
    var detailsContent;
    if (compareMode) {
      // Sort sub-runs by saved grams so the winner lands first.
      var sortedSubs = subRuns.slice().sort(function(a, b){
        return parseFloat(a.grams) - parseFloat(b.grams);
      });

      if (sortedSubs.length === 2) {
        // ── Two-sub-run layout: side columns + shared two-mass rows ──
        var sideColumnsHtml = sortedSubs.map(function(s, i){
          var sDur = (s.durationS != null && !isNaN(s.durationS) && s.durationS > 0)
                     ? parseFloat(s.durationS) : null;
          var sMul = (sDur != null) ? continuousMul(continuousKey, sDur) : 1;
          var sideWh = (s.deltaWh != null && !isNaN(s.deltaWh))
                       ? parseFloat(s.deltaWh) * sMul : 0;
          var blockHtml = buildSideBlock(sideWh, s.label, /*isWinner=*/i === 0,
                                         /*includeHeader=*/true, /*compactMode=*/true);
          return '<div style="flex:1;min-width:240px;padding:0.5rem 0.6rem;'
               + 'border:1px solid var(--border-2);background:var(--panel)">'
               + blockHtml + '</div>';
        }).join('');
        var compZones = zones.filter(function(z){ return z !== home; }).map(function(z){
          var s2 = statics[z] || {};
          return {label: s2.label || z, intensity: s2.g_per_kwh, year: s2.year};
        });
        var sharedComparison = buildSharedRows(sortedSubs, compZones, false);
        var sharedHistoricalRows = '';
        if (history.length > 0) {
          var histItems = history.map(function(h){
            return {label: h.label, intensity: h.g_per_kwh, note: h.note};
          });
          sharedHistoricalRows = buildSharedRows(sortedSubs, histItems, true);
        }
        var subWhSummary = sortedSubs.map(function(s){
          var sDur = (s.durationS != null && !isNaN(s.durationS) && s.durationS > 0)
                     ? parseFloat(s.durationS) : null;
          var sMul = (sDur != null) ? continuousMul(continuousKey, sDur) : 1;
          var sideWh = (s.deltaWh != null && !isNaN(s.deltaWh))
                       ? parseFloat(s.deltaWh) * sMul : 0;
          return fmtEnergy(sideWh) + ' (' + s.label.split('·')[0].trim().split(' ')[0] + ')';
        }).join(' / ');
        var compHeading =
            '<div style="margin-top:0.6rem;color:var(--text-5);font-size:0.65rem;'
          + 'letter-spacing:0.04em;text-transform:uppercase;margin-bottom:0.3rem">'
          + 'Same energy (' + subWhSummary + '), on other grids (Ember 2025 annual means)'
          + '</div>';
        var histHeading = sharedHistoricalRows
          ? ('<div style="margin-top:0.6rem;padding-top:0.5rem;border-top:1px solid var(--border-2);'
             + 'color:var(--text-5);font-size:0.65rem;letter-spacing:0.04em;'
             + 'text-transform:uppercase;margin-bottom:0.3rem">'
             + 'Through history — same energy on this zone’s past grids</div>')
          : '';
        var histCaption = sharedHistoricalRows
          ? ('<div style="color:var(--text-5);font-size:0.66rem;padding:0.4rem 0.4rem 0;'
             + 'font-style:italic;line-height:1.5">'
             + 'Same lifecycle methodology as the live number above (Eco2mix consolidated '
             + '× IPCC AR6 factors). Curated dates illustrate the range of grid '
             + 'evolution; not exhaustive.</div>')
          : '';
        detailsContent =
            '<div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-bottom:0.6rem">'
          + sideColumnsHtml
          + '</div>'
          + compHeading
          + sharedComparison
          + histHeading
          + sharedHistoricalRows
          + histCaption;
      } else {
        // ── 3+ sub-runs (all_codecs): per-mode list + winner comparison ──
        // The per-mode list shows each sub-run's mass + ratio-vs-best + Wh
        // in a single readable column. The comparison + historical rows
        // below it are computed against the winner only — the linear
        // relationship (mass = Wh × intensity / 1000) means visitors can
        // mentally scale to any other sub-run from the per-mode list above.
        var subRows = sortedSubs.map(function(s){
          var sDur = (s.durationS != null && !isNaN(s.durationS) && s.durationS > 0)
                     ? parseFloat(s.durationS) : null;
          var sMul = (sDur != null) ? continuousMul(continuousKey, sDur) : 1;
          var sGrams = parseFloat(s.grams) * sMul;
          var sWh = (s.deltaWh != null && !isNaN(s.deltaWh))
                    ? parseFloat(s.deltaWh) * sMul : null;
          return {label: s.label, grams: sGrams, wh: sWh};
        });
        var bestGrams = subRows[0].grams;
        // Wh column dropped — already in the per-codec matrix above the
        // strip. Per-mode breakdown is the carbon view: label · CO₂e mass
        // · ratio-vs-best only.
        var perModeRowsHtml = subRows.map(function(s, i){
          var ratio = (bestGrams > 0) ? (s.grams / bestGrams) : null;
          var ratioStr = (ratio != null && i > 0)
            ? (ratio >= 1.5 ? ratio.toFixed(1) + '× best' : ratio.toFixed(2) + '× best')
            : (i === 0 ? 'best' : '');
          return '<div style="display:flex;align-items:baseline;justify-content:space-between;'
               + 'gap:0.4rem;padding:0.3rem 0.4rem;font-family:monospace">'
               + '<span style="color:var(--text-2);flex:1;min-width:0;'
               + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap" '
               + 'title="' + s.label + '">' + s.label + '</span>'
               + '<span style="color:var(--text);white-space:nowrap;font-weight:bold;'
               + 'min-width:90px;text-align:right" title="' + massTitle(s.grams) + '">'
               + fmtMass(s.grams) + '</span>'
               + '<span style="color:var(--text-4);font-size:0.7rem;white-space:nowrap;'
               + 'min-width:80px;text-align:right">' + ratioStr + '</span>'
               + '</div>';
        }).join('');
        var perModeBlockHtml =
            '<div style="margin-bottom:0.6rem">'
          + '<div style="color:var(--text-5);font-size:0.65rem;letter-spacing:0.04em;'
          + 'text-transform:uppercase;margin-bottom:0.3rem">'
          + 'Per-mode breakdown — ' + sortedSubs.length + ' sub-runs sorted by CO₂e</div>'
          + perModeRowsHtml
          + '</div>';
        // The single-best comparison + history block uses the headline
        // displayWh (= winner's projected Wh).
        var winnerCaption =
            '<div style="color:var(--text-5);font-size:0.65rem;font-style:italic;'
          + 'margin-bottom:0.5rem;padding:0 0.4rem">'
          + 'Comparison rows below use the winner (' + (sortedSubs[0].label || 'best') + ') · '
          + 'others scale linearly from the per-mode list above.'
          + '</div>';
        detailsContent =
            perModeBlockHtml
          + winnerCaption
          + buildSideBlock(displayWh, label || '', false, false, false);
      }
    } else {
      detailsContent = buildSideBlock(displayWh, label || '', false, false, false);
    }

    // Optional: live French production mix (Eco2mix only). Sums positive
    // sources, shows top contributors by share. Hidden if mix_mw absent.
    // Shown whenever we have a mix — even when the headline intensity has
    // fallen back to static (RTE's taux_co2 lag flips the headline past the
    // 30-min TTL while the mix is still recent); the header below labels it
    // "live" only when homeLive, otherwise by its true age (mix_age_s).
    var mixHtml = '';
    if (homeI.mix_mw && Object.keys(homeI.mix_mw).length){
      var mix = homeI.mix_mw;
      var labels = {nucleaire:'Nuclear', eolien:'Wind', solaire:'Solar',
                    hydraulique:'Hydro', bioenergies:'Bioenergy',
                    gaz:'Gas', charbon:'Coal', fioul:'Oil', pompage:'Pumped storage'};
      var entries = [];
      var totalPos = 0;
      Object.keys(mix).forEach(function(k){
        var mw = mix[k];
        if (typeof mw === 'number' && mw > 0){ entries.push([k, mw]); totalPos += mw; }
      });
      if (totalPos > 0){
        entries.sort(function(a,b){ return b[1]-a[1]; });
        var rows = entries.map(function(e){
          var pct = (e[1] / totalPos) * 100;
          var pctStr = pct >= 1 ? pct.toFixed(0) + '%' : pct.toFixed(1) + '%';
          // Label takes the slack; MW and % are fixed-width right-aligned
          // columns so the digits line up down the table (a space-between
          // middle child floated per-row and read as misaligned).
          return '<div style="display:flex;gap:1rem;'
               + 'padding:0.15rem 0.4rem;font-family:monospace;font-variant-numeric:tabular-nums">'
               + '<span style="color:var(--text-2);flex:1">' + (labels[e[0]] || e[0]) + '</span>'
               + '<span style="color:var(--text-3);min-width:80px;text-align:right">' + Math.round(e[1]) + ' MW</span>'
               + '<span style="color:var(--text);min-width:50px;text-align:right">' + pctStr + '</span>'
               + '</div>';
        }).join('');
        var mixZone = homeI.zone_label || home;
        var mixProvider = homeLive ? (homeI.provider || 'live')
                                   : (homeI.mix_provider || 'Eco2mix');
        var mixHeader = homeLive
          ? (mixZone + ' grid right now (live, via ' + mixProvider + ')')
          : (mixZone + ' grid mix (' + fmtAge(homeI.mix_age_s) + ', via ' + mixProvider + ')');
        mixHtml =
            '<div style="margin-top:0.6rem;padding-top:0.5rem;border-top:1px solid var(--border-2)">'
          + '<div style="color:var(--text-5);font-size:0.65rem;letter-spacing:0.04em;'
          + 'text-transform:uppercase;margin-bottom:0.3rem">'
          + mixHeader + '</div>'
          + rows
          + '</div>';
      }
    }

    // Live source explainer — FR derives lifecycle intensity from the
    // current Eco2mix production mix × IPCC AR6 factors (CR-016). Any
    // other home zone uses ElectricityMaps' published intensity directly.
    // Full live-source dispatch for non-FR zones is a deferred CR; this
    // just keeps the wording correct if HOME_ZONE flips.
    var homeLabel = (homeI.zone_label || home);
    var liveExplain = (home === 'FR')
      ? 'Live (home zone, ' + homeLabel + '): production mix from '
        + '<a href="' + WL_CFG.urls.eco2mix + '" target="_blank" rel="noopener" '
        + 'style="color:var(--text-3)">Eco2mix</a> (RTE/Etalab — official French TSO, '
        + 'refreshed every 15 min) × IPCC AR6 lifecycle emission factors per source. '
        + 'Falls back to '
        + '<a href="' + WL_CFG.urls.electricitymaps + '" target="_blank" rel="noopener" '
        + 'style="color:var(--text-3)">ElectricityMaps</a>, then to the static '
        + 'annual mean if both are unavailable.'
      : 'Live (home zone, ' + homeLabel + '): '
        + '<a href="' + WL_CFG.urls.electricitymaps + '" target="_blank" rel="noopener" '
        + 'style="color:var(--text-3)">ElectricityMaps</a> real-time grid intensity. '
        + 'Falls back to the static annual mean if unavailable.';

    // CR-036 — formula block names the 🟢 direct / 🟡 indicative split
    // explicitly, anchored to the Language Lab AI position paper's data-
    // quality framework. Single source of truth for the framing; the
    // top-of-strip chip is the visible signal, this block is the receipt.
    var formulaHtml =
        '<div style="margin-top:0.6rem;padding-top:0.5rem;border-top:1px solid var(--border-2);'
      + 'color:var(--text-4);font-size:0.7rem;line-height:1.55">'
      + '<div style="margin-bottom:0.4rem">'
      + '<strong style="color:var(--text-3)">Data quality</strong>'
      + ' &middot; <span style="color:var(--accent)">🟢 Direct</span> = the energy figure '
      + 'above (P110 polling at the wall, validated method, GoS primary measurement). '
      + '<span style="color:var(--warn)">🟡 Indicative</span> = this carbon block — '
      + 'Wh × third-party grid intensity. Provided for context, not for citation as '
      + 'GoS data. (Framework: <a href="' + WL_CFG.urls.position_paper + '" target="_blank" rel="noopener" style="color:var(--text-3)">'
      + 'Language Lab AI position paper, Jan 2026</a>.)'
      + '</div>'
      + '<div style="margin-bottom:0.25rem"><strong style="color:var(--text-3)">How this is calculated</strong></div>'
      + 'gCO₂e&nbsp;=&nbsp;Wh × (g/kWh) ÷ 1000<br>'
      + '<span style="color:var(--text-3)">Scope: use phase only.</span> '
      + 'Energy drawn at the wall × grid intensity. Embodied carbon of the '
      + 'hardware — manufacturing, transport, end-of-life — is not included.<br>'
      + liveExplain + '<br>'
      + 'Indicative (reference &amp; comparison zones): '
      + '<a href="' + WL_CFG.urls.ember + '" target="_blank" rel="noopener" '
      + 'style="color:var(--text-3)">Ember</a> 2025 annual mean grid carbon intensity, '
      + 'lifecycle basis. Static so values do not drift between page loads.<br>'
      + '<span style="color:var(--text-5)">Live and reference are on the same '
      + 'lifecycle boundary, so the two numbers are directly comparable. The gap '
      + 'between them reflects real diurnal grid variance, not a methodology '
      + 'mismatch.</span><br>'
      + 'Raw module status: <a href="/carbon" style="color:var(--text-3)">/carbon</a>'
      + '</div>';

    el.innerHTML =
        estimateCaption
      + headlineHtml
      + '<details style="margin-top:0.6rem">'
      + '<summary style="cursor:pointer;color:var(--text-3);font-size:0.78rem;'
      + 'list-style:none;padding:0.25rem 0;border-top:1px solid var(--border-2)">'
      + '<span style="color:var(--text-4)">▸</span> '
      + 'If this had run elsewhere · or in past years · how this is calculated'
      + '</summary>'
      + '<div style="margin-top:0.5rem">'
      + detailsContent
      + mixHtml
      + formulaHtml
      + '</div>'
      + '</details>';

    // Wire the continuous-projection toggle. Change handler writes the
    // new state to the URL hash and re-renders. The recursive call reads
    // the hash on entry, so all strips on the page that share the hash
    // (in practice: just one per result page today) update consistently.
    if (canProject) {
      var sel = el.querySelector('[data-continuous-toggle]');
      if (sel) {
        sel.addEventListener('change', function(){
          writeContinuousHash(sel.value);
          _renderStrip(elId, wh, label, durationS, savedIntensityG, subRuns);
        });
      }
    }
  }
})();
