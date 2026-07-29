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
import uploads
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
    retention_picker  = ui.upload_retention_radios(disabled=upload_disabled)
    # Per-run VMAF toggle defaults from the global vmaf_enabled setting
    # (VMAF-polish item 4): terminal pass, so it only trades wall time.
    vmaf_checked      = " checked" if cfg.load().get("vmaf_enabled", True) else ""
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

    # Operator tool: given an energy budget, how many hours of video at a target
    # VMAF, by hardware + codec. Always shown (not gated on findings_enabled).
    budget_link_html = (
        '<div style="margin-bottom:1.25rem;font-size:0.82rem;color:var(--text-3);'
        'border-left:2px solid var(--accent);padding-left:0.75rem">'
        '⚡ <a href="/video/budget" style="color:var(--accent);text-decoration:none">'
        'Transcode options for a set energy budget →</a>'
        '<div style="font-size:0.72rem;color:var(--text-5);margin-top:0.15rem">'
        'How many hours of video fit a given Wh budget, by hardware &amp; codec at a target VMAF.</div>'
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

        /* Report styles live in wl-result.js (self-injected, .wl-rich
           namespace) since the 2026-07-07 renderer unification — fresh
           runs, prev-row expansion, and findings embeds share one card. */
        .scope-note {{ color: var(--text-5); font-size: 0.72rem; margin-top: 1rem; }}
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
        &nbsp;·&nbsp; Encode is half the story:
        <a href="/decode" style="color:var(--accent);text-decoration:none">Decode rig — client-device energy →</a>
        <span style="border:1px solid var(--border-3);border-radius:3px;padding:0 0.35rem;font-size:0.7rem">Lab only</span>
    </div>

    {findings_beta_html}

    {budget_link_html}

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
        {retention_picker}
    </div>
    <div style="margin:0.5rem 0 0.75rem">
        <label style="font-size:0.8rem;color:var(--text-3);cursor:pointer">
            <input type="checkbox" id="vmafToggle"{vmaf_checked}> Score quality (VMAF) after comparison runs
        </label>
        <div style="font-size:0.7rem;color:var(--text-5);margin-top:0.15rem">
            Scored after the measurement window closes — never part of the energy figure, but it adds
            minutes of wall time. Uncheck for a faster energy-only run. Single-preset runs never score.
        </div>
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

    // Stage lists + server-stage→index maps are shared globals in the
    // progress bundle (WL_VIDEO_PRESET_STAGES / WL_VIDEO_PRESET_IDX) — one
    // definition for this page AND /demo's tour poll, so the lists can't
    // drift again (2026-07-17: /demo's local copy was missing the 'vmaf'
    // stage and showed "Baseline" through the whole scoring pass).
    const STAGES = WL_VIDEO_PRESET_STAGES;
    const STAGE_MAP = WL_VIDEO_PRESET_IDX;

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
        // "VMAF · N of M scored" — shared helper in the progress bundle.
        let vmafLine = wlVmafLine(serverStage, data);
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
                const _ret = document.querySelector('input[name=retention]:checked');
                form.append('retention', _ret ? _ret.value : 'evict');
                form.append('compute_vmaf', document.getElementById('vmafToggle').checked ? 'true' : 'false');
                for (const [k, v] of Object.entries(cmds)) form.append(k, v);
                resp = await fetch('/video/upload', {{ method: 'POST', body: form }});
            }} else {{
                status.innerHTML = '<div style="color:var(--warn)">Starting measurement on ' + selectedSource + '...</div>';
                const form = new FormData();
                form.append('source_key', selectedSource);
                form.append('preset', selectedPreset);
                form.append('compute_vmaf', document.getElementById('vmafToggle').checked ? 'true' : 'false');
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

    // renderSingle / renderBoth / renderAllCodecs moved to wl-result.js
    // (wlRenderVideoCard) in the 2026-07-07 renderer unification — the
    // fresh-run card and the stored-result card are the same function now.

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
        // One renderer for fresh AND stored results (wl-result.js) — the
        // download links are the only fresh-run extra.
        el.innerHTML = elapsedNote + window.wlRenderVideoCard({{result: r}}) + links;
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
                  source_key: str = None, vmaf_override: bool = None):
    try:
        jobs[job_id].update({"status": "running", "stage": "starting"})
        _BOTH_PRESETS = {
            "both":      ("cpu",      "gpu"),
            "h265_both": ("h265_cpu", "h265_gpu"),
            "av1_both":  ("av1_cpu",  "av1_gpu"),
        }
        if preset == "all_codecs":
            result = await run_all_measurement(input_path, job_id, jobs,
                                               vmaf_override=vmaf_override)
        elif preset in ("codecs_cpu", "codecs_gpu"):
            result = await run_codecs_single_measurement(
                input_path, job_id, jobs, side=preset.split("_", 1)[1],
                vmaf_override=vmaf_override)
        elif preset in _BOTH_PRESETS:
            p_cpu, p_gpu = _BOTH_PRESETS[preset]
            result = await run_both_measurement(input_path, job_id, jobs,
                                                custom_cmd_cpu=custom_cmd_cpu,
                                                custom_cmd_gpu=custom_cmd_gpu,
                                                preset_cpu=p_cpu, preset_gpu=p_gpu,
                                                vmaf_override=vmaf_override)
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
        # Uploaded inputs (delete_after) honour their retention: proc → delete now,
        # evict/keep → touch mtime. Curated sources (delete_after=False) untouched.
        if delete_after:
            uploads.cleanup_after_job(input_path.parent, input_path.name)


@router.post("/video/use-source", dependencies=[Depends(requires(VIDEO_RUN))])
async def use_preloaded_source(
    request: Request,
    source_key: str = Form(...),
    preset: str = Form("both"),
    custom_cmd: str = Form(None),
    custom_cmd_cpu: str = Form(None),
    custom_cmd_gpu: str = Form(None),
    compute_vmaf: str = Form(""),   # ""=follow global vmaf_enabled; "true"/"false" per-run
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

    vmaf_override = None if compute_vmaf == "" else compute_vmaf == "true"

    async def coro():
        await run_job(job_id, source["path"], preset, False,
                      custom_cmd=custom_cmd,
                      custom_cmd_cpu=custom_cmd_cpu,
                      custom_cmd_gpu=custom_cmd_gpu,
                      source_key=source_key,
                      vmaf_override=vmaf_override)

    position = queue_control.enqueue(job_id, "video", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}

@router.post("/video/upload", dependencies=[Depends(requires(CUSTOM_UPLOAD))])
async def upload_video(
    request: Request,
    file: UploadFile = File(...),
    preset: str = Form("both"),
    retention: str = Form(uploads.DEFAULT_RETENTION),
    custom_cmd: str = Form(None),
    custom_cmd_cpu: str = Form(None),
    custom_cmd_gpu: str = Form(None),
    compute_vmaf: str = Form(""),   # ""=follow global vmaf_enabled; "true"/"false" per-run
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
    # Shared upload store (off /tmp); retention prefix drives lifecycle.
    saved = uploads.save(contents, file.filename, retention=retention,
                         feature="video", dest_dir=uploads.shared_dir())
    input_path = saved["path"]
    label = f"Video — {preset} · {file.filename}"

    vmaf_override = None if compute_vmaf == "" else compute_vmaf == "true"

    async def coro():
        await run_job(job_id, input_path, preset, True,
                      custom_cmd=custom_cmd,
                      custom_cmd_cpu=custom_cmd_cpu,
                      custom_cmd_gpu=custom_cmd_gpu,
                      vmaf_override=vmaf_override)

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
