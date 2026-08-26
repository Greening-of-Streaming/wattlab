#!/usr/bin/env python3
"""Side-watcher for a long Apple TV row (2026-08-26): every N seconds record
pyatv power/playback state + position + app, and the rig job's live sample,
to a JSONL; flag anomalies (asleep, not Playing, position stalled, app
changed, power_state off, job sample below the idle floor). Read-only.
Usage: atv_watch.py --job JOBID --out file.jsonl [--every 15] [--hours 1]"""
import argparse, json, subprocess, time, urllib.request
from pathlib import Path

ATVREMOTE = next(b for b in ("/srv/data/owl/pyatv-venv/bin/atvremote", "/tmp/pyatv-venv/bin/atvremote") if Path(b).is_file())
CREDS = Path("/srv/data/owl/atv"); ATV = "192.168.1.152"


def atv(*cmds, timeout=40):
    cc = (CREDS / "companion_creds").read_text().strip(); ac = (CREDS / "airplay_creds").read_text().strip()
    try:
        r = subprocess.run([ATVREMOTE, "-s", ATV, "--companion-credentials", cc, "--airplay-credentials", ac, *cmds],
                           capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f"ERR {type(e).__name__}"


def snapshot():
    out = atv("power_state", "playing", "app")
    d = {"t": time.time(), "power": None, "state": None, "position_s": None, "title": None, "app": None}
    for line in out.splitlines():
        s = line.strip()
        if "PowerState." in s: d["power"] = s.rsplit(".", 1)[-1]
        elif s.startswith("Device state:"): d["state"] = s.split(":", 1)[1].strip()
        elif s.startswith("Position:"):
            try: d["position_s"] = float(s.split(":", 1)[1].strip().split("/")[0].rstrip("s"))
            except ValueError: pass
        elif s.startswith("Title:"): d["title"] = s.split(":", 1)[1].strip()
        elif s.startswith("App:"): d["app"] = s.split(":", 1)[1].strip()
    if out.startswith("ERR"): d["err"] = out
    return d


def job_state(job_id):
    try:
        j = json.load(urllib.request.urlopen(f"http://127.0.0.1:8000/decode/job/{job_id}", timeout=5))
        dev = (j.get("devices") or {}).get("atv") or {}
        return {"status": j.get("status"), "detail": dev.get("detail"), "watts": dev.get("watts"),
                "stage": dev.get("stage") or j.get("stage")}
    except Exception as e:
        return {"status": f"ERR {type(e).__name__}"}


def main():
    p = argparse.ArgumentParser(); p.add_argument("--job", required=True); p.add_argument("--out", required=True)
    p.add_argument("--every", type=float, default=15); p.add_argument("--hours", type=float, default=1.2)
    p.add_argument("--idle_floor_w", type=float, default=3.5)
    a = p.parse_args(); out = Path(a.out); t_end = time.time() + a.hours * 3600
    last_pos, n = None, 0
    while time.time() < t_end:
        s = snapshot(); j = job_state(a.job); s["job"] = j; flags = []
        if s["power"] != "On": flags.append(f"power={s['power']}")
        if j.get("status") == "running" and "sampling" in (j.get("detail") or ""):
            if s["state"] != "Playing": flags.append(f"state={s['state']}")
            if s["position_s"] is not None and last_pos is not None and s["position_s"] <= last_pos: flags.append("position stalled")
            if s["app"] and "VLC" not in s["app"]: flags.append(f"app={s['app']}")
            w = j.get("watts")
            if isinstance(w, (int, float)) and w < a.idle_floor_w: flags.append(f"watts {w} < floor {a.idle_floor_w}")
        if "err" in s: flags.append(s["err"])
        s["flags"] = flags; last_pos = s["position_s"]; n += 1
        with out.open("a") as f: f.write(json.dumps(s) + "\n")
        print(time.strftime("%H:%M:%S"), s["power"], s["state"], s["position_s"], s["app"], "|", j.get("status"), (j.get("detail") or "")[:50], j.get("watts"), "|", " ".join(flags) or "ok", flush=True)
        if j.get("status") in ("done", "error"): break
        time.sleep(a.every)


if __name__ == "__main__":
    main()
