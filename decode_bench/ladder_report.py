#!/usr/bin/env python3
"""ladder_report.py — decode power vs bitrate from `ladder_bbb_h264` jobs.

Each job has seven rows per box (one per rung). Pools any number of jobs
(reps), reports per box per rung: mean ΔW ± 95 % CI, whether the box actually
stayed PLAYING at full rate (the content clock's segments — a rung that
rebuffered on Wi-Fi is flagged, not silently averaged), and a slope in
W per Mbps with CI over the rungs. Boxes with different slopes flex
differently against bitstream load — that is the cross-box question.

Usage: python3 ladder_report.py <job_id> [<job_id> ...] [--csv out.csv]
"""
import argparse
import csv
import json
import re
import statistics
import sys
import urllib.request

sys.path.insert(0, "/home/gos/wattlab/wattlab_service")
import decode_sync  # noqa: E402
from content_profile import _mean_ci, _ols, _corr  # noqa: E402

_KBPS = re.compile(r"_(\d+)k$")


def fetch(job_id):
    req = urllib.request.Request(f"http://127.0.0.1:8000/decode/job/{job_id}",
                                 headers={"x-real-ip": "127.0.0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs", nargs="+")
    ap.add_argument("--csv", default=None)
    a = ap.parse_args()
    cells: dict = {}      # (device, kbps) -> list of row dicts
    for jid in a.jobs:
        env = (fetch(jid).get("result") or {})
        for row in env.get("runs") or []:
            m = _KBPS.search(row.get("run", ""))
            if not m or row.get("error"):
                continue
            cells.setdefault((row["device"], int(m.group(1))), []).append(row)
    devices = sorted({d for d, _ in cells})
    rungs = sorted({k for _, k in cells})
    print(f"\n=== bitrate ladder — jobs {', '.join(a.jobs)} ===")
    print("regime: realtime playback, BBB H.264 1080p60 NVENC CBR, 90 s windows, "
          "video-only, four boxes started together\n")
    hdr = f"{'Mbps':>6}" + "".join(f"{d:>28}" for d in devices)
    print(hdr)
    print(f"{'':>6}" + "".join(f"{'W (ΔW) (n) [play%]':>28}" for _ in devices))
    table = {}
    for k in rungs:
        line = f"{k/1000:>6.2f}"
        for d in devices:
            rows = cells.get((d, k), [])
            ws = [r["w_task"] for r in rows if r.get("w_task") is not None]
            dws = [r["delta_w"] for r in rows if r.get("delta_w") is not None]
            m, ci, n = _mean_ci(ws)
            dm, _, _ = _mean_ci(dws)
            # fraction of the SAMPLED window the clock says was PLAYING at 1×
            # (the clock thread also covers the settle/provenance seconds either
            # side of the window, so clip to the sample span, not window_s)
            play = []
            for r in rows:
                cc = r.get("content_clock") or {}
                tt = r.get("raw_task_t") or []
                if cc.get("n_polls") and len(tt) >= 2:
                    t0, t1 = tt[0], tt[-1]
                    segs = decode_sync.clock_segments(r.get("raw_content_clock") or [])
                    covered = sum(max(0.0, min(s[1], t1) - max(s[0], t0)) for s in segs)
                    play.append(min(1.0, covered / max(1.0, t1 - t0)))
            pf = statistics.mean(play) if play else None
            ps = f"[{100*pf:.0f}%]" if pf is not None else ""
            flag = "⚠" if pf is not None and pf < 0.9 else ""
            if m is None:
                cell = "—"
            else:
                cell = f"{m:.3f}" + (f"±{ci:.3f}" if ci else "")
                cell += f" ({dm:+.2f}) ({n}) {ps}{flag}"
            line += f"{cell:>28}"
            if m is not None:
                table[(d, k)] = (m, ci, n, pf, dm)
        print(line)
    print("\nslope over rungs (absolute W per Mbps, 95 % CI) and r:")
    for d in devices:
        xs = [k / 1000 for k in rungs if (d, k) in table]
        ys = [table[(d, k)][0] for k in rungs if (d, k) in table]
        if len(xs) >= 3:
            b, ci, n = _ols(xs, ys)
            r, _, t = _corr(xs, ys)
            lo, hi = ys[0], ys[-1]
            print(f"  {d:<11} {b:+.4f} ±{ci:.4f} W/Mbps  r={r:+.2f} (t={t:.1f})  "
                  f"{lo:.3f} W @ {xs[0]:.2f} Mbps → {hi:.3f} W @ {xs[-1]:.0f} Mbps"
                  f"  (+{100*(hi-lo)/lo:.0f} %)")
    print("W = mean draw during the 90 s window (the comparable lens: each rung's 20 s"
          " baseline is taken with the player UI foregrounded, and on the Fire TV that"
          " state draws MORE than playback, so its ΔW is negative and meaningless);"
          " (ΔW) = W minus that per-rung baseline, kept for the record.\n"
          "[play%] = share of the sampled window the box's own clock shows PLAYING at 1×;"
          " ⚠ < 90 % = rebuffering, treat that rung as contaminated.")
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["device", "kbps", "w_task_mean", "ci95", "n", "play_frac",
                        "delta_w_mean"])
            for (d, k), (m, ci, n, pf, dm) in sorted(table.items()):
                w.writerow([d, k, round(m, 4), round(ci, 4) if ci else "", n,
                            round(pf, 3) if pf is not None else "",
                            round(dm, 4) if dm is not None else ""])
        print(f"csv -> {a.csv}")


if __name__ == "__main__":
    main()
