"""Stage-2 decode recipes: materialisation, phase parsing, route gating."""
import json

from fastapi.testclient import TestClient

import decode_run
import main
import rig

_LAB = {"x-real-ip": "127.0.0.1"}
_ANON = {"x-real-ip": "8.8.8.8"}
client = TestClient(main.app)


def test_recipes_reference_real_rig_devices():
    for key, r in decode_run.RECIPES.items():
        assert r["device"] in rig.RIG["devices"], key
        assert r["bench"]["runs"], key


def test_materialize_uses_live_rig_addresses(tmp_path, monkeypatch):
    p = decode_run._materialize("testjob1", "gtv_smoke")
    try:
        cfg = json.loads(p.read_text())
        assert cfg["meter_ip"] == rig.RIG["devices"]["gtv"]["plug_ip"]
        assert cfg["device"]["serial"] == rig.RIG["devices"]["gtv"]["target"]
        assert cfg["monitor_meter_ip"] == rig.RIG["monitor"]["plug_ip"]
        assert "192.168.1.35" not in p.read_text()   # Lab-C guard
    finally:
        p.unlink()


def test_materialize_ssh_device_splits_target():
    p = decode_run._materialize("testjob2", "pi5_h264_rt")
    try:
        cfg = json.loads(p.read_text())
        assert cfg["device"] == {"type": "ssh", "host": "192.168.1.102",
                                 "user": "admin"}
    finally:
        p.unlink()


def test_phase_patterns_match_bench_output():
    lines = {
        "[12:00:01] bbb_h264_smoke: settle 15s": "settle",
        "[12:00:16] bbb_h264_smoke: baseline 20 samples @1.5s": "baseline",
        "[12:00:46] bbb_h264_smoke: started — sampling 90s": "sampling",
        "[12:02:20] bbb_h264_smoke: base=1.02W task=1.90W dW=+0.88W (🟢) "
        "alive_at_end=True": "finishing",
    }
    for line, expected in lines.items():
        hit = None
        for pat, phase in decode_run._PHASE_PATTERNS:
            if pat.search(line):
                hit = phase
                break
        assert hit == expected, line


def test_recipe_phases_have_durations():
    for key, r in decode_run.RECIPES.items():
        phases = decode_run.recipe_phases(r)
        assert [p[0] for p in phases] == ["settle", "baseline", "starting",
                                          "sampling", "finishing"]
        assert all(p[1] > 0 for p in phases)


def test_run_endpoint_validates_recipe():
    r = client.post("/decode/run", headers=_LAB, json={"recipe": "nope"})
    assert r.status_code == 400


def test_run_endpoint_lab_only():
    r = client.post("/decode/run", headers=_ANON, json={"recipe": "gtv_smoke"})
    assert r.status_code == 403


def test_page_lists_recipes():
    page = client.get("/decode", headers=_LAB).text
    for key in decode_run.RECIPES:
        assert key in page
