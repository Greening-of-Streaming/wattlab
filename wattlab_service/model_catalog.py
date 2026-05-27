"""Model catalog — auto-discovery + per-surface enable list (CR-050).

Single source of truth for "what models are usable on this server right now".
Replaces the hand-maintained `MODELS` dicts in llm.py, rag.py, and image_gen.py
so that pulling a new Ollama model (or downloading a new HF image model into the
cache) makes it appear on /llm, /rag, /image, and their /compare pages without
a code change — the only thing needed is a tick in the new /settings Models
section to enable it.

Two catalog sources:
- LLMs (used by /llm and /rag): `ollama list`, filtered to text models.
- Image models: scan of `~/.cache/huggingface/hub/models--*` plus a built-in
  defaults table for known families. Unknown image families render with safe
  defaults; if they don't work well, the user disables them.

Per-surface enable lists live in settings.json as `llm_enabled_models`,
`rag_enabled_models`, `image_enabled_models`. Empty list / absent key means
"all available enabled" — so a fresh server with no settings file Just Works.

Catalog scans are cached for 60 s so /llm/compare doesn't reshell out to
`ollama list` for every render.
"""
import os
import re
import subprocess
import time
from pathlib import Path

import settings as cfg

# ---------------------------------------------------------------------------
# Name parsing — best-effort metadata from a model key
# ---------------------------------------------------------------------------

# Captures things like "1.7B", "12b", "7B", "1.1B" anywhere in the name.
_PARAMS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([bB])(?![a-zA-Z])")

# Image-only Ollama models (GGUF ports of HF image models — not text LLMs).
# Filtered out of the LLM catalog so they don't pollute /llm and /rag panels.
_OLLAMA_IMAGE_PREFIXES = ("x/flux", "x/z-image", "x/stable-diffusion", "x/sdxl")


def _params_from_name(name: str) -> str:
    """Best-effort parameter count extraction. 'qwen3:1.7b' -> '1.7B'."""
    m = _PARAMS_RE.search(name)
    if m:
        return f"{m.group(1)}{m.group(2).upper()}"
    # Special-cased families where the name encodes size differently.
    lo = name.lower()
    if "tinyllama" in lo:
        return "1.1B"
    if "phi-4" in lo or "phi4" in lo:
        return "14B"
    if "phi-3" in lo or "phi3" in lo:
        return "3.8B"
    return "?"


def params_numeric(params_str: str) -> float:
    """'1.7B' -> 1.7, '12B' -> 12.0, '?' -> +inf (sorts to end)."""
    m = re.match(r"~?\s*(\d+(?:\.\d+)?)\s*[bB]", params_str or "")
    return float(m.group(1)) if m else float("inf")


_FAMILY_OVERRIDES = {
    "Tinyllama":     "TinyLlama",
    "Gpt-Oss":       "GPT-OSS",
    "Gpt Oss":       "GPT-OSS",
    "Mistral Nemo":  "Mistral Nemo",
    "Qwen3":         "Qwen3",
    "Phi4":          "Phi-4",
    "Phi3":          "Phi-3",
}


def _prettify_family(family: str) -> str:
    fam_p = " ".join(w.capitalize() for w in re.split(r"[-_]", family))
    return _FAMILY_OVERRIDES.get(fam_p, fam_p)


def _label_from_key(key: str) -> str:
    """'qwen3:1.7b' -> 'Qwen3 1.7B'. 'phi4' -> 'Phi-4'. Best effort."""
    base = key.replace(":latest", "")
    if ":" in base:
        family, tag = base.split(":", 1)
        tag_p = _PARAMS_RE.sub(lambda m: f"{m.group(1)}{m.group(2).upper()}", tag)
        return f"{_prettify_family(family)} {tag_p}"
    return _prettify_family(base)


