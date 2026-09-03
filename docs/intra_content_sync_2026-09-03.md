# Intra-content decode power on four set-top boxes (2026-09-03, overnight)

**Status: DRAFT, overnight data collection finished 03:59 (03 Sep). Owner review
before anything leaves the lab. What ran, what did not, and why: §7.**

Regime on every row here: realtime playback (decode + present), 1080p unless
stated, LAN HTTP from GoS1's origin, Just Player 0.196 (GTV 0.212-legacy),
one Tapo P110 per box at 1 s, protocol v3 idle guard, `confidence.py` per row.

---

## 1. What this session set out to do

Until now a decode row produced **one number per box per codec**: the mean ΔW
over a window. The question this session opened is finer — does a box's draw
move *within* the clip, and do different boxes respond to the same content the
same way? Answering it needs every power sample tagged with the **content time**
the box was decoding, which no driver recorded.

Two orthogonal comparisons are on the bench:

| Axis | Held constant | Varies | Pair |
|---|---|---|---|
| **A — silicon** | MediaTek MT8696 | OS/vendor stack, form factor | Fire TV Stick 4K vs Google TV Streamer |
| **B — vendor** | Xiaomi, Google TV, box form factor | Amlogic generation (sc2/OMX vs s7d/Codec2) | Xiaomi TV Box Gen 2 vs Gen 3 |

## 2. How the boxes are synchronised

Four mechanisms, in order of how much they actually matter:

1. **Per-box content clock (the load-bearing one).** Every 2 s each box reports
   its own player position. On Android/Fire OS that is the media session's
   `position`, which media3 **freezes between state changes** — the Gen 2 read
   `position=0, updated=77188` 45 minutes into playback — so the real clock is
   `position + (uptime_now − updated) × speed`, with the box's `/proc/uptime`
   read in the *same* adb call to keep each poll self-consistent. Roku reports
   position directly over ECP. Power samples are binned by **content** time,
   never wall time.
2. **A pre-built looped clip.** `loopmarked_xN_<clip>` = N × [5 s black · 5 s
   white · 5 s black + content], concatenated with stream copy (never
   re-encoded — re-encoding would change the very decode workload being
   measured). One monotonic timeline for the whole run; player-side looping
   would reset position each lap and hide the wrap.
3. **A cross-process start barrier.** Each device is a separate `bench.py`
   process, so they meet at a file rendezvous: after its baseline each writes
   `<name>.<run>.ready` (atomic tmp+rename, epoch inside), waits for its peers,
   and every process independently computes `start_at = max(ready) + 3 s`.
4. **The marker head as physical ground truth.** On whichever box holds the
   shared C2 panel, each loop's white field is a hard electrical timestamp on
   the panel's own meter, predicted from the software clock and looked for in
   the trace (`decode_sync.marker_edges_from_clock`).

**A live HLS stream was considered and rejected**: every player picks its own
live-edge latency, so inter-box skew would be larger and less stable than a
rendezvous-launched VOD, and TS/fMP4 segmenting would change the delivery
regime versus every existing row (AV1/VP9 would need fMP4 — a second variable).

### Measured sync quality

- Two Xiaomi boxes ran **0.35 s apart in content time after 35 minutes** of
  playback (2116.33 s vs 2115.98 s).
- Start barrier: all processes computed the identical `start_at`; waits 14–19 s.
- Clock coverage: 1055/1055 and 1046/1046 polls PLAYING, max gap 2.2 s,
  **0 unaligned power samples** on both.
- **Software clock vs the physical panel: median residual +1.05 s (MAD 0.07 s)
  on the first run, +1.21 s (MAD 0.13 s) on the re-run** — Fire TV, 4 and 5
  loops respectively, every white-field step found within 1.0–1.3 s of where
  the clock said it would be, with a 30–33 W panel swing each time. Loop 0 is
  excluded by rule: its head sits inside the launch transient and reads +11 s
  on both runs. The offset is real (render pipeline + the meter's own ~1.3 s
  refresh) but *constant* — which is what makes the clock usable as a
  content-time reference.
- Launch skew after the barrier: 1.3 s (run 1) and 4.6 s (run 2, the GTV
  reaches PLAYING faster than the Wi-Fi-buffering stick). Irrelevant by
  construction — binning is by content clock — but recorded per row
  (`playing_epoch`).

Sync is therefore ~1 s, and the instrument's own resolution (P110 refresh
~1.3–1.6 s, polled at 1 s) is the floor. Sub-second alignment would buy nothing.

## 3. Result: is intra-content structure detectable?

From `loop_bbb_h264_sync` (job `ebce47ca`, 6 loops of BBB H.264 1080p, three
boxes clean). Two statistics, computed by `decode_bench/content_profile.py`:

- **Per-box SNR** = between-bin SD ÷ mean within-bin (loop-to-loop) SD. Above 1
  means a box resolves content structure from its own trace.
- **Cross-device r** = correlation between two boxes' per-bin profiles. The
  boxes are independent hardware on independent meters, so agreement about
  *which* parts of the clip cost more cannot come from noise.

| bin | Gen 2 SNR | Gen 3 SNR | Fire TV SNR | Gen2~Gen3 | Gen2~Fire | Gen3~Fire |
|---|---|---|---|---|---|---|
| 5 s | 0.72 | 0.74 | 0.85 | +0.52 (t=5.1) | +0.37 (t=3.3) | +0.60 (t=6.3) |
| 10 s | 0.76 | 0.69 | 0.91 | +0.64 (t=4.9) | +0.56 (t=3.9) | +0.69 (t=5.5) |
| **20 s** | 0.69 | 0.71 | 0.86 | **+0.79 (t=5.1)** | +0.60 (t=3.0) | **+0.79 (t=5.1)** |
| 30 s | 0.73 | 0.76 | 1.19 | +0.81 (t=4.3) | +0.62 (t=2.5) | +0.79 (t=4.1) |
| 60 s | 0.58 | 0.59 | 1.08 | +0.57 (t=1.4) | +0.54 (t=1.3) | +0.74 (t=2.2) |

