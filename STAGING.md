# OWL Staging — single-service swap with maintenance page

**CR-011** — captured 2026-05-01, shipped 2026-05-02.

Operating procedure (stage-on/stage-off, watchdog, bypass paths) lives in [`bin/README.md`](bin/README.md) and
[`systemd/README.md`](systemd/README.md) — this file keeps only the CR-011 design rationale and the one-time nginx install recipe.

## Design rationale

A way for the owner to swap OWL onto a feature branch, test it live with all the production wiring (nginx, cert, systemd, P110, GPU), then swap back — without public visitors hitting a 502 during the restart window.

There's only one OWL process and one Tapo P110, so a parallel staging instance isn't viable (the two would corrupt each other's measurements). Instead we accept short downtime windows and put up a friendly maintenance page during them.

`stage-on` drains the queue best-effort with a 60s timeout before raising the flag; any jobs still pending after that are *lost* (visitors must re-submit). We deliberately did **not** implement snapshot+restore for pending jobs. That would require refactoring every `enqueue()` call site (video / llm / image / rag) to pass a serialisable `(type, params)` tuple instead of a coroutine closure, plus a factory registry to rebuild the coroutine on the other side — roughly half a day of work touching four modules. The drain-with-timeout approach is ~10 lines of bash and acceptable given GoS1's typical queue depth (≈0 outside active demos). For pre-conference demos, the owner can request CR-001b demo-mode well in advance to let the queue settle naturally; if the queue is unexpectedly deep, restart the whole machine and set demo-mode on boot.

If conference traffic ever makes this trade-off bite, the captured follow-up is "snapshot + coro registry refactor" — search this repo for `CR-011` to find the spot.

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

To revert the vhost edit: remove the `error_page 503`, `@maintenance` location, `/static/` location override, and the two `if (-f /tmp/owl-maintenance)` stanzas, then reload. `/tmp/owl-maintenance` itself is ephemeral (cleared on reboot); `rm /tmp/owl-maintenance` lowers it without restarting anything.
