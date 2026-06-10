"""
LLM routes — /llm inference test, batched/all runs, and the CR-048
/llm/compare across-models page.

Orchestration (run_llm_job / run_llm_all_job / run_llm_compare_models_job)
lives here; inference + measurement stay in llm.py. benchmark.py reaches
run_llm_compare_models_job through the main.py alias. Phase 3 per-feature
route module — shared state from runtime.py, chrome from ui.py, never
import main.
"""
import asyncio
import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

import audience
import queue_control
import settings as cfg
import ui
from capabilities import (requires, can, gate,
                          BATCH_COMPARE, CUSTOM_PROMPT, LLM_RUN,
                          PUBLIC_PAGE, QUEUE_VIEW)
from llm import (run_llm_measurement, run_llm_batch_measurement,
                 run_llm_both_measurement, MODELS, TASKS, grade as llm_grade)
from persist import save_result
from power import CooldownCancelled, meter_display_name
from runtime import jobs, job_status as _job_status
from ui import (CHARTJS_URL, _BETA_CHIP, _CONF_HELP_WIDGET, _LOCK_STYLES,
                _PROGRESS_JS, _RESULT_JS, _ai_intro, _bake_durations,
                _disabled_attr, _gpu_display_name, _gpu_runtime,
                _lock_badge_html, _lock_class, _model_date_line)

router = APIRouter()


# --- LLM job runner ---

async def run_llm_job(job_id: str, model_key: str, task_key: str,
                      repeats: int = 1, warm: bool = False, prompt: str = None,
                      device: str = "gpu"):
    try:
        jobs[job_id].update({"status": "running", "stage": "baseline", "partial_response": ""})
        if device == "both":
            result = await run_llm_both_measurement(
                model_key, task_key, jobs, job_id, warm, prompt)
        elif repeats > 1:
            result = await run_llm_batch_measurement(
                model_key, task_key, repeats, warm, prompt, jobs, job_id)
        else:
            result = await run_llm_measurement(
                model_key, task_key, jobs, job_id, warm, prompt, device)
        save_result("llm", job_id, result)
        jobs[job_id].update({"status": "done", "stage": "done", "result": result})
    except Exception as e:
        jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}

