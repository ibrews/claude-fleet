#!/usr/bin/env bash
# master-loop.sh — the always-on Command Center MASTER session (SECONDARY surface).
#
# The PRIMARY surface is the Claude Desktop MCP connector; this is the mobile
# two-way channel (the operator's Telegram replies, routed via #sid=cc-master, reach a
# live session here). It is OPTIONAL: even without it, the loop still pings the operator
# on Telegram and his replies fall through to whatever session is attached, and
# the Desktop MCP works regardless.
#
# Model: Opus (per the operator — the master reasons; it is idle/zero-token until a
# message arrives). Runs under launchd KeepAlive on Alpha so a crash restarts it.
#
# ⚠️ VERIFY-ON-DEPLOY: whether a headless `claude` session keeps a persistent
# Monitor bus-listener alive across turns needs empirical confirmation on Alpha
# with a throwaway BEFORE trusting this unattended (the fleet-session-bus recipe
# is verified in interactive/agent sessions; headless-always-on is the new bit).
# If it doesn't hold, the Telegram fall-through + Desktop MCP still cover the operator —
# this session is the nicety, not the load-bearing path.
set -uo pipefail

KB_ROOT="${KB_ROOT:-$HOME/knowledge}"
INSTANCE="${CC_MASTER_INSTANCE:-your-project}"
ENGINE_DIR="$KB_ROOT/departments/engineering/command-center"
FLEET_BUS="$KB_ROOT/departments/engineering/fleet-tools/fleet_bus.py"
MODEL="${CC_MASTER_MODEL:-opus}"

# Render the charter with the concrete instance name.
PROMPT="$(sed "s/{INSTANCE}/$INSTANCE/g" "$ENGINE_DIR/master/system-prompt.md")"

echo "[cc-master] starting for instance=$INSTANCE model=$MODEL"

# The initial turn tells the session to arm its bus listener as cc-master and
# stay reachable. The Monitor tool (command mode, long-poll) keeps it alive and
# idle-cheap; each incoming message wakes one turn. If the session ever exits,
# launchd KeepAlive restarts this script (and the listener re-arms).
exec claude \
  --model "$MODEL" \
  --append-system-prompt "$PROMPT" \
  --permission-mode acceptEdits \
  -p "Arm your fleet-bus listener as session cc-master and stay reachable per your charter: \
Monitor (command mode) running \`python3 $FLEET_BUS listen --session cc-master --title 'CC master ($INSTANCE)'\`, \
persistent, long timeout. When a message arrives, handle it per your charter, then keep listening. \
Do nothing else until a message arrives."
