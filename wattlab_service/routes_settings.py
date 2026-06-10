"""
Settings + calibration routes — /settings page (CR-050 Models section,
test-data cleanup panel), settings save, /variance/run calibration
trigger, and /precalibration/data (thermal-recovery probe JSON).

Phase 3 per-feature route module — shared state from runtime.py, chrome
from ui.py, never import main.
"""
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

import audience
import auth
import model_catalog
import queue_control
import settings as cfg
import ui
import video as vid
from capabilities import (requires, can, PUBLIC_PAGE, SETTINGS_READ_FULL,
                          SETTINGS_WRITE, VARIANCE_RUN)
from runtime import jobs
from ui import CHARTJS_URL, _gpu_enc

router = APIRouter()


def _models_section_html(s: dict, local: bool) -> str:
    """CR-050 — render the Models section on /settings.
    Three panels (LLM, RAG, Image), each showing every model the catalog
    found, with checkboxes preselected from the per-surface enabled list
    in settings. Anonymous viewers see disabled checkboxes (read-only).
    """
    enabled_keys = {
        "llm_enabled_models":   set(s.get("llm_enabled_models")   or []),
        "rag_enabled_models":   set(s.get("rag_enabled_models")   or []),
        "image_enabled_models": set(s.get("image_enabled_models") or []),
    }
    available = {
        "llm_enabled_models":   model_catalog.available_llm_models(),
        "rag_enabled_models":   model_catalog.available_llm_models(),  # shared catalog
        "image_enabled_models": model_catalog.available_image_models(),
    }
    # CUDA-only models (e.g. FLUX NF4) are shown but flagged; on a non-NVIDIA
    # GPU they can't run, so they're rendered disabled + "unavailable" (and
    # enabled_image_models() drops them from the runner) — see backend_allows().
    gpu_vendor = model_catalog.active_gpu_vendor()
    labels = {
        "llm_enabled_models":   ("LLM models",   "Drives /llm and /llm/compare. Source: <code>ollama list</code>."),
        "rag_enabled_models":   ("RAG models",   "Drives /rag and /rag/compare. Same Ollama catalog as LLM; can be a different subset."),
        "image_enabled_models": ("Image models", "Drives /image. Source: HuggingFace cache scan."),
    }

    def panel(surface_key: str) -> str:
        title, desc = labels[surface_key]
        avail = available[surface_key]
        enabled = enabled_keys[surface_key]
        # Empty enabled list = all available enabled (per the catalog convention).
        all_on = not enabled
        rows = []
        for k, v in avail.items():
            # cuda_only models can't run on a non-NVIDIA GPU: force them
            # disabled + unchecked so the UI never implies they're active.
            cuda_only = bool(v.get("cuda_only"))
            blocked = cuda_only and gpu_vendor != "nvidia"
            checked = "checked" if ((all_on or k in enabled) and not blocked) else ""
            disabled = "disabled" if (not local or blocked) else ""
            extras = []
            if v.get("params"):
                extras.append(v["params"])
            if v.get("size"):
                extras.append(v["size"])
            extra_str = " · ".join(extras)
            badge = ""
            if cuda_only:
                badge = (
                    '<span style="font-size:0.62rem;font-weight:bold;letter-spacing:0.03em;'
                    'padding:0.05rem 0.4rem;border-radius:3px;background:var(--accent-soft);'
                    'color:var(--accent);border:1px solid var(--accent)">CUDA-only</span>'
                )
                if blocked:
                    badge += (
                        f'<span style="font-size:0.66rem;color:var(--warn);margin-left:0.4rem">'
                        f'unavailable on {gpu_vendor.upper()} GPU</span>'
                    )
            rows.append(
                f'<label style="display:flex;align-items:center;gap:0.6rem;'
                f'padding:0.35rem 0.5rem;border-bottom:1px solid var(--panel-2);'
                f'cursor:{"pointer" if (local and not blocked) else "default"};font-size:0.85rem;'
                f'opacity:{"0.55" if blocked else "1"}">'
                f'<input type="checkbox" class="model-toggle" data-surface="{surface_key}" '
                f'data-key="{k}" {checked} {disabled} '
                f'style="accent-color:var(--accent);margin:0">'
                f'<span style="color:var(--text-2);flex:1">{v.get("label", k)} '
                f'<span style="color:var(--text-5);font-size:0.75rem">'
                f'({extra_str})</span> {badge}</span>'
                f'<code style="color:var(--text-4);font-size:0.72rem">{k}</code>'
                f'</label>'
            )
        if not rows:
            rows = ['<div style="color:var(--text-5);font-size:0.8rem;padding:0.5rem">'
                    'No models detected in catalog.</div>']
        return (
            f'<div style="border:1px solid var(--border-3);padding:0.85rem 1rem;'
            f'margin-bottom:0.75rem;background:var(--panel-2)">'
            f'<div style="color:var(--text-2);font-size:0.85rem;font-weight:bold;'
            f'margin-bottom:0.2rem">{title}</div>'
            f'<div style="color:var(--text-5);font-size:0.72rem;margin-bottom:0.5rem">{desc}</div>'
            f'{"".join(rows)}'
            f'</div>'
        )

    edit_hint = (
        ' Tick to enable a model on the surface; untick to hide it. Empty selection = all available enabled.'
        if local else ' Display-only — sign in as Lab to edit.'
    )

    return (
        f'<div class="section">Models (CR-050)</div>'
        f'<div style="color:var(--text-4);font-size:0.75rem;line-height:1.6;margin-bottom:0.75rem">'
        f'Auto-discovered from <code>ollama list</code> and the HuggingFace cache (60 s TTL).'
        f' To add a new LLM: <code>ollama pull &lt;name&gt;</code> on the server.'
        f' To add an image model: download into <code>~/.cache/huggingface</code>.'
        f' Reload this page to see new entries.{edit_hint}'
        f'</div>'
        f'{panel("llm_enabled_models")}'
        f'{panel("rag_enabled_models")}'
        f'{panel("image_enabled_models")}'
    )

