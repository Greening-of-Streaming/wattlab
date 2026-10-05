# GoS2 — second OWL node: design

**Status:** design phase, opened 2026-10-04. Tracked as **CR-085** (CHANGE_REQUESTS.md). Nothing built yet.
**Hardware (read over SSH 2026-10-04):** Mac mini `Mac18,5`, **Apple M6** (12 cores: 2 Super + 4 Performance +
6 Efficiency), 24 GB, 460 GB SSD, macOS **27.0**, FileVault off. Hostname `gos2` / ComputerName `GoS2`, admin user
`gos`, no Apple ID (deliberate: no Activation Lock, no iCloud background load). Reached from GoS1 with
`~/.ssh/id_ed25519_gos2`. Wi-Fi `.95` (MAC `c8:80:6d:3d:a7:6e`, private address off); Ethernet `en0`
`c8:80:6d:2e:20:cc`, not yet cabled. Metered by two daisy-chained Tapo P110s, **lab-G1** and **lab-G2** (§8).
Still unmeasured: encoders (no ffmpeg yet), what `powermetrics` exposes, and the idle floor (the 5.2 W seen on
G1 was with a 4K screen attached and Setup Assistant running). Sits next to GoS1 on the Bbox LAN today; must be movable to another
member's office later with configuration changes only.

---

## 1. Decisions taken (owner, 2026-10-04)

| # | Question | Decision |
|---|---|---|
| D1 | Role of GoS2 | **Failover host + second bench (Apple silicon), with the always-on role swapped:** GoS2 is the always-on front door; GoS1 becomes the bench, woken when there is work. |
| D2 | Interconnect | **SSH first.** No Tailscale, no Linode proxy — each is one more thing to run. Revisit only on the triggers in §5.3. |
| D3 | Mesh coordination (Tailscale vs Headscale) | **Not applicable** — falls away with D2. |
| D4 | Who is Lab | **Each node's own LAN + anyone arriving over SSH** (today's `ssh -L 8000` practice). See §6 for the cross-node case. |
| D5 | Location | Co-located with GoS1 now; architecture must allow a **simple move to another member's office**. |
| D6 | UI (2026-10-04) | **Engines, not hosts.** Visitors compare *encoding engines* (CPU · GPU/NVENC · Apple media engine · ASIC card, which is coming); the machine is provenance on the result, never a form option. The UI covers the common runs; complex runs go through natural language driving the job API. Design of the engine registry and the bulk-data rules is **deferred** until after a working GoS2 encode (done 2026-10-04, §13). |

Rejected models, for the record: *master/slave* and *client/server* both make GoS1 the single point the site
depends on, which contradicts the "GoS1 goes dark" requirement unless we add master election — too heavy for a
member-recruitment loss-leader (board steer 2026-05-11). *Two fully independent servers* diverge: two member
lists, two archives.

## 2. Shape: two autonomous peers, one front door

```
Internet ──443──▶ GoS2 nginx  ("front door" role — always on, low power)
                     ├─ primary upstream : GoS1 OWL :8000   (LAN today · SSH tunnel after the move)
                     └─ backup  upstream : GoS2 OWL :8000   (archive + GoS2's own Apple-silicon jobs)

GoS1  = the bench — NVENC, CUDA, LLM/image ladder, decode rig, Lab sessions. Asleep when idle.
GoS2  = front door + archive replica + a second, different bench.
```

- **Same codebase on both.** Each node is a complete OWL with its own queue, meters, settings and calibration.
  Neither node ever drives the other's hardware.
- **The front door is a role, not a machine.** Both nodes carry the same nginx config. If the office cannot take
  inbound 443 (§5.3), the front door goes back to GoS1 and GoS2 becomes the backup upstream. No redesign needed.
- **Failover is plain nginx:** an `upstream` with GoS1 primary and GoS2 marked `backup`. Health checks are passive
  (`max_fails`/`fail_timeout`; open-source nginx has no active checks), so a dead or asleep GoS1 costs one slow
  request before the switch. Good enough for a loss-leader site.
