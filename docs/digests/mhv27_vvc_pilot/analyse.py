#!/usr/bin/env python3
"""MHV'27 VVC pilot — tables, CSV and figures from the stored artifacts (read-only).

Inputs : results/calibration/_staging/mhv27_vvc_pilot_encode_*.json   (GoS1 encode grid)
         /srv/data/owl/mhv27_vvc_pilot/{gos1,gos2,pi5}_decode.jsonl  (decode benches; any may be absent)
Outputs: runs_encode.csv, runs_decode.csv, summary.md (tables pasted into the digest),
         fig_encode_energy_vs_vmaf.png, fig_decode.png
Run with a Python that has numpy + matplotlib, e.g. /srv/data/owl/figenv/bin/python analyse.py

Stats: per-point mean ± t-CI (df = n-1). Iso-VMAF-92 values are linear interpolation between the two
measured points that bracket VMAF 92 (as make_iso_vmaf_table.py), on per-point means; their 95 % intervals
and those of every ratio come from a bootstrap that resamples the reps of each point (10 000 draws).
Decode rows on GoS2/Pi meters are also re-flagged on fresh samples (consecutive identical readings
collapsed, as docs/decode_p110_refresh_audit_2026-10-06.md), with that node's own settings.
"""
import csv, glob, json, math, statistics as st, sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "wattlab_service"))
import confidence as conf_mod   # noqa: E402

DATA = Path("/srv/data/owl/mhv27_vvc_pilot")
TARGET = 92.0
RNG = np.random.default_rng(20261022)
B = 10_000
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571}
LABEL = {"h265": "HEVC (x265 Main10)", "av1": "AV1 (SVT-AV1 10-bit)", "vvc": "VVC (VVenC)"}
NODE_SETTINGS = {"gos1": json.loads((REPO / "settings.json").read_text()),
                 "gos2": json.loads(((DATA / "gos2_settings.json") if (DATA / "gos2_settings.json").exists()
                                     else (HERE / "raw/gos2_settings.json")).read_text())}


