"""
routes_peer.py — the node-to-node job API (CR-085 autonomy Phase 4).

Served by every OWL node. Every call needs an HMAC signature (peer.verify)
AND a caller address that is a registered peer (peer.source_allowed). Jobs run on THIS node's own queue, meters and
scorer, and are stamped by this node's persist.save_result; the caller mirrors
progress and imports the envelope verbatim (peer.follow / persist.import_result).
Feature modules never import main.
"""
import glob
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

import audience
import benchmark
import gpu
import hosts
import peer
import persist
import queue_control
import settings as cfg
from capabilities import PEER_API, PUBLIC_PAGE, NODE_LAN_LINKS, NODE_GATEWAY_VIEW, can, requires
from runtime import jobs, job_status as _job_status

router = APIRouter()


async def require_peer(request: Request):
    ip = audience.client_ip(request)
    if not peer.source_allowed(ip):
        raise HTTPException(status_code=403, detail="not a registered peer address")
    body = await request.body()
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    if not peer.verify(request.method, path, body, request.headers.get(peer.HEADER, "")):
        raise HTTPException(status_code=403, detail="peer signature invalid")


_DEPS = [Depends(requires(PEER_API)), Depends(require_peer)]


def _engines() -> dict:
    """What this node can encode on: CPU always; hardware when its backend has it."""
    out = {"cpu": {"label": "CPU (software)", "codecs": ["h264", "h265", "av1"]}}
    if gpu.BACKEND.available:
        out["gpu"] = {"label": {"apple": "Apple media engine (VBR)", "nvidia": "NVENC",
                                "amd": "VAAPI"}.get(gpu.BACKEND.vendor, "GPU"),
                      "codecs": [c for c in ("h264", "h265", "av1") if gpu.supports(c)]}
    return out


@router.get("/peer/info", dependencies=_DEPS)
async def peer_info():
    import image_gen, llm, version
    s = cfg.load()
    return {"host": hosts.identity(hosts.local_host()), "gpu": gpu.stamp(),
            "engines": _engines(),
            "image_models": list(image_gen.IMAGE_MODELS.keys()),
            "llm_models": list(llm.MODELS.keys()),
            "mlx_models": sorted((s.get("local_mlx_models") or {}).keys()),
            "queue_depth": queue_control.depth(),
            "benchmark": queue_control.benchmark_state(),
            "rig": bool(s.get("run_rig_poller", True)),
            "version": version.version_dict()}


_PRESET = {("both", "h264"): "both", ("both", "h265"): "h265_both", ("both", "av1"): "av1_both",
           ("cpu", "h264"): "cpu", ("cpu", "h265"): "h265_cpu", ("cpu", "av1"): "av1_cpu",
           ("gpu", "h264"): "gpu", ("gpu", "h265"): "h265_gpu", ("gpu", "av1"): "av1_gpu"}


@router.post("/peer/jobs", dependencies=_DEPS)
async def peer_submit(request: Request):
    req = json.loads(await request.body() or b"{}")
    jtype, p = req.get("type"), req.get("params") or {}
    job_id = f"{hosts.local_host()['id']}-{uuid.uuid4().hex[:8]}"
    label = f"Peer job ({jtype})"

    if jtype == "video":
        import routes_video
        from sources import PRELOADED
        codec, engine = p.get("codec", "h264"), p.get("engine", "both")
        preset = _PRESET.get((engine, codec))
        src = PRELOADED.get(p.get("source_key"))
        if preset is None or src is None or not src["path"].exists():
            return JSONResponse({"error": "unknown preset/source on this node"}, status_code=400)
        if engine != "cpu" and not gpu.supports(codec):
            return JSONResponse({"error": f"no hardware {codec} encoder on this node"}, status_code=400)
        vmaf = p.get("compute_vmaf")
        async def coro():
            await routes_video.run_job(job_id, src["path"], preset, False,
                                       source_key=p.get("source_key"),
                                       vmaf_override=None if vmaf is None else bool(vmaf))
    elif jtype == "llm":
        import routes_llm
        async def coro():
            await routes_llm.run_llm_job(job_id, p["model_key"], p.get("task_key", "T2"),
                                         1, False, None, p.get("device", "gpu"))
    elif jtype == "llm_mlx":
        import remote_ai
        async def coro():
            try:
                import video
                jobs[job_id].update({"status": "running", "stage": "baseline"})
                stopped = video.focus_mode_enter()
                try:
                    r = await remote_ai.run_local_mlx(p["model_key"], p.get("task_key", "T2"), job_id, jobs)
                finally:
                    video.focus_mode_exit(stopped)
                persist.save_result("llm", job_id, r)
                jobs[job_id].update({"status": "done", "stage": "done", "result": r})
            except Exception as e:
                jobs[job_id] = {"status": "error", "stage": "error", "error": str(e)}
    elif jtype in ("image_session", "image"):
        import remote_ai, image_gen, curated
        async def coro():
            try:
                jobs[job_id].update({"status": "running", "stage": "starting"})
                if jtype == "image_session":
                    prompt = (p.get("prompt") or "").strip()
                    r = await remote_ai.run_image_session(
                        "local", p.get("model_key", "sd-turbo"), jobs, job_id,
                        per_prompt=int(p.get("per_prompt", 5)), settle_s=int(p.get("settle_s", 30)),
                        prompts=[prompt] if prompt else None, target_s=float(p.get("target_s", 30)))
                else:
                    r = await image_gen.run_image_measurement(
                        (p.get("prompt") or curated.CANONICAL_IMAGE_PROMPT), job_id, jobs,
                        device=p.get("device", "gpu"), model_key=p.get("model_key", "sd-turbo"))
                persist.save_result("image", job_id, r)
                jobs[job_id].update({"status": "done", "stage": "done", "result": r})
            except Exception as e:
                jobs[job_id].update({"status": "error", "stage": "error", "error": str(e)})
    elif jtype == "benchmark":
        # Multi-node benchmark (2026-10-09): the launcher's plan on THIS node's
        # queue + meters. Not followed by the caller — an overnight run outlives
        # any poll; the finished run file comes back by replication.
        import routes_benchmark
        position = routes_benchmark.launch_local(job_id, p.get("config"), p.get("group_id"))
        if position is None:
            return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
        return {"job_id": job_id, "queue_position": position}
    else:
        return JSONResponse({"error": f"unknown job type {jtype!r}"}, status_code=400)

    position = queue_control.enqueue(job_id, jtype.split("_")[0], label, coro, request=None)
    if position is None:
        return JSONResponse({"error": "Queue full — try again later."}, status_code=429)
    return {"job_id": job_id, "queue_position": position}


