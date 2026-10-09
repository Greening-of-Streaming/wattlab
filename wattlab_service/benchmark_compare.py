"""
benchmark_compare.py — side-by-side view of benchmark runs, typically one per
node from a multi-node launch (shared group_id), 2026-10-09.

Pure functions over stored results: each run's steps are reduced to named
metrics (one per source × codec × engine side for video, one per model for the
AI panels), repeats are summarised as mean ± sd with their n, and the table has
one column per run. Values are NEVER pooled across runs or hosts
(docs/gos2_design.md §2) — each column is its own machine's measurement.
Replaces the offline campaign scripts (compare.py / analyse.py) for the
standard benchmark panels.
"""
import statistics

import persist


def _video(step: dict, d: dict):
    src = step.get("params", {}).get("source_key", "?")
    for codec, cd in (d.get("codecs") or {}).items():
        for side in ("cpu", "gpu"):
            e = ((cd or {}).get(side) or {}).get("energy") or {}
            if e.get("delta_e_wh") is not None:
                eng = "CPU" if side == "cpu" else "HW"
                yield (f"video · {src} · {codec} · {eng}", "ΔE Wh / encode", e["delta_e_wh"])


def _ai_models(section: str, unit: str, field: str):
    def fn(step: dict, d: dict):
        for m in d.get("models") or []:
            v = (m.get("energy") or {}).get(field) if field == "wh_per_image" else m.get(field)
            if v is not None:
                yield (f"{section} · {m.get('model_label') or m.get('model_key')}", unit, v)
    return fn


_EXTRACT = {
    "video": _video,
    "llm": _ai_models("LLM", "mWh / token", "mwh_per_token"),
    "rag": _ai_models("RAG", "mWh / token", "mwh_per_token"),
    "image": _ai_models("Image", "Wh / image", "wh_per_image"),
}


def run_metrics(run: dict) -> tuple[dict, int]:
    """{metric: (unit, [values…])} for one run, plus the count of step results
    not present on this node (not yet replicated)."""
    out, missing = {}, 0
    for st in run.get("steps", []):
        ref = st.get("result_ref") or {}
        fn = _EXTRACT.get(st.get("kind"))
        if not fn or not ref.get("job_id"):
            continue
        d = persist.load_result(ref.get("type", ""), ref["job_id"], visitor_key=None)
        if d is None:
            missing += 1
            continue
        for name, unit, v in fn(st, d):
            out.setdefault(name, (unit, []))[1].append(float(v))
    return out, missing


def cell(values: list) -> dict:
    n = len(values)
    if not n:
        return {"n": 0}
    return {"n": n, "mean": statistics.mean(values),
            "sd": statistics.stdev(values) if n > 1 else None}


def table(runs: list) -> dict:
    """{"columns": [{bid, host, gpu, missing}], "rows": [{metric, unit, cells}]}.
    Row order: first appearance across the runs (plan order)."""
    import hosts
    cols, per_run, order = [], [], []
    for r in runs:
        mets, missing = run_metrics(r)
        h = hosts.result_host(r)
        cols.append({"bid": r.get("benchmark_run_id") or r.get("job_id"),
                     "host": h.get("label") or h.get("id"), "host_id": h.get("id"),
                     "gpu": persist.bench_gpu(r),
                     "status": r.get("status"), "started_at": r.get("started_at"),
                     "missing": missing})
        per_run.append(mets)
        for k in mets:
            if k not in order:
                order.append(k)
    rows = []
    for k in order:
        unit = next(m[k][0] for m in per_run if k in m)
        rows.append({"metric": k, "unit": unit,
                     "cells": [cell(m[k][1]) if k in m else {"n": 0} for m in per_run]})
    return {"columns": cols, "rows": rows}
