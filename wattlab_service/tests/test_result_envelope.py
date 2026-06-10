"""
Phase 4 (2026-06 refactor) — result-envelope contract guards.

docs/result_envelope.md is the catalogue; persist._SUMMARISERS is the
dispatch. These tests pin the loud-fallback behaviour: an unregistered
mode must still summarise (listings never break) but must carry the
"unrecognised_mode" marker, and registered modes must not.
"""
from pathlib import Path

import persist

STATIC = Path(__file__).resolve().parents[1] / "static"


def test_unregistered_video_mode_is_loud():
    s = persist._summarise("video", {"job_id": "x", "mode": "hologram",
                                     "result": {"energy": {"delta_e_wh": 1.0}}})
    assert s["unrecognised_mode"] == "hologram"
    assert s["mode"] == "hologram"
    # still summarises through the single-run shape — listings don't break
    assert s["delta_e_wh"] == 1.0


def test_unregistered_llm_mode_is_loud():
    s = persist._summarise("llm", {"job_id": "x", "mode": "telepathy"})
    assert s["unrecognised_mode"] == "telepathy"


def test_registered_modes_carry_no_marker():
    cases = [
        ("video", {"mode": "single", "result": {}}),
        ("video", {"mode": "both"}),
        ("video", {"mode": "codecs_gpu", "analysis": {}, "codecs": {}}),
        ("llm",   {"mode": "single"}),
        ("llm",   {"mode": "compare_models", "models": []}),
        ("llm",   {"mode": "rag_compare_models", "models": []}),
        ("llm",   {"mode": "rag"}),
        ("image", {"mode": "cpu"}),
        ("image", {"mode": "compare_models"}),
    ]
    for job_type, data in cases:
        s = persist._summarise(job_type, data)
        assert "unrecognised_mode" not in s, (job_type, data["mode"])


def test_legacy_records_without_mode_use_family_default():
    # video legacy: absent mode → "?" → single path, no marker
    s = persist._summarise("video", {"result": {"energy": {}}})
    assert s["mode"] == "?" and "unrecognised_mode" not in s
    # llm legacy default
    s = persist._summarise("llm", {})
    assert s["mode"] == "single" and "unrecognised_mode" not in s
    # image legacy default (mode = device, "cpu")
    s = persist._summarise("image", {})
    assert s["mode"] == "cpu" and "unrecognised_mode" not in s


def test_every_writer_mode_is_registered():
    """Every mode string a runner writes must be in _SUMMARISERS — the
    envelope doc's 'register it in three places' rule, machine-checked
    for the persist leg."""
    expected = {
        "video": {"single", "both", "all_codecs", "codecs_cpu", "codecs_gpu"},
        "llm": {"single", "both", "batch", "all", "all_both",
                "compare_models", "rag", "rag_compare", "rag_compare_models"},
        "image": {"cpu", "gpu", "both", "compare_models"},
    }
    for family, modes in expected.items():
        missing = modes - set(persist._SUMMARISERS[family])
        assert not missing, f"{family}: unregistered modes {missing}"


def test_cooldown_summary_accepts_both_stamp_shapes():
    """wl-carbon.js must normalise the singular 'cooldown' dict stamp
    (measurement-module CPU-vs-GPU paths) to a one-item list — see
    docs/result_envelope.md 'Cooldown stamp-key variants'."""
    src = (STATIC / "wl-carbon.js").read_text()
    i = src.index("window.wlCooldownSummary")
    body = src[i:i + 600]
    assert "Array.isArray(cooldowns)" in body
