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
import hosts
import persist
import peer
import queue_control
import settings as cfg
import ui
from capabilities import requires, BENCHMARK_RUN, BENCHMARK_VIEW
from persist import list_results, load_result
from runtime import jobs
from ui import _BENCH_HYDRATE_JS, _RESULT_JS

router = APIRouter()


def launch_local(bid: str, config: dict | None = None, group_id: str | None = None,
                 request: Request | None = None):
    """Create the queued manifest and enqueue the run on THIS node. `config`
    (a launcher's benchmark._config) makes a group member run the launcher's
    plan; None = this node's own settings. Returns the queue position (None =
    queue full). Shared by POST /benchmark/run and POST /peer/jobs."""
    benchmark.create_run(bid, benchmark.settings_for(config, cfg.load()), group_id)
    label = "Overnight benchmark" + (f" (group {group_id})" if group_id else "")

    async def coro():
        try:
            jobs[bid].update({"status": "running", "stage": "starting"})
            result = await benchmark.run_benchmark_job(
                bid, jobs, benchmark.settings_for(config, cfg.load()))
            jobs[bid].update({"status": "done", "stage": "done", "result": result})
        except Exception as e:
            jobs[bid] = {**jobs.get(bid, {}), "status": "error",
                         "stage": "error", "error": str(e)}

    return queue_control.enqueue(bid, "benchmark", label, coro, request=request)


@router.post("/benchmark/run", dependencies=[Depends(requires(BENCHMARK_RUN))])
async def benchmark_run(request: Request):
    """CR-061 — launch the in-app overnight benchmark as one queue job.

    Optional JSON body {"targets": [node ids]} (default: this node only).
    Several targets = one run per node, in parallel, each on its own queue and
    meters, sharing a group_id and this node's plan. A peer that is offline or
    refuses is reported as skipped — a measurement never moves to another node
    (docs/gos2_design.md §2). Peers' finished runs arrive by replication."""
    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        body = {}
    me = hosts.local_host()["id"]
    targets = [t for t in (body.get("targets") or [me]) if isinstance(t, str)]
    group_id = uuid.uuid4().hex[:8] if len(targets) > 1 else None
    config = benchmark._config(cfg.load())
    out = {"group_id": group_id, "runs": [], "skipped": []}
    for hid in targets:
        if hid == me:
            bid = str(uuid.uuid4())[:8]
            position = launch_local(bid, config if group_id else None, group_id, request)
            if position is None:
                out["skipped"].append({"host": me, "reason": "queue full"})
                continue
            out["runs"].append({"host": me, "job_id": bid, "queue_position": position})
            out.setdefault("job_id", bid)
            out.setdefault("queue_position", position)
            continue
        h = hosts.get(hid)
        if not h or hosts.driver(h) != "peer":
            out["skipped"].append({"host": hid, "reason": "not a peer node"})
            continue
        label = h.get("label", hid)
        if not peer.online(h):
            out["skipped"].append({"host": label, "reason": "offline"})
            continue
        try:
            r = peer.call(h, "POST", "/peer/jobs",
                          {"type": "benchmark", "params": {"config": config, "group_id": group_id}},
                          timeout=20)
            out["runs"].append({"host": label, "job_id": r["job_id"],
                                "queue_position": r.get("queue_position")})
        except Exception as e:
            out["skipped"].append({"host": label, "reason": repr(e)[:200]})
    if not out["runs"]:
        why = "; ".join(f"{s['host']}: {s['reason']}" for s in out["skipped"])
        return JSONResponse({**out, "error": f"No run started ({why})."}, status_code=429)
    return out


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


def _bench_row_html(r: dict, check: bool = True) -> str:
    bid = r.get("benchmark_run_id") or r.get("job_id")
    status = r.get("status") or "?"
    dot = _BENCH_STATUS_DOT.get(status, "⚪")
    done, total = r.get("n_done", 0), r.get("total_steps", 0)
    err = r.get("n_error", 0)
    when = (r.get("started_at") or r.get("saved_at") or "")[:16].replace("T", " ")
    err_html = (f' · <span style="color:var(--err)">{err} err</span>') if err else ""
    gpu_html = f' · {html_lib.escape(r["gpu"])}' if r.get("gpu") else ""
    measures = ", ".join((r.get("config") or {}).get("enabled") or [])
    box = (f'<input type="checkbox" class="bench-pick" value="{html_lib.escape(bid)}" '
           f'title="tick two or more runs to compare">') if check else ""
    return (
        f'<div class="bench-row">{box}'
        f'<a class="finding-row" href="/benchmark/{html_lib.escape(bid)}">'
        f'<div class="finding-row-top">'
        f'<span class="finding-row-dot">{dot}</span>'
        f'<span class="host-badge">{html_lib.escape(str(r.get("host") or "?"))}</span>'
        f'<span class="finding-row-headline">Benchmark {html_lib.escape(bid)} · '
        f'{html_lib.escape(status)}</span>'
        f'<span class="finding-row-date">{html_lib.escape(when)}</span></div>'
        f'<div class="finding-row-claim">{done}/{total} steps done{err_html}{gpu_html}'
        f'{(" · " + html_lib.escape(measures)) if measures else ""}</div></a></div>'
    )


