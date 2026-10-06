"""
peer.py — node-to-node job API plumbing (CR-085 autonomy Phase 4).

Every OWL node serves /peer/* (routes_peer.py). A caller (e.g. GoS1's "Other
machines" panels) submits a job to another node, which runs it on ITS OWN queue,
meters and scorer and stamps the result itself; the caller keeps a local job
stub that mirrors progress + the callee's live power, then imports the finished
envelope verbatim. Peer jobs never enter the caller's queue — so the same job
can run on both machines at the same time.

Auth: HMAC-SHA256 with a key derived from the shared OWL_AUTH_SECRET (purpose-
separated from session/magic-link tokens), over METHOD, PATH(+query), SHA-256 of
the body, a timestamp (±60 s) and a single-use nonce. Refused outright if the
secret is the ephemeral fallback. The routes are ALSO Lab-tier (LAN/tunnel only).
"""
import asyncio
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.request

import auth

HEADER = "X-OWL-Peer"
MAX_SKEW_S = 60
_SEEN: dict = {}          # nonce -> ts (single use within the skew window)


class PeerAuthError(Exception):
    pass


def _key() -> bytes:
    if auth.SECRET_IS_EPHEMERAL:
        raise PeerAuthError("OWL_AUTH_SECRET not set — peer API disabled on this node")
    return hmac.new(auth._SECRET, b"owl-peer-v1", hashlib.sha256).digest()


def _msg(method: str, path: str, body: bytes, ts: int, nonce: str) -> bytes:
    return f"{method.upper()}\n{path}\n{hashlib.sha256(body or b'').hexdigest()}\n{ts}\n{nonce}".encode()


def sign(method: str, path: str, body: bytes = b"") -> str:
    ts, nonce = int(time.time()), secrets.token_hex(12)
    sig = hmac.new(_key(), _msg(method, path, body, ts, nonce), hashlib.sha256).hexdigest()
    return f"{ts}.{nonce}.{sig}"


def verify(method: str, path: str, body: bytes, header: str) -> bool:
    try:
        ts_s, nonce, sig = (header or "").split(".", 2)
        ts = int(ts_s)
    except ValueError:
        return False
    now = time.time()
    if abs(now - ts) > MAX_SKEW_S or nonce in _SEEN:
        return False
    try:
        want = hmac.new(_key(), _msg(method, path, body, ts, nonce), hashlib.sha256).hexdigest()
    except PeerAuthError:
        return False
    if not hmac.compare_digest(want, sig):
        return False
    _SEEN[nonce] = ts
    for n, t in list(_SEEN.items()):
        if now - t > 2 * MAX_SKEW_S:
            _SEEN.pop(n, None)
    return True


# --- who may call (receiving side) -------------------------------------------

def _url_hosts() -> set:
    """Addresses of every registered peer's `url` (names resolved). The SAME
    entry that says how to reach a peer says who that peer is when it calls
    back — so moving a node to another network (Tailscale, VPN, public host)
    is one edit: its `url` in compute_hosts."""
    import ipaddress, socket
    from urllib.parse import urlparse
    import hosts
    out = set()
    for h in hosts.all_remote().values():
        name = urlparse(h.get("url") or "").hostname
        if not name:
            continue
        try:
            out.add(str(ipaddress.ip_address(name)))
        except ValueError:
            try:
                out.update(i[4][0] for i in socket.getaddrinfo(name, None))
            except OSError:
                pass
    return out


_SRC_CACHE = {"ts": 0, "ips": set()}


def source_allowed(ip: str) -> bool:
    """LAN / loopback (incl. an SSH tunnel) always; otherwise only a
    registered peer's address, or a CIDR in settings `peer_source_networks`."""
    import ipaddress
    import settings as cfg
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_loopback or addr.is_private:
        return True
    if time.time() - _SRC_CACHE["ts"] > 60:
        _SRC_CACHE.update(ts=time.time(), ips=_url_hosts())
    if ip in _SRC_CACHE["ips"]:
        return True
    for net in cfg.load().get("peer_source_networks") or []:
        try:
            if addr in ipaddress.ip_network(net, strict=False):
                return True
        except ValueError:
            continue
    return False


# --- client ---------------------------------------------------------------------

def call(host: dict, method: str, path: str, payload=None, timeout: float = 15):
    body = json.dumps(payload).encode() if payload is not None else b""
    req = urllib.request.Request(host["url"].rstrip("/") + path, method=method,
                                 data=body if method != "GET" else None,
                                 headers={"Content-Type": "application/json",
                                          HEADER: sign(method, path, body)})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


_INFO: dict = {}          # host id -> (ts, info | None)


def info(host: dict, max_age: float = 20) -> dict | None:
    """The peer's /peer/info, cached; None = offline/unreachable."""
    hid = host.get("id")
    ts, val = _INFO.get(hid, (0, None))
    if time.time() - ts < max_age:
        return val
    try:
        val = call(host, "GET", "/peer/info", timeout=3)
    except Exception:
        val = None
    _INFO[hid] = (time.time(), val)
    return val


def online(host: dict) -> bool:
    return info(host) is not None


# --- caller-side job stub -------------------------------------------------------

_MIRROR = ("status", "stage", "queue_position", "partial_response", "images_done",
           "vmaf_total", "vmaf_done", "input_duration_s", "progress_pct", "encode_speed",
           "eta_s", "full_prompt", "error", "cooldown_waited_s", "current_model_idx")


async def follow(host: dict, job_id: str, result_type: str, jobs: dict) -> None:
    """Mirror a peer job into this node's jobs dict until it finishes, then import
    the callee's envelope verbatim (persist.import_result)."""
    import persist
    fails = 0
    loop = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(2)
        try:
            st = await loop.run_in_executor(None, lambda: call(host, "GET", f"/peer/jobs/{job_id}", timeout=10))
            fails = 0
        except Exception as e:
            fails += 1
            if fails >= 15:                       # ~30 s of silence
                jobs[job_id].update({"status": "error", "stage": "error",
                                     "error": f"{host.get('label')} unreachable: {e!r}"[:300]})
                return
            continue
        stub = jobs.setdefault(job_id, {})
        for k in _MIRROR:
            if k in st:
                stub[k] = st[k]
        stub["peer_watts"] = st.get("watts")
        if st.get("status") == "error":
            return
        if st.get("status") == "done" or (st.get("result") and st.get("stage") == "done"):
            try:
                env = await loop.run_in_executor(
                    None, lambda: call(host, "GET", f"/peer/results/{result_type}/{job_id}", timeout=60))
                persist.import_result(result_type, env)
                stub.update({"status": "done", "stage": "done", "result": env})
            except Exception as e:
                stub.update({"status": "error", "stage": "error",
                             "error": f"result import failed: {e!r}"[:300]})
            return


def submit(host: dict, job_type: str, params: dict, result_type: str, jobs: dict) -> dict:
    """Submit to the peer, create the local stub, start following. Returns the
    {job_id, queue_position} the caller's page polls with."""
    r = call(host, "POST", "/peer/jobs", {"type": job_type, "params": params}, timeout=20)
    jid = r["job_id"]
    jobs[jid] = {"status": "queued", "stage": "queued", "queue_position": r.get("queue_position"),
                 "peer": host.get("id"), "peer_host": host.get("label")}
    asyncio.get_event_loop().create_task(follow(host, jid, result_type, jobs))
    return {"job_id": jid, "queue_position": r.get("queue_position"), "peer": host.get("label")}
