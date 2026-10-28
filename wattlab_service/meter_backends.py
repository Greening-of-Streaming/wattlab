"""
meter_backends.py — non-Tapo power sources (CR-031 §2, 2026-10-28).

power.py owns the Tapo P110 path (GoS1/GoS2 wall plugs) and stays the ONE
place measurement code reads watts from. When `OWL_POWER_SOURCE` names a
backend here, power._read_meter_watts() routes its primary read to it
instead. Every backend implements the same small contract:

    read() -> float            total watts NOW (sync; power.py offloads it to a
                               thread). Raise on failure — never return a
                               guess, a cached value or a smoothed value.
    last_components            {component: watts} from the latest read(), or
                               None when the source has no breakdown.
    stamp() -> dict            provenance stamped on every result
                               (name, kind, resolution_s, scope, simulated?).

Backends:
  synthetic  — no hardware. Idle constant + a CPU-load term from /proc/stat +
               noise. For smoke-testing a deployment ONLY: results are stamped
               simulated and every page carries a "SIMULATED POWER" strip.
  component  — sums per-component readings (CPU package, DRAM, GPU, …) from
               one or more readers listed in OWL_COMPONENT_READERS:
                 rapl    Linux powercap energy counters (Intel + AMD Zen)
                 nvidia  nvidia-smi power.draw, summed over GPUs
                 http    any JSON or Prometheus endpoint (OWL_POWER_URL), with
                         OWL_POWER_FIELDS mapping component -> path/metric
               This is the reference adapter for provider telemetry (see
               container/README.md — "The meter contract").
"""
import json
import os
import random
import re
import subprocess
import time
import urllib.request


def _env(key: str, default: str = "") -> str:
    """.env value with the process environment winning (env.load contract)."""
    import env
    return (env.load().get(key) or os.environ.get(key) or default).strip()


# --- synthetic ----------------------------------------------------------------

class _CpuUtil:
    """Whole-machine CPU utilisation (0..1) between successive calls, from
    /proc/stat. Returns 0.0 where /proc/stat is unavailable (e.g. macOS)."""

    def __init__(self):
        self._prev = self._snap()

    @staticmethod
    def _snap():
        try:
            with open("/proc/stat") as f:
                vals = [int(x) for x in f.readline().split()[1:]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            return sum(vals), idle
        except Exception:
            return None

    def __call__(self) -> float:
        cur = self._snap()
        prev, self._prev = self._prev, cur
        if not cur or not prev or cur[0] == prev[0]:
            return 0.0
        busy = (cur[0] - prev[0]) - (cur[1] - prev[1])
        return max(0.0, min(1.0, busy / (cur[0] - prev[0])))


class SyntheticBackend:
    kind = "synthetic"

    def __init__(self):
        self.idle_w = float(_env("OWL_SYNTH_IDLE_W", "60"))
        self.cpu_w = float(_env("OWL_SYNTH_CPU_W", "120"))       # at 100 % CPU
        self.noise = float(_env("OWL_SYNTH_NOISE_PCT", "1.0")) / 100.0
        self._util = _CpuUtil()
        self.last_components = None

    def read(self) -> float:
        cpu = self.cpu_w * self._util()
        rest = self.idle_w * (1 + random.gauss(0, self.noise))
        self.last_components = {"cpu": round(cpu, 3), "rest": round(rest, 3)}
        return cpu + rest

    def stamp(self) -> dict:
        return {"name": "Synthetic (simulated)", "kind": self.kind,
                "resolution_s": 1.0, "simulated": True,
                "scope": "SIMULATED — not a measurement. Idle "
                         f"{self.idle_w:g} W + {self.cpu_w:g} W x CPU utilisation + noise."}


# --- component readers ----------------------------------------------------------

class RaplReader:
    """Linux powercap RAPL: average power between successive reads, from the
    cumulative energy_uj counters (wraparound handled). Top-level zones are
    `package-N`; their `dram` sub-zones are reported separately. Needs read
    access to /sys/class/powercap (root, or a udev rule / container mount)."""

    ROOT = "/sys/class/powercap"

    def __init__(self):
        self.zones = {}   # component -> (energy_path, max_range_uj)
        for d in sorted(os.listdir(self.ROOT)) if os.path.isdir(self.ROOT) else []:
            if not re.match(r"intel-rapl:\d+(:\d+)?$", d):
                continue
            base = os.path.join(self.ROOT, d)
            try:
                name = open(os.path.join(base, "name")).read().strip()
                rng = int(open(os.path.join(base, "max_energy_range_uj")).read())
                open(os.path.join(base, "energy_uj")).read()
            except Exception:
                continue
            if name.startswith("package"):
                comp = "cpu" if name == "package-0" else f"cpu{name.split('-')[-1]}"
            elif name == "dram":
                pkg = d.split(":")[1]
                comp = "dram" if pkg == "0" else f"dram{pkg}"
            else:
                continue   # core/uncore are inside the package figure
            self.zones[comp] = (os.path.join(base, "energy_uj"), rng)
        if not self.zones:
            raise RuntimeError("RAPL: no readable /sys/class/powercap/intel-rapl:* zones "
                               "(VM without RAPL passthrough, or permission denied)")
        self._prev = self._snap()

    def _snap(self):
        return time.monotonic(), {c: int(open(p).read()) for c, (p, _) in self.zones.items()}

    def read(self) -> dict:
        t0, e0 = self._prev
        t1, e1 = self._snap()
        self._prev = (t1, e1)
        dt = t1 - t0
        if dt <= 0:
            raise RuntimeError("RAPL: zero interval")
        out = {}
        for c, (_, rng) in self.zones.items():
            de = e1[c] - e0[c]
            if de < 0:
                de += rng
            out[c] = de / 1e6 / dt
        return out


class NvidiaReader:
    """GPU board power from nvidia-smi (instantaneous power.draw), one
    component per GPU (gpu, gpu1, …)."""

    def read(self) -> dict:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True).stdout
        vals = [float(x) for x in out.split() if x.strip()]
        if not vals:
            raise RuntimeError("nvidia-smi: no GPUs reported")
        return {("gpu" if i == 0 else f"gpu{i}"): v for i, v in enumerate(vals)}


