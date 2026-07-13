#!/bin/bash
# command-center-freshness-lib.sh — shared logic for command-center-freshness-check.sh
# (SubagentStop hook). Mirrors the git-freshness-lib.sh split: small, testable
# functions sourced by the hook script, not executed directly.
#
# Synced to the fleet via ~/knowledge/departments/engineering/hooks/ (same
# mechanism as git-freshness-*.sh) — see that directory's install-fleet-hooks.sh.
# Registering the SubagentStop hook in a machine's live settings.json is a
# separate, deliberate step (see command-center-freshness-check.sh header) —
# this lib file alone does nothing until sourced by that script.

# cc_extract_trigger_paths <text>
# Prints one `triggers/<slug>.md`-shaped path per line, deduped, found
# anywhere in <text> (a subagent's last_assistant_message or transcript dump).
# Matches both bare `triggers/foo.md` and `.../triggers/foo.md` references so
# it survives being embedded in a longer repo-relative or absolute path.
cc_extract_trigger_paths() {
  local text="$1"
  printf '%s' "$text" \
    | grep -oE '(^|[[:space:]/`"'"'"'(])triggers/[A-Za-z0-9._-]+\.md' \
    | sed -E 's#^.*(triggers/)#\1#' \
    | sort -u
}

# cc_resolve_kb_root <start-dir>
# Walks up from <start-dir> looking for a directory that has a `triggers/`
# subdirectory (the KB root, or a worktree of it). Falls back to ~/knowledge
# if nothing is found on the way up (matches this fleet's canonical KB path
# per ~/knowledge/CLAUDE.md: "Always use that path").
cc_resolve_kb_root() {
  local dir="$1"
  [ -d "$dir" ] || dir="$(dirname "$dir")"
  while [ "$dir" != "/" ] && [ -n "$dir" ]; do
    if [ -d "$dir/triggers" ]; then
      printf '%s' "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  printf '%s' "$HOME/knowledge"
}

# cc_trigger_git_state <abs-path-to-trigger-md>
# Prints one of: "missing" | "untracked" | "uncommitted" | "not_pushed" | "clean"
# "not_pushed" compares the file's latest local commit against the upstream
# branch tip for that path — same left/right-count idea as git-freshness-lib's
# ahead/behind check, but scoped to a single file rather than the whole repo.
cc_trigger_git_state() {
  local path="$1"
  [ -f "$path" ] || { echo "missing"; return; }

  local repo
  repo="$(git -C "$(dirname "$path")" rev-parse --show-toplevel 2>/dev/null)"
  [ -z "$repo" ] && { echo "missing"; return; }  # not even a git repo — can't judge freshness

  local rel
  rel="$(git -C "$repo" ls-files --full-name "$path" 2>/dev/null | head -1)"
  if [ -z "$rel" ]; then
    echo "untracked"
    return
  fi

  if ! git -C "$repo" diff --quiet -- "$rel" 2>/dev/null || \
     ! git -C "$repo" diff --cached --quiet -- "$rel" 2>/dev/null; then
    echo "uncommitted"
    return
  fi

  local upstream
  upstream="$(git -C "$repo" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"
  if [ -z "$upstream" ]; then
    echo "clean"   # no upstream configured — can't check pushed-ness, don't guess
    return
  fi

  local local_sha upstream_sha
  local_sha="$(git -C "$repo" log -1 --format=%H -- "$rel" 2>/dev/null)"
  upstream_sha="$(git -C "$repo" log -1 --format=%H "$upstream" -- "$rel" 2>/dev/null)"
  if [ -n "$local_sha" ] && [ "$local_sha" != "$upstream_sha" ]; then
    # Local history for this path has a commit the upstream copy doesn't.
    if ! git -C "$repo" merge-base --is-ancestor "$local_sha" "$upstream" 2>/dev/null; then
      echo "not_pushed"
      return
    fi
  fi
  echo "clean"
}

# cc_trigger_status_field <abs-path>
# Prints the frontmatter `status:` value (bare, no comment), or empty.
cc_trigger_status_field() {
  local path="$1"
  [ -f "$path" ] || return
  awk -F': *' '/^---$/{n++; next} n==1 && /^status:/{print $2; exit}' "$path" \
    | sed -E 's/[[:space:]]*(#.*)?$//'
}

# cc_result_section_state <abs-path>
# Prints "missing" | "placeholder" | "real" for the `## Result` section.
# "placeholder" = empty, or only HTML-comment / angle-bracket / "_Pending_"
# stand-ins (the patterns actually used across this KB's trigger templates —
# see triggers/README.md and the inbox-action-trigger-template.md).
cc_result_section_state() {
  local path="$1"
  [ -f "$path" ] || { echo "missing"; return; }

  local body
  body="$(awk '/^## Result/{f=1; next} /^## /{if (f) exit} f' "$path")"
  # Strip HTML comments and blank lines to see if any real prose is left.
  local stripped
  stripped="$(printf '%s' "$body" | sed -E 's/<!--.*-->//g' | sed -E '/^[[:space:]]*$/d')"

  if [ -z "$(printf '%s' "$body" | tr -d '[:space:]')" ]; then
    echo "missing"
    return
  fi
  if [ -z "$stripped" ]; then
    echo "placeholder"
    return
  fi
  # Whole-line placeholder markers even when not HTML comments, e.g. "_Pending_"
  # or a single "<fill in when done>" / "<Filled in ...>" line with no other text.
  local non_placeholder_lines
  non_placeholder_lines="$(printf '%s\n' "$stripped" | grep -Ev '^[[:space:]]*(_Pending_|<[^>]*>)[[:space:]]*$')"
  if [ -z "$(printf '%s' "$non_placeholder_lines" | tr -d '[:space:]')" ]; then
    echo "placeholder"
    return
  fi
  echo "real"
}
