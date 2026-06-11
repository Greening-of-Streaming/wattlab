"""
Power-meter provenance + display-name factorisation (cheap-wins pass, 2026-06-09).

Mirrors what gpu.stamp() / _gpu_display_name() do for the GPU: the meter that
produced a result is stamped on it (so a future PDU/IPMI swap — CR-031 §2 —
can't be silently compared against Tapo P110 runs), and the meter name shown in
the UI follows a `meter_display_name` setting override rather than a hardcoded
"Tapo P110". The full multi-backend abstraction (POWER_SOURCE / PduBackend /
resolution-aware confidence) is deliberately deferred to CR-031.
"""
import json

import pytest
from fastapi.testclient import TestClient

import power
import persist
import main


def test_stamp_shape_and_defaults(monkeypatch):
    # Single-meter: exact legacy shape, byte-identical to pre-CR-065.
    monkeypatch.setattr(power, "_meter_ips", lambda: ["10.0.0.1"])
    s = power.stamp()
    assert s == {"name": "Tapo P110", "kind": "smart_plug", "resolution_s": 1.0}


def test_stamp_dual_meter_extension(monkeypatch):
    # Dual-meter (CR-065): legacy keys preserved, configuration facts added —
    # never measured performance (fresh-sample rates live in the findings doc).
    monkeypatch.setattr(power, "_meter_ips", lambda: ["10.0.0.1", "10.0.0.2"])
    s = power.stamp()
    assert s["name"] == "Tapo P110"
    assert s["kind"] == "smart_plug"
    assert s["resolution_s"] == 1.0
    assert s["meters"] == 2
    assert s["topology"] == "daisy_chain"
    assert s["stagger_s"] == 0.5


def test_meter_display_name_honours_setting_override(monkeypatch):
    import settings
    monkeypatch.setattr(settings, "load", lambda: {"meter_display_name": "Rack PDU A3"})
    assert power.meter_display_name() == "Rack PDU A3"
    assert power.stamp()["name"] == "Rack PDU A3"


def test_meter_display_name_falls_back_when_unset(monkeypatch):
    import settings
    monkeypatch.setattr(settings, "load", lambda: {})
    assert power.meter_display_name() == power.METER_NAME


def test_save_result_stamps_power_hardware(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "RESULTS_DIR", tmp_path)
    path = persist.save_result("video", "job-meter-test",
                               {"energy": {"delta_e_wh": 0.5, "delta_t_s": 10}})
    payload = json.loads(path.read_text())
    assert "power_hardware" in payload
    assert payload["power_hardware"]["name"] == "Tapo P110"
    assert payload["power_hardware"]["resolution_s"] == 1.0
    # Stamped alongside gpu_hardware, not instead of it.
    assert "gpu_hardware" in payload


def test_ui_meter_name_follows_override(monkeypatch):
    """The /methodology Hardware Disclosure row must reflect the display-name
    override, proving the UI reads power.meter_display_name() not a literal."""
    import settings
    real = settings.load()  # genuine settings, captured before patching
    monkeypatch.setattr(settings, "load",
                        lambda: {**real, "meter_display_name": "Rack PDU A3"})
    client = TestClient(main.app)
    body = client.get("/methodology").text
    assert "Rack PDU A3" in body
    assert "Tapo P110, 1-second polling" not in body  # the literal model name is gone
