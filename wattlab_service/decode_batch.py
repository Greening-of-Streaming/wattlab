"""
decode_batch.py — collate a decode *campaign* (CR-073): every stored decode
result sharing one `batch_id`, folded into a device × (content × codec)
matrix that a reader can take in at a glance.

Pure functions over envelopes (no IO): `matrix(envelopes)` is the whole
contract; routes_decode renders it as HTML / JSON / CSV. Reads only the fields
persist.py stores (`runs[]`, `template`, `mode`, `protocol`, provenance) and
tolerates both envelope eras (raw arrays in runs[] only, or duplicated under
devices[].rows) — it never touches raw samples.

Cell = one (device, content, codec[, mode]) measurement:
  delta_w · ci · flag · n_task · window_s · liveness proofs (playback state at
  mid-window, screenshot present, alive at window end, play presses) · job_id ·
  error (row or device-section failure) · context_delta_w for screen rows.

Content / codec come from the template key: `loop_<family>_<codec>` (the
campaign templates), the July recipe keys `<family>_<codec>_…`, or an upload
(`upload/<name>`, codec unknown). Unknown shapes still land in the matrix as
`other`, never dropped — a collation that silently loses rows is worse than
an ugly one.
"""
from __future__ import annotations

import re

_TEMPLATE_RE = re.compile(r"^(?:loop_)?(?P<family>[a-z0-9]+)_(?P<codec>h264|h265|hevc|av1|vp9)(?:_|$)")
_CODEC_LABEL = {"h264": "H.264", "h265": "HEVC", "hevc": "HEVC", "av1": "AV1", "vp9": "VP9"}
_FAMILY_LABEL = {"bbb": "BBB", "meridian": "Meridian", "kranjska": "Kranjska"}


def parse_template(template: str | None, template_label: str | None = None,
                   upload_name: str | None = None) -> tuple[str, str]:
    """→ (content, codec) display keys. Uploads → (upload/<name>, '?')."""
    t = template or ""
    if t == "upload":
        name = upload_name or (template_label or "").split("— ")[-1].strip() or "clip"
        return f"upload/{name}", "?"
    m = _TEMPLATE_RE.match(t)
    if not m:
        return (t or "other"), "?"
    fam, cod = m.group("family"), m.group("codec")
    return _FAMILY_LABEL.get(fam, fam), _CODEC_LABEL.get(cod, cod)


def _cell_from_row(row: dict, job: dict, device: str, content: str,
                   codec: str) -> dict:
    conf = row.get("confidence") or {}
    prov = row.get("provenance") or {}
    return {
        "device": device, "content": content, "codec": codec,
        "mode": (job.get("mode") or "").replace("ui_", "") or None,
        "job_id": job.get("job_id"),
        "run": row.get("run"),
        "delta_w": row.get("delta_w"),
        "w_base": row.get("w_base"), "w_task": row.get("w_task"),
        "ci": conf.get("ci_delta_w_95"),
        "flag": conf.get("flag"),
        "confidence_positive": conf.get("confidence_positive"),
        "n_task": row.get("n_task"),
        "window_s": row.get("window_s"),
        "context_delta_w": row.get("context_delta_w"),
        "context_task_w": row.get("context_task_w"),
        "mid_state": prov.get("playback_state_midwindow"),
        "screenshot": prov.get("screenshot"),
        "alive_at_end": row.get("alive_at_window_end"),
        "play_presses": prov.get("play_presses_after_launch"),
        "keep_awake": prov.get("keep_awake"),
        "decoders": prov.get("decoders_allocated"),
        "error": row.get("error"),
        "error_where": row.get("error_where"),
    }


def cells(envelopes: list[dict]) -> list[dict]:
    """Flatten a batch into one dict per (job, device, run). Device-section
    failures (a device that never produced rows) become an error cell so the
    matrix shows ✗ where a reader expects a number."""
    out = []
    for job in envelopes:
        content, codec = parse_template(job.get("template"), job.get("template_label"),
                                        job.get("upload_name"))
        seen_devices = set()
        for row in job.get("runs") or []:
            dev = row.get("device") or "device"
            seen_devices.add(dev)
            out.append(_cell_from_row(row, job, dev, content, codec))
        for dev, sec in (job.get("devices") or {}).items():
            if dev in seen_devices:
                continue
            # a section without runs: either an outright error, or rows that
            # all errored (bench.py error rows carry no delta_w) — surface both
            rows = sec.get("rows") or []
            if rows:
                for r in rows:
                    out.append(_cell_from_row(r, job, dev, content, codec))
            else:
                out.append({**_cell_from_row({}, job, dev, content, codec),
                            "error": sec.get("error") or "no rows"})
    return out


