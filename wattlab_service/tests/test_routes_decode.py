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


def test_all_decode_routes_are_lab_only():
    assert client.get("/decode", headers=_ANON).status_code == 403
    assert client.get("/decode/status.json", headers=_ANON).status_code == 403
    assert client.post("/decode/device/pi5/power", headers=_ANON,
                       json={"action": "on"}).status_code == 403
    assert client.post("/decode/monitor/power", headers=_ANON,
                       json={"on": True}).status_code == 403
    assert client.post("/decode/master/power", headers=_ANON,
                       json={"on": True}).status_code == 403


def test_status_shape():
    r = client.get("/decode/status.json", headers=_LAB)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"master", "monitor", "devices", "screen_owner",
                         "total_w", "saving_note", "age_s"}
    assert set(body["devices"]) == set(rig.RIG["devices"])


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
