"""
budget_data.py — turn a measured encode-parity artifact into the /video/budget
page's recipe table (the shape _demo_fixture() defines).

Falls back to None when no usable measured artifact exists, so the page keeps its
illustrative fixture until a calibration run has happened. Pure data-shaping; no
measurement, no I/O beyond reading the artifact JSON.

The measured campaign is 1080p SINGLE RENDITION (one rung), so the unit reported
here is "Wh per minute of source · 1080p single rendition (measured)", NOT the
fixture's projected 4-rung ABR ladder. We do not extrapolate unmeasured rungs.
"""
import glob
import json
import os
from pathlib import Path

ARTIFACT_GLOB = str(Path(__file__).resolve().parent.parent
                    / "results" / "calibration" / "encode_parity_*.json")

# Complexity by MEASURED ITU-T P.910 SI/TI (2026-06-19): BBB (SI~33) is the
# high-complexity clip, Meridian (SI~13, soft cinematic) the low one — the opposite
# of the clips' loose reputations, and the reason higher-complexity correctly costs
# more bitrate to hit a VMAF target.
# Three measured complexity tiers: low (Meridian, SI~13/TI~2), high (BBB,
# SI~33/TI~6), sport (Kranjska downhill-MTB, SI~101/TI~45 — high spatial AND
# temporal). Sport needs a taller bitrate sweep to reach VMAF 92 (parity.SPORTS_BITRATES).
_CLIP_COMPLEXITY = {"meridian_120s": "low", "bbb_120s": "high", "kranjska_120s": "sport"}
_COMPLEXITY_CLIP = {v: k for k, v in _CLIP_COMPLEXITY.items()}
_TIERS = ("low", "high", "sport")
_CODEC_LABEL = {"h264": "H.264", "h265": "H.265", "av1": "AV1"}


def latest_artifact_path() -> str | None:
    """Newest complete, non-dry artifact (by mtime), or None."""
    best, best_mtime = None, -1.0
    for p in glob.glob(ARTIFACT_GLOB):
        if p.endswith("_DRY.json"):
            continue
        try:
            a = json.loads(Path(p).read_text())
        except Exception:
            continue
        # Require a COMPLETE run — never present a half-finished sweep as "measured".
        if a.get("dry_run") or not a.get("complete") or not a.get("rows"):
            continue
        mt = os.path.getmtime(p)
        if mt > best_mtime:
            best, best_mtime = p, mt
    return best


def _interp(xy: list, x_target: float):
    """Given (x, y) points, return y at x_target by linear interpolation between
    the bracketing points (clamped to the ends). None if no points."""
    pts = sorted((x, y) for x, y in xy if x is not None and y is not None)
    if not pts:
        return None
    if x_target <= pts[0][0]:
        return pts[0][1]
    if x_target >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x_target <= x1:
            if x1 == x0:
                return y0
            f = (x_target - x0) / (x1 - x0)
            return y0 + f * (y1 - y0)
    return pts[-1][1]


def _bitrate_at_vmaf(points: list, target: float):
    """points: list of dict rows for one (device,codec,complexity). Return the
    achieved bitrate (kbps) that hits `target` VMAF, or None if unreachable."""
    vb = [(r["vmaf"], (r["achieved_bitrate_bps"] or 0) / 1000.0)
          for r in points if r.get("vmaf") is not None and r.get("achieved_bitrate_bps")]
    vb = sorted(vb)
    if not vb:
        return None
    if target > vb[-1][0] + 0.01:          # target above the best measured VMAF
        return None
    if target <= vb[0][0]:                 # already exceeded at the lowest bitrate
        return round(vb[0][1])
    for (v0, b0), (v1, b1) in zip(vb, vb[1:]):
        if v0 <= target <= v1:
            f = 0 if v1 == v0 else (target - v0) / (v1 - v0)
            return round(b0 + f * (b1 - b0))
    return round(vb[-1][1])


def _wh_at_bitrate(points: list, bitrate_kbps: float):
    """Wh/min interpolated at the given achieved bitrate."""
    xy = [((r["achieved_bitrate_bps"] or 0) / 1000.0, r.get("wh_per_min_video"))
          for r in points if r.get("achieved_bitrate_bps") and r.get("wh_per_min_video") is not None]
    v = _interp(xy, bitrate_kbps)
    return round(v, 3) if v is not None else None


def _pick_gpu_profile(rows: list, codec: str) -> str:
    """Per codec, choose the GPU profile we'd ship: the one reaching the higher max
    VMAF (tie → baseline, the simpler/faster config)."""
    def maxv(profile):
        vs = [r["vmaf"] for r in rows
              if r["codec"] == codec and r["profile"] == profile and r.get("vmaf") is not None]
        return max(vs) if vs else -1
    return "gpu_tuned" if maxv("gpu_tuned") > maxv("gpu_baseline") + 0.3 else "gpu_baseline"


