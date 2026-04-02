# Installing Claude Code

Claude Code needs to be installed and authenticated on every machine in your fleet.

## Install

```bash
npm install -g @anthropic-ai/claude-code
```

Verify:
```bash
claude --version
```

## Authenticate

On each machine, run Claude interactively and log in:

```bash
claude
# Type: /login
# Complete the browser OAuth flow
# Wait for "Successfully logged in"
# Type: /exit
```

## Test Headless Mode

The fleet trigger runs Claude non-interactively via `claude -p`. Test it:

```bash
claude -p "Say hello" --max-turns 1
```

You should get a response. If you see "Not logged in", re-run the auth step.

## Platform Notes

### macOS (Homebrew)

```bash
# Binary location
/opt/homebrew/bin/claude    # Apple Silicon
/usr/local/bin/claude       # Intel

# If installed via Claude Desktop app, it may be at:
# ~/Library/Application Support/Claude/claude-code/<version>/claude.app/Contents/MacOS/claude
```

### Windows

```bash
# Usually installed to the npm global prefix
# If SSH doesn't find it, check:
where claude

# You may need the full path in get_claude_cmd():
# C:\Users\<username>\AppData\Roaming\npm\claude.cmd
```

**Important Windows notes:**
- Windows SSH runs `cmd.exe` by default. The `claude` command usually works if Node.js is in the system PATH.
- If your Windows machine has WSL installed, `bash` resolves to WSL's bash, not Git Bash. Use `node` for hooks instead of `bash` on Windows. The `notify-human.js` script is designed for this.
- SSH key files must have restricted permissions: `icacls id_ed25519 /inheritance:r /grant:r "%USERNAME%:(R)"`

### Linux

```bash
# Binary usually at
/usr/local/bin/claude
# or
~/.npm-global/bin/claude
```

## Setting Bypass Permissions

For autonomous fleet operation, you'll want Claude to run without permission prompts:

```json
{
  "permissions": {
    "defaultMode": "bypassPermissions",
    "deny": [
      "Bash(rm -rf /)",
      "Bash(sudo rm -rf *)"
    ]
  }
}
```

Add this to `~/.claude/settings.json` on each machine. The `deny` list prevents catastrophic commands while allowing everything else.
