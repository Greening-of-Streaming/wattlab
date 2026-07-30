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
        # settings-driven (decode_screen_startup_skip_s, default 5)
        assert cfg["startup_skip_s"] == 5
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


def test_protocol_settings_defaults_v3(monkeypatch):
    import settings as cfg
    monkeypatch.setattr(cfg, "load", lambda: {})
    p = decode_run.protocol_settings()
    assert p["cadence_s"] == 1.0
    assert p["idle_guard"] == {"tolerance_w": 0.5, "settle_polls": 4,
                               "max_wait_s": 60}
    assert p["protocol_version"] == 3


def test_protocol_settings_guard_off_is_v2(monkeypatch):
    import settings as cfg
    monkeypatch.setattr(cfg, "load", lambda: {"decode_idle_guard": False,
                                              "decode_cadence_s": 1.5})
    p = decode_run.protocol_settings()
    assert p["idle_guard"] is None
    assert p["protocol_version"] == 2
    assert p["cadence_s"] == 1.5


def test_materialize_injects_settings_protocol(monkeypatch):
    import settings as cfg
    monkeypatch.setattr(cfg, "load", lambda: {})
    p = decode_run._materialize("tj4", "bbb_h264_rt", "pi5", "headless", False)
    try:
        c = json.loads(p.read_text())
        assert c["cadence_s"] == 1.0
        assert c["protocol_version"] == 3
        assert c["idle_guard"]["settle_polls"] == 4
        # Reference-floor mode from the rig's known idle (2026-07-30 fix)
        assert c["idle_guard"]["reference_w"] == rig.RIG["devices"]["pi5"]["idle_w"]
    finally:
        p.unlink()


def test_segment_marker_trace_on_reference_run():
    """The actual screen trace from reference run 2026-07-30_14366b25."""
    trace = [17.5, 13.3, 32.4, 28.0, 28.1, 27.9, 28.0, 28.1,
             32.8, 33.1, 33.0, 33.0, 32.9,
             28.0, 28.0, 27.9, 28.0, 27.9,
             31.8, 32.6, 32.6, 32.4] + [30.9] * 60
    seg = decode_run.segment_marker_trace(trace)
    assert seg is not None
    assert 27.5 <= seg["black_w"] <= 28.5        # resync lows excluded
    assert 32.5 <= seg["white_w"] <= 33.5
    assert 27.5 <= seg["black2_w"] <= 28.5
    assert seg["marker_swing_w"] >= 4.0
    assert 30.0 <= seg["content_w"] <= 32.0


def test_segment_marker_trace_rejects_flat_and_short():
    assert decode_run.segment_marker_trace([30.0] * 40) is None
    assert decode_run.segment_marker_trace([1, 2, 3]) is None
    assert decode_run.segment_marker_trace(None) is None


def test_lem_csv_export_shape(monkeypatch):
    import persist

    def _fake_load(job_type, job_id, visitor_key=None):
        assert job_type == "decode"
        return {"devices": {"pi5": {"rows": [{
            "raw_baseline_t": [1000.0, 1001.0], "raw_baseline_w": [3.4, 3.5],
            "raw_task_t": [1002.0], "raw_task_w": [4.9],
            "raw_context_t": [1002.5], "raw_context_w": [30.5],
        }]}}}
    monkeypatch.setattr(persist, "load_result", _fake_load)
    r = client.get("/decode/result/testjob/lem.csv", headers=_LAB)
    assert r.status_code == 200
    lines = r.text.strip().split("\n")
    assert lines[0] == "timestamp,alias,power_w"
    assert len(lines) == 5
    assert ",pi5,3.4" in lines[1] and lines[1].startswith("1970-01-01T00:16:40")
    assert ",monitor,30.5" in lines[-1]


def test_lem_csv_404_without_timestamps(monkeypatch):
    import persist
    monkeypatch.setattr(persist, "load_result",
                        lambda *a, **k: {"devices": {"pi5": {"rows": [
                            {"raw_task_w": [1.0]}]}}})
    r = client.get("/decode/result/x/lem.csv", headers=_LAB)
    assert r.status_code == 404


