#!/usr/bin/env bash
# worktree-reaper.sh — remove worktree DIRECTORIES whose branch is provably safe elsewhere,
# and report branches that never made it back to main. Dry-run by default, deterministic,
# no AI call. Reference implementation of the pattern in docs/19-resource-reaper-pattern.md.
#
# HARD RULES — read these before changing the logic, they exist because a naive version of
# this script gets someone's in-progress work deleted:
#   1. NEVER delete a branch. Directories only. "Pushed to origin" answers "can I delete this
#      directory", it does NOT answer "should this work be merged" — that needs a human.
#      Deleting the branch destroys the evidence that the question was ever open.
#   2. Compare tips against `git ls-remote`, NOT the local `origin/<branch>` ref. A stale
#      local ref can make an already-pushed branch look local-only, or vice versa.
#   3. Check whether local main is AHEAD of origin/main before trusting "merged into main" —
#      if it is, that merge only exists on this disk and the safety claim is void.
#   4. Always report the unmerged backlog, even when nothing was reaped. A backlog that isn't
#      surfaced regrows silently.
#   5. NEVER reap a worktree a live process is sitting in. Git safety ("is this branch safe
#      to lose") is a different question from "is anyone using this directory right now" —
#      a merged-and-clean worktree can still be someone's active read-only workspace.
#      "Clean and merged" and "freshly created, zero commits yet" look IDENTICAL from a
#      filesystem snapshot — recency alone is not proof a resource is dead. Cross-check a
#      live-process signal (below) before ever concluding "idle."
#      NEVER use `rm -rf` here — `git worktree remove` refuses on a dirty tree; `rm -rf` has
#      no such refusal and no undo.

# One lsof call gets every live process's cwd; a worktree containing any of them is in use.
live_cwds=$(lsof -d cwd -Fn 2>/dev/null | grep '^n/' | sed 's/^n//' | sort -u)
in_use() {  # in_use <path> -> 0 if some process cwd is at or below <path>
  [ -z "$live_cwds" ] && return 1
  printf '%s\n' "$live_cwds" | grep -qF -e "$1" && return 0
  printf '%s\n' "$live_cwds" | awk -v p="$1/" 'index($0,p)==1{f=1} END{exit !f}'
}

set -uo pipefail

KB="${KB_ROOT:-$HOME/knowledge}"
REPOS_FILE="${WORKTREE_REAPER_REPOS:-$KB/state/worktree-reaper-repos.txt}"
REPORT_DIR="$KB/intelligence/worktree-reaper-reports"
DRY_RUN="${DRY_RUN:-1}"
mkdir -p "$REPORT_DIR" "$(dirname "$REPOS_FILE")"
REPORT="$REPORT_DIR/$(date +%Y-%m-%d).md"

{
  echo "# Worktree reaper — $(date '+%Y-%m-%d %H:%M')"
  echo
  [ "$DRY_RUN" = "1" ] && echo "**DRY RUN** — nothing removed."
  echo
} > "$REPORT"

if [ ! -f "$REPOS_FILE" ]; then
  echo "no repo list at $REPOS_FILE — one repo path per line, # comments allowed. Nothing to do." | tee -a "$REPORT"
  exit 0
fi

