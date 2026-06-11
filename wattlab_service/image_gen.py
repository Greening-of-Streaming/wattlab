import asyncio
import base64
import io
import os
import random
import subprocess
import time
import json
from pathlib import Path
from video import focus_mode_enter, focus_mode_exit
import settings as cfg
from confidence import confidence
import power
from power import get_power_watts, read_sensors_dict, cooldown_between_runs
import gpu

# GPU-vendor env (must be set before torch import). On AMD this sets the ROCm
# HSA_OVERRIDE_GFX_VERSION; on NVIDIA it is a no-op. Vendor-resolved in gpu.py
# so a card swap needs no change here (CR-060).
gpu.BACKEND.torch_env_setup()


LOCK_FILE = Path("/tmp/gos-measure.lock")

# Prompt colour/mood modifiers for variation per run (anti-slideware proof)
PROMPT_MODIFIERS = [
    "bathed in emerald light",
    "under a cobalt sky",
    "in amber afternoon sun",
    "in violet twilight",
    "with a crimson horizon",
    "drenched in golden hour light",
    "in cool silver mist",
    "with deep indigo shadows",
]

IMAGE_MODEL_ID = "stabilityai/sd-turbo"  # default / backwards compat
IMAGE_STEPS_CPU = 8        # ~12s per image on Ryzen 9 7900 — reliable P110 measurement
IMAGE_STEPS_GPU = 20       # ~2s per image on RX 7800 XT — need batch for reliable measurement
IMAGE_STEPS = IMAGE_STEPS_CPU  # default / backwards compat
IMAGE_SIZE = 512           # px, square
GPU_BATCH_SIZE = 5         # GPU generates 5 images (~10s total) → report energy/image = total/5

# Model registry. CPU paths use fp32 (ROCm not available for CPU); GPU uses fp16.
# sd-turbo: ~1B params, 512px, ADD-distilled SD 2.1. Natural 1–4 steps; we use
#   higher step counts to get reliable P110 polls.
# sdxl-turbo: ~3.5B params, ADD-distilled SDXL. Native 1–4 steps, 1024×1024
#   trained but run here at 512×512 for apples-to-apples model comparison and
#   VRAM fit (the automatic SDXL fp32 VAE upcast at 1024 exceeds 12GB).
#   GPU only — CPU fp32 path is impractical (>5min/image).
# CR-050 — IMAGE_MODELS is now a live view from model_catalog. Adding a
# model is a HuggingFace download + a tick on /settings; no edit here.
# Known families (sd-turbo, sdxl-turbo, sdxl-lightning, sana) have full
# operational metadata baked into the catalog. Unknown ones get safe
# defaults — if they don't work well, disable them in /settings.
import model_catalog


class _ImageModelsView:
    def _src(self): return model_catalog.enabled_image_models()
    def __getitem__(self, k): return self._src()[k]
    def get(self, k, default=None): return self._src().get(k, default)
    def __contains__(self, k): return k in self._src()
    def __iter__(self): return iter(self._src())
    def __len__(self): return len(self._src())
    def keys(self):   return self._src().keys()
    def values(self): return self._src().values()
    def items(self):  return self._src().items()


IMAGE_MODELS = _ImageModelsView()

# Shared sampler delegation (CR-065) — legacy signatures/shapes preserved;
# see power.sample_baseline / power.sample_task.
async def measure_baseline(polls: int = 10) -> dict:
    return await power.sample_baseline(polls, read_watts=get_power_watts)

async def poll_during_task(stop_event: asyncio.Event) -> list:
    return await power.sample_task(stop_event, read_watts=get_power_watts,
                                   tuples=True)

def read_sensors() -> dict:
    return read_sensors_dict()

# confidence() is imported from confidence.py (CR-028 Phase 2).

# --- Generation ---

