"""
Tests for the "Prepare REM Files" feature (rem_prep.py + routes_rem.py).

Pattern mirrors test_capabilities / test_pixop: pure-function unit tests for the
bitrate-search math + concat assembly, a monkeypatched end-to-end of the VMAF
search (video.transcode / video.compute_vmaf scripted to a VMAF-vs-bitrate
curve), and TestClient checks for route gating + the un-gated share link.
"""
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import rem_prep
import settings
import video


# --------------------------------------------------------------------------
# Bitrate-search math (pure)
# --------------------------------------------------------------------------
def test_next_bitrate_secant_within_bracket():
    # below=(90 @ 4000), above=(94 @ 8000); target 92 → halfway-ish by VMAF.
    samples = [(4000, 90.0), (8000, 94.0)]
    nb = rem_prep._next_bitrate(samples, 92.0)
    assert 4000 < nb < 8000


def test_next_bitrate_bumps_up_when_all_below_target():
    samples = [(2000, 80.0), (4000, 88.0)]
    assert rem_prep._next_bitrate(samples, 92.0) > 4000


def test_next_bitrate_drops_when_all_above_target():
    samples = [(6000, 95.0), (8000, 97.0)]
    assert rem_prep._next_bitrate(samples, 92.0) < 6000


def test_accept_prefers_at_or_above_target_with_least_overshoot():
    samples = [(4000, 90.0), (6000, 92.4), (9000, 97.0)]
    bps, v = rem_prep._accept(samples, 92.0)
    assert bps == 6000 and v == 92.4


def test_accept_falls_back_to_closest_when_none_reach_target():
    samples = [(2000, 80.0), (4000, 89.0)]
    bps, v = rem_prep._accept(samples, 92.0)
    assert bps == 4000 and v == 89.0  # closest to target


def test_slope_from_bracket_is_positive():
    samples = [(4000, 90.0), (8000, 94.0)]
    s = rem_prep._slope(samples, 92.0)
    assert s is not None and s > 0


def test_clamp_and_round():
    assert rem_prep._round50(4123) == 4100
    assert rem_prep._clamp_bps(50) == rem_prep._BPS_FLOOR
    assert rem_prep._clamp_bps(999999) == rem_prep._BPS_CEIL


# --------------------------------------------------------------------------
# encode_to_vmaf — convergence with a scripted VMAF curve
# --------------------------------------------------------------------------
def _curve(bps: float) -> float:
    """Monotone diminishing-returns curve crossing 92 around ~4600 kbps."""
    return min(100.0, max(0.0, 80.0 + 10.0 * math.log2(bps / 2000.0)))


@pytest.fixture
def scripted_encoder(monkeypatch):
    """Fake video.transcode (parses -b:v, records call) + video.compute_vmaf
    (returns the curve at the last bitrate). Also pins the parity seed off."""
    holder = {"bps": None, "calls": 0}

    def fake_transcode(cmd, progress_cb=None):
        holder["calls"] += 1
        i = cmd.index("-b:v")
        holder["bps"] = int(cmd[i + 1].rstrip("k"))
        return {"success": True, "ffmpeg_cmd": " ".join(map(str, cmd))}

    def fake_vmaf(distorted, reference, s=None):
        return round(_curve(holder["bps"]), 2)

    monkeypatch.setattr(video, "transcode", fake_transcode)
    monkeypatch.setattr(video, "compute_vmaf", fake_vmaf)
    import budget_data
    monkeypatch.setattr(budget_data, "latest_artifact_path", lambda: None)
    return holder


@pytest.mark.asyncio
async def test_encode_to_vmaf_converges(scripted_encoder, tmp_path):
    out = await rem_prep.encode_to_vmaf(
        Path("excerpt.mp4"), tmp_path, "h264", "cpu", 1080,
        target=92.0, tol=0.5, max_iters=8, jobs=None, job_id="t1")
    assert out["converged"] is True
    assert abs(out["excerpt_vmaf"] - 92.0) <= 0.5
    assert out["slope"] and out["slope"] > 0
    assert out["bps"] > 0


