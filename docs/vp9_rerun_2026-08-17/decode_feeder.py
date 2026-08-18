#!/usr/bin/env python3
"""VP9 re-run, decode arm: feed the iso-bitrate loop templates through OWL's /decode
queue one job at a time (the queue is a single worker; never stack jobs), all five rig
devices in parallel per job, headless, 1080 s windows, calibrate off, one batch_id so
/decode/batch/<id> collates the night.

Cells: 3 contents × 4 codecs, REP-OUTER order (pass 1 of all 12 cells, then pass 2) —
an early morning cut still leaves n=1 everywhere. Resumable via done.txt.

Same pattern as decode_bench/campaign.py + vp9_stage_decode.sh (2026-07-31 / 08-09).
"""
import json, os, sys, time, urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
DIR = Path("/srv/data/owl/campaign_2026-08-17_vp9b")
DONE = DIR / "decode_done.txt"
OUT = DIR / "decode_results.jsonl"
BATCH_ID = "20260817b9c0de"          # [0-9a-f]{6,32}
DEVICES = ["gtv", "firestick", "bbox", "c2", "pi400"]
WINDOW_S = 1080                    # = the non-h264 loop clamp (20-min clips)
FAMILIES = ["bbbiso", "kranjskaiso", "meridianiso"]
CODECS = ["h264", "h265", "av1", "vp9"]
REPS = int(os.environ.get("VP9B_REPS", "2"))
STREAMS = Path("/srv/data/owl/decode-bench/streams")
PI400_MAX_BYTES = int(1.7e9)       # /dev/shm ceiling on the 4 GB Pi 400


def post_run(template, devices):
    body = json.dumps({"template": template, "mode": "headless", "devices": devices,
                       "window_s": WINDOW_S, "cadence_s": 1, "calibrate": False,
                       "batch_id": BATCH_ID}).encode()
    req = urllib.request.Request(BASE + "/decode/run", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def poll(job_id, timeout_s):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            with urllib.request.urlopen(BASE + f"/decode/job/{job_id}", timeout=15) as r:
                d = json.load(r)
            if d.get("stage") in ("done", "error"):
                return d
        except Exception:
            pass
        time.sleep(15)
    return None


def log(msg):
    line = f"{time.strftime('%F %T')} {msg}"
    print(line, flush=True)


def main():
    done = set(DONE.read_text().split()) if DONE.exists() else set()
    # passes 1-2: every cell; pass 3: H.264 + VP9 only (the comparison the post is about)
    cells = [(f"loop_{fam}_{cod}", rep) for rep in range(REPS)
             for fam in FAMILIES for cod in CODECS]
    cells += [(f"loop_{fam}_{cod}", REPS) for fam in FAMILIES for cod in ("h264", "vp9")]
    log(f"feeder start: {len(cells)} cells, {len(done)} already done, batch {BATCH_ID}")
    for template, rep in cells:
        key = f"{template}#r{rep}"
        if key in done:
            continue
        fam, cod = template.split("_")[1], template.split("_")[2]
        clip = STREAMS / f"{fam}_{cod}_20min.{'webm' if cod == 'vp9' else 'mp4'}"
        if not clip.exists():
            log(f"SKIP {key}: clip missing {clip.name}")
            continue
        devices = list(DEVICES)
        if clip.stat().st_size > PI400_MAX_BYTES and "pi400" in devices:
            devices.remove("pi400")
            log(f"{key}: clip {clip.stat().st_size/1e9:.2f} GB > Pi 400 shm ceiling → pi400 dropped")
        try:
            resp = post_run(template, devices)
        except Exception as e:
            log(f"POST failed for {key}: {e} — retry in 60 s")
            time.sleep(60)
            try:
                resp = post_run(template, devices)
            except Exception as e2:
                log(f"POST failed twice for {key}: {e2} — skipping")
                continue
        jid = resp["job_id"]
        log(f"{key} → job {jid} (queue pos {resp.get('queue_position')})")
        d = poll(jid, WINDOW_S + 900)
        if d is None:
            log(f"{key} job {jid}: TIMEOUT waiting for done — moving on")
            continue
        env = d.get("result") or {}
        summary = {}
        for run in env.get("runs", []) or []:
            summary[run.get("device")] = {
                "delta_w": run.get("delta_w"), "flag": (run.get("confidence") or {}).get("flag"),
                "playing_mid": (run.get("provenance") or {}).get("playback_state_midwindow"),
                "alive_end": run.get("alive_at_window_end"),
                "decoders": (run.get("provenance") or {}).get("decoders_allocated"),
                "error": run.get("error"),
            }
        with open(OUT, "a") as f:
            f.write(json.dumps({"cell": key, "job_id": jid, "stage": d.get("stage"),
                                "status": d.get("status"), "partial_errors": d.get("partial_errors"),
                                "summary": summary, "t": time.time()}) + "\n")
        with open(DONE, "a") as f:
            f.write(key + "\n")
        log(f"{key} done: " + " · ".join(
            f"{dev} {v['delta_w']} W {v['flag'] or ''} {v['playing_mid'] or ''}"
            for dev, v in summary.items()))
        time.sleep(5)
    log("feeder finished")
    (DIR / "decode_done").write_text(time.strftime("%F %T") + "\n")


if __name__ == "__main__":
    main()