- **Measurements never fail over.** GoS1 and GoS2 are different silicon, so their results are never pooled,
  compared as replicas, or used to stand in for each other. Every result says which host produced it (§4).

### What visitors see per state

| GoS1 | GoS2 | Served by | Behaviour |
|---|---|---|---|
| awake | up | GoS1 (primary) | Everything as today. |
| asleep / dead | up | GoS2 (backup) | Home, `/findings`, archive, `/methodology`, member sign-in, GoS2 job types. GoS1-only features (`/video` NVENC, `/llm`, `/image`, `/rag`, `/decode`, Lab reservations) show **"bench asleep — waking"** (and trigger wake, §7) or **"bench offline"**. |
| awake | dead | — (front door gone) | Site down until the front-door role moves to GoS1 (manual: DNS / port-forward flip). |

The third row is the price of putting the front door on GoS2. It is the same exposure we have today (one box
behind one Bbox), now on a box that draws a few watts instead of ~79 W.

## 3. Why the role swap

GoS1 idles at **~79 W** display-blanked (post-GPU-swap figure, CLAUDE.md), i.e. ~690 kWh/yr if it never
sleeps, and most of that time it is serving pages. A Mac Mini idles at single-digit watts. **That is still an
estimate.** Phase 0 measures GoS2's idle on G1/G2, and Phase 3 measures the actual before/after. Once both
numbers exist, the swap becomes a GoS finding in its own right ("the lab applies its own advice"), stated with
n and CI like every other claim, or dropped if the numbers don't hold.

## 4. State: who owns what

The rule is **one writer per piece of state**. Results are append-only and host-tagged, so they sync both ways.

| State | Home | Replication | Notes |
|---|---|---|---|
| `results/**` | node that measured it | rsync both ways, **no `--delete`**, over SSH | Requires **host-prefixed job IDs** (today 8-hex UUID fragments) and a `host` field in the envelope (bump `envelope_version`, `docs/result_envelope.md`). Renderers must show the host. |
| `docs/findings/` | git | GitHub | Both nodes pull. Findings cite results by path, so the replica must hold the cited files. |
| `data/members.json` | **GoS2** (always on) | GoS2 → GoS1, one way | GoS1 treats it as a read-only replica. Allowlist edits only on GoS2. |
| `OWL_AUTH_SECRET` | Bitwarden | copied once to both `.env` | The same secret on both means a magic link signed by either node verifies on either. |
| `uploads/` (keep-class) | node that received the upload | both ways, no delete | Upload names must be unique across nodes (same host-prefix rule). |
| `results/_analytics/visits.json` | per node | none | `/audience` merges both at read time. |
| `settings.json` | per node, **never replicated** | — | Host-specific calibration (CR-031 watch-out). A new host must calibrate on first run. |
| `data/lab_reservations.json` | GoS1 | none | It reserves GoS1. Unavailable while GoS1 is asleep (acceptable). |
| Tapo / SMTP credentials | Bitwarden | each `.env` | Same TP-Link account. Each node's `.env` lists **only its own plugs** (§8). |
| TLS cert | front-door node | none | certbot on whichever node holds the role. Re-issue on a role move. |

Side effect: GoS2 becomes a live second copy of the results archive and `members.json`. That closes part of the
gap in `GOS1_DISASTER_RECOVERY.md`. It does not cover secrets or SSH keys; that is still CR-067 item 5.

## 5. The link: SSH

### 5.1 Co-located (now)

No tunnel. The two nodes talk over the Bbox LAN, both with reserved IPs. GoS2 needs a Bbox DHCP reservation
(add it to the decode_bench/README.md §Network table convention), and so do lab-G1/G2.

### 5.2 After the move

One **outbound** SSH connection from GoS2 to GoS1's existing fixed public IP on `:2222` carries everything:

