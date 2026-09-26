# TV Box W5 — onboarding and first characterisation (2026-09-21 → 22)

No-brand Android box, added to the decode rig 2026-09-21 into the retired Xiaomi Gen 2's Lab-F3
plug (`192.168.1.1`) and the LG C2's **HDMI_1**. Device key `w5`. Connected by Ethernet and Wi-Fi,
developer mode on, factory fresh (no Google account, no Play Services, no user apps).

---

## 1. Identity — the product props are a lie

| field | reports | truth |
|---|---|---|
| `ro.product.model` | `ADT-3` | no-brand "TV Box W5" |
| `ro.product.brand` / `manufacturer` | `google` / `Google` | — |
| `ro.product.device` / `name` | `blueline` (Pixel 3) | — |
| `ro.build.fingerprint` | `google/blueline/blueline:15/SP1A.211105.004/20260703.141939:userdebug/test-keys` | — |
| `ro.build.version.release` | **12** (API 31) | Android 12 |
| `ro.board.platform` | `apollo` | **Allwinner H618** |
| `ro.hardware` | `sun50iw9p1` | ” |
| `ro.soc.model` / `manufacturer` | `H618` / `Allwinner` | ” |

The spoof contradicts itself: the fingerprint claims Android 15, `ro.build.version.release` says 12.
**Provenance must come from `ro.board.platform`/`ro.soc.*` and from the decoder actually allocated in
logcat — never from `ro.product.*`.** This is the concrete case CR-080 (decode-pipeline provenance)
was worried about.

Other hardware facts: 4× Cortex-A53, Mali-G31, 4 GB RAM, **`armeabi-v7a` only** — a 32-bit userland
on a 64-bit SoC (`ro.product.cpu.abilist64` is empty). `adb root` works (userdebug build).

## 2. Codec support

From `/vendor/etc/media_codecs.xml`: **legacy OMX IL HAL**, no `c2.*` vendor components — the same
HAL generation as the retired Xiaomi Gen 2, not the Gen 3. Hardware decoders:

`OMX.allwinner.video.decoder.{avc, hevc, vp9, vp8, vp6, mpeg1, mpeg2, mpeg4, mjpeg, vc1, divx, xvid, wmv1, wmv2, msmpeg4v1, msmpeg4v2, s263, rxg2}`

`avc.secure` and `h263` are commented out. Sole encoder: `OMX.allwinner.video.encoder.avc`.
**There is no AV1 decoder in the vendor list** — which makes this the rig's first box with
**hardware VP9 but no hardware AV1**, and therefore the first that can contrast a hardware and a
software modern-codec path *on one piece of silicon, in one session*.

## 3. The headline finding — it cannot play AV1, and it fails in the flattering direction

Presented-frame rate measured from SurfaceFlinger frame timestamps
(`dumpsys SurfaceFlinger --latency`), source 1080p60 in every case:

| codec | decoder allocated | presented fps | ΔW, 90 s probe — **superseded, see §8** |
|---|---|---|---|
| H.264 | `OMX.allwinner.video.decoder.avc` (hw) | **60.0** | +1.441 |
| HEVC | `OMX.allwinner.video.decoder.hevc` (hw) | **60.0** | +0.927 |
| VP9 | `OMX.allwinner.video.decoder.vp9` (hw) | **60.0** | +1.077 |
| AV1 | none — Just Player's bundled `Libgav1VideoRenderer` (in-app software) | **1.3** | +0.504 |

The method validates itself: the three hardware codecs land on exactly 60.0 fps.

⚠ **The ΔW column above is a 90 s probe and is NOT the reportable number.** The n=3 campaign
(§8) measures the same H.264 cell at **+1.086 W** against the probe's +1.441 W, off an identical
baseline (3.774 vs 3.776 W) — the gap is window length over varying content, not a discrepancy.
BBB's power varies within the clip (JOURNAL S73: texture up, motion down), so a 90 s sample lands
wherever it lands. **Short windows on varying content are not representative**; use the campaign
figures. The fps column is unaffected — frame rate is a rate, not an average over content.

**AV1 renders a ~1.3 fps slideshow, and because it is not doing the work its ΔW is the lowest of
the four.** A campaign that recorded ΔW alone would have published *"AV1 is the cheapest codec on
this device"* — precisely backwards.

**Every gate the rig currently applies would have passed it:** the media session reported state 3
(PLAYING) from start to end, the power trace was flat and stable (sd 0.10 W over 90 samples), the
mid-window screenshot showed correct, non-black picture, and `alive_at_window_end` was fine. The
only signal that catches it is a presented-frame-rate check, which the harness does not currently
make. Recommendation for `bench.py`, for the owner to weigh: sample the video layer's presented-frame
rate mid-window and fail any row that is not within tolerance of the source frame rate.

