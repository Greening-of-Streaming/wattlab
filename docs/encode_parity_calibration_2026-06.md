# Encode parity & energy-quality calibration — method note

*Last updated: 2026-06-19 (Session 53). Companion to the `/video/budget` calculator
and the `encode-parity` measurement harness (`wattlab_service/parity.py`).*

This note explains, in plain terms, what the encode-parity study measures, why the
method is sound, and how to re-run it when the hardware changes. It is written to be
handed to a non-OWL reader (e.g. Tania) without further context.

---

## 1. The operator question

Streaming operators rarely ask "how small can the file be." They fix a **quality
target** — most commonly **VMAF 92** — and then try to **hit that quality for the
least energy**. Two questions follow:

1. **Parity.** For a given codec, can the GPU encoder reach the same VMAF as the CPU
   encoder? Operators report the GPU often scores lower, *especially for AV1*. Is
   that a real hardware ceiling, or just an under-tuned configuration?
2. **Budget.** Given an energy budget (say 1000 Wh), how much video can I transcode
   at my target VMAF, on which hardware, with which codec? This is what the
   `/video/budget` page answers.

Both reduce to the same underlying data: for each *(hardware, codec, quality)* point,
**what bitrate hits the target, what VMAF is achieved, and how many watt-hours per
minute of video it costs.** This study measures that table.

---

## 2. What we measure, and against what

For a fixed source clip we sweep an **ABR bitrate ladder** across:

