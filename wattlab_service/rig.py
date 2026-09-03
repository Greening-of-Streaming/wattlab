"""
rig.py — client-decode rig power control (/decode page backend).

The rig is three playback devices (Pi 5, Pi 400, Google TV Streamer), each
powered through its own Tapo P110 "Lab" plug, sharing one 4K monitor (its own
plug), plus an optional Shelly "master" switch feeding the strip that powers
the three device plugs. Devices are OFF by default; the monitor auto-switches
to the single live HDMI signal, so the screen follows whichever one device is
powered (verified 2026-07-29, see decode-bench README on GoS1).

This module owns:
  RIG            — the rig topology (devices, plugs, boot expectations).
  plug_status()/plug_set()      — Tapo control for arbitrary plug IPs
                                  (power.py's cache+lock pattern, generalised;
                                  power.py itself stays meter-only).
  shelly_status()/shelly_set()  — master switch; Gen1/Gen2+ auto-detected.
  rig_cache + rig_poller()      — background state machine driving the tiles.
  device_on()/device_off()/device_cycle(), monitor_power(), master_power().
  touch_activity() + idle_off_state()/_maybe_idle_off() — the idle auto-off:
                                  the rig is OFF by default; after N hours
                                  (settings rig_idle_off_hours) with no
                                  operator/job activity every powered box is
                                  gracefully stopped (then the master, if one
                                  is switchable). CLI bench.py campaigns keep
                                  the rig alive by touching RIG_HOLD_FILE.

State machine per device (tile colour in parentheses):
  off (red) → powering (orange: relay on, draw < boot threshold)
            → booting  (orange: draw up, ready-probe failing; progress bar)
            → ready    (green) [→ busy badge while a decode job runs]
  graceful stop: stopping (orange: ssh shutdown/adb reboot -p → wait → relay
  off) → off.  Probe not passing within 3× expected boot → stuck (red+badge).
  Master OFF ⇒ device plugs are unpowered/unreachable → unpowered (grey) —
  a modelled state, not an error.

⚠ HAZARD (do not "fix"): the Tapo at 192.168.1.35 (Lab-C) powers the Bouygues
ROUTER. It must never appear in this config or any control surface — relay-off
would kill the LAN including the path to turn it back on. A guard test greps
every /decode response for that IP.

All ssh/adb/Shelly subprocess+HTTP calls run via asyncio.to_thread — never on
the event loop. Tests monkeypatch the module-level IO functions (plug_status,
plug_set, shelly_status, shelly_set, probe_ready, send_shutdown).
"""
import asyncio
import json
import logging
import subprocess
import time
import urllib.request
from pathlib import Path
from dotenv import dotenv_values

import lg

log = logging.getLogger(__name__)

_config = dotenv_values("/home/gos/wattlab/.env")

# Android platform-tools r37.0.0 (adb 1.0.41, build 37.0.0-14910828), a pinned
# release unpacked under /srv/data (the data NVMe — survives reboots and /tmp
# cleaning; NOT the apt `adb` 34.x). decode_bench/tools -> that dir is a
# gitignored symlink so bench.py resolves the same binary (it also honours
# $OWL_ADB_BIN). Host key: ~/.android/adbkey — every box trusts THAT key's
# fingerprint (adb_host_fingerprint()); never regenerate it. 2026-08-26.
ADB_BIN = "/srv/data/owl/decode-bench/tools/platform-tools/adb"

