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


# ── 2026-07-07 tour redesign: 9 steps, core path + optional AI detour ────────

def test_tour_has_budget_and_enhancement_steps():
    t = client.get("/demo").text
    assert "'Energy Budget'" in t and "'Video Enhancement'" in t  # stepLabels
    for n in range(9):
        assert f'id="step-{n}"' in t, f"step-{n} missing"


def test_step3_branches_core_vs_ai_detour():
    """Step 3 must offer BOTH exits: the core path to Confidence (primary)
    and the clearly-optional AI detour. The detour steps stay reachable."""
    t = client.get("/demo").text
    assert "Next: How we flag confidence" in t
    assert "Measure AI workloads too" in t
    assert "Optional detour" in t


def test_counter_is_honest_about_the_detour():
    """No '4/9 → 8/9' jump: core steps count 1-6, detour counts 1-3."""
    t = client.get("/demo").text
    assert "Step 1 of 6" in t          # initial counter markup
    assert "'Step 4 of 6'" in t        # STEP_META core entry (step 3)
    assert "AI detour · 1 of 3" in t   # STEP_META detour entry


def test_welcome_tour_map_present():
    t = client.get("/demo").text
    assert "This tour" in t and "optional detour: AI workloads" in t


def test_budget_teaser_from_live_fixture(monkeypatch):
    """The Energy-budget step's teaser table renders from
    routes_budget.current_fixture(); when no measured artifact exists the
    badge must say so instead of implying measurement."""
    import routes_budget
    t = client.get("/demo").text
    assert "Wh per minute of 1080p video" in t
    assert 'href="/video/budget"' in t
    # Force the illustrative path.
    fix = routes_budget._demo_fixture()
    monkeypatch.setattr(routes_budget, "current_fixture", lambda: fix)
    t2 = client.get("/demo").text
    assert "illustrative figures" in t2


def test_enhance_step_embeds_pinned_example_not_a_dead_link():
    """Anonymous visitors get the pinned showcase card + explicit member-only
    copy — never a bare link that 403s (the pre-redesign breakage)."""
    t = client.get("/demo").text
    assert "/demo/last/enhance" in t
    assert "wlRenderEnhanceCard" in t
    assert "member feature" in t
    # The only /enhance-run reference routes through sign-in (auth carries
    # the visitor to the page once they're a member).
    assert "/auth/sign-in?next=/enhance-run" in t
    assert 'href="/enhance-run"' not in t
