"""
Unit tests for quality.py — the single funnel for terminal-pass quality
metrics (FR VMAF/PSNR/SSIM + NR VQA), and the VMAF v1 upgrade lever.

What's covered:
  - model resolution: v0 → libvmaf built-in default (no model arg, id
    vmaf_v0.6.1); v1 → file model under vmaf_model_dir + honest fallback to
    v0 when the file is missing (provenance must NEVER mislabel a score);
    absolute-path passthrough; uhd variant maps to the 4K model families.
  - vmaf_model_id: what callers stamp into results as `vmaf_model`.
  - scoring binary: vmaf_ffmpeg_bin used when present, ffmpeg_bin fallback
    when unset/missing (the encode binary must never be bumped for scoring).
  - compute_psnr_ssim: parse + fail-soft.
  - delegation: video.compute_vmaf and pixop.probe_vqa_nr are thin wrappers
    over quality.* (the read_sensors pattern) — the refactor contract.
"""
import json
import types
from pathlib import Path

import quality
import pixop
import video


def _fake_proc(stderr=""):
    return types.SimpleNamespace(returncode=0, stdout="", stderr=stderr)


def _capture_run(captured, mean=90.0):
    def run(cmd, **kw):
        captured["cmd"] = cmd
        captured["lavfi"] = cmd[cmd.index("-lavfi") + 1]
        logp = captured["lavfi"].split("log_path=")[1]
        Path(logp).write_text(json.dumps({"pooled_metrics": {"vmaf": {"mean": mean}}}))
        return _fake_proc()
    return run


def _clips(tmp_path):
    d, r = tmp_path / "d.mp4", tmp_path / "r.mp4"
    d.write_bytes(b"x"); r.write_bytes(b"x")
    return d, r


# ── model resolution + provenance ───────────────────────────────────────────

def test_v0_uses_builtin_default_model(tmp_path, monkeypatch):
    d, r = _clips(tmp_path)
    monkeypatch.setattr(quality, "_probe_dims", lambda p: (1920, 1080))
    captured = {}
    monkeypatch.setattr(quality.subprocess, "run", _capture_run(captured))
    quality.compute_vmaf(d, r, {"vmaf_enabled": True, "vmaf_model": "v0"})
    assert "model=" not in captured["lavfi"]          # built-in vmaf_v0.6.1
    assert quality.vmaf_model_id({"vmaf_model": "v0"}) == "vmaf_v0.6.1"


def test_v1_uses_file_model_and_id(tmp_path, monkeypatch):
    d, r = _clips(tmp_path)
    mdir = tmp_path / "models"
    mdir.mkdir()
    (mdir / "vmaf_v1.0.16_3d0h.json").write_text("{}")
    s = {"vmaf_enabled": True, "vmaf_model": "v1", "vmaf_model_dir": str(mdir)}
    monkeypatch.setattr(quality, "_probe_dims", lambda p: (1920, 1080))
    captured = {}
    monkeypatch.setattr(quality.subprocess, "run", _capture_run(captured))
    quality.compute_vmaf(d, r, s)
    assert f"model=path={mdir}/vmaf_v1.0.16_3d0h.json" in captured["lavfi"]
    assert quality.vmaf_model_id(s) == "vmaf_v1.0.16_3d0h"


def test_v1_missing_file_falls_back_to_v0_honestly(tmp_path):
    # A missing v1 model must fall back to v0 AND report v0 provenance —
    # scoring keeps flowing, and the stamped id stays truthful.
    s = {"vmaf_model": "v1", "vmaf_model_dir": str(tmp_path / "nowhere")}
    assert quality.vmaf_model_id(s) == "vmaf_v0.6.1"


def test_absolute_path_model_passthrough(tmp_path):
    p = tmp_path / "custom_model.json"
    p.write_text("{}")
    s = {"vmaf_model": str(p)}
    assert quality.vmaf_model_id(s) == "custom_model"
    assert quality._resolve_model(s)[0] == f"path={p}"


def test_uhd_variant_maps_to_4k_models(tmp_path):
    mdir = tmp_path / "models"
    mdir.mkdir()
    (mdir / "vmaf_v1.0.16_1d5h_2160.json").write_text("{}")
    s1 = {"vmaf_model": "v1", "vmaf_model_dir": str(mdir)}
    assert quality.vmaf_model_id(s1, variant="uhd") == "vmaf_v1.0.16_1d5h_2160"
    s0 = {"vmaf_model": "v0"}
    assert quality.vmaf_model_id(s0, variant="uhd") == "vmaf_4k_v0.6.1"
    assert quality._resolve_model(s0, "uhd")[0] == "version=vmaf_4k_v0.6.1"


# ── scoring binary selection ────────────────────────────────────────────────

