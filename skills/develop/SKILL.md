---
name: develop
description: PR-based development workflow with SE team simulation
user_invocable: true
---

# Develop

PM orchestration playbook for the full PR-based development lifecycle.

## Phase Flow

```
intake → research → design → branch → [test_writing → implement → test] → review → merge → acceptance → complete
                                        └──────── TDD loop ────────┘
Kickbacks:
  test ──────────→ implement        (tests fail)
  review ────────→ implement        (code issues)
  review ────────→ test_writing     (test gaps)
  merge ─────────→ implement        (conflicts)
  acceptance ────→ implement        (requirements)
  acceptance ────→ test_writing     (test gaps)
```

## Agent Lifecycle

| Role | Spawn At | Shut Down After |
|------|----------|-----------------|
| PM | Workflow start (team lead) | complete |
| Researcher | research | research complete |
| Architect | design | design approved |
| Implementer | test_writing | complete |
| Reviewer | review | complete |
| Git-agent | branch | complete |
| Debugger | On demand | Issue resolved |

## Phases

### 1. Startup

Create team and start workflow. PM is team lead.

```
TeamCreate(team_name="develop-<feature>")
workflow__workflow_start(workflow_id="develop", task="<feature description>")
mkdir -p .develop/  # artifact directory for stories, research, design
```

### 2. Intake

Gather requirements from user. Write user stories with acceptance criteria.

**Actions:**
- Elicit requirements via conversation
- Write user stories (As a..., I want..., So that...) with acceptance criteria
- Optionally create feature ticket: `gh issue create --title "<feature>" --body "<stories>"`
- Store stories in workflow state: `workflow__set_value(wf_id, "stories", stories)`
- Write to `.develop/stories.md`
- Advance: `workflow__advance_phase(wf_id, "research")`

### 3. Research

Spawn Researcher to gather codebase context.

**Actions:**
- Register + spawn Researcher teammate
  ```
  reg = router__register_agent(agent_id="researcher", agent_type="researcher", workflow_id="develop")
  Task(team_name=<team>, name="researcher", prompt=reg.briefing + "\n\n" + context_request)
  ```
- Send context request via `SendMessage(recipient="researcher", content=<stories + questions>)`
- Wait for context document
- Researcher writes findings to `.develop/research.md`
- Shut down Researcher: `SendMessage(type="shutdown_request", recipient="researcher")`
- Advance: `workflow__advance_phase(wf_id, "design")`

### 4. Design

Spawn Architect to produce design spec with subtask dependency graph.

**Actions:**
- Register + spawn Architect teammate
  ```
  reg = router__register_agent(agent_id="architect", agent_type="architect", workflow_id="develop")
  Task(team_name=<team>, name="architect", prompt=reg.briefing + "\n\n" + design_request)
  ```
- Send stories + research context via `SendMessage`
- Wait for design spec with:
  - Architecture decisions
  - Subtask breakdown with dependency graph
  - Interface contracts between subtasks
- Architect writes to `.develop/design.md`
- **Checkpoint:** PM reviews and approves design
- Optionally create subtask tickets: `gh issue create` per subtask
- Shut down Architect: `SendMessage(type="shutdown_request", recipient="architect")`
- Advance: `workflow__advance_phase(wf_id, "branch")`

### 5. Branch

Spawn Git-agent to create feature branch from main.

**Actions:**
- Register + spawn Git-agent teammate
  ```
  reg = router__register_agent(agent_id="git-agent", agent_type="git-agent", workflow_id="develop")
  Task(team_name=<team>, name="git-agent", prompt=reg.briefing + "\n\n" + branch_request)
  ```
- Request branch creation via `SendMessage`
  ```
  SendMessage(recipient="git-agent", content="Create feature branch 'feat/<name>' from main")
  ```
- Git-agent creates branch, reports name
- Advance: `workflow__advance_phase(wf_id, "test_writing")`

### 6. TDD Loop (test_writing -> implement -> test)

For each eligible subtask (respecting dependency graph):

**Actions:**
- Build subtask queue from design spec. Store in workflow state:
  ```
  workflow__set_value(wf_id, "subtask_queue", subtask_list)
  ```
- Dequeue unblocked subtasks (all dependencies complete)
- For each unblocked subtask:
  ```
  # Implementers use iterate sub-workflow (TDD loop) for their individual work.
  # The develop workflow governs the PM's outer lifecycle.
  reg = router__register_agent(agent_id=<subtask-id>, agent_type="implementer", workflow_id="iterate")
  Task(
    team_name=<team>,
    name=<subtask-id>,
    prompt=reg.briefing + "\n\n" + subtask_description + working_dir,
    subagent_type="implementer",
    isolation="worktree"  # parallel subtasks get isolated worktrees
  )
  ```
- Independent subtasks run in parallel via isolated worktrees
- Each Implementer follows iterate sub-workflow: `test_writing -> implement -> test`
- Monitor via messages and task list
- When subtask tests pass, mark complete, check for newly eligible subtasks
- Re-assign idle Implementers to next unblocked subtask
- When all subtasks complete: `workflow__advance_phase(wf_id, "review")`

