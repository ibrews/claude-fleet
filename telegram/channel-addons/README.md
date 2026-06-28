# Telegram Channel Add-ons

These scripts extend the **official Telegram plugin channel** (`claude --channels plugin:telegram@claude-plugins-official`) with fleet-aware controls. They are **separate from the fleet-bot** in `../fleet-bot/` — the fleet-bot handles turn-guard notifications and operator controls; these scripts handle rate-limit sleep, usage visibility, and terminal-side controls.

## Scripts

### `statusline.py`

A Claude Code `statusLine` bridge. Wired into `~/.claude/settings.json` as:

```json
{ "statusLine": "python3 $HOME/claude-fleet/telegram/channel-addons/statusline.py" }
```

On every model response it:
1. Prints the visible status line: `Model | dir | 5h 42% | wk 18%`
2. Persists rate-limit data to `~/.claude/usage-state.json` — the only way Claude Code exposes subscription rate limits programmatically. The rate-limit autosleep hook and `/usage` bot command read this file.

### `rate-limit-autosleep.sh`

A `StopFailure` hook. When any session fails with a rate limit, it:
1. Flips the Telegram channel into sleep mode (messages queue, Claude isn't woken)
2. Auto-expires: uses the 5h-window reset time from `usage-state.json` if available, else 1 hour
3. Sends a single Telegram notification: "💤 Claude hit a usage limit — sleeping until ~3:42 PM"

Wire it in `~/.claude/settings.json`:
```json
{
  "hooks": {
    "StopFailure": [{
      "hooks": [{ "type": "command", "command": "$HOME/claude-fleet/telegram/channel-addons/rate-limit-autosleep.sh", "timeout": 10 }]
    }]
  }
}
```

Requires: `~/.claude/channels/telegram/` directory (created by the official plugin), `.env` with `TELEGRAM_BOT_TOKEN`, and `access.json` with `allowFrom` chat IDs.

### `tg-mode.sh`

Terminal-side controls for the channel's sleep/wake/limitless modes. Writes the same flag files that the `/sleep`, `/wake`, `/limitless` bot commands use — both surfaces stay in sync.

```bash
tg-mode sleep [8h|30m]   # queue inbound messages, don't wake Claude
tg-mode wake             # resume delivery
tg-mode limitless [8h]   # bypass the turn-guard tool-call cap temporarily
tg-mode limited          # re-arm the turn-guard
tg-mode status           # show current modes
```

Install: symlink or copy to `~/claude-fleet/telegram/channel-addons/tg-mode.sh` and add to your `$PATH`.

## Setup Order

1. Install the official Telegram plugin: `claude --channels plugin:telegram@claude-plugins-official`
2. Wire `statusline.py` as the statusLine
3. Add `rate-limit-autosleep.sh` to StopFailure hooks
4. Put `tg-mode.sh` in your PATH
5. The `/usage`, `/sessions`, and `/briefing` commands in your bot will now have live rate-limit data
