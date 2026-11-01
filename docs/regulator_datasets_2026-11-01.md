# GoS datasets for ARCEP / BEREC: what we have, what we could easily create

*Inventory taken 2026-11-01 on GoS1. It updates `docs/shareable_datasets_2026-09-25.md` (written for Streamscapes) and is re-targeted at telecom regulators. Every number below is copied from the file named in its row. Counts are live file counts.*

**Read this first**
- **Energy only.** We measure W and Wh, never CO2e. Each dataset measures one layer, and the layer is named in its row. We measure the device layer (server, box, screen, home network kit). We do not measure the network, the CDN or the data centre.
- **Status labels.** 🟢/🟡 = traffic-light confidence on the claim. **Published** = live on `/findings` or the GoS website. **Draft** = not yet lab-reviewed (Tania). **Internal** = not written up.
- **Sharing bar.** n = 3 is the minimum for anything that leaves the room (WattLab call 2026-09-03). The n column shows which rows meet it.
- **Two arms.**
  - **Lab** = OWL: the GoS1 server (Ryzen 9 + RTX 5080), the GoS2 Mac mini M6, and a 10-device client rig.
  - **Field** = REM: a Tapo P110 plug fleet in volunteers' homes, read through the TP-Link cloud at 1 W resolution. Plus LEM: local mW polling of the same plugs, as macOS/Windows apps.

---

## 1. Lab (OWL): datasets we have, grouped by regulator question

### 1a. The screen vs the box: where a viewer's energy goes

| Dataset | What was measured | n · status | Headline (exact, from source) | Source |
|---|---|---|---|---|
| TV screen vs streaming box | LG C2 OLED + 7 boxes, HD/4K, SDR/HDR, both metered at the wall | n=3 🟢 · Draft | The box is "3.3–4.5 % of the pair at the wall, across HD/4K and SDR/HDR" | `docs/findings_drafts/tv-screen-draws-20x-the-streaming-box.md` |
| TV picture modes | LG C2 + Google TV, 5 picture modes, football and an ad break (2026-10-10) | n=3 (one cell n=2) · Draft | Vivid − Standard "+20.36 W [95 % CI 19.93–20.79]"; Eco 52.94 W vs Standard 52.69 W, so Eco saved nothing here; the box stayed "flat at 1.79–1.88 W throughout" | `docs/findings_drafts/tv-picture-mode-outweighs-streaming-choices.md`; raw `/srv/data/owl/campaign_2026-10-10_c2modes/` |
| HDR costs the screen, 4K costs the box | UHD/HDR campaign: 7 boxes + the LG C2 (2026-10-04) | n=3 🟢 · Draft | "HDR adds 3.7–4.4 W (7–8 %) at an OLED screen and nothing at six of seven boxes"; "4K adds 0.28–1.07 W (11–21 %) at every box" | `docs/findings_drafts/hdr-costs-the-screen-4k-costs-the-box.md`; `/srv/data/owl/campaign_2026-10-04_uhd_hdr/ANALYSIS.md` |
| Full-field colour draw | LG C2 showing pure-colour fields (2026-09-24) | n=3 · **Published** (report page) | "37 W showing black, 90 W showing white, and 95 to 106 W" for single primaries | wattlab.greeningofstreaming.org/static/reports/c2_fullfield_draw_2026-09-24.html |
| TV standby | LG C2 in standby | single figure | "9.7 W" | `docs/intra_content_sync_2026-09-03.md`:632 |

### 1b. Set-top boxes and streaming devices: what the content choice costs at the viewer