**Reading:** no single box resolves intra-content structure from its own trace
at n=6 (SNR < 1 nearly everywhere) — yet all three agree strongly on the shape,
r ≈ 0.8 at 20–30 s bins with t ≈ 5. Three independent boxes and three
independent meters do not agree by accident. So:

> Intra-content decode-power structure on this content is **real and
> measurable, but small** — below one box's own noise floor at n=6, and
> recoverable through cross-device agreement. Optimal granularity ≈ 20–30 s.

**No thermal drift to confound it:** per-loop content means are flat on all
three boxes (slope −0.005…+0.004 W/loop, every CI spanning zero; first loop
within 0.011 W of the rest). The loops can be pooled as replicates.

### Replication — the four-box re-run (job `987f428d`, GTV on Wi-Fi)

All four boxes clean (clocks 1045–1055/1045–1055, 0 unaligned samples). Six
device pairs, all significant at 5 s bins (t = 4.2–6.8), r up to **+0.82** at
20 s (Gen 2 ~ GTV). Note **same silicon does not mean a closer profile**: the
two MT8696 boxes correlate at 0.61–0.74, while Gen 2 ~ GTV (different silicon)
reaches 0.82 — the shape is a property of the *content*, not a silicon
signature.

**Test–retest, same box, two runs 1.5 h apart** (72 shared content bins):
Gen 2 r = +0.67 (t = 7.5), Gen 3 r = +0.69 (t = 8.0), Fire TV r = +0.48
(t = 4.5); mean content power reproduces to within 0.02 W on all three
(2.945 vs 2.927, 2.511 vs 2.503, 1.827 vs 1.848 W). The per-bin profile is
reproducible — it belongs to the content, not to the night.

With six clean loops the Gen 2 box alone now clears SNR = 1 at 10–30 s bins
(1.01–1.31); the other three remain below 1 on their own.

The method also passes a **positive control**: the black/white/black marker head
reads *lower* than content on every box (Gen 2 −0.118 ±0.062 W, Gen 3 −0.063
±0.027 W, Fire TV −0.075 ±0.048 W). Near-zero-entropy frames are cheaper to
decode, exactly as expected — and this is an independent confirmation that the
content clock is aligned, since a misaligned clock would smear that dip away.

## 3b. What the profile tracks — content descriptors (first look, H.264 1080p)

Per-second descriptors of the *source* clip (`decode_bench/content_descriptors.py`):
delivered **bits**, **motion** (frame-difference energy), **edge** (Sobel energy
= spatial detail/texture), **luma** (mean Y), on the same content-bin grid as
the power profiles. Job `ebce47ca`, 72 content bins at 5 s, n=6 loops.

Sanity check that the cross-codec and cross-resolution runs compare like with
like: the picture-side descriptors of the H.264 6-min, HEVC 6-min and 4K
2-min clips agree (motion 1.31 / 1.30 / 1.28, edge 38.5 / 38.6 / 38.4, luma
135.4 / 135.3 / 135.3) — three encodes of the same source, differing only in
the bitstream. The HDR clip is different content entirely (luma 244, edge 43).

First fact about the corpus: the encode is **near-constant bitrate** — 7.67 to
8.14 Mbps across every 20 s bin. Whatever the boxes agree on, it is not the
number of bits arriving. Bits are not a usable "hardness" descriptor for this
corpus (the iso-bitrate family is flatter still); testing bitrate sensitivity
would need VBR content, which is a note for any future SD/4K ladder design.

Univariate r (t) and slope, content bins, 5 s:

| box | edge (texture) | motion | luma | bits |
|---|---|---|---|---|
| Gen 2 (sc2, OMX) | +0.19 (1.6) · +0.0006±0.0008 W/u | −0.37 (−3.3) | −0.19 (−1.6) | +0.28 (2.5) |
| Gen 3 (s7d, Codec2) | **+0.61 (6.4) · +0.0014±0.0004 W/u** | −0.29 (−2.6) | **−0.52 (−5.1)** | +0.06 |
| Fire TV (MT8696) | **+0.40 (3.7) · +0.0013±0.0007 W/u** | −0.10 | **−0.45 (−4.3)** | +0.18 |

Joint fit, standardised betas (sd of W per sd of descriptor; descriptors are
collinear on real content — motion blur lowers edge energy, BBB's bright skies
are flat):

| box | edge | motion | luma | bits | R² (5 s / 20 s bins) |
|---|---|---|---|---|---|
| Gen 2 | +0.22 | −0.31 | +0.01 | +0.26 | 0.23 / 0.29 |
| Gen 3 | **+0.53** | −0.22 | −0.13 | +0.11 | **0.46 / 0.58** |
| Fire TV | +0.25 | +0.01 | −0.30 | +0.23 | 0.27 / 0.32 |

