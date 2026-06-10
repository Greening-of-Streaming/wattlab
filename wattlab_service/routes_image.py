"""
Image-generation routes — /image page, /image/start, /image/job/{id}.

SD-Turbo / SDXL-Turbo (+ catalog models) via image_gen.py; CR-050 N-way
compare. Phase 3 per-feature route module — shared state from runtime.py,
chrome from ui.py, never import main.
"""
import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

import audience
import curated
import queue_control
import ui
from capabilities import (requires, can, gate,
                          BATCH_COMPARE, CUSTOM_PROMPT, IMAGE_RUN,
                          PUBLIC_PAGE, QUEUE_VIEW)
from image_gen import (run_image_measurement, run_image_both_measurement,
                       run_image_compare_models_measurement, IMAGE_MODELS,
                       IMAGE_STEPS_CPU, IMAGE_STEPS_GPU, GPU_BATCH_SIZE)
from persist import save_result, list_results
from power import CooldownCancelled
from runtime import jobs, job_status as _job_status
from ui import (_BETA_CHIP, _CONF_HELP_WIDGET, _LOCK_STYLES, _PROGRESS_JS,
                _RESULT_JS, _ai_intro, _bake_durations, _disabled_attr,
                _gpu_display_name, _gpu_runtime, _lock_badge_html, _lock_class)
from video import LOCK_FILE

router = APIRouter()


@router.get("/image/job/{job_id}", dependencies=[Depends(requires(QUEUE_VIEW))])
async def image_job_status(job_id: str):
    return _job_status(job_id)


