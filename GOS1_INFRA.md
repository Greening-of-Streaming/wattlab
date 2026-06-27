# GoS1 Infrastructure & Backup Context
# Companion to CLAUDE.md (which covers WattLab project specifics)
# Last updated: 2026-06-26 (two infra facts logged in "External Access Incidents & DNS": GoS1 now has a
#   FIXED public IP — free "IP fixe" opt-in on the Bouygues portal after a WiFi 7 Bbox firmware upgrade
#   blocked all ports; and the LAN link-flap / old-switch (IPTV-multicast-flood) incident.)

## Owner
Ben Schwarz (bs@ctoic.net / EURL CTO INNOVATION CONSULTING / SIREN 508109337)

## Physical Location (2026-06-19)
GoS1 was relocated to the **basement** — cooler and far less exposed to heatwaves (a fresh
one is starting in France as of this date). This directly improves **measurement stability**:
the variance calibration is ambient-sensitive (idle noise floor swings 2–6× in heat waves —
see WattLab `variance_calibration_ambient_sensitive` memory / CLAUDE.md), so a cooler, steadier
ambient means calibration and energy runs are more repeatable and the "don't calibrate during a
heatwave" caveat is largely mitigated. Re-confirm the idle floor at the new location with a fresh
variance calibration, since the absolute idle baseline may shift slightly with ambient temp.

## Network — fixed IPs (2026-06-19)
The **server and both Tapo P110 plugs now have fixed/reserved IPs** on the Bbox router (DHCP
reservations), so they no longer risk re-assignment on lease renewal or router reboot. Addresses
unchanged: GoS1 server `.62`, outer plug `.159`, inner/primary plug `.91`. This removes a latent
failure mode for the meter `.env` (`TAPO_P110_IP` / `TAPO_P110_IP_2`) and the external-access /
DuckDNS path — they were previously DHCP and could have drifted.

## Disk Layout (May 2026 — two NVMe SSDs)

Two disks since S24 (2026-05-12): a 500 GB system drive and a 4 TB data drive.

```
nvme0n1  500 GB  Crucial CT500P310SSD8 — system disk
  └─ nvme0n1p1   1 GB  vfat   /boot/efi
  └─ nvme0n1p2 465 GB  ext4   /            ~170G used, ~264G free (40%)  [post-S24]

nvme1n1  4 TB    SPCC M.2 PCIe SSD — data disk (added S24)
  └─ nvme1n1p1 3.6T  ext4 (label "tests", mkfs -m 1)  /srv/data   ~79G used
     /srv/data/owl/      OWL bulk + archival data — symlinked into the repo:
       test_content/       <- ~/wattlab/test_content   (Meridian source clips, ~1 GB)
       results/            <- ~/wattlab/results        (result JSON archive — grows forever; no pruning)
       corpus/             <- ~/wattlab/corpus          (RAG source PDFs, ~280 MB)
       .chroma/            <- ~/wattlab/.chroma         (RAG vector store, ~140 MB)
     /srv/data/rem/        Simon's REM display-test clips (77 GB) — symlinked from /home/simon/rem
     /srv/data/media/      general media bucket (empty)
```

fstab entry: `UUID=3b621612-f3fa-4873-8c10-0cea94105591  /srv/data  ext4  defaults,nofail  0 2`.
`wattlab.service` drop-in `/etc/systemd/system/wattlab.service.d/mount.conf` adds `RequiresMountsFor=/srv/data` so the service waits for the mount on boot.

```
/home/gos     ~57 GB  (mostly caches/venvs — wattlab/ itself ~1.4 GB; .cache 20G, .local 18G, .venvs 6.8G, .ollama 4.7G, snap 2.2G)
/opt          ~27 GB  rocm-6.2.4 (reinstallable) + amdgpu + teamviewer
/usr          ~64 GB
/var          ~10 GB  (logs, package cache, snapd, docker)
/etc          ~14 MB  (system configs)
```

**Backup-cron note:** `/etc/cron.d/wattlab-results-backup` syncs `/home/gos/wattlab/results/` (now a symlink) to Nextcloud. Verified S24 that rclone 1.73.2 follows the symlink when it's the root source path, so the nightly sync still works. Optional hardening: repoint it at the real path `/srv/data/owl/results/` to remove any fragility — `sudo sed -i 's|/home/gos/wattlab/results/|/srv/data/owl/results/|' /etc/cron.d/wattlab-results-backup`.