def _benchmark_rows_html(runs: list) -> str:
    """Newest first; runs launched together (shared group_id) are drawn as one
    block, at the position of the group's newest run, with a compare link."""
    if not runs:
        return ('<p style="color:var(--text-3);font-family:monospace;font-size:0.85rem">'
                'No benchmark runs yet. Launch one from <a href="/settings" '
                'style="color:var(--accent)">/settings</a>.</p>')
    groups = {}
    for r in runs:
        if r.get("group_id"):
            groups.setdefault(r["group_id"], []).append(r)
    rows, drawn = [], set()
    for r in runs:
        gid = r.get("group_id")
        if not gid or len(groups[gid]) < 2:
            rows.append(_bench_row_html(r))
            continue
        if gid in drawn:
            continue
        drawn.add(gid)
        members = sorted(groups[gid], key=lambda x: str(x.get("host") or ""))
        ids = ",".join(m.get("benchmark_run_id") or m.get("job_id") for m in members)
        hosts_txt = " · ".join(
            f'{html_lib.escape(str(m.get("host")))} {_BENCH_STATUS_DOT.get(m.get("status"), "⚪")}'
            for m in members)
        when = (members[0].get("created_at") or "")[:10]
        rows.append(
            f'<div class="bench-group"><div class="bench-group-head">Parallel run '
            f'{html_lib.escape(gid)} · {html_lib.escape(when)} · {hosts_txt} · '
            f'<a href="/benchmark/compare?ids={html_lib.escape(ids)}" '
            f'style="color:var(--accent)">compare →</a></div>'
            + "".join(_bench_row_html(m, check=False) for m in members) + '</div>')
    return "".join(rows)


def _host_chips(runs: list, current: str) -> str:
    """All · <every node> — from the configured nodes plus any host present in
    the data (a retired node's runs stay reachable)."""
    me = hosts.local_host()
    names = {me["id"]: me.get("label", me["id"])}
    for hid, h in hosts.all_remote().items():
        if hosts.driver(h) == "peer":
            names[hid] = h.get("label", hid)
    for r in runs:
        if r.get("host_id"):
            names.setdefault(r["host_id"], r.get("host") or r["host_id"])
    chips = [("", "All")] + sorted(names.items(), key=lambda kv: kv[1])
    out = []
    for hid, label in chips:
        on = hid == current
        href = "/benchmark" + (f"?host={html_lib.escape(hid)}" if hid else "")
        n = sum(1 for r in runs if not hid or r.get("host_id") == hid)
        out.append(f'<a class="host-chip{" on" if on else ""}" href="{href}">'
                   f'{html_lib.escape(label)} <span style="color:var(--text-5)">{n}</span></a>')
    return '<div class="host-chips">' + "".join(out) + '</div>'


_BENCH_LIST_JS = """<script>
(function(){
  const btn = document.getElementById('bench-compare-btn');
  if (!btn) return;
  const upd = () => {
    const ids = [...document.querySelectorAll('.bench-pick:checked')].map(e => e.value);
    btn.disabled = ids.length < 2;
    btn.dataset.ids = ids.join(',');
  };
  document.querySelectorAll('.bench-pick').forEach(e => e.addEventListener('change', upd));
  btn.addEventListener('click', () => { location.href = '/benchmark/compare?ids=' + btn.dataset.ids; });
  upd();
})();
</script>"""