def _normalize_key(name: str) -> str:
    """Strip ':latest' from Ollama names (it's the default tag, semantic noise).
    Keep meaningful tags like ':1.7b', ':8b' as-is. Ollama's API accepts both
    bare names and ':latest' interchangeably, so stripping is safe.
    """
    return name[:-len(":latest")] if name.endswith(":latest") else name


# ---------------------------------------------------------------------------
# Ollama list — cached
# ---------------------------------------------------------------------------

_CACHE_TTL_S = 60
_ollama_cache: list[dict] | None = None
_ollama_cache_t: float = 0.0


def _ollama_list_raw() -> list[dict]:
    """Returns [{'name': 'qwen3:8b', 'size': '5.2 GB'}, ...] or [] on failure."""
    global _ollama_cache, _ollama_cache_t
    now = time.time()
    if _ollama_cache is not None and (now - _ollama_cache_t) < _CACHE_TTL_S:
        return _ollama_cache
    try:
        out = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        _ollama_cache = []
        _ollama_cache_t = now
        return []
    rows = []
    for line in out.splitlines()[1:]:  # skip header
        # Format: NAME<TAB>ID<TAB>SIZE_NUM SIZE_UNIT<TAB>MODIFIED…
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 3:
            continue
        name = parts[0].strip()
        size = parts[2].strip() if len(parts) >= 3 else "?"
        if not name:
            continue
        rows.append({"name": name, "size": size})
    _ollama_cache = rows
    _ollama_cache_t = now
    return rows


def invalidate_ollama_cache():
    """Force the next call to re-shell. Used by the /settings refresh hook."""
    global _ollama_cache_t
    _ollama_cache_t = 0.0


# ---------------------------------------------------------------------------
# LLM catalog
# ---------------------------------------------------------------------------

def available_llm_models() -> dict:
    """{key: {label, size, params}} for every text LLM in `ollama list`.
    Keys are normalised ('phi4:latest' -> 'phi4'); meaningful tags retained.
    Sorted by parsed parameter count ascending so callers iterating the dict
    (compare runners, page selector cards, charts) get a size-ordered panel
    by default — Ollama's "recently modified first" order is rarely useful.
    """
    out = {}
    for row in _ollama_list_raw():
        name = row["name"]
        if any(name.startswith(p) for p in _OLLAMA_IMAGE_PREFIXES):
            continue
        key = _normalize_key(name)
        out[key] = {
            "label":  _label_from_key(name),
            "size":   row.get("size", "?"),
            "params": _params_from_name(name),
        }
    return dict(sorted(out.items(), key=lambda kv: params_numeric(kv[1]["params"])))


def _enabled_for(surface_key: str, available: dict) -> dict:
    """Apply settings[surface_key] (a list of model keys) to available.
    Empty / missing list = all available. Order follows enabled list when set.
    """
    s = cfg.load()
    enabled = s.get(surface_key) or []
    if not enabled:
        return available
    return {k: available[k] for k in enabled if k in available}


def enabled_llm_models() -> dict:
    return _enabled_for("llm_enabled_models", available_llm_models())


def enabled_rag_models() -> dict:
    return _enabled_for("rag_enabled_models", available_llm_models())


# ---------------------------------------------------------------------------
# Image catalog
# ---------------------------------------------------------------------------

_HF_CACHE = Path.home() / ".cache" / "huggingface" / "hub"

