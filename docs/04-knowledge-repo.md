# Knowledge Base Repository

The shared git repo is the communication backbone of your fleet. Every machine clones it, reads from it, writes to it, and pushes changes back.

## Create the Repo

Create a **private** repository on GitHub (or GitLab, Bitbucket, etc.):

```bash
# On GitHub
gh repo create fleet-kb --private
```

## Recommended Structure

```
fleet-kb/
├── CLAUDE.md           # Navigation guide for AI agents (see below)
├── inbox/              # Inter-machine messaging
│   ├── README.md       # Protocol documentation
│   ├── alpha.md        # Alpha's inbox
│   ├── beta.md         # Beta's inbox
│   └── gamma.md        # Gamma's inbox
├── fleet/              # Fleet configuration
│   └── roster.md       # Machine inventory
└── daily/              # Auto-generated session logs (optional)
    └── 2024-01-15-alpha.md
```

## Clone on Every Machine

**Always clone to `~/knowledge`** — never into `~/.claude/`:

```bash
git clone git@github.com:you/fleet-kb.git ~/knowledge
```

Optionally create a compatibility symlink:
```bash
ln -s ~/knowledge ~/.claude/knowledge
```

On Windows:
```cmd
git clone git@github.com:you/fleet-kb.git %USERPROFILE%\knowledge
mklink /J %USERPROFILE%\.claude\knowledge %USERPROFILE%\knowledge
```

## CLAUDE.md Navigation Guide

Add a `CLAUDE.md` file to the root of your knowledge base. This is the first file AI agents read — it tells them how to find, use, and update context. A good navigation guide includes:

- **Folder structure** — what each directory contains
- **Routing table** — "if the task involves X, look in Y"
- **Writing rules** — frontmatter requirements, file naming conventions
- **Sync rules** — how to pull/push, conflict resolution
- **The `~/knowledge` rule** — always access via `~/knowledge/`, never `~/.claude/knowledge/`

A starter template is included at [templates/CLAUDE.md](../templates/CLAUDE.md) — copy it into your KB root and customize it for your setup.

## Formatting and Style Rules

For consistency across multiple machines and agents writing to the same KB:

- **Frontmatter:** Every file should have YAML frontmatter with at least `title`, `updated`, and `tags`
- **Date format:** `YYYY-MM-DD` everywhere
- **File naming:** Lowercase, hyphen-separated (e.g., `auth-middleware-decision.md`)
- **One topic per file.** Prefer creating a new file over appending to a catch-all
- **Daily logs:** Use machine-specific filenames: `daily/YYYY-MM-DD-<machine>.md` to prevent merge conflicts
- **Cross-references:** Use `[[wiki-links]]` to connect related files

Consider adding a `STYLE_GUIDE.md` to your KB with your specific conventions. All agents and humans contributing to the KB should follow it.

## Git Authentication

Every machine needs to push without a password prompt. Two options:

### Option A: SSH Keys (Recommended)

```bash
# Generate a key (no passphrase for headless operation)
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N "" -C "machine-name@fleet"

# Add the public key to GitHub
cat ~/.ssh/id_ed25519.pub
# → Add at github.com/settings/keys or as a deploy key on the repo

# Use SSH remote
git remote set-url origin git@github.com:you/fleet-kb.git
```

**Windows note:** SSH key files must have restricted permissions or OpenSSH will refuse to use them:
```cmd
icacls %USERPROFILE%\.ssh\id_ed25519 /inheritance:r /remove "BUILTIN\Administrators" /remove "NT AUTHORITY\SYSTEM" /grant:r "%USERNAME%:(R)"
```

### Option B: Personal Access Token

```bash
# Store credentials
git config --global credential.helper store
git pull  # enter PAT as password once — it's cached
```

## Auto-Sync Cron (Optional)

Pull the KB every 15 minutes so machines stay current even without active Claude sessions:

```bash
# macOS/Linux crontab
*/15 * * * * cd ~/knowledge && git pull --rebase origin master >/dev/null 2>&1
```

## Conflict Resolution

With multiple machines pushing, conflicts will happen. The hooks use `git pull --rebase` to minimize merge commits. For markdown files, conflicts usually auto-resolve (both sides kept). If a rebase fails, `git rebase --skip` and move on — the git history preserves everything.
