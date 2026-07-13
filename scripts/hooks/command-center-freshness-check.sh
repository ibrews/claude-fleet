#!/bin/bash
# SubagentStop hook: warn the orchestrator when a subagent's output mentions a
# triggers/*.md file that looks stale — uncommitted, committed-but-not-pushed,
# or claiming completion with an empty/placeholder `## Result` section.
#
# Built because the command center only stayed current through the
# orchestrator manually writing ledger rows + pushing trigger updates after
# every subagent finished — pure habit, not enforcement (same problem
# git-freshness-check.sh solved for git state: "a rule alone wasn't reliable
# enough", ~/.claude/CLAUDE.md § Git Freshness). This hook mirrors that
# pattern exactly:
#   - non-blocking (WARN via additionalContext, never "decision":"block")
#   - silent + zero-token in the common case (nothing mentioned, or mentioned
#     and actually fresh) — only speaks up when something looks off
#   - does NOT decide anything or auto-write ledger rows/trigger status. It
#     only nags the orchestrator to go look. (This session already got
#     auto-deciding wrong once: 8 triggers were falsely read as "abandoned" by
#     a different sweep script's naive heuristic — see the trigger's
#     prior_art note. This hook is deliberately dumber than that.)
#
# Input: SubagentStop's real payload (confirmed live via
# ~/.ccgram/logs/hook-diag.log on this machine, 2026-07-13) has keys:
#   session_id, transcript_path, cwd, prompt_id, permission_mode, agent_id,
#   agent_type, effort, hook_event_name, stop_hook_active,
#   agent_transcript_path, last_assistant_message, background_tasks,
#   session_crons
# We only need `last_assistant_message` (primary text to scan) with
# `agent_transcript_path`/`transcript_path` as a fallback if the subagent
# ended without one, plus `cwd` to resolve the KB root.
#
# Synced to the fleet via ~/knowledge/departments/engineering/hooks/ (same
# mechanism as git-freshness-*.sh — see install-fleet-hooks.sh).
# REGISTERING THIS HOOK in a machine's ~/.claude/settings.json is a separate,
# deliberate step (per this repo's own stated convention for hook rollout —
# see departments/engineering/command-center/README.md "Prior-art gate"
# section for the identical carve-out on a different hook). Writing this file
# to departments/engineering/hooks/ does not, by itself, turn it on anywhere.

set -u
source "$(dirname "${BASH_SOURCE[0]}")/command-center-freshness-lib.sh"

input="$(cat)"

get_field() {
  printf '%s' "$input" | jq -r ".$1 // empty" 2>/dev/null
}

text="$(get_field last_assistant_message)"
cwd="$(get_field cwd)"
[ -z "$cwd" ] && cwd="$(pwd)"

if [ -z "$text" ]; then
  # Fall back to the transcript file when the harness didn't populate
  # last_assistant_message (older Claude Code versions per enhanced-hook-notify.js's
  # own fallback chain). Best-effort text scrape — tail keeps this cheap even
  # on a long transcript; trigger mentions are almost always in the final turn.
  transcript="$(get_field agent_transcript_path)"
  [ -z "$transcript" ] && transcript="$(get_field transcript_path)"
  if [ -n "$transcript" ] && [ -f "$transcript" ]; then
    text="$(tail -c 200000 "$transcript" 2>/dev/null)"
  fi
fi

[ -z "$text" ] && exit 0   # nothing to scan — silent, matches "zero token cost in the common case"

trigger_rels="$(cc_extract_trigger_paths "$text")"
[ -z "$trigger_rels" ] && exit 0   # subagent never mentioned a trigger file — silent

kb_root="$(cc_resolve_kb_root "$cwd")"

warnings=()
while IFS= read -r rel; do
  [ -z "$rel" ] && continue
  abs="$kb_root/$rel"

  state="$(cc_trigger_git_state "$abs")"
  case "$state" in
    missing)
      warnings+=("$rel: mentioned by the subagent but no file found at $abs (check the path/kb_root)")
      continue
      ;;
    untracked)
      warnings+=("$rel: exists but is untracked in git — never committed")
      ;;
    uncommitted)
      warnings+=("$rel: has uncommitted local changes")
      ;;
    not_pushed)
      warnings+=("$rel: committed locally but not pushed to origin")
      ;;
  esac

  status_field="$(cc_trigger_status_field "$abs")"
  result_state="$(cc_result_section_state "$abs")"
  if [ "$status_field" = "completed" ] && [ "$result_state" != "real" ]; then
    warnings+=("$rel: status: completed but its ## Result section is $result_state — fill it in")
  fi
done <<< "$trigger_rels"

if [ "${#warnings[@]}" -gt 0 ]; then
  msg="command-center-freshness-check: subagent mentioned trigger file(s) that look stale — ${warnings[*]}"
  esc=$(printf '%s' "$msg" | tr '"' "'" | tr '\n' ' ')
  printf '{"hookSpecificOutput":{"hookEventName":"SubagentStop","additionalContext":"%s"}}\n' "$esc"
fi

exit 0
