# decode-bench — portable CPE decode/playback energy harness

One protocol (identical to `stb-decode-2026-07`: settle → baseline → start → startup-skip →
sample window → stop → OWL `confidence.py` → per-row checkpoint), pluggable devices via
JSON config. New rows are directly comparable with the July Google TV panel.

```
python3 bench.py configs/gtv_smoke.json      # Google TV, one 90 s validation row (CLI path)
python3 bench.py configs/pi4_matrix.json     # copy configs/pi_matrix.json.example, fill host + meter
```

**Since S59 (2026-07-30) the normal path is OWL's `/decode` Lab console** (`wattlab_service/rig.py` +
`decode_run.py`): templates → per-device bench configs → one `bench.py` subprocess per device in
parallel, envelopes under `results/decode/`, campaigns collated at `/decode/batch/{id}` (CR-073). The
CLI path above still works for stand-alone runs but bypasses the queue, the plug-pause hand-off and
the envelope; only use it when the rig poller is not watching the same plugs.

Results (CLI) land in `results/<config name>.json` (raw samples included, resumable).
Streams: `streams/` (→ `/srv/data/owl/stb-decode-2026-07/streams`, ~40 GB): the matched-VMAF
(~92–93, v1) 1080p NVENC loop families (`<fam>_<codec>_{20,60}min.mp4`, fams bbb/meridian/kranjska),
the **iso-bitrate software-encoded family** `<fam>iso_<codec>_20min.{mp4|webm}` (2026-08-17, VP9 as
WebM+Opus — MP4/vp09 stalls the GTV player) and the `bbbnet_h264_{1500,20000}k_20min.mp4` network arms;
served by the Range-correct `origin.py` on GoS1 `:8123` (CR-072; `?pace_kbps=` caps a response for the
paced/live-like arm).

## Devices

| driver | box | start | provenance |
|---|---|---|---|
| `adb` | Google TV Streamer `.126` (Lab-D `.36`, HDMI_2) · Fire TV Stick 4K `.200` (Lab-A `.146`, HDMI_4, **Wi-Fi only**, no logcat decoder names, loses ADB auth after a mains cycle) · Bbox 4K operator CPE `.10` eth / `.173` Wi-Fi, MAC-followed (Lab-F `.155`, HDMI_1, Android 11, Marvell Berlin) | VIEW intent → Just Player, `--ei position 0`, PLAYING verified (≤2 presses), keep-awake pins + CEC rule applied in `prepare()` | logcat `CCodec allocate(c2.*)` + mid-window screenshot + `playback_state_midwindow`/`_at_end`, `alive_at_window_end` |
| `ssh` | Raspberry Pi 400 `.108` (Lab-B `.31`, HDMI_3; Wi-Fi `.110` for the CR-074 arms) · Pi 5 `.102` (**parked**, shares Lab-A) | per-run `cmd` over SSH (`ffmpeg -re … -f null -` headless, `mpv` screen mode); `pre_cmd`/`post_cmd` hooks | the command + `ifaces_midwindow` |
| `webos` | LG C2 55" `.25` (Lab-E `.71` = the panel plug; native decode via the built-in browser, `lg.py` SSAP + Wake-on-LAN) | `launch_url` | `current_app` only (no state/screenshot); rows are panel-dominated (picture term) — differential only |

Authoritative registry (IPs, plugs, `idle_w`, boot thresholds, HDMI ports): `wattlab_service/rig.py` `RIG`.
The table above is a reading aid; when it disagrees with `rig.py`, `rig.py` wins.

Protocol fix vs July: the adb driver never runs `pm clear` (grants + force-stop only), so
the first-run tooltip overlay that contaminated all nine 20-min runs cannot recur; the
mid-window screenshot proves it.

## Raspberry Pi decode-option matrix

