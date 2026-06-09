"""
Benchmark routes — CR-061 in-app overnight benchmark.

/benchmark/run + /benchmark/cancel drive benchmark.py (the multi-step
variance→video→llm→rag→image orchestrator); /benchmark + /benchmark/{bid}
are the Member-visible results views. Phase 3 per-feature route module —
shared state from runtime.py, chrome from ui.py, never import main.
"""
import html as html_lib
import io
import json
import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

import benchmark
import queue_control
import settings as cfg
import ui
from capabilities import requires, BENCHMARK_RUN, BENCHMARK_VIEW
from persist import list_results, load_result
from runtime import jobs
from ui import _BENCH_HYDRATE_JS, _RESULT_JS

router = APIRouter()


@router.post("/benchmark/run", dependencies=[Depends(requires(BENCHMARK_RUN))])
async def benchmark_run(request: Request):
    """CR-061 — launch the in-app overnight benchmark as one queue job."""
    bid = str(uuid.uuid4())[:8]
    benchmark.create_run(bid, cfg.load())   # pre-create queued manifest
    label = "Overnight benchmark"

    async def coro():
        try:
            jobs[bid].update({"status": "running", "stage": "starting"})
            result = await benchmark.run_benchmark_job(bid, jobs, cfg.load())
            jobs[bid].update({"status": "done", "stage": "done", "result": result})
        except Exception as e:
            jobs[bid] = {**jobs.get(bid, {}), "status": "error",
                         "stage": "error", "error": str(e)}

    position = queue_control.enqueue(bid, "benchmark", label, coro, request=request)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": bid, "queue_position": position}


@router.post("/benchmark/cancel", dependencies=[Depends(requires(BENCHMARK_RUN))])
async def benchmark_cancel(request: Request, job_id: str = Form(...)):
    """Cancel a benchmark run. Running → cooperative flag (lands after the
    current step); queued-but-not-started → drop from queue + mark cancelled."""
    job_id = (job_id or "").strip()
    if queue_control.current_job_id == job_id:
        if job_id in jobs:
            jobs[job_id]["cancel_requested"] = True
        return {"ok": True, "state": "cancelling"}
    if queue_control.cancel_pending(job_id):
        if job_id in jobs:
            jobs[job_id].update({"status": "cancelled", "stage": "cancelled"})
        benchmark.cancel_queued(job_id)
        return {"ok": True, "state": "cancelled_before_start"}
    return JSONResponse({"ok": False, "state": "not_found"}, status_code=404)


# ── CR-061 benchmark results view ───────────────────────────────────────────

_BENCH_STATUS_DOT = {"done": "🟢", "running": "🟡", "queued": "⚪",
                     "cancelled": "⚫", "error": "🔴"}


def _benchmark_rows_html(runs: list) -> str:
    if not runs:
        return ('<p style="color:var(--text-3);font-family:monospace;font-size:0.85rem">'
                'No benchmark runs yet. Launch one from <a href="/settings" '
                'style="color:var(--accent)">/settings</a>.</p>')
    rows = []
    for r in runs:
        bid = r.get("benchmark_run_id") or r.get("job_id")
        status = r.get("status") or "?"
        dot = _BENCH_STATUS_DOT.get(status, "⚪")
        done, total = r.get("n_done", 0), r.get("total_steps", 0)
        err = r.get("n_error", 0)
        when = (r.get("started_at") or r.get("saved_at") or "")[:16].replace("T", " ")
        err_html = (f' · <span style="color:var(--err)">{err} err</span>') if err else ""
        rows.append(
            f'<a class="finding-row" href="/benchmark/{html_lib.escape(bid)}">'
            f'<div class="finding-row-top">'
            f'<span class="finding-row-dot">{dot}</span>'
            f'<span class="finding-row-headline">Benchmark {html_lib.escape(bid)} · '
            f'{html_lib.escape(status)}</span>'
            f'<span class="finding-row-date">{html_lib.escape(when)}</span></div>'
            f'<div class="finding-row-claim">{done}/{total} steps done{err_html}</div></a>'
        )
    return "".join(rows)


@router.get("/benchmark", response_class=HTMLResponse,
         dependencies=[Depends(requires(BENCHMARK_VIEW))])
async def benchmark_list_page(request: Request):
    runs = list_results("benchmark", limit=50, visitor_key=None)
    body = (
        '<div class="finding-wrap">'
        '<h1 style="font-size:1.2rem;color:var(--text)">Benchmark runs</h1>'
        '<p style="color:var(--text-4);font-family:monospace;font-size:0.78rem">'
        'Full-pipeline overnight benchmarks (CR-061). Launch + cancel from '
        '<a href="/settings" style="color:var(--accent)">/settings</a>.</p>'
        f'{_benchmark_rows_html(runs)}'
        '</div>'
    )
    # S41 owner request: standard chrome (header back-link + footer) on the
    # benchmark pages — previously the chrome-less findings-style shell.
    return HTMLResponse(ui.render_page(
        request, "Benchmark runs", body,
        head='    <meta name="viewport" content="width=device-width,initial-scale=1">\n',
        styles=(
            'body{background:var(--bg);color:var(--text)}'
            '.finding-wrap{max-width:880px;margin:1.5rem auto;padding:0 1rem;color:var(--text);background:var(--bg)}'
            '.finding-row{display:block;border:1px solid var(--border);padding:0.6rem 0.8rem;margin:0.5rem 0;text-decoration:none;background:var(--panel)}'
            '.finding-row:hover{border-color:var(--accent)}'
            '.finding-row-top{display:flex;gap:0.5rem;align-items:baseline}'
            '.finding-row-dot{font-size:0.8rem}'
            '.finding-row-headline{color:var(--text);font-family:monospace;font-size:0.85rem;flex:1}'
            '.finding-row-date{color:var(--text-5);font-family:monospace;font-size:0.72rem}'
            '.finding-row-claim{color:var(--text-3);font-family:monospace;font-size:0.75rem;margin-top:0.3rem}'
        )))


