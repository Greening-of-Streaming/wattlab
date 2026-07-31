#!/usr/bin/env python3
"""campaign.py — decode duration + codec measurement campaign (2026-07-31).

Autonomous, fault-tolerant, resumable. Drives OWL's /decode/run over localhost
(Lab), one job at a time (the queue serialises anyway), polls each to done, and
appends per-device rows to results.jsonl. A cell key already in done.txt is
skipped, so a re-launch resumes where it stopped.

Order is by descending value: the duration study first (shortest durations
first, so all families get breadth early), then the codec suite (all-5 parallel
first, then one-device-at-a-time as the sequential-vs-parallel sanity check).

Run:  setsid nohup python3 campaign.py >> campaign.log 2>&1 < /dev/null &
"""
import json
import os
import time
import urllib.request

BASE = "http://localhost:8000"
OUT = "/srv/data/owl/campaign_2026-07-31"
os.makedirs(OUT, exist_ok=True)
RESULTS = os.path.join(OUT, "results.jsonl")
DONE = os.path.join(OUT, "done.txt")

DEVICES = ["pi5", "firestick", "gtv", "bbox", "c2"]
FAMILIES = ["bbb", "meridian", "kranjska"]
CODECS = ["h264", "h265", "av1"]
CODEC_WINDOW_S = 150


def _log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def post_run(template, devices, window_s, mode="headless"):
    body = json.dumps({"template": template, "mode": mode, "devices": devices,
                       "window_s": window_s, "calibrate": False}).encode()
    req = urllib.request.Request(BASE + "/decode/run", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def poll(job_id, timeout_s):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            with urllib.request.urlopen(BASE + f"/decode/job/{job_id}",
                                        timeout=15) as r:
                d = json.load(r)
            if d.get("stage") == "done":
                return d
        except Exception:
            pass
        time.sleep(10)
    return None


def load_done():
    return set(open(DONE).read().split()) if os.path.exists(DONE) else set()


def mark_done(key):
    with open(DONE, "a") as f:
        f.write(key + "\n")


def record(cell, job):
    rows = {}
    r = (job or {}).get("result", {})
    for name, sec in r.get("devices", {}).items():
        row = (sec.get("rows") or [{}])[0]
        rows[name] = {k: row.get(k) for k in
                      ("delta_w", "w_base", "w_task", "n_task", "window_s",
                       "flag", "confidence", "error")}
    with open(RESULTS, "a") as f:
        f.write(json.dumps({"cell": cell,
                            "job_id": (job or {}).get("job_id"),
                            "ok": job is not None, "rows": rows}) + "\n")


def run_cell(key, template, devices, window_s):
    if key in load_done():
        _log(f"skip {key}")
        return
    _log(f"RUN {key}  {template} {devices} win={window_s}")
    try:
        j = post_run(template, devices, window_s)
        jid = j.get("job_id")
    except Exception as e:
        _log(f"  POST failed: {e!r} — marking done, moving on")
        record({"key": key, "template": template, "devices": devices,
                "window_s": window_s}, None)
        mark_done(key)
        return
    if not jid:
        _log(f"  no job_id: {j}")
        record({"key": key}, None)
        mark_done(key)
        return
    res = poll(jid, window_s + 500)         # generous overhead budget
    record({"key": key, "template": template, "devices": devices,
            "window_s": window_s, "job_id": jid}, res)
    mark_done(key)
    _log(f"  {'DONE' if res else 'TIMEOUT/None'} {key} (job {jid})")
    time.sleep(5)                           # let the plugs breathe


def build_cells():
    cells = []
    # A — duration study: h264, all families, all-5 parallel. Shortest first.
    for dur in (30, 300, 1200, 3540):       # 3540 ≈ 59 min (fits the 60 min clip)
        for fam in FAMILIES:
            cells.append((f"A_dur{dur}_{fam}", f"loop_{fam}_h264", DEVICES, dur))
    # B — codec suite: all-5 parallel first (quick), then one device at a time.
    for fam in FAMILIES:
        for cod in CODECS:
            cells.append((f"B_all_{fam}_{cod}", f"loop_{fam}_{cod}",
                          DEVICES, CODEC_WINDOW_S))
    for fam in FAMILIES:
        for cod in CODECS:
            for d in DEVICES:
                cells.append((f"B_seq_{fam}_{cod}_{d}", f"loop_{fam}_{cod}",
                              [d], CODEC_WINDOW_S))
    return cells


def main():
    cells = build_cells()
    _log(f"CAMPAIGN START — {len(cells)} cells "
         f"({len(load_done())} already done)")
    for key, tpl, devs, win in cells:
        run_cell(key, tpl, devs, win)
    _log("CAMPAIGN COMPLETE")


if __name__ == "__main__":
    main()
