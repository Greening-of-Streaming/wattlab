"""
Unit tests for the lm-sensors parsing in `power.py`.

What's covered:
  - `amdgpu_chip()` resolves the *discrete* GPU's chip key by the presence of
    a `junction` temperature (the integrated Radeon exposes only `edge`/`PPT`).
  - Regression: `amdgpu_chip` survives PCIe re-enumeration. Adding the S24 NVMe
    data disk renamed the GPU chip `amdgpu-pci-0300` → `amdgpu-pci-0400`, which
    silently broke the old hardcoded lookups (GPU temp/PPT showed "—"). The
    resolver must not care about the bus address.
  - `read_sensors_dict()` uses the resolver and degrades to all-None on garbage.
"""
import json

import power


def test_amdgpu_chip_picks_discrete_card_by_junction():
    data = {
        "k10temp-pci-00c3": {"Tctl": {"temp1_input": 56.5}},
        # integrated Radeon on the Ryzen — has PPT but no junction
        "amdgpu-pci-0e00": {"PPT": {"power1_average": 8.0}, "edge": {"temp1_input": 41.0}},
        # discrete RX 7800 XT — junction + fan + mem
        "amdgpu-pci-0400": {"PPT": {"power1_average": 18.0},
                            "junction": {"temp2_input": 38.0},
                            "fan1": {"fan1_input": 0}},
    }
    assert power.amdgpu_chip(data) == "amdgpu-pci-0400"


def test_amdgpu_chip_survives_pci_renumbering():
    # Same card, the old bus address — must still resolve. This is the bug the
    # S24 disk add introduced (chip moved 0300 → 0400).
    data = {"amdgpu-pci-0300": {"junction": {"temp2_input": 40.0},
                                "PPT": {"power1_average": 12.0}}}
    assert power.amdgpu_chip(data) == "amdgpu-pci-0300"


def test_amdgpu_chip_none_when_no_discrete_gpu():
    data = {"k10temp-pci-00c3": {"Tctl": {"temp1_input": 50.0}},
            "amdgpu-pci-0e00": {"PPT": {"power1_average": 7.0}}}
    assert power.amdgpu_chip(data) is None


def test_read_sensors_dict_composes_cpu_and_gpu_backend(monkeypatch):
    # Post-CR-060 the CPU temp still comes from lm-sensors in power.py, but the
    # GPU temp/power is delegated to the resolved GPU backend (gpu.py) so the
    # read is vendor-agnostic. Patch both halves and assert the composition.
    class _R:
        stdout = json.dumps({"k10temp-pci-00c3": {"Tctl": {"temp1_input": 56.5}}})

    monkeypatch.setattr(power.subprocess, "run", lambda *a, **k: _R())
    monkeypatch.setattr(power.gpu, "read_gpu_sensors",
                        lambda: {"gpu_junction": 38.0, "gpu_ppt_w": 18.0})
    assert power.read_sensors_dict() == {
        "cpu_tctl": 56.5, "gpu_junction": 38.0, "gpu_ppt_w": 18.0,
    }


def test_read_sensors_dict_safe_on_garbage(monkeypatch):
    class _R:
        stdout = "not json at all"

    monkeypatch.setattr(power.subprocess, "run", lambda *a, **k: _R())
    monkeypatch.setattr(power.gpu, "read_gpu_sensors",
                        lambda: {"gpu_junction": None, "gpu_ppt_w": None})
    assert power.read_sensors_dict() == {
        "cpu_tctl": None, "gpu_junction": None, "gpu_ppt_w": None,
    }