# --- Rig topology -----------------------------------------------------------
#
# plug_ip may be a list of candidate IPs (first that answers wins, cached) —
# Lab-D has a pending DHCP reservation move (.1 → .36), so both are listed
# until the plug's lease renews. expected_boot_s: pi5 measured 2026-07-29;
# pi400/gtv are placeholders until the first live verification measures them.
RIG: dict = {
    "devices": {
        "pi5": {
            # Un-parked 2026-08-24 (SMPTE gap-fill, F9 control pair): back
            # HEADLESS — no HDMI at all (pure-decode rows need none) — on a
            # NEW owner-added P110 (Tapo nickname "F2" — owner renamed it
            # 2026-08-24 from "lab-F", which had collided with the Bbox's
            # "Lab-F" at .155; named lab-F2 here). Not on the
            # Shelly-metered strip (master tile won't see it). The board now
            # also runs Pi-hole (LAN DNS) — a small always-on background
            # load, disclosed per campaign; do NOT stop it (LAN infra).
            "label": "Pi 5", "plug_name": "lab-F2",
            "os": "Raspberry Pi OS", "chip_vendor": "Broadcom",
            # Headless since 2026-08-19 (own P110, no HDMI cable) — not on any
            # of the C2's four inputs; the screen map (rig_hdmi_inputs) can
            # put it on one when it is physically re-cabled.
            "hdmi_input": None,
            "plug_ip": "192.168.1.184",
            "kind": "ssh", "target": "admin@192.168.1.102",
            "device_class": "sbc",
            "silicon": "BCM2712 · sw decode only",
            "expected_boot_s": 29, "boot_threshold_w": 1.0,
            "shutdown_wait_s": 22,
            "network": "ethernet",
            # Known settled idle (W) — the decode guard's reference floor
            # (stability alone settles on post-boot plateaus; see the
            # 2026-07-30 negative-ΔW row that motivated this).
            "idle_w": 3.4,
        },
        "pi400": {
            # Un-parked 2026-08-08 for the R6 hw-vs-sw reconciliation — back on
            # Lab-B, displacing the Fire TV Stick (parked below). To switch the
            # bench back: move "parked": True from firestick to here.
            "label": "Pi 400", "plug_name": "Lab-B",
            "os": "Raspberry Pi OS", "chip_vendor": "Broadcom",
            "plug_ip": "192.168.1.31",
            "kind": "ssh", "target": "nebul2@192.168.1.108",
            "device_class": "sbc",
            "silicon": "BCM2711 · hw H.264",
            "expected_boot_s": 45, "boot_threshold_w": 1.0,
            "shutdown_wait_s": 22,
            "idle_w": 3.0,
            "network": "ethernet",
            # HDMI_3 physically re-cabled to the Roku 2026-08-29 (Ben,
            # on-site, during the switch install) — the Pi 400 runs headless
            # fine over SSH (decode-to-null never touches a display anyway).
            "hdmi_input": None,
        },
        "firestick": {
            # Back on the bench 2026-08-15 on Lab-A + HDMI_4 (Pi 5 now on its
            # own plug, above). Was parked 2026-08-08 (Pi 400 took Lab-B for R6);
            # first bench 2026-07-31 on Lab-B/HDMI_3.
            "label": "Fire TV 4K", "plug_name": "Lab-A",
            "plug_ip": "192.168.1.146",
            # Fire TV Stick 4K 2nd-gen (AFTKRT "karat"), Fire OS 8.1.8 /
            # Android 11. Wi-Fi ONLY (no Ethernet port) — reserve .200 for
            # MAC ec:31:5f:6d:7c:a7 on the router or the ADB target drifts
            # (GTV lesson). Methodology/transparency: the only Wi-Fi device
            # on the rig. Link quality is not the concern (the Bbox Wi-Fi 7
            # AP is a few metres away — likely better than the bench Ethernet)
            # — the energy caveat is that the stick powers its own radio,
            # so its device-total W includes a Wi-Fi share the Ethernet boxes
            # don't carry. State it next to any cross-device comparison.
            "kind": "adb", "target": "192.168.1.200:5555",
            "macs": ["ec:31:5f:6d:7c:a7"],          # wlan0 (Wi-Fi only)
            "device_class": "stb",
            # Render-only override (2026-08-29): the physical form factor is an
            # HDMI dongle, not a set-top box — device_class stays "stb" (same
            # categorisation/filtering as every other STB on the rig).
            "shape": "stick",
            "os": "Fire OS 8", "chip_vendor": "MediaTek",
            "silicon": "MediaTek MT8696 · hw H.264/HEVC/VP9/AV1",
            "network": "wifi",
            # HDMI_4 physically re-cabled to the Apple TV 2026-08-29 (Ben,
            # on-site, during the switch install). Fire TV now has NO HDMI
            # cable at all (not just "unclaimed") — unlike the Pi boards,
            # this is Android app-launch playback, and it's genuinely
            # untested whether that still decodes/renders correctly with
            # zero display sink attached. Confirm with a live smoke test
            # before trusting any headless row from this box (2026-08-29,
            # Ben's catch — see the matching note on Xiaomi below).
            "hdmi_input": None,
            "expected_boot_s": 40, "boot_threshold_w": 0.4,
            "shutdown_wait_s": 15,
            # Awake-home idle measured 2026-07-31: ~1.3–2.2 W (Amazon autoplay
            # spikes it). Reference floor must sit ABOVE the spikes or the guard
            # never settles (w ≤ idle_w+tol) and burns max_wait — 1.5 left the
            # 2.2 spikes above the 2.0 threshold, causing the long settles Ben
            # saw. 1.8 → settles ≤2.3, covers the spikes.
            "idle_w": 1.8,
        },
        "gtv": {
            "label": "Google TV", "plug_name": "Lab-D",
            "plug_ip": "192.168.1.36",
            # The owner's re-pinned reservation (.126, the July address) took
            # effect on the 2026-07-30 boot — the interim .189 lease is dead.
            # The "stuck/no-network" episode was this address move mid-flight.
            "kind": "adb", "target": "192.168.1.126:5555",
            # eth0, then wlan0. The Wi-Fi MAC is Android's per-SSID randomised
            # one (0e:/de: = locally administered) — stable for a given SSID
            # unless the network is forgotten on the box; re-read with
            # `adb shell ip link` if the follower stops finding it on Wi-Fi.
            # 2026-09-03: it HAD rotated (the old 0e: one no longer resolves,
            # which is exactly why the follower lost this box for 20 minutes
            # on 2026-09-02) — de:17:… is the current "schwarz" one, recorded
            # when the box was moved to Wi-Fi so Axis A (Fire TV vs GTV, same
            # MT8696) stops confounding OS with network path (CR-074 measured
            # that term at +0.21 W here, the same size as the codec deltas).
            # Ethernet and Wi-Fi are mutually exclusive on this box: it drops
            # the Wi-Fi association the moment the cable goes back in.
            "macs": ["b4:23:a2:af:e4:a4", "0e:03:41:ca:06:29",
                     "de:17:af:66:eb:45"],
            "device_class": "stb",
            "os": "Google TV (Android 14)", "chip_vendor": "MediaTek",
            # VP9 added 2026-09-03: logcat on the n=3 batch allocated
            # c2.mtk.vp9.decoder alongside c2.mtk.{avc,hevc,av1} — all four
            # codecs are hardware Codec2 on this box.
            "silicon": "MediaTek MT8696 · hw H.264/HEVC/AV1/VP9 (c2.mtk.*)",   # getprop ro.soc.model, R3a 2026-08-26
            "hdmi_input": "HDMI_2",
            "expected_boot_s": 90, "boot_threshold_w": 0.4,
            "shutdown_wait_s": 15,
            # Wi-Fi since 2026-09-03 (was "ethernet"): moved deliberately so
            # the Fire TV vs Google TV axis — same MediaTek MT8696, different
            # OS/vendor stack — stops confounding the OS difference with the
            # network path. The Fire TV is Wi-Fi-only, and CR-074 measured
            # GTV's own Wi-Fi term at +0.21 W here, i.e. the same size as the
            # per-codec deltas being compared. Address comes from the settings
            # override (rig_target_overrides → .127); its randomised wlan MAC
            # is in `macs` above. The box refuses both at once: plugging the
            # Ethernet cable back in drops the Wi-Fi association, so restoring
            # Ethernet means clearing the override too.
            "network": "wifi",
            "idle_w": 1.0,
        },
        "bbox": {
            "label": "Bbox 4K", "plug_name": "Lab-F",
            # Lab-F re-plugged 2026-07-30 (new unit on fw 1.3.1 for 1 s mW
            # polling; old .22 was fw 1.4.0). New DHCP lease → .155.
            "plug_ip": "192.168.1.155",
            # Operator CPE (Bouygtel4K, Android 11, Marvell Berlin / Arcadyan
            # HMB9213NW — R3a 2026-08-26) — the first operator box on the
            # bench. On Ethernet at .10 (re-onboarded after a factory reset
            # 2026-07-31: complete setup wizard → dev options → USB debugging →
            # re-auth; never power-cycle it mid-boot). Its Ethernet cable was
            # pulled for CR-074 (2026-08-19) and put back 2026-08-26 evening;
            # both MACs are reserved on the router (.10 eth / .173 Wi-Fi) and
            # the MAC follower below resolves it either way.
            "kind": "adb", "target": "192.168.1.10:5555",
            "macs": ["ec:6c:9a:ef:73:a1", "70:f7:54:37:4f:e4"],   # eth0 (.10), wlan0 (.173)
            "device_class": "stb",
            "os": "Android 11 (operator CPE)", "chip_vendor": "Marvell",
            "silicon": "Marvell Berlin (Arcadyan HMB9213NW) · Android 11 · hw H.264/HEVC, no AV1 block",
            "hdmi_input": "HDMI_1",
            "expected_boot_s": 45, "boot_threshold_w": 4.0,
            "shutdown_wait_s": 15,
            # Measured 2026-07-31: operator box idles ~6.3 W (its live-TV UI
            # runs in the background) — much higher than an SBC. The guessed
            # 3.0 made the idle guard time out every run.
            "idle_w": 6.6,
            "network": "ethernet",
        },
        "atv": {
            # Apple TV 4K 1st gen (AppleTV6,2, 2017, A10X Fusion, tvOS 18.0) —
            # CR-075, on the rig 2026-08-26. Driven over pyatv (Companion +
            # AirPlay creds in /srv/data/owl/atv/): power state = readiness,
            # `turn_off` = graceful stop, playback = VLC for tvOS launched with
            # its x-callback stream scheme (AirPlay play_url is dead on tvOS
            # 18 — receiver-side, pyatv #2403). No screenshot/logcat: liveness
            # is the pyatv playback state. Not cabled to the C2 (no HDMI
            # input) until the screen map says otherwise.
            #
            # Parked 2026-09-02 (unplugged so the revived Gen 2 Xiaomi could
            # take Lab-F3 and its HDMI for the Gen2-vs-Gen3 A/B); BACK 2026-09-03
            # evening on its own NEW plug Lab-F6 (.170, MAC c0:3a:55:58:92:68,
            # read 3.1 W = the tvOS 26.6 idle floor below on first contact) and
            # on HDMI_2 via the /settings screen map (gtv 1 · atv 2 · roku 3 ·
            # xiaomi3 4; Fire TV and Gen 2 headless). Visual check on the
            # football clip passed the same evening (VLC via Companion).
            # Lab-F6 is NOT on the Shelly-metered 8-way strip (own socket):
            # the Shelly sum excludes this box and the master switch does
            # not cut it — device power is this plug alone.
            "parked": False,
            "label": "Apple TV 4K", "plug_name": "Lab-F6",
            "plug_ip": "192.168.1.170",
            "kind": "atv", "target": "192.168.1.152",
            "macs": ["90:dd:5d:ab:70:8e"],
            "device_class": "stb",
            # tvOS 26.6 since the 2026-08-27 update (was 18.0 at CR-075's
            # original measurement — see JOURNAL for the idle-floor recheck
            # this triggered).
            "os": "tvOS 26.6", "chip_vendor": "Apple",
            "silicon": "Apple A10X Fusion (2017) · hw H.264/HEVC · no AV1/VP9 block",
            "network": "ethernet",
            # HDMI_4 (2026-08-29, physically re-cabled from the Fire TV's old
            # socket — Ben's actual on-site wiring; Roku took the Pi 400's old
            # HDMI_3 instead). The only device on the rig that structurally
            # CANNOT be measured headless — VLC pauses on HDMI loss. CR-075
            # still owes n≥3.
            "hdmi_input": "HDMI_4",
            "expected_boot_s": 60, "boot_threshold_w": 1.0,
            "shutdown_wait_s": 10,
            # RE-CHARACTERIZED 2026-08-29 on tvOS 26.6 (the 2.1-2.3 W figure
            # below was tvOS 18-era and is now stale — this answers the
            # "does 26 have a higher floor than 18" question raised earlier
            # this session): 148 s of live-watched parked (VLC stopped) power
            # sat consistently at ~2.9-3.1 W, with occasional brief bumps to
            # 3.6-3.8 W and one real spike to 6.1 W correlated with a moving
            # AirPlay promotional overlay. Confirmed NOT fixable via
            # Screensaver/Reduce Motion/Auto-Play Video Previews — all three
            # were checked/changed live and none moved the sustained floor;
            # this looks like a genuine tvOS-version floor increase, not a
            # settings problem. (Old note, now superseded: "Parked sits at
            # ~2.1-2.3 W; home screen autoplays previews (6-15 W) and tvOS
            # Settings spikes to ~5.7 W on 26.6 — neither is the idle.")
            "idle_w": 3.0,
            # 2026-08-27: found live during the first overnight campaign —
            # the generic 5 s / 20-sample protocol is tuned to the Android
            # boxes' fast post-stop settle. This box's draw kept moving for
            # 15-20+ s after `stop` (idle_guard was passing on a transient
            # 3 s window, then the fixed-length baseline caught the tail:
            # base sd up to 2 W, several rows falsely 🔴). A direct
            # atv_probe.py run with 20-30 s settle / 40-45 s baseline stayed
            # clean all night — these floors reproduce that.
            "min_settle_s": 25, "min_baseline_samples": 40,
            # 2026-08-29, corrected same day: first tried raising max_wait_s
            # alone (to 90 s) to let the guard wait out contamination — WRONG
            # half of the fix. The box's idle state has frequent BRIEF
            # single-sample spikes (6.1 W AirPlay overlay, 8.2 W on a
            # "Welcome to Apple TV" screen) against a genuinely noisy
            # ~2.9-3.8 W floor — a permanent recurring feature, not a
            # one-time event that clears. Against the global 0.5 W tolerance
            # settle_polls likely never succeeds, so a bigger max_wait_s just
            # burned its full ceiling every run (Ben: "settle and baseline
            # still seem overly long") without ever actually settling faster.
            # Widening tolerance_w lets normal jitter read as settled
            # quickly; max_wait_s is dialed back down since it should now
            # rarely be needed — it stays as the circuit breaker for a
            # genuinely sustained excursion (the campaign's 5.3+ W case),
            # not the routine path.
            "min_idle_tolerance_w": 1.0, "min_idle_max_wait_s": 45,
        },
        "xiaomi": {
            # Xiaomi TV Box (Gen 2) — REVIVED 2026-09-02: a new PSU brought it
            # back to life, correcting the 2026-08-29 note below — this was a
            # PSU fault, not DOA hardware. Now running an A/B against the new
            # Gen 3 unit (see "xiaomi3") to decide whether to keep or return
            # the Gen 2. ADB is still trusted from before (no re-pair
            # needed). No "MiTV ADB debugging" toggle exists on this Gen —
            # that's Gen-3-specific; stock "USB debugging" was always enough
            # here. idle_w/expected_boot_s are STILL UNMEASURED GUESSES —
            # onboard_device.py never ran; run it before trusting any row.
            #
            # (superseded) PARKED 2026-08-29 after the switch-install
            # physical relocation: box stopped powering on entirely (no
            # video, no boot). Tapo meter + cable/PSU reasoning inconclusive
            # at the time (DOA hardware vs. PSU fault not distinguishable
            # without a confirmed-matching spare PSU or a second unit).
            #
            # ⚠ Runs the same Android VIEW-intent/Just Player mechanism as
            # the Fire TV — genuinely unverified whether it decodes/renders
            # the same way with zero display sink attached (moot for now:
            # it's cabled, see hdmi_input note below). Confirm with a live
            # smoke test (logcat CCodec allocation + playback_state) before
            # trusting a headless row from this box.
            "label": "Xiaomi TV Box (Gen 2)", "plug_name": "Lab-F3",
            "plug_ip": "192.168.1.1",
            "kind": "adb", "target": "192.168.1.151:5555",
            "macs": ["32:6c:9f:c5:c1:fd"],   # wlan0 — no Ethernet port on this box
            "device_class": "stb",
            # SoC audit 2026-08-29: ro.soc.* is empty (same gap as the Bbox) —
            # identified instead via ro.hardware=amlogic + ro.board.platform=sc2
            # (Amlogic's own codename for the S905X4, confirmed via web search;
            # model MiTV_AFKR0, codename "jaws", Android 11 confirmed live).
            "os": "Google TV (Android 11)", "chip_vendor": "Amlogic",
            # Confirmed 2026-09-03 from logcat on the n=3 batch: this box uses
            # the LEGACY OMX IL HAL, not Codec2 — OMX.amlogic.{avc,hevc,vp9}
            # .decoder.awesome2 are hardware. AV1 settled the same day with a
            # 60 s probe + unfiltered logcat: hardware too —
            # "MediaCodec: [OMX.amlogic.av1.decoder.awesome2]", kernel
            # vdec_init dev_name ammvdec_av1_v4l with the av1_mmu firmware
            # loaded in the TEE. Just Player loads its bundled Libgav1 renderer
            # at init but MediaCodec wins the surface. The n=3 rows missed it
            # because the OMX line is logged under the MediaCodec tag, not
            # OmxComponent — bench.py's provenance filter now scans both.
            "silicon": "Amlogic S905X4 (sc2) · Android 11 · hw H.264/HEVC/VP9/AV1"
                       " (OMX.amlogic.*.awesome2, legacy OMX HAL; AV1 = ammvdec_av1_v4l)",
            "network": "wifi",
            # Live/temporary for the Gen2-vs-Gen3 A/B (2026-09-02): cabled to
            # HDMI_2 on Lab-F3's old Apple TV plug, took over the Apple TV's
            # power spot while the Apple TV sits aside decommissioned for
            # now. NOT hardcoded here — this box's permanent design is
            # headless — carried instead via /settings rig_hdmi_inputs
            # ({"xiaomi": "HDMI_2", "gtv": "", "atv": ""}) so it reverts
            # cleanly once the A/B concludes.
            "hdmi_input": None,
            "expected_boot_s": 60, "boot_threshold_w": 0.4,   # UNMEASURED guess
            "shutdown_wait_s": 15,
            "idle_w": 1.5,   # UNMEASURED guess — replace via onboard_device.py
        },
        "xiaomi3": {
            # Xiaomi TV Box (Gen 3), arrived + onboarded 2026-09-02 — set up
            # specifically to A/B against the revived Gen 2 ("xiaomi" above)
            # to decide whether the Gen 2 is worth keeping or should go back.
            # Different SoC generation from the Gen 2 (Amlogic s7d vs sc2),
            # so a real comparison is plausible, not just noise.
            #
            # Setup notes from onboarding: CEC disabled on-device. Ethernet
            # via USB adapter was tried first (showed a 169.254.x self-
            # assigned/APIPA address post-Wi-Fi-disable — DHCP never actually
            # succeeded over it) and abandoned in favour of Wi-Fi. ADB needs
            # BOTH stock "Network debugging" AND a Gen-3-specific "MiTV ADB
            # debugging" toggle (reboot-gated) — Gen 2 has no such second
            # toggle. idle_w/expected_boot_s are UNMEASURED GUESSES —
            # onboard_device.py never ran; run it before trusting any row.
            "label": "Xiaomi TV Box (Gen 3)", "plug_name": "Lab-F4",
            "plug_ip": "192.168.1.33",
            "kind": "adb", "target": "192.168.1.192:5555",
            "macs": ["9c:9d:07:8c:87:7e"],   # wlan0 — confirmed live via ARP + adb connect
            "device_class": "stb",
            "os": "Google TV (Android 14)", "chip_vendor": "Amlogic",
            # Confirmed 2026-09-03 from logcat on the n=3 batch: Codec2 hardware
            # decoders c2.amlogic.{avc,hevc,av1,vp9}.decoder for all four codecs.
            "silicon": "Amlogic s7d · Android 14 · hw H.264/HEVC/AV1/VP9 (c2.amlogic.*)",
            "network": "wifi",
            # Live/temporary for the Gen2-vs-Gen3 A/B (2026-09-02): cabled to
            # HDMI_4, took over the Apple TV's old panel input while the
            # Apple TV sits aside decommissioned. Carried via /settings
            # rig_hdmi_inputs ({"xiaomi3": "HDMI_4", "atv": ""}), not
            # hardcoded — revert cleanly once the A/B concludes.
            "hdmi_input": None,
            "expected_boot_s": 60, "boot_threshold_w": 0.4,   # UNMEASURED guess
            "shutdown_wait_s": 15,
            "idle_w": 1.5,   # UNMEASURED guess — replace via onboard_device.py
        },
        "roku": {
            # Roku Express 4K, onboarded 2026-08-29. No ADB/logcat equivalent
            # — control + liveness are both ECP (port 8060, "Control by
            # mobile apps" set to Permissive on the box, confirmed working
            # live). Playback (bench.py RokuDevice) uses Dom's own
            # pre-installed "Greening of Streaming" channel (app id 775528,
            # built for hackathons) — NOT the Media Assistant community hack
            # first attempted; that path is abandoned (see JOURNAL/memory
            # roku-gos-channel-2026-08-29 for the full story).
            #
            # ⚠ ONE-TIME MANUAL SETTING, required for this to work at all:
            # in the app's own on-screen settings, its playlist URL must be
            # set to http://192.168.1.62:8123/gos_local_test.m3u — the app's
            # own default (one of Dom's personal domains) is dead, which is
            # why every attempt 404s until this is set. If this box is ever
            # factory-reset or the app reinstalled, re-enter this URL by hand
            # before anything will play. RokuDevice.PLAYLIST_URL/PATH in
            # bench.py hold the same values — keep both in sync if it moves.
            "label": "Roku Express 4K", "plug_name": "Lab-F5",
            "plug_ip": "192.168.1.113",
            "kind": "roku", "target": "192.168.1.13",
            "macs": ["d4:e2:2f:e2:39:bb"],   # Wi-Fi only, no Ethernet port
            "device_class": "stb",
            "os": "Roku OS 14.0.4", "chip_vendor": "Realtek",
            "silicon": "Realtek RTD1315 · hw H.264/HEVC/VP9/AV1 per spec"
                       " — unconfirmed (Roku has no decoder-provenance signal"
                       " of any kind, unlike the Android boxes' logcat)",
            "network": "wifi",
            # HDMI_3, physically re-cabled 2026-08-29 (took the Pi 400's old
            # socket, on-site during the switch install).
            "hdmi_input": "HDMI_3",
            "expected_boot_s": 30, "boot_threshold_w": 0.5,   # UNMEASURED guess
            "shutdown_wait_s": 10,
            "idle_w": 2.0,   # UNMEASURED guess — replace via onboard_device.py
        },
        "c2": {
            # The C2 as a native decoder (CR-071): its own α9 SoC decodes+
            # displays the clip in the built-in webOS browser. It IS the shared
            # screen, so it shares the monitor's Lab-E plug and has NO
            # independent power/boot and NO hdmi_input. kind "webos" is
            # special-cased throughout: ready whenever webOS answers; power/boot/
            # cycle refused (that plug is the shared panel). Metered on Lab-E →
            # all-in figure; isolate decode by the differential (native minus a
            # GTV-on-HDMI run of the same clip). No idle_w → the pre-job guard
            # runs in self-stability mode (the ~40-85 W panel is content-driven,
            # so a fixed reference floor is meaningless; the marker head + the
            # differential carry the measurement).
            "label": "LG C2 (native)", "plug_name": "Lab-E",
            "plug_ip": "192.168.1.71",
            "kind": "webos", "target": "192.168.1.26",   # moved from .25, 2026-08-29 (see monitor.lg_host note)
            "device_class": "tv",
            "os": "webOS 22", "chip_vendor": "LG",
            "silicon": "LG α9 Gen5 · hw H.264/HEVC/VP9/AV1",
            "network": "ethernet",   # (also on Wi-Fi .109 — we use Ethernet)
            "expected_boot_s": 15, "boot_threshold_w": 5.0,
            "shutdown_wait_s": 0,
        },
    },
    "monitor": {
        "label": "Shared screen", "plug_name": "Lab-E",
        "plug_ip": "192.168.1.71",
        "panel": "LG OLED55C2 (OLED55C25LB)",
        # The panel has exactly four HDMI inputs; which four of the external
        # devices are cabled to them is the screen map — rig.py defaults per
        # device (`hdmi_input`) overridden from /settings `rig_hdmi_inputs`
        # (2026-08-26: seven devices, four sockets — a device without an
        # input cannot claim the screen or run screen mode).
        "hdmi_inputs": ["HDMI_1", "HDMI_2", "HDMI_3", "HDMI_4"],
        # webOS control (CR-071): lg_host set ⇒ claim_screen is an explicit
        # HDMI input-select, not the auto-switch/DPMS dance. Client key at
        # lg.CLIENT_KEY_PATH. Moved `.25` → `.26` 2026-08-29 (the switch-
        # install reservation drift that broke every claim-screen attempt —
        # confirmed via `paired: True` at the new address, same physical TV,
        # same stored key). The C2 is also on Wi-Fi `.109`. ⚠ webOS has no
        # MAC-follower support (unlike the adb/atv devices) — if this drifts
        # again, it has to be found and fixed by hand like this, not
        # automatically. Worth a router-side reservation recheck for `.26`
        # so it doesn't drift again on the next lease renewal.
        "lg_host": "192.168.1.26",
        # Above this draw the panel is showing a picture — could be Ben's Mac
        # extension, so the Off button asks for confirmation client-side.
        "in_use_threshold_w": 15.0,
    },
    # Shelly on the new 8-way strip (2026-08-29 switch install) — every
    # device plug EXCEPT the C2/monitor (Lab-E) now runs through it: all 8
    # rig.py devices (pi5, pi400, firestick, gtv, bbox, atv, xiaomi, roku).
    # Useful sanity check (Ben, 2026-08-29): with all 8 running, sum of the
    # 8 individual P110 readings should track the Shelly's own apower_w —
    # a live cross-check against meter drift, independent of the individual
    # per-device Tapo readings. None ⇒ master tile absent. Settings key
    # rig_shelly_ip overrides. Generation AND capability are auto-detected:
    # the installed unit (2026-07-29) is a Plug PM Gen3 (S3PL-30116EU) — a
    # 16 A pass-through METER with no relay (RPC exposes PM1.*, no Switch.*),
    # so the tile is strip-metering only; swap in a relay model (Plug S,
    # 1PM) and the Rig on/off button appears without a code change.
    "shelly_ip": "192.168.1.17",
    "tapo_standby_w": 0.65,   # per-plug standby the master switch saves
}

