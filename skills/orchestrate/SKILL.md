---
name: orchestrate
description: Workflow orchestrator. Builds task queue from input, dispatches subagents, manages completion.
user_invocable: false
---

# Orchestrate

## Phases

```
[intake] → [design] → orchestrate
```

- `intake` (optional): gather missing info. Skip if input sufficient.
- `design` (optional): plan doc. Only from intake.
- `orchestrate`: default entry. Build queue → dispatch → PRs. Can → intake if needed.

## Task Queue

Single ordered list in workflow state. Orchestrator owns exclusively.

### Building

Read all input (specs, requirements, code) → produce complete work orders.

Principle: **orchestrator decides, subagents execute.**

Bar: can subagent execute with ONLY this description? No arch decisions, no discovery. Must choose between approaches → task needs more detail.

Requirements:
- **Actionable**: exact interfaces, behavior, edge cases
- **Scoped**: one testable increment per task
- **Opinionated**: orchestrator makes arch calls (data structures, APIs, layout)
- **Self-contained**: no external reference needed

Also:
- shared code → extract as shared tasks (don't let N agents reinvent)
- one spec → multiple focused tasks (not 1:1)
- cross-task contracts: "task B imports X from task A's module"

### Schema

`workflow__set_value(wf_id, "task_queue", queue)`

```json
[
  {"id": "00a", "group": "shared", "depends_on": [], "title": "...", "description": "...", "status": "pending"},
  {"id": "01a", "group": "01-feature", "depends_on": ["00a"], "title": "...", "description": "...", "status": "pending"}
]
```

| Field | Purpose |
|-------|---------|
| id | unique identifier |
| group | PR boundary (all tasks in group → one PR) |
| depends_on | task IDs that must complete first |
| title | short label |
| description | complete work order |
| status | pending \| in_progress \| complete \| failed |

Pre-sorted: deps before dependents, parallel tasks adjacent. Dequeue from front.

## Dispatch

```
while ¬stop_condition:
  task ← next pending where ∀(depends_on) == complete
  task found → launch subagent(iterate, task)
  on return → mark complete, check unblocked
  group_complete → create PR
```

### Supervision
- dead/stuck agent → mark failed → reset pending → reassign next slot
- no special retry; queue is the mechanism

### PR Review Feedback
- monitor PRs for comments
- each comment → new task (same group, depends on original)
- append to queue → dispatch when slot opens

## Stop Condition

ALL true simultaneously:
1. queue empty (all complete)
2. no agents in flight
3. no unaddressed PR review comments
4. working tree clean
5. every group has PR

## Subagent Model

Each task runs iterate: `test_writing → implement → test → review(commit+push)`

Review gate inside subagent. Result returned = verified + committed + pushed. No re-review.
