"""CR-085 autonomy Phase 2 — macOS / Apple-silicon platform layer (runs on GoS1
with platform calls faked)."""
import gpu
import video


def test_apple_backend_encoders_and_av1():
    b = gpu.AppleBackend("Apple M6 GPU")
    assert b.ffmpeg_encoder("h264") == "h264_videotoolbox"
    assert b.ffmpeg_encoder("h265") == "hevc_videotoolbox"
    assert b.supports("h264") and not b.supports("av1")
    try:
        b.ffmpeg_encoder("av1")
        assert False, "AV1 must raise"
    except RuntimeError:
        pass


def test_apple_backend_matches_validated_vbr_args():
    """Same args as GoS2's validated hw_vbr registry engine (campaign 2026-10-05)."""
    b = gpu.AppleBackend()
    assert b.ffmpeg_gpu_norm_args("h264", "120") == \
        ["-g", "120", "-profile:v", "high", "-bf", "2", "-allow_sw", "0", "-prio_speed", "0"]
    assert "-tag:v" in b.ffmpeg_gpu_norm_args("h265", "120")
    assert b.ffmpeg_hwaccel_args() == [] and b.ffmpeg_scale_filter(1080) == "scale=-2:1080"


def test_detect_prefers_apple_on_darwin(monkeypatch):
    import platform
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(gpu, "_run", lambda cmd: "Apple M6\n" if cmd[0] == "sysctl" else None)
    b = gpu.detect()
    assert b.vendor == "apple" and b.name == "Apple M6 GPU"


def test_gpu_detail_and_label_safe_for_unsupported_codec(monkeypatch):
    import ui
    monkeypatch.setattr(gpu, "BACKEND", gpu.AppleBackend("Apple M6 GPU"))
    assert "unavailable" in video._gpu_detail("av1", 1500)
    assert "VBR" in video._gpu_detail("h264", 4000)
    assert ui._gpu_enc("av1") == "GPU encode unavailable"


def test_apple_sensors_off_by_default(monkeypatch):
    import settings
    monkeypatch.setattr(settings, "load", lambda: {"apple_powermetrics": False})
    assert gpu.AppleBackend().read_gpu_sensors() == {"gpu_junction": None, "gpu_ppt_w": None}


def test_focus_mode_kind(monkeypatch, tmp_path):
    import platform
    assert video.focus_mode_kind() == "systemd-timers"          # GoS1
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(video, "_MAC_FOCUS", str(tmp_path / "owl-focus"))
    assert video.focus_mode_kind() == "unavailable"
    assert video.focus_mode_enter() == []                        # nothing to pause, no error
    (tmp_path / "owl-focus").write_text("#!/bin/sh\n")
    assert video.focus_mode_kind() == "macos-owl-focus"


def test_torch_device_order():
    import image_gen
    class T:
        class cuda:
            @staticmethod
            def is_available(): return False
        class backends:
            class mps:
                @staticmethod
                def is_available(): return True
    assert image_gen.torch_device(T) == "mps"