_STOPPED_STATES = ("off", "unpowered", "unreachable")
_READY_DETAIL = {"ssh": "ssh ok", "adb": "adb ok", "atv": "pyatv ok", "roku": "ECP ok"}
_WAIT_LABEL = {"ssh": "SSH", "adb": "ADB", "atv": "pyatv", "roku": "ECP"}

# --- Idle auto-off ---------------------------------------------------------
#
# Origin: 2026-08 — Ben came back after a week away to find every rig device
# powered. The rig is OFF by default; anything that turns a box on must also
# have a way to turn it off again without a human remembering. Activity =
# any Lab control op, a Lab visit to /decode, an OWL decode job (start/end +
# every poll while busy), a device powered from outside the UI (adopted by
# the poller), or a fresh RIG_HOLD_FILE (touched per row by bench.py so a
# standalone CLI campaign — overnight_queue.sh — is never cut mid-run).
# Per-device target overrides from /settings (`rig_target_overrides`, e.g.
# {"gtv": "192.168.1.143:5555"}) — 2026-08-19, CR-074: a box moved from Ethernet
# to Wi-Fi comes back on a different DHCP address; the rig must follow it
# without a code edit. Applied in place at import and on every poller sweep,
# so a settings change takes effect within ~10 s. The original wired targets
# stay in RIG_TARGETS_DEFAULT for the day the cable goes back in.
RIG_TARGETS_DEFAULT: dict = {n: d.get("target") for n, d in RIG["devices"].items()}