def _load_sdxl_unet_ckpt(cfg_m: dict, torch):
    """Load a UNet-only SDXL distillation (e.g. SDXL-Lightning) by swapping its
    distilled UNet checkpoint into a cached full-SDXL pipeline shell.

    These repos ship a bare `*_unet.safetensors` with no `model_index.json`, so
    `AutoPipelineForText2Image.from_pretrained` fails. Rather than pull the 6.9 GB
    SDXL-base-1.0 repo, we reuse whatever full SDXL pipeline `base_repo` names
    (sdxl-turbo is already cached and shares SDXL's VAE + text encoders + UNet
    architecture). Requires the Euler trailing-timestep schedule + guidance 0
    (generate_image already passes guidance_scale=0.0). CUDA only.

    This is the generic hook for non-AutoPipeline model families; add a new
    `loader` value + branch for the next one (FLUX / SD3.5 with bnb 4-bit, etc.).
    """
    from diffusers import (StableDiffusionXLPipeline, UNet2DConditionModel,
                           EulerDiscreteScheduler)
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file
    base = cfg_m["base_repo"]
    unet = UNet2DConditionModel.from_config(
        UNet2DConditionModel.load_config(base, subfolder="unet")
    ).to("cuda", torch.float16)
    unet.load_state_dict(
        load_file(hf_hub_download(cfg_m["repo"], cfg_m["unet_ckpt"]), device="cuda")
    )
    pipe = StableDiffusionXLPipeline.from_pretrained(
        base, unet=unet, torch_dtype=torch.float16, variant="fp16",
    ).to("cuda")
    pipe.scheduler = EulerDiscreteScheduler.from_config(
        pipe.scheduler.config, timestep_spacing="trailing")
    return pipe


def _load_flux_nf4(cfg_m: dict, torch):
    """Load FLUX.1-schnell with bitsandbytes NF4 4-bit on the 12B transformer +
    the T5-XXL text encoder (~13 GB VRAM resident vs ~24 GB fp16 — fits the
    16 GB 5080). NF4 4-bit is the CUDA gate (model_catalog marks it cuda_only),
    smoke-tested for sm_120 correctness on the RTX 5080 (bitsandbytes 0.49.2).

    Everything stays resident on the GPU (no model-CPU-offload) so the energy
    measurement isn't confounded by host<->device weight shuffling."""
    from diffusers import FluxPipeline, FluxTransformer2DModel
    from diffusers import BitsAndBytesConfig as _DiffBnb
    from transformers import T5EncoderModel
    from transformers import BitsAndBytesConfig as _TfBnb
    repo = cfg_m["repo"]
    diff_nf4 = _DiffBnb(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                        bnb_4bit_compute_dtype=torch.float16)
    tf_nf4 = _TfBnb(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.float16)
    transformer = FluxTransformer2DModel.from_pretrained(
        repo, subfolder="transformer",
        quantization_config=diff_nf4, torch_dtype=torch.float16)
    text_encoder_2 = T5EncoderModel.from_pretrained(
        repo, subfolder="text_encoder_2",
        quantization_config=tf_nf4, torch_dtype=torch.float16)
    pipe = FluxPipeline.from_pretrained(
        repo, transformer=transformer, text_encoder_2=text_encoder_2,
        torch_dtype=torch.float16)
    # The two NF4 components are already on cuda; .to() moves the fp16 VAE +
    # CLIP encoder and is a no-op (skipped) for the quantized modules.
    pipe = pipe.to("cuda")
    return pipe


