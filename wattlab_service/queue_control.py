"""
Queue control — single chokepoint for OWL's job queue.

Holds the FIFO queue, the external pause flag, and the worker loop. This is
the spine that CR-001 (per-tier rate limits) and CR-001b (demo lock) plug
into — both will live inside enqueue() at the single chokepoint.

State and shared references (the global `jobs` dict, the per-job
`/tmp/gos-measure.lock` path) are injected via start() at app startup, so
this module imports nothing from main.py — no circular deps.
"""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from fastapi import Request

# --- Public state -----------------------------------------------------------
pending_queue: list = []        # list of {"job_id", "type", "label", "coro_fn",
                                #          "visitor_key": Optional[str]}
queue_event = asyncio.Event()
current_job_id = None           # job currently executing, or None
current_visitor_key: Optional[str] = None  # visitor of the running job, for cap accounting
MAX_QUEUE_DEPTH = 8             # total queued + running; 429 beyond this


def visitor_key(request) -> Optional[str]:
    """Identity for per-tier cap accounting.

    - Lab tier      → None (uncapped).
    - Member tier   → 'm:<lowercased email>'.
    - Anonymous     → 'a:<pseudonymised-IP token>' (truncated + keyed-hashed,
                      never the raw address — analytics.hash_ip); 'a:' if no IP.

    queue_control depending on audience+auth is fine: both sit at the
    spine layer, neither imports queue_control. Kept at the bottom of
    enqueue() so the queue tests that don't pass a request keep working.
    """
    if request is None:
        return None
    try:
        import audience as _aud
        t = _aud.tier(request)
    except (AttributeError, TypeError):
        # Stub / non-Request object passed (legacy tests). Treat as
        # uncapped — the cap is a soft layer over the depth limit, so
        # silently opting out is safer than blowing up the request.
        return None
    if t == _aud.Tier.Lab:
        return None
    if t == _aud.Tier.Member:
        try:
            import auth as _auth
            email = _auth.member_email_from_request(request) or ""
        except Exception:
            email = ""
        return f"m:{email.strip().lower()}"
    # Anonymous — pseudonymise the IP: a raw address must never reach disk
    # (GDPR). analytics.hash_ip truncates to /24 (v4) / /48 (v6) then keyed-
    # hashes, giving a stable-per-subnet token that still scopes a visitor to
    # their own results (CR-026) without being reversible to the address.
    ip = (request.headers.get("x-real-ip") if request.headers else None) or (
        request.client.host if request.client else "")
    import analytics as _an
    return f"a:{_an.hash_ip(ip)}"


def _visitor_cap(visitor_key: Optional[str]) -> Optional[int]:
    """Look up the concurrent-job cap for a visitor key.

    None (Lab) → uncapped. Otherwise returns the int cap from settings.json
    (queue_anonymous_cap / queue_member_cap). Read live so a /settings save
    takes effect without a restart.
    """
    if visitor_key is None:
        return None
    import settings as _cfg
    s = _cfg.load()
    if visitor_key.startswith("m:"):
        return int(s.get("queue_member_cap", 4))
    return int(s.get("queue_anonymous_cap", 1))


def _visitor_in_flight(visitor_key: Optional[str]) -> int:
    """Count of jobs (queued + running) that belong to this visitor."""
    if visitor_key is None:
        return 0
    n = sum(1 for e in pending_queue if e.get("visitor_key") == visitor_key)
    if current_job_id is not None and current_visitor_key == visitor_key:
        n += 1
    return n

# External pause: when this file exists, the worker waits between jobs
# rather than picking up the next one. In-flight jobs are unaffected.
# Created/removed by external tools (e.g. the local-model router at
# /home/gos/claude-local-router which holds the GPU during its session).
# See OWL_INTEGRATION_PROPOSAL.md in that repo for the full rationale.
PAUSE_FLAG = "/tmp/owl-paused"

# --- Injected by start() ----------------------------------------------------
_jobs: dict | None = None
_lock_file: Path | None = None


def start(jobs: dict, lock_file: Path) -> asyncio.Task:
    """Wire shared state and spawn the worker.

    Called from main.py's @app.on_event("startup"). The `jobs` dict is the
    in-memory job-state map; `lock_file` is video.py's `/tmp/gos-measure.lock`
    path. We hold references so this module doesn't import from main, which
    would create a cycle (main imports queue_control).
    """
    global _jobs, _lock_file
    _jobs = jobs
    _lock_file = lock_file
    return asyncio.create_task(_worker())


