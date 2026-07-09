"""
Guided Tour route — /demo (the Anonymous landing experience, CR-033/027/
058). Settings-driven numbers are injected per request so the tour can
never contradict the running config; the Findings step pulls the curated
catalog from routes_findings.

Phase 3 per-feature route module — chrome from ui.py, never import main.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

import curated
import findings as findings_mod
import gpu
import llm as llm_mod
import settings as cfg
import sources
import ui
from capabilities import requires, PUBLIC_PAGE
from image_gen import IMAGE_MODELS
from power import meter_display_name, meter_cadence_label
import routes_budget
from routes_findings import _findings_catalog_rows_html, _FINDINGS_CATALOG_CSS
from ui import (GOS_URL, JOIN_GOS_URL, _BETA_CHIP, _CONF_HELP_WIDGET,
                _PROGRESS_JS, _RESULT_JS, _gpu_display_name, _gpu_enc,
                _gpu_runtime, _tier_indicator_html)

router = APIRouter()


# Findings are frozen as-measured and legitimately name the hardware they ran
# on (the AMD-era av1_vaapi finding keeps "vaapi" forever). The /demo teaser,
# however, is live serve-time chrome that must match the running backend — a
# finding whose *visible* row names the other backend's encoder reads as a
# copy-leak, not provenance, and trips the GPU-wording guards. So the teaser
# hides findings whose rendered surface (headline + claim_short — the only
# fields _findings_catalog_rows_html shows; scope/tags are NOT rendered) names
# the OTHER encoder family. The full /findings catalog still lists everything.
# Routes the live family through gpu.BACKEND.stamp(), per the GPU-copy rule.
_FOREIGN_BACKEND_TOKENS = {"nvenc": ("vaapi", "rocm"), "vaapi": ("nvenc", "cuda")}


def _finding_matches_live_backend(f) -> bool:
    live_enc = (gpu.BACKEND.stamp() or {}).get("encode", "")
    foreign = _FOREIGN_BACKEND_TOKENS.get(live_enc, ())
    if not foreign:
        return True
    rendered = (f.headline + " " + f.claim_short).lower()
    return not any(tok in rendered for tok in foreign)


# --- Demo mode ---

# Single source of truth for what the demo buttons actually run. The tour
# copy AND the JS form fields both bake from these at request time, so the
# page can never describe a model/source the button doesn't run (the way
# the copy still said "Mistral 7B via Ollama ROCm" months after the demo
# moved to qwen3:4b on CUDA). RAG follows curated.CANONICAL_RAG_MODEL.
DEMO_LLM_MODEL = "qwen3:4b"
DEMO_VIDEO_SOURCE = "meridian_120s"
DEMO_IMAGE_MODEL = "sd-turbo"   # /image/start server-side default


def _llm_model_label(key: str) -> str:
    """'Qwen3 4B' from the live model registry; fail-soft to the raw key if
    the model is currently disabled or uninstalled (the demo run itself
    would fail too — the copy just mustn't lie about what it runs)."""
    m = llm_mod.MODELS.get(key)
    return m["label"] if m else key


def _llm_model_size(key: str) -> str:
    m = llm_mod.MODELS.get(key)
    return m.get("size", "?") if m else "?"


def _demo_video_source_desc() -> str:
    """Registry description of the demo clip ('3840×2160 · 59.94fps · …'),
    so the tour's source facts track sources.py, not hand-typed numbers."""
    e = sources.PRELOADED.get(DEMO_VIDEO_SOURCE) or {}
    return e.get("description") or e.get("label") or DEMO_VIDEO_SOURCE


def _demo_image_detail() -> str:
    """'CPU, 8 steps, 512×512' from the live image-model catalog."""
    m = IMAGE_MODELS.get(DEMO_IMAGE_MODEL)
    if not m:
        return "CPU"
    return f"CPU, {m['cpu_steps']} steps, {m['size_px']}&times;{m['size_px']}"


def _budget_teaser_html() -> str:
    """Energy-budget step teaser — the one takeaway from the live
    /video/budget fixture: Wh per minute of 1080p output at the operator's
    target VMAF, per codec × hardware path. Reads
    routes_budget.current_fixture() so the numbers can't drift from the
    planner page (measured when a calibration artifact exists). Vendor
    names deliberately absent — GPU wording elsewhere in the tour routes
    through gpu.BACKEND, and this table is data, not hardware copy.
    Fail-soft: any surprise shape renders nothing rather than breaking /demo."""
    try:
        fix = routes_budget.current_fixture()
        targets = fix["vmaf_targets"]
        target = cfg.load().get("target_vmaf", 92)
        idx = (targets.index(target) if target in targets else
               min(range(len(targets)), key=lambda i: abs(targets[i] - target)))
        cells: dict[tuple[str, str], float | None] = {}
        codec_labels: dict[str, str] = {}
        for r in fix["recipes"]:
            if r.get("projected") or r.get("device") not in ("cpu", "gpu"):
                continue
            wh = (r.get("wh_low") or [])[idx] if idx < len(r.get("wh_low") or []) else None
            cells[(r["codec"], r["device"])] = wh
            codec_labels[r["codec"]] = r.get("codec_label", r["codec"])
        if not cells:
            return ""
        best = min((v for v in cells.values() if v is not None), default=None)

        def cell(codec: str, device: str) -> str:
            wh = cells.get((codec, device))
            if wh is None:
                return '<td style="text-align:right;color:var(--text-5);padding:0.25rem 0.75rem">—</td>'
            hl = "color:var(--accent);font-weight:bold" if wh == best else "color:var(--text-2)"
            return f'<td style="text-align:right;{hl};padding:0.25rem 0.75rem">{wh:.3f}</td>'

        rows = "".join(
            f'<tr><td style="text-align:left;color:var(--text);padding:0.25rem 0.75rem 0.25rem 0">{codec_labels[c]}</td>'
            f'{cell(c, "cpu")}{cell(c, "gpu")}</tr>'
            for c in ("h264", "h265", "av1") if c in codec_labels
        )
        meta = fix.get("meta", {})
        if meta.get("illustrative", True):
            badge = ('<span style="color:var(--warn)">illustrative figures</span>'
                     ' — no calibration artifact yet')
        else:
            when = str(meta.get("measured_on", ""))[:10]
            badge = f'<span style="color:var(--accent)">measured</span> · GoS1 · {when}'
        clip = str(meta.get("clip_low", "low-complexity clip"))
        return (
            '<div style="border:1px solid var(--border-2);padding:1rem 1.25rem;'
            'max-width:560px;margin:1rem 0;font-family:monospace">'
            '<div style="color:var(--text-4);font-size:0.68rem;text-transform:uppercase;'
            f'letter-spacing:0.06em;margin-bottom:0.5rem">Wh per minute of 1080p video · VMAF {targets[idx]} · {badge}</div>'
            '<table style="border-collapse:collapse;font-size:0.82rem">'
            '<thead><tr style="color:var(--text-4);font-size:0.7rem;text-transform:uppercase">'
            '<th style="text-align:left;padding:0.25rem 0.75rem 0.25rem 0">Codec</th>'
            '<th style="text-align:right;padding:0.25rem 0.75rem">CPU</th>'
            '<th style="text-align:right;padding:0.25rem 0.75rem">GPU</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
            '<div style="color:var(--text-5);font-size:0.7rem;margin-top:0.5rem;line-height:1.5">'
            f'Single stream · {clip} · the full planner adds ABR ladders, budgets and every VMAF target.</div>'
            '</div>'
        )
    except Exception:
        return ""

_DEMO_STYLES = f"""
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);
       color:var(--text);max-width:840px;margin:0 auto;padding:2rem}}
  h1{{font-family:monospace;color:var(--accent);font-size:1.5rem;margin-bottom:0.25rem}}
  h2{{font-family:monospace;color:var(--accent);font-size:1.1rem;margin-bottom:0.75rem}}
  .mono{{font-family:monospace}}
  .dim{{color:var(--text-3)}}
  .accent{{color:var(--accent)}}

  /* Step nav */
  .step-nav{{display:flex;align-items:center;gap:0.5rem;margin-bottom:2.5rem;
             font-family:monospace;font-size:0.78rem;color:var(--text-5)}}
  .step-nav .dot{{width:8px;height:8px;border-radius:50%;background:var(--border);
                  transition:background 0.3s}}
  .step-nav .dot.done{{background:#00ff9966}}
  .step-nav .dot.active{{background:var(--accent)}}
  /* Optional AI-detour dots (steps 4-6): hollow + smaller so the detour
     reads as a branch off the core path, not a longer road. */
  .step-nav .dot.opt{{width:6px;height:6px;background:transparent;border:1px solid var(--border-3)}}
  .step-nav .dot.opt.done{{border-color:#00ff9966;background:#00ff9922}}
  .step-nav .dot.opt.active{{border-color:var(--accent);background:var(--accent)}}
  .step-nav .label{{color:var(--text-3);font-size:0.72rem}}
  .step-nav .label.active{{color:var(--accent)}}

  /* Steps */
  .step{{display:none}}
  .step.active{{display:block}}

  /* Logo header */
  .page-header{{display:flex;justify-content:space-between;align-items:flex-start;
                margin-bottom:2rem}}

  /* Big metric */
  .big-metric{{font-family:monospace;font-size:3.5rem;color:var(--accent);
               font-weight:bold;line-height:1;margin:1rem 0}}
  .big-label{{color:var(--text-3);font-size:0.85rem;margin-bottom:2rem}}

  /* Methodology expander */
  details{{margin:1rem 0;border-left:2px solid #222;padding-left:1rem}}
  summary{{color:var(--text-4);font-size:0.8rem;cursor:pointer;list-style:none;
           padding:0.4rem 0;user-select:none}}
  summary::-webkit-details-marker{{display:none}}
  summary::before{{content:"▶  ";font-size:0.65rem}}
  details[open] summary::before{{content:"▼  "}}
  details p{{color:var(--text-3);font-size:0.82rem;line-height:1.7;margin-top:0.5rem}}
  details p+p{{margin-top:0.5rem}}

  /* Action buttons */
  .btn-row{{display:flex;gap:0.75rem;flex-wrap:wrap;margin-top:1.5rem}}
  .btn{{font-family:monospace;font-size:0.9rem;padding:0.65rem 1.5rem;
        cursor:pointer;border:none;transition:background 0.15s}}
  .btn-primary{{background:var(--accent);color:#000}}
  .btn-primary:hover{{background:var(--accent-hover)}}
  .btn-secondary{{background:transparent;color:var(--accent);
                  border:1px solid #00ff9944}}
  .btn-secondary:hover{{background:#00ff9911}}
  .btn:disabled{{background:#1a1a1a;color:var(--text-5);cursor:not-allowed;border:none}}

  /* Result card */
  .result-card{{border:1px solid var(--border-2);padding:1.5rem;margin-top:1.5rem}}
  .result-card .headline{{font-size:1rem;color:var(--text);line-height:1.6;
                           margin-bottom:1rem}}
  .kpi-row{{display:flex;gap:1.5rem;flex-wrap:wrap;margin-bottom:1rem}}
  .kpi{{flex:1;min-width:120px}}
  .kpi .val{{font-family:monospace;font-size:1.4rem;color:var(--accent)}}
  .kpi .lbl{{font-size:0.72rem;color:var(--text-4);margin-top:0.2rem}}
  .conf-badge{{display:inline-block;font-size:0.75rem;color:var(--text-3);
               margin-top:0.5rem}}
  .response-preview{{background:var(--panel-2);border-left:2px solid #00ff9933;
                     padding:0.75rem 1rem;margin-top:1rem;font-size:0.8rem;
                     color:var(--text-3);line-height:1.7;max-height:300px;
                     overflow-y:auto;white-space:pre-wrap;font-family:monospace}}
  .scope-note{{color:var(--text-5);font-size:0.72rem;margin-top:1rem;font-family:monospace}}
  .prev-note{{color:var(--text-5);font-size:0.75rem;font-family:monospace;
              margin-top:0.5rem}}
  .divider{{border:none;border-top:1px solid var(--panel);margin:1.5rem 0}}

  /* Three-band layout */
  .band{{margin-bottom:1.75rem;padding-bottom:1.75rem;border-bottom:1px solid var(--panel-2)}}
  .band-label{{color:var(--text-5);font-size:0.68rem;text-transform:uppercase;letter-spacing:0.08em;
               font-family:monospace;margin-bottom:0.6rem}}
  .limitation{{color:var(--text-5);font-size:0.75rem;margin-top:1rem;line-height:1.6;
               font-family:monospace;border-left:1px solid var(--border-2);padding-left:0.75rem}}

  /* Progress */
  .progress-note{{color:var(--warn);font-family:monospace;font-size:0.85rem;
                  margin-top:1rem}}
  .stream-box{{background:var(--panel-2);border-left:2px solid #00ff9922;
               padding:0.75rem 1rem;margin-top:0.75rem;font-size:0.78rem;
               color:var(--text-4);line-height:1.7;max-height:160px;overflow-y:auto;
               white-space:pre-wrap;font-family:monospace;min-height:2.5rem}}

  /* Summary table */
  .summary-table{{width:100%;border-collapse:collapse;font-family:monospace;
                  font-size:0.82rem;margin-top:1rem}}
  .summary-table td{{padding:0.5rem 0.75rem;border-bottom:1px solid var(--panel)}}
  .summary-table td:first-child{{color:var(--text-3);width:40%}}
  .summary-table td:last-child{{color:var(--accent)}}

  /* CR-001 capability matrix — Findings step. Locked rows are the
     GoS membership pitch; visual treatment must read as product copy,
     not as a punishment. CR-027: three columns ("Public" / "Member" /
     "Lab"), with the Member column accent-tinted so the eye lands there
     (Member sign-up is the conversion target; Lab is operator-only and
     visible mostly so visitors understand the access ladder). */
  .cap-matrix{{width:100%;border-collapse:collapse;margin:0.5rem 0 1.5rem;
               font-family:monospace;font-size:0.83rem}}
  .cap-matrix thead th{{padding:0.6rem 0.5rem;text-align:left;
                         border-bottom:1px solid var(--border-3);
                         color:var(--text-4);font-weight:normal;
                         font-size:0.72rem;letter-spacing:0.08em;
                         text-transform:uppercase}}
  .cap-matrix .cap-col-anon{{width:23%;color:var(--text-3)}}
  .cap-matrix .cap-col-member{{width:23%;color:var(--accent)}}
  .cap-matrix .cap-col-lab{{width:23%;color:var(--text-4)}}
  .cap-matrix tbody td{{padding:0.55rem 0.5rem;
                         border-bottom:1px solid var(--panel);
                         color:var(--text-3);line-height:1.5}}
  .cap-matrix tbody tr td:first-child{{color:var(--text-2);
                                         font-family:system-ui,sans-serif;
                                         font-size:0.88rem;width:31%}}
  .cap-matrix .cap-yes{{color:var(--accent);font-weight:bold}}
  .cap-matrix .cap-no{{color:var(--text-5)}}
  .cap-matrix .cap-partial{{color:var(--warn);font-size:0.78rem}}
  .cap-cta{{display:flex;gap:0.75rem;flex-wrap:wrap;margin-top:1.5rem;
            justify-content:center}}
"""

_DEMO_HTML = f"""
<div class="page-header">
  <div id="step-nav" class="step-nav">
    <span class="dot active" id="dot-0"></span>
    <span class="dot" id="dot-1"></span>
    <span class="dot" id="dot-2"></span>
    <span class="dot" id="dot-3"></span>
    <span class="dot opt" id="dot-4" data-opt="1"></span>
    <span class="dot opt" id="dot-5" data-opt="1"></span>
    <span class="dot opt" id="dot-6" data-opt="1"></span>
    <span class="dot" id="dot-7"></span>
    <span class="dot" id="dot-8"></span>
    <span class="label active" id="nav-label">Welcome</span>
    <span id="step-counter" style="color:var(--text-5);font-size:0.7rem;margin-left:0.25rem">Step 1 of 6</span>
  </div>
</div>

<!-- Step 0: Welcome -->
<div class="step active" id="step-0">
  <h1>OWL</h1>
  <p style="color:var(--text-3);font-size:0.85rem;margin-bottom:1.5rem">
    Greening of Streaming · Live energy measurement · GoS1</p>

  {{TIER_INDICATOR}}

  <p style="color:var(--text-2);line-height:1.8;max-width:560px">
    OWL measures the real energy cost of video transcoding and AI inference —
    using a calibrated smart plug, not estimates. Every number on this page
    comes from a live measurement on GoS1, a server in our lab in France.
  </p>

  <p style="color:var(--text-2);line-height:1.8;max-width:560px">
    OWL is built by <strong>Greening of Streaming</strong> &mdash; a global,
    member-driven non-profit working to reduce the energy footprint of streaming.
  </p>

  <details>
    <summary>About Greening of Streaming</summary>
    <p><strong>Mission.</strong> Reduce the environmental impact of streaming
    through energy-efficient solutions and industry collaboration.</p>
    <p><strong>No greenwashing.</strong> Every public claim is backed by
    verifiable data and real-world implementation.</p>
    <p>A network of member organisations collaborating through Labs &mdash;
    working groups that produce research, build measurement tools like OWL, and
    publish recommendations. Membership is open across the streaming ecosystem.</p>
  </details>

  <p style="margin-top:0.5rem;font-size:0.9rem">
    <a href="{GOS_URL}" target="_blank" rel="noopener"
       style="color:var(--accent);text-decoration:none;border-bottom:1px solid var(--border-2);padding-bottom:1px">
      Learn more at greeningofstreaming.org &rarr;</a>
  </p>

  <div class="big-metric" id="live-watts">— W</div>
  <div class="big-label">GoS1 current power draw · {{METER_NAME}} · device layer only</div>

  <details>
    <summary>What's being measured?</summary>
    <p>GoS1 is an AMD Ryzen 9 workstation with an {{GPU_DISPLAY_NAME}} GPU.
    Power is sampled via {{METER_NAME}} at {{METER_CADENCE}},
    connected to the mains supply. We measure the delta between idle
    baseline and task power — not estimated TDP or nameplate figures.</p>
    <p>Scope: device layer only. Network, CDN, and CPE are explicitly excluded.
    Amortised embodied carbon and training cost are not included in LLM measurements.</p>
  </details>

  <details>
    <summary>Why does this matter?</summary>
    <p>Streaming accounts for a significant and growing share of global internet
    traffic. Codec choice, inference model size, and hardware path all affect
    real energy use — but most published figures are estimates or averages.
    OWL produces primary measurement data that operators and researchers
    can reproduce and cite.</p>
  </details>

  <p style="margin-top:1.25rem;font-size:0.85rem;color:var(--text-3)">
    <a href="/methodology" style="color:var(--accent);text-decoration:none;border-bottom:1px solid var(--border-2);padding-bottom:1px">
      &rarr; Read the full measurement methodology</a>
    <span style="color:var(--text-5);margin-left:0.5rem">protocol, confidence framework, scope statements, calibration</span>
  </p>

  <div style="margin-top:1.5rem;border:1px solid var(--border-2);padding:1rem 1.25rem;max-width:560px;font-family:monospace;font-size:0.8rem;line-height:2">
    <div style="color:var(--text-4);font-size:0.68rem;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:0.4rem">This tour &mdash; about 5 minutes</div>
    <div style="color:var(--text-2)">1 &nbsp;Video transcode &mdash; what one encode really costs</div>
    <div style="color:var(--text-2)">2 &nbsp;Energy budget &mdash; turn Wh/min into planning</div>
    <div style="color:var(--text-2)">3 &nbsp;Video enhancement &mdash; when improving video earns its watts</div>
    <div style="color:var(--text-2)">4 &nbsp;Confidence &amp; findings &mdash; how we know a number is real</div>
    <div style="color:var(--text-4)">+ &nbsp;optional detour: AI workloads (LLM &middot; image &middot; RAG)</div>
    <div style="color:var(--text-5);font-size:0.72rem;line-height:1.6;margin-top:0.4rem">Every step opens on a real stored measurement &mdash; and you can trigger fresh runs and watch them live.</div>
  </div>

  <div class="btn-row">
    <button class="btn btn-primary" onclick="goStep(1)">Start Tour →</button>
  </div>
</div>

<!-- Step 1: Video -->
<div class="step" id="step-1">
  <div class="btn-row" style="margin-bottom:1.5rem"><button class="btn btn-secondary" onclick="goStep(0)">&lsaquo; Welcome</button><button class="btn btn-primary" onclick="goStep(2)">Energy budget &rsaquo;</button></div>
  <h1>Video Transcode</h1>

  <div class="band">
    <div class="band-label">What this shows</div>
    <p style="color:var(--text-2);line-height:1.8;max-width:560px">
      Whether transcoding to the same quality target uses more energy on CPU or GPU —
      and whether the faster path is also the more efficient one.
    </p>
  </div>

  <div class="band">
    <div class="band-label">What we're doing</div>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px;margin-bottom:0.75rem">
      Encoding a 2-minute 4K clip (Meridian, Netflix Open Content, CC BY 4.0) to 1080p —
      once in software on the CPU and once as a full GPU pipeline (hardware decode +
      scale + encode via {{GPU_H265_ENC}}, or {{GPU_AV1_ENC}} on the AV1 chip).
      Same source. Same per-codec bitrate target.
      {{METER_NAME}} sampled at {{METER_CADENCE}} throughout.
    </p>
    <details>
      <summary>How this is measured</summary>
      <p>{{BASELINE_POLLS}}s idle baseline before each run. {{VIDEO_COOLDOWN_S}}s thermal cooldown between CPU and GPU.
      Energy = ΔW × duration / 3600. Confidence: each run carries a per-run confidence
      interval — 🟢 needs ≥95% confidence above idle and ≥ {{CONF_GREEN_POLLS}} task polls
      (the full story is the Confidence step, later in the tour).</p>
      <p>Source: {{DEMO_VIDEO_SOURCE_DESC}}.
      The Result panel below always shows the most recent stored run.</p>
    </details>
  </div>

  <div>
    <div class="band-label">Result</div>
    <div id="video-action">
      <div id="video-btns" style="display:none">
        <!-- CR-033 — codec chips select which both-mode runs. Both chips use
             meridian_120s; preset switches between h265_both and av1_both.
             The run-button label updates to reflect the choice. -->
        <div class="btn-row" id="demo-codec-chips" style="margin-bottom:0.6rem;gap:0.4rem">
          <button type="button" class="demo-chip" id="demo-chip-h265"
                  data-codec="h265" data-codec-label="H.265"
                  onclick="selectDemoCodec('h265')"
                  style="padding:0.35rem 0.7rem;font-size:0.78rem;
                         background:var(--accent);color:var(--bg);
                         border:1px solid var(--accent);border-radius:3px;
                         font-family:inherit;cursor:pointer">
            H.265 (CPU vs GPU)
          </button>
          <button type="button" class="demo-chip" id="demo-chip-av1"
                  data-codec="av1" data-codec-label="AV1"
                  onclick="selectDemoCodec('av1')"
                  style="padding:0.35rem 0.7rem;font-size:0.78rem;
                         background:transparent;color:var(--text-3);
                         border:1px solid var(--border-3);border-radius:3px;
                         font-family:inherit;cursor:pointer">
            AV1 (CPU vs GPU)
          </button>
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" id="btn-run-video" onclick="runDemoVideo()">
            Run a standard transcode (H.265 CPU vs GPU on Meridian 2&thinsp;min · ~3&thinsp;min)</button>
        </div>
      </div>
      <div id="video-status"></div>
    </div>
    <p class="limitation">Scope: device layer only (GoS1). Network, CDN, and CPE not included.
    A faster encode does not automatically mean less energy — this measures total Wh, not rate.</p>
  </div>

  <div id="next-1" style="display:none;margin-top:2rem;padding-top:1.5rem;border-top:1px solid var(--panel)">
    <div style="margin-bottom:1.25rem;padding:0.85rem 1rem;border:1px dashed var(--border-3);
                background:var(--panel-2);font-size:0.78rem;color:var(--text-3);
                line-height:1.6;max-width:560px">
      <div style="color:var(--text-5);font-size:0.6rem;letter-spacing:0.1em;
                  text-transform:uppercase;margin-bottom:0.4rem">
        Entering beta · exploratory</div>
      That was the production-grade GoS measurement — video transcoding is what
      we report on with confidence. The next three steps cover exploratory AI
      workloads (LLM, image, RAG): less mature, signal can sit below the meter's
      floor on small tasks, and quality / faithfulness matter alongside energy.
      Stop here if you only wanted the streaming-impact story.
    </div>
    <div class="btn-row">
      <button class="btn btn-secondary" onclick="goStep(0)">← Welcome</button>
      <button class="btn btn-primary" onclick="goStep(2)">Next: Energy budget →</button>
      <button class="btn btn-secondary" onclick="resetVideoStep()">Run a fresh transcode</button>
    </div>
  </div>
</div>

<!-- Step 2: Energy budget -->
<div class="step" id="step-2">
  <div class="btn-row" style="margin-bottom:1.5rem"><button class="btn btn-secondary" onclick="goStep(1)">&lsaquo; Video</button><button class="btn btn-primary" onclick="goStep(3)">Video enhancement &rsaquo;</button></div>
  <h1>Energy Budget Planner</h1>
  <div class="band">
    <div class="band-label">What this shows</div>
    <p style="color:var(--text-2);line-height:1.8;max-width:560px">
      The same measurements, flipped into the operator&rsquo;s question: given an energy
      budget and a quality target, how much video can you actually ship? Pick a VMAF
      target (92 by default &mdash; the figure transcoding farms cite) and OWL shows how
      many hours each codec and hardware path buys you, from real measured curves.
    </p>
  </div>
  <div class="band">
    <div class="band-label">Why it matters</div>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px">
      It turns Wh-per-minute into planning &mdash; the H.264 / HEVC / AV1 and CPU-vs-GPU
      decision, sized to a budget, measured rather than estimated.
    </p>
  </div>
  {{BUDGET_TEASER}}
  <div class="btn-row" style="margin:1rem 0">
    <a class="btn btn-primary" href="/video/budget" target="_blank" rel="noopener" style="text-decoration:none;display:inline-block;line-height:1">Open the energy budget planner &#8599;</a>
  </div>
  <div class="btn-row" style="margin-top:2rem;padding-top:1.5rem;border-top:1px solid var(--panel)"><button class="btn btn-secondary" onclick="goStep(1)">&lsaquo; Video</button><button class="btn btn-primary" onclick="goStep(3)">Next: Video enhancement &rsaquo;</button></div>
</div>

<!-- Step 3: Video enhancement -->
<div class="step" id="step-3">
  <div class="btn-row" style="margin-bottom:1.5rem"><button class="btn btn-secondary" onclick="goStep(2)">&lsaquo; Energy budget</button><button class="btn btn-primary" onclick="goStep(7)">Confidence &rsaquo;</button></div>
  <h1>ML Video Enhancement <span style="font-size:0.6rem;color:var(--text-5);border:1px solid var(--border-3);padding:0.05rem 0.3rem;border-radius:2px;vertical-align:middle">BETA</span></h1>
  <div class="band">
    <div class="band-label">What this shows</div>
    <p style="color:var(--text-2);line-height:1.8;max-width:560px">
      Step 1 spent energy to <em>shrink</em> video. This flips the question: what does
      it cost to make video <em>better</em>? A machine-learning enhancer on the lab GPU
      takes a rough, low-resolution clip and denoises and upscales it &mdash; and OWL
      meters the watt-hours at the wall and scores the quality before and after, like
      every other workload on the bench.
    </p>
    <p style="color:var(--text-2);line-height:1.8;max-width:560px">
      The showcase below: real 2005 phone footage &mdash; 544&times;408, heavily
      compressed &mdash; machine-upscaled to 4K for a couple of watt-hours. Watch the
      two previews, then read what that difference cost in the card underneath.
    </p>
  </div>
  <div id="enhance-preview" style="display:none;margin:1rem 0">
    <div style="display:flex;gap:1rem;flex-wrap:wrap">
      <figure style="flex:1;min-width:260px;margin:0">
        <figcaption style="color:var(--text-3);font-family:monospace;font-size:0.72rem;margin-bottom:0.35rem">SOURCE &mdash; 2005 phone clip as a player would show it</figcaption>
        <video id="enhance-vid-before" muted loop playsinline preload="metadata"
               onclick="wlToggleEnhancePreview()"
               style="width:100%;border:1px solid var(--border-2);display:block;background:#000;cursor:pointer"></video>
      </figure>
      <figure style="flex:1;min-width:260px;margin:0">
        <figcaption style="color:var(--accent);font-family:monospace;font-size:0.72rem;margin-bottom:0.35rem">ENHANCED &mdash; ML denoise + upscale to 4K, same region</figcaption>
        <video id="enhance-vid-after" muted loop playsinline preload="metadata"
               onclick="wlToggleEnhancePreview()"
               style="width:100%;border:1px solid var(--border-2);display:block;background:#000;cursor:pointer"></video>
      </figure>
    </div>
    <div class="btn-row" style="margin-top:0.6rem">
      <button id="enhance-playpause" class="btn btn-secondary" onclick="wlToggleEnhancePreview()">&#9654; Play both</button>
    </div>
    <p style="color:var(--text-5);font-size:0.7rem;line-height:1.6;margin-top:0.4rem;max-width:560px">
      Both previews show the <em>same magnified region of the frame</em>, re-encoded
      for the web: the left is the source scaled up conventionally (no ML), the right
      is the ML output. The quality scores below are measured on the full originals.
    </p>
  </div>
  <div id="enhance-status"></div>
  <p style="color:var(--text-4);font-size:0.75rem;max-width:560px;line-height:1.6">
    How to read the card: the quality line is a no-reference score of the source
    vs the enhanced output (higher is better) &mdash; the measured quality change the
    watt-hours bought. Energy and duration cover the whole enhancement run,
    metered at the wall like every OWL measurement.
  </p>
  <div class="band">
    <div class="band-label">Why it matters</div>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px">
      Operators handed an imperfect feed can weigh enhancing it against its real energy
      cost &mdash; and see where enhancement earns its watts and where it just burns them.
    </p>
  </div>
  <div style="border:1px dashed var(--border-3);padding:0.85rem 1rem;max-width:560px;margin:1rem 0">
    <p style="color:var(--text-3);font-size:0.78rem;line-height:1.7;margin:0">
      Running an enhancement yourself is a <strong>member feature</strong> &mdash; each run
      holds the lab GPU for real minutes, and an open free enhancer would turn the
      measurement bench into a video-improvement service.
      <a href="/auth/sign-in?next=/enhance-run" style="color:var(--accent);text-decoration:none;border-bottom:1px solid var(--border-2);padding-bottom:1px">Members: sign in and open ML Video Enhancement &rarr;</a>
    </p>
  </div>
  <div class="btn-row" style="margin-top:2rem;padding-top:1.5rem;border-top:1px solid var(--panel)">
    <button class="btn btn-secondary" onclick="goStep(2)">&lsaquo; Energy budget</button>
    <button class="btn btn-primary" onclick="goStep(7)">Next: How we flag confidence &rsaquo;</button>
    <button class="btn btn-secondary" onclick="goStep(4)" style="border:1px dashed var(--border-3)"><span style="font-size:0.6rem;letter-spacing:0.06em;color:var(--text-5);text-transform:uppercase;margin-right:0.4rem">Optional detour</span>Measure AI workloads too (LLM &middot; Image &middot; RAG &mdash; 3 steps) &rsaquo;</button>
  </div>
</div>

<!-- Step 4: LLM -->
<div class="step" id="step-4">
  <div style="color:var(--text-4);font-size:0.72rem;margin-bottom:1rem;padding:0.4rem 0.6rem;border:1px dashed var(--border-3);display:inline-block">
    Optional AI detour &middot; <a href="javascript:goStep(7)" style="color:var(--accent);text-decoration:none">jump to Confidence anytime &rarr;</a>
  </div>
  <div class="btn-row" style="margin-bottom:1.5rem"><button class="btn btn-secondary" onclick="goStep(3)">&lsaquo; Video enhancement</button><button class="btn btn-primary" onclick="goStep(5)">Image generation &rsaquo;</button></div>
  <h1>LLM Inference {{BETA_CHIP}}</h1>

  <div class="band">
    <div class="band-label">What this shows</div>
    <p style="color:var(--text-2);line-height:1.8;max-width:560px">
      How much energy each generated token costs — and how model size
      translates into energy use per unit of output.
    </p>
  </div>

  <div class="band">
    <div class="band-label">What we're doing</div>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px;margin-bottom:0.75rem">
      Running a fixed prompt (T3, long generation — a technical briefing on network
      energy attribution) through {{DEMO_LLM_MODEL_LABEL}} cold: model unloaded before
      baseline so we capture the true first-request cost.
      GPU inference via Ollama ({{GPU_RUNTIME}}).
    </p>
    <details>
      <summary>How this is measured</summary>
      <p>Model unloaded from VRAM. 3s settle. {{BASELINE_POLLS}}s idle baseline. Single inference run.
      {{METER_NAME}} at {{METER_CADENCE}}. Primary metric: mWh per output token.</p>
      <p>Model: {{DEMO_LLM_MODEL_LABEL}} ({{DEMO_LLM_MODEL_SIZE}}).
      The Result panel below always shows the most recent stored run.</p>
    </details>
    <details>
      <summary>Why mWh per token?</summary>
      <p>Token count varies between models and prompts, so raw Wh figures aren't
      comparable. Energy per token puts a 1-billion-parameter model and a
      20-billion-parameter model on the same axis, so model size can be traded
      off against energy directly. The Findings step carries the citable numbers.</p>
    </details>
  </div>

  <div>
    <div class="band-label">Result</div>
    <div id="llm-action">
      <div class="btn-row" id="llm-btns" style="display:none">
        <button class="btn btn-primary" id="btn-run-llm" onclick="runDemoLLM()">
          Run a standard LLM generation ({{DEMO_LLM_MODEL_LABEL}} · cold · T3 prompt · ~3&thinsp;min)</button>
      </div>
      <div id="llm-status"></div>
    </div>
    <p class="limitation">Scope: device layer only (GoS1). No amortised training cost included.
    mWh/token measures inference energy only — not the energy cost of training the model.</p>
  </div>

  <div id="next-4" style="display:none;margin-top:2rem;padding-top:1.5rem;border-top:1px solid var(--panel)">
    <div class="btn-row">
      <button class="btn btn-secondary" onclick="goStep(3)">&lsaquo; Video enhancement</button>
      <button class="btn btn-primary" onclick="goStep(5)">Next: Image generation →</button>
      <button class="btn btn-secondary" onclick="resetLLMStep()">Run a fresh LLM generation</button>
    </div>
  </div>
</div>

<!-- Step 5: Image generation -->
<div class="step" id="step-5">
  <div class="btn-row" style="margin-bottom:1.5rem"><button class="btn btn-secondary" onclick="goStep(4)">&lsaquo; LLM inference</button><button class="btn btn-primary" onclick="goStep(6)">RAG &rsaquo;</button></div>
  <h1>Image Generation {{BETA_CHIP}}</h1>

  <div class="band">
    <div class="band-label">What this shows</div>
    <p style="color:var(--text-2);line-height:1.8;max-width:560px">
      How much energy one AI-generated image costs — measured end to end on
      real hardware, not estimated from TDP or cloud benchmarks.
    </p>
  </div>

  <div class="band">
    <div class="band-label">What we're doing</div>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px;margin-bottom:0.75rem">
      Running SD-Turbo (stabilityai/sd-turbo, {{DEMO_IMAGE_DETAIL}}) with a
      randomly modified prompt — the colour modifier changes each run to prove
      the image is generated live, not replayed from cache.
    </p>
    <details>
      <summary>How this is measured</summary>
      <p>{{BASELINE_POLLS}}s idle baseline. CPU diffusion run. {{METER_NAME}} at {{METER_CADENCE}}.
      Metric: Wh per image = ΔW × generation_time / 3600.</p>
      <p>The Result panel below always shows the most recent stored run.</p>
    </details>
  </div>

  <div>
    <div class="band-label">Result</div>
    <div id="image-btns" class="btn-row" style="display:none">
      <button class="btn btn-primary" onclick="runDemoImage()">Run a standard image generation (SD-Turbo · 512&times;512 · ~30&thinsp;s)</button>
    </div>
    <div id="image-status"></div>
    <p class="limitation">Scope: device layer only (GoS1). Network and storage excluded.
    This measures one image on one machine — not the energy cost of a hosted API call.</p>
  </div>

  <div id="next-5" style="display:none;margin-top:2rem;padding-top:1.5rem;border-top:1px solid var(--panel)">
    <div class="btn-row">
      <button class="btn btn-secondary" onclick="goStep(4)">&lsaquo; LLM</button>
      <button class="btn btn-primary" onclick="goStep(6)">Next: RAG →</button>
      <button class="btn btn-secondary" onclick="resetImageStep()">Run a fresh image generation</button>
    </div>
  </div>
</div>

<!-- Step 6: RAG -->
<div class="step" id="step-6">
  <div class="btn-row" style="margin-bottom:1.5rem"><button class="btn btn-secondary" onclick="goStep(5)">&lsaquo; Image generation</button><button class="btn btn-primary" onclick="goStep(7)">Confidence &rsaquo;</button></div>
  <h1>RAG Energy Cost {{BETA_CHIP}}</h1>

  <div class="band">
    <div class="band-label">What this shows</div>
    <p style="color:var(--text-2);line-height:1.8;max-width:560px">
      Whether retrieval-augmented generation (RAG) — searching a local corpus
      before answering — costs meaningfully more energy than plain inference,
      and see the difference in context size the model must process.
    </p>
  </div>

  <div class="band">
    <div class="band-label">What we're doing</div>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px;margin-bottom:0.75rem">
      Running three modes back-to-back on {{DEMO_RAG_MODEL_LABEL}}: baseline (no retrieval),
      RAG (small corpus), and RAG Large (with re-ranking).
      Same question, same model, same hardware — only the retrieval pipeline changes.
    </p>
    <details>
      <summary>How this is measured</summary>
      <p>Each mode: {{BASELINE_POLLS}}s idle baseline, inference with {{METER_NAME}} at {{METER_CADENCE}}.
      Metric: mWh per output token. ChromaDB embeddings via sentence-transformers.
      Corpus: academic papers on streaming energy.</p>
    </details>
  </div>

  <div>
    <div class="band-label">Result</div>
    <div id="rag-btns" class="btn-row" style="display:none">
      <button class="btn btn-primary" onclick="runDemoRAG()">Run a standard RAG energy test ({{DEMO_RAG_MODEL_LABEL}} · 3-mode · ~10&thinsp;min)</button>
    </div>
    <div id="rag-status"></div>
    <p class="limitation">Scope: device layer only (GoS1). Network excluded.
    RAG retrieval adds overhead but the dominant cost remains token generation.</p>
  </div>

  <div id="next-6" style="display:none;margin-top:2rem;padding-top:1.5rem;border-top:1px solid var(--panel)">
    <div class="btn-row">
      <button class="btn btn-secondary" onclick="goStep(5)">&lsaquo; Image</button>
      <button class="btn btn-primary" onclick="goStep(7)">Next: How we flag confidence →</button>
      <button class="btn btn-secondary" onclick="resetRAGStep()">Run a fresh RAG energy test</button>
    </div>
  </div>
</div>

<!-- Step 7: Confidence -->
<div class="step" id="step-7">
  <div class="btn-row" style="margin-bottom:1.5rem"><button class="btn btn-secondary conf-back" onclick="goStep(confBack)">&lsaquo; Video enhancement</button><button class="btn btn-primary" onclick="goStep(8)">Findings &rsaquo;</button></div>
  <h1>How We Flag Confidence</h1>

  <div class="band">
    <div class="band-label">The problem</div>
    <p style="color:var(--text-2);line-height:1.8;max-width:560px">
      Not every measurement we take is equally trustworthy.
      System noise — {{METER_NAME}} quantisation, OS jitter, Wi-Fi polling variance — is real.
      A task that adds a small delta above baseline might be signal or artefact.
      We need a principled way to say which.
    </p>
  </div>

  <div class="band">
    <div class="band-label">The system</div>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px;margin-bottom:1rem">
      Every result carries a traffic light. As of CR-028 Phase 2 it's a <em>per-run
      confidence interval</em> — "can this run be told apart from idle?" — not a fixed
      watt rule.
      <code style="font-family:monospace;font-size:0.82rem;color:var(--text-3)">confidence = Φ(ΔW / SE), SE from this run's noise + the calibrated idle floor</code>
    </p>
    <div style="display:flex;flex-direction:column;gap:0.75rem;max-width:480px">
      <div style="border-left:2px solid #1a3a1a;padding:0.6rem 1rem">
        <div style="font-family:monospace;font-size:0.9rem">🟢 Repeatable</div>
        <div style="color:var(--text-3);font-size:0.82rem;margin-top:0.25rem">
          ≥95% confident above idle <em>and</em> ≥ {{CONF_GREEN_POLLS}} task polls. Reliable enough to cite.</div>
      </div>
      <div style="border-left:2px solid #3a3a00;padding:0.6rem 1rem">
        <div style="font-family:monospace;font-size:0.9rem">🟡 Early insight</div>
        <div style="color:var(--text-3);font-size:0.82rem;margin-top:0.25rem">
          ≥80% confident above idle <em>and</em> ≥ {{CONF_YELLOW_POLLS}} task polls. Directional, but needs a longer run
          before we'd stake a public claim on it.</div>
      </div>
      <div style="border-left:2px solid #2a0000;padding:0.6rem 1rem">
        <div style="font-family:monospace;font-size:0.9rem">🔴 Need more data</div>
        <div style="color:var(--text-3);font-size:0.82rem;margin-top:0.25rem">
          Not yet distinguishable from idle.
          We publish it anyway — but we won't cite it yet.</div>
      </div>
    </div>
  </div>

  <div class="band">
    <div class="band-label">Why a confidence interval?</div>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px;margin-bottom:0.75rem">
      Fixed thresholds (e.g. "5W = green") don't adapt to the machine's actual noise
      level. Instead we take this run's own baseline + task power samples, form a
      standard error on ΔW (worst case of the run's observed noise and the calibrated
      idle floor, plus a drift term), and turn ΔW into a one-sided confidence that the
      task draws above idle. A short run can't go green on a couple of lucky readings —
      it also needs enough task polls.
    </p>
    <p style="color:var(--text-3);line-height:1.7;max-width:560px">
      On any result page, click a 🟢 🟡 🔴 badge for a quick reminder of the formula.
    </p>
  </div>

  <div class="btn-row" style="margin-top:0.5rem">
    <button class="btn btn-secondary conf-back" onclick="goStep(confBack)">&lsaquo; Video enhancement</button>
    <button class="btn btn-primary" onclick="goStep(8)">See findings →</button>
  </div>
</div>

<!-- Step 8: Findings -->
<div class="step" id="step-8">
  <div class="btn-row" style="margin-bottom:1.5rem"><button class="btn btn-secondary" onclick="goStep(7)">&lsaquo; Confidence</button><button class="btn btn-primary" onclick="goStep(1)">&#8635; Start over</button></div>
  <h1>Findings</h1>
  <p style="color:var(--text-3);font-size:0.85rem;margin-bottom:1.5rem">
    Greening of Streaming · OWL · GoS1</p>

  <div id="summary-content">
    {{FINDINGS_PANEL}}
  </div>

  <hr class="divider">

  <!-- CR-001 capability matrix; CR-027 three-column refresh.
       Same measurement quality across all three tiers — what changes is
       who shapes the inputs. Member is the conversion target (accent
       column), Lab is shown so visitors understand the full access ladder
       and see who runs the bench. Upload caps are wired to settings.json
       via the UPLOAD_MEMBER_MB placeholder so this table never silently drifts. -->
  <h2 style="margin-top:2rem;margin-bottom:0.5rem">Want to dig deeper?</h2>
  <p style="color:var(--text-3);font-size:0.85rem;margin-bottom:1.25rem;line-height:1.6">
    OWL has three access tiers. The numbers and methodology you've just
    seen are identical for all three — what changes is who can shape the
    inputs (custom prompts, custom ffmpeg, all-codecs sweeps, your own
    corpus, full settings access).
  </p>
  <table class="cap-matrix">
    <thead>
      <tr>
        <th></th>
        <th class="cap-col-anon">Public</th>
        <th class="cap-col-member">GoS member</th>
        <th class="cap-col-lab">Lab (operator)</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Pre-baked workloads, live wall-power &amp; CO<sub>2</sub>e</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
      </tr>
      <tr>
        <td>Guided tour, methodology, recent-run history</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
      </tr>
      <tr>
        <td>Custom video upload</td>
        <td class="cap-no">—</td>
        <td class="cap-yes">≤ {{UPLOAD_MEMBER_MB}} MB</td>
        <td class="cap-yes">no cap</td>
      </tr>
      <tr>
        <td>Custom prompts &amp; custom ffmpeg commands</td>
        <td class="cap-no">—</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
      </tr>
      <tr>
        <td>All-codecs sweeps, batch / compare-modes</td>
        <td class="cap-no">—</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
      </tr>
      <tr>
        <td>RAG corpus upload (your own PDFs)</td>
        <td class="cap-no">—</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
      </tr>
      <tr>
        <td>CSV / JSON export of your runs</td>
        <td class="cap-no">—</td>
        <td class="cap-yes">✓</td>
        <td class="cap-yes">✓</td>
      </tr>
      <tr>
        <td>Edit settings, run variance calibration, full results view</td>
        <td class="cap-no">—</td>
        <td class="cap-no">—</td>
        <td class="cap-yes">✓</td>
      </tr>
    </tbody>
  </table>
  <p style="color:var(--text-5);font-size:0.72rem;margin-top:0.25rem;margin-bottom:1.25rem;
            font-family:monospace;line-height:1.5">
    Lab tier is granted automatically on the GoS1 LAN (loopback / 192.168.x).
    There's no public sign-up for Lab — it's the operator surface for the
    bench itself.
  </p>
  <div class="cap-cta">
    <a href="{JOIN_GOS_URL}" target="_blank"
       class="btn btn-primary" style="text-decoration:none;display:inline-block;line-height:1">
      Join GoS — unlock the middle column ↗</a>
    <a href="/auth/sign-in" class="btn btn-secondary"
       style="text-decoration:none;display:inline-block;line-height:1">
      Already a member? Sign in</a>
  </div>
  <p style="color:var(--text-5);font-size:0.72rem;margin-top:1rem;font-family:monospace;text-align:center">
    Same measurement quality on every tier. Members shape the inputs; everyone sees the results.
  </p>

  <hr class="divider">
  <div class="btn-row">
    <button class="btn btn-secondary" onclick="goStep(7)">&lsaquo; Confidence</button>
    <button class="btn btn-secondary" onclick="goStep(1)">↺ Start over</button>
    <a href="{GOS_URL}" target="_blank"
       class="btn btn-secondary" style="text-decoration:none;display:inline-block;line-height:1">
      greeningofstreaming.org ↗</a>
  </div>
  <p class="scope-note" style="margin-top:1.5rem">
    Scope: device layer only (GoS1). Network, CDN, CPE excluded.<br>
    LLM: no amortised training cost included.</p>
</div>

<script>
// ─── State ──────────────────────────────────────────────────────────────────
let currentStep = 0;
let videoResult = null;
let llmResult = null;
let imageResult = null;
let ragResult = null;
let enhanceResult = null;
const stepLabels = ['Welcome', 'Video Transcode', 'Energy Budget', 'Video Enhancement', 'LLM Inference', 'Image Generation', 'RAG', 'Confidence', 'Findings'];
// Honest progress: the core path is 6 stops (0,1,2,3,7,8); steps 4-6 are the
// optional AI detour with its own 3-step count — never a "4/9 → 8/9" jump.
const STEP_META = {{
  0: 'Step 1 of 6', 1: 'Step 2 of 6', 2: 'Step 3 of 6', 3: 'Step 4 of 6',
  4: 'AI detour · 1 of 3', 5: 'AI detour · 2 of 3', 6: 'AI detour · 3 of 3',
  7: 'Step 5 of 6', 8: 'Step 6 of 6'
}};
// Confidence's back button returns to wherever the visitor came from:
// the AI detour's RAG step (6) or the core path's enhancement step (3).
let confBack = 3;
let streamTimer = null;
let imageTimer = null;

// ─── Step navigation ─────────────────────────────────────────────────────────
function goStep(n) {{
  document.querySelectorAll('.step').forEach(el => el.classList.remove('active'));
  document.getElementById('step-' + n).classList.add('active');
  for (let i = 0; i < 9; i++) {{
    const dot = document.getElementById('dot-' + i);
    const base = dot.dataset.opt ? 'dot opt' : 'dot';
    dot.className = base + (i < n ? ' done' : i === n ? ' active' : '');
  }}
  const lbl = document.getElementById('nav-label');
  lbl.textContent = stepLabels[n];
  lbl.className = 'label active';
  document.getElementById('step-counter').textContent = STEP_META[n] || '';
  if (n === 7) {{
    confBack = (currentStep === 6) ? 6 : 3;
    document.querySelectorAll('.conf-back').forEach(b => {{
      b.textContent = (confBack === 6) ? '‹ RAG' : '‹ Video enhancement';
    }});
  }}
  currentStep = n;
  window.scrollTo(0, 0);
  // Tour navigation is NEVER gated on a pre-loaded result rendering. Reveal
  // the measurement step's Next button on entry so the visitor can always
  // advance — even when /demo/last/* returns a shape the single-run card
  // renderer doesn't recognise (a compare/RAG record), which previously left
  // renderLLMResult / renderDemoImageResult bailing out before revealNext and
  // trapped the tour on the LLM and Image steps. The pre-load below is
  // decorative: it populates the card but must not be able to block the tour.
  revealNext(n);
  if (n === 1 && !videoResult) loadVideoStep();
  if (n === 3 && !enhanceResult) loadEnhanceStep();
  if (n === 4 && !llmResult) loadLLMStep();
  if (n === 5 && !imageResult) loadImageStep();
  if (n === 6 && !ragResult) loadRAGStep();
  if (n === 8) buildSummary();
}}

function revealNext(n) {{
  const el = document.getElementById('next-' + n);
  if (el) el.style.display = 'block';
}}

// Deep-linkable steps — the public nav's Enhancement item sends anonymous
// visitors to /demo#enhance (the showcase) instead of the members-only
// /enhance-run gate. hashchange handles same-page nav clicks.
const HASH_STEPS = {{video: 1, budget: 2, enhance: 3, confidence: 7, findings: 8}};
function goHashStep() {{
  const n = HASH_STEPS[location.hash.replace('#', '')];
  if (n !== undefined) goStep(n);
}}
window.addEventListener('hashchange', goHashStep);
goHashStep();

function loadVideoStep() {{
  document.getElementById('video-status').innerHTML = '<p class="progress-note" style="color:var(--text-3)">Loading last result…</p>';
  showPrevVideo();
}}
function loadLLMStep() {{
  document.getElementById('llm-status').innerHTML = '<p class="progress-note" style="color:var(--text-3)">Loading last result…</p>';
  showPrevLLM();
}}
function loadImageStep() {{
  document.getElementById('image-status').innerHTML = '<p class="progress-note" style="color:var(--text-3)">Loading last result…</p>';
  showPrevImage();
}}
function loadRAGStep() {{
  document.getElementById('rag-status').innerHTML = '<p class="progress-note" style="color:var(--text-3)">Loading last result…</p>';
  showPrevRAG();
}}
function loadEnhanceStep() {{
  document.getElementById('enhance-status').innerHTML = '<p class="progress-note" style="color:var(--text-3)">Loading showcase run…</p>';
  showPrevEnhance();
  loadEnhancePreviews();
}}

// Before/after previews for the pinned showcase (derived web-safe clips —
// bin/make-demo-enhance-previews). Decorative and fail-soft: a 404 leaves
// the block hidden and the numeric card carries the step alone.
async function loadEnhancePreviews() {{
  try {{
    // Probe with a plain GET on the small poster (HEAD used to 405 on
    // FastAPI @get routes — the block silently never revealed on phones).
    const probe = await fetch('/demo/enhance-preview/after.jpg');
    if (!probe.ok) return;
    const before = document.getElementById('enhance-vid-before');
    const after = document.getElementById('enhance-vid-after');
    before.poster = '/demo/enhance-preview/before.jpg';
    after.poster = '/demo/enhance-preview/after.jpg';
    before.src = '/demo/enhance-preview/before.mp4';
    after.src = '/demo/enhance-preview/after.mp4';
    document.getElementById('enhance-preview').style.display = 'block';
  }} catch(e) {{}}
}}

// One control for BOTH clips (they start paused on their posters): re-sync
// on every toggle so the comparison never drifts apart across loops. Both
// files carry the clip's original audio but only 'before' is unmuted —
// two synced tracks would echo. Unmuting inside the click handler is a
// user gesture, so mobile browsers allow it.
function wlToggleEnhancePreview() {{
  const before = document.getElementById('enhance-vid-before');
  const after = document.getElementById('enhance-vid-after');
  const btn = document.getElementById('enhance-playpause');
  if (before.paused) {{
    before.muted = false;
    after.currentTime = before.currentTime;
    before.play(); after.play();
    btn.innerHTML = '&#10074;&#10074; Pause both';
  }} else {{
    before.pause(); after.pause();
    after.currentTime = before.currentTime;
    btn.innerHTML = '&#9654; Play both';
  }}
}}

// ─── Video enhancement (step 3) ──────────────────────────────────────────────
// Pinned showcase only — /demo/last/enhance serves the operator-pinned
// record or 404s (member uploads are private; there is no latest-fallback).
// Decorative like every pre-load: the step's nav buttons are static markup,
// so a missing pin can never trap the tour.
async function showPrevEnhance() {{
  const el = document.getElementById('enhance-status');
  try {{
    const resp = await fetch('/demo/last/enhance');
    if (!resp.ok) {{
      el.innerHTML = '<p class="progress-note" style="color:var(--text-3)">No showcase run pinned yet — the description below is the workload.</p>';
      return;
    }}
    const full = await resp.json();
    enhanceResult = full;
    el.innerHTML = wlRenderEnhanceCard({{result: full, isPrev: true, savedAt: full.saved_at}});
  }} catch(e) {{
    el.innerHTML = '<p class="progress-note" style="color:var(--text-3)">Showcase run unavailable.</p>';
  }}
}}

// ─── Live power ───────────────────────────────────────────────────────────────
async function refreshPower() {{
  try {{
    const resp = await fetch('/power');
    const data = await resp.json();
    document.getElementById('live-watts').textContent = data.watts.toFixed(1) + ' W';
  }} catch(e) {{}}
}}
refreshPower();
setInterval(refreshPower, 10000);

// ─── Helpers ─────────────────────────────────────────────────────────────────
function timeAgo(isoStr) {{
  if (!isoStr) return '';
  const diff = (Date.now() - new Date(isoStr)) / 1000;
  if (diff < 120) return 'just now';
  if (diff < 3600) return Math.floor(diff/60) + ' min ago';
  if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
  return Math.floor(diff/86400) + 'd ago';
}}

function fmt(v, dec=2) {{ return v != null ? Number(v).toFixed(dec) : '—'; }}

// ─── Previous run ─────────────────────────────────────────────────────────────
// CR-026 carve-out: /demo loads the latest result regardless of visitor
// via the dedicated /demo/last/{type} endpoint. Without this carve-out,
// Anonymous visitors land on an empty guided tour because their session
// has never produced a run.
async function showPrevVideo() {{
  document.getElementById('video-btns').style.display = 'none';
  try {{
    const resp = await fetch('/demo/last/video');
    if (resp.status === 404) {{
      document.getElementById('video-status').innerHTML =
        '<p class="progress-note" style="color:var(--text-3)">No previous run on file — run one below, or skip ahead.</p>';
      document.getElementById('video-btns').style.display = 'flex';
      revealNext(1);
      return;
    }}
    const full = await resp.json();
    videoResult = full;
    renderVideoResult(full, full.saved_at, true);
  }} catch(e) {{
    document.getElementById('video-btns').style.display = 'flex';
    document.getElementById('video-status').innerHTML =
      '<p class="progress-note" style="color:var(--err)">Error: ' + e + '</p>';
    revealNext(1);
  }}
}}

async function showPrevLLM() {{
  document.getElementById('llm-btns').style.display = 'none';
  try {{
    // RAG runs persist under results/llm/ too; exclude them server-side
    // by listing and filtering. The /demo/last/{type} endpoint returns
    // the first run that doesn't have task starting with "RAG".
    const resp = await fetch('/demo/last/llm');
    if (resp.status === 404) {{
      document.getElementById('llm-status').innerHTML =
        '<p class="progress-note" style="color:var(--text-3)">No previous run on file — run one below, or skip ahead.</p>';
      document.getElementById('llm-btns').style.display = 'flex';
      revealNext(4);
      return;
    }}
    const full = await resp.json();
    if ((full.task || '').startsWith('RAG')) {{
      // Most recent llm/ entry is a RAG run — fall back to "no run".
      document.getElementById('llm-status').innerHTML =
        '<p class="progress-note" style="color:var(--text-3)">No previous LLM run on file — run one below, or skip ahead.</p>';
      document.getElementById('llm-btns').style.display = 'flex';
      revealNext(4);
      return;
    }}
    llmResult = full;
    renderLLMResult(full, full.saved_at, true);
  }} catch(e) {{
    document.getElementById('llm-btns').style.display = 'flex';
    document.getElementById('llm-status').innerHTML =
      '<p class="progress-note" style="color:var(--err)">Error: ' + e + '</p>';
    revealNext(4);
  }}
}}


// ─── Run new video measurement ────────────────────────────────────────────────
//
// Predetermined demo job: H.265 CPU vs GPU on the 2-minute Meridian sample.
// Bounded (~2-3 min wall time including baselines + cooldowns), demonstrates
// the GPU advantage cleanly, and lets the visitor get to the result card
// while the demo session is still fresh in their head. The full-Meridian +
// both-codecs run that lived here previously was a 10-15 minute commitment,
// which broke the guided-tour flow on the public surface. CR-033 captures
// follow-up: offer a small set of curated demo jobs (e.g. H.265 CPU vs GPU,
// AV1 CPU vs GPU) for visitors who want to compare codec families.
// CR-033 — codec chip state for the demo step 1 video block. Default is
// H.265 (matches the canonical streaming workload + current expectations).
// AV1 is the alternate; both run on meridian_120s with the same shape.
let selectedDemoCodec = 'h265';

function selectDemoCodec(codec) {{
  selectedDemoCodec = codec;
  document.querySelectorAll('.demo-chip').forEach(el => {{
    const on = el.dataset.codec === codec;
    el.style.background = on ? 'var(--accent)' : 'transparent';
    el.style.color      = on ? 'var(--bg)'     : 'var(--text-3)';
    el.style.borderColor = on ? 'var(--accent)' : 'var(--border-3)';
  }});
  const btn = document.getElementById('btn-run-video');
  if (btn) {{
    const label = codec === 'av1' ? 'AV1' : 'H.265';
    btn.innerHTML = 'Run a standard transcode (' + label
      + ' CPU vs GPU on Meridian 2&thinsp;min · ~3&thinsp;min)';
  }}
}}

async function runDemoVideo() {{
  document.getElementById('video-btns').style.display = 'none';
  try {{
    // Show the progress widget immediately rather than a stale "Starting…"
    // line — pollVideo's first response is up to 5s away, so the empty
    // shell tells the visitor "yes, something is happening" right away.
    // Inside the try so that if wlRenderProgress (or any prerequisite
    // global) is undefined, the failure surfaces via showVideoError
    // instead of silently leaving the button hidden + page blank.
    wlRenderProgress({{
      target: 'video-status',
      header: 'Submitting video job…',
      stagesHtml: wlStageList(WL_VIDEO_STAGES, 0),
      elapsed: 0,
    }});
    const form = new FormData();
    form.append('source_key', '{{DEMO_VIDEO_SOURCE_KEY}}');
    form.append('preset', selectedDemoCodec === 'av1' ? 'av1_both' : 'h265_both');
    const resp = await fetch('/video/use-source', {{method:'POST', body:form}});
    const data = await resp.json();
    if (data.job_id) {{
      pollVideo(data.job_id, Date.now());
    }} else {{
      showVideoError(JSON.stringify(data));
    }}
  }} catch(e) {{ showVideoError(e); }}
}}

function showVideoError(msg) {{
  document.getElementById('video-btns').style.display = 'flex';
  document.getElementById('video-status').innerHTML =
    '<p class="progress-note" style="color:var(--err)">Error: ' + msg + '</p>';
}}

// CR-019 — /demo's poll loops use the shared wlRenderProgress widget
// (with opts.target → per-step status div) so visitors see the same
// big live wall-power readout and stage list as the main pages.
const VIDEO_STAGE_IDX = {{
  starting: 0, baseline: 0, baseline_2: 0,
  cpu_encode: 1, gpu_encode: 1,
  rest: 2,
  done: 3,
}};

function pollVideo(jobId, t0) {{
  fetch('/video/job/' + jobId).then(r=>r.json()).then(data => {{
    if (data.status === 'done') {{
      videoResult = data.result;
      renderVideoResult(data.result, new Date().toISOString(), false);
    }} else if (data.status === 'error') {{
      showVideoError(data.error);
    }} else {{
      const stage = data.stage || '';
      const idx = VIDEO_STAGE_IDX[stage] ?? 0;
      // For *_both presets the four stages cycle once for CPU then again
      // for GPU (baseline → encode → rest → baseline_2 → encode again).
      // Without an explicit side label, the visitor sees the bar "go
      // around twice" with no idea why. This banner names which side is
      // currently running, mirroring the RAG mode-of-3 banner.
      const sideLabels = {{
        baseline:    'Side 1 of 2 — CPU encode (measuring baseline)',
        cpu_encode:  'Side 1 of 2 — CPU encode',
        rest:        'Cooldown — letting thermals settle before GPU',
        baseline_2:  'Side 2 of 2 — GPU encode (measuring baseline)',
        gpu_encode:  'Side 2 of 2 — GPU encode',
      }};
      const lbl = sideLabels[stage] || '';
      const sideLine = lbl
        ? '<div style="color:var(--accent);font-size:0.82rem;margin-top:0.6rem;font-weight:bold">' + lbl + '</div>'
        : '';
      wlRenderProgress({{
        target: 'video-status',
        stagesHtml: wlStageList(WL_VIDEO_STAGES, idx),
        watts: data.watts,
        elapsed: Date.now() - t0,
        progressPct: data.progress_pct,
        etaS:        data.eta_s,
        encodeSpeed: data.encode_speed,
        extraHtml: sideLine,
        cooldownData: data,
      }});
      setTimeout(() => pollVideo(jobId, t0), 5000);
    }}
  }}).catch(() => setTimeout(() => pollVideo(jobId, t0), 5000));
}}

// ─── Run new LLM measurement ──────────────────────────────────────────────────
async function runDemoLLM() {{
  document.getElementById('llm-btns').style.display = 'none';
  try {{
    // Render the progress widget immediately so the visitor sees the
    // shell rather than a stale text line during the up-to-5s gap before
    // pollLLM's first response. Inside the try so widget-render
    // failure surfaces via showLLMError rather than silently leaving
    // the button hidden + page blank.
    wlRenderProgress({{
      target: 'llm-status',
      header: 'Submitting LLM job…',
      stagesHtml: wlStageList(WL_LLM_STAGES, 0),
      elapsed: 0,
      extraHtml: '<div class="stream-box" id="stream-box" style="margin-top:0.75rem"></div>',
    }});
    const form = new FormData();
    form.append('model_key', '{{DEMO_LLM_MODEL_KEY}}');
    form.append('task_key', 'T3');
    form.append('repeats', '1');
    form.append('warm', 'false');
    const resp = await fetch('/llm/run', {{method:'POST', body:form}});
    const data = await resp.json();
    if (data.job_id) {{
      pollLLM(data.job_id, Date.now());
    }} else {{
      showLLMError(JSON.stringify(data));
    }}
  }} catch(e) {{ showLLMError(e); }}
}}

function showLLMError(msg) {{
  document.getElementById('llm-btns').style.display = 'flex';
  document.getElementById('llm-status').innerHTML =
    '<p class="progress-note" style="color:var(--err)">Error: ' + msg + '</p>';
}}

function pollLLM(jobId, t0) {{
  fetch('/llm/job/' + jobId).then(r=>r.json()).then(data => {{
    if (data.status === 'done') {{
      if (streamTimer) {{ clearTimeout(streamTimer); streamTimer = null; }}
      llmResult = data.result;
      renderLLMResult(data.result, new Date().toISOString(), false);
    }} else if (data.status === 'error') {{
      if (streamTimer) {{ clearTimeout(streamTimer); streamTimer = null; }}
      showLLMError(data.error);
    }} else {{
      const stage = data.stage || '';
      const idx = stage === 'baseline' ? 0 : stage.startsWith('inference') ? 1 : 0;
      const partial = data.partial_response || '';
      const streamHtml = '<div class="stream-box" id="stream-box" style="margin-top:0.75rem">'
                       + partial + '</div>';
      wlRenderProgress({{
        target: 'llm-status',
        stagesHtml: wlStageList(WL_LLM_STAGES, idx),
        watts: data.watts,
        elapsed: Date.now() - t0,
        extraHtml: streamHtml,
        cooldownData: data,
      }});
      const delay = stage.startsWith('inference') ? 500 : 3000;
      streamTimer = setTimeout(() => pollLLM(jobId, t0), delay);
    }}
  }}).catch(() => {{ streamTimer = setTimeout(() => pollLLM(jobId, t0), 5000); }});
}}

// ─── Result renderers (CR-034 Phase A wrappers) ──────────────────────────────
// Cards are rendered by shared helpers in _RESULT_JS — the thin wrappers
// below only own the /demo lifecycle (button visibility + revealNext).
// Future polish items (drift note, carbon strip extensions, etc.) ship
// once and apply to all surfaces.
function renderVideoResult(r, savedAt, isPrev) {{
  document.getElementById('video-status').innerHTML =
    wlRenderVideoCard({{result: r, savedAt: savedAt, isPrev: isPrev}});
  document.getElementById('video-btns').style.display = 'none';
  revealNext(1);
}}

function renderLLMResult(r, savedAt, isPrev) {{
  const html = wlRenderLLMCard({{result: r, savedAt: savedAt, isPrev: isPrev}});
  // Shared helper guards on missing energy with a "format not recognised"
  // message; preserve the original behaviour of re-showing run buttons in
  // that case so visitors can retry from the buttons row rather than a
  // dead card.
  if (!r.energy && !(r.runs && r.runs.length) && !r.summary && r.mode !== 'both') {{
    document.getElementById('llm-btns').style.display = 'flex';
    document.getElementById('llm-status').innerHTML = html;
    revealNext(4);  // unrecognised shape ≠ trapped tour: still let them advance
    return;
  }}
  document.getElementById('llm-status').innerHTML = html;
  document.getElementById('llm-btns').style.display = 'none';
  revealNext(4);
}}

function resetVideoStep() {{
  videoResult = null;
  document.getElementById('video-btns').style.display = 'flex';
  document.getElementById('video-status').innerHTML = '';
  document.getElementById('next-1').style.display = 'none';
}}
function resetLLMStep() {{
  llmResult = null;
  document.getElementById('llm-btns').style.display = 'flex';
  document.getElementById('llm-status').innerHTML = '';
  document.getElementById('next-4').style.display = 'none';
}}
function resetImageStep() {{
  imageResult = null;
  document.getElementById('image-btns').style.display = 'flex';
  document.getElementById('image-status').innerHTML = '';
  document.getElementById('next-5').style.display = 'none';
}}
function resetRAGStep() {{
  ragResult = null;
  document.getElementById('rag-btns').style.display = 'flex';
  document.getElementById('rag-status').innerHTML = '';
  document.getElementById('next-6').style.display = 'none';
}}

// ─── RAG ─────────────────────────────────────────────────────────────────────
async function showPrevRAG() {{
  document.getElementById('rag-btns').style.display = 'none';
  try {{
    // Pin-first pseudo-type: /demo/last/rag maps to the results/llm dir
    // filtered on mode=rag_compare (the old task_eq text filter stopped
    // matching once newer records persisted task=null — the step sat
    // empty for weeks). Same /demo carve-out endpoint as the other steps.
    const resp = await fetch('/demo/last/rag');
    if (resp.status === 404) {{
      document.getElementById('rag-status').innerHTML =
        '<p class="progress-note" style="color:var(--text-3)">No previous 3-mode RAG comparison on file — run one below, or skip ahead.</p>';
      document.getElementById('rag-btns').style.display = 'flex';
      revealNext(6);
      return;
    }}
    const full = await resp.json();
    ragResult = full;
    renderRAGResult(full, full.saved_at, true);
  }} catch(e) {{
    document.getElementById('rag-btns').style.display = 'flex';
    document.getElementById('rag-status').innerHTML =
      '<p class="progress-note" style="color:var(--err)">Error: ' + e + '</p>';
    revealNext(6);
  }}
}}

async function runDemoRAG() {{
  document.getElementById('rag-btns').style.display = 'none';
  try {{
    wlRenderProgress({{
      target: 'rag-status',
      header: 'Submitting RAG comparison…',
      stagesHtml: wlStageList(WL_RAG_STAGES, 0),
      elapsed: 0,
    }});
    const form = new FormData();
    form.append('model_key', '{{DEMO_RAG_MODEL_KEY}}');
    // No `question` field — server uses curated.CANONICAL_RAG_QUESTION,
    // which keeps the call Anonymous-OK (CR-001 capability dispatch).
    const resp = await fetch('/rag/run-compare', {{method:'POST', body:form}});
    const data = await resp.json();
    if (data.job_id) pollDemoRAG(data.job_id, Date.now());
    else document.getElementById('rag-status').innerHTML =
      '<p class="progress-note" style="color:var(--err)">' + JSON.stringify(data) + '</p>';
  }} catch(e) {{
    document.getElementById('rag-status').innerHTML =
      '<p class="progress-note" style="color:var(--err)">Error: ' + e + '</p>';
    document.getElementById('rag-btns').style.display = 'flex';
  }}
}}

function pollDemoRAG(jobId, t0) {{
  fetch('/rag/job/' + jobId).then(r=>r.json()).then(data => {{
    if (data.stage === 'done' && data.result) {{
      ragResult = data.result;
      renderRAGResult(data.result, new Date().toISOString(), false);
    }} else if (data.error) {{
      document.getElementById('rag-status').innerHTML =
        '<p class="progress-note" style="color:var(--err)">Error: ' + data.error + '</p>';
      document.getElementById('rag-btns').style.display = 'flex';
    }} else {{
      const stage = data.stage || '';
      const idx = stage.startsWith('baseline') ? 0 : stage.startsWith('inference') ? 1 : 0;
      // Friendly mode label so visitors see "No retrieval / RAG / RAG Large"
      // rolling through, plus a "1 of 3" position indicator. The server
      // sets jobs[id].current_mode to baseline|rag|rag_large|cooldown and
      // jobs[id].mode_index to 0|1|2 (set in run_rag_compare_job).
      const modeLabels = {{
        baseline: 'Mode 1 of 3 — No retrieval (control)',
        rag: 'Mode 2 of 3 — RAG (small corpus)',
        rag_large: 'Mode 3 of 3 — RAG Large (full corpus)',
        cooldown: 'Cooldown between modes — letting thermals settle',
      }};
      const cm = data.current_mode || '';
      const lbl = modeLabels[cm] || (cm ? cm : '');
      const modeLine = lbl
        ? '<div style="color:var(--accent);font-size:0.82rem;margin-top:0.6rem;font-weight:bold">' + lbl + '</div>'
        : '';
      wlRenderProgress({{
        target: 'rag-status',
        stagesHtml: wlStageList(WL_RAG_STAGES, idx),
        watts: data.watts,
        elapsed: Date.now() - t0,
        extraHtml: modeLine,
        cooldownData: data,
      }});
      setTimeout(() => pollDemoRAG(jobId, t0), 3000);
    }}
  }}).catch(() => setTimeout(() => pollDemoRAG(jobId, t0), 5000));
}}

function renderRAGResult(r, savedAt, isPrev) {{
  document.getElementById('rag-status').innerHTML =
    wlRenderRAGCard({{result: r, savedAt: savedAt, isPrev: isPrev}});
  document.getElementById('rag-btns').style.display = 'none';
  revealNext(6);
}}

// ─── Image ────────────────────────────────────────────────────────────────────
async function runDemoImage() {{
  document.getElementById('image-btns').style.display = 'none';
  try {{
    wlRenderProgress({{
      target: 'image-status',
      header: 'Submitting image job…',
      stagesHtml: wlStageList(WL_IMAGE_STAGES, 0),
      elapsed: 0,
    }});
    // No `prompt` field — server uses curated.CANONICAL_IMAGE_PROMPT, which
    // keeps the call Anonymous-OK (CR-001 capability dispatch).
    const resp = await fetch('/image/start', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
      body: '',
    }});
    const data = await resp.json();
    if (data.error) {{
      document.getElementById('image-btns').style.display = 'flex';
      document.getElementById('image-status').innerHTML =
        '<p class="progress-note" style="color:var(--err)">' + data.error + '</p>';
      return;
    }}
    pollDemoImage(data.job_id);
  }} catch(e) {{
    document.getElementById('image-btns').style.display = 'flex';
    document.getElementById('image-status').innerHTML =
      '<p class="progress-note" style="color:var(--err)">Error: ' + e + '</p>';
  }}
}}

async function pollDemoImage(jobId) {{
  if (!pollDemoImage._t0) pollDemoImage._t0 = Date.now();
  try {{
    const r = await fetch('/image/job/' + jobId);
    const j = await r.json();
    if (j.stage === 'queued') {{
      wlRenderQueued(j.queue_position, {{target: 'image-status'}});
      imageTimer = setTimeout(() => pollDemoImage(jobId), 3000);
      return;
    }}
    if (j.stage === 'done' && j.result) {{
      imageResult = j.result;
      pollDemoImage._t0 = null;
      renderDemoImageResult(j.result);
      return;
    }}
    if (j.error) {{
      pollDemoImage._t0 = null;
      document.getElementById('image-status').innerHTML =
        '<p class="progress-note" style="color:var(--err)">Error: ' + j.error + '</p>';
      document.getElementById('image-btns').style.display = 'flex';
      return;
    }}
    const idx = j.stage === 'generating' ? 1 : 0;
    wlRenderProgress({{
      target: 'image-status',
      stagesHtml: wlStageList(WL_IMAGE_STAGES, idx),
      watts: j.watts,
      elapsed: Date.now() - pollDemoImage._t0,
      cooldownData: j,
    }});
    imageTimer = setTimeout(() => pollDemoImage(jobId), 2000);
  }} catch(e) {{
    imageTimer = setTimeout(() => pollDemoImage(jobId), 3000);
  }}
}}

async function showPrevImage() {{
  document.getElementById('image-btns').style.display = 'none';
  try {{
    const resp = await fetch('/demo/last/image');
    if (resp.status === 404) {{
      document.getElementById('image-status').innerHTML =
        '<p class="progress-note" style="color:var(--text-3)">No previous run on file — run one below, or skip ahead.</p>';
      document.getElementById('image-btns').style.display = 'flex';
      revealNext(5);
      return;
    }}
    const full = await resp.json();
    imageResult = full;
    renderDemoImageResult(full);
  }} catch(e) {{
    document.getElementById('image-btns').style.display = 'flex';
    document.getElementById('image-status').innerHTML =
      '<p class="progress-note" style="color:var(--err)">Error: ' + e + '</p>';
    revealNext(5);
  }}
}}

function renderDemoImageResult(r) {{
  // Single-run path with no energy block: re-show the buttons row so
  // visitors can retry, and let the shared helper render the
  // "format not recognised" notice.
  if (r.mode !== 'both' && !r.energy) {{
    document.getElementById('image-btns').style.display = 'flex';
    document.getElementById('image-status').innerHTML =
      wlRenderImageCard({{result: r, isPrev: false}});
    revealNext(5);  // unrecognised shape ≠ trapped tour: still let them advance
    return;
  }}
  document.getElementById('image-status').innerHTML =
    wlRenderImageCard({{result: r, isPrev: false}});
  document.getElementById('image-btns').style.display = 'none';
  revealNext(5);
}}

// ─── Summary ─────────────────────────────────────────────────────────────────
function buildSummary() {{
  // CR-058 — when the findings catalog is on, the Findings step renders
  // the catalog preview server-side and buildSummary() must NOT overwrite
  // it. Flipping settings.findings_enabled to false makes the server stop
  // setting this global, restoring the original session-echo behaviour.
  if (window.OWL_FINDINGS_CATALOG_ENABLED) return;
  const el = document.getElementById('summary-content');
  let videoRows = '', llmRows = '', imageRows = '', ragRows = '';
  try {{

  // Video — the headline. GoS raison d'être.
  try {{
    if (videoResult && videoResult.mode === 'both') {{
      const a = videoResult.analysis || {{}};
      const ce = videoResult.cpu && videoResult.cpu.energy;
      const ge = videoResult.gpu && videoResult.gpu.energy;
      videoRows += `<tr><td>CPU energy</td><td>${{fmt(ce && ce.delta_e_wh,4)}} Wh ${{a.energy_winner==='CPU'?'✓':''}}</td></tr>`;
      videoRows += `<tr><td>GPU energy</td><td>${{fmt(ge && ge.delta_e_wh,4)}} Wh ${{a.energy_winner==='GPU'?'✓':''}}</td></tr>`;
      videoRows += `<tr><td>Finding</td><td style="color:var(--text-2);font-size:0.78rem">${{a.finding || a.energy_winner + ' used less energy'}}</td></tr>`;
    }} else if (videoResult) {{
      const e = videoResult.energy || (videoResult.result && videoResult.result.energy);
      videoRows += `<tr><td>Energy</td><td>${{fmt(e && e.delta_e_wh,4)}} Wh</td></tr>`;
    }} else {{
      videoRows += `<tr><td>Video</td><td style="color:var(--text-5)">— not run yet</td></tr>`;
    }}
  }} catch(err) {{ videoRows += `<tr><td>Video</td><td style="color:var(--text-3)">error: ${{err.message}}</td></tr>`; }}

  // LLM
  try {{
    if (llmResult && llmResult.mode === 'both') {{
      const a = llmResult.analysis || {{}};
      const ce = llmResult.cpu && llmResult.cpu.energy;
      const ge = llmResult.gpu && llmResult.gpu.energy;
      llmRows += `<tr><td>Model</td><td>${{llmResult.model_label || ''}}</td></tr>`;
      llmRows += `<tr><td>CPU mWh/token</td><td>${{fmt(ce && ce.mwh_per_token,4)}} ${{a.mwh_winner==='CPU'?'✓':''}}</td></tr>`;
      llmRows += `<tr><td>GPU mWh/token</td><td>${{fmt(ge && ge.mwh_per_token,4)}} ${{a.mwh_winner==='GPU'?'✓':''}}</td></tr>`;
    }} else if (llmResult) {{
      let e = llmResult.energy;
      let inf = llmResult.inference;
      if (!e && llmResult.runs && llmResult.runs.length) {{
        e = llmResult.runs[llmResult.runs.length-1].energy;
        inf = llmResult.runs[llmResult.runs.length-1].inference;
      }}
      if (!e && llmResult.summary) {{
        e = {{ mwh_per_token: llmResult.summary.mwh_per_token_mean }};
        inf = {{ tokens_per_sec: llmResult.summary.tokens_per_sec_mean }};
      }}
      llmRows += `<tr><td>Model</td><td>${{llmResult.model_label || ''}}</td></tr>`;
      llmRows += `<tr><td>Energy / token</td><td>${{fmt(e && e.mwh_per_token,4)}} mWh/token</td></tr>`;
      llmRows += `<tr><td>Speed</td><td>${{fmt(inf && inf.tokens_per_sec,1)}} tok/s</td></tr>`;
    }} else {{
      llmRows += `<tr><td>LLM</td><td style="color:var(--text-5)">— not run yet</td></tr>`;
    }}
  }} catch(err) {{ llmRows += `<tr><td>LLM</td><td style="color:var(--text-3)">error: ${{err.message}}</td></tr>`; }}

  // Image
  try {{
    if (imageResult && imageResult.mode === 'both') {{
      const a = imageResult.analysis || {{}};
      const ce = imageResult.cpu && imageResult.cpu.energy;
      const ge = imageResult.gpu && imageResult.gpu.energy;
      const cg = imageResult.cpu && imageResult.cpu.generation;
      const gg = imageResult.gpu && imageResult.gpu.generation;
      imageRows += `<tr><td>CPU Wh/image</td><td>${{fmt(ce && (ce.wh_per_image||ce.delta_e_wh),4)}} Wh ${{a.energy_winner==='cpu'?'✓':''}}</td></tr>`;
      imageRows += `<tr><td>GPU Wh/image</td><td>${{fmt(ge && (ge.wh_per_image||ge.delta_e_wh),4)}} Wh ${{a.energy_winner==='gpu'?'✓':''}}</td></tr>`;
      imageRows += `<tr><td>Time CPU/GPU</td><td>${{fmt(cg && cg.gen_s,1)}}s / ${{fmt(gg && (gg.gen_s_per_image||gg.gen_s),1)}}s</td></tr>`;
    }} else if (imageResult) {{
      const e = imageResult.energy;
      const gen = imageResult.generation;
      imageRows += `<tr><td>Wh / image</td><td>${{fmt(e && (e.wh_per_image||e.delta_e_wh),4)}} Wh</td></tr>`;
      imageRows += `<tr><td>Generation time</td><td>${{fmt(gen && gen.total_s,1)}}s</td></tr>`;
    }} else {{
      imageRows += `<tr><td>Image</td><td style="color:var(--text-5)">— not run yet</td></tr>`;
    }}
  }} catch(err) {{ imageRows += `<tr><td>Image</td><td style="color:var(--text-3)">error: ${{err.message}}</td></tr>`; }}

  // RAG
  try {{
    if (ragResult && ragResult.results) {{
      const bl = ragResult.results.baseline, rl = ragResult.results.rag_large;
      if (bl && rl) {{
        const overhead = bl.energy && rl.energy && bl.energy.mwh_per_token > 0
          ? (((rl.energy.mwh_per_token - bl.energy.mwh_per_token) / bl.energy.mwh_per_token) * 100).toFixed(1)
          : null;
        ragRows += `<tr><td>Without RAG mWh/tok</td><td>${{fmt(bl.energy && bl.energy.mwh_per_token,3)}}</td></tr>`;
        ragRows += `<tr><td>RAG Large mWh/tok</td><td>${{fmt(rl.energy && rl.energy.mwh_per_token,3)}}</td></tr>`;
        if (overhead !== null) ragRows += `<tr><td>RAG overhead</td><td>${{overhead}}%</td></tr>`;
      }}
    }} else {{
      ragRows += `<tr><td>RAG</td><td style="color:var(--text-5)">— not run yet</td></tr>`;
    }}
  }} catch(err) {{ ragRows += `<tr><td>RAG</td><td style="color:var(--text-3)">error: ${{err.message}}</td></tr>`; }}

  }} catch(outerErr) {{
    el.innerHTML = '<p style="color:var(--err);font-family:monospace;font-size:0.82rem">Summary error: ' + outerErr + '</p>';
    return;
  }}

  // Render: video as headline, AI workloads collapsed beneath.
  const collapseStyle = 'margin-top:0.75rem;border:1px solid var(--border);padding:0.5rem 0.9rem';
  const summaryStyle = 'cursor:pointer;color:var(--text-2);font-size:0.92rem;padding:0.25rem 0;list-style:none';
  const section = (title, rows) =>
    `<details style="${{collapseStyle}}">
       <summary style="${{summaryStyle}}">▸ ${{title}}</summary>
       <table class="summary-table" style="margin-top:0.5rem"><tbody>${{rows}}</tbody></table>
     </details>`;

  el.innerHTML = `
    <h2 style="color:var(--accent);font-size:1.05rem;margin-bottom:0.4rem">▶ Video transcoding</h2>
    <p style="color:var(--text-3);font-size:0.78rem;margin-bottom:0.75rem">
      The core GoS focus — streaming's largest controllable energy footprint.</p>
    <table class="summary-table"><tbody>${{videoRows}}</tbody></table>

    <p style="color:var(--text-3);font-size:0.78rem;margin-top:1.5rem;letter-spacing:0.04em">
      OTHER WORKLOADS MEASURED</p>
    ${{section('LLM inference', llmRows)}}
    ${{section('Image generation', imageRows)}}
    ${{section('RAG (retrieval-augmented inference)', ragRows)}}

    <p style="color:var(--text-3);font-size:0.82rem;line-height:1.7;margin-top:1.5rem;max-width:560px">
      These figures are from live measurements on GoS1, a server in France,
      using a calibrated smart plug. Not modelled. Not averaged.
      Reproducible by anyone with the same hardware.
    </p>`;
}}
</script>
    {_PROGRESS_JS}
    {_RESULT_JS}
    {_CONF_HELP_WIDGET}
"""


@router.get("/demo", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def demo_page(request: Request):
    # CR-002: confidence numbers and baseline/cooldown windows in the Guided
    # Tour are injected from settings.json at request time, so the tour can
    # never silently contradict the running config (same pattern as
    # /methodology — see methodology_page below).
    # CR-001: AUTH_CHIP placeholder renders the tier-aware sign-in widget.
    # CR-027: TIER_INDICATOR + upload-cap placeholders so the Welcome-step
    # tier framing and the Findings-step capability matrix stay in sync
    # with settings.json (no silent drift if caps change).
    s = cfg.load()
    member_cap_mb = s.get("upload_size_member_mb", "—")
    # CR-058 — Findings step terminus. When findings_enabled is true,
    # the Findings step (step 7) shows the curated catalog (top entries
    # + "See all findings" link) instead of echoing the visitor's just-
    # finished session runs. The original session-echo buildSummary() JS
    # early-returns when window.OWL_FINDINGS_CATALOG_ENABLED is set, so
    # flipping the flag back to false fully restores the prior behaviour.
    findings_panel_html = (
        '<p style="color:var(--text-3);font-size:0.85rem">Loading results…</p>'
    )
    if s.get("findings_enabled", False):
        catalog_items = findings_mod.list_all()
        catalog_items.sort(key=lambda f: f.last_refined, reverse=True)
        preview = [f for f in catalog_items if _finding_matches_live_backend(f)][:3]
        rows_html = _findings_catalog_rows_html(preview)
        if not preview:
            rows_html = (
                '<p style="color:var(--text-3);font-size:0.85rem;'
                'border-left:2px solid var(--border-3);padding-left:1rem">'
                'No findings published yet.</p>'
            )
        findings_panel_html = (
            f'{_FINDINGS_CATALOG_CSS}'
            '<p style="color:var(--text-3);font-size:0.85rem;line-height:1.55;margin-bottom:0.85rem">'
              "From OWL's body of evidence — citable findings backed by stored measurements:"
            '</p>'
            f'{rows_html}'
            '<div style="margin-top:0.85rem;font-size:0.82rem">'
              '<a href="/findings" style="color:var(--accent);text-decoration:none">'
              f'See all findings ({len(catalog_items)}) →</a>'
            '</div>'
            '<script>window.OWL_FINDINGS_CATALOG_ENABLED = true;</script>'
        )
    return (ui.render_page(request, "Guided Tour · Greening of Streaming",
                           styles=_DEMO_STYLES, body=_DEMO_HTML)
            .replace("{BASELINE_POLLS}",     str(s.get("baseline_polls",     "—")))
            .replace("{VIDEO_COOLDOWN_S}",   str(s.get("video_cooldown_s",   "—")))
            .replace("{CONF_GREEN_POLLS}",   str(s.get("conf_green_polls",   "—")))
            .replace("{CONF_YELLOW_POLLS}",  str(s.get("conf_yellow_polls",  "—")))
            .replace("{BETA_CHIP}",          _BETA_CHIP)
            .replace("{TIER_INDICATOR}",     _tier_indicator_html(request))
            .replace("{UPLOAD_MEMBER_MB}",   str(member_cap_mb))
            .replace("{GPU_H265_ENC}",       _gpu_enc("h265"))
            .replace("{GPU_AV1_ENC}",        _gpu_enc("av1"))
            .replace("{GPU_RUNTIME}",        _gpu_runtime())
            .replace("{GPU_DISPLAY_NAME}",   _gpu_display_name())
            .replace("{DEMO_LLM_MODEL_KEY}",   DEMO_LLM_MODEL)
            .replace("{DEMO_LLM_MODEL_LABEL}", _llm_model_label(DEMO_LLM_MODEL))
            .replace("{DEMO_LLM_MODEL_SIZE}",  _llm_model_size(DEMO_LLM_MODEL))
            .replace("{DEMO_RAG_MODEL_KEY}",   curated.CANONICAL_RAG_MODEL)
            .replace("{DEMO_RAG_MODEL_LABEL}", _llm_model_label(curated.CANONICAL_RAG_MODEL))
            .replace("{DEMO_VIDEO_SOURCE_KEY}",  DEMO_VIDEO_SOURCE)
            .replace("{DEMO_VIDEO_SOURCE_DESC}", _demo_video_source_desc())
            .replace("{DEMO_IMAGE_DETAIL}",  _demo_image_detail())
            .replace("{METER_NAME}",         meter_display_name())
            .replace("{METER_CADENCE}",      meter_cadence_label())
            .replace("{BUDGET_TEASER}",      _budget_teaser_html())
            .replace("{FINDINGS_PANEL}",     findings_panel_html))
