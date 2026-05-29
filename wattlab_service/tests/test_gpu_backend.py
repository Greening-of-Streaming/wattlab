"""
Unit tests for the GPU vendor abstraction (gpu.py, CR-060).

The point of gpu.py is that swapping the physical card (AMD ⇄ NVIDIA) needs
only a reboot — no code edits. These tests pin the contract each backend must
honour so a future card/driver change can't silently break encode commands,
sensor reads, or the result provenance stamp.
"""
import gpu


def _build(backend, codec, bps=1500):
    """Assemble a GPU encode command from a backend, the way video._gpu_cmd does."""
    return [
        "ffmpeg", "-y",
        *backend.ffmpeg_hwaccel_args(),
        "-i", "IN.mp4",
        "-vf", backend.ffmpeg_scale_filter(1080),
        "-c:v", backend.ffmpeg_encoder(codec), "-b:v", f"{bps}k",
        *backend.ffmpeg_gpu_norm_args(codec, "120"),
        "-c:a", "aac", "-b:a", "128k", "OUT.mp4",
    ]


# ── AMD backend reproduces the pre-refactor VAAPI commands exactly ───────────

def test_amd_commands_are_byte_identical_to_legacy_vaapi():
    b = gpu.AmdBackend(name="RX 7800 XT")
    expect = {
        "h264": ["ffmpeg", "-y", "-hwaccel", "vaapi", "-hwaccel_output_format", "vaapi",
                 "-extra_hw_frames", "32", "-vaapi_device", "/dev/dri/renderD128",
                 "-i", "IN.mp4", "-vf", "scale_vaapi=w=-2:h=1080:format=nv12",
                 "-c:v", "h264_vaapi", "-b:v", "1500k",
                 "-g", "120", "-profile:v", "high", "-bf", "2",
                 "-c:a", "aac", "-b:a", "128k", "OUT.mp4"],
        "h265": ["ffmpeg", "-y", "-hwaccel", "vaapi", "-hwaccel_output_format", "vaapi",
                 "-extra_hw_frames", "32", "-vaapi_device", "/dev/dri/renderD128",
                 "-i", "IN.mp4", "-vf", "scale_vaapi=w=-2:h=1080:format=nv12",
                 "-c:v", "hevc_vaapi", "-b:v", "1500k",
                 "-g", "120", "-profile:v", "main", "-bf", "2",
                 "-c:a", "aac", "-b:a", "128k", "OUT.mp4"],
        "av1":  ["ffmpeg", "-y", "-hwaccel", "vaapi", "-hwaccel_output_format", "vaapi",
                 "-extra_hw_frames", "32", "-vaapi_device", "/dev/dri/renderD128",
                 "-i", "IN.mp4", "-vf", "scale_vaapi=w=-2:h=1080:format=nv12",
                 "-c:v", "av1_vaapi", "-b:v", "1500k",
                 "-g", "120", "-profile:v", "main",
                 "-c:a", "aac", "-b:a", "128k", "OUT.mp4"],
    }
    for codec, want in expect.items():
        assert _build(b, codec) == want, codec


# ── NVIDIA backend produces valid NVENC commands ────────────────────────────

def test_nvidia_uses_nvenc_encoders_and_cuda_pipeline():
    b = gpu.NvidiaBackend(name="RTX 5080")
    assert b.ffmpeg_encoder("h264") == "h264_nvenc"
    assert b.ffmpeg_encoder("h265") == "hevc_nvenc"
    assert b.ffmpeg_encoder("av1") == "av1_nvenc"
    assert "cuda" in b.ffmpeg_scale_filter(1080)
    assert b.ffmpeg_hwaccel_args()[:2] == ["-hwaccel", "cuda"]


def test_nvidia_uses_cbr_rate_control_matching_abr_target():
    b = gpu.NvidiaBackend()
    for codec in ("h264", "h265", "av1"):
        args = b.ffmpeg_gpu_norm_args(codec, "120")
        assert args[:2] == ["-g", "120"]
        assert "cbr" in args, f"{codec} should use -rc cbr (ABR-equivalent)"


def test_nvidia_av1_omits_profile_av1_nvenc_has_no_profile_knob():
    # av1_nvenc exposes no -profile option; pinning one would error.
    assert "-profile:v" not in gpu.NvidiaBackend().ffmpeg_gpu_norm_args("av1", "120")
    # but h264/h265 nvenc do take a profile
    assert "-profile:v" in gpu.NvidiaBackend().ffmpeg_gpu_norm_args("h264", "120")


# ── cross-vendor invariants (apples-to-apples) ──────────────────────────────

def test_bframes_on_h264_h265_not_av1_both_vendors():
    for b in (gpu.AmdBackend(), gpu.NvidiaBackend()):
        assert "-bf" in b.ffmpeg_gpu_norm_args("h264", "120")
        assert "-bf" in b.ffmpeg_gpu_norm_args("h265", "120")
        assert "-bf" not in b.ffmpeg_gpu_norm_args("av1", "120")


def test_gop_pinned_on_every_codec_both_vendors():
    for b in (gpu.AmdBackend(), gpu.NvidiaBackend()):
        for codec in ("h264", "h265", "av1"):
            a = b.ffmpeg_gpu_norm_args(codec, "96")
            assert a[a.index("-g") + 1] == "96"


# ── detection + override ─────────────────────────────────────────────────────

def test_override_forces_vendor(monkeypatch):
    monkeypatch.setenv("OWL_GPU_VENDOR", "nvidia")
    assert gpu.detect().vendor == "nvidia"
    monkeypatch.setenv("OWL_GPU_VENDOR", "none")
    nb = gpu.detect()
    assert nb.vendor == "none" and nb.available is False


def test_no_gpu_backend_disables_gpu_encode():
    import pytest
    with pytest.raises(RuntimeError):
        gpu.NoGpuBackend().ffmpeg_encoder("h264")


# ── provenance stamp ─────────────────────────────────────────────────────────

def test_stamp_records_vendor_and_encode():
    assert gpu.AmdBackend(name="RX 7800 XT").stamp() == {
        "vendor": "amd", "name": "RX 7800 XT", "encode": "vaapi"}
    assert gpu.NvidiaBackend(name="RTX 5080").stamp() == {
        "vendor": "nvidia", "name": "RTX 5080", "encode": "nvenc"}


def test_amd_sets_hsa_override_nvidia_clears_it(monkeypatch):
    monkeypatch.setenv("HSA_OVERRIDE_GFX_VERSION", "stale")
    gpu.NvidiaBackend().torch_env_setup()
    import os
    assert "HSA_OVERRIDE_GFX_VERSION" not in os.environ
    monkeypatch.delenv("HSA_OVERRIDE_GFX_VERSION", raising=False)
    gpu.AmdBackend().torch_env_setup()
    assert os.environ.get("HSA_OVERRIDE_GFX_VERSION") == "11.0.0"
