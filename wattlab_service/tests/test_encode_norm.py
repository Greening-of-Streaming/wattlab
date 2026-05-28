"""
Unit tests for CR-029 §2 — apples-to-apples encode-parameter normalization.

What's covered:
  - `_norm_args` pins an identical GOP on every preset, sourced from
    `encode_gop_frames`, and the GOP is operator-tunable (flows through).
  - profile is pinned explicit on all six; closed GOP + scene-cut off only on
    the CPU encoders (VAAPI is fixed-GOP natively); `-bf 2` requested on
    H.264/H.265 but never on AV1 (alt-ref, not B-frames).
  - the flags actually land in the assembled command (build_preset_cmd) and in
    the variance-calibration template, since those are the measured workload.
"""
import video


ALL = ["cpu", "gpu", "h265_cpu", "h265_gpu", "av1_cpu", "av1_gpu"]
CPU = ["cpu", "h265_cpu", "av1_cpu"]
BF_PRESETS = ["cpu", "gpu", "h265_cpu", "h265_gpu"]  # H.264 + H.265, both paths


def _gop(monkeypatch, n):
    monkeypatch.setattr(video.cfg, "load", lambda: {"encode_gop_frames": n})


# ── _norm_args ──────────────────────────────────────────────────────────────

def test_every_preset_pins_a_gop(monkeypatch):
    _gop(monkeypatch, 120)
    for k in ALL:
        a = video._norm_args(k)
        assert "-g" in a and a[a.index("-g") + 1] == "120"
        assert "-profile:v" in a


def test_gop_is_identical_across_all_presets(monkeypatch):
    _gop(monkeypatch, 96)
    gops = {video._norm_args(k)[video._norm_args(k).index("-g") + 1] for k in ALL}
    assert gops == {"96"}   # one value, every preset


def test_gop_is_operator_tunable(monkeypatch):
    _gop(monkeypatch, 48)
    assert video._norm_args("gpu")[video._norm_args("gpu").index("-g") + 1] == "48"


def test_gop_defaults_to_120_when_unset(monkeypatch):
    monkeypatch.setattr(video.cfg, "load", lambda: {})  # key absent
    assert video._norm_args("cpu")[video._norm_args("cpu").index("-g") + 1] == "120"


def test_bframes_requested_on_h264_h265_not_av1(monkeypatch):
    _gop(monkeypatch, 120)
    for k in BF_PRESETS:
        assert "-bf" in video._norm_args(k), f"{k} should request B-frames"
    for k in ("av1_cpu", "av1_gpu"):
        assert "-bf" not in video._norm_args(k), f"{k} (AV1) must not pass -bf"


def test_scenecut_disabled_on_cpu_only(monkeypatch):
    _gop(monkeypatch, 120)
    # CPU encoders need explicit scene-cut off for a deterministic GOP;
    # VAAPI is fixed-GOP natively and takes no such param.
    assert "scenecut=0:open_gop=0" in video._norm_args("cpu")
    assert "scenecut=0:open-gop=0" in video._norm_args("h265_cpu")
    assert "scd=0" in video._norm_args("av1_cpu")
    for k in ("gpu", "h265_gpu", "av1_gpu"):
        joined = " ".join(video._norm_args(k))
        assert "scenecut" not in joined and "scd=" not in joined


def test_profiles_pinned_expected(monkeypatch):
    _gop(monkeypatch, 120)
    prof = lambda k: video._norm_args(k)[video._norm_args(k).index("-profile:v") + 1]
    assert prof("cpu") == "high" and prof("gpu") == "high"
    assert prof("h265_cpu") == "main" and prof("h265_gpu") == "main"
    assert prof("av1_cpu") == "main" and prof("av1_gpu") == "main"


# ── flags reach the assembled command + variance template ───────────────────

def test_build_preset_cmd_carries_normalization(monkeypatch):
    _gop(monkeypatch, 120)
    for k in ALL:
        cmd = video.build_preset_cmd(k, "{input}", "{output}")
        assert "-g" in cmd and cmd[cmd.index("-g") + 1] == "120"
        assert "-profile:v" in cmd
        # GOP must sit after the codec/bitrate, before the output path
        assert cmd.index("-g") > cmd.index("-c:v")
        assert cmd.index("-g") < len(cmd) - 1


def test_variance_template_includes_gop(monkeypatch):
    _gop(monkeypatch, 120)
    tpl = video.variance_template("cpu", {"h264_bitrate_kbps": 4000})
    assert "-g 120" in tpl
    assert "scenecut=0:open_gop=0" in tpl