def test_scoring_bin_prefers_vmaf_ffmpeg_bin(tmp_path, monkeypatch):
    d, r = _clips(tmp_path)
    score_bin = tmp_path / "ffmpeg-score"
    score_bin.write_text("")
    s = {"vmaf_enabled": True, "vmaf_model": "v0",
         "vmaf_ffmpeg_bin": str(score_bin), "ffmpeg_bin": "/usr/bin/ffmpeg"}
    monkeypatch.setattr(quality, "_probe_dims", lambda p: (1920, 1080))
    captured = {}
    monkeypatch.setattr(quality.subprocess, "run", _capture_run(captured))
    quality.compute_vmaf(d, r, s)
    assert captured["cmd"][0] == str(score_bin)


def test_scoring_bin_falls_back_to_encode_bin(tmp_path, monkeypatch):
    d, r = _clips(tmp_path)
    s = {"vmaf_enabled": True, "vmaf_model": "v0",
         "vmaf_ffmpeg_bin": str(tmp_path / "gone"), "ffmpeg_bin": "/usr/bin/ffmpeg"}
    monkeypatch.setattr(quality, "_probe_dims", lambda p: (1920, 1080))
    captured = {}
    monkeypatch.setattr(quality.subprocess, "run", _capture_run(captured))
    quality.compute_vmaf(d, r, s)
    assert captured["cmd"][0] == "/usr/bin/ffmpeg"


# ── compute_psnr_ssim ───────────────────────────────────────────────────────

def test_psnr_ssim_parse(tmp_path, monkeypatch):
    d, r = _clips(tmp_path)
    monkeypatch.setattr(quality, "_probe_dims", lambda p: (1920, 1080))
    def run(cmd, **kw):
        lavfi = cmd[cmd.index("-lavfi") + 1]
        if "psnr" in lavfi:
            return _fake_proc(stderr="[Parsed_psnr_0] PSNR y:39 average:38.5211 max:45")
        return _fake_proc(stderr="[Parsed_ssim_0] SSIM All:0.98822 (19.3)")
    monkeypatch.setattr(quality.subprocess, "run", run)
    out = quality.compute_psnr_ssim(d, r, {"ffmpeg_bin": "ffmpeg"})
    assert out == {"psnr_db": 38.52, "ssim": 0.9882}


def test_psnr_ssim_identical_clips_inf_psnr(tmp_path, monkeypatch):
    d, r = _clips(tmp_path)
    monkeypatch.setattr(quality, "_probe_dims", lambda p: (1920, 1080))
    def run(cmd, **kw):
        lavfi = cmd[cmd.index("-lavfi") + 1]
        if "psnr" in lavfi:
            return _fake_proc(stderr="PSNR average:inf")
        return _fake_proc(stderr="SSIM All:1.000000")
    monkeypatch.setattr(quality.subprocess, "run", run)
    out = quality.compute_psnr_ssim(d, r, {"ffmpeg_bin": "ffmpeg"})
    assert out["psnr_db"] is None
    assert out["ssim"] == 1.0


def test_psnr_ssim_fail_soft(tmp_path, monkeypatch):
    d, r = _clips(tmp_path)
    monkeypatch.setattr(quality, "_probe_dims", lambda p: (1920, 1080))
    def boom(cmd, **kw):
        raise OSError("gone")
    monkeypatch.setattr(quality.subprocess, "run", boom)
    assert quality.compute_psnr_ssim(d, r, {"ffmpeg_bin": "ffmpeg"}) == {}


# ── delegation contract (the single-funnel guarantee) ───────────────────────

def test_video_compute_vmaf_delegates_to_quality(tmp_path, monkeypatch):
    seen = {}
    def fake(d, r, s=None, variant="hd"):
        seen["args"] = (d, r, s)
        return 91.0
    monkeypatch.setattr(quality, "compute_vmaf", fake)
    assert video.compute_vmaf("a.mp4", "b.mp4", {"x": 1}) == 91.0
    assert seen["args"] == ("a.mp4", "b.mp4", {"x": 1})


def test_pixop_probe_vqa_nr_delegates_to_quality(monkeypatch):
    seen = {}
    def fake(path, c=None):
        seen["args"] = (path, c)
        return {"score": 9.0}
    monkeypatch.setattr(quality, "probe_vqa_nr", fake)
    c = {"vqa_enabled": True}
    assert pixop.probe_vqa_nr("x.mp4", c) == {"score": 9.0}
    assert seen["args"] == ("x.mp4", c)


def test_no_stray_libvmaf_invocations_outside_quality():
    # The single-funnel guarantee itself: no service module other than
    # quality.py may build a libvmaf filtergraph or spawn the VQA scorer.
    svc = Path(quality.__file__).parent
    offenders = []
    for py in svc.glob("*.py"):
        if py.name == "quality.py":
            continue
        text = py.read_text()
        if "libvmaf=" in text or "VQA_NR.py" in text:
            offenders.append(py.name)
    assert offenders == [], f"quality metrics invoked outside quality.py: {offenders}"
