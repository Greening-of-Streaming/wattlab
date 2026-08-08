"""/decode route tests — gating, shapes, and the Lab-C guard."""
import json

import pytest
from fastapi.testclient import TestClient

import main
import rig

_LAB = {"x-real-ip": "127.0.0.1"}
_ANON = {"x-real-ip": "8.8.8.8"}

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _fresh_rig():
    for name in rig.RIG["devices"]:
        rig.rig_cache["devices"][name] = rig._blank_dev()
    rig._OP_LOCKS.clear()
    yield


def test_page_renders_for_lab():
    r = client.get("/decode", headers=_LAB)
    assert r.status_code == 200
    assert "Decode rig" in r.text
    assert "rig-tile" in r.text


def test_bench_schematic_scaffolding_present():
    t = client.get("/decode", headers=_LAB).text
    assert 'id="rig-wires"' in t          # SVG wire overlay
    assert 'id="rig-bench"' in t          # schematic grid
    assert 'id="rig-stripbar"' in t       # power strip bar
    assert "GoS1" in t                    # control rail node
    assert "SHAPES" in t and "SCREEN_SHAPE" in t   # silhouettes
    assert "drawWires" in t


def test_status_carries_bench_metadata():
    body = client.get("/decode/status.json", headers=_LAB).json()
    d = body["devices"]["pi5"]
    assert d["device_class"] == "sbc"
    assert "BCM2712" in d["silicon"]
    assert d["conn"] == "ssh"
    assert body["devices"]["gtv"]["device_class"] == "stb"
    assert body["devices"]["bbox"]["device_class"] == "stb"   # operator CPE
    assert "OLED55C2" in body["monitor"]["panel"]             # C2 display
    # The Lab-B slot is a physical either/or (firestick vs pi400 share the
    # plug); derive the expectation from the rig's park flags so a deliberate
    # bench swap doesn't need a test edit — but exactly one must be visible.
    parked = {k for k, v in rig.RIG["devices"].items() if v.get("parked")}
    visible = {"firestick", "pi400"} - parked
    assert len(visible) == 1, "exactly one Lab-B occupant on the bench"
    occupant = visible.pop()
    assert occupant in body["devices"]
    assert parked & {"firestick", "pi400"} == {"firestick", "pi400"} - {occupant}
    assert not any(p in body["devices"] for p in parked)
    if occupant == "firestick":
        fs = body["devices"]["firestick"]
        assert fs["device_class"] == "stb" and fs["conn"] == "adb"
        assert "AV1" in fs["silicon"]
    else:
        p4 = body["devices"]["pi400"]
        assert p4["device_class"] == "sbc" and p4["conn"] == "ssh"
        assert "hw H.264" in p4["silicon"]


def test_control_routes_are_lab_only_read_routes_public():
    # Read surfaces open (guided-tour material)…
    assert client.get("/decode", headers=_ANON).status_code == 200
    assert client.get("/decode/status.json", headers=_ANON).status_code == 200
    assert client.get("/decode/runs.json", headers=_ANON).status_code == 200
    # …every switch/run/upload stays Lab.
    assert client.post("/decode/device/pi5/power", headers=_ANON,
                       json={"action": "on"}).status_code == 403
    assert client.post("/decode/device/pi5/screen", headers=_ANON).status_code == 403
    assert client.post("/decode/monitor/power", headers=_ANON,
                       json={"on": True}).status_code == 403
    assert client.post("/decode/master/power", headers=_ANON,
                       json={"on": True}).status_code == 403


def test_anon_page_is_read_only():
    page = client.get("/decode", headers=_ANON).text
    assert "Read-only view" in page
    assert "var IS_LAB = false;" in page
    lab = client.get("/decode", headers=_LAB).text
    assert "Read-only view" not in lab
    assert "var IS_LAB = true;" in lab


def test_recent_runs_shape(monkeypatch, tmp_path):
    import persist
    d = tmp_path / "decode"
    d.mkdir()
    (d / "2026-07-30_abc123.json").write_text(json.dumps({
        "job_id": "abc123", "saved_at": "2026-07-30T02:00:00",
        "mode": "ui_screen", "template_label": "Smoke",
        "protocol": {"protocol_version": 3},
        "runs": [{"device": "pi400", "run": "x", "delta_w": 2.2,
                  "confidence": {"flag": "🟢"}}]}))
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    r = client.get("/decode/runs.json", headers=_ANON)
    assert r.status_code == 200
    runs = r.json()["runs"]
    assert runs[0]["job_id"] == "abc123"
    assert runs[0]["protocol_version"] == 3
    assert runs[0]["rows"][0]["delta_w"] == 2.2


def test_status_shape():
    r = client.get("/decode/status.json", headers=_LAB)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"master", "monitor", "devices", "screen_owner",
                         "screen_settling", "total_w", "saving_note", "age_s"}
    expected = {n for n, c in rig.RIG["devices"].items() if not c.get("parked")}
    assert set(body["devices"]) == expected


def test_unknown_action_400():
    r = client.post("/decode/device/pi5/power", headers=_LAB,
                    json={"action": "explode"})
    assert r.status_code == 400


def test_unknown_device_404():
    r = client.post("/decode/device/toaster/power", headers=_LAB,
                    json={"action": "on"})
    assert r.status_code == 404


def test_master_off_conflict_surfaces_409():
    # Relay-mode refusal path (no plug IO — refused before any hardware call).
    rig.rig_cache["master"]["switchable"] = True
    rig.rig_cache["devices"]["pi5"]["state"] = "ready"
    try:
        r = client.post("/decode/master/power", headers=_LAB, json={"on": False})
    finally:
        rig.rig_cache["master"]["switchable"] = False
    assert r.status_code == 409
    assert "Pi 5" in r.json()["error"]


def test_lab_c_router_ip_never_served():
    """The Lab-C plug powers the Bouygues router (see rig.py hazard note) —
    no /decode surface may ever mention it."""
    page = client.get("/decode", headers=_LAB).text
    status = json.dumps(client.get("/decode/status.json", headers=_LAB).json())
    assert "192.168.1.35" not in page
    assert "192.168.1.35" not in status
