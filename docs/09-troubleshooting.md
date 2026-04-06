# Troubleshooting

## Hooks fail with "node: command not found"

**Symptom:** Stop hooks (Telegram notifications, KB sync) silently fail. Check `/tmp/` or hook logs for `node: command not found`.

**Cause:** Headless sessions (`claude -p`) and hooks run in a minimal shell that doesn't load your profile. `node` isn't in the default PATH.

**Fix:** Use the full path to `node` in all hook commands in `~/.claude/settings.json`:
```json
// Bad:  "command": "node $HOME/claude-fleet/notify-human.js"
// Good: "command": "/opt/homebrew/bin/node $HOME/claude-fleet/notify-human.js"
```

Find your node path with `which node` and update all hook entries.

## Claude CLI not found via SSH

**Symptom:** `claude: command not found` when running via SSH.

**Cause:** SSH non-interactive shells don't load your full shell profile, so PATH may not include the Claude binary.

**Fix:** Use the full path in `get_claude_cmd()`:
```bash
# macOS (Homebrew)
/opt/homebrew/bin/claude

# macOS (App bundle)
~/Library/Application\ Support/Claude/claude-code/<version>/claude.app/Contents/MacOS/claude

# Find it on your system
which claude
```

## Windows: bash resolves to WSL

**Symptom:** Hook scripts can't find files at expected paths. Errors like `/root/claude-fleet/...: No such file or directory`.

**Cause:** `bash` on Windows may point to `C:\Windows\System32\bash.exe` (WSL), which has a completely different filesystem.

**Fix:** Use `node` for hooks on Windows instead of `bash`. The `notify-human.js` script works natively on Windows.

## Windows: SSH key "Permission denied (publickey)"

**Symptom:** `git pull` fails with permission denied, even though the key is on GitHub.

**Possible causes:**

1. **Key has a passphrase.** SSH can't prompt for it in non-interactive mode. Generate a new key without a passphrase:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
   ```

2. **Key file permissions too open.** Windows OpenSSH rejects keys that Administrators/SYSTEM can read:
   ```cmd
   icacls %USERPROFILE%\.ssh\id_ed25519 /inheritance:r /remove "BUILTIN\Administrators" /remove "NT AUTHORITY\SYSTEM" /grant:r "%USERNAME%:(R)"
   ```

3. **Git using HTTPS instead of SSH.** The Windows credential manager (`wincredman`) needs a TTY:
   ```bash
   git remote set-url origin git@github.com:you/fleet-kb.git
   ```

## Git conflicts on pull

**Symptom:** `CONFLICT (content): Merge conflict in daily/...` or inbox files.

**Fix:** For most fleet files, either side's version is fine:
```bash
git rebase --skip   # skip the conflicting commit
# or
git checkout --theirs . && git add -A && git rebase --continue
```

## Telegram notifications not arriving

**Checklist:**
1. Verify token/chat ID: `curl -s "https://api.telegram.org/bot<TOKEN>/getMe"` — should return bot info
2. Test send: `curl -s -X POST "https://api.telegram.org/bot<TOKEN>/sendMessage" -d chat_id="<ID>" -d text="test"`
3. Check the `.env` file path matches what the script expects (`~/claude-fleet/fleet.env` or `~/.ccgram/.env`)
4. On Windows, verify `node` is in PATH: `where node`

## Machine hits max turns (15) without finishing

**Symptom:** Telegram shows ⚠️ and the task may be incomplete.

**Causes:**
- The SessionStart hook consumed turns (git pull, inbox processing)
- Complex tasks need more turns

**Fix:** Increase `--max-turns` in `fleet-inbox-check.sh`, or re-trigger the specific machine:
```bash
./fleet-inbox-check.sh beta
```

## SSH timeout connecting to a machine

**Checklist:**
1. Is Tailscale running on both machines? `tailscale status`
2. Is the machine awake/powered on?
3. Is SSH enabled? `tailscale up --ssh`
4. Test basic connectivity: `ping <machine-name>`

## Claude Desktop permission prompts blocking automation

**Symptom:** Claude Desktop shows permission prompts (tool approval dialogs) during headless or automated sessions, causing them to hang indefinitely.

**Cause:** Claude Code requires explicit approval for certain tools by default.

**Fix:** Enable `bypassPermissions` mode in `~/.claude/settings.json`:
```json
{
  "permissions": {
    "defaultMode": "bypassPermissions",
    "deny": [
      "Bash(rm -rf /)",
      "Bash(sudo rm -rf *)"
    ]
  },
  "skipDangerousModePermissionPrompt": true
}
```

Both fields are required:
- `defaultMode: "bypassPermissions"` — skips interactive permission prompts
- `skipDangerousModePermissionPrompt: true` — skips the one-time "are you sure?" confirmation

Only enable this on machines you trust — it allows Claude to run any tool without asking.

**Known behaviors in bypass mode:**
- Editing `~/.claude/CLAUDE.md` always prompts (built-in safeguard — prevents agents from silently rewriting their own instructions)
- If you **deny** any single permission prompt during a session, Claude Code switches to prompting for ALL subsequent tool calls. The session cannot recover — start a new one.

## "Session not found" when clicking Telegram approval buttons

**Symptom:** You click an inline button (approve/reject) in Telegram but get "Session not found" or "Expired."

**Cause:** The approval session timed out. By default, callback sessions expire after a few minutes. If the bot restarts or enough time passes, the session context is lost.

**Fix:** Use `bypassPermissions` mode (above) to avoid needing Telegram approval in the first place. If you need approval workflows, ensure the bot stays running persistently and process approvals quickly.

## Inbox not being processed

**Symptom:** You pushed a task to `inbox/alpha.md` and triggered the machine, but nothing happened. The inbox item is still pending.

**Causes:**
1. **Machine name mismatch.** The script looks for `inbox/<machine-name>.md`. If the hostname doesn't match the inbox filename, it finds nothing.
   - **Fix:** Set `FLEET_MACHINE_NAME` explicitly. See [Machine Name Detection](07-hooks.md#machine-name-detection).
2. **KB not pulled.** The machine's local copy of `~/knowledge` is stale.
   - **Fix:** Verify with `cd ~/knowledge && git log --oneline -1` — does it show the commit with your inbox item?
3. **Hook not installed.** The SessionStart hook isn't configured.
   - **Fix:** Check `~/.claude/settings.json` for the SessionStart hook entry.

## Git push failures

**Symptom:** The session-end hook (`kb-session-end.sh`) fails to push changes. Work may be committed locally but not shared.

**Causes and fixes:**

1. **Network unavailable.** The machine is offline or Tailscale is down.
   - **Fix:** Check `tailscale status`. Changes are committed locally and will push on the next successful sync.

2. **Credential issues.** SSH key not loaded, expired token, etc.
   - **Fix:** Test manually: `cd ~/knowledge && git push`. Fix any auth errors.

3. **Merge conflicts.** Another machine pushed first and the rebase failed.
   - **Fix:** Pull and resolve manually:
   ```bash
   cd ~/knowledge
   git pull --rebase
   # Resolve any conflicts, then:
   git push
   ```

4. **Remote rejected (branch protection, etc.).**
   - **Fix:** Ensure the git user has push access to the KB repo's default branch.
