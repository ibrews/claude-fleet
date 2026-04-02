# Inbox System

The inbox is the core communication protocol. It's deliberately simple: markdown checkboxes in git.

## Message Format

```markdown
- [ ] [YYYY-MM-DD HH:MM] @<sender> → <verb>: <details>
```

**Example:**
```markdown
- [ ] [2024-01-15 14:00] @alpha → run: python benchmark.py --gpu
- [ ] [2024-01-15 14:30] @alpha → check: is the database backup complete?
- [ ] [2024-01-15 15:00] @gamma → build: compile project and deploy to staging
```

## Verbs

| Verb | Meaning |
|------|---------|
| `run:` | Execute a command or script |
| `check:` | Verify a status and report back |
| `build:` | Compile, package, or deploy |
| `fetch:` | Download or retrieve something |
| `message:` | Informational — no action needed |

## Processing Flow

When Claude starts a session, the `kb-inbox-check.sh` hook:

1. Pulls the latest knowledge base
2. Reads this machine's inbox file
3. Finds lines matching `- [ ]` (unchecked items)
4. Injects them into Claude's context as high-priority instructions

Claude then:

1. Processes each item
2. Changes `- [ ]` to `- [x] (2024-01-15)`
3. Moves completed items to the `## Done` section
4. If the task came from `@sender`, writes a confirmation to the sender's inbox
5. Commits and pushes

## Inbox File Template

```markdown
# Inbox: machine-name

## Pending

<!-- New tasks go here -->

## Done

<!-- Completed tasks are moved here -->
```

## Sending a Task

From any machine:

```bash
cd ~/.claude/knowledge

# Add a task to beta's inbox
cat >> inbox/beta.md << 'EOF'
- [ ] [2024-01-15 14:00] @alpha → run: python train.py --epochs 50
EOF

git add inbox/beta.md
git commit -m "task: training job for beta"
git push
```

Or just tell Claude: *"Send a message to beta's inbox asking it to run the training script."*

## Confirmation Protocol

After completing a task from `@alpha`, the processing machine writes back:

```markdown
# In inbox/alpha.md, under ## Pending:
- [ ] [2024-01-15 14:30] @beta → message: completed "run: python train.py" — 50 epochs, loss 0.023
```

This creates a two-way conversation through git.

## Tips

- **Keep tasks specific.** "Run the tests" is better than "check if things work."
- **One task per line.** Don't bundle multiple requests.
- **Clean up weekly.** Delete done items older than 7 days. Git history preserves everything.
- **Don't modify other machines' done items.** Only add to their Pending section.