# Target discovery by MAC (2026-08-26). The adb targets above are DHCP
# addresses, and a box takes a new lease whenever it moves between Ethernet
# and Wi-Fi (CR-074 cable pulls) or the router forgets a reservation: the
# Bbox came up on .173 (Wi-Fi) while rig.py said .10, and the rig reported
# "stuck — not ready after 145s" with the box running happily at 4.9 W (R3a).
# Each adb device lists the MACs of ALL its interfaces (`macs`); when a
# powered adb box fails its readiness probe past its expected boot time, the
# poller looks those MACs up in the kernel neighbour table (after a ~2 s
# ping sweep of the /24 to populate it) and follows the box to wherever it
# answers. In-memory only — logged, shown in the tile (`target_source`),
# forgotten when the box goes off. Precedence: discovered > /settings
# override > rig.py default (a discovered address was just seen on the wire;
# an override can be as stale as the default).
DISCOVERED_TARGETS: dict = {}          # name → "ip:5555" found by MAC
_discover_last: dict = {}              # name → monotonic of the last sweep
DISCOVER_MIN_INTERVAL_S = 45
_LAN_PREFIX = "192.168.1."
_NEIGH_STATE_RANK = {"REACHABLE": 0, "DELAY": 1, "PROBE": 1, "STALE": 2}


def _parse_neigh(text: str) -> dict:
    """`ip -4 neigh show` → {mac: ip}; the freshest entry wins per MAC,
    FAILED/INCOMPLETE entries are ignored."""
    best: dict = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4 or "lladdr" not in parts:
            continue
        ip = parts[0]
        mac = parts[parts.index("lladdr") + 1].lower()
        rank = _NEIGH_STATE_RANK.get(parts[-1])
        if rank is None:
            continue
        if mac not in best or rank < best[mac][0]:
            best[mac] = (rank, ip)
    return {mac: ip for mac, (_, ip) in best.items()}


def _neigh_table() -> dict:
    try:
        return _parse_neigh(_run(["ip", "-4", "neigh", "show"], timeout=5).stdout)
    except Exception:
        return {}


def _ping_sweep(prefix: str = _LAN_PREFIX) -> None:
    """One ICMP echo to every host of the /24, in parallel (~2 s) — only to
    populate the neighbour table; replies are not inspected."""
    from concurrent.futures import ThreadPoolExecutor

    def _one(i: int) -> None:
        try:
            subprocess.run(["ping", "-c", "1", "-W", "1", "-q", f"{prefix}{i}"],
                           capture_output=True, timeout=3)
        except Exception:
            pass
    with ThreadPoolExecutor(max_workers=128) as ex:
        list(ex.map(_one, range(1, 255)))


def discover_target(dev: dict) -> str | None:
    """Find an adb device's current address by MAC: neighbour table first,
    then a ping sweep and a second look. Returns "ip:5555" or None. Runs in
    a thread."""
    macs = [m.lower() for m in dev.get("macs", [])]
    if not macs:
        return None
    suffix = ":5555" if dev.get("kind") == "adb" else ""   # pyatv targets are bare IPs
    for attempt in (0, 1):
        table = _neigh_table()
        for mac in macs:
            if mac in table:
                return f"{table[mac]}{suffix}"
        if attempt == 0:
            _ping_sweep()
    return None


def target_source(name: str) -> str:
    """Where a device's effective target came from: discovered | settings |
    default (for the tile and status.json)."""
    if name in DISCOVERED_TARGETS:
        return "discovered"
    dev = RIG["devices"].get(name) or {}
    return "default" if dev.get("target") == RIG_TARGETS_DEFAULT.get(name) else "settings"


def apply_target_overrides(overrides: dict | None = None) -> dict:
    """Merge settings `rig_target_overrides` into RIG in place; returns the
    effective {name: target}. Unknown names / empty values are ignored; a
    device absent from the dict reverts to its default target. A target the
    poller discovered by MAC (DISCOVERED_TARGETS) outranks both."""
    if overrides is None:
        try:
            import settings as _cfg
            overrides = _cfg.load().get("rig_target_overrides") or {}
        except Exception:
            overrides = {}
    if not isinstance(overrides, dict):
        overrides = {}
    eff = {}
    for name, dev in RIG["devices"].items():
        t = DISCOVERED_TARGETS.get(name) or overrides.get(name)
        dev["target"] = str(t) if t else RIG_TARGETS_DEFAULT.get(name)
        eff[name] = dev["target"]
    return eff


apply_target_overrides()

# --- Screen map: which device sits on which of the panel's HDMI inputs ------
RIG_HDMI_DEFAULT: dict = {n: d.get("hdmi_input") for n, d in RIG["devices"].items()}


def apply_hdmi_assignments(overrides: dict | None = None) -> dict:
    """Merge settings `rig_hdmi_inputs` ({device: "HDMI_n" | ""}) into RIG in
    place; returns the effective {input: device | None} over the monitor's
    inputs. Rules: a device absent from the dict keeps its rig.py default,
    "" explicitly unplugs it, unknown devices/inputs are ignored, the webOS
    panel never has an input (it IS the screen), and an input holds ONE
    device — a second claimant (in RIG order) is dropped with a log line."""
    if overrides is None:
        try:
            import settings as _cfg
            overrides = _cfg.load().get("rig_hdmi_inputs") or {}
        except Exception:
            overrides = {}
    if not isinstance(overrides, dict):
        overrides = {}
    inputs = list(RIG["monitor"].get("hdmi_inputs") or [])
    taken: dict = {}
    for name, dev in RIG["devices"].items():
        if dev.get("kind") == "webos":
            dev["hdmi_input"] = None
            continue
        want = overrides[name] if name in overrides else RIG_HDMI_DEFAULT.get(name)
        want = str(want).strip() if want else None
        if want and want not in inputs:
            log.warning("rig: %s → unknown HDMI input %r ignored", name, want)
            want = None
        if want and want in taken:
            log.warning("rig: %s and %s both mapped to %s — keeping %s",
                        taken[want], name, want, taken[want])
            want = None
        dev["hdmi_input"] = want
        if want:
            taken[want] = name
    return {inp: taken.get(inp) for inp in inputs}


def screen_claimable(dev_cfg: dict) -> bool:
    """THE rule for "may this device take the shared screen": the webOS panel
    always (it is the screen), anything else only when the screen map puts
    it on one of the panel's HDMI inputs. Used by claim_screen, the run
    route's screen-mode check and status.json (`screen_claimable`) — the UI
    reads the boolean and carries no device-specific knowledge."""
    return dev_cfg.get("kind") == "webos" or bool(dev_cfg.get("hdmi_input"))


def not_claimable_reason(dev_cfg: dict) -> str:
    return (f"{dev_cfg['label']} is not cabled to one of the screen's "
            f"{len(RIG['monitor'].get('hdmi_inputs') or [])} HDMI inputs "
            "— assign it under /settings › Rig › HDMI inputs first")


def hdmi_map() -> dict:
    """{input: device | None} from the current RIG state (no settings IO)."""
    inputs = list(RIG["monitor"].get("hdmi_inputs") or [])
    by_input = {d.get("hdmi_input"): n for n, d in RIG["devices"].items()
                if d.get("hdmi_input")}
    return {inp: by_input.get(inp) for inp in inputs}


apply_hdmi_assignments()

RIG_HOLD_FILE = Path("/tmp/owl-rig-hold")
# Ignore hold files older than this (a stale touch from a crashed campaign
# must not pin the rig on forever) — generous vs bench.py's per-row cadence.
HOLD_STALE_S = 30 * 60


def touch_activity(reason: str = "") -> None:
    """Record rig activity now (wall clock — the idle window is hours)."""
    rig_cache["last_activity"] = time.time()
    rig_cache["last_activity_reason"] = reason


def idle_off_settings() -> dict:
    """{"enabled", "hours", "monitor"} from /settings (defaults if unavailable)."""
    try:
        import settings as _cfg
        s = _cfg.load()
    except Exception:
        s = {}
    try:
        hours = float(s.get("rig_idle_off_hours", 4.0))
    except (TypeError, ValueError):
        hours = 4.0
    return {"enabled": s.get("rig_idle_off_enabled", True)
                       in (True, "true", "on", "1", 1),
            "hours": max(0.25, hours),
            "monitor": s.get("rig_idle_off_monitor", False)
                       in (True, "true", "on", "1", 1)}


def _hold_file_mtime() -> float | None:
    try:
        return RIG_HOLD_FILE.stat().st_mtime
    except OSError:
        return None


def last_activity() -> float:
    """Wall-clock time of the most recent activity — the later of the
    in-process record and a non-stale hold-file touch."""
    t = rig_cache.get("last_activity") or 0.0
    hm = _hold_file_mtime()
    if hm is not None and time.time() - hm <= HOLD_STALE_S:
        t = max(t, hm)
    return t


def _powered_devices() -> list:
    """Device names the idle timer would stop: relay on (any non-stopped,
    non-stopping state), excluding the webOS C2 (it IS the shared screen;
    the monitor plug is handled by rig_idle_off_monitor)."""
    return [n for n, d in rig_cache["devices"].items()
            if RIG["devices"][n].get("kind") != "webos"
            and not RIG["devices"][n].get("parked")
            and d["state"] not in _STOPPED_STATES and d["state"] != "stopping"]


def idle_off_state() -> dict:
    """Idle-timer readout for the console: {"enabled", "hours", "idle_s",
    "armed" (something is powered so the timer is counting), "off_in_s",
    "last": the last auto-off event or None}."""
    st = idle_off_settings()
    hold_touched = _hold_file_mtime()
    idle_s = max(0.0, time.time() - last_activity())
    armed = bool(st["enabled"] and _powered_devices())
    limit = st["hours"] * 3600
    return {"enabled": st["enabled"], "hours": st["hours"],
            "monitor": st["monitor"], "idle_s": round(idle_s),
            "armed": armed,
            "off_in_s": (max(0, round(limit - idle_s)) if armed else None),
            "hold_active": bool(hold_touched is not None
                                and time.time() - hold_touched <= HOLD_STALE_S),
            "last": rig_cache.get("idle_off_last")}


async def _maybe_idle_off() -> bool:
    """Called once per poll sweep. Fires the auto-off when the timer has
    elapsed; returns True when it fired. Never raises."""
    st = idle_off_settings()
    if not st["enabled"]:
        return False
    if any(d["busy"] for d in rig_cache["devices"].values()):
        touch_activity("job running")
        return False
    powered = _powered_devices()
    if not powered:
        return False
    idle_s = time.time() - last_activity()
    if idle_s < st["hours"] * 3600:
        return False
    log.warning("rig idle auto-off: %.1f h without activity — stopping %s",
                idle_s / 3600, ", ".join(powered))
    stopped, errors = [], []
    for name in powered:
        try:
            await device_off(name)
            stopped.append(name)
        except Exception as e:
            errors.append(f"{RIG['devices'][name]['label']}: {e}")
    if st["monitor"]:
        try:
            await monitor_power(False)
            stopped.append("monitor")
        except Exception as e:
            errors.append(f"monitor: {e}")
    rig_cache["idle_off_last"] = {
        "at": time.time(), "idle_h": round(idle_s / 3600, 2),
        "stopped": stopped, "errors": errors, "master": None}
    # Reset the clock so a stop that fails to complete isn't re-fired every
    # sweep; the next elapsed window will try again.
    touch_activity("idle auto-off")
    if rig_cache["master"].get("switchable"):
        asyncio.create_task(_idle_off_master())
    return True


