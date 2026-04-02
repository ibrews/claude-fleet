# Five-Machine Fleet with Role Specialization

A more realistic setup where machines have distinct roles and tasks are routed based on capability.

## Roster

| Machine | Hardware | Role | Best For |
|---------|----------|------|----------|
| **coord** | Mac Mini (always-on) | Coordinator | Routing, monitoring, KB management |
| **gpu-1** | RTX 4090, 128GB RAM | Heavy Compute | Training, rendering, large builds |
| **gpu-2** | RTX 3080, 64GB RAM | Compute | Parallel workloads, testing |
| **dev** | MacBook Pro | Development | Code generation, reviews, testing |
| **light** | Older desktop | Light Duty | Monitoring, classification, batch jobs |

## Routing Guide

Put this in your knowledge base as `fleet/routing.md` so Claude knows where to send tasks:

```markdown
# Task Routing

1. **GPU-heavy work** (training, rendering) → gpu-1, fallback gpu-2
2. **Code generation/review** → dev
3. **Simple queries, monitoring** → light
4. **Coordination, KB management** → coord
5. **Batch of 10+ small tasks** → light (parallel)
```

Claude sessions on any machine can read this file and route tasks to the right inbox.

## Running the Fleet

```bash
# From coord (the always-on machine):

# Check all inboxes
./fleet-inbox-check.sh

# Check only GPU machines
./fleet-inbox-check.sh gpu-1 gpu-2

# Schedule hourly checks via cron
crontab -e
0 * * * * /path/to/fleet-inbox-check.sh >> /tmp/fleet.log 2>&1
```

## Scaling Tips

- **Add machines easily**: Create an inbox file, install hooks, add to `ALL_MACHINES`. No other configuration needed.
- **Remove machines**: Just remove from `ALL_MACHINES`. Old inbox file stays in git for history.
- **Role changes**: Update the routing guide. Claude adapts immediately.
- **Shared context**: Put architectural decisions, API docs, or project state in the knowledge base. All machines see it.
