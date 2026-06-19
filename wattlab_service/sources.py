from pathlib import Path
import subprocess
import json

# CR-047 — parent source + variants schema for the /video Source picker.
# Each parent groups variants that share the same conceptual content
# (Meridian, Big Buck Bunny, the GoS promo). Variants are the actual
# files OWL re-encodes — short extracts for fast demos, full-length
# masters for full-fidelity runs.
#
# Empirical scope (see docs/input_sensitivity_findings.md, 2026-05-26):
# the 5-variant matrix originally sketched (mid / high-complexity /
# low-complexity / codec-of-origin) collapsed to 3 after measurement —
# input bitrate barely moves re-encode energy (<5% spread, at noise),
# codec-of-origin is borderline (10% GPU, 3% CPU, only AV1 carries it).
# So variants are length-axis only: extract + full. Vignette (a still
# image for UI friendliness, no measurement purpose) is reserved as an
# optional parent field, plumbed but not rendered yet.

SOURCES = [
    {
        "id": "gos",
        "name": "GoS promo",
        "character": "Promo / motion graphics — text & sharp edges, very high spatial detail (SI ~57, TI ~8)",
        "credit": "Greening of Streaming",
        "license": None,  # in-house
        "source_url": None,
        "vignette": "/static/source_vignettes/gos.jpg",
        "variants": [
            {
                "key": "gos_in_50s",
                "label": "50s HD",
                "description": "1920×1080 · 30fps · H.264 · 50s · <100MB",
                "length": "full",
                "path": Path("/home/gos/wattlab/test_content/GoS-in-50s.mp4"),
            },
        ],
    },
    {
        "id": "meridian",
        "name": "Meridian 4K",
        "character": "Cinematic live-action — soft, shallow depth-of-field, dark scenes; low spatial detail (SI ~13, TI ~2), compresses easily",
        "credit": "Netflix Open Content (opencontent.netflix.com)",
        "license": "CC BY 4.0",
        "source_url": "https://opencontent.netflix.com/",
        "vignette": "/static/source_vignettes/meridian.jpg",
        "variants": [
            {
                "key": "meridian_120s",
                "label": "2 min extract",
                "description": "3840×2160 · 59.94fps · H.264 · 2min · ~122MB · fast demo",
                "length": "extract",
                "path": Path("/home/gos/wattlab/test_content/meridian_120s.mp4"),
            },
            {
                "key": "meridian_4k",
                "label": "Full 12 min",
                "description": "3840×2160 · 59.94fps · H.264 · 12min · ~812MB · ⚠ Both mode ~14-18 min incl. VMAF",
                "length": "full",
                "path": Path("/home/gos/wattlab/test_content/meridian_4k.mp4"),
            },
        ],
    },
    {
        "id": "bbb",
        "name": "Big Buck Bunny 4K",
        "character": "3D animation — sharp edges, flat gradients, high detail & motion (SI ~33, TI ~6); banding-prone, harder to compress to a VMAF target",
        "credit": "Blender Foundation / Peach Open Movie Project (peach.blender.org)",
        "license": "CC BY 3.0",
        "source_url": "https://peach.blender.org/",
        "vignette": "/static/source_vignettes/bbb.jpg",
        "variants": [
            {
                "key": "bbb_120s",
                "label": "2 min extract",
                "description": "3840×2160 · 60fps · H.264 · 2min · ~102MB · fast demo",
                "length": "extract",
                "path": Path("/home/gos/wattlab/test_content/bbb_120s.mp4"),
            },
            {
                "key": "bbb_4k",
                "label": "Full ~10 min",
                "description": "3840×2160 · 60fps · H.264 · ~10min · ~642MB · ⚠ Both mode ~12-16 min incl. VMAF",
                "length": "full",
                "path": Path("/home/gos/wattlab/test_content/bbb_4k.mp4"),
            },
        ],
    },
    {
        "id": "kranjska",
        "name": "Downhill MTB (Kranjska Gora)",
        "character": "Fast-action sport — POV downhill mountain biking; extreme spatial & temporal complexity (SI ~101, TI ~45), the hardest-to-compress source on the bench · © Maks Berc (CC BY 3.0)",
        "credit": "Maks Berc, via Wikimedia Commons",
        "license": "CC BY 3.0",
        "source_url": "https://commons.wikimedia.org/wiki/File:Downhill_bike_park_Kranjska_Gora.webm",
        "vignette": None,
        "variants": [
            {
                "key": "kranjska_120s",
                "label": "2 min extract",
                "description": "1920×1440 · 30fps · VP9 · 2min · ~173MB · high temporal complexity",
                "length": "extract",
                "path": Path("/home/gos/wattlab/test_content/kranjska_dh_120s.webm"),
            },
            {
                "key": "kranjska_full",
                "label": "Full 6:40",
                "description": "1920×1440 · 30fps · VP9 · 6:40 · ~661MB · ⚠ long run",
                "length": "full",
                "path": Path("/home/gos/wattlab/test_content/kranjska_dh.webm"),
            },
        ],
    },
]