This generalises beyond this box: **a low decode-power reading is only meaningful if the device was
actually decoding at real-time rate.** Any client-decode comparison that includes a codec the device
cannot sustain will systematically flatter that codec.

## 4. Traps found during onboarding

- **Dual-homed, and the second address is not a second path.** eth0 `.98`
  (`58:5c:de:01:31:59`), wlan0 `.124` (`fe:fd:fc:bb:c4:3b`). Both sit on the same /24 and the kernel
  answers ARP for `.124` out of eth0 — the neighbour table maps both IPs to the Ethernet MAC.
  **Addressing the box at `.124` silently measures Ethernet.** A Wi-Fi row (CR-074 style) needs the
  cable physically removed; the path cannot be selected by IP here. The wlan0 MAC is
  locally-administered and rotates per SSID, so the Bbox reservation must pin the **eth0** MAC.
- **Multichannel audio fails the entire playback** (`state=7`) rather than downmixing to stereo.
  Isolated by test: stereo AAC, stereo Opus and stereo MP3 all play; only 5.1 fails. Not a broken
  audio HAL — a YouTube clip played with audio, which is what disproved that theory. 10 of the 95
  corpus clips are 5.1 (the plain `bbb_av1_*`/`bbb_h264_*`/`bbb_h265_*` family); the `bbbiso_*`,
  `bbbladder_*`, `bbbloop*` and `bbbnet_*` families are stereo, so **the comparison corpus is
  unaffected and W5 rows use the standard, unmodified files**.
- **`position` never advances** in `dumpsys media_session` on this box. Liveness must come from
  power and playback state, not position — the same class of trap as the Apple TV's pyatv
  `playing` misreport and the Fire TV's `alive_at_window_end` false negative.
- **Display geometry is not what it looks like.** The HDMI link runs **4096×2160p60 — DCI 4K, not
  the C2's native 3840×2160 UHD**, so the panel rescales; and Android renders a **1280×720**
  framebuffer that the display engine upscales to fill it
  (`fb[1280,720] → frame[0,0,4096,2160]`, `/sys/class/disp/disp/attr/sys`). The decoder still
  decodes the stream at its native 1080p, but the **composite/render half is happening at 720p**,
  which is a real difference from the other boxes and a caveat on any cross-device comparison.
  No 4K claim from this box until it is resolved.

## 5. What went right

- **`adb root` works** — display mode and sysfs are drivable from the shell, no on-device menu trips.
- **It auto-boots on mains restore**: plug off → on, ADB back unaided at **t+65 s**, and the ADB
  authorisation *survived* the power cycle (the Fire TV loses its). The rig can therefore drive it
  through the normal power-cycle protocol.
- Just Player 0.196 sideloaded from the upstream universal APK (carries a v7a slice); installs and
  runs as `primaryCpuAbi=armeabi-v7a`. The `0.196-legacy` build carries the same media3
  (1.8.0-rc01) and behaves identically — it is not a workaround for anything here.

## 6. Comparability caveats for any W5 row

1. **Factory fresh.** No Google account, no Play Services, no background sync — so its idle floor is
   *cleaner* than the account-carrying boxes (Google TV, Xiaomi Gen 3, Fire TV). A W5-vs-GTV delta
   is part silicon and part "no account", the same class of confound as CR-074's Wi-Fi term, which
   was the same magnitude as the codec deltas being compared. Do not attribute it all to the SoC.
2. **720p composite** (see §4) against other boxes' 1080p/4K.
3. **Sink regime**: the W5 is on `panel:HDMI_1`. The 2026-08 tables in `docs/vp9_oneoff_2026-08.md`
   §5.2 are **headless** rows (no sink), a different regime (JOURNAL S73: up to 0.77 W). W5 rows are
   not drop-in comparable with those and are reported separately.

---

*Campaign: batch `3e54b322a9b4`, BBB iso-bitrate 1080p60 @8 Mb/s, screen mode, 1080 s windows,
n=3 per codec, 2026-09-21→22. Results and the n=3 table are in §7 below once imported.*

## 7. Protocol incident — self-inflicted, logged and quantified

While checking that the campaign was alive I issued one `adb shell dumpsys media_session` against
the W5 **inside the measurement window of row `64e14084` (rep 1, H.264)**. An adb command wakes the
device's CPU, and the rig deliberately pauses its own plug polling during a window for exactly this
reason.

