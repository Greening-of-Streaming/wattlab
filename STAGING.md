# OWL Staging — single-service swap with maintenance page

**CR-011** — captured 2026-05-01, shipped 2026-05-02.

## What this is

A way for the owner to swap OWL onto a feature branch, test it live with all the production wiring (nginx, cert, systemd, P110, GPU), then swap back — without public visitors hitting a 502 during the restart window.

There's only one OWL process and one Tapo P110, so a parallel staging instance isn't viable (the two would corrupt each other's measurements). Instead we accept short downtime windows and put up a friendly maintenance page during them.

## Workflow

```bash
# Switch to a feature branch, restart wattlab, raise the maintenance flag.
~/wattlab/bin/stage-on --branch <feature-branch>

# …test on http://192.168.1.62:8000 (LAN) or via SSH tunnel…

# Switch back to main, restart wattlab, lower the flag.
~/wattlab/bin/stage-off --main
```

You can also run `stage-on` without `--branch` (just raises the flag, e.g. for a planned cert-renewal restart) and `stage-off` without `--main` (e.g. you're staying on the staged branch because you've decided to ship it directly).

## Owner access during staging

Public visitors hit nginx at `wattlab.greeningofstreaming.org` and see the maintenance page. The owner bypasses nginx via either:

- **LAN**: `http://192.168.1.62:8000` — direct to FastAPI.
- **SSH tunnel**: `ssh -p 2222 -L 8000:localhost:8000 user@gos1.duckdns.org`, then `http://localhost:8000`.

Requests arriving through the tunnel are **loopback (127.0.0.1) → Lab tier** (full access, bypasses nginx + the public gate). The public hostname gives Anonymous/Member tier only. Note `-p 2222` is the *external* port — the Bbox forwards `2222 → GoS1:22`; on-LAN just use `ssh gos@192.168.1.62`.

### Prefilled — collaborator SSH access

Hand these to a collaborator whose key is in their `~/.ssh/authorized_keys` on GoS1.

```bash
# arian (added 2026-07-01)
ssh -p 2222 arian@gos1.duckdns.org                            # shell login
ssh -p 2222 -L 8000:localhost:8000 arian@gos1.duckdns.org     # tunnel → open http://localhost:8000 (Lab tier)
```

Same single-operator rule as owner Lab sessions: only one person should run measurements at a time (one OWL process, one P110) — a tunnelled collaborator contends for the box if they run jobs mid-measurement.

## What `stage-on` does (and the queue trade-off)

1. **Drain the queue, best-effort, with a 60s timeout.** If a visitor's job is in flight when you stage, the script waits up to 60s for it to finish. After that it warns and proceeds; any pending jobs are *lost* (visitors must re-submit).
2. **Touch `/tmp/owl-maintenance`** — the file nginx watches.
3. **(Optional) `git checkout <branch>`**.
4. **`sudo systemctl restart wattlab`**.

We deliberately did **not** implement snapshot+restore for pending jobs. That would require refactoring every `enqueue()` call site (video / llm / image / rag) to pass a serialisable `(type, params)` tuple instead of a coroutine closure, plus a factory registry to rebuild the coroutine on the other side — roughly half a day of work touching four modules. The drain-with-timeout approach is ~10 lines of bash and acceptable given GoS1's typical queue depth (≈0 outside active demos). For pre-conference demos, the owner can request CR-001b demo-mode well in advance to let the queue settle naturally; if the queue is unexpectedly deep, restart the whole machine and set demo-mode on boot.

If conference traffic ever makes this trade-off bite, the captured follow-up is "snapshot + coro registry refactor" — search this repo for `CR-011` to find the spot.

## What `stage-off` does

1. **(Optional) `git checkout main`**.
2. **`sudo systemctl restart wattlab`**.
3. **Wait for `/live` to respond OK** (up to 30s) — prevents a brief 502 between flag-removal and FastAPI being ready.
4. **Remove `/tmp/owl-maintenance`**.

If the service fails to come up, the flag is *not* removed and `stage-off` exits non-zero. Public visitors keep seeing the maintenance page until the next successful `stage-off`.

## Auto-lower on inactivity (CR-015)

A systemd timer (`owl-maintenance-watchdog.timer`) fires every minute and lowers the flag automatically once it goes stale. Stale = mtime older than `max_idle_mins` (default 30, in `settings.json`). The Lab-tier middleware in `main.py` touches the flag on every request, so the window stays open as long as the operator is using the LAN URL or SSH tunnel — no manual heartbeat required. Manual `touch /tmp/owl-maintenance` also extends the window.

See `bin/README.md` (`## owl-maintenance-watchdog`) and `systemd/README.md` for install + tuning.

## Files

| Path | What | Owner |
|---|---|---|
| `bin/stage-on` | Raise flag + restart on (optionally) a feature branch | gos (repo) |
| `bin/stage-off` | Wait-for-up + lower flag + restart on (optionally) main | gos (repo) |
| `bin/owl-maintenance-watchdog` | One-shot CR-015 auto-lower watchdog | gos (repo) |
| `systemd/owl-maintenance-watchdog.{service,timer}` | Timer + service that drive the watchdog | gos (repo) |
| `wattlab_service/static/maintenance.html` | The page nginx serves while flag is up | gos (repo) |
| `/etc/nginx/sites-available/wattlab` | Vhost with maintenance-flag block (see below) | root |
| `/tmp/owl-maintenance` | The flag itself — touched by stage-on, removed by stage-off | gos |

## nginx config (one-time install)

### 1. Grant nginx read access to the repo's static dir

`/home/gos/` is `drwxr-x---`, so `www-data` (nginx) can't traverse into the repo to read `maintenance.html`. Group `gos` already has rx on `/home/gos`, so adding `www-data` to it is the lightest fix:

```bash
sudo usermod -a -G gos www-data
sudo systemctl restart nginx
```

This grants `www-data` traversal through `/home/gos/` and read of files within (which are `-rw-r--r--`). Subdirectories with their own restrictive perms are unaffected. To roll back: `sudo gpasswd -d www-data gos && sudo systemctl restart nginx`.

### 2. Vhost edits

Add the following to the active `server { }` block in `/etc/nginx/sites-available/wattlab` — the one with `listen 443 ssl;` (managed by Certbot). It needs to sit *before* the existing `location /` block:

```nginx
    # CR-011 — maintenance-page swap. Triggered by /tmp/owl-maintenance.
    error_page 503 @maintenance;
    location @maintenance {
        root /home/gos/wattlab/wattlab_service/static;
        rewrite ^.*$ /maintenance.html break;
        internal;
    }

    # Serve /static/* directly from disk so the maintenance page's owl.svg
    # loads even while FastAPI is restarting. Also a small perf win in
    # normal operation (nginx is faster than proxying through uvicorn for
    # tiny files). Pairs with the gos-group membership step above.
    location /static/ {
        root /home/gos/wattlab/wattlab_service;
        access_log off;
    }
```

Then prepend this stanza to *each* `location` block that proxies to FastAPI (the `location ~ ^/(video/use-source|...)$` block and the `location /` block):

```nginx
        if (-f /tmp/owl-maintenance) {
            return 503;
        }
```

Reload nginx:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## Rollback

The CR-011 surface is intentionally narrow:

- **OWL repo:** `bin/stage-on`, `bin/stage-off`, `wattlab_service/static/maintenance.html`, this file. No Python changes. `git revert` on the staging commit reverts everything.
- **System config:** the nginx vhost edit. To revert, remove the `error_page 503`, `@maintenance` location, `/static/` location override, and the two `if (-f /tmp/owl-maintenance)` stanzas.
- **Filesystem state:** `/tmp/owl-maintenance` (ephemeral, cleared on reboot). If accidentally left up, `rm /tmp/owl-maintenance` lowers it without restarting anything.

If the whole approach turns out to be the wrong call, the rollback is a `git revert` and a one-block nginx edit. No data migrations, no compat shims.
