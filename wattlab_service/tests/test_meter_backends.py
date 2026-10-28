"""CR-031 §2 (2026-10-28) — non-Tapo power sources for the container build.

Pins: Tapo stays the default and byte-identical; a synthetic/component source
routes the primary read, stamps itself (simulated / scope), reports a single
meter, and carries per-component series into energy.meters.components without
touching ΔW/confidence; a broken source fails reads loudly.
"""
import asyncio

import pytest

import meter_backends as mb
import power


class _FakeBackend:
    kind = "component"

    def __init__(self, seq):
        self.seq = list(seq)
        self.last_components = None

    def read(self):
        cpu, gpu = self.seq.pop(0)
        self.last_components = {"cpu": cpu, "gpu": gpu}
        return cpu + gpu

    def stamp(self):
        return {"name": "fake", "kind": self.kind, "resolution_s": 1.0, "scope": "test"}


@pytest.fixture
def backend(monkeypatch):
    def use(b, name="component"):
        monkeypatch.setattr(power, "BACKEND", b)
        monkeypatch.setattr(power, "POWER_SOURCE", name)
        return b
    return use


def test_tapo_is_default(monkeypatch):
    monkeypatch.setattr(power, "_config", {"TAPO_P110_IP": "1.2.3.4"})
    assert power._resolve_power_source() == ("tapo", None)


def test_unknown_source_kept_as_error_and_reads_fail(monkeypatch, backend):
    monkeypatch.setattr(power, "_config", {"OWL_POWER_SOURCE": "nope"})
    name, b = power._resolve_power_source()
    assert name == "nope" and isinstance(b, Exception)
    backend(b, "nope")
    with pytest.raises(RuntimeError, match="unavailable"):
        asyncio.run(power.get_power_watts())
    assert power.stamp()["kind"] == "unavailable"


def test_backend_routes_primary_read_and_stamp(backend):
    backend(_FakeBackend([(10.0, 5.0)]))
    assert asyncio.run(power.get_power_watts()) == 15.0
    assert power.meter_count() == 1
    assert power.stamp()["scope"] == "test"
    assert power.last_components() == {"cpu": 10.0, "gpu": 5.0}


def test_use_meters_override_bypasses_backend(backend):
    backend(_FakeBackend([]))
    with power.use_meters(["10.0.0.1", "10.0.0.2"]):
        assert power.meter_count() == 2
        assert power._backend() is None


def test_components_flow_into_meters_block(backend):
    b = backend(_FakeBackend([(10, 5), (10, 5), (30, 25), (30, 25)]))

    async def run():
        base = await power.sample_baseline(2, read_watts=power.get_power_watts, interval=0)
        stop = asyncio.Event()

        async def stopper():
            while len(b.seq) > 0:
                await asyncio.sleep(0)
            stop.set()
        asyncio.get_event_loop().create_task(stopper())
        readings = await power.sample_task(stop, read_watts=power.get_power_watts,
                                           tuples=True, interval=0)
        return base, readings

    base, readings = asyncio.run(run())
    assert base["w_base"] == 15.0
    meters = power.meters_summary(base, readings, [w for _, w in readings])
    by = meters["components"]["by_component"]
    assert by["cpu"]["delta_w"] == 20.0 and by["gpu"]["delta_w"] == 20.0
    assert "outer" not in meters and "delta_w_combined" not in meters


def test_tapo_run_meters_block_unchanged():
    assert power.meters_summary({"samples_w": [1.0]}, power.TaskReadings(), [2.0]) is None


def test_synthetic_backend_is_stamped_simulated():
    b = mb.SyntheticBackend()
    w = b.read()
    assert w > 0 and set(b.last_components) == {"cpu", "rest"}
    assert b.stamp()["simulated"] is True


def test_http_reader_json_and_prometheus(monkeypatch):
    monkeypatch.setenv("OWL_POWER_URL", "http://x/metrics")
    monkeypatch.setenv("OWL_POWER_FIELDS", "cpu=cpu.w,gpu=gpus.0.w")
    monkeypatch.setenv("OWL_POWER_SCALE", "0.001")
    r = mb.HttpReader()

    class Resp:
        def __init__(self, body): self.body = body.encode()
        def read(self): return self.body
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(mb.urllib.request, "urlopen",
                        lambda req, timeout: Resp('{"cpu": {"w": 42000}, "gpus": [{"w": 8000}]}'))
    assert r.read() == {"cpu": 42.0, "gpu": 8.0}

    monkeypatch.setenv("OWL_POWER_FIELDS", 'cpu=node_cpu_watts,gpu=gpu_watts{gpu="0"}')
    monkeypatch.setenv("OWL_POWER_SCALE", "1")
    r = mb.HttpReader()
    monkeypatch.setattr(mb.urllib.request, "urlopen", lambda req, timeout: Resp(
        '# HELP x\nnode_cpu_watts 41.5\ngpu_watts{gpu="0"} 7.25\n'))
    assert r.read() == {"cpu": 41.5, "gpu": 7.25}


def test_rapl_reader_handles_wraparound(tmp_path, monkeypatch):
    z = tmp_path / "intel-rapl:0"
    z.mkdir()
    (z / "name").write_text("package-0\n")
    (z / "max_energy_range_uj").write_text("1000000\n")
    (z / "energy_uj").write_text("900000\n")
    monkeypatch.setattr(mb.RaplReader, "ROOT", str(tmp_path))
    r = mb.RaplReader()
    (z / "energy_uj").write_text("100000\n")       # wrapped: +200000 uJ
    t0 = r._prev[0]
    monkeypatch.setattr(mb.time, "monotonic", lambda: t0 + 2.0)
    assert r.read() == {"cpu": pytest.approx(0.1)}


def test_rapl_reader_without_zones_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(mb.RaplReader, "ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="RAPL"):
        mb.RaplReader()
