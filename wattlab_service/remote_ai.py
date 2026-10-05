"""
remote_ai.py — LLM inference and image generation on a remote compute host
(CR-085 Part 3). Same contract as remote_video.py: GoS1 drives the host over
SSH, measures on the host's own plugs (power.use_meters), and computes energy
with the SAME functions the local paths use — image_gen._calc_energy for
images, the llm.py arithmetic for inference — so a GoS2 figure and a GoS1
figure differ only by the machine.

Host registry keys used (hosts.py entry):
  "python":   remote interpreter with torch + diffusers (image gen)
  "ollama":   true when the host runs Ollama on its loopback :11434
Image models must exist in GoS1's catalog (IMAGE_MODELS) and be present in the
remote host's HF cache; LLM models in GoS1's catalog (llm.MODELS) and pulled on
the host (same tag + digest — the job records the host's digest).
"""

import asyncio
import json
import random
import shlex
import socket
import subprocess
import time
from typing import Optional

import energy
import hosts
import image_gen
import llm
import power
import remote_video
import settings as cfg
from confidence import confidence

LOCK_FILE = remote_video.LOCK_FILE
REMOTE_IMAGEGEN = "owl_imagegen.py"     # deployed from wattlab_service/remote/


def _scope(host: dict, what: str) -> str:
    return (f"Device layer only ({host['label']}, {host.get('chip', '')}). {what}. "
            "Network and CPE excluded. No amortised training cost.")


async def _poll_while(host: dict, fn):
    """Run blocking `fn` in an executor while sampling the host's meters."""
    stop = asyncio.Event()
    with power.use_meters(host["meters"]):
        poll = asyncio.create_task(power.sample_task(stop, read_watts=power.get_power_watts,
                                                     tuples=True))
    try:
        out = await asyncio.get_event_loop().run_in_executor(None, fn)
    finally:
        stop.set()
        readings = await poll
    return out, readings


# --- Image generation ----------------------------------------------------------

def _remote_generate(host: dict, args: dict) -> dict:
    wd = host.get("workdir", "owl")
    py = host.get("python", f"{wd}/venv/bin/python")
    cmd = f"cd {shlex.quote(wd)} && HF_HUB_OFFLINE=1 {shlex.quote(py)} {REMOTE_IMAGEGEN} {shlex.quote(json.dumps(args))}"
    r = hosts.run(host, cmd, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"{host['label']} image generation failed: {r.stderr[-400:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


async def run_remote_image(prompt: str, job_id: str, host_id: str,
                           model_key: str = "sd-turbo", jobs: dict = None,
                           batch: int = None) -> dict:
    host = hosts.get(host_id)
    if host is None:
        raise ValueError(f"unknown or disabled host '{host_id}'")
    cfg_m = image_gen.IMAGE_MODELS.get(model_key)
    if cfg_m is None:
        raise ValueError(f"Unknown image model: {model_key}")
    if cfg_m.get("loader"):
        raise ValueError(f"{cfg_m['label']} uses a CUDA-only loader — not portable")
    s = cfg.load()
    modifier = random.choice(image_gen.PROMPT_MODIFIERS)
    full_prompt = f"{prompt}, {modifier}"
    args = {"repo": cfg_m["repo"], "prompt": full_prompt, "steps": cfg_m["gpu_steps"],
            "size_px": cfg_m["size_px"], "batch": int(batch or cfg_m["gpu_batch"]), "seed": None,
            "fp16_variant": bool(cfg_m.get("fp16_variant")),
            "torch_dtype": cfg_m.get("torch_dtype", "float16"),
            "guidance_scale": cfg_m.get("guidance_scale", 0.0),
            "pipeline": cfg_m.get("pipeline")}

    if jobs is not None:
        jobs[job_id].update({"stage": "baseline", "full_prompt": full_prompt})
    baseline = await remote_video._baseline(host, s["baseline_polls"])
    LOCK_FILE.write_text(job_id)
    try:
        if jobs is not None: jobs[job_id]["stage"] = "generating"
        gen, readings = await _poll_while(host, lambda: _remote_generate(host, args))
    finally:
        LOCK_FILE.unlink(missing_ok=True)

    w_base = baseline["w_base"]
    w_task = sum(r[1] for r in readings) / len(readings) if readings else w_base
    # Same window convention as GoS1 (image_gen.run_image_measurement):
    # polled across load + generation, ΔT = generation time only.
    e = image_gen._calc_energy(w_base, w_task, gen["gen_s"], readings, gen["batch_size"],
                               baseline["baseline_samples_w"],
                               baseline_dict={"w_base": w_base,
                                              **{k: v for k, v in baseline.items()
                                                 if k.startswith("baseline_samples_w_2")}})
    gen.update({"model_key": model_key, "model_label": cfg_m["label"]})
    return {
        "mode": "gpu",                       # accelerator path, like GoS1's "gpu" mode
        "job_id": job_id, "host": hosts.identity(host),
        "engine": {"id": "gpu", "kind": "hw", "label": f"{host.get('chip', '')} GPU (Metal/MPS)"},
        "prompt": prompt, "full_prompt": full_prompt, "modifier": modifier,
        "model_key": model_key, "model_label": cfg_m["label"],
        "generation": gen, "energy": e,
        **({"bench_batch": int(batch)} if batch else {}),
        "thermals": {"cpu_base": None, "cpu_end": None, "gpu_base": None, "gpu_end": None,
                     "note": "not sampled on remote hosts"},
        "scope": _scope(host, f"GPU (Metal/MPS). Model: {cfg_m['label']} "
                              f"({cfg_m.get('params', '?')}) at {cfg_m['size_px']}px"),
    }


# --- LLM inference ---------------------------------------------------------------

class _Tunnel:
    """ssh -L to the host's loopback Ollama for the duration of one job."""
    def __init__(self, host: dict):
        self.host = host
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.port = sk.getsockname()[1]
        self.proc = None

    def __enter__(self):
        cmd = hosts.ssh_base(self.host)[:-1] + ["-N", "-o", "ExitOnForwardFailure=yes",
               "-L", f"{self.port}:127.0.0.1:11434", self.host["ssh"]]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return self
            except OSError:
                time.sleep(0.2)
        self.proc.terminate()
        raise RuntimeError(f"{self.host['label']}: Ollama tunnel did not open")

    def __exit__(self, *a):
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=5)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _remote_digest(base: str, model: str) -> Optional[str]:
    import urllib.request
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=5) as r:
            for m in json.load(r).get("models", []):
                if m.get("name") == model or m.get("model") == model:
                    return m.get("digest")
    except Exception:
        return None


