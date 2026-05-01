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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request

# --- Public state -----------------------------------------------------------
pending_queue: list = []        # list of {"job_id", "type", "label", "coro_fn"}
queue_event = asyncio.Event()
current_job_id = None           # job currently executing, or None
MAX_QUEUE_DEPTH = 8             # total queued + running; 429 beyond this

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
            *, request: "Request | None" = None):
    """Add a job to the FIFO queue.

    Returns the 1-based queue position, or None if the queue is full
    (caller should respond 429).

    The optional `request` parameter is a seam for CR-001b (demo lock) and
    CR-001 per-tier rate limits — unused today. When the demo lock ships,
    this is where the owner-vs-others check goes; when CR-001 ships, this
    is where the per-tier concurrent-job cap is enforced.
    """
    total = len(pending_queue) + (1 if current_job_id else 0)
    if total >= MAX_QUEUE_DEPTH:
        return None
    position = len(pending_queue) + 1
    _jobs[job_id] = {
        "stage": "queued", "queue_position": position,
        "type": job_type, "label": label,
        "result": None, "error": None,
    }
    pending_queue.append({
        "job_id": job_id, "type": job_type,
        "label": label, "coro_fn": coro_fn,
    })
    queue_event.set()
    return position


def depth() -> int:
    """Total jobs in flight (queued + running)."""
    return len(pending_queue) + (1 if current_job_id else 0)


def paused() -> bool:
    """True if the external pause flag file exists."""
    return Path(PAUSE_FLAG).exists()


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
        }
    pending_info = [
        {"job_id": e["job_id"], "type": e["type"], "label": e["label"], "position": i + 1}
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
    global current_job_id
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