def generate_image(prompt: str, seed: int = None, device: str = "cpu",
                   model_key: str = "sd-turbo",
                   steps_override: int = None,
                   batch_override: int = None) -> dict:
    """Run text-to-image generation on CPU or GPU for the named model.
    GPU mode generates model-specific batch size and reports energy/image.
    Compare-models mode passes steps_override/batch_override to force the
    native operating point across both models.
    Returns base64 PNG of last image + timing."""
    from diffusers import AutoPipelineForText2Image
    import torch

    cfg_m = IMAGE_MODELS.get(model_key)
    if cfg_m is None:
        raise ValueError(f"Unknown image model: {model_key}")

    use_gpu = (device == "gpu")
    if not use_gpu and not cfg_m["cpu_ok"]:
        raise ValueError(f"Model {model_key} is GPU-only (CPU path disabled)")

    steps = steps_override if steps_override is not None else (
        cfg_m["gpu_steps"] if use_gpu else cfg_m["cpu_steps"])
    batch = batch_override if batch_override is not None else (
        cfg_m["gpu_batch"] if use_gpu else 1)
    size_px = cfg_m["size_px"]
    repo = cfg_m["repo"]

    t_start = time.time()
    pipe = None
    try:
        loader = cfg_m.get("loader")
        if loader == "sdxl_unet_ckpt":
            # UNet-only distillation (e.g. SDXL-Lightning) — no model_index.json,
            # so AutoPipeline can't load it. Swap the checkpoint into a cached
            # full-SDXL shell. GPU/CUDA only (cpu_ok is False for these).
            pipe = _load_sdxl_unet_ckpt(cfg_m, torch)
        elif loader == "flux_nf4":
            # 12B FLUX.1-schnell via bitsandbytes NF4 4-bit (CUDA-only).
            pipe = _load_flux_nf4(cfg_m, torch)
        elif use_gpu:
            kwargs = {"torch_dtype": torch.float16}
            if cfg_m.get("fp16_variant"):
                kwargs["variant"] = "fp16"
            pipe = AutoPipelineForText2Image.from_pretrained(repo, **kwargs)
            pipe = pipe.to("cuda")
        else:
            pipe = AutoPipelineForText2Image.from_pretrained(
                repo,
                torch_dtype=torch.float32,
            )
        t_load = time.time()

        images = []
        for i in range(batch):
            gen = torch.Generator().manual_seed(seed + i) if seed is not None else None
            result = pipe(
                prompt=prompt,
                num_inference_steps=steps,
                guidance_scale=0.0,
                height=size_px,
                width=size_px,
                generator=gen,
            )
            images.append(result.images[0])
        t_end = time.time()

        # Encode the last generated image to base64 PNG
        buf = io.BytesIO()
        images[-1].save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        total_s = round(t_end - t_start, 2)
        gen_s = round(t_end - t_load, 2)

        return {
            "b64_png": b64,
            "prompt": prompt,
            "steps": steps,
            "size": size_px,
            "model": repo,
            "model_key": model_key,
            "model_label": cfg_m["label"],
            "device": device,
            "batch_size": batch,
            "load_s": round(t_load - t_start, 2),
            "gen_s": gen_s,
            "gen_s_per_image": round(gen_s / batch, 2),
            "total_s": total_s,
        }
    finally:
        # Release pipeline weights so the uvicorn worker doesn't accumulate
        # VRAM across sequential image jobs (otherwise each run strands its
        # ~2GB of UNet + text-encoder weights until Python GC eventually runs).
        if pipe is not None:
            del pipe
        import gc
        gc.collect()
        if use_gpu and torch.cuda.is_available():
            torch.cuda.empty_cache()


def _calc_energy(w_base: float, w_task: float, delta_t: float,
                 readings: list, batch: int, baseline_samples: list = None,
                 baseline_dict: dict = None) -> dict:
    poll_count = len(readings)
    delta_w = round(w_task - w_base, 2)
    task_samples = [round(r[1], 2) for r in readings]
    meters = power.meters_summary(baseline_dict, readings, task_samples)
    if meters and "delta_w_combined" in meters:
        delta_w = meters["delta_w_combined"]
    delta_e_wh = round(delta_w * (delta_t / 3600), 4)
    wh_per_image = round(delta_e_wh / batch, 4)
    conf = confidence(delta_w, poll_count, w_base,
                      baseline_samples_w=baseline_samples,
                      task_samples_w=task_samples, meters=meters)
    return {
        "w_base": round(w_base, 2),
        "w_task": round(w_task, 2),
        "delta_w": delta_w,
        "delta_t_s": round(delta_t, 2),
        "delta_e_wh": delta_e_wh,
        "wh_per_image": wh_per_image,
        "poll_count": poll_count,
        "baseline_samples_w": baseline_samples,
        "task_samples_w": task_samples,
        "confidence": conf,
        **({"meters": meters} if meters else {}),
    }


