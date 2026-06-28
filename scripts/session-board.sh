#!/usr/bin/env bash
# session-board.sh — a presence board for concurrent Claude Code sessions.
#
# WHY this exists: when many autonomous sessions run across the fleet, they
# CANNOT talk to each other at runtime — send_message and
# search_session_transcripts are harness-blocked in unsupervised/auto/loop mode
# regardless of user approval (see
# https://github.com/ibrews/claude-fleet/blob/main/docs/14-concurrent-sessions.md).
# The only reliable cross-session channel is committed files. This board answers
# the live question "who is doing what right now, and which singletons are they
# holding?" (e.g. "who is compiling Unreal and why?") with zero live messaging.
#
# WHY a folder of one-file-per-session (not one shared ACTIVE-SESSIONS.md): each
# session writes ONLY its own file, so two sessions never edit the same file and
# git never hits a merge/index race. Reading the board is just `ls` + cat.
#
# This is a VISIBILITY layer for the singletons you can't duplicate (one build
# engine, one device, one sim, one shared config toggle). It does NOT prevent
# collisions on source — that's worktree isolation, the real fix. See
# sessions/README.md.

set -euo pipefail

KB="${KB_ROOT:-$HOME/knowledge}"
DIR="$KB/sessions/active"
STALE_MIN="${SESSION_STALE_MIN:-15}"
MACHINE="${FLEET_MACHINE:-$(hostname -s 2>/dev/null || echo unknown)}"

mkdir -p "$DIR"

now_epoch() { date -u +%s; }
now_iso()   { date -u +%Y-%m-%dT%H:%M:%SZ; }

# Read a single-line "key: value" frontmatter field from a file (empty if absent).
getfield() { sed -n "s/^$2: //p" "$1" 2>/dev/null | head -1 || true; }

slug_file() { echo "$DIR/${MACHINE}-${1}.md"; }

# The DURABLE Claude runtime PID for this session. WHY: $PPID is the ephemeral
# shell-snapshot subshell that runs this script — it dies within seconds, so the
# old `pid: $PPID` made the board's pid field useless for liveness (every recorded
# pid was already dead — see the 2026-06-23 load-collapse incident). Walk up the
# process tree to the real `claude` agent runtime (desktop: `MacOS/claude
# --output-format …`; headless: `claude -p` / `--print`). Falls back to $PPID.
# See https://github.com/ibrews/claude-fleet/blob/main/docs/14-concurrent-sessions.md
durable_pid() {
  local p="$$" cmd
  while [ "${p:-0}" -gt 1 ]; do
    cmd="$(ps -p "$p" -o command= 2>/dev/null || true)"
    case "$cmd" in
      *claude*--output-format*|*claude\ -p*|*claude*--print*) echo "$p"; return;;
    esac
    p="$(ps -p "$p" -o ppid= 2>/dev/null | tr -d ' ')"; [ -n "$p" ] || break
  done
  echo "${SESSION_BOARD_PID:-$PPID}"
}

# Harness sessionId for a runtime pid (from ~/.claude/sessions/<pid>.json), if present.
# This is the liveness key that actually survives — cross-check with list_sessions.
session_id_for() {
  local j="$HOME/.claude/sessions/${1}.json"
  [ -f "$j" ] || { echo ""; return; }
  python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('sessionId',''))" "$j" 2>/dev/null || true
}

usage() {
  cat <<'EOF'
session-board.sh — presence board for concurrent sessions

  checkin   <slug> [-s software] [-r repo] [-b branch] [-c claim] [-f files] [-e eta] [-S status] [-w doing]
  heartbeat <slug> [-S status] [-e eta] [-w doing]     # bump heartbeat — call at each checkpoint / periodically
  claim     <slug> "<resource...>"                     # set the singletons you hold (build engine, device, sim)
  checkout  <slug>                                      # remove your entry when done
  board                                                # show all active sessions + staleness

slug = a short stable handle THIS session picks, e.g. 'ue-build' or 'accvr-deploy'.
Pass the SAME slug to heartbeat/claim/checkout.  File: sessions/active/<machine>-<slug>.md

Fields:
  -s software   what you're running        (e.g. "Unreal 5.6 / UnrealEngineVisionOS")
  -r repo       repo path                   (e.g. ~/git/UnrealRealityKitBridge)
  -b branch     git branch / worktree
  -c claim      SINGLETONS you hold — the load-bearing field (e.g. "ue-build-engine, AVP-device")
  -f files      key files/folders you're touching
  -e eta        when you expect to release  (e.g. "~00:40, build running")
  -S status     active | building | blocked | verifying | done
  -w doing      one-line "what I'm doing right now"

Env: FLEET_MACHINE (default hostname), KB_ROOT (default ~/knowledge), SESSION_STALE_MIN (default 15),
     SESSION_PRUNE_HOURS (default 4 — dead-process entries older than this are auto-removed on board).
EOF
}

cmd="${1:-board}"; shift || true

case "$cmd" in
  checkin)
    slug="${1:?slug required}"; shift
    software="" ; repo="" ; branch="" ; claim="" ; files="" ; eta="" ; status="active" ; doing=""
    while getopts "s:r:b:c:f:e:S:w:" o; do case "$o" in
      s) software="$OPTARG";; r) repo="$OPTARG";; b) branch="$OPTARG";; c) claim="$OPTARG";;
      f) files="$OPTARG";; e) eta="$OPTARG";; S) status="$OPTARG";; w) doing="$OPTARG";;
    esac; done
    f="$(slug_file "$slug")"; ts="$(now_iso)"; ep="$(now_epoch)"
    rt_pid="$(durable_pid)"; sess_id="$(session_id_for "$rt_pid")"
    cat > "$f" <<EOF