@router.get("/peer/jobs/{job_id}", dependencies=_DEPS)
async def peer_status(job_id: str):
    return _job_status(job_id)


@router.post("/peer/jobs/{job_id}/cancel", dependencies=_DEPS)
async def peer_cancel(job_id: str):
    if (jobs.get(job_id) or {}).get("type") == "benchmark":
        import routes_benchmark
        st = routes_benchmark.cancel_local(job_id)
        return {"cancelled": st != "not_found", "state": st}
    return {"cancelled": bool(queue_control.cancel_pending(job_id))}


# Result types a node exports to its peers (replication.TYPES pulls these).
EXPORT_TYPES = ("video", "llm", "image", "decode", "benchmark")


def _result_path(job_type: str, job_id: str):
    if job_type not in EXPORT_TYPES or "/" in job_id or ".." in job_id:
        return None
    m = sorted(glob.glob(str(persist.RESULTS_DIR / job_type / f"*_{job_id}.json")))
    return Path(m[-1]) if m else None


@router.get("/peer/results/{job_type}/{job_id}", dependencies=_DEPS)
async def peer_result(job_type: str, job_id: str):
    p = _result_path(job_type, job_id)
    if p is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    d = json.loads(p.read_text())
    if not (d.get("host") or {}).get("id"):
        # Pre-envelope-v2 results carry no host: by construction they are this
        # node's (GoS1). Make the read-time default explicit for the importer.
        d["host"] = hosts.result_host(d)
        d["host_inferred"] = True
    return d


@router.get("/peer/results/{job_type}", dependencies=_DEPS)
async def peer_result_index(job_type: str, since: str = ""):
    """Replication index (Phase 5): envelopes THIS node produced (host = this
    node), saved after `since` (ISO), oldest first."""
    if job_type not in EXPORT_TYPES:
        return JSONResponse({"error": "bad type"}, status_code=400)
    me = hosts.local_host()["id"]
    bench = job_type == "benchmark"
    out = []
    for f in sorted((persist.RESULTS_DIR / job_type).glob("*.json")):
        # Benchmark files are named by their START date and can finish days
        # later — no filename pre-filter for them (there are few).
        if since and not bench and f.name[:10] < since[:10]:
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if hosts.result_host(d).get("id") != me or (since and str(d.get("saved_at", "")) <= since):
            continue
        # A run file changes until the run ends; replication is append-only.
        if bench and d.get("status") not in benchmark.FINAL_STATUSES:
            continue
        out.append({"job_id": d.get("job_id"), "saved_at": d.get("saved_at")})
    return {"host": me, "type": job_type, "results": out}


@router.get("/peer/members", dependencies=_DEPS)
async def peer_members():
    """Member allowlist for replication to other nodes (one writer — the node
    whose peers mark it members_source)."""
    import auth
    return {"host": hosts.local_host()["id"], "members": auth.list_members()}


@router.post("/peer/replicate-now", dependencies=_DEPS)
async def peer_replicate_now():
    """Trigger an immediate pull from this node's peers (drills, tests)."""
    import asyncio, replication
    return await asyncio.get_event_loop().run_in_executor(None, replication.pull_all)


# --- /decode remote control (CR-085, owner 2026-10-07: one rig owner) ---------
# A node without the rig forwards every /decode request here; the owner runs it
# through its OWN /decode handlers in-process, so its queue stays the single
# reservation authority for the rig. `_owl_tier` (inside the signed query)
# carries the visitor's tier from the caller: lab → loopback identity, anything
# else → a public-IP identity, so pages render exactly the controls that
# visitor may use. Allowlisted to the /decode prefix.