def enqueue(job_id: str, job_type: str, label: str, coro_fn,
            *, request: "Request | None" = None, page: "str | None" = None):
    """Add a job to the FIFO queue.

    Returns the 1-based queue position, or None if the queue is full
    or the caller is over their per-tier concurrent-job cap (caller
    should respond 429).

    `request` is used for per-tier cap accounting (CR-001 part D):
    Anonymous visitors are capped to settings.json's queue_anonymous_cap
    (default 1, IP-keyed); Members to queue_member_cap (default 4,
    email-keyed); Lab is uncapped. Tests pass request=None to opt out.
    """
    vk = visitor_key(request)
    cap = _visitor_cap(vk)
    if cap is not None and _visitor_in_flight(vk) >= cap:
        return None
    total = len(pending_queue) + (1 if current_job_id else 0)
    if total >= MAX_QUEUE_DEPTH:
        return None
    position = len(pending_queue) + 1
    _jobs[job_id] = {
        "stage": "queued", "queue_position": position,
        "type": job_type, "label": label,
        "result": None, "error": None,
        # Attended Lab runs (vk is None) may be offered the idle-wait timeout
        # dialog by power.cooldown_between_runs. Members/Anonymous, batch and
        # benchmark runs are never interactive (the latter override this False).
        "interactive_eligible": vk is None,
        # Page to reconnect to from /queue-status ↩ Resume. Defaults (None) to
        # /<job_type>; sub-pages like /llm/compare & /rag/compare pass it
        # explicitly so Resume lands on the page the job was started from.
        "resume_page": page,
    }
    pending_queue.append({
        "job_id": job_id, "type": job_type,
        "label": label, "coro_fn": coro_fn,
        "visitor_key": vk,
    })
    queue_event.set()
    return position


def depth() -> int:
    """Total jobs in flight (queued + running)."""
    return len(pending_queue) + (1 if current_job_id else 0)


def cancel_pending(job_id: str) -> bool:
    """Remove a not-yet-started job from the queue (CR-061 benchmark cancel).

    Returns True if `job_id` was queued and removed. The CURRENTLY RUNNING job
    (`current_job_id`) is NOT affected — that case is handled cooperatively by
    the job's own coroutine checking a cancel flag. Re-numbers the remaining
    queue positions, mirroring the worker's renumber at _worker()."""
    for i, e in enumerate(pending_queue):
        if e["job_id"] == job_id:
            pending_queue.pop(i)
            for j, ee in enumerate(pending_queue):
                if _jobs and ee["job_id"] in _jobs:
                    _jobs[ee["job_id"]]["queue_position"] = j + 1
            return True
    return False


def empty_pending() -> list[str]:
    """Drain every not-yet-started job (CR-064 — the /queue-status "Empty
    queue" button). The RUNNING job is untouched (that's cancel-current's
    job, workload-permitting). Each drained job is marked cancelled so its
    page poll concludes instead of spinning. Returns the drained ids."""
    drained = []
    while pending_queue:
        e = pending_queue.pop()
        drained.append(e["job_id"])
        if _jobs and e["job_id"] in _jobs:
            _jobs[e["job_id"]].update({
                "status": "error", "stage": "error",
                "error": "Cancelled — queue emptied from /queue-status",
            })
    return drained


def paused() -> bool:
    """True if the external pause flag file exists."""
    return Path(PAUSE_FLAG).exists()


def set_paused(on: bool) -> bool:
    """Create/remove PAUSE_FLAG (the /queue-status Lab toggle). Same flag the
    external tools use (claude-local-router GPU sessions), so the UI and the
    tools see one state. In-flight jobs are never touched — the worker just
    stops picking up new ones. Returns the resulting paused state."""
    p = Path(PAUSE_FLAG)
    try:
        if on:
            p.write_text("paused via /queue-status toggle\n")
        else:
            p.unlink(missing_ok=True)
    except Exception:
        pass
    return paused()


def snapshot() -> dict:
    """Snapshot of queue state for the /queue JSON endpoint."""
    running = None
    if current_job_id and _jobs and current_job_id in _jobs:
        j = _jobs[current_job_id]
        running = {
            "job_id": current_job_id,
            "stage": j.get("stage"),
            "type": j.get("type"),
            "label": j.get("label"),
            "resume_page": j.get("resume_page"),
        }
    pending_info = [
        {"job_id": e["job_id"], "type": e["type"], "label": e["label"], "position": i + 1,
         "resume_page": (_jobs.get(e["job_id"]) or {}).get("resume_page")}
        for i, e in enumerate(pending_queue)
    ]
    return {
        "depth": depth(),
        "running": running,
        "pending": pending_info,
        "paused": paused(),
    }


async def _worker():
    """Single sequential worker. Pops from pending_queue, dispatches the
    coroutine, cleans up on exception. Honours PAUSE_FLAG between jobs."""
    global current_job_id, current_visitor_key
    while True:
        await queue_event.wait()
        queue_event.clear()
        while pending_queue:
            # External pause: tools touch PAUSE_FLAG to block the worker
            # between jobs without killing it. In-flight jobs are unaffected.
            while Path(PAUSE_FLAG).exists() and pending_queue:
                await asyncio.sleep(1)
            if not pending_queue:
                break
            entry = pending_queue.pop(0)
            job_id = entry["job_id"]
            current_job_id = job_id
            current_visitor_key = entry.get("visitor_key")
            # Update queue positions for remaining jobs
            for i, e in enumerate(pending_queue):
                if e["job_id"] in _jobs:
                    _jobs[e["job_id"]]["queue_position"] = i + 1
            try:
                await entry["coro_fn"]()
            except Exception as ex:
                _jobs[job_id] = {**_jobs.get(job_id, {}),
                                 "stage": "error", "error": str(ex)}
                _lock_file.unlink(missing_ok=True)
            finally:
                current_job_id = None
                current_visitor_key = None
