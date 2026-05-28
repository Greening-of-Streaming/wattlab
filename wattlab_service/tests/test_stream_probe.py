"""
Unit tests for CR-029 §3 — ffprobe-on-output stream provenance.

What's covered:
  - `_probe_gop`: GOP avg/max + keyframe/frame counts from packet `K` flags;
    <2 keyframes degrades gracefully; subprocess failure fails soft to blanks.
  - `probe_output_stream`: missing file / subprocess-raises / empty-stream all
    fail soft to None; happy path parses stream json and merges GOP; bit_rate
    "N/A" → None; level 0 → None (ffprobe's "unset" sentinel).
"""
import json
import types

import video


def _proc(stdout="", returncode=0):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


# ── _probe_gop ──────────────────────────────────────────────────────────────

def test_probe_gop_basic(monkeypatch):
    # K at frame 0, 4, 8 → gaps [4, 4]
    flags = "\n".join(["K__", "___", "___", "___",
                       "K__", "___", "___", "___", "K__"])
    monkeypatch.setattr(video.subprocess, "run", lambda cmd, **kw: _proc(flags))
    g = video._probe_gop("/tmp/x.mp4")
    assert g == {"gop_avg": 4.0, "gop_max": 4, "keyframe_count": 3, "frame_count": 9}


def test_probe_gop_uneven_gaps(monkeypatch):
    # K at 0, 2, 7 → gaps [2, 5] → avg 3.5, max 5
    flags = "\n".join(["K__", "___", "K__", "___", "___", "___", "___", "K__"])
    monkeypatch.setattr(video.subprocess, "run", lambda cmd, **kw: _proc(flags))
    g = video._probe_gop("/tmp/x.mp4")
    assert g["gop_avg"] == 3.5
    assert g["gop_max"] == 5
    assert g["keyframe_count"] == 3


def test_probe_gop_single_keyframe_is_soft(monkeypatch):
    flags = "\n".join(["K__", "___", "___"])
    monkeypatch.setattr(video.subprocess, "run", lambda cmd, **kw: _proc(flags))
    g = video._probe_gop("/tmp/x.mp4")
    assert g["gop_avg"] is None and g["gop_max"] is None
    assert g["keyframe_count"] == 1 and g["frame_count"] == 3


def test_probe_gop_nonzero_returncode_is_blank(monkeypatch):
    monkeypatch.setattr(video.subprocess, "run", lambda cmd, **kw: _proc("garbage", returncode=1))
    assert video._probe_gop("/tmp/x.mp4") == {
        "gop_avg": None, "gop_max": None, "keyframe_count": None, "frame_count": None}


def test_probe_gop_subprocess_raises_is_blank(monkeypatch):
    def boom(cmd, **kw):
        raise OSError("ffprobe vanished")
    monkeypatch.setattr(video.subprocess, "run", boom)
    assert video._probe_gop("/tmp/x.mp4")["gop_avg"] is None


# ── probe_output_stream ─────────────────────────────────────────────────────

_STREAM = {"streams": [{
    "codec_name": "h264", "profile": "High", "level": 42,
    "width": 1920, "height": 1080, "pix_fmt": "yuv420p",
    "bit_rate": "3731313", "has_b_frames": 2,
}]}


def _router(stream_json=_STREAM, packet_flags="K__\n___\n___\n___\nK__"):
    """Fake subprocess.run that branches on the -show_entries argument:
    stream-level json vs packet-flags csv."""
    def run(cmd, **kw):
        entries = cmd[cmd.index("-show_entries") + 1]
        if entries.startswith("stream="):
            return _proc(json.dumps(stream_json))
        return _proc(packet_flags)
    return run


def test_probe_output_stream_missing_file_none(tmp_path):
    assert video.probe_output_stream(tmp_path / "nope.mp4") is None


def test_probe_output_stream_subprocess_raises_none(tmp_path, monkeypatch):
    f = tmp_path / "o.mp4"; f.write_bytes(b"x")
    def boom(cmd, **kw):
        raise OSError("ffprobe vanished")
    monkeypatch.setattr(video.subprocess, "run", boom)
    assert video.probe_output_stream(f) is None


def test_probe_output_stream_empty_streams_none(tmp_path, monkeypatch):
    f = tmp_path / "o.mp4"; f.write_bytes(b"x")
    monkeypatch.setattr(video.subprocess, "run",
                        lambda cmd, **kw: _proc(json.dumps({"streams": []})))
    assert video.probe_output_stream(f) is None


def test_probe_output_stream_happy(tmp_path, monkeypatch):
    f = tmp_path / "o.mp4"; f.write_bytes(b"x")
    monkeypatch.setattr(video.subprocess, "run", _router())
    info = video.probe_output_stream(f)
    assert info["codec"] == "h264"
    assert info["profile"] == "High"
    assert info["level"] == 42
    assert info["width"] == 1920 and info["height"] == 1080
    assert info["pix_fmt"] == "yuv420p"
    assert info["bit_rate_bps"] == 3731313
    assert info["has_b_frames"] == 2
    # GOP merged in: K at 0, 4 → one gap of 4
    assert info["gop_avg"] == 4.0 and info["gop_max"] == 4
    assert info["keyframe_count"] == 2 and info["frame_count"] == 5


def test_probe_output_stream_bitrate_na_is_none(tmp_path, monkeypatch):
    s = {"streams": [{"codec_name": "av1", "profile": "Main", "level": 9,
                      "width": 1920, "height": 1080, "pix_fmt": "yuv420p",
                      "bit_rate": "N/A", "has_b_frames": 0}]}
    f = tmp_path / "o.mp4"; f.write_bytes(b"x")
    monkeypatch.setattr(video.subprocess, "run", _router(stream_json=s))
    info = video.probe_output_stream(f)
    assert info["bit_rate_bps"] is None
    assert info["codec"] == "av1"


def test_probe_output_stream_level_zero_is_none(tmp_path, monkeypatch):
    # ffprobe reports unset level as 0 (or -99); both must normalise to None.
    s = {"streams": [{"codec_name": "hevc", "profile": "Main", "level": 0,
                      "width": 1920, "height": 1080, "pix_fmt": "yuv420p",
                      "bit_rate": "1962905", "has_b_frames": 0}]}
    f = tmp_path / "o.mp4"; f.write_bytes(b"x")
    monkeypatch.setattr(video.subprocess, "run", _router(stream_json=s))
    info = video.probe_output_stream(f)
    assert info["level"] is None
    assert info["has_b_frames"] == 0
