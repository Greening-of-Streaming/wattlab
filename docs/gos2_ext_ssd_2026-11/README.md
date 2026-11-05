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
  OWL's own pipeline, so it is only indicative. The post-disk benchmark is the proper comparison.
- **Limits:** the source was served mostly from page cache, so the external arm is largely a write-side test. A job that
  keeps the external disk continuously busy could approach the 0.4 W above, about +18 % on this ΔE (inference, not
  measured). The `nice -n -5` prefix was left out so a non-root failure could not abort the unattended run.

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
