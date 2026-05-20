"""Tests for the pinned canonical video-encode reference (CR-037 keystone)."""
import canonical


def test_baseline_loads_and_has_required_fields():
    base = canonical.video_baseline()
    assert base is not None, "canonical/video_baseline.json must be present + valid"
    for key in ("delta_e_wh", "source_duration_s", "preset_label"):
        assert key in base
    assert base["delta_e_wh"] > 0
    assert base["preset_key"] == "h265_gpu"


def test_times_vs_video_basic_ratio():
    ref = canonical.video_baseline()["delta_e_wh"]
    out = canonical.times_vs_video(ref * 12)
    assert out is not None
    assert round(out["ratio"]) == 12
    assert "120 s 1080p" in out["text"]
    assert out["baseline_wh"] == ref


def test_times_vs_video_rejects_bad_input():
    for bad in (None, 0, -1, "x"):
        assert canonical.times_vs_video(bad) is None


def test_ratio_formatting_thresholds():
    assert canonical._fmt_ratio(0.5) == "0.50×"
    assert canonical._fmt_ratio(2.4) == "2.4×"
    assert canonical._fmt_ratio(12.3) == "12×"
    assert canonical._fmt_ratio(137) == "140×"


def test_wh_per_minute_matches_baseline():
    base = canonical.video_baseline()
    expected = base["delta_e_wh"] / (base["source_duration_s"] / 60.0)
    assert abs(canonical.video_baseline_wh_per_minute() - expected) < 1e-9


def test_enrich_result_adds_video_relative_to_nested_energy_blocks():
    ref = canonical.video_baseline()["delta_e_wh"]
    result = {
        "mode": "both",
        "cpu": {"energy": {"delta_e_wh": ref * 2}},
        "gpu": {"tasks": [{"energy": {"delta_e_wh": ref * 5}}]},
        "energy": {"delta_e_wh": ref},
    }
    canonical.enrich_result(result)
    assert round(result["cpu"]["energy"]["video_relative"]["ratio"]) == 2
    assert "video_relative" in result["gpu"]["tasks"][0]["energy"]
    assert "video_relative" in result["energy"]


def test_enrich_result_noop_without_delta_e_wh():
    result = {"energy": {"foo": 1}}
    canonical.enrich_result(result)
    assert "video_relative" not in result["energy"]
