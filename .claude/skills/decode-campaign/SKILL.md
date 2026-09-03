---
name: decode-campaign
description: Run and import a decode-bench campaign (the 10-device decode rig, client-decode energy) — wake-check, July-comparable protocol, contamination screen, idempotent import into OWL decode envelopes, regime-labelled reporting. Use when running decode/playback energy rows on the portable rig, or when the user says "decode campaign", "run the decode bench", "import decode results", or types /decode-campaign.
argument-hint: [device/config or "import <files>"]
---

# Decode-bench campaign (WattLab / OWL)

Rig code: `decode_bench/` in the repo (`bench.py` + drivers, `origin.py`, JSON device configs);
deployed bench home `/srv/data/owl/decode-bench/`. Full protocol + device/plug/IP table:
`decode_bench/README.md`. Target: $ARGUMENTS

## 1. Before running (on top of /bench-preflight)

- **Rig = 10 devices across five drivers** — adb: Fire TV, Google TV Streamer, Bbox, Xiaomi Gen 2,
  Xiaomi Gen 3 · ssh: Pi 400, Pi 5 · atv: Apple TV · roku: Roku · webos: LG C2. Fire TV, Xiaomi
  Gen 2 and Bbox run headless. Registry + plugs: `rig.py` `RIG`; addresses: `decode_bench/README.md`.
- **Shared screen = the LG C2** (SSAP host `.26`, panel plug Lab-E `.71`); its 4 HDMI inputs are
  mapped in `/settings` (`rig_hdmi_inputs`: gtv HDMI_1, atv HDMI_2, roku HDMI_3, xiaomi3 HDMI_4) —
  claim-screen / screen-mode is refused for an uncabled device.
- **Wake-check the adb boxes** — they sleep and lock out adb; wake via the WoL path first. Pis over
  ssh (BatchMode keys, ethernet or wlan power-save off); purge `/dev/shm` on the Pi 5 first.
- **Streams** = the matched-VMAF loop families `bbb` / `meridian` / `kranjska` / `football`, their
  iso-bitrate families (`bbbiso` / `meridianiso` / `kranjskaiso` / `footballiso`), the `bbbnet`
  network arms and the sync clips — served from GoS1 `:8123` by `origin.py` (Range-correct since
  2026-07-31, CR-072).

## 2. Run

- `python3 bench.py <config>.json` — settle → baseline → start → startup-skip → sample window →
  stop → `confidence.py` → per-row checkpoint, resumable (details: `decode_bench/README.md`).
- Two arms, never mixed in one comparison: **realtime** playback (device-total W) vs **full-speed
  pure decode** (`ffmpeg -f null` — Wh per file, never bare W) (details: `decode_bench/README.md`).
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