**Reading (hypothesis, one content, n=6):** the variable part of decode power
tracks **spatial texture**, not motion — at a fixed bit budget, high-motion
scenes are *cheaper* (the encoder spends bits on prediction rather than
residual; fewer coefficients to reconstruct and filter). The residual
reconstruction / in-loop filtering path is the part of the chain that flexes.
And it flexes **most on the newest silicon**: content descriptors explain about
half of Gen 3's bin-to-bin variation (R² 0.46–0.58, steepest edge slope) and
only a quarter of Gen 2's (0.23–0.29, edge slope not significant) — consistent
with a legacy fixed-function/fixed-clock decoder (OMX, sc2) running flat versus
a newer block that idles harder on easy pictures. Fire TV sits between. The
luma term is ambiguous (a real dark-scene cost on the box's own meter, or just
BBB's flat bright skies standing in for "low edge") and needs other content.

**Replication verdict (H.264 re-run, four boxes):** the *driver* replicates —
edge (texture) is the largest positive standardised beta on all four boxes
(+0.31, +0.31, +0.32, +0.41) and motion is negative on all four (−0.19 to
−0.31). Two things did **not** replicate and are withdrawn: the luma term
flips sign between runs and boxes (a collinearity artefact of BBB's flat
bright skies, as suspected), and the "newest silicon flexes most" ranking —
Gen 3's R² fell from 0.46 to 0.35 while Gen 2's rose from 0.23 to 0.28; all
four now sit at R² 0.20–0.35. So: **spatial texture is what the variable part
of decode power tracks, on every box; which box tracks it hardest is not
resolved at n=6.** Still to come: the same content in HEVC (larger transforms,
SAO), the same first 120 s at 4K, and the bitrate ladder — where bits finally
become a controlled variable instead of a flat one. This is the kind of result
to put in front of Tania rather than assert.

## 4. Where the axes stand — n=3, both axes, like for like

Batch `85c22b801df6` (03 Sep 01:03–01:50): three interleaved reps × four boxes,
all on **Wi-Fi**, run four-wide with the start barrier, standard 150 s
`bbb_codecs_rt` + `loop_bbbiso_vp9` protocol (audio-bearing clips — the same
regime as every earlier decode row, so it pools with them). 48 rows, all 🟢,
all alive at window end. Mean ΔW ± 95 % CI (t, n=3):

| ΔW (W) | Fire TV Stick 4K | Google TV Streamer | Xiaomi Gen 2 | Xiaomi Gen 3 |
|---|---|---|---|---|
| H.264 | 0.468 ±0.150 | 0.893 ±0.085 | 0.947 ±0.098 | 0.820 ±0.232 |
| HEVC | 0.484 ±0.041 | 0.835 ±0.147 | 0.907 ±0.018 | 0.559 ±0.034 |
| AV1 | 0.496 ±0.086 | 0.760 ±0.075 | 0.811 ±0.086 | 0.508 ±0.120 |
| VP9 | 0.422 ±0.180 | 0.813 ±0.026 | 0.856 ±0.089 | 0.484 ±0.218 |

**Axis A — same MediaTek MT8696, different OS/vendor/form factor.** The Google
TV Streamer's decode increment is **+0.43 W (H.264), +0.35 W (HEVC), +0.26 W
(AV1), +0.39 W (VP9)** above the Fire TV Stick's; the per-box CIs do not overlap on any codec.
On identical silicon, the OS/vendor stack (and stick-vs-box form factor)
roughly **doubles the marginal cost of a stream**. Both boxes are on Wi-Fi, so
the CR-074 network term no longer confounds this. What is *not* controlled:
Just Player 0.212-legacy on the GTV vs 0.196 on the Fire TV, and the Fire TV
has no decoder provenance (Fire OS logs no decoder names).

**Axis B — same vendor/OS family, different Amlogic generation.** Gen 3 is
**−0.35 W on HEVC, −0.30 W on AV1 and −0.37 W on VP9** (CIs clear — VP9 only
just: 0.70 vs 0.77 at the CI edges); on H.264 the CIs overlap (0.82 ±0.23 vs
0.95 ±0.10) — **no claim**. The n=2 hint
replicated exactly where it mattered. Pooling with the earlier n=2 Xiaomi rows
(`a9f06c58ab09`, same protocol, 2-wide instead of 4-wide) gives n=5 and the
same picture (Gen 2 H.264 0.95 vs 0.81 earlier; Gen 3 HEVC 0.56 vs 0.58).

### 4a. Decoder provenance (logcat on the same batch)

| | H.264 | HEVC | AV1 | VP9 |
|---|---|---|---|---|
| Fire TV Stick 4K | *none logged* | *none logged* | *none logged* | *none logged* |
| Google TV Streamer | `c2.mtk.avc` | `c2.mtk.hevc` | `c2.mtk.av1` | `c2.mtk.vp9` |
| Xiaomi Gen 2 | `OMX.amlogic.avc…awesome2` | `OMX.amlogic.hevc…awesome2` | **unresolved** | `OMX.amlogic.vp9…awesome2` |
| Xiaomi Gen 3 | `c2.amlogic.avc` | `c2.amlogic.hevc` | `c2.amlogic.av1` | `c2.amlogic.vp9` |

GTV and Gen 3 are hardware Codec2 on all four codecs (VP9 on the GTV was not
in `rig.py` before tonight). Gen 2 runs the **legacy OMX IL HAL** for
H.264/HEVC/VP9 — a different decode stack from Gen 3, which is a candidate
explanation for Axis B beyond the silicon itself. Gen 2's AV1 is unresolved:
the platform lists `OMX.amlogic.av1.decoder.awesome2`, Just Player also ships
libgav1 (in-app software AV1), and the AV1 rows logged neither — yet their ΔW
(0.81 W, below the box's own H.264) makes 1080p60 software decode implausible,
so the likelier reading is a hardware path logging under a tag the provenance
filter misses. To settle: one 60 s AV1 playback with an unfiltered logcat.
Fire OS logs no decoder names at all, so the Fire TV's paths are inferred
from power only.

These are decode *increments* over each box's own idle, and on Axis A the
marginal and the attributional views disagree in size — worth stating both
(methodology v0.7). In the four-box sync run (video-only, 2185 s windows):
Fire TV **idles higher** (1.44 W — Amazon's home-screen autoplay) but adds
less (+0.38 W); the GTV idles lower (1.29 W) and adds more (+0.69 W). Marginal
gap +0.31 W in the GTV's disfavour; **total playback power 1.83 vs 1.98 W —
the stick still wins, by 0.15 W, not by 0.3–0.4 W.** Which number is "the"
cost depends on whether the box would otherwise be idle-on or off.

Existing evidence going in, from batch `a9f06c58ab09` (n=2, headless, 150 s
windows, audio-bearing clips — a different regime from the sync runs):

| Codec | Gen 2 | Gen 3 | Gap |
|---|---|---|---|
| H.264 | 0.81 W | 0.89 W | ~none |
| HEVC | 0.88 W | 0.58 W | −34 % |
| AV1 | 0.83 W | 0.52 W | −37 % |
| VP9 | 0.85 W | 0.55 W | −35 % |

Consistent in direction on every rep, and larger than the within-box spread —
but **n=2 is below this project's n≥3 bar, so it is a hypothesis, not a
finding.** A mechanistic candidate was found the same session: Gen 2 decodes
through the **legacy OMX** API (`OMX.amlogic.avc.decoder.awesome2`), Gen 3
through **Codec2** — different decode stacks, not merely different silicon.

Axis A had **no usable clean data** before tonight: the only four-box run had
7 of 12 rows contaminated.


**Gen 2 AV1 — resolved 12:20 with a 60 s probe and an unfiltered logcat.**
Hardware: `MediaCodec: [OMX.amlogic.av1.decoder.awesome2]`, kernel
`vdec_init dev_name ammvdec_av1_v4l` with the `av1_mmu` firmware loaded in the
TEE; Just Player loads its bundled Libgav1 renderer at init but MediaCodec
takes the surface. The n=3 rows missed it because the OMX name is logged
under the `MediaCodec` tag, not `OmxComponent` — `bench.py` now scans both.
Separately, every long looped-clip row (30+ min) came back with
`decoders_allocated: []` on all four boxes: the mid-window logcat read is
made ~15 min after launch and a Xiaomi logs ~5k lines/min, so the allocation
had scrolled out of the default ring buffer. `bench.py` now grows the buffer
(`logcat -G 32M`, best-effort) before clearing it. Both fixes are in code,
untested on a live row until the next job.

## 5. Caveats carried on every number here

- **Video-only regime** on the sync templates: marker segments carry no audio
  track, so the concat drops the source AAC/Opus. Not comparable with the
  audio-bearing `loop_*` rows; compare only within the sync family.
- **Network**: the Google TV was moved to Wi-Fi on 2026-09-03 specifically so
  Axis A stops confounding OS with network path (CR-074 measured GTV's Wi-Fi
  term at +0.21 W — the same size as the codec deltas). All four boxes are now
  Wi-Fi. Rows recorded *before* that move have GTV on Ethernet.
- **Player version** is not uniform: 0.196 on three boxes, 0.212-legacy on the
  Google TV. Pinned deliberately, but it is an uncontrolled variable on Axis A.
- **HDMI-CEC auto-pause** cost real data this session: switching the panel's
  input makes Android pause the media session of a box that loses "active
  source" (confirmed in logcat: `onCecState: 0` → `MediaSessionRecord:pause`
  4 ms later). CEC is now disabled on all four boxes. Any run where the panel
  input was switched by hand should be treated as suspect.
- **Fire TV has no decoder provenance** (Fire OS logs no decoder names), so its
  hardware path is inferred from the power signature only.
- The **HDR arm carries no marker head** — a colour/geometry-matched marker
  could not be built safely for it (see §6).

## 5b. A failed run, diagnosed and repeated — the HEVC sync (batch `2e7f67befb29`)

The first HEVC sync run is **recorded and discarded**: every Android box sat
at idle power for the whole 36 min (Gen 3 2.06 W vs its 1.95 W baseline, GTV
1.27 vs 1.19, Fire TV 1.30 vs 1.39) while each box's position clock advanced
at exactly 1×; Gen 3's panel showed one white flash at loop 0 and then a flat
41.2 W (a frozen frame) to the end; Gen 2's player fell into BUFFERING at 77 s
and stayed there. Head-dip and cross-device statistics were null. This is the
S72 stuck-decoder signature. Cause: `bbb_h265_6min.mp4` is **hevc_nvenc
content coded at 1920×1088** (CTU-padded); the marker heads were libx265,
coded at a clean 1080 — the 2026-08-29 fix, made for the iso family whose HEVC
content *is* libx265/1080. A stream-copy concat then changes the coded picture
size at the first head→content splice, and every hardware HEVC decoder on the
bench (c2.amlogic, c2.mtk, OMX.amlogic) froze on it while still consuming
input. The lesson generalises the S72 one: **match the content's coded height;
choose the head's encoder per clip** (`decode_run._marker_encoder`, tested).
The clip was rebuilt with hevc_nvenc heads (coded 1088 throughout, 2250.74 s)
and the run is repeated after the ladder. AV1 content and heads are both a
clean 1080 — that arm is unaffected.

**Re-run, 10:12–10:50 (job `d9a03bf3`, batch `c63a1e99e321`, Gen 3 on the
panel): the fix holds.** All four boxes played to the end (0 unaligned samples,
1046–1054 clock segments each, content skew < 1.5 s at launch), and every box
shows the marker head cheaper than content — Gen 2 −0.08 ±0.05 W, Gen 3
−0.08 ±0.03, Fire TV −0.08 ±0.01, GTV −0.02 ±0.05 (loop 0 excluded: the Fire
TV's loop-0 head coincides with its cold-start spike, +0.58 W, so `head_dip`
now skips loop 0 exactly as the marker residual does). Panel vs software clock
on Gen 3: median +1.69 s, MAD 0.18 s (n=5) — ~0.5 s later than with H.264
(+1.05/+1.21 s), a constant offset within the run, so the HEVC render path on
Gen 3 simply sits further behind the media-session position.

| | Gen 2 | Gen 3 | Fire TV | GTV |
|---|---|---|---|---|
| mean content W, HEVC (this run) | 2.812 | 2.454 | 1.845 | 1.901 |
| mean content W, H.264 (`987f428d`) | 2.945 | 2.511 | 1.827 | 1.981 |
| head dip W (loops 1–5) | −0.08 ±0.05 | −0.08 ±0.03 | −0.08 ±0.01 | −0.02 ±0.05 |
| single-box SNR, 5 s / 30 s bins | 0.84 / 0.79 | 0.82 / 1.12 | 0.63 / 0.65 | 0.80 / 0.91 |
| same box, HEVC vs H.264 profile r (n=72) | +0.46 (t 4.3) | +0.39 (t 3.5) | +0.39 (t 3.5) | +0.66 (t 7.3) |

Axis B inside one run: Gen 3 − Gen 2 = **−0.357 ±0.009 W** per 5 s bin (n=72),
the iso-HEVC number (−0.35) reproduced on a different clip regime. Axis A in
absolute watts: GTV − Fire TV +0.057 ±0.013 W (the ΔW-over-idle lens in §4 is
the one that separates them). Cross-device r at 10 s bins runs 0.60–0.82
(t 4.3–8.3), all six pairs positive at every bin width, Gen 2 ~ GTV strongest
(0.88 at 20 s). Gen 3 at 30 s bins is the first single box to reach SNR > 1
(1.12). The **same content decoded through a different codec keeps part of its
power shape** (r 0.39–0.66 per box) — the profile is partly a property of the
pictures, not just of the bitstream. Descriptors agree with §3b: edge energy
positive on all four (r +0.28…+0.52), motion negative or null, and luma
negative on all four here (r −0.21…−0.43) — luma was withdrawn after the H.264
replication failed, so this is one run of three, not a claim.

## 5c. 4K H.264 — three of four boxes cannot, and the reason is in the codec table

`loop_bbb4k_h264_sync` (batch `b208e9da489c`, 3840×2160@60 H.264, 20.5 Mbps)
launched on the **Google TV only**. Both Xiaomi players went to `state=ERROR`
at launch; the Fire TV sat in BUFFERING for the whole 30 s launch budget. All
four rows are recorded (the three as error rows). The Xiaomi failures are a
hard capability limit, readable from the boxes' own codec tables: Gen 2's
hardware AVC decoder advertises `blocks-per-second-range 1–972000` at 16×16
blocks — a 4K frame is 32,400 blocks, so **4K H.264 tops out at 30 fps** on
Gen 2 (Gen 3 advertises 1,036,800 blocks/s ⇒ 32 fps at 4K, and measures its
own AVC decoder at 134 fps for 1080p — 4K60 H.264 is beyond both). The
Fire TV shares the GTV's MT8696, which *does* play this stream, so its stall
is most likely delivery (Wi-Fi 5 stick vs the Streamer's radio, four boxes
pulling 20 Mbps with ExoPlayer bursting ahead) rather than the decoder — an
Axis A observation in its own right, not proven either way tonight.

Consequence: the resolution arm on all four boxes is run in **HEVC** instead
(`loop_bbb4k_h265_sync`: same 4K master, hevc_nvenc CBR 20 Mbps, 4K60, 15
loops, hevc_nvenc heads matching the content's padded coded height) — every
box decodes 4K60 HEVC in hardware. The GTV's H.264 4K run still gives one box
a clean 1080p→4K comparison at fixed codec and frame rate.

## 5d. HDR 4K60 HEVC Main 10 (batch `15173658d41f`, marker-free, 30 loops)

Three boxes clean for the whole 1290 s window (clocks 619–626/619–626 PLAYING,
29 loops binned): **Gen 2 ΔW 1.41 W, Gen 3 1.03 W, GTV 1.29 W** (all 🟢). The
Fire TV never left BUFFERING at launch — its second 4K failure of the night,
both at ≥ 20 Mbps, both while the same-chip GTV played the same stream; this
reads as a delivery limit on the stick's Wi-Fi link with three other boxes
streaming, not a decoder limit, and a solo run would settle it. Axis B holds
under 10-bit PQ 4K60: **Gen 3 −0.38 W vs Gen 2** (per-bin −0.48 ±0.03 W over
the 9 content bins), the same size as at 1080p HEVC. With only 45 s of content
the bin profile is short (9 bins), but with n=29 loops per bin the three boxes
agree on it strongly: r = +0.90 (Gen 2 ~ GTV, t=5.5), +0.93 (Gen 3 ~ GTV,
t=6.6), +0.75 (Gen 2 ~ Gen 3). Descriptor fits are not reported (4 predictors
on 9 points). One curiosity worth keeping: the panel-meter edge finder, run
against a clip with *no* marker head, still found a step at 26 of 29 loop
starts (+1.24 s, MAD 0.47 s) — the content's own opening scene-cut acting as a
natural marker.

## 5e. GTV alone at 4K H.264 (batch `b208e9da489c`, 15 loops)

ΔW **1.12 W** at 3840×2160@60 vs 0.69 W at 1080p60 in the same regime — +0.43 W
(+62 %) for 4× the pixels, on one box; marker validation over 14 loops, median
residual +2.00 s (MAD 0.53 s), i.e. the 4K path adds ~0.8 s of display latency
over 1080p. The texture/motion driver survives the resolution change on this
box (edge +0.47, motion −0.60 standardised, R² 0.43); the bin-profile
correlation between its 1080p and 4K runs is weak-positive (r=+0.35, t=1.8,
24 shared bins — 2 min of content is thin).

## 5f. Bitrate ladder — four boxes, 0.25 → 32 Mbps, H.264 1080p60 (batch `bae281b52f90`, n=3)

Owner's ask: "short runs on all 4 boxes simultaneously starting very low
bitrate, stepping up to very high". Seven NVENC CBR rungs of the same BBB
2-min clip (250 k, 500 k, 1.5 M, 4 M, 8 M, 16 M, 32 Mbps), 90 s windows, all
four boxes rendezvous-started on each rung, two full passes (jobs `acb6fefc`,
`bf22114b`, 11:00–11:29; third pass `b6e748a9` at 13:20 after the WattLab call, when
Arian pointed out n=2 was below the bar). 84/84 rows; one row not alive at
window end (pass 3, Fire TV 0.25 Mbps: PAUSED on the last two clock polls,
after the sampled window, reading 0.15 W below the other two passes — kept,
it widens that cell's CI to ±0.22).

**Absolute draw during playback (W, mean of the three passes):**

| Mbps | Fire TV | GTV | Gen 2 | Gen 3 |
|---|---|---|---|---|
| 0.25 | 1.750 | 1.693 | 2.734 | 2.495 |
| 0.5 | 1.752 | 1.728 | 2.705 | 2.485 |
| 1.5 | 1.795 | 1.771 | 2.751 | 2.506 |
| 4 | 1.828 | 1.816 | 2.828 | 2.524 |
| 8 | 1.883 | 1.876 | 2.910 | 2.740 |
| 16 | 1.977 | 1.997 | 3.052 | 2.768 |
| 32 | 2.101 | 2.132 | 3.261 ⚠ | 2.880 |
| **slope, mW per Mbps (95 % CI over the 7 rungs)** | **11.0 ±2.3** | **13.2 ±3.5** | **17.2 ±3.1** | **13.0 ±6.2** |
| r (linear in Mbps) | 0.98 | 0.97 | 0.99 | 0.92 |
| 0.25 → 32 Mbps | +20 % | +26 % | +19 % | +15 % |

Pass-to-pass agreement is within 0.1 W per rung on every box except the Fire
TV's lowest rung (above); the per-rung n=3 CIs are 0.01–0.17 W; the slope over
seven rungs is the statistic that carries, and it moved by < 0.2 mW/Mbps
between n=2 and n=3.

What it says, stated carefully:

- **Decode power is linear in delivered bitrate across two decades**, on all
  four boxes (r ≥ 0.92). There is no knee: the 0.25–1.5 Mbps rungs are flat
  within 0.03 W, and every doubling above 4 Mbps costs about the same
  increment. This is the bits axis the near-CBR sync corpus could not test
  (§3b) — with the bitrate actually varied, its coefficient is clean.
- **The whole 128× bitrate span moves playback draw by 15–26 %.** The
  operating point (which box, which idle floor) still dominates; the bitstream
  is a second-order lever on the client — consistent with the SMPTE "content
  over codec" and iso-bitrate findings.
- **Same silicon, different slope:** the Fire TV pays 11.0 ±2.3 mW/Mbps, the
  GTV 13.2 ±3.5 on the same MT8696 — CIs overlap, so 🟡; but the GTV ends the
  ladder at the Fire TV's level (2.13 vs 2.10 W) after starting 0.06 W below it.
- **Gen 2 flexes most** (17.2 ±3.1 mW/Mbps vs Gen 3's 13.0 ±6.2) — the older
  S905X4/OMX path spends more per delivered bit; Gen 3's wide CI comes from its
  8 Mbps rung (2.72 vs 2.79 across passes) and its own slope is not separable
  from the MT8696 boxes.
- **32 Mbps over Wi-Fi is where delivery starts to bite:** Gen 2 shows only
  85–92 % PLAYING on that rung (⚠, its 3.26 W is stall-contaminated — stalls
  raise, not lower, its draw), GTV and Gen 3 94–100 %, the Fire TV 95–99 %. So the
  Fire TV *does* sustain 32 Mbps 1080p on this Wi-Fi — which means its 4K stall
  in §5c at ≥ 20 Mbps was not raw Wi-Fi throughput; it is specific to the 4K60
  AVC path.

**A measurement lesson from the Fire TV's ΔW column.** Its per-rung ΔW is
*negative* at every rung below 32 Mbps (−0.13 to −0.33 W). The 20 s baseline
before each rung is taken with the player UI in the foreground (the previous
rung was just stopped), and on the Fire TV that state draws 2.06–2.15 W —
**more than playing video** (1.78–2.13 W). The other three boxes' foreground
UIs sit at or below their playback draw, so their ΔW is positive. This is the
attributional point of §4 in its sharpest form: "idle" on the Fire TV is not
one number, it is the screen it happens to be showing. `ladder_report.py`
therefore leads with absolute watts and keeps ΔW for the record; the same
caveat applies to any short-gap multi-clip template on that box.

## 5g. 4K60 HEVC on all four boxes (batch `70351d846a8a`, 15 loops, GTV on the panel)

The arm the AVC decoders could not do (§5c) runs cleanly as HEVC: `bbb_h265_4k_2min`
(hevc_nvenc Main, 3840×2160, coded 2176, 19.1 Mbps mean, 60 fps), 15 loops,
1955 s, all four `alive_at_window_end`, clocks 935–946 polls all PLAYING, 0
unaligned samples, launch skew ≤ 1.1 s. Panel vs software clock on the GTV:
median +1.20 s, MAD 0.15 s over 14 loops (H.264 on the same box: +1.21 s —
the render offset is a per-box constant, not a per-codec one on MediaTek).

| | Gen 2 | Gen 3 | Fire TV | GTV |
|---|---|---|---|---|
| mean playback W, 4K60 HEVC 19 Mbps | 2.894 | 2.347 | 2.215 | 2.273 |
| mean content W, 1080p60 HEVC (§5b) | 2.812 | 2.454 | 1.845 | 1.901 |
| 4K − 1080p | +0.08 | −0.11 | **+0.37** | **+0.37** |
| single-box SNR, 5 s / 30 s bins | 1.28 / 1.45 | 0.68 / 0.60 | 1.77 / 3.04 | 1.99 / 2.67 |
| head vs content (loops 1–14) | **+0.30 ±0.03 ⚠** | **+0.27 ±0.04 ⚠** | −0.07 ±0.01 | −0.02 ±0.02 |

**Intra-content structure is now resolvable from a single box.** At 4K the
content-driven swing is ~0.3 W on every box (bins 85–100 s of the clip are
the floor on all four, the 45–55 s bins the ceiling), and three boxes cross
SNR 1 on their own trace — the Fire TV and GTV reach SNR 2.3–3.0 at 10–30 s
bins. Cross-device agreement is correspondingly the strongest of the session:
r 0.77–0.94 at 5 s bins (t 5.7–13.2), 0.92–1.00 at 20–30 s (Gen 3 ~ GTV
r = 1.00, t = 21). Axis B inside the run: Gen 3 − Gen 2 = **−0.54 ±0.02 W** per
bin (n=24); Axis A in absolute watts +0.05 ±0.02 (GTV − Fire TV).

**Resolution costs the MediaTek boxes 0.37 W; it costs the Amlogic boxes
nothing.** Both MT8696 boxes pay the same +0.37 W going from 1080p to 4K HEVC.
Roughly half of that is bitrate (the ladder's 10–13 mW/Mbps × the ~15 Mbps
difference ≈ 0.15–0.20 W), the rest is pixels. Gen 2 pays +0.08 W and Gen 3
*less* at 4K than at 1080p (−0.11 W) — despite 5× the bits. The reading that
fits is that Amlogic's 1080p path includes a VPU upscale to the 4K output
mode that the native-4K stream bypasses, and that its HEVC decode cost per
pixel is small; it is a hypothesis for Tania, stated as such.

**Two things the Amlogic boxes do at 4K that the MediaTek boxes don't:**

1. **The black·white·black head costs *more* than content on both Xiaomis**
   (+0.30 / +0.27 W, every loop, ⚠ in the table), the opposite of every 1080p
   run (−0.08 W). The head segments were checked against the content: same
   codec, profile, 2176 coded height, `yuv420p`, level, frame rate, untagged
   colour — only the bitrate differs (113 kbps vs 19 Mbps), which makes decode
   cheaper, not dearer. Per bin: black 3.07 → white 3.21 → black 3.21 → first
   content bin 3.03 → 2.87 (Gen 2), i.e. the draw rises on the white frames
   and *decays* over ~10 s afterwards. That is not the decoder; it is
   downstream of it — a post-processing or output stage that reacts to a
   full-white 4K60 frame with a time constant. The MediaTek boxes show
   nothing of the kind. Not a measurement fault (the clock, the panel marker
   and the content bins all line up); a real device behaviour to name.
2. **Gen 3 toggles between two states ~0.2 W apart at loop granularity**
   (per-loop content means 2.21–2.24 W in nine loops, 2.42–2.47 in five;
   loops 0–1, 6–7 and 14 high). Its own SNR is 0.6 because of it — the loop
   noise is bimodal, not Gaussian. Nothing like it at 1080p HEVC on the same
   box (drift −0.001 W/loop). Candidates: the Wi-Fi radio's power-save state
   at 19 Mbps, or a periodic background task; recorded, not diagnosed.

**Descriptors at 4K (first corpus with real bitrate variation: 8–22 Mbps over
the content bins).** Joint OLS, standardised betas (n=24 bins): edge +0.41…
+0.62 on all four, motion −0.33…−0.47 on all four, bits −0.10…−0.54 (Gen 3
most), luma +0.29 on the Amlogic pair only; R² 0.34–0.47. **Delivered bits are
negatively associated with power *within* a clip and positively across the
ladder** — no contradiction: inside a clip, NVENC spends its bits on the
motion-heavy sections, which are the cheap ones to decode; across the ladder,
the same pictures at more bits cost more. Bits are not the cost driver; what
the bits encode is. Texture positive, motion negative is now the same answer
on three codec/resolution regimes and four boxes.

## 5h. Loop validity — does a looped excerpt measure as the continuous original? (batch `22bb632c434f`, n=3)

Every loop family on the rig is a concat of one 2-min excerpt (`bbb_h264_20min`
= ×10, `_60min` = ×30), so this assumption sits under every long-window row.
The owner asked for the test after the WattLab call; Tania's caveat was that
*short* loops add artificial cuts. One NVENC encode of 600 s of BBB (1080p60
CBR 8 Mbps, the corpus recipe, keyframes forced every 30 s so stream-copy cuts
are exact), three arms of identical length in one job per box, all four boxes
rendezvous-started, three passes (jobs `7e3b31a9`, `40259132`, `52f9cf24`,
13:40–18:35 with the boxes' boots in between): **A** the continuous 600 s ·
**B** its 120–240 s excerpt ×5 · **C** its 120–150 s excerpt ×20. Video-only,
headless, 600 s windows; means below are over PLAYING-only samples (the clip
ends with the window, so the last ~12 of 600 samples per row sit after EOF and
are excluded — identically for all three arms).

| box | A continuous, W (n=3) | B − A, 120 s ×5 | C − A, 30 s ×20 |
|---|---|---|---|
| Fire TV Stick 4K | 1.867 ±0.022 | +0.007 ±0.029 | +0.026 ±0.050 |
| Google TV Streamer | 1.944 ±0.036 | −0.003 ±0.024 | **+0.012 ±0.009** |
| Xiaomi Gen 2 | 2.954 ±0.058 | +0.006 ±0.042 | +0.008 ±0.028 |
| Xiaomi Gen 3 | 2.682 ±0.025 | +0.019 ±0.237 | **+0.101 ±0.027** |

(paired within pass, 95 % CI, t with n=3; every one of the 36 rows 🟢)

- **A multi-minute loop is measurement-neutral.** The 120 s ×5 arm sits within
  0.02 W of the continuous original on all four boxes, CIs straddling zero,
  and the bound the data supports is ±0.03–0.04 W (< 2 %) on the three boxes
  with tight CIs. Gen 3's CI is wide (±0.24) because its two-state behaviour
  (§5g) put one pass 0.09 W low and two 0.06–0.09 W high — inconclusive on that
  box at n=3, not a loop effect.
- **A 30 s loop is not free everywhere.** It costs the Streamer +0.012 W (CI
  clear, +0.6 %) and Gen 3 **+0.10 W (+3.8 %, all three passes +0.095 to
  +0.114)**; the Stick and Gen 2 show +0.01–0.03 W inside their CIs. One cut
  every 30 s (a keyframe-aligned discontinuity, no decoder reset) is enough for
  the Amlogic s7d box to pay for it — Tania's caveat, measured.
- **Consequence for CR-081:** the ReadySetGo source on GoS1 is a **5 s** UVG
  sequence (600 frames at 120 fps, on disk as seven repeats = 35 s); the rig's
  150 s and 20-min protocols would cut every 5 s, six times as often as arm C,
  with a per-box cost the other tiers don't carry. A longer source is needed before it becomes the sports
  tier; a 30 s-looped tier would have to be caveated per device.

## 6. Overnight queue

n=3 top-up on both axes (4-wide parallel, all Wi-Fi, standard 150 s protocol so
it pools with existing data), then the sync family: H.264 re-run (GTV died in
the first when its Ethernet was pulled), HEVC, 4K, HDR.

- **4K**: `bbb_h264_4k_2min` 3840×2160@60, 15 loops → n=15 per content bin.
- **HDR**: `hdrmeridian_h265_4k_45s` (HEVC Main 10, bt2020/PQ, 59.94 fps), 30
  loops, **marker-free**. A matched marker was attempted and rejected on
  evidence: libx265 would not write the PQ transfer into the VUI, and its
  segments code at a clean 2160 while the source is CTU-padded to 2176 — the
  exact coded-height discontinuity that froze Roku's HEVC decoder in S72. The
  content clock does not need the marker; what is lost is the on-screen
  validation and the head-dip check, and that is stated rather than hidden.
  Content provenance is weak (a Pixop proto upscaled from dirty SD): this arm
  exercises the 10-bit/PQ **decode path**, it is not a content claim.


## 7. Morning status (03 Sep, 10:05) — what ran, what did not, and why

> **10:55 update:** the owner freed the rig at ~10:05; the four missing jobs were
> queued at 10:10. The HEVC re-run has landed and is analysed in §5b (fix
> confirmed, all four boxes, head dip on every one). The ladder ×2 landed at
> 11:29 and is in §5f (56/56 rows, linear in bitrate on all four boxes). The
> 4K HEVC arm landed at 12:03 and is in §5g — the strongest intra-content
> signal of the session (single-box SNR > 1 on three boxes, r up to 1.00).
> **12:30: all queued arms done.** Gen 2's AV1 path resolved as hardware
> (§4a addendum), TV switched off, provenance gap on long rows fixed in
> `bench.py`, 1072 tests green, everything still uncommitted.
> **18:40:** third ladder pass in (n=3, §5f) and the loop-validity job
> analysed (§5h): multi-minute loops are neutral, 30 s loops cost Gen 3
> +0.10 W. The panel had woken itself again (Active on HDMI_3, the Fire TV's
> input, during headless jobs) — switched off a third time; see JOURNAL.

**Ran and analysed:** the n=3 top-up (both axes, all 🟢), H.264 sync ×2 (four
boxes, test–retest), HEVC sync (failed — diagnosed, §5b), 4K H.264 (GTV only,
§5c/§5e), HDR (three boxes, §5d). The rig's own idle auto-off powered the boxes
down at 07:59 (4 h after the last job); the panel is in standby (9.7 W).

**Did not run — my fault, not the rig's:** the bitrate ladder (×2), the HEVC
re-run on the rebuilt clip, and the 4K HEVC arm. All three were to be queued by
a post-queue script after the HDR job, gated on a "HDR result stored" check. I
rewrote that script three times during the night (fixing the check, adding
jobs), and a process running an *earlier* version survived the restarts and
kept polling a condition that could never be true — it ran, correctly, for six
hours, waiting. The clips are built and verified, the templates and tests are
in, the batch ids are reserved; the runs themselves need ~2 h of rig time
(ladder ×2 ≈ 40 min, HEVC sync ≈ 40 min, 4K HEVC ≈ 35 min). Lesson recorded in
the journal: never hot-patch a running orchestration script — replace it via a
state file and confirm the old process is gone.

**Still open:** Gen 2's AV1 decoder path (60 s probe, §4a); Fire TV at ≥ 20 Mbps
(solo run); the three unrun arms above.

**Uncommitted:** everything from this session is on disk, tested (1072 tests),
and running in the service, but not committed — the owner asked for commits
only on request. `/ship-service-change` will land it with `settings.json`
excluded.