| Forward | Purpose |
|---|---|
| `-L 18000:127.0.0.1:8001` | Front door → GoS1 OWL (the dedicated front-door listener, §6) |
| rsync over the same host key | Results/uploads/members replication |
| `-R 2223:127.0.0.1:22` | Admin reach into GoS2 by jumping through GoS1. Works even if the office has no inbound SSH, **but only while GoS1 is awake**. |

- **Key:** a dedicated `id_ed25519_gos2_link` with `authorized_keys` restrictions on GoS1:
  `restrict,port-forwarding,permitopen="127.0.0.1:8001",permitlisten="127.0.0.1:2223"`, plus an rsync-only
  forced command for the replication key (or a second key). This key gets no shell on GoS1.
- **Supervision:** a launchd agent (`KeepAlive`) running `ssh -N` with `ServerAliveInterval`/`ExitOnForwardFailure`.
  autossh is optional, since launchd already restarts.
- **Visible failure (the backup and DuckDNS lesson):** the link has a last-success heartbeat that shows up
  somewhere a human looks (`/queue-status` and `bin/owl-status`). It must not fail silently.
- **Direction:** GoS2 calls GoS1, never the reverse, because GoS1's side is the one with a fixed IP and an open
  port. The office needs no port forwarding for the link itself.

### 5.3 When SSH stops being enough (revisit triggers for D2)

1. **The office cannot accept inbound 443** (CGNAT, or no access to its router). The front door then moves back
   to GoS1 (§2). That still needs no new infrastructure. Only if *neither* site can take 443 does a relay
   (Linode Caddy, the historical plan B in GOS1_INFRA.md) become necessary.
2. **GoS1 loses its fixed IP / inbound 2222** (Bbox firmware, ISP change). The link has no rendezvous point.
   Tailscale or WireGuard via the Linode becomes the fix.
3. **A third node appears.** Point-to-point tunnels stop scaling. That is the point to consider a mesh.

None of these holds today.

## 6. Access tiers and proxy trust

`audience.tier()` grants Lab to any loopback or RFC1918 origin, taking `X-Real-IP` first and `client.host` as the
fallback. Two traps follow:

1. **Tunnelled traffic arrives from 127.0.0.1.** Through the §5.2 tunnel, *every* public visitor reaches GoS1 from
   loopback. If the visitor IP is ever missing, they become Lab, which means rig control, settings and queue
   control. **The front-door path must fail closed:** it lands on a dedicated GoS1 listener (nginx
   `127.0.0.1:8001`) that tags requests as `via-front-door`. On that listener a missing or invalid visitor IP
   resolves to **Anonymous, never Lab**. Admin `ssh -L` to `:8000` keeps today's loopback→Lab behaviour.
2. **`X-Real-IP` is trusted from anyone today** (CR-066 item 2, open). It must be trusted only from the known proxy
   hop before any second proxy hop exists. **CR-066 item 2 is a hard prerequisite for Phase 2.**

**Policy (D4), stated per node:**
- A node grants Lab to its **own** LAN and to SSH-tunnelled loopback.
- The office LAN, arriving at GoS1 *through the front door*, is **not** Lab on GoS1 by default. Lab on GoS1
  controls the rig and the bench, and an office LAN is a member's network, not ours. It may also reuse
  192.168.1.x, which makes "private" meaningless across sites. Lab on GoS1 from the office means `ssh -L`.
  *(Owner to confirm. While co-located, both LANs are the same LAN and this is moot.)*
- All of this lives in `capabilities.py`/`audience.py` as today. Routes still never compare tiers.
- Regression guard: a probe with a public-IP header through the front door asserts Anonymous. Tests run as Lab,
  so this has to be an explicit test (`tests_run_as_lab_tier`).

## 7. GoS1 sleep / wake

- **Gate:** GoS1 serves the public site today, so it **cannot sleep until Phase 2** moves the front door to GoS2.
- **Sleep policy:** GoS1 sleeps after N idle minutes when **all** of these hold: queue empty, no Lab session flag,
  no rig hold (`/tmp/owl-rig-hold`), no CLI campaign, no SSH sessions, no overnight benchmark scheduled. A
  measurement box that sleeps mid-campaign is worse than one that never sleeps. The default is to stay awake.
