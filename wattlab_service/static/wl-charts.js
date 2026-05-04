/* WattLab shared chart helpers.
 *
 * Wraps Chart.js 4.x with the OWL look-and-feel (dark theme, monospace,
 * accent palette) so every chart on the site renders the same way and the
 * underlying tech can be swapped in one place.
 *
 * Pages must load Chart.js before this file:
 *   <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
 *   <script src="/static/wl-charts.js"></script>
 *
 * Usage:
 *   const chart = WlCharts.line({
 *     canvas: document.getElementById('myChart'),
 *     datasets: [
 *       { label: 'cpu', points: [{x:0,y:80},{x:5,y:55}], color: 'cpu' },
 *       { label: 'gpu', points: [{x:0,y:78},{x:5,y:54}], color: 'gpu' },
 *     ],
 *     xLabel: 'distance (s)',
 *     yLabel: 'watts',
 *     yUnit:  'W',
 *   });
 *
 * The `color` field is a semantic name (cpu / gpu / accent / warn / err);
 * the helper picks the actual hex from the OWL palette so charts stay
 * consistent with the rest of the UI without each call site re-specifying.
 */
(function (global) {
  'use strict';

  // --- Palette ------------------------------------------------------------
  // Mirror the OWL CSS vars (--accent etc.). Repeating the hexes here keeps
  // chart code free of getComputedStyle gymnastics; if these drift from CSS
  // it's a one-line fix.
  const PALETTE = {
    accent: '#00ff99',   // primary, matches --accent
    cpu:    '#ff7755',   // warm — used for CPU-side series across the site
    gpu:    '#00ff99',   // accent green — GPU
    warn:   '#ffaa00',
    err:    '#ff4466',
    text:   '#cccccc',   // dataset legend
    axis:   '#888888',   // axis labels + ticks
    grid:   '#1a1a1a',   // grid lines
  };

  function pickColor(name) {
    return PALETTE[name] || name || PALETTE.accent;
  }

  // --- Default styling ----------------------------------------------------
  const FONT = { family: 'monospace', size: 11 };

  function baseScales(xLabel, yLabel) {
    return {
      x: {
        type: 'linear',
        title: { display: !!xLabel, text: xLabel || '', color: PALETTE.axis, font: FONT },
        ticks: { color: PALETTE.axis, font: FONT },
        grid:  { color: PALETTE.grid },
      },
      y: {
        title: { display: !!yLabel, text: yLabel || '', color: PALETTE.axis, font: FONT },
        ticks: { color: PALETTE.axis, font: FONT },
        grid:  { color: PALETTE.grid },
      },
    };
  }

  function basePlugins(yUnit) {
    return {
      legend: { labels: { color: PALETTE.text, font: FONT } },
      tooltip: {
        backgroundColor: '#000',
        titleColor: PALETTE.accent,
        bodyColor: PALETTE.text,
        titleFont: FONT,
        bodyFont: FONT,
        borderColor: PALETTE.grid,
        borderWidth: 1,
        callbacks: {
          label: (c) => {
            const v = c.parsed.y;
            const unit = yUnit ? ' ' + yUnit : '';
            return c.dataset.label + ': ' + (typeof v === 'number' ? v.toFixed(2) : v) + unit;
          },
        },
      },
    };
  }

  // --- Public: line chart -------------------------------------------------
  function line(opts) {
    if (typeof Chart === 'undefined') {
      throw new Error('WlCharts.line: Chart.js not loaded — include the chart.umd.min.js <script> first.');
    }
    const ctx = (opts.canvas instanceof HTMLCanvasElement)
      ? opts.canvas.getContext('2d')
      : opts.canvas; // already a 2d context
    const datasets = (opts.datasets || []).map((ds) => {
      const color = pickColor(ds.color);
      return {
        label: ds.label,
        data: (ds.points || []).map((p) => ({ x: p.x, y: p.y })),
        borderColor: color,
        backgroundColor: color + '33',
        tension: ds.tension !== undefined ? ds.tension : 0.2,
        pointRadius: ds.pointRadius !== undefined ? ds.pointRadius : 3,
      };
    });
    return new Chart(ctx, {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'nearest', intersect: false },
        scales: baseScales(opts.xLabel, opts.yLabel),
        plugins: basePlugins(opts.yUnit),
      },
    });
  }

  // --- Export -------------------------------------------------------------
  global.WlCharts = {
    line,
    palette: PALETTE,
    // Reserved for future use — same signature pattern as line():
    // bar(opts), scatter(opts), etc. Add as needed; keep the public surface
    // narrow so swapping Chart.js for something else (uPlot, ECharts) is a
    // one-file change.
  };
})(window);