_LIST_STYLES = (
    'body{background:var(--bg);color:var(--text);max-width:912px;margin:0 auto;padding:0 1rem}'
    '.finding-wrap{max-width:880px;margin:1.5rem auto;padding:0 1rem;color:var(--text);background:var(--bg)}'
    '.bench-row{display:flex;gap:0.5rem;align-items:center}'
    '.bench-row .finding-row{flex:1;min-width:0}'
    '.finding-row{display:block;border:1px solid var(--border);padding:0.6rem 0.8rem;margin:0.5rem 0;text-decoration:none;background:var(--panel)}'
    '.finding-row:hover{border-color:var(--accent)}'
    '.finding-row-top{display:flex;gap:0.5rem;align-items:baseline;flex-wrap:wrap}'
    '.finding-row-dot{font-size:0.8rem}'
    '.finding-row-headline{color:var(--text);font-family:monospace;font-size:0.85rem;flex:1}'
    '.finding-row-date{color:var(--text-5);font-family:monospace;font-size:0.72rem}'
    '.finding-row-claim{color:var(--text-3);font-family:monospace;font-size:0.75rem;margin-top:0.3rem}'
    '.host-badge{font-family:monospace;font-size:0.72rem;color:var(--accent);border:1px solid var(--accent);padding:0 0.35rem}'
    '.host-chips{display:flex;gap:0.4rem;flex-wrap:wrap;margin:0.8rem 0}'
    '.host-chip{font-family:monospace;font-size:0.78rem;color:var(--text-3);border:1px solid var(--border);padding:0.15rem 0.6rem;text-decoration:none}'
    '.host-chip.on{color:var(--accent);border-color:var(--accent)}'
    '.bench-group{border-left:2px solid var(--accent);padding-left:0.6rem;margin:0.8rem 0}'
    '.bench-group-head{font-family:monospace;font-size:0.76rem;color:var(--text-3)}'
    '.bench-cmp{width:100%;border-collapse:collapse;font-family:monospace;font-size:0.76rem}'
    '.bench-cmp th,.bench-cmp td{border-bottom:1px solid var(--border);padding:0.3rem 0.4rem;text-align:right;vertical-align:top}'
    '.bench-cmp th:first-child,.bench-cmp td:first-child{text-align:left}'
    '.bench-cmp-wrap{overflow-x:auto}'
)


@router.get("/benchmark", response_class=HTMLResponse,
         dependencies=[Depends(requires(BENCHMARK_VIEW))])
async def benchmark_list_page(request: Request, host: str = ""):
    # Every node holds every node's finished runs (replication), so this list
    # works with any node down; the host chips filter, never fetch.
    runs = list_results("benchmark", limit=500, visitor_key=None)
    shown = [r for r in runs if not host or r.get("host_id") == host]
    body = (
        '<div class="finding-wrap">'
        '<h1 style="font-size:1.2rem;color:var(--text)">Benchmark runs</h1>'
        '<p style="color:var(--text-4);font-family:monospace;font-size:0.78rem">'
        'Full-pipeline overnight benchmarks (CR-061), from every OWL node — each run is '
        'labelled with the machine that measured it. Launch + cancel from '
        '<a href="/settings" style="color:var(--accent)">/settings</a>. Other nodes\' '
        'runs appear here once they finish (replicated every few minutes).</p>'
        f'{_host_chips(runs, host)}'
        '<button id="bench-compare-btn" disabled style="background:var(--border);color:var(--accent);'
        'border:1px solid var(--accent);padding:0.3rem 0.9rem;font-family:monospace;font-size:0.78rem;'
        'cursor:pointer">Compare ticked runs</button>'
        f'{_benchmark_rows_html(shown[:100])}'
        '</div>'
    )
    # S41 owner request: standard chrome (header back-link + footer) on the
    # benchmark pages — previously the chrome-less findings-style shell.
    return HTMLResponse(ui.render_page(request, "Benchmark runs", body,
                                       styles=_LIST_STYLES, tail=_BENCH_LIST_JS))


def _fmt(c: dict) -> str:
    if not c.get("n"):
        return '<span style="color:var(--text-5)">—</span>'
    mean, sd = c["mean"], c.get("sd")
    digits = 4 if abs(mean) < 1 else 2
    s = f"{mean:.{digits}f}"
    if sd is not None:
        s += f' <span style="color:var(--text-4)">± {sd:.{digits}f}</span>'
    return s + f' <span style="color:var(--text-5)">n={c["n"]}</span>'


@router.get("/benchmark/compare", response_class=HTMLResponse,
         dependencies=[Depends(requires(BENCHMARK_VIEW))])
