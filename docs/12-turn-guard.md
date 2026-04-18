# Turn Guard & fleet-bot

The turn guard is a PreToolUse hook that stops runaway Claude Code sessions before they burn unbounded tokens. It pairs with **fleet-bot**, a Telegram relay that gives you operator controls (`Stop Now`, `Unrestrict`, `reply-to-continue`) from your phone.

## Why

Left unattended, a Claude Code session can loop on a tool-error chain and burn through hundreds of tool calls without making progress. This is especially painful when you're away from the keyboard and the loop only surfaces hours later via the API bill. The turn guard gives you three escalating interventions:

| Count | Action |
|---|---|
| **200** | Telegram warning: session context + `[🛑 Stop Now] [🔓 Unrestrict]` buttons |
| **450** | Second warning, same buttons |
| **490** | Block one tool call with a reason telling Claude to write a `HANDOFF_PROMPT.md` so the next session can resume cleanly |
| **500** | Block all further tool calls with a "session killed" Telegram notice |

Tuning: edit the constants at the top of `scripts/hooks/turn-guard.sh`. `MAX_TURNS=500` is a reasonable ceiling for Sonnet/Opus — well past normal work, comfortably under "spent $50 on a loop".

## Install the hook

1. Symlink or copy `scripts/hooks/turn-guard.sh` and `scripts/hooks/lib/tg-notify.sh` into `~/claude-fleet/scripts/hooks/` on every fleet machine.
2. In `~/.claude/settings.json`:
   ```json
   {
     "hooks": {
       "PreToolUse": [{
         "hooks": [{
           "type": "command",
           "command": "$HOME/claude-fleet/scripts/hooks/turn-guard.sh",
           "timeout": 10
         }]
       }]
     }
   }
   ```
3. Make sure `~/claude-fleet/fleet.env` has `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Without them the notifier silently no-ops — the hook itself still guards turns, you just won't see the warnings on Telegram.

## Install fleet-bot (buttons + replies)

See [`telegram/fleet-bot/README.md`](../telegram/fleet-bot/README.md). TL;DR:

1. Create a **dedicated** Telegram bot via @BotFather — don't reuse the one your MCP/ccgram instance is already polling or you'll hit 409 Conflict.
2. Edit `telegram/fleet-bot/machines.json` with your Tailscale IPs / SSH users.
3. Run `telegram/fleet-bot/install.sh` on your always-on gateway machine.

## How the pieces fit

```
  Claude Code session                       Telegram                    fleet-bot
  ───────────────────                       ────────                    ─────────
  tool call N  ──► turn-guard.sh ──► tg-notify.sh ──► sendMessage
                   (count→file)         (HTML + inline keyboard
                                         + #sid= #machine= tag)

  You tap [Stop Now]                                               long-poll getUpdates
                   ◄─────────────── callback_query "s:<m>:<sid>" ───┘
                                                                      │
                                                                      ▼
                                                                  SSH to <m>
                                                                  touch /tmp/tg-<sid>.stop

  Claude Code session
  next tool call ──► turn-guard.sh sees .stop flag ──► returns block decision
```

Replies work the same way: the bot parses `#sid=` / `#machine=` from the `reply_to_message.text`, so routing survives bot restarts and works for messages turn-guard sent directly via curl (bypassing the grammy Api layer).

## Operator overrides (per session)

| File | Effect |
|---|---|
| `/tmp/tg-<sid>` | Current turn count (integer). Managed by turn-guard. |
| `/tmp/tg-<sid>.stop` | Presence → next tool call blocks with an operator-stop reason. |
| `/tmp/tg-<sid>.max` | Integer → replaces `MAX_TURNS` for this session; `FINAL_TURNS` recomputes and the handoff flag is re-armed. |
| `/tmp/tg-<sid>.handoff-delivered` | Presence → handoff nudge already fired, don't fire again this session. |

If you ever need to intervene manually: `ssh <machine> touch /tmp/tg-<session-id>.stop` stops the session at the next tool call.

## Handoff-prompt nudge

At `MAX_TURNS - 10` the hook blocks exactly one tool call with a `reason` asking Claude to write `HANDOFF_PROMPT.md` (in the repo root if in a project, otherwise in `~/claude-fleet/triggers/`). The remaining 10 turns let it finish. A future session can pick up the handoff cleanly.

This matters because force-stopping at exactly the cap usually catches a session mid-thought — the next session then starts cold. The handoff nudge converts the last few turns into documentation instead of more work.
