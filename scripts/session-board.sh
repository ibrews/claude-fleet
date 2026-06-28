#!/bin/bash
# session-board.sh — lightweight concurrent session coordination
#
# Tracks active Claude Code sessions via the shared KB so multiple machines
# (or multiple terminal windows on one machine) don't step on each other.
#
# Usage:
#   session-board.sh board                              # show all active sessions
#   session-board.sh heartbeat <slug> [-S status] [-w "what you're doing"] [-e "eta"]
#   session-board.sh checkout <slug>                    # mark session done
#
# Board file lives at: ~/knowledge/sessions/board.md
# Each session is one line; stale = no heartbeat for 15+ minutes.

KNOWLEDGE_DIR="${KNOWLEDGE_DIR:-$HOME/knowledge}"
BOARD_FILE="$KNOWLEDGE_DIR/sessions/board.md"
STALE_MINUTES=15
MACHINE_NAME="${FLEET_MACHINE_NAME:-$(hostname -s)}"

mkdir -p "$(dirname "$BOARD_FILE")"
[ -f "$BOARD_FILE" ] || printf "# Session Board\n\n" > "$BOARD_FILE"

now_epoch() { date +%s; }
now_iso()   { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

# Parse a field from a board line (tab-separated: slug|machine|status|doing|eta|last_hb_epoch)
# Format per entry: slug TAB machine TAB status TAB doing TAB eta TAB epoch
read_board() {
  grep -v '^#' "$BOARD_FILE" | grep -v '^$'
}

write_board() {
  local tmp
  tmp=$(mktemp)
  printf "# Session Board\n\n" > "$tmp"
  cat "$KNOWLEDGE_DIR/sessions/.board_entries.tsv" 2>/dev/null >> "$tmp"
  mv "$tmp" "$BOARD_FILE"
}

ENTRIES_FILE="$KNOWLEDGE_DIR/sessions/.board_entries.tsv"
touch "$ENTRIES_FILE"

CMD="$1"
shift

case "$CMD" in
  board)
    echo ""
    printf "%-35s %-12s %-12s %-30s %-10s %s\n" "SESSION" "MACHINE" "STATUS" "DOING" "ETA" "LAST HEARTBEAT"
    printf '%0.s-' {1..110}; echo ""
    NOW=$(now_epoch)
    while IFS=$'\t' read -r slug machine status doing eta hb_epoch; do
      age=$(( (NOW - hb_epoch) / 60 ))
      hb_str="${age}m ago"
      stale_flag=""
      if [ "$age" -gt "$STALE_MINUTES" ]; then
        stale_flag=" ⚠ STALE"
      fi
      printf "%-35s %-12s %-12s %-30s %-10s %s\n" \
        "$slug" "$machine" "$status" "${doing:0:28}" "${eta:--}" "${hb_str}${stale_flag}"
    done < "$ENTRIES_FILE"
    echo ""
    ;;

  heartbeat)
    SLUG="$1"; shift
    STATUS="active"
    DOING=""
    ETA="-"
    while [ $# -gt 0 ]; do
      case "$1" in
        -S) STATUS="$2"; shift 2 ;;
        -w) DOING="$2"; shift 2 ;;
        -e) ETA="$2"; shift 2 ;;
        *)  shift ;;
      esac
    done
    # Remove old entry for this slug, add updated one
    grep -v "^${SLUG}	" "$ENTRIES_FILE" > "$ENTRIES_FILE.tmp" 2>/dev/null || true
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$SLUG" "$MACHINE_NAME" "$STATUS" "$DOING" "$ETA" "$(now_epoch)" \
      >> "$ENTRIES_FILE.tmp"
    mv "$ENTRIES_FILE.tmp" "$ENTRIES_FILE"
    echo "Heartbeat: $SLUG [$STATUS] — $DOING"
    # Commit to KB so other machines can see it
    cd "$KNOWLEDGE_DIR" && \
      git add sessions/ --quiet && \
      git commit -m "chore(board): heartbeat $SLUG" --quiet && \
      git push --quiet &
    ;;

  checkout)
    SLUG="${1:-$MACHINE_NAME}"
    grep -v "^${SLUG}	" "$ENTRIES_FILE" > "$ENTRIES_FILE.tmp" 2>/dev/null || true
    mv "$ENTRIES_FILE.tmp" "$ENTRIES_FILE"
    echo "Checked out: $SLUG"
    cd "$KNOWLEDGE_DIR" && \
      git add sessions/ --quiet && \
      git commit -m "chore(board): checkout $SLUG" --quiet && \
      git push --quiet
    ;;

  *)
    echo "Usage: session-board.sh board | heartbeat <slug> [-S status] [-w 'doing'] [-e 'eta'] | checkout [slug]"
    exit 1
    ;;
esac
