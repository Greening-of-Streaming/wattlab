"""
GPU UI factorisation guard.

The encoder names and GPU labels shown in the live UI (video preset cards,
/settings bitrate labels, /demo + /methodology prose) must track gpu.BACKEND,
not a hardcoded vendor. This pins that contract: flip the backend to AMD and
the pages must show VAAPI encoders; flip to NVIDIA and they must show NVENC —
with no code edit in between. That is what makes an AMD revert or a datacentre
GPU swap a reboot, not a patch.

Tests run as Lab tier (loopback TestClient), so every gated page renders.
"""
import pytest
from fastapi.testclient import TestClient

import gpu
import main

client = TestClient(main.app)

# Pages whose copy names GPU encoders / the card, with the helper that feeds them.
_ENCODER_PAGES = ["/video", "/settings", "/methodology"]


@pytest.fixture
def as_amd(monkeypatch):
    monkeypatch.setattr(gpu, "BACKEND", gpu.AmdBackend(name="RX 7800 XT"))


@pytest.fixture
def as_nvidia(monkeypatch):
    monkeypatch.setattr(gpu, "BACKEND", gpu.NvidiaBackend(name="RTX 5080"))


def test_pages_show_vaapi_encoders_on_amd(as_amd):
    for p in _ENCODER_PAGES:
        t = client.get(p).text
        assert "h264_vaapi" in t, p
        assert "hevc_vaapi" in t, p
        assert "av1_vaapi" in t, p
        # The opposite vendor must NOT appear in the dynamic copy.
        assert "h264_nvenc" not in t, f"{p} leaked NVENC while backend is AMD"


def test_pages_show_nvenc_encoders_on_nvidia(as_nvidia):
    for p in _ENCODER_PAGES:
        t = client.get(p).text
        assert "h264_nvenc" in t, p
        assert "hevc_nvenc" in t, p
        assert "av1_nvenc" in t, p
        assert "h264_vaapi" not in t, f"{p} leaked VAAPI while backend is NVIDIA"


def test_helpers_follow_backend(as_amd):
    # Direct unit check on the shared helpers used by the templates above.
    assert main._gpu_enc("h264") == "h264_vaapi"
    assert main._gpu_runtime() == "ROCm"


def test_gpu_enc_helper_is_no_gpu_safe(monkeypatch):
    """The UI-copy helper must not raise on a CPU-only host — it returns a
    placeholder instead. (Full CPU-only page rendering is a separate concern:
    the GPU *presets* themselves still assume a GPU via video._gpu_detail —
    out of scope for this UI-copy factorisation pass, and moot for a GPU swap,
    which always lands on *some* discrete card.)"""
    monkeypatch.setattr(gpu, "BACKEND", gpu.NoGpuBackend())
    assert main._gpu_enc("h264") == "GPU encode unavailable"
    assert main._gpu_runtime() == "CPU"


# CR-068: the AMD card was swapped for an RTX 5080 on 2026-05-29, but the
# /rag/compare and /llm/compare methodology blocks kept the retired GPU pinned
# next to the current CPU as a live spec line ("Ryzen 9 7900 + RX 7800 XT") —
# wrong hardware shown publicly for weeks, and outside _ENCODER_PAGES so the
# guards above never saw it. Backstop: no non-comment route line may pin the
# retired card ("7800") beside the current CPU ("7900") as current kit. A
# *historical* mention (routes_methodology's idle-delta note: "prior AMD 7800
# XT") is legitimate and, crucially, does not co-locate the current CPU.
def test_no_current_spec_line_names_retired_gpu():
    """No routes_*.py presents the retired AMD card as live hardware. Current
    card names must route through ui._gpu_display_name() so a swap stays a
    reboot, not a patch."""
    import pathlib
    routes = pathlib.Path(main.__file__).parent.glob("routes_*.py")
    offenders = []
    for path in routes:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            code = line.split("//", 1)[0].split("#", 1)[0]  # strip JS + Python comments
            if "7800" in code and "7900" in code:  # retired GPU beside current CPU
                offenders.append(f"{path.name}:{n}")
    assert not offenders, (
        "Retired GPU pinned as current hardware in route copy — use "
        "ui._gpu_display_name(): " + ", ".join(offenders))


def test_compare_pages_show_live_card_not_stale_literal(as_nvidia):
    """The two compare methodology blocks the audit flagged render the live
    card, never the retired AMD one."""
    for p in ["/rag/compare", "/llm/compare"]:
        t = client.get(p).text
        assert "RX 7800" not in t, f"{p} still shows the retired AMD card"