@pytest.mark.asyncio
async def test_encode_to_vmaf_respects_max_iters(scripted_encoder, tmp_path):
    # tol=0 is unreachable on a 50-kbps-rounded grid → it must stop at max_iters.
    out = await rem_prep.encode_to_vmaf(
        Path("excerpt.mp4"), tmp_path, "h264", "cpu", 1080,
        target=92.0, tol=0.0, max_iters=3, jobs=None, job_id="t2")
    assert scripted_encoder["calls"] <= 3
    assert len(out["iterations"]) <= 3


@pytest.mark.asyncio
async def test_encode_to_vmaf_writes_progress_to_jobs(scripted_encoder, tmp_path):
    jobs = {"j": {}}
    await rem_prep.encode_to_vmaf(
        Path("excerpt.mp4"), tmp_path, "h264", "cpu", 1080,
        target=92.0, tol=0.5, max_iters=8, jobs=jobs, job_id="j")
    assert jobs["j"]["stage"] == "searching"
    assert jobs["j"]["iter_done"] >= 1
    assert isinstance(jobs["j"]["iterations"], list)


# --------------------------------------------------------------------------
# build_encode_cmd — pins 4:2:0 + audio; reuses the live fragments
# --------------------------------------------------------------------------
def test_build_encode_cmd_cpu_pins_pix_fmt_and_audio():
    cmd = rem_prep.build_encode_cmd("h264", "cpu", 720, 3000, "in.mp4", "out.mp4")
    assert "libx264" in cmd
    assert "-pix_fmt" in cmd and cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert "scale=-2:720" in cmd
    assert "3000k" in cmd
    # constant audio for concat compatibility
    assert "-ar" in cmd and "48000" in cmd and "-ac" in cmd


def test_build_encode_cmd_forces_width_when_given():
    cmd = rem_prep.build_encode_cmd("h264", "cpu", 1080, 3000, "in.mp4", "out.mp4",
                                    width=1920)
    assert "scale=1920:1080,setsar=1" in cmd


# --------------------------------------------------------------------------
# assemble_rem_file — concat order + filter fallback
# --------------------------------------------------------------------------
def test_assemble_copy_path_uses_segment_order(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, capture_output=True, text=True):
        # demuxer copy path: read the list file (arg after -i), record + create out.
        listfile = Path(cmd[cmd.index("-i") + 1])
        captured["list"] = listfile.read_text()
        Path(cmd[-1]).write_bytes(b"x")
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(rem_prep.subprocess, "run", fake_run)
    segs = [tmp_path / n for n in ("timer", "black", "white", "black2", "video", "tail")]
    out = tmp_path / "final.mp4"
    res = rem_prep.assemble_rem_file(segs, out, "h264", "cpu", 4000)
    assert res == {"method": "copy", "ok": True}
    lines = [l for l in captured["list"].splitlines() if l]
    assert lines[0].endswith("timer'") and lines[-1].endswith("tail'")
    assert len(lines) == 6