async def _idle_off_master(budget_s: int = 180) -> None:
    """After an idle auto-off, wait for the graceful stops to land, then cut
    the switchable master too (saves the plugs' Tapo standby — the "whole
    rig" off Ben asked for). Gives up quietly if a box never reaches off."""
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        if not any(d["state"] not in _STOPPED_STATES
                   for n, d in rig_cache["devices"].items()
                   if RIG["devices"][n].get("kind") != "webos"
                   and not RIG["devices"][n].get("parked")):
            try:
                await master_power(False)
                if rig_cache.get("idle_off_last"):
                    rig_cache["idle_off_last"]["master"] = "off"
            except Exception as e:
                if rig_cache.get("idle_off_last"):
                    rig_cache["idle_off_last"]["master"] = f"failed: {e}"
            return
        await asyncio.sleep(5)
    if rig_cache.get("idle_off_last"):
        rig_cache["idle_off_last"]["master"] = "skipped: a device never reached off"


def shelly_ip() -> str | None:
    """Configured Shelly master IP — settings key `rig_shelly_ip` wins over the
    RIG constant so Ben can enable the master from /settings without a deploy."""
    try:
        import settings as _cfg
        return (_cfg.load().get("rig_shelly_ip") or "").strip() or RIG["shelly_ip"]
    except Exception:
        return RIG["shelly_ip"]


def master_tapo_ip() -> str | None:
    """Optional Tapo P110 acting as the strip's MASTER SWITCH (the installed
    Shelly Plug PM is metering-only — no relay, verified at RPC level
    2026-07-29). Chain: wall → this P110 (switch) → Shelly (meter) → strip.
    Settings key `rig_master_tapo_ip`; None ⇒ no switchable master."""
    try:
        import settings as _cfg
        return (_cfg.load().get("rig_master_tapo_ip") or "").strip() or None
    except Exception:
        return None


# --- Tapo plug control (arbitrary IPs) --------------------------------------
#
# Same recovery pattern as power.py's _read_meter_watts: cached handle per IP,
# per-IP asyncio lock (KLAP sessions are exclusive), drop + rebuild on error.
# Separate caches from power.py — the bench meter must never share a handle.

_PLUG_CACHE: dict = {}
_PLUG_LOCKS: dict = {}
_RESOLVED_IP: dict = {}   # device plug key → the candidate IP that answered

# Plug IPs a running measurement owns right now (Stage 2 sets this while
# bench.py samples at 1.5 s) — the rig poller skips these entirely so it never
# contends for the KLAP session mid-row.
PAUSED_PLUGS: set = set()


async def _plug_handle(ip: str):
    from tapo import ApiClient
    device = _PLUG_CACHE.get(ip)
    if device is None:
        client = ApiClient(_config["TAPO_EMAIL"], _config["TAPO_PASSWORD"])
        device = await client.p110(ip)
        _PLUG_CACHE[ip] = device
    return device


async def _resolve_ip(plug_ip) -> str:
    """plug_ip may be one IP or a candidate list; return the first that
    answers (cached until it stops answering)."""
    if isinstance(plug_ip, str):
        return plug_ip
    key = tuple(plug_ip)
    cached = _RESOLVED_IP.get(key)
    order = ([cached] + [ip for ip in plug_ip if ip != cached]) if cached else list(plug_ip)
    last_err = None
    for ip in order:
        try:
            lock = _PLUG_LOCKS.setdefault(ip, asyncio.Lock())
            async with lock:
                d = await asyncio.wait_for(_plug_handle(ip), 8)
                await asyncio.wait_for(d.get_device_info(), 8)
            _RESOLVED_IP[key] = ip
            return ip
        except Exception as e:
            _PLUG_CACHE.pop(ip, None)
            last_err = e
    raise last_err or RuntimeError(f"no plug answered at {plug_ip}")


async def plug_status(plug_ip, retries: int = 2) -> dict:
    """{"on": bool, "watts": float, "ip": str} for the plug at plug_ip
    (str or candidate list). Raises on total failure — callers map that to
    unreachable/unpowered."""
    ip = await _resolve_ip(plug_ip)
    lock = _PLUG_LOCKS.setdefault(ip, asyncio.Lock())
    for attempt in range(retries):
        try:
            async with lock:
                d = await _plug_handle(ip)
                info = await asyncio.wait_for(d.get_device_info(), 10)
                energy = await asyncio.wait_for(d.get_energy_usage(), 10)
            return {"on": bool(info.device_on),
                    "watts": energy.current_power / 1000.0, "ip": ip}
        except Exception:
            _PLUG_CACHE.pop(ip, None)
            if attempt == retries - 1:
                raise
            await asyncio.sleep(1)


async def plug_set(plug_ip, on: bool, retries: int = 2) -> None:
    ip = await _resolve_ip(plug_ip)
    lock = _PLUG_LOCKS.setdefault(ip, asyncio.Lock())
    for attempt in range(retries):
        try:
            async with lock:
                d = await _plug_handle(ip)
                await asyncio.wait_for(d.on() if on else d.off(), 10)
            return
        except Exception:
            _PLUG_CACHE.pop(ip, None)
            if attempt == retries - 1:
                raise
            await asyncio.sleep(1)


# --- Shelly master (generation auto-detect) ---------------------------------

_SHELLY_GEN: dict = {}   # ip → 1 | 2


def _http_json(url: str, timeout: float = 6.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _shelly_probe(ip: str) -> dict:
    """Detect generation AND capability. Gen2+: has Switch.* → switchable;
    only PM1.* (Plug PM Gen3) → meter-only. Gen1: /status with relays[]."""
    try:
        _http_json(f"http://{ip}/rpc/Shelly.GetDeviceInfo")
    except Exception:
        s = _http_json(f"http://{ip}/status")   # raises if not Gen1 either
        return {"gen": 1, "switchable": bool(s.get("relays"))}
    methods = _http_json(f"http://{ip}/rpc/Shelly.ListMethods").get("methods", [])
    return {"gen": 2, "switchable": "Switch.GetStatus" in methods,
            "pm1": "PM1.GetStatus" in methods}


def _shelly_caps(ip: str) -> dict:
    caps = _SHELLY_GEN.get(ip)
    if caps is None:
        caps = _shelly_probe(ip)
        _SHELLY_GEN[ip] = caps
    return caps


def _shelly_status_sync(ip: str) -> dict:
    caps = _shelly_caps(ip)
    if caps["gen"] >= 2:
        if caps["switchable"]:
            s = _http_json(f"http://{ip}/rpc/Switch.GetStatus?id=0")
            return {"on": bool(s.get("output")), "apower_w": s.get("apower"),
                    "gen": caps["gen"], "switchable": True}
        s = _http_json(f"http://{ip}/rpc/PM1.GetStatus?id=0")
        return {"on": None, "apower_w": s.get("apower"),
                "gen": caps["gen"], "switchable": False}
    s = _http_json(f"http://{ip}/status")
    relay = (s.get("relays") or [{}])[0]
    meter = (s.get("meters") or [{}])[0]
    return {"on": bool(relay.get("ison")) if s.get("relays") else None,
            "apower_w": meter.get("power"), "gen": 1,
            "switchable": bool(s.get("relays"))}


def _shelly_set_sync(ip: str, on: bool) -> None:
    caps = _shelly_caps(ip)
    if not caps.get("switchable"):
        raise RigError(400, "master plug is metering-only (no relay) — "
                            "cannot switch the strip")
    if caps["gen"] >= 2:
        _http_json(f"http://{ip}/rpc/Switch.Set?id=0&on={'true' if on else 'false'}")
    else:
        _http_json(f"http://{ip}/relay/0?turn={'on' if on else 'off'}")


async def shelly_status() -> dict:
    """Master status — a switchable Tapo master (wall→P110→Shelly→strip)
    takes precedence when configured; else the Shelly (switch if it has a
    relay, meter otherwise). {"configured", "reachable", "on" (None when
    meter-only), "apower_w", "gen", "switchable", "kind"}. Never raises.

    With a Tapo master OFF, the downstream Shelly meter is unpowered — the
    Tapo's own reading (≈0 W) stands in, so the strip bar shows 0.0 W
    instead of 'not answering'."""
    t_ip = master_tapo_ip()
    if t_ip:
        try:
            ps = await plug_status(t_ip)
            out = {"configured": True, "reachable": True, "on": ps["on"],
                   "apower_w": round(ps["watts"], 1), "gen": None,
                   "switchable": True, "kind": "tapo"}
        except Exception:
            return {"configured": True, "reachable": False, "on": None,
                    "apower_w": None, "gen": None, "switchable": True,
                    "kind": "tapo"}
        # Prefer the inline Shelly's reading while the strip is live (it
        # excludes the master's own relay draw); fall back to the Tapo's.
        if ps["on"]:
            s_ip = shelly_ip()
            if s_ip:
                try:
                    s = await asyncio.to_thread(_shelly_status_sync, s_ip)
                    if s.get("apower_w") is not None:
                        out["apower_w"] = round(s["apower_w"], 1)
                except Exception:
                    pass
        return out
    ip = shelly_ip()
    if not ip:
        return {"configured": False, "reachable": False, "on": None,
                "apower_w": None, "gen": None, "switchable": False,
                "kind": None}
    try:
        s = await asyncio.to_thread(_shelly_status_sync, ip)
        return {"configured": True, "reachable": True, "kind": "shelly", **s}
    except Exception:
        caps = _SHELLY_GEN.get(ip) or {}
        return {"configured": True, "reachable": False, "on": None,
                "apower_w": None, "gen": caps.get("gen"),
                "switchable": caps.get("switchable", False),
                "kind": "shelly"}


async def shelly_set(on: bool) -> None:
    ip = shelly_ip()
    if not ip:
        raise RigError(400, "master switch not configured")
    await asyncio.to_thread(_shelly_set_sync, ip, on)


# --- Device probes / graceful shutdown (subprocess, monkeypatchable) --------

_SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=4",
             "-o", "StrictHostKeyChecking=accept-new"]


def _run(cmd: list, timeout: int = 20):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# --- Apple TV (pyatv) ---------------------------------------------------------
ATV_CREDS_DIR = Path("/srv/data/owl/atv")
_ATVREMOTE_CANDIDATES = ("/srv/data/owl/pyatv-venv/bin/atvremote",
                         "/tmp/pyatv-venv/bin/atvremote")


def atvremote_bin() -> str | None:
    for c in _ATVREMOTE_CANDIDATES:
        if Path(c).is_file():
            return c
    return None


def atv_cmd(dev: dict, *cmds: str, timeout: int = 40) -> str:
    """Run atvremote against the device with the stored Companion + AirPlay
    credentials; returns stdout+stderr. Raises if pyatv is not installed."""
    bin_ = atvremote_bin()
    if not bin_:
        raise RuntimeError("atvremote not installed (pyatv venv missing)")
    cc = (ATV_CREDS_DIR / "companion_creds").read_text().strip()
    ac = (ATV_CREDS_DIR / "airplay_creds").read_text().strip()
    r = _run([bin_, "-s", dev["target"], "--companion-credentials", cc,
              "--airplay-credentials", ac, *cmds], timeout=timeout)
    return (r.stdout or "") + (r.stderr or "")


