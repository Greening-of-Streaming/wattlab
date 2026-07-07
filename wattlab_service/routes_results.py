"""
Results routes — list / delete / JSON / CSV / reproduce.zip downloads,
plus the /demo/last carve-out (mode-filtered pre-load for the Guided
Tour). CR-026 visitor scoping applies on the generic endpoints; the demo
carve-out loads unscoped curated types only.

Phase 3 per-feature route module — never import main.
"""
import io
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

import queue_control
import settings as cfg
from capabilities import requires, PUBLIC_PAGE, RESULTS_DOWNLOAD, SETTINGS_WRITE
from persist import list_results, load_result, to_csv, delete_result

router = APIRouter()


# --- Results: list, JSON download, CSV download ---

@router.get("/results/{job_type}/list", dependencies=[Depends(requires(RESULTS_DOWNLOAD))])
async def results_list(job_type: str, request: Request, limit: int = 10):
    if job_type not in ("video", "llm", "image", "enhance"):
        return JSONResponse({"error": "Invalid type"}, status_code=400)
    # CR-026: own-jobs scope for non-Lab. Lab passes None → unfiltered.
    return list_results(job_type, limit=max(1, min(limit, 200)),
                        visitor_key=queue_control.visitor_key(request))


@router.delete("/results/{job_type}/{job_id}", dependencies=[Depends(requires(SETTINGS_WRITE))])
async def results_delete(job_type: str, job_id: str):
    """Lab-only — delete a stored result JSON (dev cleanup of test runs). Gated
    on SETTINGS_WRITE (Lab tier). CSV is generated on the fly, so the JSON is the
    only artifact to remove."""
    if job_type not in ("video", "llm", "image", "enhance"):
        return JSONResponse({"ok": False, "error": "Invalid type"}, status_code=400)
    if delete_result(job_type, job_id):
        return {"ok": True, "deleted": job_id}
    return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)