async def _run_single_image(prompt: str, device: str, job_id: str,
                             jobs: dict, stage_prefix: str,
                             stopped_timers: list,
                             model_key: str = "sd-turbo",
                             seed: int = None,
                             steps_override: int = None,
                             batch_override: int = None) -> dict:
    """Run one image measurement pass (CPU or GPU). Returns result dict."""
    s = cfg.load()

    if jobs is not None:
        jobs[job_id]["stage"] = f"{stage_prefix}_baseline"

    sensors_base = read_sensors()
    _baseline = await measure_baseline(polls=s["baseline_polls"])
    w_base = _baseline["w_base"]
    baseline_samples_w = _baseline["samples_w"]

    if jobs is not None:
        jobs[job_id]["stage"] = f"{stage_prefix}_generating"

    stop_event = asyncio.Event()
    poll_task = asyncio.create_task(poll_during_task(stop_event))

    gen_result = await asyncio.get_event_loop().run_in_executor(
        None, generate_image, prompt, seed, device, model_key,
        steps_override, batch_override
    )

    stop_event.set()
    readings = await poll_task

    sensors_end = read_sensors()
    batch = gen_result["batch_size"]
    delta_t = gen_result["gen_s"]   # measure only generation time, not load time
    w_task = sum(r[1] for r in readings) / len(readings) if readings else w_base
    energy = _calc_energy(w_base, w_task, delta_t, readings, batch,
                          baseline_samples_w, baseline_dict=_baseline)

    return {
        "device": device,
        "model_key": model_key,
        "generation": gen_result,
        "energy": energy,
        "thermals": {
            "cpu_base": sensors_base.get("cpu_tctl"),
            "cpu_end": sensors_end.get("cpu_tctl"),
            "gpu_base": sensors_base.get("gpu_junction"),
            "gpu_end": sensors_end.get("gpu_junction"),
        },
    }


# --- Main measurement entry points ---

async def run_image_measurement(prompt: str, job_id: str,
                                jobs: dict = None,
                                device: str = "cpu",
                                model_key: str = "sd-turbo") -> dict:
    s = cfg.load()

    cfg_m = IMAGE_MODELS.get(model_key)
    if cfg_m is None:
        raise ValueError(f"Unknown image model: {model_key}")
    if device == "cpu" and not cfg_m["cpu_ok"]:
        raise ValueError(f"{cfg_m['label']} is GPU-only")

    modifier = random.choice(PROMPT_MODIFIERS)
    full_prompt = f"{prompt}, {modifier}"

    if jobs is not None:
        jobs[job_id]["stage"] = "baseline"
        jobs[job_id]["full_prompt"] = full_prompt

    stopped = focus_mode_enter()
    sensors_base = read_sensors()
    _baseline = await measure_baseline(polls=s["baseline_polls"])
    w_base = _baseline["w_base"]
    baseline_samples_w = _baseline["samples_w"]

    LOCK_FILE.write_text(job_id)

    if jobs is not None:
        jobs[job_id]["stage"] = "generating"

    stop_event = asyncio.Event()
    poll_task = asyncio.create_task(poll_during_task(stop_event))

    gen_result = await asyncio.get_event_loop().run_in_executor(
        None, generate_image, full_prompt, None, device, model_key
    )

    stop_event.set()
    readings = await poll_task

    LOCK_FILE.unlink(missing_ok=True)
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, focus_mode_exit, stopped)

    if jobs is not None:
        jobs[job_id]["stage"] = "done"

    sensors_end = read_sensors()
    batch = gen_result["batch_size"]
    delta_t = gen_result["gen_s"]
    w_task = sum(r[1] for r in readings) / len(readings) if readings else w_base
    energy = _calc_energy(w_base, w_task, delta_t, readings, batch,
                          baseline_samples_w, baseline_dict=_baseline)

    device_label = f"GPU ({gpu.BACKEND.device_label()})" if device == "gpu" else "CPU (Ryzen 9 7900)"
    scope = (f"Device layer only (GoS1). {device_label}. "
             f"Model: {cfg_m['label']} ({cfg_m['params']}) at {cfg_m['size_px']}px. "
             f"No amortised training cost.")

    return {
        "mode": device,
        "job_id": job_id,
        "prompt": prompt,
        "full_prompt": full_prompt,
        "modifier": modifier,
        "model_key": model_key,
        "model_label": cfg_m["label"],
        "generation": gen_result,
        "energy": energy,
        "thermals": {
            "cpu_base": sensors_base.get("cpu_tctl"),
            "cpu_end": sensors_end.get("cpu_tctl"),
            "gpu_base": sensors_base.get("gpu_junction"),
            "gpu_end": sensors_end.get("gpu_junction"),
        },
        "scope": scope,
    }


