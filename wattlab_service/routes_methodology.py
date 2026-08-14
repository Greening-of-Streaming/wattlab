"""
Methodology route — /methodology, the public measurement-protocol page.

Bespoke-design shell (own topbar + design tokens, no standard footer —
S41 decision, like /findings); live settings are injected per request so
the prose can never contradict the running config (CR-002). Includes the
thermal-recovery chart payload helper.

Phase 3 per-feature route module — never import main.
"""
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

import settings as cfg
import ui
from capabilities import requires, PUBLIC_PAGE
from power import meter_display_name, meter_cadence_label, meter_topology_row
from ui import (CHARTJS_URL, ECO2MIX_URL, EMBER_URL, GITHUB_ISSUES_URL,
                GITHUB_REPO_URL, GOS_LOGO_URL, GOS_URL, POSITION_PAPER_URL,
                _AUTH_CHIP_STYLES, _auth_chip_html)

router = APIRouter()


_METHODOLOGY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="icon" type="image/svg+xml" href="/static/owl.svg">
<title>OWL Measurement Methodology</title>
<!--OG_META-->
<style>
  :root {
    --bg: #0a0a0a;
    --surface: #141414;
    --surface-hover: #1a1a1a;
    --border: #2a2a2a;
    --text: #e0e0e0;
    --text-dim: #888;
    --accent: #00ff99;
    --accent-dim: rgba(0,255,153,0.15);
    --warning: #ffaa00;
    --red: #ff4444;
    --mono: 'SF Mono', 'Cascadia Code', 'Fira Code', Consolas, monospace;
    --sans: 'Inter', system-ui, -apple-system, sans-serif;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-size: 15px;
    line-height: 1.7;
    padding: 0;
  }

  /* ── Header bar (matches other OWL pages) ── */
  .topbar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 24px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
  }
  .topbar img { height: 32px; border-radius: 50%; }
  .topbar .title {
    font-family: var(--mono);
    font-size: 14px;
    color: var(--accent);
    letter-spacing: 0.5px;
  }
  .topbar .back {
    margin-left: auto;
    color: var(--text-dim);
    text-decoration: none;
    font-size: 13px;
    font-family: var(--mono);
  }
  .topbar .back:hover { color: var(--accent); }

  /* ── Main content ── */
  .content {
    max-width: 780px;
    margin: 0 auto;
    padding: 40px 24px 80px;
  }

  h1 {
    font-family: var(--mono);
    font-size: 22px;
    color: var(--accent);
    margin-bottom: 6px;
    letter-spacing: 0.5px;
  }
  .subtitle {
    color: var(--text-dim);
    font-size: 13px;
    font-family: var(--mono);
    margin-bottom: 36px;
  }

  h2 {
    font-family: var(--mono);
    font-size: 15px;
    color: var(--accent);
    margin-top: 40px;
    margin-bottom: 16px;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--border);
    letter-spacing: 0.3px;
  }

  h3 {
    font-family: var(--sans);
    font-size: 14px;
    font-weight: 600;
    color: var(--text);
    margin-top: 24px;
    margin-bottom: 8px;
  }

  p { margin-bottom: 14px; }

  /* ── Scope banner ── */
  .scope-banner {
    background: var(--accent-dim);
    border: 1px solid rgba(0,255,153,0.3);
    border-radius: 6px;
    padding: 16px 20px;
    margin-bottom: 32px;
    font-family: var(--mono);
    font-size: 13px;
    line-height: 1.6;
    color: var(--accent);
  }
  .scope-banner strong { color: #fff; }

  /* ── Protocol steps ── */
  .protocol-steps {
    counter-reset: step;
    list-style: none;
    padding: 0;
    margin: 16px 0 20px;
  }
  .protocol-steps li {
    counter-increment: step;
    position: relative;
    padding: 12px 16px 12px 52px;
    margin-bottom: 8px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 5px;
    font-size: 14px;
    line-height: 1.5;
  }
  .protocol-steps li::before {
    content: counter(step);
    position: absolute;
    left: 16px;
    top: 12px;
    width: 24px;
    height: 24px;
    background: var(--accent-dim);
    border: 1px solid rgba(0,255,153,0.3);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--mono);
    font-size: 12px;
    color: var(--accent);
    font-weight: 600;
  }
  .protocol-steps li code {
    font-family: var(--mono);
    font-size: 12px;
    background: rgba(255,255,255,0.06);
    padding: 1px 5px;
    border-radius: 3px;
    color: var(--accent);
  }

  /* ── Confidence table ── */
  .confidence-table {
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0 20px;
    font-size: 14px;
  }
  .confidence-table th {
    text-align: left;
    font-family: var(--mono);
    font-size: 12px;
    color: var(--text-dim);
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .confidence-table td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }
  .confidence-table tr:last-child td { border-bottom: none; }
  .badge { font-size: 16px; }

  /* ── Hardware spec table ── */
  .hw-table {
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0 20px;
    font-size: 14px;
  }
  .hw-table td {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }
  .hw-table td:first-child {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--text-dim);
    width: 160px;
    white-space: nowrap;
  }

  /* ── Info callout ── */
  .callout {
    background: var(--surface);
    border-left: 3px solid var(--warning);
    padding: 14px 18px;
    margin: 16px 0 20px;
    border-radius: 0 5px 5px 0;
    font-size: 14px;
  }
  .callout.green { border-left-color: var(--accent); }

  /* ── Formula block ── */
  .formula {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 16px 20px;
    margin: 14px 0 20px;
    font-family: var(--mono);
    font-size: 13px;
    line-height: 1.8;
    color: var(--text);
    overflow-x: auto;
  }
  .formula .label {
    color: var(--text-dim);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    display: block;
    margin-bottom: 4px;
  }
  .formula .var { color: var(--accent); }

  /* ── Open questions ── */
  .open-q {
    padding: 10px 16px;
    margin-bottom: 6px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 5px;
    font-size: 14px;
    display: flex;
    gap: 10px;
    align-items: baseline;
  }
  .open-q .marker {
    color: var(--warning);
    font-family: var(--mono);
    font-size: 12px;
    flex-shrink: 0;
  }

  /* ── Section links (bottom nav) ── */
  .section-nav {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 12px 0 28px;
  }
  .section-nav a {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--accent);
    text-decoration: none;
    padding: 5px 10px;
    background: var(--accent-dim);
    border: 1px solid rgba(0,255,153,0.2);
    border-radius: 4px;
  }
  .section-nav a:hover {
    background: rgba(0,255,153,0.25);
  }

  /* ── Timestamp footer ── */
  .footer-note {
    margin-top: 48px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
    color: var(--text-dim);
    font-family: var(--mono);
    font-size: 11px;
    line-height: 1.6;
  }

  /* ── Home link (top + bottom) — matches `_BACK` used on other pages ── */
  .home-link {
    display: inline-block;
    color: var(--text-3);
    text-decoration: none;
    font-family: var(--mono);
    font-size: 13px;
  }
  .home-link:hover { color: var(--accent); }
  .home-link.top    { margin-bottom: 24px; }
  .home-link.bottom { margin-top: 32px; }

  /* ── Responsive ── */
  @media (max-width: 600px) {
    .content { padding: 24px 16px 60px; }
    h1 { font-size: 18px; }
    .protocol-steps li { padding-left: 44px; }
    .hw-table td:first-child { width: 120px; }
  }
{AUTH_CHIP_STYLES}
</style>
<script src="{CHARTJS_URL}"></script>
<script src="/static/wl-charts.js"></script>
</head>
<body>
{AUTH_CHIP}

<!-- Top bar -->
<div class="topbar">
  <a href="/" title="OWL home" style="display:inline-flex;align-items:center;gap:0.5rem;text-decoration:none">
    <img src="/static/owl.svg" alt="OWL" style="height:32px;width:32px;border-radius:0;flex-shrink:0">
  </a>
  <a href="{GOS_URL}" target="_blank" title="Greening of Streaming">
    <img src="{GOS_LOGO_URL}" alt="GoS">
  </a>
  <span class="title">OWL · Methodology</span>
  <a href="/" class="back">&larr; Home</a>