def build_recipes(artifact: dict, vmaf_targets: list) -> dict | None:
    """Return {recipes, meta_extra, gpu_choice} from a measured artifact, or None
    if it lacks the codecs/points needed."""
    allrows = [r for r in artifact.get("rows", []) if r.get("vmaf") is not None and not r.get("error")]
    if not allrows:
        return None
    # Sweep rows (1080p top rung) build the VMAF-vs-bitrate curve; ladder rows
    # (lower rungs, fixed bitrate) add the rest of the ABR ladder's energy.
    sweep = [r for r in allrows if r.get("rung", "sweep") == "sweep" and r.get("height", 1080) == 1080]
    ladder = [r for r in allrows if r.get("rung") == "ladder"]
    # Only treat the ladder as available once the merge COMPLETED (has_ladder flag) —
    # otherwise a page load mid-merge would show partial-rung sums as if complete.
    have_ladder = bool(artifact.get("has_ladder")) and bool(ladder)
    codecs = sorted({r["codec"] for r in sweep}, key=lambda c: ["h264", "h265", "av1"].index(c)
                    if c in ("h264", "h265", "av1") else 9)

    gpu_choice = {c: _pick_gpu_profile(sweep, c) for c in codecs}

    def ladder_add(profile, codec, clip):
        """Sum of lower-rung Wh/min for this profile+codec+clip (fixed bitrate, so a
        near-constant add to the top-rung energy). None if no ladder data."""
        rr = [r for r in ladder if r["codec"] == codec and r["profile"] == profile
              and r["clip"] == clip and r.get("wh_per_min_video") is not None]
        return round(sum(r["wh_per_min_video"] for r in rr), 3) if rr else None

    recipes = []
    device_profiles = {"cpu": (lambda c: "cpu"), "gpu": (lambda c: gpu_choice[c])}
    # Ladder rungs were measured on cpu + gpu_baseline only — map gpu→gpu_baseline.
    ladder_profile = {"cpu": "cpu", "gpu": "gpu_baseline"}
    for device in ("cpu", "gpu"):
        for codec in codecs:
            profile = device_profiles[device](codec)
            sel = [r for r in sweep if r["codec"] == codec and r["profile"] == profile]
            by_cx = {t: [] for t in _TIERS}
            for r in sel:
                cx = _CLIP_COMPLEXITY.get(r["clip"])
                if cx in by_cx:
                    by_cx[cx].append(r)
            if not any(by_cx[t] for t in _TIERS):
                continue

            def arrays(cx_rows):
                if not cx_rows:
                    return [None] * len(vmaf_targets), [None] * len(vmaf_targets)
                brs = [_bitrate_at_vmaf(cx_rows, t) for t in vmaf_targets]
                whs = [_wh_at_bitrate(cx_rows, b) if b else None for b in brs]
                return brs, whs

            br = {t: arrays(by_cx[t])[0] for t in _TIERS}
            wh = {t: arrays(by_cx[t])[1] for t in _TIERS}
            max_vmaf = round(max((r["vmaf"] for r in sel), default=0))
            rec = {
                "device": device,
                "device_label": {"cpu": "CPU · general-purpose cores",
                                 "gpu": "GPU · hardware encoder"}[device],
                "codec": codec, "codec_label": _CODEC_LABEL.get(codec, codec.upper()),
                "max_vmaf": max_vmaf, "available": True, "projected": False,
                "measured_profile": profile,
            }
            for t in _TIERS:
                rec[f"wh_{t}"] = wh[t]
                rec[f"br_{t}"] = br[t]
                rec[f"ladder_add_{t}"] = ladder_add(
                    ladder_profile[device], codec, _COMPLEXITY_CLIP[t])
            recipes.append(rec)
    if not recipes:
        return None
    return {"recipes": recipes, "gpu_choice": gpu_choice, "have_ladder": have_ladder}


def measured_fixture(vmaf_targets: list, asic_recipes: list, classes: list,
                     sponsorship_note: str) -> dict | None:
    """Full page payload from the latest measured artifact, or None to fall back.
    `asic_recipes` (the illustrative projected ASIC rows) are appended as-is since
    we have no ASIC measurement yet."""
    path = latest_artifact_path()
    if not path:
        return None
    artifact = json.loads(Path(path).read_text())
    built = build_recipes(artifact, vmaf_targets)
    if not built:
        return None
    fp = artifact.get("fingerprint", {})
    gpu_name = (fp.get("gpu") or {}).get("name", "GPU")
    cpu_name = (fp.get("cpu") or {}).get("model", "CPU")
    have_ladder = built.get("have_ladder")
    rungs = artifact.get("protocol", {}).get("ladder_rungs") or []
    n_rungs = len(rungs) + 1  # + the 1080p top rung
    if have_ladder:
        ladder_lbl = (f"{n_rungs}-rung ABR ladder (1080p + "
                      + "/".join(f"{h}p" for h, _ in rungs) + ", measured)")
        unit = "Wh per minute of source · full ABR ladder"
    else:
        ladder_lbl = "1080p single rendition (measured — not a full ABR ladder)"
        unit = "Wh per minute of source · 1080p single rendition"
    return {
        "meta": {
            "illustrative": False,
            "measured_on": artifact.get("generated_at"),
            "hardware": f"{cpu_name} · {gpu_name}",
            "have_ladder": bool(have_ladder),
            "ladder": ladder_lbl,
            "unit": unit,
            "clip_low": "Meridian (soft live-action — low SI/TI)",
            "clip_high": "Big Buck Bunny (sharp 3D animation — high SI/TI)",
            "clip_sport": "Kranjska Gora downhill MTB (high SI/TI — sport)",
            "gpu_profile": built["gpu_choice"],
            "asic_projected": True,
        },
        "vmaf_targets": vmaf_targets,
        "recipes": built["recipes"] + asic_recipes,
        "classes": classes,
        "sponsorship_note": sponsorship_note,
    }
