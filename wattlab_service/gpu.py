"""
gpu.py — GPU vendor abstraction for WattLab (CR-060).

One job: isolate every vendor-specific assumption about the discrete GPU
(AMD VAAPI/ROCm vs NVIDIA NVENC/CUDA) behind a single resolved backend so
that swapping the physical card only requires a reboot — no code edits.

Detection runs ONCE at import and is cached in `BACKEND`. The wattlab
systemd service restarts on boot, so a card swap is picked up automatically
the next time the box comes up. Force a vendor for testing with the
`OWL_GPU_VENDOR` env var (amd | nvidia | none).

Consumers:
  - power.read_sensors_dict()  -> BACKEND.read_gpu_sensors()
  - video.PRESETS (GPU entries) -> BACKEND.ffmpeg_* helpers
  - image_gen                   -> BACKEND.torch_env_setup() / device_label()
  - persist (result stamp)      -> BACKEND.stamp()

The AMD backend reproduces the exact VAAPI commands and sensor lookups OWL
shipped before this module existed — it is the regression baseline. The
NVIDIA backend is a best-effort first cut to be validated/tuned once the
RTX 5080 is physically installed.
"""

import json
import os
import subprocess


def _run(cmd: list, timeout: int = 5) -> "str | None":
    """Best-effort subprocess capture. Returns stdout or None on any failure."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r.stdout
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------
# AMD — VAAPI encode + ROCm + lm-sensors amdgpu chip
# --------------------------------------------------------------------------
class AmdBackend:
    vendor = "amd"
    available = True

    def __init__(self, name: str = "AMD discrete GPU"):
        self.name = name

    # --- thermals (sensors -j amdgpu chip) ---------------------------------
    @staticmethod
    def _amdgpu_chip(data: dict) -> "str | None":
        """The discrete card is the only amdgpu chip reporting `junction`
        (the iGPU exposes just edge/PPT). Resolve by that, never by PCI
        address — enumeration shifts it (see power.py history / CR notes)."""
        return next((k for k, v in data.items()
                     if k.startswith('amdgpu') and isinstance(v, dict) and 'junction' in v),
                    None)

    def read_gpu_sensors(self) -> dict:
        try:
            out = _run(['sensors', '-j'])
            data = json.loads(out)
            chip = self._amdgpu_chip(data)
            return {
                "gpu_junction": data.get(chip, {}).get('junction', {}).get('temp2_input'),
                "gpu_ppt_w": data.get(chip, {}).get('PPT', {}).get('power1_average'),
            }
        except Exception:
            return {"gpu_junction": None, "gpu_ppt_w": None}

    # --- ffmpeg GPU encode pieces ------------------------------------------
    _ENCODER = {"h264": "h264_vaapi", "h265": "hevc_vaapi", "av1": "av1_vaapi"}

    def ffmpeg_hwaccel_args(self) -> list:
        return ["-hwaccel", "vaapi", "-hwaccel_output_format", "vaapi",
                "-extra_hw_frames", "32",
                "-vaapi_device", "/dev/dri/renderD128"]

    def ffmpeg_scale_filter(self, height: int = 1080) -> str:
        return f"scale_vaapi=w=-2:h={height}:format=nv12"

    def ffmpeg_encoder(self, codec: str) -> str:
        return self._ENCODER[codec]

    def ffmpeg_gpu_norm_args(self, codec: str, gop: str) -> list:
        # AMD VAAPI caps B-frames in hardware (H.264 reorder depth 1, HEVC 0),
        # but we still request -bf 2 on h264/h265 to match the CPU task; AV1
        # uses native alt-ref (no -bf). Profiles pinned explicit.
        return {
            "h264": ["-g", gop, "-profile:v", "high", "-bf", "2"],
            "h265": ["-g", gop, "-profile:v", "main", "-bf", "2"],
            "av1":  ["-g", gop, "-profile:v", "main"],
        }[codec]

    # --- torch / labels -----------------------------------------------------
    def torch_env_setup(self):
        # gfx1101 = RX 7800 XT; overridable for other RDNA3 cards. Must be set
        # before torch imports. No-op cost on the wrong card is harmless.
        gfx = os.environ.get("OWL_HSA_GFX_VERSION", "11.0.0")
        os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", gfx)

    def device_label(self) -> str:
        return f"{self.name}, ROCm"

    def stamp(self) -> dict:
        return {"vendor": self.vendor, "name": self.name, "encode": "vaapi"}


# --------------------------------------------------------------------------
# NVIDIA — NVENC encode + CUDA + nvidia-smi
# (best-effort first cut; validate once the RTX 5080 is installed)
# --------------------------------------------------------------------------
class NvidiaBackend:
    vendor = "nvidia"
    available = True

    def __init__(self, name: str = "NVIDIA discrete GPU"):
        self.name = name

    def read_gpu_sensors(self) -> dict:
        # nvidia-smi reports a single GPU temperature (no AMD-style junction)
        # and instantaneous board power draw. We map temp -> gpu_junction to
        # keep the result schema stable across vendors.
        out = _run(['nvidia-smi',
                    '--query-gpu=temperature.gpu,power.draw',
                    '--format=csv,noheader,nounits'])
        if not out:
            return {"gpu_junction": None, "gpu_ppt_w": None}
        try:
            temp_s, power_s = out.strip().splitlines()[0].split(',')
            return {"gpu_junction": float(temp_s.strip()),
                    "gpu_ppt_w": float(power_s.strip())}
        except Exception:
            return {"gpu_junction": None, "gpu_ppt_w": None}

    _ENCODER = {"h264": "h264_nvenc", "h265": "hevc_nvenc", "av1": "av1_nvenc"}

    def ffmpeg_hwaccel_args(self) -> list:
        return ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]

    def ffmpeg_scale_filter(self, height: int = 1080) -> str:
        return f"scale_cuda=-2:{height}"

    def ffmpeg_encoder(self, codec: str) -> str:
        return self._ENCODER[codec]

    def ffmpeg_gpu_norm_args(self, codec: str, gop: str) -> list:
        # NVENC: `-rc cbr` is the ABR-equivalent constant-bitrate mode, matching
        # the `-b:v` target used on the CPU/AMD side so the task stays apples-to-
        # apples. B-frames are supported in NVENC hardware (unlike AMD VAAPI).
        return {
            "h264": ["-g", gop, "-profile:v", "high", "-bf", "2", "-rc", "cbr"],
            "h265": ["-g", gop, "-profile:v", "main", "-bf", "2", "-rc", "cbr"],
            "av1":  ["-g", gop, "-rc", "cbr"],
        }[codec]

    def torch_env_setup(self):
        # CUDA needs no HSA override. Clear any stale AMD override that a prior
        # boot on the old card may have left in the environment.
        os.environ.pop("HSA_OVERRIDE_GFX_VERSION", None)

    def device_label(self) -> str:
        return f"{self.name}, CUDA"

    def stamp(self) -> dict:
        return {"vendor": self.vendor, "name": self.name, "encode": "nvenc"}


# --------------------------------------------------------------------------
# None — CPU-only box (no discrete GPU detected). GPU presets are disabled.
# --------------------------------------------------------------------------
class NoGpuBackend:
    vendor = "none"
    available = False
    name = "no discrete GPU"

    def read_gpu_sensors(self) -> dict:
        return {"gpu_junction": None, "gpu_ppt_w": None}

    def ffmpeg_hwaccel_args(self) -> list:
        return []

    def ffmpeg_scale_filter(self, height: int = 1080) -> str:
        return f"scale=-2:{height}"

    def ffmpeg_encoder(self, codec: str) -> str:
        raise RuntimeError("No discrete GPU detected — GPU encode unavailable.")

    def ffmpeg_gpu_norm_args(self, codec: str, gop: str) -> list:
        return ["-g", gop]

    def torch_env_setup(self):
        pass

    def device_label(self) -> str:
        return "CPU only"

    def stamp(self) -> dict:
        return {"vendor": self.vendor, "name": self.name, "encode": None}


# --------------------------------------------------------------------------
# Apple silicon (macOS) — VideoToolbox media engine + Metal/MPS (CR-085 autonomy
# Phase 2). Pipeline = software decode + CPU scale + media-engine encode: the
# exact command shape the SSH-driven M6 campaign measured (2026-10-05), so a
# standalone GoS2 is parity-checkable against it. Rate control = VBR (owner,
# 2026-10-05): VideoToolbox CBR pads with filler (−5 VMAF, 50 % slower).
# No AV1 encoder on the M6 media engine (decode only) → supports("av1") False.
# --------------------------------------------------------------------------
class AppleBackend:
    vendor = "apple"
    available = True

    def __init__(self, name: str = "Apple silicon GPU"):
        self.name = name

    _ENCODER = {"h264": "h264_videotoolbox", "h265": "hevc_videotoolbox"}

    def supports(self, codec: str) -> bool:
        return codec in self._ENCODER

    def read_gpu_sensors(self) -> dict:
        # powermetrics needs root (narrow wrapper owl-powermetrics) and costs
        # CPU on every call — sampling it at 1 Hz would load the machine being
        # measured. Off unless `apple_powermetrics` is enabled.
        try:
            import settings as _cfg
            if not _cfg.load().get("apple_powermetrics", False):
                return {"gpu_junction": None, "gpu_ppt_w": None}
        except Exception:
            return {"gpu_junction": None, "gpu_ppt_w": None}
        out = _run(["sudo", "-n", "/usr/local/sbin/owl-powermetrics", "1", "200"])
        return {"gpu_junction": None, "gpu_ppt_w": _apple_gpu_power_w(out)}

    def ffmpeg_hwaccel_args(self) -> list:
        return []

    def ffmpeg_scale_filter(self, height: int = 1080) -> str:
        return f"scale=-2:{height}"

    def ffmpeg_encoder(self, codec: str) -> str:
        if codec not in self._ENCODER:
            raise RuntimeError(f"{self.name}: no hardware {codec} encoder")
        return self._ENCODER[codec]

    def ffmpeg_gpu_norm_args(self, codec: str, gop: str) -> list:
        profile = {"h264": "high", "h265": "main"}[codec]
        extra = ["-tag:v", "hvc1"] if codec == "h265" else []
        return ["-g", gop, "-profile:v", profile, *extra, "-bf", "2",
                "-allow_sw", "0", "-prio_speed", "0"]

    def torch_env_setup(self):
        pass

    def device_label(self) -> str:
        return f"{self.name}, Metal"

    def stamp(self) -> dict:
        return {"vendor": self.vendor, "name": self.name, "encode": "videotoolbox"}


def _apple_gpu_power_w(plist_text) -> "float | None":
    """GPU power (W) from a powermetrics plist sample; None if absent."""
    if not plist_text:
        return None
    try:
        import plistlib
        d = plistlib.loads(plist_text.split("\x00")[0].encode())
        g = d.get("gpu") or {}
        mw = g.get("gpu_energy") if "gpu_energy" in g else (d.get("processor") or {}).get("gpu_power")
        return round(float(mw) / 1000, 2) if mw is not None else None
    except Exception:
        return None


def _detect_apple() -> "AppleBackend | None":
    import platform
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return None
    name = (_run(["sysctl", "-n", "machdep.cpu.brand_string"]) or "Apple silicon").strip()
    return AppleBackend(name=f"{name} GPU")


def supports(codec: str) -> bool:
    """Whether the resolved backend has a hardware encoder for `codec`."""
    f = getattr(BACKEND, "supports", None)
    return bool(BACKEND.available) and (f(codec) if f else True)


# --------------------------------------------------------------------------
# Detection — run once at import, cached in BACKEND.
# --------------------------------------------------------------------------
def _detect_nvidia() -> "NvidiaBackend | None":
    out = _run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'])
    if out and out.strip():
        return NvidiaBackend(name=out.strip().splitlines()[0].strip())
    return None


def _detect_amd() -> "AmdBackend | None":
    out = _run(['sensors', '-j'])
    if not out:
        return None
    try:
        data = json.loads(out)
    except Exception:
        return None
    if AmdBackend._amdgpu_chip(data) is None:
        return None
    # Try to name the card via lspci; fall back to a generic label.
    name = "AMD discrete GPU"
    lspci = _run(['bash', '-c',
                  "lspci | grep -iE 'VGA|Display|3D' | grep -i 'AMD\\|ATI'"])
    if lspci:
        # e.g. "...: Advanced Micro Devices, Inc. [AMD/ATI] Navi 32 [Radeon RX 7800 XT] (rev c8)"
        line = lspci.strip().splitlines()[0]
        if '[' in line and ']' in line:
            name = line[line.rfind('[') + 1:line.rfind(']')] or name
    return AmdBackend(name=name)


def detect() -> object:
    """Resolve the GPU backend. Honours OWL_GPU_VENDOR override, else probes
    NVIDIA (nvidia-smi) then AMD (sensors amdgpu) then falls back to none."""
    forced = (os.environ.get("OWL_GPU_VENDOR") or "").strip().lower()
    if forced == "amd":
        return _detect_amd() or AmdBackend()
    if forced == "nvidia":
        return _detect_nvidia() or NvidiaBackend()
    if forced == "none":
        return NoGpuBackend()
    if forced == "apple":
        return _detect_apple() or AppleBackend()
    return _detect_apple() or _detect_nvidia() or _detect_amd() or NoGpuBackend()


BACKEND = detect()


# Convenience module-level shims (keep call sites terse) -------------------
def read_gpu_sensors() -> dict:
    return BACKEND.read_gpu_sensors()


def stamp() -> dict:
    return BACKEND.stamp()