## GPU (swapped 2026-05-29, S36 — CR-060)
**NVIDIA RTX 5080, 16 GB VRAM** — NVENC (video) + CUDA (AI; torch `2.11.0+cu128`). Replaced the AMD Radeon RX 7800 XT (VAAPI/ROCm); the swap was Pixop-driven (CUDA-only partner pipeline). `gpu.py` auto-detected the new card with zero code edits, as designed. **Idle wall power post-swap: ~79 W** (display-blanked; ~101 W with active display — display-state-sensitive), vs ~51–58 W across the AMD era. The frozen AMD pre-swap baseline (energy + VMAF, n=10 benchmark) lives in WattLab `docs/gpu_swap_amd_baseline.md`; the swap/rollback procedure (ROCm wheel pins + Mesa hold) in `docs/gpu_swap_checklist.md`.

## Cooling (S24, 2026-05-13 — fan census predates the GPU swap)
9 fans total: **5 case** (the 5th re-enabled via a Y-splitter off an existing header — had been left deactivated), **2 GPU** (integrated; counted on the RX 7800 XT — the RTX 5080 brings its own), **1 CPU** (the board header can drive a 2nd if thermals warrant), **1 PSU internal**. The case + CPU fans run a BIOS curve (quiet below ~70 °C; never observed ramping in any OWL run) and are **not Linux-controllable** — no super-I/O sensor driver (`nct6775`/`it87`/…), the only platform hwmon is an empty `asus` node. So they're an effectively fixed-airflow constant; only the GPU fans exposed PWM (via `amdgpu` hwmon in the AMD era). The whole envelope is inside the P110 boundary — the extra fan added ~1-2 W (the S24 thermal-recovery probe put steady idle at ~56-58 W, vs the old ~51-54 W; combined NVMe + fan — both AMD-era figures; see the GPU section for the post-swap ~79 W). See WattLab `CHANGE_REQUESTS_CLOSED.md` CR-005 for the full fan-control investigation.

## Power Metering (CR-065, 2026-06-11)
Two Tapo P110 smart plugs daisy-chained: **wall → `.159` (outer, the original plug) → `.91` (inner, primary, Tapo nickname "GoS1b-server") → GoS1**. The inner plug measures the server alone and supplies every absolute-W figure (`TAPO_P110_IP`); the outer (`TAPO_P110_IP_2`) doubles the fresh-sample rate via staggered polling and additionally sees the inner plug's ~0.7 W self-draw. The two units are unequal samplers (inner refreshes ≥1 Hz, outer exactly 1.5 s) and KLAP sessions are exclusive per device — never poll a plug from two clients at once (`bin/probe-dual-meter` requires the wattlab service stopped). Pre-test record: WattLab `docs/dual_meter_pretest_findings.md`.

## Other Users
dom, marisol, simon, tania — home dirs exist but unreadable by gos user.

## External Access Incidents & DNS

### Public IP — now FIXED (free, opt-in via Bouygues portal)
**GoS1's public IP is a dedicated FIXED/static IP** (confirmed by owner 2026-06-26). How we got there:
a **WiFi 7 Bbox upgrade** (latest hardware) shipped an **unsolicited firmware update that blocked ALL ports**
— catastrophic, total external-access loss. After some digging the fix was to **opt in to the "IP fixe"
option on the Bouygues customer portal** (free) — which both restores forwarding and pins a static public IP.
This is the durable resolution of the 2026-06-01 CGNAT incident below. **Consequences:** external hosting of
`wattlab.greeningofstreaming.org` is stable on a known IP. **DuckDNS is redundant for *this* IP but
DELIBERATELY KEPT** — it's portability insurance: if GoS1 ever moves to a site **without** a fixed IP
(no opt-in available), dynamic DNS is needed again, so the updater stays in place. **If ports ever drop again
after a Bbox firmware push:** re-check the "IP fixe" / port-forwarding settings on the Bouygues portal first
(a firmware update can silently reset them).

