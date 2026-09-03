#!/usr/bin/env python3
"""content_profile.py — intra-content decode power from a sync-family job.

Every row of a `loop_*_sync` job carries the box's own content clock
(`raw_content_clock`, from the player's media session) alongside the 1 s power
trace. This maps each power sample onto the content second it was decoding,
folds the N loops together, and reports:

  · per box: mean W per content bin, ±95 % CI across loops (t, not z — n≈6),
    plus loop-to-loop drift (thermal creep / cold first loop)
  · detectability: per-box SNR (between-bin ÷ within-bin SD) and cross-device
    r — the load-bearing statistic, see pearson()
  · per pair: the per-bin difference with its CI — the intra-content answer
    to "same silicon, different OS" and "same vendor, different silicon"
  · head-dip check: the black/white/black head is near-zero-entropy video, so
    every box should read LOWER there than in content. If it doesn't, that
    box's clock is misaligned and its profile is not trustworthy.
  · marker residuals (screen box only): the software clock vs the frames
    physically on the panel.
  · --descriptors: what property of the CONTENT the profile tracks — bits,
    motion, edge energy, luma per bin (content_descriptors.py) → r and a
    slope per box. Slope differences between boxes are "which box flexes
    more against hard content".
  · --compare JOB2: same box across two runs/templates — test–retest
    reliability, H.264 vs HEVC shape, 1080p vs 4K shape (the 4K clip is the
    head of the same BBB; shared content bins align automatically).

Usage:
    python3 content_profile.py <job_id> [--bin 5] [--csv out.csv]
        [--pairs gtv-firestick,xiaomi3-xiaomi] [--descriptors] [--compare JOB2]
"""
import argparse
import csv
import json
import statistics
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "/home/gos/wattlab/wattlab_service")
import decode_sync  # noqa: E402

HERE = Path(__file__).parent
JOB_URL = "http://127.0.0.1:8000/decode/job/{}"


