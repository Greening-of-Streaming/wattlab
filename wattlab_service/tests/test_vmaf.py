"""
Unit tests for CR-044 — VMAF perceptual-quality scoring on video comparisons.

What's covered:
  - `_parse_vmaf_log`: pooled-mean path, per-frame fallback, garbage -> None.
  - `compute_vmaf`: disabled / missing-file / subprocess-raises all fail soft
    to None; happy path returns the pooled mean; the lavfi *crops* the
    distorted to the probed dims (regression for the VAAPI 1080->1088 decode
    mismatch that tripped libvmaf with "input height must match"); the
    n_subsample knob is wired; stderr "VMAF score:" is the parse fallback.
  - `analyse`: quality_note reads both sides' VMAF — "equivalent" within JND,
    names the winner when divergent, None when VMAF is absent (e.g. the
    all-codecs per-pair analysis runs before the terminal VMAF pass).
  - Renderer smoke: the /video page ships the VMAF renderer.
"""
import json
import types
from pathlib import Path

import video


def _fake_proc(stderr=""):
    return types.SimpleNamespace(returncode=0, stdout="", stderr=stderr)


def _logwriting_run(mean):
    """A fake subprocess.run that writes a libvmaf json log at the path baked
    into the -lavfi arg and returns a clean process."""
    def run(cmd, **kw):
        lavfi = cmd[cmd.index("-lavfi") + 1]
        logp = lavfi.split("log_path=")[1]
        Path(logp).write_text(json.dumps({"pooled_metrics": {"vmaf": {"mean": mean}}}))
        return _fake_proc()
    return run


# ── _parse_vmaf_log ─────────────────────────────────────────────────────────

def test_parse_vmaf_log_pooled_mean(tmp_path):
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"pooled_metrics": {"vmaf": {"mean": 91.4811}}}))
    assert video._parse_vmaf_log(p) == 91.48


def test_parse_vmaf_log_frames_fallback(tmp_path):
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"frames": [
        {"metrics": {"vmaf": 90.0}}, {"metrics": {"vmaf": 92.0}}]}))
    assert video._parse_vmaf_log(p) == 91.0


def test_parse_vmaf_log_garbage_is_none(tmp_path):
    p = tmp_path / "v.json"
    p.write_text("not json at all")
    assert video._parse_vmaf_log(p) is None


# ── compute_vmaf fail-soft ──────────────────────────────────────────────────

def test_compute_vmaf_disabled_returns_none(tmp_path):
    d, r = tmp_path / "d.mp4", tmp_path / "r.mp4"
    d.write_bytes(b"x"); r.write_bytes(b"x")
    assert video.compute_vmaf(d, r, {"vmaf_enabled": False}) is None


def test_compute_vmaf_missing_distorted_returns_none(tmp_path):
    r = tmp_path / "r.mp4"; r.write_bytes(b"x")
    assert video.compute_vmaf(tmp_path / "nope.mp4", r, {"vmaf_enabled": True}) is None


def test_compute_vmaf_subprocess_raises_returns_none(tmp_path, monkeypatch):
    d, r = tmp_path / "d.mp4", tmp_path / "r.mp4"
    d.write_bytes(b"x"); r.write_bytes(b"x")
    monkeypatch.setattr(video, "_probe_dims", lambda p: (1920, 1080))
    def boom(cmd, **kw):
        raise OSError("ffmpeg vanished")
    monkeypatch.setattr(video.subprocess, "run", boom)
    assert video.compute_vmaf(d, r, {"vmaf_enabled": True}) is None


# ── compute_vmaf happy + behaviour ──────────────────────────────────────────

def test_compute_vmaf_happy_path(tmp_path, monkeypatch):
    d, r = tmp_path / "d.mp4", tmp_path / "r.mp4"
    d.write_bytes(b"x"); r.write_bytes(b"x")
    monkeypatch.setattr(video, "_probe_dims", lambda p: (1920, 1080))
    monkeypatch.setattr(video.subprocess, "run", _logwriting_run(91.31))
    score = video.compute_vmaf(d, r, {"vmaf_enabled": True, "vmaf_n_subsample": 1,
                                      "vmaf_n_threads": 4})
    assert score == 91.31


def test_compute_vmaf_crops_distorted_to_probed_dims(tmp_path, monkeypatch):
    # Regression: the distorted must be CROPPED (not just the reference scaled)
    # to the probed display dims, so the VAAPI 1080->1088 decode padding can't
    # trip libvmaf. Verified live 2026-05-22.
    d, r = tmp_path / "d.mp4", tmp_path / "r.mp4"
    d.write_bytes(b"x"); r.write_bytes(b"x")
    monkeypatch.setattr(video, "_probe_dims", lambda p: (1920, 1080))
    captured = {}
    def run(cmd, **kw):
        captured["lavfi"] = cmd[cmd.index("-lavfi") + 1]
        Path(captured["lavfi"].split("log_path=")[1]).write_text(
            json.dumps({"pooled_metrics": {"vmaf": {"mean": 90.0}}}))
        return _fake_proc()
    monkeypatch.setattr(video.subprocess, "run", run)
    video.compute_vmaf(d, r, {"vmaf_enabled": True})
    lavfi = captured["lavfi"]
    assert "crop=1920:1080:0:0" in lavfi
    assert "scale=1920:1080" in lavfi
    assert "libvmaf" in lavfi


