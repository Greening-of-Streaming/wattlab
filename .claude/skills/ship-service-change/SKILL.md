---
name: ship-service-change
description: Land a wattlab_service/ change properly — run the 7-second pytest tier (plus targeted tier-2 families), restart the wattlab service yourself and verify /live, then commit files by name with settings.json excluded and CR numbers checked against git log. Use whenever code changes in wattlab_service/ are ready to land, or when the user says "ship it", "land this", "restart and commit", or types /ship-service-change.
argument-hint: [optional commit subject or CR number]
---

# Ship a service change (WattLab / OWL)

The land-a-change checklist. Seed from the user: $ARGUMENTS

## 1. Tests — always, before anything restarts

```bash
cd wattlab_service && pytest tests/
```
- Must run **from inside `wattlab_service/`** (conftest sets sys.path; bare repo-root pytest collects nothing).
- ~7–9 s. The suite has been green after every commit since it existed — keep that property.
- Touched `persist.py` / result envelope / settings / a measurement module? Run the tier-2 family too
  (`pytest tests/ -k "cooldown or confidence"`, `tests/test_result_envelope.py`, etc. — see TESTING.md).
- Monkeypatch rule: patch the `routes_*.py` module that binds the name, never `main`'s alias.
- ⚠ Tests run as **Lab tier** (loopback). If the change touches Anonymous/Member-visible behaviour,
  reason about those tiers explicitly; probe Anonymous with a real public IP header like `8.8.8.8`.

## 2. Restart + verify — do it yourself, no "restart pending"

Only needed for `wattlab_service/` changes (bin/ scripts, docs, findings need no restart).

```bash
sudo systemctl restart wattlab        # narrow sudoers grant — works non-interactively
```
Then poll `http://127.0.0.1:8000/live` until it responds, and spot-check the page the change
touches. If a public-visible page changed, check it via the LAN URL too.
Don't restart mid-measurement: check `/live` queue_depth first; a planned public outage goes
through `bin/stage-on` / `stage-off` instead (the maintenance flag does NOT auto-lower).

## 3. Commit hygiene

- **Add files by name** — never `git add -A` on this tree.
- `settings.json` is live GoS1 state: exclude from feature commits; only a deliberate
  "settings catch-up" commit may include it. `.env` never.
- Assigning a new CR number? Check BOTH before picking:
  `git log --oneline | grep -oE 'CR-[0-9]+' | sort -Vu | tail` **and** `CHANGE_REQUESTS.md` —
  the file lags commits that shipped without an active-CR entry.
- Subject in house style (`CR-NNN: …` or plain imperative; `S<NN>:` is reserved for
  session-close). End with the standard Co-Authored-By trailer. **Never push** unless asked
  this turn.
- Full journal/CLAUDE.md/test-count sync is NOT this skill's job — that's `/session-close`.