while read -r repo; do
  [ -z "$repo" ] && continue
  case "$repo" in \#*) continue;; esac
  [ -d "$repo/.git" ] || continue

  git -C "$repo" fetch origin --quiet 2>/dev/null
  main=$(git -C "$repo" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
  main="${main:-main}"

  echo "## $(basename "$repo")" >> "$REPORT"

  # RULE 3: local main ahead of origin/main voids every "merged into main" claim.
  ahead_main=$(git -C "$repo" rev-list --count "origin/$main..$main" 2>/dev/null || echo 0)
  if [ "${ahead_main:-0}" != "0" ]; then
    echo "- SKIPPED: local \`$main\` is $ahead_main commit(s) ahead of origin/$main." >> "$REPORT"
    echo "  Work 'merged to main' exists only on this disk. Push $main, then re-run." >> "$REPORT"
    echo >> "$REPORT"
    continue
  fi

  # Reap directories whose branch is safe elsewhere. Handles both a checked-out branch and
  # a detached HEAD pointing at a same-named local branch (some tooling checks worktrees
  # out detached even when a matching branch exists at the same commit).
  git -C "$repo" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree /{p=$2} /^HEAD /{h=$2} /^branch /{gsub("refs/heads/","",$2); print p"\t"$2} /^detached/{print p"\tDETACHED:"h}' \
    | while IFS=$'\t' read -r wpath br; do
        [ "$wpath" = "$repo" ] && continue          # never the main worktree
        [ -d "$wpath" ] || continue

        case "$br" in
          DETACHED:*)
            hsha="${br#DETACHED:}"
            resolved=$(git -C "$repo" for-each-ref --points-at="$hsha" --format='%(refname:short)' refs/heads/ 2>/dev/null | head -1)
            br="${resolved:-$hsha}"
            ;;
        esac

        lsha=$(git -C "$repo" rev-parse "$br" 2>/dev/null)
        rsha=$(git -C "$repo" ls-remote origin "refs/heads/$br" 2>/dev/null | cut -f1)   # RULE 2
        n_ahead=$(git -C "$repo" rev-list --count "$main..$br" 2>/dev/null || echo 0)

        safe=0; why=""
        if [ "${n_ahead:-0}" = "0" ]; then
          safe=1; why="fully merged into $main"
        elif [ -n "$rsha" ] && [ "$lsha" = "$rsha" ]; then
          safe=1; why="tip identical on origin ($n_ahead ahead of $main)"
        elif [ -z "$rsha" ] && [ "$(git -C "$repo" cherry "$main" "$br" 2>/dev/null | grep -c '^+')" = "0" ]; then
          safe=1; why="squash-merged (patch-id present in $main)"
        fi

        # RULE 5: a live process sitting here blocks reaping, no matter how safe git says it is.
        if in_use "$wpath"; then
          echo "- KEPT \`$(basename "$wpath")\` — a live process has its cwd here (in use)." >> "$REPORT"
          continue
        fi

        # Uncommitted TRACKED changes block reaping. Ignored build output does not.
        dirty=$(git -C "$wpath" status --porcelain --untracked-files=no 2>/dev/null | wc -l | tr -d ' ')
        if [ "$dirty" != "0" ]; then
          echo "- KEPT \`$(basename "$wpath")\` — $dirty uncommitted tracked change(s). Commit them first." >> "$REPORT"
          continue
        fi

        if [ "$safe" = "1" ]; then
          if [ "$DRY_RUN" = "1" ]; then
            echo "- would reap \`$(basename "$wpath")\` — $why" >> "$REPORT"
          else
            if git -C "$repo" worktree remove --force "$wpath" 2>/dev/null; then
              echo "- reaped \`$(basename "$wpath")\` — $why (branch \`$br\` KEPT)" >> "$REPORT"
            else
              echo "- FAILED to reap \`$(basename "$wpath")\`" >> "$REPORT"
            fi
          fi
        else
          echo "- KEPT \`$(basename "$wpath")\` — branch \`$br\` has $n_ahead commit(s) not on origin and not in $main. Push or merge it." >> "$REPORT"
        fi
      done

  [ "$DRY_RUN" = "1" ] || git -C "$repo" worktree prune

  # RULE 4: always surface the unmerged backlog, even when nothing was reaped.
  nb=0
  for b in $(git -C "$repo" for-each-ref --format='%(refname:short)' refs/heads/ | grep -v "^$main$"); do
    n=$(git -C "$repo" rev-list --count "$main..$b" 2>/dev/null || echo 0)
    [ "${n:-0}" != "0" ] && nb=$((nb+1))
  done
  main_age=$(( ( $(date +%s) - $(git -C "$repo" log -1 --format=%ct "$main" 2>/dev/null || date +%s) ) / 86400 ))
  echo "- $nb branch(es) carry commits not in \`$main\`; \`$main\` last advanced ${main_age}d ago." >> "$REPORT"
  if [ "$nb" -ge 10 ] || [ "$main_age" -ge 7 ]; then
    echo "  **INTEGRATION STALL** — ask why these aren't merged, don't just tidy around them." >> "$REPORT"
  fi
  echo >> "$REPORT"
done < "$REPOS_FILE"

echo "report: $REPORT"
