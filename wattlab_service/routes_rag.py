"""
RAG routes — /rag energy test, corpus self-service (CR-051), and the
CR-049 /rag/compare across-models page.

Orchestration (run_rag_compare_job / run_rag_compare_models_job) lives
here; retrieval + measurement stay in rag.py. benchmark.py reaches
run_rag_compare_models_job through the main.py alias. Phase 3 per-feature
route module — shared state from runtime.py, chrome from ui.py, never
import main.
"""
import asyncio
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import audience
import auth
import corpus_manifest
import curated
import queue_control
import rag as rag_module
import settings as cfg
import ui
from capabilities import (requires, can, gate,
                          BATCH_COMPARE, CUSTOM_PROMPT, PUBLIC_PAGE,
                          QUEUE_VIEW, RAG_CORPUS_DELETE_OWN,
                          RAG_CORPUS_UPLOAD, RAG_RUN, SETTINGS_READ_FULL)
from llm import grade as llm_grade
from persist import save_result
from power import CooldownCancelled, meter_display_name
from runtime import jobs, job_status as _job_status
from ui import (CHARTJS_URL, _BETA_CHIP, _CONF_HELP_WIDGET, _LOCK_STYLES,
                _PROGRESS_JS, _RESULT_JS, _ai_intro, _bake_durations,
                _disabled_attr, _lock_badge_html, _lock_class,
                _model_date_line)

router = APIRouter()


# --- RAG page and endpoints ---

