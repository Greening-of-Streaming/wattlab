---
name: decode-campaign
description: Run and import a decode-bench campaign (Google TV / Raspberry Pi client-decode energy) — wake-check, July-comparable protocol, contamination screen, idempotent import into OWL decode envelopes, regime-labelled reporting. Use when running decode/playback energy rows on the portable rig, or when the user says "decode campaign", "run the decode bench", "import decode results", or types /decode-campaign.
argument-hint: [device/config or "import <files>"]
---

# Decode-bench campaign (WattLab / OWL)

Rig lives at `/srv/data/owl/decode-bench/` (bench.py + JSON device configs; full protocol in its
README and `docs/pi_decode_energy_2026-07.md`). Target: $ARGUMENTS

## 1. Before running (on top of /bench-preflight)

- **Wake-check the Google TV** — the box sleeps and locks out adb (standby ≈0.64 W); wake via the
  raw-WoL path first. Devices: GTV `.126` (plug Lab-D `.36`, monitor `.199`); Pis over ssh
  (BatchMode keys, ethernet or wlan power-save off).
- Streams: `streams/` symlink → the 27 matched-VMAF (~92–93, v1) 1080p NVENC encodes, served from
  GoS1 `:8123`. ⚠ That server **ignores Range requests** — prime suspect for the media3 2.1×
  over-fetch; don't attribute network-fetch anomalies to the player without remembering this.
- Pi tmpfs staging: purge `/dev/shm` first (clips accumulate on the Pi 5).

## 2. Run

- `python3 bench.py <config>.json` — protocol per row: settle → baseline → start → startup-skip →
  sample window → stop → OWL `confidence.py` → per-row checkpoint. Results in
  `results/<config>.json` (raw 1.5 s samples included, resumable).
- Two arms, never mixed in one comparison: **realtime** (mpv on KMS / `-re`; device-total W is
  meaningful) vs **full-speed pure decode** (`ffmpeg -f null`; decode outruns realtime — report
  Wh per file, never bare W).
- The adb driver deliberately never runs `pm clear` (the July tooltip-overlay contamination);
  the mid-window screenshot is the proof — keep it.

## 3. Contamination screen — before believing any row

- Check screenshots/logcat (`CCodec allocate(c2.*)` proves the decoder path on GTV) and the Pi
  player log per row. Precedent: the first realtime h264/hevc Pi rows were contaminated and
  discarded — replication (n≥2) on headline rows is the norm.
- Bad rows are **discarded and documented**, imported into the envelope's top-level
  `discarded[]` block — visible provenance, excluded from `runs[]`.

## 4. Import into OWL

- `bin/import-decode-bench-results` — idempotent (re-run overwrites the same files); writes
  `results/decode/{date}_{job_id}.json`, mode `decode_panel`, contract-shaped `energy{}` per run
  with raw samples.
- **New campaign result files must be added to the script's source list** (and new job_ids
  minted) — it imports a fixed set; it won't discover your new JSON.
- After import: `cd wattlab_service && pytest tests/ -k "envelope or decode"`.

## 5. Report + claims

- **Always state the regime.** Software codec ordering is h264 < av1 < hevc at 1× on both Pis
  and INVERTS saturated — a decode-energy claim without its regime is wrong by omission.
- Board facts that shape hypotheses: Pi 5 has NO hw H.264 (block removed); both Pis' HEVC hw is
  stranded on stock Bookworm userspace; Pi 400/Pi 4 hw H.264 ≤1080p60 via `h264_v4l2m2m`.
- Findings go through `/finding-draft` (cite the imported `decode/<job_id>` result ids).
