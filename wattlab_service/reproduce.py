"""CR-040 — "Reproduce this result" downloadable bundle (video-only V1).

Given a stored video result, build a self-contained zip a visitor can run on
their own GoS1-class server to check their numbers against OWL's:

  cmd.sh        — prints + runs each ffmpeg encode, timing wall-clock.
  expected.json — OWL's measured numbers + a k=3σ envelope from the calibration
                  variance, for a numeric pass/fail.
  compare.py    — stdlib only; reads expected.json + your_run.json and prints a
                  green/yellow/red verdict per run against the envelope.
  README.md     — prerequisites, running, interpreting (envelope, not identicality).

The Meridian asset is linked (CC BY 4.0), never shipped (812 MB).

Shape-agnostic: walks the result for any block carrying both a `transcode`
(with an ffmpeg_cmd) and an `energy` block, so single / both / all_codecs all
produce the right number of runs without per-mode wiring.
"""
import io
import json
import re
import zipfile
from datetime import datetime

# OWL runs on one machine and results don't store a per-run HW fingerprint, so
# the bundle records GoS1's. Keep in sync with CLAUDE.md "GoS1 Server".
_HARDWARE = {
    "cpu": "AMD Ryzen 9 7900 (24 cores)",
    "gpu": "AMD Radeon RX 7800 XT (VAAPI / ROCm)",
    "ram_gb": 61,
    "kernel": "6.17",
    "os": "Ubuntu 24.04",
}

_MERIDIAN = {
    "name": "meridian_120s.mp4",
    "derived_from": "Meridian — Netflix Open Content",
    "license": "CC BY 4.0",
    "url": "https://opencontent.netflix.com/",
    "note": "Not shipped (812 MB source). Provide your own clip; OWL used a "
            "120 s 1080p cut of Meridian.",
}


