# GoS2 external SSD: power implications (night of 4–5 November 2026)

Disk: 2 TB Fanxiang S690Q NVMe in a Ugreen USB4 enclosure, bus-powered, APFS `GoS2-Ext`, empty.
Meter: GoS2 inner P110 at 1 Hz, OWL's poller paused. Scripts in this folder; raw data on GoS1 in
`/srv/data/owl/campaign_2026-11-04_gos2_ext_ssd/` (`trials_run.jsonl`, `run.log`).

## Result in one paragraph

The disk's cost is almost all floor, not activity. Attached and mounted, it takes GoS2's idle from 1.33 W to 7.80 W,
nearly six times as much. Software can remove only 1.6 W of that (eject); only unplugging removes the rest.
Encode ΔE barely moves when the job stays on the internal SSD. With source and output on the external SSD,
ΔE rises about 5 %. Gross energy per job rises far more, because the floor is in it.

## Idle floor

| State | Idle W | Note |
|---|---|---|
| No disk (rows 1–4, October 2026) | ~1.33 | Not re-measured this campaign, needs an unplug |
| Plugged, ejected | 6.189 | 2 clean 6-min windows (6.194, 6.184); third excluded, CPU idle 82 %; 15 encode baselines agree (6.17–6.21) |
| Plugged, unmounted only | ~7.86 | 5-s `/live` readings, no formal window; same as mounted |
| Plugged, mounted | 7.804 ± 0.008 | n = 3 windows; design doc row 5 gave 7.824 ± 0.019 |

- **Attached cost:** +6.47 W mounted, of which 1.62 W goes on eject and 4.86 W stays.
- **Per year, if left attached:** about 57 kWh mounted, about 43 kWh ejected (6.47 W and 4.86 W × 8,760 h).
- **No software off switch found:** the enclosure stays enumerated after an eject, and `diskutil mountDisk` restores the
  volume without a replug. Row 5's 40 minutes show no sleep benefit from `pmset disksleep 10`.
- **CPU is not the cause:** cluster idle ratios are comparable in both states (E 0.90–0.98, P 0.97–1.00).
- **Attribution limit:** `powermetrics` reports zero energy on this M6 / macOS, so the split between the Mac's USB4
  controller and the enclosure (bridge + NVMe) is not measured. An inline USB-C power meter would answer it.

## Disk activity

Same job on both disks: 1 MiB sequential, incompressible data, cache bypassed, 20 GiB file, shuffled, n = 3. ΔW is the
job against the last 15 s of its own baseline, with the first 5 s of the job dropped. Read and write are within error
at the paced rates, so they are shown together.

| Rate | Internal ΔW | External ΔW | Internal J/GB | External J/GB |
|---|---|---|---|---|
| 10 MB/s | +0.07–0.08 | +0.47–0.48 | 7–8 | 47–48 |
| 100 MB/s | +0.19 | +0.86 | 1.9 | 8.6 |
| Flat-out read | +9.64 ± 0.45 (6.7 GB/s) | +6.54 (2.7 GB/s, n = 2) | 1.43 | 2.42 |
| Flat-out write | +9.21 ± 0.05 (6.1 GB/s) | +6.84 ± 0.04 (2.9 GB/s) | 1.50 | 2.39 |

- **Waking the external path costs about 0.4 W extra**, even at a trickle. Per GB it costs 1.6–6 times the internal
  path, worst at low rates.
- **Internal after-burn:** all three internal flat-out writes were followed by about 30 s at ~10.1 W (+2.3 W) after the
  job had returned. External writes showed none. Cause not established.
- **One unexplained event:** a spike to 9.7 W in the baseline before one external flat-out read (02:14). That trial is
  excluded (n = 2 above). The other flat-out baselines were clean.

## Speed

Flat-out trials, 1 MiB sequential at queue depth 1, cache bypassed, 20 s, n = 3.

| Direction | Internal MB/s | External MB/s | Internal / external |
|---|---|---|---|
| Read | 6,719 (6,601–6,782) | 2,657 (2,569–2,701) | 2.5 × |
| Write | 6,132 (6,106–6,147) | 2,856 (2,851–2,859) | 2.1 × |

- **Preparing the 20 GiB files agreed:** 6,031 MB/s internal and 2,916 MB/s external.
- **Encode time did not change:** 234–236 s in every arm, because 484 MB over 235 s is only about 2 MB/s.
- **Not measured:** random I/O, latency, and writes longer than 20 s (about 57 GB per external trial). Speed could fall
  on a longer external write.

## Encode

OWL's Apple hardware HEVC command on `meridian_120s` looped to 16 min (1080p, 4 Mb/s, 484 MB out), n = 5 per arm,
interleaved, 90 s baseline before each. Durations were the same in all arms, 234–235 s.

| Arm | Base W | ΔW | ΔE Wh | Gross Wh |
|---|---|---|---|---|
| Internal, disk mounted | 7.818 | 2.285 ± 0.012 | 0.1488 ± 0.0008 | 0.658 |
| External source + output | 7.805 | 2.395 ± 0.021 | 0.1564 ± 0.0011 | 0.666 |
| Internal, disk ejected | 6.189 | 2.324 ± 0.045 | 0.1514 ± 0.0030 | 0.555 |

