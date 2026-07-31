#!/usr/bin/env python3
"""campaign_summary.py — collate campaign results.jsonl into a readable report.

Run:  python3 campaign_summary.py            (prints to stdout)
Safe to run mid-campaign — reflects whatever's completed so far.
"""
import json
import os

OUT = "/srv/data/owl/campaign_2026-07-31"
RESULTS = os.path.join(OUT, "results.jsonl")
DEVICES = ["pi5", "firestick", "gtv", "bbox", "c2"]


def load():
    rows = []
    if not os.path.exists(RESULTS):
        return rows
    for line in open(RESULTS):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def cell_key(rec):
    return (rec.get("cell") or {}).get("key", "?")


def fmt(rows, name):
    r = rows.get(name) or {}
    dw = r.get("delta_w")
    if r.get("error"):
        return "ERR"
    if dw is None:
        return "—"
    conf = r.get("confidence") or {}
    flag = conf.get("flag") or r.get("flag") or ""
    n = r.get("n_task")
    return f"{dw:+.2f}{flag}({n})"


def main():
    recs = load()
    by_key = {cell_key(r): r for r in recs}
    print(f"# Decode campaign — {len(recs)} cells recorded\n")

    print("## A — Duration study (BBB/Meridian/Kranjska H.264, all-5 parallel)")
    print("cell shows ΔW±flag(n_task); flag 🟢 repeatable / 🟡 early / 🔴 idle\n")
    hdr = f"{'':22} " + " ".join(f"{d:>16}" for d in DEVICES)
    for fam in ("bbb", "meridian", "kranjska"):
        print(f"### {fam}")
        print(hdr)
        for dur in (30, 300, 1200, 3540):
            k = f"A_dur{dur}_{fam}"
            rec = by_key.get(k)
            lbl = f"{dur}s" if dur < 300 else f"{dur // 60}m"
            if not rec:
                print(f"{lbl:22} " + "  (pending)")
                continue
            rows = rec.get("rows", {})
            print(f"{lbl:22} " + " ".join(f"{fmt(rows, d):>16}" for d in DEVICES))
        print()

    print("## B — Codec suite (150 s): parallel vs one-at-a-time")
    for fam in ("bbb", "meridian", "kranjska"):
        for cod in ("h264", "h265", "av1"):
            par = by_key.get(f"B_all_{fam}_{cod}")
            print(f"### {fam} {cod}")
            if par:
                rows = par.get("rows", {})
                print(f"  parallel : " +
                      " ".join(f"{d}={fmt(rows, d)}" for d in DEVICES))
            seqbits = []
            for d in DEVICES:
                s = by_key.get(f"B_seq_{fam}_{cod}_{d}")
                if s:
                    seqbits.append(f"{d}={fmt(s.get('rows', {}), d)}")
            if seqbits:
                print("  sequential: " + " ".join(seqbits))
            if not par and not seqbits:
                print("  (pending)")
        print()


if __name__ == "__main__":
    main()