def test_upload_rejects_bad_extension():
    r = client.post("/decode/upload", headers=_LAB,
                    files={"file": ("evil.exe", b"xx")})
    assert r.status_code == 400


def test_upload_lab_only():
    r = client.post("/decode/upload", headers=_ANON,
                    files={"file": ("a.mp4", b"xx")})
    assert r.status_code == 403


def test_upload_saves_with_retention(monkeypatch, tmp_path):
    import uploads

    def _fake_save(blob, orig, *, retention, feature, dest_dir):
        assert feature == "decode"
        assert retention == "keep"
        assert str(dest_dir).endswith("_uploads")
        return {"name": f"keep__decode__{orig}", "path": tmp_path / orig,
                "size_mb": 0.1, "retention": retention}
    monkeypatch.setattr(uploads, "save", _fake_save)
    r = client.post("/decode/upload", headers=_LAB,
                    files={"file": ("clip.mp4", b"data")},
                    data={"retention": "keep"})
    assert r.status_code == 200
    assert r.json()["name"] == "keep__decode__clip.mp4"


def test_run_upload_template_requires_existing_upload():
    r = client.post("/decode/run", headers=_LAB, json={
        "template": "upload", "upload_name": "nope.mp4",
        "devices": ["pi5"], "mode": "headless"})
    assert r.status_code == 400
    assert "upload a clip first" in r.json()["error"]


def test_cadence_override_validated_and_applied(monkeypatch):
    r = client.post("/decode/run", headers=_LAB, json={
        "template": "bbb_h264_rt", "devices": ["pi5"], "mode": "headless",
        "cadence_s": 22})
    assert r.status_code == 400
    import settings as cfg
    monkeypatch.setattr(cfg, "load", lambda: {})
    p = decode_run._materialize("tj8", "bbb_h264_rt", "pi5", "headless",
                                False, cadence_s=5)
    try:
        assert json.loads(p.read_text())["cadence_s"] == 5.0
    finally:
        p.unlink()


def test_template_device_restriction_enforced():
    r = client.post("/decode/run", headers=_LAB, json={
        "template": "bbb_h264_hw_rt", "devices": ["pi5", "pi400"],
        "mode": "headless"})
    assert r.status_code == 400
    assert "only runs on: Pi 400" in r.json()["error"]


def test_best_path_template_maps_decoder_per_device():
    p400 = decode_run._materialize("tj6", "bbb_h264_best_rt", "pi400",
                                   "headless", False)
    p5 = decode_run._materialize("tj7", "bbb_h264_best_rt", "pi5",
                                 "headless", False)
    try:
        c400 = json.loads(p400.read_text())
        c5 = json.loads(p5.read_text())
        assert "-c:v h264_v4l2m2m -i" in c400["runs"][0]["cmd"]   # HW
        assert "v4l2m2m" not in c5["runs"][0]["cmd"]              # SW
    finally:
        p400.unlink()
        p5.unlink()


def test_hw_decoder_template_names_v4l2m2m():
    p = decode_run._materialize("tj5", "bbb_h264_hw_rt", "pi400", "headless",
                                False)
    try:
        cfg = json.loads(p.read_text())
        assert "-c:v h264_v4l2m2m -i" in cfg["runs"][0]["cmd"]
    finally:
        p.unlink()


def test_marked_name_is_subdir_safe():
    assert decode_run.marked_name("bbb.mp4") == "marked_bbb.mp4"
    assert decode_run.marked_name("_uploads/x.mp4") == "_uploads/marked_x.mp4"


def test_page_has_mode_and_device_controls():
    page = client.get("/decode", headers=_LAB).text
    for frag in ("headless — parallel", "on screen — exclusive",
                 "dev-pi5", "dev-pi400", "dev-gtv", "calibrate"):
        assert frag in page, frag
    for key in decode_run.TEMPLATES:
        assert key in page