| Dataset | What was measured | n · status | Headline | Source |
|---|---|---|---|---|
| **Decode-rig store** (the master dataset) | 1,088 jobs / 2,668 device-runs, 2026-07-29 → 10-22. Devices: GTV 485 · Bbox 479 · Fire TV 314 · Apple TV 285 · Pi 5 244 · Xiaomi Gen 3 206 · Pi 400 182 · LG C2 158 · Xiaomi Gen 2 145 · Roku 121 · TV Box W5 15. Each run has a 1 s power trace. | mixed | Up from 909 jobs / 2,120 device-runs on 09-25. JSON per job (69 MB); needs flattening to CSV. | `/srv/data/owl/results/decode/` |
| Hardware decoder vs software | Client decode on the rig boxes | 🟢 · **Published** | "3.7× rt / 4.6× sat" | `docs/findings/hw-decoder-cuts-client-energy-4x.md` |
| Codec the chip lacks (Apple TV 2017) | AV1/VP9 software fallback | n=3, 3 contents 🟢 · **Published** | AV1 "+1.19 W (+29 %)" | `docs/findings/appletv-a10x-av1-vp9-software-fallback.md` |
| Bitrate barely moves box power | H.264 1080p60 ladder 0.25 → 32 Mb/s, 4 boxes | n=3 🟢 · Draft | "10–17 mW per Mb/s"; "+0.30 to +0.53 W" across the whole 128× span | `docs/findings_drafts/bitrate-barely-moves-box-playback-power.md` |
| Encode settings vs playback power (e2e pilot) | 17 single-parameter encodes of one title, each played on 5 boxes (09-27/28) | n=3 · Internal | On hardware decoders, no encode setting moved playback power by more than ~0.1 W. Frame rate 60→30 fps: −0.10 to −0.22 W (Android), −1.04 W (Apple TV). | `/srv/data/owl/campaign_2026-09-27_e2e_pilot/E2E_REPORT_2026-09-28.md` |
| Decoder-friendly encodes (x264 fastdecode, SVT-AV1 fast-decode) | Software decode on Pi 5 / Apple TV, hardware-decode controls (10-10 → 10-12) | n=3 · Internal | x264 fastdecode: "+25 % bits … against −0.60 ±0.24 W decode ΔW on a Pi 5"; AV1 fast-decode=2: Pi 5 "−0.057 ±0.030 W (−1.3 %)", hardware boxes flat | `/srv/data/owl/campaign_2026-10-10_fastdecode/RESULTS_encode.md`; `/srv/data/owl/campaign_2026-10-11_av1fastdecode/RESULTS.md` |
| VVC (H.266) playback | M6 software vs hardware decode; Pi 5 (10-22) | 🟡 · Internal (MHV'27 pilot) | M6 VVC software "+1.23 W" vs "+0.17 W" hardware; "Pi 5 cannot decode this … VVC stream in real time", and trying costs "+4.94 W" | `docs/digests/mhv27-vvc-pilot.md` |

### 1c. The home network path: Wi-Fi vs Ethernet ⚑ BEREC

| Dataset | What was measured | n · status | Headline | Source |
|---|---|---|---|---|
| Operator STB: Wi-Fi vs Ethernet | Bbox 4K. Wi-Fi vs Ethernet at idle and in the menu, local file vs streamed, SD → 4K (09-14/15, 99 jobs) | n=2–3 · Internal | Streamed rows: Wi-Fi "+0.16/+0.21/+0.25 W" (10/20/35 Mb/s). Idle and local-file rows are identical on both interfaces. Quoted range across sessions: "0.15–0.5 W". The 1080p → 2160p step (+1.34 W) is not a Wi-Fi effect. | `/srv/data/owl/campaign_2026-09-14_bbox_wifi/OVERNIGHT_REPORT.md` |
| Network-path survey (CR-074) | Wi-Fi / Ethernet / local file, burst vs paced, across rig boxes (08-18/19) | indicative · Internal | GTV "+0.21 W"; "Ethernet and an idle radio cost nothing". The earlier Bbox "+0.98 W" is superseded by the September campaign above. | `docs/netpath_2026-08-18/README.md`; CHANGE_REQUESTS.md CR-074 |
| **Open question:** does a wired box switch its Wi-Fi radio off? | `dumpsys` shows Wi-Fi "enabled, just disconnected/idle" on the Bbox and the GTV | no power measurement yet | Not a claim yet. The Bbox report cannot tell "a dearer Wi-Fi receive path" from "a box that powers its radio down more completely". | memory note `wifi_radio_power_investigation.md`; Bbox report §6 |

### 1d. Standby and HDMI behaviour

| Dataset | Headline | Source |
|---|---|---|
| Standby via HDMI-CEC | GTV "1.16 → 0.94 W" and "did not wake when the panel woke"; Fire TV "1.46 → 1.15 W" | `docs/hdmi_sink_regime_2026-09-05.md` §6 |
| Sink regime | A mismatched-resolution dummy plug "costs 0.54 W" on MediaTek boxes (a measurement trap, and a real-world one) | same doc |

### 1e. Head-end / encode side (server layer, not data centre)

| Dataset | What | n · status | Headline | Source |
|---|---|---|---|---|
| Consolidated encode dataset | 569 encodes, 9 campaigns, VMAF + Wh/min, CSV with data dictionary (05-22 → 08-29) | n≥3 · SMPTE paper | Cleanest dataset we own | `docs/smpte_2026/consolidated_encode_dataset.csv` |
| SMPTE clean sweep | 1,062 rows, 4 contents, n=3 (09-06/07) | n=3 · shared once Tania signs off | — | `docs/smpte_2026/clean_sweep_2026-09-06.csv` |
| /video encode store | 967 jobs (04-10 → 10-28): GoS1 625 · GoS2 342. Was 285 jobs on 09-25. | mixed | JSON; the ForTania CSV template exists | `/srv/data/owl/results/video/` |
| Codec × preset × silicon | NVENC, x264/x265/SVT-AV1 on Ryzen, Apple M6 (10-21) | "72/72 rows 🟢" · Internal | "x264 medium 0.370 vs NVENC H.264 0.122 = 3.0×"; SVT-AV1 p3 = 9.3× x264; NVENC HEVC "p7 = 3.3× p1, same VMAF" | `/srv/data/owl/campaign_2026-10-21_m6_swcodecs/RESULTS.md` |
| Encode levers: NVENC vs Apple M6 | Preset/parameter sensitivity on two silicon families (10-12/13) | n=3 · Draft | M6 is "5.1× (H.264) / 5.4× (H.265) less marginal energy"; live encodes "43–61× less above idle" | `docs/findings_drafts/encode-energy-levers-nvenc-vs-apple-m6.md` |
| VVC encode | VVenC vs x265 (10-22) | Internal (MHV'27) | "55 % fewer bits than x265 … for 10.3×" the energy (Meridian), "18× and 47×" (football) | `docs/digests/mhv27-vvc-pilot.md` |
| ML enhancement vs bitrate | Pixop super-resolution vs plain upscale (10-18) | Internal | "12–14× a plain upscale at the head-end"; "Bitrate moves encode energy by ~0–3 %" | `docs/enhance_bitrate_2026-10/README.md` |
| Contribution vs origin ladder | 18 overnight runs (09-20) | Internal, gross W only | No ΔW write-up yet | `/srv/data/owl/contrib_sim_2026-09-20/` |

### 1f. AI tethered to streaming (low regulator priority)

LLM: 186 results (84 since 09-25, 64 of them on GoS2). Image generation: 145 (109 since 09-25). Apple-native stacks on the M6 (n=3 🟢, Draft): MLX image generation uses "12 % MORE energy per image"; gpt-oss uses "0.1524 ± 0.0019" vs "0.1260 ± 0.0022" mWh/token (−17 %). Source: `docs/findings_drafts/apple-native-stacks-on-m6-flux2-gpt-oss.md`.

### 1g. Method evidence (useful when a regulator asks "how sure are you?")

- **Dual-meter daisy chain** on GoS1 (CR-065). **Variance calibration:** idle 1.84 %, n=20. **Traffic-light confidence:** Φ(ΔW/SE), raw samples kept in every result.
- **GoS2 idle floor:** "1.325 W ± 0.076 W", unchanged across four software-install checkpoints (`docs/gos2_design.md`).
- **P110 refresh audit** (`docs/decode_p110_refresh_audit_2026-10-06.md`): below ~12 W the plug refreshes every ~2 s while we poll every 1 s. "42 of 2,381 flags change (1.8 %)", "No published claim changes". Re-flagging is pending Tania; earthed plugs are ordered.

---

## 2. Field (REM / LEM): datasets we have

| Dataset | Scope | Resolution | n · status | Headline (exact) | Source |
|---|---|---|---|---|---|
| REM fleet | 61 registered plugs (2026-07-23: 37 online). TVs (OLED, LCD, plasma, 8K QLED), 6 set-top boxes, routers/mesh, encoders/servers. Prod DB from 2026-02-08. | cloud, 1 W, 10–30 s | inventory | No ONT metered. The fleet history since 02-08 has never been analysed. | `/srv/data/owl/worldcup-2026-07/device_registry.json`; prod DB on Linode (not queried) |
| C1: Nov 2025 hackathon rerun | TNO servers + ~4 TV models, 13 contributors | cloud 10 s / 1 W; server PDU 4 s | 🟡 · **Published** (GoS ref [2]) | "resolution accounts for ~55 % of the observed variance in encoding power"; device shifts "1–4 % (largest 3.71 %)" | `smpte-4951/digests/2025-11-cycle.md` |
| Home gateway (hackathon #4c, Feb 2025) | One tester's home router | 20 s | n=1 · **Published** (ref [2]) | "Router power usage fluctuated between 4W (idle) and 8W (streaming)"; "not able to discern any significant impact on the (home) gateways we tested" | ref [2] PDF |
| C3: World Cup 2026 | 3 matches (06-26, 07-07, 07-19), 4–8 active TVs, 4 markets (FR, UK, CA, US) | cloud 10 s / 1 W, 938–1,216 samples per device per session | public digest | Ad breaks: "W-per-step ×2–3 … mean within −2 to −6 %"; 8K set "423 W mean on the final" vs 301 W SDR | `smpte-4951/digests/2026-07-worldcup.md`; raw `/srv/data/owl/worldcup-2026-07/` |
| C4: Summer hackathon 2026-07-08 | 5 households, 10 plugs, 80 min | cloud 10 s, "all 4,811 samples are whole watts" | 🔴 · public digest | Codec/bitrate deltas all span zero (e.g. OLED "−0.03 W [−0.36, +0.31]"); STBs "read only the values 1, 2, 3 W" | `smpte-4951/digests/2026-summer-hackathon.md` |
| C8/R2: cloud vs local accuracy | 3 plugs; LEM at 10 s and 1 s (mW) vs REM cloud (08-25) | mW | public digest | LEM path "within 1–3 % at 10 s and 0.2 % at 1 s"; cloud reads "−11.4, −11.4, −11.1 % … −9.1 %" low | `smpte-4951/digests/2026-08-r2-dual-capture.md` |
| LEM field uploads | Volunteer groups (07-23/24, 07-26, 07-30) | mW, 1–2 s | Internal | Never analysed; counts not found | `smpte-4951/digests/2026-07-cycle.md` |

**Why the field arm needs LEM for regulator questions.** The cloud path reads in integer watts and averages about 0.5 W low. That is "10–25 %" of a 2–4 W STB but "0.3 %" of a 150 W TV. So REM-cloud is fine for TVs and useless for STB or router standby. LEM (mW, 1 s) fixes this.

---

## 3. Could easily create (existing tools; effort as the docs state it)

### Lab (OWL)

| # | Dataset | Regulator question | Effort | Builds on |
|---|---|---|---|---|
| L1 | **Wi-Fi radio power-down check**: local-file + radio-off controls on the Google TV (the "future run" named in the Bbox report); Xiaomi "Mobile data always active" toggle before/after | BEREC: does a wired box still pay for its radio? | not stated; described as a "quick before/after power check" | `wifi_day.py`, Bbox protocol |
| L2 | **Standby/CEC sweep across all rig boxes + panel** | Standby and networked-standby draw | not stated | `docs/hdmi_sink_regime_2026-09-05.md` method |
| L3 | **Flattened decode CSV + data dictionary** (2,668 device-runs) | The shareable master table | half a day | decode store |
| L4 | **Bbox Wi-Fi campaign as CSV** | Operator-CPE data in a tidy table | a "small job" | Bbox logs |
| L5 | `/video` encode export refresh (967 jobs, both nodes) | Head-end energy table | one hour | ForTania CSV template |
| L6 | Frame-rate and resolution levers replicated on football + Meridian, panel metered | Do the per-viewer levers hold beyond one cartoon? | about one night | existing sweep script |
| L7 | CR-079: HD/4K ladder × resolution, 18 variants × 10 devices, with VMAF | The resolution/bitrate cost curve per device | not stated (dry run first) | CR-079 |
| L8 | CR-080: decode-stack survey | Which player app/stack the device uses, and what it costs | one night | CR-080 |
| L9 | C2 grey ramp / saturation / HDR fields; the same clip through each box into the C2 | Screen share, box vs panel | one overnight / one evening | colour clip + script |
| L10 | GoS1 sleep vs shutdown draw; GoS2 Wi-Fi vs Ethernet idle | Small-server standby | "measurable", not costed | CR-085 Phase 3 |

### Field (REM / LEM)

| # | Dataset | Regulator question | Effort | Notes |
|---|---|---|---|---|
| F1 | **Home router / mesh: standby vs streaming** with LEM on the router and mesh plugs already in the fleet | Home-gateway energy and the effect of traffic | not stated for LEM on existing plugs; a dedicated gateway meter is "L (staged)" | The only prior point is #4c (4 W idle → 8 W streaming, n=1) |
| F2 | **STB standby vs deep standby** (Tapo + LEM only; Shelly is "unreliable for STB standby") | Networked standby (EU Ecodesign) | not stated | The cloud path cannot do it (1–3 W readings) |
| F3 | **Wi-Fi vs Ethernet at home**: the bench result cross-checked in volunteers' homes | BEREC, real homes | not stated | Open CR-074 item. LEM on home Wi-Fi is "remains to be validated". |
| F4 | **TV viewing-hours profiles** from the REM history since 2026-02-08 | Real-world TV usage and draw | analysis not done; needs a prod-DB query. Fleet-wide pause fix ("Mid" focus) is "~2–3 hours". | Integer W is fine at TV scale |
| F5 | Hackathon kits (Pi + LEM + join code) for a regulator-hosted or member-hosted cycle | More households at mW resolution | Effort M | `docs/TOOLSET_STRATEGY.md` S2 |

---

## 4. Handle with care before sharing

- **Operator naming.** The Bbox is Bouygues CPE: "check with Bouygues before naming it". With ARCEP in the room this matters more than usual.
- **Field privacy.** REM device aliases contain people's names and places, so share them only aggregated or pseudonymised. No consent or GDPR handling was found in the REM/LEM repos. A July REM audit flagged committed secrets, exposed ports and 90-day destructive retention. Expect the regulator to ask about this.
- **Content licences.** No pictures from the football family or Kranjska; numbers only.
- **Not lab-reviewed.** Every "Draft" and "Internal" row needs Tania before it is quoted outside the room.
- **Rig caveats.** Rows use Just Player, not service apps. Some sinks are headless or dummy plugs, so group rows by `sink`. Presented frame rate is not sampled automatically: a box can show a "green" row while playing at 1.7 fps.
- **Missing field metadata.** Picture mode, HDR state, firmware and feed type were not logged in any 2026 field session.

## 5. What changed since the 2026-09-25 inventory

- **Decode store:** 909 → 1,088 jobs, 2,120 → 2,668 device-runs. Items from 09-26 on: the UHD/HDR campaign (10-04), picture modes (10-10), the e2e encode→play pilot (09-27/28), fast-decode arms (10-10/11), the VVC pilot (10-22). The TV Box W5 was onboarded (15 runs).
- **Encode store:** 285 → 967 jobs. The second node, GoS2 (Apple M6), went live in October and added 342 encodes. Codec×preset×silicon and NVENC-vs-M6 campaigns ran.
- **Four screen/CPE draft findings** (10-16), regulator-relevant: screen ≈ 20× the box, HDR costs the screen, 4K costs the box, bitrate barely moves the box.
- **No new field data since July/August.** The REM fleet keeps logging to the prod DB, unanalysed.
