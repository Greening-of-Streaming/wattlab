"""Decode run v2: templates × devices × modes, materialisation, route gating."""
import json

from fastapi.testclient import TestClient

import decode_run
import main
import rig

_LAB = {"x-real-ip": "127.0.0.1"}
_ANON = {"x-real-ip": "8.8.8.8"}
client = TestClient(main.app)


def test_templates_are_device_agnostic():
    for key, t in decode_run.TEMPLATES.items():
        assert t["clips"], key
        assert "device" not in t, key   # devices compose at run time


def test_materialize_headless_pi_uses_null_sink(tmp_path):
    p = decode_run._materialize("tj1", "bbb_h264_rt", "pi5", "headless", False)
    try:
        cfg = json.loads(p.read_text())
        assert cfg["meter_ip"] == rig.RIG["devices"]["pi5"]["plug_ip"]
        assert cfg["device"]["type"] == "ssh"
        assert "-f null" in cfg["runs"][0]["cmd"]
        assert "monitor_meter_ip" not in cfg
        assert "192.168.1.35" not in p.read_text()   # Lab-C guard
    finally:
        p.unlink()


def test_materialize_screen_pi_uses_marked_clip_and_monitor_context(tmp_path):
    p = decode_run._materialize("tj2", "bbb_h264_rt", "pi5", "screen", True)
    try:
        cfg = json.loads(p.read_text())
        assert cfg["monitor_meter_ip"] == rig.RIG["monitor"]["plug_ip"]
        assert len(cfg["runs"]) == 1                     # no bracket rows
        row = cfg["runs"][0]
        assert "marked_bbb_h264_6min.mp4" in row["cmd"]  # marker-headed clip
        assert "mpv --fs" in row["cmd"]
        # window extends over the 15 s head; skip shrinks so the head is sampled
        assert row["window_s"] == (decode_run.TEMPLATES["bbb_h264_rt"]["bench"]
                                   ["window_s"] + decode_run.MARKER_HEAD_S)
        assert cfg["startup_skip_s"] == 2
        assert cfg["cadence_s"] == 1.0
    finally:
        p.unlink()


def test_materialize_screen_without_calibrate_uses_plain_clip(tmp_path):
    p = decode_run._materialize("tj2b", "bbb_h264_rt", "pi5", "screen", False)
    try:
        cfg = json.loads(p.read_text())
        assert "marked_" not in cfg["runs"][0]["cmd"]
    finally:
        p.unlink()


def test_materialize_gtv_uses_urls():
    p = decode_run._materialize("tj3", "bbb_codecs_rt", "gtv", "headless", False)
    try:
        cfg = json.loads(p.read_text())
        assert cfg["device"]["type"] == "adb"
        assert all(r["url"].startswith(decode_run.STREAM_BASE_URL)
                   for r in cfg["runs"])
        assert len(cfg["runs"]) == 3
    finally:
        p.unlink()


def test_phase_patterns_match_bench_output():
    lines = {
        "[12:00:01] x: settle 15s": "settle",
        "[12:00:16] x: baseline 20 samples @1.5s": "baseline",
        "[12:00:46] x: started — sampling 90s": "sampling",
        "[12:02:20] x: base=1.02W task=1.90W dW=+0.88W (🟢) alive_at_end=True":
            "finishing",
    }
    for line, expected in lines.items():
        hit = None
        for pat, phase in decode_run._PHASE_PATTERNS:
            if pat.search(line):
                hit = phase
                break
        assert hit == expected, line


def test_run_endpoint_validations():
    assert client.post("/decode/run", headers=_LAB, json={
        "template": "nope", "devices": ["pi5"], "mode": "headless"
    }).status_code == 400
    assert client.post("/decode/run", headers=_LAB, json={
        "template": "bbb_h264_rt", "devices": [], "mode": "headless"
    }).status_code == 400
    assert client.post("/decode/run", headers=_LAB, json={
        "template": "bbb_h264_rt", "devices": ["toaster"], "mode": "headless"
    }).status_code == 400
    assert client.post("/decode/run", headers=_LAB, json={
        "template": "bbb_h264_rt", "devices": ["pi5"], "mode": "sideways"
    }).status_code == 400
    assert client.post("/decode/run", headers=_LAB, json={
        "template": "bbb_h264_rt", "devices": ["pi5", "gtv"], "mode": "screen"
    }).status_code == 400


def test_run_endpoint_lab_only():
    r = client.post("/decode/run", headers=_ANON, json={
        "template": "bbb_h264_rt", "devices": ["pi5"], "mode": "headless"})
    assert r.status_code == 403


def test_page_has_mode_and_device_controls():
    page = client.get("/decode", headers=_LAB).text
    for frag in ("headless — parallel", "on screen — exclusive",
                 "dev-pi5", "dev-pi400", "dev-gtv", "calibrate"):
        assert frag in page, frag
    for key in decode_run.TEMPLATES:
        assert key in page
