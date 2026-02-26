# Develop Workflow Design

**Date:** 2026-02-26
**Status:** Approved

## Overview

The `develop` workflow simulates a full software engineering team using a PR-based development methodology. A PM agent acts as team lead and stakeholder proxy, coordinating specialized agents through a TDD-driven lifecycle from requirements gathering to merge.

Uses Claude Code's native team system (`TeamCreate`/`SendMessage`) for agent communication rather than ephemeral Task subagents, preserving agent context across phases.

## Team Roles

| Role | Agent Type | Purpose |
|------|-----------|--------|
| **PM** | pm | Stakeholder proxy. Owns feature lifecycle. Writes user stories. Makes acceptance decisions. |
| **Researcher** | researcher | Gathers codebase/API/library context before design. |
| **Architect** | architect | Decomposes feature into subtasks, defines interfaces and test strategy. |
| **Implementer** | implementer | TDD: writes tests first, then implementation. Addresses all kickback feedback. Uses `iterate` sub-workflow. |
| **Reviewer** | reviewer | Adversarial code review against design spec. Approves or kicks back with target (implement or test_writing). |
| **Git-agent** | git-agent | Branch creation, PR creation, merge handling. Reports conflicts. |
| **Debugger** | debugger | On-demand escalation for persistent test failures. |

## Phase Flow

```
intake -> research -> design -> branch -> test_writing -> implement -> test -> review -> merge -> acceptance -> complete
```

### Phase Definitions

| Phase | Agent | Purpose | Key Permissions |
|-------|-------|---------|-----------------|
| `intake` | PM | Gather requirements, write user stories, (optional) create feature ticket | FILE_READ, USER_INTERACTION |
| `research` | Researcher | Investigate codebase, APIs, prior art. Produce context document | FILE_READ, FILE_SEARCH, CODE_QUERY, WEB_RESEARCH |
| `design` | Architect | Decompose feature into subtasks with dependency graph, define interfaces, (optional) create subtask tickets | FILE_READ, CODE_QUERY, FILE_SEARCH |
| `branch` | Git-agent | Create feature branch from main | SHELL_SAFE (git only) |
| `test_writing` | Implementer | Write failing tests per TDD | FILE_READ, FILE_WRITE, CODE_EDIT, SHELL_SAFE |
| `implement` | Implementer | Make tests pass | FILE_READ, FILE_WRITE, CODE_EDIT, SHELL_SAFE |
| `test` | (via iterate) | Run tests, verify implementation | FILE_READ, SHELL_SAFE |
| `review` | Reviewer | Adversarial code review. (Optional) create follow-up tickets | FILE_READ, CODE_QUERY |
| `merge` | Git-agent | Create PR (links to tickets), merge | SHELL_SAFE (git/gh only) |
| `acceptance` | PM | Validate against user stories. (Optional) create follow-up tickets | FILE_READ, CODE_QUERY, USER_INTERACTION |
| `complete` | PM | Terminal state. Summary output | -- |

### Transitions

| From | To | Condition |
|------|----|----------|
| `intake` | `research` | Requirements gathered, user stories written |
| `research` | `design` | Context document produced |
| `design` | `branch` | PM approves design |
| `branch` | `test_writing` | Feature branch created |
| `test_writing` | `implement` | Failing tests written |
| `implement` | `test` | Implementation complete |
| `test` | `review` | Tests pass |
| `test` | `implement` | **Kickback: tests fail** |
| `review` | `merge` | Reviewer approves |
| `review` | `implement` | **Kickback: code quality issues** |
| `review` | `test_writing` | **Kickback: insufficient test coverage** |
| `merge` | `acceptance` | PR merged cleanly |
| `merge` | `implement` | **Kickback: merge conflicts** |
| `acceptance` | `complete` | PM accepts |
| `acceptance` | `implement` | **Kickback: doesn't meet requirements** |
| `acceptance` | `test_writing` | **Kickback: tests don't validate the requirement** |

## Kickback Model

All quality gates can kick work back to `implement` or `test_writing`. The deciding agent (Reviewer or PM) chooses the target based on what's wrong:

- **Implementation issue** -> kickback to `implement`
- **Insufficient/wrong tests** -> kickback to `test_writing`

Each kickback source tracks its own retry counter. Configurable `max_review_retries` (0 = unlimited).

### Kickback Data Structure

```yaml
kickback:
  from: review
  to: implement
  reason: "Missing error handling for network timeout in auth_handler.py"
  attempt: 2
  max_retries: 0
```

## Agent Lifecycle & Teams

Uses Claude Code native teams (`TeamCreate`/`SendMessage`/`TaskCreate`). Agents are long-lived teammates, not ephemeral subagents.

| Role | Alive From | Shut Down After |
|------|-----------|----------------|
| PM | Workflow start (team lead) | `complete` |
| Researcher | `research` | Research complete |
| Architect | `design` | Design approved |
| Implementer | `test_writing` | `complete` |
| Reviewer | `review` | `complete` |
| Git-agent | `branch` | `complete` |
| Debugger | On demand | Issue resolved |

