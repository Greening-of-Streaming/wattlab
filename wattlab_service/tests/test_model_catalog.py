"""CR-050 / CR-052 — model_catalog dates table + helpers.

Light tests: pins the date enrichment shape and the params parser /
key normalisation, so adding new models or refactoring the catalog
doesn't silently break the date-line render on /llm and /rag.
"""
import model_catalog as mc


# --- date table -------------------------------------------------------------

def test_dates_for_known_model_returns_full_shape():
    d = mc._dates_for("phi4")
    assert d["released"] == "2024-12-12"
    assert d["training_cutoff"] == "2024-06"
    assert "Phi-4" in d["source"]

def test_dates_for_unknown_model_returns_uniform_unknown_shape():
    d = mc._dates_for("does-not-exist:9999")
    assert d == {"released": None, "training_cutoff": None, "source": None}

def test_dates_present_for_every_panel_model():
    """Every model in the static _MODEL_DATES table must have all three keys
    set (training_cutoff may be None, but released + source should not)."""
    for key, dates in mc._MODEL_DATES.items():
        assert dates.get("released"), f"{key} missing released"
        assert dates.get("source"),   f"{key} missing source"
        # training_cutoff is allowed to be None when not publicly stated.

def test_qwen_and_mistral_nemo_have_no_cutoff_claimed():
    """Don't accidentally start claiming a training cutoff we don't have."""
    assert mc._MODEL_DATES["qwen3:1.7b"]["training_cutoff"] is None
    assert mc._MODEL_DATES["qwen3:4b"]["training_cutoff"]   is None
    assert mc._MODEL_DATES["qwen3:8b"]["training_cutoff"]   is None
    assert mc._MODEL_DATES["mistral-nemo:12b"]["training_cutoff"] is None


# --- params parser + key normaliser -----------------------------------------

def test_params_from_name():
    assert mc._params_from_name("qwen3:1.7b")   == "1.7B"
    assert mc._params_from_name("qwen3:8b")     == "8B"
    assert mc._params_from_name("mistral-nemo:12b") == "12B"
    assert mc._params_from_name("phi4")         == "14B"   # special-cased
    assert mc._params_from_name("tinyllama")    == "1.1B"  # special-cased
    assert mc._params_from_name("gpt-oss:20b")  == "20B"
    assert mc._params_from_name("strange-thing") == "?"

def test_params_numeric_sort_key():
    assert mc.params_numeric("1.1B") == 1.1
    assert mc.params_numeric("12B")  == 12.0
    assert mc.params_numeric("?")    == float("inf")
    # Sorted catalog order ascends by params.
    assert mc.params_numeric("1.1B") < mc.params_numeric("12B")

def test_normalize_strips_latest_only():
    assert mc._normalize_key("phi4:latest")       == "phi4"
    assert mc._normalize_key("tinyllama:latest")  == "tinyllama"
    # Meaningful tags retained
    assert mc._normalize_key("qwen3:1.7b")        == "qwen3:1.7b"
    assert mc._normalize_key("gpt-oss:20b")       == "gpt-oss:20b"


# --- cuda_only backend gate (auto-disable on GPU swap) ----------------------

def test_flux_family_is_cuda_only_with_loader():
    """FLUX.1-schnell ships marked cuda_only + a custom NF4 loader so it never
    silently appears on a non-NVIDIA box or hits AutoPipeline."""
    flux = mc._IMAGE_FAMILIES["flux-schnell"]
    assert flux["cuda_only"] is True
    assert flux["loader"] == "flux_nf4"
    assert flux["cpu_ok"] is False

def test_backend_allows_blocks_cuda_only_off_nvidia(monkeypatch):
    cuda_model = {"cuda_only": True}
    plain_model = {}
    monkeypatch.setattr(mc, "active_gpu_vendor", lambda: "amd")
    assert mc.backend_allows(cuda_model) is False    # AMD can't run it
    assert mc.backend_allows(plain_model) is True     # normal model unaffected
    monkeypatch.setattr(mc, "active_gpu_vendor", lambda: "none")
    assert mc.backend_allows(cuda_model) is False     # no discrete GPU either
    monkeypatch.setattr(mc, "active_gpu_vendor", lambda: "nvidia")
    assert mc.backend_allows(cuda_model) is True      # NVIDIA unlocks it

def test_enabled_image_models_drops_cuda_only_on_amd(monkeypatch):
    """The runner-facing list auto-drops a cuda_only model on AMD (swap-back =
    auto-disable, no settings edit) but keeps it on NVIDIA."""
    catalog = {
        "sd-turbo":     {"label": "SD-Turbo"},
        "flux-schnell": {"label": "FLUX.1-schnell (NF4)", "cuda_only": True},
    }
    monkeypatch.setattr(mc, "available_image_models", lambda: dict(catalog))
    monkeypatch.setattr(mc.cfg, "load", lambda: {})   # empty enable list = all

    monkeypatch.setattr(mc, "active_gpu_vendor", lambda: "amd")
    assert set(mc.enabled_image_models()) == {"sd-turbo"}

    monkeypatch.setattr(mc, "active_gpu_vendor", lambda: "nvidia")
    assert set(mc.enabled_image_models()) == {"sd-turbo", "flux-schnell"}
