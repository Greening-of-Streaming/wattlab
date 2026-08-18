# Measuring a too-short clip: is "loop it to reach a green flag" valid?

**Bench experiment, 2026-07-07.** Standalone harness (`scratchpad/loop_validity.py`) — drives
ffmpeg directly + polls the `.91` P110 at 1 Hz, imports only `confidence.confidence()` so the
flag matches OWL exactly. **No OWL code touched.** Data: `scratchpad/loop_validity_results.json`
(62 rows). Teardown clean (lock + `owl-paused` cleared, focus timers restarted).

## The question
A clip whose transcode finishes in fewer seconds than the 1 Hz sampler needs is flagged **RED**
(too few task samples). OWL's `parity._measure_recipe` works around this by repeating the encode
back-to-back until the window reaches 20 s, then normalising energy by content-seconds. **Is that
valid, and does the *way* you loop change the answer?** Four ways compared:
- **A · 1×** — single encode (the red baseline)
- **B · ffmpeg internal loop** — one process, `-stream_loop k` (ONE startup, k clips)
- **C · N back-to-back invocations** in one continuous window (**parity's method** — N startups)
- **D · N full OWL-style runs, aggregated** (separate windows + gaps, pooled samples)

## Setup
- **Clip:** BBB down-scaled to **1080p, 9.97 s** (HD→HD, no scaling in the measured command).
- **GPU:** `h264_nvenc` CBR 4 Mbps (hardware-fast). **CPU:** `libx264 -preset ultrafast` 4 Mbps
  (software-fast, minimal work). Both are **RED at 1×** (GPU ~1.5 s, CPU ~0.7 s wall).
- Energy math identical to OWL: `ΔW = mean(task) − w_base`, `ΔE = ΔW × ΔT/3600`. Output `-f null`.
- 3 reps/point (2 for D). Focus mode + `owl-paused` + measure-lock held throughout.

## Results (means across reps)

| enc | method | clips | wall s | n_task | flag | ΔW (W) | Wh/clip | Wh/min |
|---|---|--:|--:|--:|:--:|--:|--:|--:|
| gpu | **A 1×** | 1 | 1.6 | 2 | 🔴 | **7.98** | 0.00353 | 0.021 |
| gpu | C→green | 10–18 | 14–25 | 15–26 | 🟢 | 73–79 | **0.0285–0.0307** | 0.171–0.185 |
| gpu | B→green | 8–16 | 9–17 | 9–18 | 🟢 | 69–75 | **0.0210–0.0225** | 0.127–0.135 |
| gpu | D N=20 | 20 | 29 | 40 | 🟢 | **44.8** | 0.0183 | 0.110 |
| cpu | **A 1×** | 1 | 0.8 | 1 | 🔴 | **0.91** | 0.0002 | 0.001 |
| cpu | C→green | 18–35 | 13–25 | 14–26 | 🟢 | 65–69 | **0.0130–0.0139** | 0.078–0.084 |
| cpu | B→green | 16–32 | 9–19 | 10–19 | 🟢 | 65–71 | **0.0106–0.0114** | 0.064–0.069 |
| cpu | D N=20 | 20 | 16 | 20 | 🟢 | **38.2** | 0.0084 | 0.051 |

## The six verdicts

**1. A single encode (1×) is unusable — correctly RED.** ΔW came out **7.98 W (GPU) / 0.91 W
(CPU)** when the true encode draw is ~72 W / ~65 W. The 1–2 stale samples over a ~1 s encode miss
the power spike entirely, so the energy is **10–70× under-measured**. The red flag is right.

**2. Looping to green is legitimate — *if the encoder stays continuously busy* (B and C).** Both
give accurate ΔW (~65–79 W) and real green flags. The extra samples are genuine power readings
over a genuinely longer, continuously-loaded window — not gamed.

**3. But the per-content energy is METHOD-DEPENDENT.** At the green plateau:
- **GPU:** C (startup-in) = **0.0296 Wh/clip** vs B (steady) = **0.0218** → **+35.8%**.
- **CPU:** C = **0.0134** vs B = **0.0110** → **+22.0%**.
The gap ≈ the **per-encode ffmpeg/NVENC startup energy** (~0.0078 Wh/encode on GPU). C pays it N
times (one per invocation); B amortises one startup over k clips. **The divergence scales with
encoder speed** (bigger on hardware-fast NVENC), exactly as predicted — startup is a larger share
of a faster encode.

**4. ⚠ The "re-run N times and aggregate" method (D) is INVALID for short clips — and dangerously
so, because it looks green.** D reaches 🟢 (40 pooled samples) but reports **0.0183 Wh/clip (GPU)**
— *below both* B and C, an **under-count of ~40%** — because each short sub-run's 1 Hz sampling is
stale and the idle gaps between runs dilute the pooled mean (ΔW collapses to 44.8 W vs the true
~72 W). **A green flag obtained by pooling separate short runs does NOT certify a correct energy.**
This is the one method to never use.

**5. Repeatable once green.** C-plateau relative std is **4.2% (GPU) / 3.5% (CPU)** across reps —
the green figures are stable and trustworthy.

**6. Verdict / recommendation for OWL.**
- **Parity's choice (C: back-to-back, *continuous*, normalise by content) is the right one** — it
  is the only approach that both reaches green *and* keeps the encoder continuously loaded so ΔW
  is accurate. It correctly beats the naive re-run (D).
- **Caveat to document:** for a *short* clip, C's content-normalised `Wh/min` is **startup-inflated
  by +22–36%** (more on faster encoders). It represents "energy to encode this clip repeatedly,
  startup included" — which is what a user actually pays per short encode — but it is **not
  comparable to a long clip's Wh/min** (whose startup share is negligible). Two honest options:
  report **per-encode energy + the startup fraction**, or only content-normalise once the *single*
  encode is long enough that startup is a small share.
- **Never aggregate separate short re-runs (D)** — it silently under-counts behind a green flag.
- If you want the true steady per-content figure (for extrapolating to long content), that's **B**
  (internal `-stream_loop`), not C.

## Caveats
- n=1 clip, one bitrate, one box. The effect magnitudes are specific to this hardware/preset; the
  *direction* (C > B by the startup share; D under-counts; A unusable) is the robust result.
- D used one shared baseline for its N sub-runs (a faithful-enough stand-in for "re-run and
  aggregate"; the under-count comes from the short sub-windows, not the baseline).
- The whole effect is a consequence of 1 Hz P110 sampling vs sub-second encodes — the exact regime
  `parity` was built for; this validates that design and quantifies its short-clip caveat.
