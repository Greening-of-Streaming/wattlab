# bin/ — operations scripts

This directory holds the operator-facing shell scripts for OWL. Each one is documented below with: what it does, how to run it, the flags it accepts, and any "things to know" that don't fit in `--help`.

When you add a new script here, **add a section to this file**. The pattern: `## script-name`, then a short description, then a fenced usage block, then options/examples/gotchas. Keep it self-contained — the script's `--help` and this README should both stand alone.

---

## stage-on / stage-off — staging mode

Switch OWL onto a feature branch and test it live with full production wiring (nginx, cert, systemd, P110, GPU), without public visitors hitting a 502 during the restart window. Public visitors see a friendly maintenance page; the owner bypasses nginx and reaches the live site via LAN or SSH tunnel.

This pair was shipped as **CR-011** — see [`STAGING.md`](../STAGING.md) for the full design and the one-time nginx config that has to land before the scripts do anything useful.

### stage-on

Raises the maintenance page and (optionally) checks out a feature branch before restarting wattlab.

```bash
~/wattlab/bin/stage-on [--branch <name>] [--drain-timeout <seconds>]
```

**What it does, in order:**
1. Polls `/live` for `queue_depth`. If non-zero, waits up to 60s for in-flight jobs to finish. If still non-zero after the timeout, warns and proceeds (pending jobs are lost — visitors must re-submit).
2. Touches `/tmp/owl-maintenance` — the file nginx watches. From this point on, public visitors get a 503 + maintenance page.
3. *(Optional)* `git checkout <branch>` if `--branch` was given.
4. `sudo systemctl restart wattlab`.

**Options:**

| Flag | Purpose |
|---|---|
| `--branch <name>` | Branch to check out before restarting. `<name>` is a placeholder — replace with the actual git branch name (e.g. `cr-001b-demo-lock`). Omit to keep the currently-checked-out branch (useful if you've checked it out manually, or you just want to take the public site down for a planned restart like a cert renewal). |
| `--drain-timeout <seconds>` | Override the 60s queue-drain budget. Rarely needed. |

**Examples:**

```bash
# Most common: test a feature branch you've already pushed.
~/wattlab/bin/stage-on --branch cr-001b-demo-lock

# Just take the public site down for ~5 minutes (no branch switch).
~/wattlab/bin/stage-on
```

### stage-off

Brings OWL back to public service and (optionally) returns to `main` first.

```bash
~/wattlab/bin/stage-off [--main]
```

**What it does, in order:**
1. *(Optional)* `git checkout main` if `--main` was given.
2. `sudo systemctl restart wattlab`.
3. Polls `/live` (up to 30s) until FastAPI responds — prevents a brief 502 between flag-removal and FastAPI being ready.
4. Removes `/tmp/owl-maintenance`. Public site is live again on the next request.

If FastAPI fails to come up within 30s, the flag is **not** removed and the script exits non-zero. Public visitors keep seeing the maintenance page until the next successful `stage-off`.

**Options:**

| Flag | Purpose |
|---|---|
| `--main` | Check out `main` before restarting. Omit if you're shipping the staged feature directly (you've decided the branch is good and want to merge later, but the staged commit *is* the new production state). |

**Examples:**

```bash
# Done testing — back to main.
~/wattlab/bin/stage-off --main

# Done testing and we're keeping this branch live (will merge to main later).
~/wattlab/bin/stage-off
```

### Things to know

- **The maintenance flag does NOT auto-disable.** Once `stage-on` raises `/tmp/owl-maintenance`, the public site stays on the maintenance page until you explicitly run `stage-off`, manually `rm /tmp/owl-maintenance`, or the server reboots (which clears `/tmp` — implicit safety net, don't rely on it). If you walk away from the desk after running `stage-on`, public visitors will see "Brief maintenance" for as long as you're gone. A future CR could add an auto-lower cron after N hours; for now, just remember to run `stage-off` when you're done.
- **Owner bypass paths during staging:** LAN `http://192.168.1.62:8000` (direct to FastAPI, skips nginx) or SSH tunnel `ssh -p 2222 -L 8000:localhost:8000 user@gos1.duckdns.org`. Both reach the live site with zero maintenance page in the way.
- **Both scripts source `/home/gos/wattlab/.env`** to get `WATTLAB_GATE_PASSWORD` for the `/live` cookie — needed because the loopback `/live` request still goes through the gate middleware.
- **Both call `sudo systemctl restart wattlab`** — your shell's sudo cache will be prompted if it's expired.
- **Manual recovery:** if a script fails partway through and leaves things wedged, the safe sequence is: `rm /tmp/owl-maintenance`, then `sudo systemctl restart wattlab`, then `git checkout main` if you want to be back on main. The flag file is the only persistent state.