def _dig(obj, path: str):
    """'gpu.0.power' -> obj['gpu'][0]['power']."""
    for part in path.split("."):
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return float(obj)


class HttpReader:
    """Generic provider endpoint. OWL_POWER_URL is fetched once per read;
    OWL_POWER_FIELDS maps components to values, comma-separated:
      JSON        cpu=cpu.power_w,dram=memory.power_w,gpu=gpus.0.watts
      Prometheus  cpu=node_cpu_power_watts,gpu=gpu_power_watts{gpu="0"}
    Format is auto-detected (JSON if the body parses, else Prometheus text).
    OWL_POWER_SCALE multiplies every value (e.g. 0.001 for a mW API).
    OWL_POWER_HEADERS adds request headers: 'Authorization=Bearer x;X-Y=z'."""

    def __init__(self):
        self.url = _env("OWL_POWER_URL")
        if not self.url:
            raise RuntimeError("http reader: set OWL_POWER_URL")
        self.fields = {}
        for item in _env("OWL_POWER_FIELDS").split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                self.fields[k.strip()] = v.strip()
        if not self.fields:
            raise RuntimeError("http reader: set OWL_POWER_FIELDS (component=path,...)")
        self.scale = float(_env("OWL_POWER_SCALE", "1"))
        self.headers = {}
        for h in filter(None, _env("OWL_POWER_HEADERS").split(";")):
            k, _, v = h.partition("=")
            self.headers[k.strip()] = v.strip()
        self.timeout = float(_env("OWL_POWER_TIMEOUT_S", "0.8"))

    def read(self) -> dict:
        req = urllib.request.Request(self.url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            body = r.read().decode()
        try:
            doc = json.loads(body)
            return {c: _dig(doc, p) * self.scale for c, p in self.fields.items()}
        except json.JSONDecodeError:
            pass
        out = {}
        for c, metric in self.fields.items():
            m = re.search(r"^" + re.escape(metric) + r"\s+([-+0-9.eE]+)", body, re.M)
            if not m:
                raise RuntimeError(f"http reader: metric {metric!r} not in response")
            out[c] = float(m.group(1)) * self.scale
        return out


_READERS = {"rapl": RaplReader, "nvidia": NvidiaReader, "http": HttpReader}


class ComponentBackend:
    kind = "component"

    def __init__(self):
        names = [n.strip() for n in _env("OWL_COMPONENT_READERS", "rapl").split(",") if n.strip()]
        unknown = [n for n in names if n not in _READERS]
        if unknown:
            raise RuntimeError(f"unknown OWL_COMPONENT_READERS: {unknown} (have {sorted(_READERS)})")
        self.reader_names = names
        self.readers = [_READERS[n]() for n in names]
        self.last_components = None

    def read(self) -> float:
        comps = {}
        for r in self.readers:
            comps.update(r.read())
        self.last_components = {k: round(v, 3) for k, v in comps.items()}
        return sum(comps.values())

    def stamp(self) -> dict:
        comps = sorted(self.last_components or {})
        return {"name": _env("OWL_METER_NAME") or "Component telemetry (" + "+".join(self.reader_names) + ")",
                "kind": self.kind, "resolution_s": 1.0,
                "components": comps,
                "scope": _env("OWL_METER_SCOPE") or (
                    "Component-level: sum of " + (", ".join(comps) or "reported components")
                    + ". PSU conversion losses, fans, NIC, storage and anything not "
                      "listed are excluded — not comparable to wall-plug figures.")}


BACKENDS = {"synthetic": SyntheticBackend, "component": ComponentBackend}


def create(name: str):
    """Instantiate a backend by name; raises with a readable reason."""
    if name not in BACKENDS:
        raise RuntimeError(f"unknown OWL_POWER_SOURCE {name!r} (have tapo, {', '.join(BACKENDS)})")
    return BACKENDS[name]()