def test_assemble_falls_back_to_filter_on_copy_failure(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_run(cmd, capture_output=True, text=True):
        calls["n"] += 1
        is_copy = "concat" in cmd and "copy" in cmd
        if is_copy:
            return type("R", (), {"returncode": 1, "stderr": "boom"})()
        # filter re-encode path
        assert "-filter_complex" in cmd
        Path(cmd[-1]).write_bytes(b"x")
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(rem_prep.subprocess, "run", fake_run)
    segs = [tmp_path / "a", tmp_path / "b"]
    out = tmp_path / "final.mp4"
    res = rem_prep.assemble_rem_file(segs, out, "h264", "cpu", 4000)
    assert res["method"] == "filter" and res["ok"] is True
    assert calls["n"] == 2


# --------------------------------------------------------------------------
# Share-token registry — un-gated link resolution
# --------------------------------------------------------------------------
def test_share_token_register_and_resolve(monkeypatch, tmp_path):
    monkeypatch.setattr(rem_prep.cfg, "load",
                        lambda: {**settings.DEFAULTS, "rem_output_dir": str(tmp_path)})
    out_dir, _, _ = rem_prep.rem_dirs()
    (out_dir / "rem_abc_h264_1080p.mp4").write_bytes(b"video")
    token = rem_prep.register_share_token(out_dir, "rem_abc_h264_1080p.mp4")
    assert len(token) >= 16
    resolved = rem_prep.resolve_share_token(token)
    assert resolved is not None and resolved.name == "rem_abc_h264_1080p.mp4"
    assert rem_prep.resolve_share_token("deadbeef" * 4) is None


def test_share_token_rejects_traversal(monkeypatch, tmp_path):
    monkeypatch.setattr(rem_prep.cfg, "load",
                        lambda: {**settings.DEFAULTS, "rem_output_dir": str(tmp_path)})
    out_dir, _, _ = rem_prep.rem_dirs()
    # An index entry with a non-basename value must not resolve.
    (out_dir / "share_tokens.json").write_text('{"feedface": "../secret.mp4"}')
    assert rem_prep.resolve_share_token("feedface") is None


# --------------------------------------------------------------------------
# Route gating (TestClient is loopback == Lab; public IP == Anonymous)
# --------------------------------------------------------------------------
import main  # noqa: E402

client = TestClient(main.app)
_LAB = {"x-real-ip": "127.0.0.1"}
_ANON = {"x-real-ip": "8.8.8.8", "accept": "text/html"}
_ANON_FETCH = {"x-real-ip": "8.8.8.8", "accept": "*/*"}


def test_page_renders_for_lab():
    r = client.get("/prepare-rem", headers=_LAB)
    assert r.status_code == 200
    assert "Prepare REM Files" in r.text
    # Lab → controls enabled, no read-only banner.
    assert "Read-only preview" not in r.text
    assert "Generate REM file" in r.text


def test_page_readonly_for_member(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "member_email_from_request",
                        lambda req: "simon@example.org")
    r = client.get("/prepare-rem", headers=_ANON)
    assert r.status_code == 200
    assert "Read-only preview" in r.text
    # The run button is disabled for non-Lab.
    assert 'id="runBtn"' in r.text
    assert "disabled>Generate REM file" in r.text


def test_page_403_for_anonymous():
    r = client.get("/prepare-rem", headers=_ANON)
    assert r.status_code == 403


def test_run_denied_for_anonymous():
    r = client.post("/prepare-rem/run", headers=_ANON_FETCH,
                    data={"source_key": "meridian_120s", "codec": "h264"})
    assert r.status_code == 403


def test_run_rejects_bad_codec_for_lab():
    r = client.post("/prepare-rem/run", headers=_LAB,
                    data={"source_key": "meridian_120s", "codec": "vp9"})
    assert r.status_code == 400


def test_share_link_is_public(monkeypatch, tmp_path):
    monkeypatch.setattr(rem_prep.cfg, "load",
                        lambda: {**settings.DEFAULTS, "rem_output_dir": str(tmp_path)})
    out_dir, _, _ = rem_prep.rem_dirs()
    (out_dir / "rem_xyz_h264_1080p.mp4").write_bytes(b"video-bytes")
    token = rem_prep.register_share_token(out_dir, "rem_xyz_h264_1080p.mp4")
    # Anonymous (public IP) can fetch the share link — it is intentionally un-gated.
    r = client.get(f"/rem-file/{token}", headers=_ANON_FETCH)
    assert r.status_code == 200
    assert r.content == b"video-bytes"


def test_share_link_bad_token_404():
    r = client.get("/rem-file/notavalidtoken", headers=_ANON_FETCH)
    assert r.status_code == 404
