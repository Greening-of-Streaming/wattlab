"""
bench_cluster.py — which OWL nodes are running a benchmark (2026-10-10).

Every node answers `benchmark` in its /peer/info (queue_control.benchmark_state).
A light poller keeps each peer's info fresh in peer's cache, so pages and the
enqueue chokepoint read the cluster state without ever waiting on a peer.

Policy (owner 2026-10-10): a node running (or about to run) a benchmark refuses
new non-Lab runs and points visitors at a free node; when every node is busy the
whole lab is effectively in a Lab session. A node with no benchmark stays fully
open. Lab tier is never refused (it can queue behind a benchmark on purpose).
"""
import asyncio

import hosts
import peer
import queue_control

POLL_S = 30          # GoS2 idles at ~1.3 W: keep the poll light


def nodes(request=None) -> list:
    """[{id, label, self, online, benchmark, url, locked}] — this node first.
    `online` None = no answer cached yet (just started). `url` follows the
    machine switch's rules (routes_peer.node_link) when a request is given."""
    me = hosts.local_host()
    out = [{"id": me["id"], "label": me.get("label", me["id"]), "self": True,
            "online": True, "benchmark": queue_control.benchmark_state(),
            "url": None, "locked": False}]
    for hid, h in hosts.remote_hosts().items():
        if hosts.driver(h) != "peer":
            continue
        h = {**h, "id": hid}
        inf = peer.cached(h)
        url, locked = (None, False)
        if request is not None:
            import routes_peer
            url, locked = routes_peer.node_link(request, h)
            url = None if locked else url
        out.append({"id": hid, "label": h.get("label", hid), "self": False,
                    "online": None if inf is peer.UNKNOWN else inf is not None,
                    "benchmark": (inf or {}).get("benchmark") if inf is not peer.UNKNOWN else None,
                    "url": url, "locked": locked})
    return out


def busy_message(request=None) -> str:
    """Why this node refuses a run while it benchmarks, naming a free node."""
    ns = nodes(request)
    me = ns[0]
    free = [n for n in ns[1:] if n["online"] and not n["benchmark"]]
    if not free:
        others = " and ".join(n["label"] for n in ns[1:] if n["online"])
        if others:
            return (f"Every OWL machine ({me['label']} and {others}) is running a benchmark, "
                    "so new runs are paused until one finishes. Browsing (guided tour, "
                    "findings, past results) stays open.")
        return (f"{me['label']} is running a benchmark, so new runs are paused until it "
                "finishes. Browsing stays open.")
    tips = []
    for n in free:
        if n["url"]:
            tips.append(f"{n['label']} is free: {n['url']}")
        elif n["locked"]:
            tips.append(f"{n['label']} is free (members)")
    return (f"{me['label']} is running a benchmark, so new runs are paused here. "
            + (" · ".join(tips) + "." if tips else "Another OWL machine is free."))


async def poller():
    """Refresh every peer's /peer/info into peer's cache (in a worker thread —
    an offline peer costs a 3 s timeout there, never on a page)."""
    loop = asyncio.get_event_loop()
    while True:
        for hid, h in hosts.remote_hosts().items():
            if hosts.driver(h) == "peer":
                try:
                    await loop.run_in_executor(
                        None, lambda h=h, hid=hid: peer.info({**h, "id": hid}, max_age=POLL_S - 5))
                except Exception:
                    pass
        await asyncio.sleep(POLL_S)