def matrix(envelopes: list[dict], batch_id: str | None = None) -> dict:
    """The collation: {batch_id, jobs[], devices[], columns[], cells{},
    protocol, notes[]} — `cells` keyed "device|content|codec|mode" (JSON-safe),
    `columns` ordered content-major then codec, `devices` in first-seen order.
    Screen-mode rows keep their own column key so a device measured both
    headless and on-screen for the same clip shows both."""
    cs = cells(envelopes)
    devices, columns, cellmap = [], [], {}
    for c in cs:
        if c["device"] not in devices:
            devices.append(c["device"])
        col = (c["content"], c["codec"], c["mode"] if c["mode"] == "screen" else None)
        if col not in columns:
            columns.append(col)
        key = "|".join([c["device"], c["content"], c["codec"], col[2] or ""])
        # duplicates (a repeat of the same cell inside one batch): keep all,
        # the matrix cell becomes a list; the reader sees n>1 explicitly
        cellmap.setdefault(key, []).append(c)
    columns.sort(key=lambda t: (t[0], t[1], t[2] or ""))
    jobs = [{"job_id": e.get("job_id"), "saved_at": e.get("saved_at"),
             "template": e.get("template"), "template_label": e.get("template_label"),
             "mode": e.get("mode"), "n_runs": len(e.get("runs") or []),
             "window_s": (e.get("protocol") or {}).get("window_s"),
             "owl_version": (e.get("owl_version") or {}).get("git_sha")
                            or (e.get("owl_version") or {}).get("sha")}
            for e in envelopes]
    protos = {}
    for e in envelopes:
        p = e.get("protocol") or {}
        for k in ("protocol_version", "cadence_s", "baseline_samples", "settle_s",
                  "startup_skip_s", "harness"):
            if p.get(k) is not None:
                protos.setdefault(k, set()).add(str(p[k]))
    notes = []
    if any(c.get("keep_awake") for c in cs):
        notes.append("Android boxes' sleep / screensaver / CEC-standby timers were pinned "
                     "OFF for the bench (recorded per row as keep_awake) — a living-room "
                     "box on defaults would sleep mid-window; rows measure the box while "
                     "playing.")
    if any(c.get("mode") == "screen" for c in cs):
        notes.append("Screen-mode rows meter the shared panel as context (context Δ) — "
                     "panel draw is content-driven and is NOT decode.")
    n_err = sum(1 for c in cs if c.get("error"))
    if n_err:
        notes.append(f"{n_err} cell(s) errored (✗) — shown, not hidden.")
    labels = [e.get("batch_label") for e in envelopes if e.get("batch_label")]
    return {"batch_id": batch_id, "label": (labels[-1] if labels else None),
            "jobs": jobs, "devices": devices,
            "columns": [{"content": c, "codec": k, "mode": m or "headless"}
                        for c, k, m in columns],
            "cells": cellmap,
            "protocol": {k: sorted(v) for k, v in protos.items()},
            "notes": notes,
            "n_cells": len(cs), "n_errors": n_err,
            "date_range": [min((j["saved_at"] or "" for j in jobs), default=None),
                           max((j["saved_at"] or "" for j in jobs), default=None)]}


def to_csv_rows(m: dict) -> list[dict]:
    """One flat row per cell (repeats included) for the .csv export."""
    out = []
    for key, lst in m["cells"].items():
        for c in lst:
            ci = c.get("ci") or [None, None]
            out.append({
                "batch_id": m.get("batch_id"), "job_id": c["job_id"], "device": c["device"],
                "content": c["content"], "codec": c["codec"], "mode": c["mode"],
                "run": c["run"], "w_base": c["w_base"], "w_task": c["w_task"],
                "delta_w": c["delta_w"], "ci_low": ci[0], "ci_high": ci[1],
                "flag": c["flag"], "confidence_positive": c["confidence_positive"],
                "n_task": c["n_task"], "window_s": c["window_s"],
                "context_delta_w": c["context_delta_w"],
                "mid_state": c["mid_state"], "alive_at_end": c["alive_at_end"],
                "play_presses": c["play_presses"], "screenshot": c["screenshot"],
                "error": c["error"],
            })
    out.sort(key=lambda r: (r["device"] or "", r["content"] or "", r["codec"] or "",
                            r["mode"] or "", r["job_id"] or ""))
    return out


CSV_FIELDS = ["batch_id", "job_id", "device", "content", "codec", "mode", "run",
              "w_base", "w_task", "delta_w", "ci_low", "ci_high", "flag",
              "confidence_positive", "n_task", "window_s", "context_delta_w",
              "mid_state", "alive_at_end", "play_presses", "screenshot", "error"]
