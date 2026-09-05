# The HDMI sink is a measurement variable — decode-rig sink campaign, 2026-09-05

**Status:** primary data, n≥3 on every headline cell (WattLab call bar, 2026-09-03).
**Rig:** GoS1 decode bench, ten devices. **Content:** BBB 1080p60 matched-VMAF family, 150 s realtime windows.
**Batches:** `bef05e0905` (pre-swap, warm), `af7e050905` (post-swap), `aaaa050901` (night, panel lit, 135 rows),
`eeee050901` (VP9, 27 rows). Anchors from S73 `85c22b801df6` (panel) and `ff44e9cbd81f` (no sink).

## 0. What this settles

S73 (2026-09-03) found that a streaming box with no HDMI cable plays measurably cheaper than the same box
with one, and called headless rows "a different regime" that must not pool with screen-attached rows. HDMI
dummy plugs were fitted on 2026-09-05 to close that gap. They do close it — but only under a condition
nobody had stated, and the condition is not "a sink is present".

1. **A dummy plug at *matched output resolution* reproduces the panel's decode increment.** Two Amlogic
   boxes: ΔW agrees within **0.006–0.025 W** on the three same-session codecs (H.264/HEVC/AV1) and within
   **0.056 W** once cross-night VP9 is included. What remains is a small constant offset.
2. **At *mismatched* resolution the substitution fails, and how badly is silicon-dependent.** The dummies
   negotiate 1080p on Android 11 boxes and 4K on Android 14 boxes. On MediaTek that mismatch costs
   **0.54 W** and nearly half the decode increment; on Amlogic it costs **0.07 W** and *nothing* of the
   increment.
3. **No sink at all is a third, worse regime** — as S73 said, but the ladder is now resolved.
4. **A TV going to standby is not a sink event at all.** It is a CEC `<Standby>` broadcast, and three boxes
   answer it three different ways. One of them sleeps and never wakes.

The practical rule: **declare the output mode, not just the presence of a sink.**

## 1. Wiring

Four boxes on the LG C2's real inputs, four on HDMI dummy/EDID plugs, one bare as the control.

| box | silicon | sink during this campaign | negotiated mode |
|---|---|---|---|
| Fire TV 4K | MediaTek MT8696 | panel HDMI_4 (was dummy for `bef05e0905`) | 3840×2160 |
| Google TV Streamer | MediaTek MT8696 | panel HDMI_1 | 3840×2160 |
| Roku Express 4K | Realtek RTD1315 | panel HDMI_3 | — |
| Apple TV 4K | Apple A10X | panel HDMI_2 | — |
| Xiaomi Gen 2 | Amlogic S905X4 (Android 11) | dummy | **1920×1080** |
| Xiaomi Gen 3 | Amlogic s7d (Android 14) | dummy (was panel HDMI_4) | **3840×2160** |
| Bbox 4K | Marvell Berlin (Android 11) | dummy | **1920×1080** |
| Pi 400 | BCM2711 | dummy (pure decode, `-f null`) | 1920×1080 |
| Pi 5 | BCM2712 | **none** — control | — |

Dummies are FUE `4k60-1080@240`, EDID verified by direct read: CTA VIC 97 (3840×2160p60) plus an
HDMI-Forum block declaring 600 MHz. **They are 4K-capable; the Android 11 boxes simply do not select it.**
That is a box-side mode choice, not a dummy limitation, and not a cable-adapter limitation (§5).

## 2. The sink ladder (H.264, device-total W during playback)

| box | no sink | dummy | panel | dummy→panel |
|---|---|---|---|---|
| **Fire TV** (MT8696, dummy@1080p) | 1.139 (n=1) | 1.410 ±0.010 (n=3) | **1.945 ±0.015 (n=11)** | **−0.535 W** |
| **Xiaomi Gen 2** (S905X4, dummy@1080p) | 2.579 (n=1) | 2.958 ±0.010 (n=11) | 3.030 ±0.009 (n=3) | −0.072 W |
| **Xiaomi Gen 3** (s7d, dummy@**4K**) | — | 2.625 ±0.070 (n=8) | 2.779 ±0.055 (n=6) | −0.154 W |

