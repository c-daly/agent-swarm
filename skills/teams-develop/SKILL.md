---
name: teams-develop
description: "Full PR-based development lifecycle using native Claude Code teams — PM coordinates specialized agents through intake, research, design, implement, review, integrate, and complete phases"
user_invocable: true
---

# Teams Develop

PM orchestration playbook for the full PR-based development lifecycle using native Claude Code teams. No router dependency — all coordination via TeamCreate, SendMessage, TaskList.

## Phase Flow

```
INTAKE → RESEARCH → DESIGN → IMPLEMENT → REVIEW → INTEGRATE → COMPLETE
                                  ↑           |         |
                                  └───────────┘         |
                                  ↑                     |
                                  └─────────────────────┘
```

Kickbacks: REVIEW → IMPLEMENT (code issues), INTEGRATE → IMPLEMENT (merge conflicts / test failures).

<!-- spawn-conformance: native-teams-exempt -->
## Agent Lifecycle

These agents run as native Claude Code team members via `Agent()` / `TeamCreate()` / `SendMessage()` and do not route through the router; they cannot use `mcp-call` and do not need `register_agent` or a briefing prepend.

| Role | Phase | Agent Type | Model | Isolation | Writes? |
|------|-------|------------|-------|-----------|---------|
| PM (lead) | All | (is the lead) | — | none | yes |
| Researcher | RESEARCH | `Explore` | haiku | none | no |
| Architect | DESIGN | `feature-dev:code-architect` | sonnet | none | no |
| Implementer ×N | IMPLEMENT | `general-purpose` | opus | `worktree` | yes |
| Reviewer | REVIEW | `superpowers:code-reviewer` | sonnet | none | no |
| Git-agent | INTEGRATE | `general-purpose` | haiku | none | no |
| Debugger | On demand | `general-purpose` | sonnet | none | yes |

Agents are spawned at phase start and shut down at phase end (except implementers which persist through REVIEW kickbacks).

---

## Phases

### 1. INTAKE — Gather Requirements

Elicit requirements from the user. Write user stories with acceptance criteria.

**Actions:**
1. Discuss the feature with the user until requirements are clear
2. Write user stories (As a..., I want..., So that...) with acceptance criteria
3. Create team and artifacts directory:
   ```
   TeamCreate(team_name="td-<slug>")
   mkdir -p .develop/
   ```
4. Write stories to `.develop/stories.md`
5. **Checkpoint:** Get user approval on stories before proceeding

### 2. RESEARCH — Explore the Codebase

Spawn a researcher to gather codebase context relevant to the stories.

**Actions:**
1. Spawn researcher teammate:
   ```
   Agent(
     team_name="td-<slug>",
     name="researcher",
     subagent_type="Explore",
     model="haiku",
     prompt=<stories + "Explore the codebase for relevant patterns, files, conventions, and constraints. Report findings.">
   )
   ```
2. Researcher sends findings via SendMessage
3. PM writes findings to `.develop/research.md`
4. Shut down researcher: `SendMessage(type="shutdown_request", recipient="researcher")`

### 3. DESIGN — Architecture and Subtask Breakdown

Spawn an architect to produce a design spec with subtask dependency graph.

**Actions:**
1. Spawn architect teammate:
   ```
   Agent(
     team_name="td-<slug>",
     name="architect",
     subagent_type="feature-dev:code-architect",
     model="sonnet",
     prompt=<stories + research + "Produce: architecture decisions, subtask breakdown with dependency graph, interface contracts, file lists, test strategy">
   )
   ```
2. Architect sends design via SendMessage
3. PM writes design to `.develop/design.md`
4. **Checkpoint:** Get user approval on design before proceeding
5. Shut down architect: `SendMessage(type="shutdown_request", recipient="architect")`

### 4. IMPLEMENT — TDD in Worktrees

Create feature branch, create tasks per subtask, spawn implementers in isolated worktrees.

**Actions:**
1. Create feature branch: `git checkout -b feat/<name> main`
2. Create TaskCreate per subtask from the design, using `addBlockedBy` for dependencies:
   ```
   TaskCreate(subject="Implement: <subtask>", description=<details>)
   TaskUpdate(taskId=<id>, addBlockedBy=[<dependency-ids>])
   ```
3. For each unblocked task, spawn an implementer:
<!-- spawn-conformance: native-teams-exempt -->
   ```
   Agent(
     team_name="td-<slug>",
     name="impl-<subtask-slug>",
     subagent_type="general-purpose",
     model="opus",
     isolation="worktree",
     prompt=<TDD briefing below + subtask description + design context>
   )
   ```
4. Monitor via messages and TaskList:
   - Mark tasks completed as implementers finish
   - Spawn new implementers for newly unblocked tasks
   - Handle blockers — spawn debugger if needed
5. When all implementation tasks are complete, proceed to REVIEW

#### TDD Briefing (include verbatim in every implementer prompt)

