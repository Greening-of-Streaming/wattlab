#!/usr/bin/env python3
"""
rescore-bitrate-ext-v0.py — fix the VMAF-version mismatch in the 2026-08-28
bitrate-ceiling extension.

The extension campaign ran under the live service's current default
(vmaf_model=v1), but the canonical dataset it's meant to extend
(encode_parity_nvenc_24c_2026-06-20.json, 207 rows) is v0.6.1. Rather than
re-running the full metered campaign (another ~28 min touching the P110),
this re-runs each row's EXACT stored ffmpeg_cmd (deterministic CBR encode,
same input/settings -> bit-identical output) against the still-present
trimmed reference clips, and scores the result under v0.6.1 via an
in-process settings override — video.compute_vmaf(s=...) — that does NOT
touch the live service's settings.json, so it has zero effect on what any
concurrent visitor's job gets scored with.

No power measurement, no focus mode, no lock/pause needed — this is pure
CPU/GPU re-encode + score, energy-irrelevant. Adds a `vmaf_v0` field to each
row alongside the existing v1 `vmaf` field; does not touch delta_w/wh_per_min
(those are valid regardless of VMAF model).
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "wattlab_service"))
import video     # noqa: E402
import quality   # noqa: E402
import settings as cfg  # noqa: E402

ARTIFACT = Path(__file__).resolve().parent.parent / "results" / "calibration" / \
    "encode_parity_nvenc_24c_2026-08-28_bitrate_ext.json"
REF_DIR = Path("/tmp/wattlab_parity_clips")
OUT_DIR = Path("/tmp/wattlab_rescore_v0")

V0_SETTINGS = {**cfg.load(), "vmaf_model": "v0"}


REF_STEM = {"meridian_120s": "meridian_120s", "bbb_120s": "bbb_120s",
            "kranjska_120s": "kranjska_dh_120s"}  # CLIPS dict key != file stem for kranjska


def ref_for(clip_key: str) -> Path:
    return REF_DIR / f"{REF_STEM.get(clip_key, clip_key)}_30s.mp4"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    d = json.loads(ARTIFACT.read_text())
    rows = d["rows"]
    print(f"[rescore] {len(rows)} rows to re-encode + score under vmaf_model=v0")

    for i, r in enumerate(rows):
        if "vmaf_v0" in r:
            continue  # already done in a prior pass — don't redo deterministic work
        ref = ref_for(r["clip"])
        if not ref.exists():
            print(f"  {i+1}/{len(rows)}: SKIP {r['clip']}/{r['codec']}/{r['profile']} "
                  f"— reference clip missing: {ref}")
            r["vmaf_v0_error"] = "reference clip missing"
            continue

        out_path = OUT_DIR / f"row{i:03d}_{r['clip']}_{r['codec']}_{r['profile']}_{r['target_bitrate_kbps']}.mp4"
        cmd = r["ffmpeg_cmd"]
        # Original cmd already has correct absolute input/output paths baked in
        # (points at this same REF_DIR clip and a /tmp/wattlab_uploads/... out
        # path) — redirect only the output to our own scratch dir so nothing
        # collides with a live job, input path is reused as-is.
        cmd_fixed = cmd
        # find "-y ... {output}" — the stored cmd's last arg before -progress is
        # the original output path; swap it for ours.
        parts = cmd.split()
        # locate the original out path: it's the token right before "-progress"
        # if present, else the last .mp4 token that isn't the input.
        orig_out = None
        for tok in parts:
            if tok.endswith(".mp4") and "wattlab_uploads" in tok:
                orig_out = tok
                break
        if orig_out:
            cmd_fixed = cmd.replace(orig_out, str(out_path))
        else:
            print(f"  {i+1}/{len(rows)}: WARN could not locate original output path in "
                  f"stored ffmpeg_cmd, appending output manually")
            cmd_fixed = cmd + f" {out_path}"

        print(f"  {i+1}/{len(rows)}: {r['clip']:15s} {r['codec']:5s} {r['profile']:12s} "
              f"{r['target_bitrate_kbps']}k ...", end=" ", flush=True)

        try:
            subprocess.run(cmd_fixed, shell=True, check=True,
                            capture_output=True, text=True, timeout=180)
            vmaf_v0 = video.compute_vmaf(out_path, ref, s=V0_SETTINGS)
            r["vmaf_v0"] = vmaf_v0
            r["vmaf_v0_model"] = quality.vmaf_model_id(V0_SETTINGS)
            print(f"vmaf_v0={vmaf_v0}  (v1 was {r.get('vmaf')})")
        except subprocess.CalledProcessError as exc:
            print(f"ENCODE FAILED: {exc.stderr[-300:] if exc.stderr else exc}")
            r["vmaf_v0_error"] = f"encode failed: {exc}"
        except Exception as exc:
            print(f"SCORE FAILED: {exc!r}")
            r["vmaf_v0_error"] = f"score failed: {exc!r}"
        finally:
            out_path.unlink(missing_ok=True)

        # checkpoint after every row
        ARTIFACT.write_text(json.dumps(d, indent=2))

    ok = sum(1 for r in rows if "vmaf_v0" in r)
    print(f"\n[rescore] done: {ok}/{len(rows)} rows now carry vmaf_v0. Artifact updated in place: {ARTIFACT}")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
