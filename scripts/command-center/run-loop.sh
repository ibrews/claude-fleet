#!/usr/bin/env bash
# run-loop.sh — always-on Command Center orchestrator loop.
#
# Intended host: a dedicated always-on machine in your fleet — run under launchd
# KeepAlive (com.example.command-center.plist / com.example... in the public
# template) so a crash restarts the loop; this script itself is stateless.
#
# A single bad cycle must NOT kill the loop (no `set -e` around the python
# call) — log the failure and keep going; that's what the ledger is for.
#
# DURABILITY (v2, 2026-07-12): all generated state (ledger, notified.json,
# briefing.json, dashboards, index) lives in a DEDICATED private git repo —
# the STATE_ROOT clone (your-org/command-center-state internally) — which
# this loop pulls before and commits+pushes after every cycle. Nothing is
# local-only: if this machine dies, a fresh clone of the KB (engine+config)
# plus a fresh clone of the state repo fully reinstates the command center.
#
# Guardrail note: this push is NOT the forbidden push_shared_or_main action —
# that red rule is about the shared KB master / project mains. Committing to
# the orchestrator's OWN dedicated state repo was green in the signed-off
# design ("commit to its own state branch"); v2 just makes it real. Bonus:
# a HALT file pushed to the state repo from ANY machine (or github.com)
# stops dispatch on the next cycle — a remote kill switch.
#
# Install (some machines require an interactive session for launchd registration
# on a sandboxed/automated host — see README.md "Install on your always-on host"):
#   cp com.example.command-center.plist ~/Library/LaunchAgents/
#   # edit the placeholder paths first
#   launchctl load ~/Library/LaunchAgents/com.example.command-center.plist

set -uo pipefail

KB_ROOT="${KB_ROOT:-$HOME/knowledge}"
STATE_ROOT="${CC_STATE_ROOT:-$HOME/command-center-state}"
# No project-specific default here on purpose — this script is copied verbatim
# into every fork. A silent fallback would run against the wrong project's
# state or fail confusingly. Require the caller to say which instance.
if [ -z "${CC_INSTANCE:-}" ]; then
  echo "[run-loop] FATAL: CC_INSTANCE is not set — point it at your project's instance.json" >&2
  echo "  e.g. CC_INSTANCE=\$KB_ROOT/projects/<your-project>/command-center/instance.json" >&2
  exit 1
fi
INSTANCE="$CC_INSTANCE"
ENGINE_DIR="$KB_ROOT/departments/engineering/command-center"
SLEEP_SECONDS="${CC_CYCLE_SECONDS:-1800}"   # matches policy.json's cycle_interval_seconds default

echo "[run-loop] starting — instance=$INSTANCE state_root=$STATE_ROOT interval=${SLEEP_SECONDS}s"

sync_state_repo() {  # $1 = pull|push
  [ -d "$STATE_ROOT/.git" ] || { echo "[run-loop] WARNING: $STATE_ROOT is not a git clone — state is NOT being backed up"; return 0; }
  if [ "$1" = "pull" ]; then
    git -C "$STATE_ROOT" pull --rebase --quiet || echo "[run-loop] WARNING: state repo pull failed"
  else
    git -C "$STATE_ROOT" add -A
    if ! git -C "$STATE_ROOT" diff --cached --quiet; then
      git -C "$STATE_ROOT" commit -q -m "cycle: $(date -u +%Y-%m-%dT%H:%M:%SZ) ($(hostname -s))" \
        && git -C "$STATE_ROOT" push --quiet || echo "[run-loop] WARNING: state repo push failed — will retry next cycle"
    fi
  fi
}

while true; do
  # Pull both repos so the cycle reconciles the latest committed reality:
  # KB = other machines' triggers/session-board; state repo = briefing edits,
  # remote HALT, other machines' cycles.
  ( cd "$KB_ROOT" && git pull --rebase --quiet ) || echo "[run-loop] WARNING: KB pull failed, reconciling against local state"
  sync_state_repo pull

  if python3 "$ENGINE_DIR/cycle.py" --instance "$INSTANCE"; then
    :
  else
    echo "[run-loop] WARNING: cycle.py exited non-zero — logged, continuing loop (not fatal)"
  fi

  sync_state_repo push
  sleep "$SLEEP_SECONDS"
done
