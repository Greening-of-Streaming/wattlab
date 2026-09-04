# GoS1 Disaster Recovery — how to rebuild from nothing

First written 2026-08-31. **Revised 2026-09-05** — repo ownership corrected,
the "not backed up" list extended after a second live audit, and this file
moved into git so it is no longer single-homed on Nextcloud.

Every claim below was verified against the running system, not read off
documentation. Full backup context/history: `GOS1_INFRA.md`.
**This file contains no secret values** — only where they live and how to
restore them.

Two copies, deliberately: `wattlab/GOS1_DISASTER_RECOVERY.md` (GitHub, so it
survives losing Nextcloud) and `nextcloud:GoS1-backup/GOS1_DISASTER_RECOVERY.md`
(so it survives losing GitHub access). Keep them in step.

## The GitHub org is the durable copy (verified 2026-09-05)

Everything important lives on the **Greening-of-Streaming** org:

| Repo | What it is | Visibility |
|---|---|---|
| `wattlab` | OWL — this bench's own app | public |
| `LEM` | Local Energy Measurement (mW-lossless local plug polling) | public |
| `rem` | Remote Energy Measurement — TimescaleDB + UI + collector | public |
| `rem-backup` | The GoS REM software | private |
| `smpte-4951` | The SMPTE 2026 paper + digests/findings | private |
| `smpte-4951-evidence` | Citable evidentiary record behind paper #4951 | public |
| `wg4`, `wg7` | Working-group shared IP | public / private |

Clone those; that's the code and every published finding/digest. **None of it
needs Nextcloud.**

⚠ **Do not read ownership off the local clones' `origin`.** On GoS1 the working
copies point at `nebul2` mirrors — `~/wattlab/REM/repo` has origin `nebul2/REM`
with `Greening-of-Streaming/rem-backup` as `upstream`, and `~/dev/LAN-reader`
(LEM) has only `nebul2/LEM`. That is a local convenience, not where the durable
copy lives. Verified 2026-09-05: org `LEM` HEAD is identical to local
(`f69903f`), and local REM HEAD (`12a3f98`) is an ancestor of org
`rem-backup/master`, which is 2 commits ahead. The org copies are complete.

## What Nextcloud actually has (re-verified 2026-09-05)

**Live and current:** `nextcloud:GoS1-backup/wattlab-results/` — synced nightly
at 03:30 by `/etc/cron.d/wattlab-results-backup`, logging to
`~/.cache/wattlab-backup.log`. Covers every measurement result type including
`results/decode/` and `results/training/`.

Verified by `rclone check`, not by reading the log: **8657 files matching**,
9 missing and 1 differing — all of which were created *after* the last 03:30
run (that night's decode rows, the football calibration staging files, and
`_analytics/visits.json`, which changes daily). That is normal sync lag.
Local 8667 files / 328.8 MiB, remote 8658 / 326.8 MiB.

Restore: `rclone sync nextcloud:GoS1-backup/wattlab-results/ /srv/data/owl/results/`

Transient failures self-heal: on 2026-09-03 Hetzner sent an HTTP/2 `GOAWAY`
mid-upload, attempt 1 of 3 failed, attempt 2 succeeded. Worth knowing so a lone
ERROR line in the log doesn't read as a broken backup.

**Stale — a one-time snapshot from 2026-04-09, never repeated:** `ssh/`,
`gnupg/`, `config/`, `etc/` under `nextcloud:GoS1-backup/`. Useful as a starting
skeleton; anything created or edited after 2026-04-09 is **not** in it.

The whole Nextcloud account holds ~346 MiB. Essentially all of it is the results
sync. For scale, GoS1's data disk holds 367 GB.

## What is NOT backed up anywhere — rebuild these manually

### Secrets and access

- **`.env`** (`/home/gos/wattlab/.env`) — gitignored, never in Nextcloud.
  `TAPO_EMAIL`, `TAPO_PASSWORD`, `TAPO_P110_IP` (+`_2`), `OWL_AUTH_SECRET`,
  `OWL_SMTP_USER`, `OWL_SMTP_PASSWORD`. **Zero backup coverage.** Keep a copy in
  Bitwarden — it cannot be reconstructed from any backup. (Losing
  `OWL_AUTH_SECRET` invalidates every outstanding magic link; members simply
  sign in again, so it is recoverable in practice, unlike the Tapo/SMTP
  credentials.)
- **SSH keys created or touched after 2026-04-09 — none are backed up.**
  `~/.ssh/id_ed25519_decodebench` (rig access), `id_ed25519_gh` (GitHub auth),
  `id_ed25519_linode_rem` (REM Linode host), `id_ed25519_macbook`
  (MacBook↔GoS1). The April snapshot contains only the older `id_ed25519`,
  `authorized_keys`, `known_hosts` and `config`. **Losing GoS1 means
  regenerating all four keys and re-authorising each by hand** — GitHub keys,
  the rig's `authorized_keys`, the REM host's `authorized_keys`, the MacBook.
  Plan for this; it is not a restore, it is a rebuild.
