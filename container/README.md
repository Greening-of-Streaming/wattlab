# OWL in a container — measuring streaming & AI workloads on your hardware

**OWL (Online WattLab)** is the energy-measurement bench of
[Greening of Streaming](https://www.greeningofstreaming.org) (GoS). It runs a
workload (a video encode, an LLM inference, an image generation, a RAG query),
samples power at 1 Hz before and during it, and reports the energy the workload
added above idle with a statistical confidence flag.

On GoS's own bench, power comes from a Tapo P110 smart plug at the wall. This
folder packages OWL so it can run **on a server where power comes from somewhere
else**, for example per-component telemetry (CPU package, DRAM, GPU) exposed by
the platform. Plugging that source in is one small adapter, described in
[The meter contract](#the-meter-contract).

> **If you are an AI agent adapting OWL:** read this file top to bottom, then
> `wattlab_service/meter_backends.py` (≈250 lines) and `power.py` §"Shared
> measurement samplers". Your job is almost certainly **only** to make
> `OWL_POWER_SOURCE=component` read the platform's numbers, either by
> configuring the `http` reader or by adding one reader class. Do not touch
> `confidence.py`, the ΔE maths or the result format. [What not to change](#what-not-to-change)
> explains why.

---

## 1. Ground rules (GoS framing, which applies to anything published from OWL data)

- **Energy, not carbon.** OWL's claims are W and Wh. Any CO₂e figure is an
  indicative add-on, never GoS data.
- **State the scope.** Every result records what its meter covers. Component
  telemetry (CPU+DRAM+GPU) is *not* wall power: PSU losses, fans, NIC, storage
  and the rest of the board are missing. Don't compare it with wall-plug numbers
  without saying so.
- **n = 3 minimum** for anything that leaves the room, with the confidence
  interval and the operating point (codec, preset, bitrate, model, hardware)
  stated.
- **Simulated power is not data.** The `synthetic` source exists to smoke-test a
  deployment. Every page then shows a red *SIMULATED POWER* strip, and every
  result is stamped `power_hardware.simulated: true`. It models CPU load only,
  so GPU work (NVENC, CUDA) shows almost no ΔW under it. That is expected.

## 2. Quickstart

Requirements: Docker 24+ with Compose v2, about 15 GB of disk for the CPU image
plus content, and 16 GB RAM or more (LLMs). For GPUs, an NVIDIA driver and the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/).

```bash
git clone https://github.com/greeningofstreaming/wattlab.git && cd wattlab
cp container/owl.env.example container/owl.env      # then edit (node name, power source, tiers…)

export OWL_GIT_SHA=$(git rev-parse --short HEAD)   # stamps the code version on every result

# CPU-only host:
docker compose -f container/docker-compose.yml up -d --build
# NVIDIA host (NVENC encode, CUDA image gen, GPU LLM inference):
docker compose -f container/docker-compose.yml -f container/docker-compose.gpu.yml up -d --build

docker compose -f container/docker-compose.yml logs -f owl   # wait for "Uvicorn running"
```

OWL listens on **127.0.0.1:8000 of the host only**. From your laptop, tunnel in:

```bash
ssh -L 8000:localhost:8000 you@server     # then open http://localhost:8000
```

Through the tunnel you have the **Lab** tier: settings, batch runs and
calibration. To expose OWL to others, read [Access & security](#access--security)
first.

On first start the entrypoint:
1. Seeds `/data/settings.json` from `container/settings.container.json`. This
   switches off GoS-bench-only features: decode rig, field meters, Pixop and
   peer nodes.
2. Downloads the three open-licence test videos (`OWL_FETCH_CONTENT=1`, about
   1.3 GB). They are byte-identical to the files GoS encodes, checksum-verified,
   so your encodes and GoS's start from the same input.
3. Pulls the LLM tiers named in `OWL_LLM_TIERS`, but only those that fit
   ([LLM ladder](#llm-ladder)).

All state lives in the `owl-data` volume (`/data`): results, settings, test
content, HF cache. Models live in `ollama-models`.

### Updating

GoS publishes changes on `main`. Nothing updates by itself: pull and rebuild.

```bash
cd wattlab
git pull --ff-only
export OWL_GIT_SHA=$(git rev-parse --short HEAD)
docker compose -f container/docker-compose.yml up -d --build      # add -f container/docker-compose.gpu.yml on NVIDIA hosts
```

- **Kept across updates:** results, `settings.json` and test content (the
  `owl-data` volume), models (`ollama-models`), and `container/owl.env`
  (gitignored). `settings.json` is seeded only on the first start, so later
  changes to `settings.container.json` do not reach an existing install; new
  settings take their defaults from code.
- **Code version:** every result records `owl_version.sha`, the commit the image
  was built from. Without `OWL_GIT_SHA` it reads `unknown`, and results from
  before and after an update can no longer be told apart.
- **Local code changes** (for example a reader added to `meter_backends.py`)
  make `git pull --ff-only` stop on a conflict. Prefer sending the reader to GoS
  so it lands upstream; otherwise keep it on your own branch and merge.

## 3. How a measurement works (one page)

```
 queue ─► idle guard ─► unload models ─► BASELINE (N×1 s polls) ─► TASK (poll 1 s until done) ─► cooldown
                                            │                          │
                                            ▼                          ▼
                                     baseline_samples_w          task_samples_w
                                            └───────► ΔW = mean(task) − mean(baseline)
                                                      ΔE (Wh) = ΔW × duration / 3600
                                                      confidence = Φ(ΔW / SE)  → 🟢 🟡 🔴
                                                      → results/{type}/{date}_{job_id}.json
```

- One job at a time (single worker, lock file). A run never shares the box with
  another measured job.
- **Baseline**: `baseline_polls` polls (default 5) right before the task. The
  pre-job idle guard waits until power is back near the rolling idle floor.
- **Task**: polls every `METER_RESOLUTION_S = 1.0` s while the workload runs.
- **ΔW** is the *incremental* power of the workload above this machine's idle.
  It is not the machine's total draw.
- **Confidence** (`confidence.py`, GoS methodology §9): 🟢 when
  P(ΔW > 0) ≥ 0.95 with at least 10 task polls; 🟡 when ≥ 0.80 with at least 5;
  otherwise 🔴. It uses the raw samples, which is why they are persisted.
- **Cooldown** between runs waits for power to return to the idle floor, so one
  run's heat does not leak into the next run's baseline.

Workloads available in the container:

| Page | Workload | Engines |
|---|---|---|
| `/video` | Re-encode a test video; optional VMAF quality score | CPU: x264 / x265 / SVT-AV1 · NVIDIA: h264/hevc/av1_nvenc |
| `/llm` | Fixed prompts (T1–T3) on an Ollama model; mWh/token | Ollama (GPU if passed through, else CPU) |
| `/image` | Diffusers text-to-image (sd-turbo, SDXL-Turbo, …) | CUDA or CPU torch |
| `/rag` | Retrieval-augmented answer over a document corpus | Ollama + Chroma; add PDFs via `/rag` (Lab), then build the index |
| `/benchmark` | A fixed suite across all of the above | n repeats, summary table |

## 4. The meter contract

Everything OWL measures goes through **one function**,
`power._read_meter_watts()`. The environment variable `OWL_POWER_SOURCE` picks
what sits behind it:

| `OWL_POWER_SOURCE` | Backend | Use |
|---|---|---|
| `tapo` | `power.py` (built in) | GoS's own bench: Tapo P110 smart plug(s) on the LAN |
| `synthetic` (container default) | `meter_backends.SyntheticBackend` | No meter: idle constant + CPU-load term + noise. Smoke tests only |
| `component` | `meter_backends.ComponentBackend` | **The adapter for platform telemetry.** Sums the readers listed in `OWL_COMPONENT_READERS` |

### 4.1 The interface

A backend is an object with:

```python
def read(self) -> float
    # Total watts for the measured scope, RIGHT NOW. Synchronous; OWL calls it
    # from a thread once per second. Raise on any failure.
last_components: dict[str, float] | None
    # {component: watts} for the read() just made, e.g. {"cpu": 61.2, "dram": 9.8, "gpu": 104.5}
def stamp(self) -> dict
    # Provenance stamped on every result as power_hardware:
    # {"name", "kind", "resolution_s", "scope", ...}
```

A component **reader** (`OWL_COMPONENT_READERS=rapl,nvidia,http`) is even
smaller. It has one method, `read() -> {component: watts}`, and the component
backend sums every reader's dict into the total. Readers that ship today:

| Reader | Source | Notes |
|---|---|---|
| `rapl` | `/sys/class/powercap/intel-rapl:*` energy counters | CPU package(s) and DRAM, on Intel and AMD Zen. Power = Δenergy/Δt between reads (wraparound handled). Needs read access to `energy_uj` (root on most kernels). **Usually absent inside VMs.** |
| `nvidia` | `nvidia-smi --query-gpu=power.draw` | One component per GPU (`gpu`, `gpu1`, …). Board power, instantaneous. |
| `http` | Any HTTP endpoint returning JSON or Prometheus text | Configure with env, no code. See below. |

### 4.2 Adapting to platform telemetry: the recipes, in order of preference

**A. The platform has an HTTP endpoint (JSON or Prometheus): configure, don't code.**

```bash
OWL_POWER_SOURCE=component
OWL_COMPONENT_READERS=http
OWL_POWER_URL=http://169.254.0.10/v1/power           # whatever the platform exposes
# JSON: component=dotted.path (list indices allowed)
OWL_POWER_FIELDS=cpu=sockets.0.power_w,dram=memory.power_w,gpu=gpus.0.power_w
# …or Prometheus text: component=metric_name{labels}
#OWL_POWER_FIELDS=cpu=node_rapl_package_joules_rate,gpu=DCGM_FI_DEV_POWER_USAGE{gpu="0"}
OWL_POWER_SCALE=1                                     # 0.001 if the API reports mW
OWL_POWER_HEADERS=Authorization=Bearer <token>        # optional
OWL_METER_NAME=<Platform> component telemetry
OWL_METER_SCOPE=Component-level: CPU package + DRAM + GPU board (platform telemetry). PSU, fans, NIC, storage excluded.
```

Prometheus counters (joules) are *not* power. Either point at a rate/gauge
metric (watts), or write a reader that differentiates, like `RaplReader` does.

**B. The platform exposes something else (a CLI, a file, a socket, IPMI/Redfish).**
Add a reader class to `meter_backends.py` and register it in `_READERS`:

```python
class PlatformReader:
    """<what it reads, its native update rate, its scope>"""
    def __init__(self):
        ...  # validate access here; raise RuntimeError("why") if unavailable
    def read(self) -> dict:
        return {"cpu": ..., "dram": ..., "gpu": ...}   # watts, fresh, unsmoothed

_READERS = {..., "platform": PlatformReader}
```

Then add a test next to `tests/test_meter_backends.py` (fake the source, assert
the watts) and set `OWL_COMPONENT_READERS=platform`. Readers compose, so
`OWL_COMPONENT_READERS=platform,nvidia` is fine *as long as they do not
double-count* (e.g. two sources that both include the GPU).

Redfish/IPMI DCMI give **whole-system** power (closer to the wall). Name that
component `system` and say so in `OWL_METER_SCOPE`. Don't add it to CPU/DRAM
readers, which it already contains.

### 4.3 Invariants a backend must keep

1. **Watts, as a float, now.** Not an average over minutes, not a cumulative
   counter, not a cached value. If the source only refreshes every *k* seconds,
   say so in `stamp()["resolution_s"]`. OWL still polls at 1 Hz, and repeated
   values lower the effective sample count.
2. **Raise on failure.** Never return 0, the last value or a guess: a silent
   substitute corrupts ΔW. OWL retries, and a job that cannot read power fails
   loudly.
3. **No smoothing, filtering or flooring.** Confidence is computed from the raw
   sample variance, so smoothing makes results look more certain than they are.
4. **Same scope for baseline and task.** The set of components must not change
   mid-run.
5. **Fast.** `read()` must return well under 1 s (the HTTP reader times out at
   0.8 s by default).
6. **Honest scope.** `stamp()["scope"]` is copied onto every result. It is what
   lets a reader of the data know what was and wasn't measured.

### 4.4 What you get per result

`power_hardware` carries your stamp. `energy` carries the total
(`w_base`, `w_task`, `delta_w`, `delta_e_wh`, raw `*_samples_w`, `confidence`).
With a component source, `energy.meters.components` adds the breakdown:

```json
"components": {
  "by_component": {"cpu": {"w_base": 38.1, "w_task": 96.4, "delta_w": 58.3},
                   "dram": {"w_base": 7.9, "w_task": 9.2, "delta_w": 1.3},
                   "gpu":  {"w_base": 21.0, "w_task": 23.5, "delta_w": 2.5}},
  "baseline_components_w": [{"cpu": 38.0, "dram": 7.9, "gpu": 21.0}, ...],
  "task_components_w":     [{"cpu": 95.9, "dram": 9.1, "gpu": 23.6}, ...]
}
```

This per-component view, for example "a CPU x264 encode is ~95 % package power"
or "an NVENC encode barely moves the GPU board", is the most valuable thing a
platform with component telemetry can add to GoS's wall-plug data.

## 5. Validating a new power source (do this before trusting any number)

1. **Synthetic first.** Run one `/video` job (Meridian, preset `cpu`) and one
   `/llm` job (tier S, T1) with `OWL_POWER_SOURCE=synthetic`. This proves the
   stack works end to end before the meter is in question.
2. **Switch to your source** and check the live reading at
   `http://localhost:8000/live` (`watts` updates every 5 s). Watch it rise when
   you load the CPU (`docker exec owl-owl-1 python -c "while 1: pass"`) and fall
   back when you stop.
3. **Idle stability.** On an idle box the reading should be flat to within a few
   %. Then run **Settings → Variance calibration** (`POST /variance/run`, Lab).
   It measures this host's idle noise, which the confidence model uses. GoS1's
   calibration values do **not** transfer to your host.
4. **Thermal recovery.** Run **Settings → Pre-calibration**
   (`POST /precalibration/run`). It measures how long this host takes to return
   to idle after load, and sets the cooldowns.
5. **Sanity against a second source**, if you have one (PDU or BMC whole-system
   power): ΔW from components should be *less than or equal to* ΔW at the wall,
   with the gap being PSU losses, fans and so on. A component ΔW above the wall
   ΔW means double counting.
6. **Repeat**: n = 3 per configuration, and report the spread.

## 6. LLM ladder

OWL measures a curated ladder of open models (`model_catalog.LLM_LADDER`):

| Tier | Model | Q4 size | Active params | Fits GoS1 (16 GB GPU, 62 GB RAM) |
|---|---|---|---|---|
| S | `qwen3.5:4b` | 3.4 GB | 4B | GPU |
| M | `qwen3.5:9b` | 6.6 GB | 9B | GPU |
| L | `gpt-oss:20b` | 13 GB | 3.6B (MoE) | GPU |
| XL | `qwen3.5:122b` | 81 GB | 10B (MoE) | ✗ (big hosts only) |

`OWL_LLM_TIERS=S,M,L,XL` pulls the tiers you name, but **only those that fit**
this host (GPU memory + RAM, see `model_catalog.fit_on_host`). Models too big
for the host are greyed out in **/settings** and never offered to run. A model
that only partly fits the GPU runs with part of it on the CPU. It is flagged
*partly on CPU here*: that is a different regime from a full-GPU run, so don't
compare the two. On a large GPU host, `XL` is the interesting addition.

Any other Ollama model can be pulled by hand
(`docker exec owl-ollama-1 ollama pull <model>`). It appears on /llm untiered.

## 7. Access & security

OWL has three tiers. **Anonymous** can browse and run single curated jobs.
**Member** signs in by magic link (needs SMTP, so it is off in the container).
**Lab** (operator) gets settings, batch runs, calibration and deletes.

On GoS's own LAN, "any private IP" is Lab. In a container every visitor arrives
from a private Docker address, so the container **replaces that rule**:

- `OWL_LAB_CIDRS` (default `172.16.0.0/12`, the Docker bridge, which means the
  host itself and SSH tunnels). Lab = loopback + these CIDRs only.
- `OWL_TRUSTED_PROXIES`: if you put nginx, Caddy or a load balancer in front,
  list its address range here. OWL then reads the client IP from `X-Real-IP`,
  which the proxy **must overwrite**, not append.
- The compose file publishes on `127.0.0.1` only. Publishing publicly
  (`OWL_PUBLISH=8000`) without a TLS proxy and a deliberate `OWL_LAB_CIDRS` is
  not recommended.
- The container runs as root so RAPL counters are readable. Treat it as a test
  deployment on a dedicated instance.

## 8. What not to change

| Don't change | Why |
|---|---|
| `confidence.py`, ΔW/ΔE maths (`energy.py`) | The GoS methodology, reviewed by GoS's statistician. Results are only comparable across sites if it is identical. |
| The result format (`results/**.json`) | GoS imports your results (`persist.import_result`) next to its own. Add keys if you must. Never rename or reinterpret existing ones. |
| Cooldown / idle guard (`power.cooldown_between_runs`) | It keeps one run's heat out of the next run's baseline. |
| 1 s polling (`METER_RESOLUTION_S`) | The confidence thresholds (≥10 / ≥5 task polls) assume it. |

If the platform genuinely cannot meet an invariant (e.g. telemetry updates only
every 10 s), say so in the stamp and tell us. Don't work around it in the maths.

## 9. Sending results back

```bash
docker run --rm -v owl_owl-data:/data -v "$PWD":/out alpine \
  tar czf /out/owl-results-$(hostname)-$(date +%F).tgz -C /data results settings.json
```

Every result carries the host, GPU and power-source stamps, so GoS can import
them next to its own bench data, clearly labelled as yours. The host name comes
from `OWL_NODE_LABEL` (else the hostname); set it before your first run, because
it is written into each result and its scope statement.

## 10. Not in the container

These are GoS-bench-specific and switched off via `disabled_routers` and the
`run_*` flags in `settings.container.json`:
- the 10-device client-decode rig (`/decode`);
- REM field meters (`/prepare-rem`);
- Pixop enhancement (`/enhance-run`, which needs Docker-in-Docker and a licence);
- the NR-VQA sandbox;
- peer replication between OWL nodes;
- the GoS findings catalogue (it cites GoS1 results).

## Reference

| File | What |
|---|---|
| `container/Dockerfile` | Ubuntu 24.04 + Python 3.12 venv + torch (`TORCH_FLAVOUR=cpu\|cu128`) + static FFmpeg (NVENC + libvmaf) |
| `container/docker-compose.yml` / `.gpu.yml` | OWL + Ollama 0.35.1; GPU override |
| `container/entrypoint.sh` | `serve` (default), `pull-models`, `fetch-content`, `shell` |
| `container/settings.container.json` | First-start settings (container profile) |
| `container/owl.env.example` | Every environment variable, commented |
| `wattlab_service/meter_backends.py` | Synthetic + component backends, RAPL / nvidia / http readers |
| `wattlab_service/power.py` | Meter dispatch, baseline/task samplers, cooldown, provenance stamp |
| `ARCHITECTURE.md` | Full module map |
| `docs/result_envelope.md` | Result JSON contract |
| `docs/wattlab_traffic_light_confidence.md` | Confidence model (the maths) |

Questions: Greening of Streaming, via the contact on the website.
OWL code: Apache-2.0 (see `LICENSE`). Test videos: CC BY (credits in `wattlab_service/sources.py`).