@router.get("/rag", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def rag_page(request: Request):
    # CR-001 part C2c — capability flags drive lock badges on the question
    # textarea (CUSTOM_PROMPT), the 3-mode compare button (BATCH_COMPARE),
    # and the corpus build/rebuild buttons (RAG_CORPUS_UPLOAD). The runtime
    # gates already enforce these — this is the visible product copy.
    can_custom_prompt = can(audience.tier(request), CUSTOM_PROMPT)
    can_batch_compare = can(audience.tier(request), BATCH_COMPARE)
    can_corpus_upload = can(audience.tier(request), RAG_CORPUS_UPLOAD)
    lk_q_class        = _lock_class(request, CUSTOM_PROMPT)
    lk_q_badge        = _lock_badge_html(request, CUSTOM_PROMPT, "Edit question — Members only")
    lk_batch_class    = _lock_class(request, BATCH_COMPARE)
    lk_batch_badge    = _lock_badge_html(request, BATCH_COMPARE, "Compare 4 modes — Members only")
    lk_corpus_class   = _lock_class(request, RAG_CORPUS_UPLOAD)
    lk_corpus_badge   = _lock_badge_html(request, RAG_CORPUS_UPLOAD, "Build / rebuild index — Members only")
    dis_q             = _disabled_attr(request, CUSTOM_PROMPT)
    dis_batch         = _disabled_attr(request, BATCH_COMPARE)
    dis_corpus        = _disabled_attr(request, RAG_CORPUS_UPLOAD)

    # CR-055 — RAG mode constants injected as JS so the frontend stays
    # in lock-step with the rag.py source of truth.
    import json as _json
    rag_modes_js        = _json.dumps(list(rag_module.COMPARE_MODES))
    rag_mode_labels_js  = _json.dumps(rag_module.MODE_LABELS)
    rag_short_labels_js = _json.dumps(rag_module.SHORT_MODE_LABELS)

    models_html = "".join([
        f'''<div class="preset" id="rmodel-{k}" onclick="selectRModel('{k}')">
            <h3>{v["label"]}</h3>
            <p style="color:var(--text-3);font-size:0.75rem">{v["params"]} · {v["size"]}</p>
            {_model_date_line(v)}
        </div>'''
        for k, v in rag_module.MODELS.items()
    ])
    # Live-view panel — same rule as /llm: default = first key, never hardcode.
    first_rmodel = next(iter(rag_module.MODELS), "")

    queue_depth = queue_control.depth()
    busy_banner = (f'<div style="background:var(--border-3);color:var(--warn);padding:0.75rem 1rem;'
                   f'margin-bottom:1rem;font-size:0.85rem">'
                   f'⏱ {queue_depth} job{"s" if queue_depth != 1 else ""} in queue — '
                   f'yours will be added and run automatically.</div>') \
        if queue_depth > 0 else ""

    return _bake_durations(ui.render_page(request, "RAG Energy Test", styles=f"""
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
        textarea {{ background:var(--panel); border:1px solid var(--border-3); color:var(--text);
                    font-family:monospace; font-size:0.88rem; padding:0.75rem;
                    width:100%; resize:vertical; line-height:1.5; }}
        textarea:focus {{ border-color:#00ff9966; outline:none; }}
        .mode-card {{ border:1px solid var(--border-3); padding:0.75rem 1rem; cursor:pointer;
                      flex:1; transition:border-color 0.15s; }}
        .mode-card:hover {{ border-color:#00ff9966; }}
        .mode-card.selected {{ border-color:var(--accent); background:#00ff9911; }}
        .mode-card h4 {{ color:var(--accent); font-size:0.85rem; margin-bottom:0.2rem; }}
        .mode-card p {{ color:var(--text-3); font-size:0.75rem; }}
        .index-bar {{ border:1px solid var(--border-2); padding:0.75rem 1rem;
                      font-size:0.8rem; color:var(--text-3); margin-bottom:1.5rem;
                      display:flex; align-items:center; justify-content:space-between; gap:1rem; }}
        .index-dot {{ width:8px; height:8px; border-radius:50%; flex-shrink:0; }}
        {_LOCK_STYLES}
""", body=f"""
    {busy_banner}
    <h1>RAG Energy Test {_BETA_CHIP}</h1>
    <div class="subtitle">Greening of Streaming · OWL · GoS1</div>

    <div style="margin-bottom:1.5rem;padding:0.85rem 1rem;border:1px solid var(--accent);
                background:var(--accent-soft);font-size:0.85rem;line-height:1.5">
        <span style="color:var(--accent);font-weight:bold">NEW</span> &middot;
        <a href="/rag/compare" style="color:var(--accent);text-decoration:none;
                                       border-bottom:1px solid var(--accent)">Compare {len(rag_module.MODELS)} models on one question &rarr; energy per correct answer &nearr;</a>
        <span style="color:var(--text-3)"> &nbsp;CR-049 hybrid: BBC showcase + member &ldquo;Try your own question&rdquo;.</span>
    </div>

    {_ai_intro('rag')}

    <div style="margin-bottom:1rem;font-size:0.78rem;color:var(--text-3)">
        First time here? <a href="/demo" style="color:var(--accent);text-decoration:none">Try the Guided Tour →</a>
    </div>

    <details style="margin-bottom:1.5rem;border-left:2px solid #222;padding-left:1rem">
        <summary style="cursor:pointer;color:var(--text-3);font-size:0.82rem;list-style:none;outline:none">
            ⓘ About this test <span style="color:var(--text-4);font-size:0.72rem">(click to expand)</span>
        </summary>
        <div style="color:var(--text-3);font-size:0.82rem;line-height:1.6;margin-top:0.75rem">
            Retrieval-Augmented Generation (RAG) augments an LLM with chunks retrieved from a PDF corpus (ChromaDB + sentence-transformer embeddings).<br>
            Compare three modes: <strong style="color:var(--text-2)">baseline</strong> (no retrieval), <strong style="color:var(--text-2)">RAG</strong> (top 3 chunks, 4096 ctx), <strong style="color:var(--text-2)">RAG Large</strong> (top 8 chunks, 8192 ctx).<br>
            Use "Compare 4 modes" to run all three sequentially with fresh baselines — a side-by-side energy comparison for the same question.<br>
            Scope: device layer only — no network, no amortised training cost.
        </div>
    </details>

    <div class="index-bar">
        <div style="display:flex;align-items:center;gap:0.6rem">
            <div class="index-dot" id="index-dot" style="background:var(--border-3)"></div>
            <span id="index-status-text">Checking index…</span>
        </div>
        <div class="{lk_corpus_class}" style="display:flex;gap:0.5rem;align-items:center">
            {lk_corpus_badge}
            <button id="buildBtn" onclick="buildIndex(false)"{dis_corpus}
                    style="background:none;border:1px solid var(--border-3);color:var(--text-3);
                           font-size:0.75rem;padding:0.3rem 0.75rem;cursor:pointer;
                           font-family:monospace;margin-top:0">Build index</button>
            <button id="rebuildBtn" onclick="buildIndex(true)"{dis_corpus}
                    style="background:none;border:1px solid var(--border-3);color:var(--text-3);
                           font-size:0.75rem;padding:0.3rem 0.75rem;cursor:pointer;
                           font-family:monospace;margin-top:0">Rebuild</button>
        </div>
    </div>

    <dialog id="preview-dlg" style="border:1px solid var(--accent);background:var(--bg);
            color:var(--text);width:80vw;height:85vh;max-width:1100px;padding:0;margin:auto">
      <div style="display:flex;align-items:center;justify-content:space-between;
                  padding:0.5rem 0.85rem;background:var(--panel);border-bottom:1px solid var(--border)">
        <span id="preview-title" style="font-family:monospace;font-size:0.82rem;color:var(--text-2);
              overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-right:0.75rem">filename</span>
        <button onclick="document.getElementById('preview-dlg').close()"
                style="background:none;border:1px solid var(--border-3);color:var(--text-3);
                       font-size:0.85rem;padding:0.15rem 0.5rem;cursor:pointer;font-family:monospace"
                title="Close (Esc)">×</button>
      </div>
      <iframe id="preview-iframe" style="width:100%;height:calc(100% - 2.5rem);border:none;background:var(--panel-2)"></iframe>
    </dialog>

    <details id="corpus-browser" style="margin-bottom:1.5rem;border:1px solid var(--border);padding:0.5rem 0.9rem;font-size:0.82rem"
             ontoggle="if(this.open) loadCorpus();">
      <summary style="cursor:pointer;color:var(--text-2);list-style:none">
        <span id="corpus-summary-text">▸ Browse corpus documents</span>
      </summary>
      {("<div id='upload-form' style='margin-top:0.75rem;padding:0.6rem 0.75rem;border:1px dashed var(--border-3);background:var(--panel-2)'>"
        "<div style='color:var(--text-2);font-size:0.8rem;margin-bottom:0.4rem;font-weight:bold'>Upload a PDF to the corpus</div>"
        "<div style='color:var(--text-5);font-size:0.72rem;margin-bottom:0.4rem' id='upload-quota'>Loading quota…</div>"
        "<input type='file' id='upload-file' accept='application/pdf,.pdf,text/markdown,.md' "
        "style='font-family:monospace;font-size:0.78rem;color:var(--text-3);background:#0f0f0f;"
        "border:1px solid var(--border-3);padding:0.35rem;width:100%;margin-bottom:0.4rem'>"
        "<input type='text' id='upload-title' maxlength='200' "
        "placeholder='Optional note / qualifier (e.g. &quot;Internal GoS working document&quot;)' "
        "style='font-family:monospace;font-size:0.78rem;color:var(--text-3);background:#0f0f0f;"
        "border:1px solid var(--border-3);padding:0.35rem;width:100%;margin-bottom:0.5rem'>"
        "<button onclick='uploadDoc()' style='background:var(--accent);color:#000;border:none;"
        "padding:0.45rem 1rem;cursor:pointer;font-family:monospace;font-size:0.78rem'>Upload + index</button>"
        "<span id='upload-status' style='margin-left:0.75rem;color:var(--text-4);font-size:0.78rem'></span>"
        "</div>") if can_corpus_upload else ""}
      <div id="corpus-list" style="margin-top:0.6rem;color:var(--text-3);font-size:0.78rem;line-height:1.6">
        <p style="color:var(--text-4)">Loading…</p>
      </div>
    </details>

    <div class="section-label">Model</div>
    <div class="presets">{models_html}</div>

    <div class="section-label">Retrieval mode</div>
    <div class="presets" style="margin-bottom:1.5rem">
        <div class="mode-card selected" id="rmode-baseline" onclick="selectRMode('baseline')">
            <h4>Without RAG</h4>
            <p>No retrieval. Cold LLM inference only.</p>
        </div>
        <div class="mode-card" id="rmode-rag" onclick="selectRMode('rag')">
            <h4>RAG</h4>
            <p>Top 3 chunks · faithful (chunks only)</p>
        </div>
        <div class="mode-card" id="rmode-rag_blended" onclick="selectRMode('rag_blended')">
            <h4>RAG Blended</h4>
            <p>Top 3 chunks + training knowledge</p>
        </div>
        <div class="mode-card" id="rmode-rag_large" onclick="selectRMode('rag_large')">
            <h4>RAG Large</h4>
            <p>Top 8 chunks · 8192 ctx</p>
        </div>
    </div>

    <div class="section-label">Question</div>
    {lk_q_badge}
    <div class="{lk_q_class}">
      <textarea id="questionText" rows="3"{dis_q}
                placeholder="What is REM (Remote Energy Measurement)?"
                style="margin-bottom:0.5rem"></textarea>
    </div>
    <details style="margin-bottom:1.5rem;color:var(--text-3);font-size:0.78rem">
      <summary style="cursor:pointer;color:var(--text-2)">ⓘ Why this question, and how to read the answers</summary>
      <div style="padding:0.75rem 0;line-height:1.6">
        <p style="margin-bottom:0.5rem"><strong>"What is REM?"</strong> is corpus-grounded — the GoS REM whitepaper is in the index but unlikely in any model's training data. So the answer should come <em>from</em> retrieval, not from prior knowledge. Good test of whether RAG is working.</p>
        <p style="margin-bottom:0.5rem"><strong>What you'll see (2026-04-29 runs):</strong> all three model sizes retrieve the <em>same correct chunks</em>. But TinyLlama (1.1B) hallucinates "REM is a framework provided by the European Commission" — blending the GoS source with adjacent chunks. Gemma 3 (12B) and Phi-4 (14B) stay faithful and describe REM correctly as the GoS streaming-energy framework.</p>
        <p><strong>The headline:</strong> RAG retrieval ≠ RAG quality. Smaller models can't faithfully read what they retrieve. Hallucination rate is a third axis on the energy/quality tradeoff — alongside speed and accuracy.</p>
      </div>
    </details>

    {lk_batch_badge}
    <div style="display:flex;gap:0.75rem;flex-wrap:wrap">
        <button id="runBtn" onclick="startRag()">▶ Run single</button>
        <button id="compareBtn" class="{lk_batch_class}" onclick="startCompare()"{dis_batch}
                style="background:var(--panel);border:1px solid var(--accent);color:var(--accent)">
            ▶▶ Compare 4 modes
        </button>
    </div>

    <div id="status"></div>

    <div id="prev-runs" style="margin-top:2.5rem"></div>

    <script>
    // CR-001 part C2c — capability flags from server.
    // Anonymous: textarea is locked, JS posts an empty `question` so
    // /rag/run uses CANONICAL_RAG_QUESTION (curated.py); the BATCH_COMPARE
    // gate is enforced server-side, the disabled button is just polite UX.
    const CAN_CUSTOM_PROMPT = {('true' if can_custom_prompt else 'false')};
    const CAN_BATCH_COMPARE = {('true' if can_batch_compare else 'false')};

    let selectedRModel = '{first_rmodel}';
    let selectedRMode = 'baseline';
    let ragTimer = null;
    let ragStartTime = null;
    let compareTimer = null;

    function selectRModel(k) {{
        document.querySelectorAll('.presets .preset').forEach(el => el.classList.remove('selected'));
        const el = document.getElementById('rmodel-' + k);
        if (el) el.classList.add('selected');
        selectedRModel = k;
    }}
    function selectRMode(m) {{
        document.querySelectorAll('.mode-card').forEach(el => el.classList.remove('selected'));
        const el = document.getElementById('rmode-' + m);
        if (el) el.classList.add('selected');
        selectedRMode = m;
    }}
    selectRModel('{first_rmodel}');

    function toggleAns(id) {{
        var el = document.getElementById(id);
        if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
    }}

    // Index status
    async function loadIndexStatus() {{
        try {{
            const r = await fetch('/rag/index-status');
            const d = await r.json();
            const dot = document.getElementById('index-dot');
            const txt = document.getElementById('index-status-text');
            if (d.status === 'ready') {{
                dot.style.background = '#00ff99';
                txt.textContent = 'Index ready · ' + d.doc_count + ' chunks';
            }} else if (d.status === 'building') {{
                dot.style.background = '#ffaa00';
                txt.textContent = 'Building index…';
                setTimeout(loadIndexStatus, 3000);
            }} else if (d.status === 'error') {{
                dot.style.background = '#ff4400';
                txt.textContent = 'Index error: ' + (d.error || 'unknown');
            }} else {{
                dot.style.background = '#555';
                txt.textContent = 'Index not built — click "Build index" to start';
            }}
        }} catch(e) {{
            document.getElementById('index-status-text').textContent = 'Could not check index';
        }}
    }}

    async function loadCorpus() {{
        const el = document.getElementById('corpus-list');
        const sumEl = document.getElementById('corpus-summary-text');
        const quotaEl = document.getElementById('upload-quota');
        try {{
            const r = await fetch('/rag/corpus-list');
            const d = await r.json();
            sumEl.textContent = '▾ Browse corpus documents — ' + d.total + ' PDFs (' + d.indexed + ' indexed)';
            // CR-051 — Member quota display (above upload form)
            if (quotaEl) {{
                const u = d.member_usage, c = d.caps || {{}};
                if (u && c.member_doc_count != null) {{
                    const mb = (u.total_bytes / 1024 / 1024).toFixed(1);
                    quotaEl.textContent = 'Your uploads: ' + u.file_count + '/' + c.member_doc_count
                        + ' files · ' + mb + ' / ' + c.member_total_mb + ' MB · '
                        + 'per-file cap: ' + c.per_file_mb + ' MB';
                }} else {{
                    quotaEl.textContent = 'Lab tier — uncapped. Per-file cap: ' + (c.per_file_mb || '?') + ' MB.';
                }}
            }}
            if (!d.docs || d.docs.length === 0) {{
                el.innerHTML = '<p style="color:var(--text-4)">No PDFs found in the corpus directory.</p>';
                return;
            }}
            // CR-051 — sort: Member-uploaded first (so they find their own quickly), then pending, then alpha.
            d.docs.sort((a,b) => {{
                const aM = (a.origin === 'Member') ? 0 : 1;
                const bM = (b.origin === 'Member') ? 0 : 1;
                return aM - bM || (a.indexed - b.indexed) || a.rel_path.localeCompare(b.rel_path);
            }});
            const rows = d.docs.map(doc => {{
                const flag = doc.indexed
                    ? '<span style="color:var(--accent)" title="indexed">●</span>'
                    : '<span style="color:var(--warn)" title="not yet indexed — rebuild">○</span>';
                const tag = doc.indexed ? 'indexed' : 'pending — rebuild to add';
                const sizeStr = doc.size_kb >= 1024
                    ? (doc.size_kb / 1024).toFixed(1) + ' MB'
                    : doc.size_kb + ' KB';
                const originChip = doc.origin === 'Member'
                    ? '<span style="color:var(--accent);border:1px solid var(--accent);font-size:0.65rem;padding:0 0.3rem;border-radius:2px">Member</span>'
                    : '<span style="color:var(--text-4);border:1px solid var(--border-3);font-size:0.65rem;padding:0 0.3rem;border-radius:2px">Lab</span>';
                const addedShort = (doc.added_at || '').slice(0, 10);  // YYYY-MM-DD
                const safeJsName = doc.rel_path.replace(/\\\\/g, "\\\\\\\\").replace(/'/g, "\\\\'");
                const viewBtn = '<button onclick="viewDoc(\\'' + safeJsName + '\\')" '
                    + 'style="background:none;border:1px solid var(--border-3);color:var(--text-3);'
                    + 'font-size:0.7rem;padding:0 0.4rem;cursor:pointer;font-family:monospace" title="Preview">👁</button>';
                const delBtn = doc.can_delete
                    ? '<button onclick="deleteDoc(\\'' + safeJsName + '\\')" '
                      + 'style="background:none;border:1px solid var(--border-3);color:var(--err);'
                      + 'font-size:0.7rem;padding:0 0.4rem;cursor:pointer;font-family:monospace" title="Delete this document">×</button>'
                    : '';
                // CR-051 — optional title shown inline after filename. Both
                // get individual `title` HTML attributes so a long-name OR a
                // long-note still surfaces fully on hover.
                const titleHtml = doc.title
                    ? '<span style="color:var(--text-5);font-style:italic" title="' + (doc.title.replace(/"/g, '&quot;')) + '"> · ' + doc.title + '</span>'
                    : '';
                return '<div style="display:flex;align-items:center;gap:0.5rem;padding:0.2rem 0;border-bottom:1px solid var(--border-2)">'
                    + '<span style="flex-shrink:0">' + flag + '</span>'
                    + '<span style="flex:1;font-family:monospace;font-size:0.75rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + doc.rel_path + '">'
                    + doc.rel_path + titleHtml + '</span>'
                    + '<span style="flex-shrink:0">' + originChip + '</span>'
                    + '<span style="flex-shrink:0;color:var(--text-5);font-size:0.7rem;width:5.5rem;text-align:right">' + addedShort + '</span>'
                    + '<span style="flex-shrink:0;color:var(--text-4);font-size:0.72rem;width:5rem;text-align:right">' + sizeStr + '</span>'
                    + '<span style="flex-shrink:0;color:var(--text-4);font-size:0.7rem;width:8rem;text-align:right">' + tag + '</span>'
                    + '<span style="flex-shrink:0;display:flex;gap:0.25rem">' + viewBtn + delBtn + '</span>'
                    + '</div>';
            }}).join('');
            el.innerHTML = '<div style="max-height:28rem;overflow-y:auto;padding-right:0.4rem">' + rows + '</div>'
                + '<p style="color:var(--text-4);font-size:0.72rem;margin-top:0.5rem">'
                + 'Origin: <span style="color:var(--accent)">Member</span> = uploaded via the form above (Members can delete their own). '
                + '<span style="color:var(--text-4)">Lab</span> = seeded by the GoS team. '
                + 'Names of Member uploaders are not shown publicly.</p>';
        }} catch(e) {{
            el.innerHTML = '<p style="color:var(--err)">Failed to load corpus: ' + e + '</p>';
        }}
    }}

    async function uploadDoc() {{
        const fileEl = document.getElementById('upload-file');
        const titleEl = document.getElementById('upload-title');
        const status = document.getElementById('upload-status');
        const file = fileEl.files[0];
        if (!file) {{ status.style.color = 'var(--err)'; status.textContent = 'pick a PDF first'; return; }}
        status.style.color = 'var(--warn)'; status.textContent = 'uploading…';
        const fd = new FormData();
        fd.append('file', file);
        const t = (titleEl.value || '').trim();
        if (t) fd.append('title', t);
        try {{
            const r = await fetch('/rag/upload', {{method: 'POST', body: fd}});
            const d = await r.json();
            if (!r.ok || d.error) {{
                status.style.color = 'var(--err)';
                status.textContent = d.error || ('HTTP ' + r.status);
                return;
            }}
            status.style.color = 'var(--accent)';
            const chunks = d.indexed && d.indexed.chunks_added;
            status.textContent = '✓ ' + d.filename + (chunks ? ' (' + chunks + ' chunks indexed)' : ' (indexing…)');
            fileEl.value = '';
            titleEl.value = '';
            // Refresh the corpus list to show the new entry.
            setTimeout(loadCorpus, 500);
        }} catch(e) {{
            status.style.color = 'var(--err)';
            status.textContent = 'failed: ' + e;
        }}
    }}

    function viewDoc(filename) {{
        const dlg = document.getElementById('preview-dlg');
        document.getElementById('preview-title').textContent = filename;
        document.getElementById('preview-iframe').src = '/rag/doc/' + encodeURIComponent(filename);
        dlg.showModal();
    }}

    async function deleteDoc(filename) {{
        if (!confirm('Delete "' + filename + '" from the corpus? This removes the PDF and its index chunks.')) return;
        try {{
            const r = await fetch('/rag/doc/' + encodeURIComponent(filename), {{method: 'DELETE'}});
            const d = await r.json();
            if (!r.ok || d.error) {{
                alert('Delete failed: ' + (d.error || ('HTTP ' + r.status)));
                return;
            }}
            loadCorpus();
        }} catch(e) {{
            alert('Delete failed: ' + e);
        }}
    }}

    async function buildIndex(rebuild) {{
        const btn = rebuild ? document.getElementById('rebuildBtn') : document.getElementById('buildBtn');
        btn.disabled = true;
        btn.textContent = 'Working…';
        document.getElementById('index-dot').style.background = '#ffaa00';
        document.getElementById('index-status-text').textContent = 'Building index…';
        try {{
            await fetch('/rag/build-index', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{rebuild: rebuild}})
            }});
        }} catch(e) {{}}
        btn.disabled = false;
        btn.textContent = rebuild ? 'Rebuild' : 'Build index';
        setTimeout(loadIndexStatus, 2000);
    }}

    async function startRag() {{
        const question = document.getElementById('questionText').value.trim();
        if (CAN_CUSTOM_PROMPT && !question) {{
            document.getElementById('status').innerHTML =
                '<div style="color:var(--err);font-size:0.85rem;margin-top:1rem">Please enter a question.</div>';
            return;
        }}
        document.getElementById('runBtn').disabled = true;
        ragStartTime = Date.now();
        const form = new FormData();
        form.append('model_key', selectedRModel);
        form.append('rag_mode', selectedRMode);
        if (CAN_CUSTOM_PROMPT && question) form.append('question', question);
        try {{
            const resp = await fetch('/rag/run', {{method:'POST', body:form}});
            const data = await resp.json();
            if (data.job_id) {{
                renderRagProgress('baseline');
                pollRag(data.job_id);
            }} else {{
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + JSON.stringify(data) + '</div>';
                document.getElementById('runBtn').disabled = false;
            }}
        }} catch(e) {{
            document.getElementById('status').innerHTML =
                '<div style="color:var(--err)">Failed: ' + e + '</div>';
            document.getElementById('runBtn').disabled = false;
        }}
    }}

    const RAG_STAGES = ['Baseline poll ({{BASELINE_S}}s)', 'Inference running', 'Complete'];
    const RAG_STAGE_IDX = {{baseline:0, inference:1, done:2}};

    // Single-mode renderRagProgress (used by pollRag below). The 3-mode
    // compare flow has its own renderCompareProgress further down \u2014 earlier
    // I dispatched compare/single inside this function, but single-mode
    // jobs never carry mode_index so the compare branch was dead code AND
    // its const RAG_MODE_LABELS collided with the per-mode label dict
    // injected from rag.py for renderCompareProgress. Reverted to original.
    function renderRagProgress(stage, watts, jobData) {{
        wlRenderProgress({{
            header: 'Measuring RAG energy \u2014 do not close this tab',
            stagesHtml: wlStageList(RAG_STAGES, RAG_STAGE_IDX[stage] ?? 0),
            watts: watts,
            elapsed: ragStartTime ? Date.now() - ragStartTime : null,
            cooldownData: jobData,
        }});
    }}

    async function pollRag(jobId) {{
        try {{
            const [resp, powerR] = await Promise.all([
                fetch('/rag/job/' + jobId),
                fetch('/power').catch(() => null),
            ]);
            const data = await resp.json();
            const watts = powerR ? (await powerR.json().catch(()=>({{}}))).watts ?? null : null;
            if (data.stage === 'done' && data.result) {{
                if (ragTimer) {{ clearTimeout(ragTimer); ragTimer = null; }}
                renderRagResult(data.result, jobId);
                document.getElementById('runBtn').disabled = false;
                loadPrevRuns();
            }} else if (data.stage === 'error' || data.error) {{
                if (ragTimer) {{ clearTimeout(ragTimer); ragTimer = null; }}
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + (data.error||'unknown') + '</div>';
                document.getElementById('runBtn').disabled = false;
            }} else if (data.stage === 'queued') {{
                wlRenderQueued(data.queue_position);
                ragTimer = setTimeout(() => pollRag(jobId), 3000);
            }} else {{
                if (data.stage === 'awaiting_cooldown_decision') {{
                    wlCooldownDialog(jobId, data.cooldown_decision_options);
                }} else {{ wlCooldownDialogClose(); }}
                renderRagProgress(data.stage || 'baseline', watts, data);
                ragTimer = setTimeout(() => pollRag(jobId), 2000);
            }}
        }} catch(e) {{
            ragTimer = setTimeout(() => pollRag(jobId), 5000);
        }}
    }}

    function renderRagResult(r, jobId) {{
        const e = r.energy || {{}};
        const inf = r.inference || {{}};
        const conf = e.confidence || {{}};
        const ragModeLabels = RAG_MODE_LABELS;
        const sourcesHtml = r.chunk_sources && r.chunk_sources.length
            ? r.chunk_sources.map(s => `<span style="font-size:0.72rem;color:var(--text-3);
                background:var(--panel);padding:0.2rem 0.4rem;margin-right:0.3rem">${{s}}</span>`).join('')
            : '<span style="color:var(--text-5);font-size:0.75rem">none</span>';
        const retrievalHtml = r.rag_mode !== 'baseline' ? `
            <div class="section-title">Retrieval</div>
            <div class="metric"><span>Chunks retrieved</span><span class="val">${{r.chunks_retrieved}} / ${{r.top_k}}</span></div>
            <div class="metric"><span>Embedding</span><span class="val">${{r.embedding_ms}} ms</span></div>
            <div class="metric"><span>Vector search</span><span class="val">${{r.retrieval_ms}} ms</span></div>
            <div class="metric"><span>Context window</span><span class="val">${{r.num_ctx}} tokens</span></div>
            <div class="section-title" style="margin-top:0.75rem">Sources</div>
            <div style="margin-bottom:0.5rem">${{sourcesHtml}}</div>
        ` : '';
        document.getElementById('status').innerHTML = `
            <div class="result-box">
                <h2>Result — ${{r.model_label}} · ${{ragModeLabels[r.rag_mode] || r.rag_mode}}</h2>
                <div class="section-title">Question</div>
                <div style="color:var(--text-2);font-size:0.82rem;margin-bottom:0.75rem">${{r.question}}</div>
                ${{retrievalHtml}}
                <div class="section-title">Inference</div>
                <div class="metric"><span>Output tokens</span><span class="val">${{inf.output_tokens}}</span></div>
                <div class="metric"><span>Tokens/sec</span><span class="val">${{inf.tokens_per_sec}}</span></div>
                <div class="metric"><span>Duration</span><span class="val">${{inf.duration_s}} s</span></div>
                <div class="section-title">Energy</div>
                <div class="metric"><span>Baseline</span><span class="val">${{e.w_base}} W</span></div>
                <div class="metric"><span>Task mean</span><span class="val">${{e.w_task}} W</span></div>
                <div class="metric"><span>ΔW</span><span class="val">${{e.delta_w}} W</span></div>
                <div class="metric"><span>ΔE</span><span class="val">${{e.delta_e_wh}} Wh</span></div>
                ${{wlCarbonRow(e)}}
                <div class="metric"><span>mWh/token</span><span class="val">${{e.mwh_per_token ?? '—'}}</span></div>
                <div class="metric"><span>Confidence</span>
                    <span class="val conf-badge">${{conf.flag||'—'}} ${{conf.label||''}}</span></div>
                <div class="section-title">Answer</div>
                <div class="response-box">${{inf.response}}</div>
                ${{wlCarbonStrip(e.delta_e_wh, r.model_label + ' · ' + (ragModeLabels[r.rag_mode] || r.rag_mode), e.delta_t_s, e.co2e && e.co2e.intensity ? e.co2e.intensity.g_per_kwh : null)}}
                <div class="scope-note">${{r.scope}}</div>
                <div style="display:flex;gap:0.5rem;margin-top:0.75rem">
                    <a href="/results/llm/${{jobId}}/download.json" download
                       style="color:var(--text-3);font-size:0.75rem;text-decoration:none">↓ JSON</a>
                    <a href="/results/llm/${{jobId}}/download.csv" download
                       style="color:var(--text-3);font-size:0.75rem;text-decoration:none">↓ CSV</a>
                </div>
            </div>`;
    }}

    // --- Compare 4 modes ---

    async function startCompare() {{
        if (!CAN_BATCH_COMPARE) return;   // button is disabled, this is a backstop
        const question = document.getElementById('questionText').value.trim();
        if (CAN_CUSTOM_PROMPT && !question) {{
            document.getElementById('status').innerHTML =
                '<div style="color:var(--err);font-size:0.85rem;margin-top:1rem">Please enter a question.</div>';
            return;
        }}
        document.getElementById('runBtn').disabled = true;
        document.getElementById('compareBtn').disabled = true;
        ragStartTime = Date.now();
        const form = new FormData();
        form.append('model_key', selectedRModel);
        if (CAN_CUSTOM_PROMPT && question) form.append('question', question);
        try {{
            const resp = await fetch('/rag/run-compare', {{method:'POST', body:form}});
            const data = await resp.json();
            if (data.job_id) {{
                renderCompareProgress({{}}, null, null);
                pollCompare(data.job_id);
            }} else {{
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + JSON.stringify(data) + '</div>';
                document.getElementById('runBtn').disabled = false;
                document.getElementById('compareBtn').disabled = false;
            }}
        }} catch(e) {{
            document.getElementById('status').innerHTML =
                '<div style="color:var(--err)">Failed: ' + e + '</div>';
            document.getElementById('runBtn').disabled = false;
            document.getElementById('compareBtn').disabled = false;
        }}
    }}

    // CR-055 — single source of truth (mirrors rag.COMPARE_MODES + LABELS).
    const RAG_COMPARE_MODES  = {rag_modes_js};
    const RAG_MODE_LABELS    = {rag_mode_labels_js};
    const RAG_SHORT_LABELS   = {rag_short_labels_js};

    function renderCompareProgress(partial, data, watts) {{
        const MODES = RAG_COMPARE_MODES;
        // CR-055 alignment — labels come from RAG_SHORT_LABELS (rag.py source of truth).
        data = data || {{}};
        const stage = data.stage;
        const currentMode = data.current_mode;
        const inCooldown = (stage === 'cooldown');
        const stagesHtml = MODES.map((m, i) => {{
            const done = partial && partial[m];
            const active = (m === currentMode) && !done && !inCooldown;
            const col = done ? '#00ff99' : active ? '#ffaa00' : '#333';
            const icon = done ? '✓' : active ? '▶' : '·';
            let extra = '';
            if (done) {{
                const e = partial[m].energy || {{}};
                extra = ' <span style="color:var(--text-3);font-size:0.75rem">\u2014 '
                    + (e.delta_w != null ? e.delta_w + ' W \xb7 ' : '')
                    + (e.mwh_per_token != null ? e.mwh_per_token + ' mWh/tok' : '')
                    + (e.confidence ? ' ' + e.confidence.flag : '')
                    + '</span>';
            }}
            return '<div style="display:flex;align-items:center;gap:0.6rem;font-size:0.82rem;margin-bottom:0.3rem">'
                + '<span style="color:' + col + ';width:1rem">' + icon + '</span>'
                + '<span style="color:' + col + '">' + (RAG_SHORT_LABELS[m] || m) + extra + '</span></div>';
        }}).join('');
        // CR-019/CR-050 \u2014 explicit cooldown row with live thermal-floor wait info.
        let cooldownHtml = '';
        if (inCooldown && WL_CFG.show_wait_detail === false) {{
            cooldownHtml = '<div style="display:flex;align-items:center;gap:0.6rem;font-size:0.82rem;margin-bottom:0.3rem">'
                + '<span style="color:#ffaa00;width:1rem">\u23f1</span>'
                + '<span style="color:#ffaa00">Cooldown\u2026</span></div>';
        }} else if (inCooldown) {{
            const tol    = isNaN(Number(WL_CFG.idle_tolerance_w)) ? 3 : Number(WL_CFG.idle_tolerance_w);
            const tgt    = (data.cooldown_reference_w != null) ? '\u2264 ' + (Number(data.cooldown_reference_w) + tol).toFixed(1) + ' W' : '?';
            const cur    = (data.cooldown_w           != null) ? Number(data.cooldown_w).toFixed(1) : '?';
            const waited = (data.cooldown_waited_s    != null) ? data.cooldown_waited_s + 's' : '?';
            cooldownHtml = '<div style="display:flex;align-items:center;gap:0.6rem;font-size:0.82rem;margin-bottom:0.3rem">'
                + '<span style="color:#ffaa00;width:1rem">\u23f1</span>'
                + '<span style="color:#ffaa00">Cooldown \u2014 ' + waited
                + ' \xb7 ' + cur + ' W \u2192 target ' + tgt + '</span></div>';
        }}
        wlRenderProgress({{
            header: 'Comparing ' + MODES.length + ' modes \u2014 do not close this tab',
            stagesHtml: stagesHtml + cooldownHtml,
            watts: watts,
            elapsed: ragStartTime ? Date.now() - ragStartTime : null,
        }});
    }}

    async function pollCompare(jobId) {{
        try {{
            const [resp, powerR] = await Promise.all([
                fetch('/rag/job/' + jobId),
                fetch('/power').catch(() => null),
            ]);
            const data = await resp.json();
            const watts = powerR ? (await powerR.json().catch(()=>({{}}))).watts ?? null : null;
            if (data.stage === 'done' && data.result) {{
                if (compareTimer) {{ clearTimeout(compareTimer); compareTimer = null; }}
                renderCompareResult(data.result, jobId);
                document.getElementById('runBtn').disabled = false;
                document.getElementById('compareBtn').disabled = false;
                loadPrevRuns();
            }} else if (data.stage === 'error' || data.error) {{
                if (compareTimer) {{ clearTimeout(compareTimer); compareTimer = null; }}
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + (data.error||'unknown') + '</div>';
                document.getElementById('runBtn').disabled = false;
                document.getElementById('compareBtn').disabled = false;
            }} else if (data.stage === 'queued') {{
                wlRenderQueued(data.queue_position);
                compareTimer = setTimeout(() => pollCompare(jobId), 3000);
            }} else {{
                renderCompareProgress(data.partial_results || {{}}, data, watts);
                // CR-050 alignment — tighter cadence during cooldown so the
                // waited-Ns counter visibly advances between 1 s server polls.
                const next = data.stage === 'cooldown' ? 750 : 2000;
                compareTimer = setTimeout(() => pollCompare(jobId), next);
            }}
        }} catch(e) {{
            compareTimer = setTimeout(() => pollCompare(jobId), 5000);
        }}
    }}

    function renderCompareResult(r, jobId) {{
        const MODES = RAG_COMPARE_MODES;
        const MODE_LABELS = RAG_MODE_LABELS;
        // CR-055 \u2014 STRIPE colour per mode; baseline dark (no retrieval),
        // rag blue, rag_blended teal (blend = somewhere between), rag_large accent green.
        const STRIPE = {{baseline:'#444', rag:'#0088cc', rag_blended:'#00b3a4', rag_large:'#00ff99'}};
        const cards = MODES.map(m => {{
            const res = (r.results || {{}})[m];
            if (!res) return '';
            const e = res.energy || {{}};
            const inf = res.inference || {{}};
            const conf = e.confidence || {{}};
            const retrievalRow = m !== 'baseline'
                ? '<div style="color:var(--text-3);font-size:0.78rem;margin:0.4rem 0">'
                  + 'embed ' + res.embedding_ms + 'ms \xb7 search ' + res.retrieval_ms + 'ms \xb7 '
                  + res.chunks_retrieved + ' chunks</div>'
                : '<div style="color:var(--text-5);font-size:0.78rem;margin:0.4rem 0">No retrieval</div>';
            const answerId = 'ans-' + m + '-' + jobId;
            return '<div style="border:1px solid var(--border);border-left:3px solid ' + STRIPE[m] + ';padding:1.25rem;margin-bottom:0.75rem">'
                + '<div style="font-size:0.9rem;color:var(--text);margin-bottom:0.5rem">' + MODE_LABELS[m] + '</div>'
                + retrievalRow
                + '<div style="display:flex;gap:1.5rem;font-size:0.82rem;flex-wrap:wrap;margin-bottom:0.5rem">'
                + '<span>\u0394W <span style="color:var(--accent)">' + e.delta_w + ' W</span></span>'
                + '<span>\u0394E <span style="color:var(--accent)">' + e.delta_e_wh + ' Wh</span></span>'
                + '<span>mWh/tok <span style="color:var(--accent)">' + (e.mwh_per_token ?? '\u2014') + '</span></span>'
                + '<span>' + inf.tokens_per_sec + ' tok/s</span>'
                + '<span class="conf-badge">' + (conf.flag||'') + ' ' + (conf.label||'') + '</span>'
                + '</div>'
                + '<div style="font-size:0.75rem;color:var(--text-3);margin-bottom:0.4rem;cursor:pointer" '
                + 'data-id="' + answerId + '" onclick="toggleAns(this.dataset.id)">'
                + '\u25b6 Show / hide answer</div>'
                + '<div id="' + answerId + '" style="display:none;background:var(--panel);padding:0.75rem;'
                + 'font-size:0.78rem;color:var(--text-2);line-height:1.6;white-space:pre-wrap;max-height:300px;overflow-y:auto;'
                + 'border-left:2px solid ' + STRIPE[m] + '44">' + (inf.response || '') + '</div>'
                + '</div>';
        }}).join('');
        // Per-report carbon strip: use the lowest energy across the 3 modes
        // (the most efficient mode) so the "if this had run elsewhere"
        // comparison reflects the best-case carbon footprint of this run.
        const _stripWhArr = MODES
            .map(m => (r.results||{{}})[m] && r.results[m].energy ? r.results[m].energy.delta_e_wh : null)
            .filter(v => v != null);
        const _stripWh = _stripWhArr.length ? Math.min.apply(null, _stripWhArr) : null;
        const _stripLbl = r.model_label + ' \xb7 3-mode RAG comparison (best of)';
        // Find the winning mode's energy block for drift note + duration.
        let _winE = null;
        let _winWh = Infinity;
        MODES.forEach(m => {{
            const me = (r.results||{{}})[m] && r.results[m].energy;
            if (me && me.delta_e_wh != null && me.delta_e_wh < _winWh) {{
                _winE = me; _winWh = me.delta_e_wh;
            }}
        }});
        const _stripDur = _winE ? _winE.delta_t_s : null;
        const _stripSavedG = _winE && _winE.co2e && _winE.co2e.intensity
            ? _winE.co2e.intensity.g_per_kwh : null;
        // CR-032 \u2014 sub-runs across the 3 retrieval modes.
        const _subRuns = MODES
            .map(m => {{
                const res = (r.results||{{}})[m];
                if (!res || !res.energy || !res.energy.co2e) return null;
                return {{
                    label: MODE_LABELS[m],
                    grams: res.energy.co2e.grams,
                    deltaWh: res.energy.delta_e_wh,
                    durationS: res.energy.delta_t_s
                }};
            }})
            .filter(s => s != null);
        // CR-038 \u2014 structured efficiency verdict above the per-mode cards.
        const _ragVerdict = wlEfficiencyVerdict(MODES.map(m => {{
            const res = (r.results||{{}})[m];
            if (!res || !res.energy) return null;
            return {{label: MODE_LABELS[m], energy: res.energy.mwh_per_token}};
        }}).filter(x => x != null), {{unit: 'mWh/token'}});
        document.getElementById('status').innerHTML =
            '<div style="border:1px solid var(--border);padding:1.5rem">'
            + '<div style="color:var(--accent);font-size:1.1rem;margin-bottom:0.25rem">Comparison \u2014 ' + r.model_label + '</div>'
            + '<div style="color:var(--text-3);font-size:0.82rem;margin-bottom:1rem">' + r.question + '</div>'
            + _ragVerdict
            + cards
            + wlCarbonStrip(_stripWh, _stripLbl, _stripDur, _stripSavedG, _subRuns)
            + '<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.75rem">' + (r.scope||'') + '</div>'
            + '<div style="display:flex;gap:0.5rem;margin-top:0.75rem">'
            + '<a href="/results/llm/' + jobId + '/download.json" download style="color:var(--text-3);font-size:0.75rem;text-decoration:none">\u2193 JSON</a>'
            + '</div></div>';
    }}

    // --- Previous runs ---

    async function loadPrevRuns() {{
        try {{
            const resp = await fetch('/results/llm/list');
            const runs = await resp.json();
            const ragRuns = runs.filter(r => r.task && (r.task.startsWith('RAG/') || r.task === 'RAG compare (3 modes)'));
            renderPrevRuns(ragRuns);
        }} catch(e) {{}}
    }}

    function renderPrevRuns(runs) {{
        const el = document.getElementById('prev-runs');
        if (!runs || runs.length === 0) {{
            el.innerHTML = '<div style="color:var(--text-5);font-size:0.8rem">No previous RAG runs.</div>';
            return;
        }}
        const rows = runs.map(r => {{
            const date = r.saved_at ? r.saved_at.slice(0,16).replace('T',' ') : '\u2014';
            const summary = (r.model||'') + ' \xb7 ' + (r.task||'') + ' \xb7 ' + r.mwh_per_token + ' mWh/tok ' + (r.confidence ? '<span class="conf-badge">'+r.confidence+'</span>' : '');
            const base = '/results/llm/' + r.job_id;
            const savedAt = r.saved_at || '';
            // RAG persists under llm/ but renders with the RAG card; passing
            // jobType='llm' + cardKind='rag' to wlExpandPrevRow handles both.
            const isCompare = r.task === 'RAG compare (3 modes)';
            const cardKind = isCompare ? 'rag' : 'llm';
            return '<div style="border-bottom:1px solid var(--panel);padding:0.6rem 0">'
                + '<div style="display:flex;justify-content:space-between;align-items:baseline">'
                + '<span style="color:var(--text);font-size:0.82rem">' + date + '</span>'
                + '<span style="color:var(--text-3);font-size:0.75rem;font-family:monospace">' + r.job_id + '</span></div>'
                + '<div style="color:var(--accent);font-size:0.8rem;margin:0.2rem 0">' + summary + '</div>'
                + '<div style="display:flex;gap:0.75rem;margin-top:0.3rem;align-items:center">'
                + '<a href="javascript:void(0)" '
                + 'onclick="wlExpandPrevRow(\\\'llm\\\',\\\'' + r.job_id + '\\\',\\\'' + savedAt + '\\\',\\\'' + cardKind + '\\\')" '
                + 'style="color:var(--text-3);font-size:0.75rem;text-decoration:none;cursor:pointer">'
                + '<span id="chev-' + r.job_id + '">\u25b8</span> Show full result</a>'
                + '<a href="' + base + '/download.json" download style="color:var(--text-5);font-size:0.75rem;text-decoration:none">\u2193 JSON</a>'
                + '<a href="' + base + '/download.csv" download style="color:var(--text-5);font-size:0.75rem;text-decoration:none">\u2193 CSV</a>'
                + '</div>'
                + '<div id="expand-' + r.job_id + '" style="display:none;margin-top:0.6rem"></div>'
                + '</div>';
        }}).join('');
        el.innerHTML = '<div style="color:var(--text-4);font-size:0.72rem;text-transform:uppercase;'
            + 'letter-spacing:0.05em;margin-bottom:0.75rem">Previous RAG runs</div>' + rows;
    }}

    loadIndexStatus();
    loadPrevRuns();
    const _resumeJob = new URLSearchParams(location.search).get('job');
    if (_resumeJob) {{ pollRag(_resumeJob); }}
    </script>
    {_PROGRESS_JS}
    {_RESULT_JS}
    {_CONF_HELP_WIDGET}
"""))


@router.get("/rag/index-status", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def rag_index_status():
    return {
        "status": rag_module.index_status,
        "doc_count": rag_module.index_doc_count,
        "error": rag_module.index_error,
    }


@router.get("/rag/corpus-list", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def rag_corpus_list(request: Request):
    """CR-051 — enriched with manifest data + per-row can_delete flag.

    For each PDF, returns origin ("Lab"/"Member"), added_at, plus a boolean
    can_delete tailored to the requesting visitor (Lab: always, Member: own
    only, Anonymous: never). Member usage counters returned for the upload
    form to gate against rag_member_doc_count_cap / rag_member_total_mb_cap.
    """
    docs = rag_module.corpus_list()
    visitor_tier = audience.tier(request).name
    visitor_email = auth.member_email_from_request(request) if visitor_tier == "Member" else None
    manifest = corpus_manifest.load_manifest()
    enriched = []
    for d in docs:
        fn = d.get("rel_path") or d.get("name") or ""
        meta = manifest.get(fn) or corpus_manifest.ensure_entry(fn)
        origin = meta.get("origin", "Lab")
        can_del = corpus_manifest.can_delete(fn, visitor_tier, visitor_email)
        enriched.append({
            **d,
            "origin":      origin,                       # "Lab" | "Member"  (Anonymous never appears as owner)
            "added_at":    meta.get("added_at"),
            "title":       meta.get("title"),            # CR-051 — uploader's optional note/qualifier
            "can_delete":  can_del,
        })
    s = cfg.load()
    return {
        "docs": enriched,
        "total":   len(enriched),
        "indexed": sum(1 for d in enriched if d["indexed"]),
        "visitor_tier": visitor_tier,
        "member_usage": corpus_manifest.member_usage(visitor_email) if visitor_email else None,
        "caps": {
            "per_file_mb":         s["rag_upload_max_mb"],
            "member_doc_count":    s["rag_member_doc_count_cap"],
            "member_total_mb":     s["rag_member_total_mb_cap"],
        },
    }


@router.post("/rag/upload", dependencies=[Depends(requires(RAG_CORPUS_UPLOAD))])
async def rag_upload(request: Request, file: UploadFile = File(...),
                     title: str = Form(None)):
    """CR-051 — Member uploads a PDF to the corpus.

    Hardened upload path: filename sanitised, %PDF- magic-byte sniff, per-file
    size cap, per-Member doc count + total size caps. Lab is uncapped. On
    success the doc is incrementally added to the ChromaDB index (~3-8 s) so
    it's queryable immediately — no full rebuild needed.
    """
    s = cfg.load()
    visitor_tier  = audience.tier(request).name
    visitor_email = auth.member_email_from_request(request) if visitor_tier == "Member" else None
    if visitor_tier == "Member" and not visitor_email:
        return JSONResponse({"error": "session has no member email"}, status_code=403)

    # 1. Read + size-cap (read into memory; 50 MB is fine for RAM).
    max_bytes = int(s["rag_upload_max_mb"]) * 1024 * 1024
    blob = await file.read()
    if len(blob) > max_bytes:
        return JSONResponse({"error": f"file exceeds {s['rag_upload_max_mb']} MB cap "
                             f"({len(blob) // 1024 // 1024} MB)"}, status_code=413)
    if not blob:
        return JSONResponse({"error": "empty file"}, status_code=400)

    # 2. Format validation — dispatch on the sanitised extension.
    #    .pdf → require %PDF- magic header (defends against renamed binaries)
    #    .md  → require UTF-8 + no NUL bytes (defends against binary mislabel)
    # We sanitise the filename here (early) so the extension check is on the
    # same string the rest of the handler will use for everything else.
    pre_safe_name = corpus_manifest.sanitise_filename(file.filename or "upload.pdf")
    ext = pre_safe_name.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        if not blob.startswith(b"%PDF-"):
            return JSONResponse({"error": "not a PDF (missing %PDF- magic header)"},
                                status_code=400)
    elif ext == "md":
        if b"\x00" in blob[:1024]:
            return JSONResponse({"error": "markdown file appears to be binary (NUL bytes in first 1 KB)"},
                                status_code=400)
        try:
            blob.decode("utf-8")
        except UnicodeDecodeError:
            return JSONResponse({"error": "markdown must be UTF-8 encoded"},
                                status_code=400)
    else:
        return JSONResponse({"error": f"unsupported extension .{ext}; allowed: .pdf, .md"},
                            status_code=400)

    # 3. Per-Member quota (Lab uncapped).
    if visitor_tier == "Member":
        usage = corpus_manifest.member_usage(visitor_email)
        if usage["file_count"] >= int(s["rag_member_doc_count_cap"]):
            return JSONResponse({"error": f"member doc count cap reached "
                                 f"({usage['file_count']} / {s['rag_member_doc_count_cap']}) "
                                 f"— delete an old upload first"}, status_code=413)
        max_total = int(s["rag_member_total_mb_cap"]) * 1024 * 1024
        if usage["total_bytes"] + len(blob) > max_total:
            return JSONResponse({"error": f"member total size cap reached "
                                 f"({(usage['total_bytes'] + len(blob)) // 1024 // 1024} MB / "
                                 f"{s['rag_member_total_mb_cap']} MB)"}, status_code=413)

    # 4. Sanitise + write. Auto-suffix on collision so we never overwrite.
    # Re-uses pre_safe_name from step 2 (already extension-dispatched + sanitised).
    safe_name = corpus_manifest.unique_filename(pre_safe_name)
    papers_dir = Path(s["rag_corpus_path"])
    papers_dir.mkdir(parents=True, exist_ok=True)
    target = papers_dir / safe_name
    target.write_bytes(blob)

    # 5. Manifest + audit.
    origin = "Lab" if visitor_tier == "Lab" else "Member"
    actor  = visitor_email if visitor_email else "Lab"
    clean_title = (title or "").strip()[:200] or None   # cap at 200 chars
    corpus_manifest.record_upload(safe_name, added_by=actor, origin=origin,
                                   size_bytes=len(blob), title=clean_title)

    # 6. Incremental index in background (don't block the POST response).
    loop = asyncio.get_event_loop()
    fut = loop.run_in_executor(None, lambda: rag_module.add_doc_to_index(safe_name))
    try:
        idx_result = await asyncio.wait_for(fut, timeout=60)
    except asyncio.TimeoutError:
        idx_result = {"chunks_added": None, "indexed": "still indexing in background"}
    except Exception as e:
        idx_result = {"error": str(e)}
    return {"ok": True, "filename": safe_name, "size_bytes": len(blob),
            "origin": origin, "indexed": idx_result}


@router.get("/rag/doc/{filename:path}", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def rag_doc_view(filename: str):
    """CR-051 follow-up — direct view of a corpus document for the in-page
    preview iframe. Anonymous-readable since the corpus is already publicly
    queryable through /rag/run (so the content isn't private even without
    direct view). Path-traversal guards mirror the DELETE handler.
    """
    safe = os.path.basename(filename)
    if not safe or "/" in safe or ".." in safe:
        return JSONResponse({"error": "invalid filename"}, status_code=400)
    s = cfg.load()
    target = Path(s["rag_corpus_path"]) / safe
    if not target.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    ext = target.suffix.lower()
    media_type = {
        ".pdf": "application/pdf",
        ".md":  "text/markdown; charset=utf-8",
    }.get(ext, "application/octet-stream")
    return FileResponse(
        path=str(target),
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{safe}"'},
    )


@router.delete("/rag/doc/{filename:path}", dependencies=[Depends(requires(RAG_CORPUS_DELETE_OWN))])
async def rag_doc_delete(filename: str, request: Request):
    """CR-051 — Lab: delete any. Member: delete own (ownership in manifest).

    The capability dispatch is bespoke here because the rule mixes tier
    (Lab) with per-row ownership (Member). Routes don't normally compare
    tiers, but this is the cleanest expression of "Lab can do anything,
    Member can only act on their own rows" — the auth check sits in the
    handler because the row data is part of the auth decision.
    """
    visitor_tier  = audience.tier(request).name
    visitor_email = auth.member_email_from_request(request) if visitor_tier == "Member" else None
    if visitor_tier == "Anonymous":
        return JSONResponse({"error": "sign in required"}, status_code=401)
    # Strip path components defensively — the {filename:path} param could
    # otherwise be used to delete `../../etc/passwd` style targets.
    safe_name = os.path.basename(filename)
    if not safe_name or "/" in safe_name or ".." in safe_name:
        return JSONResponse({"error": "invalid filename"}, status_code=400)

    if not corpus_manifest.can_delete(safe_name, visitor_tier, visitor_email):
        return JSONResponse({"error": "not your document (or you're not a member)"},
                            status_code=403)

    s = cfg.load()
    target = Path(s["rag_corpus_path"]) / safe_name
    existed_on_disk = target.exists()
    try:
        if existed_on_disk:
            target.unlink()
    except Exception as e:
        return JSONResponse({"error": f"could not remove file: {e}"}, status_code=500)

    # Remove chunks from the index. Idempotent — safe if the doc was never
    # indexed (e.g. removed before build-index ran).
    try:
        rag_module.remove_doc_from_index(safe_name)
    except Exception:
        pass

    actor = visitor_email if visitor_email else "Lab"
    corpus_manifest.record_delete(safe_name, actor=actor, tier=visitor_tier)
    return {"ok": True, "filename": safe_name, "removed_from_disk": existed_on_disk}


@router.get("/rag/audit", dependencies=[Depends(requires(SETTINGS_READ_FULL))])
async def rag_audit():
    """CR-051 — Lab-only view of the corpus audit log (last 200 events)."""
    return {"events": corpus_manifest.read_audit(limit=200)}


@router.post("/rag/build-index", dependencies=[Depends(requires(RAG_CORPUS_UPLOAD))])
async def rag_build_index(request: Request):
    body = await request.json()
    rebuild = bool(body.get("rebuild", False))
    if rag_module.index_status == "building":
        return {"status": "already_building"}
    loop = asyncio.get_event_loop()
    asyncio.create_task(loop.run_in_executor(None, lambda: rag_module.build_index(rebuild)))
    return {"status": "started"}


@router.post("/rag/run", dependencies=[Depends(requires(RAG_RUN))])
async def rag_run(
    request: Request,
    model_key: str = Form(...),
    rag_mode: str = Form(...),
    question: str = Form(None),
):
    if model_key not in rag_module.MODELS:
        return JSONResponse({"error": "Invalid model"}, status_code=400)
    if rag_mode not in rag_module.TOP_K:
        return JSONResponse({"error": f"Invalid rag_mode (allowed: {list(rag_module.TOP_K.keys())})"}, status_code=400)
    # CR-001 capability dispatch — free-form question → CUSTOM_PROMPT;
    # absent → curated canonical (Anonymous-OK).
    effective_question = question.strip() if question and question.strip() else None
    if effective_question is not None:
        gate(request, CUSTOM_PROMPT)
    else:
        effective_question = curated.CANONICAL_RAG_QUESTION
    if rag_mode != "baseline" and rag_module.index_status != "ready":
        return JSONResponse({"error": "Index not ready — build it first"}, status_code=400)

    job_id = str(uuid.uuid4())[:8]
    label = f"RAG — {rag_module.MODELS[model_key]['label']} · {rag_module.SHORT_MODE_LABELS.get(rag_mode, rag_mode)}"

    async def coro():
        jobs[job_id]["stage"] = "baseline"
        result = await rag_module.run_rag_measurement(model_key, rag_mode, effective_question, jobs, job_id)
        save_result("llm", job_id, result)
        jobs[job_id] = {"stage": "done", "result": result}

    position = queue_control.enqueue(job_id, "rag", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


@router.get("/rag/job/{job_id}", dependencies=[Depends(requires(QUEUE_VIEW))])
async def rag_job_status(job_id: str):
    return _job_status(job_id)


async def run_rag_compare_job(job_id: str, model_key: str, question: str):
    """4-mode RAG compare (baseline / rag / rag_blended / rag_large) on a single model.

    CR-050 alignment (2026-05-27): now uses the same active-probe thermal-floor
    cooldown as /rag/compare-models and /llm/compare-models, and emits explicit
    `stage` transitions per mode so the shared `wlRenderProgress` widget
    can show "Mode 2/3 · baseline" + cooldown progress instead of staying
    frozen on "inference" through the entire cooldown gap.

    Cooldown reference = mode #1's baseline (cold reading captured first).
    """
    from power import cooldown_between_runs, CooldownCancelled
    partial_results = {}
    modes = rag_module.COMPARE_MODES   # single source of truth — see rag.py
    floor_reference_w = None
    cooldowns = []
    try:
        for i, rag_mode in enumerate(modes):
            jobs[job_id]["current_mode"]     = rag_mode
            jobs[job_id]["mode_index"]       = i
            jobs[job_id]["total_modes"]      = len(modes)
            jobs[job_id]["partial_results"]  = dict(partial_results)
            # Inter-mode cooldown — same pattern as the N-model compare flows:
            # actively wait for power to drop back to model #1's cold baseline
            # ±3 W. Otherwise a fast mode after a long one measures a
            # contaminated baseline and the confidence flag goes 🔴.
            if i > 0 and floor_reference_w is not None:
                jobs[job_id]["stage"] = "cooldown"
                cd = await cooldown_between_runs(
                    fixed_seconds=cfg.load().get("llm_rest_s", 10),
                    reference_w=floor_reference_w,
                    stage="cooldown", jobs=jobs, job_id=job_id,
                    allow_dialog=True,
                )
                cooldowns.append({"before_mode": rag_mode, **cd})
            result = await rag_module.run_rag_measurement(
                model_key, rag_mode, question, jobs, job_id)
            partial_results[rag_mode] = result
            jobs[job_id]["partial_results"] = dict(partial_results)
            if floor_reference_w is None:
                floor_reference_w = (result.get("energy") or {}).get("w_base")

        final = {
            "mode": "rag_compare",
            "model_key": model_key,
            "model_label": rag_module.MODELS[model_key]["label"],
            "model_params": rag_module.MODELS[model_key]["params"],
            "question": question,
            "results": partial_results,
            "floor_reference_w": floor_reference_w,
            "cooldowns": cooldowns,
            "scope": "Device layer only (GoS1). Network and CPE excluded. No amortised training cost.",
        }
        save_result("llm", job_id, final)
        jobs[job_id] = {"stage": "done", "result": final}
    except CooldownCancelled:
        jobs[job_id] = {"stage": "cancelled",
                        "error": "Cancelled by operator during cooldown."}
    except Exception as e:
        jobs[job_id] = {"stage": "error", "error": str(e)}


@router.post("/rag/run-compare", dependencies=[Depends(requires(RAG_RUN))])
async def rag_run_compare(
    request: Request,
    model_key: str = Form(...),
    question: str = Form(None),
):
    if model_key not in rag_module.MODELS:
        return JSONResponse({"error": "Invalid model"}, status_code=400)
    # CR-001 capability dispatch — free-form 3-mode compare with a custom
    # question is BATCH_COMPARE (it crosses both axes: free-form input AND
    # multi-mode sweep); absent question falls back to curated, Anonymous-OK.
    effective_question = question.strip() if question and question.strip() else None
    if effective_question is not None:
        gate(request, BATCH_COMPARE)
    else:
        effective_question = curated.CANONICAL_RAG_QUESTION
    if rag_module.index_status != "ready":
        return JSONResponse({"error": "Index not ready — build it first"}, status_code=400)

    job_id = str(uuid.uuid4())[:8]
    label = f"RAG Compare — {rag_module.MODELS[model_key]['label']} · 3 modes"

    async def coro():
        await run_rag_compare_job(job_id, model_key, effective_question)

    position = queue_control.enqueue(job_id, "rag", label, coro, request=request,
                                     page="/rag/compare")
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


# --- CR-049 · /rag compare-across-models (sibling of /llm/compare) ---
# One corpus-grounded question × all 4 panel models, graded against a
# user-supplied expected answer. Same energy-per-correct-answer headline
# as /llm/compare; here the wrong-answer story has an extra dimension —
# the model can be wrong because *retrieval* surfaced the wrong chunk,
# not because the model is bad. Probe at /tmp/rag_probe/.

async def run_rag_compare_models_job(job_id: str, question: str, expected: str):
    """Sequentially run question through RAG (top-3) across every model in rag.MODELS, grade, save.

    Panel = list(rag_module.MODELS.keys()) so adding/swapping a model in
    rag.py is automatically reflected on /rag/compare.
    """
    panel = list(rag_module.MODELS.keys())
    from power import cooldown_between_runs, CooldownCancelled
    from llm import unload_all_loaded_models
    try:
        jobs[job_id].update({
            "status": "running", "stage": "compare_models",
            "total_models": len(panel), "current_model_idx": 0,
            "partial_response": "",
        })
        # Clear VRAM before measuring model #1's cold reference (see /llm/compare).
        unloaded = unload_all_loaded_models()
        if unloaded:
            await asyncio.sleep(2)
        rows = []
        floor_reference_w = None
        cooldowns = []
        for idx, model_key in enumerate(panel, start=1):
            if idx > 1 and floor_reference_w is not None:
                # Same Ollama keep_alive issue as /llm/compare — unload every
                # previously-run model before waiting for the thermal floor,
                # else the wait times out chasing a floor that 11+ GB of
                # resident VRAM is permanently inflating.
                evicted = unload_all_loaded_models()
                jobs[job_id]["stage"] = "cooldown"
                jobs[job_id]["current_model_idx"] = idx
                jobs[job_id]["current_model"] = model_key
                jobs[job_id]["current_model_label"] = rag_module.MODELS[model_key]["label"]
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
            jobs[job_id]["current_model_label"] = rag_module.MODELS[model_key]["label"]
            try:
                m_result = await rag_module.run_rag_measurement(
                    model_key, "rag", question, jobs, job_id,
                )
                if floor_reference_w is None:
                    floor_reference_w = (m_result.get("energy") or {}).get("w_base")
                inf = m_result.get("inference") or {}
                en = m_result.get("energy") or {}
                resp = inf.get("response", "") or ""
                ok = llm_grade(expected, resp)
                rows.append({
                    "model_key": model_key,
                    "model_label": rag_module.MODELS[model_key]["label"],
                    "params": rag_module.MODELS[model_key]["params"],
                    "response": resp,
                    "output_tokens": inf.get("output_tokens"),
                    "duration_s": inf.get("duration_s"),
                    "tokens_per_sec": inf.get("tokens_per_sec"),
                    "delta_w": en.get("delta_w"),
                    "delta_e_wh": en.get("delta_e_wh"),
                    "mwh_per_token": en.get("mwh_per_token"),
                    "confidence": en.get("confidence"),
                    "chunks_retrieved": m_result.get("chunks_retrieved"),
                    "chunk_sources": m_result.get("chunk_sources"),
                    "correct": ok,
                })
            except Exception as e:
                rows.append({
                    "model_key": model_key,
                    "model_label": rag_module.MODELS.get(model_key, {}).get("label", model_key),
                    "params": rag_module.MODELS.get(model_key, {}).get("params", "?"),
                    "error": str(e), "correct": False,
                })

        correct = [r for r in rows if r.get("correct") and (r.get("delta_e_wh") or 0) > 0]
        cheapest = min(correct, key=lambda r: r["delta_e_wh"]) if correct else None
        final = {
            "mode": "rag_compare_models",
            "question": question,
            "expected": expected,
            "models": rows,
            "cheapest_correct_key": cheapest["model_key"] if cheapest else None,
            "panel_pass_rate": round(len(correct) / len(rows), 3) if rows else 0,
            "floor_reference_w": floor_reference_w,
            "cooldowns": cooldowns,
            "scope": "Device layer only (GoS1). Network and CPE excluded. No amortised training cost. Retrieval = top-3 chunks (rag mode).",
        }
        save_result("llm", job_id, final)
        jobs[job_id] = {"status": "done", "stage": "done", "result": final}
    except CooldownCancelled:
        jobs[job_id] = {"status": "cancelled", "stage": "cancelled",
                        "error": "Cancelled by operator during cooldown."}
    except Exception as e:
        jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}


@router.post("/rag/compare-models", dependencies=[Depends(requires(BATCH_COMPARE))])
async def rag_compare_models(
    request: Request,
    question: str = Form(...),
    expected: str = Form(...),
):
    """Member 'Try your own question' for the RAG energy-per-correct-answer card."""
    question = (question or "").strip()
    expected = (expected or "").strip()
    if not question:
        return JSONResponse({"error": "question is required"}, status_code=400)
    if not expected:
        return JSONResponse({"error": "expected answer is required (grading needs ground truth)"},
                            status_code=400)
    if len(question) > 2000:
        return JSONResponse({"error": "question too long (max 2000 chars)"}, status_code=400)
    if rag_module.index_status != "ready":
        return JSONResponse({"error": "Index not ready — build it first"}, status_code=400)

    job_id = str(uuid.uuid4())[:8]
    label = f"RAG Compare · {question[:50]}{'…' if len(question) > 50 else ''}"

    async def coro():
        await run_rag_compare_models_job(job_id, question, expected)

    position = queue_control.enqueue(job_id, "rag", label, coro, request=request,
                                     page="/rag/compare")
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


# Hardcoded showcase data from the 2026-05-26 RAG probe — 1 rep per cell,
# real P110 measurement (not estimated). The probe tried 3 corpus-grounded
# prompts × 4 models; only this BBC prompt had a 4/4 panel pass rate. The
# two IEA candidates failed across the panel because top-3 retrieval missed
# the right pages of the 250-page IEA report — a finding worth keeping for
# a future "retrieval-precision matters" demo, but not a clean showcase.
# Probe data: /tmp/rag_probe/results_20260526_223406.jsonl
#
# NOTE (2026-05-27 — S30 ladder refresh): the rows below reference the
# PREVIOUS panel — `mistral` (7B) and `gemma3:12b` were retired in favour
# of `qwen3:4b` and `mistral-nemo:12b`. Real-P110 measurements preserved
# as a historical snapshot; a re-probe of the new 5-model panel via
# /rag/compare-models is the planned follow-up that will replace this dict.
_RAG_COMPARE_SHOWCASE = {
    'rag_bbc_total': {
        'label': 'BBC Radio 2018 energy total',
        'prompt': "According to the BBC Radio energy footprint paper (WHP 393), what was the total mean energy consumption for the 2018 baseline of BBC radio? Output the value and unit, e.g. '325 GWh'.",
        'expected': '325 GWh',
        'tagline': 'Single corpus fact, single right answer. Retrieval surfaces BBC WHP 393 for every model; the energy spread is purely the cost of inference at different model sizes.',
        'source_paper': 'BBC WHP 393 — Energy Footprint of Radio Services',
        'rows': [
            {'model': 'tinyllama',        'params': '1.1B', 'ok': True, 'ans': 'The BBC Radio energy footprint paper (WHP 393) reported that in 2018, the total mean energy consumption for the BBC radio system was 325 GW…',   'tok': 236, 'wall': 1.56,  'wh_measured': 0.0080, 'flag': '🟡'},
            {'model': 'qwen3:1.7b',       'params': '1.7B', 'ok': True, 'ans': 'The total mean energy consumption for BBC radio services in 2018, as stated in the document, was **325 GWh** (Gigawatt-hours). This value i…',  'tok': 426, 'wall': 4.29,  'wh_measured': 0.1179, 'flag': '🟡'},
            {'model': 'qwen3:4b',         'params': '4B',   'ok': True, 'ans': 'Based on the provided excerpts from the BBC Energy Footprint report (WHP 393), the total mean energy consumption for BBC radio services in…',  'tok': 652, 'wall': 9.54,  'wh_measured': 0.4553, 'flag': '🟢'},
            {'model': 'qwen3:8b',         'params': '8B',   'ok': True, 'ans': 'The total mean energy consumption for the BBC Radio services in 2018 was **325 GWh**. This figure is explicitly stated in the document and…', 'tok': 438, 'wall': 10.86, 'wh_measured': 0.6035, 'flag': '🟢'},
            {'model': 'mistral-nemo:12b', 'params': '12B',  'ok': True, 'ans': 'According to the BBC Radio energy footprint paper (page 19), the total mean energy consumption for the 2018 baseline of BBC radio was 325 G…', 'tok': 39,  'wall': 4.90,  'wh_measured': 0.0740, 'flag': '🟡'},
            {'model': 'phi4',             'params': '14B',  'ok': True, 'ans': 'According to the BBC Radio energy footprint paper, the total mean energy consumption for the 2018 baseline of BBC radio services was 325 GW…','tok': 62,  'wall': 4.88,  'wh_measured': 0.0801, 'flag': '🟡'},
            {'model': 'gpt-oss:20b',      'params': '20B',  'ok': True, 'ans': '325 GWh',                                                                                                                                  'tok': 141, 'wall': 12.34, 'wh_measured': 0.3739, 'flag': '🟢'},
        ],
    },
}


@router.get("/rag/compare", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def rag_compare_page(request: Request):
    """Hybrid showcase + member 'Try your own question' for RAG energy-per-correct-answer.

    Anonymous: BBC showcase card (4 models, real P110 data from the probe).
    Member (BATCH_COMPARE): question + expected-answer inputs → runs across all
    4 RAG-panel models sequentially with P110 measurement, renders into the
    same card.
    """
    can_batch = can(audience.tier(request), BATCH_COMPARE)
    lk_batch_class = _lock_class(request, BATCH_COMPARE)
    lk_batch_badge = _lock_badge_html(request, BATCH_COMPARE,
                                      "Try your own question — Members only")
    dis_batch = _disabled_attr(request, BATCH_COMPARE)

    import json as _json
    showcase_js = _json.dumps(_RAG_COMPARE_SHOWCASE)
    panel_n     = len(rag_module.MODELS)
    panel_list  = " &middot; ".join(f"{m['label']} ({m['params']})" for m in rag_module.MODELS.values())
    size_order_js = _json.dumps([m["params"] for m in rag_module.MODELS.values()])

    return _bake_durations(ui.render_page(request, "RAG · Compare across models", head=f"""    <script src="{CHARTJS_URL}"></script>
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
        .upload-note{{margin-top:1rem;padding:0.75rem 1rem;border:1px dashed var(--border-3);
                      background:var(--panel-2);font-size:0.78rem;color:var(--text-3);line-height:1.5}}
        .upload-note b{{color:var(--text-2)}}
        {_LOCK_STYLES}
""", body=f"""
    <a href="/rag" style="color:var(--text-3);text-decoration:none;font-size:0.82rem;
        margin-left:0.75rem;margin-bottom:1.5rem;display:inline-block;
        vertical-align:middle;position:relative;top:-2px;transition:color 0.2s"
        onmouseover="this.style.color='#00ff99'" onmouseout="this.style.color='#777'">&larr; /rag</a>
    <h1>RAG &middot; Compare across models</h1>
    <div class="subtitle">Energy cost of correct answers from the corpus. Device layer only (GoS1). Network and CPE excluded.</div>

    <div class="demo-tabs" id="tabs"></div>

    <div class="prompt-card">
        <div class="label-sm">Question</div>
        <div class="prompt-text" id="prompt-text"></div>
        <div class="prompt-meta">Expected: <b id="expected"></b> &middot; Retrieval: top-3 chunks &middot; Source: <span id="source-paper" style="color:var(--text-2)"></span></div>
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

    <div class="label-sm">Same question, all models &mdash; ranked by energy of a correct answer</div>
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
        <h2>Try your own question</h2>
        <div class="desc">
            Runs your question across all {panel_n} RAG-panel models sequentially with P110 power measurement.
            Each model retrieves the top 3 chunks from the corpus (94 papers) before answering. Between models the runner actively polls power and waits for the system to return to within &plusmn;3 W of model #1's baseline (max 120 s cap), so a verbose model's heat can't skew the next baseline.
        </div>
        <div class="label-sm">Question</div>
        <textarea id="userQuestion" rows="3"{dis_batch}
            placeholder="e.g. According to the IEA Energy and AI report, what is the projected global data centre electricity consumption in 2030, in TWh?"></textarea>
        <div class="label-sm" style="margin-top:0.85rem">Expected answer (used to grade &#10003;/&#10007;)</div>
        <input type="text" id="userExpected"{dis_batch}
            placeholder="e.g. 945">
        <div class="label-sm" style="margin-top:0.5rem;color:var(--text-5)">
            Substring match, case-insensitive (with a punctuation-stripped retry). For numeric answers, leading-integer match.
        </div>
        <button class="run" id="runBtn" onclick="runCompare()"{dis_batch}>Run on all {panel_n} models &rarr;</button>
        <div id="run-status" style="margin-top:1.25rem"></div>
        <div class="upload-note">
            <b>Want to ask about a document we don't have?</b> Document upload is coming in a future release.
            The current corpus is 94 curated papers covering streaming energy, network infrastructure, AI/data-centre energy,
            and policy. Until upload ships, the only path is to drop a PDF into the server's <code>corpus/papers/</code>
            directory and rebuild the index &mdash; ask the GoS team.
        </div>
    </div>

    <details>
        <summary>Methodology &amp; scope</summary>
        <p><b>What's measured:</b> {meter_display_name()} wall-power at 1 Hz, baseline before each model (10 polls), &Delta;W &times; &Delta;t &rarr; Wh, mWh/output_token, Traffic Light Confidence per the CR-028 CI model. Same protocol as the existing /rag endpoint.</p>
        <p><b>Why "Wh per correct answer" is the headline:</b> mWh/token rewards verbose models &mdash; a model that "thinks out loud" looks more efficient per token than a model that answers in 1 token, even when it burned 100&times; the energy. The headline metric is the energy cost of <em>correctness</em>. mWh/token stays as a supporting column because it's the canonical operator-facing figure.</p>
        <p><b>RAG-specific wrong-answer story:</b> A model can be wrong because retrieval gave it the wrong chunk (so the answer was generated from training memory, with no anchor), or because it was right but couldn't extract. The 2026-05-26 probe found two IEA prompts where all 4 models failed because top-3 retrieval missed the right pages of the 250-page IEA report &mdash; a finding the energy data makes vivid: you can burn watts producing wrong answers from bad retrieval.</p>
        <p><b>{panel_n}-model panel:</b> {panel_list}. All on GoS1 (Ryzen 9 7900 + {ui._gpu_display_name()}, Ollama 0.20.2). Panel reflects the current <code>rag.MODELS</code> dict; the BBC showcase card is frozen on the older 4-model probe and will be re-baselined when a fresh probe of the new panel runs.</p>
        <p><b>Grading:</b> Same tolerant rule as /llm/compare &mdash; substring match (case-insensitive) or punctuation-stripped substring or leading-integer match.</p>
    </details>

    <a class="back" href="/rag">&larr; /rag (single-model + 3-mode compare)</a>

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

    const tabs = document.getElementById('tabs');
    const order = Object.keys(SHOWCASE);
    order.forEach(k => {{
        const b = document.createElement('button');
        b.textContent = SHOWCASE[k].label;
        b.id = 'tab-' + k;
        b.onclick = () => renderShowcase(k);
        tabs.appendChild(b);
    }});

    function paramsToNumeric(p) {{
        return parseFloat(String(p).replace(/[^\\d.]/g, '')) || 0;
    }}

    function renderShowcase(key) {{
        const d = SHOWCASE[key];
        order.forEach(k => document.getElementById('tab-'+k).classList.toggle('active', k === key));
        // Showcase uses real measured Wh per row (probe data), not the wall × 25W estimate.
        // Prefer per-row wh_measured (real P110 from showcase regeneration);
        // fall back to legacy parallel array d.wh_measured[i] if a row lacks
        // its own value, then to wall × 25 W estimate.
        const measured = d.wh_measured || [];
        const rows = d.rows.map((r, i) => ({{...r, whEst: (r.wh_measured != null ? r.wh_measured
                                                            : (i < measured.length ? measured[i] : wh(r.wall)))}}));
        document.getElementById('source-paper').textContent = d.source_paper || '—';
        renderCompareCard({{
            promptText: d.prompt, expected: d.expected,
            rows: rows, tagline: d.tagline, sourceLabel: 'Showcase (P110 measured)',
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
            document.getElementById('hero-cheap-sub').textContent = 'No model in the panel got it right — likely a retrieval miss.';
        }}

        const sizeOrder = {size_order_js};
        const sIdx = p => sizeOrder.indexOf(p);
        let bustHead = '', bustDetail = '';
        const biggerWrong = payload.rows.filter(r => !r.ok && cheapest && sIdx(r.params) > sIdx(cheapest.params));
        if (biggerWrong.length) {{
            const bw = biggerWrong[biggerWrong.length-1];
            bustHead = bw.model.replace(':latest','') + ' (' + bw.params + ') was wrong; ' +
                       cheapest.model.replace(':latest','') + ' (' + cheapest.params + ') was right';
            bustDetail = 'A larger model (' + bw.params + ') failed while a smaller one (' + cheapest.params + ') succeeded. On RAG, this often means the smaller model trusted the retrieved chunk while the larger one hallucinated past it.';
        }} else if (cheapest && trustedCorrect.length > 1) {{
            const priciest = trustedCorrect[trustedCorrect.length-1];
            const ratio = (priciest.whEst / cheapest.whEst).toFixed(1);
            bustHead = 'Same answer, ' + ratio + '&times; more energy';
            bustDetail = priciest.model.replace(':latest','') + ' (' + priciest.params + ') and ' + cheapest.model.replace(':latest','') + ' (' + cheapest.params + ') both retrieved the same chunks and answered correctly &mdash; the larger model used ' + ratio + '&times; the energy for the same output.';
        }} else {{
            bustHead = 'No size-vs-smarts split on this question';
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
            h = 'No model in the panel got this question right at all &mdash; check whether the retrieved chunks actually contained the answer (top-3 retrieval can miss in a long source).';
        }}
        document.getElementById('headline').innerHTML =
            '<div class="label-sm">What this tells you</div>' + h +
            ' <span style="color:var(--text-5)">[' + payload.sourceLabel + ']</span>';

        renderCharts(payload);
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

    function escapeHTML(s) {{
        return String(s).replace(/[&<>"']/g, c => ({{
            '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
        }}[c]));
    }}

    async function runCompare() {{
        if (!CAN_BATCH) return;
        stopCooldownTicker();
        const question = document.getElementById('userQuestion').value.trim();
        const expected = document.getElementById('userExpected').value.trim();
        if (!question || !expected) {{
            document.getElementById('run-status').innerHTML =
                '<div style="color:var(--err);font-size:0.85rem">Both question and expected answer are required.</div>';
            return;
        }}
        const btn = document.getElementById('runBtn');
        btn.disabled = true;
        document.getElementById('run-status').innerHTML =
            '<div style="color:var(--warn);font-size:0.85rem">Queued &mdash; running across {panel_n} models with active-probe thermal floor wait between each&hellip;</div>';
        const form = new FormData();
        form.append('question', question);
        form.append('expected', expected);
        try {{
            const resp = await fetch('/rag/compare-models', {{method:'POST', body:form}});
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
            const resp = await fetch('/rag/job/' + jobId);
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
                document.getElementById('source-paper').textContent = '(live run — corpus retrieval)';
                renderCompareCard({{
                    promptText: r.question, expected: r.expected,
                    rows: rows, tagline: '', sourceLabel: 'Live (P110 measured)',
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

    renderShowcase(order[0]);
    // Resume a queued/running compare job (↩ Resume from /queue-status).
    const _resumeJob = new URLSearchParams(location.search).get('job');
    if (_resumeJob) {{ var _rb = document.getElementById('runBtn'); if (_rb) _rb.disabled = true; pollCompare(_resumeJob); }}
    </script>
"""))
