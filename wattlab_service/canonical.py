"""Pinned canonical reference result(s).

CR-037 tethers the AI workload pages to streaming by expressing each AI job's
energy as a multiple of a real video encode: "≈ N× a 120 s 1080p hardware
encode". The reference is the canonical H.265 GPU encode of Meridian-120s.

The reference is PINNED to a committed file (canonical/video_baseline.json) —
never "whatever result is latest on disk". The multiplier therefore only moves
when we deliberately re-pin (e.g. after CR-029 re-runs the canonical bitrates),
at which point the multiplier copy gets re-reviewed. See CR-037 watch-outs.

Everything here fails soft: if the baseline file is missing or malformed, the
helpers return None and callers render nothing rather than erroring.
"""
import json
from pathlib import Path

_BASELINE_FILE = Path(__file__).resolve().parent / "canonical" / "video_baseline.json"

_video_baseline = None  # lazily loaded + cached


def video_baseline():
    """Return the pinned canonical video-encode reference dict, or None.

    Cached after first read. None means the file is missing/malformed — callers
    must treat that as 'no comparison available' and render nothing.
    """
    global _video_baseline
    if _video_baseline is None:
        try:
            _video_baseline = json.loads(_BASELINE_FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            _video_baseline = {}  # sentinel: loaded-but-absent (don't retry disk)
    return _video_baseline or None


def _fmt_ratio(n: float) -> str:
    """Human ratio: 2 dp below 1, one dp under 10, whole numbers under 100,
    rounded to the nearest ten above that (the multiplier is a framing aid, not
    a precise figure — don't imply false precision)."""
    if n < 1:
        return f"{n:.2f}×"
    if n < 10:
        return f"{n:.1f}×"
    if n < 100:
        return f"{round(n)}×"
    return f"{round(n, -1):.0f}×"


def times_vs_video(delta_e_wh):
    """Express an AI job's energy as a multiple of the canonical video encode.

    Returns a dict {ratio, text, baseline_wh, baseline_label} or None when the
    baseline is unavailable or the input is unusable (caller renders nothing).
    """
    base = video_baseline()
    if not base:
        return None
    ref = base.get("delta_e_wh")
    try:
        delta_e_wh = float(delta_e_wh)
        ref = float(ref)
    except (TypeError, ValueError):
        return None
    if delta_e_wh <= 0 or ref <= 0:
        return None
    ratio = delta_e_wh / ref
    return {
        "ratio": ratio,
        "text": f"≈ {_fmt_ratio(ratio)} a 120 s 1080p H.265 GPU encode",
        "baseline_wh": ref,
        "baseline_label": base.get("preset_label", "H.265 GPU"),
    }


def video_baseline_wh_per_minute():
    """Energy to encode one minute of 1080p video at the canonical operating
    point (for the /image '1 minute of personalised frames' framing). None if
    the baseline or its source duration is unavailable."""
    base = video_baseline()
    if not base:
        return None
    wh = base.get("delta_e_wh")
    secs = base.get("source_duration_s")
    try:
        wh = float(wh)
        secs = float(secs)
    except (TypeError, ValueError):
        return None
    if wh <= 0 or secs <= 0:
        return None
    return wh / (secs / 60.0)


def enrich_result(obj):
    """Recursively attach a `video_relative` block to every nested `energy`
    dict, mirroring carbon.walk_and_enrich. Called by persist.save_result for AI
    result types (CR-037) so each AI energy figure carries its
    "≈ N× a 120 s 1080p H.265 GPU encode" streaming anchor. No-op wherever the
    baseline or delta_e_wh is unavailable, so it never blocks a save.
    """
    if isinstance(obj, dict):
        energy = obj.get("energy")
        if isinstance(energy, dict) and "delta_e_wh" in energy:
            vr = times_vs_video(energy.get("delta_e_wh"))
            if vr:
                energy["video_relative"] = vr
        for v in obj.values():
            enrich_result(v)
    elif isinstance(obj, list):
        for v in obj:
            enrich_result(v)