The artifact is visible in the row's raw trace and is the only excursion in it: **two consecutive
samples at 23:57:53-54 reading 5.109 W**, against a window mean of 4.860 W (sd 0.077) — the only
two samples in 1091 above mean+3sd. That is +0.25 W for 2 s, which biases the window mean by
**+0.0005 W on a reported ΔW of 1.086 W (0.05 %)**.

**Disposition: the row is kept, not discarded.** The bias is quantified, disclosed, and three orders
of magnitude below the effect being measured; discarding would cost an hour of rig time and remove
information for no gain in accuracy. It is recorded here so the row is never mistaken for an
untouched one. Liveness after this point was checked only against the OWL server (`/live`,
`/decode/status.json`), which reads cached state and never contacts the device.

## 8. Campaign results — n=3, BBB iso-bitrate

Batch `3e54b322a9b4`, 2026-09-21→22. BBB iso-bitrate 1080p60 @ ~8 Mb/s (marker-encoded clips),
**screen mode** (sink `panel:HDMI_1`), 1095 s windows, 1 s cadence, n=3 per codec, 12 rows, none
discarded. Device-total ΔW over the box's own idle.

| codec | decode path | mean ΔW | reps | sd | presented fps |
|---|---|---|---|---|---|
| H.264 | hw `OMX.allwinner.video.decoder.avc` | **+1.073 W** | 1.051 / 1.083 / 1.086 | 0.019 | 60.0 |
| HEVC | hw `OMX.allwinner.video.decoder.hevc` | **+0.966 W** | 0.931 / 0.975 / 0.993 | 0.032 | 60.0 |
| VP9 | hw `OMX.allwinner.video.decoder.vp9` | **+0.971 W** | 0.923 / 0.987 / 1.002 | 0.042 | 60.0 |
| AV1 | **none** — in-app `Libgav1VideoRenderer` | *(0.442 W — see below)* | 0.422 / 0.451 / 0.452 | 0.017 | **1.7** |

Every row: `playback_state_midwindow = PLAYING`, decoder provenance captured, mid-window screenshot
showing correct moving content, panel context ΔW +27.3 to +31.5 W (the screen really was displaying
HDMI_1 throughout).

### 8.1 On this silicon, hardware decode is NOT codec-flat

Welch comparisons across the three hardware codecs:

| comparison | difference | t | 95 % CI | verdict |
|---|---|---|---|---|
| H.264 − HEVC | **+0.107 W** | 4.96 | +0.038 … +0.176 | **separated** |
| H.264 − VP9 | **+0.103 W** | 3.85 | +0.018 … +0.188 | **separated** |
| HEVC − VP9 | −0.004 W | 0.14 | −0.089 … +0.080 | tie |

**H.264 costs about 0.10 W (≈11 %) more than HEVC and VP9 on this box's own hardware decoders, and
the rep ranges do not overlap.** HEVC and VP9 are indistinguishable from each other.

This qualifies a generalisation the panel has been carrying. On the Google TV Streamer the three
codecs sat within **0.08 W** of each other and that was read as "codec choice is nearly free on
decode silicon" (`codec-decode-energy-depends-on-silicon-and-regime`). On the Allwinner H618 the
codec difference is **resolvable at n=3**. The honest statement is narrower than the old one:
*a fixed-function decoder makes codec choice cheap, not free, and how cheap is a property of the
particular silicon.* Note the older, more efficient codec is the expensive one here — the opposite
of the software ordering (h264 < av1 < hevc), so this is not "newer codecs cost more" in hardware.

At iso-bitrate all four streams carry the same bit volume, so this is not a bitrate artefact.
It is one content family on one box; it says H.264 is dearer **on this decoder**, not in general.

### 8.2 The AV1 rows are not a measurement