@router.get("/llm", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def llm_page(request: Request):
    # CR-001 part C2c — capability flags drive the lock-badge UI.
    # Anonymous sees the same controls dim/disabled with a "Members only ·
    # Join GoS" badge; the runtime gates in /llm/run already enforce the
    # rule — this is the visible product copy.
    can_custom_prompt = can(audience.tier(request), CUSTOM_PROMPT)
    can_batch_compare = can(audience.tier(request), BATCH_COMPARE)
    lk_prompt_class   = _lock_class(request, CUSTOM_PROMPT)
    lk_prompt_badge   = _lock_badge_html(request, CUSTOM_PROMPT, "Edit prompt — Members only")
    lk_batch_class    = _lock_class(request, BATCH_COMPARE)
    lk_batch_badge    = _lock_badge_html(request, BATCH_COMPARE, "Batch / compare — Members only")
    dis_prompt        = _disabled_attr(request, CUSTOM_PROMPT)
    dis_batch         = _disabled_attr(request, BATCH_COMPARE)

    models_html = "".join([
        f'''<div class="preset" id="model-{k}" onclick="selectModel('{k}')">
            <h3>{v["label"]}</h3>
            <p style="color:var(--text-3);font-size:0.75rem">{v["params"]} · {v["size"]}</p>
            {_model_date_line(v)}
        </div>'''
        for k, v in MODELS.items()
    ])
    # Default selection = first model in the live panel. MODELS is a live view
    # (catalog ∩ llm_enabled_models ∩ ollama list) — never hardcode a key here:
    # tinyllama dropped out of llm_enabled_models and the dead
    # getElementById('model-tinyllama') killed the page's whole init block
    # (empty prompt box, nothing selected, stale key → "Invalid model"; S41).
    first_model = next(iter(MODELS), "")

    tasks_html = "".join([
        f'''<label style="display:flex;gap:0.75rem;border:1px solid var(--border-3);
                     padding:0.75rem;cursor:pointer;margin-bottom:0.5rem">
            <input type="radio" name="task" value="{k}"
                   {"checked" if k == "T1" else ""}
                   onchange="selectedTask='{k}'; document.getElementById('promptText').value=defaultPrompts['{k}']||''"
                   style="accent-color:var(--accent);margin-top:0.2rem">
            <div>
                <div style="color:var(--text);font-size:0.85rem">{v["label"]}</div>
                <div style="color:var(--text-3);font-size:0.75rem">{v["prompt"][:80]}...</div>
            </div>
        </label>'''
        for k, v in TASKS.items()
    ])

    import json as _json
    tasks_js = _json.dumps({k: v["prompt"] for k, v in TASKS.items()})

    return _bake_durations(ui.render_page(request, "LLM Inference Test", styles=f"""
        * {{ box-sizing:border-box; margin:0; padding:0; }}
        body {{ font-family:monospace; background:var(--bg); color:var(--text);
               max-width:780px; margin:0 auto; padding:2rem; }}
        h1 {{ color:var(--accent); margin-bottom:0.25rem; font-size:1.6rem; }}
        .subtitle {{ color:var(--text-3); font-size:0.8rem; margin-bottom:1.5rem; }}
        .info {{ color:var(--text-3); font-size:0.82rem; margin-bottom:1.5rem;
                 border-left:2px solid #222; padding-left:1rem; line-height:1.6; }}
        .presets {{ display:flex; gap:0.75rem; margin-bottom:1.5rem; }}
        .preset {{ border:1px solid var(--border-3); padding:1rem; cursor:pointer; flex:1; }}
        .preset:hover {{ border-color:#00ff9966; }}
        .preset.selected {{ border-color:var(--accent); background:#00ff9911; }}
        .preset h3 {{ color:var(--accent); font-size:0.9rem; margin-bottom:0.4rem; }}
        .section-label {{ color:var(--text-3); font-size:0.75rem; text-transform:uppercase;
                          letter-spacing:0.05em; margin-bottom:0.75rem; }}
        button {{ background:var(--accent); color:#000; border:none; padding:0.75rem 2rem;
                  cursor:pointer; font-family:monospace; font-size:1rem; margin-top:1rem; }}
        button:disabled {{ background:var(--border); color:var(--text-3); cursor:not-allowed; }}
        button:hover:not(:disabled) {{ background:var(--accent-hover); }}
        #status {{ margin-top:1.5rem; }}
        .result-box {{ border:1px solid var(--border); padding:1.5rem; }}
        .result-box h2 {{ color:var(--accent); font-size:1.1rem; margin-bottom:1rem;
                          padding-bottom:0.5rem; border-bottom:1px solid var(--border); }}
        .metric {{ display:flex; justify-content:space-between;
                   padding:0.3rem 0; border-bottom:1px solid var(--panel); font-size:0.82rem; }}
        .val {{ color:var(--accent); }}
        .section-title {{ color:var(--text-4); font-size:0.72rem; text-transform:uppercase;
                          letter-spacing:0.05em; margin:0.75rem 0 0.4rem; }}
        .response-box {{ background:var(--panel); padding:1rem; margin-top:0.75rem;
                         font-size:0.8rem; color:var(--text-2); line-height:1.6;
                         border-left:2px solid #00ff9944; max-height:500px;
                         overflow-y:auto; white-space:pre-wrap; }}
        .scope-note {{ color:var(--text-5); font-size:0.72rem; margin-top:1rem; }}
        .progress-box {{ border:1px solid var(--border); padding:1.5rem; }}
        .progress-header {{ color:var(--warn); font-size:0.9rem; margin-bottom:1rem; }}
        .stage {{ display:flex; align-items:center; gap:0.75rem;
                  font-size:0.82rem; margin-bottom:0.4rem; }}
        .stage.active .stage-label {{ color:var(--warn); }}
        .stage.done .stage-label {{ color:var(--accent); }}
        .stage.pending .stage-label {{ color:var(--text-5); }}
        a.back {{ color:var(--text-3); text-decoration:none; font-size:0.82rem;
                  display:inline-block; margin-top:1.5rem; }}
        a.back:hover {{ color:var(--accent); }}
        {_LOCK_STYLES}
""", body=f"""
    <h1>LLM Inference Energy Test {_BETA_CHIP}</h1>
    <div class="subtitle">Greening of Streaming · OWL · GoS1</div>

    <div style="margin-bottom:1.5rem;padding:0.85rem 1rem;border:1px solid var(--accent);
                background:var(--accent-soft);font-size:0.85rem;line-height:1.5">
        <span style="color:var(--accent);font-weight:bold">NEW</span> &middot;
        <a href="/llm/compare" style="color:var(--accent);text-decoration:none;
                                       border-bottom:1px solid var(--accent)">Compare {len(MODELS)} models on one prompt &rarr; energy per correct answer &nearr;</a>
        <span style="color:var(--text-3)"> &nbsp;CR-048 hybrid: 3-prompt showcase + member &ldquo;Try your own&rdquo;.</span>
    </div>

    {_ai_intro('llm')}

    <div style="margin-bottom:1rem;font-size:0.78rem;color:var(--text-3)">
        First time here? <a href="/demo" style="color:var(--accent);text-decoration:none">Try the Guided Tour →</a>
    </div>

    <details style="margin-bottom:1.5rem;border-left:2px solid #222;padding-left:1rem">
        <summary style="cursor:pointer;color:var(--text-3);font-size:0.82rem;list-style:none;outline:none">
            ⓘ About this test <span style="color:var(--text-4);font-size:0.72rem">(click to expand)</span>
        </summary>
        <div style="color:var(--text-3);font-size:0.82rem;line-height:1.6;margin-top:0.75rem">
            Run a language model on a fixed prompt and measure energy per token.<br>
            Models span small → large: TinyLlama 1.1B · Mistral 7B · Gemma 3 12B. CPU + ROCm GPU (via Ollama).<br>
            Cold mode unloads the model first; warm mode reuses a loaded model. Batch mode runs N inferences with a rest between.<br>
            Primary metric: <strong style="color:var(--text-2)">mWh per output token</strong> · P110 polled at 1s intervals.<br>
            Scope: device layer only — no amortised training cost included.
        </div>
    </details>

    <div class="section-label">Model</div>
    <div class="presets">{models_html}</div>

    <div class="section-label">Task</div>
    {tasks_html}

    {lk_prompt_badge}
    <div id="prompt-editor" class="{lk_prompt_class}" style="margin-bottom:1.5rem">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:0.4rem">
            <div style="color:var(--text-2);font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em">✎ Edit prompt</div>
            <button onclick="resetPrompt()"{dis_prompt} style="background:none;border:none;color:var(--text-3);
                font-size:0.75rem;cursor:pointer;padding:0;font-family:monospace">Reset to default</button>
        </div>
        <textarea id="promptText" rows="3"{dis_prompt}
            style="width:100%;background:#0f0f0f;border:1px solid var(--border-3);border-left:2px solid #00ff9966;
                   color:var(--text-2);font-family:monospace;font-size:0.8rem;padding:0.75rem;
                   resize:vertical;line-height:1.5"></textarea>
    </div>

    <div style="display:flex;gap:2rem;margin-bottom:1.5rem;flex-wrap:wrap">
        <div>
            <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                        letter-spacing:0.05em;margin-bottom:0.5rem">Backend</div>
            <div style="display:flex;gap:0.75rem">
                <label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="device" value="gpu" checked
                           onchange="selectedDevice='gpu'" style="accent-color:var(--accent)"> GPU
                </label>
                <label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="device" value="cpu"
                           onchange="selectedDevice='cpu'" style="accent-color:var(--accent)"> CPU
                </label>
                <label class="{lk_batch_class}" style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="device" value="both"{dis_batch}
                           onchange="selectedDevice='both'" style="accent-color:var(--accent)"> Both ⚡
                </label>
            </div>
            <div style="color:var(--text-5);font-size:0.72rem;margin-top:0.3rem">
                Both: CPU then GPU with new baseline — full side-by-side comparison
            </div>
        </div>
        <div>
            <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                        letter-spacing:0.05em;margin-bottom:0.5rem">Mode</div>
            <div style="display:flex;gap:0.75rem">
                <label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="warmMode" value="cold" checked
                           onchange="selectedWarm=false" style="accent-color:var(--accent)"> Cold
                </label>
                <label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="warmMode" value="warm"
                           onchange="selectedWarm=true" style="accent-color:var(--accent)"> Warm
                </label>
            </div>
            <div style="color:var(--text-5);font-size:0.72rem;margin-top:0.3rem">
                Cold: unload model before baseline · Warm: model stays loaded
            </div>
        </div>
        <div>
            <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                        letter-spacing:0.05em;margin-bottom:0.5rem">Repeats</div>
            <div style="display:flex;gap:0.75rem">
                <label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="repeats" value="1" checked
                           onchange="selectedRepeats=1" style="accent-color:var(--accent)"> 1×
                </label>
                <label class="{lk_batch_class}" style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="repeats" value="3"{dis_batch}
                           onchange="selectedRepeats=3" style="accent-color:var(--accent)"> 3×
                </label>
                <label class="{lk_batch_class}" style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.85rem">
                    <input type="radio" name="repeats" value="5"{dis_batch}
                           onchange="selectedRepeats=5" style="accent-color:var(--accent)"> 5×
                </label>
            </div>
            <div style="color:var(--text-5);font-size:0.72rem;margin-top:0.3rem">
                Batch: load once, 10s rest between runs
            </div>
        </div>
    </div>

    {lk_batch_badge}
    <div style="display:flex;gap:0.75rem;flex-wrap:wrap">
        <button id="runBtn" onclick="runInference()">Run Measurement</button>
        <button id="runAllBtn" class="{lk_batch_class}" onclick="runAllTasks()"{dis_batch}
            style="background:var(--bg);border:1px solid #00ff9966;color:var(--accent);
                   padding:0.65rem 1.25rem;font-family:monospace;font-size:0.85rem;cursor:pointer">
            Run All Tasks (T1+T2+T3)
        </button>
    </div>
    <div id="status"></div>
    <div id="prev-runs" style="margin-top:2rem;border-top:1px solid var(--panel);padding-top:1.5rem"></div>

    <script>
    // CR-001 part C2c — capability flags from the server.
    // CAN_CUSTOM_PROMPT false → JS never posts `prompt=`, server uses
    // the canonical task prompt. Stops Anonymous from tripping the
    // runtime CUSTOM_PROMPT gate just because the textarea is pre-filled.
    const CAN_CUSTOM_PROMPT = {('true' if can_custom_prompt else 'false')};
    const CAN_BATCH_COMPARE = {('true' if can_batch_compare else 'false')};

    let selectedModel = '{first_model}';
    let selectedTask = 'T1';
    let selectedWarm = false;
    let selectedRepeats = 1;
    let selectedDevice = 'gpu';
    let startTime = null;
    let streamTimer = null;

    const defaultPrompts = {tasks_js};

    // Select the first model in the panel by default. Guarded: an empty
    // panel must not throw here — everything below this line is the page's
    // init (prompt fill, loadPrevRuns) and dies with it.
    const _firstModelCard = document.getElementById('model-' + selectedModel);
    if (_firstModelCard) _firstModelCard.classList.add('selected');
    document.getElementById('promptText').value = defaultPrompts['T1'] || '';

    function selectModel(key) {{
        selectedModel = key;
        document.querySelectorAll('.preset').forEach(el => el.classList.remove('selected'));
        document.getElementById('model-' + key).classList.add('selected');
    }}

    function resetPrompt() {{
        document.getElementById('promptText').value = defaultPrompts[selectedTask] || '';
    }}

    function renderProgress(stage, watts, jobData) {{
        const isBoth = stage.startsWith('baseline_cpu') || stage.startsWith('cpu_') ||
                       stage.startsWith('baseline_gpu') || stage.startsWith('gpu_') ||
                       stage === 'cooldown';
        const displayStage = stage.startsWith('inference_') ? 'inference' :
                             stage.startsWith('rest_') ? 'rest' :
                             stage.startsWith('cpu_inference') ? 'cpu_inference' :
                             stage.startsWith('gpu_inference') ? 'gpu_inference' : stage;
        const stageLabel = stage.startsWith('inference_') ? 'Running inference (' + stage.replace('inference_','').replace('_',' ') + ')' :
                           stage.startsWith('rest_') ? 'Resting between runs\u2026' : null;
        const stages = isBoth ? [
            ['baseline_cpu', 'Measuring CPU baseline ({{BASELINE_S}}s)'],
            ['cpu_inference', 'CPU inference (num_gpu=0)'],
            ['cooldown', 'Cooldown between runs {{COOLDOWN_PAREN}}'],
            ['baseline_gpu', 'Measuring GPU baseline ({{BASELINE_S}}s)'],
            ['gpu_inference', 'GPU inference (ROCm)'],
            ['done', 'Done'],
        ] : [
            ['baseline', 'Measuring baseline ({{BASELINE_S}}s)'],
            ['inference', stageLabel || 'Running inference'],
            ['rest', 'Resting between runs\u2026 ({{LLM_REST_S}}s)'],
            ['done', 'Done'],
        ].filter(([k]) => k !== 'rest' || displayStage === 'rest');
        const stageIdx = stages.findIndex(([k]) => k === displayStage);
        wlRenderProgress({{
            header: 'Running \u2014 do not close this tab',
            stagesHtml: wlStageList(stages.map(([k,l]) => l), stageIdx < 0 ? 0 : stageIdx),
            watts: watts,
            elapsed: startTime ? Date.now() - startTime : null,
            extraHtml: '<div id="stream-preview" style="margin-top:0.75rem;background:var(--panel);'
                + 'padding:0.75rem;font-size:0.78rem;color:var(--text-3);line-height:1.6;'
                + 'min-height:2rem;border-left:2px solid #00ff9933;max-height:120px;'
                + 'overflow-y:auto;white-space:pre-wrap"></div>',
            cooldownData: jobData,
        }});
    }}

    async function runInference() {{
        const btn = document.getElementById('runBtn');
        btn.disabled = true;
        startTime = Date.now();

        const form = new FormData();
        form.append('model_key', selectedModel);
        form.append('task_key', selectedTask);
        form.append('repeats', selectedRepeats);
        form.append('warm', selectedWarm ? 'true' : 'false');
        form.append('device', selectedDevice);
        const promptVal = document.getElementById('promptText').value.trim();
        if (promptVal && CAN_CUSTOM_PROMPT) form.append('prompt', promptVal);

        try {{
            const resp = await fetch('/llm/run', {{method:'POST', body:form}});
            const data = await resp.json();
            if (data.job_id) {{
                renderProgress('baseline');
                pollLLM(data.job_id);
            }} else {{
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + JSON.stringify(data) + '</div>';
                btn.disabled = false;
            }}
        }} catch(e) {{
            document.getElementById('status').innerHTML =
                '<div style="color:var(--err)">Failed: ' + e + '</div>';
            btn.disabled = false;
        }}
    }}

    async function pollLLM(jobId) {{
        try {{
            const [resp, powerR] = await Promise.all([
                fetch('/llm/job/' + jobId),
                fetch('/power').catch(() => null),
            ]);
            const data = await resp.json();
            const watts = powerR ? (await powerR.json().catch(()=>({{}}))).watts ?? null : null;
            if (data.status === 'done') {{
                if (streamTimer) {{ clearTimeout(streamTimer); streamTimer = null; }}
                renderLLMResult(data.result, jobId);
                document.getElementById('runBtn').disabled = false;
            }} else if (data.status === 'error') {{
                if (streamTimer) {{ clearTimeout(streamTimer); streamTimer = null; }}
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + data.error + '</div>';
                document.getElementById('runBtn').disabled = false;
            }} else if (data.stage === 'queued') {{
                wlRenderQueued(data.queue_position);
                streamTimer = setTimeout(() => pollLLM(jobId), 3000);
            }} else {{
                const stage = data.stage || 'baseline';
                renderProgress(stage, watts, data);
                if (stage.startsWith('inference') && data.partial_response) {{
                    const box = document.getElementById('stream-preview');
                    if (box) box.textContent = data.partial_response;
                }}
                const delay = stage.startsWith('inference') ? 500 : 5000;
                streamTimer = setTimeout(() => pollLLM(jobId), delay);
            }}
        }} catch(e) {{
            streamTimer = setTimeout(() => pollLLM(jobId), 5000);
        }}
    }}

    function renderLLMResult(r, jobId) {{
        const elapsed = startTime ? wlFormatElapsed(Date.now() - startTime) : '';
        const base = '/results/llm/' + jobId;
        const links = jobId ? `<div style="margin-top:1rem;display:flex;gap:0.75rem">
            <a href="${{base}}/download.json" download
               style="color:var(--accent);font-size:0.8rem;border:1px solid #00ff9944;
                      padding:0.3rem 0.75rem;text-decoration:none">↓ JSON</a>
            <a href="${{base}}/download.csv" download
               style="color:var(--accent);font-size:0.8rem;border:1px solid #00ff9944;
                      padding:0.3rem 0.75rem;text-decoration:none">↓ CSV</a>
        </div>` : '';
        const elapsedNote = elapsed ? `<div style="color:var(--text-4);font-size:0.78rem;margin-bottom:1rem">
            Total elapsed: ${{elapsed}}</div>` : '';

        let body;
        if (r.mode === 'both') {{
            body = renderLLMBoth(r);
        }} else if (r.mode === 'batch') {{
            body = renderLLMBatch(r);
        }} else if (r.mode === 'all') {{
            body = renderLLMAll(r);
        }} else if (r.mode === 'all_both') {{
            body = renderLLMAllBoth(r);
        }} else {{
            body = renderLLMSingle(r);
        }}
        document.getElementById('status').innerHTML = elapsedNote + body + links;
        loadPrevRuns();
    }}

    function renderLLMSingle(r) {{
        const e = r.energy;
        const i = r.inference;
        const t = r.thermals;
        const modeNote = r.warm ? '🌡 Warm (model pre-loaded)' : '❄ Cold (model unloaded before baseline)';
        return `<div class="result-box">
                <h2>Energy Report — ${{r.model_label}} · ${{r.task_label}}</h2>
                <div class="section-title">Inference</div>
                <div class="metric"><span>Model</span><span class="val">${{r.model_label}} (${{r.model_params}})</span></div>
                <div class="metric"><span>Task</span><span class="val">${{r.task_label}}</span></div>
                <div class="metric"><span>Mode</span><span class="val">${{modeNote}}</span></div>
                <div class="metric"><span>Output tokens</span><span class="val">${{i.output_tokens}}</span></div>
                <div class="metric"><span>Tokens/sec</span><span class="val">${{i.tokens_per_sec}}</span></div>
                <div class="metric"><span>Duration</span><span class="val">${{i.duration_s}}s</span></div>
                <div class="section-title">Power (P110)</div>
                <div class="metric"><span>Baseline</span><span class="val">${{e.w_base}} W</span></div>
                <div class="metric"><span>Task mean</span><span class="val">${{e.w_task}} W</span></div>
                <div class="metric"><span>Delta (ΔW)</span><span class="val">${{e.delta_w}} W</span></div>
                <div class="metric"><span>Energy (ΔE)</span><span class="val">${{e.delta_e_wh}} Wh</span></div>
                ${{wlCarbonRow(e)}}
                <div class="metric"><span>Energy/token</span>
                    <span class="val">${{e.mwh_per_token}} mWh/token</span></div>
                <div class="metric"><span>Polls</span><span class="val">${{e.poll_count}}</span></div>
                <div class="section-title">Thermals</div>
                <div class="metric"><span>CPU (start→end)</span>
                    <span class="val">${{t.cpu_base}}→${{t.cpu_end}}°C</span></div>
                <div class="metric"><span>GPU (start→end)</span>
                    <span class="val">${{t.gpu_base}}→${{t.gpu_end}}°C</span></div>
                <div class="conf-badge" style="margin-top:0.75rem">${{e.confidence.flag}} ${{e.confidence.label}}</div>
                ${{e.video_relative ? '<div style="font-size:0.78rem;color:var(--text-3);margin-top:0.5rem">This run ' + e.video_relative.text + '</div>' : ''}}
                <div class="section-title">Response preview</div>
                <div class="response-box">${{i.response}}</div>
                ${{wlCarbonStrip(e.delta_e_wh, r.model_label + ' · ' + r.task_label, e.delta_t_s, e.co2e && e.co2e.intensity ? e.co2e.intensity.g_per_kwh : null)}}
                <div class="scope-note">${{r.scope}}</div>
            </div>`;
    }}

    function renderLLMBatch(r) {{
        const agg = r.aggregate;
        const t = r.thermals;
        const modeNote = r.warm ? '🌡 Warm' : '❄ Cold';
        const runsRows = r.runs.map(run => {{
            const e = run.energy;
            const i = run.inference;
            return `<tr>
                <td style="color:var(--text-3)">${{run.run}}</td>
                <td>${{i.output_tokens}}</td>
                <td>${{i.tokens_per_sec}}</td>
                <td>${{e.delta_e_wh}} Wh</td>
                <td>${{e.mwh_per_token}} mWh/tok</td>
                <td class="conf-badge">${{e.confidence.flag}}</td>
            </tr>`;
        }}).join('');
        return `<div class="result-box">
                <h2>Batch Report — ${{r.model_label}} · ${{r.task_label}}</h2>
                <div class="section-title">Run parameters</div>
                <div class="metric"><span>Model</span><span class="val">${{r.model_label}} (${{r.model_params}})</span></div>
                <div class="metric"><span>Task</span><span class="val">${{r.task_label}}</span></div>
                <div class="metric"><span>Mode</span><span class="val">${{modeNote}} · ${{r.repeats}}× runs · 10s rest</span></div>
                <div class="section-title">Aggregate</div>
                <div class="metric"><span>Energy/token (mean)</span>
                    <span class="val">${{agg.mwh_per_token_mean}} mWh/token</span></div>
                <div class="metric"><span>Energy/token (σ)</span>
                    <span class="val">${{agg.mwh_per_token_stddev ?? '—'}}</span></div>
                <div class="metric"><span>Energy per run (mean)</span>
                    <span class="val">${{agg.delta_e_wh_mean}} Wh</span></div>
                <div class="metric"><span>Energy per run (σ)</span>
                    <span class="val">${{agg.delta_e_wh_stddev ?? '—'}}</span></div>
                <div class="metric"><span>Tokens/sec (mean)</span>
                    <span class="val">${{agg.tokens_per_sec_mean}}</span></div>
                <div class="section-title">Per-run breakdown</div>
                <table style="width:100%;border-collapse:collapse;font-size:0.78rem">
                    <thead><tr style="color:var(--text-4);text-align:left">
                        <th style="padding:0.3rem 0.5rem 0.3rem 0">#</th>
                        <th style="padding:0.3rem 0.5rem">Tokens</th>
                        <th style="padding:0.3rem 0.5rem">Tok/s</th>
                        <th style="padding:0.3rem 0.5rem">ΔE</th>
                        <th style="padding:0.3rem 0.5rem">mWh/tok</th>
                        <th style="padding:0.3rem 0.5rem">Conf</th>
                    </tr></thead>
                    <tbody style="color:var(--text-2)">${{runsRows}}</tbody>
                </table>
                <div class="section-title">Thermals</div>
                <div class="metric"><span>CPU (start→end)</span>
                    <span class="val">${{t.cpu_base}}→${{t.cpu_end}}°C</span></div>
                <div class="metric"><span>GPU (start→end)</span>
                    <span class="val">${{t.gpu_base}}→${{t.gpu_end}}°C</span></div>
                <div class="section-title">Response preview (last run)</div>
                <div class="response-box">${{r.runs[r.runs.length-1].inference.response}}</div>
                ${{wlCarbonStrip(agg.delta_e_wh_mean, r.model_label + ' · ' + r.task_label + ' (mean of ' + r.repeats + ')')}}
                <div class="scope-note">${{r.scope}}</div>
            </div>`;
    }}

    function renderLLMBoth(r) {{
        const a = r.analysis;
        const cpu = r.cpu, gpu = r.gpu;
        const ce = cpu.energy, ge = gpu.energy;
        const ci = cpu.inference, gi = gpu.inference;
        const winnerColor = (winner, side) => winner === side ? '#00ff99' : '#888';
        // Strip uses the lower (more efficient) of the two energies.
        const _stripWh = (ce.delta_e_wh != null && ge.delta_e_wh != null)
            ? Math.min(ce.delta_e_wh, ge.delta_e_wh)
            : (ce.delta_e_wh != null ? ce.delta_e_wh : ge.delta_e_wh);
        const _stripLbl = r.model_label + ' · ' + r.task_label
            + ' (' + (a.energy_winner ? a.energy_winner + ' wins' : 'best of CPU/GPU') + ')';
        // Winner's energy block — drift note + duration for the strip.
        const _winE = (ce.delta_e_wh != null && ge.delta_e_wh != null)
            ? (ce.delta_e_wh <= ge.delta_e_wh ? ce : ge)
            : (ce.delta_e_wh != null ? ce : ge);
        const _stripDur = _winE ? _winE.delta_t_s : null;
        const _stripSavedG = _winE && _winE.co2e && _winE.co2e.intensity
            ? _winE.co2e.intensity.g_per_kwh : null;
        // CR-032 — sub-runs for the carbon strip's per-mode breakdown.
        const _subRuns = [
            {{side: 'CPU', e: ce}},
            {{side: 'GPU', e: ge}}
        ].filter(s => s.e && s.e.co2e).map(s => ({{
            label: s.side + ' · ' + r.model_label,
            grams: s.e.co2e.grams,
            deltaWh: s.e.delta_e_wh,
            durationS: s.e.delta_t_s
        }}));
        // CR-038 — structured efficiency verdict, alongside a.finding prose.
        const _llmBothVerdict = wlEfficiencyVerdict([
          ce ? {{label: 'CPU', energy: ce.mwh_per_token}} : null,
          ge ? {{label: 'GPU', energy: ge.mwh_per_token}} : null
        ], {{unit: 'mWh/token'}});
        return `<div class="result-box">
            <h2>CPU vs GPU — ${{r.model_label}} · ${{r.task_label}}</h2>
            <div style="background:#0d1a0d;border:1px solid #00ff9933;
                        padding:1rem;margin-bottom:1.25rem;font-size:0.82rem;line-height:1.7">
              ${{a.finding}}
            </div>
            ${{_llmBothVerdict}}
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1.25rem">
              <div style="border:1px solid var(--border);padding:1rem">
                <div style="color:var(--text-3);font-size:0.72rem;margin-bottom:0.75rem">CPU (num_gpu=0 · Ryzen 9 7900)</div>
                <div class="metric"><span>Tokens/sec</span>
                  <span class="val" style="color:${{winnerColor(a.speed_winner,'CPU')}}">${{ci.tokens_per_sec}}</span></div>
                <div class="metric"><span>Duration</span><span class="val">${{ci.duration_s}}s</span></div>
                <div class="metric"><span>ΔE total</span>
                  <span class="val" style="color:${{winnerColor(a.energy_winner,'CPU')}}">${{ce.delta_e_wh}} Wh</span></div>
                ${{wlCarbonRow(ce)}}
                <div class="metric"><span>mWh/token</span>
                  <span class="val" style="color:${{winnerColor(a.mwh_winner,'CPU')}}">${{ce.mwh_per_token}}</span></div>
                <div class="metric"><span>ΔW</span><span class="val">${{ce.delta_w}} W</span></div>
                <div class="conf-badge" style="margin-top:0.5rem">${{ce.confidence.flag}} ${{ce.confidence.label}}</div>
              </div>
              <div style="border:1px solid var(--border);padding:1rem">
                <div style="color:var(--text-3);font-size:0.72rem;margin-bottom:0.75rem">GPU ({_gpu_runtime()} · {_gpu_display_name()})</div>
                <div class="metric"><span>Tokens/sec</span>
                  <span class="val" style="color:${{winnerColor(a.speed_winner,'GPU')}}">${{gi.tokens_per_sec}}</span></div>
                <div class="metric"><span>Duration</span><span class="val">${{gi.duration_s}}s</span></div>
                <div class="metric"><span>ΔE total</span>
                  <span class="val" style="color:${{winnerColor(a.energy_winner,'GPU')}}">${{ge.delta_e_wh}} Wh</span></div>
                ${{wlCarbonRow(ge)}}
                <div class="metric"><span>mWh/token</span>
                  <span class="val" style="color:${{winnerColor(a.mwh_winner,'GPU')}}">${{ge.mwh_per_token}}</span></div>
                <div class="metric"><span>ΔW</span><span class="val">${{ge.delta_w}} W</span></div>
                <div class="conf-badge" style="margin-top:0.5rem">${{ge.confidence.flag}} ${{ge.confidence.label}}</div>
              </div>
            </div>
            <div class="section-title">CPU response preview</div>
            <div class="response-box">${{ci.response}}</div>
            <div class="section-title">GPU response preview</div>
            <div class="response-box">${{gi.response}}</div>
            ${{wlCarbonStrip(_stripWh, _stripLbl, _stripDur, _stripSavedG, _subRuns)}}
            <div class="scope-note">${{r.scope}}</div>
        </div>`;
    }}

    function renderLLMAll(r) {{
        const taskLabels = {{'T1': 'Short factual', 'T2': 'Medium reasoning', 'T3': 'Long generation'}};
        const cards = Object.entries(r.tasks).map(([key, t]) => {{
            const e = t.energy;
            const i = t.inference;
            return `<div style="border:1px solid var(--border);padding:1rem;margin-bottom:0.75rem">
                <div style="color:var(--accent);font-size:0.78rem;margin-bottom:0.75rem">${{key}} — ${{taskLabels[key] || key}}</div>
                <div class="metric"><span>Output tokens</span><span class="val">${{i.output_tokens}}</span></div>
                <div class="metric"><span>Tokens/sec</span><span class="val">${{i.tokens_per_sec}}</span></div>
                <div class="metric"><span>Duration</span><span class="val">${{i.duration_s}}s</span></div>
                <div class="metric"><span>ΔE</span><span class="val">${{e.delta_e_wh}} Wh</span></div>
                ${{wlCarbonRow(e)}}
                <div class="metric"><span>mWh/token</span><span class="val">${{e.mwh_per_token}}</span></div>
                <div class="metric"><span>ΔW</span><span class="val">${{e.delta_w}} W</span></div>
                <div class="conf-badge" style="margin-top:0.5rem;font-size:0.82rem">${{e.confidence.flag}} ${{e.confidence.label}}</div>
                ${{e.video_relative ? '<div style="font-size:0.76rem;color:var(--text-3);margin-top:0.4rem">This run ' + e.video_relative.text + '</div>' : ''}}
                <div class="section-title" style="margin-top:0.75rem">Response preview</div>
                <div class="response-box">${{i.response}}</div>
            </div>`;
        }}).join('');
        // Headline Wh = T3 (long generation), the largest of the three tasks.
        const _t3e = r.tasks && r.tasks.T3 && r.tasks.T3.energy ? r.tasks.T3.energy : null;
        const _t3 = _t3e ? _t3e.delta_e_wh : null;
        const _t3Dur = _t3e ? _t3e.delta_t_s : null;
        const _t3SavedG = _t3e && _t3e.co2e && _t3e.co2e.intensity
            ? _t3e.co2e.intensity.g_per_kwh : null;
        // CR-032 — sub-runs across T1/T2/T3 so the strip details show every
        // task's CO2e snapshot, not only the T3 headline.
        const _subRuns = Object.entries(r.tasks || {{}})
            .filter(([k, t]) => t && t.energy && t.energy.co2e)
            .map(([k, t]) => ({{
                label: k + ' — ' + (taskLabels[k] || k),
                grams: t.energy.co2e.grams,
                deltaWh: t.energy.delta_e_wh,
                durationS: t.energy.delta_t_s
            }}));
        return `<div class="result-box">
            <h2>All Tasks — ${{r.model_label}} (${{r.model_params}})</h2>
            <div style="color:var(--text-3);font-size:0.78rem;margin-bottom:1rem">
                ${{r.warm ? '🌡 Warm' : '❄ Cold'}} · ${{r.device.toUpperCase()}} · 3 tasks
            </div>
            ${{cards}}
            ${{wlCarbonStrip(_t3, r.model_label + ' · T3 long generation', _t3Dur, _t3SavedG, _subRuns)}}
            <div class="scope-note">${{r.scope}}</div>
        </div>`;
    }}

    function renderLLMAllBoth(r) {{
        const taskLabels = {{'T1':'Short factual','T2':'Medium reasoning','T3':'Long generation'}};
        const winCol = (cpu_val, gpu_val, lower_is_better) => {{
            if (cpu_val == null || gpu_val == null) return ['#ccc','#ccc'];
            const cpuWins = lower_is_better ? cpu_val <= gpu_val : cpu_val >= gpu_val;
            return cpuWins ? ['#00ff99','#888'] : ['#888','#00ff99'];
        }};
        const rows = Object.keys(taskLabels).map(tk => {{
            const cpu = r.cpu[tk] || {{}};
            const gpu = r.gpu[tk] || {{}};
            const ce = cpu.energy || {{}};
            const ge = gpu.energy || {{}};
            const ci = cpu.inference || {{}};
            const gi = gpu.inference || {{}};
            const [cSpeedCol, gSpeedCol] = winCol(ci.tokens_per_sec, gi.tokens_per_sec, false);
            const [cECol, gECol] = winCol(ce.mwh_per_token, ge.mwh_per_token, true);
            return `<tr style="border-bottom:1px solid var(--panel)">
                <td style="padding:0.5rem 0.75rem 0.5rem 0;color:var(--text-3);font-size:0.78rem">${{tk}}<br><span style="font-size:0.7rem;color:var(--text-4)">${{taskLabels[tk]}}</span></td>
                <td style="padding:0.5rem 0.75rem;font-size:0.8rem;color:${{cSpeedCol}}">${{ci.tokens_per_sec ?? '—'}}</td>
                <td style="padding:0.5rem 0.75rem;font-size:0.8rem;color:${{gSpeedCol}}">${{gi.tokens_per_sec ?? '—'}}</td>
                <td style="padding:0.5rem 0.75rem;font-size:0.8rem;color:${{cECol}}">${{ce.mwh_per_token ?? '—'}}</td>
                <td style="padding:0.5rem 0.75rem;font-size:0.8rem;color:${{gECol}}">${{ge.mwh_per_token ?? '—'}}</td>
                <td class="conf-badge" style="padding:0.5rem 0;font-size:0.78rem">${{ce.confidence ? ce.confidence.flag : ''}} ${{ge.confidence ? ge.confidence.flag : ''}}</td>
            </tr>`;
        }}).join('');
        return `<div class="result-box">
            <h2>All Tasks CPU vs GPU — ${{r.model_label}} (${{r.model_params}})</h2>
            <div style="color:var(--text-3);font-size:0.78rem;margin-bottom:1rem">${{r.warm ? '🌡 Warm' : '❄ Cold'}} · 3 tasks × 2 backends</div>
            <table style="width:100%;border-collapse:collapse">
                <thead><tr style="color:var(--text-4);font-size:0.72rem;text-align:left;border-bottom:1px solid var(--border)">
                    <th style="padding:0.4rem 0.75rem 0.4rem 0">Task</th>
                    <th style="padding:0.4rem 0.75rem">CPU tok/s</th>
                    <th style="padding:0.4rem 0.75rem">GPU tok/s</th>
                    <th style="padding:0.4rem 0.75rem">CPU mWh/tok</th>
                    <th style="padding:0.4rem 0.75rem">GPU mWh/tok</th>
                    <th style="padding:0.4rem 0">Conf</th>
                </tr></thead>
                <tbody>${{rows}}</tbody>
            </table>
            <div class="scope-note" style="margin-top:1rem">${{r.scope}}</div>
        </div>`;
    }}

    async function runAllTasks() {{
        const btn = document.getElementById('runAllBtn');
        const runBtn = document.getElementById('runBtn');
        btn.disabled = true;
        runBtn.disabled = true;
        startTime = Date.now();

        const form = new FormData();
        form.append('model_key', selectedModel);
        form.append('warm', selectedWarm ? 'true' : 'false');
        form.append('device', selectedDevice);  // cpu / gpu / both all supported

        try {{
            const resp = await fetch('/llm/run-all', {{method:'POST', body:form}});
            const data = await resp.json();
            if (data.job_id) {{
                renderProgress('T1_baseline');
                pollLLMAll(data.job_id);
            }} else {{
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + JSON.stringify(data) + '</div>';
                btn.disabled = false; runBtn.disabled = false;
            }}
        }} catch(e) {{
            document.getElementById('status').innerHTML =
                '<div style="color:var(--err)">Failed: ' + e + '</div>';
            btn.disabled = false; runBtn.disabled = false;
        }}
    }}

    async function pollLLMAll(jobId) {{
        try {{
            const [resp, powerR] = await Promise.all([
                fetch('/llm/job/' + jobId),
                fetch('/power').catch(() => null),
            ]);
            const data = await resp.json();
            const watts = powerR ? (await powerR.json().catch(()=>({{}}))).watts ?? null : null;
            if (data.status === 'done') {{
                if (streamTimer) {{ clearTimeout(streamTimer); streamTimer = null; }}
                renderLLMResult(data.result, jobId);
                document.getElementById('runBtn').disabled = false;
                document.getElementById('runAllBtn').disabled = false;
            }} else if (data.status === 'error') {{
                if (streamTimer) {{ clearTimeout(streamTimer); streamTimer = null; }}
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + data.error + '</div>';
                document.getElementById('runBtn').disabled = false;
                document.getElementById('runAllBtn').disabled = false;
            }} else if (data.stage === 'queued') {{
                wlRenderQueued(data.queue_position);
                streamTimer = setTimeout(() => pollLLMAll(jobId), 3000);
            }} else {{
                const task = data.current_task || 'T1';
                const dev = data.current_device || '';
                const taskNums = {{'T1':1,'T2':2,'T3':3}};
                const taskNum = taskNums[task] || 1;
                const devBadge = dev ? ' (' + dev.toUpperCase() + ')' : '';
                const taskPips = ['T1','T2','T3'].map(k => {{
                    const s = k === task ? 'active' : taskNums[k] < taskNum ? 'done' : 'pending';
                    const color = s === 'done' ? '#00ff99' : s === 'active' ? '#ffaa00' : '#333';
                    return '<span style="border:1px solid ' + color + ';padding:0.2rem 0.5rem;font-size:0.78rem;color:' + color + '">' + k + '</span>';
                }}).join('');
                wlRenderProgress({{
                    header: 'Running All Tasks \u2014 do not close this tab',
                    stagesHtml: '<div style="display:flex;gap:0.5rem;margin-bottom:0.5rem">' + taskPips + '</div>'
                        + '<div style="color:var(--text-3);font-size:0.8rem;margin-bottom:0.25rem">' + task + devBadge + '</div>',
                    watts: watts,
                    elapsed: startTime ? Date.now() - startTime : null,
                    cooldownData: data,
                }});
                streamTimer = setTimeout(() => pollLLMAll(jobId), 3000);
            }}
        }} catch(e) {{
            streamTimer = setTimeout(() => pollLLMAll(jobId), 5000);
        }}
    }}

    async function loadPrevRuns() {{
        try {{
            const resp = await fetch('/results/llm/list');
            const runs = await resp.json();
            renderPrevRuns(runs);
        }} catch(e) {{}}
    }}

    function renderPrevRuns(runs) {{
        const el = document.getElementById('prev-runs');
        if (!runs || runs.length === 0) {{
            el.innerHTML = '<div style="color:var(--text-5);font-size:0.8rem">No previous runs.</div>';
            return;
        }}
        const rows = runs.map(r => {{
            const date = r.saved_at ? r.saved_at.slice(0,16).replace('T',' ') : '—';
            const summary = `${{r.model||''}} · ${{r.task||''}} · ${{r.mwh_per_token}} mWh/tok · ${{r.tokens_per_sec}} tok/s ${{r.confidence ? '<span class="conf-badge">'+r.confidence+'</span>' : ''}}`;
            const base = '/results/llm/' + r.job_id;
            const savedAt = r.saved_at || '';
            return `<div style="border-bottom:1px solid var(--panel);padding:0.6rem 0">
                <div style="display:flex;justify-content:space-between;align-items:baseline">
                    <span style="color:var(--text);font-size:0.82rem">${{date}}</span>
                    <span style="color:var(--text-3);font-size:0.75rem;font-family:monospace">${{r.job_id}}</span>
                </div>
                <div style="color:var(--accent);font-size:0.8rem;margin:0.2rem 0">${{summary}}</div>
                <div style="display:flex;gap:0.75rem;margin-top:0.3rem;align-items:center">
                    <a href="javascript:void(0)"
                       onclick="wlExpandPrevRow('llm','${{r.job_id}}','${{savedAt}}')"
                       style="color:var(--text-3);font-size:0.75rem;text-decoration:none;cursor:pointer">
                       <span id="chev-${{r.job_id}}">▸</span> Show full result</a>
                    <a href="${{base}}/download.json" download
                       style="color:var(--text-5);font-size:0.75rem;text-decoration:none">↓ JSON</a>
                    <a href="${{base}}/download.csv" download
                       style="color:var(--text-5);font-size:0.75rem;text-decoration:none">↓ CSV</a>
                </div>
                <div id="expand-${{r.job_id}}" style="display:none;margin-top:0.6rem"></div>
            </div>`;
        }}).join('');
        el.innerHTML = `<div style="color:var(--text-4);font-size:0.72rem;text-transform:uppercase;
            letter-spacing:0.05em;margin-bottom:0.75rem">Previous runs</div>${{rows}}`;
    }}

    loadPrevRuns();
    const _resumeJob = new URLSearchParams(location.search).get('job');
    if (_resumeJob) {{ pollLLM(_resumeJob); }}
    </script>
    {_PROGRESS_JS}
    {_RESULT_JS}
    {_CONF_HELP_WIDGET}
"""))

@router.post("/llm/run", dependencies=[Depends(requires(LLM_RUN))])
async def llm_run(
    request: Request,
    model_key: str = Form(...),
    task_key: str = Form(...),
    repeats: int = Form(1),
    warm: bool = Form(False),
    prompt: str = Form(None),
    device: str = Form("gpu"),
):
    if model_key not in MODELS:
        return JSONResponse({"error": "Invalid model"}, status_code=400)
    if task_key not in TASKS:
        return JSONResponse({"error": "Invalid task"}, status_code=400)
    if device not in ("cpu", "gpu", "both"):
        return JSONResponse({"error": "device must be cpu, gpu, or both"}, status_code=400)
    if repeats not in (1, 3, 5):
        return JSONResponse({"error": "repeats must be 1, 3, or 5"}, status_code=400)

    effective_prompt = prompt.strip() if prompt and prompt.strip() else None
    # CR-001 capability dispatch: presence of free-form prompt or any
    # multi-run / cross-device request escalates the required capability.
    # Routes never compare tiers; they ask for the capability.
    if effective_prompt is not None:
        gate(request, CUSTOM_PROMPT)
    if repeats > 1 or device == "both":
        gate(request, BATCH_COMPARE)
    job_id = str(uuid.uuid4())[:8]
    device_label = "CPU vs GPU" if device == "both" else device.upper()
    label = f"LLM — {MODELS[model_key]['label']} · {TASKS[task_key]['label']} · {device_label}"

    async def coro():
        await run_llm_job(job_id, model_key, task_key, repeats, warm, effective_prompt, device)

    position = queue_control.enqueue(job_id, "llm", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


async def run_llm_all_job(job_id: str, model_key: str, warm: bool, device: str):
    try:
        devices = ["cpu", "gpu"] if device == "both" else [device]
        jobs[job_id].update({"status": "running", "stage": "baseline",
                             "current_task": "T1", "current_device": devices[0], "partial_response": ""})
        dev_results = {}
        for dev in devices:
            task_results = {}
            for task_key in ["T1", "T2", "T3"]:
                jobs[job_id]["current_task"] = task_key
                jobs[job_id]["current_device"] = dev
                result = await run_llm_measurement(
                    model_key, task_key, jobs, job_id, warm, None, dev)
                task_results[task_key] = result
            dev_results[dev] = task_results

        if device == "both":
            final = {
                "mode": "all_both",
                "model_key": model_key,
                "model_label": MODELS[model_key]["label"],
                "model_params": MODELS[model_key]["params"],
                "warm": warm,
                "device": device,
                "cpu": dev_results["cpu"],
                "gpu": dev_results["gpu"],
                "scope": "Device layer only (GoS1). Network and CPE excluded. No amortised training cost.",
            }
        else:
            final = {
                "mode": "all",
                "model_key": model_key,
                "model_label": MODELS[model_key]["label"],
                "model_params": MODELS[model_key]["params"],
                "warm": warm,
                "device": device,
                "tasks": dev_results[device],
                "scope": "Device layer only (GoS1). Network and CPE excluded. No amortised training cost.",
            }
        save_result("llm", job_id, final)
        jobs[job_id] = {"status": "done", "stage": "done", "result": final}
    except CooldownCancelled:
        jobs[job_id] = {"status": "cancelled", "stage": "cancelled",
                        "error": "Cancelled by operator during cooldown."}
    except Exception as e:
        jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}


@router.post("/llm/run-all", dependencies=[Depends(requires(BATCH_COMPARE))])
async def llm_run_all(
    request: Request,
    model_key: str = Form(...),
    warm: bool = Form(False),
    device: str = Form("gpu"),
):
    if model_key not in MODELS:
        return JSONResponse({"error": "Invalid model"}, status_code=400)
    if device not in ("cpu", "gpu", "both"):
        return JSONResponse({"error": "device must be cpu, gpu, or both"}, status_code=400)

    job_id = str(uuid.uuid4())[:8]
    label = f"LLM All Tasks — {MODELS[model_key]['label']} · {device.upper()}"

    async def coro():
        await run_llm_all_job(job_id, model_key, warm, device)

    position = queue_control.enqueue(job_id, "llm", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


# --- CR-048 · LLM compare-across-models ---
# One prompt × every model in llm.MODELS, graded against a user-supplied
# expected answer, ranked by energy of the correct answers. Headline metric
# is "Wh per correct answer" — mWh/token stays in the table as a supporting
# column because it rewards verbose models and so cannot be the headline.
# Panel = list(MODELS.keys()) so adding/swapping a model in llm.py is
# automatically reflected on /llm/compare without touching this file.

async def run_llm_compare_models_job(job_id: str, prompt: str, expected: str, device: str = "gpu"):
    """Sequentially run prompt across every model in MODELS, grade each, save aggregated result.

    Each model gets its own clean baseline (no cross-model contamination). Grading
    uses llm_grade — substring or leading-integer match, the same rule the
    2026-05-26 probe used to pick these showcase prompts.
    """
    panel = list(MODELS.keys())
    from power import cooldown_between_runs, CooldownCancelled
    from llm import unload_all_loaded_models
    try:
        jobs[job_id].update({
            "status": "running", "stage": "compare_models",
            "total_models": len(panel), "current_model_idx": 0,
            "partial_response": "",
        })
        # Clear any models left over from /llm interactive use before we even
        # measure model #1's baseline — otherwise the "cold reference" we
        # capture is itself contaminated by ~60 W of resident VRAM.
        unloaded = unload_all_loaded_models()
        if unloaded:
            await asyncio.sleep(2)
        rows = []
        floor_reference_w = None  # set after model #1 baseline; used to wait_for_thermal_floor
        cooldowns = []  # diagnostics: how long each inter-model wait took
        for idx, model_key in enumerate(panel, start=1):
            if idx > 1 and floor_reference_w is not None:
                # CRITICAL: unload every previously-run model before waiting.
                # Ollama's default keep_alive holds them in VRAM for ~5 min,
                # which inflates the apparent power floor by ~30-60 W per
                # resident model. Without this the thermal-floor wait can
                # never reach the cold reference and just times out.
                evicted = unload_all_loaded_models()
                jobs[job_id]["stage"] = "cooldown"
                jobs[job_id]["current_model_idx"] = idx
                jobs[job_id]["current_model"] = model_key
                jobs[job_id]["current_model_label"] = MODELS[model_key]["label"]
                # Brief wait for VRAM to actually free (Ollama unload is async).
                if evicted:
                    await asyncio.sleep(3)
                cd = await cooldown_between_runs(
                    fixed_seconds=cfg.load().get("llm_rest_s", 10),
                    reference_w=floor_reference_w,
                    stage="cooldown", jobs=jobs, job_id=job_id,
                    allow_dialog=True,
                )
                cd["evicted_before_wait"] = evicted
                cooldowns.append({"before_model": model_key, **cd})
            jobs[job_id]["current_model_idx"] = idx
            jobs[job_id]["current_model"] = model_key
            jobs[job_id]["current_model_label"] = MODELS[model_key]["label"]
            try:
                m_result = await run_llm_measurement(
                    model_key, "T1",
                    jobs, job_id, warm=False, prompt=prompt, device=device,
                )
                # Capture first model's baseline as the cold-system reference
                # for subsequent thermal-floor waits.
                if floor_reference_w is None:
                    floor_reference_w = (m_result.get("energy") or {}).get("w_base")
                inf = m_result.get("inference") or {}
                en = m_result.get("energy") or {}
                resp = inf.get("response", "") or ""
                ok = llm_grade(expected, resp)
                rows.append({
                    "model_key": model_key,
                    "model_label": MODELS[model_key]["label"],
                    "params": MODELS[model_key]["params"],
                    "response": resp,
                    "output_tokens": inf.get("output_tokens"),
                    "duration_s": inf.get("duration_s"),
                    "tokens_per_sec": inf.get("tokens_per_sec"),
                    "w_base": en.get("w_base"),
                    "w_task": en.get("w_task"),
                    "delta_w": en.get("delta_w"),
                    "delta_e_wh": en.get("delta_e_wh"),
                    "mwh_per_token": en.get("mwh_per_token"),
                    "confidence": en.get("confidence"),
                    "correct": ok,
                })
            except Exception as e:
                rows.append({"model_key": model_key,
                             "model_label": MODELS.get(model_key, {}).get("label", model_key),
                             "params": MODELS.get(model_key, {}).get("params", "?"),
                             "error": str(e), "correct": False})

        correct = [r for r in rows if r.get("correct") and (r.get("delta_e_wh") or 0) > 0]
        cheapest = min(correct, key=lambda r: r["delta_e_wh"]) if correct else None
        final = {
            "mode": "compare_models",
            "prompt": prompt,
            "expected": expected,
            "device": device,
            "models": rows,
            "cheapest_correct_key": cheapest["model_key"] if cheapest else None,
            "panel_pass_rate": round(len(correct) / len(rows), 3) if rows else 0,
            "floor_reference_w": floor_reference_w,
            "cooldowns": cooldowns,
            "scope": "Device layer only (GoS1). Network and CPE excluded. No amortised training cost.",
        }
        save_result("llm", job_id, final)
        jobs[job_id] = {"status": "done", "stage": "done", "result": final}
    except CooldownCancelled:
        jobs[job_id] = {"status": "cancelled", "stage": "cancelled",
                        "error": "Cancelled by operator during cooldown."}
    except Exception as e:
        jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}


@router.post("/llm/compare-models", dependencies=[Depends(requires(BATCH_COMPARE))])
async def llm_compare_models(
    request: Request,
    prompt: str = Form(...),
    expected: str = Form(...),
    device: str = Form("gpu"),
):
    """Member 'Try your own' for the compare-across-models card."""
    prompt = (prompt or "").strip()
    expected = (expected or "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt is required"}, status_code=400)
    if not expected:
        return JSONResponse({"error": "expected answer is required (grading needs ground truth)"},
                            status_code=400)
    if device not in ("cpu", "gpu"):
        return JSONResponse({"error": "device must be cpu or gpu"}, status_code=400)
    if len(prompt) > 2000:
        return JSONResponse({"error": "prompt too long (max 2000 chars)"}, status_code=400)

    job_id = str(uuid.uuid4())[:8]
    label = f"LLM Compare · {prompt[:50]}{'…' if len(prompt) > 50 else ''}"

    async def coro():
        await run_llm_compare_models_job(job_id, prompt, expected, device)

    position = queue_control.enqueue(job_id, "llm", label, coro, request=request,
                                     page="/llm/compare")
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