```
## TDD DISCIPLINE (MANDATORY)

You MUST follow this sequence for every unit of work:

1. TESTS FIRST — Write tests that define the expected behavior. Run them. Confirm they FAIL.
   Commit with prefix: `test: <description>`

2. IMPLEMENT — Write the minimum code to make tests pass. Run tests. Confirm they PASS.
   Commit with prefix: `feat: <description>`

3. VERIFY — Run the full test suite + linter (ruff check). Fix any issues.

4. REPORT — Send a message to the team lead with:
   - Files modified (list)
   - Test count (new tests added, total passing)
   - Commits made (list with hashes)
   - Any blockers or concerns

Do NOT skip the test-first step. Do NOT write implementation before tests exist.
If you cannot write a meaningful test first (e.g., pure config), explain why in your report.
```

### 5. REVIEW — Adversarial Code Review

Spawn a reviewer to check the implementation against stories and design.

**Actions:**
1. Generate diff: `git diff main...feat/<name>`
2. Spawn reviewer teammate:
   ```
   Agent(
     team_name="td-<slug>",
     name="reviewer",
     subagent_type="superpowers:code-reviewer",
     model="sonnet",
     prompt=<review briefing below + stories + design + diff>
   )
   ```
3. Reviewer sends verdict: APPROVED or CHANGES_REQUESTED

#### Review Briefing (include in reviewer prompt)

```
## REVIEW CRITERIA

Review this implementation against the stories and design spec. Check:

1. **Design compliance** — Does the code match the architecture in the design spec?
2. **Story satisfaction** — Does each acceptance criterion have corresponding code?
3. **Test coverage** — Are there tests for each story? Check commit history for test: commits BEFORE feat: commits (TDD compliance).
4. **Code quality** — Conventions, error handling, no obvious bugs.
5. **Security** — No OWASP top-10 vulnerabilities introduced.

Verdict: Reply with APPROVED or CHANGES_REQUESTED.
If CHANGES_REQUESTED, provide a numbered list of specific issues to fix.
```

**Outcomes:**

| Verdict | Action |
|---------|--------|
| APPROVED | Shut down reviewer, proceed to INTEGRATE |
| CHANGES_REQUESTED | Create fix tasks, route to implementers, re-run review (max 3 cycles) |

If 3 review cycles fail on the same issue, escalate to the user.

### 6. INTEGRATE — Merge and PR

Merge worktree branches, run full test suite, create PR.

**Actions:**
1. If implementers used worktrees, merge their branches onto `feat/<name>` in topological order
2. Run the full test suite
3. Create PR: `gh pr create --base main --head feat/<name> --title "<title>" --body "<summary>"`
4. Invoke `superpowers:finishing-a-development-branch` for merge strategy

**Outcomes:**

| Result | Action |
|--------|--------|
| Clean merge + tests pass | Proceed to COMPLETE |
| Merge conflicts | Create fix task, spawn implementer on feature branch (no worktree), re-integrate |
| Test failures | Create fix task, spawn implementer/debugger, re-integrate |

### 7. COMPLETE — Wrap Up

**Actions:**
1. Shut down all remaining teammates:
   ```
   SendMessage(type="shutdown_request", recipient="<each-agent>")
   ```
2. Output summary table:
   ```
   | Item | Detail |
   |------|--------|
   | Stories | <count> satisfied |
   | Subtasks | <count> completed |
   | PR | <link> |
   | Review cycles | <count> |
   | Kickbacks | <list if any> |
   ```
3. Clean up team: `TeamDelete()`

---

## State Management

All state via native TaskList — no external state stores:

| Task prefix | Purpose |
|-------------|---------|
| `[META] <feature>` | Overall feature tracking |
| `Implement: <subtask>` | Subtask implementation work |
| `Fix: <issue>` | Review kickback fix |
| `Integrate: merge + PR` | Integration work |

Dependencies via `TaskUpdate(addBlockedBy=[...])`.

## Error Handling

| Scenario | Response |
|----------|----------|
| Agent crash | Re-spawn up to 3 times with error context |
| Review loop (3+ cycles, same issue) | Escalate to user |
| Merge conflicts | Create fix task, spawn implementer on feature branch |
| Researcher/architect failure | PM absorbs their role directly |
| Persistent test failures | Spawn debugger with error context |

## Rules

1. **PM never implements** — coordinate only. Delegate all code work to implementers.
2. **One task per implementer** — each implementer owns exactly one subtask at a time.
3. **TDD is mandatory** — implementers must write tests before implementation. Reviewer validates.
4. **User approves stories and design** — never proceed past INTAKE or DESIGN without explicit approval.
5. **Worktree isolation for parallel work** — independent subtasks get isolated worktrees.
6. **Respect dependency order** — never assign a subtask until its dependencies are complete.
7. **Escalate, don't loop** — after 3 failed review cycles on the same issue, ask the user.
8. **Clean shutdown** — always shut down teammates and delete the team at completion.

## Artifacts

| File | Content |
|------|---------|
| `.develop/stories.md` | User stories + acceptance criteria |
| `.develop/research.md` | Codebase research findings |
| `.develop/design.md` | Architecture + subtask breakdown |
