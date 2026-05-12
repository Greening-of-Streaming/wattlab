# GoS1 Infrastructure & Backup Context
# Companion to CLAUDE.md (which covers WattLab project specifics)
# Last updated: 2026-05-12 (S24 — 4TB data disk added, OWL bulk data moved to /srv/data)

## Owner
Ben Schwarz (bs@ctoic.net / EURL CTO INNOVATION CONSULTING / SIREN 508109337)

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

## Cooling (S24, 2026-05-12)
9 fans total: **5 case** (the 5th re-enabled via a Y-splitter off an existing header — had been left deactivated), **2 GPU** (integrated on the RX 7800 XT), **1 CPU** (the board header can drive a 2nd if thermals warrant), **1 PSU internal**. The whole envelope is inside the P110 measurement boundary, so the extra fan shows up in idle/active draw — see the recalibration note above. Relevant to WattLab CR-005 (fan control).

## Other Users
dom, marisol, simon, tania — home dirs exist but unreadable by gos user.

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
