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
        pipe = DiffusionPipeline.from_pretrained(a["repo"], **kwargs).to(device)
    else:
        pipe = AutoPipelineForText2Image.from_pretrained(a["repo"], **kwargs).to(device)
    _sync(torch, device)
    return pipe, device


def _gen(torch, pipe, device, a, prompt, seed):
    gen = torch.Generator().manual_seed(seed) if seed is not None else None
    img = pipe(prompt=prompt, num_inference_steps=int(a["steps"]),
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
    t_load = time.time()
    images = []
    seed = a.get("seed")
    for i in range(int(a["batch"])):
        images.append(_gen(torch, pipe, device, a, a["prompt"],
                           seed + i if seed is not None else None))
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
    load_s = round(time.time() - t0, 2)
    prompts = a["prompts"]
    seed = int(a.get("seed", 1234))
    t_w = time.time()
    for i in range(int(a.get("warmup", 2))):
        _gen(torch, pipe, device, a, prompts[0], seed + 10_000 + i)
    warmup_s = round(time.time() - t_w, 2)
    print(json.dumps({"ev": "ready", "device": device, "load_s": load_s,
                      "warmup_s": warmup_s, **_versions(torch)}), flush=True)
    for line in sys.stdin:                     # wait while GoS1 samples the warm baseline
        if line.strip() == "GO":
            break
    per_prompt = int(a["per_prompt"])
    spans, last = [], None
    t_go = time.time()
    for p_idx, prompt in enumerate(prompts):
        t_p = time.time()
        for k in range(per_prompt):
            last = _gen(torch, pipe, device, a, prompt, seed + p_idx * 1000 + k)
            print(json.dumps({"ev": "img", "p": p_idx, "k": k}), flush=True)
        spans.append(round(time.time() - t_p, 3))
    gen_s = round(time.time() - t_go, 3)
    n = per_prompt * len(prompts)
    buf = io.BytesIO()
    last.resize((256, 256)).save(buf, format="PNG")
    print(json.dumps({"ev": "done", "gen_s": gen_s, "n_images": n,
                      "s_per_image": round(gen_s / n, 4), "per_prompt_s": spans,
                      "device": device,
                      "thumb_b64_png": base64.b64encode(buf.getvalue()).decode()}), flush=True)


if __name__ == "__main__":
    args = json.loads(sys.argv[1])
    (session if args.get("mode") == "session" else oneshot)(args)