@router.get("/benchmark/{bid}", response_class=HTMLResponse,
         dependencies=[Depends(requires(BENCHMARK_VIEW))])
async def benchmark_detail_page(bid: str, request: Request):
    m = load_result("benchmark", bid, visitor_key=None)
    if not m:
        return HTMLResponse('<p style="font-family:monospace">Benchmark run not found. '
                            '<a href="/benchmark">← all runs</a></p>', status_code=404)
    status = m.get("status", "?")
    cfg_blob = m.get("config", {})
    steps_html = []
    for st in m.get("steps", []):
        dot = _BENCH_STATUS_DOT.get(st.get("status"), "⚪")
        label = html_lib.escape(st.get("label", st.get("id", "?")))
        sstatus = html_lib.escape(st.get("status", "?"))
        err = st.get("error")
        head = (f'<div style="font-family:monospace;font-size:0.82rem;margin:0.8rem 0 0.3rem">'
                f'{dot} <b>{label}</b> · <span style="color:var(--text-4)">{sstatus}</span>'
                + (f' · <span style="color:var(--err)">{html_lib.escape(str(err))}</span>' if err else '')
                + '</div>')
        ref = st.get("result_ref")
        if ref and ref.get("job_id"):
            head += (f'<div class="bench-embed" data-bid="{html_lib.escape(bid)}" '
                     f'data-type="{html_lib.escape(ref.get("type",""))}" '
                     f'data-kind="{html_lib.escape(st.get("kind",""))}" '
                     f'data-result-id="{html_lib.escape(ref.get("job_id"))}">'
                     f'<div class="loading" style="color:var(--text-5);font-family:monospace;'
                     f'font-size:0.75rem">Loading…</div></div>')
        steps_html.append(head)
    body = (
        '<div class="bench-wrap">'
        f'<p style="font-family:monospace;font-size:0.78rem"><a href="/benchmark" style="color:var(--accent)">← all runs</a></p>'
        f'<h1 style="font-size:1.2rem;color:var(--text)">{_BENCH_STATUS_DOT.get(status,"⚪")} Benchmark {html_lib.escape(bid)}</h1>'
        f'<div style="color:var(--text-4);font-family:monospace;font-size:0.76rem;line-height:1.6">'
        f'status: {html_lib.escape(status)} · {m.get("total_steps",0)} steps · '
        f'started {html_lib.escape((m.get("started_at") or "—")[:19].replace("T"," "))}'
        f'{(" · finished " + html_lib.escape((m.get("finished_at") or "")[:19].replace("T"," "))) if m.get("finished_at") else ""}<br>'
        f'config: reps={cfg_blob.get("video_reps")} · sources={html_lib.escape(", ".join(cfg_blob.get("sources",[])))} · '
        f'measures={html_lib.escape(", ".join(cfg_blob.get("enabled",[])))}</div>'
        + "".join(steps_html)
        + '</div>'
    )
    # Footer already ships _CARBON_JS; the result-card + hydrate bundles ride
    # in tail so the embeds keep working.
    return HTMLResponse(ui.render_page(
        request, f"Benchmark {html_lib.escape(bid)}", body,
        head='    <meta name="viewport" content="width=device-width,initial-scale=1">\n',
        styles=('body{background:var(--bg);color:var(--text)}'
                '.bench-wrap{max-width:900px;margin:1.5rem auto;padding:0 1rem;color:var(--text);background:var(--bg)}'),
        tail=_RESULT_JS + _BENCH_HYDRATE_JS))


@router.get("/benchmark/{bid}/result/{job_type}/{job_id}.json",
         dependencies=[Depends(requires(BENCHMARK_VIEW))])
async def benchmark_result_json(bid: str, job_type: str, job_id: str):
    """CR-061 — serve a benchmark step's result to anyone who can VIEW the
    benchmark (Member+). The generic /results/.../download.json is visitor-
    scoped (own-jobs only, CR-026), so a member can't load Lab-produced
    benchmark results through it. This loads unscoped, but ONLY for (type,
    job_id) pairs actually referenced by THIS manifest — so it can't be used
    to read another visitor's private results."""
    if job_type not in ("video", "llm", "image"):
        return JSONResponse({"error": "Invalid type"}, status_code=400)
    manifest = load_result("benchmark", bid, visitor_key=None)
    if not manifest:
        return JSONResponse({"error": "Not found"}, status_code=404)
    allowed = set()
    for st in manifest.get("steps", []):
        ref = st.get("result_ref")
        if ref and ref.get("job_id"):
            allowed.add((ref.get("type"), ref.get("job_id")))
    if (job_type, job_id) not in allowed:
        return JSONResponse({"error": "Not found"}, status_code=404)
    data = load_result(job_type, job_id, visitor_key=None)
    if not data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return StreamingResponse(
        io.BytesIO(json.dumps(data, indent=2).encode()),
        media_type="application/json",
    )
