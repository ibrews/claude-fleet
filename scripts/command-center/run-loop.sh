#!/usr/bin/env bash
# run-loop.sh — always-on Command Center orchestrator loop.
#
# Intended host: a dedicated always-on machine in your fleet — run under launchd
# KeepAlive (com.example.command-center.plist) so a crash restarts the loop; all
# working state lives in committed files (state_dir/ledger per instance),
# so a restart rehydrates cleanly — this script itself is stateless.
#
# A single bad cycle must NOT kill the loop (no `set -e` around the python
# call) — log the failure and keep going; that's what the ledger is for.
#
# Generated state (ledger, notified.json, dashboard/index.html, HALT) is
# LOCAL to the machine running the loop — deliberately untracked (see
# .gitignore entries), NOT committed or pushed. Auto-pushing to the KB's
# shared master every cycle would itself be the push_shared_or_main RED
# action policy.json forbids the orchestrator from taking autonomously —
# an early draft of this script did exactly that and was caught and fixed
# before install. Local files + launchd KeepAlive is sufficient for
# restart durability; publishing the dashboard is a separate, deliberate
# step once you've set up hosting for it (note: GitHub Pages requires a paid
# plan for private repos — a public repo, or Cloudflare Pages/Workers, are
# common alternatives if you want it private and free).
#
# Install (some machines require an interactive session for launchd registration
# on a sandboxed/automated host — see README.md "Install on your always-on host"):
#   cp com.example.command-center.plist ~/Library/LaunchAgents/
#   # edit __KB_ROOT__ / __INSTANCE__ placeholders first
#   launchctl load ~/Library/LaunchAgents/com.example.command-center.plist

set -uo pipefail

KB_ROOT="${KB_ROOT:-$HOME/knowledge}"
# No project-specific default here on purpose — this script is copied verbatim
# into every fork (see README.md "Forking for a new project"). A silent
# fallback to your project's instance.json would either run against the wrong
# project's state or fail confusingly on a fork that doesn't have it. Require
# the caller (the launchd plist, or you) to say which instance explicitly.
if [ -z "${CC_INSTANCE:-}" ]; then
  echo "[run-loop] FATAL: CC_INSTANCE is not set — point it at your project's instance.json" >&2
  echo "  e.g. CC_INSTANCE=\$KB_ROOT/projects/<your-project>/command-center/instance.json" >&2
  exit 1
fi
INSTANCE="$CC_INSTANCE"
ENGINE_DIR="$KB_ROOT/departments/engineering/command-center"
SLEEP_SECONDS="${CC_CYCLE_SECONDS:-1800}"   # matches policy.json's cycle_interval_seconds default

echo "[run-loop] starting — instance=$INSTANCE interval=${SLEEP_SECONDS}s"

while true; do
  # Pull first so the loop always reconciles against the latest committed
  # state (other machines' triggers, session-board updates, HALT files).
  ( cd "$KB_ROOT" && git pull --rebase --quiet ) || echo "[run-loop] WARNING: git pull failed, reconciling against local state"

  if python3 "$ENGINE_DIR/cycle.py" --instance "$INSTANCE"; then
    :
  else
    echo "[run-loop] WARNING: cycle.py exited non-zero — logged, continuing loop (not fatal)"
  fi

  sleep "$SLEEP_SECONDS"
done