- **Wake triggers:** a GoS1-only job submitted on the front door, a Lab reservation start, or an admin command.
  - Co-located: **Wake-on-LAN** from GoS2 (BIOS + `ethtool -s eno2 wol g`).
  - After the move, WoL packets can't cross the internet. Options: (a) the Bbox's own WoL feature if it has one;
    (b) power GoS1 off rather than sleep it, and wake it by switching its Tapo plug through the **cloud** API
    (REM already uses that path) with BIOS "power on AC restore". Must be decided before the move (Open Q3).
- **Measurement integrity:** the first job after a wake runs on a cold box. The CR-070 idle-floor guard
  (`power.wait_for_thermal_floor`) already blocks until the floor settles. Confirm it covers a resume-from-sleep
  floor, and that the GPU clock pin (`gpu-clock-pin.service`) is re-applied on resume, not only at boot.
- Visitors waiting on a wake get an honest ETA from the measured wake + settle time.

## 8. GoS2 as a bench

- **Never pooled with GoS1.** GoS2 results are a different host, so GoS2 is a new comparison axis
  (Apple silicon vs x86 + discrete GPU), reported per host.
- **Meters (read off the LAN 2026-10-04, `get_device_info` + 5 × `get_energy_usage` mW samples):**

  | Plug | IP (DHCP, not yet reserved) | MAC | Model / fw | Reading | Role |
  |---|---|---|---|---|---|
  | lab-G1 | `.165` | `C0:3A:55:58:94:64` | P110 hw 1.0 · **fw 1.3.1** (Build 240621) | 0.92–0.97 W | **inner / primary**: Mac Mini only |
  | lab-G2 | `.22` | `EC:75:0C:96:D6:5D` | P110 hw 1.0 · **fw 1.4.8** (Build 260804) | 1.94–1.99 W | outer: Mini + G1 self-draw |

  The owner's "3.1" / "4.8" are 1.3.1 / 1.4.8, normal P110 lines, and `tapo 0.8.12` talks to both. G2 reads
  about 1.0 W above G1, which is G1's self-draw. That confirms **wall → G2 → G1 → Mac Mini**, the same layout as
  GoS1's pair. G1 is on the fast (≥1 Hz) 1.3.1 firmware. G2's 1.4.8 has never been probed but is expected to be
  1.5 s like every post-2024 build, so these are the unequal samplers of CR-065 again: run `bin/probe-p110-fw` on
  both and **turn auto-update off on G1** before any measurement. (`.22` was the Lab-F unit's old lease; it was
  reassigned, so treat any pre-July config naming `.22` as unrelated.)
  The ~0.95 W on G1 at scan time means the Mini was asleep or off, not idle. Its idle floor is still unmeasured.
- G1/G2 belong to GoS2's OWL alone. They must **not** go into `rig.RIG`: rig idle-off would cut power to GoS2 and
  the rig poller would contend for KLAP sessions. Neither node's `.env` lists the other's plugs. Until GoS2's OWL
  owns them, nothing should poll them continuously from GoS1.
- **Ethernet before the first measurement.** CR-074 measured Wi-Fi at +0.2–1.0 W per box, which is a large share of
  a single-digit idle.
- **macOS port surface:**
  - `gpu.py` needs an Apple backend (VideoToolbox encoders; AV1 encode presence to be checked on the M6).
  - Sensors via `powermetrics` (needs a sudoers entry) instead of lm-sensors.
  - launchd plists instead of systemd units.
  - A macOS focus mode (Spotlight indexing, Time Machine, softwareupdate, Photos analysis) to replace the
    systemd timer list.
  - Ollama runs natively (Metal). Image generation via torch MPS.
  - NR-VQA and `ffmpeg-master` paths stay GoS1-only until proven.
- **Calibration:** a fresh variance calibration on first run (CR-031 rule), under normal ambient. The idle floor is
  re-measured after the move, because ambient changes.
- Linux in a VM is not an option for measurement: it would meter the hypervisor.