- **`/etc/sudoers.d/`** — `wattlab-restart` (lets Claude restart the service
  non-interactively) and `wattlab-focus` (the focus-mode timer grants). Narrow,
  hand-authored, not backed up. `wattlab-focus` has a stale template in the
  April snapshot; treat both as hand-authored.
- **TLS certs** (`/etc/letsencrypt/`) — correctly not backed up; reissue with
  certbot on a rebuilt box.

### Knowledge and glue — the part that isn't obvious

- **`REM/CLAUDE.md`, `REM/DUAL_TRACK_METHODOLOGY.md`, `REM/TRAINING_REM_5MIN.md`,
  `REM/.claude/settings.local.json`** (~24 KB total). These sit in the wattlab
  tree but are **gitignored** (`.gitignore:34` ignores `REM/`) and are **not**
  inside `REM/repo`'s own git either. **Single copy, on this box only.** This is
  the OWL↔REM operating knowledge — how the two projects relate, the dual-track
  methodology, the 5-minute training note. Highest-value unbacked item in the
  repo.
- **`~/.claude/projects/-home-gos-wattlab/memory/`** — 25 memory files plus
  `MEMORY.md`: durable working rules (publication bar, energy-not-CO2e, tests
  run as Lab tier, the Roku channel nav sequence, the Apple TV state notes).
  An off-repo archive of the *2026-08-19 pruned* set exists at
  `/srv/data/owl/claude-memory-archive-2026-08-19/` — itself not backed up.
- **`/srv/data/owl/vqa-eval/`** (555 MB) — the NR-VQA sandbox, a documented
  runtime dependency that is deliberately not in git. Critically it carries a
  **local patch** to `CompressedVQA-HDR/NR/VQA_NR.py` (the
  `video_read_index < video_length_read` guard, ~line 60) without which upstream
  crashes on 23.976 fps clips. CLAUDE.md says "reapply after any re-clone" — but
  the patch itself exists nowhere else. Re-derive from CLAUDE.md's description
  if lost.
- **`data/members.json`** (3.2 KB) — the live member allowlist for the public
  service. Not git-tracked, not in the results sync. `data/lab_reservations.json`
  (CR-083) sits beside it; that one is a courtesy calendar and acceptable loss.

### Bulk data

Not backed up, and mostly too large to be:

| Path | Size | Recoverable? |
|---|---|---|
| `/srv/data/owl/stb-decode-2026-07` | 98 GB | Raw campaign captures — no |
| `/srv/data/owl/rem_out` | 97 GB | REM playback files; **carries circulating share tokens** |
| `/srv/data/owl/pixop` | 34 GB | Re-derivable from sources |
| `/srv/data/owl/test_content` | 26 GB | Mostly re-downloadable; the `football` master is a third-party re-upload that may not be |
| `/srv/data/owl/campaign_*` | 14 dirs | Findings survive in git digests; the raw reproducibility trail does not |
| `/srv/data/owl/corpus` | 278 MB | RAG corpus (redistributed PDFs) |
| `/srv/data/owl/uploads` | 141 MB | Keep-class user uploads — **a user-facing "never removed" promise** |
| `/srv/data/owl/.chroma` | 153 MB | Regenerable from `corpus/` |

### Config

- **nginx `sites-enabled/`** — symlinks, skipped by the backup's `--skip-links`.
  `sites-available/wattlab` is captured but stale (April); re-enable with `ln -s`.
- **systemd:** `wattlab.service` and its `wattlab.service.d/mount.conf` drop-in,
  plus `/etc/cron.d/wattlab-results-backup`, exist only in `/etc` on this box —
  `systemd/README.md`'s "source of truth lives here" claim is currently false for
  the primary unit. (Tracked as CR-031 §3 pre-work item 3.)
- **DuckDNS updater** (`~/duckdns/duck.sh`, gos crontab, every 5 min) —
  redundant while the IP is static, kept as insurance; not backed up, short
  enough to recreate from `GOS1_INFRA.md`.

## Hardware / rig side

`rig.RIG` in `wattlab_service/rig.py` is git-tracked — safe. What isn't, and
cannot be: physical device state — paired webOS/Bluetooth keys, ADB
authorisations, the Roku channel install, Apple TV Companion pairing. All
on-site, hands-on work after a rebuild. Nothing to back up; just know it's not
covered.

## The actual gap, stated plainly

The backup that looks "done" is fully current **for measurement results only**.
Everything that would matter most in a real disaster — secrets, the four working
SSH keys, the REM glue docs, the VQA patch, the member allowlist — is either a
stale April snapshot or has no coverage at all.

This is the same failure class already logged in `GOS1_INFRA.md`'s "Silent
failure incident": a backup that appears healthy while quietly not covering what
it needs to. The difference is that this time it is written down.

**The fix is scoped but not done** — widen the recurring sync to include
`.ssh/`, `.env`, `sudoers.d/`, `data/`, the REM glue docs and the VQA patch,
behind an `rclone crypt` overlay, plus a last-success health check. That is
**CR-067 item 5** plus the standing `rclone-crypt` TODO in `GOS1_INFRA.md`. It
needs an owner decision on encryption before anything secret is uploaded.