**Idle management:** Agents stay alive and idle when no work is available. PM messages them to wake them up -- preserving accumulated context. Only early-phase agents (Researcher, Architect) are shut down after their role completes. Core-loop agents (Implementer, Reviewer, Git-agent) stay alive through `complete` because any phase can kick back to `implement`.

## Parallel Subtask Execution

The Architect's design spec includes a dependency graph:

```yaml
subtasks:
  - id: 1
    name: "Add auth middleware"
    files: [src/middleware/auth.py, tests/test_auth.py]
    depends_on: []
  - id: 2
    name: "Add login endpoint"
    files: [src/routes/auth.py, tests/test_routes.py]
    depends_on: [1]
  - id: 3
    name: "Add user model"
    files: [src/models/user.py, tests/test_models.py]
    depends_on: []
```

**Scheduling rules:**
- Independent subtasks run in parallel via separate Implementer agents in isolated git worktrees (`isolation: "worktree"`)
- Dependent subtasks run sequentially -- PM waits for blockers to complete
- When an Implementer finishes and remaining subtasks are blocked, it stays idle (alive, preserving context) until work unblocks
- PM re-assigns idle Implementers when dependencies resolve

## Data Flow & Artifacts

```
User request
    |
[intake] PM -> User Stories (acceptance criteria, scope) + (optional) Feature Ticket
    |
[research] Researcher -> Context Document (codebase analysis, API docs, patterns)
    |
[design] Architect -> Design Spec (subtask list, dependency graph, interfaces, test strategy) + (optional) Subtask Tickets
    |
[branch] Git-agent -> Branch name, base commit
    |
[test_writing] Implementer -> Test files (failing tests per TDD)
    |
[implement] Implementer -> Implementation code (tests should pass)
    |
[test] Test results (pass/fail + output)
    |
[review] Reviewer -> Review verdict (approve | request_changes) + (optional) Follow-up Tickets
    |
[merge] Git-agent -> PR URL, merge status (merged | conflict)
    |
[acceptance] PM -> Accept/reject against user stories + (optional) Follow-up Tickets
    |
[complete] Summary (what was done, PR link, ticket links, stories satisfied)
```

### Artifact passing mechanisms

1. **Messages** -- PM sends relevant context to each agent via `SendMessage` when assigning work. Agents message results back.
2. **Files in repo** -- Design specs, tests, code live in the working tree. Conventional paths (e.g., `.develop/design.md`, `.develop/stories.md`).
3. **Workflow state** -- Lightweight metadata (phase, retry counters, subtask status) stored in daemon via `workflow__update`.
4. **Shared task list** -- `TaskCreate`/`TaskUpdate` tracks subtasks, assignments, and completion.

## Configuration

```yaml
name: develop
initial_phase: intake
terminal_phase: complete
max_review_retries: 0      # per kickback source, 0 = unlimited
max_agent_respawns: 3      # per agent role per phase, 0 = unlimited
max_agents: 8              # concurrent agent limit
tickets:
  enabled: true            # master switch for ticket creation
  provider: github         # github issues via gh CLI
  feature_ticket: true     # PM creates at intake
  subtask_tickets: true    # Architect creates at design
  followup_tickets: true   # Reviewer/PM create at review/acceptance
```

## Error Handling

### Agent failures (crash, timeout, context exhaustion)
- PM receives the error and decides: re-spawn (retry), spawn different agent type (escalate), or abort
- `max_agent_respawns` limits retries per agent role per phase (0 = unlimited)
- Workflow state persists in daemon regardless of agent failure

### Kickback loops
- Each kickback source has its own retry counter
- PM monitors kickback history -- if same issue kicked back 3+ times with no progress, PM intervenes (clarifies requirement, overrides review, or redesigns)

### Merge conflicts
- Git-agent reports conflicts with file list to PM
- PM kicks back to Implementer with conflict details
- Implementer resolves, flow continues from `test`

### Daemon restart mid-workflow
- In-memory workflow state is lost (known limitation)
- Mitigation: design spec, stories, and code are in files/git. PM can restart from last checkpointed phase by inspecting repo state

### Reviewer-Implementer disagreement
- With unbounded retries, could loop indefinitely
- PM monitors kickback history and intervenes if no progress is being made

## Testing Strategy

### Unit tests
- Phase transition logic: given current phase + event, assert correct next phase
- Kickback routing: given target `implement` vs `test_writing`, verify correct transition
- Retry counter logic: increment, bounds checking, reset on success
- Configuration parsing: YAML schema validation, defaults, 0-means-unlimited

### Integration tests
- Workflow state persistence through daemon
- Permission enforcement per phase
- Agent briefing assembly for each role
- Team creation, message passing, shutdown lifecycle

### E2E test
- Full `develop` workflow on a controlled task in a test repo
- Complete lifecycle: intake -> stories -> design -> branch -> TDD -> implement -> review -> PR -> acceptance
- At least one kickback cycle (reviewer requests changes, implementer fixes, re-review)

### Out of scope for testing
- Agent quality (LLM behavior, not workflow behavior)
- External services (mock `gh` commands)
