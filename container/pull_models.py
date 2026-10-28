"""Pull the models a containerised OWL measures — only what fits this host.

LLMs: the tiers named in OWL_LLM_TIERS (e.g. "S,M,L" or "all") from the
curated ladder (model_catalog.LLM_LADDER), skipping any tier fit_on_host()
says won't load. Image models: the slugs in OWL_IMAGE_MODELS (e.g.
"sd-turbo,sdxl-turbo"), downloaded into the HF cache (HF_HOME).

Run from wattlab_service/ (the entrypoint does): `entrypoint.sh pull-models`.
Flags: --dry-run prints the plan only.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "wattlab_service"))
import model_catalog as mc  # noqa: E402
import ollama_api  # noqa: E402


def pull_llm(key: str) -> None:
    req = urllib.request.Request(
        ollama_api.url("api/pull"), data=json.dumps({"model": key, "stream": False}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=6 * 3600) as r:
        print(f"  {key}: {json.loads(r.read()).get('status')}", flush=True)


def main(dry: bool) -> int:
    mem = mc.host_memory()
    print(f"host memory: GPU {mem['gpu_gb'] or '—'} GB, RAM {mem['ram_gb']} GB", flush=True)
    want = [t.strip().upper() for t in os.environ.get("OWL_LLM_TIERS", "").split(",") if t.strip()]
    for key, m in mc.ladder_fit(mem).items():
        if not want or ("ALL" not in want and m["tier"] not in want):
            continue
        if m["fit"] == "wont-load":
            print(f"  skip {m['tier']:>2} {key} (~{m['gb']} GB): too large for this host", flush=True)
            continue
        note = " — partly on CPU here" if m["fit"] == "cpu-spill" else ""
        print(f"  pull {m['tier']:>2} {key} (~{m['gb']} GB, fit={m['fit']}){note}", flush=True)
        if not dry:
            pull_llm(key)

    images = [s.strip() for s in os.environ.get("OWL_IMAGE_MODELS", "").split(",") if s.strip()]
    for slug in images:
        fam = mc._IMAGE_FAMILIES.get(slug)
        if not fam:
            print(f"  skip image {slug}: unknown (have {', '.join(mc._IMAGE_FAMILIES)})", flush=True)
            continue
        print(f"  image {slug} <- {fam['repo']}", flush=True)
        if not dry:
            from huggingface_hub import snapshot_download
            snapshot_download(fam["repo"])
    return 0


if __name__ == "__main__":
    sys.exit(main("--dry-run" in sys.argv))
