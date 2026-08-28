---
title: "Command Center Operator Walkthrough"
updated: 2026-08-26
tags: [command-center, project-management, runbook]
---

# Command Center Operator Walkthrough

The Command Center is a lean delivery-control system for projects run by humans and AI agents. It
uses a Kanban-style flow: one durable ticket queue, explicit ownership, visible blockers, current
delivery evidence, and proof before closure. Scrum ceremonies are optional.

Open `/#command-center` in the Fleet Command Center. Select **Run 3-minute tour** for the guided
version of this walkthrough.

## The 30-second scan

1. Check the **generated** time. Old state is a warning, even when the numbers look healthy.
2. Read the top count strip. Non-zero means inspect; it does not automatically mean failure.
3. Clear **Needs the operator** first. It should contain only genuine human decisions or external gates.
4. Triage **Delivery risks**: red CI, blocked tickets, unintegrated Git work, stale reports, and
   unavailable host evidence.
5. Confirm **Recently completed** work includes a result and verification evidence.

## What each panel means

| Panel | Use it for | Healthy signal |
|---|---|---|
| Needs the operator | Decisions, approvals, credentials, external gates | Empty, or every item has an imminent decision |
| Live operations | Fresh, process-backed sessions | Work shown matches the intended active projects |
| Delivery risks | CI, ticket blockers, Git drift, telemetry gaps | Empty, or every risk has an owner and next action |
| Recently completed | Evidence-backed outcomes | Each result has a completion date and evidence link |

Open a project card for its full briefing, repository evidence, ticket integrity, roadmap, and live
session details.

## Turn a risk into work

Use **Work this** beside a delivery risk. It opens a dispatch brief prefilled with the project,
starting evidence, recommended first move, definition of done, and verification. Review the source
first, then either open the project evidence or copy the brief into the Fleet Control Center's
dispatch surface or an agent conversation. It deliberately does not create a ticket or start an
agent by itself: assignment, priority, and permission scope still require an explicit decision.

## Facts, summaries, and freshness

- **Machine fact** is deterministic evidence from tickets, sessions, Git, CI, or host reports.
- **AI summary** is interpretation written at a checkpoint. It can be useful and still be stale.
- Missing evidence is explicit. A missing or stale report is never treated as a clean checkout.
- A host reporter publishes read-only Git evidence every five minutes. Reports older than fifteen
  minutes are stale. Unintegrated branches and open PRs are flagged stale after fourteen days.

## Ticket lifecycle

`triggers/*.md` is the one durable queue. New tickets use `schema: work-item/v1`.

An actionable ticket needs:

- `project`: the exact project identity;
- `owner`: one accountable person or agent;
- `done_when`: an observable finish condition;
- `verification`: the exact check that will prove it;
- `blocked_on` and dated `next_check` when blocked;
- `evidence` when in review or completed;
- a substantive `## Result` before archival.

The normal lifecycle is `open` → `in_progress` → `review` → `completed`. Use `blocked` only when a
named condition prevents progress. Cancelled or superseded work is excluded from completed results.

Validate the queue with:

```bash
python3 departments/engineering/command-center/lib/work_items.py --kb-root .
```

Add `--strict` when doing migration work and warnings must also block.

## Daily operating loop

1. Scan freshness and counts.
2. Decide, delegate, or reject genuine human gates.
3. Assign an owner and next action to each meaningful risk.
4. Inspect the affected project card and source evidence.
5. Verify the work, integrate it into the default branch, deploy when required, and record evidence.
6. Close and archive the ticket only after the cockpit can still show the result.

## Weekly review

- Are human gates staying open longer than expected?
- Are old branches, dirty checkouts, or open PRs accumulating?
- Are red CI results owned and being rechecked?
- Do completed tickets have evidence, not just optimistic status text?
- Are project briefings still aligned with machine facts and current goals?
- Are migration warnings shrinking rather than becoming permanent background noise?

The goal is not process volume. The goal is to make unfinished, unverified, or unintegrated work
impossible to mistake for delivered work.
