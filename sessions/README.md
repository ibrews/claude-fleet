# sessions/

This directory is written by the session board (`session-board.sh`). You don't edit it directly.

## sessions/active/

One `.md` file per live session, named `<machine>-<slug>.md`. Each session writes **only its own file** — no two sessions ever touch the same file, so git never races.

The `session-board-show.sh` hook creates the entry at SessionStart. The `session-board-checkout.sh` hook removes it at SessionEnd. To see all active sessions:

```bash
~/claude-fleet/session-board.sh board
```

Entries older than 15 minutes with no heartbeat are flagged as stale. A stale entry with a dead PID means the session crashed without cleaning up — it is safe to remove manually:

```bash
rm ~/knowledge/sessions/active/<machine>-<slug>.md
```

## Reading the board from Claude

During any session, Claude can call `session-board.sh board` to see who is active and what resources they hold. The `claim:` field is the key one: it lists the singletons a session is holding (e.g. `"ue-build-engine, AVP-device"`) so you know not to start a competing build or try to install to the same device.
