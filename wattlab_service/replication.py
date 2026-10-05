"""
replication.py — results flow both ways between OWL nodes (CR-085 autonomy Phase 5).

Every node periodically PULLS from each online peer (driver "peer"): the peer's
own results (host == that peer) saved since the last pull, imported verbatim
(persist.import_result — never re-stamped). Append-only: nothing is deleted on
either side. A node can also pull the member allowlist from the one host marked
`members_source: true` (one writer — design §4), so magic-link sign-in works on
either node. Progress is kept per peer in results/_replication/<peer>.json.

Pull, not push: a node that was offline simply catches up when it returns; no
node ever needs the other to be up to keep working.
"""
import asyncio
import json
import time

import hosts
import paths
import peer
import persist
import settings as cfg

TYPES = ("video", "llm", "image")


def _state_file(hid: str):
    d = persist.RESULTS_DIR / "_replication"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{hid}.json"


def _load(hid: str) -> dict:
    try:
        return json.loads(_state_file(hid).read_text())
    except Exception:
        return {}


def pull_once(hid: str, h: dict) -> dict:
    """One pass against one peer. Returns {type: n_imported, ...} (+ members)."""
    h = {**h, "id": hid}
    if not peer.online(h):
        return {"offline": True}
    st = _load(hid)
    out = {}
    for t in TYPES:
        since = st.get(t, "")
        q = f"/peer/results/{t}?since={since}" if since else f"/peer/results/{t}"
        idx = peer.call(h, "GET", q, timeout=30)
        n = 0
        for row in idx.get("results", []):
            jid = row.get("job_id")
            if not jid:
                continue
            if list((persist.RESULTS_DIR / t).glob(f"*_{jid}.json")):
                st[t] = max(st.get(t, ""), str(row.get("saved_at") or ""))
                continue
            env = peer.call(h, "GET", f"/peer/results/{t}/{jid}", timeout=60)
            persist.import_result(t, env)
            st[t] = max(st.get(t, ""), str(env.get("saved_at") or ""))
            n += 1
        out[t] = n
    if h.get("members_source"):
        try:
            m = peer.call(h, "GET", "/peer/members", timeout=15)
            if isinstance(m.get("members"), list):
                import auth
                f = auth._members_file_path()
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps(m["members"], indent=2))
                out["members"] = auth.reload_members()
        except Exception as e:
            out["members_error"] = repr(e)[:200]
    st["last_pull"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _state_file(hid).write_text(json.dumps(st, indent=2))
    return out


def pull_all() -> dict:
    return {hid: pull_once(hid, h) for hid, h in hosts.remote_hosts().items()
            if hosts.driver(h) == "peer"}


async def poller():
    """Background loop (main.startup, setting run_replication)."""
    loop = asyncio.get_event_loop()
    await asyncio.sleep(30)
    while True:
        try:
            res = await loop.run_in_executor(None, pull_all)
            if any(isinstance(v, dict) and sum(x for x in v.values() if isinstance(x, int)) for v in res.values()):
                print(f"replication: {res}", flush=True)
        except Exception as e:
            print(f"WARN replication: {e!r}", flush=True)
        await asyncio.sleep(int(cfg.load().get("replication_interval_s", 600)))