def _remote_mlx(host: dict, repo: str, prompt: str) -> dict:
    wd = host.get("workdir", "owl")
    py = host.get("python", f"{wd}/venv/bin/python")
    args = json.dumps({"repo": repo, "prompt": prompt})
    r = hosts.run(host, f"cd {shlex.quote(wd)} && HF_HUB_OFFLINE=1 {shlex.quote(py)} "
                        f"owl_mlxgen.py {shlex.quote(args)}", timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"{host['label']} MLX inference failed: {r.stderr[-400:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


async def run_remote_llm(model_key: str, task_key: str, job_id: str, host_id: str,
                         jobs: dict = None, runtime: str = "ollama") -> dict:
    """runtime "ollama" = llama.cpp/GGUF, byte-identical model to GoS1 (the
    controlled comparison). runtime "mlx" = Apple's native mlx-lm with the
    host's `mlx_models[model_key]` conversion (a different engine, labelled so)."""
    host = hosts.get(host_id)
    if host is None:
        raise ValueError(f"unknown or disabled host '{host_id}'")
    if runtime == "mlx":
        return await _run_remote_mlx(model_key, task_key, job_id, host, jobs)
    if not host.get("ollama"):
        raise ValueError(f"host '{host_id}' is not an Ollama host")
    model = llm.MODELS[model_key]
    task = llm.TASKS[task_key]
    s = cfg.load()
    with _Tunnel(host) as tun:
        url = f"{tun.base}/api/generate"
        if jobs is not None: jobs[job_id]["stage"] = "baseline"
        llm.unload_model(model_key, url=url)            # cold start, like GoS1
        await asyncio.sleep(s["llm_unload_settle_s"])
        baseline = await remote_video._baseline(host, s["baseline_polls"])
        LOCK_FILE.write_text(job_id)
        try:
            if jobs is not None:
                jobs[job_id].update({"stage": "gpu_inference", "partial_response": ""})
            inf, readings = await _poll_while(
                host, lambda: llm.run_inference_streaming(model_key, task["prompt"], None, -1,
                                                          url=url))
        finally:
            LOCK_FILE.unlink(missing_ok=True)
        digest = _remote_digest(tun.base, model_key)

    w_base = baseline["w_base"]
    task_samples_w = [round(r[1], 2) for r in readings]
    w_task = sum(r[1] for r in readings) / len(readings) if readings else w_base
    delta_w = round(w_task - w_base, 2)
    meters = power.meters_summary({"w_base": w_base, **{k: v for k, v in baseline.items()
                                   if k.startswith("baseline_samples_w_2")}},
                                  readings, task_samples_w)
    if meters and "delta_w_combined" in meters:
        delta_w = meters["delta_w_combined"]
    delta_t = inf["duration_s"]
    delta_e_wh = energy.energy_wh(delta_w, delta_t)
    out_tok = inf["output_tokens"]
    conf = confidence(delta_w, len(readings), w_base,
                      baseline_samples_w=baseline["baseline_samples_w"],
                      task_samples_w=task_samples_w, meters=meters)
    return {
        "mode": "single", "job_id": job_id, "host": hosts.identity(host),
        "engine": {"id": "gpu", "kind": "hw", "label": f"{host.get('chip', '')} GPU (Metal)",
                   "runtime": "ollama (llama.cpp, GGUF)"},
        "model_key": model_key, "model_label": model["label"],
        "model_params": model.get("params"), "model_digest_remote": digest,
        "task_key": task_key, "task_label": task["label"], "prompt": task["prompt"],
        "warm": False, "device": "gpu",
        "inference": inf,
        "energy": {
            "w_base": round(w_base, 2), "w_task": round(w_task, 2), "delta_w": delta_w,
            "delta_t_s": delta_t, "delta_e_wh": delta_e_wh,
            "mwh_per_token": round(delta_e_wh * 1000 / out_tok, 4) if out_tok else None,
            "poll_count": len(readings),
            "baseline_samples_w": baseline["baseline_samples_w"],
            "task_samples_w": task_samples_w, "confidence": conf,
            **({"meters": meters} if meters else {}),
        },
        "thermals": {"cpu_base": None, "gpu_base": None, "cpu_end": None, "gpu_end": None,
                     "note": "not sampled on remote hosts"},
        "scope": _scope(host, "GPU (Metal) via Ollama"),
    }


async def _run_remote_mlx(model_key: str, task_key: str, job_id: str, host: dict,
                          jobs: dict = None) -> dict:
    repo = (host.get("mlx_models") or {}).get(model_key)
    if not repo:
        raise ValueError(f"{host['label']}: no MLX conversion registered for {model_key}")
    model = llm.MODELS[model_key]
    task = llm.TASKS[task_key]
    s = cfg.load()
    if jobs is not None: jobs[job_id]["stage"] = "baseline"
    baseline = await remote_video._baseline(host, s["baseline_polls"])
    LOCK_FILE.write_text(job_id)
    try:
        if jobs is not None: jobs[job_id]["stage"] = "gpu_inference"
        inf, readings = await _poll_while(host, lambda: _remote_mlx(host, repo, task["prompt"]))
    finally:
        LOCK_FILE.unlink(missing_ok=True)
    w_base = baseline["w_base"]
    task_samples_w = [round(r[1], 2) for r in readings]
    w_task = sum(r[1] for r in readings) / len(readings) if readings else w_base
    delta_w = round(w_task - w_base, 2)
    meters = power.meters_summary({"w_base": w_base, **{k: v for k, v in baseline.items()
                                   if k.startswith("baseline_samples_w_2")}},
                                  readings, task_samples_w)
    if meters and "delta_w_combined" in meters:
        delta_w = meters["delta_w_combined"]
    delta_t = inf["duration_s"]
    delta_e_wh = energy.energy_wh(delta_w, delta_t)
    out_tok = inf["output_tokens"]
    conf = confidence(delta_w, len(readings), w_base,
                      baseline_samples_w=baseline["baseline_samples_w"],
                      task_samples_w=task_samples_w, meters=meters)
    return {
        "mode": "single", "job_id": job_id, "host": hosts.identity(host),
        "engine": {"id": "gpu", "kind": "hw", "label": f"{host.get('chip', '')} GPU (MLX)",
                   "runtime": f"mlx-lm {inf.get('mlx_lm', '?')}"},
        "model_key": model_key, "model_label": f"{model['label']} (MLX {repo.split('/')[-1]})",
        "model_params": model.get("params"), "model_repo_mlx": repo,
        "task_key": task_key, "task_label": task["label"], "prompt": task["prompt"],
        "warm": False, "device": "gpu", "inference": inf,
        "energy": {
            "w_base": round(w_base, 2), "w_task": round(w_task, 2), "delta_w": delta_w,
            "delta_t_s": delta_t, "delta_e_wh": delta_e_wh,
            "mwh_per_token": round(delta_e_wh * 1000 / out_tok, 4) if out_tok else None,
            "poll_count": len(readings),
            "baseline_samples_w": baseline["baseline_samples_w"],
            "task_samples_w": task_samples_w, "confidence": conf,
            **({"meters": meters} if meters else {}),
        },
        "thermals": {"cpu_base": None, "gpu_base": None, "cpu_end": None, "gpu_end": None,
                     "note": "not sampled on remote hosts"},
        "scope": _scope(host, f"GPU via MLX ({repo})"),
    }