@router.get("/image", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def image_page(request: Request):
    # CR-001 part C2c — capability flags drive the lock UI on the prompt
    # textarea (CUSTOM_PROMPT) and the Both / Compare-Models buttons
    # (BATCH_COMPARE). Anonymous sees the curated CANONICAL_IMAGE_PROMPT
    # rendered read-only with a lock badge; the runtime gate enforces.
    can_custom_prompt = can(audience.tier(request), CUSTOM_PROMPT)
    can_batch_compare = can(audience.tier(request), BATCH_COMPARE)
    lk_prompt_class   = _lock_class(request, CUSTOM_PROMPT)
    lk_prompt_badge   = _lock_badge_html(request, CUSTOM_PROMPT, "Edit prompt — Members only")
    lk_batch_class    = _lock_class(request, BATCH_COMPARE)
    lk_batch_badge    = _lock_badge_html(request, BATCH_COMPARE, "CPU vs GPU compare — Members only")
    dis_prompt        = _disabled_attr(request, CUSTOM_PROMPT)
    dis_batch         = _disabled_attr(request, BATCH_COMPARE)
    # Anonymous default = canonical curated prompt; Member/Lab default = today's
    # original copy. Avoids "user types nothing → server rejects empty".
    default_prompt    = ("a lone wind turbine in an open landscape"
                          if can_custom_prompt else curated.CANONICAL_IMAGE_PROMPT)

    queue_depth = queue_control.depth()
    busy_banner = (f'<div style="background:var(--border-3);color:var(--warn);padding:0.75rem 1rem;'
                   f'margin-bottom:1rem;font-size:0.85rem">'
                   f'⏱ {queue_depth} job{"s" if queue_depth != 1 else ""} in queue — '
                   f'yours will be added and run automatically.</div>') \
        if queue_depth > 0 else ""

    # CR-050 — build the model selector dynamically from IMAGE_MODELS so
    # adding a model on /settings is enough; no hardcoded HTML to drift.
    default_model_key = "sd-turbo" if "sd-turbo" in IMAGE_MODELS else (
        next(iter(IMAGE_MODELS.keys()), "sd-turbo"))
    image_model_cards = "".join([
        f'<div class="preset{" selected" if k == default_model_key else ""}" '
        f'id="mdl-{k}" data-model="{k}" data-cpu-ok="{"true" if v.get("cpu_ok") else "false"}" '
        f'onclick="selectModelKey(\'{k}\')" '
        f'style="border:1px solid {"var(--accent)" if k == default_model_key else "var(--border-3)"};'
        f'{"background:#00ff9911;" if k == default_model_key else ""}'
        f'padding:0.75rem 1rem;cursor:pointer;flex:1 1 170px;min-width:160px">'
        f'<div style="color:{"var(--accent)" if k == default_model_key else "var(--text-2)"};'
        f'font-size:0.85rem;font-weight:bold">{v.get("label", k)}</div>'
        f'<div style="color:var(--text-3);font-size:0.72rem">{v.get("params","?")} params · '
        f'{v.get("size_px",512)}×{v.get("size_px",512)} · {"CPU + GPU" if v.get("cpu_ok") else "GPU only"}</div>'
        f'</div>'
        for k, v in IMAGE_MODELS.items()
    ]) or '<div style="color:var(--text-5);font-size:0.85rem">No image models enabled — see /settings.</div>'
    # Compare Models button: enabled when at least 2 image models exist.
    # The runner iterates every enabled model — disable the ones you don't
    # want by unchecking them in /settings.
    compare_available = len(IMAGE_MODELS) >= 2
    compare_label = f"Compare all {len(IMAGE_MODELS)} models (GPU) ⚡"
    # Pre-compute the stage progression for the compare-models run so JS
    # can render an accurate progress dot strip for N models without
    # guessing the stage names.
    import json as _json2
    compare_stages_js  = ["m1_baseline", "m1_generating"]
    compare_labels_extra = {}
    for i, (k, v) in enumerate(IMAGE_MODELS.items(), start=1):
        b = f"m{i}_baseline"
        g = f"m{i}_generating"
        if i > 1:
            # Unique per-gap cooldown key — a repeated literal 'cooldown' made
            # the strip collapse every inter-model cooldown onto the first one
            # (JS indexOf returns the first match), so the indicator snapped
            # backward on each later cooldown. The runner still emits the generic
            # 'cooldown' stage; pollJob maps it to cooldown_<idx> via
            # current_model_idx, so the substring cooldown-detection paths are
            # untouched. Label uses the shared toggle-aware {COOLDOWN_PAREN}.
            cd_key = f"cooldown_{i}"
            compare_stages_js += [cd_key, b, g]
            compare_labels_extra[cd_key] = f"Cooldown before {v.get('label', k)} {{COOLDOWN_PAREN}}"
        compare_labels_extra[b] = f"{v.get('label', k)} — baseline ({{BASELINE_S}}s)"
        compare_labels_extra[g] = f"{v.get('label', k)} — generating (GPU batch)"
    compare_stages_js += ["done"]
    compare_stages_inject = _json2.dumps(compare_stages_js)
    compare_labels_inject = _json2.dumps(compare_labels_extra)

    # CR-026: scope to own-jobs for non-Lab. Lab passes None → unfiltered.
    prev_runs = list_results("image", limit=5,
                             visitor_key=queue_control.visitor_key(request))
    prev_html = ""
    if prev_runs:
        prev_html = '<div class="prev-runs"><h3>Previous runs</h3>'
        for r in prev_runs:
            fp = r.get("full_prompt", "")
            date_str = (r.get("saved_at") or "")[:16].replace("T", " ")
            saved_at = r.get("saved_at") or ""
            mode = r.get("mode", "cpu")
            # CR-034 Phase B / CR-013 — click-to-expand toggle. Lazy-loads the
            # full result via /results/image/<id>/download.json and renders
            # through window.wlRenderImageCard from _RESULT_JS.
            expand_link = (
                f'<a href="javascript:void(0)" '
                f'onclick="wlExpandPrevRow(\'image\',\'{r["job_id"]}\',\'{saved_at}\')" '
                f'style="color:var(--text-3);font-size:0.72rem;text-decoration:none;'
                f'margin-right:0.75rem;cursor:pointer">'
                f'<span id="chev-{r["job_id"]}">▸</span> Show full result</a>'
            )
            downloads = (
                expand_link
                + f'<a href="/results/image/{r["job_id"]}/download.json" download '
                f'style="color:var(--text-5);font-size:0.72rem;text-decoration:none;margin-right:0.75rem">↓ JSON</a>'
                f'<a href="/results/image/{r["job_id"]}/download.csv" download '
                f'style="color:var(--text-5);font-size:0.72rem;text-decoration:none">↓ CSV</a>'
            )
            expand_div = f'<div id="expand-{r["job_id"]}" style="display:none;margin-top:0.6rem"></div>'
            if mode == "both":
                def _side_html(label, s):
                    img = (f'<img src="data:image/png;base64,{s["b64_png"]}" '
                           f'style="width:64px;height:64px;object-fit:cover;margin-right:0.5rem">'
                           if s.get("b64_png") else "")
                    conf = s.get("confidence", {})
                    return (f'<div style="display:flex;align-items:center;margin-top:0.4rem">'
                            f'{img}<span style="color:var(--text-3);font-size:0.78rem">'
                            f'<span style="color:var(--text-2)">{label}</span> &nbsp;·&nbsp; '
                            f'{conf.get("flag","")} {conf.get("label","")} &nbsp;·&nbsp; '
                            f'{s.get("delta_e_wh","?")} Wh &nbsp;·&nbsp; {s.get("delta_t_s","?")}s'
                            f'</span></div>')
                model_lbl = r.get("model_label") or ""
                model_tag = f' &nbsp;·&nbsp; {model_lbl}' if model_lbl else ""
                prev_html += f"""<div class="prev-item" style="flex-direction:column;align-items:flex-start">
                  <span class="prev-meta">{date_str} &nbsp;·&nbsp; CPU vs GPU{model_tag}</span>
                  {_side_html("CPU", r.get("cpu", {}))}
                  {_side_html("GPU", r.get("gpu", {}))}
                  <div class="prev-prompt" style="color:var(--text-3);font-size:0.75rem;margin-top:0.3rem">{fp[:80]}</div>
                  <div style="margin-top:0.3rem">{downloads}</div>
                  {expand_div}
                </div>"""
            elif mode == "compare_models":
                def _mdl_html(s):
                    # Per-model run dict is flattened on save: the energy/generation
                    # fields live as siblings of the model_label, not nested.
                    img = (f'<img src="data:image/png;base64,{s["b64_png"]}" '
                           f'style="width:64px;height:64px;object-fit:cover;margin-right:0.5rem">'
                           if s.get("b64_png") else "")
                    conf = s.get("confidence", {}) or {}
                    lbl = s.get("model_label") or s.get("model_key", "?")
                    px = s.get("size_px", "?")
                    return (f'<div style="display:flex;align-items:center;margin-top:0.4rem">'
                            f'{img}<span style="color:var(--text-3);font-size:0.78rem">'
                            f'<span style="color:var(--text-2)">{lbl} ({px}px)</span> &nbsp;·&nbsp; '
                            f'{conf.get("flag","")} {conf.get("label","")} &nbsp;·&nbsp; '
                            f'{s.get("wh_per_image","?")} Wh/img &nbsp;·&nbsp; {s.get("delta_t_s","?")}s'
                            f'</span></div>')
                # New schema: r["models"] is a list of per-model summary dicts
                # (already flattened by persist._summarise — size_px / delta_t_s
                # naming, not raw generation/energy). Legacy schema
                # (pre-2026-05-27): r["small"] + r["large"] only.
                model_list = r.get("models") or []
                if model_list:
                    rows_html = "".join(_mdl_html(m) for m in model_list)
                    n_label = f"Compare {len(model_list)} models (GPU)"
                else:
                    rows_html = _mdl_html(r.get("small", {})) + _mdl_html(r.get("large", {}))
                    n_label = "Compare models (GPU)"
                prev_html += f"""<div class="prev-item" style="flex-direction:column;align-items:flex-start">
                  <span class="prev-meta">{date_str} &nbsp;·&nbsp; {n_label}</span>
                  {rows_html}
                  <div class="prev-prompt" style="color:var(--text-3);font-size:0.75rem;margin-top:0.3rem">{fp[:80]}</div>
                  <div style="margin-top:0.3rem">{downloads}</div>
                  {expand_div}
                </div>"""
            else:
                conf = r.get("confidence", {})
                img_tag = (f'<img src="data:image/png;base64,{r["b64_png"]}" '
                           f'style="width:80px;height:80px;object-fit:cover;vertical-align:middle;margin-right:0.75rem">'
                           if r.get("b64_png") else "")
                mode_label = {"cpu": "CPU", "gpu": "GPU"}.get(mode, mode)
                prev_html += f"""<div class="prev-item" style="flex-direction:column;align-items:flex-start">
                  <div style="display:flex;align-items:flex-start;width:100%">
                    {img_tag}
                    <div>
                      <span class="prev-meta">
                        {date_str} &nbsp;·&nbsp; {mode_label}
                        &nbsp;·&nbsp; <span class="conf-badge">{conf.get("flag","")} {conf.get("label","")}</span>
                        &nbsp;·&nbsp; {r.get("delta_e_wh","?")} Wh/image
                        &nbsp;·&nbsp; {r.get("delta_t_s","?")}s
                      </span>
                      <div class="prev-prompt" style="color:var(--text-3);font-size:0.75rem;margin-top:0.3rem">{fp[:80]}</div>
                      <div style="margin-top:0.3rem">{downloads}</div>
                    </div>
                  </div>
                  {expand_div}
                </div>"""
        prev_html += "</div>"

    return _bake_durations(ui.render_page(request, "Image Generation Test", styles=f"""
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: monospace; background: var(--bg); color: var(--text);
               max-width: 780px; margin: 0 auto; padding: 2rem; }}
        h1 {{ color: var(--accent); margin-bottom: 0.25rem; font-size: 1.6rem; }}
        .subtitle {{ color: var(--text-3); font-size: 0.8rem; margin-bottom: 1.5rem; }}
        .info {{ color: var(--text-3); font-size: 0.82rem; margin-bottom: 1.5rem;
                 border-left: 2px solid #222; padding-left: 1rem; line-height: 1.6; }}
        textarea {{ width: 100%; background: var(--panel); color: var(--text); border: 1px solid var(--border-3);
                    padding: 0.75rem; font-family: monospace; font-size: 0.9rem;
                    resize: vertical; margin-bottom: 1rem; }}
        button {{ background: var(--accent); color: #000; border: none;
                  padding: 0.75rem 2rem; cursor: pointer;
                  font-family: monospace; font-size: 1rem; }}
        button:disabled {{ background: var(--border); color: var(--text-3); cursor: not-allowed; }}
        button:hover:not(:disabled) {{ background: var(--accent-hover); }}
        #status {{ margin-top: 1.5rem; }}
        .progress-box {{ border: 1px solid var(--border); padding: 1.5rem; }}
        .progress-header {{ color: var(--warn); font-size: 0.9rem; margin-bottom: 1.25rem; }}
        .stages {{ display: flex; flex-direction: column; gap: 0.5rem; margin-bottom: 1.25rem; }}
        .stage {{ display: flex; align-items: center; gap: 0.75rem; font-size: 0.82rem; }}
        .stage-icon {{ width: 1.2rem; text-align: center; flex-shrink: 0; }}
        .live-watts {{ font-size: 2rem; color: var(--accent); font-weight: bold; margin-top: 0.5rem; }}
        .result-box {{ border: 1px solid #00ff9944; padding: 1.5rem; margin-top: 1.5rem; }}
        .result-box h2 {{ color: var(--accent); font-size: 1.1rem; margin-bottom: 1.25rem; }}
        .kpis {{ display: flex; gap: 1.5rem; flex-wrap: wrap; margin-bottom: 1.25rem; }}
        .kpi {{ display: flex; flex-direction: column; gap: 0.25rem; }}
        .kpi .val {{ font-size: 1.4rem; color: var(--accent); font-weight: bold; }}
        .kpi .lbl {{ font-size: 0.72rem; color: var(--text-3); }}
        .conf-badge {{ display: inline-block; border: 1px solid var(--border-3); padding: 0.25rem 0.75rem;
                       font-size: 0.8rem; color: var(--text-2); margin-bottom: 1rem; }}
        .scope-note {{ color: var(--text-5); font-size: 0.75rem; margin-top: 1rem; }}
        .prev-runs {{ margin-top: 2rem; border-top: 1px solid var(--border-2); padding-top: 1.5rem; }}
        .prev-runs h3 {{ color: var(--text-4); font-size: 0.85rem; margin-bottom: 1rem; }}
        .prev-item {{ padding: 0.75rem 0; border-bottom: 1px solid var(--panel);
                      display: flex; align-items: flex-start; flex-wrap: wrap; }}
        .prev-meta {{ color: var(--text-3); font-size: 0.78rem; }}
        .image-preview {{ margin-top: 1.25rem; }}
        .image-preview img {{ max-width: 100%; border: 1px solid var(--border); display: block; }}
        .image-caption {{ color: var(--text-4); font-size: 0.75rem; margin-top: 0.5rem; font-style: italic; }}
        .back {{ color: var(--text-3); font-size: 0.8rem; margin-bottom: 1.5rem; display: block; }}
        .back:hover {{ color: var(--accent); }}
        {_LOCK_STYLES}
""", body=f"""
    {busy_banner}
    <h1>Image Generation Test {_BETA_CHIP}</h1>
    <div class="subtitle">SD-Turbo (~1B) · SDXL-Turbo (~3.5B) · 512×512 · {_gpu_runtime()} fp16 on {_gpu_display_name()}</div>

    {_ai_intro('image')}

    <div style="margin-bottom:1rem;font-size:0.78rem;color:var(--text-3)">
        First time here? <a href="/demo" style="color:var(--accent);text-decoration:none">Try the Guided Tour →</a>
    </div>

    <details style="margin-bottom:1.5rem;border-left:2px solid #222;padding-left:1rem">
        <summary style="cursor:pointer;color:var(--text-3);font-size:0.82rem;list-style:none;outline:none">
            ⓘ About this test <span style="color:var(--text-4);font-size:0.72rem">(click to expand)</span>
        </summary>
        <div style="color:var(--text-3);font-size:0.82rem;line-height:1.6;margin-top:0.75rem">
            Measures the wall-power cost of generating one AI image from text.<br>
            <strong style="color:var(--text-2)">SD-Turbo</strong>: CPU {IMAGE_STEPS_CPU} steps (~12s) or GPU batch of {GPU_BATCH_SIZE} × {IMAGE_STEPS_GPU} steps (~10s). Note: solo-mode GPU over-samples (native is 1–4 steps) to keep runtime above the P110 polling floor.<br>
            <strong style="color:var(--text-2)">SDXL-Turbo</strong>: GPU only, 4 steps (native), batch of 15 (~10s).<br>
            <strong style="color:var(--text-2)">Compare Models ⚡</strong>: both run at 4 steps (native for each), 512×512, same seed — SD-Turbo batch 30, SDXL-Turbo batch 15. Model size is the only variable.<br>
            Each run appends a random colour/mood modifier — live proof the image is generated, not replayed.
        </div>
    </details>

    <label style="color:var(--text-3);font-size:0.8rem;display:block;margin-bottom:0.4rem">Model</label>
    <div id="model-row" style="display:flex;gap:0.75rem;margin-bottom:1.2rem;flex-wrap:wrap">
      {image_model_cards}
    </div>

    <label style="color:var(--text-3);font-size:0.8rem;display:block;margin-bottom:0.4rem">Prompt</label>
    {lk_prompt_badge}
    <div class="{lk_prompt_class}">
      <textarea id="prompt" rows="3"{dis_prompt}>{default_prompt}</textarea>
    </div>
    <div style="color:var(--text-3);font-size:0.75rem;margin-bottom:1.2rem">
        A random colour/mood modifier is appended per run (e.g. "bathed in emerald light").
    </div>

    <div style="margin-bottom:1.25rem">
      <span style="color:var(--text-3);font-size:0.8rem;margin-right:1rem">Backend:</span>
      <label style="font-size:0.85rem;margin-right:1.2rem;cursor:pointer" id="lbl-cpu">
        <input type="radio" name="img-device" value="cpu" checked onchange="selectedDevice=this.value"> CPU
      </label>
      <label style="font-size:0.85rem;margin-right:1.2rem;cursor:pointer">
        <input type="radio" name="img-device" value="gpu" onchange="selectedDevice=this.value"> GPU
      </label>
      <label class="{lk_batch_class}" style="font-size:0.85rem;cursor:pointer" id="lbl-both">
        <input type="radio" name="img-device" value="both"{dis_batch} onchange="selectedDevice=this.value"> Both ⚡
      </label>
    </div>
    {lk_batch_badge}

    <div style="display:flex;gap:0.75rem;flex-wrap:wrap">
      <button id="run-btn" onclick="startMeasurement()">Generate &amp; Measure</button>
      {("<button id='compare-btn' class='" + lk_batch_class + "' onclick='startCompareModels()'" + dis_batch +
        " style='background:var(--bg);border:1px solid var(--accent);color:var(--accent);"
        "padding:0.75rem 1.5rem;font-family:monospace;font-size:0.95rem;cursor:pointer'>" +
        compare_label + "</button>") if compare_available else
       ("<button disabled title='Compare requires at least 2 image models enabled in /settings' "
        "style='background:var(--border);color:var(--text-3);border:1px solid var(--border-3);"
        "padding:0.75rem 1.5rem;font-family:monospace;font-size:0.95rem;cursor:not-allowed'>"
        "Compare Models — needs ≥ 2 image models enabled</button>")}
    </div>
    <div id="status"></div>
    {prev_html}
    </div>

<script>
const CPU_STAGES = ['baseline','generating','done'];
const GPU_STAGES = ['baseline','generating','done'];
const BOTH_STAGES = ['cpu_baseline','cpu_generating','cooldown','gpu_baseline','gpu_generating','done'];
const COMPARE_STAGES = {compare_stages_inject};
const STAGE_LABELS = {{
  'baseline': 'Measuring baseline power ({{BASELINE_S}}s)',
  'generating': 'Generating image',
  'cpu_baseline': 'CPU — measuring baseline ({{BASELINE_S}}s)',
  'cpu_generating': 'CPU — generating image',
  'cooldown': 'Cooldown between passes {{COOLDOWN_PAREN}}',
  'gpu_baseline': 'GPU — measuring baseline ({{BASELINE_S}}s)',
  'gpu_generating': 'GPU — generating images (batch)',
  'done': 'Complete',
}};
// CR-050 follow-up — N-way compare-models stage labels injected from the server
// (one m<i>_baseline / m<i>_generating pair per enabled image model).
Object.assign(STAGE_LABELS, {compare_labels_inject});
// CR-001 part C2c — capability flags from server.
// Anonymous: textarea is locked at the canonical prompt; JS omits
// `prompt=` from the body so /image/start uses the curated default
// without tripping the CUSTOM_PROMPT gate.
const CAN_CUSTOM_PROMPT = {('true' if can_custom_prompt else 'false')};
const CAN_BATCH_COMPARE = {('true' if can_batch_compare else 'false')};

let pollTimer = null;
let selectedDevice = 'cpu';
let selectedModelKey = '{default_model_key}';
let imgStartTime = null;

// CR-050 — generic over N image models. Cards carry data-model and
// data-cpu-ok; CPU + Both radios enable based on the active model's
// cpu_ok metadata. GPU-only models force backend=gpu.
function selectModelKey(k) {{
  selectedModelKey = k;
  let cpuOk = false;
  document.querySelectorAll('#model-row .preset').forEach(card => {{
    const active = card.dataset.model === k;
    card.style.borderColor = active ? '#00ff99' : '#333';
    card.style.background = active ? '#00ff9911' : 'transparent';
    if (card.children[0]) card.children[0].style.color = active ? '#00ff99' : '#aaa';
    if (active) cpuOk = card.dataset.cpuOk === 'true';
  }});
  const cpuIn  = document.querySelector('input[name="img-device"][value="cpu"]');
  const bothIn = document.querySelector('input[name="img-device"][value="both"]');
  if (cpuOk) {{
    cpuIn.disabled = false;
    bothIn.disabled = false;
    document.getElementById('lbl-cpu').style.opacity = '1';
    document.getElementById('lbl-both').style.opacity = '1';
  }} else {{
    cpuIn.disabled = true;
    bothIn.disabled = true;
    document.getElementById('lbl-cpu').style.opacity = '0.35';
    document.getElementById('lbl-both').style.opacity = '0.35';
    const gpuIn = document.querySelector('input[name="img-device"][value="gpu"]');
    gpuIn.checked = true;
    selectedDevice = 'gpu';
  }}
}}

function fmt(v, dp=2) {{
  if (v === null || v === undefined) return '—';
  return Number(v).toFixed(dp);
}}

async function startMeasurement() {{
  const prompt = document.getElementById('prompt').value.trim();
  if (CAN_CUSTOM_PROMPT && !prompt) {{ alert('Enter a prompt'); return; }}

  document.getElementById('run-btn').disabled = true;
  document.getElementById('compare-btn').disabled = true;
  document.getElementById('status').innerHTML = '';

  let body = 'device=' + encodeURIComponent(selectedDevice)
           + '&model_key=' + encodeURIComponent(selectedModelKey);
  if (CAN_CUSTOM_PROMPT && prompt) body += '&prompt=' + encodeURIComponent(prompt);
  const resp = await fetch('/image/start', {{
    method: 'POST',
    headers: {{'Content-Type':'application/x-www-form-urlencoded'}},
    body: body,
  }});
  const data = await resp.json();
  if (data.error) {{
    alert(data.error);
    document.getElementById('run-btn').disabled = false;
    document.getElementById('compare-btn').disabled = false;
    return;
  }}
  const jobId = data.job_id;

  imgStartTime = Date.now();
  renderProgress('baseline', null, null);
  pollTimer = setInterval(() => pollJob(jobId), 1500);
}}

async function startCompareModels() {{
  if (!CAN_BATCH_COMPARE) return;   // button is disabled, this is a backstop
  const prompt = document.getElementById('prompt').value.trim();
  if (CAN_CUSTOM_PROMPT && !prompt) {{ alert('Enter a prompt'); return; }}

  // Compare Models is GPU-only (SDXL-Turbo can't run on CPU). Flip the
  // backend radio to GPU so the page state reflects what's about to run —
  // otherwise the radio stays on CPU/Both while the progress widget shows
  // GPU stages, which reads as a contradiction.
  const gpuRadio = document.querySelector('input[name="img-device"][value="gpu"]');
  if (gpuRadio && !gpuRadio.checked) {{
    gpuRadio.checked = true;
    selectedDevice = 'gpu';
  }}

  document.getElementById('run-btn').disabled = true;
  document.getElementById('compare-btn').disabled = true;
  document.getElementById('status').innerHTML = '';

  let body = 'device=compare_models'
           + '&model_key=sd-turbo';   // ignored by server for compare_models
  if (CAN_CUSTOM_PROMPT && prompt) body += '&prompt=' + encodeURIComponent(prompt);
  const resp = await fetch('/image/start', {{
    method: 'POST',
    headers: {{'Content-Type':'application/x-www-form-urlencoded'}},
    body: body,
  }});
  const data = await resp.json();
  if (data.error) {{
    alert(data.error);
    document.getElementById('run-btn').disabled = false;
    document.getElementById('compare-btn').disabled = false;
    return;
  }}
  const jobId = data.job_id;

  imgStartTime = Date.now();
  renderProgress('m1_baseline', null, null);
  pollTimer = setInterval(() => pollJob(jobId), 1500);
}}

async function pollJob(jobId) {{
  const r = await fetch('/image/job/' + jobId);
  const j = await r.json();

  if (j.stage === 'queued') {{ wlRenderQueued(j.queue_position); return; }}

  if (j.stage === 'awaiting_cooldown_decision') {{
    wlCooldownDialog(jobId, j.cooldown_decision_options);
  }} else {{ wlCooldownDialogClose(); }}

  const powerR = await fetch('/power');
  const powerJ = await powerR.json().catch(() => ({{}}));
  // The compare runner emits a generic 'cooldown' stage; the progress strip
  // carries a unique cooldown_<idx> key per gap (so repeated cooldowns don't
  // collapse onto the first). current_model_idx is the model the cooldown
  // precedes, which is exactly the index the strip key was built with.
  let _dispStage = j.stage;
  if (_dispStage === 'cooldown' && j.current_model_idx) {{
    _dispStage = 'cooldown_' + j.current_model_idx;
  }}
  renderProgress(_dispStage, j.result, powerJ.watts ?? null);

  if (j.stage === 'done' && j.result) {{
    clearInterval(pollTimer);
    if (j.result.mode === 'both') renderImageBoth(j.result);
    else if (j.result.mode === 'compare_models') {{
      // Use the shared N-aware card (reads r.models) — the legacy
      // renderCompareModels only knew r.small/r.large, so a 3-model run
      // showed just 2. Same renderer as the prev-row / demo expand paths.
      document.getElementById('status').innerHTML =
        wlRenderImageCard({{result: j.result, isPrev: false}});
    }}
    else renderResult(j.result);
    document.getElementById('run-btn').disabled = false;
    document.getElementById('compare-btn').disabled = false;
  }}
  if (j.error) {{
    clearInterval(pollTimer);
    document.getElementById('status').innerHTML =
      '<p style="color:var(--err)">Error: ' + j.error + '</p>';
    document.getElementById('run-btn').disabled = false;
    document.getElementById('compare-btn').disabled = false;
  }}
}}

function renderProgress(stage, result, watts) {{
  const isCompare = COMPARE_STAGES.includes(stage) && stage !== 'done';
  const isBoth = !isCompare && BOTH_STAGES.includes(stage) && stage !== 'done';
  const stageKeys = isCompare ? COMPARE_STAGES : (isBoth ? BOTH_STAGES : CPU_STAGES);
  const stageIdx = stageKeys.indexOf(stage);
  wlRenderProgress({{
    header: '\u26a1 Measuring\u2026 do not close this tab',
    stagesHtml: wlStageList(stageKeys.map(s => STAGE_LABELS[s] || s), stageIdx),
    watts: watts,
    elapsed: imgStartTime ? Date.now() - imgStartTime : null,
    cooldownData: result,
  }});
}}

function _imageCard(label, pass_r, isWinner) {{
  const e = pass_r.energy;
  const gen = pass_r.generation;
  const borderCol = isWinner ? '#00ff9966' : '#222';
  const imgHtml = gen.b64_png
    ? `<div style="margin-top:0.75rem"><img src="data:image/png;base64,${{gen.b64_png}}" style="max-width:180px;border:1px solid var(--border)"></div>`
    : '';
  return `<div style="border:1px solid ${{borderCol}};padding:1rem;flex:1;min-width:220px">
    <div style="color:${{isWinner?'#00ff99':'#777'}};font-size:0.85rem;font-weight:bold;margin-bottom:0.75rem">${{label}}${{isWinner?' 🏆':''}}</div>
    <div class="kpis">
      <div class="kpi"><div class="val" style="font-size:1.15rem">${{fmt(e.wh_per_image,4)}} Wh</div><div class="lbl">per image</div></div>
      <div class="kpi"><div class="val" style="font-size:1.15rem">${{fmt(gen.gen_s_per_image,1)}} s</div><div class="lbl">gen/image</div></div>
      <div class="kpi"><div class="val" style="font-size:1.1rem">${{fmt(e.delta_w,1)}} W</div><div class="lbl">delta W</div></div>
      <div class="kpi"><div class="val" style="font-size:1.1rem">${{e.poll_count}}</div><div class="lbl">polls</div></div>
    </div>
    <div style="font-size:0.78rem;color:var(--text-3);margin-top:0.5rem"><span class="conf-badge">${{e.confidence.flag}} ${{e.confidence.label}}</span> · ${{gen.batch_size}}×${{gen.steps}} steps</div>
    ${{imgHtml}}
  </div>`;
}}

function renderImageBoth(r) {{
  const a = r.analysis;
  const cpuWinsEnergy = a.energy_winner === 'cpu';
  const gpuWinsEnergy = a.energy_winner === 'gpu';
  const _stripWh = (r.cpu && r.cpu.energy && r.gpu && r.gpu.energy)
    ? Math.min(r.cpu.energy.delta_e_wh, r.gpu.energy.delta_e_wh)
    : ((r.cpu && r.cpu.energy && r.cpu.energy.delta_e_wh) || (r.gpu && r.gpu.energy && r.gpu.energy.delta_e_wh));
  const _winE = (r.cpu && r.cpu.energy && r.gpu && r.gpu.energy)
    ? (r.cpu.energy.delta_e_wh <= r.gpu.energy.delta_e_wh ? r.cpu.energy : r.gpu.energy)
    : ((r.cpu && r.cpu.energy) || (r.gpu && r.gpu.energy));
  const _stripDur = _winE ? _winE.delta_t_s : null;
  const _stripSavedG = _winE && _winE.co2e && _winE.co2e.intensity
    ? _winE.co2e.intensity.g_per_kwh : null;
  // CR-032 — sub-runs across the two devices.
  const _subRuns = [
    {{label: 'CPU · Ryzen 9 7900',  e: r.cpu  && r.cpu.energy}},
    {{label: 'GPU · {_gpu_display_name()}',    e: r.gpu  && r.gpu.energy}}
  ].filter(s => s.e && s.e.co2e).map(s => ({{
    label: s.label,
    grams: s.e.co2e.grams,
    deltaWh: s.e.delta_e_wh,
    durationS: s.e.delta_t_s
  }}));
  // CR-038 — structured efficiency verdict above the per-device cards.
  const _imgBothVerdict = wlEfficiencyVerdict([
    r.cpu && r.cpu.energy ? {{label: 'CPU', energy: (r.cpu.energy.wh_per_image || r.cpu.energy.delta_e_wh)}} : null,
    r.gpu && r.gpu.energy ? {{label: 'GPU', energy: (r.gpu.energy.wh_per_image || r.gpu.energy.delta_e_wh)}} : null
  ], {{unit: 'Wh/image'}});
  document.getElementById('status').innerHTML = `
    <div class="result-box">
      <h2>CPU vs GPU — Image Generation</h2>
      <div style="background:var(--panel);border:1px solid var(--border-3);padding:0.75rem 1rem;margin-bottom:1.25rem;font-size:0.85rem;color:var(--text-2)">
        ${{a.finding}}
      </div>
      ${{_imgBothVerdict}}
      <div style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1rem">
        ${{_imageCard('CPU · Ryzen 9 7900', r.cpu, cpuWinsEnergy)}}
        ${{_imageCard('GPU · {_gpu_display_name()}', r.gpu, gpuWinsEnergy)}}
      </div>
      <div style="font-size:0.75rem;color:var(--text-4);margin-top:0.5rem">
        Prompt: "${{r.full_prompt}}" · modifier: <em>${{r.modifier}}</em>
      </div>
      ${{wlCarbonStrip(_stripWh, 'Image gen · most efficient device', _stripDur, _stripSavedG, _subRuns)}}
      <p class="scope-note">${{r.scope}}</p>
    </div>`;
}}

function _modelCard(side_r) {{
  const e = side_r.energy;
  const gen = side_r.generation;
  const imgHtml = gen.b64_png
    ? `<div style="margin-top:0.75rem"><img src="data:image/png;base64,${{gen.b64_png}}" style="max-width:100%;border:1px solid var(--border)"></div>`
    : '';
  return `<div style="border:1px solid var(--border);padding:1rem;flex:1;min-width:260px">
    <div style="color:var(--accent);font-size:0.9rem;font-weight:bold;margin-bottom:0.25rem">${{gen.model_label}}</div>
    <div style="color:var(--text-3);font-size:0.72rem;margin-bottom:0.75rem">${{gen.model}} · ${{gen.size}}px · ${{gen.steps}} steps × batch ${{gen.batch_size}}</div>
    <div class="kpis">
      <div class="kpi"><div class="val" style="font-size:1.2rem">${{fmt(e.wh_per_image,4)}} Wh</div><div class="lbl">per image</div></div>
      <div class="kpi"><div class="val" style="font-size:1.2rem">${{fmt(gen.gen_s_per_image,1)}} s</div><div class="lbl">gen/image</div></div>
      <div class="kpi"><div class="val" style="font-size:1.1rem">${{fmt(e.delta_w,1)}} W</div><div class="lbl">delta W</div></div>
      <div class="kpi"><div class="val" style="font-size:1.1rem">${{e.poll_count}}</div><div class="lbl">polls</div></div>
    </div>
    <div class="conf-badge" style="font-size:0.78rem;color:var(--text-3);margin-top:0.5rem">${{e.confidence.flag}} ${{e.confidence.label}}</div>
    ${{imgHtml}}
  </div>`;
}}

function renderCompareModels(r) {{
  // Legacy 2-model renderer retired (2026-06-02): it only read r.small/r.large,
  // so a 3-model compare showed just 2 cards. Delegate to the shared N-aware
  // card so this can't drift again. Kept as a shim for any stray caller.
  document.getElementById('status').innerHTML =
    wlRenderImageCard({{result: r, isPrev: false}});
}}

function renderResult(r) {{
  const e = r.energy;
  const gen = r.generation;
  const batch = gen.batch_size || 1;
  const batchNote = batch > 1 ? ` (batch of ${{batch}})` : '';
  const imgHtml = gen.b64_png
    ? `<div class="image-preview">
         <img src="data:image/png;base64,${{gen.b64_png}}" alt="Generated image">
         <div class="image-caption">"${{r.full_prompt}}"</div>
       </div>`
    : '';
  document.getElementById('status').innerHTML = `
    <div class="result-box">
      <h2>Result</h2>
      <div class="kpis">
        <div class="kpi">
          <div class="val">${{fmt(e.wh_per_image,4)}} Wh</div>
          <div class="lbl">energy / image</div>
        </div>
        <div class="kpi">
          <div class="val">${{fmt(e.delta_w,1)}} W</div>
          <div class="lbl">delta above idle</div>
        </div>
        <div class="kpi">
          <div class="val">${{fmt(gen.gen_s_per_image,1)}} s</div>
          <div class="lbl">gen time / image${{batchNote}}</div>
        </div>
        <div class="kpi">
          <div class="val">${{fmt(gen.load_s,1)}} s</div>
          <div class="lbl">model load</div>
        </div>
        <div class="kpi">
          <div class="val">${{e.poll_count}}</div>
          <div class="lbl">P110 polls</div>
        </div>
      </div>
      <div class="conf-badge">${{e.confidence.flag}} ${{e.confidence.label}}</div>
      ${{e.video_relative ? '<div style="font-size:0.78rem;color:var(--text-3);margin-top:0.5rem">This run ' + e.video_relative.text + '</div>' : ''}}
      ${{imgHtml}}
      <div class="modifier-note" style="color:var(--text-4);font-size:0.75rem;margin-top:0.75rem">
        Modifier applied this run: "<em>${{r.modifier}}</em>"
      </div>
      ${{wlCarbonStrip(e.delta_e_wh, 'Image generation total run', e.delta_t_s, e.co2e && e.co2e.intensity ? e.co2e.intensity.g_per_kwh : null)}}
      <p class="scope-note">${{r.scope}}</p>
    </div>`;
}}
const _resumeJob = new URLSearchParams(location.search).get('job');
if (_resumeJob) {{ document.getElementById('run-btn').disabled = true; pollTimer = setInterval(() => pollJob(_resumeJob), 1500); }}
</script>
    {_PROGRESS_JS}
    {_RESULT_JS}
    {_CONF_HELP_WIDGET}
"""))


@router.post("/image/start", dependencies=[Depends(requires(IMAGE_RUN))])
async def image_start(request: Request,
                      prompt: str = Form(None),
                      device: str = Form("cpu"),
                      model_key: str = Form("sd-turbo")):
    if device not in ("cpu", "gpu", "both", "compare_models"):
        device = "cpu"
    if model_key not in IMAGE_MODELS:
        return JSONResponse({"error": f"Unknown model: {model_key}"}, status_code=400)
    # CR-001 capability dispatch:
    #   prompt provided (free-form) → CUSTOM_PROMPT
    #   prompt absent                → curated canonical, Anonymous-OK
    #   device in {'both','compare_models'} → BATCH_COMPARE
    effective_prompt = prompt.strip() if prompt and prompt.strip() else None
    if effective_prompt is not None:
        gate(request, CUSTOM_PROMPT)
    else:
        effective_prompt = curated.CANONICAL_IMAGE_PROMPT
    if device in ("both", "compare_models"):
        gate(request, BATCH_COMPARE)
    prompt = effective_prompt
    cfg_m = IMAGE_MODELS[model_key]
    if device in ("cpu", "both") and not cfg_m["cpu_ok"]:
        return JSONResponse(
            {"error": f"{cfg_m['label']} is GPU-only — pick GPU or Compare Models."},
            status_code=400,
        )
    job_id = uuid.uuid4().hex[:8]
    if device == "compare_models":
        label = f"Image (compare SD/SDXL-Turbo) — {prompt[:35]}"
    else:
        label = f"Image ({cfg_m['label']} · {device.upper()}) — {prompt[:35]}"

    async def coro():
        try:
            if device == "compare_models":
                result = await run_image_compare_models_measurement(prompt, job_id, jobs)
            elif device == "both":
                result = await run_image_both_measurement(
                    prompt, job_id, jobs, model_key=model_key)
            else:
                result = await run_image_measurement(
                    prompt, job_id, jobs, device=device, model_key=model_key)
            save_result("image", job_id, result)
            jobs[job_id]["result"] = result
        except CooldownCancelled:
            jobs[job_id]["stage"] = "cancelled"
            jobs[job_id]["error"] = "Cancelled by operator during cooldown."
            LOCK_FILE.unlink(missing_ok=True)
        except Exception as e:
            jobs[job_id]["error"] = str(e)
            LOCK_FILE.unlink(missing_ok=True)

    position = queue_control.enqueue(job_id, "image", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}