# Flat back-compat view: variant_key → variant + parent context.
# Existing callers (main.py /video/use-source, the runtime gate on the
# upload route, etc.) look up by key here, expecting `label`, `path`,
# `credit`, `description`. Built lazily so module import is cheap and
# tests can mutate SOURCES without rebuilding.
def _build_preloaded() -> dict:
    out = {}
    for src in SOURCES:
        for v in src["variants"]:
            out[v["key"]] = {
                "label":       f"{src['name']} — {v['label']}",
                "description": v["description"],
                "path":        v["path"],
                "credit":      src["credit"],
                "_parent":     src["id"],
            }
    return out


PRELOADED = _build_preloaded()


def get_variant(key: str) -> dict:
    """Return the variant dict for a globally-unique variant key, or None."""
    for src in SOURCES:
        for v in src["variants"]:
            if v["key"] == key:
                return v
    return None


def get_parent_for(key: str) -> dict:
    """Return the parent source dict that owns this variant key, or None."""
    for src in SOURCES:
        for v in src["variants"]:
            if v["key"] == key:
                return src
    return None


def _probe(path: Path) -> dict:
    """ffprobe a file → flat dict of display fields. Empty dict on failure."""
    try:
        result = subprocess.run([
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams", "-show_format",
            str(path)
        ], capture_output=True, text=True)
        data = json.loads(result.stdout)
        video = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
        fmt = data.get("format", {})
        return {
            "size_mb":    round(path.stat().st_size / 1024 / 1024, 1),
            "duration_s": round(float(fmt.get("duration", 0)), 1),
            "resolution": f"{video.get('width', '?')}x{video.get('height', '?')}",
            "codec":      video.get("codec_name", "?"),
            "fps":        video.get("r_frame_rate", "?"),
        }
    except Exception:
        return {}


def get_source_info(key: str) -> dict:
    """Back-compat: flat per-variant info dict, the shape /video/sources
    has served since before CR-047. Includes parent metadata so callers
    that want to group can do so without a second lookup.

    `label` is the parent-prefixed form ("Big Buck Bunny 4K — 2 min
    extract") — back-compat for the queue label and any historical
    JSON consumer. `variant_label` is the short form ("2 min extract")
    for the picker, which already shows the parent in its header.
    """
    v = get_variant(key)
    parent = get_parent_for(key)
    if not v or not parent or not v["path"].exists():
        return None
    info = {
        "key":           v["key"],
        "label":         f"{parent['name']} — {v['label']}",
        "variant_label": v["label"],
        "description":   v["description"],
        "credit":        parent["credit"],
        "path":          str(v["path"]),
        "parent":        parent["id"],
        "parent_name":   parent["name"],
        "length":        v["length"],
    }
    info.update(_probe(v["path"]))
    return info


def get_all_sources() -> list:
    """Flat list, ordered as in SOURCES. Back-compat for /video/sources."""
    out = []
    for src in SOURCES:
        for v in src["variants"]:
            info = get_source_info(v["key"])
            if info:
                out.append(info)
    return out


def get_grouped_sources() -> list:
    """Parent-grouped view for the /video Source picker. List of:
        {id, name, credit, license, source_url, vignette,
         variants: [variant_info, ...]}
    where each variant_info has the same shape as get_source_info()
    returns (so the picker template can speak one schema for both the
    parent header and the radio rows).
    """
    out = []
    for src in SOURCES:
        variants = []
        for v in src["variants"]:
            info = get_source_info(v["key"])
            if info:
                variants.append(info)
        if not variants:
            continue
        out.append({
            "id":         src["id"],
            "name":       src["name"],
            "character":  src.get("character"),
            "credit":     src["credit"],
            "license":    src.get("license"),
            "source_url": src.get("source_url"),
            "vignette":   src.get("vignette"),
            "variants":   variants,
        })
    return out
