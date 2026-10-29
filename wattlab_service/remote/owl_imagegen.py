"""
owl_imagegen.py — host-side text-to-image runner (CR-085 Part 3).

Runs on any compute host — GoS2 over SSH (torch "mps"), GoS1 as a local
subprocess (torch "cuda") — so both machines execute the identical code path.
Mirrors image_gen.generate_image's GPU path: same pipeline class, dtype,
guidance, steps, size, seeds.

Two modes (args["mode"]):

  "oneshot" (default) — load, generate `batch`, print ONE JSON line with the
      keys image_gen.generate_image returns. Used by /image/remote and
      /image/bench (OWL's convention: power polled across load + generation).

  "session" — the clean measurement window (owner request 2026-10-05):
      load → `warmup` discarded images → print a {"ev": "ready"} line → block on
      stdin until "GO" → for each prompt, `per_prompt` images, one
      {"ev": "img"} line per image (device-synchronised) → a final
      {"ev": "done", …} line. GoS1's service samples the warm-model baseline
      while this process waits, and the task window from GO to done —
      generation only: no import, load or warm-up inside it.

Usage: python owl_imagegen.py '<json args>'
"""
import base64
import io
import json
import sys
import time


def _sync(torch, device):
    if device == "cuda":
        torch.cuda.synchronize()
    elif device == "mps":
        torch.mps.synchronize()


def _load(torch, a):
    from diffusers import AutoPipelineForText2Image
    device = a.get("device") or ("cuda" if torch.cuda.is_available()
                                 else "mps" if torch.backends.mps.is_available() else "cpu")
    kwargs = {"torch_dtype": getattr(torch, a.get("torch_dtype") or "float16")
              if device != "cpu" else torch.float32}
    if a.get("fp16_variant") and device != "cpu":
        kwargs["variant"] = "fp16"
    if a.get("pipeline") == "diffusion":
        from diffusers import DiffusionPipeline
        pipe = DiffusionPipeline.from_pretrained(a["repo"], **kwargs)
    else:
        pipe = AutoPipelineForText2Image.from_pretrained(a["repo"], **kwargs)
    if not a.get("encode_once"):        # encode_once: moved to the device by _encode_once
        pipe = pipe.to(device)
        _sync(torch, device)
    return pipe, device


def _encode_once(torch, pipe, device, prompts):
    """Families whose text encoder + transformer exceed the GPU (FLUX.2 Klein
    4B: 7.5 + 7.3 GB bf16 on a 16 GB card): encode every prompt once with the
    text encoder on the device, park it on the CPU, then generate from the
    cached embeddings. Same on every device, so CUDA and MPS stay comparable.
    Returns {prompt: prompt_embeds}. Mirrors image_gen.encode_once."""
    pipe.text_encoder.to(device)
    with torch.no_grad():
        embeds = {p: pipe.encode_prompt(prompt=p, device=device)[0] for p in dict.fromkeys(prompts)}
    pipe.text_encoder.to("cpu")
    pipe.text_encoder = None
    if device == "cuda":
        torch.cuda.empty_cache()
    elif device == "mps":
        torch.mps.empty_cache()
    pipe.to(device)
    _sync(torch, device)
    return embeds


def _gen(torch, pipe, device, a, prompt, seed, embeds=None):
    gen = torch.Generator().manual_seed(seed) if seed is not None else None
    text = {"prompt_embeds": embeds[prompt]} if embeds else {"prompt": prompt}
    img = pipe(**text, num_inference_steps=int(a["steps"]),
               guidance_scale=float(a.get("guidance_scale", 0.0)),
               height=int(a["size_px"]), width=int(a["size_px"]),
               generator=gen).images[0]
    _sync(torch, device)
    return img


def _versions(torch):
    return {"torch": torch.__version__, "diffusers": __import__("diffusers").__version__}


def oneshot(a):
    import torch
    t_start = time.time()                 # as before: imports outside load_s
    pipe, device = _load(torch, a)
    embeds = _encode_once(torch, pipe, device, [a["prompt"]]) if a.get("encode_once") else None
    t_load = time.time()
    images = []
    seed = a.get("seed")
    for i in range(int(a["batch"])):
        images.append(_gen(torch, pipe, device, a, a["prompt"],
                           seed + i if seed is not None else None, embeds))
    t_end = time.time()
    buf = io.BytesIO()
    images[-1].save(buf, format="PNG")
    gen_s = round(t_end - t_load, 2)
    print(json.dumps({
        "b64_png": base64.b64encode(buf.getvalue()).decode(),
        "prompt": a["prompt"], "steps": int(a["steps"]), "size": int(a["size_px"]),
        "model": a["repo"], "device": device, "batch_size": int(a["batch"]),
        "load_s": round(t_load - t_start, 2), "gen_s": gen_s,
        "gen_s_per_image": round(gen_s / int(a["batch"]), 2),
        "total_s": round(t_end - t_start, 2), **_versions(torch),
    }), flush=True)


def session(a):
    import torch
    t0 = time.time()
    pipe, device = _load(torch, a)
    prompts = a["prompts"]
    embeds = _encode_once(torch, pipe, device, prompts) if a.get("encode_once") else None
    load_s = round(time.time() - t0, 2)
    seed = int(a.get("seed", 1234))
    t_w = time.time()
    for i in range(int(a.get("warmup", 2))):
        _gen(torch, pipe, device, a, prompts[0], seed + 10_000 + i, embeds)
    warmup_s = round(time.time() - t_w, 2)
    print(json.dumps({"ev": "ready", "device": device, "load_s": load_s,
                      "warmup_s": warmup_s, **_versions(torch)}), flush=True)
    for line in sys.stdin:                     # wait while GoS1 samples the warm baseline
        if line.strip() == "GO":
            break
    per_prompt = int(a["per_prompt"])
    # target_s (Lab buttons, 2026-10-05): keep going until the measured window
    # reaches target_s, so a fast GPU gets as many meter polls as a slow one.
    # per_prompt is then the minimum per prompt.
    target_s = float(a.get("target_s") or 0)
    spans, last, n, firsts = [], None, 0, {}
    t_go = time.time()
    for p_idx, prompt in enumerate(prompts):
        t_p = time.time()
        p_target = target_s * (p_idx + 1) / len(prompts)
        k = 0
        while k < per_prompt or (target_s and time.time() - t_go < p_target):
            last = _gen(torch, pipe, device, a, prompt, seed + p_idx * 1000 + k, embeds)
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
                      "device": device,
                      "noise": "torch-cpu",
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
    (session if args.get("mode") == "session" else oneshot)(args)
