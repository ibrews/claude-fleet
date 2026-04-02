# Inbox System — Protocol

This folder is the inter-machine messaging layer. Any Claude session on any machine can write to any inbox. Machines check their own inbox at session start and process pending items.

## How It Works

```
You (or Claude) write a task → inbox/<machine>.md
        ↓
git push → shared knowledge base repo
        ↓
Target machine pulls repo → finds pending item in its inbox
        ↓
Claude processes the item → marks done → git push
```

## Writing a Message

Add a task to the target machine's inbox file under `## Pending`:

```markdown
- [ ] [2024-01-15 14:00] @alpha → run: python train.py --epochs 100
- [ ] [2024-01-15 14:00] @alpha → check: is the API server healthy?
- [ ] [2024-01-15 14:00] @beta → build: compile the project and run tests
```

**Format:** `- [ ] [YYYY-MM-DD HH:MM] @<sender> → <verb>: <details>`

**Verbs:**
- `run:` — execute a command or script
- `check:` — verify a status and report back
- `build:` — compile or package a project
- `fetch:` — download or retrieve something
- `message:` — informational, no action required

## Machine Pickup

Each machine processes its inbox automatically via the SessionStart hook:

1. `git pull origin master`
2. Read `inbox/<this-machine>.md`
3. Process any `- [ ]` items under `## Pending`
4. Mark completed: change `- [ ]` to `- [x] (YYYY-MM-DD)`
5. Move to `## Done` section
6. If the task came from another machine (`@sender`), add a confirmation to the sender's inbox
7. `git add inbox/ && git commit -m "chore(inbox): processed" && git push`

## Cleanup

Done items older than 7 days should be deleted. Git history preserves everything.
