# GPU swap checklist — RX 7800 XT → RTX 5080 (CR-060)

**Written:** 2026-05-29, immediately before power-down for the swap.
**Why this exists:** the code side (CR-060 `gpu.py`) auto-detects the card at
boot, so the swap needs **no code edits** — but the GPU *driver* and the *torch
wheel* are not auto-handled. This is that manual list, plus a clean rollback.

The OWL service is `enabled` and starts on boot. `gpu.py` resolves the backend
once at import: probes `nvidia-smi`, then AMD `sensors` (amdgpu `junction`
chip), else `NoGpuBackend`. Override with `OWL_GPU_VENDOR=amd|nvidia|none`.

---

## Frozen pre-swap state (the rollback target)

| Item | Value |
|---|---|
| Discrete card (out) | AMD Radeon RX 7800 XT — Navi 32, was at PCI `04:00.0` |
| iGPU (stays) | AMD Raphael `0e:00.0` — reports only `edge`/`PPT`, never `junction`, so it never false-detects as the discrete card |
| torch stack | `torch==2.5.1+rocm6.2`, `torchvision==0.20.1+rocm6.2`, `pytorch-triton-rocm==3.1.0` |
| rocm wheel index | `https://download.pytorch.org/whl/rocm6.2` |
| amdgpu driver | **in-kernel module** — nothing to install/reinstall for AMD |
| Mesa VA | `mesa-amdgpu-va-drivers` **apt-held** (CR-022) — must stay held |
| ffmpeg | `/usr/local/bin/ffmpeg-master` already ships `h264/hevc/av1_nvenc` + `scale_cuda` — **no rebuild** |
| AMD energy baseline | `docs/gpu_swap_amd_baseline.md` (compare after swap) |

---

## After the 5080 is in — bring-up

1. **Boot and confirm the service survived.** With no Nvidia driver yet, OWL
   falls back to `NoGpuBackend` (CPU paths work, GPU encode disabled — this is
   expected, not a failure). Check:
   ```
   systemctl is-active wattlab
   curl -s localhost:8000/methodology | grep -i gpu   # or just load /video
   ```

2. **Install the Nvidia driver + CUDA** (Blackwell needs a recent driver — CUDA
   **12.8+**). After install:
   ```
   nvidia-smi   # must list "RTX 5080"
   sudo systemctl restart wattlab   # re-run gpu.detect() so it picks up NvidiaBackend
   ```
   → GPU **video (NVENC)** now works with zero code changes.

3. **Swap torch to CUDA — use a Blackwell-capable build.** The 5080 is Blackwell
   (`sm_120`); `torch 2.5.1+cu124` has **no kernels for it** and image-gen will
   throw *"no kernel image available"*. Install a CUDA-12.8 build (torch ≥ 2.7):
   ```
   python3 -m pip uninstall -y torch torchvision pytorch-triton-rocm
   python3 -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
   python3 -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
   sudo systemctl restart wattlab
   ```
   → GPU **image-gen (CUDA)** now works. (Until this step it falls back to CPU.)

4. **Sanity-check before trusting numbers.** The `NvidiaBackend` presets
   (`-rc cbr`, `av1_nvenc` with no `-profile`) have never run on real hardware.
   Run one `/video` GPU pass per codec and one `/image` GPU pass; eyeball the
   output + that `power.read_sensors_dict()` returns real `gpu_junction`/`gpu_ppt_w`.

5. **Re-run the in-app benchmark** (CR-061) and compare to the frozen AMD
   baseline in `docs/gpu_swap_amd_baseline.md`. Note: NVENC `power.draw` is
   *instantaneous* vs AMD `power1_average` — see the CR-060 open question before
   reading too much into small power deltas.

---

## ROLLBACK — putting the RX 7800 XT back in

Cheap and low-risk: `amdgpu` is in-kernel and Mesa is held, so there's **no AMD
driver to reinstall**. Only torch has to be reverted.

1. Power down, reseat the **RX 7800 XT**, boot.
2. `gpu.py` auto-detects AMD again (no code edit). Confirm:
   ```
   sensors | grep -iA2 junction        # discrete card reports junction
   sudo systemctl restart wattlab
   ```
3. **Revert torch to the rocm wheel** (exact pins from the frozen state above):
   ```
   python3 -m pip uninstall -y torch torchvision
   python3 -m pip install torch==2.5.1+rocm6.2 torchvision==0.20.1+rocm6.2 \
       pytorch-triton-rocm==3.1.0 --index-url https://download.pytorch.org/whl/rocm6.2
   python3 -c "import torch; print(torch.__version__, torch.cuda.is_available())"
   sudo systemctl restart wattlab
   ```
4. Verify Mesa is still held (a CUDA-side `apt` op shouldn't have touched it, but
   check): `apt-mark showhold | grep mesa` → expect `mesa-amdgpu-va-drivers`.
5. Optional belt-and-braces while diagnosing: force the backend with
   `OWL_GPU_VENDOR=amd` in the service env until detection is confirmed.

> **Tip for a fast round-trip:** if you expect to swap back and forth, cache the
> rocm wheels on the 4TB disk now so reinstall is offline/instant:
> `pip download torch==2.5.1+rocm6.2 torchvision==0.20.1+rocm6.2 pytorch-triton-rocm==3.1.0 --index-url https://download.pytorch.org/whl/rocm6.2 -d /srv/data/owl/wheels/rocm62`
> then rollback step 3 becomes `pip install /srv/data/owl/wheels/rocm62/*.whl`.