## 9. Prerequisites in the existing backlog

| Item | Why GoS2 needs it |
|---|---|
| **CR-031 §3 pre-work 1** — `OWL_ROOT` + one env layer | 15 modules hardcode `/home/gos/wattlab`; macOS home is `/Users/…`. |
| **CR-031 §3 pre-work 3** — commit `wattlab.service` + drop-ins | Needed so the GoS1 side of the deployment is reproducible; GoS2 gets the launchd equivalent beside it. |
| **CR-031 §3 pre-work 4** — make `wattlab_service/` a package | Removes CWD-dependent imports under launchd. |
| **CR-066 item 2** — trusted-proxy check | §6 trap 2. A hard gate for Phase 2. |
| **CR-031 §2** — power backend | Not required: G1/G2 are Tapo and the CR-065 registry covers them. |

## 10. Phases

0. **Bring-up and facts (no code).** Bbox reservations for GoS2, G1, G2. Identify the plug model and firmware,
   confirm cabling, `probe-p110-fw` on both. Measure GoS2 idle on Wi-Fi vs Ethernet. Read the M6's encoder list
   (`ffmpeg -encoders | grep videotoolbox`) and what `powermetrics` exposes.
1. **Portability pre-work** (§9 rows 1, 3, 4). Host-prefixed job IDs and a `host` field in the envelope. GoS2
   boots OWL in archive mode (`NoGpuBackend`, no meters) on the LAN, with results and members replicating.
2. **Front-door swap.** Land CR-066 item 2 and the §6 front-door listener. nginx + certbot on GoS2. Bbox 80/443
   forward moves to GoS2. Exercise failover by stopping GoS1's service.
3. **GoS1 sleep/wake** (WoL, co-located). Measure the before/after energy (§3).
4. **GoS2 bench:** Apple `gpu.py` backend, `powermetrics` sensors, macOS focus mode, calibration. First job type:
   whichever runs natively with least porting (likely LLM via Ollama).
5. **The move:** SSH link (§5.2), wake path decided (§7), Lab policy confirmed (§6), idle floor re-measured.

Each phase stands on its own: stopping after Phase 2 still gives a working failover site.

## 11. Open questions

1. ~~Plug model + firmware + cabling~~ answered 2026-10-04 (§8). Still open: fw probe on both, G1 auto-update off,
   Bbox reservations for `.165`/`.22`.
2. Office LAN → Lab on GoS1 through the front door: default **no**. Owner to confirm. (§6)
3. Remote wake after the move: Bbox WoL vs power-cycle via the Tapo cloud. (§7)
4. Can the destination office take inbound 443 (and 80 for ACME, or use DNS-01)? Decides where the front door
   lives after the move. (§5.3)
5. Sleep vs shutdown for GoS1, and the idle timeout. Trades wake latency against standby draw, which is measurable.

## 12. Watch-outs

- Don't let a GoS2 number appear anywhere a GoS1 number is expected (findings, demo, benchmark tables) without a
  host label.
- Don't replicate `settings.json`. A copied calibration on the wrong host gives confident-looking but wrong readings.
- Don't poll a plug from both nodes: KLAP sessions are exclusive per device.
- Don't let the front-door path ever default to Lab (§6). Test it from a public-IP header.
- Every background piece (tunnel, rsync, sleep timer, wake) needs a visible last-success signal.

## 13. Phase 0 log (2026-10-04/05)

### Facts established on the machine
- **Access:** `ssh gos@192.168.1.29` (GoS1 key `~/.ssh/id_ed25519_gos2`, owner MacBook key). Six standard,
  key-only accounts copied from GoS1 (tania, simon, dom, marisol, jon, arian; keys from their GoS1
  `authorized_keys`). Remote access via `ssh -J <user>@gos1.duckdns.org:2222 <user>@192.168.1.29`; no new Bbox port.
  Scripts kept for new users: `~gos/gos2_collect_keys.sh` (GoS1) → `~gos/gos2_add_users.sh` (GoS2).