async def _dispatch(request: Request, target_prefix: str, path: str):
    """Run a forwarded request through THIS node's own app in-process, with
    the visitor identity the calling node verified (signed query: _owl_tier,
    _owl_member) held in audience.PEER_VISITOR for the duration. Shared by
    /peer/decode (rig remote control) and /peer/view (member gateway)."""
    import httpx
    import audience
    from urllib.parse import parse_qsl, urlencode
    from fastapi.responses import Response
    q = parse_qsl(request.url.query, keep_blank_values=True)
    meta = {k: v for k, v in q if k in ("_owl_tier", "_owl_member")}
    q = [(k, v) for k, v in q if k not in meta]
    tier = meta.get("_owl_tier", "anonymous")
    tier = tier if tier in ("lab", "member", "anonymous") else "anonymous"
    target = target_prefix + (f"/{path}" if path else "") + (f"?{urlencode(q)}" if q else "")
    # x-real-ip is public on purpose: without the ContextVar the request is anonymous.
    headers = {"x-real-ip": "1.1.1.1"}
    for h in ("content-type", "accept"):
        if request.headers.get(h):
            headers[h] = request.headers[h]
    # via_gateway: the visitor arrived on a PUBLIC name (the member gateway), so
    # this node's links (machine switch) must stay on public names too.
    token = audience.PEER_VISITOR.set({"tier": tier, "email": meta.get("_owl_member"),
                                       "via_gateway": target_prefix == ""})
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=request.app),
                                     base_url="http://owner") as c:
            r = await c.request(request.method, target or "/", content=await request.body(),
                                headers=headers, timeout=120)
    finally:
        audience.PEER_VISITOR.reset(token)
    out_headers = {k: v for k, v in r.headers.items()
                   if k.lower() in ("content-disposition", "cache-control", "location")}
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type"), headers=out_headers)


@router.api_route("/peer/decode/{path:path}", methods=["GET", "POST"], dependencies=_DEPS)
async def peer_decode(path: str, request: Request):
    try:
        import rig
        rig.touch_activity("peer /decode")
    except Exception:
        pass
    return await _dispatch(request, "/decode", path)


@router.api_route("/peer/view/{path:path}", methods=["GET", "POST"], dependencies=_DEPS)
async def peer_view(path: str, request: Request):
    """Member gateway (owner 2026-10-07): any page or API of this node, for a
    visitor the forwarding node has verified. Never the peer API itself."""
    from fastapi.responses import JSONResponse as _J
    p = "/" + path.lstrip("/")
    if p == "/peer" or p.startswith("/peer/") or ".." in p:
        return _J({"error": "not available through the gateway"}, status_code=404)
    return await _dispatch(request, "", path)


# --- machine switch (CR-085, owner 2026-10-07) --------------------------------
# Derived entirely from the registry: this node + every peer (driver "peer")
# that has an address the visitor can reach. Lab visitors get the peer's `url`;
# everyone else only peers declaring a `public_url` (none until a node has a
# public front door). Online state comes from the cached peer.info, fetched in
# a worker thread so the page that asks never waits on an offline peer.

def _arrived_on_public_name(request: Request) -> bool:
    import audience, ipaddress
    pv = audience.PEER_VISITOR.get()
    if pv is not None:
        return bool(pv.get("via_gateway"))
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(":")[0].lower()
    if not host or host in ("localhost", "testserver") or host.endswith(".local"):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        return True


def node_link(request: Request, h: dict):
    """(url, locked) for a peer node as this visitor may see it: keep visitors
    on the kind of address they arrived on (owner 2026-10-07: a Lab visitor
    who came in by the public name was sent to raw LAN addresses) — public
    name, or the member gateway → the peer's public_url; LAN/IP → its url.
    public_tier "member": visitors below it see the node locked, no address."""
    lan = can(audience.tier(request), NODE_LAN_LINKS)
    if lan and not _arrived_on_public_name(request):
        url = h.get("url")
    else:
        url = h.get("public_url") or (h.get("url") if lan else None)
    locked = (not lan and h.get("public_tier") == "member"
              and not can(audience.tier(request), NODE_GATEWAY_VIEW))
    return (url.rstrip("/") + "/" if url else None), locked


@router.get("/nodes.json", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def nodes_json(request: Request):
    import asyncio
    me = hosts.local_host()
    out = [{"id": me["id"], "label": me.get("label", me["id"]), "chip": me.get("chip", ""),
            "self": True, "online": True, "url": None}]
    loop = asyncio.get_event_loop()
    for hid, h in hosts.remote_hosts().items():
        if hosts.driver(h) != "peer":
            continue
        url, locked = node_link(request, h)
        if not url:
            continue
        inf = await loop.run_in_executor(None, lambda h=h, hid=hid: peer.info({**h, "id": hid}))
        out.append({"id": hid, "label": h.get("label", hid), "chip": h.get("chip", ""),
                    "self": False, "online": inf is not None, "locked": locked,
                    "url": None if locked else url,
                    "benchmark": (inf or {}).get("benchmark")})
    return {"nodes": out}
