# WattLab

WattLab measures the real device-side energy cost of video transcoding and AI inference on physical hardware — using a calibrated smart plug, not estimates or models.

Built by [Greening of Streaming](https://greeningofstreaming.org), a French NGO working on the environmental impact of streaming infrastructure.

**Live instance:** [wattlab.greeningofstreaming.org](https://wattlab.greeningofstreaming.org)

**Current release:** `v1.2.0` · [Report an issue or feature request](https://github.com/greeningofstreaming/wattlab/issues)

---

## What it measures

| Test | What you get |
|---|---|
| Video transcode | Energy (Wh) and time for CPU vs GPU — H.264, H.265, AV1 at matched ABR bitrates. "Compare all codecs" runs all six presets in one go. |
| LLM inference | mWh per output token, tokens/sec — TinyLlama 1.1B, Mistral 7B, Gemma 3 12B across three size tiers |
| Image generation | Wh per image — SD-Turbo (~1B), SDXL-Turbo (~3.5B). "Compare Models" runs both with same prompt + seed so model size is the only variable. |
| RAG energy test | Energy cost of retrieval-augmented generation vs plain LLM — baseline / rag / rag_large compared side-by-side |

All figures are delta above idle baseline, sampled at 1-second intervals via a Tapo P110 smart plug on the mains supply.

**Scope: device layer only.** Network, CDN, and CPE are explicitly excluded. No amortised training cost in LLM measurements.

---

## What it does not measure

- Network energy (transit, CDN, last-mile)
- Embodied carbon or manufacturing impact
- LLM training cost
- Cloud or multi-node workloads

These exclusions are deliberate. Scope statements appear on every result.

---

## Hardware

**GoS1** — lab server in France

| Component | Spec |
|---|---|
| CPU | AMD Ryzen 9 7900, 24 cores |
| GPU | AMD Radeon RX 7800 XT, 12 GB VRAM (ROCm) |
| RAM | 61 GB |
| OS | Ubuntu 24, kernel 6.17 |
| Power meter | Tapo P110 smart plug (mains, 1s polling) |
| Idle draw | ~51–54 W |

---

## Key findings so far

**Video — ABR all-codecs benchmark (Meridian 120s, 3 runs, all 🟢)**
- H.264 at 4000 kbps: CPU 37.3s / 0.83 Wh · GPU 17.5s / 0.37 Wh → GPU ~55% less energy
- H.265 at 2000 kbps: CPU 70.3s / 1.58 Wh · GPU 14.5s / 0.29 Wh → GPU ~81% less energy
- AV1 at 1500 kbps: CPU 30.8s / 0.65 Wh · GPU 14.5s / 0.30 Wh → GPU ~55% less energy
- All GPU presets use the full VAAPI pipeline (decode + scale + encode). Earlier "GPU uses more energy" result was from a partial pipeline (CPU decode + GPU encode) — superseded.

**LLM cold inference 🟢**
- Mistral 7B T3: 0.94 mWh/token
- TinyLlama 1.1B T3: 0.06 mWh/token (~15× more efficient per token)
- Gemma 3 12B now available for larger-model comparison

**Image generation — SD-Turbo CPU 🟢**
- 0.21 Wh/image, 12s generation time, ~30W delta above idle

**Ship-of-Theseus honesty:** when earlier methodology improvements (full GPU pipeline, ABR rate control) change what a result means, the old finding is marked superseded rather than silently overwritten.

---

## Access

Three tiers, one URL — `https://wattlab.greeningofstreaming.org`. The same page renders different controls depending on who's looking:

| Tier | Who | How | What's unlocked |
|---|---|---|---|
| **Anonymous** | Public visitors | Just open the URL — Anonymous tier resolves automatically | Curated workloads, full guided tour at `/demo`, prev-result panels populated from curated demo runs |
| **Member** | GoS members on the allowlist | Sign in via the magic-link form on `/auth/sign-in` (email-based) | Custom prompts / ffmpeg commands, all-codecs sweeps, RAG corpus uploads, video uploads ≤ 1 GB, CSV/JSON bulk export |
| **Lab** | Operators on GoS1 | LAN address (`192.168.x.x`) or SSH tunnel | Full settings, variance calibration, thermal-recovery probe, all jobs unscoped |

**Anonymous quick-look:** `https://wattlab.greeningofstreaming.org/demo` — the seven-step Guided Tour with predetermined demo jobs (H.265 CPU vs GPU, Mistral 7B T3, SD-Turbo, RAG 3-mode).

**Lab via SSH tunnel:**
```
ssh -p 2222 -L 8000:localhost:8000 user@gos1.duckdns.org
# then open http://localhost:8000
```

The capability matrix is product copy on `/demo` step 6, and lives in code at `wattlab_service/capabilities.py` (one row per capability). All routes gate on capabilities, not raw tier compares.

---

## Running locally

Requires GoS1 or equivalent hardware (P110 plug, ROCm GPU optional).

```bash
cd wattlab_service
pip install -r requirements.txt   # see CLAUDE.md for full package list
cp .env.example .env              # add TAPO_EMAIL, TAPO_PASSWORD, TAPO_P110_IP
uvicorn main:app --host 0.0.0.0 --port 8000
```

The service runs as a systemd unit on GoS1 (`systemctl status wattlab`).

---

## Documentation

- [`WATTLAB_SPEC.md`](WATTLAB_SPEC.md) — original v0.2 product spec (April 2026, mostly delivered; current architecture in `CLAUDE.md`)
- [`JOURNAL.md`](JOURNAL.md) — session-by-session build log with findings
- [`TESTING.md`](TESTING.md) — three-tier testing strategy (smoke / integration / manual)
- [`STAGING.md`](STAGING.md) — staging mode (swap onto a feature branch with a maintenance page)
- [`bin/README.md`](bin/README.md) — operator-facing shell scripts (`stage-on`, `stage-off`, `probe-thermal-recovery`, `owl-maintenance-watchdog`)
- [`systemd/README.md`](systemd/README.md) — systemd unit files for OWL services
- [`CHANGE_REQUESTS.md`](CHANGE_REQUESTS.md) — active design / change requests
- [`CHANGE_REQUESTS_CLOSED.md`](CHANGE_REQUESTS_CLOSED.md) — shipped CRs archive
- [`docs/wattlab_traffic_light_confidence.md`](docs/wattlab_traffic_light_confidence.md) — Tania's statistical framework for the confidence flag (CR-028 Phase 2 spec)
- [`docs/wattlab_parameters_audit.md`](docs/wattlab_parameters_audit.md) — every settings parameter classified and the path to principled values
- [`CLAUDE.md`](CLAUDE.md) — project context for Claude Code (AI assistant config)