### Bouygues Bbox shared-IPv4 / CGNAT incident — 2026-06-01 (RESOLVED — see above)
Bouygues moved the Bbox to a **shared IPv4** (CGNAT), limiting forwardable ports to **24576–32767** — which killed public 80/443 and took `wattlab.greeningofstreaming.org` offline. External HTTPS restored (externally confirmed reachable 2026-06-11); **permanently resolved by the "IP fixe" opt-in above.** Historical plan B (if Bouygues ever can't provide it): a Linode-hosted Caddy reverse proxy fronting GoS1.

### DuckDNS auto-updater — on GoS1 (kept on purpose for portability)
Runs on GoS1 at `/home/gos/duckdns/duck.sh` via the `gos` crontab, every 5 minutes (`*/5 * * * *`, verified 2026-06-11). **Redundant for the current static IP but deliberately retained** as insurance for a future move to a site without a fixed IP (where dynamic DNS is needed again) — do NOT retire it on the assumption it's dead weight. The previous updater ran off-box and **silently failed** during the 2026-06-01 outage — same lesson as the backup incident below: silent background jobs need a visible failure signal.

### LAN link-flap / old-switch incident — 2026-06-26
**Symptom:** a "partial network outage" (~30 min, recovered by ~14:33). Owner on the LAN, others affected.

**What the box logged (kernel, authoritative):** GoS1's NIC `eno2` (Realtek **r8169**, PCI `08:00.0`) flapped ~5× between **14:01:55 and 14:11:31**, then went stable and stayed clean. The unused second NIC `eno1` (`07:00.0`) briefly came up at 14:10:22 / down 14:11:27 (likely a cable momentarily touched that port). DuckDNS updates (5-min cron) returned `NO_RESPONSE` at **14:05** (during the flaps) and again at **14:30** (after the link was stable → that later blip was **upstream/WAN**, not the box).

**Signature = physical, not congestion / not software:**
- Every re-link negotiated **1Gbps/Full** → it is an *old gigabit* switch, **not** 10 Mbps as first assumed (the switch's uplink-to-router speed is separate/unknown).
- NIC counters across the event: RX errors/dropped/missed **0**, TX errors **0** → the port physically lost carrier (switch resetting the port), **not** buffer overruns from a saturated link.
- No reboot (then up 5d+), load <1, RAM fine, no ffmpeg/heavy egress, `eno1`/`eno2` **not** bridged or bonded (the `br-*`/veth are Docker's) → **no L2 loop**, GoS1 was not flooding.

**Root-cause hypothesis (strong, not proven):** since the **2026-06-19 basement move, GoS1 lost its direct router cable and now hangs off a very old gigabit switch — shared with a TV used for 4K-streaming tests**. Sustained 4K load on a marginal/aging switch (weak PSU brown-out / thermal) is a classic trigger for ports physically resetting → flapped GoS1 *and* rippled to other devices on that switch ⇒ the "partial" feel. GoS1 is a **victim of the shared switch, not the cause**. (Confidence: link-flap timeline + physical-vs-congestion call = high, from logs/counters; 4K-as-trigger = strong correlation, no switch/TV telemetry to confirm.)

**Recommended fixes (in order):** (1) get GoS1 **off the shared switch — restore a direct router port** (it was stable that way pre-move); (2) replace the old switch / verify it isn't overheating; (3) leave only `eno2` cabled (avoid an accidental `eno1` second-port loop). **Repro test:** stream 4K to the TV while watching `journalctl -k -f | grep "Link is"` on GoS1 — port flaps under load ⇒ switch condemned. Same lesson as the silent-failure incidents: this was only diagnosable because the kernel keeps a visible link-event log.

**UPDATE — same-day live repro (confirmed mechanism): IPTV multicast flood, not just "old switch".** The switch is a **Netgear GS305v3 — unmanaged, so NO IGMP snooping**. The Bbox delivers TV by **multicast**; with no snooping the switch **floods every channel to all ports, including GoS1**. Measured live with France 3 HD on the TV: `eno2` was receiving **~5 Mbps, 514 mcast pkts/s (~95% of RX)** for a stream GoS1 never joined (its only multicast memberships were normal local `224.0.0.251`/`224.0.0.1`). A **4K channel ≈ 25–40 Mbps** flood at far higher pkt-rate is what makes GoS1's SSH session go **unresponsive**, and very plausibly what overwhelmed the cheap switch into the 14:01–14:11 **port resets** (one root cause, two symptoms). EEE (802.3az) was also `enabled-active` on `eno2` (Realtek r8169/rtl8125b — a known flap factor) — disable as belt-and-suspenders: `sudo ethtool --set-eee eno2 eee off`. **Primary fix = separate IPTV from GoS1** (GoS1 *or* the TV on a direct Bbox port), **or** swap the GS305v3 for an IGMP-snooping smart switch (GS305E/GS308E). The Bbox "only one HD channel works" is likely its own IPTV/line-capacity issue (ISP side). ⚠ Don't re-trigger 4K casually — it floods GoS1 and can hang a live session.

**RESOLUTION — ordered 2026-06-26: 2× Netgear GS305E** (Plus/Web-Managed, **has IGMP snooping**) to replace the unmanaged **GS305v3** (P/N `272-13158-01`, S/N `5UB19865Y04DD0`). The "E" suffix is the whole point — plain GS305/GS105/TL-SG105 are *unmanaged* (no snooping) and would flood GoS1 identically. **Install checklist:** (1) in the GS305E web UI, **enable IGMP snooping** and verify the multicast/querier defaults (Netgear KB 31257 — default IGMP settings can disrupt multicast; the Bbox should be the querier); (2) **disable EEE/green-Ethernet on GoS1's `eno2`** — `sudo ethtool --set-eee eno2 eee off`, then make it persistent (networkd `.link` / NM / udev) — it was `enabled-active` and is a known r8169/rtl8125b flap factor; (3) cable only `eno2` (avoid an accidental `eno1` second-port loop). **Verify:** stream 4K to the TV while watching `journalctl -k -f | grep "Link is"` and `eno2` multicast pkts/s (`watch -n1 "ip -s link show eno2"`) — the flood + flaps should disappear. **Free fallback** still valid if the switch swap is delayed or snooping needs tuning: put **GoS1 *or* the TV on a direct Bbox port** (off the shared switch). Second GS305E = spare / second location.

**RESOLVED — installed, configured & verified 2026-06-27.** Both GS305E units in service, GS305v3 retired. Topology is now a **chain**:

```
Bbox (192.168.1.254, IGMP querier)
  └─ GS305E-1  192.168.1.173  MAC 28:94:01:8A:F7:23  S/N 5W18635XA583A  fw V1.0.0.22  ── GoS1 eno2
       └─ GS305E-2  192.168.1.8  MAC 28:94:01:8A:F7:46                                ── STB (4K IPTV)
```

- Both switches: **DHCP-enabled** (got `.173` / `.8` leases from the Bbox — reserve these on the Bbox if stable IPs are wanted), web UI at `http://<ip>/index.cgi`, admin password set to **`Wattlab1`** on both. Names set in-UI: **GS305E-1**, **GS305E-2**.
- **IGMP snooping was already ON by factory default** on both — it was **not** the missing piece. The **only change from factory on each** was setting **Block Unknown Multicast Address → Enable** (System → Multicast). That's the setting that actually stops the un-joined channels flooding GoS1's port; snooping alone only prunes *learned* groups. GS305E-2 shipped with default password `password` (set to `Wattlab1` on first login).
- **Why GS305E-1 alone protects GoS1:** in the chain, the STB's IGMP joins flow *upstream* (STB → GS305E-2 → GS305E-1 → Bbox), so GS305E-1 forwards the 4K multicast only out its GS305E-2 port, never GoS1's. GS305E-2's config is hygiene only — nothing downstream of it but the STB.
- **VERIFIED live (2026-06-27, 4K IPTV streaming):** `eno2` RX multicast = **0 frames over 10 s (~0/s)**, total ~50 pkt/s / ~62 kbit/s — vs the old GS305v3 flood of **~514 mcast pkt/s / ~5 Mbps on France 3 HD**. Flood eliminated; GoS1's only multicast memberships are the normal local `224.0.0.1`/`224.0.0.251`. The hang-during-4K problem is gone.
- ⚠ **Still open (belt-and-suspenders, low priority):** checklist item (2) — `eno2` EEE is now `enabled-inactive` (the GS305E doesn't negotiate it, so the flap risk is currently moot) but was **never explicitly disabled/persisted** via `ethtool --set-eee eno2 eee off`. Do it if any future r8169 flaps recur.
- **Ops note for re-finding the switches:** NSDP auto-discovery (UDP 63322) is **dead from GoS1** because `ufw` is active and drops the unicast reply to the broadcast probe. Discover instead by ARP OUI **`28:94:01`** (`ip neigh show dev eno2 | grep 28:94:01`) + web-UI fingerprint (`<title>Redirect to Login</title>`, `index.cgi`).

## Nextcloud Backup (Hetzner Storage Share)
- **URL:** https://nx92576.your-storageshare.de
- **Plan:** NX11 base (possibly upgraded to 1 TB — verify at accounts.hetzner.com)
- **Username:** ben.flute@proton.me
- **Auth:** App password required for WebDAV/rclone (regular password rejected)
- **Custom domain planned:** cloud.ctoic.net (CNAME, not yet configured)
- **Version:** Nextcloud Hub 25 Autumn (32.0.6)
- **2FA:** Not configured (flagged in admin overview)
- **WebDAV endpoint:** https://nx92576.your-storageshare.de/remote.php/dav/files/ben.flute@proton.me/

### rclone Config (on GoS1)
- **Remote name:** `nextcloud`
- **Type:** webdav, vendor nextcloud
- **Commands:**
  - `rclone lsd nextcloud:` — list folders
  - `rclone about nextcloud:` — check used space
  - `rclone sync <src> nextcloud:<dest>/ --progress --skip-links`

### Backup Completed (April 2026)
Location: `nextcloud:GoS1-backup/`
- `ssh/` — SSH keys
- `gnupg/` — GPG keys
- `config/` — app settings
- `etc/` — system configs (minus root-only files: shadow, gshadow, ssh host private keys)
- `.claude.json`, `.gitconfig`, `.bashrc`, `.profile`

**Not backed up (by design):**
- wattlab/ — on GitHub
- .ollama, .venvs, .cache, .local, snap — reinstallable
- /opt/rocm-6.2.4, /opt/amdgpu, /opt/teamviewer — reinstallable
- Password hashes, SSH host private keys — shouldn't be in cloud

**Known quirks:**
- Snap mount files with `\x2d` in filenames rejected by Nextcloud WebDAV (backslash not allowed)
- Root-owned /etc files fail with permission denied under gos user — expected

**TODO:**
- [x] Cron job for recurring backup — `/etc/cron.d/wattlab-results-backup`, runs 03:30 daily, syncs `results/` to `nextcloud:GoS1-backup/wattlab-results/`, logs to `/home/gos/.cache/wattlab-backup.log`
- [ ] Consider `rclone crypt` overlay for encryption before upload
- [ ] Replace raw /etc folder with selective tarball of key configs
- [ ] Add a "backup last-success ≤ 26h" health check (file mtime monitor or a result-listing sanity check) — see "Silent failure incident" below; without it, this class of bug recurs invisibly.

### Silent failure incident — 2026-04-10 → 2026-05-05 (24 nights)

The cron line as originally configured wrote its log to `/var/log/wattlab-backup.log`, but `gos` does not have write permission to `/var/log/`. rclone failed to open its log file on every nightly run and exited *before* doing any sync work; cron's stderr went to the local mail spool nobody reads, so the failure was invisible. Discovered 2026-05-05 during a routine "what's been backed up?" check: local file count 106, remote file count 8, last successful remote write 2026-04-10 (the manual one-shot that established the directory).

**Catch-up sync 2026-05-05 00:02:** all 98 missing files (~10 MiB) pushed via manual `rclone sync` with `--log-file=/home/gos/.cache/wattlab-backup.log`. Remote and local now both at 106 files / 11.4 MiB.

**Fix to the cron line** (run by operator with sudo): point `--log-file` at `/home/gos/.cache/wattlab-backup.log` (writable by `gos`). One sed:
```bash
sudo sed -i 's|/var/log/wattlab-backup.log|/home/gos/.cache/wattlab-backup.log|' /etc/cron.d/wattlab-results-backup
```

**Lesson worth keeping:** failure modes that produce no signal are the worst kind. Any silent operation (cron, systemd timer, background task) needs either (a) a heartbeat / last-success check that *visibly* breaks if the operation stops, or (b) error output routed somewhere a human will actually see. The mail spool isn't that place.

## Nextcloud — Other Uses
- 1,031 deduplicated contacts (imported from contacts_final.vcf)
- Synced to Fairphone via DAVx⁵ (groups as per-contact categories)
- Synced to MacBook via native CardDAV (System Settings → Internet Accounts)
- CalDAV available but not yet configured

## Ben's Broader Stack
- **Phone:** Fairphone 6, e/OS (Murena)
- **Mail + Calendar:** Proton (migrating from Gmail)
- **Passwords:** Bitwarden (self-hosted eventually)
- **TOTP:** Leaning toward Aegis (offline, open-source)
- **Domain:** ctoic.net
- **DNS pending:** MX/SPF/DKIM for bs@ctoic.net + CNAME for cloud.ctoic.net
- **SSH from Fairphone:** Termux (F-Droid) + openssh

## Design Principles
- Minimize vendor concentration risk (including Proton monoculture)
- Prioritize data portability and exportability
- Prefer offline-first, open-source tools
- Favor clean architecture over patchwork workarounds
- Long-term sovereignty over short-term convenience
