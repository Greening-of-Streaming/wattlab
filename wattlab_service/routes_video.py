"""
Video routes — /video transcode energy test (the production-grade core
workload): page, run_job orchestration, source picker/upload, preview-cmd,
and job status.

Measurement stays in video.py. benchmark.py reaches run_job through the
main.py alias; tests pin main.run_job / main.video_preview_cmd the same
way. Phase 3 per-feature route module — shared state from runtime.py,
chrome from ui.py, never import main.
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

import audience
import queue_control
import settings as cfg
import ui
from capabilities import (requires, can, gate,
                          BATCH_COMPARE, CUSTOM_PROMPT, CUSTOM_UPLOAD,
                          PUBLIC_PAGE, QUEUE_VIEW, VIDEO_RUN)
from persist import save_result
from runtime import jobs, job_status as _job_status
from sources import get_all_sources, get_grouped_sources, PRELOADED
from ui import (_CONF_HELP_WIDGET, _LOCK_STYLES, _PROGRESS_JS, _RESULT_JS,
                _bake_durations, _disabled_attr, _gpu_enc,
                _lock_badge_html, _lock_class)
from video import (run_video_measurement, run_both_measurement,
                   run_all_measurement, run_codecs_single_measurement,
                   UPLOAD_DIR)

router = APIRouter()


# --- Video page ---

def _video_source_picker_html() -> str:
    """CR-047 — render the /video Source picker from
    `sources.get_grouped_sources()`. Pre-CR-047 the radios were a
    hardcoded HTML block alongside `sources.PRELOADED`; this drives them
    off the schema so adding a variant only requires editing sources.py.
    Each parent gets a small dim header (name + license), variants under
    it as radios with the same density / border style as the upload row.
    """
    label_style = (
        "display:flex;align-items:flex-start;gap:0.75rem;"
        "border:1px solid var(--border-3);padding:0.75rem;cursor:pointer"
    )
    radio_style = "margin-top:0.2rem;accent-color:var(--accent)"
    title_style = "color:var(--text);font-size:0.85rem"
    desc_style = "color:var(--text-3);font-size:0.75rem"
    header_style = (
        "color:var(--text-4);font-size:0.7rem;text-transform:uppercase;"
        "letter-spacing:0.05em;padding:0.5rem 0 0.15rem;"
        "display:flex;align-items:center;gap:0.5rem"
    )
    thumb_style = (
        "height:32px;width:auto;border-radius:2px;"
        "border:1px solid var(--border-3);flex-shrink:0"
    )
    # Subtle hyperlink style — inherit the dim header colour, dotted underline
    # so the link is discoverable without shouting (full underline would read
    # as link-soup against the deliberately quiet header row).
    link_style = "color:inherit;text-decoration:none;border-bottom:1px dotted var(--border-3)"
    parts = []
    for src in get_grouped_sources():
        lic = src.get("license")
        suffix = f" · {lic}" if lic else ""
        thumb = src.get("vignette")
        thumb_html = (f'<img src="{thumb}" alt="" style="{thumb_style}">'
                      if thumb else "")
        url = src.get("source_url")
        label = f'{src["name"]}{suffix}'
        # External link → new tab + noopener so the picker keeps its state.
        # No url → plain <span> (e.g. the in-house GoS promo has no canonical
        # external page to link to).
        label_html = (
            f'<a href="{url}" target="_blank" rel="noopener" '
            f'title="Canonical source · {url}" style="{link_style}">{label}</a>'
            if url else f'<span>{label}</span>'
        )
        parts.append(
            f'<div style="{header_style}">'
            f'{thumb_html}{label_html}'
            f'</div>'
        )
        if src.get("character"):
            parts.append(
                f'<div style="font-size:0.72rem;color:var(--text-5);'
                f'line-height:1.5;margin:-0.2rem 0 0.5rem 0;font-style:italic">'
                f'{src["character"]}</div>'
            )
        for v in src["variants"]:
            key = v["key"]
            parts.append(
                f'<label style="{label_style}">'
                f'<input type="radio" name="source" value="{key}" '
                f'onchange="selectSource(\'{key}\')" '
                f'style="{radio_style}">'
                f'<div>'
                f'<div style="{title_style}">{v["variant_label"]}</div>'
                f'<div style="{desc_style}">{v["description"]}</div>'
                f'</div>'
                f'</label>'
            )
    return "".join(parts)


@router.get("/video", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def video_page(request: Request):
    # CR-001 part C2c — custom ffmpeg edits were Lab-only by UI before
    # CR-001 had a notion of Member tier. Now they key on CUSTOM_PROMPT
    # (Member+), matching the runtime gate in /video/use-source. The
    # all_codecs preset and custom-cmd textareas show as locked for
    # Anonymous with a "Members only · Join GoS" badge.
    can_custom_cmd    = can(audience.tier(request), CUSTOM_PROMPT)
    can_batch_compare = can(audience.tier(request), BATCH_COMPARE)
    can_upload        = can(audience.tier(request), CUSTOM_UPLOAD)
    lk_cmd_class      = _lock_class(request, CUSTOM_PROMPT)
    lk_cmd_badge      = _lock_badge_html(request, CUSTOM_PROMPT, "Custom ffmpeg — Members only")
    lk_batch_class    = _lock_class(request, BATCH_COMPARE)
    lk_batch_badge    = _lock_badge_html(request, BATCH_COMPARE, "All-codecs sweep — Members only")
    lk_upload_class   = _lock_class(request, CUSTOM_UPLOAD)
    lk_upload_badge   = _lock_badge_html(request, CUSTOM_UPLOAD, "Upload — Members only")
    upload_disabled   = _disabled_attr(request, CUSTOM_UPLOAD)
    queue_depth = queue_control.depth()
    busy_banner = (f'<div style="background:var(--border-3);color:var(--warn);padding:0.75rem 1rem;'
                   f'margin-bottom:1rem;font-size:0.85rem">'
                   f'⏱ {queue_depth} job{"s" if queue_depth != 1 else ""} in queue — '
                   f'yours will be added and run automatically.</div>') \
        if queue_depth > 0 else ""
    source_picker_html = _video_source_picker_html()
    # CR-054 — discreet beta link to the AV1 hw-vs-sw VMAF finding (the
    # worked example). Gated on `findings_enabled` so the same flag that
    # rolls back the /findings route also removes this link. When CR-055
    # (catalog index) ships, this can repoint at /findings with a video
    # filter; for now it deep-links to the one finding that exists.
    findings_beta_html = ""
    if cfg.load().get("findings_enabled", False):
        findings_beta_html = (
            '<div style="margin-bottom:1rem;font-size:0.78rem;color:var(--text-3);'
            'border-left:2px solid var(--accent-soft);padding-left:0.75rem">'
            '<span style="font-size:0.55rem;letter-spacing:0.08em;color:var(--text-5);'
            'border:1px solid var(--border-3);padding:0.1rem 0.35rem;'
            'text-transform:uppercase;margin-right:0.4rem">beta</span>'
            'Some initial findings: '
            '<a href="/findings" '
            'style="color:var(--accent);text-decoration:none">'
            'browse the OWL findings catalog →</a>'
            '</div>'
        )

    return _bake_durations(ui.render_page(request, "Video Test", styles=f"""
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: monospace; background: var(--bg); color: var(--text);
               max-width: 780px; margin: 0 auto; padding: 2rem; }}
        h1 {{ color: var(--accent); margin-bottom: 0.25rem; font-size: 1.6rem; }}
        .subtitle {{ color: var(--text-3); font-size: 0.8rem; margin-bottom: 1.5rem; }}
        .info {{ color: var(--text-3); font-size: 0.82rem; margin-bottom: 1.5rem;
                 border-left: 2px solid #222; padding-left: 1rem; line-height: 1.6; }}
        .presets {{ display: flex; gap: 0.75rem; margin-bottom: 1.5rem; }}
        .preset {{ border: 1px solid var(--border-3); padding: 1rem; cursor: pointer;
                   flex: 1; transition: border-color 0.15s; }}
        .preset:hover {{ border-color: #00ff9966; }}
        .preset.selected {{ border-color: var(--accent); background: #00ff9911; }}
        .batch-box {{ border: 1px solid #00ff9933; cursor: pointer; transition: border-color 0.15s; }}
        .batch-box:hover {{ border-color: #00ff9966; }}
        .batch-box.selected {{ border-color: var(--accent); background: #00ff9911; }}
        .batch-box.lock-block {{ cursor: not-allowed; }}
        .preset h3 {{ color: var(--accent); font-size: 0.9rem; margin-bottom: 0.4rem; }}
        .preset p {{ color: var(--text-4); font-size: 0.78rem; line-height: 1.5; }}
        .preset .badge {{ display: inline-block; background: #00ff9922;
                          color: var(--accent); font-size: 0.7rem;
                          padding: 0.1rem 0.4rem; margin-bottom: 0.4rem; }}
        .pdesc {{ margin-top: 0.4rem; }}
        .pdesc summary {{ color: var(--text-4); font-size: 0.7rem; cursor: pointer; list-style: none; }}
        .pdesc summary::-webkit-details-marker {{ display: none; }}
        .pdesc summary::before {{ content: '▸ '; }}
        details[open].pdesc summary::before {{ content: '▾ '; }}
        .pdesc[open] {{ color: var(--text-3); font-size: 0.72rem; line-height: 1.5; padding-top: 0.3rem; }}
        input[type=file] {{ color: var(--text-2); margin-bottom: 1rem; width: 100%; }}
        button {{ background: var(--accent); color: #000; border: none;
                  padding: 0.75rem 2rem; cursor: pointer;
                  font-family: monospace; font-size: 1rem; }}
        button:disabled {{ background: var(--border); color: var(--text-3); cursor: not-allowed; }}
        button:hover:not(:disabled) {{ background: var(--accent-hover); }}
        #status {{ margin-top: 1.5rem; }}

        /* Progress styles */
        .progress-box {{ border: 1px solid var(--border); padding: 1.5rem; }}
        .progress-header {{ color: var(--warn); font-size: 0.9rem; margin-bottom: 1.25rem; }}
        .stages {{ display: flex; flex-direction: column; gap: 0.5rem; margin-bottom: 1.25rem; }}
        .stage {{ display: flex; align-items: center; gap: 0.75rem; font-size: 0.82rem; }}
        .stage-icon {{ width: 1.2rem; text-align: center; flex-shrink: 0; }}
        .stage-label {{ color: var(--text-4); }}
        .stage.done .stage-label {{ color: var(--accent); }}
        .stage.active .stage-label {{ color: var(--warn); }}
        .stage.active .stage-icon {{ animation: pulse 1s infinite; }}
        @keyframes pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.3; }} }}
        .progress-footer {{ display: flex; justify-content: space-between;
                            color: var(--text-4); font-size: 0.78rem; border-top: 1px solid var(--panel);
                            padding-top: 0.75rem; }}
        .elapsed {{ color: var(--text-3); }}

        /* Report styles */
        .report h2 {{ color: var(--accent); font-size: 1.1rem; margin-bottom: 1rem;
                      padding-bottom: 0.5rem; border-bottom: 1px solid var(--border); }}
        .cols {{ display: flex; gap: 1rem; margin-bottom: 1rem; }}
        .col {{ flex: 1; border: 1px solid var(--border); padding: 1rem; }}
        .col h3 {{ color: var(--accent); font-size: 0.85rem; margin-bottom: 0.4rem; }}
        .col .sub {{ color: var(--text-3); font-size: 0.75rem; margin-bottom: 0.75rem; }}
        .metric {{ display: flex; justify-content: space-between;
                   padding: 0.3rem 0; border-bottom: 1px solid var(--panel); font-size: 0.82rem; }}
        .metric:last-child {{ border-bottom: none; }}
        .val {{ color: var(--accent); }}
        .section-title {{ color: var(--text-4); font-size: 0.72rem; text-transform: uppercase;
                          letter-spacing: 0.05em; margin: 0.75rem 0 0.4rem; }}
        .analysis-box {{ border: 1px solid #00ff9944; padding: 1rem;
                         margin-bottom: 1rem; background: #00ff9908; }}
        .analysis-box h3 {{ color: var(--accent); font-size: 0.85rem; margin-bottom: 0.5rem; }}
        .finding {{ color: var(--text-2); font-size: 0.85rem; line-height: 1.7; }}
        .conf-note {{ color: var(--text-4); font-size: 0.78rem; margin-top: 0.5rem; }}
        .scope-note {{ color: var(--text-5); font-size: 0.72rem; margin-top: 1rem; }}
        .single-report {{ border: 1px solid var(--border); padding: 1.5rem; }}
        a.back {{ color: var(--text-3); text-decoration: none; font-size: 0.82rem;
                  display: inline-block; margin-top: 1.5rem; }}
        a.back:hover {{ color: var(--accent); }}
        {_LOCK_STYLES}
""", body=f"""
    {busy_banner}
    <h1>Video Transcode Energy Test</h1>
    <div class="subtitle">Greening of Streaming · OWL · GoS1</div>

    <div style="margin-bottom:1rem;font-size:0.78rem;color:var(--text-3)">
        First time here? <a href="/demo" style="color:var(--accent);text-decoration:none">Try the Guided Tour →</a>
    </div>

    {findings_beta_html}

    <details style="margin-bottom:1.5rem;border-left:2px solid #222;padding-left:1rem">
        <summary style="cursor:pointer;color:var(--text-3);font-size:0.82rem;list-style:none;outline:none">
            ⓘ About this test <span style="color:var(--text-4);font-size:0.72rem">(click to expand)</span>
        </summary>
        <div style="color:var(--text-3);font-size:0.82rem;line-height:1.6;margin-top:0.75rem">
            Transcode a source video and measure the server's wall-power draw during the encode.<br>
            Accepted: MP4, MOV, MKV, AVI, WebM, TS · Max 1GB.<br>
            Baseline measured 10s before each run · P110 + thermals at 1s intervals.<br>
            All GPU presets use the full VAAPI pipeline (hardware decode + encode + scale) — representative of live encoding workflows.<br>
            Rate control is ABR (constant bitrate target) across all 6 presets so CPU and GPU receive identical tasks.<br>
            Scope: device layer only — network, CDN, and client devices (CPE) excluded.
        </div>
    </details>

    <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                letter-spacing:0.05em;margin-bottom:0.5rem">H.264</div>
    <div class="presets" style="margin-bottom:0.75rem">
        <div class="preset" id="preset-cpu" onclick="selectPreset('cpu')">
            <h3>H.264 CPU</h3>
            <p class="pspec">libx264 · ABR · 1080p</p>
            <details class="pdesc"><summary>details</summary>Software encode across all 24 cores.</details>
        </div>
        <div class="preset" id="preset-gpu" onclick="selectPreset('gpu')">
            <h3>H.264 GPU</h3>
            <p class="pspec">{_gpu_enc('h264')} · ABR · 1080p · full pipeline</p>
            <details class="pdesc"><summary>details</summary>Hardware decode + encode. Full GPU pipeline — representative of live encoding.</details>
        </div>
        <div class="preset selected" id="preset-both" onclick="selectPreset('both')">
            <h3>H.264 Both</h3>
            <p class="pspec">CPU then GPU · same file</p>
            <details class="pdesc"><summary>details</summary>Side-by-side energy + thermal report with analysis.</details>
        </div>
    </div>
    <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                letter-spacing:0.05em;margin-bottom:0.5rem">H.265</div>
    <div class="presets" style="margin-bottom:0.75rem">
        <div class="preset" id="preset-h265_cpu" onclick="selectPreset('h265_cpu')">
            <h3>H.265 CPU</h3>
            <p class="pspec">libx265 · ABR · 1080p</p>
            <details class="pdesc"><summary>details</summary>Software HEVC encode.</details>
        </div>
        <div class="preset" id="preset-h265_gpu" onclick="selectPreset('h265_gpu')">
            <h3>H.265 GPU</h3>
            <p class="pspec">{_gpu_enc('h265')} · ABR · 1080p · full pipeline</p>
            <details class="pdesc"><summary>details</summary>Hardware decode + encode. Full GPU pipeline.</details>
        </div>
        <div class="preset" id="preset-h265_both" onclick="selectPreset('h265_both')">
            <h3>H.265 Both</h3>
            <p class="pspec">CPU then GPU · same file</p>
            <details class="pdesc"><summary>details</summary>Side-by-side H.265 CPU vs GPU comparison.</details>
        </div>
    </div>
    <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                letter-spacing:0.05em;margin-bottom:0.5rem">AV1</div>
    <div class="presets" style="margin-bottom:1.5rem">
        <div class="preset" id="preset-av1_cpu" onclick="selectPreset('av1_cpu')">
            <h3>AV1 CPU</h3>
            <p class="pspec">libsvtav1 · ABR · 1080p</p>
            <details class="pdesc"><summary>details</summary>SVT-AV1 software encode.</details>
        </div>
        <div class="preset" id="preset-av1_gpu" onclick="selectPreset('av1_gpu')">
            <h3>AV1 GPU</h3>
            <p class="pspec">{_gpu_enc('av1')} · ABR · 1080p · full pipeline</p>
            <details class="pdesc"><summary>details</summary>Hardware decode + AV1 encode on the GPU's dedicated AV1 engine.</details>
        </div>
        <div class="preset" id="preset-av1_both" onclick="selectPreset('av1_both')">
            <h3>AV1 Both</h3>
            <p class="pspec">CPU then GPU · same file</p>
            <details class="pdesc"><summary>details</summary>Side-by-side AV1 CPU vs GPU comparison.</details>
        </div>
    </div>

    {lk_batch_badge}
    <div class="batch-box {lk_batch_class}" style="padding:0.9rem 1rem;margin-bottom:0.6rem;
                display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.5rem"
         id="preset-codecs_cpu" onclick="if(CAN_BATCH_COMPARE) selectPreset('codecs_cpu')">
        <div>
            <div style="color:var(--accent);font-size:0.9rem;font-weight:bold">Compare codecs · CPU (software)</div>
            <div style="color:var(--text-3);font-size:0.75rem;margin-top:0.2rem">H.264 · H.265 · AV1 on CPU · same source · same target bitrate — which codec is cheapest in software</div>
        </div>
        <div style="color:var(--text-4);font-size:0.75rem">~3× longer · locks queue</div>
    </div>
    <div class="batch-box {lk_batch_class}" style="padding:0.9rem 1rem;margin-bottom:0.6rem;
                display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.5rem"
         id="preset-codecs_gpu" onclick="if(CAN_BATCH_COMPARE) selectPreset('codecs_gpu')">
        <div>
            <div style="color:var(--accent);font-size:0.9rem;font-weight:bold">Compare codecs · GPU (hardware)</div>
            <div style="color:var(--text-3);font-size:0.75rem;margin-top:0.2rem">H.264 · H.265 · AV1 on GPU · same source · same target bitrate — which codec is cheapest in hardware</div>
        </div>
        <div style="color:var(--text-4);font-size:0.75rem">~3× longer · locks queue</div>
    </div>
    <div class="batch-box {lk_batch_class}" style="padding:0.9rem 1rem;margin-bottom:1.5rem;
                display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.5rem"
         id="preset-all_codecs" onclick="if(CAN_BATCH_COMPARE) selectPreset('all_codecs')">
        <div>
            <div style="color:var(--accent);font-size:0.9rem;font-weight:bold">Compare all (CPU vs GPU)</div>
            <div style="color:var(--text-3);font-size:0.75rem;margin-top:0.2rem">H.264 · H.265 · AV1 · CPU + GPU · same source · same target bitrate — full matrix</div>
        </div>
        <div style="color:var(--text-4);font-size:0.75rem">~6× longer · locks queue</div>
    </div>

    <div style="margin-bottom:1.5rem">
        <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                    letter-spacing:0.05em;margin-bottom:0.75rem">Source</div>
        <div style="display:flex;flex-direction:column;gap:0.5rem">
            <label style="display:flex;align-items:flex-start;gap:0.75rem;
                          border:1px solid var(--border-3);padding:0.75rem;cursor:pointer"
                   id="src-upload-label">
                <input type="radio" name="source" value="upload" checked
                       onchange="selectSource('upload')"
                       style="margin-top:0.2rem;accent-color:var(--accent)">
                <div>
                    <div style="color:var(--text);font-size:0.85rem">Upload a file</div>
                    <div style="color:var(--text-3);font-size:0.75rem">MP4, MOV, MKV, AVI, WebM, TS · Max 1GB</div>
                </div>
            </label>
            {source_picker_html}
        </div>
    </div>

    <div id="cmd-preview-area" class="{lk_cmd_class}" style="margin-bottom:1.5rem;display:none">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:0.5rem">
            <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                        letter-spacing:0.05em">ffmpeg command</div>
            <div>{lk_cmd_badge}</div>
        </div>
        <div id="cmd-preview-box"></div>
    </div>

    <div id="upload-area" class="{lk_upload_class}">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:0.5rem">
            <div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;
                        letter-spacing:0.05em">Upload your own</div>
            <div>{lk_upload_badge}</div>
        </div>
        <input type="file" id="fileInput" accept=".mp4,.mov,.mkv,.avi,.webm,.ts"{upload_disabled}>
    </div>
    <button id="runBtn" onclick="uploadAndRun()"{upload_disabled}>Upload & Measure</button>

    <div id="status"></div>
    <div id="prev-runs" style="margin-top:2rem;border-top:1px solid var(--panel);padding-top:1.5rem"></div>

    <script>
    // CR-001 part C2c — capability flags from server. CAN_CUSTOM_CMD
    // mirrors the CUSTOM_PROMPT cap the /video/use-source route gates on;
    // CAN_BATCH_COMPARE mirrors the BATCH_COMPARE gate for all_codecs.
    const CAN_CUSTOM_CMD = {'true' if can_custom_cmd else 'false'};
    const CAN_BATCH_COMPARE = {'true' if can_batch_compare else 'false'};
    // IS_LAN kept as an alias so _cmdBox() reads naturally — same
    // editable-textarea-vs-readonly-div decision, just resolved against
    // the right capability now.
    const IS_LAN = CAN_CUSTOM_CMD;
    let selectedPreset = 'both';
    let selectedSource = 'upload';
    let customCmds = {{}};   // {{single: str}} or {{cpu: str, gpu: str}}

    function selectSource(src) {{
        selectedSource = src;
        document.getElementById('upload-area').style.display =
            src === 'upload' ? 'block' : 'none';
        document.getElementById('runBtn').textContent =
            src === 'upload' ? 'Upload & Measure' : 'Run Measurement';
    }}

    function _cmdBox(id, value, forceReadonly=false) {{
        if (IS_LAN && !forceReadonly) {{
            return '<textarea id="' + id + '" rows="3" spellcheck="false" '
                + 'style="width:100%;background:var(--panel-2);border:1px solid var(--border-2);'
                + 'color:var(--text-2);font-family:monospace;font-size:0.72rem;'
                + 'padding:0.5rem;resize:vertical;line-height:1.5">'
                + value + '</textarea>';
        }} else {{
            return '<div style="background:var(--panel-2);border:1px solid var(--border-2);'
                + 'padding:0.5rem;font-family:monospace;font-size:0.72rem;'
                + 'color:var(--text-3);word-break:break-all;line-height:1.5">' + value + '</div>';
        }}
    }}

    async function fetchCmdPreview(preset) {{
        const area = document.getElementById('cmd-preview-area');
        const box  = document.getElementById('cmd-preview-box');
        try {{
            const resp = await fetch('/video/preview-cmd?preset=' + preset);
            const data = await resp.json();
            if (data.mode === 'all_codecs') {{
                customCmds = {{}};
                const labels = {{cpu:'H.264 CPU',gpu:'H.264 GPU',h265_cpu:'H.265 CPU',h265_gpu:'H.265 GPU',av1_cpu:'AV1 CPU',av1_gpu:'AV1 GPU'}};
                box.innerHTML = Object.entries(data.cmds).map(([k,v]) =>
                    '<div style="color:var(--text-4);font-size:0.7rem;margin:0.4rem 0 0.2rem">' + (labels[k]||k) + '</div>'
                    + _cmdBox('cmd_'+k, v, true)
                ).join('');
            }} else if (data.mode === 'both') {{
                customCmds = {{cpu: data.cpu_cmd, gpu: data.gpu_cmd}};
                box.innerHTML =
                    '<div style="color:var(--text-4);font-size:0.7rem;margin-bottom:0.3rem">CPU</div>'
                    + _cmdBox('cmd_cpu', data.cpu_cmd)
                    + '<div style="color:var(--text-4);font-size:0.7rem;margin:0.5rem 0 0.3rem">GPU</div>'
                    + _cmdBox('cmd_gpu', data.gpu_cmd);
            }} else {{
                customCmds = {{single: data.cmd}};
                box.innerHTML = _cmdBox('cmd_single', data.cmd);
            }}
            area.style.display = 'block';
        }} catch(e) {{
            box.innerHTML = '<div style="color:var(--text-3);font-size:0.72rem">Could not load preview</div>';
            area.style.display = 'block';
        }}
    }}

    function _getCustomCmds() {{
        if (selectedPreset === 'both') {{
            const cpu = document.getElementById('cmd_cpu');
            const gpu = document.getElementById('cmd_gpu');
            return {{
                custom_cmd_cpu: cpu ? cpu.value : '',
                custom_cmd_gpu: gpu ? gpu.value : '',
            }};
        }} else {{
            const el = document.getElementById('cmd_single');
            return {{ custom_cmd: el ? el.value : '' }};
        }}
    }}
    let progressTimer = null;
    let elapsedTimer = null;
    let startTime = null;

    const _SINGLE = ['Baseline ({{BASELINE_S}}s)', 'Encode', 'Done'];
    const _SINGLE_MAP = {{'starting':0, 'baseline':0, 'cpu_encode':1, 'gpu_encode':1,
                          'h265_cpu_encode':1, 'h265_gpu_encode':1, 'av1_cpu_encode':1, 'done':2}};
    const _BOTH_STAGES = ['Baseline ({{BASELINE_S}}s)', 'CPU encode', '{{REST_LABEL}}', 'Baseline 2 ({{BASELINE_S}}s)', 'GPU encode', 'VMAF (quality)', 'Done'];
    const _BOTH_MAP = {{'starting':0, 'baseline':0, 'cpu_encode':1, 'rest':2,
                        'baseline_2':3, 'gpu_encode':4, 'vmaf':5, 'done':6}};
    const _ALL_STAGES = ['H.264 CPU','{{REST_LABEL}}','H.264 GPU','{{REST_LABEL}}','H.265 CPU','{{REST_LABEL}}','H.265 GPU','{{REST_LABEL}}','AV1 CPU','{{REST_LABEL}}','AV1 GPU','VMAF (quality)','Done'];
    const _ALL_MAP = {{'starting':0,
        'h264_cpu_baseline':0,'h264_cpu_encode':0,
        'h264_rest':1,
        'h264_gpu_baseline':2,'h264_gpu_encode':2,
        'h264_inter_rest':3,
        'h265_cpu_baseline':4,'h265_cpu_encode':4,
        'h265_rest':5,
        'h265_gpu_baseline':6,'h265_gpu_encode':6,
        'h265_inter_rest':7,
        'av1_cpu_baseline':8,'av1_cpu_encode':8,
        'av1_rest':9,
        'av1_gpu_baseline':10,'av1_gpu_encode':10,
        'vmaf':11,
        'done':12}};
    // Single-device codec sweeps (3 codecs on one device).
    const _CODECS_CPU_STAGES = ['H.264 CPU','{{REST_LABEL}}','H.265 CPU','{{REST_LABEL}}','AV1 CPU','VMAF (quality)','Done'];
    const _CODECS_GPU_STAGES = ['H.264 GPU','{{REST_LABEL}}','H.265 GPU','{{REST_LABEL}}','AV1 GPU','VMAF (quality)','Done'];
    const _CODECS_CPU_MAP = {{'starting':0,
        'h264_cpu_baseline':0,'h264_cpu_encode':0,
        'h265_cpu_rest':1,
        'h265_cpu_baseline':2,'h265_cpu_encode':2,
        'av1_cpu_rest':3,
        'av1_cpu_baseline':4,'av1_cpu_encode':4,
        'vmaf':5,'done':6}};
    const _CODECS_GPU_MAP = {{'starting':0,
        'h264_gpu_baseline':0,'h264_gpu_encode':0,
        'h265_gpu_rest':1,
        'h265_gpu_baseline':2,'h265_gpu_encode':2,
        'av1_gpu_rest':3,
        'av1_gpu_baseline':4,'av1_gpu_encode':4,
        'vmaf':5,'done':6}};
    const STAGES = {{
        cpu:        _SINGLE,
        gpu:        _SINGLE,
        h265_cpu:   _SINGLE,
        h265_gpu:   _SINGLE,
        av1_cpu:    _SINGLE,
        av1_gpu:    _SINGLE,
        both:       _BOTH_STAGES,
        h265_both:  _BOTH_STAGES,
        av1_both:   _BOTH_STAGES,
        all_codecs: _ALL_STAGES,
        codecs_cpu: _CODECS_CPU_STAGES,
        codecs_gpu: _CODECS_GPU_STAGES,
    }};

    const STAGE_MAP = {{
        cpu:        _SINGLE_MAP,
        gpu:        _SINGLE_MAP,
        h265_cpu:   _SINGLE_MAP,
        h265_gpu:   _SINGLE_MAP,
        av1_cpu:    _SINGLE_MAP,
        av1_gpu:    _SINGLE_MAP,
        both:       _BOTH_MAP,
        h265_both:  _BOTH_MAP,
        av1_both:   _BOTH_MAP,
        all_codecs: _ALL_MAP,
        codecs_cpu: _CODECS_CPU_MAP,
        codecs_gpu: _CODECS_GPU_MAP,
    }};

    function selectPreset(key) {{
        selectedPreset = key;
        // single .preset cards and the three .batch-box sweeps share one
        // selection mechanism: the 'selected' class (border + tint via CSS)
        document.querySelectorAll('.preset, .batch-box').forEach(el => el.classList.remove('selected'));
        const el = document.getElementById('preset-' + key);
        if (el) el.classList.add('selected');
        fetchCmdPreview(key);
    }}

    // CR-035 \u2014 optional 5th arg `data` carries the full /video/job/<id>
    // dict so we can pluck the encode-progress fields. Old callers that
    // pass a literal stage string just don't populate the bar.
    function renderProgress(jobId, mode, serverStage, watts, data) {{
        const stages = STAGES[mode];
        const stageMap = STAGE_MAP[mode];
        const currentStage = stageMap[serverStage] !== undefined ? stageMap[serverStage] : 0;
        // VMAF (CR-044) doesn't pipe ffmpeg progress, but the server surfaces
        // vmaf_done / vmaf_total so we can still show "N of M".
        let vmafLine = '';
        if (serverStage === 'vmaf' && data && data.vmaf_total) {{
            vmafLine = '<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.4rem">'
                     + 'VMAF \xb7 ' + (data.vmaf_done || 0) + ' of ' + data.vmaf_total
                     + ' encode' + (data.vmaf_total > 1 ? 's' : '') + ' scored</div>';
        }}
        // Idle-wait cooldown readout \u2014 shared single source (wlCooldownLine in
        // _PROGRESS_JS). cooldown_waited_s is set ONLY by the active-probe path
        // (power.wait_for_thermal_floor), so the line shows only during a real
        // wait-for-idle; absent => the fixed Rest(Xs) the static label implies.
        let cdLine = wlCooldownLine(data);
        wlRenderProgress({{
            header: 'Running measurement \u2014 do not close this tab',
            stagesHtml: wlStageList(stages, currentStage),
            watts: watts,
            elapsed: startTime ? Date.now() - startTime : null,
            progressPct: data && data.progress_pct,
            etaS:        data && data.eta_s,
            encodeSpeed: data && data.encode_speed,
            extraHtml: vmafLine + cdLine + '<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.4rem">Job: ' + jobId + '</div>',
        }});
    }}

    function stopProgress() {{
        if (progressTimer) {{ clearInterval(progressTimer); progressTimer = null; }}
    }}

    async function uploadAndRun() {{
        const btn = document.getElementById('runBtn');
        btn.disabled = true;
        const status = document.getElementById('status');

        let resp;
        let isUpload = false;
        try {{
            const cmds = _getCustomCmds();
            if (selectedSource === 'upload') {{
                isUpload = true;
                const file = document.getElementById('fileInput').files[0];
                if (!file) {{ alert('Please select a file first'); btn.disabled = false; return; }}
                if (file.size > 1024 * 1024 * 1024) {{ alert('File too large (max 1GB)'); btn.disabled = false; return; }}
                status.innerHTML = '<div style="color:var(--warn)">Uploading ' + file.name + '...</div>';
                const form = new FormData();
                form.append('file', file);
                form.append('preset', selectedPreset);
                for (const [k, v] of Object.entries(cmds)) form.append(k, v);
                resp = await fetch('/video/upload', {{ method: 'POST', body: form }});
            }} else {{
                status.innerHTML = '<div style="color:var(--warn)">Starting measurement on ' + selectedSource + '...</div>';
                const form = new FormData();
                form.append('source_key', selectedSource);
                form.append('preset', selectedPreset);
                for (const [k, v] of Object.entries(cmds)) form.append(k, v);
                resp = await fetch('/video/use-source', {{ method: 'POST', body: form }});
            }}

            let data;
            try {{
                data = await resp.json();
            }} catch(_) {{
                const hint = isUpload && resp.status === 413
                    ? ' — file too large for server (nginx limit)'
                    : '';
                status.innerHTML = '<div style="color:var(--err)">Failed (HTTP ' + resp.status + ')' + hint + '.</div>';
                btn.disabled = false;
                return;
            }}
            if (data.job_id) {{
                startTime = Date.now();
                renderProgress(data.job_id, selectedPreset, 'starting');
                pollJob(data.job_id, selectedPreset);
            }} else {{
                status.innerHTML = '<div style="color:var(--err)">Error: ' + JSON.stringify(data) + '</div>';
                btn.disabled = false;
            }}
        }} catch(e) {{
            status.innerHTML = '<div style="color:var(--err)">Failed: ' + e + '</div>';
            btn.disabled = false;
        }}
    }}

    async function pollJob(jobId, mode) {{
        try {{
            const [resp, powerR] = await Promise.all([
                fetch('/video/job/' + jobId),
                fetch('/power').catch(() => null),
            ]);
            const data = await resp.json();
            const watts = powerR ? (await powerR.json().catch(()=>({{}}))).watts ?? null : null;
            if (data.status === 'done') {{
                stopProgress();
                renderResult(data.result, jobId);
                document.getElementById('runBtn').disabled = false;
            }} else if (data.status === 'error') {{
                stopProgress();
                document.getElementById('status').innerHTML =
                    '<div style="color:var(--err)">Error: ' + data.error + '</div>';
                document.getElementById('runBtn').disabled = false;
            }} else if (data.stage === 'queued') {{
                renderQueued(data.queue_position);
                setTimeout(() => pollJob(jobId, mode), 3000);
            }} else {{
                renderProgress(jobId, mode, data.stage || "starting", watts, data);
                // Poll fast during an idle-wait cooldown so the "waiting Xs for
                // floor" readout actually shows — GPU rests settle in a few
                // seconds and were slipping between the 5s polls. Normal cadence
                // otherwise (encodes are long).
                const _st = data.stage || '';
                const _inCooldown = data.cooldown_waited_s != null &&
                    (_st.indexOf('rest') !== -1 || _st.indexOf('cooldown') !== -1);
                setTimeout(() => pollJob(jobId, mode), _inCooldown ? 1000 : 2000);
            }}
        }} catch(e) {{
            setTimeout(() => pollJob(jobId, mode), 5000);
        }}
    }}

    function renderQueued(position) {{ wlRenderQueued(position); }}

    function metricRow(label, val, unit='') {{
        return `<div class="metric"><span>${{label}}</span>
                <span class="val">${{val}}${{unit ? ' ' + unit : ''}}</span></div>`;
    }}

    function renderSingle(r) {{
        const e = r.energy;
        const t = r.thermals;
        const pptNote = t.gpu_ppt_mean_w
            ? metricRow('GPU PPT mean / peak', t.gpu_ppt_mean_w + ' / ' + t.gpu_ppt_peak_w, 'W')
              + '<div style="color:var(--text-4);font-size:0.72rem;padding:0.1rem 0 0.6rem 1rem">'
              + 'GPU self-reported power (PPT). P110 ΔW above is the full system delta — includes CPU, RAM, drives.'
              + '</div>'
            : '';
        const cmdNote = r.transcode && r.transcode.ffmpeg_cmd
            ? '<details style="margin-top:0.75rem"><summary style="color:var(--text-5);font-size:0.72rem;cursor:pointer">ffmpeg command</summary>'
              + '<div style="color:var(--text-3);font-size:0.7rem;font-family:monospace;word-break:break-all;margin-top:0.4rem;padding:0.5rem;background:var(--panel-2);border:1px solid var(--border-2)">'
              + r.transcode.ffmpeg_cmd + '</div></details>'
            : '';
        return `
        <div class="single-report">
            <h2>Energy Report — ${{r.preset_label}}</h2>
            <div class="section-title">Encode</div>
            ${{metricRow('Preset', r.preset_detail)}}
            ${{metricRow('Duration', e.delta_t_s, 's')}}
            ${{metricRow('Output size', r.output_size_mb, 'MB')}}
            ${{cmdNote}}
            <div class="section-title">Power (P110)</div>
            ${{metricRow('Baseline', e.w_base, 'W')}}
            ${{metricRow('Task mean', e.w_task, 'W')}}
            ${{metricRow('Delta (ΔW)', e.delta_w, 'W')}}
            ${{metricRow('Energy (ΔE)', e.delta_e_wh, 'Wh')}}
            ${{wlCarbonRow(e)}}
            ${{metricRow('Polls', e.poll_count)}}
            <div class="section-title">Thermals</div>
            ${{metricRow('CPU base → peak', t.cpu_base + ' → ' + t.cpu_peak, '°C')}}
            ${{metricRow('GPU base → peak', t.gpu_base + ' → ' + t.gpu_peak, '°C')}}
            ${{pptNote}}
            <div class="conf-badge" style="margin-top:0.75rem">${{e.confidence.flag}} ${{e.confidence.label}}</div>
            ${{e.confidence.hint ? '<div style="margin-top:0.35rem;color:var(--text-3);font-size:0.72rem">' + e.confidence.hint + '</div>' : ''}}
            ${{wlCarbonStrip(e.delta_e_wh, r.preset_label, e.delta_t_s, e.co2e && e.co2e.intensity ? e.co2e.intensity.g_per_kwh : null)}}
        </div>`;
    }}

    function renderBoth(r) {{
        const cpu = r.cpu;
        const gpu = r.gpu;
        const a = r.analysis;

        function col(res) {{
            const e = res.energy;
            const t = res.thermals;
            // Side is CPU unless the preset key is a GPU variant. The bare
            // 'cpu'/'gpu' keys are H.264 only; H.265/AV1 use h265_/av1_ prefixes,
            // so a literal `=== 'cpu'` mismarked every non-H.264 comparison and
            // both columns inherited the GPU winner's flag.
            const side = res.preset_key.indexOf('gpu') !== -1 ? 'GPU' : 'CPU';
            const isEnergyWinner = a.energy_winner === side;
            const isSpeedWinner  = a.speed_winner  === side;
            const pptNote = t.gpu_ppt_mean_w
                ? metricRow('GPU PPT mean', t.gpu_ppt_mean_w, 'W')
                  + '<div style="color:var(--text-4);font-size:0.72rem;padding:0.1rem 0 0.6rem 1rem">'
                  + 'GPU self-reported · P110 ΔW is full system delta.'
                  + '</div>'
                : '';
            const cmdNote = res.transcode && res.transcode.ffmpeg_cmd
                ? '<details style="margin-top:0.5rem"><summary style="color:var(--text-5);font-size:0.7rem;cursor:pointer">ffmpeg command</summary>'
                  + '<div style="color:var(--text-3);font-size:0.68rem;font-family:monospace;word-break:break-all;margin-top:0.3rem;padding:0.4rem;background:var(--panel-2);border:1px solid var(--border-2)">'
                  + res.transcode.ffmpeg_cmd + '</div></details>'
                : '';
            return `<div class="col">
                <h3>${{res.preset_label}}</h3>
                <div class="sub">${{res.preset_detail}}</div>
                <div class="section-title">Encode</div>
                ${{metricRow('Duration', e.delta_t_s + (isSpeedWinner ? ' \U0001F3C1' : ''), 's')}}
                ${{metricRow('Output size', res.output_size_mb, 'MB')}}
                ${{metricRow('VMAF', res.vmaf != null ? res.vmaf : '—')}}
                ${{cmdNote}}
                <div class="section-title">Power (P110)</div>
                ${{metricRow('Baseline', e.w_base, 'W')}}
                ${{metricRow('Task mean', e.w_task, 'W')}}
                ${{metricRow('Peak delta', e.delta_w, 'W')}}
                ${{metricRow('Energy (ΔE)', e.delta_e_wh + (isEnergyWinner ? ' ✓' : ''), 'Wh')}}
                ${{wlCarbonRow(e)}}
                ${{metricRow('Polls', e.poll_count)}}
                <div class="section-title">Thermals</div>
                ${{metricRow('CPU base → peak', t.cpu_base + ' → ' + t.cpu_peak, '°C')}}
                ${{metricRow('GPU base → peak', t.gpu_base + ' → ' + t.gpu_peak, '°C')}}
                ${{pptNote}}
                <div class="conf-badge" style="margin-top:0.75rem;font-size:0.8rem">
                    ${{e.confidence.flag}} ${{e.confidence.label}}
                </div>
                ${{e.confidence.hint ? '<div style="margin-top:0.3rem;color:var(--text-3);font-size:0.7rem">' + e.confidence.hint + '</div>' : ''}}
            </div>`;
        }}

        // Carbon strip for the comparison report uses the lower of the two
        // energy figures (the more efficient option) — that's the headline
        // number for "given this is the best result here, here's how it'd
        // play out elsewhere".
        const cpuWh = (cpu.energy && cpu.energy.delta_e_wh) || null;
        const gpuWh = (gpu.energy && gpu.energy.delta_e_wh) || null;
        const stripWh = (cpuWh != null && gpuWh != null)
            ? Math.min(cpuWh, gpuWh)
            : (cpuWh != null ? cpuWh : gpuWh);
        // Label is the *winner's* preset, but explicitly framed as "best of
        // CPU vs GPU" so the visitor reads the carbon number as the most-
        // efficient mode of a comparison rather than the only mode tested.
        // The page above the strip already lists both per-device columns;
        // this just stops the strip from misleading on its own.
        const _winnerLbl = (cpuWh != null && gpuWh != null)
            ? (cpuWh <= gpuWh ? cpu.preset_label : gpu.preset_label)
            : (cpuWh != null ? cpu.preset_label : gpu.preset_label);
        const stripLbl = (cpuWh != null && gpuWh != null)
            ? (_winnerLbl + ' · best of CPU vs GPU')
            : _winnerLbl;
        // Saved intensity for the drift note — pull from the winning
        // side's energy.co2e block. Both sides share the same /carbon
        // snapshot at save time, so either would work.
        const _winnerE = (cpuWh != null && gpuWh != null)
            ? (cpuWh <= gpuWh ? cpu.energy : gpu.energy)
            : (cpuWh != null ? cpu.energy : gpu.energy);
        const _stripSavedG = _winnerE && _winnerE.co2e && _winnerE.co2e.intensity
            ? _winnerE.co2e.intensity.g_per_kwh : null;
        const _stripDur = _winnerE ? _winnerE.delta_t_s : null;
        // CR-032 — sub-runs for the carbon strip's per-mode breakdown.
        const _subRuns = [cpu, gpu].filter(s => s && s.energy && s.energy.co2e).map(s => ({{
            label: s.preset_label,
            grams: s.energy.co2e.grams,
            deltaWh: s.energy.delta_e_wh,
            durationS: s.energy.delta_t_s
        }}));
        return `
        <div class="report">
            <h2>Comparison Report</h2>
            <div class="analysis-box">
                <h3>Finding</h3>
                <div class="finding">${{a.finding}}</div>
                <div class="conf-note">${{a.confidence_note}}</div>
                ${{a.quality_note ? '<div class="conf-note" style="color:var(--accent)">◆ ' + a.quality_note + '</div>' : ''}}
            </div>
            <div class="cols">
                ${{col(cpu)}}
                ${{col(gpu)}}
            </div>
            ${{wlCarbonStrip(stripWh, stripLbl, _stripDur, _stripSavedG, _subRuns)}}
            <div class="scope-note">${{r.scope}}</div>
        </div>`;
    }}

    function renderAllCodecs(r) {{
        const codecs = r.codecs;
        const a = r.analysis;
        const codecOrder = [['h264','H.264'],['h265','H.265'],['av1','AV1']];
        const fmt = v => v != null ? v : '—';

        // Summary matrix table
        let tableRows = codecOrder.map(([key, label]) => {{
            const cd = codecs[key];
            if (!cd) return '';
            const ce = cd.cpu.energy, ge = cd.gpu.energy;
            const ca = cd.analysis;
            const ew = ca.energy_winner, sw = ca.speed_winner;
            const cpuWin = (ew==='CPU'?'✓':'') + (sw==='CPU'?' \U0001F3C1':'');
            const gpuWin = (ew==='GPU'?'✓':'') + (sw==='GPU'?' \U0001F3C1':'');
            // Headers right-align, so data cells must too — otherwise the
            // numeric columns drift left of their headers and visitors can't
            // read off CPU vs GPU at a glance.
            return `<tr>
                <td style="color:var(--text);font-weight:bold;text-align:left">${{label}}</td>
                <td style="text-align:right">${{fmt(ce.delta_t_s)}}s</td>
                <td style="color:${{ew==='CPU'?'#00ff99':'#888'}};text-align:right">${{fmt(ce.delta_e_wh)}} Wh ${{cpuWin}}</td>
                <td style="color:var(--text-3);font-size:0.75rem;text-align:right">${{fmt(cd.cpu.output_size_mb)}} MB</td>
                <td style="color:var(--text-3);font-size:0.75rem;text-align:right">${{fmt(cd.cpu.vmaf)}}</td>
                <td style="text-align:right">${{fmt(ge.delta_t_s)}}s</td>
                <td style="color:${{ew==='GPU'?'#00ff99':'#888'}};text-align:right">${{fmt(ge.delta_e_wh)}} Wh ${{gpuWin}}</td>
                <td style="color:var(--text-3);font-size:0.75rem;text-align:right">${{fmt(cd.gpu.output_size_mb)}} MB</td>
                <td style="color:var(--text-3);font-size:0.75rem;text-align:right">${{fmt(cd.gpu.vmaf)}}</td>
                <td class="conf-badge" style="font-size:0.78rem;text-align:center">${{ce.confidence.flag}} ${{ge.confidence.flag}}</td>
            </tr>`;
        }}).join('');

        const bestE = a.most_efficient;
        const bestS = a.fastest;
        const highlights = `
            <div style="display:flex;gap:1.5rem;flex-wrap:wrap;margin-top:0.75rem;font-size:0.82rem">
                <span>⚡ Most efficient: <span style="color:var(--accent)">${{bestE ? bestE.label + ' (' + bestE.delta_e_wh + ' Wh)' : '—'}}</span></span>
                <span>\U0001F3C1 Fastest: <span style="color:var(--accent)">${{bestS ? bestS.label + ' (' + bestS.delta_t_s + 's)' : '—'}}</span></span>
            </div>`;

        // Per-codec collapsible detail
        const details = codecOrder.map(([key, label]) => {{
            const cd = codecs[key];
            if (!cd) return '';
            function miniCol(res, tag) {{
                const e = res.energy, t = res.thermals;
                return `<div style="flex:1;min-width:180px">
                    <div style="color:var(--text-3);font-size:0.72rem;margin-bottom:0.4rem">${{tag}}</div>
                    ${{metricRow('Duration', e.delta_t_s, 's')}}
                    ${{metricRow('Output size', res.output_size_mb, 'MB')}}
                    ${{metricRow('VMAF', res.vmaf != null ? res.vmaf : '—')}}
                    ${{metricRow('Baseline', e.w_base, 'W')}}
                    ${{metricRow('ΔW', e.delta_w, 'W')}}
                    ${{metricRow('ΔE', e.delta_e_wh, 'Wh')}}
                    ${{wlCarbonRow(e)}}
                    ${{metricRow('Polls', e.poll_count)}}
                    ${{metricRow('CPU peak', t.cpu_peak, '°C')}}
                    ${{metricRow('GPU peak', t.gpu_peak, '°C')}}
                    <div class="conf-badge" style="margin-top:0.5rem;font-size:0.78rem">${{e.confidence.flag}} ${{e.confidence.label}}</div>
                    ${{e.confidence.hint ? '<div style="color:var(--text-3);font-size:0.7rem;margin-top:0.2rem">' + e.confidence.hint + '</div>' : ''}}
                </div>`;
            }}
            return `<details style="margin-top:0.5rem;border:1px solid var(--border-2);padding:0.75rem">
                <summary style="color:var(--text-3);font-size:0.8rem;cursor:pointer;list-style:none">
                    <span style="color:var(--accent)">${{label}}</span> — ${{cd.analysis.finding.slice(0,80)}}…
                </summary>
                <div style="display:flex;gap:1.5rem;flex-wrap:wrap;margin-top:0.75rem">
                    ${{miniCol(cd.cpu, cd.cpu.preset_label)}}
                    ${{miniCol(cd.gpu, cd.gpu.preset_label)}}
                </div>
            </details>`;
        }}).join('');

        // Strip uses the most-efficient codec/device's energy as the headline.
        // Label explicitly frames it as "most efficient of all codecs" so the
        // visitor can't read the carbon figure as if it were the only codec
        // tested — the matrix above the strip lists every codec/device pair.
        const stripWh = bestE && bestE.delta_e_wh != null ? bestE.delta_e_wh : null;
        const stripLbl = bestE
            ? (bestE.label + ' · most efficient codec across all comparisons')
            : 'Most efficient codec';
        // Winner's energy block — used for duration and saved-intensity drift
        // note. bestE carries codec/side; the full energy block lives in
        // r.codecs[codec][side].energy. All sub-runs share the same /carbon
        // snapshot at save time, so any of them would do for savedG.
        const _winE = (bestE && r.codecs && r.codecs[bestE.codec]
                       && r.codecs[bestE.codec][bestE.side])
            ? r.codecs[bestE.codec][bestE.side].energy : null;
        const _stripDur = _winE ? _winE.delta_t_s : null;
        const _stripSavedG = _winE && _winE.co2e && _winE.co2e.intensity
            ? _winE.co2e.intensity.g_per_kwh : null;
        // CR-032 — sub-runs for the carbon strip's per-mode breakdown
        // (6 cells: H.264/H.265/AV1 × CPU/GPU). Each cell carries its own
        // co2e snapshot, so the strip's details block surfaces all 6 instead
        // of eliding 5/6 of the work the visitor just ran.
        const _subRuns = [];
        codecOrder.forEach(([key, label]) => {{
            const cd = codecs[key];
            if (!cd) return;
            ['cpu','gpu'].forEach(side => {{
                const sub = cd[side];
                if (sub && sub.energy && sub.energy.co2e) {{
                    _subRuns.push({{
                        label: sub.preset_label || (label + ' ' + side.toUpperCase()),
                        grams: sub.energy.co2e.grams,
                        deltaWh: sub.energy.delta_e_wh,
                        durationS: sub.energy.delta_t_s
                    }});
                }}
            }});
        }});
        return `
        <div class="report">
            <h2>All Codecs — Energy &amp; Speed Matrix</h2>
            <table style="width:100%;border-collapse:collapse;font-size:0.82rem;margin-bottom:0.5rem">
                <thead><tr style="color:var(--text-4);font-size:0.72rem;text-transform:uppercase;letter-spacing:0.05em">
                    <th style="text-align:left;padding:0.3rem 0.5rem 0.5rem 0">Codec</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">CPU time</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">CPU energy</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">CPU out</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">CPU VMAF</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">GPU time</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">GPU energy</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">GPU out</th>
                    <th style="text-align:right;padding:0.3rem 0.5rem">GPU VMAF</th>
                    <th style="text-align:center;padding:0.3rem 0.5rem">Conf</th>
                </tr></thead>
                <tbody style="font-family:monospace">${{tableRows}}</tbody>
            </table>
            <div style="font-size:0.7rem;color:var(--text-5);margin-bottom:0.25rem">✓ energy winner · \U0001F3C1 speed winner · CPU out / GPU out should match — confirms same bitrate target · VMAF = perceptual quality 0–100 (higher better)</div>
            ${{highlights}}
            <div style="margin-top:1rem;color:var(--text-3);font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em">Per-codec detail</div>
            ${{details}}
            ${{wlCarbonStrip(stripWh, stripLbl, _stripDur, _stripSavedG, _subRuns)}}
            <div class="scope-note">${{r.scope}}</div>
        </div>`;
    }}

    function downloadLinks(jobId) {{
        const base = '/results/video/' + jobId;
        return `<div style="margin-top:1rem;display:flex;gap:0.75rem">
            <a href="${{base}}/download.json" download
               style="color:var(--accent);font-size:0.8rem;border:1px solid #00ff9944;
                      padding:0.3rem 0.75rem;text-decoration:none">↓ JSON</a>
            <a href="${{base}}/download.csv" download
               style="color:var(--accent);font-size:0.8rem;border:1px solid #00ff9944;
                      padding:0.3rem 0.75rem;text-decoration:none">↓ CSV</a>
            <a href="${{base}}/reproduce.zip" download
               style="color:var(--accent);font-size:0.8rem;border:1px solid #00ff9944;
                      padding:0.3rem 0.75rem;text-decoration:none">↓ Reproduce this</a>
        </div>`;
    }}

    function renderResult(r, jobId) {{
        const el = document.getElementById('status');
        const elapsed = startTime ? wlFormatElapsed(Date.now() - startTime) : '';
        const elapsedNote = elapsed ? `<div style="color:var(--text-4);font-size:0.78rem;margin-bottom:1rem">
            Total elapsed: ${{elapsed}}</div>` : '';
        const links = jobId ? downloadLinks(jobId) : '';
        let html;
        if (r.mode === 'both') {{
            html = renderBoth(r) + links;
        }} else if (r.mode === 'all_codecs') {{
            html = renderAllCodecs(r) + links;
        }} else if (r.mode === 'codecs_cpu' || r.mode === 'codecs_gpu') {{
            html = window.wlRenderCodecsSingle(r) + links;
        }} else {{
            html = renderSingle(r.result) + links;
        }}
        el.innerHTML = elapsedNote + html;
        loadPrevRuns();
    }}

    async function loadPrevRuns() {{
        try {{
            const resp = await fetch('/results/video/list');
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
            let summary, codec;
            if (r.mode === 'both') {{
                codec = [r.cpu_preset, r.gpu_preset].filter(Boolean).join(' vs ');
                summary = `CPU ${{r.cpu_delta_e_wh}} Wh ${{r.cpu_confidence ? '<span class="conf-badge">'+r.cpu_confidence+'</span>' : ''}} · GPU ${{r.gpu_delta_e_wh}} Wh ${{r.gpu_confidence ? '<span class="conf-badge">'+r.gpu_confidence+'</span>' : ''}}`;
            }} else if (r.mode === 'all_codecs') {{
                codec = 'H.264 · H.265 · AV1 — all codecs (CPU vs GPU)';
                summary = `Best: ${{r.most_efficient||'—'}} (${{r.best_delta_e_wh||'—'}} Wh) · Fastest: ${{r.fastest||'—'}} ${{r.all_green ? '<span class="conf-badge">🟢</span>' : ''}}`;
            }} else if (r.mode === 'codecs_cpu' || r.mode === 'codecs_gpu') {{
                const dev = r.mode === 'codecs_gpu' ? 'GPU (hardware)' : 'CPU (software)';
                codec = `H.264 · H.265 · AV1 — ${{dev}}`;
                summary = `Best: ${{r.most_efficient||'—'}} (${{r.best_delta_e_wh||'—'}} Wh) · Fastest: ${{r.fastest||'—'}} ${{r.all_green ? '<span class="conf-badge">🟢</span>' : ''}}`;
            }} else {{
                codec = r.preset || '';
                summary = `${{r.delta_e_wh}} Wh ${{r.confidence ? '<span class="conf-badge">'+r.confidence+'</span>' : ''}}`;
            }}
            const base = '/results/video/' + r.job_id;
            const savedAt = r.saved_at || '';
            return `<div style="border-bottom:1px solid var(--panel);padding:0.6rem 0">
                <div style="display:flex;justify-content:space-between;align-items:baseline">
                    <span style="color:var(--text);font-size:0.82rem">${{date}}</span>
                    <span style="color:var(--text-3);font-size:0.75rem;font-family:monospace">${{r.job_id}}</span>
                </div>
                <div style="color:var(--text-3);font-size:0.75rem;margin:0.1rem 0">${{codec}}</div>
                <div style="color:var(--accent);font-size:0.8rem;margin:0.2rem 0">${{summary}}</div>
                <div style="display:flex;gap:0.75rem;margin-top:0.3rem;align-items:center">
                    <a href="javascript:void(0)"
                       onclick="wlExpandPrevRow('video','${{r.job_id}}','${{savedAt}}')"
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
    fetchCmdPreview(selectedPreset);
    const _resumeJob = new URLSearchParams(location.search).get('job');
    if (_resumeJob) {{ pollJob(_resumeJob, 'both'); }}
    </script>
    {_PROGRESS_JS}
    {_RESULT_JS}
    {_CONF_HELP_WIDGET}
"""))


# --- Job runner ---

async def run_job(job_id: str, input_path: Path, preset: str, delete_after: bool = True,
                  custom_cmd: str = None, custom_cmd_cpu: str = None, custom_cmd_gpu: str = None,
                  source_key: str = None):
    try:
        jobs[job_id].update({"status": "running", "stage": "starting"})
        _BOTH_PRESETS = {
            "both":      ("cpu",      "gpu"),
            "h265_both": ("h265_cpu", "h265_gpu"),
            "av1_both":  ("av1_cpu",  "av1_gpu"),
        }
        if preset == "all_codecs":
            result = await run_all_measurement(input_path, job_id, jobs)
        elif preset in ("codecs_cpu", "codecs_gpu"):
            result = await run_codecs_single_measurement(
                input_path, job_id, jobs, side=preset.split("_", 1)[1])
        elif preset in _BOTH_PRESETS:
            p_cpu, p_gpu = _BOTH_PRESETS[preset]
            result = await run_both_measurement(input_path, job_id, jobs,
                                                custom_cmd_cpu=custom_cmd_cpu,
                                                custom_cmd_gpu=custom_cmd_gpu,
                                                preset_cpu=p_cpu, preset_gpu=p_gpu)
        else:
            result = await run_video_measurement(input_path, job_id, preset, jobs,
                                                 custom_cmd=custom_cmd)
        # CR-047 follow-up — stamp the variant + parent ids on the result so
        # historical jobs stay filterable as the source schema evolves. Only
        # set when the job came from a preloaded source (not /video/upload).
        if source_key:
            entry = PRELOADED.get(source_key) or {}
            result["source"] = {"key": source_key,
                                "parent": entry.get("_parent")}
        save_result("video", job_id, result)
        jobs[job_id].update({"status": "done", "stage": "done", "result": result})
    except Exception as e:
        jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}
    finally:
        if delete_after:
            input_path.unlink(missing_ok=True)


@router.post("/video/use-source", dependencies=[Depends(requires(VIDEO_RUN))])
async def use_preloaded_source(
    request: Request,
    source_key: str = Form(...),
    preset: str = Form("both"),
    custom_cmd: str = Form(None),
    custom_cmd_cpu: str = Form(None),
    custom_cmd_gpu: str = Form(None),
):
    if preset not in ("cpu", "gpu", "both", "h265_cpu", "h265_gpu", "h265_both", "av1_cpu", "av1_gpu", "av1_both", "all_codecs", "codecs_cpu", "codecs_gpu"):
        return JSONResponse({"error": "Invalid preset"}, status_code=400)
    # CR-001 capability dispatch: all-codecs sweep is BATCH_COMPARE; any
    # custom ffmpeg arg is CUSTOM_PROMPT.
    if preset in ("all_codecs", "codecs_cpu", "codecs_gpu"):
        gate(request, BATCH_COMPARE)
    if any((custom_cmd, custom_cmd_cpu, custom_cmd_gpu)):
        gate(request, CUSTOM_PROMPT)

    source = PRELOADED.get(source_key)
    if not source or not source["path"].exists():
        return JSONResponse({"error": f"Source '{source_key}' not found"}, status_code=404)

    job_id = str(uuid.uuid4())[:8]
    label = f"Video — {preset} · {source['label']}"

    async def coro():
        await run_job(job_id, source["path"], preset, False,
                      custom_cmd=custom_cmd,
                      custom_cmd_cpu=custom_cmd_cpu,
                      custom_cmd_gpu=custom_cmd_gpu,
                      source_key=source_key)

    position = queue_control.enqueue(job_id, "video", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}

@router.post("/video/upload", dependencies=[Depends(requires(CUSTOM_UPLOAD))])
async def upload_video(
    request: Request,
    file: UploadFile = File(...),
    preset: str = Form("both"),
    custom_cmd: str = Form(None),
    custom_cmd_cpu: str = Form(None),
    custom_cmd_gpu: str = Form(None),
):
    if preset not in ("cpu", "gpu", "both", "h265_cpu", "h265_gpu", "h265_both", "av1_cpu", "av1_gpu", "av1_both", "all_codecs", "codecs_cpu", "codecs_gpu"):
        return JSONResponse({"error": "Invalid preset"}, status_code=400)
    # CR-001 capability dispatch — same shape as /video/use-source.
    if preset in ("all_codecs", "codecs_cpu", "codecs_gpu"):
        gate(request, BATCH_COMPARE)
    if any((custom_cmd, custom_cmd_cpu, custom_cmd_gpu)):
        gate(request, CUSTOM_PROMPT)

    allowed = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".ts"}
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed:
        return JSONResponse({"error": f"File type {suffix} not allowed"}, status_code=400)

    # CR-001 part D / CR-026 — upload size cap. CR-026 moved CUSTOM_UPLOAD
    # to Member tier, so Anonymous can't reach this code path; the per-tier
    # branch collapses to the Member cap. The `upload_size_anonymous_mb`
    # setting is left in place for future scope (e.g. re-enabling bounded
    # Anonymous uploads with a different policy).
    # Pre-check via Content-Length so we 413 before reading the body when
    # nginx hands us the header; fall back to length-after-read otherwise.
    s = cfg.load()
    max_mb = s["upload_size_member_mb"]
    max_bytes = max_mb * 1024 * 1024
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > max_bytes:
        return JSONResponse({"error": f"Upload too large (max {max_mb} MB for your tier)"}, status_code=413)

    contents = await file.read()
    if len(contents) > max_bytes:
        return JSONResponse({"error": f"Upload too large (max {max_mb} MB for your tier)"}, status_code=413)

    job_id = str(uuid.uuid4())[:8]
    input_path = UPLOAD_DIR / f"{job_id}_in{suffix}"
    input_path.write_bytes(contents)
    label = f"Video — {preset} · {file.filename}"

    async def coro():
        await run_job(job_id, input_path, preset, True,
                      custom_cmd=custom_cmd,
                      custom_cmd_cpu=custom_cmd_cpu,
                      custom_cmd_gpu=custom_cmd_gpu)

    position = queue_control.enqueue(job_id, "video", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


@router.get("/video/sources", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def video_sources():
    return get_all_sources()


@router.get("/video/preview-cmd", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def video_preview_cmd(preset: str = "both"):
    from video import PRESETS, build_preset_cmd
    placeholder_in = Path("{input}")
    placeholder_out = Path("{output}")
    _BOTH_MAP = {"both": ("cpu","gpu"), "h265_both": ("h265_cpu","h265_gpu"), "av1_both": ("av1_cpu","av1_gpu")}
    if preset == "all_codecs":
        pairs = [("cpu","gpu"),("h265_cpu","h265_gpu"),("av1_cpu","av1_gpu")]
        cmds = {}
        for cpu_k, gpu_k in pairs:
            cmds[cpu_k] = " ".join(build_preset_cmd(cpu_k, placeholder_in, placeholder_out))
            cmds[gpu_k] = " ".join(build_preset_cmd(gpu_k, placeholder_in, placeholder_out))
        return {"mode": "all_codecs", "cmds": cmds}
    elif preset in ("codecs_cpu", "codecs_gpu"):
        # Single-device codec sweep — 3 read-only cmds. Reuses the all_codecs
        # preview shape so fetchCmdPreview's label map renders them.
        side = preset.split("_", 1)[1]
        keys = {"cpu": ["cpu", "h265_cpu", "av1_cpu"],
                "gpu": ["gpu", "h265_gpu", "av1_gpu"]}[side]
        cmds = {k: " ".join(build_preset_cmd(k, placeholder_in, placeholder_out))
                for k in keys}
        return {"mode": "all_codecs", "cmds": cmds}
    elif preset in _BOTH_MAP:
        p_cpu, p_gpu = _BOTH_MAP[preset]
        cpu_cmd = " ".join(build_preset_cmd(p_cpu, placeholder_in, placeholder_out))
        gpu_cmd = " ".join(build_preset_cmd(p_gpu, placeholder_in, placeholder_out))
        return {"mode": "both", "cpu_cmd": cpu_cmd, "gpu_cmd": gpu_cmd}
    elif preset in PRESETS:
        cmd = " ".join(build_preset_cmd(preset, placeholder_in, placeholder_out))
        return {"mode": "single", "cmd": cmd}
    else:
        return JSONResponse({"error": "Unknown preset"}, status_code=400)


@router.get("/video/job/{job_id}", dependencies=[Depends(requires(QUEUE_VIEW))])
async def job_status(job_id: str):
    return _job_status(job_id)
