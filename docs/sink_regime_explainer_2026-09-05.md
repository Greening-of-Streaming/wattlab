# What is the TV doing while you measure the box?

*OWL / WattLab, 6 September 2026. Device layer only (streaming boxes on a lab bench).
Network, CDN and data-centre impacts excluded. Energy figures only — no carbon claims.*

## The question nobody writes down

Measuring how much electricity a streaming box uses looks simple. Put it on a metered socket, play a
video, read the meter. Every published estimate of streaming's device-side energy rests on numbers
gathered roughly that way.

But a streaming box has an HDMI cable coming out of it, and that cable has to go somewhere. Into a
television that is switched on? A television in standby? A television showing a different input? Or
nowhere at all?

We assumed this was a detail. It is not. **It changes the answer by up to 40%.**

## What we found

We measured the same boxes playing the same video, changing only what was on the end of the HDMI cable.
Three conditions: a real television, a small plug that pretends to be a television (an "EDID emulator",
about the price of a coffee), and nothing at all.

On an Amazon Fire TV Stick, playing identical content:

- plugged into a **real television**: 1.95 W
- plugged into a **fake television**: 1.41 W
- plugged into **nothing**: 1.14 W

Same box. Same file. Same decoder. The only thing that changed was what the cable was connected to.

Worse for anyone doing comparisons: the figure most studies actually care about is not the total, but the
*extra* power caused by playing the video — the box's decoding cost. On this box that extra cost was
**+0.49 W** with a real TV and **+0.14 W** with nothing attached. It more than tripled. That is not a
number you can quietly correct for afterwards; it is a different measurement.

## Why it happens

A streaming box is doing two jobs at once. It decodes the video — the part everyone means to measure —
and it also *drives a picture down the cable*, which means running a display pipeline and an HDMI
transmitter. Take away the television and some of that second job stops. You are still measuring
something real; you are just no longer measuring the thing you meant to.

The pipeline does not politely shut itself off, either. A Raspberry Pi engineer put it precisely when a
user assumed it did: turning off the HDMI output alone saved nothing measurable, while shutting down the
whole display pipeline — "clocks, the Hardware Video Scaler, the Pixel Valve, fetches of display layers
from sdram" — saved about 10% of the board's power. Unless something explicitly tears it down, the box
keeps composing a picture for an audience that isn't there.

## The part that surprised us

We expected the fake television to be a poor substitute. It isn't — **provided it asks for the same
picture as the real one.**

Where the fake screen requested the same resolution as the TV (4K), it reproduced the real television's
decoding cost to within **0.025 W across three different codecs** measured the same night — and within
0.056 W on a fourth measured three days apart, which is about what this bench drifts over three days
anyway. That is as close to identical as we can resolve. A €10 plug can stand in for a television.

Where it requested a *lower* resolution than the TV, the substitution broke — and here is the twist that
matters for anyone comparing devices: **how badly it broke depended on the chip inside.**

- On MediaTek silicon, dropping the output from 4K to 1080p cost **0.54 W**.
- On Amlogic silicon, the same drop cost **0.07 W** — and left the decoding cost completely unchanged.

So a lab that standardises on 1080p fake screens and then compares a MediaTek box against an Amlogic box
is not comparing decoders. It is comparing display pipelines, and the bias runs one way. Two labs could
follow the same written protocol, use the same equipment, and publish different rankings of the same
hardware.

## And switching the TV off isn't what you think

We also tested what happens when the television drops into standby mid-measurement — the kind of thing
that happens overnight in an unattended lab.

It is not a cable event at all. The television sends a command down the HDMI wire telling everything
attached to go to sleep. Three boxes received the identical command and did three different things: one
went to sleep and **never woke up again**, one ignored it but still lost power, and one carried on as if
nothing had happened.

The specification permits all three. It leaves the response explicitly to the manufacturer. So this is
not a bug anyone should fix — it is a documented freedom that quietly makes overnight measurements
unrepeatable across brands.

One detail is worth flagging to anyone building a test rig: on one box, this happened **even though HDMI
control was switched off in its settings**. The setting was off; the chip-level software obeyed anyway.

## What the standards say

We went looking for the rule we had evidently broken. There isn't one — there are two, and they
contradict each other.

- **ENERGY STAR** for set-top boxes requires that "if the UUT supports connection to a Display Device, it
  shall be connected to a Display Device."
- The **EU Code of Conduct on Digital TV Service Systems** requires that "there shall be no external loads
  connected to the EUT, unless these are required for the EUT to function."

One says attach a television. The other, read plainly, says don't. And **neither one specifies whether
that television should be switched on**, in standby, or showing another input while you measure.

We could not find a single published study — standards body, academic, industry or NGO — that treats the
state of the screen as something to control and report. In the major streaming-footprint studies, the
viewing device is a single flat number taken from a product database. DIMPACT's own published methodology
is candid about the gap, noting that the interaction between a television and an attached streaming box
"has not been confirmed via systematic testing."

That is not a criticism of those studies. At the scale they work at — national electricity totals — this
effect is far too small to matter. It matters at *our* scale: when the question is which codec, which
box, or which encoding ladder is cheaper, an uncontrolled half-watt is the whole answer.

## What we would say with confidence

Keeping to what the data supports, with sample sizes attached:

1. **The state of the HDMI connection is a measurement variable and belongs in every method statement.**
   Across three conditions on one box, playback power moved 1.14 → 1.41 → 1.95 W (n=1, n=3, n=11).
2. **A dummy HDMI plug is a sound substitute for a television, if — and only if — it negotiates the same
   output mode.** Matched at 4K, the decoding cost agreed with a real television within 0.025 W on three
   codecs measured the same night (n=5–8 per cell), and within 0.056 W on a fourth measured three days
   apart (n=3 vs n=12).
3. **The cost of getting that wrong is chip-dependent**: 0.54 W on MediaTek, 0.07 W on Amlogic (n=3–11).
   Cross-device comparisons are the ones at risk.
4. **What we cannot yet tell you:** whether unplugging at the television end differs from unplugging at
   the box end. It is a fair question, the electrical topology suggests it might, and neither our bench
   nor the published literature has answered it. That test is designed and next.

Our own numbers before today's work were affected by this. Some earlier rows were taken without a screen
attached; they measure something real, but not the same thing as our screen-attached rows, and they are
now labelled accordingly rather than quietly pooled.

## The practical ask

If you publish device-side energy figures, state what was on the end of the HDMI cable and what
resolution it negotiated. Two lines in a method statement. It costs nothing, and without it a number
cannot be reproduced — including by you.

---

*Full method, per-codec tables, confidence intervals and the raw result files:
`docs/hdmi_sink_regime_2026-09-05.md`. Measurements are device-layer only and were taken on a
ten-device bench at Greening of Streaming's WattLab. We are glad to be corrected — the underlying
result files are available.*