# Hardcoded showcase data from the 2026-05-26 probe (mean of 3 reps per cell).
# Wh on these cards is *estimated* (wall_s × 25 W / 3600) because the probe
# used direct Ollama API calls rather than the production P110 pipeline.
# Backfilling these three with real P110 runs via /llm/compare-models is a
# follow-up; the page renderer marks the source per row.
# Probe data: /tmp/llm_probe/results_20260526_174852.jsonl
#
# NOTE (2026-05-27 — S30 ladder refresh): the rows below reference the
# PREVIOUS panel — `mistral` (7B) and `gemma3:12b` were retired in favour
# of `qwen3:4b` and `mistral-nemo:12b`. Data preserved as a historical
# snapshot; a re-probe of the new 5-model panel via /llm/compare-models
# is the planned follow-up that will replace this dict.
_LLM_COMPARE_SHOWCASE = {
    't2_count': {
        'label': 'Strawberry (the meme)',
        'prompt': "How many times does the letter R appear in the word 'strawberry'? Output only the number.",
        'expected': '3',
        'tagline': 'The famous LLM-fails-at-letter-counting prompt. Classic tokenization trap.',
        'rows': [
            {'model': 'tinyllama',        'params': '1.1B', 'ok': False, 'ans': 'The program should output the number of occurrences of the letter "R" in the word "strawberry". It can be easily done by using a loop that…', 'tok': 159,  'wall': 1.49,  'wh_measured': -0.0003, 'flag': '🔴'},
            {'model': 'qwen3:1.7b',       'params': '1.7B', 'ok': True,  'ans': 'The word "strawberry" is spelled as: **S-T-R-A-W-B-E-R-R-Y**. \n\nBreaking it down letter by letter:\n- S, T, R, A, W, B, E, R, R, Y.\n\nCountin…',           'tok': 677,  'wall': 6.09,  'wh_measured':  0.1750, 'flag': '🟡'},
            {'model': 'qwen3:4b',         'params': '4B',   'ok': True,  'ans': '3',                                                                                                                                                  'tok': 1509, 'wall': 19.20, 'wh_measured':  1.1452, 'flag': '🟢'},
            {'model': 'qwen3:8b',         'params': '8B',   'ok': True,  'ans': '3',                                                                                                                                                  'tok': 467,  'wall': 11.05, 'wh_measured':  0.5834, 'flag': '🟢'},
            {'model': 'mistral-nemo:12b', 'params': '12B',  'ok': False, 'ans': 'The letter R appears 2 times in the word "strawberry".',                                                                                              'tok': 16,   'wall': 2.73,  'wh_measured':  0.0045, 'flag': '🔴'},
            {'model': 'phi4',             'params': '14B',  'ok': False, 'ans': '2',                                                                                                                                                  'tok': 2,    'wall': 2.15,  'wh_measured':  0.0027, 'flag': '🔴'},
            {'model': 'gpt-oss:20b',      'params': '20B',  'ok': True,  'ans': '3',                                                                                                                                                  'tok': 153,  'wall': 10.28, 'wh_measured':  0.2888, 'flag': '🟢'},
        ],
    },
    't1_logic': {
        'label': 'Logic (Carol)',
        'prompt': 'Alice is older than Bob. Bob is older than Carol. Who is youngest? Answer with one name.',
        'expected': 'Carol',
        'tagline': "All models that pass give the same one-word answer — energy varies, output doesn't.",
        'rows': [
            {'model': 'tinyllama',        'params': '1.1B', 'ok': False, 'ans': 'The youngest person in the given statement is not named, so no single name can be used to identify them. The answer with one name should be…',     'tok': 35,  'wall': 1.04, 'wh_measured':  0.0000, 'flag': '🔴'},
            {'model': 'qwen3:1.7b',       'params': '1.7B', 'ok': True,  'ans': 'Carol is the youngest. \n\n**Step-by-Step Explanation:**\n1. **Given Relationships:**\n   - Alice > Bob (Alice is older than Bob)\n   - Bob > Ca…',  'tok': 391, 'wall': 4.10, 'wh_measured':  0.0507, 'flag': '🟡'},
            {'model': 'qwen3:4b',         'params': '4B',   'ok': True,  'ans': 'Carol',                                                                                                                                            'tok': 717, 'wall': 10.00,'wh_measured':  0.4993, 'flag': '🟢'},
            {'model': 'qwen3:8b',         'params': '8B',   'ok': True,  'ans': 'Carol',                                                                                                                                            'tok': 200, 'wall': 6.25, 'wh_measured':  0.1739, 'flag': '🟡'},
            {'model': 'mistral-nemo:12b', 'params': '12B',  'ok': True,  'ans': 'Carol',                                                                                                                                            'tok': 3,   'wall': 2.34, 'wh_measured':  0.0066, 'flag': '🔴'},
            {'model': 'phi4',             'params': '14B',  'ok': True,  'ans': 'Carol is the youngest. Given that Alice is older than Bob and Bob is older than Carol, it follows that Carol is younger than both Alice and…',    'tok': 39,  'wall': 3.13, 'wh_measured':  0.0163, 'flag': '🔴'},
            {'model': 'gpt-oss:20b',      'params': '20B',  'ok': True,  'ans': 'Carol',                                                                                                                                            'tok': 44,  'wall': 7.30, 'wh_measured':  0.1320, 'flag': '🟡'},
        ],
    },
    't1_addition': {
        'label': 'Addition (50)',
        'prompt': 'What is 25 + 17 + 8? Output only the number.',
        'expected': '50',
        'tagline': "Three-term addition. Most models do it; some can't.",
        'rows': [
            {'model': 'tinyllama',        'params': '1.1B', 'ok': False, 'ans': 'The input string "25 + 17 + 8" is not understood by this program. Please try again or use different inputs to get a correct output.', 'tok': 35,  'wall': 1.03, 'wh_measured': -0.0016, 'flag': '🔴'},
            {'model': 'qwen3:1.7b',       'params': '1.7B', 'ok': True,  'ans': '50',                                                                                                                                  'tok': 295, 'wall': 3.44, 'wh_measured':  0.0463, 'flag': '🟡'},
            {'model': 'qwen3:4b',         'params': '4B',   'ok': True,  'ans': '50',                                                                                                                                  'tok': 583, 'wall': 8.39, 'wh_measured':  0.3507, 'flag': '🟡'},
            {'model': 'qwen3:8b',         'params': '8B',   'ok': True,  'ans': '50',                                                                                                                                  'tok': 295, 'wall': 7.92, 'wh_measured':  0.3098, 'flag': '🟡'},
            {'model': 'mistral-nemo:12b', 'params': '12B',  'ok': False, 'ans': '40',                                                                                                                                  'tok': 3,   'wall': 2.36, 'wh_measured':  0.0033, 'flag': '🔴'},
            {'model': 'phi4',             'params': '14B',  'ok': True,  'ans': '50',                                                                                                                                  'tok': 2,   'wall': 2.12, 'wh_measured':  0.0012, 'flag': '🔴'},
            {'model': 'gpt-oss:20b',      'params': '20B',  'ok': True,  'ans': '50',                                                                                                                                  'tok': 59,  'wall': 7.27, 'wh_measured':  0.1329, 'flag': '🟡'},
        ],
    },
}