# CR-037 — tether the AI pages to streaming. Each AI page gets a one-line
# streaming-anchored framing band plus a shared "how to read AI energy in a
# streaming context" expander drawn from the Language Lab AI position paper
# (Jan 2026). Reframing only — no new measurement. Centralised here so the five
# framing principles read identically on /llm, /image and /rag and can't drift
# from the paper (CR-037 watch-out). Built with plain `+` concatenation, not an
# f-string, so the URL splice can't be mistaken for an undefined name.
_ai_streaming_band = ui._ai_streaming_band
_ai_intro          = ui._ai_intro
_ui_cfg            = ui._ui_cfg
_bake_durations    = ui._bake_durations


@router.post("/variance/run", dependencies=[Depends(requires(VARIANCE_RUN))])
async def variance_run(request: Request):
    from video import run_variance_calibration
    if int(cfg.load().get("variance_runs", 0)) <= 0:
        return JSONResponse(
            {"error": "Variance Runs is 0 — calibration disabled. Set it to ≥2 to run."},
            status_code=400)
    job_id = str(uuid.uuid4())[:8]
    label = "Variance calibration — system offline"

    async def coro():
        try:
            jobs[job_id].update({"status": "running", "stage": "starting"})
            result = await run_variance_calibration(job_id, jobs)
            jobs[job_id].update({"status": "done", "stage": "done", "result": result})
        except Exception as e:
            jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}

    position = queue_control.enqueue(job_id, "variance", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


@router.get("/precalibration/data", dependencies=[Depends(requires(SETTINGS_READ_FULL))])
async def precalibration_data():
    """Return the latest thermal-recovery probe data as JSON.

    Source: results/diagnostics/recovery_<timestamp>_summary.csv (one row per
    distance × workload). Generated by `bin/probe-thermal-recovery`. The
    summary CSV is enough for the recovery-curve chart; the matching
    `_<timestamp>.csv` (raw per-poll readings) is referenced for download.
    """
    import csv as csv_mod
    diag_dir = Path("/home/gos/wattlab/results/diagnostics")
    if not diag_dir.exists():
        return {"available": False, "reason": "no diagnostics directory"}
    summaries = sorted(diag_dir.glob("recovery_*_summary.csv"))
    if not summaries:
        return {"available": False, "reason": "no probe data yet"}
    latest = summaries[-1]
    raw = latest.with_name(latest.stem.replace("_summary", "") + ".csv")
    points = []
    with latest.open() as f:
        for row in csv_mod.DictReader(f):
            points.append({
                "distance_s": int(row["distance_s"]),
                "workload":   row["workload"],
                "encode_s":   float(row["encode_s"]),
                "n_polls":    int(row["n_polls"]),
                "mean_w":     float(row["mean_w"]),
                "std_w":      float(row["std_w"]),
                "cv_pct":     float(row["cv_pct"]),
                "min_w":      float(row["min_w"]),
                "max_w":      float(row["max_w"]),
            })
    return {
        "available": True,
        "source_summary": str(latest),
        "source_raw":     str(raw) if raw.exists() else None,
        "generated_at":   datetime.fromtimestamp(latest.stat().st_mtime)
                                  .isoformat(timespec="seconds"),
        "points": points,
    }


# --- Settings ---

@router.get("/settings", response_class=HTMLResponse, dependencies=[Depends(requires(PUBLIC_PAGE))])
async def settings_page(request: Request):
    s = cfg.load()
    local = can(audience.tier(request), SETTINGS_READ_FULL)

    def field(fid, val, min_, max_, unit, hint="", step=None):
        step_attr = f' step="{step}"' if step else ""
        if local:
            ctrl = (f'<input type="number" id="{fid}" min="{min_}" max="{max_}"{step_attr}'
                    f' value="{val}" style="background:var(--panel);border:1px solid var(--border-3);color:var(--text);'
                    f'font-family:monospace;font-size:0.9rem;padding:0.3rem 0.5rem;'
                    f'width:80px;text-align:right">')
        else:
            ctrl = f'<span style="font-family:monospace;color:var(--accent);font-size:0.95rem">{val}</span>'
        hint_html = f'<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.2rem">{hint}</div>' if hint else ""
        return (f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
                f'padding:0.5rem 0;border-bottom:1px solid var(--panel-2);gap:1rem">'
                f'<div><label style="color:var(--text-2);font-size:0.85rem">{fid.replace("_"," ").title()}</label>'
                f'{hint_html}</div>'
                f'<div style="display:flex;align-items:baseline;gap:0.5rem">'
                f'{ctrl}<span style="color:var(--text-3);font-size:0.8rem">{unit}</span>'
                f'</div></div>')

    def toggle_field(fid, val, hint="", onchange=""):
        oc = f' onchange="{onchange}"' if onchange else ""
        if local:
            checked = "checked" if val else ""
            ctrl = (f'<input type="checkbox" id="{fid}" {checked}{oc}'
                    f' style="width:18px;height:18px;accent-color:var(--accent);cursor:pointer">')
        else:
            ctrl = (f'<span style="font-family:monospace;color:var(--accent);font-size:0.95rem">'
                    f'{"ON" if val else "OFF"}</span>')
        hint_html = f'<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.2rem">{hint}</div>' if hint else ""
        return (f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
                f'padding:0.5rem 0;border-bottom:1px solid var(--panel-2);gap:1rem">'
                f'<div><label style="color:var(--text-2);font-size:0.85rem">{fid.replace("_"," ").title()}</label>'
                f'{hint_html}</div>'
                f'<div style="display:flex;align-items:baseline;gap:0.5rem">{ctrl}</div></div>')

    def slider_field(fid, val, min_, max_, step, unit, hint="", label=None):
        if local:
            ctrl = (f'<input type="range" id="{fid}" min="{min_}" max="{max_}" step="{step}"'
                    f' value="{val}"'
                    f' oninput="document.getElementById(\'{fid}_disp\').textContent=this.value"'
                    f' style="width:130px;accent-color:var(--accent);vertical-align:middle"> '
                    f'<span id="{fid}_disp" style="font-family:monospace;color:var(--accent);'
                    f'font-size:0.9rem;min-width:2.5rem;display:inline-block">{val}</span>')
        else:
            ctrl = f'<span style="font-family:monospace;color:var(--accent);font-size:0.95rem">{val}</span>'
        hint_html = f'<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.2rem">{hint}</div>' if hint else ""
        return (f'<div style="display:flex;justify-content:space-between;align-items:center;'
                f'padding:0.5rem 0;border-bottom:1px solid var(--panel-2);gap:1rem">'
                f'<div><label style="color:var(--text-2);font-size:0.85rem">{label or fid.replace("_"," ").title()}</label>'
                f'{hint_html}</div>'
                f'<div style="display:flex;align-items:center;gap:0.5rem">'
                f'{ctrl}<span style="color:var(--text-3);font-size:0.8rem">{unit}</span>'
                f'</div></div>')

    def textarea_field(fid, val, hint="", rows=3):
        if local:
            ctrl = (f'<textarea id="{fid}" rows="{rows}" spellcheck="false"'
                    f' style="width:100%;background:var(--panel-2);border:1px solid var(--border);'
                    f'color:var(--text-3);font-family:monospace;font-size:0.72rem;'
                    f'padding:0.4rem 0.5rem;resize:vertical;line-height:1.5">{val}</textarea>')
        else:
            ctrl = (f'<div style="background:var(--panel-2);border:1px solid var(--border-2);padding:0.4rem 0.5rem;'
                    f'font-family:monospace;font-size:0.72rem;color:var(--text-4);word-break:break-all;'
                    f'line-height:1.5">{val}</div>')
        hint_html = f'<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.2rem;margin-bottom:0.3rem">{hint}</div>' if hint else ""
        return (f'<div style="padding:0.5rem 0;border-bottom:1px solid var(--panel-2)">'
                f'<label style="color:var(--text-2);font-size:0.85rem">{fid.replace("_"," ").title()}</label>'
                f'{hint_html}{ctrl}</div>')

    def calib_field(fid, val, hint=""):
        disp = f"{val:.2f} %" if val is not None else "—"
        color = "#00ff99" if val is not None else "#333"
        hint_html = f'<div style="color:var(--text-5);font-size:0.72rem;margin-top:0.1rem">{hint}</div>' if hint else ""
        return (f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
                f'padding:0.5rem 0;border-bottom:1px solid var(--panel-2);gap:1rem">'
                f'<div><label style="color:var(--text-4);font-size:0.85rem">{fid.replace("_"," ").title()}</label>'
                f'{hint_html}</div>'
                f'<div style="display:flex;align-items:baseline;gap:0.5rem">'
                f'<span style="font-family:monospace;color:{color};font-size:0.95rem">{disp}</span>'
                f'</div></div>')

    notice = ('' if local else
              '<div style="background:var(--panel);border-left:3px solid #555;padding:0.75rem 1rem;'
              'margin-bottom:1.5rem;font-size:0.82rem;color:var(--text-3)">'
              '🔒 Read-only — settings can only be modified from the lab network or SSH tunnel.'
              '</div>')
    save_block = ('<button onclick="saveSettings()" style="background:var(--accent);color:#000;border:none;'
                  'padding:0.75rem 2rem;cursor:pointer;font-family:monospace;font-size:1rem;margin-top:2rem">'
                  'Save Settings</button><div id="msg" style="margin-top:1rem;font-size:0.85rem"></div>'
                  if local else '')
    subtitle = 'OWL · GoS1 · Lab mode' if local else 'OWL · GoS1 · Read-only'

    chart_js = ('<script src="' + CHARTJS_URL + '"></script>'
                '<script src="/static/wl-charts.js"></script>'
                if local else '')
    return ui.render_page(request, "Settings", head=f"    {chart_js}\n", styles=f"""
        * {{ box-sizing:border-box; margin:0; padding:0; }}
        body {{ font-family:monospace; background:var(--bg); color:var(--text);
               max-width:600px; margin:0 auto; padding:2rem; }}
        h1 {{ color:var(--accent); margin-bottom:0.25rem; font-size:1.6rem; }}
        .subtitle {{ color:var(--text-3); font-size:0.8rem; margin-bottom:2rem; }}
        .section {{ color:var(--text-4); font-size:0.72rem; text-transform:uppercase;
                    letter-spacing:0.05em; margin:1.5rem 0 0.75rem;
                    padding-bottom:0.4rem; border-bottom:1px solid var(--panel); }}
        input[type=number]:focus {{ border-color:var(--accent); outline:none; }}
        details.calib-details > summary {{ cursor:pointer; color:var(--accent);
            font-size:0.82rem; padding:0.5rem 0; list-style:none;
            border-top:1px dashed var(--panel-2); margin-top:0.75rem;
            padding-top:0.75rem; }}
        details.calib-details > summary::-webkit-details-marker {{ display:none; }}
        details.calib-details > summary::before {{ content:"▸ "; color:var(--text-4); }}
        details.calib-details[open] > summary::before {{ content:"▾ "; color:var(--text-4); }}
        details.calib-details .panel {{ background:var(--panel-2); border:1px solid var(--border-3);
            padding:0.75rem; margin-top:0.5rem; }}
""", body=f"""
    <h1>Settings</h1>
    <div class="subtitle">{subtitle}</div>
    {notice}

    <div class="section">Measurement</div>
    {field("baseline_polls",    s['baseline_polls'],    5,  60,  "× 1s",   "baseline window duration")}
    {field("llm_unload_settle_s", s['llm_unload_settle_s'], 1, 30, "s",   "wait after model unload before baseline")}

    <div class="section">Cooldown between passes</div>
    {toggle_field("cooldown_wait_for_idle", s.get('cooldown_wait_for_idle', True),
                  "ON: wait for wall power to settle back to the idle floor before each next pass "
                  "(active-probe, the /rag /llm compare technique). OFF: use the fixed rest periods below. "
                  "Variance calibration always keeps its fixed protocol.", onchange="syncCooldownMode()")}
    {field("video_cooldown_s",  s['video_cooldown_s'],  10, 300, "s",      "fixed rest between CPU and GPU runs (used when wait-for-idle is OFF; also the fallback after an idle-wait timeout)")}
    {field("llm_rest_s",        s['llm_rest_s'],        5,  120, "s",      "fixed pause between LLM batch / compare runs (used when wait-for-idle is OFF; also the timeout fallback)")}
    {field("cooldown_idle_tolerance_w", s.get('cooldown_idle_tolerance_w', 3.0), 0.5, 20, "W", "idle-wait: settle when a reading is within this of the captured floor", step=0.5)}
    {field("cooldown_idle_settle_polls", s.get('cooldown_idle_settle_polls', 3), 1, 10, "polls", "idle-wait: consecutive in-band reads needed to confirm settle")}
    {field("cooldown_idle_max_wait_s", s.get('cooldown_idle_max_wait_s', 120), 10, 600, "s", "idle-wait: cap before timeout → dialog (Lab) or fixed fallback")}
    {field("cooldown_dialog_watchdog_s", s.get('cooldown_dialog_watchdog_s', 75), 15, 300, "s", "idle-wait timeout dialog: auto-apply the fallback if no operator answer within this")}
    {toggle_field("cooldown_show_wait_detail", s.get('cooldown_show_wait_detail', True),
                  "Show the live idle-wait readout (\u23f3 waited \u00b7 current W \u00b7 target) in the progress "
                  "widget on every page during cooldowns. Display only \u2014 cooldown behaviour is unchanged.")}

    <div class="section">Staging</div>
    {field("max_idle_mins",     s['max_idle_mins'],     5,  240, "min",    "auto-lower /tmp/owl-maintenance after this much Lab inactivity (CR-015 watchdog)")}

    <div class="section">Encoding targets</div>
    <div style="color:var(--text-4);font-size:0.75rem;line-height:1.6;margin-bottom:0.75rem">
      ABR target bitrate applied to both CPU and GPU presets for each codec — ensures apples-to-apples energy comparison. Custom ffmpeg commands on the video page override these.
    </div>
    {field("h264_bitrate_kbps", s['h264_bitrate_kbps'], 500, 20000, "kbps", f"H.264 target bitrate (libx264 + {_gpu_enc('h264')})", step=100)}
    {field("h265_bitrate_kbps", s['h265_bitrate_kbps'], 500, 20000, "kbps", f"H.265 target bitrate (libx265 + {_gpu_enc('h265')})", step=100)}
    {field("av1_bitrate_kbps",  s['av1_bitrate_kbps'],  500, 20000, "kbps", f"AV1 target bitrate (libsvtav1 + {_gpu_enc('av1')})", step=100)}

    <div class="section">Confidence thresholds — CI model (CR-028 Phase 2)</div>
    {field("conf_positive_green",  s.get('conf_positive_green', 0.95),  0.5, 0.999, "P", "🟢 min confidence_positive Φ(z) that task draws above idle", step=0.01)}
    {field("conf_positive_yellow", s.get('conf_positive_yellow', 0.80), 0.5, 0.999, "P", "🟡 min confidence_positive", step=0.01)}
    {field("conf_green_polls", s['conf_green_polls'],  1, 100, "polls", "🟢 minimum task polls (both models)")}
    {field("conf_yellow_polls",s['conf_yellow_polls'], 1, 50,  "polls", "🟡 minimum task polls (both models)")}
    {calib_field("variance_idle_pct",       s['variance_idle_pct'],       "calibrated idle noise floor — feeds the CI model (SE_calibrated)")}
    {calib_field("variance_idle_drift_pct", s.get('variance_idle_drift_pct'), "between-window drift CV — feeds SE_drift in the CI model")}
    {calib_field("variance_cpu_pct",        s['variance_cpu_pct'],        "run-level repeatability CV — NOT used in the single-run flag (reserved for aggregate layer)")}
    {calib_field("variance_gpu_pct",        s['variance_gpu_pct'],        "run-level repeatability CV — NOT used in the single-run flag (reserved for aggregate layer)")}
    <div class="section">Confidence thresholds — legacy variance model (fallback for results without raw samples)</div>
    {field("variance_pct",     s['variance_pct'],     0, 50,  "%",     "legacy composite variance — used only when a run has no raw samples", step=0.1)}
    {field("variance_green_x", s['variance_green_x'], 1, 20,  "× noise", "🟢 (legacy) ΔW must exceed this multiple of noise floor", step=0.5)}
    {field("variance_yellow_x",s['variance_yellow_x'],1, 10,  "× noise", "🟡 (legacy) ΔW must exceed this multiple of noise floor", step=0.5)}

    <div class="section">Variance calibration</div>
    <div style="color:var(--text-4);font-size:0.75rem;line-height:1.6;margin-bottom:0.75rem">
      Runs H.264 CPU then H.265 GPU on Meridian N times, sampling raw P110 readings throughout.
      Writes <strong>Variance Idle %</strong> (the idle noise floor) and <strong>Variance Idle Drift %</strong>
      (between-window drift) — these feed the <strong>live CI confidence model</strong> (SE_calibrated + SE_drift).
      Also records per-codec repeatability CVs (CPU/GPU ΔW), reserved for a future aggregate layer — not used in
      the single-run flag. The composite <strong>Variance %</strong> (mean of the three) now feeds only the
      <em>legacy</em> fallback for results saved without raw samples. Queue is blocked for the duration.
    </div>
    {slider_field("variance_runs",      s['variance_runs'],      0,  100, 2,  "runs",    "number of H264-CPU + H265-GPU run pairs · steps of 2 (a pair needs ≥2) · 0 disables calibration here and in the benchmark", label="Variance Runs (0 to skip)")}
    {slider_field("variance_cooldown_s",s['variance_cooldown_s'],10, 300, 10, "s",       "cooldown between each run pair")}
    <div style="padding:0.5rem 0;border-bottom:1px solid var(--panel-2)">
      <label style="color:var(--text-2);font-size:0.85rem">H.264 CPU command (derived)</label>
      <div style="color:var(--text-5);font-size:0.72rem;margin-top:0.2rem;margin-bottom:0.3rem">Mirrors the <code>/video</code> H.264 CPU preset · bitrate from <code>h264_bitrate_kbps</code> · {{input}}/{{output}} substituted at runtime</div>
      <div style="background:var(--panel-2);border:1px solid var(--border-2);padding:0.4rem 0.5rem;font-family:monospace;font-size:0.72rem;color:var(--text-4);word-break:break-all;line-height:1.5">{vid.variance_template("cpu", s)}</div>
    </div>
    <div style="padding:0.5rem 0;border-bottom:1px solid var(--panel-2)">
      <label style="color:var(--text-2);font-size:0.85rem">H.265 GPU command (derived)</label>
      <div style="color:var(--text-5);font-size:0.72rem;margin-top:0.2rem;margin-bottom:0.3rem">Mirrors the <code>/video</code> H.265 GPU preset · bitrate from <code>h265_bitrate_kbps</code> · {{input}}/{{output}} substituted at runtime</div>
      <div style="background:var(--panel-2);border:1px solid var(--border-2);padding:0.4rem 0.5rem;font-family:monospace;font-size:0.72rem;color:var(--text-4);word-break:break-all;line-height:1.5">{vid.variance_template("h265_gpu", s)}</div>
    </div>
    {'<button onclick="runVarianceCalibration()" id="varCalBtn" style="background:var(--border);color:var(--accent);border:1px solid #00ff9944;padding:0.5rem 1.25rem;cursor:pointer;font-family:monospace;font-size:0.85rem;margin-top:0.75rem">▶ Run variance calibration</button><div id="var-cal-msg" style="margin-top:0.5rem;font-size:0.82rem"></div>' if local else '<div style="color:var(--text-5);font-size:0.78rem;margin-top:0.5rem">Calibration requires lab access.</div>'}

    {('''<details class="calib-details" id="precalDetails">
      <summary>More calibration details</summary>
      <div class="panel">
        <div style="color:var(--text-4);font-size:0.72rem;line-height:1.6;margin-bottom:0.5rem">
          Thermal-recovery probe (<code>bin/probe-thermal-recovery</code>): for each distance d after a CPU and a GPU encode, samples N idle polls. Used to validate that <code>variance_cooldown_s</code> is long enough — the curve should flatten well below it.
        </div>
        <div id="precal-meta" style="color:var(--text-5);font-size:0.72rem;margin-bottom:0.5rem">Loading…</div>
        <div style="position:relative;height:260px"><canvas id="precalChart"></canvas></div>
        <div id="precal-stats" style="margin-top:0.75rem;font-size:0.78rem;color:var(--text-3);line-height:1.7"></div>
      </div>
    </details>''') if local else ''}

    <div class="section">Overnight benchmark</div>
    <div style="color:var(--text-4);font-size:0.75rem;line-height:1.6;margin-bottom:0.5rem">
      Full-pipeline benchmark (CR-061): variance calibration &rarr; video all-codecs &times; reps &times; sources &rarr; LLM/RAG/image compare panels.
      Runs as <strong>one queue job that blocks other runs</strong>; follow it on <a href="/queue-status" style="color:var(--accent)">/queue-status</a>, view results at <a href="/benchmark" style="color:var(--accent)">/benchmark</a>.
      <span style="color:var(--warn)">&#9888; calibration is ambient-sensitive &mdash; don't launch during a heat wave.</span>
      Which measures &amp; sources run is set by <code>bench_run_*</code> / <code>bench_sources</code> in settings.json.
    </div>
    {slider_field("bench_video_reps", s['bench_video_reps'], 1, 10, 1, "reps", "video all-codecs repeats per source")}
    {'<button onclick="runBenchmark()" id="benchBtn" style="background:var(--border);color:var(--accent);border:1px solid #00ff9944;padding:0.5rem 1.25rem;cursor:pointer;font-family:monospace;font-size:0.85rem;margin-top:0.75rem">&#9654; Run overnight benchmark</button> <button onclick="cancelBenchmark()" id="benchCancelBtn" style="background:var(--border);color:var(--err);border:1px solid var(--err);padding:0.5rem 1.25rem;cursor:pointer;font-family:monospace;font-size:0.85rem;margin-top:0.75rem">&#9632; Cancel</button><div id="bench-msg" style="margin-top:0.5rem;font-size:0.82rem"></div>' if local else '<div style="color:var(--text-5);font-size:0.78rem;margin-top:0.5rem">Benchmark requires lab access.</div>'}

    {('''<details class="calib-details" id="testdataDetails">
      <summary>Test data cleanup (Lab)</summary>
      <div class="panel">
        <div style="color:var(--text-4);font-size:0.75rem;line-height:1.6;margin-bottom:0.75rem">
          Delete stored result JSON for dev / test runs (CSV is generated on the fly, so removing the
          JSON removes the run entirely). Newest first, up to 50 per type. <span style="color:var(--warn)">No undo &mdash; deletes immediately.</span>
        </div>
        <div id="testdata-panel" style="font-size:0.8rem;color:var(--text-3)">loading&hellip;</div>
      </div>
    </details>''') if local else ''}

    {(f'''<div class="section">Members</div>
    <div style="color:var(--text-4);font-size:0.75rem;line-height:1.6;margin-bottom:0.75rem">
      Magic-link allowlist (<code>data/members.json</code>) — one email per line.
      Lowercased, stripped, deduped and sorted on save. Reloaded into the running service
      automatically; no restart needed. <span style="color:var(--text-3)">{len(auth.list_members())} email(s)</span>
    </div>
    {textarea_field("members", chr(10).join(auth.list_members()), "", rows=12)}''') if local else ''}

    <div class="section">Tier limits</div>
    <div style="color:var(--text-4);font-size:0.75rem;line-height:1.6;margin-bottom:0.75rem">
      CR-001 part D — concurrent-job caps and upload-size caps per audience
      tier. Anonymous keyed by IP, Member by email, Lab uncapped.
    </div>
    {field("queue_anonymous_cap",      s['queue_anonymous_cap'],      1, 10,   "jobs",  "concurrent (queued + running) Anonymous jobs per IP")}
    {field("queue_member_cap",         s['queue_member_cap'],         1, 20,   "jobs",  "concurrent jobs per Member email")}
    {field("upload_size_anonymous_mb", s['upload_size_anonymous_mb'], 10, 1024, "MB",    "Anonymous /video/upload byte cap")}
    {field("upload_size_member_mb",    s['upload_size_member_mb'],    100, 4096, "MB",   "Member /video/upload byte cap")}
    {field("enhance_upload_max_mb",    s.get('enhance_upload_max_mb', 1024), 10, 4096, "MB", "Member /enhance-run upload byte cap (Lab uncapped)")}
    {field("enhance_upload_max_duration_s", s.get('enhance_upload_max_duration_s', 60), 10, 3600, "s", "Member /enhance-run clip-duration cap — runs are 1×-paced, so duration ≈ processing time (Lab uncapped)")}

    {_models_section_html(s, local)}

    {save_block}
    <script>
    function collectModelToggles(surfaceKey) {{
        return Array.from(
            document.querySelectorAll('.model-toggle[data-surface="' + surfaceKey + '"]:checked')
        ).map(el => el.dataset.key);
    }}
    function syncCooldownMode() {{
        // When wait-for-idle is ON, the fixed rest periods are greyed (the
        // idle tunables drive cooldown instead); when OFF, the idle tunables
        // are greyed. Mirrors power.cooldown_between_runs's strategy switch.
        var tog = document.getElementById('cooldown_wait_for_idle');
        if (!tog || tog.type !== 'checkbox') return;   // read-only view → no-op
        var on = tog.checked;
        function setDisabled(id, dis) {{
            var el = document.getElementById(id);
            if (el) {{ el.disabled = dis; el.style.opacity = dis ? '0.35' : '1'; }}
        }}
        setDisabled('video_cooldown_s', on);
        setDisabled('llm_rest_s', on);
        ['cooldown_idle_tolerance_w','cooldown_idle_settle_polls',
         'cooldown_idle_max_wait_s','cooldown_dialog_watchdog_s'].forEach(function(id) {{
            setDisabled(id, !on);
        }});
    }}
    document.addEventListener('DOMContentLoaded', syncCooldownMode);

    async function saveSettings() {{
        const num_fields = ['baseline_polls','video_cooldown_s','llm_rest_s','llm_unload_settle_s',
                            'cooldown_idle_tolerance_w','cooldown_idle_settle_polls',
                            'cooldown_idle_max_wait_s','cooldown_dialog_watchdog_s',
                            'h264_bitrate_kbps','h265_bitrate_kbps','av1_bitrate_kbps',
                            'variance_pct','variance_green_x','variance_yellow_x',
                            'conf_positive_green','conf_positive_yellow',
                            'conf_green_polls','conf_yellow_polls',
                            'variance_runs','variance_cooldown_s',
                            'queue_anonymous_cap','queue_member_cap',
                            'upload_size_anonymous_mb','upload_size_member_mb',
                            'enhance_upload_max_mb','enhance_upload_max_duration_s',
                            'bench_video_reps'];
        const bool_fields = ['cooldown_wait_for_idle','cooldown_show_wait_detail'];
        const str_fields = ['members'];
        const list_fields = ['llm_enabled_models','rag_enabled_models','image_enabled_models'];
        const body = {{}};
        for (const f of num_fields) {{
            const el = document.getElementById(f);
            if (el) body[f] = parseFloat(el.value);
        }}
        for (const f of bool_fields) {{
            const el = document.getElementById(f);
            if (el) body[f] = el.checked;
        }}
        for (const f of str_fields) {{
            const el = document.getElementById(f);
            if (el) body[f] = el.value;
        }}
        for (const f of list_fields) {{
            if (document.querySelector('.model-toggle[data-surface="' + f + '"]')) {{
                body[f] = collectModelToggles(f);
            }}
        }}
        try {{
            const resp = await fetch('/settings', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(body),
            }});
            const data = await resp.json();
            if (data.ok) {{
                document.getElementById('msg').innerHTML =
                    '<span style="color:var(--accent)">✓ Saved.</span>';
            }} else {{
                document.getElementById('msg').innerHTML =
                    '<span style="color:var(--err)">Error: ' + JSON.stringify(data) + '</span>';
            }}
        }} catch(e) {{
            document.getElementById('msg').innerHTML =
                '<span style="color:var(--err)">Failed: ' + e + '</span>';
        }}
    }}

    async function runVarianceCalibration() {{
        const btn = document.getElementById('varCalBtn');
        const msg = document.getElementById('var-cal-msg');
        if (!btn) return;
        btn.disabled = true;
        msg.innerHTML = '<span style="color:var(--warn)">Saving settings…</span>';
        await saveSettings();
        msg.innerHTML = '<span style="color:var(--warn)">Queuing calibration job…</span>';
        try {{
            const resp = await fetch('/variance/run', {{method: 'POST'}});
            const data = await resp.json();
            if (data.job_id) {{
                msg.innerHTML = '<span style="color:var(--accent)">Job ' + data.job_id
                    + ' queued (position ' + data.queue_position + '). '
                    + '<a href="/queue-status" style="color:var(--accent)">View queue →</a>'
                    + '</span>';
            }} else {{
                msg.innerHTML = '<span style="color:var(--err)">Error: ' + JSON.stringify(data) + '</span>';
                btn.disabled = false;
            }}
        }} catch(e) {{
            msg.innerHTML = '<span style="color:var(--err)">Failed: ' + e + '</span>';
            btn.disabled = false;
        }}
    }}

    let _benchJobId = null;
    async function runBenchmark() {{
        const btn = document.getElementById('benchBtn');
        const msg = document.getElementById('bench-msg');
        if (!btn) return;
        btn.disabled = true;
        msg.innerHTML = '<span style="color:var(--warn)">Saving settings…</span>';
        await saveSettings();
        msg.innerHTML = '<span style="color:var(--warn)">Queuing benchmark…</span>';
        try {{
            const resp = await fetch('/benchmark/run', {{method: 'POST'}});
            const data = await resp.json();
            if (data.job_id) {{
                _benchJobId = data.job_id;
                msg.innerHTML = '<span style="color:var(--accent)">Benchmark ' + data.job_id
                    + ' queued (position ' + data.queue_position + '). '
                    + '<a href="/queue-status" style="color:var(--accent)">Follow on the queue →</a></span>';
            }} else {{
                msg.innerHTML = '<span style="color:var(--err)">Error: ' + JSON.stringify(data) + '</span>';
                btn.disabled = false;
            }}
        }} catch(e) {{
            msg.innerHTML = '<span style="color:var(--err)">Failed: ' + e + '</span>';
            btn.disabled = false;
        }}
    }}
    async function cancelBenchmark() {{
        const msg = document.getElementById('bench-msg');
        let jid = _benchJobId;
        if (!jid) {{
            // page may have reloaded — fall back to the running job if it's a benchmark
            try {{
                const q = await (await fetch('/queue')).json();
                if (q.running && q.running.type === 'benchmark') jid = q.running.job_id;
            }} catch(e) {{}}
        }}
        if (!jid) {{ msg.innerHTML = '<span style="color:var(--text-4)">No benchmark to cancel.</span>'; return; }}
        const form = new FormData(); form.append('job_id', jid);
        try {{
            const resp = await fetch('/benchmark/cancel', {{method: 'POST', body: form}});
            const data = await resp.json();
            msg.innerHTML = '<span style="color:var(--warn)">Cancel: ' + (data.state || JSON.stringify(data))
                + ' — takes effect after the current step.</span>';
            const b = document.getElementById('benchBtn'); if (b) b.disabled = false;
        }} catch(e) {{
            msg.innerHTML = '<span style="color:var(--err)">Cancel failed: ' + e + '</span>';
        }}
    }}

    let precalChartInstance = null;
    async function loadPrecalibration() {{
        const meta = document.getElementById('precal-meta');
        const stats = document.getElementById('precal-stats');
        if (precalChartInstance) return;  // already loaded
        try {{
            const resp = await fetch('/precalibration/data');
            const data = await resp.json();
            if (!data.available) {{
                meta.innerHTML = '<span style="color:var(--text-5)">No probe data yet — '
                    + 'run <code>bin/probe-thermal-recovery</code> from the shell to generate.</span>';
                return;
            }}
            const cpu = data.points.filter(p => p.workload === 'cpu');
            const gpu = data.points.filter(p => p.workload === 'gpu');
            precalChartInstance = WlCharts.line({{
                canvas: document.getElementById('precalChart'),
                xLabel: 'distance from encode end (s)',
                yLabel: 'mean idle watts (8-poll window)',
                yUnit:  'W',
                datasets: [
                    {{ label: 'post-CPU encode', color: 'cpu',
                       points: cpu.map(p => ({{x:p.distance_s, y:p.mean_w}})) }},
                    {{ label: 'post-GPU encode', color: 'gpu',
                       points: gpu.map(p => ({{x:p.distance_s, y:p.mean_w}})) }},
                ]
            }});
            // Quick stats: idle reached, recommended cooldown (last point where mean delta to floor < 1W)
            const meanW = arr => arr.reduce((s,p)=>s+p.mean_w,0)/arr.length;
            const settled = data.points.filter(p => p.distance_s >= 60);
            const floor = settled.length ? meanW(settled).toFixed(2) : 'n/a';
            // Recovery threshold: first distance where mean within 1W of the settled floor
            function recoveryAt(workload) {{
                const pts = data.points.filter(p => p.workload === workload).sort((a,b)=>a.distance_s-b.distance_s);
                const f = parseFloat(floor);
                for (const p of pts) {{ if (Math.abs(p.mean_w - f) < 1.0) return p.distance_s; }}
                return null;
            }}
            const cpuRec = recoveryAt('cpu'), gpuRec = recoveryAt('gpu');
            const fname = data.source_summary.split('/').pop();
            meta.innerHTML = 'source: <code>' + fname + '</code> · generated ' + data.generated_at;
            stats.innerHTML =
                '· settled idle (d ≥ 60s mean): <strong style="color:var(--accent)">' + floor + ' W</strong><br>' +
                '· post-CPU recovery to ±1W of floor: <strong>' + (cpuRec !== null ? cpuRec + 's' : 'not within 1W') + '</strong><br>' +
                '· post-GPU recovery to ±1W of floor: <strong>' + (gpuRec !== null ? gpuRec + 's' : 'not within 1W') + '</strong><br>' +
                '· n distances: ' + (new Set(data.points.map(p=>p.distance_s))).size;
        }} catch(e) {{
            meta.innerHTML = '<span style="color:var(--err)">Failed to load probe data: ' + e + '</span>';
        }}
    }}
    const _precalDetails = document.getElementById('precalDetails');
    if (_precalDetails) {{
        _precalDetails.addEventListener('toggle', () => {{
            if (_precalDetails.open) loadPrecalibration();
        }});
    }}

    // Lab-only test-data cleanup panel. Lists recent results per type and lets
    // a Lab user delete a run's stored JSON via DELETE /results/<type>/<id>.
    // Delete buttons carry the id in data-attrs (no inline-quote escaping).
    async function loadTestData() {{
        const panel = document.getElementById('testdata-panel');
        if (!panel) return;
        const types = [['llm', 'LLM / RAG'], ['image', 'Image'], ['video', 'Video'], ['enhance', 'Enhance']];
        let html = '';
        for (const pair of types) {{
            const t = pair[0], lbl = pair[1];
            let runs = [];
            try {{
                const resp = await fetch('/results/' + t + '/list?limit=50');
                runs = await resp.json();
                if (!Array.isArray(runs)) runs = [];
            }} catch(e) {{ runs = []; }}
            html += '<div style="margin:0.75rem 0 0.3rem;color:var(--text-2)">' + lbl
                  + ' <span style="color:var(--text-5)">(' + runs.length + ')</span></div>';
            if (!runs.length) {{ html += '<div style="color:var(--text-5);font-size:0.75rem">none</div>'; continue; }}
            html += runs.map(function(r) {{
                const date = (r.saved_at || '').slice(0, 16).replace('T', ' ');
                const mode = r.mode ? ' &middot; ' + r.mode : '';
                return '<div style="display:flex;justify-content:space-between;align-items:center;'
                     + 'padding:0.25rem 0;border-bottom:1px solid var(--panel-2);gap:0.5rem">'
                     + '<span style="color:var(--text-3);font-size:0.75rem;font-family:monospace">'
                     + date + ' &middot; ' + r.job_id + mode + '</span>'
                     + '<button class="td-del" data-type="' + t + '" data-id="' + r.job_id + '" '
                     + 'style="background:none;border:1px solid var(--err);color:var(--err);'
                     + 'font-size:0.72rem;padding:0.1rem 0.5rem;cursor:pointer">&#10005; delete</button>'
                     + '</div>';
            }}).join('');
        }}
        panel.innerHTML = html;
        panel.querySelectorAll('.td-del').forEach(function(b) {{
            b.onclick = function() {{ deleteTestResult(b.getAttribute('data-type'), b.getAttribute('data-id')); }};
        }});
    }}

    async function deleteTestResult(jobType, jobId) {{
        // No per-delete confirm by design — the collapsed dropdown is the guard
        // (Lab tool). Deletes immediately and refreshes the panel.
        try {{
            const resp = await fetch('/results/' + jobType + '/' + jobId, {{method: 'DELETE'}});
            const d = await resp.json().catch(function() {{ return {{}}; }});
            if (d && d.ok) loadTestData();          // refresh the panel in place
            else alert('Delete failed: ' + ((d && d.error) || resp.status));
        }} catch(e) {{ alert('Delete failed: ' + e); }}
    }}

    // Lazy-load the cleanup lists when the dropdown is first opened (and refresh
    // on each open). Keeps the panel out of the way until the Lab user wants it.
    const _tdDetails = document.getElementById('testdataDetails');
    if (_tdDetails) {{
        _tdDetails.addEventListener('toggle', function() {{ if (_tdDetails.open) loadTestData(); }});
    }}
    </script>
""")


@router.post("/settings", dependencies=[Depends(requires(SETTINGS_WRITE))])
async def settings_save(request: Request, data: dict):
    members_raw = data.pop("members", None)
    member_count = auth.write_members(members_raw) if members_raw is not None else None
    saved = cfg.save(data)
    # CR-050 — invalidate catalog caches so per-surface enable changes
    # take effect on the next /llm /rag /image /compare render without
    # waiting for the 60 s TTL.
    model_catalog.refresh_all()
    return {"ok": True, "settings": saved, "member_count": member_count}
