#!/usr/bin/env bash
# Relocate Claude Desktop's Computer Use VM bundle on macOS.
#
# STATUS: NOT YET IMPLEMENTED.
#
# When this becomes needed, the macOS equivalent would:
#   - Source path: "$HOME/Library/Application Support/Claude/vm_bundles"  (verify on first use)
#   - Detect whether Claude Desktop or its VM is running (`pgrep -f "Claude.app"`, `vmctl list`, etc.)
#   - rsync -a --remove-source-files SRC/ DEST/ && find SRC -type d -empty -delete
#   - ln -s DEST SRC
#   - Verify with `stat -L` that the symlink resolves
#
# Until implemented, do not run.
echo "macos.sh: not yet implemented. See SKILL.md for the planned approach." >&2
exit 64