</div>

<div class="content">

  <a href="/" class="home-link top">&larr; Home</a>

  <h1>OWL Measurement Methodology</h1>
  <p class="subtitle">How OWL measures the energy cost of compute tasks &mdash; and what it doesn&rsquo;t measure.</p>

  <div style="margin: -18px 0 32px; font-family: var(--mono); font-size: 12px; display: flex; gap: 18px; flex-wrap: wrap;">
    <a href="{GITHUB_REPO_URL}" target="_blank" rel="noopener"
       style="color: var(--accent); text-decoration: none; border-bottom: 1px solid rgba(0,255,153,0.3);">
      Source on GitHub &rarr;
    </a>
    <a href="{GITHUB_ISSUES_URL}" target="_blank" rel="noopener"
       style="color: var(--warning); text-decoration: none; border-bottom: 1px solid rgba(255,170,0,0.3);">
      Report an issue / feature request &rarr;
    </a>
  </div>

  <div class="section-nav">
    <a href="#scope">Scope</a>
    <a href="#principle">Principle</a>
    <a href="#protocol">Protocol</a>
    <a href="#energy">Energy maths</a>
    <a href="#confidence">Confidence</a>
    <a href="#diagnostics">Diagnostics</a>
    <a href="#hardware">Hardware</a>
    <a href="#tests">Test types</a>
    <a href="#energy-budget">Energy budget</a>
    <a href="#limits">Limitations</a>
    <a href="#carbon">CO&#x2082;e</a>
    <a href="#open">Open questions</a>
  </div>

  <h2 id="scope">Scope</h2>

  <div class="scope-banner">
    <strong>Device layer only.</strong><br>
    All measurements cover the GoS1 server: CPU, GPU, RAM, storage, fans, motherboard.<br>
    Network, CDN, client devices (CPE), and production/storage infrastructure are explicitly excluded.<br>
    LLM measurements do not include amortised training cost.
  </div>

  <p>OWL measures what happens inside one machine when it performs a real task. This is intentionally narrow. The energy cost of streaming is distributed across data centres, networks, and consumer devices &mdash; each with different measurement challenges and attribution problems. We start with the layer we can measure directly, at the wall, with no modelling assumptions.</p>

  <p>This scoping decision means OWL results are <em>not</em> lifecycle assessments and should not be cited as total-cost-of-delivery figures. They answer a specific question: how much additional energy does this server draw to perform this task, above its idle baseline?</p>

  <p>One deliberate extension exists: since 2026-07 the <a href="/findings" style="color:var(--accent);text-decoration:none">findings catalog</a> also carries <strong>client-device decode panels</strong> measured on a separate rig under the same protocol; each states its own device scope (see Test Types).</p>

  <h2 id="principle">Measurement Principle</h2>

  <p>OWL uses <strong>wall-power delta measurement</strong>: the difference between what the server draws at idle and what it draws under load, captured by an external smart plug.</p>

  <div class="callout green">
    The plug measures the entire system &mdash; not a model, not a software estimate, not a per-component reading. If the CPU fan spins faster, the PSU runs less efficiently, or the GPU draws from the 12V rail, it&rsquo;s all in the number.
  </div>

  <p>OWL is the <strong>bench</strong> half of GoS&rsquo;s dual-track methodology: its sister programme <strong>REM (Remote Energy Measurement)</strong> observes real devices in the field at fleet scale &mdash; <em>where</em> effects exist &mdash; while OWL quantifies <em>why, and by how much</em>, under controlled conditions. Both tracks share one instrument principle, documented by GoS&rsquo;s <strong>LEM (Local Energy Measurement)</strong> programme: real hardware running real workloads, measured externally at the wall by a smart plug read over the <em>local</em> network &mdash; milliwatt-resolution readings at second-scale cadence, no software estimation.</p>

  <h2 id="protocol">Measurement Protocol</h2>

  <p>Every test in OWL &mdash; video, LLM, image generation, RAG &mdash; follows the same core protocol:</p>

  <ol class="protocol-steps">
    <li>
      <strong>Focus mode.</strong> Suppress background system tasks (apt, cron, man-db, fwupd, etc.) that would introduce energy noise. Managed via <code>systemctl stop</code> with dedicated sudoers rules.
    </li>
    <li>
      <strong>Model unload</strong> (LLM/RAG only). Send <code>keep_alive=0</code> to Ollama and wait 3 seconds for GPU memory release. Ensures a cold start when cold-inference mode is selected.
    </li>
    <li>
      <strong>Baseline capture.</strong> Poll the {METER_NAME} at {METER_CADENCE} for a configurable period (currently <code>{BASELINE_POLLS}</code> polls &mdash; configurable in Settings). The mean of these readings becomes W<sub>base</sub> &mdash; the server&rsquo;s idle power draw.
    </li>
    <li>
      <strong>Lock.</strong> Acquire <code>/tmp/gos-measure.lock</code> to prevent concurrent measurements from overlapping. A FIFO queue manages waiting jobs.
    </li>
    <li>
      <strong>Execute task.</strong> Run the actual workload (ffmpeg, Ollama inference, SD-Turbo diffusion) while continuing to poll the {METER_NAME} at {METER_CADENCE}. Thermal sensors (CPU Tctl, GPU junction, GPU PPT) are read in parallel.
    </li>
    <li>
      <strong>Compute energy.</strong> Calculate delta power, total energy, and per-unit metrics (see formulas below).
    </li>
    <li>
      <strong>Persist.</strong> Write the full result to a JSON file &mdash; parameters, energy report, raw poll data, thermal readings, confidence flag. Every result is reproducible and exportable.
    </li>
    <li>
      <strong>Focus exit.</strong> Restart suppressed system timers in parallel (via ThreadPoolExecutor) to minimise downtime.
    </li>
  </ol>

  <p>Between sequential runs (e.g., CPU vs GPU comparison), a configurable cooldown (currently <code>{VIDEO_COOLDOWN_S}</code> seconds &mdash; configurable in Settings) allows the system to return to thermal equilibrium.</p>

  <h2 id="energy">Energy Calculation</h2>

  <div class="formula">
    <span class="label">Delta power (average above idle)</span>
    <span class="var">&Delta;W</span> = mean(<span class="var">W<sub>polls</sub></span>) &minus; <span class="var">W<sub>base</sub></span>
  </div>

  <div class="formula">
    <span class="label">Total energy consumed by task</span>
    <span class="var">&Delta;E</span> = <span class="var">&Delta;W</span> &times; (<span class="var">&Delta;t</span> / 3600) &nbsp; [Wh]
    <br><br>
    where <span class="var">&Delta;t</span> = task duration in seconds
  </div>

  <div class="formula">
    <span class="label">Per-token energy (LLM / RAG)</span>
    <span class="var">E<sub>token</sub></span> = <span class="var">&Delta;E</span> / <span class="var">N<sub>tokens</sub></span> &nbsp; [mWh/token]
  </div>

  <div class="formula">
    <span class="label">Per-image energy (image generation)</span>
    <span class="var">E<sub>image</sub></span> = <span class="var">&Delta;E</span> / <span class="var">N<sub>images</sub></span> &nbsp; [Wh/image]
  </div>

  <p>All formulas use wall-power from the P110 (system-level), not component-level readings. The GPU&rsquo;s self-reported power (its vendor sensor &mdash; <code>amdgpu</code> PPT or <code>nvidia-smi</code> power draw) is captured for reference but is not used in the primary energy calculation &mdash; it covers only the GPU die/board, not the full system delta (CPU, RAM, drives, fans, PSU losses).</p>

  <h3 style="margin-top:1.25rem">Marginal vs attributional energy &mdash; two lenses, one measurement</h3>
  <p>The headline &Delta;E above is <strong>marginal</strong> accounting: it answers &ldquo;how much <em>extra</em> energy did this task cause, on a machine that was running anyway?&rdquo; The idle floor is subtracted, so the task is never charged for occupying the machine. That is the honest lens for a shared, always-on box &mdash; and it is deliberately conservative for comparisons, because it cannot be inflated by a high idle floor.</p>
  <p>There is a second, equally honest lens. If the machine exists <em>to run these tasks</em> &mdash; a dedicated encode fleet is the canonical case &mdash; then the full bill per task includes the idle power the machine burns while the task holds it open:</p>

  <div class="formula">
    <span class="label">Attributional energy (machine-occupancy accounting)</span>
    <span class="var">E<sub>attr</sub></span> = (<span class="var">W<sub>base</sub></span> + <span class="var">&Delta;W</span>) &times; (<span class="var">&Delta;t</span> / 3600) &nbsp; [Wh]
  </div>

  <p>Both figures come from the <em>same</em> samples &mdash; the attributional one is derived, not separately measured. The choice between them is a <strong>scoping decision, stated openly</strong>, not a correction: marginal for &ldquo;what did this task add?&rdquo;, attributional for &ldquo;what does a task cost on hardware dedicated to it?&rdquo;. The distinction only matters when the compared tasks take different amounts of time. Real-time playback is immune (every codec occupies the device for exactly the video&rsquo;s duration); faster-than-real-time work &mdash; VoD encoding above all &mdash; is where it bites: a slow software encode holds a whole machine open for minutes that a hardware encoder releases in seconds, so attribution adds far more idle energy to the slow row and widens the absolute gap between them (the &ldquo;race to idle&rdquo; effect). On this bench it roughly doubles CPU-encode figures while adding only a fraction to the seconds-long hardware encodes. Encode-parity rows now carry the attributional figure alongside the marginal one (<code>wh_per_min_video_attributional</code>), plus their per-row idle baseline. Earlier stored results can be recomputed under this lens: standard result envelopes persist their idle baseline and task duration; older parity artifacts, which stored only the delta, are recomputed against the documented idle floor of their hardware era and labelled as such.</p>

  <h3 style="margin-top:1.25rem">Isolating the encoder &mdash; transcode vs encode</h3>
  <p>Every video figure above is the energy of a <strong>full transcode</strong> &mdash; ffmpeg decodes the source, converts colour space, scales, <em>then</em> encodes &mdash; not the encoder in isolation. For most comparisons that is the honest number (you cannot encode without first decoding), and when the input is held constant the decode cost is a near-constant offset that cancels out of the comparison. Where the encoder&rsquo;s <em>own</em> share is wanted &mdash; currently in the REM file-prep flow (<code>/prepare-rem</code>) &mdash; OWL runs a second, <strong>decode-only</strong> pass under the identical protocol (the same source decoded and discarded to a null sink, no encode) and subtracts it:</p>

  <div class="formula">
    <span class="label">Encoder-only energy (approximate)</span>
    <span class="var">&Delta;E<sub>encode</sub></span> &asymp; <span class="var">&Delta;E<sub>transcode</sub></span> &minus; <span class="var">&Delta;E<sub>decode</sub></span>
  </div>

  <p>All three figures &mdash; transcode, decode, and the derived encode &mdash; are reported side by side, so the attribution is shown rather than asserted.</p>

  <div class="open-q"><span class="marker">&#9658;</span><span><strong>Why &ldquo;approximate&rdquo; &mdash; measured.</strong> We checked it directly: on 120-second clips of three sources (Big Buck Bunny, Meridian, and a hard downhill-MTB clip) we measured decode-only, encode-from-raw, and the full transcode under one protocol (CPU, 1080p, standard bitrates), with enough 1&nbsp;Hz samples per op for a tight reading. <code>transcode &minus; decode</code> agrees with the directly-isolated encode to within about <strong>&plusmn;5%</strong> across every content/codec cell, with a slight tendency to read a few percent <em>low</em> &mdash; the standalone encode-from-raw carries a little extra disk I/O, and the real transcode runs decode, scale and encode <em>concurrently</em>, so it costs marginally less than the parts measured apart (<code>transcode &lt; decode + encode</code>). So the split is a sound estimate of pure-encoder energy, good to a few percent. (An earlier 30-second run pointed the other way; that was an artefact of the decode op being too brief for 1&nbsp;Hz sampling &mdash; a reminder that the limit here is samples-per-task, not the method.) On the GPU path the probe is hardware-decode only, so scaling is counted under encode. The split signals its own uncertainty &mdash; consistent with the confidence framework below.</span></div>

  <h2 id="confidence">Confidence Framework</h2>

  <p>Every OWL result carries a traffic-light confidence flag. Under the CR-028 Phase 2 model (designed with Tania Pouli), the flag answers one defensible question per run: <strong>can this run be distinguished from idle?</strong> It is a per-run confidence interval, not a fixed-watt rule of thumb.</p>

  <p>We keep the raw per-poll power samples from both the baseline window and the task window, form a standard error on the measured power increase &Delta;W, then convert &Delta;W into a one-sided confidence that the task really draws above idle:</p>

  <div class="formula">
    <span class="label">Standard error &mdash; conservative (worst case of the calibrated and per-run estimates, plus drift)</span>
    SE<sub>final</sub> = max(SE<sub>calibrated</sub>, SE<sub>per-run</sub>) + SE<sub>drift</sub><br>
    SE<sub>calibrated</sub> = (<span class="var">variance_idle_pct</span>/100 &middot; W<sub>base</sub>) &times; &radic;(1/n<sub>base</sub> + 1/n<sub>task</sub>)<br>
    SE<sub>per-run</sub> = &radic;(&sigma;&sup2;<sub>base</sub>/n<sub>base</sub> + &sigma;&sup2;<sub>task</sub>/n<sub>task</sub>)<br>
    SE<sub>drift</sub> = (<span class="var">variance_idle_drift_pct</span>/100) &middot; W<sub>base</sub>
    <span class="label" style="margin-top:0.6rem">Confidence the task draws above idle</span>
    <span class="var">confidence<sub>positive</sub></span> = &Phi;(&Delta;W / SE<sub>final</sub>)
  </div>

  <table class="confidence-table">
    <tr>
      <th>Flag</th>
      <th>Meaning</th>
      <th>Criteria (defaults)</th>
    </tr>
    <tr>
      <td><span class="badge">&#x1F7E2;</span></td>
      <td><strong>Repeatable</strong> &mdash; the task is almost certainly above idle, with enough samples to be reliable.</td>
      <td>confidence<sub>positive</sub> &ge; 95% and &ge; <code>{CONF_GREEN_POLLS}</code> task polls</td>
    </tr>
    <tr>
      <td><span class="badge">&#x1F7E1;</span></td>
      <td><strong>Early insight</strong> &mdash; directional evidence; a longer run would strengthen it.</td>
      <td>confidence<sub>positive</sub> &ge; 80% and &ge; <code>{CONF_YELLOW_POLLS}</code> task polls</td>
    </tr>
    <tr>
      <td><span class="badge">&#x1F534;</span></td>
      <td><strong>Need more data</strong> &mdash; cannot yet be distinguished from idle.</td>
      <td>below the yellow threshold</td>
    </tr>
  </table>

  <div class="callout green">
    <strong>Why a confidence interval, not a fixed-watt rule?</strong> The flag uses this run&rsquo;s own observed noise (<code>SE<sub>per-run</sub></code>), takes the worst case against a calibrated idle floor (<code>SE<sub>calibrated</sub></code>), and adds a drift term for the time gap between the baseline and task windows &mdash; so it reflects real signal quality on the day, not an assumed noise floor. The minimum task-sample counts remain because 1&nbsp;s power samples are autocorrelated: a very short task should not turn green on one or two lucky readings.
  </div>

  <div class="callout">
    <strong>Inputs (CR-028 Phase 2, &ldquo;option C&rdquo;).</strong> The single-run flag uses only <code>variance_idle_pct</code> as the calibrated idle noise floor. The per-codec calibration CVs (<code>variance_cpu_pct</code> / <code>variance_gpu_pct</code>) are run-to-run repeatability measures, reserved for a future aggregate-confidence layer rather than mixed into the single-run formula. Planned refinements to the critical value and sample counts are listed under Open Questions.
  </div>

  <div class="callout">
    <strong>Legacy results.</strong> Results saved before raw per-poll samples were persisted fall back to the earlier variance-threshold flag (&Delta;W against a multiple of <code>variance_pct</code> &times; W<sub>base</sub>), so historical runs keep their badge.
  </div>

  <div class="callout">
    <strong>Meter and total system noise:</strong> OWL polls the {METER_NAME} over its <strong>local API, which preserves the instrument&rsquo;s full ~1&nbsp;mW reading</strong> (the coarser 1&nbsp;W figure sometimes quoted for these plugs applies to cloud-API paths, not this deployment). In practice the noise floor is set not by the meter but by OS background processes (apt, cron, systemd timers) and thermal drift between runs. Focus mode suppresses the worst offenders; the variance calibration measures the residual combined noise empirically and stores it as the reference for all confidence calculations.
  </div>

  <p>The confidence framework follows GoS&rsquo;s broader principle: <em>if it can&rsquo;t be measured, it shouldn&rsquo;t be asserted.</em> A &#x1F534; result is not a failure &mdash; it&rsquo;s an honest signal that the measurement instrument isn&rsquo;t sensitive enough for that task. Publishing it transparently is more useful than hiding it.</p>

  <h3 style="margin-top:1.25rem">Calibration integrity</h3>
  <p>The variance calibration runner (<code>/variance/run</code>) executes <code>{VARIANCE_RUNS}</code> pairs of H.264&nbsp;CPU + H.265&nbsp;GPU encodes with <code>{VARIANCE_COOLDOWN_S}</code>&thinsp;seconds between them, and computes three coefficients of variation: <strong>idle</strong> (raw P110 baseline readings, captures system noise), <strong>CPU</strong> (run-to-run reproducibility of the CPU encode &Delta;W), <strong>GPU</strong> (same for GPU). Their mean becomes <code>variance_pct</code>.</p>
  <p>The runner is hardened against silent encode failures: every <code>ffmpeg</code> invocation&rsquo;s exit code is checked, only successful encodes contribute &Delta;W, and per-side failure counters are tracked. <strong>If &ge;50% of either side fails, the runner refuses to update settings</strong> &mdash; the result JSON is still returned (with <code>cpu_failed</code>, <code>gpu_failed</code>, <code>failure_stderr</code>, <code>abort_reason</code> fields) for forensics, but <code>variance_pct</code> stays unchanged on disk. This protects against the failure mode where partial-encode &Delta;W values contaminate the calibration without the operator noticing.</p>

  <h2 id="diagnostics">Diagnostics &amp; Pre-calibration</h2>

  <p>Two layers of measurement-discipline tooling sit alongside the calibration:</p>

  <h3>Thermal-recovery probe</h3>
  <p>Before trusting a calibration result, the system needs to know that <code>variance_cooldown_s</code> is long enough &mdash; the idle samples taken between encodes must come from a thermally recovered system, not from the tail of the previous workload. The <code>bin/probe-thermal-recovery</code> diagnostic characterises this empirically. For a sequence of distances <em>d</em> after each of a CPU and a GPU encode (defaults: 0, 2, 5, 8, 12, 18, 25, 35, 50, 70, 95, 120 seconds), the probe samples idle power for 8 polls and writes the mean / std / CV to a CSV under <code>results/diagnostics/</code>.</p>
  <figure id="recoveryFig" style="margin:18px 0 22px;padding:14px 16px;background:var(--surface);border:1px solid var(--border);border-radius:6px">
    <div style="position:relative;height:280px"><canvas id="recoveryChart"></canvas></div>
    <figcaption id="recoveryCap" style="margin-top:10px;font-size:12px;color:var(--text-dim);line-height:1.6">Recovery curve from the latest probe run.</figcaption>
  </figure>
  <script>
  (function () {
    var data = {RECOVERY_CHART_DATA};
    var fig = document.getElementById('recoveryFig');
    if (!data || !window.WlCharts) { if (fig) fig.style.display = 'none'; return; }
    var cpu = data.points.filter(function (p) { return p.workload === 'cpu'; }).map(function (p) { return {x: p.distance_s, y: p.mean_w}; });
    var gpu = data.points.filter(function (p) { return p.workload === 'gpu'; }).map(function (p) { return {x: p.distance_s, y: p.mean_w}; });
    WlCharts.line({
      canvas: document.getElementById('recoveryChart'),
      xLabel: 'seconds after the encode ends',
      yLabel: 'mean idle power (8-poll window)',
      yUnit:  'W',
      datasets: [
        { label: 'after a CPU encode', color: 'cpu', points: cpu },
        { label: 'after a GPU encode', color: 'gpu', points: gpu },
        { label: 'configured cooldown (' + data.cooldown + 's)', color: 'warn', borderDash: [5, 4], pointRadius: 0,
          points: [{x: data.cooldown, y: data.yLo}, {x: data.cooldown, y: data.yHi}] }
      ]
    });
    var cap = document.getElementById('recoveryCap');
    if (cap) cap.innerHTML = 'Source: <code>' + data.source + '</code> &middot; generated ' + data.generatedAt +
      '. Idle power drops back to &approx;' + data.floor + '&nbsp;W within roughly 5&nbsp;s of either encode ending and stays flat; the dashed line marks the configured ' + data.cooldown + '&nbsp;s cooldown &mdash; comfortably past recovery.';
  })();
  </script>

  <p>On the GoS1 hardware the recovery is fast (see chart above): post-CPU and post-GPU baselines converge to the settled idle floor by <em>d&nbsp;=&nbsp;5&ndash;8&thinsp;s</em> with within-window CV around 1&ndash;2.5%. So the configured cooldown of <code>{VARIANCE_COOLDOWN_S}</code>&thinsp;seconds is comfortably more than necessary &mdash; useful as a margin, not as a correction.</p>
  <p>The same curve is also on the Settings page (lab access), where it refreshes live from the probe endpoint. Each probe run overwrites nothing &mdash; it leaves a fresh timestamped CSV pair under <code>results/diagnostics/</code> so historical curves can be diffed if hardware or thermal conditions change.</p>

  <h3>Why the probe matters</h3>
  <p>The probe was the seam that exposed the <code>scale_vaapi</code> leak (the GPU encode failed within 90 seconds of starting the diagnostic) and the silent-failure path in the calibration loop. Generalisable lesson: <em>measurement code should fail loudly, not interpolate around brokenness.</em> It now runs queue-aware from the Settings page (<code>/precalibration/run</code>, lab access) as well as the CLI.</p>

  <h2 id="hardware">Hardware Disclosure</h2>

  <p>All results are tied to specific hardware. Different CPUs, GPUs, RAM configurations, and PSU efficiencies will produce different numbers. OWL results should always be cited with their hardware context.</p>

  <table class="hw-table">
    <tr><td>Server</td><td>GoS1 &mdash; custom build, Ubuntu 24, kernel 6.17</td></tr>
    <tr><td>CPU</td><td>AMD Ryzen 9 7900, 24 cores (12C/24T), 65W TDP</td></tr>
    <tr><td>GPU</td><td>{GPU_HW}</td></tr>
    <tr><td>RAM</td><td>61 GB DDR5</td></tr>
    <tr><td>Storage</td><td>500 GB NVMe SSD (OS + working set) + 4 TB NVMe SSD (test media &amp; result archive, mounted <code>/srv/data</code>)</td></tr>
    <tr><td>Idle power</td><td>~79W at the wall (settled, display-blanked). The mid-2026 RTX 5080 swap raised idle ~+20W over the prior AMD 7800 XT (~57&ndash;59W) &mdash; intrinsic to the larger card, not a fault. The 5080 idle is display-state-sensitive: a blanked desktop sits at ~79W, an active (non-blanked) desktop ~101W; GoS1 blanks ~15&nbsp;min after the last input, so the like-for-like figure is ~79W</td></tr>
    <tr><td>Measurement</td><td>{METER_NAME}, polled at {METER_CADENCE} via local API (tapo 0.8.12)</td></tr>{METER_TOPOLOGY_ROW}
    <tr><td>Video</td><td>ffmpeg current master build (<code>/usr/local/bin/ffmpeg-master</code> &mdash; ships the NVENC encoders + <code>scale_cuda</code> filter) &mdash; libx264, libx265, libsvtav1 (CPU); {VIDEO_GPU_ENCODERS}</td></tr>
    <tr><td>LLM</td><td>Ollama 0.20.2 &mdash; model ladder ~1B&ndash;20B, CPU + CUDA GPU (live panel on <a href="/llm" style="color:var(--accent);text-decoration:none">/llm</a>); Qwen3 4B is the canonical RAG model</td></tr>
    <tr><td>Image</td><td>PyTorch + diffusers &mdash; panel of distilled diffusion models ~0.6B&ndash;3.5B, CPU + CUDA GPU, larger models GPU-only (live panel on <a href="/image" style="color:var(--accent);text-decoration:none">/image</a>)</td></tr>
  </table>

  <div class="callout">
    <strong>Hardware change &mdash; GPU swap (mid-2026).</strong> GoS1&rsquo;s GPU was replaced from an AMD Radeon RX&nbsp;7800&nbsp;XT (VAAPI + ROCm) with an NVIDIA RTX&nbsp;5080 (NVENC + CUDA). OWL&rsquo;s vendor-abstraction layer auto-detected the new card with no code change, and results are stamped with the GPU they ran on. The driver was tooling reach (CUDA-only partner workloads), not energy &mdash; and the swap has a real methodology consequence worth stating plainly: <strong>idle power rose ~+20W at the wall</strong> (~57&ndash;59W &rarr; ~79W), intrinsic to the larger card. Per-encode NVENC is more efficient than VAAPI at matched bitrate (measured n=10: H.264 &minus;42%, H.265 &minus;22%, AV1 &minus;25% energy), but the higher idle floor means the swap is only <em>net</em> energy-positive for H.264-heavy, near-saturated duty cycles; for H.265 the idle penalty is never repaid by transcode alone. We therefore treat the 5080 as a <strong>capability / quality / speed upgrade, not a same-workload energy win</strong>. The frozen pre-swap AMD baseline is preserved for comparison.
  </div>

  <h2 id="tests">Test Types</h2>

  <h3>Video transcoding</h3>
  <p>Transcode a source file (default: Netflix Meridian 4K, CC BY 4.0) to a target codec and 1080p. Measures the energy cost of the full encode pipeline &mdash; decode, colour-space conversion, scale, encode. Supports CPU vs GPU comparison: both paths are run sequentially with a cooldown between them, and results are presented side by side.</p>
  <p>Six presets across three codecs: <strong>H.264</strong> (libx264 / {GPU_H264_ENC}, 4000 kbps), <strong>H.265</strong> (libx265 / {GPU_H265_ENC}, 2000 kbps), <strong>AV1</strong> (libsvtav1 / {GPU_AV1_ENC}, 1500 kbps). A seventh <strong>Compare all codecs</strong> preset runs all six in sequence and produces a cross-codec energy matrix. (Encoder names track the installed GPU &mdash; the live list is in the Hardware Disclosure table above.)</p>
  <p>All presets use <strong>ABR (Average Bit Rate)</strong> rate control at a shared per-codec bitrate target, so CPU and GPU receive the identical encoding task &mdash; output file sizes match across devices as confirmation. All GPU presets use the <strong>full hardware pipeline</strong>: hardware decode (<code>-hwaccel cuda</code>) + <code>scale_cuda</code> + hardware encode, with frames GPU-resident throughout. This represents real live-encoding workflows (Harmonic, Ateme); an earlier partial pipeline (CPU decode + GPU encode) has been replaced because it was unrepresentative and bottlenecked on CPU decode overhead.</p>
  <p>The ffmpeg command used for each run is logged in the result JSON, editable from the page (signed-in GoS members and lab access), and reproduced in the result card for full transparency.</p>
  <p><strong>Perceptual quality (VMAF).</strong> Comparison runs (CPU vs GPU, or all codecs) also report <strong>VMAF</strong> &mdash; Netflix&rsquo;s perceptual quality metric (0&ndash;100, higher is better) &mdash; so the energy figures sit next to a quality figure rather than an unstated assumption that the encodes are equivalent. It is computed at the delivered 1080p, comparing each encoded output against the source downscaled to 1080p (the distorted side is cropped to strip hardware-encoder padding, never upscaled). VMAF runs <em>after</em> the measurement window closes, so its compute cost is excluded from the reported energy. It is a quality cross-check, not a primary GoS measurement.</p>
  <p><strong>VMAF model version &mdash; v1 since 2026-07-17.</strong> OWL scores with Netflix&rsquo;s <strong>VMAF&nbsp;v1</strong> (model <code>vmaf_v1.0.16</code>, released 2026-06-20 with libvmaf&nbsp;3.2.0). v1 drops the VIF feature, adds a banding detector (CAMBI) and VMAF&rsquo;s first chroma (colour) feature, and corrects v0&rsquo;s over-prediction on high-motion content &mdash; failure modes that sit exactly where OWL&rsquo;s tests live (starvation-bitrate encodes band; sports content is high-motion). Every stored score carries its model identity (<code>vmaf_model</code>); <strong>results without that field predate 2026-07-17 and were all scored by <code>vmaf_v0.6.1</code></strong> &mdash; they remain valid v0 scores. The two scales are <strong>not comparable</strong> (the same degraded-vs-clean 1080p pair scored 77.95 on v0 and 83.59 on v1 on this bench), so result cards label every score v0 or v1 and comparisons are only ever made within one model. Scoring runs through a dedicated newer ffmpeg build (needed for libvmaf&nbsp;&ge;3.2.0); the pinned <em>encode</em> binary is untouched, so the model upgrade cannot confound energy measurements. Measured scoring cost on this bench is within a few percent of v0 either way &mdash; removing VIF roughly pays for CAMBI&nbsp;+&nbsp;chroma.</p>
  <p><strong>No-reference quality (CompressedVQA-HDR).</strong> Enhancement / super-resolution runs on uploaded or general content have no ground-truth reference (the AI adds detail the source never had), so full-reference metrics do not apply there. Instead, OWL reports a <strong>no-reference</strong> score from <strong>CompressedVQA-HDR</strong> (Sun et al., arXiv:2507.11900, Apache 2.0 &mdash; winner of the ICME 2025 HDR/SDR VQA grand challenge), a learned model that scores each file independently and handles both HDR10 and SDR content. Like VMAF it runs <em>after</em> the measurement window closes, so its compute cost is excluded from the reported energy. Being a learned opinion of perceptual quality rather than a measurement, it is presented as a relative indicator <em>within</em> a run &mdash; never as an absolute quality claim &mdash; and is subject to further refinement pending validation.</p>
  <p><strong>Full-reference fidelity on ladder fixtures &mdash; two axes, read together.</strong> For the ten degraded-ladder fixtures OWL generated from its own pristine 4K masters (Big Buck Bunny and Meridian), a ground truth <em>does</em> exist, and enhancement runs on them additionally report <strong>full-reference VMAF</strong> (v1, 4K model) against that master &mdash; computed after the measurement window closes, like all quality scoring. Fidelity and perceptual quality are <strong>different axes</strong>, and OWL reports both deliberately: the no-reference score rates how good the output looks on its own; the full-reference score measures <em>similarity to the reference</em>, not perceived quality in the broader sense. Enhanced output is rarely one thing or the other: in practice it mixes genuinely recovered structure, reconstruction from learned priors, and newly synthesised detail, and the synthesised share can look convincing without matching the master&rsquo;s exact pixels. Enhancement therefore typically raises perceived quality while moving the signal <em>further</em> from the master, and an output scoring below the naive-upscale anchor on fidelity while beating it on the no-reference axis is an expected signature of generative enhancement &mdash; not a defect of the enhancer or the metric, and <strong>not</strong> evidence that the output looks worse; the divergence between the two axes is itself the measurement. Two anchors give the fidelity score context, both paying the same pipeline encode as the measured output: a plain lanczos upscale of the degraded source (<em>naive-encode anchor</em> &mdash; what dumb scaling preserves) and the pristine master itself through the same pipeline (<em>pristine-encode anchor</em> &mdash; its gap to 100 is encode cost alone, landing around 89&ndash;91 on these fixtures). The degraded source scored as a player would display it (no pipeline encode) is shown as a separate path, never compared directly. Full-reference scoring requires an SDR 4K output &mdash; the anchors are 4K-denominated, and VMAF across HDR/SDR transfer functions is not meaningful &mdash; so other output targets, uploads, and non-ladder sources stay no-reference only.</p>
  <p><strong>Contributed technology.</strong> Some measured workloads use technology contributed by GoS member organisations &mdash; the AI video-enhancement harness measures <strong>{PARTNER_NAME}</strong>, contributed by {PARTNER_ORG}. Contributed technologies run on GoS hardware under this methodology; results are energy data, not endorsements. GoS members can contribute streaming technologies for measurement on the same terms.</p>
  <p><strong>4K&nbsp;HDR enhancement &mdash; reduced-capacity note.</strong> The HDR&nbsp;&rarr;&nbsp;4K super-resolution combo sits close to the GPU&rsquo;s memory ceiling on this hardware (peak ~94&nbsp;% of 16&nbsp;GB). To run it reliably, OWL applies two {PARTNER_ORG}-supplied pipeline settings that lower the in-flight memory pressure (a smaller input buffer and fewer concurrent super-resolution threads), which bring the peak down to ~85&nbsp;%. A controlled A/B on identical content found this changed the measured energy and encode throughput by less than the run-to-run noise &mdash; so the figure is reported normally, with the settings recorded in the result JSON. This note applies <em>only</em> to the 4K&nbsp;HDR combo; every other enhancement preset runs at the pipeline&rsquo;s default settings.</p>

  <h3>AI workloads <span style="color:var(--text-dim);font-weight:400;font-size:13px">— beta, exploratory</span></h3>
  <p>Video transcoding is OWL&rsquo;s core benchmark. Three AI workloads run alongside it on the same protocol and confidence framework, but they are explicitly <strong>beta</strong> &mdash; useful for relative comparisons, with headline numbers still being hardened (see Open Questions). In brief:</p>
  <ul style="margin: 12px 0 18px 20px; font-size: 14px; line-height: 1.7;">
    <li><strong>LLM inference</strong> &mdash; mWh/token across a model ladder (TinyLlama&nbsp;1.1B, Qwen3&nbsp;1.7B/4B/8B, Mistral-NeMo&nbsp;12B, Phi-4&nbsp;14B, up to GPT-OSS&nbsp;20B), cold or warm, CPU or GPU, with an optional batch mode. Prompts are saved in the result JSON; output streams word-by-word as live-run proof.</li>
    <li><strong>Image generation</strong> &mdash; Wh/image across the distilled diffusion panel (~0.6B&ndash;3.5B), CPU or GPU, with a Compare-Models mode that fixes prompt, seed and resolution so the model is the only variable.</li>
    <li><strong>RAG</strong> &mdash; the energy delta of retrieval: baseline (no retrieval) vs RAG with 3 context chunks vs 8, retrieved from a document corpus via ChromaDB + sentence-transformer embeddings, compared side by side.</li>
  </ul>

  <p><strong>Framing (GoS Language Lab position paper, Jan 2026):</strong> AI in streaming is <strong>neither inherently sustainable nor unsustainable</strong> &mdash; type, size and deployment decide net impact. The type matters enormously: streaming leans on <strong>small specialised CNNs</strong> (per-title encoding, scene classification, super-resolution) that are orders of magnitude cheaper than the general-purpose LLMs and diffusion models these tabs measure as an upper bound. OWL measures the energy AI <strong>adds</strong> (inference only); it does not measure the infrastructure energy AI <strong>avoids</strong> through better compression, caching or routing &mdash; both halves are needed for net impact, and OWL has the first. Each AI result is also shown as a multiple of a real video encode (the pinned canonical H.265&nbsp;GPU encode of Meridian-120s) so the number stays anchored to a streaming workload rather than floating free. Full framing: <a href="{POSITION_PAPER_URL}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none">Language Lab AI position paper &rarr;</a>.</p>

  <h3>Client-device decode panels <span style="color:var(--text-dim);font-weight:400;font-size:13px">— external rig, 2026-07</span></h3>
  <p>Encode energy is paid once per title; <strong>decode energy is paid per viewer</strong> &mdash; so in 2026-07 the protocol went to the client side. A portable rig (a Google TV set-top box; Raspberry Pi 5 and Pi 400) measured decode power per codec, per decode path (hardware vs software) and per regime (paced playback vs flat-out), with the same baseline/&Delta;W/confidence method and local-mW metering. Headlines: a hardware decoder cuts decode power ~3.6&ndash;4&times; on the same board; codec choice is nearly free on decode silicon but moves software decode power by up to ~60%. Full results, replication counts and caveats are in the <a href="/findings" style="color:var(--accent);text-decoration:none">findings catalog</a>; these panels state their own device scope and are not GoS1-server results.</p>

  <h2 id="energy-budget">Energy budget &amp; encode parity</h2>

  <p>Operators rarely ask &ldquo;how small can the file be.&rdquo; They fix a <strong>quality target</strong> &mdash; most often VMAF&nbsp;92 &mdash; and then try to <strong>hit that quality for the least energy</strong>. The <a href="/video/budget" style="color:var(--accent);text-decoration:none">transcode budget calculator</a> answers the inverse: given an energy budget, how many minutes of video can you push at your target VMAF, on which hardware, with which codec?</p>

  <p>That calculator runs on a <strong>measured calibration table</strong>, built under the same protocol as every other OWL test. For a fixed source we sweep an ABR bitrate ladder across each codec (H.264&nbsp;/&nbsp;H.265&nbsp;/&nbsp;AV1) on both the CPU encoder (libx264&nbsp;/&nbsp;libx265&nbsp;/&nbsp;libsvtav1) and the GPU encoder (NVENC), measuring wall energy and &mdash; as a terminal pass &mdash; VMAF. For a chosen target VMAF we read the bitrate that hits it off the measured curve, and the watt-hours per minute that bitrate costs.</p>

  <p><em>Model note:</em> the current calibration table and the VMAF&nbsp;92 operator target were measured in <strong><code>vmaf_v0.6.1</code></strong> terms (the model in force at calibration, 2026-06). Live scoring moved to VMAF&nbsp;v1 in 2026-07; because the scales are not comparable, the budget page stays in v0 terms &mdash; and says so &mdash; until the next re-calibration re-scores the table under v1.</p>

  <h3>Encode parity &mdash; is the GPU really &ldquo;worse&rdquo;?</h3>
  <p>Operators often say hardware encoders score lower than software, &ldquo;especially for AV1.&rdquo; To test that fairly we measure the GPU twice at each bitrate &mdash; once with OWL&rsquo;s current NVENC arguments (<em>baseline</em>) and once with a quality-knob bundle (<em>tuned</em>: <code>-preset p7 -multipass 2 -spatial-aq -temporal-aq -rc-lookahead</code>, B-frame references) &mdash; so the VMAF difference, and its energy cost, are <strong>measured rather than asserted</strong>. What the first full run (90 encodes, all&nbsp;&#x1F7E2;) showed:</p>
  <ul style="margin: 12px 0 18px 20px; font-size: 14px; line-height: 1.7;">
    <li><strong>Energy:</strong> NVENC uses <strong>2.5&ndash;4.4&times; less energy per minute</strong> of video than the CPU encoder &mdash; and the win is <em>speed</em>, not lower draw: instantaneous wattage is similar (~70&nbsp;W either way); the GPU simply finishes far sooner.</li>
    <li><strong>Parity:</strong> the &ldquo;GPU is worse, especially AV1&rdquo; effect is real but <strong>only on low-complexity content at low bitrate</strong> (AV1 on Big Buck Bunny trailed by up to ~9 VMAF at 1&nbsp;Mbps). On high-complexity content (Meridian) the gap nearly vanishes &mdash; and NVENC AV1 actually <em>beats</em> libsvtav1 at its default preset at mid-to-high bitrate.</li>
    <li><strong>Tuning, measured and rejected:</strong> the &ldquo;tuned&rdquo; bundle cost <strong>1.6&ndash;2.8&times; the energy</strong> and <em>lowered</em> VMAF for H.264 and AV1 (adaptive quantisation trades a fidelity metric like VMAF for perceptual quality). So the live encode path keeps the baseline NVENC config; we do not pay energy to make the metric worse.</li>
  </ul>

  <h3>What an &ldquo;ABR ladder&rdquo; means here</h3>
  <p>A real delivery encodes the same source at several resolutions so a player can adapt to bandwidth. The calculator&rsquo;s &ldquo;full ABR ladder&rdquo; unit is a <strong>5-rung</strong> ladder: 1080p (the quality-anchor rung, whose bitrate is set by the VMAF target) plus fixed lower rungs at 720p&nbsp;/&nbsp;540p&nbsp;/&nbsp;480p&nbsp;/&nbsp;360p (lower rungs scale per codec). Ladder energy is the sum of all five rungs; the &ldquo;1080p only&rdquo; unit is the top rung alone.</p>

  <p>The calibration is keyed by a <strong>hardware fingerprint</strong> (GPU, CPU, ffmpeg version) and is re-runnable from the Lab when the encode hardware changes &mdash; e.g. when dedicated ASIC/FPGA transcode cards arrive &mdash; so a hardware swap produces a new dataset rather than silently reusing stale numbers. Full method note: <code>docs/encode_parity_calibration_2026-06.md</code>.</p>

  <div class="open-q"><span class="marker">&#9658;</span><span><strong>Fast encoders vs 1&nbsp;Hz sampling.</strong> An NVENC encode of a 30&nbsp;s clip finishes in a few seconds &mdash; too few 1&nbsp;Hz power samples for a tight interval. The calibration repeats each encode back-to-back until at least ~20&nbsp;s of wall-clock has elapsed, then normalises energy by total content encoded. Clip length itself (30&nbsp;s) follows the quality/energy literature (&gt;15&nbsp;s to clear encoder start-up overhead; &ge;10&nbsp;s for a representative VMAF).</span></div>

  <h2 id="limits">Known Limitations</h2>

  <div class="open-q"><span class="marker">&#9658;</span><span><strong>Temporal resolution.</strong> Polling at {METER_CADENCE} means tasks shorter than ~5 seconds produce few data points. Very fast models (e.g., TinyLlama single inference at 1&ndash;4 seconds) are at the edge of measurability. Batching mitigates this but changes what&rsquo;s being measured (batch cost, not single-inference cost). The same constraint puts a floor on any artificially-shortened encode: a workload that finishes in 3&ndash;4 seconds yields only 3&ndash;4 polls, and the resulting per-run &Delta;W mean becomes noisy enough to inflate the coefficient of variation independently of any real measurement issue. The binding limit is the meter&rsquo;s <em>internal refresh rate</em> (firmware-dependent; measured per plug with <code>bin/probe-p110-fw</code>) &mdash; polling faster than the refresh yields duplicate readings, not more information. Power <em>resolution</em> is not the limit: the local API preserves the instrument&rsquo;s ~1&nbsp;mW reading (see Confidence above).</span></div>

  <div class="open-q"><span class="marker">&#9658;</span><span><strong>Single server.</strong> All results are from one machine. Generalisability to other hardware configurations is unknown without cross-platform measurement.</span></div>

  <div class="open-q"><span class="marker">&#9658;</span><span><strong>Baseline drift.</strong> The server&rsquo;s idle power drifts with thermal state, background processes, and &mdash; since the RTX 5080 swap &mdash; GPU display power state: a blanked vs active desktop alone moves the wall figure by ~20W (~79W &rarr; ~101W). The per-run baseline capture (re-measured immediately before each task) mitigates this, but it introduces variance between runs taken at different times.</span></div>

  <div class="open-q"><span class="marker">&#9658;</span><span><strong>PSU efficiency curve.</strong> Wall power includes PSU conversion losses, which are non-linear (PSUs are less efficient at low and very high loads). Two tasks that consume the same <em>internal</em> power may report different wall-power deltas depending on where they sit on the PSU efficiency curve.</span></div>

  <h2 id="carbon">From energy to CO<sub>2</sub>e &mdash; for reference only</h2>

  <p><strong>OWL is a power meter, not a carbon calculator.</strong> The number OWL produces and stands behind is <strong>energy</strong> &mdash; watts at the wall and watt-hours per task, measured directly by the P110. Everything else on this page is about getting that energy number right. We lead with power because it is what we can measure at the wall with no modelling assumptions; carbon is one modelling layer removed.</p>

  <p>Every result <em>also</em> carries a gCO<sub>2</sub>e figure, but only as a downstream convenience: we multiply the measured energy by a grid carbon-intensity factor (Wh &times; gCO<sub>2</sub>e/kWh) so the energy can be read against everyday activities. That makes it a <strong>reference estimate, never a GoS measurement.</strong> Carbon attribution &mdash; allocation, boundaries, double-counting, marginal vs average intensity &mdash; is a hard problem that GoS deliberately leaves to the bodies whose job it is. This follows the GoS principle directly: <em>&ldquo;if it can&rsquo;t be measured, it shouldn&rsquo;t be asserted&rdquo;</em> &mdash; and what OWL measures directly is energy. Read the energy figure as the result; the CO<sub>2</sub>e is a footnote.</p>

  <p style="background:rgba(255,170,0,0.06);border-left:3px solid var(--warning);padding:0.65rem 0.85rem">
    <strong style="color:var(--accent)">🟢 Direct</strong> = the energy figure (P110 polling at the wall, validated method, GoS primary measurement &mdash; this is what we cite). <strong style="color:var(--warning)">🟡 Indicative</strong> = the gCO<sub>2</sub>e figure (Wh &times; third-party grid intensity &mdash; context, not citable as GoS data). Vocabulary follows the Greening of Streaming <a href="{POSITION_PAPER_URL}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none">Language Lab AI position paper (Jan 2026)</a>, which proposes this 🟢/🟡/🔴 traffic-light for the entire ICT-energy-measurement landscape and rates IEA top-down energy figures as 🟡 Amber. OWL applies the same framework to its own outputs &mdash; every result-card carbon block carries the 🟡 chip; the energy headline retains the green palette.
  </p>
  <p>For what it&rsquo;s worth, the intensity used is lifecycle-basis (IPCC AR6 factors): the live French grid mix via <a href="{ECO2MIX_URL}" style="color:var(--accent);text-decoration:none">Eco2mix</a> when reachable, ElectricityMaps as a backup, and <a href="{EMBER_URL}" style="color:var(--accent);text-decoration:none">Ember</a> annual country means as the fallback (also used for the stable comparison cities). The value and which source produced it are recorded in every result JSON and CSV export (CSV header carries a leading comment marking the carbon columns indicative). A result&rsquo;s carbon dropdown also shows the same energy on a few past French grids for context. Module status &mdash; live cache, source, age, fallback &mdash; is at <a href="/carbon" style="color:var(--accent);text-decoration:none">/carbon</a>.</p>

  <h2 id="open">Open Questions</h2>

  <p>These are questions OWL has surfaced but not yet answered. They are published here in the interest of transparency.</p>

  <div class="open-q"><span class="marker">?</span><span><strong>Confidence thresholds.</strong> The live flag is the CR-028 Phase 2 confidence interval described above; its positive-confidence cut-points (95% / 80%) and minimum poll counts are still set by judgement, and the first pass uses a 1.96 critical value with raw sample counts. A working session with the measurement team is planned to ground these &mdash; and to add the autocorrelation (effective-<em>n</em>) and Student-<em>t</em> refinements &mdash; against repeated calibration runs across workloads and thermal states. (The legacy 5&times; / 2&times; variance multipliers now apply only to pre-CI historical results.)</span></div>

  <div class="open-q"><span class="marker">?</span><span><strong>Transcoding profile/GOP equivalence.</strong> ABR rate control now gives CPU and GPU the same bitrate target, and output file sizes match as confirmation. GOP structure and profile level are still default-per-encoder and have not been explicitly normalised. A working session is planned to confirm apples-to-apples at that level, and to add a second benchmark family at each codec&rsquo;s natural operating point (CRF for CPU, QP for GPU).</span></div>

  <div class="open-q"><span class="marker">?</span><span><strong>AI-workload questions (beta).</strong> LLM: does mWh/token drift across a batch (thermal saturation, memory pressure)? Image / RAG: how much of each energy delta is fixed overhead (model load, embedding lookup) vs. work that scales with output or context length? Secondary to the video benchmark; not yet investigated in depth.</span></div>

  <div class="open-q"><span class="marker">?</span><span><strong>Cross-platform comparability.</strong> How should results from different hardware be compared? Normalisation by TDP? By performance tier? By workload-equivalent output quality?</span></div>

  <div class="footer-note">
    OWL is built and maintained by <a href="{GOS_URL}" style="color:var(--accent);text-decoration:none;">Greening of Streaming</a>, a French NGO (loi 1901).<br>
    Methodology version 0.7 &middot; last updated 2026-08-15 &middot; Feedback: bs@ctoic.net<br>
    Source: <a href="{GITHUB_REPO_URL}" style="color:var(--accent);text-decoration:none;">github.com/greeningofstreaming/wattlab</a>
  </div>

  <a href="/" class="home-link bottom">&larr; Home</a>

</div>
</body>
</html>"""


def _recovery_chart_payload(cooldown_s):
    """Latest thermal-recovery probe summary, trimmed to what the static
    /methodology chart needs (points + settled floor + provenance), or None
    if no probe data is on disk. Unlike /precalibration/data this carries no
    auth — it's a frozen snapshot baked into a public page at render time,
    re-read from the CSV on each request."""
    import csv as csv_mod
    diag_dir = Path("/home/gos/wattlab/results/diagnostics")
    summaries = sorted(diag_dir.glob("recovery_*_summary.csv")) if diag_dir.exists() else []
    if not summaries:
        return None
    latest = summaries[-1]
    pts = []
    try:
        with latest.open() as f:
            for row in csv_mod.DictReader(f):
                pts.append({"distance_s": int(row["distance_s"]),
                            "workload":   row["workload"],
                            "mean_w":     round(float(row["mean_w"]), 2)})
    except (OSError, KeyError, ValueError):
        return None
    if not pts:
        return None
    ys      = [p["mean_w"] for p in pts]
    settled = [p["mean_w"] for p in pts if p["distance_s"] >= 60]
    floor   = round(sum(settled) / len(settled), 1) if settled else round(min(ys), 1)
    return {
        "points":      pts,
        "cooldown":    cooldown_s,
        "floor":       floor,
        "yLo":         round(min(ys), 1),
        "yHi":         round(max(ys), 1),
        "source":      latest.name,
        "generatedAt": datetime.fromtimestamp(latest.stat().st_mtime).isoformat(timespec="seconds"),
    }


_gpu_display_name   = ui._gpu_display_name
_gpu_hw_row         = ui._gpu_hw_row
_gpu_video_encoders = ui._gpu_video_encoders
_gpu_enc            = ui._gpu_enc
_gpu_runtime        = ui._gpu_runtime


def _partner() -> dict:
    """Member-contributed-technology naming — single source in pixop.config
    (settings-overridable), shared with /enhance-run."""
    import pixop
    return pixop.config()


@router.get("/methodology", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def methodology_page(request: Request):
    # Inject live settings into placeholder fields so the methodology page
    # can never silently drift from the actual configuration in settings.json.
    # See CR-002 for context — `baseline_polls`, `video_cooldown_s`, and the
    # confidence thresholds (variance multipliers + poll counts) were
    # previously hard-coded in the prose and table, and contradicted the
    # running config any time settings were changed.
    s = cfg.load()
    recovery = _recovery_chart_payload(s.get("variance_cooldown_s", 40))
    return (_METHODOLOGY_HTML
            .replace("<!--OG_META-->",       ui.og_meta_html(
                "OWL Measurement Methodology", "/methodology",
                "How OWL measures: wall-metered baselines and deltas, "
                "traffic-light confidence on every claim, explicit scope. "
                "The full public protocol."))
            .replace("{AUTH_CHIP_STYLES}",   _AUTH_CHIP_STYLES)
            .replace("{AUTH_CHIP}",          _auth_chip_html(request))
            .replace("{BASELINE_POLLS}",     str(s.get("baseline_polls",     "—")))
            .replace("{VIDEO_COOLDOWN_S}",   str(s.get("video_cooldown_s",   "—")))
            .replace("{CONF_GREEN_X}",       str(s.get("variance_green_x",   "—")))
            .replace("{CONF_YELLOW_X}",      str(s.get("variance_yellow_x",  "—")))
            .replace("{CONF_GREEN_POLLS}",   str(s.get("conf_green_polls",   "—")))
            .replace("{CONF_YELLOW_POLLS}",  str(s.get("conf_yellow_polls",  "—")))
            .replace("{VARIANCE_RUNS}",      str(s.get("variance_runs",      "—")))
            .replace("{VARIANCE_COOLDOWN_S}",str(s.get("variance_cooldown_s","—")))
            .replace("{GPU_HW}",             _gpu_hw_row())
            .replace("{VIDEO_GPU_ENCODERS}", _gpu_video_encoders())
            .replace("{GPU_H264_ENC}",       _gpu_enc("h264"))
            .replace("{GPU_H265_ENC}",       _gpu_enc("h265"))
            .replace("{GPU_AV1_ENC}",        _gpu_enc("av1"))
            .replace("{METER_NAME}",         meter_display_name())
            .replace("{METER_CADENCE}",      meter_cadence_label())
            .replace("{METER_TOPOLOGY_ROW}", meter_topology_row())
            .replace("{PARTNER_NAME}",       _partner()["partner_name"])
            .replace("{PARTNER_ORG}",        _partner()["partner_org"])
            .replace("{RECOVERY_CHART_DATA}", json.dumps(recovery))
            .replace("{POSITION_PAPER_URL}",  POSITION_PAPER_URL)
            .replace("{GOS_URL}",             GOS_URL)
            .replace("{GOS_LOGO_URL}",        GOS_LOGO_URL)
            .replace("{GITHUB_REPO_URL}",     GITHUB_REPO_URL)
            .replace("{GITHUB_ISSUES_URL}",   GITHUB_ISSUES_URL)
            .replace("{ECO2MIX_URL}",         ECO2MIX_URL)
            .replace("{EMBER_URL}",           EMBER_URL)
            .replace("{CHARTJS_URL}",         CHARTJS_URL))
