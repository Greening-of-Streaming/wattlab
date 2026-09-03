# STB two-axis decode campaign — same silicon vs same vendor (2026-09-02, DRAFT plan)

> **Superseded 2026-09-03.** This is the pre-launch plan; the campaign ran the same night and every decision here was taken and reported in `intra_content_sync_2026-09-03.md` (§4 axes at n=3, §5 caveats). The HDMI map, device parking and 'headless' definition below are as of 2026-09-02 and no longer current (headless rows are now a no-sink regime; Apple TV is back on HDMI_2, Roku on HDMI_3). Kept as the design record.

Status: **plan only — nothing beyond the two probes below has run.** Owner review before launch.
Executor: any model with the rig context (this file + `decode_bench/README.md` + `/decode-campaign` skill).

## 0. The question

Four boxes, two orthogonal comparisons, one shared protocol:

| Axis | Held constant | Varies | Pair |
|---|---|---|---|
| **A — silicon** | MediaTek MT8696 | OS/vendor stack (Fire OS 8 / Android 11 vs Google TV / Android 14), form factor (stick vs box), network (Wi-Fi vs Ethernet), PSU | **Fire TV Stick 4K** (`firestick`) vs **Google TV Streamer** (`gtv`) |
| **B — vendor** | Xiaomi, Google TV, box form factor, Wi-Fi | Silicon generation (Amlogic S905X4 "sc2" / Android 11 / **OMX** decoder HAL vs Amlogic s7d / Android 14 / **Codec2**) | **Xiaomi TV Box Gen 2** (`xiaomi`) vs **Gen 3** (`xiaomi3`) |

Shared across all four: Just Player (see §1 decision 2), the matched-VMAF (~92, v1) 1080p NVENC clips
from GoS1 `:8123` over LAN HTTP, `bbb_codecs_rt`'s bench block (settle 15 · baseline 20 · startup-skip
8 · window 150 · gap 10, 1 s cadence), one Tapo P110 (fw 1.3.1) per box, protocol v3 idle guard,
`confidence.py` per row. **Regime: realtime playback (decode + present) — state it on every table.**

What we want to be able to say (each with n + 95 % CI, operating point named):
1. **Idle floor** per box — form factor/OS lives here (stick 0.6 W vs box 1.3–2.5 W), not silicon.
2. **Marginal ΔW per codec** (H.264 / HEVC / AV1 / VP9) per box — silicon lives here.
3. **Attributional total** (idle + Δ) per box × codec — what a viewer actually pays.
4. **Decoder provenance** 4×4: which hardware block (or software fallback) each box actually uses per
   codec, from logcat — this alone may be the headline on both axes (does Google TV expose MT8696's
   VP9 block? does s7d hw-decode AV1/VP9? does Fire OS route the same chip differently?).
5. Whether **4-wide parallel** measurement reproduces the serial rows (§2 probe) — a rig capability claim.

## 1. Decisions needed from the owner before launch

1. ~~**GTV's HDMI input.**~~ **RESOLVED** — GTV was physically re-cabled onto HDMI_1 (displacing the
   Bbox) earlier the same session; `rig_hdmi_inputs` just caught up to match (`gtv: "HDMI_1", bbox: ""`).
   Live map confirmed: `HDMI_1 gtv · HDMI_2 xiaomi · HDMI_3 firestick · HDMI_4 xiaomi3`. Leg S is clear
   to run on all four.
2. **Just Player version on GTV.** Installed today: Fire TV **0.196**, Gen 2 **0.196**, Gen 3 **0.196**,
   GTV **0.212-legacy** (its July/Aug findings ran on it). For the "same everything else" logic the
   player should match. Recommendation: install 0.196 on GTV for this campaign (uninstall + install —
   Android 14 refuses `-d` downgrades, as Gen 3 did), one JOURNAL line noting GTV's prior findings were on
   0.212-legacy. Ben's stated view that pure software-layer effects are imperceptible argues this is safe;
   matching it anyway removes an argument later. Alternative: leave it and carry it as a stated caveat.
3. **n = 3 (recommended) or n = 2.** Gen 2's serial rows already show rep spread of 0.1–0.27 W on sub-watt
   deltas (H.264 0.677 → 0.944) — comparable to the between-codec gaps. n = 2 will separate *devices*;
   it will not support any within-device *codec ordering* claim. n = 3 costs ~65 min more (§3).