### 7. Review

Spawn Reviewer for adversarial code review.

**Actions:**
- Register + spawn Reviewer teammate
  ```
  reg = router__register_agent(agent_id="reviewer", agent_type="reviewer", workflow_id="develop")
  Task(team_name=<team>, name="reviewer", prompt=reg.briefing + "\n\n" + review_request)
  ```
- Send design spec + full diff via `SendMessage`
- Reviewer performs adversarial review against:
  - Design spec compliance
  - Code quality and conventions
  - Test coverage adequacy
  - Edge cases and error handling

**Outcomes:**

| Result | Action |
|--------|--------|
| Approve | `workflow__advance_phase(wf_id, "merge")` |
| Code issues | Record kickback, `workflow__advance_phase(wf_id, "implement")` |
| Test gaps | Record kickback, `workflow__advance_phase(wf_id, "test_writing")` |

### 8. Merge

Message Git-agent to create PR and merge.

**Actions:**
- Send merge request via `SendMessage(recipient="git-agent")`
- Git-agent pushes branch, creates PR: `gh pr create --base main --head <branch>`
- Attempt merge

**Outcomes:**

| Result | Action |
|--------|--------|
| Clean merge | `workflow__advance_phase(wf_id, "acceptance")` |
| Conflicts | Record conflict files, `workflow__advance_phase(wf_id, "implement")` |

### 9. Acceptance

PM validates implementation against user stories.

**Actions:**
- Check each acceptance criterion from stories
- Run acceptance tests if applicable
- Validate against original requirements

**Outcomes:**

| Result | Action |
|--------|--------|
| Accept | `workflow__advance_phase(wf_id, "complete")` |
| Code issue | Record issue, `workflow__advance_phase(wf_id, "implement")` |
| Test gap | Record gap, `workflow__advance_phase(wf_id, "test_writing")` |

### 10. Complete

Shut down all teammates and summarize.

**Actions:**
- Shut down all remaining teammates:
  ```
  SendMessage(type="shutdown_request", recipient="<each-agent>")
  ```
- Output summary:
  - What was done (stories satisfied)
  - PR link
  - Ticket links (if tickets enabled)
  - Kickback history
- Workflow done

## Kickback Routing

| From | Target | Reason |
|------|--------|--------|
| test | implement | Tests fail |
| review | implement | Code quality issues |
| review | test_writing | Insufficient test coverage |
| merge | implement | Merge conflicts |
| acceptance | implement | Doesn't meet requirements |
| acceptance | test_writing | Tests don't validate requirements |

Kickback loops (3+ same-issue kickbacks) trigger PM intervention — escalate to user.

## Subtask Parallelism

- Independent subtasks (no shared dependencies) run in parallel via isolated worktrees
- Dependent subtasks wait until their dependencies complete
- PM re-assigns idle Implementers when dependencies resolve
- Max concurrent agents governed by `max_agents` in workflow config (default: 8)

## Artifacts

| Artifact | Location | Purpose |
|----------|----------|---------|
| User stories | `.develop/stories.md` | Requirements + acceptance criteria |
| Research | `.develop/research.md` | Codebase context and findings |
| Design spec | `.develop/design.md` | Architecture, subtasks, dependency graph |
| Workflow state | Router state store | Phase, kickbacks, subtask status |

## Error Handling

- **Agent crash**: Re-spawn up to `max_agent_respawns` (default: 3). If exceeded, mark subtask failed and alert PM.
- **Kickback loops**: PM intervenes after 3+ same-issue kickbacks. Escalate to user if unresolvable.
- **Merge conflicts**: Kickback to implement with conflict file list.
- **Stale agents**: Monitor via messages/task list. Dead/stuck agent -> re-register and re-spawn.
- **Debugger escalation**: For persistent test failures, spawn a debugger on demand:
  ```
  reg = router__register_agent(agent_id="debugger-<issue>", agent_type="debugger", workflow_id="develop")
  Task(team_name=<team>, name="debugger-<issue>", prompt=reg.briefing + "\n\n" + error_context)
  ```
  Shut down debugger after issue is resolved.

## Configuration

Settings in `config/workflows/develop.yaml`:

| Setting | Default | Purpose |
|---------|---------|---------|
| `max_agents` | 8 | Max concurrent agents |
| `max_review_retries` | 0 | Auto-retry limit for review kickbacks (0 = unlimited) |
| `max_agent_respawns` | 3 | Max re-spawns per crashed agent |
| `tickets.enabled` | true | Create GitHub issues |
| `tickets.provider` | github | Issue provider (gh CLI) |
| `tickets.feature_ticket` | true | Create parent feature ticket |
| `tickets.subtask_tickets` | true | Create per-subtask tickets |
| `tickets.followup_tickets` | true | Reviewer/PM create at review/acceptance |