async def run_image_both_measurement(prompt: str, job_id: str,
                                     jobs: dict = None,
                                     model_key: str = "sd-turbo") -> dict:
    """Run CPU pass then GPU pass, with cooldown in between. Report comparison."""
    s = cfg.load()

    cfg_m = IMAGE_MODELS.get(model_key)
    if cfg_m is None:
        raise ValueError(f"Unknown image model: {model_key}")
    if not cfg_m["cpu_ok"]:
        raise ValueError(f"{cfg_m['label']} is GPU-only — cannot run CPU vs GPU comparison")

    modifier = random.choice(PROMPT_MODIFIERS)
    full_prompt = f"{prompt}, {modifier}"

    if jobs is not None:
        jobs[job_id]["stage"] = "baseline_cpu"
        jobs[job_id]["full_prompt"] = full_prompt

    stopped = focus_mode_enter()
    LOCK_FILE.write_text(job_id)

    # --- CPU pass ---
    cpu_result = await _run_single_image(full_prompt, "cpu", job_id, jobs,
                                          "cpu", stopped, model_key=model_key)

    # --- Cooldown (unified dispatcher: idle-wait or fixed per settings) ---
    # reference_w = the CPU pass's cold baseline. Binary compare → allow_dialog
    # stays False (focus/lock held across this gap, no try/finally here).
    cd_cpu_gpu = await cooldown_between_runs(
        fixed_seconds=s.get("video_cooldown_s", 30),
        reference_w=(cpu_result.get("energy") or {}).get("w_base"),
        stage="cooldown", jobs=jobs, job_id=job_id,
    )

    # --- GPU pass ---
    gpu_result = await _run_single_image(full_prompt, "gpu", job_id, jobs,
                                          "gpu", stopped, model_key=model_key)

    LOCK_FILE.unlink(missing_ok=True)
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, focus_mode_exit, stopped)

    if jobs is not None:
        jobs[job_id]["stage"] = "done"

    analysis = _analyse_image(cpu_result, gpu_result)

    return {
        "mode": "both",
        "job_id": job_id,
        "prompt": prompt,
        "full_prompt": full_prompt,
        "modifier": modifier,
        "model_key": model_key,
        "model_label": cfg_m["label"],
        "cpu": cpu_result,
        "gpu": gpu_result,
        "analysis": analysis,
        "cooldown": cd_cpu_gpu,
        "scope": (f"Device layer only (GoS1). CPU vs GPU comparison. "
                  f"Model: {cfg_m['label']} ({cfg_m['params']}). "
                  f"No amortised training cost."),
    }


