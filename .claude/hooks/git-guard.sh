#!/usr/bin/env bash
# PreToolUse(Bash) guard — blocks git commands that can silently destroy
# uncommitted work. Born from the 2026-06→07 finding-drafter near-loss
# (written, never committed, buried in a mixed `git stash -u`).
#
# Reads the hook JSON on stdin, inspects .tool_input.command, and on a match
# emits a PreToolUse "deny" decision (the command never runs). Read-only git
# (status/log/diff/show/stash list/stash show) is always allowed. Fail-open:
# any internal error allows the command (a guard must never wedge the session).
#
# Only ACTUAL command invocations are inspected — heredoc bodies (commit
# messages) are stripped and the command is split on shell separators, so a
# commit message that merely NAMES `git reset --hard` is not flagged.
set -uo pipefail

cmd="$(jq -r '.tool_input.command // ""' 2>/dev/null || echo "")"
[ -z "$cmd" ] && exit 0

deny() {  # $1 = reason shown to the user + model; blocks the tool call.
  jq -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

# Drop everything from the first heredoc operator on (commit-message bodies live
# there), then normalise every shell separator to a newline so each surviving
# segment is a single command whose FIRST tokens are the actual invocation.
analyze="${cmd%%<<*}"
analyze="$(printf '%s' "$analyze" | sed -E 's/(\|\||&&|[|&;()`\n])/\n/g')"

while IFS= read -r seg; do
  # Trim leading whitespace + common prefixes that precede a real command
  # (env assignments, sudo, nice, etc. left as-is — we only need the git token).
  seg="${seg#"${seg%%[![:space:]]*}"}"
  [ -z "$seg" ] && continue

  # Must be a git invocation at the start of this segment.
  [[ "$seg" =~ ^git[[:space:]]+([a-z-]+) ]] || continue
  sub="${BASH_REMATCH[1]}"

  case "$sub" in
    reset)
      [[ "$seg" == *--hard* ]] && deny "Blocked: 'git reset --hard' discards uncommitted work irrecoverably. Commit to a branch first, or 'git stash -u' if you truly need a clean tree. (WattLab VC discipline)"
      ;;
    clean)
      if ! [[ "$seg" =~ (--dry-run|-[A-Za-z]*n) ]]; then
        deny "Blocked: 'git clean' without -n deletes untracked files (new .py has no other copy; .gitignore does NOT protect them). Run 'git clean -n' to preview, then delete named paths deliberately. (WattLab VC discipline)"
      fi
      ;;
    stash)
      # Only CREATE forms (bare / push / save) need untracked inclusion;
      # list/show/pop/apply/drop/branch/clear are read-only or restorative.
      stashsub="$(awk '{print $3}' <<<"$seg")"
      case "$stashsub" in
        list|show|pop|apply|drop|branch|clear) : ;;
        *)
          if ! [[ "$seg" =~ (--include-untracked|--all|-[A-Za-z]*[ua]) ]]; then
            deny "Blocked: a bare 'git stash' drops untracked (new) files silently — that's how work gets lost. Prefer a wip/ branch commit. If you must stash: 'git stash -u' then 'git stash branch <name>' to turn it into a commit. (WattLab VC discipline)"
          fi
          ;;
      esac
      ;;
    add)
      if [[ "$seg" =~ (^|[[:space:]])(-A|--all|\.)([[:space:]]|$) ]]; then
        deny "Blocked: 'git add -A/./--all' stages everything (settings.json live-state + strays). Add files BY NAME: 'git add path/to/file ...'. (WattLab VC discipline)"
      fi
      ;;
  esac
done <<< "$analyze"

exit 0