# CR-026 carve-out for /demo's "show last result" panel.
#
# /demo's guided tour pre-loads the most recent persisted result for each
# workload so visitors land on a populated card rather than an empty page.
# CR-026's visitor scoping correctly hides cross-visitor jobs from
# Anonymous, but for /demo specifically we want the latest result to be
# visible regardless of who ran it — that's the whole point of the
# pre-loaded panel. This endpoint is the deliberate exception to the
# CR-026 default: returns the FULL latest result for the requested type
# (and optional task filter), unfiltered by visitor.
#
# Privacy note: the rendered /demo cards use energy figures, model
# labels, generated text, and produced images — all already meant to
# be illustrative. Curated pins (`demo_pinned_results` in settings) are
# the operator's promise that a specific record is fit to show anyone;
# "enhance" is pin-ONLY because that dir holds member-uploaded content
# and "latest" could leak a private job. If a future Member workflow
# ever runs anything personally identifying on the other types, extend
# the pin-only rule to them too.
@router.get("/demo/last/{job_type}", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def demo_last_result(job_type: str, task_eq: str | None = None):
    """Pinned-or-latest persisted result for /demo's tour panels,
    unfiltered by visitor (deliberate CR-026 carve-out for the demo
    surface).

    Pin-first: `demo_pinned_results[job_type]` (settings) names a job_id
    to serve; a dangling pin falls back to latest-matching — except
    `enhance`, which never falls back (member uploads are private).

    `job_type='rag'` is a pseudo-type: RAG records persist under
    results/llm/ with mode='rag_compare'; the demo's RAG step reads this
    instead of task-text filtering (newer records carry task=None).
    `job_type='llm'` defaults to *plain* LLM runs — RAG/compare records
    in the same dir are excluded so /demo's LLM step shows an actual
    single inference instead of the wrong widget shape.
    """
    if job_type not in ("video", "llm", "image", "rag", "enhance"):
        return JSONResponse({"error": "Invalid type"}, status_code=400)
    store_dir = "llm" if job_type == "rag" else job_type

    pin = (cfg.load().get("demo_pinned_results") or {}).get(job_type)
    if pin:
        full = load_result(store_dir, pin, visitor_key=None)
        if full is not None:
            return full
    if job_type == "enhance":
        # Pin-only: no pin (or a dangling one) means nothing to show.
        return JSONResponse({"error": "no result"}, status_code=404)

    runs = list_results(store_dir, limit=20, visitor_key=None)
    if job_type == "rag":
        runs = [r for r in runs if r.get("mode") == "rag_compare"]
    elif task_eq:
        runs = [r for r in runs if r.get("task") == task_eq]
    elif job_type == "llm":
        # Plain-LLM default: only a genuine single inference. Compare/RAG
        # records (mode=compare_models, rag_compare_models, rag, rag_compare,
        # both, batch, all, …) persist under results/llm/ too but carry a
        # different card shape. Pre-loading one into /demo's single-run widget
        # rendered a "format not recognised" card and (pre-fix) trapped the
        # tour, since the single-run renderer bailed before revealing Next.
        # Filter on `mode` (more reliable than the `task` text — compare
        # records have task=None, so the old "RAG" prefix test let them pass).
        runs = [r for r in runs if r.get("mode", "single") == "single"]
    elif job_type == "image":
        # Same reasoning: the image step's single-run card only handles a
        # single cpu/gpu generation, not an N-way compare_models record.
        runs = [r for r in runs if r.get("mode", "cpu") in ("cpu", "gpu")]
    if not runs:
        return JSONResponse({"error": "no result"}, status_code=404)
    full = load_result(store_dir, runs[0]["job_id"], visitor_key=None)
    if full is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return full


# Web-safe before/after media for the PINNED enhance showcase — the visual
# half of the tour's Video-Enhancement step. Same trust model as the pin
# itself: the raw /enhance-run asset endpoints stay Member-gated; what this
# serves are the small derived previews `bin/make-demo-enhance-previews`
# writes for the one operator-pinned job (matched-size H.264 + posters,
# HDR tonemapped). No pin, or no generated files → 404 and the tour step
# falls back to the numeric card alone.
_PREVIEW_KINDS = {
    "before.mp4": "video/mp4", "after.mp4": "video/mp4",
    "before.jpg": "image/jpeg", "after.jpg": "image/jpeg",
}


@router.get("/demo/enhance-preview/{kind}", dependencies=[Depends(requires(PUBLIC_PAGE))])
async def demo_enhance_preview(kind: str):
    media_type = _PREVIEW_KINDS.get(kind)
    if media_type is None:
        return JSONResponse({"error": "Invalid kind"}, status_code=400)
    pin = (cfg.load().get("demo_pinned_results") or {}).get("enhance")
    if not pin or "/" in pin or ".." in pin:
        return JSONResponse({"error": "no preview"}, status_code=404)
    f = (Path(cfg.load().get("pixop_workdir", "/srv/data/owl/pixop"))
         / "demo-previews" / f"{pin}__{kind}")
    if not f.is_file():
        return JSONResponse({"error": "no preview"}, status_code=404)
    # FileResponse handles Range requests — required for video on Safari/iOS.
    return FileResponse(f, media_type=media_type)


@router.get("/results/{job_type}/{job_id}/download.json", dependencies=[Depends(requires(RESULTS_DOWNLOAD))])
async def results_download_json(job_type: str, job_id: str, request: Request):
    if job_type not in ("video", "llm", "image", "enhance"):
        return JSONResponse({"error": "Invalid type"}, status_code=400)
    data = load_result(job_type, job_id, visitor_key=queue_control.visitor_key(request))
    if not data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    content = json.dumps(data, indent=2)
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=wattlab_{job_type}_{job_id}.json"},
    )

@router.get("/results/{job_type}/{job_id}/download.csv", dependencies=[Depends(requires(RESULTS_DOWNLOAD))])
async def results_download_csv(job_type: str, job_id: str, request: Request):
    if job_type not in ("video", "llm", "image", "enhance"):
        return JSONResponse({"error": "Invalid type"}, status_code=400)
    data = load_result(job_type, job_id, visitor_key=queue_control.visitor_key(request))
    if not data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    content = to_csv(job_type, data)
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=wattlab_{job_type}_{job_id}.csv"},
    )


@router.get("/results/{job_type}/{job_id}/reproduce.zip", dependencies=[Depends(requires(RESULTS_DOWNLOAD))])
async def results_reproduce_zip(job_type: str, job_id: str, request: Request):
    # CR-040 — video-only V1 (AI results are far less reproducible across GPU
    # driver / ROCm / cuDNN versions than a video encode is).
    if job_type != "video":
        return JSONResponse({"error": "Reproduce bundles are video-only in V1"}, status_code=400)
    data = load_result(job_type, job_id, visitor_key=queue_control.visitor_key(request))
    if not data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    import reproduce
    blob = reproduce.build_bundle(job_type, job_id, data, cfg.load().get("variance_pct"))
    if blob is None:
        return JSONResponse({"error": "No reproducible encode in this result"}, status_code=422)
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=owl_reproduce_{job_id}.zip"},
    )