All three AV1 rows look clean by every gate the harness applies and are invalid. Re-measured on the
exact marker-encoded clip the campaign played: **1.7 fps against a 1080p60 source** (the H.264
marker clip returns 60.0 fps on the same box, same session — the method's own control).

The AV1 figure of +0.442 W must therefore never be quoted as AV1 decode energy. It is the cost of a
device failing to decode AV1, and it is **58 % below the cheapest codec the box can actually play** —
so quoting it would rank AV1 as this device's most efficient codec by a wide margin. The three reps
agree to ±0.015 W, which is the trap: it is consistently wrong, not noisily wrong, and consistency
is what usually earns trust.

One incidental tell did show up in the raw traces: the AV1 rows' within-window sample sd is
**0.126–0.139 W** against 0.063–0.079 W for all nine hardware rows. A jitter check would have
flagged these as unusual — not as proof, but as a reason to look.

## 9. Same-night comparator — W5 vs Google TV Streamer

Run immediately after the W5 campaign on the same corpus, protocol and window (BBB iso-bitrate
1080p60 @8 Mb/s, `loop_bbbiso_h264`, 1080 s, 1 s cadence), batch `4b94ea5075f3`, so nothing about
the clip, the origin, the meter family or the night differs.

| job | ΔW | w_base | w_task | disposition |
|---|---|---|---|---|
| `1e1a0c75` | −0.928 | **2.757** | 1.829 | **DISCARDED** |
| `ffa41f71` | +0.643 | 0.979 | 1.622 | kept |
| `7685cffc` | +0.595 | 1.036 | 1.631 | kept |

**`1e1a0c75` is discarded**, and it is worth naming why because it is the CR-077 failure mode in the
wild: its baseline reads 2.757 W against 0.979–1.036 W on the other two reps — the box was still
coming down from boot when its baseline was taken, so ΔW went **negative**. The row's liveness and
decoder provenance were both fine. The Google TV's `expected_boot_s`/settle constants were never
characterised with `onboard_device.py` either; this is the same debt the Roku still carries.

**Kept rows: Google TV H.264 = +0.619 W (n=2, 0.595–0.643).** That independently reproduces the
+0.59 ±0.05 W (n=3) measured for the same cell in `docs/vp9_oneoff_2026-08.md` §5.2 in August, on a
different night under the older headless regime — a useful check that the corpus and harness are
stable.

### 9.1 What the comparison supports, and what it does not

| box | silicon | H.264 ΔW | idle |
|---|---|---|---|
| Google TV Streamer | MediaTek MT8696 | **+0.619 W** (n=2) | ~1.0 W |
| TV Box W5 | Allwinner H618 | **+1.073 W** (n=3) | ~3.8 W |

**Playing the same file, the W5 costs ~1.7× the Google TV — and idles at roughly 3.8×.** For a box
that sits powered on all day the idle gap is the larger term: ~2.8 W continuous is ~67 Wh/day, which
dwarfs the ~0.45 W playback difference over any realistic viewing schedule.

**Caveats, and they cut in a specific direction.** The two boxes are not in identical states: the GTV
was on Wi-Fi with a dummy plug, the W5 on Ethernet with the panel sink. CR-074 measured the GTV's own
Wi-Fi term at **+0.21 W**, so that confound *inflates* the GTV and the true silicon gap is if anything
wider than shown. The sink difference (dummy vs panel) is unquantified and is the weaker leg — the
dummy plugs are fitted but the no-sink penalty has not been re-measured as absent. One codec, one
content family, n=2 vs n=3. This is enough to say these two boxes are not in the same efficiency
class; it is not enough for a general claim about streaming boxes, and it is not a 4–7× result.

## 10. Settle characterisation (`onboard_device.py`, CR-077)

Run `--reps 3 --hold-s 25 --obs-s 100`; full report `/srv/data/owl/onboard_w5_2026-09-22.md`.

| quantity | value | source |
|---|---|---|
| `idle_w` | **3.69 W** (reps 3.683 / 3.683 / 3.697) | characterised floor |
| `expected_boot_s` | **75** | the live mains-restore test (ADB back at t+65 s), **not** the tool |
| `min_idle_tolerance_w` | **1.0** | see below |

**The tool's boot number is not usable here.** It reported `ready=True after 0.12 s` because the box
was already up when the run started, so it measured nothing. The real figure comes from the
power-cycle test in §5: mains off → on, ADB back unaided at t+65 s, hence 75 s with headroom.

**The tool's `min_settle_s: 96` recommendation was deliberately NOT applied.** It flagged a false
early settle in 2 of 3 reps, but the decay itself is fast — 3.19 s, 3.39 s and 2.13 s. What keeps
violating the guard's 0.5 W band is that this box **spikes periodically at idle**, to ~3.9–4.4 W on a
3.68 W floor, throughout the observation window. Re-running the tool's own settle analysis at a 1.0 W
tolerance collapses the worst rep from **94.91 s to 3.39 s**, and all three then settle in 2–4 s.

So the fix is a **wider tolerance, not a longer wait** — the same conclusion CR-075 reached for the
Apple TV on 2026-08-26, and for the same observed signature (permanent periodic idle spikes).
Applying `min_settle_s: 96` would have spent 96 s of dead time on every W5 row and bought nothing.

This is worth recording as a limit of the tool rather than a fault in it: `onboard_device.py`
correctly detects *that* the guard declares settled too early, but it cannot distinguish "the device
is still decaying" from "the device has a spiky idle", and those need opposite remedies. A human
still has to look at the curve. The cause of the spikes was not investigated.