_ATV_LAST_POWER: dict = {}     # target → last "On"/"Off"/None seen by atv_power_state


def atv_power_state(dev: dict) -> str | None:
    """"On" / "Off" / None (unreachable) from `atvremote power_state`.
    "Off" = tvOS asleep (mains still on) — with no HDMI attached the box
    sleeps within minutes of being parked (2026-08-26)."""
    state = None
    try:
        out = atv_cmd(dev, "power_state", timeout=25)
        for line in out.splitlines():
            if "PowerState." in line:
                state = line.strip().rsplit(".", 1)[-1]
    except Exception:
        state = None
    _ATV_LAST_POWER[dev.get("target")] = state
    return state


def atv_wake(dev: dict) -> None:
    """Wake a sleeping Apple TV (pyatv turn_on). Best-effort; a cold-booting
    box just ignores it."""
    try:
        atv_cmd(dev, "turn_on", timeout=25)
    except Exception:
        log.debug("atv_wake failed for %s", dev.get("label"), exc_info=True)


def probe_ready(dev: dict) -> bool:
    """True when the device is ready for work: SSH answers (Pis), Android
    reports boot completed (GTV), pyatv reports PowerState.On (Apple TV).
    Runs in a thread; must stay cheap."""
    try:
        if dev["kind"] == "webos":
            return lg.status(dev["target"]).get("reachable", False)
        if dev["kind"] == "ssh":
            return _run(["ssh"] + _SSH_OPTS + [dev["target"], "true"]).returncode == 0
        if dev["kind"] == "atv":
            return atv_power_state(dev) == "On"
        if dev["kind"] == "roku":
            with urllib.request.urlopen(
                    f"http://{dev['target']}:8060/query/device-info", timeout=6) as r:
                return r.status == 200
        serial = dev["target"]
        _run([ADB_BIN, "connect", serial], timeout=10)
        out = _run([ADB_BIN, "-s", serial, "shell", "getprop",
                    "sys.boot_completed"], timeout=10).stdout
        return out.strip().endswith("1")
    except Exception:
        return False


def adb_auth_state(dev: dict) -> str | None:
    """Transport state of an adb device as `adb devices` reports it:
    "device" (authorised), "unauthorized" (the box is showing its "Allow USB
    debugging?" prompt and waiting for a remote-control OK), "offline", or
    None (not in the list / not an adb device). Runs in a thread.

    2026-08-15: both adb boxes came back from a cold power-up unauthorised
    and sat in `stuck` for hours — the probe can't distinguish "not booted"
    from "booted but rejecting our key", and the prompt was invisible because
    the TV was asleep on another input. This is what tells the tile apart."""
    if dev.get("kind") != "adb":
        return None
    try:
        out = _run([ADB_BIN, "devices"], timeout=10).stdout
    except Exception:
        return None
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[0] == dev["target"]:
            return parts[1]
    return None


def adb_host_fingerprint() -> str | None:
    """MD5 fingerprint of GoS1's adb host key, formatted the way Android
    shows it in the "Allow USB debugging?" dialog — so the operator can
    match the prompt to this machine before accepting."""
    import base64
    import hashlib
    from pathlib import Path as _P
    try:
        pub = _P.home() / ".android" / "adbkey.pub"
        b64 = pub.read_text().split()[0]
        return ":".join(f"{x:02X}" for x in
                        hashlib.md5(base64.b64decode(b64)).digest())
    except Exception:
        return None


def adb_reconnect(dev: dict) -> None:
    """ONE disconnect + connect. Each connect while unauthorised queues one
    more prompt on the box (Ben had to accept 4× per box on 2026-08-15 after
    repeated manual reconnects) — the repair path sends exactly one."""
    serial = dev["target"]
    _run([ADB_BIN, "disconnect", serial], timeout=10)
    time.sleep(1)
    _run([ADB_BIN, "connect", serial], timeout=15)


_WL_ENV = "WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000"


def set_signal(dev: dict, on: bool) -> None:
    """Raise/drop the device's HDMI signal WITHOUT touching power.

    The shared monitor does not gate hot-plug per input (verified 2026-07-29:
    the GTV still saw full EDID while the Pi 5 held the picture), so devices
    cannot detect losing the screen. Arbitration is therefore active: the
    screen goes to whichever single device has a live signal.

    Reliability lessons (first live claims, 2026-07-29):
    - Pi raise must PULSE (off → 2 s → on): a plain --on is a no-op when the
      output is already enabled — no fresh hot-plug, the panel never re-scans.
    - GTV wake/sleep must retry + verify mWakefulness: a single keyevent
      frequently doesn't stick (same finding as bench.py's prepare())."""
    if dev["kind"] in ("atv", "roku"):
        return      # no per-input signal control over pyatv/ECP; the C2 input-select path does the arbitration
    if dev["kind"] == "ssh":
        # DPMS via wlopm, NOT output disable via wlr-randr: labwc auto-revives
        # a session's only output when disabled (seen live 2026-07-29 as the
        # Pi 400's black-desktop-with-cursor stealing the panel back). DPMS
        # drops the TMDS signal while the output stays configured — nothing
        # for the compositor to revert.
        if on:
            # Repair every layer, then pulse: re-enable any wlr-disabled
            # output (a leftover --off makes DPMS a no-op on zero heads —
            # bit the Pi 5 on 2026-07-29), then DPMS off→on for the fresh
            # signal transition the panel's auto-switch needs.
            cmd = (f"outs=$({_WL_ENV} wlr-randr | awk '/^[[:alnum:]]/{{print $1}}'); "
                   f"for o in $outs; do {_WL_ENV} wlr-randr --output $o --on || true; done; "
                   f"sleep 1; {_WL_ENV} wlopm --off '*'; sleep 2; "
                   f"{_WL_ENV} wlopm --on '*'")
        else:
            cmd = f"{_WL_ENV} wlopm --off '*'"
        r = _run(["ssh"] + _SSH_OPTS + [dev["target"], cmd], timeout=40)
        if r.returncode != 0:
            raise RuntimeError(
                f"{dev['label']}: signal raise/drop failed "
                f"(rc={r.returncode} {(r.stderr or '').strip()[:120]})")
        return
    serial = dev["target"]
    _run([ADB_BIN, "connect", serial], timeout=10)
    if on:
        # A wake keyevent on an already-Awake box produces NO signal
        # transition and the panel never re-scans — force one: sleep first
        # if awake, then wake + HOME so the box actually draws.
        state = _run([ADB_BIN, "-s", serial, "shell",
                      "dumpsys power | grep -m1 mWakefulness"], timeout=15).stdout
        if "mWakefulness=Awake" in state:
            _run([ADB_BIN, "-s", serial, "shell", "input", "keyevent",
                  "KEYCODE_SLEEP"], timeout=15)
            time.sleep(3)
    key = "KEYCODE_WAKEUP" if on else "KEYCODE_SLEEP"
    # Sleeping boxes report Asleep OR Dozing (ambient/screensaver state) —
    # both mean the HDMI signal is down. Only Awake counts for wake.
    wants = ("mWakefulness=Awake",) if on else ("mWakefulness=Asleep",
                                                "mWakefulness=Dozing")
    for _ in range(4):
        _run([ADB_BIN, "-s", serial, "shell", "input", "keyevent", key],
             timeout=15)
        time.sleep(2)
        state = _run([ADB_BIN, "-s", serial, "shell",
                      "dumpsys power | grep -m1 mWakefulness"],
                     timeout=15).stdout
        if any(w in state for w in wants):
            if on:
                _run([ADB_BIN, "-s", serial, "shell", "input", "keyevent",
                      "KEYCODE_HOME"], timeout=15)
            return
    raise RuntimeError(f"{dev['label']}: did not reach "
                       + "/".join(w.split('=')[1] for w in wants))


def send_shutdown(dev: dict) -> None:
    """Best-effort graceful shutdown; the relay cut follows after
    shutdown_wait_s regardless."""
    try:
        if dev["kind"] == "ssh":
            _run(["ssh"] + _SSH_OPTS + [dev["target"], "sudo -n shutdown -h now"])
        elif dev["kind"] == "atv":
            atv_cmd(dev, "turn_off", timeout=30)     # tvOS sleep; the relay cut follows
        elif dev["kind"] == "roku":
            # No documented/reliable ECP "power off" — best-effort return to
            # Home before the relay does the real cut (same shape as atv).
            urllib.request.urlopen(urllib.request.Request(
                f"http://{dev['target']}:8060/keypress/Home", method="POST"), timeout=10)
        else:
            serial = dev["target"]
            _run([ADB_BIN, "connect", serial], timeout=10)
            _run([ADB_BIN, "-s", serial, "shell", "reboot", "-p"], timeout=15)
    except Exception:
        log.debug("send_shutdown failed for %s", dev.get("label"), exc_info=True)


# --- State machine + cache ---------------------------------------------------

class RigError(Exception):
    """Control-op refusal; routes map to an HTTP status + reason."""
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _blank_dev() -> dict:
    return {"state": "off", "watts": None, "detail": "", "busy": False,
            "boot_started": None, "elapsed_s": None, "probe_fails": 0,
            "adb_auth": None}


rig_cache: dict = {
    "devices": {name: _blank_dev() for name in RIG["devices"]},
    "monitor": {"on": None, "watts": None, "in_use_hint": False,
                "reachable": False},
    "master": {"configured": False, "reachable": False, "on": None,
               "apower_w": None, "gen": None, "switchable": False},
    "screen_owner": None,
    "updated_monotonic": None,
    # Idle auto-off bookkeeping. Startup counts as activity so a service
    # restart with boxes left on grants a full idle window, never an instant cut.
    "last_activity": time.time(),
    "last_activity_reason": "service start",
    "idle_off_last": None,
}

_OP_LOCKS: dict = {}   # device name → asyncio.Lock for control ops


def _op_lock(name: str) -> asyncio.Lock:
    return _OP_LOCKS.setdefault(name, asyncio.Lock())