| codec | Pi 4 (BCM2711) | Pi 5 (BCM2712) |
|---|---|---|
| H.264 | **hw** ≤1080p60 (`h264_v4l2m2m`) + sw | **sw only** — hw block removed |
| HEVC  | **hw** ≤4Kp60 (rpivid, V4L2 stateless) + sw | **hw** ≤4Kp60 (HEVC block) + sw |
| AV1   | sw only (dav1d; 1080p60 marginal) | sw only (dav1d; 1080p60 OK) |

The Pi 5's dropped-H.264-hw is the headline hypothesis: **the first consumer-relevant case
where a NEWER device must software-decode the OLDEST codec** — the inverse of the
`input-master-sensitivity` story, on the same three-codec panel as the Google TV round.

Two arms per condition, don't mix them:
- **Realtime playback** (`mpv --fs --hwdec=no|auto` on the KMS console, HDMI to the metered
  monitor) — comparable to the Google TV rows; report device-total W.
- **Pure decode** (`ffmpeg -f null -`) — no display path; decode outruns realtime, so either
  pace with `-re` (then W is meaningful) or report **Wh per file**, never bare W.

### Pi setup checklist (owner)
1. Flash Raspberry Pi OS **Bookworm 64-bit** (ships the patched ffmpeg/mpv with the V4L2
   hw-decode paths), enable SSH, put Ben's key on it (`BatchMode=yes` — no password prompts).
2. Ethernet preferred (Wi-Fi power management would pollute the numbers; else
   `iwconfig wlan0 power off`).
3. Power the Pi from a **spare Tapo P110** (official USB-C PSU on the plug). Before trusting
   it: `bin/probe-p110-fw` for cadence/dup-rate (fw ≥1.4 ⇒ 1.5 s, matches `cadence_s`).
   Pi 4 idles ~2.7 W, Pi 5 ~3 W, decode loads 5–10 W — well inside the mW path's resolution.
4. Verify hw paths before a round: `mpv --hwdec=auto ...` then check its log for
   `v4l2` / `drm` vs `sw`; on Pi 5 confirm H.264 actually falls back to software.
5. Disable desktop compositing / run from the console (`mpv --vo=gpu` on KMS); no browser,
   no auto-updates during runs (`sudo systemctl stop apt-daily.timer` etc. — Pi-side
   focus-mode equivalent, manual for now).

## Known infra caveats
- **adb** (2026-08-26): Android platform-tools **r37.0.0** (adb 1.0.41, build 37.0.0-14910828) lives at
  `/srv/data/owl/decode-bench/tools/platform-tools/` on the data NVMe — durable across reboots; NOT the
  apt `adb` (34.x, not installed). `rig.py`/`decode_run.py`/`c2_hunt.py` name that path; `decode_bench/tools`
  is a gitignored symlink to it so `bench.py` resolves the same binary whether run through
  `/srv/data/owl/decode-bench/bench.py` (the service) or the checkout (`$OWL_ADB_BIN` overrides). Host key
  `~/.android/adbkey` (each box trusts its fingerprint — never regenerate); a copy is kept at
  `/srv/data/owl/decode-bench/android-keys-backup-2026-08-26/` (mode 600, off-repo). The stray copy a
  July session had left under `/tmp` (byte-identical) was deleted; all three boxes verified `device` after.
- **Targets follow the box by MAC** (2026-08-26): adb devices carry `macs` (every interface); when a
  powered box fails its readiness probe past `expected_boot_s`, the poller ping-sweeps the /24, reads the
  neighbour table and retargets (`target_source: discovered` in status.json, "followed by MAC" in the tile).
  Precedence discovered > `/settings` `rig_target_overrides` > `rig.py` default; forgotten when the box goes
  off. This is the fix for the "stuck — not ready after 145s" class (Bbox on Wi-Fi at `.173` while rig.py
  said `.10`; the CR-074 Wi-Fi moves before it).
- (Fixed 2026-07-31, CR-072) the old bare `python -m http.server` on `:8123` ignored Range requests
  (200 + full body) — the prime suspect for the July media3 2.1× over-fetch. `origin.py` is
  Range-correct (206/416/HEAD, `/status` byte counters) and owned by the service.
