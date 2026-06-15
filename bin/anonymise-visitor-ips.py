#!/usr/bin/env python3
"""
anonymise-visitor-ips — one-off (idempotent) data migration.

Pre-2026-06 results stored anonymous visitors' visitor_key as 'a:<raw IP>'.
That raw IP is personal data (GDPR). This rewrites every such key in place to
'a:<pseudonymised token>' using analytics.hash_ip — the SAME transform the live
code now applies — so a returning visitor still matches their own results
(CR-026) but no raw address remains on disk.

Idempotent: keys that are already tokens (not parseable as an IP) are skipped.
Dry-run by default; pass --apply to write.

Usage:
    python3 bin/anonymise-visitor-ips.py [--apply]
"""
import argparse
import ipaddress
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "wattlab_service"))
import analytics  # noqa: E402

RESULTS_DIR = Path("/home/gos/wattlab/results")


def _is_raw_ip(token: str) -> bool:
    try:
        ipaddress.ip_address(token)
        return True
    except ValueError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    changed = scanned = 0
    for f in RESULTS_DIR.glob("*/*.json"):
        scanned += 1
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        vk = data.get("visitor_key")
        if not (isinstance(vk, str) and vk.startswith("a:")):
            continue
        token = vk[2:]
        if not _is_raw_ip(token):
            continue  # already pseudonymised
        new_vk = f"a:{analytics.hash_ip(token)}"
        changed += 1
        print(f"{'rewrite' if args.apply else 'would rewrite'}: {f.name}  {vk} -> {new_vk}")
        if args.apply:
            data["visitor_key"] = new_vk
            f.write_text(json.dumps(data, indent=2))

    verb = "rewrote" if args.apply else "would rewrite"
    print(f"\nscanned {scanned} result files; {verb} {changed} raw-IP key(s).")
    if not args.apply and changed:
        print("re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
