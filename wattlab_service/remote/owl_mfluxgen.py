"""
owl_mfluxgen.py — MLX-native text-to-image runner (Apple silicon only, mflux).

Second image environment on a Mac node, next to torch/diffusers on MPS: mflux
runs the diffusion model on Apple's MLX framework. It speaks the SAME session
protocol as owl_imagegen.py, so remote_ai.run_image_session drives either
runner unchanged and an MPS run and an MLX run differ only by the stack:

  load → `warmup` discarded images → {"ev": "ready"} → wait for "GO" on stdin →
  one {"ev": "img"} per image → {"ev": "done", …}

Runs in its own venv (~/owl/mflux-venv) so mflux's MLX pin cannot disturb
mlx-lm. Weights: the same HF repo diffusers uses, from the shared HF cache.

Usage: python owl_mfluxgen.py '<json args>'   args as owl_imagegen.py session
mode, plus "mflux_model" (the ModelConfig name, e.g. "flux2_klein_4b").
"""
import base64
import io
import json
import sys
import time

# mflux model name → (variant module, class). Add a row per supported family.
_VARIANTS = {
    "flux2_klein_4b": ("mflux.models.flux2.variants", "Flux2Klein"),
    "flux2_klein_9b": ("mflux.models.flux2.variants", "Flux2Klein"),
}


def _load(a):
    import importlib
    from mflux.models.common.config import ModelConfig
    name = a["mflux_model"]
    if name not in _VARIANTS:
        raise SystemExit(f"owl_mfluxgen: unsupported mflux model {name!r}")
    mod, cls = _VARIANTS[name]
    model_cls = getattr(importlib.import_module(mod), cls)
    # No quantize: bf16 weights, the same precision diffusers runs on the GPU.
    return model_cls(model_config=getattr(ModelConfig, name)())


def _encode_once(model, prompts):
    """Parity with the diffusers runner's encode_once: mflux re-encodes the
    prompt with the 4B text encoder on every generate_image call; encode each
    session prompt once at load and serve later calls from the cache, so both
    stacks measure generation from cached embeddings. No-op for a variant
    without _encode_prompt_pair."""
    enc = getattr(model, "_encode_prompt_pair", None)
    if enc is None:
        return
    import mlx.core as mx
    cache = {}

    def cached(*, prompt, negative_prompt, guidance):
        key = (prompt, negative_prompt, guidance)
        if key not in cache:
            out = enc(prompt=prompt, negative_prompt=negative_prompt, guidance=guidance)
            mx.eval([x for x in out if x is not None])
            cache[key] = out
        return cache[key]
    model._encode_prompt_pair = cached
    for p in dict.fromkeys(prompts):        # same arguments generate_image passes
        cached(prompt=p, negative_prompt=" ", guidance=1.0)


def _gen(model, a, prompt, seed):
    out = model.generate_image(seed=seed, prompt=prompt,
                               num_inference_steps=int(a["steps"]),
                               width=int(a["size_px"]), height=int(a["size_px"]))
    # generate_image returns a GeneratedImage wrapper (PIL image on .image);
    # converting to PIL forces MLX's lazy graph, so the image is finished here.
    return getattr(out, "image", out)


def _versions():
    import importlib.metadata as md
    return {"mflux": md.version("mflux"), "mlx": md.version("mlx")}


def _peak_gb():
    try:
        import mlx.core as mx
        return round(mx.get_peak_memory() / 1e9, 2)
    except Exception:
        return None


def session(a):
    t0 = time.time()
    model = _load(a)
    prompts = a["prompts"]
    _encode_once(model, prompts)
    load_s = round(time.time() - t0, 2)
    seed = int(a.get("seed", 1234))
    t_w = time.time()
    for i in range(int(a.get("warmup", 2))):
        _gen(model, a, prompts[0], seed + 10_000 + i)
    warmup_s = round(time.time() - t_w, 2)
    print(json.dumps({"ev": "ready", "device": "mlx", "load_s": load_s,
                      "warmup_s": warmup_s, **_versions()}), flush=True)
    for line in sys.stdin:                     # wait while the service samples the warm baseline
        if line.strip() == "GO":
            break
    per_prompt = int(a["per_prompt"])
    target_s = float(a.get("target_s") or 0)
    spans, last, n, firsts = [], None, 0, {}
    t_go = time.time()
    for p_idx, prompt in enumerate(prompts):
        t_p = time.time()
        p_target = target_s * (p_idx + 1) / len(prompts)
        k = 0
        while k < per_prompt or (target_s and time.time() - t_go < p_target):
            last = _gen(model, a, prompt, seed + p_idx * 1000 + k)
            if k == 0:                         # same seed on every stack: the comparable pair
                firsts[p_idx] = (seed + p_idx * 1000, last)
            print(json.dumps({"ev": "img", "p": p_idx, "k": k}), flush=True)
            k += 1
        n += k
        spans.append(round(time.time() - t_p, 3))
    gen_s = round(time.time() - t_go, 3)
    buf = io.BytesIO()
    firsts.get(0, (None, last))[1].resize((256, 256)).save(buf, format="PNG")
    print(json.dumps({"ev": "done", "gen_s": gen_s, "n_images": n,
                      "s_per_image": round(gen_s / n, 4), "per_prompt_s": spans,
                      "device": "mlx", "peak_memory_gb": _peak_gb(),
                      "noise": "mlx",
                      "thumb_b64_png": base64.b64encode(buf.getvalue()).decode()}), flush=True)
    _emit_full(firsts)


def _emit_full(firsts):
    """After "done" (the service has closed the measurement window): the first
    image of each prompt at full size, lossless. Its seed is the same on every
    stack, so two runs can be compared image for image (owner 2026-10-29)."""
    for p_idx, (seed, img) in sorted(firsts.items()):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        print(json.dumps({"ev": "full", "p": p_idx, "seed": seed,
                          "png_b64": base64.b64encode(buf.getvalue()).decode()}), flush=True)


if __name__ == "__main__":
    args = json.loads(sys.argv[1])
    if args.get("mode") != "session":
        raise SystemExit("owl_mfluxgen: only mode=session is supported")
    session(args)