async def benchmark_compare_page(request: Request, ids: str = ""):
    import benchmark_compare
    runs = []
    for bid in [x.strip() for x in ids.split(",") if x.strip()][:8]:
        m = load_result("benchmark", bid, visitor_key=None)
        if m:
            runs.append(m)
    if len(runs) < 2:
        return HTMLResponse('<p style="font-family:monospace">Pick two or more benchmark runs. '
                            '<a href="/benchmark">← all runs</a></p>', status_code=400)
    tb = benchmark_compare.table(runs)
    head = "".join(
        f'<th><a href="/benchmark/{html_lib.escape(c["bid"])}" style="color:var(--accent)">'
        f'{html_lib.escape(str(c["host"]))}</a><br><span style="color:var(--text-5);font-weight:normal">'
        f'{html_lib.escape(c.get("gpu") or "")}<br>{html_lib.escape(c["bid"])} · '
        f'{html_lib.escape((c.get("started_at") or "")[:10])}</span>'
        + (f'<br><span style="color:var(--warn);font-weight:normal">{c["missing"]} step result(s) '
           f'not yet on this node</span>' if c["missing"] else "")
        + '</th>' for c in tb["columns"])
    body_rows = "".join(
        f'<tr><td>{html_lib.escape(r["metric"])} <span style="color:var(--text-5)">'
        f'{html_lib.escape(r["unit"])}</span></td>'
        + "".join(f'<td>{_fmt(c)}</td>' for c in r["cells"]) + '</tr>'
        for r in tb["rows"])
    body = (
        '<div class="finding-wrap" style="max-width:1100px">'
        '<p style="font-family:monospace;font-size:0.78rem"><a href="/benchmark" '
        'style="color:var(--accent)">← all runs</a></p>'
        '<h1 style="font-size:1.2rem;color:var(--text)">Benchmark comparison</h1>'
        '<p style="color:var(--text-4);font-family:monospace;font-size:0.76rem;line-height:1.6">'
        'One column per run, each measured on its own machine and its own meters — '
        'values are never pooled across columns. Cells: mean ± sd over the run\'s repeats, '
        'with n. Each machine has its own idle floor, so ΔE compares the task\'s '
        'increment above idle on each machine, not wall energy. Device layer only.</p>'
        f'<div class="bench-cmp-wrap"><table class="bench-cmp"><tr><th>metric</th>{head}</tr>'
        f'{body_rows}</table></div></div>'
    )
    return HTMLResponse(ui.render_page(request, "Benchmark comparison", body,
                                       styles=_LIST_STYLES + 'body{max-width:1132px}'))


@router.get("/benchmark/{bid}", response_class=HTMLResponse,
         dependencies=[Depends(requires(BENCHMARK_VIEW))])
async def benchmark_detail_page(bid: str, request: Request):
    m = load_result("benchmark", bid, visitor_key=None)
    if not m:
        return HTMLResponse('<p style="font-family:monospace">Benchmark run not found. '
                            '<a href="/benchmark">← all runs</a></p>', status_code=404)
    status = m.get("status", "?")
    cfg_blob = m.get("config", {})
    h = hosts.result_host(m)
    host_label = h.get("label") or h.get("id")
    remote_run = h.get("id") != hosts.local_host()["id"]
    gpu_name = persist.bench_gpu(m)
    group_html = ""
    if m.get("group_id"):
        peers = [r for r in list_results("benchmark", limit=500, visitor_key=None)
                 if r.get("group_id") == m["group_id"]]
        ids = ",".join(r.get("benchmark_run_id") or r.get("job_id") for r in peers)
        group_html = (f' · parallel run {html_lib.escape(m["group_id"])} '
                      + (f'(<a href="/benchmark/compare?ids={html_lib.escape(ids)}" '
                         f'style="color:var(--accent)">compare {len(peers)} nodes →</a>)'
                         if len(peers) > 1 else '(other nodes\' runs not here yet)'))
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
                     f'data-host="{html_lib.escape(str(host_label)) if remote_run else ""}" '
                     f'data-result-id="{html_lib.escape(ref.get("job_id"))}">'
                     f'<div class="loading" style="color:var(--text-5);font-family:monospace;'
                     f'font-size:0.75rem">Loading…</div></div>')
        steps_html.append(head)
    body = (
        '<div class="bench-wrap">'
        f'<p style="font-family:monospace;font-size:0.78rem"><a href="/benchmark" style="color:var(--accent)">← all runs</a></p>'
        f'<h1 style="font-size:1.2rem;color:var(--text)">{_BENCH_STATUS_DOT.get(status,"⚪")} Benchmark {html_lib.escape(bid)}</h1>'
        f'<div style="color:var(--text-4);font-family:monospace;font-size:0.76rem;line-height:1.6">'
        f'measured on <b style="color:var(--accent)">{html_lib.escape(str(host_label))}</b>'
        f'{(" · " + html_lib.escape(gpu_name)) if gpu_name else ""}'
        f'{group_html}<br>'
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
        styles=('body{background:var(--bg);color:var(--text);max-width:932px;margin:0 auto;padding:0 1rem}'
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