- **External vs internal:** ΔE +0.0076 ± 0.0018 Wh (+5.1 %). This is real, well above the 1.37 % calibration spread.
- **Ejected vs mounted:** ΔE +1.8 % ± 2.3 %, not distinguishable. The baseline subtraction removes the floor correctly.
- **Comparison with no disk:** an October run through OWL read ΔW 2.26 W, ΔE 0.1441 Wh on the same settings, but through
  OWL's own pipeline, so it is only indicative. See the full benchmark below.
- **Limits:** the source was served mostly from page cache, so the external arm is largely a write-side test. A job that
  keeps the external disk continuously busy could approach the 0.4 W above, about +18 % on this ΔE (inference, not
  measured). The `nice -n -5` prefix was left out so a non-root failure could not abort the unattended run.

## Full benchmark with the disk attached

Benchmark `aceb9402` and thermal probe `bd1415ba`, 5 November, against `gos2-387264bb`, 10 October, with the disk mounted
but unused. Same config, ffmpeg 9.0.2, macOS 27.0.1 and encode commands. The runs are 26 days apart, so ambient and
OWL version also differ.

| Source, codec, engine (n = 10) | ΔE Oct Wh | ΔE Nov Wh | Change | Gross Oct Wh | Gross Nov Wh |
|---|---|---|---|---|---|
| meridian H.264 hw | 0.1816 | 0.1751 | −3.6 % | 0.192 | 0.219 |
| meridian H.265 hw | 0.1847 | 0.1825 | −1.2 % | 0.195 | 0.231 |
| meridian H.264 CPU | 0.4967 | 0.4928 | −0.8 % | 0.524 | 0.584 |
| meridian H.265 CPU | 0.7361 | 0.7207 | −2.1 % | 0.762 | 0.857 |
| meridian AV1 CPU | 0.3837 | 0.3789 | −1.2 % | 0.396 | 0.450 |
| bbb H.264 hw | 0.1866 | 0.1814 | −2.8 % | 0.194 | 0.226 |
| bbb H.265 hw | 0.1924 | 0.1875 | −2.5 % | 0.201 | 0.236 |
| bbb H.264 CPU | 0.4163 | 0.4033 | −3.1 % | 0.430 | 0.476 |
| bbb H.265 CPU | 0.6973 | 0.6814 | −2.3 % | 0.721 | 0.813 |
| bbb AV1 CPU | 0.4485 | 0.4435 | −1.1 % | 0.463 | 0.520 |

- **ΔE did not inflate.** All ten fell, by 0.8–3.6 %, with durations unchanged. The cause is not established. Lower
  mains-to-DC losses at a higher floor would fit, and so would ambient over 26 days. Treat October and November ΔE as
  comparable to about 4 %, not as identical.
- **Gross rose 11–19 %** on these short encodes, because the floor is in it.
- **Image:** the three shared models agree within about 2 % on the three settled prompts. FLUX.2 Klein is new in the panel
  (0.11–0.12 Wh per image), which is why the step took longer.
- **LLM:** not comparable. The panel's models changed on 28 October.
- **Thermal recovery unchanged:** power is within 0.14 W of floor at OWL's 35 s cooldown and settled by about 50 s, as in
  October. `video_cooldown_s` can stay at 35.

### Calibration (n = 30)

| | Pre-disk, 10 Oct | With disk, 5 Nov |
|---|---|---|
| `variance_pct` | 1.37 % | 0.88 % |
| Idle CV | 2.57 % (0.035 W) | 0.69 % (0.055 W) |
| Idle drift | 4.40 % (0.060 W) | 1.51 % (0.120 W) |
| CPU encode CV | 1.12 % | 1.21 % |
| GPU encode CV | 0.43 % | 0.74 % |
| Mean baseline | 1.371 W | 7.947 W |

**The lower percentages are not a quieter rig.** They are relative to a base nearly six times larger, and idle noise and
drift are higher in watts. Drift enters OWL's confidence model as an absolute term, so the smallest ΔW that can reach green
rises from about 0.12 W to about 0.20 W. Only very light jobs are affected.

### Internet outage during the run

A Bouygues outage ran from about 10:41 to 10:46, during bbb rep 6. Poll counts in that rep are normal and both meters
agree. One encode in it, H.265 CPU, is 2.7 % below its siblings, a 0.3 % effect on that row's mean. No step failed and nothing
was re-run.

## What this means for OWL

1. **Keep measured jobs on the internal SSD.** Scratch, source and output on the external disk cost about 5 % in ΔE, and
   mixing would make GoS2 runs non-comparable. The external disk suits archive and cold data.
2. **Gross figures for GoS2 nearly triple on this encode.** Estimated no-disk gross is 0.24 Wh
   ((1.33 + 2.29) W × 235 s) against 0.66 Wh attached. Any GoS2 gross figure must state the disk.
3. **Do not leave it attached for headline GoS2 idle numbers.** Its idle (7.8 W) no longer shows what the Mac mini draws.
4. **Eject helps a little, unplug helps fully.** A switched USB hub or plugging in on demand is the only way to the 1.33 W floor.

## Method notes

- Campaign bug: the automatic launch of the benchmark failed on a malformed ssh command (`rc 2`). It was launched by hand
  at 05:12, within 5 minutes of the planned time. Fixed in the copy here.
- `analyse.py` is the first pass. `analyse_b.py` is the one the tables use, because its baselines avoid the after-burn.