def test_compute_vmaf_subsample_wired(tmp_path, monkeypatch):
    d, r = tmp_path / "d.mp4", tmp_path / "r.mp4"
    d.write_bytes(b"x"); r.write_bytes(b"x")
    monkeypatch.setattr(video, "_probe_dims", lambda p: (1920, 1080))
    captured = {}
    def run(cmd, **kw):
        captured["lavfi"] = cmd[cmd.index("-lavfi") + 1]
        Path(captured["lavfi"].split("log_path=")[1]).write_text(
            json.dumps({"pooled_metrics": {"vmaf": {"mean": 90.0}}}))
        return _fake_proc()
    monkeypatch.setattr(video.subprocess, "run", run)
    video.compute_vmaf(d, r, {"vmaf_enabled": True, "vmaf_n_subsample": 5})
    assert "n_subsample=5" in captured["lavfi"]


def test_compute_vmaf_no_subsample_when_one(tmp_path, monkeypatch):
    d, r = tmp_path / "d.mp4", tmp_path / "r.mp4"
    d.write_bytes(b"x"); r.write_bytes(b"x")
    monkeypatch.setattr(video, "_probe_dims", lambda p: (1920, 1080))
    captured = {}
    def run(cmd, **kw):
        captured["lavfi"] = cmd[cmd.index("-lavfi") + 1]
        Path(captured["lavfi"].split("log_path=")[1]).write_text(
            json.dumps({"pooled_metrics": {"vmaf": {"mean": 90.0}}}))
        return _fake_proc()
    monkeypatch.setattr(video.subprocess, "run", run)
    video.compute_vmaf(d, r, {"vmaf_enabled": True, "vmaf_n_subsample": 1})
    assert "n_subsample" not in captured["lavfi"]


def test_compute_vmaf_stderr_fallback(tmp_path, monkeypatch):
    # If the json log is unwritten/unparseable, fall back to ffmpeg's stderr.
    d, r = tmp_path / "d.mp4", tmp_path / "r.mp4"
    d.write_bytes(b"x"); r.write_bytes(b"x")
    monkeypatch.setattr(video, "_probe_dims", lambda p: (1920, 1080))
    monkeypatch.setattr(video.subprocess, "run",
                        lambda cmd, **kw: _fake_proc(stderr="[libvmaf] VMAF score: 88.50\n"))
    assert video.compute_vmaf(d, r, {"vmaf_enabled": True}) == 88.5


def test_compute_vmaf_cleans_up_temp_log(tmp_path, monkeypatch):
    d, r = tmp_path / "d.mp4", tmp_path / "r.mp4"
    d.write_bytes(b"x"); r.write_bytes(b"x")
    monkeypatch.setattr(video, "_probe_dims", lambda p: (1920, 1080))
    seen = {}
    def run(cmd, **kw):
        logp = cmd[cmd.index("-lavfi") + 1].split("log_path=")[1]
        seen["log"] = logp
        Path(logp).write_text(json.dumps({"pooled_metrics": {"vmaf": {"mean": 90.0}}}))
        return _fake_proc()
    monkeypatch.setattr(video.subprocess, "run", run)
    video.compute_vmaf(d, r, {"vmaf_enabled": True})
    assert not Path(seen["log"]).exists()  # temp log removed in finally


# ── analyse() quality note ──────────────────────────────────────────────────

def _side(delta_e, delta_t, vmaf=None, flag="🟢"):
    return {
        "preset_key": "cpu",
        "energy": {"delta_e_wh": delta_e, "delta_t_s": delta_t, "delta_w": 30.0,
                   "confidence": {"flag": flag}},
        "thermals": {"cpu_peak": 60.0, "gpu_peak": 50.0, "gpu_ppt_mean_w": 18.0},
        "vmaf": vmaf,
    }


def test_analyse_quality_note_equivalent_within_jnd():
    a = video.analyse(_side(1.58, 70, 91.48), _side(0.29, 14, 91.31))
    assert a["quality_note"] is not None
    assert "equivalent" in a["quality_note"].lower()


def test_analyse_quality_note_names_winner_when_divergent():
    a = video.analyse(_side(1.0, 70, 95.0), _side(0.5, 14, 80.0))
    assert "higher perceptual quality" in a["quality_note"]
    assert a["quality_note"].startswith("CPU")  # 95 > 80


def test_analyse_quality_note_absent_without_vmaf():
    a = video.analyse(_side(1.0, 70, None), _side(0.5, 14, None))
    assert a["quality_note"] is None


# ── renderer smoke ──────────────────────────────────────────────────────────

def test_video_page_ships_vmaf_renderer():
    from fastapi.testclient import TestClient
    import main
    resp = TestClient(main.app).get("/video")
    assert resp.status_code == 200
    assert "VMAF" in resp.text