---
machine: $MACHINE
slug: $slug
pid: $rt_pid
session_id: $sess_id
software: $software
repo: $repo
branch: $branch
claim: $claim
files: $files
status: $status
eta: $eta
doing: $doing
started: $ts
started_epoch: $ep
heartbeat: $ts
heartbeat_epoch: $ep
---

## Notes to sibling sessions  (FACTS only — mark anything unverified as HYPOTHESIS)

- (e.g. FACT: KickoffEngineHeadless() restored at commit c157b0e)
- (e.g. HYPOTHESIS, unverified: plain Xcode.app links fine — verify before trusting)
EOF
    echo "checked in → $f"
    ;;

  heartbeat)
    slug="${1:?slug required}"; shift
    f="$(slug_file "$slug")"
    [ -f "$f" ] || { echo "no entry for '$slug' on $MACHINE — run checkin first" >&2; exit 1; }
    status="$(getfield "$f" status)"; eta="$(getfield "$f" eta)"; doing="$(getfield "$f" doing)"
    while getopts "S:e:w:" o; do case "$o" in
      S) status="$OPTARG";; e) eta="$OPTARG";; w) doing="$OPTARG";;
    esac; done
    ts="$(now_iso)"; ep="$(now_epoch)"
    # Single-pass rewrite of the volatile fields (portable: no in-place sed -i flag differences).
    awk -v ts="$ts" -v ep="$ep" -v st="$status" -v eta="$eta" -v doing="$doing" '
      /^heartbeat: /        {print "heartbeat: " ts; next}
      /^heartbeat_epoch: /  {print "heartbeat_epoch: " ep; next}
      /^status: /           {print "status: " st; next}
      /^eta: /              {print "eta: " eta; next}
      /^doing: /            {print "doing: " doing; next}
      {print}
    ' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    echo "heartbeat → $slug ($status)"
    ;;

  claim)
    slug="${1:?slug required}"; shift
    f="$(slug_file "$slug")"
    [ -f "$f" ] || { echo "no entry for '$slug' on $MACHINE — run checkin first" >&2; exit 1; }
    res="$*"
    awk -v c="$res" '/^claim: /{print "claim: " c; next} {print}' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    echo "claim($slug) = $res"
    ;;

  checkout)
    slug="${1:?slug required}"; shift || true
    f="$(slug_file "$slug")"
    rm -f "$f" && echo "checked out → ${MACHINE}-${slug}"
    ;;

  board)
    shopt -s nullglob
    files=("$DIR"/*.md)
    now="$(now_epoch)"; stale_s=$(( STALE_MIN * 60 ))
    # Auto-prune: remove entries where the process is confirmed dead AND the
    # heartbeat is older than SESSION_PRUNE_HOURS (default 4h). This keeps the
    # board — and the SessionStart hook output — clean without losing entries
    # for sessions that are merely busy and not heartbeating (e.g. a long build).
    prune_s=$(( ${SESSION_PRUNE_HOURS:-4} * 3600 ))
    for f in "${files[@]}"; do
      hb_e="$(getfield "$f" heartbeat_epoch)"; pidf="$(getfield "$f" pid)"
      age=$(( now - ${hb_e:-0} ))
      if [ "$age" -gt "$prune_s" ] && [ -n "$pidf" ] && ! ps -p "$pidf" >/dev/null 2>&1; then
        rm -f "$f"
      fi
    done
    files=("$DIR"/*.md)   # re-read after pruning
    n=${#files[@]}
    echo "ACTIVE SESSIONS — $n entr$([ "$n" = 1 ] && echo y || echo ies)  (stale > ${STALE_MIN}m)"
    echo
    [ "$n" = 0 ] && { echo "  (none checked in)"; exit 0; }
    for f in "${files[@]}"; do
      m="$(getfield "$f" machine)"; sl="$(getfield "$f" slug)"; sw="$(getfield "$f" software)"
      rp="$(getfield "$f" repo)"; br="$(getfield "$f" branch)"; cl="$(getfield "$f" claim)"
      st="$(getfield "$f" status)"; eta="$(getfield "$f" eta)"; doing="$(getfield "$f" doing)"
      hb="$(getfield "$f" heartbeat_epoch)"; age=$(( now - ${hb:-0} )); mins=$(( age / 60 ))
      pidf="$(getfield "$f" pid)"
      mark="●"; tail=""
      if [ "${hb:-0}" -gt 0 ] && [ "$age" -gt "$stale_s" ]; then mark="⚠"; tail="  STALE"; fi
      if [ -n "$pidf" ] && ! ps -p "$pidf" >/dev/null 2>&1; then mark="⚠"; tail="$tail  ✗proc-gone"; fi
      printf "%s %-22s %-10s claim: %-28s eta: %-14s hb: %sm ago%s\n" \
        "$mark" "$m/$sl" "${st:--}" "${cl:--}" "${eta:--}" "$mins" "$tail"
      printf "    %s · %s%s\n" "${sw:-?}" "${rp:-?}" "${br:+ @ $br}"
      [ -n "$doing" ] && printf "    doing: %s\n" "$doing"
      if [ "$mark" = "⚠" ]; then
        printf "    ↳ stale — cross-check liveness before assuming its claim is free:  list_sessions  |  ps aux | grep claude\n"
      fi
      echo
    done
    echo "Reminder: STALE = quiet >${STALE_MIN}m (crashed, or just busy). A held claim (build engine, device)"
    echo "is only safe to take over after list_sessions/ps confirm the owner is actually gone."
    ;;

  -h|--help|help) usage ;;
  *) echo "unknown command: $cmd" >&2; usage; exit 1 ;;
esac