def ci(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return (xs[0] if xs else None), None
    return st.mean(xs), T975.get(len(xs) - 1, 1.96) * st.stdev(xs) / math.sqrt(len(xs))


def fmt(m, h, nd=3):
    if m is None:
        return "—"
    return f"{m:.{nd}f}" if h is None else f"{m:.{nd}f} ± {h:.{nd}f}"


def interp_at(xs, ys, x0):
    """Linear interpolation of y at x0 over points sorted by x; None if x0 is outside the range."""
    pts = sorted(zip(xs, ys))
    for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
        if xa <= x0 <= xb and xb > xa:
            return ya + (yb - ya) * (x0 - xa) / (xb - xa)
    return None


# ---------------------------------------------------------------- encode
CLIP_TITLE = {"meridian_120s": "Meridian", "football_30s": "Football (lab-internal source)"}


def load_encode():
    """Latest artifact per clip → {clip: (art, rows, path)}; staging first, raw/ copies as fallback."""
    files = sorted(glob.glob(str(REPO / "results/calibration/_staging/mhv27_vvc_pilot_encode_*.json"))) \
        or sorted(glob.glob(str(HERE / "raw/mhv27_vvc_pilot_encode_*.json")))
    out = {}
    for f in files:
        art = json.loads(Path(f).read_text())
        out[art["protocol"]["clip"]] = (art, [r for r in art["rows"] if not r.get("error")], f)
    return out


def encode_points(rows):
    pts = defaultdict(list)
    for r in rows:
        pts[(r["codec"], r["target_kbps"])].append(r)
    return pts


def iso_values(per_point):
    """per_point: {codec: [(vmaf, kbps, wh1000), ...]} means → {codec: (kbps@92, wh@92)}."""
    out = {}
    for c, p in per_point.items():
        v = [x[0] for x in p]
        out[c] = (interp_at(v, [x[1] for x in p], TARGET), interp_at(v, [x[2] for x in p], TARGET))
    return out


def bootstrap_iso(pts):
    codecs = sorted({c for c, _ in pts})
    draws = defaultdict(list)
    for _ in range(B):
        per = defaultdict(list)
        for (c, k), rs in pts.items():
            idx = RNG.integers(0, len(rs), len(rs))
            sel = [rs[i] for i in idx]
            per[c].append((np.mean([s["vmaf"] for s in sel]),
                           np.mean([s["achieved_bitrate_bps"] / 1000 for s in sel]),
                           np.mean([s["wh_per_1000_frames"] for s in sel])))
        iso = iso_values(per)
        for c in codecs:
            draws[c].append(iso[c])
    return draws


def pct(a):
    a = [x for x in a if x is not None and not math.isnan(x)]
    return (np.percentile(a, 2.5), np.percentile(a, 97.5)) if len(a) > 100 else (None, None)


def encode_section(art, rows, path, lines):
    pts = encode_points(rows)
    lines.append(f"## Encode (GoS1), {CLIP_TITLE.get(art['protocol']['clip'], art['protocol']['clip'])} — "
                 f"artifact `{Path(path).name}`\n")
    lines.append(f"{len(rows)} rows, complete={art.get('complete')}. Per point: mean ± 95 % t-CI over reps.\n")
    lines.append("| Codec | Target kb/s | Actual kb/s | VMAF v0.6.1 | Wh/1000 frames | ΔW (W) | Encode s / pass | n | flags | elevated |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    means = defaultdict(list)
    for (c, k) in sorted(pts, key=lambda x: (["h265", "av1", "vvc"].index(x[0]), x[1])):
        rs = pts[(c, k)]
        kb = ci([r["achieved_bitrate_bps"] / 1000 for r in rs])
        vm = ci([r["vmaf"] for r in rs])
        wh = ci([r["wh_per_1000_frames"] for r in rs])
        dw = ci([r["delta_w"] for r in rs])
        es = ci([st.mean(r["encode_wall_s"]) for r in rs])
        flags = "".join(r["confidence_flag"] or "?" for r in rs)
        elev = sum(1 for r in rs if r.get("baseline_elevated"))
        means[c].append((vm[0], kb[0], wh[0], wh[1] or 0, vm[1] or 0))
        lines.append(f"| {c} | {k} | {fmt(*kb, 0)} | {fmt(*vm, 2)} | {fmt(*wh, 4)} | {fmt(*dw, 1)} | "
                     f"{fmt(*es, 1)} | {len(rs)} | {flags} | {elev} |")
    iso = iso_values({c: [(m[0], m[1], m[2]) for m in v] for c, v in means.items()})
    draws = bootstrap_iso(pts)
    lines.append("\n### At VMAF 92 (interpolated; 95 % bootstrap interval)\n")
    lines.append("| Codec | kb/s @ VMAF 92 | Wh/1000 frames @ VMAF 92 |")
    lines.append("|---|---|---|")
    for c in ["h265", "av1", "vvc"]:
        if c not in iso:
            continue
        kb_lo, kb_hi = pct([d[0] for d in draws[c]])
        wh_lo, wh_hi = pct([d[1] for d in draws[c]])
        k0, w0 = iso[c]
        lines.append(f"| {LABEL[c]} | {k0:.0f} [{kb_lo:.0f}, {kb_hi:.0f}] | {w0:.4f} [{wh_lo:.4f}, {wh_hi:.4f}] |"
                     if k0 is not None and w0 is not None and kb_lo is not None else f"| {LABEL[c]} | — | — |")
    lines.append("\n| Ratio at VMAF 92 | Energy ratio [95 %] | Bitrate change [95 %] |")
    lines.append("|---|---|---|")
    for other in ["h265", "av1"]:
        if "vvc" not in draws or other not in draws:
            continue
        er = [a[1] / b[1] for a, b in zip(draws["vvc"], draws[other]) if a[1] and b[1]]
        br = [a[0] / b[0] - 1 for a, b in zip(draws["vvc"], draws[other]) if a[0] and b[0]]
        e0 = iso["vvc"][1] / iso[other][1]
        b0 = iso["vvc"][0] / iso[other][0] - 1
        elo, ehi = pct(er)
        blo, bhi = pct(br)
        lines.append(f"| VVC vs {LABEL[other]} | {e0:.2f}× [{elo:.2f}, {ehi:.2f}] | "
                     f"{b0 * 100:+.0f} % [{blo * 100:+.0f}, {bhi * 100:+.0f}] |")
    # Conservative envelope: interpolate the per-point t-CI bounds instead of the means (a bootstrap over
    # n=3 reps understates spread). Ratio bounds pair the extreme ends.
    env = {}
    for c, v in means.items():
        vm = [m[0] for m in v]
        env[c] = (interp_at(vm, [m[2] - m[3] for m in v], TARGET), interp_at(vm, [m[2] + m[3] for m in v], TARGET))
    lines.append("\nConservative interval (per-point 95 % t-CI bounds interpolated, extremes paired):\n")
    for c in ["h265", "av1", "vvc"]:
        if c in env and None not in env[c]:
            lines.append(f"- {LABEL[c]}: Wh/1000 frames @ VMAF 92 in [{env[c][0]:.4f}, {env[c][1]:.4f}]")
    for other in ["h265", "av1"]:
        if None not in env.get("vvc", (None,)) and None not in env.get(other, (None,)):
            lines.append(f"- VVC vs {LABEL[other]}: energy ratio in "
                         f"[{env['vvc'][0] / env[other][1]:.2f}×, {env['vvc'][1] / env[other][0]:.2f}×]")
    # matched bitrate: interpolate energy vs actual kb/s inside the range all three codecs cover
    lo = max(min(m[1] for m in v) for v in means.values())
    hi = min(max(m[1] for m in v) for v in means.values())
    if lo < hi:
        kb0 = round((lo + hi) / 2 / 50) * 50
        lines.append(f"\n### At matched bitrate ({kb0} kb/s actual; interpolated, 95 % bootstrap interval)\n")
        lines.append("| Codec | VMAF @ matched | Wh/1000 frames @ matched |")
        lines.append("|---|---|---|")
        mdraw = defaultdict(list)
        for _ in range(B // 5):
            for c in means:
                sel = {k: [pts[(c, k)][i] for i in RNG.integers(0, len(pts[(c, k)]), len(pts[(c, k)]))]
                       for (cc, k) in pts if cc == c}
                kbs = [np.mean([s["achieved_bitrate_bps"] / 1000 for s in v]) for v in sel.values()]
                mdraw[c].append((interp_at(kbs, [np.mean([s["vmaf"] for s in v]) for v in sel.values()], kb0),
                                 interp_at(kbs, [np.mean([s["wh_per_1000_frames"] for s in v]) for v in sel.values()], kb0)))
        for c in ["h265", "av1", "vvc"]:
            v0 = interp_at([m[1] for m in means[c]], [m[0] for m in means[c]], kb0)
            w0 = interp_at([m[1] for m in means[c]], [m[2] for m in means[c]], kb0)
            wl, wh_ = pct([d[1] for d in mdraw[c]])
            lines.append(f"| {LABEL[c]} | {v0:.2f} | {w0:.4f} [{wl:.4f}, {wh_:.4f}] |")
        for other in ["h265", "av1"]:
            er = [a[1] / b[1] for a, b in zip(mdraw["vvc"], mdraw[other]) if a[1] and b[1]]
            elo, ehi = pct(er)
            e0 = interp_at([m[1] for m in means["vvc"]], [m[2] for m in means["vvc"]], kb0) / \
                interp_at([m[1] for m in means[other]], [m[2] for m in means[other]], kb0)
            lines.append(f"\nVVC vs {LABEL[other]} at {kb0} kb/s: energy {e0:.2f}× [{elo:.2f}, {ehi:.2f}]")
    return means


def write_encode_csv(rows):
    keys = ["clip", "codec", "target_kbps", "rep", "at", "achieved_kbps", "vmaf", "vmaf_model", "n_encodes",
            "encode_wall_s_mean", "frames_encoded", "delta_t_s", "w_base", "delta_w", "delta_e_wh_total",
            "wh_per_1000_frames", "wh_per_min_video", "poll_count", "confidence_flag", "confidence_positive",
            "baseline_elevated", "cache_evicted", "ffmpeg_cmd"]
    with open(HERE / "runs_encode.csv", "w", newline="") as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        for r in rows:
            w.writerow({**{k: r.get(k) for k in keys},
                        "achieved_kbps": round(r["achieved_bitrate_bps"] / 1000, 1),
                        "encode_wall_s_mean": round(st.mean(r["encode_wall_s"]), 1),
                        "confidence_positive": (r.get("confidence") or {}).get("confidence_positive")})


# ---------------------------------------------------------------- decode
def fresh(xs):
    out = xs[:1]
    for a, b in zip(xs, xs[1:]):
        if b != a:
            out.append(b)
    return out


def fresh_flag(r, s):
    b, t = r.get("baseline_samples_w") or [], r.get("task_samples_w") or []
    if len(b) < 2 or len(t) < 2:
        return None
    fb, ft = fresh(b), fresh(t)
    c = conf_mod.confidence(st.mean(ft) - st.mean(fb), len(t), st.mean(fb),
                            baseline_samples_w=fb if len(fb) > 1 else fb * 2,
                            task_samples_w=ft if len(ft) > 1 else ft * 2, s=s)
    return c.get("flag")


def load_decode():
    rows = []
    for node in ("gos1", "gos2", "pi5"):
        p = DATA / f"{node}_decode.jsonl"
        if not p.exists():
            p = HERE / "raw" / f"{node}_decode.jsonl"
        if p.exists():
            for line in p.read_text().splitlines():
                r = json.loads(line)
                if not r.get("error"):
                    r["node"] = node
                    rows.append(r)
    return rows


def decode_section(rows, lines):
    lines.append("\n## Decode\n")
    lines.append("Per cell: mean ± 95 % t-CI over reps. `fresh` = flags recomputed on fresh samples "
                 "(P110 fw 1.3.1 holds readings ~2 s below ~12 W).\n")
    lines.append("| Node | Decoder | Regime | ΔW (W) | Wh/1000 frames | speed× (median) | n | flags | fresh flags | elevated |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    cells = defaultdict(list)
    for r in rows:
        regime = r["regime"] + ("/threads1" if r.get("threads1") else "")
        cells[(r["node"], r["arm"], regime)].append(r)
    out = {}
    for (node, arm, regime), rs in sorted(cells.items()):
        dw = ci([r["delta_w"] for r in rs])
        wh = ci([r["wh_per_1000_frames"] for r in rs])
        sp = st.median([x for r in rs for x in r["speed_x"] if x])
        flags = "".join(r["confidence_flag"] or "?" for r in rs)
        s = NODE_SETTINGS.get(node, NODE_SETTINGS["gos1"])
        fr = "".join(fresh_flag(r, s) or "?" for r in rs)
        elev = sum(1 for r in rs if r.get("baseline_elevated"))
        out[(node, arm, regime)] = (dw, wh, sp, flags)
        lines.append(f"| {node} | {arm} | {regime} | {fmt(*dw, 2)} | {fmt(*wh, 5)} | {sp:.2f} | {len(rs)} | "
                     f"{flags} | {fr} | {elev} |")
    return out


def write_decode_csv(rows):
    keys = ["node", "host", "arm", "regime", "threads1", "rep", "at", "stream", "ffmpeg_version", "cmd",
            "n_invocations", "frames", "speed_x", "delta_t_s", "w_base", "delta_w", "delta_e_wh",
            "wh_per_1000_frames", "poll_count", "confidence_flag", "fresh_flag", "baseline_elevated",
            "hw_fallback"]
    with open(HERE / "runs_decode.csv", "w", newline="") as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        for r in rows:
            s = NODE_SETTINGS.get(r["node"], NODE_SETTINGS["gos1"])
            w.writerow({**{k: r.get(k) for k in keys}, "speed_x": " ".join(str(x) for x in r["speed_x"]),
                        "fresh_flag": fresh_flag(r, s)})


# ---------------------------------------------------------------- figures
def figures(means_by_clip, dec):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"h265": "#1f77b4", "av1": "#ff7f0e", "vvc": "#2ca02c"}
    clips = [c for c in CLIP_TITLE if c in means_by_clip]
    fig, axes = plt.subplots(1, len(clips), figsize=(7 * len(clips), 4.5), squeeze=False)
    for ax, clip in zip(axes[0], clips):
        means = means_by_clip[clip]
        for c in ["h265", "av1", "vvc"]:
            if c not in means:
                continue
            m = sorted(means[c])
            ax.errorbar([x[0] for x in m], [x[2] for x in m], yerr=[x[3] for x in m], xerr=[x[4] for x in m],
                        marker="o", capsize=3, label=LABEL[c], color=colors[c])
        ax.axvline(TARGET, ls=":", c="grey")
        ax.set_xlabel("VMAF v0.6.1 (1080p, vs 4K source)")
        ax.set_ylabel("Encode energy above idle (Wh / 1000 frames)")
        ax.set_title(f"{CLIP_TITLE[clip]} 30 s", fontsize=10)
        ax.set_ylim(bottom=0)
        ax.legend(fontsize=8)
    fig.suptitle("GoS1 CPU encode (Ryzen 9 7900), 10-bit, default presets (n=3, 95 % CI)", fontsize=10)
    fig.tight_layout()
    fig.savefig(HERE / "fig_encode_energy_vs_vmaf.png", dpi=150)

    if dec:
        names = {"vvc": "VVC sw", "hevc": "HEVC sw", "dav1d": "AV1 dav1d", "hevc_vt": "HEVC hw (VT)",
                 "av1_vt": "AV1 hw (VT)"}
        col = {"vvc": "#2ca02c", "hevc": "#1f77b4", "dav1d": "#ff7f0e", "hevc_vt": "#9ecae1", "av1_vt": "#fdd0a2"}
        fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), sharey=True)
        for ax, regime, title in ((axes[0], "paced", "Paced playback (-re), 1080p59.94"),
                                  (axes[1], "afap", "As fast as possible, default threads")):
            ks = [k for k in sorted(dec, key=lambda k: (k[0], list(names).index(k[1]))) if k[2] == regime]
            ax.bar(range(len(ks)), [dec[k][1][0] for k in ks], yerr=[dec[k][1][1] or 0 for k in ks],
                   capsize=3, color=[col[k[1]] for k in ks])
            ax.set_xticks(range(len(ks)))
            ax.set_xticklabels([f"{ {'gos1': 'GoS1', 'gos2': 'GoS2', 'pi5': 'Pi 5'}[k[0]] }\n{names[k[1]]}" for k in ks],
                               fontsize=7, rotation=45, ha="right")
            ax.set_yscale("log")
            ax.set_title(title, fontsize=10)
        axes[0].set_ylabel("Decode energy above idle (Wh / 1000 frames, log)")
        fig.suptitle("Decode of the VMAF≈92 streams: GoS1 Ryzen 9 7900, GoS2 Apple M6, Pi 5 (paced only) (n=3, 95 % CI)",
                     fontsize=10)
        fig.tight_layout()
        fig.savefig(HERE / "fig_decode.png", dpi=150)


def main():
    lines = []
    enc = load_encode()
    means = {}
    all_rows = []
    for clip in [c for c in CLIP_TITLE if c in enc]:
        art, rows, path = enc[clip]
        means[clip] = encode_section(art, rows, path, lines)
        all_rows += [{**r, "clip": clip} for r in rows]
    write_encode_csv(all_rows)
    drows = load_decode()
    dec = decode_section(drows, lines) if drows else {}
    if drows:
        write_decode_csv(drows)
    figures(means, dec)
    (HERE / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
