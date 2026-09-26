---
name: session-close
description: Close out a WattLab/OWL work session — draft and write the JOURNAL.md entry and its condensed-index one-liner, sync any changed project state (variance_pct, CR statuses, test count, Deferred/open checkboxes), then stage a commit in the project's S## style. Use at the end of a session, or when the user types /session-close, "close the session", or "wrap up and journal this".
argument-hint: [optional theme or notes to seed the entry]
disable-model-invocation: true
allowed-tools:
  - Bash(git status:*)
  - Bash(git diff:*)
  - Bash(git log:*)
  - Bash(git add:*)
  - Bash(git commit:*)
  - Read
  - Edit
---

# Session close (WattLab / OWL)

Wrap up the current session by updating the project's running history and conventions, then committing. Optional seed notes from the user: $ARGUMENTS

This is a deliberate, user-invoked ritual. **Draft everything first and show it for approval before writing any file. Never `git push`.**

## 1. Gather the facts

- **Session number** = highest `## Session NN` heading in JOURNAL.md + 1 (NOT git log: some sessions never got an
  `S##` commit, which is how commit `fac9405` ended up labelled "S75" for what is JOURNAL S77).
- `git status` and `git diff --stat <last-session-commit>..HEAD` (or `git diff --stat` if work is still uncommitted) to see what actually changed.
- Read the top of `JOURNAL.md` (condensed index + newest entry) so the new entries match the current format and voice exactly.
- Resolve today's **absolute** date (YYYY-MM-DD). Convert any relative dates in notes/conversation to absolute.
- Pull the session's substance from this conversation: what shipped, what was investigated, decisions made, CRs opened/closed, the test count, and any calibration/measurement results.

## 2. Draft the entries (do not write yet)

Match the existing house style precisely:

a. **JOURNAL.md** — a full-detail `S<NN> (<date>)` entry, same depth and voice as recent entries. This is the long-form record; don't compress it.

b. **JOURNAL.md → condensed session index** (top of the file) — one dense `- S<NN> (<date[s]>): …` line, same style as the lines above it.

c. **CLAUDE.md gets NO session narrative** (moved out 2026-09-27 to save tokens on every session start — no
   `Last updated` summary, no recent-sessions list). Touch CLAUDE.md only when a *durable* fact or rule changed;
   rig open items go to `decode_bench/README.md` §Known infra caveats, non-CR deferred work to
   `CHANGE_REQUESTS.md` §Deferred items.

d. **Cross-cutting state — only what actually changed this session**, edited in place:
   - `variance_pct` / calibration numbers and the matching `## GoS1 Server` idle/variance lines.
   - CR status: move any closed CR to `CHANGE_REQUESTS_CLOSED.md`, update the live list + groupings in `CHANGE_REQUESTS.md`, and the CLAUDE.md cross-reference counts at the top.
   - Test count (e.g. "NNN tests passing").
   - Resolved items in `decode_bench/README.md` §Rig harness open items or `CHANGE_REQUESTS.md` §Deferred items.

e. **Memory** — if the session produced a durable, non-obvious fact (a user preference, a project decision, an external reference), propose a memory file under the memory dir + a one-line `MEMORY.md` pointer. Skip anything derivable from the code, git history, or CLAUDE.md.

## 3. Confirm, then write

Show the user the drafts (at minimum a→b, plus any d/e). Only after they approve, apply the changes with `Edit` against the real files. Preserve the surrounding formatting exactly — these files are read at the start of every session, so a botched edit costs every future session.

## 4. Commit

- Stage the session's files **by name** — never `git add -A`: `settings.json` is GoS1 live state and stays out
  (only a deliberate "settings catch-up" commits it), and another session may have work in the tree.
- Commit on the **current branch**, matching the project's established practice (recent `S<NN>:` commits land directly on `main`). Subject line in the house style: `S<NN>: <headline>`.
- End the commit message with the `Co-Authored-By:` trailer the harness specifies for the current model.
- Show the staged diff and the proposed message and get a final go-ahead before committing.
- **Never `git push`** unless the user explicitly asks in this turn.