4. **Wi-Fi control on Axis A (Leg N) — recommend skip.** Fire TV is Wi-Fi-only; GTV is Ethernet. CR-074
   already measured the network term on this rig (Wi-Fi vs Ethernet: GTV +0.21 W, Fire TV +0.1→0.35 W;
   `docs/netpath_2026-08-18/README.md`). Cite it and bracket the Axis A delta with it. Run Leg N (GTV on
   Wi-Fi, H.264 only, n = 2, ~12 min) only if the Axis A gap lands inside that bracket. Note tonight's
   cost: re-enabling Wi-Fi on GTV means updating its randomised wlan MAC in `rig.py` (now
   `de:17:af:66:eb:45`) so the follower can find it — and it drifted onto Wi-Fi once already today.

## 2. What already exists (roll in, don't repeat)

- **Batch `a9f06c58ab09`** (running, ~25 min left as of writing): Gen 2 and Gen 3, headless,
  `bbb_codecs_rt` × 2 + `loop_bbbiso_vp9` × 2 → **n = 2 for both Xiaomi across all four codecs.** Order
  was blocked (all Gen 2, then all Gen 3) — a mild time-drift confound; the n = 3 leg interleaves.
  Gen 2 rows so far (ΔW, 🟢 all): H.264 0.677 / 0.944 · HEVC 0.902 / 0.863 · AV1 0.759 / 0.895 · VP9 0.769 / 0.929.
- **Batch `7c634c396574`** (queued behind it): the **4-wide parallel probe** — one `bbb_codecs_rt` job,
  all four devices headless at once (~12 min). Pass criterion: each device's three ΔW within the serial
  rows' rep spread (≈ ±0.3 W) with 🟢 and PLAYING at end; Wi-Fi contention (three boxes streaming on the
  same AP) is the thing being tested. **If it passes, Leg H runs 4-wide and the schedule below shrinks ~4×.**
- Today's screen-mode smoke rows (Gen 2 / Gen 3, `loop_bbb_h264`, 30–60 s windows, `calibrate=false`): keep
  as onboarding evidence only, not campaign data.
- Condition note: "headless" tonight = **HDMI cable attached to the C2 but input not selected** for all
  four boxes (before today Fire TV and Xiaomi had no cable at all). Same condition for all four → fine,
  but it is a different condition from the pre-2026-09-02 Fire TV/Pi headless rows; say so if comparing.

## 3. Legs (in order)