async def _step_device(name: str, master_off: bool) -> None:
    dev_cfg = RIG["devices"][name]
    d = rig_cache["devices"][name]
    now = time.monotonic()

    if d["state"] == "stopping":       # owned by the device_off task
        return
    if _plug_key(dev_cfg) & PAUSED_PLUGS:
        d["detail"] = "measuring — polling paused"
        return

    if master_off:
        d.update({"state": "unpowered", "watts": None, "boot_started": None,
                  "elapsed_s": None, "detail": "master off"})
        if rig_cache["screen_owner"] == name:
            rig_cache["screen_owner"] = None
        return

    try:
        ps = await plug_status(dev_cfg["plug_ip"])
    except Exception:
        d.update({"state": "unreachable", "watts": None,
                  "detail": f"{dev_cfg['plug_name']} not answering"})
        return

    d["watts"] = round(ps["watts"], 3)
    if not ps["on"]:
        d.update({"state": "off", "boot_started": None, "elapsed_s": None,
                  "detail": f"{dev_cfg['plug_name']} ready"})
        if rig_cache["screen_owner"] == name:
            rig_cache["screen_owner"] = None
        if DISCOVERED_TARGETS.pop(name, None):
            dev_cfg["target"] = RIG_TARGETS_DEFAULT.get(name)   # re-derived next sweep
        return

    if dev_cfg["kind"] == "webos":
        # No relay boot cycle — webOS answers whenever the PANEL IS AWAKE.
        # In Always-Ready standby the TV answers the SSAP port but rejects
        # every connection with WS close 1008 (2026-08-01: read as a broken
        # TV for half a day; a mains cold boot doesn't help because AC-restore
        # boots back to standby). So probe-fail here usually means ASLEEP,
        # not broken — runs/claims wake it via raw WoL (lg.wake). Do NOT
        # auto-wake from the poller: this is the household's TV. Probe
        # SPARINGLY: a webOS connect is costly — ~every 30 s.
        if d["state"] != "ready" or now - d.get("webos_probed", 0) > 30:
            ready = await asyncio.to_thread(probe_ready, dev_cfg)
            d.update({"state": "ready" if ready else "booting",
                      "probe_fails": 0, "boot_started": None, "elapsed_s": None,
                      "webos_probed": now,
                      "detail": ("webOS ok" if ready else
                                 "asleep (Always-Ready) — a run or claim wakes it")})
        return

    # Relay is on.
    if d["state"] in ("off", "unpowered", "unreachable"):
        # Powered from outside this UI (Tapo app, etc.) — adopt it.
        d["state"] = "powering"
        d["boot_started"] = now
        touch_activity(f"{dev_cfg['label']} powered externally")

    if d["boot_started"] is not None:
        d["elapsed_s"] = round(now - d["boot_started"], 1)

    if d["state"] == "powering" and ps["watts"] >= dev_cfg["boot_threshold_w"]:
        d["state"] = "booting"

    if d["state"] in ("powering", "booting", "stuck"):
        if d["state"] == "stuck" and int(now) % 12 >= 3:
            return    # stuck: keep re-probing, but only every ~4 sweeps
        ready = await asyncio.to_thread(probe_ready, dev_cfg)
        if ready:
            via = (f" · at {dev_cfg['target']} (followed by MAC)"
                   if name in DISCOVERED_TARGETS else "")
            d.update({"state": "ready", "probe_fails": 0, "adb_auth": None,
                      "detail": _READY_DETAIL.get(dev_cfg["kind"], "adb ok") + via})
            return
        # An adb box that answers but rejects our key is a distinct
        # condition: it will NEVER become ready until someone accepts the
        # on-screen prompt — surface it instead of a generic "stuck".
        auth = (await asyncio.to_thread(adb_auth_state, dev_cfg)
                if dev_cfg["kind"] == "adb" else None)
        d["adb_auth"] = auth
        if auth == "unauthorized":
            d.update({"state": "stuck",
                      "detail": "ADB not authorised — needs an on-site OK on the "
                                "box's remote (Repair ADB)"})
            return
        # A sleeping Apple TV answers pyatv with PowerState.Off: powered, not
        # broken — like the C2's Always-Ready standby. Say so; the poller does
        # not wake it (a run, or the On button, does).
        if (dev_cfg["kind"] == "atv"
                and _ATV_LAST_POWER.get(dev_cfg.get("target")) == "Off"):
            d.update({"state": "booting", "boot_started": now, "elapsed_s": 0.0,
                      "detail": "asleep (tvOS) — a run or On wakes it"})
            return
        # Not answering on the configured address past its boot time: it may
        # be up on another lease (Ethernet↔Wi-Fi move) — follow it by MAC
        # before calling it stuck. Rate-limited; the sweep runs in a thread.
        if (dev_cfg["kind"] in ("adb", "atv") and dev_cfg.get("macs")
                and (d["elapsed_s"] or 0) >= dev_cfg["expected_boot_s"]
                and now - _discover_last.get(name, 0) >= DISCOVER_MIN_INTERVAL_S):
            _discover_last[name] = now
            found = await asyncio.to_thread(discover_target, dev_cfg)
            if found and found != dev_cfg["target"]:
                DISCOVERED_TARGETS[name] = found
                dev_cfg["target"] = found
                log.info("rig: %s not at its configured target — followed to %s by MAC",
                         name, found)
                d.update({"state": "booting", "boot_started": now, "elapsed_s": 0.0,
                          "detail": f"found at {found} (by MAC) — retrying ADB"})
                return
        if d["state"] == "stuck":
            return
        limit = 3 * dev_cfg["expected_boot_s"]
        if d["elapsed_s"] is not None and d["elapsed_s"] > limit:
            d.update({"state": "stuck",
                      "detail": f"not ready after {int(d['elapsed_s'])}s — power-cycle?"})
        else:
            d["detail"] = ("waiting for draw" if d["state"] == "powering"
                           else f"waiting on {_WAIT_LABEL.get(dev_cfg['kind'], 'ADB')}")
        return

    if d["state"] in ("ready", "busy"):
        # Cheap liveness re-probe every ~4 poll cycles.
        if int(now) % 12 < 3:
            ready = await asyncio.to_thread(probe_ready, dev_cfg)
            if ready:
                d["probe_fails"] = 0
            else:
                d["probe_fails"] += 1
                if d["probe_fails"] >= 2 and not d["busy"]:
                    d.update({"state": "booting", "boot_started": now,
                              "detail": "lost contact — re-probing"})


def _plug_key(dev_cfg: dict) -> set:
    ips = dev_cfg["plug_ip"]
    return set([ips] if isinstance(ips, str) else ips)


async def poll_once() -> None:
    """One full rig sweep — factored out of rig_poller() so tests can await it
    with the IO functions monkeypatched."""
    master = await shelly_status()
    rig_cache["master"] = master
    master_off = bool(master["configured"] and master["reachable"]
                      and master.get("switchable") and master["on"] is False)

    mon_cfg = RIG["monitor"]
    if _plug_key({"plug_ip": mon_cfg["plug_ip"]}) & PAUSED_PLUGS:
        pass   # a measurement owns the monitor plug — keep last values
    else:
        try:
            ms = await plug_status(mon_cfg["plug_ip"])
            rig_cache["monitor"] = {
                "on": ms["on"], "watts": round(ms["watts"], 2),
                "in_use_hint": ms["watts"] >= mon_cfg["in_use_threshold_w"],
                "reachable": True}
        except Exception:
            rig_cache["monitor"] = {"on": None, "watts": None,
                                    "in_use_hint": False, "reachable": False}

    for name in RIG["devices"]:
        if RIG["devices"][name].get("parked"):
            continue
        try:
            await _step_device(name, master_off)
        except Exception:
            log.debug("rig poll: %s step failed", name, exc_info=True)

    rig_cache["updated_monotonic"] = time.monotonic()
    try:
        await _maybe_idle_off()
    except Exception:
        log.debug("rig idle-off check failed", exc_info=True)


async def rig_poller():
    """Background task (started from main.py startup, like runtime pollers).
    ~3 s cadence while anything is active, ~10 s when the whole rig is idle —
    the Lab plugs share the household KLAP budget with the bench meter."""
    while True:
        try:
            apply_target_overrides()      # /settings may have moved a box (Wi-Fi arms)
            apply_hdmi_assignments()      # …or re-cabled the four HDMI sockets
            await poll_once()
        except Exception:
            log.debug("rig_poller sweep failed", exc_info=True)
        # Exclude the webOS C2: it's "ready" whenever the panel is on, which
        # would otherwise pin the rig at 3 s forever (and re-poll every plug).
        active = any(d["state"] not in ("off", "unpowered", "unreachable")
                     for n, d in rig_cache["devices"].items()
                     if RIG["devices"][n].get("kind") != "webos")
        await asyncio.sleep(3 if active else 10)


# --- Control operations ------------------------------------------------------

async def device_on(name: str) -> None:
    dev_cfg = _dev_cfg(name)
    d = rig_cache["devices"][name]
    touch_activity(f"{dev_cfg['label']} on")
    async with _op_lock(name):
        if d["busy"]:
            raise RigError(409, f"{dev_cfg['label']} is running a job")
        m = rig_cache["master"]
        if m["configured"] and m.get("switchable") and m["on"] is False:
            raise RigError(409, "master is off — turn the rig on first")
        await plug_set(dev_cfg["plug_ip"], True)
        if dev_cfg["kind"] == "atv":
            # Relay already on + tvOS asleep is the common case — wake it.
            await asyncio.to_thread(atv_wake, dev_cfg)
        d.update({"state": "powering", "boot_started": time.monotonic(),
                  "elapsed_s": 0.0, "detail": "relay on"})


async def device_off(name: str) -> None:
    """Graceful: shutdown command → wait → relay off. Runs as a background
    task; the tile shows `stopping` while it is in flight."""
    dev_cfg = _dev_cfg(name)
    d = rig_cache["devices"][name]
    touch_activity(f"{dev_cfg['label']} off")
    async with _op_lock(name):
        if d["busy"]:
            raise RigError(409, f"{dev_cfg['label']} is running a job")
        if dev_cfg["kind"] == "webos":
            raise RigError(409, f"{dev_cfg['label']} shares the screen — "
                                "use the Screen control, not a device power-off")
        d.update({"state": "stopping", "detail": "graceful shutdown",
                  "boot_started": None, "elapsed_s": None})

    async def _stop():
        try:
            await asyncio.to_thread(send_shutdown, dev_cfg)
            await asyncio.sleep(dev_cfg["shutdown_wait_s"])
            await plug_set(dev_cfg["plug_ip"], False)
            d.update({"state": "off", "watts": 0.0,
                      "detail": f"{dev_cfg['plug_name']} ready"})
            if rig_cache["screen_owner"] == name:
                rig_cache["screen_owner"] = None
        except Exception as e:
            d.update({"state": "stuck", "detail": f"stop failed: {e}"})

    asyncio.create_task(_stop())


async def device_cycle(name: str) -> None:
    """Hard power-cycle for a stuck device (relay off → 3 s → on)."""
    dev_cfg = _dev_cfg(name)
    d = rig_cache["devices"][name]
    touch_activity(f"{dev_cfg['label']} power-cycle")
    async with _op_lock(name):
        if d["busy"]:
            raise RigError(409, f"{dev_cfg['label']} is running a job")
        if dev_cfg["kind"] == "webos":
            raise RigError(409, f"{dev_cfg['label']} shares the screen — "
                                "no independent power to cycle")
        await plug_set(dev_cfg["plug_ip"], False)
        await asyncio.sleep(3)
        await plug_set(dev_cfg["plug_ip"], True)
        d.update({"state": "powering", "boot_started": time.monotonic(),
                  "elapsed_s": 0.0, "probe_fails": 0, "detail": "power-cycled"})


