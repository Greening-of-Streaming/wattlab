# decode-bench — portable CPE decode/playback energy harness

One protocol (identical to `stb-decode-2026-07`: settle → baseline → start → startup-skip →
sample window → stop → OWL `confidence.py` → per-row checkpoint), pluggable devices via
JSON config. New rows are directly comparable with the July Google TV panel.

```
python3 bench.py gtv_smoke.json        # Google TV, one 90 s validation row
python3 bench.py pi4.json / pi5.json   # copy pi_matrix.json.example, fill host + meter
```

Results land in `results/<config name>.json` (raw 1.5 s samples included, resumable).
Streams: `streams/` → symlink to the 27 matched-VMAF (~92–93, v1) 1080p NVENC encodes,
served by the http server on GoS1 `:8123` (⚠ it ignores Range requests — see below).

## Devices

| driver | box | start | provenance |
|---|---|---|---|
| `adb` | Google TV Streamer `.126` (plug: Lab-D `.36` (was `.94` pre-2026-07-29), monitor `.199`) | VIEW intent → Just Player | logcat `CCodec allocate(c2.*)` + mid-window screenshot |
| `ssh` | Raspberry Pi 4 / 5 | per-run `cmd` over SSH | the command itself (+ check player log) |

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
- `:8123` is a bare `python -m http.server` and **ignores Range requests** (returns 200 +
  full body — verified 2026-07-28). Prime suspect for the July media3 2.1× over-fetch.
  For any fetch-behaviour experiment, swap in a range-capable server (nginx or
  `python -m RangeHTTPServer`) and log access; for pure decode rows it only wastes LAN bytes.
- Box home-screen baseline drifts 0.9–1.4 W between runs → ordered cross-condition
  comparisons should use device-total W (as in the July report), ΔW for magnitude only.
- Meters `.94`/`.199` have never had `bin/probe-p110-fw` run on them (dual-meter doc rule).
- KLAP sessions are exclusive per plug: don't run bench.py while anything else polls the
  same plugs locally (REM's *cloud* polling is fine — different path).

## Network — fixed addresses (router DHCP reservations, set 2026-07-29)

All bench devices and lab plugs have (or are pending) router reservations. All three
devices are on **Ethernet** via the bench switch (parallel throughput verified 178–582 Mbps,
2026-07-29). Pi 5 Wi-Fi is **soft-blocked** (rfkill, persistent) since 2026-07-29 — eth0 only. Pi 400
still has Wi-Fi up; apply the same sudo rfkill block wifi next time it is powered.
Pi 5 PSU replaced 2026-07-29 (old one under-voltage-throttled; throttled=0x0 verified —
re-validate one July decode row before comparing new Pi 5 numbers against the July panel).

| IP | What | MAC | Notes |
|---|---|---|---|
| `.62` | GoS1 (eno2) | `a0:ad:9f:58:ec:0d` | pre-existing reservation, confirmed correct (bound to eno2; eno1 is dark) |
| `.126` | Google TV Streamer (eth0) | `b4:23:a2:af:e4:a4` | rebound from Wi-Fi MAC → returns to its July address after lease renewal (was `.189` on 2026-07-29) |
| `.102` | Raspberry Pi 5 (eth0) | `88:a2:9e:27:40:ed` | user `admin` |
| `.108` | Raspberry Pi 400 (eth0) | `d8:3a:dd:76:f8:5b` | user `nebul2` |
| `.146` | Lab-A P110 — Pi 5 meter | `bc:07:1d:a2:d3:11` | fw 1.3.1 |
| `.31` | Lab-B P110 — Pi 400 meter | `bc:07:1d:a2:df:66` | fw 1.3.1 |
| `.35` | Lab-C P110 — ⚠ POWERS THE BOUYGUES ROUTER (as of 2026-07-29) | `bc:07:1d:a2:e2:6a` | fw 1.3.1 — **NEVER SWITCH OFF**: relay-off kills the whole LAN including the path to switch it back on (unrecoverable remotely). Move router to a dumb socket; until then Lab-C is read-only and must never appear in any control UI. |
| `.36` | Lab-D P110 — GTV meter | `bc:07:1d:a2:da:48` | fw 1.3.1; replaced `.94` (fw 1.4.6) on 2026-07-29; moved off its first lease `.1` (router pool constraint: `.36`, not `.147`) |
| `.71` | Lab-E P110 — 4K monitor (context) | — | fw 1.3.1; replaced Ben1-4k-monitor `.199` (fw 1.4.6) on 2026-07-29 |
| `.159` | P110-GoS1-Server | — | pre-existing reservation, unchanged |
| `.91` | P110-GoS1b | — | pre-existing reservation, unchanged |

All five Lab plugs (A–E) are on fw **1.3.1** (mW local API, 1–2 s effective cadence).
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