@router.get("/llm/compare", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def llm_compare_page(request: Request):
    """Hybrid showcase + member 'Try your own' for energy-per-correct-answer.

    Anonymous: three hardcoded demo cards (probe data, estimated Wh).
    Member (BATCH_COMPARE): textarea + expected-answer input → runs on all 5
    models sequentially with P110 measurement, renders into the same card.
    """
    can_batch = can(audience.tier(request), BATCH_COMPARE)
    lk_batch_class = _lock_class(request, BATCH_COMPARE)
    lk_batch_badge = _lock_badge_html(request, BATCH_COMPARE,
                                      "Try your own prompt — Members only")
    dis_batch = _disabled_attr(request, BATCH_COMPARE)

    import json as _json
    showcase_js = _json.dumps(_LLM_COMPARE_SHOWCASE)
    panel_n     = len(MODELS)
    panel_list  = " &middot; ".join(f"{m['label']} ({m['params']})" for m in MODELS.values())
    # JS array of params strings, ordered by size — drives the bust-card
    # "bigger-was-wrong" detection. Derived from MODELS so adding a model
    # in llm.py extends this without an edit here.
    size_order_js = _json.dumps([m["params"] for m in MODELS.values()])

    return _bake_durations(ui.render_page(request, "LLM · Compare across models", head=f"""    <script src="{CHARTJS_URL}"></script>
    <script src="/static/wl-charts.js"></script>
""", styles=f"""
        *{{box-sizing:border-box;margin:0;padding:0}}
        body{{font-family:monospace;background:var(--bg);color:var(--text);
              max-width:920px;margin:0 auto;padding:2rem}}
        h1{{color:var(--accent);font-size:1.6rem;margin-bottom:0.25rem}}
        .subtitle{{color:var(--text-3);font-size:0.8rem;margin-bottom:1.5rem}}
        .demo-tabs{{display:flex;gap:0.5rem;margin-bottom:1.25rem;flex-wrap:wrap}}
        .demo-tabs button{{background:none;color:var(--text-3);border:1px solid var(--border-3);
                           padding:0.5rem 0.9rem;cursor:pointer;font-family:monospace;font-size:0.78rem;margin:0}}
        .demo-tabs button:hover{{border-color:var(--accent);color:var(--text)}}
        .demo-tabs button.active{{border-color:var(--accent);color:var(--accent);background:var(--accent-soft)}}
        .prompt-card{{border:1px solid var(--border);padding:1rem 1.25rem;margin-bottom:1.25rem;
                      background:var(--panel-2)}}
        .label-sm{{color:var(--text-5);font-size:0.65rem;text-transform:uppercase;
                   letter-spacing:0.06em;margin-bottom:0.5rem}}
        .prompt-text{{color:var(--text-2);font-size:0.95rem;line-height:1.5}}
        .prompt-meta{{margin-top:0.6rem;color:var(--text-3);font-size:0.78rem}}
        .prompt-meta b{{color:var(--accent)}}
        .hero{{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1.25rem}}
        @media(max-width:640px){{.hero{{grid-template-columns:1fr}}}}
        .hero-card{{border:1px solid var(--border);padding:1.1rem;background:var(--panel-2)}}
        .hero-card .big{{color:var(--accent);font-size:2rem;font-weight:bold;line-height:1.1}}
        .hero-card .sub{{color:var(--text-3);font-size:0.78rem;margin-top:0.4rem;line-height:1.5}}
        .hero-card.warn .big{{color:var(--warn);font-size:1rem;line-height:1.4}}
        .hero-card.warn{{border-color:var(--warn)}}
        table{{width:100%;border-collapse:collapse;font-size:0.8rem;margin-bottom:1.25rem}}
        th{{text-align:left;padding:0.5rem 0.6rem;color:var(--text-4);
            border-bottom:1px solid var(--border-3);font-weight:normal;
            text-transform:uppercase;letter-spacing:0.05em;font-size:0.68rem}}
        th.num,td.num{{text-align:right;font-variant-numeric:tabular-nums}}
        td{{padding:0.6rem;border-bottom:1px solid var(--border-2);vertical-align:middle}}
        tr.correct td.model,tr.correct td.answer{{color:var(--text)}}
        tr.wrong td.model,tr.wrong td.answer{{color:var(--text-4)}}
        tr.noisy td{{color:var(--text-4)!important}}
        tr.noisy td.model{{color:var(--text-3)!important;font-style:italic}}
        tr.noisy{{background:transparent!important}}
        td.answer{{max-width:340px}}
        .answer-wrap{{max-height:5.5em;overflow-y:auto;white-space:pre-wrap;word-break:break-word;
                      line-height:1.45;padding-right:0.25rem;scrollbar-width:thin;
                      scrollbar-color:var(--border-3) transparent}}
        .answer-wrap::-webkit-scrollbar{{width:6px}}
        .answer-wrap::-webkit-scrollbar-thumb{{background:var(--border-3);border-radius:3px}}
        tr.cheapest{{background:var(--accent-soft)}}
        tr.cheapest td.model{{color:var(--accent);font-weight:bold}}
        .pill{{display:inline-block;font-size:0.7rem;padding:0.1rem 0.45rem;border-radius:2px}}
        .pill.ok{{color:var(--accent);border:1px solid var(--accent)}}
        .pill.bad{{color:var(--err);border:1px solid var(--err)}}
        .answer-q{{color:var(--text-3);font-style:italic}}
        .crown{{color:var(--accent)}}
        .ratio{{color:var(--accent);font-weight:bold}}
        .headline{{border-left:3px solid var(--accent);padding:0.9rem 1.1rem;margin-bottom:1.5rem;
                   background:var(--panel-2);color:var(--text-2);line-height:1.7;font-size:0.88rem}}
        .headline b{{color:var(--accent)}}
        .try{{margin-top:2rem;padding-top:1.5rem;border-top:1px solid var(--border)}}
        .try h2{{color:var(--accent);font-size:1.05rem;margin-bottom:0.4rem}}
        .try .desc{{color:var(--text-3);font-size:0.82rem;margin-bottom:1rem;line-height:1.6}}
        textarea,input[type=text]{{width:100%;background:#0f0f0f;border:1px solid var(--border-3);
                                    border-left:2px solid #00ff9966;color:var(--text-2);
                                    font-family:monospace;font-size:0.85rem;padding:0.75rem;
                                    resize:vertical}}
        textarea:focus,input[type=text]:focus{{border-color:var(--accent);outline:none}}
        button.run{{background:var(--accent);color:#000;border:none;padding:0.75rem 2rem;
                    cursor:pointer;font-family:monospace;font-size:0.95rem;margin-top:0.85rem}}
        button.run:disabled{{background:var(--border);color:var(--text-3);cursor:not-allowed}}
        button.run:hover:not(:disabled){{background:var(--accent-hover)}}
        a.back{{color:var(--text-3);text-decoration:none;font-size:0.82rem;
                display:inline-block;margin-top:2rem}}
        a.back:hover{{color:var(--accent)}}
        details{{margin-top:1.5rem;color:var(--text-3);font-size:0.78rem;
                 border-top:1px solid var(--border);padding-top:1rem}}
        summary{{cursor:pointer;color:var(--text-3)}}
        summary:hover{{color:var(--accent)}}
        details p{{margin-top:0.5rem;line-height:1.6}}
        {_LOCK_STYLES}
""", body=f"""
    <a href="/llm" style="color:var(--text-3);text-decoration:none;font-size:0.82rem;
        margin-left:0.75rem;margin-bottom:1.5rem;display:inline-block;
        vertical-align:middle;position:relative;top:-2px;transition:color 0.2s"
        onmouseover="this.style.color='#00ff99'" onmouseout="this.style.color='#777'">&larr; /llm</a>
    <h1>LLM &middot; Compare across models</h1>
    <div class="subtitle">Energy cost of correct answers. Device layer only (GoS1). Network and CPE excluded.</div>

    <div class="demo-tabs" id="tabs"></div>

    <div class="prompt-card">
        <div class="label-sm">Prompt</div>
        <div class="prompt-text" id="prompt-text"></div>
        <div class="prompt-meta">Expected: <b id="expected"></b> &middot; Panel: 5 models, mean of 3 reps each (2026-05-26 probe)</div>
    </div>

    <div class="hero">
        <div class="hero-card" id="hero-cheap">
            <div class="label-sm">Cheapest correct answer</div>
            <div class="big" id="hero-cheap-big"></div>
            <div class="sub" id="hero-cheap-sub"></div>
        </div>
        <div class="hero-card warn" id="hero-bust">
            <div class="label-sm">The size &ne; smarts finding</div>
            <div class="big" id="hero-bust-big"></div>
            <div class="sub" id="hero-bust-sub"></div>
        </div>
    </div>

    <div class="label-sm">Same prompt, all models &mdash; ranked by energy of a correct answer</div>
    <table>
        <thead>
            <tr><th>model</th><th>answer</th><th>&#10003;/&#10007;</th><th>conf</th>
                <th class="num">tokens</th><th class="num">wall</th>
                <th class="num">mWh/tok</th><th class="num">Wh</th>
                <th class="num">vs best</th></tr>
        </thead>
        <tbody id="rows"></tbody>
    </table>

    <div class="headline" id="headline"></div>

    <div id="charts-wrap" style="margin-bottom:1.5rem;display:none">
        <div class="label-sm">Energy vs model size (correct answers only) <span id="charts-source" style="color:var(--text-5)"></span></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
            <div style="border:1px solid var(--border);padding:0.75rem;background:var(--panel-2)">
                <div style="color:var(--text-3);font-size:0.7rem;text-align:center;margin-bottom:0.25rem">Total Wh per correct answer</div>
                <div style="position:relative;height:240px"><canvas id="chart-wh"></canvas></div>
            </div>
            <div style="border:1px solid var(--border);padding:0.75rem;background:var(--panel-2)">
                <div style="color:var(--text-3);font-size:0.7rem;text-align:center;margin-bottom:0.25rem">mWh per output token</div>
                <div style="position:relative;height:240px"><canvas id="chart-mwh"></canvas></div>
            </div>
        </div>
        <div id="charts-note" style="color:var(--text-5);font-size:0.72rem;margin-top:0.5rem;line-height:1.5"></div>
    </div>
    <div id="charts-hint" style="margin-bottom:1.5rem;color:var(--text-5);font-size:0.78rem;
         border-left:2px solid var(--border);padding-left:0.85rem;display:none">
        Energy-vs-size plot appears when at least 3 models answer correctly.
    </div>

    {lk_batch_badge}
    <div class="try {lk_batch_class}">
        <h2>Try your own prompt</h2>
        <div class="desc">
            Runs your prompt across all {panel_n} models sequentially with P110 power measurement.
            Each model gets its own clean baseline. Between models the runner actively polls power and waits for the system to return to within &plusmn;3 W of model #1's baseline (max 120 s cap) so heat from a verbose model can't contaminate the next reading. Total wall time depends on how hot each model leaves the GPU.
        </div>
        <div class="label-sm">Prompt</div>
        <textarea id="userPrompt" rows="3"{dis_batch}
            placeholder="e.g. What is 47 multiplied by 83? Output only the number."></textarea>
        <div class="label-sm" style="margin-top:0.85rem">Expected answer (used to grade &#10003;/&#10007;)</div>
        <input type="text" id="userExpected"{dis_batch}
            placeholder="e.g. 3901">
        <div class="label-sm" style="margin-top:0.5rem;color:var(--text-5)">
            Substring match, case-insensitive. For numeric answers, leading-integer match.
        </div>
        <button class="run" id="runBtn" onclick="runCompare()"{dis_batch}>Run on all {panel_n} models &rarr;</button>
        <div id="run-status" style="margin-top:1.25rem"></div>
    </div>

    <details>
        <summary>Methodology &amp; scope</summary>
        <p><b>What's measured (live runs):</b> {meter_display_name()} wall-power at 1 Hz, baseline before each model (10 polls), &Delta;W &times; &Delta;t &rarr; Wh, mWh/output_token, Traffic Light Confidence per the CR-028 CI model. Same protocol as the existing /llm endpoint.</p>
        <p><b>What's estimated (showcase cards):</b> Wh = wall_s &times; 25 W / 3600. The 25 W figure is a rough average power delta observed on GoS1 across Ollama 1B&ndash;20B models. Production P110 backfill of the three showcase cards is a follow-up (CR-048 phase 2).</p>
        <p><b>Why "Wh per correct answer" is the headline:</b> mWh/token rewards verbose models &mdash; a model that "thinks out loud" for 100 tokens to reach a 1-token answer looks more efficient per token than a model that answers in 1 token, even though it burned 100&times; the energy. The headline metric is the energy cost of <em>correctness</em>. mWh/token stays as a supporting column because it's the canonical inference-cost figure operators recognise.</p>
        <p><b>{panel_n}-model panel:</b> {panel_list}. All on GoS1 (Ryzen 9 7900 + RX 7800 XT, Ollama 0.20.2). Panel reflects the current <code>llm.MODELS</code> dict; the showcase tabs are frozen on the older 5-model probe and will be re-baselined when a fresh probe of the new panel runs.</p>
        <p><b>Grading:</b> Tolerant &mdash; substring match (case-insensitive) or leading-integer match. Same rule used by the 2026-05-26 probe to select these prompts.</p>
    </details>

    <a class="back" href="/llm">&larr; /llm (single-model lab)</a>

    <script>
    const SHOWCASE = {showcase_js};
    const CAN_BATCH = {('true' if can_batch else 'false')};
    const wh = w => Math.round((w * 25 / 3600) * 10000) / 10000;
    let pollTimer = null;
    let chartWh = null, chartMwh = null;
    // CR-050 follow-up — local ticker so the cooldown counter feels smooth
    // even though the server-side poll only writes a fresh cooldown_waited_s
    // every 1 s and the UI only polls /job/{id} every 2 s.
    let cooldownTicker = null;
    let cooldownState = null;
    let cooldownLog = [];   // finished inter-model waits, persisted across stages

    function stopCooldownTicker() {{
        if (cooldownTicker) {{ clearInterval(cooldownTicker); cooldownTicker = null; }}
        cooldownState = null;
    }}

    function renderRunStatus() {{
        const s = cooldownState;
        if (!s) return;
        const msg = s.stage === 'queued'
            ? 'In queue (position ' + (s.qpos || '?') + ')…'
            : (s.mi && s.mt
                ? 'Model ' + s.mi + '/' + s.mt + (s.ml ? ' — ' + s.ml : '') + ' · ' + s.stage
                : 'Running… ' + s.stage);
        const watts = s.watts != null ? ' · ' + Number(s.watts).toFixed(1) + ' W' : '';
        let cdInfo = '';
        if (s.stage === 'cooldown' && s.cdWaited != null) {{
            const liveS = s.cdWaited + (Date.now() - s.cdLocalStart) / 1000;
            const ref = s.cdRef != null ? Number(s.cdRef).toFixed(1) + 'W' : '?';
            cdInfo = ' · waiting ' + liveS.toFixed(1) + 's for floor (target ≤ ' + ref + ' +3W)';
        }}
        let logInfo = '';
        if (cooldownLog.length) {{
            logInfo = '<div style="color:var(--text-4);font-size:0.72rem;margin-top:0.25rem">'
                    + '⏳ Cooldowns done: '
                    + cooldownLog.map(function(w) {{ return Number(w).toFixed(0) + 's'; }}).join(' · ')
                    + '</div>';
        }}
        const el = document.getElementById('run-status');
        if (el) el.innerHTML =
            '<div style="color:var(--warn);font-size:0.85rem">' + msg + watts + cdInfo + '</div>' + logInfo;
    }}

    function paramsToNumeric(p) {{
        // "1.1B" -> 1.1, "12B" -> 12, "20B" -> 20
        return parseFloat(String(p).replace(/[^\\d.]/g, '')) || 0;
    }}

    function renderCharts(payload) {{
        const wrap = document.getElementById('charts-wrap');
        const hint = document.getElementById('charts-hint');
        const TRUSTED = new Set(['🟢','🟡']);
        // Plot only ✓ AND not 🔴 AND positive Wh — same filter the
        // 'cheapest correct' card uses; we don't want noisy points
        // distorting the energy-vs-size curve.
        const correct = payload.rows.filter(r => r.ok && TRUSTED.has(r.flag || '🟢') && r.whEst > 0);
        if (correct.length < 3) {{
            wrap.style.display = 'none';
            hint.style.display = '';
            if (chartWh) {{ chartWh.destroy(); chartWh = null; }}
            if (chartMwh) {{ chartMwh.destroy(); chartMwh = null; }}
            return;
        }}
        hint.style.display = 'none';
        wrap.style.display = '';

        document.getElementById('charts-source').textContent = '· ' + payload.sourceLabel;
        const wrong = payload.rows.filter(r => !r.ok);
        const noteParts = ['Plotting ' + correct.length + ' of ' + payload.rows.length + ' models that produced the correct answer.'];
        if (wrong.length) {{
            noteParts.push((wrong.length === 1 ? '1 model' : wrong.length + ' models') +
                           ' excluded for incorrect answers (' +
                           wrong.map(r => r.model.replace(':latest','')).join(', ') + ').');
        }}
        if ((payload.sourceLabel || '').toLowerCase().indexOf('estimated') >= 0) {{
            noteParts.push('Wh here is estimated from wall_s × ~25 W; live runs use direct P110 measurement.');
        }}
        document.getElementById('charts-note').textContent = noteParts.join(' ');

        const sorted = [...correct].sort((a,b) => paramsToNumeric(a.params) - paramsToNumeric(b.params));
        const whPoints = sorted.map(r => ({{x: paramsToNumeric(r.params), y: r.whEst}}));
        const mwhPoints = sorted.map(r => {{
            const tok = r.tok || 0;
            return {{x: paramsToNumeric(r.params), y: tok > 0 ? (r.whEst * 1000 / tok) : 0}};
        }});

        if (chartWh) {{ chartWh.destroy(); chartWh = null; }}
        chartWh = WlCharts.line({{
            canvas: document.getElementById('chart-wh'),
            datasets: [{{label: 'Wh per correct answer', points: whPoints, color: 'accent', tension: 0.15, pointRadius: 5}}],
            xLabel: 'parameters (B)', yLabel: 'Wh', yUnit: 'Wh',
        }});

        if (chartMwh) {{ chartMwh.destroy(); chartMwh = null; }}
        chartMwh = WlCharts.line({{
            canvas: document.getElementById('chart-mwh'),
            datasets: [{{label: 'mWh per output token', points: mwhPoints, color: 'warn', tension: 0.15, pointRadius: 5}}],
            xLabel: 'parameters (B)', yLabel: 'mWh/tok', yUnit: 'mWh/tok',
        }});
    }}

    const tabs = document.getElementById('tabs');
    const order = ['t2_count','t1_logic','t1_addition'];
    order.forEach(k => {{
        const b = document.createElement('button');
        b.textContent = SHOWCASE[k].label;
        b.id = 'tab-' + k;
        b.onclick = () => renderShowcase(k);
        tabs.appendChild(b);
    }});

    function renderShowcase(key) {{
        const d = SHOWCASE[key];
        order.forEach(k => document.getElementById('tab-'+k).classList.toggle('active', k === key));
        // Prefer per-row wh_measured (real P110 from showcase regeneration);
        // fall back to wall × 25 W estimate if a legacy row lacks it.
        const rows = d.rows.map(r => ({{...r, whEst: (r.wh_measured != null ? r.wh_measured : wh(r.wall))}}));
        renderCompareCard({{
            promptText: d.prompt, expected: d.expected,
            rows: rows, tagline: d.tagline, sourceLabel: 'Showcase (estimated)'
        }});
    }}

    function renderCompareCard(payload) {{
        document.getElementById('prompt-text').textContent = payload.promptText;
        document.getElementById('expected').textContent = payload.expected;

        const TRUSTED = new Set(['🟢','🟡']);
        const isTrust = r => TRUSTED.has(r.flag || '🟢');
        const correct = payload.rows.filter(r => r.ok).sort((a,b) => a.whEst - b.whEst);
        const wrong   = payload.rows.filter(r => !r.ok).sort((a,b) => a.whEst - b.whEst);
        const sorted  = [...correct, ...wrong];
        // 🔴 rows are visible in the table but excluded from the cheapest-correct
        // pick, the bust-card pick, and the chart — their delta_w sits inside the
        // baseline noise so a tiny Wh is just measurement noise, not efficiency.
        const trustedCorrect = correct.filter(r => isTrust(r) && r.whEst > 0);
        const cheapest = trustedCorrect[0] || null;

        if (cheapest) {{
            document.getElementById('hero-cheap-big').textContent = cheapest.whEst.toFixed(4) + ' Wh';
            document.getElementById('hero-cheap-sub').innerHTML =
                '<b style="color:var(--accent)">' + cheapest.model.replace(':latest','') + '</b> &middot; ' +
                cheapest.params + ' &middot; ' + cheapest.tok + ' tokens &middot; ' + cheapest.wall.toFixed(2) + 's';
        }} else {{
            document.getElementById('hero-cheap-big').textContent = '—';
            document.getElementById('hero-cheap-sub').textContent = 'No model in the panel got it right.';
        }}

        const sizeOrder = {size_order_js};
        const sIdx = p => sizeOrder.indexOf(p);
        let bustHead = '', bustDetail = '';
        const biggerWrong = payload.rows.filter(r => !r.ok && cheapest && sIdx(r.params) > sIdx(cheapest.params));
        if (biggerWrong.length) {{
            const bw = biggerWrong[biggerWrong.length-1];
            bustHead = bw.model.replace(':latest','') + ' (' + bw.params + ') was wrong; ' +
                       cheapest.model.replace(':latest','') + ' (' + cheapest.params + ') was right';
            bustDetail = 'A larger model (' + bw.params + ') failed at this prompt while a smaller one (' + cheapest.params + ') succeeded. More parameters did not buy more intelligence here.';
        }} else if (cheapest && trustedCorrect.length > 1) {{
            const priciest = trustedCorrect[trustedCorrect.length-1];
            const ratio = (priciest.whEst / cheapest.whEst).toFixed(1);
            bustHead = 'Same answer, ' + ratio + '&times; more energy';
            bustDetail = priciest.model.replace(':latest','') + ' (' + priciest.params + ') and ' + cheapest.model.replace(':latest','') + ' (' + cheapest.params + ') both answered correctly &mdash; but the larger model used ' + ratio + '&times; the energy for the identical output.';
        }} else {{
            bustHead = 'No size-vs-smarts split on this prompt';
            bustDetail = payload.tagline || '';
        }}
        document.getElementById('hero-bust-big').innerHTML = bustHead;
        document.getElementById('hero-bust-sub').innerHTML = bustDetail;

        const tbody = document.getElementById('rows');
        tbody.innerHTML = '';
        sorted.forEach(r => {{
            const tr = document.createElement('tr');
            const flag = r.flag || '🟢';
            const trusted = isTrust(r);
            tr.className = r.ok ? (trusted ? 'correct' : 'correct noisy') : 'wrong';
            if (r === cheapest) tr.classList.add('cheapest');
            // 🔴 rows: hide the ratio (it would compare noise to signal)
            const ratio = r.ok && trusted && cheapest ? (r.whEst / cheapest.whEst).toFixed(1) + '&times;' :
                          (r.ok && !trusted ? '<span title="noisy reading, see conf column">&mdash;</span>' : '&mdash;');
            const crown = (r === cheapest) ? ' <span class="crown">&#9733;</span>' : '';
            // A negative mWh/token means the task drew below the measured idle
            // floor — a sign-flipped noise artifact on a sub-floor model, and
            // always a 🔴 row. Show an em-dash (with a hover note) instead of a
            // misleading negative; the confidence column already carries the 🔴.
            const mwhTok = (r.tok > 0 && r.whEst > 0)
                ? (r.whEst * 1000 / r.tok).toFixed(2)
                : (r.whEst <= 0
                    ? '<span title="energy below measurement floor — not distinguishable from idle">&mdash;</span>'
                    : '&mdash;');
            tr.innerHTML =
                '<td class="model">' + escapeHTML(r.model.replace(':latest','')) +
                  ' <span style="color:var(--text-5);font-size:0.7rem">(' + r.params + ')</span>' + crown + '</td>' +
                '<td class="answer ' + (r.ok ? '' : 'answer-q') + '"><div class="answer-wrap">' + escapeHTML(String(r.ans)) + '</div></td>' +
                '<td>' + (r.ok ? '<span class="pill ok">&#10003;</span>' : '<span class="pill bad">&#10007;</span>') + '</td>' +
                '<td title="Traffic Light Confidence (CR-028) — 🟢 repeatable, 🟡 weak, 🔴 unreliable / contamination">' + flag + '</td>' +
                '<td class="num">' + (r.tok != null ? r.tok : '&mdash;') + '</td>' +
                '<td class="num">' + (r.wall != null ? r.wall.toFixed(2) + 's' : '&mdash;') + '</td>' +
                '<td class="num" style="color:var(--text-4)">' + mwhTok + '</td>' +
                '<td class="num">' + r.whEst.toFixed(4) + '</td>' +
                '<td class="num">' + ratio + '</td>';
            tbody.appendChild(tr);
        }});

        let h = '';
        if (cheapest) {{
            h = '<b>' + cheapest.model.replace(':latest','') + ' (' + cheapest.params + ')</b>' +
                ' produced the correct answer for <b>' + cheapest.whEst.toFixed(4) + ' Wh</b>.';
            if (trustedCorrect.length > 1) {{
                const priciest = trustedCorrect[trustedCorrect.length-1];
                const ratio = (priciest.whEst / cheapest.whEst).toFixed(1);
                h += ' The most expensive correct run (' + priciest.model.replace(':latest','') + ') used <span class="ratio">' + ratio + '&times; more energy</span> for the same answer.';
            }}
        }} else {{
            h = 'No model in the panel got this prompt right at all &mdash; try a different prompt or look at the showcase examples.';
        }}
        document.getElementById('headline').innerHTML =
            '<div class="label-sm">What this tells you</div>' + h +
            ' <span style="color:var(--text-5)">[' + payload.sourceLabel + ']</span>';

        renderCharts(payload);
    }}

    function escapeHTML(s) {{
        return String(s).replace(/[&<>"']/g, c => ({{
            '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
        }}[c]));
    }}

    async function runCompare() {{
        if (!CAN_BATCH) return;
        stopCooldownTicker();
        const prompt = document.getElementById('userPrompt').value.trim();
        const expected = document.getElementById('userExpected').value.trim();
        if (!prompt || !expected) {{
            document.getElementById('run-status').innerHTML =
                '<div style="color:var(--err);font-size:0.85rem">Both prompt and expected answer are required.</div>';
            return;
        }}
        const btn = document.getElementById('runBtn');
        btn.disabled = true;
        document.getElementById('run-status').innerHTML =
            '<div style="color:var(--warn);font-size:0.85rem">Queued &mdash; running across {panel_n} models with active-probe thermal floor wait between each&hellip;</div>';
        const form = new FormData();
        form.append('prompt', prompt);
        form.append('expected', expected);
        form.append('device', 'gpu');
        try {{
            const resp = await fetch('/llm/compare-models', {{method:'POST', body:form}});
            const data = await resp.json();
            if (data.job_id) {{
                pollCompare(data.job_id);
            }} else {{
                document.getElementById('run-status').innerHTML =
                    '<div style="color:var(--err)">' + (data.error || 'Error') + '</div>';
                btn.disabled = false;
            }}
        }} catch(e) {{
            document.getElementById('run-status').innerHTML =
                '<div style="color:var(--err)">Failed: ' + e + '</div>';
            btn.disabled = false;
        }}
    }}

    async function pollCompare(jobId) {{
        try {{
            const resp = await fetch('/llm/job/' + jobId);
            const data = await resp.json();
            if (data.status === 'done' && data.result) {{
                stopCooldownTicker();
                const r = data.result;
                const rows = (r.models || []).map(m => ({{
                    model: m.model_key, params: m.params, ok: !!m.correct,
                    ans: m.error ? '(error: ' + m.error + ')' : (m.response || '(empty)'),
                    tok: m.output_tokens || 0,
                    wall: m.duration_s || 0,
                    whEst: m.delta_e_wh || 0,
                    flag: (m.confidence || {{}}).flag || '🟢',
                }}));
                renderCompareCard({{
                    promptText: r.prompt, expected: r.expected,
                    rows: rows, tagline: '', sourceLabel: 'Live (P110 measured)'
                }});
                document.getElementById('run-status').innerHTML =
                    '<div style="color:var(--accent);font-size:0.85rem">&#10003; Done. Result rendered above. ' +
                    '<a href="/results/llm/' + jobId + '/download.json" style="color:var(--accent)">&darr; JSON</a></div>'
                    + wlCooldownSummary(r.cooldowns);
                document.getElementById('runBtn').disabled = false;
                document.querySelector('.prompt-card').scrollIntoView({{behavior:'smooth', block:'start'}});
            }} else if (data.status === 'error') {{
                stopCooldownTicker();
                document.getElementById('run-status').innerHTML =
                    '<div style="color:var(--err);font-size:0.85rem">Error: ' + (data.error || 'unknown') + '</div>';
                document.getElementById('runBtn').disabled = false;
            }} else {{
                const stage = data.stage || 'queued';
                if (stage === 'awaiting_cooldown_decision') {{
                    wlCooldownDialog(jobId, data.cooldown_decision_options);
                }} else {{ wlCooldownDialogClose(); }}
                const cdVal = data.cooldown_waited_s;
                const prev = cooldownState;
                const cdChanged = !prev || prev.cdWaited !== cdVal;
                // Reset the log at run start (model 1 / queued); record a finished
                // wait each time we leave the 'cooldown' stage so it persists.
                if (!data.current_model_idx || data.current_model_idx <= 1) cooldownLog = [];
                if (prev && prev.stage === 'cooldown' && stage !== 'cooldown' && prev.cdWaited != null) {{
                    cooldownLog.push(prev.cdWaited);
                }}
                cooldownState = {{
                    stage: stage,
                    qpos:  data.queue_position,
                    mi:    data.current_model_idx,
                    mt:    data.total_models,
                    ml:    data.current_model_label,
                    watts: data.watts,
                    cdWaited: cdVal,
                    cdRef:    data.cooldown_reference_w,
                    cdLocalStart: cdChanged ? Date.now() : (prev ? prev.cdLocalStart : Date.now()),
                }};
                // Start/stop the local 4 Hz ticker based on current stage,
                // so the displayed "waiting Xs" advances smoothly between
                // the server's 1 s P110 polls and the UI's 2 s job polls.
                if (stage === 'cooldown') {{
                    if (!cooldownTicker) cooldownTicker = setInterval(renderRunStatus, 250);
                }} else if (cooldownTicker) {{
                    clearInterval(cooldownTicker); cooldownTicker = null;
                }}
                renderRunStatus();
                pollTimer = setTimeout(() => pollCompare(jobId), 2000);
            }}
        }} catch(e) {{
            pollTimer = setTimeout(() => pollCompare(jobId), 4000);
        }}
    }}

    renderShowcase('t2_count');
    // Resume a queued/running compare job (↩ Resume from /queue-status).
    const _resumeJob = new URLSearchParams(location.search).get('job');
    if (_resumeJob) {{ var _rb = document.getElementById('runBtn'); if (_rb) _rb.disabled = true; pollCompare(_resumeJob); }}
    </script>
"""))


@router.get("/llm/job/{job_id}", dependencies=[Depends(requires(QUEUE_VIEW))])
async def llm_job_status(job_id: str):
    return _job_status(job_id)