async def run_image_compare_models_measurement(prompt: str, job_id: str,
                                                jobs: dict = None) -> dict:
    """CR-050 follow-up — run every enabled image model on GPU with same
    prompt + seed. Between models, actively polls power and waits until it
    returns to within ±3 W of model #1's baseline (max 120 s cap) so a hot
    GPU from one model doesn't contaminate the next baseline.
    Each model uses its own compare_steps/compare_batch from the catalog.

    Returns:
      mode='compare_models', models=[per-model results in panel order],
      analysis={cheapest, priciest, ratio, finding},
      cooldowns=[per-gap diagnostics],
      small/large aliases for backwards-compat with legacy 2-model renderers.
    """
    panel = list(IMAGE_MODELS.keys())
    if len(panel) < 2:
        raise ValueError("compare-models requires at least 2 enabled image models")

    modifier = random.choice(PROMPT_MODIFIERS)
    full_prompt = f"{prompt}, {modifier}"
    # Same seed for every model so any quality difference comes from the model,
    # not from latent noise.
    seed = int(time.time()) % (2**31)

    if jobs is not None:
        jobs[job_id]["stage"] = "m1_baseline"
        jobs[job_id]["full_prompt"] = full_prompt
        jobs[job_id]["total_models"] = len(panel)

    stopped = focus_mode_enter()
    LOCK_FILE.write_text(job_id)

    results = []
    floor_reference_w = None
    cooldowns = []
    failures = []
    try:
        for idx, mk in enumerate(panel, start=1):
            mc = IMAGE_MODELS[mk]
            if jobs is not None:
                jobs[job_id]["current_model_idx"] = idx
                jobs[job_id]["current_model"] = mk
                jobs[job_id]["current_model_label"] = mc.get("label", mk)
            if idx > 1 and floor_reference_w is not None:
                if jobs is not None:
                    jobs[job_id]["stage"] = "cooldown"
                cd = await cooldown_between_runs(
                    fixed_seconds=cfg.load().get("video_cooldown_s", 60),
                    reference_w=floor_reference_w,
                    stage="cooldown", jobs=jobs, job_id=job_id,
                    allow_dialog=True,
                )
                cooldowns.append({"before_model": mk, **cd})
            slot = f"m{idx}"
            try:
                r = await _run_single_image(
                    full_prompt, "gpu", job_id, jobs, slot, stopped,
                    model_key=mk, seed=seed,
                    steps_override=mc.get("compare_steps", 4),
                    batch_override=mc.get("compare_batch", 4),
                )
            except Exception as ex:
                # A model that fails to load/run must not take down the whole
                # panel — record it and continue. (e.g. SDXL-Lightning is a
                # UNet-only checkpoint with no model_index.json.) The surviving
                # models still produce a comparison.
                failures.append({"model_key": mk, "model_label": mc.get("label", mk),
                                 "error": str(ex)})
                if jobs is not None:
                    jobs[job_id].setdefault("model_errors", []).append(
                        {"model": mk, "error": str(ex)})
                continue
            r["model_key"] = mk
            results.append(r)
            if floor_reference_w is None:
                floor_reference_w = (r.get("energy") or {}).get("w_base")
    finally:
        LOCK_FILE.unlink(missing_ok=True)
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, focus_mode_exit, stopped)

    if not results:
        raise RuntimeError(
            "all image models failed: "
            + "; ".join(f"{f['model_key']}: {f['error']}" for f in failures))

    if jobs is not None:
        jobs[job_id]["stage"] = "done"

    analysis = _analyse_models_n(results)

    # Legacy aliases so any caller still reading r.small/r.large (older
    # rendering paths, stored-result comparisons) keeps working: smallest
    # and largest by Wh/image, falling back to first/last if energy missing.
    by_wh = sorted(
        [r for r in results if (r.get("energy") or {}).get("wh_per_image") is not None],
        key=lambda r: r["energy"]["wh_per_image"],
    )
    small_alias = by_wh[0] if by_wh else (results[0] if results else {})
    large_alias = by_wh[-1] if len(by_wh) > 1 else (results[-1] if len(results) > 1 else small_alias)

    return {
        "mode": "compare_models",
        "job_id": job_id,
        "prompt": prompt,
        "full_prompt": full_prompt,
        "modifier": modifier,
        "seed": seed,
        "models": results,
        "model_errors": failures,
        "small": small_alias,
        "large": large_alias,
        "analysis": analysis,
        "floor_reference_w": floor_reference_w,
        "cooldowns": cooldowns,
        "scope": (f"Device layer only (GoS1). GPU (RX 7800 XT, ROCm). "
                  f"{len(results)} models compared at each model's native "
                  f"compare_steps/compare_batch from the catalog. Same prompt "
                  f"+ seed. Between models the runner waits for the system "
                  f"to return to ±3 W of model #1's baseline. Image quality "
                  f"is subjective — shown side-by-side."),
    }


