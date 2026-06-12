"""
Guided Tour copy guard.

The tour's claims must track what the demo buttons actually run and what
hardware is installed — this is the page strangers judge GoS's credibility
by. Pins three contracts introduced after the 2026-06 anonymous-landing
audit (the copy said "Mistral 7B via Ollama ROCm" months after the button
ran qwen3:4b on CUDA):

1. The LLM/RAG model named in the copy IS the model the run buttons submit
   (both bake from the same constants / curated.CANONICAL_RAG_MODEL).
2. GPU encoder + runtime wording follows gpu.BACKEND — flip the vendor and
   the tour follows, with no leaked opposite-vendor terms.
3. Every serve-time {TOKEN} placeholder is replaced at render.
"""
import re

import pytest
from fastapi.testclient import TestClient

import curated
import gpu
import llm as llm_mod
import main
import routes_demo

client = TestClient(main.app)


@pytest.fixture
def as_amd(monkeypatch):
    monkeypatch.setattr(gpu, "BACKEND", gpu.AmdBackend(name="RX 7800 XT"))


@pytest.fixture
def as_nvidia(monkeypatch):
    monkeypatch.setattr(gpu, "BACKEND", gpu.NvidiaBackend(name="RTX 5080"))


def test_no_unreplaced_tokens():
    t = client.get("/demo").text
    leftovers = set(re.findall(r"\{[A-Z][A-Z0-9_]{3,}\}", t))
    assert not leftovers, f"unreplaced serve-time tokens: {leftovers}"


def test_llm_copy_and_button_run_the_same_model():
    t = client.get("/demo").text
    # The JS submits exactly the configured model…
    assert f"form.append('model_key', '{routes_demo.DEMO_LLM_MODEL}')" in t
    # …and the prose names it by its registry label (if currently enabled).
    m = llm_mod.MODELS.get(routes_demo.DEMO_LLM_MODEL)
    if m:
        assert m["label"] in t
    # The historical drift must never come back as a hardcoded literal.
    assert "Mistral 7B" not in t


def test_rag_copy_follows_canonical_model():
    t = client.get("/demo").text
    assert f"form.append('model_key', '{curated.CANONICAL_RAG_MODEL}')" in t


def test_video_source_facts_come_from_registry():
    import sources
    t = client.get("/demo").text
    desc = (sources.PRELOADED.get(routes_demo.DEMO_VIDEO_SOURCE) or {}).get("description")
    assert desc and desc in t
    assert f"form.append('source_key', '{routes_demo.DEMO_VIDEO_SOURCE}')" in t


def test_gpu_wording_follows_backend_nvidia(as_nvidia):
    t = client.get("/demo").text
    assert "hevc_nvenc" in t
    assert "av1_nvenc" in t
    assert "(CUDA)" in t
    assert "ROCm" not in t, "tour leaked AMD runtime while backend is NVIDIA"
    assert "vaapi" not in t, "tour leaked VAAPI while backend is NVIDIA"


def test_gpu_wording_follows_backend_amd(as_amd):
    t = client.get("/demo").text
    assert "hevc_vaapi" in t
    assert "av1_vaapi" in t
    assert "(ROCm)" in t
    assert "nvenc" not in t, "tour leaked NVENC while backend is AMD"
    assert "CUDA" not in t, "tour leaked CUDA runtime while backend is AMD"
