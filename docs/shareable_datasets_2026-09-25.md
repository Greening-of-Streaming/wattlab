# OWL — shareable datasets for the Streamscapes project

*Inventory taken 2026-09-25 from GoS1 (`/srv/data/owl/results`, `/srv/data/owl/campaign_*`, repo `docs/`). Counts are live file counts, not estimates. "Runs" = independent measured jobs or rows; "Fields" = distinct leaf keys in the record (JSON) or columns (CSV). Everything measures the device layer only: network, CDN and grid are out of scope, and every row carries its own traffic-light confidence.*

## A. Existing data, shareable now

| # | Name | Date range | What exists now | Runs | Fields | Format · size | Devices / hardware | Sharing notes | Streamscapes fit |
|---|------|-----------|-----------------|-----:|-------:|---------------|--------------------|---------------|------------------|
| 1 | C2 full-field colour draw | 2026-09-24 | 80 s clip of pure-RGB fields (black, white, black, green, red, blue, white, black), played natively on the LG C2 OLED, 1 Hz wall power | 3 runs × 8 fields (303 samples) | 8 per segment + raw trace | JSON (raw traces) + public report page + test clip (225 KB) | LG OLED55C2, Tapo P110 | Public already: https://wattlab.greeningofstreaming.org/static/reports/c2_fullfield_draw_2026-09-24.html | Direct |
| 2 | Consolidated encode dataset (SMPTE 2026) | 2026-05-22 → 2026-08-29 | One tidy CSV of nine encode-energy + VMAF campaigns; every row traceable to a stored result | 569 rows | 19 cols | CSV, `docs/smpte_2026/consolidated_encode_dataset.csv` + data dictionary `.md` | Ryzen 9 7900 (x264/x265/SVT-AV1/VP9), RTX 5080 NVENC, frozen AMD baseline | Cleanest dataset we own; Meridian/BBB/ReadySetGo content, Kranjska numbers only | Indirect (server side) |
| 3 | SMPTE clean sweep | 2026-09-06 → 09-07 | Re-measured n=3 sweep across four contents, two passes, contaminated rows redone | 1 062 rows | 19 cols | CSV, `docs/smpte_2026/clean_sweep_2026-09-06.csv` | as #2 | Feeds the SMPTE paper; share once Tania signs off the paper | Indirect |
| 4 | Decode-rig rows | 2026-07-29 → 2026-09-24 | Client-device decode + play energy with 1 s power traces and a content clock; headless and on-screen modes; 4K/HDR and bitrate-ladder arms; intra-content luma/texture rows (S73) | 909 jobs / 2 120 device-runs | ~1 000 leaf keys | JSON per job, 64 MB; needs a flattening script → CSV | bbox 373 · gtv 365 · firestick 246 · pi5 215 · atv 188 · pi400 169 · c2 154 · xiaomi 129 · xiaomi3 127 · roku 105 · w5 15 | Football-family frames are lab-internal (numbers OK, no pictures); headless rows are a no-sink regime, label them | Direct for the C2 and on-screen rows |
| 5 | /video encode results | 2026-04-10 → 2026-09-25 | Every transcode job run on OWL: CPU vs GPU energy, thermals, ffmpeg command, VMAF where scored | 285 jobs / ~636 encodes | ~800 leaf keys | JSON per job, 5 MB; CSV export pattern exists (ForTania, 124 rows × 37 cols) | GoS1 server | Public-tier data; anonymous visitor runs included | Indirect |
| 6 | Bbox 4K Wi-Fi vs Ethernet campaign | 2026-09-14 → 09-15 | Operator STB receive-path power: Wi-Fi vs Ethernet, idle/menu/video, resolution arms | 119 log files (~30 cells) | per-second W in logs | `.out` logs; summary in memory notes, no CSV yet | Bbox 4K (Marvell Berlin) on Lab-F | Operator device: check with Bouygues before naming it | Indirect (CPE) |
| 7 | Contribution-vs-origin overnight sim | 2026-09-20 | Realtime contribution encodes vs a parallel ladder, gross and delta W, for the 210 kWh passport question | 18 runs (54 files incl. progress/stderr) | JSON per run | `contrib_sim_2026-09-20/runs` | GoS1 NVENC/CPU | Internal until written up | Low |
| 8 | Enhance / upscale results | 2026-06-03 → 2026-09-25 | AI enhancement and upscaling energy with NR-VQA and FR anchors; degraded-source corpus (27 files) | 154 jobs | ~500 leaf keys | JSON, 2 MB; degraded corpus 27 clips | RTX 5080 CUDA | Pixop pipeline involved: confirm with Pixop before sharing model names | Low |
| 9 | LLM / RAG runs | 2026-04-09 → 2026-09-05 | mWh per token, cold vs warm, model ladder, RAG faithfulness on the REM corpus | 102 jobs / 106 runs | ~720 leaf keys | JSON, 1.1 MB | RTX 5080, Ollama ladder | Board steer: AI stays tethered to streaming | Low |
| 10 | Image-generation runs | 2026-04-07 → 2026-09-05 | Wh per image, CPU vs GPU, four diffusion models | 36 jobs | ~440 leaf keys | JSON, 39 MB (includes images) | RTX 5080 / CPU | Fine to share numbers; images are generated | Low |
| 11 | REM prep + dual-meter diagnostics | 2026-06-23 → 2026-09-24 | REM field-meter preparation runs; calibration and dual-meter pre-tests; recovery logs | 47 + 11 jobs | 160–200 leaf keys | JSON | Tapo P110 ×2, Shelly | Calibration provenance, useful as method evidence | Low |
| 12 | Published findings | 2026-05 → 2026-09 | Fourteen finding markdowns, each citing a stored result, strict schema, traffic-light rated | 14 | — | Markdown, `docs/findings/`; live on `/findings` | mixed | Already public on the site | Two are screen-related (#4 lineage) |

## B. Easy to create (one script or one overnight each)

| # | Name | Effort | What it would give | Builds on |
|---|------|--------|--------------------|-----------|
| 13 | Colour and luminance sweep on the C2 | one overnight | Grey ramp (0–100 % in steps), saturation ramps per primary, HDR versions of the same fields; per-field W at n=3 | #1 script + wrapper |
| 14 | Same colour clip on every screened rig device via HDMI into the C2 | one evening | Separates the box's contribution from the panel's: GTV, Apple TV, Roku, Xiaomi Gen 3 | #1 clip, rig screen mode |
| 15 | Per-second luma/texture vs panel power on real content | half a day | The S73 content-clock rows and the Nov-25 luma pipeline scripts already exist; needs one shared export with a data dictionary | #4, `data_analysis_nov25/` |
| 16 | Flattened decode CSV with data dictionary | half a day | One CSV over all 2 120 device-runs: device, codec, mode, sink, W, ΔW, n, confidence | #4 |
| 17 | Public `/video` export refresh | one hour | ForTania-style CSV over all 636 encodes with the current column set | #5 |

## C. Not for sharing

- Member export CSV and visitor analytics: personal data.
- Football-family pictures (lab-internal licence): provenance lines and numbers only.
- Kranjska frames: licence terms not on file; numbers only.
- `settings.json`, calibration secrets, meter credentials.

---

## Long descriptions

**1. C2 full-field colour draw.** On 24 September we asked the C2 OLED to show eight ten-second fields of pure colour and metered the whole TV at the wall once a second, three times over. The panel draws 37 W showing black, 90 W showing white, and 95 to 106 W showing a single primary, red being the most expensive. That order surprises people until they remember the C2 is a WOLED: a white field lights the dedicated white sub-pixel, while a pure primary drives a single colour sub-pixel flat out. The report page carries the chart, the per-run numbers, the method, the 80 s test clip and a player page that autoplays it full screen in a TV browser, so anyone with a plug meter can repeat it on their own set.

**2. Consolidated encode dataset.** The spine of the SMPTE 2026 paper: 569 encodes across Meridian, Big Buck Bunny, Kranjska Gora downhill and ReadySetGo, at typical ABR ladder rungs, at matched bitrates and at matched VMAF, on CPU software encoders and on NVENC. Each row gives the target and achieved bitrate, VMAF, watt-hours per minute of content, the power delta above idle, the repeat count and the confidence rating, and names the stored result it came from. The accompanying markdown explains the nine source campaigns and their caveats.

**3. SMPTE clean sweep.** The September re-measurement that brought every condition in the paper to n=3: 1 062 rows over four contents and two passes, with rows contaminated by background activity identified and redone. Same columns as the consolidated dataset. It belongs with the paper, so sharing waits for Tania's sign-off.

**4. Decode-rig rows.** The largest store: 909 jobs and 2 120 device-runs from the client-device bench, July to now. Ten boxes have been measured, from Raspberry Pis and a Fire TV stick to the Apple TV, Roku, two Xiaomi generations, the Bouygues Bbox and the C2 itself as a native player. Each run carries a one-second power trace, the device and codec, whether a screen was attached (headless rows are a different regime and say so), and for the September runs a content clock that lets per-second power be lined up with the luma and texture of the frame being shown. The 4K/HDR and bitrate-ladder arms and the football sports tier live here. It is JSON per job today and needs a flattening pass to become a spreadsheet.

**5. /video encode results.** Everything anyone has run on the public `/video` page since April: 285 jobs, about 636 individual encodes, each with CPU or GPU energy, thermals, the exact ffmpeg command and VMAF where the run scored it. A one-night export of this already exists as the ForTania spreadsheet, which is the template for a fuller one.

**6. Bbox Wi-Fi campaign.** Two days in mid-September measuring the operator set-top box on Wi-Fi and on Ethernet, idle, in the menu and playing video, at HD and 4K. Findings: the Wi-Fi receive path costs a fraction of a watt and nothing at idle, while resolution dominates. Still in log form; a CSV is a small job. The box is an operator's device, so naming it publicly is a call for Bouygues.

**7. Contribution-vs-origin simulation.** One overnight run answering whether a realtime contribution encode or a parallel ladder is the better use of a kilowatt-hour, gross and net of idle. Eighteen runs, internal until written up.

**8 to 11.** The AI and enhancement stores (upscaling, LLM, RAG, image generation) and the REM preparation and calibration diagnostics. All shareable as numbers, all off the Streamscapes topic. The upscaling set involves the Pixop pipeline, so check with Pixop before model names go out.

**12. Findings.** Fourteen short published findings, each pointing at a stored result and rated on the traffic-light scale. Two are about client decode on screens and are the nearest prior work to the colour question.

**Easy additions (13 to 17).** The colour work is a one-script job now, so a grey ramp, saturation ramps and HDR variants are one overnight away, and running the same clip through the HDMI boxes into the C2 would show how much of the draw is the box and how much the panel. The per-second luma-versus-power analysis already exists in code from November 2025 and September 2026 and only needs a tidy export. The decode and video stores each need one flattening script to become spreadsheets with a data dictionary.
