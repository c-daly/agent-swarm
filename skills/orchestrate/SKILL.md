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

### Anti-patterns
- **Spec forwarding**: creating one task whose description is just the spec.
  A spec is input to the orchestrator, not output. Every spec should decompose
  into multiple focused tasks with explicit dependencies.
- **Vague descriptions**: "implement the skip list" is not a work order.
  A work order specifies exact interfaces, data structures, behavior, and edge cases.

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

## Setup

Before entering the dispatch loop:

1. **Worktrees**: create one per group, each on its own branch
   ```
   git worktree add ../worktree-<group> -b <group-branch>
   ```
2. Pass worktree path as working directory in subagent prompts
3. Orchestrator owns worktree lifecycle — create before dispatch, clean up after PR merge

## Dispatch

```
while ¬stop_condition:
  unblocked ← all pending where ∀(depends_on) == complete
  for each task in unblocked:            ← batch launch all, preferred
    launch subagent(iterate, task)       ← non-blocking, do NOT wait
  check completed agents → mark tasks done
  check newly unblocked → next iteration
  group_complete → push branch + create PR
```

All dispatch is **non-blocking**. Launch and continue — never wait for a subagent.
Launching all unblocked tasks at once is preferred over one-at-a-time.

### Dispatch Methods

Preferred → fallback:

1. **Task with team** (preferred)
   ```
   Task(
     team_name="<team>",
     name="<task-id>",
     prompt="<task description + working dir>",
     subagent_type="implementer"
   )
   ```

2. **Task without team**
   ```
   Task(
     prompt="<task description + working dir>",
     subagent_type="implementer"
   )
   ```

3. **native__task via router** (fallback)
   ```
   mcp__router__native__task(
     prompt="<task description + working dir>",
     subagent_type="implementer",
     description="<short label for logging>"
   )
   ```

### Monitoring

- **With teams**: agents report via messages / idle notifications
- **Without teams**: `TaskOutput(block=false)` to poll
- Verify: check for new commits on group branch, run tests
- Never block-wait on a subagent

### Supervision
- dead/stuck agent → mark task failed → reset to pending
- dependents remain blocked (their depends_on is unsatisfied)
- next dispatch naturally picks up the reset task (earliest unblocked pending)
- no special reinsertion or retry logic; queue ordering + dependency checks are the mechanism

### PR Lifecycle
- Group complete → push branch: `git push origin <branch>`
- Open PR: `gh pr create --base main --head <branch>`
- Poll comments: `gh api repos/<owner>/<repo>/pulls/<n>/comments`
- Each comment → new task (same group, depends on original)
- Append to queue → dispatch when unblocked

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