def fetch_job(job_id: str) -> dict:
    req = urllib.request.Request(JOB_URL.format(job_id),
                                 headers={"x-real-ip": "127.0.0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


# --- statistics helpers -----------------------------------------------------

def _t_crit(n: int) -> float:
    """95 % two-sided t on n−1 df. scipy if present, else a small table (n≈3-15
    is the whole operating range here, and z=1.96 would understate every CI)."""
    if n < 2:
        return float("nan")
    try:
        from scipy.stats import t
        return float(t.ppf(0.975, n - 1))
    except Exception:
        table = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447,
                 8: 2.365, 9: 2.306, 10: 2.262, 11: 2.228, 12: 2.201,
                 13: 2.179, 14: 2.160, 15: 2.145, 16: 2.131}
        return table.get(n, 2.093 if n <= 20 else 1.96)


def _mean_ci(vals: list) -> tuple:
    n = len(vals)
    if n == 0:
        return None, None, 0
    m = statistics.mean(vals)
    if n == 1:
        return m, None, 1
    sd = statistics.stdev(vals)
    return m, _t_crit(n) * sd / (n ** 0.5), n


def _corr(xs: list, ys: list) -> tuple:
    """(r, n, t) with t on n−2 df."""
    n = len(xs)
    if n < 3:
        return None, n, None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
    if not den:
        return None, n, None
    r = num / den
    t = r * ((n - 2) / max(1e-12, 1 - r * r)) ** 0.5
    return r, n, t


def _ols(xs: list, ys: list) -> tuple:
    """(slope, ci95, n): least-squares slope of y on x with its 95 % CI."""
    n = len(xs)
    if n < 3:
        return None, None, n
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if not sxx:
        return None, None, n
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    resid = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    se = (resid / (n - 2) / sxx) ** 0.5
    return b, _t_crit(n - 1) * se, n


# --- profiles ---------------------------------------------------------------

def profile_row(row: dict, bin_s: float) -> dict | None:
    """One device's content-time profile: per_bin {bin: [per-loop mean W]},
    plus per_loop {loop: [bin means]} for drift."""
    clock = row.get("raw_content_clock")
    cc = row.get("content_clock") or {}
    loop_len = cc.get("loop_len_s")
    w, t = row.get("raw_task_w"), row.get("raw_task_t")
    if not (clock and loop_len and w and t):
        return None
    segs = decode_sync.clock_segments(clock)
    cells, unaligned = decode_sync.bin_by_content(w, t, segs, loop_len, bin_s)
    per_bin: dict = {}
    per_loop: dict = {}
    head_s = cc.get("head_s", 15)
    for (loop_k, b), vals in sorted(cells.items()):
        m = statistics.mean(vals)
        per_bin.setdefault(b, []).append(m)
        if b * bin_s >= head_s:
            per_loop.setdefault(loop_k, []).append(m)
    # Recompute the marker residuals from the raw traces so every run is
    # reported with the same rule (loop 0 excluded), whatever the service
    # stored at the time.
    marker = row.get("screen_marker_loops")
    if row.get("raw_context_w") and row.get("raw_context_t"):
        marker = decode_sync.marker_edges_from_clock(
            row["raw_context_w"], row["raw_context_t"], clock, loop_len,
            head_s=head_s or 15)
    return {"per_bin": per_bin, "per_loop": per_loop, "loop_len_s": loop_len,
            "bin_s": bin_s, "head_s": head_s, "unaligned": unaligned,
            "n_samples": len(w), "segments": len(segs), "marker": marker}


def load_profiles(job_id: str, bin_s: float) -> tuple:
    job = fetch_job(job_id)
    env = job.get("result") or {}
    profs = {}
    for row in env.get("runs") or []:
        p = profile_row(row, bin_s)
        if p:
            profs[row.get("device")] = p
    return env, profs


def content_bins(prof: dict) -> list:
    return sorted(b for b in prof["per_bin"] if b * prof["bin_s"] >= prof["head_s"])


def bin_means(prof: dict, keys: list) -> list:
    return [statistics.mean(prof["per_bin"][b]) for b in keys]


def head_dip(prof: dict, skip_loops: tuple = (0,)) -> tuple:
    """Per loop: mean(head bins) − mean(content bins). Should be negative on
    every box — an independent check that the clock is aligned.

    Loop 0 is skipped by default (same rule as the marker residual): its head
    coincides with the player's cold start, which on the Fire TV is a +0.5 W
    spike that would swamp the −0.1 W dip (seen 2026-09-03, job d9a03bf3)."""
    bs, hs = prof["bin_s"], prof["head_s"]
    if hs <= 0:
        return None, None, 0
    head_bins = [b for b in prof["per_bin"] if b * bs < hs]
    cont = content_bins(prof)
    if not head_bins or not cont:
        return None, None, 0
    n_loops = max(len(v) for v in prof["per_bin"].values())
    diffs = []
    for i in range(n_loops):
        if i in skip_loops and n_loops > len(skip_loops) + 1:
            continue
        h = [prof["per_bin"][b][i] for b in head_bins if len(prof["per_bin"][b]) > i]
        c = [prof["per_bin"][b][i] for b in cont if len(prof["per_bin"][b]) > i]
        if h and c:
            diffs.append(statistics.mean(h) - statistics.mean(c))
    return _mean_ci(diffs)


def pearson(a: dict, b: dict, content_only: bool = True) -> tuple:
    """r between two devices' per-bin profiles, plus n and the t statistic.

    This is the load-bearing statistic (2026-09-03). A single box cannot
    resolve intra-content structure from its own trace — its bin-to-bin
    spread is smaller than its loop-to-loop noise (snr() below returns < 1).
    But two boxes are independent hardware on independent meters, so any
    agreement about WHICH parts of the clip cost more cannot come from noise:
    cross-device r is the sensitive test where per-device SNR is not."""
    ka = set(content_bins(a) if content_only else a["per_bin"])
    kb = set(content_bins(b) if content_only else b["per_bin"])
    shared = sorted(ka & kb)
    return _corr(bin_means(a, shared), bin_means(b, shared))


def snr(prof: dict) -> float | None:
    """between-bin SD ÷ mean within-bin (across-loop) SD, content bins only.
    > 1 means this one device resolves content structure on its own."""
    keys = content_bins(prof)
    means = [statistics.mean(prof["per_bin"][k]) for k in keys]
    withins = [statistics.stdev(prof["per_bin"][k]) for k in keys
               if len(prof["per_bin"][k]) > 1]
    if len(means) < 2 or not withins:
        return None
    w = statistics.mean(withins)
    return statistics.stdev(means) / w if w else None


def loop_drift(prof: dict) -> dict:
    """Per-loop content mean, slope W/loop with CI, and first-loop excess."""
    loops = sorted(prof["per_loop"])
    means = [statistics.mean(prof["per_loop"][k]) for k in loops]
    out = {"loops": loops, "means": [round(m, 3) for m in means]}
    if len(loops) >= 3:
        b, ci, n = _ols([float(k) for k in loops], means)
        out["slope_w_per_loop"], out["slope_ci"] = b, ci
    if len(means) >= 2:
        out["first_minus_rest"] = means[0] - statistics.mean(means[1:])
    return out


# --- reporting --------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("--bin", type=float, default=5.0, help="content bin width (s)")
    ap.add_argument("--csv", default=None, help="write per-bin rows here")
    ap.add_argument("--pairs", default="gtv-firestick,xiaomi3-xiaomi")
    ap.add_argument("--descriptors", action="store_true",
                    help="correlate against content_descriptors.py output")
    ap.add_argument("--compare", default=None, metavar="JOB2",
                    help="per-box profile r against another job (same bin)")
    a = ap.parse_args()

    env, profs = load_profiles(a.job_id, a.bin)
    proto = env.get("protocol") or {}
    print(f"\n=== intra-content profile — job {a.job_id} "
          f"({env.get('template')}) ===")
    print(f"regime: realtime playback, {proto.get('window_s')}s window, "
          f"{a.bin:.0f}s content bins")
    if proto.get("regime_note"):
        print(f"CAVEAT: {proto['regime_note']}")
    if not profs:
        print("no device carried a usable content clock — nothing to profile")
        return

    print(f"\n{'device':<12}{'bins':>6}{'loops':>7}{'unaligned':>11}"
          f"{'segs':>6}{'head dip W':>15}{'drift W/loop':>16}{'1st-rest W':>12}")
    for dev, p in profs.items():
        n_loops = max((len(v) for v in p["per_bin"].values()), default=0)
        dip, dip_ci, _ = head_dip(p)
        dip_s = (f"{dip:+.3f}±{dip_ci:.3f}" if dip is not None and dip_ci
                 else (f"{dip:+.3f}" if dip is not None else "n/a (no head)"))
        flag = "  ⚠ not lower!" if (dip is not None and dip >= 0) else ""
        d = loop_drift(p)
        dr = (f"{d['slope_w_per_loop']:+.4f}±{d['slope_ci']:.4f}"
              if d.get("slope_w_per_loop") is not None else "—")
        fr = f"{d['first_minus_rest']:+.3f}" if "first_minus_rest" in d else "—"
        print(f"{dev:<12}{len(p['per_bin']):>6}{n_loops:>7}"
              f"{p['unaligned']:>11}{p['segments']:>6}{dip_s:>15}{dr:>16}{fr:>12}{flag}")

    for dev, p in profs.items():
        if p.get("marker") and p["marker"].get("n"):
            m = p["marker"]
            print(f"\nmarker vs screen ({dev}): n={m['n']} loops, median "
                  f"residual {m['median_residual_s']:+.2f}s (MAD {m['mad_s']}s)"
                  f" — software clock vs frames on the panel")

    # Is there any content structure to see, and at what granularity?
    env2 = env
    print("\n--- intra-content detectability (content bins only) ---")
    print(f"{'bin':>5}  " + "  ".join(f"{d[:9]:>9} SNR" for d in profs)
          + "   cross-device r (t)")
    for bw in (a.bin, a.bin * 2, a.bin * 4, a.bin * 6):
        sub = {r.get("device"): profile_row(r, bw)
               for r in (env2.get("runs") or []) if r.get("device") in profs}
        sub = {d: p for d, p in sub.items() if p}
        if len(sub) < 2:
            continue
        snrs = "  ".join(f"{(snr(p) or float('nan')):>13.2f}" for p in sub.values())
        ds = list(sub)
        rr = []
        for i in range(len(ds)):
            for j in range(i + 1, len(ds)):
                r, n, t = pearson(sub[ds[i]], sub[ds[j]])
                if r is not None:
                    rr.append(f"{ds[i]}~{ds[j]} {r:+.2f}(t={t:.1f})")
        print(f"{bw:>4.0f}s  {snrs}   " + " ".join(rr))
    print("SNR<1 = that box cannot resolve content structure from its own trace;\n"
          "significant cross-device r on independent meters still can.")

    # What in the content does the profile track?
    if a.descriptors:
        src = (proto.get("looped_marker") or {}).get("source")
        dpath = HERE.parent / "decode_bench"  # noqa: F841 (repo layout note)
        dfile = (Path("/srv/data/owl/decode-bench/streams/_descriptors")
                 / f"{Path(src).stem}.json") if src else None
        if not dfile or not dfile.exists():
            print(f"\n(no descriptors for {src!r} — run content_descriptors.py {src})")
        else:
            from content_descriptors import bin_descriptors
            doc = json.loads(dfile.read_text())
            head_s = next(iter(profs.values()))["head_s"]
            dbins = bin_descriptors(doc, a.bin, head_s)
            keys = ("bits_mbps", "motion", "edge", "luma", "i_frames")
            units = {"bits_mbps": "W/Mbps", "motion": "W/unit", "edge": "W/unit",
                     "luma": "W/unit", "i_frames": "W/I-frame"}
            print(f"\n--- power vs content descriptors ({src}, {a.bin:.0f}s bins) ---")
            print(f"{'device':<11}" + "".join(f"{k:>24}" for k in keys))
            print(f"{'':<11}" + "".join(f"{'r (t) · slope±ci':>24}" for _ in keys))
            for dev, p in profs.items():
                cells = []
                cb = [b for b in content_bins(p) if b in dbins]
                ys = bin_means(p, cb)
                for k in keys:
                    xs = [dbins[b].get(k) for b in cb]
                    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None]
                    if len(pairs) < 3 or len({x for x, _ in pairs}) < 3:
                        cells.append(f"{'—':>24}")
                        continue
                    r, n, t = _corr([x for x, _ in pairs], [y for _, y in pairs])
                    b, ci, _ = _ols([x for x, _ in pairs], [y for _, y in pairs])
                    cells.append(f"{r:+.2f}({t:+.1f}) {b:+.4f}±{ci:.4f}".rjust(24))
                print(f"{dev:<11}" + "".join(cells))
            print(f"units: {units}. Descriptors are content-side proxies "
                  f"(640-wide downscale): bits = delivered bitrate, motion = "
                  f"frame-difference energy, edge = Sobel energy, luma = mean Y.")
            # The descriptors are collinear on real content (motion blur
            # lowers edge energy; bright BBB skies are flat) — so also fit them
            # jointly and report STANDARDISED betas: which descriptor carries
            # the power variation once the others are held fixed, on a scale
            # that is comparable between boxes.
            try:
                import numpy as np
                pred = [k for k in ("edge", "motion", "luma", "bits_mbps")
                        if len({dbins[b].get(k) for b in dbins if k in dbins[b]}) > 3]
                print(f"\njoint OLS, standardised betas (sd W per sd descriptor), "
                      f"predictors {pred}:")
                print(f"{'device':<11}" + "".join(f"{k:>14}" for k in pred)
                      + f"{'R²':>8}{'n':>5}")
                for dev, p in profs.items():
                    cb = [b for b in content_bins(p) if b in dbins
                          and all(k in dbins[b] for k in pred)]
                    if len(cb) < len(pred) + 3:
                        continue
                    X = np.array([[dbins[b][k] for k in pred] for b in cb], float)
                    y = np.array(bin_means(p, cb), float)
                    Xs = (X - X.mean(0)) / X.std(0)
                    ys = (y - y.mean()) / y.std()
                    A = np.column_stack([Xs, np.ones(len(cb))])
                    beta, res, *_ = np.linalg.lstsq(A, ys, rcond=None)
                    r2 = 1 - float(res[0]) / len(cb) if len(res) else float("nan")
                    print(f"{dev:<11}" + "".join(f"{b:>+14.3f}" for b in beta[:-1])
                          + f"{r2:>8.2f}{len(cb):>5}")
            except Exception as e:                       # numpy optional
                print(f"(joint fit skipped: {e})")
            # what the descriptors themselves look like across the clip
            spread = {k: (min(d[k] for d in dbins.values() if k in d),
                          max(d[k] for d in dbins.values() if k in d))
                      for k in keys}
            print("descriptor range over content bins: " + ", ".join(
                f"{k} {lo:.2f}–{hi:.2f}" for k, (lo, hi) in spread.items()))

    # Same box, another run (or another codec / resolution of the same content)
    if a.compare:
        env_b, profs_b = load_profiles(a.compare, a.bin)
        print(f"\n--- per-box profile agreement: {a.job_id} "
              f"({env.get('template')}) vs {a.compare} ({env_b.get('template')}) ---")
        for dev in profs:
            if dev not in profs_b:
                continue
            r, n, t = pearson(profs[dev], profs_b[dev])
            ma = statistics.mean(bin_means(profs[dev], content_bins(profs[dev])))
            mb = statistics.mean(bin_means(profs_b[dev], content_bins(profs_b[dev])))
            print(f"{dev:<11} r={r:+.3f} (t={t:.1f}, n={n} shared content bins)"
                  f"   mean content W {ma:.3f} vs {mb:.3f}"
                  if r is not None else f"{dev:<11} too few shared bins")

    for pair in [x for x in a.pairs.split(",") if x.strip()]:
        try:
            da, db = pair.split("-", 1)
        except ValueError:
            continue
        if da not in profs or db not in profs:
            continue
        r, n_shared, t = pearson(profs[da], profs[db])
        print(f"\n--- {da} − {db} ---")
        print(f"profile correlation r={r:.3f} over {n_shared} content bins (t={t:.1f})"
              if r is not None else "profile correlation: too few bins")
        shared = sorted(set(content_bins(profs[da])) & set(content_bins(profs[db])))
        diffs = [statistics.mean(profs[da]["per_bin"][b])
                 - statistics.mean(profs[db]["per_bin"][b]) for b in shared]
        if diffs:
            m, ci, n = _mean_ci(diffs)
            print(f"mean per-bin ΔW {m:+.3f}" + (f" ±{ci:.3f} (n={n} bins)"
                                                 if ci else ""))
            print("widest bins: " + ", ".join(
                f"{b*a.bin:.0f}s {d:+.2f}W" for b, d in
                sorted(zip(shared, diffs), key=lambda kv: -abs(kv[1]))[:5]))

    if a.csv:
        with open(a.csv, "w", newline="") as f:
            wtr = csv.writer(f)
            wtr.writerow(["device", "bin_start_s", "is_head", "n_loops",
                          "mean_w", "sd_w", "ci95_w"])
            for dev, p in profs.items():
                for b in sorted(p["per_bin"]):
                    vals = p["per_bin"][b]
                    m, ci, n = _mean_ci(vals)
                    sd = statistics.stdev(vals) if len(vals) > 1 else ""
                    wtr.writerow([dev, round(b * a.bin, 1),
                                  int(b * a.bin < p["head_s"]), n,
                                  round(m, 4), round(sd, 4) if sd != "" else "",
                                  round(ci, 4) if ci else ""])
        print(f"\ncsv -> {a.csv}")


if __name__ == "__main__":
    main()