async def adb_repair(name: str) -> dict:
    """Guided fix for an unauthorised adb box: put the box on the shared
    screen (wakes the TV, selects its HDMI input), then send exactly ONE
    reconnect so its "Allow USB debugging?" prompt is on screen. Returns the
    host fingerprint to match against the dialog and the transport state a
    few seconds later ("device" ⇒ the operator already accepted)."""
    dev_cfg = _dev_cfg(name)
    if dev_cfg["kind"] != "adb":
        raise RigError(400, f"{dev_cfg['label']} is not an adb device")
    d = rig_cache["devices"][name]
    if d["state"] in _STOPPED_STATES or d["state"] == "stopping":
        raise RigError(409, f"{dev_cfg['label']} is not powered")
    touch_activity(f"adb repair {dev_cfg['label']}")
    screen_err = None
    try:
        await claim_screen(name)
    except RigError as e:
        screen_err = e.reason        # still worth reconnecting; report it
    await asyncio.to_thread(adb_reconnect, dev_cfg)
    await asyncio.sleep(3)
    auth = await asyncio.to_thread(adb_auth_state, dev_cfg)
    d["adb_auth"] = auth
    return {"fingerprint": adb_host_fingerprint(), "adb_auth": auth,
            "screen_owner": rig_cache["screen_owner"], "screen_error": screen_err}


async def claim_screen(name: str) -> None:
    """Hand the shared display to `name`.

    On the webOS C2 (monitor.lg_host set) this is a single deterministic
    HDMI input-select — devices stay awake, nothing to juggle. On an
    auto-switching panel (the PA329C) it falls back to dropping every other
    powered device's signal and raising the target's."""
    dev_cfg = _dev_cfg(name)
    d = rig_cache["devices"][name]
    touch_activity(f"screen → {dev_cfg['label']}")
    if d["state"] in _STOPPED_STATES or d["state"] == "stopping":
        raise RigError(409, f"{dev_cfg['label']} is not powered")
    busy = [RIG["devices"][n]["label"]
            for n, dd in rig_cache["devices"].items() if dd["busy"]]
    if busy:
        raise RigError(409, "job running on: " + ", ".join(busy)
                            + " — signal changes would contaminate the row")

    lg_host = RIG["monitor"].get("lg_host")
    if lg_host:
        if dev_cfg["kind"] == "webos":
            # The C2 is the panel itself — "claiming" just shows its own UI
            # (Home); there is no HDMI input to select. In Always-Ready
            # standby the first go_home is REJECTED (SSAP 1008 until the
            # panel wakes) — raw WoL, then retry.
            try:
                await asyncio.to_thread(lg.go_home, lg_host)
            except Exception:
                await _wake_and_wait(dev_cfg)
                await asyncio.to_thread(lg.go_home, lg_host)
            rig_cache["screen_owner"] = name
            rig_cache["screen_claimed_at"] = time.monotonic()
            return
        hdmi = dev_cfg.get("hdmi_input")
        if not screen_claimable(dev_cfg):
            raise RigError(409, not_claimable_reason(dev_cfg))
        try:
            await asyncio.to_thread(lg.set_input, lg_host, hdmi)
        except Exception as e:
            # Same standby mode as above: the panel rejects input-select while
            # asleep. Wake it and retry once before declaring failure.
            try:
                await _wake_and_wait(dev_cfg={"kind": "webos",
                                              "label": RIG["monitor"]["label"],
                                              "target": lg_host})
                await asyncio.to_thread(lg.set_input, lg_host, hdmi)
            except Exception:
                raise RigError(502, f"input switch failed: {e}")
        rig_cache["screen_owner"] = name
        rig_cache["screen_claimed_at"] = time.monotonic()
        return

    failures = []
    for other, dd in rig_cache["devices"].items():
        if other != name and dd["state"] not in _STOPPED_STATES:
            try:
                await asyncio.to_thread(set_signal, RIG["devices"][other], False)
            except Exception as e:
                failures.append(str(e))
    await asyncio.sleep(2)   # let the panel register the losses first
    try:
        await asyncio.to_thread(set_signal, dev_cfg, True)
    except Exception as e:
        failures.append(str(e))
    if failures:
        # Do NOT record ownership we can't have delivered — the UI must not lie.
        raise RigError(502, "claim incomplete: " + "; ".join(failures)[:300])
    rig_cache["screen_owner"] = name
    rig_cache["screen_claimed_at"] = time.monotonic()


async def _wake_and_wait(dev_cfg: dict, budget_s: int = 40) -> None:
    """Wake the C2 from Always-Ready standby (raw WoL — the only lever that
    works while SSAP rejects connections) and wait until webOS accepts."""
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        await asyncio.to_thread(lg.wake)
        await asyncio.sleep(4)
        if await asyncio.to_thread(probe_ready, dev_cfg):
            return
    raise RigError(504, f"{dev_cfg.get('label', 'C2')} did not wake "
                        f"(WoL sent for {budget_s}s)")


async def monitor_power(on: bool) -> None:
    touch_activity(f"screen {'on' if on else 'off'}")
    await plug_set(RIG["monitor"]["plug_ip"], on)


async def recycle_c2_panel(name: str) -> None:
    """Boot the C2's panel (Lab-E) to a fresh Home before a screen-mode native
    run — a deterministic, screensaver-free baseline that's identical every
    run. Needed because the panel's screensaver can't be disabled over the API
    (max 30 min) and may already be running when the job starts; a power-cycle
    guarantees a clean state (the C2's power-on is set to Home Screen). Only
    called from the C2 run prep — the UI power buttons stay refused."""
    dev_cfg = _dev_cfg(name)
    if dev_cfg["kind"] != "webos":
        raise RigError(400, "recycle_c2_panel is C2-only")
    d = rig_cache["devices"][name]
    await plug_set(dev_cfg["plug_ip"], False)
    await asyncio.sleep(3)
    await plug_set(dev_cfg["plug_ip"], True)
    d.update({"state": "booting", "boot_started": time.monotonic(),
              "detail": "panel rebooting"})
    for _ in range(20):          # ~60 s budget for webOS to answer again
        # AC-restore boots the C2 into Always-Ready STANDBY (SSAP rejecting),
        # not screen-on — keep nudging it awake with WoL while we wait.
        await asyncio.to_thread(lg.wake)
        await asyncio.sleep(3)
        if await asyncio.to_thread(probe_ready, dev_cfg):
            await asyncio.to_thread(lg.go_home, dev_cfg["target"])
            d.update({"state": "ready", "webos_probed": time.monotonic(),
                      "boot_started": None, "detail": "webOS ok (fresh boot)"})
            return
    raise RigError(504, f"{dev_cfg['label']} panel did not return after cycle")


async def master_power(on: bool) -> None:
    """Master toggle. With a switchable master (Tapo P110 at the wall, or a
    relay-equipped Shelly) this switches the strip (off refused until every
    device is down). With only the metering Plug PM it degrades to a
    SOFTWARE master: 'off' gracefully stops every powered box; 'on' is
    refused — boxes are powered individually so the monitor's auto-switch
    stays deterministic."""
    touch_activity(f"master {'on' if on else 'off'}")
    switchable = rig_cache["master"].get("switchable")
    if switchable:
        if not on:
            lively = [RIG["devices"][n]["label"]
                      for n, d in rig_cache["devices"].items()
                      if d["state"] not in _STOPPED_STATES]
            if lively:
                raise RigError(409,
                               "power devices off first: " + ", ".join(lively))
        t_ip = master_tapo_ip()
        if t_ip:
            await plug_set(t_ip, on)
        else:
            await shelly_set(on)
        return
    if on:
        raise RigError(400, "no strip relay — power boxes individually (the "
                            "screen follows the single powered device)")
    busy = [RIG["devices"][n]["label"]
            for n, d in rig_cache["devices"].items() if d["busy"]]
    if busy:
        raise RigError(409, "job running on: " + ", ".join(busy))
    for name, d in rig_cache["devices"].items():
        if d["state"] not in _STOPPED_STATES and d["state"] != "stopping":
            await device_off(name)


def _dev_cfg(name: str) -> dict:
    if name not in RIG["devices"]:
        raise RigError(404, f"unknown device {name!r}")
    return RIG["devices"][name]


def status_payload() -> dict:
    """The /decode/status.json response — assembled from cache only (no IO)."""
    devices = {}
    for name, cfg_d in RIG["devices"].items():
        if cfg_d.get("parked"):
            continue          # disconnected — hidden from the console
        d = rig_cache["devices"][name]
        devices[name] = {
            "label": cfg_d["label"], "plug_name": cfg_d["plug_name"],
            "device_class": cfg_d.get("device_class", "stb"),
            "shape": cfg_d.get("shape"),   # render override — device_class stays the behavioural tag
            "silicon": cfg_d.get("silicon", ""),
            "os": cfg_d.get("os", ""),
            "chip_vendor": cfg_d.get("chip_vendor", ""),
            "network": cfg_d.get("network", "ethernet"),
            "conn": cfg_d["kind"],
            "state": d["state"], "watts": d["watts"], "busy": d["busy"],
            "detail": d["detail"], "elapsed_s": d["elapsed_s"],
            "expected_s": cfg_d["expected_boot_s"],
            "adb_auth": d.get("adb_auth"),
            "target": cfg_d.get("target"),
            "target_source": target_source(name),
            "hdmi_input": cfg_d.get("hdmi_input"),
            "screen_claimable": screen_claimable(cfg_d),
        }
    master = rig_cache["master"]
    monitor = {**rig_cache["monitor"],
               "panel": RIG["monitor"].get("panel", ""),
               "plug_name": RIG["monitor"]["plug_name"],
               "hdmi_inputs": hdmi_map()}
    total = sum(w for w in
                ([d["watts"] for d in rig_cache["devices"].values()]
                 + [monitor.get("watts")])
                if isinstance(w, (int, float)))
    n_plugs = len(RIG["devices"])
    saving = None
    if master["configured"] and master.get("switchable") and master["on"] is False:
        saving = (f"rig fully off — saving ~"
                  f"{n_plugs * RIG['tapo_standby_w']:.1f} W of Tapo standby")
    claimed_at = rig_cache.get("screen_claimed_at")
    # Blink the receiving tile's 📺 badge until the switch has visibly settled.
    # 8 s on the LG C2 (webOS input-select reclaims ~4 s faster than the old
    # PA329C auto-switch; owner, 2026-07-31); was 12 s for the PA329C.
    settling = bool(rig_cache["screen_owner"] and claimed_at
                    and time.monotonic() - claimed_at < 8)
    return {"master": master, "monitor": monitor, "devices": devices,
            "screen_owner": rig_cache["screen_owner"],
            "screen_settling": settling,
            "total_w": round(total, 2), "saving_note": saving,
            "idle_off": idle_off_state(),
            "age_s": (None if rig_cache["updated_monotonic"] is None else
                      round(time.monotonic() - rig_cache["updated_monotonic"], 1))}