- Box home-screen baseline drifts 0.9–1.4 W between runs → ordered cross-condition
  comparisons should use device-total W (as in the July report), ΔW for magnitude only.
- Meters `.94`/`.199` have never had `bin/probe-p110-fw` run on them (dual-meter doc rule).
- KLAP sessions are exclusive per plug: don't run bench.py while anything else polls the
  same plugs locally (REM's *cloud* polling is fine — different path).

## Network — fixed addresses (router DHCP reservations, set 2026-07-29)

All bench devices and lab plugs have router reservations. GTV, Bbox, Pi 400 and the C2 are on
**Ethernet** via the bench switch (the Fire TV Stick is Wi-Fi only; Bbox re-onboarded on `.10` 2026-07-31) (parallel throughput verified 178–582 Mbps,
2026-07-29). Pi 5 Wi-Fi is **soft-blocked** (rfkill, persistent) since 2026-07-29 — eth0 only. Pi 400
still has Wi-Fi up; apply the same sudo rfkill block wifi next time it is powered.
Pi 5 PSU replaced 2026-07-29 (old one under-voltage-throttled; throttled=0x0 verified —
re-validate one July decode row before comparing new Pi 5 numbers against the July panel).

| IP | What | MAC | Notes |
|---|---|---|---|
| `.62` | GoS1 (eno2) | `a0:ad:9f:58:ec:0d` | pre-existing reservation, confirmed correct (bound to eno2; eno1 is dark) |
| `.126` | Google TV Streamer (eth0) | `b4:23:a2:af:e4:a4` (wlan0 `0e:03:41:ca:06:29`, per-SSID randomised) | rebound from Wi-Fi MAC → returns to its July address after lease renewal (was `.189` on 2026-07-29); MediaTek MT8696 (`ro.soc.model`) |
| `.102` | Raspberry Pi 5 (eth0) | `88:a2:9e:27:40:ed` | user `admin` |
| `.108` | Raspberry Pi 400 (eth0) | `d8:3a:dd:76:f8:5b` | user `nebul2` |
| `.146` | Lab-A P110 — Fire TV Stick meter (Pi 5 parked on the same plug — never power both) | `bc:07:1d:a2:d3:11` | fw 1.3.1 |
| `.31` | Lab-B P110 — Pi 400 meter | `bc:07:1d:a2:df:66` | fw 1.3.1 |
| `.35` | Lab-C P110 — ⚠ POWERS THE BOUYGUES ROUTER (as of 2026-07-29) | `bc:07:1d:a2:e2:6a` | fw 1.3.1 — **NEVER SWITCH OFF**: relay-off kills the whole LAN including the path to switch it back on (unrecoverable remotely). Move router to a dumb socket; until then Lab-C is read-only and must never appear in any control UI. |
| `.36` | Lab-D P110 — GTV meter | `bc:07:1d:a2:da:48` | fw 1.3.1; replaced `.94` (fw 1.4.6) on 2026-07-29; moved off its first lease `.1` (router pool constraint: `.36`, not `.147`) |
| `.71` | Lab-E P110 — the LG C2 panel (context meter / C2 device plug) | — | fw 1.3.1; replaced Ben1-4k-monitor `.199` (fw 1.4.6) on 2026-07-29 |
| `.155` | Lab-F P110 — Bbox 4K meter | — | fw 1.3.1 (re-plugged 2026-07-30; the earlier `.22` unit was fw 1.4.0) |
| `.10` | Bbox 4K (eth0) | `ec:6c:9a:ef:73:a1` (wlan0 `70:f7:54:37:4f:e4`) | operator CPE, ADB authorised; on Wi-Fi at `.173` whenever the cable is out (CR-074 pull 2026-08-19, still out on 2026-08-26 — eth0 NO-CARRIER); the rig follows it by MAC |
| `.200` | Fire TV Stick 4K (Wi-Fi) | `ec:31:5f:6d:7c:a7` | AFTKRT; ADB re-auth needed after a mains power cycle (came back authorised on 2026-08-26) |
| `.25` | LG C2 (eth0; also `.109` Wi-Fi) | — | webOS SSAP + WoL (`lg.C2_MAC`) |
| `.159` | P110-GoS1-Server | — | pre-existing reservation, unchanged |
| `.91` | P110-GoS1b | — | pre-existing reservation, unchanged |

All six Lab plugs (A–F) are on fw **1.3.1** (mW local API, 1–2 s effective cadence).
Configs written before 2026-07-29 that reference STB plug `.94` are historical — new
GTV rows meter via **Lab-D `.36`**.

## Display path (2026-07-29)

Only the **Google TV** is connected to a screen: HDMI to the 4K monitor metered by
**Lab-E**. Decode rows on the GTV can therefore include display/brightness arms
(device + monitor metered separately, both mW-class). Panel caveat for the record:
it is an **LCD 4K HDR** panel — not very responsive to content luminance (unlike OLED),
so luminance-driven display effects will be muted; acceptable now that the meter is
mW-class. Both Pis remain headless (pure-decode rows only).

### Monitor auto-switch behaviour (verified by eye + Lab-E draw, 2026-07-29)

All three boxes share the monitor on separate HDMI inputs. Verified:
1. **Fresh monitor power-on** -> scans and locks the only live signal.
2. **New signal appears** -> steals the input from a currently displayed source
   (Pi 400 boot took the screen from an actively playing Pi 5).
3. **Active signal lost** -> falls back to a remaining live signal
   (Pi 400 shutdown returned the screen to the Pi 5 mid-playback).

Consequence: with the boxes **off by default**, the screen deterministically follows
whichever single device is powered — no physical input-button presses needed for
remote/Tania operation. Do not run display arms on two boxes at once.

### Pi display arm (proven 2026-07-29, Pi 5)

    cmd:      WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000 mpv --fs --no-audio /dev/shm/decode/<clip>.mp4
    stop_cmd: pkill mpv

Slots into bench.py ssh driver unchanged. Informal check: Pi 5 mpv BBB H.264 drew
~ +1.6 W over idle (July headless realtime row: +1.57 W) on the NEW PSU.
Pi 400 extra arm: add --hwdec for the hardware H.264 block. Kodi + JSON-RPC held in
reserve for the stranded stateless-V4L2 HEVC experiment.
/dev/shm/decode/ is tmpfs — clips must be re-staged after every power cycle.

### Screen usage note (2026-07-29)
The 4K monitor doubles as a MacBook screen extension — while the Mac is connected,
its HDMI signal competes in the auto-switch behaviour above. Leave Lab-E on.

### Screen arbitration notes (2026-07-29, /decode claim-screen)
- The monitor does NOT gate hot-plug per input — devices cannot detect losing
  the screen. Arbitration is active: Pis drop/raise signal via **wlopm DPMS**
  (never `wlr-randr --off` — labwc auto-revives a session's only output);
  GTV via KEYCODE_SLEEP/WAKEUP with mWakefulness verify (Dozing == asleep).
- Both Pis use connector **HDMI-A-2**; output names are discovered at
  call time anyway.
- **Pi 400 required desktop auto-login** (was parked at a lightdm greeter →
  no user compositor → wlopm/mpv had nothing to talk to). Set via
  `raspi-config nonint do_boot_behaviour B4` on 2026-07-29. Pi 5 already had it.
- After a Pi boots, SSH-ready precedes desktop-ready by ~10–20 s — a claim or
  display arm fired immediately at "ready" can race the compositor; claims
  fail honestly, just retry.
- Guaranteed fallback: power off the boxes that shouldn't have the screen —
  the panel follows the single live signal deterministically.
- Known quirk: with the panel fully asleep (long no-signal), the FIRST claim
  sometimes only takes from the Pi 400; once the panel is awake any device
  claims fine. Workaround: claim once (anything) to wake the panel, then
  claim the target — or power-cycle the target device (boot hot-plug always
  wins). All-three bounce verified clean 2026-07-29 after the DPMS +
  layer-repair + GTV-transition fixes.

## Downstairs rig — LG C2 OLED display (2026-07-30 →)

Rig migrated to the **LG OLED55C25LB (C2 55")** as the shared display, replacing the PA329C
LCD (now upstairs). Dumb switch (no IGMP snooping) — fine for discovery.

**Display control — webOS (CR-071, closed 2026-08-19):** the C2 does NOT auto-switch inputs;
arbitration is an explicit `set_input(HDMI_n)` via aiowebostv (`/tmp/pyatv-venv`), client key at
`/srv/data/owl/lg/client_key`, host `192.168.1.25` (Ethernet; `.109` is its Wi-Fi). Always-Ready
standby rejects SSAP with WS 1008 → wake with raw Wake-on-LAN first (`lg.wake()`, 2026-08-01). The
poller never auto-wakes it (household TV); SIMPLINK/CEC turned OFF by the owner 2026-08-15 (input
hopping was contaminating baselines).

**HDMI port map (rig.py):** Bbox → HDMI_1 · GTV → HDMI_2 · Pi 400 → HDMI_3 · Fire TV → HDMI_4 (Pi 5 parked).

**Bbox (Bouygtel4K, operator CPE — Marvell Berlin, Arcadyan HMB9213NW, `ro.soc.*` empty; R3a 2026-08-26):** ADB authorised (Android 11), Ethernet `.10` since 2026-07-31 (on Wi-Fi `.173` since the CR-074 cable pull),
plug Lab-F `.155`, `idle_w` 6.6 W (drifts 6.3–6.8 → its H.264/HEVC ΔW sits inside its own noise; AV1
+1.2–1.4 W = software AV1). Plays via VIEW intent through the origin.

**Fire TV Stick 4K (AFTKRT, MediaTek MT8696, Fire OS 8):** Wi-Fi only, `.200`, plug Lab-A `.146`;
never emits `CCodec allocate` lines (no decoder provenance); `alive_at_window_end` returned False on flat
traces (S65 — retries + `playback_state_at_end` since `10ed87f`); loses ADB authorisation after a mains
power cycle (on-site accept, ONE reconnect).

**Apple TV 4K — `AppleTV6,2` = 1st generation (2017), A10X Fusion, "TV Room", `.152` (identified from its
AirPlay info endpoint by the desk 2026-08-26; NOT the A15 3rd gen CR-075 first assumed — no hardware AV1 on
any Apple silicon before A17 Pro/M3):** Companion + AirPlay paired (creds `/srv/data/owl/atv/`); power/keys
work; AirPlay `play_url` blocked by a tvOS-18/pyatv issue. pyatv 0.18.0 venv is at `/tmp/pyatv-venv`
(⚠ under /tmp — recreate with `python3 -m venv … && pip install pyatv==0.18.0` if it is gone). Off the LAN
on 2026-08-26 evening (ARP INCOMPLETE, no mDNS). Second attempt = CR-075.

**Origin:** Range-correct `origin.py` on `:8123`, a child of wattlab.service (`origin_control.py`,
reboot-persistent; `sudo systemctl stop wattlab` kills it — restart, don't stop). CR-072 phase 2
(metered serve window) open. `?pace_kbps=N` caps one response's rate (CR-074 paced arm).

**Harness protocol since 2026-08-16 (`fec0065`, `10ed87f`, `960675c`):** keep-awake pins
(`secure sleep_timeout=-1`, `system screen_off_timeout=2147460000`) + CEC `power_state_change_on_active_source_lost=none`
applied and recorded in provenance; start at position 0; PLAYING verified before the baseline; mid-window
screenshot + state; end-of-window liveness with 3 retries + ADB reconnect; per-run `pre_shell`/`pre_cmd`/`post_cmd`
hooks; ssh rows record `ifaces_midwindow`. Long-window rows count only with PLAYING at mid-window and a
trace flat to the end (analysis rule, JOURNAL S65).
