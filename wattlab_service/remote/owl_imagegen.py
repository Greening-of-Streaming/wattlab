"""
owl_imagegen.py — remote-side text-to-image runner (CR-085 Part 3).

Deployed to a remote compute host (GoS2: ~/owl/owl_imagegen.py) and invoked
over SSH by GoS1's service (remote_ai.py). Mirrors image_gen.generate_image's
GPU path exactly — same pipeline class, fp16, guidance 0, steps, size, batch,
seeds — on the host's accelerator (Apple silicon: torch "mps"). Prints ONE
JSON line with the same keys generate_image returns, so the energy arithmetic
on GoS1 (image_gen._calc_energy) is shared, unchanged.

Usage: python owl_imagegen.py '<json args>'
  args = {repo, prompt, steps, size_px, batch, seed, fp16_variant, device}
"""
import base64
import io
import json
import sys
import time


def main():
    a = json.loads(sys.argv[1])
    import torch
    from diffusers import AutoPipelineForText2Image

    device = a.get("device") or ("mps" if torch.backends.mps.is_available() else "cpu")
    t_start = time.time()
    kwargs = {"torch_dtype": getattr(torch, a.get("torch_dtype") or "float16")
              if device != "cpu" else torch.float32}
    if a.get("fp16_variant") and device != "cpu":
        kwargs["variant"] = "fp16"
    if a.get("pipeline") == "diffusion":
        from diffusers import DiffusionPipeline
        pipe = DiffusionPipeline.from_pretrained(a["repo"], **kwargs).to(device)
    else:
        pipe = AutoPipelineForText2Image.from_pretrained(a["repo"], **kwargs).to(device)
    if device == "mps":
        torch.mps.synchronize()
    t_load = time.time()

    images = []
    seed = a.get("seed")
    for i in range(int(a["batch"])):
        gen = torch.Generator().manual_seed(seed + i) if seed is not None else None
        r = pipe(prompt=a["prompt"], num_inference_steps=int(a["steps"]),
                 guidance_scale=float(a.get("guidance_scale", 0.0)),
                 height=int(a["size_px"]), width=int(a["size_px"]),
                 generator=gen)
        images.append(r.images[0])
    if device == "mps":
        torch.mps.synchronize()
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
        "total_s": round(t_end - t_start, 2),
        "torch": torch.__version__,
        "diffusers": __import__("diffusers").__version__,
    }))


if __name__ == "__main__":
    main()