| Axis | Values |
|------|--------|
| Codec | H.264, H.265, AV1 |
| Encoder | **CPU** (libx264 / libx265 / libsvtav1) · **GPU** (NVENC, two configs) |
| GPU config | **baseline** (OWL's current live NVENC args) · **tuned** (baseline + quality knobs) |
| Content | **BBB** (low spatial/temporal complexity) · **Meridian** (high complexity) |

Every encode goes through the **same pipeline** OWL's `/video` page uses — hardware
decode where applicable, scale to 1080p, AAC-128k audio, a GOP pinned identically on
every preset (CR-029 §2). Only the encoder and its quality args vary, so the
comparison is apples-to-apples.

The GPU is measured **twice per point** — once with OWL's current ("baseline") NVENC
arguments, once with a quality-knob bundle ("tuned") — at the **same bitrate**. That
isolates exactly how much VMAF the tuning buys, and what it costs in energy.

---

## 3. Why tuning the GPU is legitimate, not "massaging the numbers"

OWL's NVENC path was deliberately a first cut (the code says so: *"best-effort first
cut to be validated/tuned once the card is installed"*). It ran the encoder near its
**speed** default with no quality knobs. The "tuned" config adds, for NVENC:

```
-preset p7 -tune hq -multipass 2 -spatial-aq 1 -temporal-aq 1 -aq-strength 8 -rc-lookahead 32
   (+ B-frame referencing: -b_ref_mode middle, and -bf 2 for AV1)
```

The integrity line we hold:

- **Free knobs (used).** Every knob above raises quality **at the same bitrate**. It
  does **not** change the rate-control basis, so the bitrate-matched CPU↔GPU
  comparison `/video` relies on is preserved. Bringing an admittedly-unfinished
  encoder config up to its proper operating point is *finishing the measurement*, not
  rigging it.
- **Basis-changing knobs (not silently adopted).** Switching constant-bitrate (CBR)
  to VBR/constant-quality would change what "same bitrate" means. We do not do that on
  the live page. (The study can sweep quality modes separately, clearly labelled.)
- **The honest outcome.** If, fully tuned, NVENC AV1 *still* tops out below
  libsvtav1, that is reported as a genuine finding — an NVENC AV1 quality ceiling —
  not hidden by quietly handing the GPU more bitrate.

> Early signal (H.264, low-complexity content, near quality saturation): the tuned
> knobs were **not** a free win — spatial AQ redistributes bits and can lower the
> *mean* VMAF slightly on simple content. The knobs are applied per-codec only where
> they measurably help. This is exactly why we measure rather than assume.

---

## 4. Clip length — the reasoning

Clip length multiplies across ~90 encodes, so it matters. We chose **30 seconds**,
triangulated from the literature:

- **Energy needs the task to run long enough.** NVIDIA's own FFmpeg guidance
  recommends **>15 s** so process/CUDA-context init overhead is negligible; the
  `nvidia-smi` power-measurement study recommends **≥5 s** runtime and discarding the
  first ~1 s transient. SPECpower (the server-power benchmark) samples at **1 Hz** —
  the same cadence as OWL's meter — but averages over a long fixed window.
- **Quality has a standards convention of ~10 s.** ITU-R BT.500 fixes 10 s sequences
  (*"extending beyond 10 s does not improve the assessor's ability to grade"*); ITU-T
  P.910 and VQEG use ~10 s; VMAF itself was trained on 6–10 s single-scene clips. A
  QoMEX 2012 study comparing 10/15/30/60/120/240 s found no strong quality-score
  differences by duration.
- **30 s clears the energy floor with margin and contains the 10 s quality unit.**

### The NVENC-speed wrinkle (and our fix)

A 1080p NVENC encode of a 30 s clip finishes in a *few seconds* — far too fast to
collect enough 1 Hz power samples for a tight confidence interval. We therefore
**repeat the encode back-to-back inside one measurement window until ≥20 s of
wall-clock has elapsed**, and normalise energy by the **total content encoded**
(`clip_seconds × n_encodes`). Slow encoders (libx265, libsvtav1) already exceed 20 s
in a single pass and run once. This is the standard way to measure a fast operation's
power, and it is what lets NVENC rows reach usable confidence.

### Caveats we carry (honest limitations)

1. **Autocorrelation.** Consecutive 1 Hz samples are correlated, so the textbook
   σ/√n *understates* true uncertainty. The repeat-to-window approach (a longer fixed
   window) is the mitigation, in the spirit of SPECpower.
2. **Pooling > length for quality.** On multi-scene content the arithmetic-mean VMAF
   over-rates quality regardless of length. OWL reports the pooled mean; for varied
   content, harmonic-mean / 5th-percentile are the more conservative reads.
3. **Segment representativeness.** A single 30 s segment may not capture a source's
   full complexity range. SI/TI (ITU-T P.910 spatial/temporal information) is the
   right lever for choosing a representative window — OWL already computes windowed
   SI/TI and can drive segment selection in a future revision.
4. **Achieved vs target bitrate.** Single-pass ABR does not perfectly hit its target
   on short clips. We therefore record the **achieved** bitrate per encode and build
   the rate-quality curves on that, not on the requested target.

---

## 5. Measurement protocol (per encode)

Standard OWL device-layer protocol (*"device layer only — network, CDN and CPE
excluded"*):

1. **Focus mode** — background maintenance timers stopped.
2. **Baseline** — N×1 s idle polls → `W_base`.
3. **Task** — the encode(s), wall power polled at 1 Hz on the Tapo P110 (dual-meter
   daisy-chain, per-meter combine — CR-065 `ci2`).
4. **Energy** — `ΔW = W_task − W_base`; `ΔE = ΔW × ΔT/3600` Wh; `Wh/min =
   ΔE ÷ (content_minutes)`.
5. **Confidence** — Traffic-Light Confidence (`confidence.py`): 🟢/🟡/🔴 from
   `Φ(ΔW/SE)` and the task-sample count.
6. **VMAF** — computed as a **terminal pass** *after* the measurement window closes,
   so its CPU draw never enters a reported energy figure (CR-044).

---

## 6. The artifact — fingerprinted and self-documenting

Each run writes one JSON file under `results/calibration/`, keyed by a **hardware
fingerprint**, so a hardware change (e.g. the NetInt ASIC cards) produces a *new*
dataset instead of silently overwriting the old one:

```
fingerprint: { gpu (vendor/name/encode), cpu (model/cores),
               ffmpeg_version, power_meter, owl_version }
protocol:    { clips, duration_s, gop, baseline_polls, cooldown_s,
               min_task_s, tuned_knobs, expected_rows }
rows[]:      { clip, codec, profile, target_bitrate_kbps,
               ffmpeg_cmd,                 ← the EXACT command, for reproducibility
               vmaf, achieved_bitrate_bps,
               delta_w, delta_e_wh_total, wh_per_min_video,
               n_encodes, content_s, poll_count,
               confidence_flag, confidence, stream }
```

Each row carries the **exact ffmpeg command** it ran, so the data documents itself:
anyone can reproduce a single point from its row alone. The file is checkpointed after
every row and carries a `complete` flag, so an interrupted run still yields a valid
(partial) artifact.

---

## 7. How to re-run (when hardware changes)

The harness is one importable module (`parity.py`) driven two ways:

**Now — command line:**
```
bin/run-encode-parity --print-only --full   # show every recipe command, no encode
bin/run-encode-parity --dry                  # plumbing test: real encodes + VMAF,
                                             #   SYNTHETIC energy, no meter
bin/run-encode-parity --full [--duration 30] # the full metered matrix
```

**Operational contract for a real (metered) run — pause, don't stop.** The P110's
KLAP session is exclusive per device, so only one process may poll it. Rather than
stopping the service (which takes the UI down), **pause the queue** — set
`/tmp/owl-paused` (the `/queue-status` toggle, or `touch`). The 5 s background power
poller honours that flag and backs off (`runtime.power_poller`), freeing the meter for
the harness while the UI stays up. Un-pause when done.

**Future — from the UI:** a planned `/video/budget/reconfigure` page (Lab-only) runs
this same matrix as an in-service job and writes a fresh fingerprinted artifact — so
when the NetInt cards land, re-calibration is a button, not a shell session.

---

## 8. From data to the budget page

The `/video/budget` calculator reads this artifact via `budget_data.py` (it falls back
to an illustrative fixture only when no *complete* measured artifact exists):

- For a chosen **target VMAF** (default 92, set on `/settings` → `target_vmaf`), read
  off each recipe's curve the **achieved bitrate** that hits it and the corresponding
  **Wh/min**.
- `hours_of_video = budget_Wh ÷ Wh_per_min ÷ 60` — budget scales, constraints (VMAF
  floor, complexity) filter, and **codec is a comparison axis** (not a constraint —
  toggle to see codecs side by side).
- **Output unit — the ABR ladder.** "1080p only" is the top rung alone (the swept
  curve). "Full ABR ladder" is a **5-rung** ladder: 1080p (target-driven) + fixed
  720p@2800 / 540p@1600 / 480p@1100 / 360p@800 (H.264 kbps; H.265 ×0.6, AV1 ×0.5).
  Ladder Wh/min = top-rung@target + Σ lower rungs. Lower rungs are measured fixed-
  bitrate on **cpu + gpu_baseline only** (gpu_tuned was rejected, §9.3), so each adds
  ~12 encodes; the harness can add them to an existing parity run via `--ladder`
  without re-measuring the 90 sweep encodes.
- Hardware is presented as **generic classes** (CPU / GPU / ASIC-FPGA); a specific
  measured model can be listed alongside its class as a vendor comparison.
- Public method summary lives on **`/methodology#energy-budget`**, which the budget
  page links to directly.

---

## 9. Results — first full run (2026-06-19)

90 encodes, all 🟢 confidence (the repeat-to-20s sampling worked — 20–27 power
samples per row). GoS1: AMD Ryzen 9 7900 (24c) + RTX 5080 (NVENC), ffmpeg
`N-124403`. Artifact: `results/calibration/encode_parity_nvenc_24c_2026-06-18.json`.
1080p single rendition, per minute of source.

### 9.1 Energy — the headline

NVENC is **2.5–4.4× more energy-efficient per minute of video** than the CPU encoder,
and the win comes from **speed, not lower power draw** (instantaneous ΔW is similar,
~58–78 W across all encoders; the GPU simply finishes far sooner):

| Codec | CPU Wh/min | GPU Wh/min (baseline) | GPU advantage |
|-------|-----------:|----------------------:|--------------:|
| H.264 | 0.388 | 0.151 | 2.6× |
| H.265 | 0.712 | 0.161 | 4.4× |
| AV1   | 0.396 | 0.156 | 2.5× |

### 9.2 Parity — CPU vs GPU VMAF (baseline NVENC)

The "GPU scores lower, especially AV1" effect operators report is **real, but
confined to low-complexity content at low bitrate**:

- **Low-complexity (BBB):** GPU trails CPU at every bitrate — worst for **AV1 at
  1000 kbps (−8.9 VMAF)**, narrowing to ~−1.7 at 6000 kbps. H.265 −5.0→−2.2; H.264
  −2.5→−1.7.
- **High-complexity (Meridian):** the gap nearly **vanishes**. H.264 within ~0.1–0.7;
  H.265 −1.0 to −4.4 (low bitrate only); and **NVENC AV1 *beats* libsvtav1 by
  0.5–0.8 VMAF at mid-high bitrate** (libsvtav1 at its default preset gives up
  efficiency on hard content).

So the parity gap is a **low-complexity / low-bitrate** phenomenon, not a blanket GPU
deficit. The honest framing for operators: *on demanding content the hardware encoder
is at parity (or better); the CPU's quality edge shows mainly on easy content at tight
bitrates.*

### 9.3 The tuned NVENC bundle — measured, and rejected for the live path

The quality bundle (`-preset p7 -tune hq -multipass 2 -spatial-aq -temporal-aq
-rc-lookahead`, + B-frame refs) **does not earn its place on a VMAF-target workflow**:

- It **lowers** VMAF for H.264 (−0.2 to −1.4) and AV1 (−0.2 to −1.6) at every point;
  it only helps **H.265 at low bitrate** (+0.5 to +2.0).
- It costs **1.6–2.8× the energy** of baseline (`-multipass 2` ≈ doubles the work).

Mechanism: spatial/temporal AQ redistributes bits toward perceptually-salient regions,
which *raises subjective quality but lowers a fidelity metric like VMAF*. For a
VMAF-target operator the bundle is the wrong trade on two axes (quality and energy).

**Recommendation: do NOT flip the live `/video` GPU args** to the tuned bundle. Keep
the current baseline NVENC config. (If a future workflow optimises for *subjective*
quality rather than VMAF, revisit `-spatial-aq` for H.265 specifically.)

### 9.4 ABR ladder (48 lower-rung encodes, all 🟢)

Full 5-rung ladder energy at VMAF 92, low-complexity (Wh/min of source):

| Codec | CPU 1080p-only | CPU full ladder | GPU 1080p-only | GPU full ladder |
|-------|---------------:|----------------:|---------------:|----------------:|
| H.264 | 0.329 | 1.027 | 0.163 | 0.732 |
| H.265 | 0.674 | 1.905 | 0.167 | 0.791 |
| AV1   | 0.410 | 1.365 | 0.166 | 0.741 |

**The GPU advantage narrows across the ladder.** At 1080p-only the GPU is up to 4.0×
cheaper (H.265: 0.674 vs 0.167); on the full 5-rung ladder it is ~1.4–2.4× cheaper
(H.265: 1.905 vs 0.791 ≈ 2.4×). The lower rungs are cheap on *both* encoders, so they
dilute the headline 1080p gap — worth stating when quoting a single "GPU is N× greener"
figure: the multiple depends on whether you mean one rendition or a whole ladder.

### 9.5 Caveats specific to this run

- Single 30 s segment per source. The Meridian "AV1 GPU beats CPU" result is at
  **libsvtav1's default preset** — a slower SVT preset would likely reclaim the lead;
  this is a default-vs-default comparison, not SVT's ceiling.
- VMAF mean pooling; on these mixed-complexity clips the 5th-percentile read would be
  more conservative (§4 caveat 2).
- Lower ladder rungs are reported by energy only — their VMAF (lower resolution vs the
  1080p reference) is not the quality anchor; the top rung carries the VMAF target.
