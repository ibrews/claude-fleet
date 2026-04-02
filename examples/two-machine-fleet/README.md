# Two-Machine Fleet: Laptop + Desktop

The simplest fleet — your laptop as the coordinator and a desktop as the workhorse.

## Setup

| Machine | Hardware | Role | Tailscale Name |
|---------|----------|------|----------------|
| **laptop** | MacBook | Coordinator — triggers tasks, monitors | laptop |
| **desktop** | Desktop with GPU | Compute — runs heavy tasks | desktop |

## Steps

### 1. Connect via Tailscale

Install Tailscale on both. Verify:
```bash
# From laptop
ssh desktop
```

### 2. Create the knowledge base

```bash
# On GitHub
gh repo create my-fleet-kb --private

# On laptop
git clone git@github.com:you/my-fleet-kb.git ~/knowledge
cd ~/knowledge
mkdir inbox
echo '# Inbox: laptop\n\n## Pending\n\n## Done' > inbox/laptop.md
echo '# Inbox: desktop\n\n## Pending\n\n## Done' > inbox/desktop.md
git add . && git commit -m "init" && git push

# On desktop
git clone git@github.com:you/my-fleet-kb.git ~/knowledge
```

### 3. Install hooks on both machines

Copy `kb-inbox-check.sh`, `kb-session-end.sh`, and `notify-human.js` to `~/claude-fleet/` on each machine. Update `~/.claude/settings.json` per the template.

### 4. Configure the fleet trigger

Edit `fleet-inbox-check.sh` on the laptop:
```bash
ALL_MACHINES="laptop desktop"

get_host() {
  case "$1" in
    laptop) echo "localhost" ;;
    desktop) echo "desktop" ;;
  esac
}
```

### 5. Test the round trip

```bash
# From laptop — send a task to desktop
cd ~/knowledge
echo '- [ ] [2024-01-15 14:00] @laptop → check: What is your hostname and uptime?' >> inbox/desktop.md
git add . && git commit -m "test: ping desktop" && git push

# Trigger desktop
./fleet-inbox-check.sh desktop

# Check results
git pull
cat inbox/laptop.md  # Should have a confirmation from desktop
```

You'll also get a Telegram notification when desktop finishes.