### Leg 0 — pre-flight (no measurement, ~10 min with the owner)
- `/bench-preflight`: KLAP exclusivity (Tapo app closed), ambient normal, origin `:8123` serving, queue empty.
- Screen map per §1.1; verify with `curl -s :8000/decode/status.json | jq .monitor.hdmi_inputs`.
- All four `ready` on `/decode`; **never mains-cycle the Fire TV** (loses ADB auth — on-site re-accept).
  GTV: Ethernet at `.126`, **Wi-Fi off** (tonight's switch fault + MAC drift). Roku uncabled, `atv` parked.
- Just Player version per box (`adb shell dumpsys package com.brouken.player | grep versionName`) per §1.2.
- The Just Player cold-start "Choose a video to play" glitch (JOURNAL S73): a box's *first* launch after
  install may sit on the empty-state screen while decode runs behind it. All four have launched
  successfully since install; Leg S's marker head is the detector if it recurs.

### Leg 1 — characterise the two unmeasured boxes (CR-077, ~8 min each)
`python3 decode_bench/onboard_device.py --device xiaomi` then `--device xiaomi3` (defaults: 3 reps,
20 s hold, 90 s observe, 45 s boot settle). Replaces the `idle_w` / `expected_boot_s` / `boot_threshold_w`
**UNMEASURED guesses** in `rig.py` and tells us whether either needs Apple-TV-style per-device
`min_settle_s` / `min_idle_tolerance_w` (Gen 3's smoke-row idle guard did **not** settle: waited 30.9 s,
`settled: false`). Fire TV and GTV already have measured floors (1.8 W spiky / 1.0 W). Do not run this on
the Fire TV (it boots the box from the plug).

### Leg H — headless 4 × 4 matrix (the core)
Templates: `bbb_codecs_rt` (H.264 / HEVC / AV1, 150 s each, one job) + `loop_bbbiso_vp9` (150 s, default
window). Mode `headless`, `calibrate: false`, one new `batch_id` for the whole leg.
- Fire TV + GTV: reps 1–2, **interleaved** (rep-major: firestick, gtv, firestick, gtv).
- If n = 3: rep 3 for all four, interleaved (xiaomi, xiaomi3, firestick, gtv).
- Serial cost: ~16 min per device-rep → 64 min (reps 1–2) + 64 min (rep 3) ≈ **2.1 h**.
  If the §2 parallel probe passes: submit each rep as one 4-device job → ≈ **35 min total**.

Payload shape (one call per template per device-rep, or one call with all four devices if 4-wide):
```
POST /decode/run {"template":"bbb_codecs_rt","mode":"headless","devices":["firestick"],
                  "calibrate":false,"batch_id":"<LEG_H_ID>"}
POST /decode/run {"template":"loop_bbbiso_vp9","mode":"headless","devices":["firestick"],
                  "calibrate":false,"batch_id":"<LEG_H_ID>"}
```

### Leg S — screen mode with the black·white·black marker head (liveness + attributional panel term)
One row per box × codec, **n = 1**, mode `screen`, **`calibrate: true`** (that is what enables the marker
head and `segment_marker_trace`; today's smoke rows used `false`, so they have no segmentation).
Screen mode is exclusive → strictly serial, one new `batch_id`. Templates: the same
`bbb_codecs_rt` + `loop_bbbiso_vp9` (screen mode substitutes the marker-headed clip variants
automatically; window = 150 + 15 s head; VP9 marker rows work since the S72 container fix).
Cost ≈ 4.5 min per row → 16 rows ≈ **1.2 h**.
What it proves: the 5 s black · 5 s white · 5 s black head must appear as a swing on the **C2's Lab-E
meter** (`raw_context_w` → `screen_marker_segments.marker_swing_w`). That is end-to-end proof that the
decoded frames of *that* box reach the panel through *its* HDMI after tonight's re-cabling — and it is
the one check that catches the Just Player empty-state glitch (PLAYING + decoders allocated + **no swing**).
Also yields the panel's picture term per box (`context_delta_w`), reported separately, never summed into
the device number.

### Leg N — optional, per §1.4.

## 4. Gates and discards (per row, before any number is believed)
- Discard when `alive_at_window_end` is False **and** `playback_state_at_end` ≠ PLAYING (Fire TV's known
  false-negative on the first is instrumented — the retried end-state is authoritative).
- Discard Leg S rows with no credible marker swing (`screen_marker_segments` missing or
  `marker_swing_w` < 5 W — the white field on this OLED is a ~20 W step).
- Keep but flag rows whose `idle_guard.settled` is False; the row's own 🟢/🟡/🔴 already carries the
  baseline-noise penalty. Two such rows on one box → stop and re-tune that box's idle guard (Leg 1 data).
- Discards go to the envelope's `discarded[]` with the reason — visible provenance, never silently dropped.
- Contamination screen per `/decode-campaign` §3: mid-window screenshot (Gen 2's come back blank white —
  its hardware video plane is invisible to `screencap`; not a failure) and logcat decoder names.

## 5. Analysis (what to compute, what to write)
- Per cell (box × codec): mean ΔW over reps ± 95 % CI (from the per-row CIs and the rep spread), total W
  (idle + Δ), n, worst traffic light. Two tables, both headed "realtime playback, 1080p matched-VMAF ~92".
- **Decoder provenance table 4 × 4** from `decoders_allocated` (Gen 2 = `OMX.amlogic.*` now caught; Gen 3 /
  GTV = `c2.*`; **Fire TV = "n/a — Fire OS logs no decoder names"**, so its hw/sw path per codec is
  inferred from the ΔW signature only — state that).
- Axis A per codec: GTV − Fire TV (ΔW and total), bracketed by the CR-074 network term. Axis B per codec:
  Gen 3 − Gen 2. Parallel-vs-serial: per box, parallel ΔW vs serial mean — inside the rep spread or not.
- Idle floors from Leg 1 (Xiaomi) and `rig.py` (Fire TV, GTV), each with the method that produced it.
- Output: `docs/intra_content_sync_2026-09-03.md` (tables + caveats + affirmations). Findings only through
  `/finding-draft`, only for claims that clear the bar (n ≥ 3, CI excludes zero, regime and operating
  point named). Publication rule applies: a few affirmations, Tania checks, critics credited.

## 6. Caveats to carry (state up front, not in a footnote)
Wi-Fi vs Ethernet on Axis A (CR-074 bracket) · Fire TV has no decoder provenance · Fire TV device-total
includes its own radio (every box but GTV does tonight) · headless = cabled-but-unselected ·
Just Player 0.212-legacy on GTV unless aligned (§1.2) · Xiaomi n = 2 rows were blocked-order · Xiaomi
idle floors are guesses until Leg 1 · the Just Player cold-start glitch (marker-detected in Leg S only) ·
one panel, one player, one bitrate rung per codec — this is not a ladder and not a service app.

## 7. Time budget (serial worst case, after batch `a9f06c58ab09` finishes)
Leg 0 10 min · Leg 1 16 min · Leg H 2.1 h (n = 3) · Leg S 1.2 h → **≈ 3.6 h**; 4-wide Leg H → ≈ 1.9 h.
Idle auto-off is held per row by `bench.py` (`RIG_HOLD_FILE`); no operator needed between legs.