# Built-in defaults for known image-model families. Keys are short slugs
# (lowercased HF repo "name" portion) so /image stays backwards-compatible
# with existing code that hardcodes 'sd-turbo' / 'sdxl-turbo'. The full
# HF repo path is stored in `repo` for the diffusers loader.
# Anything not in this table still appears in the catalog with SAFE_DEFAULTS;
# if it doesn't work, the user disables it in /settings.
_IMAGE_FAMILIES = {
    "sd-turbo": {
        "label": "SD-Turbo", "repo": "stabilityai/sd-turbo",
        "params": "~1B", "native_px": 512, "cpu_ok": True,
        "cpu_steps": 8, "gpu_steps": 20, "gpu_batch": 5,
        "compare_steps": 4, "compare_batch": 30,
        "size_px": 512, "fp16_variant": False,
    },
    "sdxl-turbo": {
        "label": "SDXL-Turbo", "repo": "stabilityai/sdxl-turbo",
        "params": "~3.5B", "native_px": 1024, "cpu_ok": False,
        "cpu_steps": None, "gpu_steps": 4, "gpu_batch": 15,
        "compare_steps": 4, "compare_batch": 15,
        "size_px": 512, "fp16_variant": True,
    },
    "sdxl-lightning": {
        "label": "SDXL-Lightning", "repo": "ByteDance/SDXL-Lightning",
        "params": "~3.5B", "native_px": 1024, "cpu_ok": False,
        "cpu_steps": None, "gpu_steps": 4, "gpu_batch": 15,
        "compare_steps": 4, "compare_batch": 15,
        "size_px": 512, "fp16_variant": True,
    },
    "sana-600m": {
        "label": "Sana 600M", "repo": "Efficient-Large-Model/Sana_600M_512px_diffusers",
        "params": "~0.6B", "native_px": 512, "cpu_ok": False,
        "cpu_steps": None, "gpu_steps": 20, "gpu_batch": 8,
        "compare_steps": 8, "compare_batch": 8,
        "size_px": 512, "fp16_variant": False,
    },
}

# Map full HF repo string -> short slug, for cache-scan lookup.
_REPO_TO_SLUG = {v["repo"]: k for k, v in _IMAGE_FAMILIES.items()}

_SAFE_IMAGE_DEFAULTS = {
    "params": "?", "native_px": 512, "cpu_ok": False,
    "cpu_steps": None, "gpu_steps": 4, "gpu_batch": 4,
    "compare_steps": 4, "compare_batch": 4,
    "size_px": 512, "fp16_variant": True,
}

_image_cache: dict | None = None
_image_cache_t: float = 0.0


def available_image_models() -> dict:
    """Scan HF cache for downloaded image models. Returns {slug: {label, repo, ...}}.

    Slug is the lowercased repo-name portion ('sd-turbo', 'sdxl-turbo') so
    existing code paths using bare slugs keep working. Known families get full
    operational metadata; unknown ones get safe defaults.
    Embedding/sentence models are filtered out.
    """
    global _image_cache, _image_cache_t
    now = time.time()
    if _image_cache is not None and (now - _image_cache_t) < _CACHE_TTL_S:
        return _image_cache
    out = {}
    if _HF_CACHE.exists():
        for entry in _HF_CACHE.iterdir():
            if not entry.is_dir() or not entry.name.startswith("models--"):
                continue
            parts = entry.name[len("models--"):].split("--", 1)
            if len(parts) != 2:
                continue
            owner, name = parts
            repo = f"{owner}/{name}"
            low = repo.lower()
            if any(skip in low for skip in ("sentence-transformers", "all-mini", "all-mpnet")):
                continue
            # Prefer the short slug from the family table; fall back to
            # lowercased name for unknown repos.
            slug = _REPO_TO_SLUG.get(repo, name.lower())
            if slug in _IMAGE_FAMILIES:
                out[slug] = dict(_IMAGE_FAMILIES[slug])
            else:
                out[slug] = {
                    "label": name.replace("-", " ").replace("_", " "),
                    "repo":  repo,
                    **_SAFE_IMAGE_DEFAULTS,
                }
    _image_cache = out
    _image_cache_t = now
    return out


def invalidate_image_cache():
    global _image_cache_t
    _image_cache_t = 0.0


def enabled_image_models() -> dict:
    return _enabled_for("image_enabled_models", available_image_models())


def refresh_all():
    """Force-refresh both catalogs and downstream MODELS views. Called from
    the /settings save handler so a checkbox change is visible immediately."""
    invalidate_ollama_cache()
    invalidate_image_cache()
    # Downstream MODELS views read through the catalog on each access, so a
    # cache invalidation here is enough — no extra calls into llm/rag/image.
