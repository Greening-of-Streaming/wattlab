# systemd/ — service and timer units

Systemd units that need to be installed once on GoS1 with `sudo`. Source-of-truth lives here in the repo; copies under `/etc/systemd/system/` are the active ones.

When you add a unit here, document it below: what it does, how to install, how to verify.

---

## owl-maintenance-watchdog.service / .timer — auto-lower the staging flag

CR-015 follow-up to CR-011 staging. When `stage-on` raises `/tmp/owl-maintenance` and the operator forgets to run `stage-off`, public visitors see the maintenance page indefinitely. The watchdog timer fires every minute; the service runs `bin/owl-maintenance-watchdog` which:

1. Exits immediately if the flag isn't raised.
2. Reads `max_idle_mins` from `settings.json` (default 30).
3. If the flag's mtime is younger than the threshold, exits — the operator is active (the Lab-tier middleware in `main.py` touches the flag on every request).
4. Otherwise runs `bin/stage-off`, which restarts wattlab and removes the flag.

So the operator extends the staging window simply by *using* the LAN URL or SSH tunnel — no manual heartbeat command needed.

### Install (one-time, owner runs as sudo)

```bash
sudo cp /home/gos/wattlab/systemd/owl-maintenance-watchdog.service /etc/systemd/system/
sudo cp /home/gos/wattlab/systemd/owl-maintenance-watchdog.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now owl-maintenance-watchdog.timer
```

### Verify

```bash
# Should show "active (waiting)" with the next-run timestamp.
systemctl status owl-maintenance-watchdog.timer

# Last few firings of the script.
journalctl -u owl-maintenance-watchdog.service -n 20 --no-pager
```

### Tune the threshold

Edit `max_idle_mins` in `settings.json` (or via the `/settings` page, Lab tier). Default 30. Lower for "I'm doing a quick demo" (e.g. 5); higher for "I'm head-down for the afternoon" (e.g. 120). No restart needed — the watchdog re-reads settings on every fire.

### Disable temporarily

```bash
sudo systemctl stop owl-maintenance-watchdog.timer
```

Re-enable with `sudo systemctl start owl-maintenance-watchdog.timer` (the `enable` from the install step persists across reboots).