- **Narrow sudo** (`/etc/sudoers.d/owl-gos2`, installer `~gos/gos2_install_sudo.sh`): NOPASSWD for `pmset`,
  `shutdown -r now` (restart only, never halt), and root-owned argument-checked wrappers
  `/usr/local/sbin/owl-powermetrics N MS` and `owl-sample PROC SECS`. `powermetrics`/`sample` are not exposed
  directly because their output-file options would let root write anywhere. Homebrew needs no sudo.
- **Power:** `sleep 0`, `powernap 0`, `autorestart 1`, `womp 1`; macOS auto-install of updates off.
  **A cleanly shut-down Mac mini cannot be powered on remotely:** WoL only works from sleep, and cycling G1 did not
  boot it (`autorestart` only covers an *unexpected* power loss). Rule: never shut GoS2 down unless someone is on site.
- **Headless rule: GoS2 must have a logged-in console session.** With nobody logged in, `audiomxd` retries
  Bluetooth audio routing (`BTAudioRoutingRequest _ensureXPCStarted` → `SCDynamicStoreCopyConsoleUser`) and
  `configd` answers it, burning ~72 % + ~42 % of a core indefinitely (diagnosed with `owl-sample`; 66 min of
  audiomxd CPU accrued before the fix). Logging in stopped both at once. Fix in place: **auto-login `gos`**,
  screen locked immediately. Wi-Fi state and an HDMI dummy plug made no difference (the dummy isn't even detected).
- **Network:** Ethernet `en0` `.29` (1 GbE, reserved), the only path; Wi-Fi `.95` (reserved) is **off**.
  Screen Sharing (`vnc://gos2.local`) and File Sharing (SMB) are on, LAN only.
- **Meters, 4 Hz probe:** G1 (fw 1.3.1) produces a new value every **2.0 s**; G2 (fw 1.4.8) every **1.5 s**;
  both answer in ~27 ms.
- **Encoders (Homebrew ffmpeg 9.0.2):** `h264_videotoolbox`, `hevc_videotoolbox`, `prores_videotoolbox`, plus
  libx264/libx265/libsvtav1. **No AV1 hardware encode** exposed.
- **Feasibility encode** (Meridian 120 s, 4000 kbps, 1080p, OWL's own samplers + `confidence.py`, n = 1 each,
  not publishable): `h264_videotoolbox` 19.7 s, ΔW +30.2 W, **0.165 Wh** 🟢; `libx264` 40.2 s, ΔW +45.2 W,
  **0.506 Wh** 🟢. Record: `results/diagnostics/gos2_feasibility_20261004_224620.json`.

### Idle-floor history
Protocol (fixed, so rows stay comparable): console logged in, no Screen Sharing client, CPU ≥ 97 % idle for 3
consecutive one-minute checks, then 10-min runs of G1 + G2 at 1 Hz (G2 staggered 0.5 s), CPU idle and Screen
Sharing logged every minute. A run is excluded if CPU idle drops below 97 % or the Screen Sharing encoder exceeds
0.5 %. Report G1 mean ± 95 % CI over n = 3 clean runs (t, df = 2). Re-measure after every software or config change.

| # | Date | State / what changed | GoS2 idle (G1) | G1 self-draw | Record |
|---|---|---|---|---|---|
| 1 | 2026-10-05 | Near-factory: macOS 27.0.1; Homebrew with 15 formulae (only `ffmpeg` requested), 0 casks; Apple CLT; Remote Login, Screen Sharing, File Sharing; auto-login; 7 accounts; 523 launchd jobs, 701 processes; Ethernet only, Wi-Fi off | **1.352 W ± 0.008 W** (runs 2–4; run 1 excluded: CPU idle 82.5 %, Screen Sharing 3.8 %) | 1.007 W | `results/diagnostics/gos2_idle_ethernet_wifioff_20261005_001817.json` |
| 2 | 2026-10-05 | Row 1 + Homebrew python@3.12 venv (torch 2.14.1, diffusers 0.37.1, mlx-lm 0.32.0), **Ollama 0.35.1 brew service running** (idle, no model loaded), ~22 GB HF cache + 3.6 GB Ollama models, 6 standard user accounts, narrow sudo wrappers; 25 formulae (leaves: ffmpeg, ollama, python@3.12), 523 launchd jobs, 717 processes | **1.360 W ± 0.073 W** (runs 1–3, all clean) — no measurable change vs row 1 | 1.021 W | `results/diagnostics/gos2_idle_row2_20261005_043016.json` |

Caveats on every row: G1 refreshes only every 2 s at this load, and P110 accuracy around 1 W has not been checked
against a reference meter. For scale, GoS1 idles at ~79 W display-blanked. That comparison stays an internal
observation until the low-end meter accuracy is checked.

## 14. Overnight build — 2026-10-05 (interim mechanism, owner-approved)

**Owner decisions (2026-10-04, before bed):** GoS2 engines Lab-only · old results read as GoS1 at read time
(files never rewritten) · interim mechanism = GoS1 drives GoS2 over SSH and polls GoS2's plugs over the LAN
(the peer job API of §2 replaces it before any move) · new efficient models may go on GoS1 and the panel.

**What shipped (all tests green, 1156):**
- `hosts.py` — the compute-host registry (`compute_hosts` setting; one entry per machine: identity, SSH,
  meters, ffmpeg, engines × codecs with encoder args, `python`, `ollama`, `mlx_models`). Removing GoS2 or
  adding GoS3 is a settings edit. `power.use_meters()` routes meter reads to a host's plugs context-locally;
  per-host idle floor so GoS1's CR-070 reference is never moved.
- Envelope **v2**: every result carries `host`; video sides carry `engine`. Remote results carry the remote
  host's own `gpu_hardware`/`power_hardware` stamps. Pre-v2 results read as GoS1 (`hosts.result_host`), and
  per-side engine derives from preset + that result's own GPU stamp (AMD-era runs read as AMD).
- `/video`: Lab-only "Other machines" panel rendered from the registry — engines, not hosts (D6) — plus
  `POST /video/remote` (optional `bitrate_kbps` for iso-quality points).
- `remote_ai.py`: `POST /llm/remote` (`runtime=ollama|mlx`), `POST /image/remote`, `POST /image/bench` (batch
  override, local or remote). API-only (no UI panel yet). Host-side runners in `wattlab_service/remote/`.

**Facts learned (keep):**
- **VideoToolbox CBR is a trap:** `-constant_bit_rate 1` on the M6 pads with filler — 5 VMAF lower, 50 %
  slower, 15 % more energy than VBR at the same size. The registry keeps `hw` (CBR, NVENC-parity) and adds
  `hw_vbr`; quote hardware comparisons in VBR.
- **OWL image convention + short runs = wrong answer:** load-diluted mean × generation-only ΔT inverts
  cross-host image comparisons at the default 5-image batch. Use `/image/bench` batch ≥ 50.
- **GoS1 Ollama 0.20.2 image models are broken:** `x/flux2-klein` panics in the runner's Qwen3 text encoder
  (`applyRoPEQwen3` index out of range); `x/z-image-turbo` returns nothing. GoS2 has Ollama 0.35.1. An
  Ollama-image like-for-like needs GoS1's Ollama upgraded (owner sudo).
- Software on GoS2 (2026-10-05): Homebrew python@3.12 venv `~/owl/venv` (torch 2.14.1, diffusers 0.37.1,
  transformers 5.5.0, accelerate 1.13.0, mlx-lm 0.32.0), Ollama 0.35.1 (brew service, defaults — no
  flash-attention/KV env, same as GoS1), models copied byte-identically from GoS1 (Ollama digests
  359d7dd4bcda / 8f68893c685c; HF caches sd-turbo, sdxl-turbo, SANA-Sprint).
- Version gaps to remember when comparing: Ollama 0.20.2 vs 0.35.1, torch 2.11 vs 2.14.1, ffmpeg-master vs 9.0.2.