def _collect_encodes(obj, out):
    """Walk a result tree; collect every block that is itself an encode unit —
    one carrying both a `transcode` (with ffmpeg_cmd) and an `energy` block."""
    if isinstance(obj, dict):
        t, e = obj.get("transcode"), obj.get("energy")
        if (isinstance(t, dict) and t.get("ffmpeg_cmd")
                and isinstance(e, dict) and e.get("delta_e_wh") is not None):
            out.append({
                "label": obj.get("preset_label") or obj.get("preset_key") or "encode",
                "ffmpeg_cmd": t["ffmpeg_cmd"],
                "ffmpeg_version": t.get("ffmpeg_version"),
                "delta_w_mean": e.get("delta_w"),
                "delta_e_wh": e.get("delta_e_wh"),
                "duration_s": e.get("delta_t_s") or t.get("duration_s"),
                "confidence": (e.get("confidence") or {}).get("flag"),
            })
        for v in obj.values():
            _collect_encodes(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_encodes(v, out)


def _bounds(delta_e_wh, variance_pct, k=3):
    """k-sigma envelope on ΔE from the calibration CV (variance_pct)."""
    if delta_e_wh is None or variance_pct is None:
        return None
    frac = (variance_pct / 100.0) * k
    return {
        "low": round(delta_e_wh * (1 - frac), 6),
        "high": round(delta_e_wh * (1 + frac), 6),
        "variance_pct": variance_pct,
        "k_sigma": k,
    }


def _sanitize_cmd(cmd, idx):
    """Make an OWL ffmpeg command runnable on a visitor's machine: drop the
    privileged `nice`, parameterise the binary + input, and write output local."""
    c = cmd.replace("nice -n -5 ", "")
    c = c.replace("/usr/local/bin/ffmpeg-master", "${FFMPEG:-ffmpeg}")
    c = re.sub(r"-i\s+\S+\.mp4", '-i "$INPUT"', c, count=1)
    c = re.sub(r"/tmp/wattlab_uploads/\S+\.mp4", f"./owl_out_{idx}.mp4", c)
    c = c.replace(" -progress pipe:1 -nostats", "")
    return c


def _cmd_sh(runs):
    out = [
        "#!/usr/bin/env bash",
        "# OWL 'Reproduce this' — runs each encode and times wall-clock.",
        "# Set INPUT to your own clip:  INPUT=/path/clip.mp4 bash cmd.sh",
        "# You measure wall POWER yourself (Tapo P110 / PDU / Kill-A-Watt) and",
        "# record ΔWh per run into your_run.json (see README.md).",
        "set -euo pipefail",
        ': "${INPUT:?Set INPUT=/path/to/your_clip.mp4}"',
        "",
    ]
    for i, r in enumerate(runs, 1):
        out += [
            f'echo "=== Run {i}/{len(runs)}: {r["label"]} '
            f'(OWL: {r["delta_e_wh"]} Wh, {r["duration_s"]} s) ==="',
            "start=$(date +%s.%N)",
            _sanitize_cmd(r["ffmpeg_cmd"], i),
            "end=$(date +%s.%N)",
            'printf "elapsed: %.1f s\\n\\n" "$(echo "$end - $start" | bc)"',
            "",
        ]
    return "\n".join(out) + "\n"


_COMPARE_PY = '''#!/usr/bin/env python3
"""Compare your reproduction against OWL's expected.json (stdlib only).

Usage:
  python3 compare.py                # prints a your_run.json template
  python3 compare.py your_run.json  # prints per-run verdicts
"""
import json
import sys


def main():
    exp = json.load(open("expected.json"))
    path = sys.argv[1] if len(sys.argv) > 1 else "your_run.json"
    try:
        yours = json.load(open(path))
    except FileNotFoundError:
        tmpl = {"runs": [{"label": r["label"], "delta_e_wh": 0.0,
                          "duration_s": 0.0} for r in exp["runs"]]}
        print("No " + path + " yet. Fill in your measured numbers:")
        print(json.dumps(tmpl, indent=2))
        return 1
    ymap = {r.get("label"): r for r in yours.get("runs", [])}
    k = (exp["runs"][0].get("bounds_delta_e_wh") or {}).get("k_sigma", 3)
    print("OWL result " + str(exp.get("owl_result")) +
          "  (k=" + str(k) + " sigma envelope)")
    print()
    worst = "green"
    for r in exp["runs"]:
        y = ymap.get(r["label"])
        b = r.get("bounds_delta_e_wh") or {}
        print("  " + r["label"])
        print("    OWL dE: " + str(r["delta_e_wh"]) + " Wh   envelope: [" +
              str(b.get("low")) + ", " + str(b.get("high")) + "]")
        if not y or not y.get("delta_e_wh"):
            print("    yours : (not provided)")
            print()
            worst = "red"
            continue
        yv = y["delta_e_wh"]
        lo, hi = b.get("low"), b.get("high")
        within = lo is not None and lo <= yv <= hi
        near = lo is not None and lo * 0.9 <= yv <= hi * 1.1
        if within:
            verdict = "GREEN  within envelope"
        elif near:
            verdict = "YELLOW near envelope"
            if worst == "green":
                worst = "yellow"
        else:
            verdict = "RED    outside envelope"
            worst = "red"
        diff = (yv - r["delta_e_wh"]) / r["delta_e_wh"] * 100
        print("    yours : " + str(yv) + " Wh   (" + format(diff, "+.1f") +
              "% vs OWL)   -> " + verdict)
        print()
    print("Overall: " + worst.upper())
    print("Note: " + str(exp.get("comparison_note", "")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _readme(job_id, runs):
    rows = "\n".join(
        f"- **{r['label']}** — OWL ΔE {r['delta_e_wh']} Wh over {r['duration_s']} s "
        f"{r['confidence'] or ''}".rstrip()
        for r in runs
    )
    return f"""# Reproduce this OWL result ({job_id})

Re-run the exact video encode(s) OWL measured and check your own energy numbers
against ours.

## What OWL measured
{rows}

## Prerequisites
- **ffmpeg** — OWL's build is in `expected.json` → `hardware.ffmpeg_version`. A
  recent build matters for hardware (VAAPI) encodes.
- **A power meter** — any of: a Tapo P110, a PDU with ≥1 s granularity, or a
  Kill-A-Watt with manual logging. You measure *wall* power (whole machine).
- **A test clip** — OWL used a 120 s 1080p cut of Meridian (Netflix Open Content,
  CC BY 4.0). Not shipped here (812 MB); provide your own and set `INPUT`.

## Run it
```
INPUT=/path/to/your_clip.mp4 bash cmd.sh
```
`cmd.sh` prints and runs each encode and reports wall-clock time. Record the
energy you measure (ΔWh above idle) per run into `your_run.json`
(run `python3 compare.py` once with no argument to print a template):
```
{{"runs": [{{"label": "...", "delta_e_wh": 0.0, "duration_s": 0.0}}]}}
```

## Interpret it
```
python3 compare.py your_run.json
```
**This is not cross-hardware identicality.** A different CPU/GPU draws different
power; the test is whether your ΔE lands within OWL's k=3σ variance envelope on
*equivalent* hardware. If your lab is noisier than OWL's, a wide miss is itself
informative — your measurement variance is higher, not that OWL is wrong.

OWL ran this on GoS1 (`expected.json` → `hardware`). Energy is the result GoS
stands behind; the CO₂e figures in OWL's UI are indicative context only.
"""


def build_bundle(job_type, job_id, result, variance_pct):
    """Return zip bytes for a result, or None if it has no reproducible encode."""
    encodes = []
    _collect_encodes(result, encodes)
    if not encodes:
        return None
    ffmpeg_version = next(
        (e["ffmpeg_version"] for e in encodes if e.get("ffmpeg_version")), None)
    runs = [{
        "label": e["label"],
        "ffmpeg_cmd": e["ffmpeg_cmd"],
        "delta_w_mean": e["delta_w_mean"],
        "delta_e_wh": e["delta_e_wh"],
        "duration_s": e["duration_s"],
        "confidence": e["confidence"],
        "bounds_delta_e_wh": _bounds(e["delta_e_wh"], variance_pct),
    } for e in encodes]
    expected = {
        "owl_result": f"{job_type}/{job_id}",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "hardware": {**_HARDWARE, "ffmpeg_version": ffmpeg_version},
        "source_asset": _MERIDIAN,
        "scope": result.get("scope", "Device layer only (GoS1)."),
        "comparison_note": ("Pass = your ΔE falls within OWL's k=3σ envelope on "
                            "equivalent hardware. NOT cross-hardware identicality."),
        "runs": runs,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("expected.json", json.dumps(expected, indent=2))
        z.writestr("cmd.sh", _cmd_sh(runs))
        z.writestr("compare.py", _COMPARE_PY)
        z.writestr("README.md", _readme(job_id, runs))
    return buf.getvalue()