def _analyse_models_n(results: list) -> dict:
    """N-way analysis: find cheapest + priciest by Wh/image, ratio, finding."""
    valid = [r for r in results
             if (r.get("energy") or {}).get("wh_per_image") is not None]
    if not valid:
        return {"finding": "No models produced a valid measurement.",
                "ratio_priciest_over_cheapest": None}
    by_wh = sorted(valid, key=lambda r: r["energy"]["wh_per_image"])
    cheapest = by_wh[0]
    priciest = by_wh[-1]
    c_wh = cheapest["energy"]["wh_per_image"]
    p_wh = priciest["energy"]["wh_per_image"]
    c_label = cheapest.get("generation", {}).get("model_label") or cheapest.get("model_key", "?")
    p_label = priciest.get("generation", {}).get("model_label") or priciest.get("model_key", "?")
    ratio = round(p_wh / c_wh, 2) if c_wh else None
    if len(valid) == 1:
        finding = f"Only one model produced a valid measurement ({c_label})."
    elif ratio and ratio > 1.05:
        finding = (f"{p_label} uses {ratio}× more energy per image than {c_label}. "
                   f"Quality is subjective — shown side-by-side for visual comparison.")
    else:
        finding = f"Per-image energy roughly matched across {len(valid)} models."
    return {
        "cheapest_model_key":   cheapest.get("model_key"),
        "cheapest_wh_per_image": c_wh,
        "priciest_model_key":   priciest.get("model_key"),
        "priciest_wh_per_image": p_wh,
        "ratio_priciest_over_cheapest": ratio,
        "finding": finding,
    }


def _analyse_models(small: dict, large: dict) -> dict:
    s_e = small["energy"]
    l_e = large["energy"]
    s_wh = s_e["wh_per_image"]
    l_wh = l_e["wh_per_image"]
    s_t  = small["generation"]["gen_s_per_image"]
    l_t  = large["generation"]["gen_s_per_image"]

    energy_ratio = round(l_wh / s_wh, 2) if s_wh else None
    time_ratio   = round(l_t / s_t, 2)   if s_t   else None

    finding = (
        f"Larger model uses {energy_ratio}× more energy per image "
        f"and takes {time_ratio}× longer. "
        f"Quality difference is visible in the side-by-side output — "
        f"whether it's worth the extra energy is a subjective call."
    )
    return {
        "energy_ratio_large_over_small": energy_ratio,
        "time_ratio_large_over_small":   time_ratio,
        "small_wh_per_image": s_wh,
        "large_wh_per_image": l_wh,
        "finding": finding,
    }


def _analyse_image(cpu: dict, gpu: dict) -> dict:
    cpu_e = cpu["energy"]
    gpu_e = gpu["energy"]
    cpu_wh = cpu_e["wh_per_image"]
    gpu_wh = gpu_e["wh_per_image"]
    cpu_t = cpu["generation"]["gen_s_per_image"]
    gpu_t = gpu["generation"]["gen_s_per_image"]

    energy_winner = "cpu" if cpu_wh <= gpu_wh else "gpu"
    speed_winner = "gpu" if gpu_t < cpu_t else "cpu"

    energy_diff_pct = round(abs(cpu_wh - gpu_wh) / max(cpu_wh, gpu_wh) * 100, 1)
    speed_diff_pct = round(abs(cpu_t - gpu_t) / max(cpu_t, gpu_t) * 100, 1)

    if speed_winner == "gpu":
        finding = (f"GPU {speed_diff_pct}% faster per image. "
                   f"{'CPU' if energy_winner == 'cpu' else 'GPU'} {energy_diff_pct}% "
                   f"more energy efficient.")
    else:
        finding = (f"CPU {speed_diff_pct}% faster per image. "
                   f"{'CPU' if energy_winner == 'cpu' else 'GPU'} {energy_diff_pct}% "
                   f"more energy efficient.")

    return {
        "energy_winner": energy_winner,
        "speed_winner": speed_winner,
        "energy_diff_pct": energy_diff_pct,
        "speed_diff_pct": speed_diff_pct,
        "finding": finding,
    }
