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
- **Loopback `/live` needs no cookie.** Since CR-001 task #10 retired `WATTLAB_GATE_PASSWORD`, audience.tier resolves loopback IP → Lab and the request passes capability checks directly.
- **Both call `sudo systemctl restart wattlab`** — your shell's sudo cache will be prompted if it's expired.
- **Manual recovery:** if a script fails partway through and leaves things wedged, the safe sequence is: `rm /tmp/owl-maintenance`, then `sudo systemctl restart wattlab`, then `git checkout main` if you want to be back on main. The flag file is the only persistent state.

---

## fetch-historical-mix — historical France carbon-intensity helper

One-shot Python helper that fetches a given month from the Eco2mix consolidated dataset (RTE/Etalab, 2012–present, 30-min resolution), runs each record through `carbon.compute_intensity_from_mix`, and prints the monthly mean **lifecycle gCO₂/kWh**. Same calculation as the live FR path, so its output is directly comparable to today's number.

Shipped as part of **CR-018 Tier 1** — see [`CHANGE_REQUESTS.md`](../CHANGE_REQUESTS.md) for the upgrade path (Tier 2 = visitor-pickable any month, Tier 3 = interactive scrubber).

### Usage

```bash
~/wattlab/bin/fetch-historical-mix --year 2022 --month 6
~/wattlab/bin/fetch-historical-mix --year 2020 --month 6 --quiet
```

**Output:** one line on stdout, e.g. `2024-06: 26.9 g/kWh  (n=1440, range 22.5–41.8)`.

| Flag | Purpose |
|---|---|
| `--year YYYY` | Required. Any year from 2012 to last year (consolidated data lags real-time by months). |
| `--month MM` | Required. 1–12. |
| `--quiet` | Suppress per-page progress on stderr. Only prints the final line. |

### When to use it

- **Adding a new historical date to the carbon comparison strip.** Pick a year and month, run the script, copy the printed `g_per_kwh` value into `carbon.HISTORICAL_INTENSITY` (in `wattlab_service/carbon.py`) along with a label and one-line note explaining what's notable about that period. Restart wattlab. Done.
- **Sanity-checking an existing entry** if you want to confirm the table value against the source data (the script is deterministic for a given month — same factors, same records).

### Things to know

- **One-off, not a service.** No cron, no cache, no daemon. Run it when you want to add or refresh a date; otherwise it sits idle.
- **Reuses the same lifecycle math as the live path.** The script imports `carbon.compute_intensity_from_mix` directly, so any future change to `EMISSION_FACTORS` automatically applies here too. The historical and live numbers can never silently drift to different methodologies.
- **FR-only.** Eco2mix is RTE's data; for non-FR historical you'd need ElectricityMaps' paid historical API or Ember monthly data — captured as a follow-up consideration in CR-018.
- **Network and time cost.** A monthly fetch is ~1500 records via the Opendatasoft API; takes 5–15 seconds depending on RTT. Well under the API's 10000-offset cap.
- **No write side-effects.** The script doesn't touch `carbon.py`, `settings.json`, or any cache file — just prints to stdout. You manually paste the value.

---

## probe-thermal-recovery — post-encode idle recovery diagnostic

Characterise how quickly the GoS1 server's idle-power reading returns to baseline after a CPU encode and after a GPU encode. Used to validate the `variance_cooldown_s` setting is long enough — the recovery curve should flatten well before the configured cooldown.

Shipped as part of **CR-022 / CR-023** investigation in S21. Captured in `CHANGE_REQUESTS.md` as **CR-024** — promote to a queue-aware `/precalibration/run` endpoint with a "▶ Re-run probe" button on the settings panel (deferred; the panel currently renders the latest probe data read-only).

### Usage

```bash
~/wattlab/bin/probe-thermal-recovery
~/wattlab/bin/probe-thermal-recovery --distances 0,10,30,60,90,120
~/wattlab/bin/probe-thermal-recovery --baseline-polls 5 --pre-cool-s 15
```

**Output:** two CSVs under `results/diagnostics/recovery_<timestamp>{_summary,}.csv`. Summary has one row per (distance, workload); raw has one row per poll. The "More calibration details" dropdown on `/settings` reads the latest `_summary.csv`.

| Flag | Purpose |
|---|---|
| `--distances` | Comma-separated seconds. Default `0,2,5,8,12,18,25,35,50,70,95,120` — dense in 0-15s where recovery is steepest, sparse past 30s. |
| `--baseline-polls` | Idle polls per measurement window. Default = `settings.baseline_polls`. |
| `--pre-cool-s` | Wait before each encode. Default 30s. The encode itself dominates the post-state; pre-state mostly washes out. |
| `--out` | Override raw CSV path. Summary path derives from it. |

### When to use it

- **Before a variance calibration** if anything has changed (hardware swap, ambient temp shift, focus-mode exemption added). The recovery curve tells you whether the configured `variance_cooldown_s` is still adequate.
- **After fixing a measurement bug** like CR-022 / CR-023 — re-confirms the recovery shape is what you expect.
- **Investigating anomalies** in `variance_idle_pct`. The probe's per-window CV is the floor; calibration's pooled CV must be ≥ probe's mean within-window CV. If they diverge, something's polluting the calibration that the probe doesn't reproduce.

### Things to know

- **Holds visitor-protection flags.** Touches `/tmp/owl-paused` (queue worker stops dispatching new jobs) and `/tmp/gos-measure.lock` (system-busy marker). Both released on clean exit and Ctrl-C. Visitors can still browse and queue jobs during the run; nothing executes until the probe finishes.
- **Aborts at startup if `LOCK_FILE` already exists.** Wait for any in-flight measurement to finish, or `rm /tmp/gos-measure.lock` if it's stale.
- **CPU and GPU use different inputs.** CPU runs `variance_cpu_cmd` on the full `meridian_4k.mp4` (172s heavy thermal load — what variance calibration uses). GPU runs the variance template against `meridian_120s.mp4` so CR-022's `-t 30` cap (which `transcode()` applies automatically) keeps the encode cleanly bounded. Asymmetric but representative.
- **~65 min wall time** for the default 12-distance sweep. The script's own estimate is printed at startup before it begins.
- **Focus mode** stops 8 timer units (sysstat-collect, anacron, fwupd, apt-daily etc.) for the duration. Restored in `finally` — including on Ctrl-C.
