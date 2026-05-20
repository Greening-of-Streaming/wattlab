"""Tests for the CR-040 reproduce-this bundle generator."""
import io
import json
import zipfile
from pathlib import Path

import reproduce

# A real 'both' video result, committed as the canonical provenance fixture.
FIXTURE = (Path(__file__).resolve().parent.parent
           / "canonical" / "source_h265_gpu_meridian_120s.json")


def _result():
    return json.loads(FIXTURE.read_text())


def test_collect_encodes_finds_both_sides():
    out = []
    reproduce._collect_encodes(_result(), out)
    assert len(out) == 2
    labels = " ".join(e["label"] for e in out)
    assert "CPU" in labels and "GPU" in labels
    for e in out:
        assert e["ffmpeg_cmd"] and e["delta_e_wh"] > 0


def test_bounds_envelope():
    b = reproduce._bounds(1.0, 1.29, k=3)
    assert b["low"] < 1.0 < b["high"]
    assert abs(b["high"] - (1 + 3 * 0.0129)) < 1e-9
    assert reproduce._bounds(1.0, None) is None


def test_sanitize_cmd_is_runnable():
    out = []
    reproduce._collect_encodes(_result(), out)
    sc = reproduce._sanitize_cmd(out[0]["ffmpeg_cmd"], 1)
    assert "nice -n -5" not in sc
    assert '-i "$INPUT"' in sc
    assert "/tmp/wattlab_uploads" not in sc


def test_build_bundle_contents():
    blob = reproduce.build_bundle("video", "testjob", _result(), 1.29)
    assert blob is not None
    z = zipfile.ZipFile(io.BytesIO(blob))
    assert set(z.namelist()) == {"expected.json", "cmd.sh", "compare.py", "README.md"}
    exp = json.loads(z.read("expected.json"))
    assert exp["owl_result"] == "video/testjob"
    assert len(exp["runs"]) == 2
    assert all(r["bounds_delta_e_wh"]["k_sigma"] == 3 for r in exp["runs"])
    # compare.py must be valid, importable Python
    compile(z.read("compare.py").decode(), "compare.py", "exec")
    assert "CC BY 4.0" in z.read("README.md").decode()


def test_build_bundle_none_without_encode():
    assert reproduce.build_bundle("video", "x", {"mode": "nothing"}, 1.29) is None
