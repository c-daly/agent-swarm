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
- `orchestrate`: Entry point. Build queue → dispatch → push/Create PRs. Go to intake if more info is needed to create reasonable prompts for subagents.

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

### Agent Registration

Before launching any subagent, register it with the router:

```
mcp__router__router__register_agent(
  agent_id="<task-id>",
  agent_type="implementer",
  workflow_id="iterate"
)
→ returns { agent_id, agent_type, roles, workflow_id, phase, briefing }
```

Registration does four things:
1. Grants the agent permissions to use router tools
2. Sets initial workflow phase from config
3. Records agent state (for monitoring/cleanup)
4. Returns a role-specific briefing to include in the agent's prompt

**The returned `briefing` must be prepended to the task prompt.** Without it,
the agent won't know how to use `mcp-call` or router tools.

### Dispatch Methods

Preferred → fallback:

1. **Task with team** (preferred)
   ```
   reg = register_agent(agent_id=<task-id>, agent_type="implementer", workflow_id="iterate")
   Task(
     team_name="<team>",
     name="<task-id>",
     prompt=reg.briefing + "\n\n" + <task description + working dir>,
     subagent_type="implementer"
   )
   ```

2. **Task without team**
   ```
   reg = register_agent(agent_id=<task-id>, agent_type="implementer", workflow_id="iterate")
   Task(
     prompt=reg.briefing + "\n\n" + <task description + working dir>,
     subagent_type="implementer"
   )
   ```
### Task Queue
- There is almost never a one-to-one relationship between the entire spec and a task
- Tasks are logical units of work, easily tested, and small enough to be convenient
- Tasks may sometimes span concerns if a library or shared code is necessary
- The queue must support dependence ordering with a focus on parallelism
- Once complete all that needs doing is pulling tasks off the queue - the thinking is done

### Monitoring

- **With teams**: agents report via messages / idle notifications
- **Without teams**: `TaskOutput(block=false)` to poll
- Verify: check for new commits on group branch, run tests
- Never block-wait on a subagent

### Supervision
- dead/stuck agent → mark task failed → reset to pending
- **unregistered agents cannot use router tools** — if an agent fails immediately
  after spawn, check registration. Clean up unregistered agents and re-dispatch
  with proper registration.
- dependents remain blocked (their depends_on is unsatisfied)
- next dispatch naturally picks up the reset task (earliest unblocked pending)
- no special reinsertion or retry logic; queue ordering + dependency checks are the mechanism

### PR Lifecycle
- Group complete → push branch: `git push origin <branch>`
- Open PR: `gh pr create --base main --head <branch>`
- Poll review threads: `gh api graphql -f query='{ repository(owner:"<owner>", name:"<repo>") { pullRequest(number:<n>) { reviewThreads(first:100) { pageInfo { hasNextPage endCursor } nodes { id isResolved comments(first:100) { nodes { body author { login } } } } } } } }'`
  - `comments(first:100)` captures full thread context (later replies, clarifications), not just the opening comment
  - If `pageInfo.hasNextPage` is true (PR has >100 review threads — rare), paginate using `reviewThreads(first:100, after:"<endCursor>")` until exhausted before evaluating stop condition #3
- Each unresolved thread → new task (same group, depends on original)
- Task description MUST include the comment text AND the directive: "After addressing, mark the review thread resolved via `gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "<thread-id>"}) { thread { isResolved } } }'`"
- Append to queue → dispatch when unblocked
- Subagent's definition-of-done for a comment-task: code change pushed AND review thread marked resolved (both required)
- Bot/automated review comments (Copilot, etc.) get the same treatment — respond with code change OR a reply explaining why no change, then mark resolved

## Stop Condition

ALL true simultaneously:
1. queue empty (all complete)
2. no agents in flight
3. **all PR review threads marked `isResolved: true`** (not just addressed in code — explicitly resolved on GitHub)
4. working tree clean
5. every group has PR

## Subagent Model

Each task runs iterate: `test_writing → implement → test → review(commit+push)`

Review gate inside subagent. Result returned = verified + committed + pushed. No re-review.
