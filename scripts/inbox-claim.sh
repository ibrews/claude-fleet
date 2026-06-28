#!/bin/bash
# inbox-claim.sh — claim or release an inbox trigger file
#
# Usage:
#   inbox-claim.sh triggers/my-task.md          # claim (mark in_progress)
#   inbox-claim.sh triggers/my-task.md done     # release (mark completed)
#
# Requires: the KB to be at ~/knowledge (or adjust KNOWLEDGE_DIR below).
# The script edits YAML frontmatter fields using Python (no yq required).

KNOWLEDGE_DIR="${KNOWLEDGE_DIR:-$HOME/knowledge}"
TRIGGER_FILE="$1"
ACTION="${2:-claim}"

if [ -z "$TRIGGER_FILE" ]; then
  echo "Usage: inbox-claim.sh <trigger-file> [done]" >&2
  exit 1
fi

# Resolve path — accept absolute or relative-to-KB
if [ ! -f "$TRIGGER_FILE" ]; then
  TRIGGER_FILE="$KNOWLEDGE_DIR/$TRIGGER_FILE"
fi

if [ ! -f "$TRIGGER_FILE" ]; then
  echo "Error: trigger file not found: $1" >&2
  exit 1
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
MACHINE_NAME="${FLEET_MACHINE_NAME:-$(hostname -s)}"

if [ "$ACTION" = "done" ]; then
  # Release claim — mark completed
  python3 - "$TRIGGER_FILE" "$TIMESTAMP" <<'PYEOF'
import sys, re

path, ts = sys.argv[1], sys.argv[2]
text = open(path).read()

def set_field(t, key, value):
    pattern = rf'^({key}:\s*).*$'
    replacement = rf'\g<1>{value}'
    if re.search(pattern, t, re.MULTILINE):
        return re.sub(pattern, replacement, t, flags=re.MULTILINE)
    # Insert after the opening ---
    return re.sub(r'^(---\n)', rf'\1{key}: {value}\n', t, count=1)

text = set_field(text, 'status', 'completed')
text = set_field(text, 'completed_at', ts)

open(path, 'w').write(text)
print(f"Released: {path}")
PYEOF

else
  # Claim the item — mark in_progress
  python3 - "$TRIGGER_FILE" "$MACHINE_NAME" "$TIMESTAMP" $$  <<'PYEOF'
import sys, re

path, machine, ts, pid = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
text = open(path).read()

def set_field(t, key, value):
    pattern = rf'^({key}:\s*).*$'
    replacement = rf'\g<1>{value}'
    if re.search(pattern, t, re.MULTILINE):
        return re.sub(pattern, replacement, t, flags=re.MULTILINE)
    return re.sub(r'^(---\n)', rf'\1{key}: {value}\n', t, count=1)

text = set_field(text, 'status', 'in_progress')
text = set_field(text, 'claimed_by', f'{machine}:{pid}')
text = set_field(text, 'claimed_at', ts)

open(path, 'w').write(text)
print(f"Claimed: {path}")
PYEOF
fi

if [ $? -ne 0 ]; then
  echo "Error: failed to update trigger file" >&2
  exit 1
fi

# Commit and push
cd "$KNOWLEDGE_DIR" || exit 1
git pull --rebase origin "$(git branch --show-current)" --quiet 2>/dev/null
git add "$TRIGGER_FILE" 2>/dev/null || git add "${TRIGGER_FILE#$KNOWLEDGE_DIR/}"
git commit -m "chore(inbox): claim ${TRIGGER_FILE##*/} [${ACTION}]" --quiet
git push --quiet