And the same thing as the **decode increment** (ΔW over each box's own settled baseline), which is what a
codec or bitrate comparison actually rests on:

| box | ΔW no sink | ΔW dummy | ΔW panel |
|---|---|---|---|
| Fire TV | +0.140 | +0.273 | **+0.489** |
| Xiaomi Gen 2 | +0.680 | **+0.948** | **+0.948** |
| Xiaomi Gen 3 | — | +0.832 | +0.857 |

The Fire TV's decode increment **more than triples** across the ladder. That is the finding with teeth: it
is not an offset you can subtract, it changes the quantity being compared.

## 3. Matched resolution — the substitution works, across codecs

Both Amlogic boxes, dummy vs panel, per codec:

| box | codec | ΔW dummy | ΔW panel | difference |
|---|---|---|---|---|
| Gen 3 (both 4K) | H.264 | +0.832 | +0.857 | +0.025 |
| | HEVC | +0.565 | +0.559 | −0.006 |
| | AV1 | +0.491 | +0.508 | +0.017 |
| | VP9 † | +0.537 | +0.593 | −0.056 |
| Gen 2 (dummy 1080p vs panel 4K) | H.264 | +0.948 | +0.948 | **0.000** |
| | HEVC | +0.885 | +0.907 | +0.022 |
| | AV1 | +0.831 | +0.811 | −0.020 |
| | VP9 † | +0.832 | +0.880 | −0.048 |

† VP9's panel anchor is the S73 batch of 2026-09-03, i.e. a **cross-night** comparison; H.264/HEVC/AV1
panel rows are same-session. Read the three same-session codecs as the clean result (**≤25 mW**) and VP9
as the looser bound (**≤56 mW**) that carries three days of drift with it. The cross-night control is
reassuring on its own: the Fire TV's panel VP9 read 1.937 W against 1.924 W in S73, and the GTV 2.043 vs
2.074 W — so the rig reproduces itself to ~0.03 W across three days.

Gen 3 is the clean matched-resolution case and it agrees to within 25 mW on the three same-session codecs. Gen 2 is the
*mismatched* case that nonetheless agrees — because this silicon does not pay for 4K output at all. That
is the same asymmetry S73 measured for 4K *content* ("4K costs the MT8696 +0.37 W, Amlogic ~0"), arrived at
from a completely independent direction.

## 4. Silicon decides the cost of a mismatch

| box | silicon | dummy mode vs panel mode | playback gap | ΔW gap |
|---|---|---|---|---|
| Fire TV | MediaTek MT8696 | 1080p vs 4K | **−0.535 W** | **−0.216 W** |
| Xiaomi Gen 2 | Amlogic S905X4 | 1080p vs 4K | −0.072 W | 0.000 W |
| Xiaomi Gen 3 | Amlogic s7d | 4K vs 4K | −0.154 W | −0.025 W |

MediaTek pays for driving 4K; Amlogic does not. A lab that standardises on 1080p dummies and compares a
Fire TV against a Xiaomi is therefore not comparing decoders — it is comparing display pipelines, and the
bias is one-sided.

## 5. The cheap couplers are exonerated

The Fire TV and Pi 400 are male-ended and need female-female couplers to accept a dummy; the boxes with
sockets take one directly. The two coupler users were also the two anomalous boxes, so the couplers were
the obvious suspect. They are not the cause:

- The Pi 400's EDID reads cleanly **through** its coupler — 256 valid bytes, manufacturer FUE, product
  `4k60-1080@240`, CTA VIC 97 present. DDC is undamaged.
- The Fire TV sees **both 4K60 modes** through its coupler and still selects 1080p.
- **Xiaomi Gen 2 has no coupler and gets 1080p; Xiaomi Gen 3 has no coupler and gets 4K.** The split tracks
  Android version, not the connector.
- The Pi 400's missing 4K is a Pi firmware matter — `hdmi_enable_4kp60` is absent from its `config.txt`.

Untested and still open: whether these couplers carry a real 594 MHz TMDS signal, since nothing has driven
4K through one. Certified 48 Gbps parts are on order to close it.

## 6. Panel standby is a CEC event, not a sink event

An earlier reading in this session suggested LG Always-Ready standby deasserts HPD. **It does not**, and
the claim is retracted (commit `c52c9b2`). HDMI 1.3 §8.5 requires a sink to keep HPD asserted "even if the
Sink is powered-off or in standby", and logcat across the transition shows what really happens: the C2
broadcasts **CEC `<Standby>` (0x36 → 0x0F)**, and the boxes diverge.

| box | log | result | power |
|---|---|---|---|
| Google TV | `[CecMsgProcessor] handleStandby` | **Asleep**, Display OFF | 1.16 → 0.94 W |
| Fire TV | `isPowerOffChangerMessage: false` | stays **Awake**, Display ON | 1.46 → 1.15 W |
| Roku | — | unaffected | 1.77 → 1.78 W |
| Gen 3 (dummy) | — | unaffected — control | 1.79 → 1.78 W |

Two consequences:

- **The Google TV did not wake when the panel woke** (still asleep, 0.88 W, a minute later). Any overnight
  campaign in which the panel sleeps leaves that box silently asleep. This is a better explanation for a
  class of failed overnight rows than any sink hypothesis.
- **Turning CEC off in Android settings does not prevent this.** The GTV logged `mOptionEnableCec=0` with a
  null framework callback — yet `mCecHalAlwaysOn=1` and the vendor HAL obeyed Standby anyway.

The Fire TV's residual −0.31 W with its display still ON is **unexplained**. It is not established as sink
loss and should not be reported as such.

## 7. Systematics carried

- **Dummy LED.** These dummies have an indicator LED, powered from HDMI pin 18 (+5 V) — supplied by the
  *source*, so it sits inside the box's measured wall power. HDMI 1.3 §4.2.7 caps a sink at 50 mA (0.25 W);
  a current-limited indicator is realistically 10–50 mW. It is a systematic, always in the same direction,
  and it works *against* the dummy-vs-panel gaps reported here — the true offsets are if anything slightly
  larger. It also means the Pi 400's +0.19 W is an upper bound on scanout, not a measurement of it.
- **First row after a cold boot is unusable.** Every box's baseline is elevated for the first row after
  power-on, including untouched controls (Pi 5 +0.4 W, GTV +0.56 W). Warm reps land back on anchor. Discard
  the first row or warm the rig.
- **Apple TV baselines only.** Its playback watts are tight (±0.04–0.12) but its tvOS home-screen baseline
  swings ±1.5–2.0 W, so ΔW on that box is not usable. Absolute playback watts are the comparable lens.
- **Bbox is unresolvable.** Its 6.2–6.7 W idle drift exceeds the sink term. Its rows this campaign are the
  tightest ever taken on it (sd 0.03–0.15) and still cannot separate a sink effect.
- Pi rows are pure decode (`-f null`), no display path; a dummy adds a constant offset and leaves the
  decode increment unchanged (ΔW +1.475 vs the seven-week anchor of +1.48–1.50).

## 8. Against the published literature

A literature sweep was run alongside the measurements. Positioning, honestly:

**What appears to be new**
- **No published measurement varies HDMI sink state as the independent variable.** Across standards bodies,
  press, academic and NGO sources, device power is measured with the sink state fixed or — far more often —
  simply unstated. The ladder in §2 has no comparator we could find.
- **The resolution × silicon interaction on the source side.** Prior art (Carbon Trust, DIMPACT, IEA,
  Netflix) treats a viewing device as a single flat wattage; DIMPACT's own methodology says the
  display/peripheral interaction "has not been confirmed via systematic testing".
- **A vendor CEC HAL obeying `<Standby>` while CEC is disabled in settings.** Documented nowhere we found.
- **The two major test regimes contradict each other on the sink and neither pins its state.** ENERGY STAR
  for Set-top Boxes §4.2(E): "If the UUT supports connection to a Display Device, **it shall be connected to
  a Display Device**". EU Code of Conduct v9 §9.1(A): "**there shall be no external loads connected to the
  EUT**, unless these are required for the EUT to function." Neither specifies whether that display is on,
  in standby, or on another input during the power measurement.

**What we have confirmed rather than discovered**
- HPD tells a source nothing about sink state. HDMI 1.3 §8.5: it "does not indicate whether or not the Sink
  is powered or whether or not the HDMI input on the Sink is selected or active." Our data agrees.
- **"Headless" does not mean "no display work."** A Raspberry Pi engineer's answer on `userland` #447 is the
  cleanest statement of the mechanism: with no cable attached, killing the HDMI PHY saved nothing
  measurable, while `tvservice -o` — which "disables the whole display pipeline, including clocks, the
  Hardware Video Scaler, the Pixel Valve, fetches of display layers from sdram" — saved ~10%. The pipeline
  runs into a void unless something tears it down. Our Pi 400 offset is consistent.
- TVs going to standby disturb connected sources. Widely reported by Kodi/OSMC users, and the ecosystem's
  standard remedies exist precisely for it: Raspberry Pi's `hdmi_force_hotplug` ("pretends that the HDMI
  hotplug signal is asserted"), OSMC's user-facing "Lock HPD", and EDID emulators.
- Manufacturer discretion over `<Standby>` is spec-sanctioned. HDMI 1.3 CEC 13.3.2: "It is also the
  manufacturer's decision if a source device goes into standby when it receives a system (broadcast)
  `<Standby>` message." Our three-way split is exactly what the spec permits — not a set of bugs.

## 9. Open — including one the brief asked for and we cannot yet answer

- **Unplugged at the TV end vs at the box end.** Asked directly; **not tested**, and the literature does not
  answer it either. The topology predicts a difference: with the cable attached to the source but open at
  the TV, HPD (driven by the sink) deasserts while the source still drives +5 V into an open cable whose
  TMDS pairs are terminated only by their own impedance. Needs ~2 minutes of on-site cable work; designed
  and ready.
- **The Fire TV's −0.31 W with the panel in standby and its display still ON.**
- **Whether a certified 48 Gbps coupler lets the Fire TV take 4K from a dummy** — parts on order.
- Whether the Fire TV's 1080p choice is its own *Video Resolution* setting rather than EDID negotiation.
- The Bbox's sink term remains below its own noise floor.

## 10. Where the data lives

Batches on `/decode/batches`: `bef05e0905`, `af7e050905`, `aaaa050901` (135 rows), `eeee050901`.
Rows under `results/decode/2026-09-05_*.json`. Every row now carries `sink`
(`panel:HDMI_n` | `dummy` | `none`), `sink_wiring` and `panel_awake` — group on `sink`, never on
`hdmi_input`, which answers only "cabled to the shared panel". Provenance shipped in `9478c56`; the
panel-state derivation in `f9142dc` was retracted in `c52c9b2` (§6).
