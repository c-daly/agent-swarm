---
name: agent-teams-workflow
description: "Coordinate agent teams for multi-domain collaborative implementation from a design doc or plan"
---

# Agent Teams Workflow

Coordinate a team of domain-specialist Claude Code teammates for collaborative implementation work. Each teammate owns a domain (repo, module, layer, or concern), works in its own git worktree, and communicates directly with other teammates at domain boundaries.

**Usage:** `/agent-teams-workflow <path-to-document>`

**Requires:** Agent teams enabled (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in settings.json)

---

## Flow

```
FORM → PLAN → IMPLEMENT → REVIEW → INTEGRATE → DONE
```

You (the lead) coordinate the team. You never implement — use delegate mode throughout.

---

## FORM: Build the Team

### 1. Read the input document

Read the file passed as the argument. It should be a design doc or implementation plan. If the file doesn't exist, report the error and stop.

### 2. Identify domains

Scan the document for natural boundaries. A domain is whatever makes sense for the work — a repo, a directory, a layer (frontend/backend), or a concern (auth/data/API). Each domain becomes one teammate.

### 3. Propose team composition

Present a table to the user:

```
| Teammate | Domain       | Branch                      | Context Summary              |
|----------|--------------|-----------------------------|------------------------------|
| sophia   | sophia repo  | teams/<effort-name>/sophia  | "You own the sophia repo..." |
| hermes   | hermes repo  | teams/<effort-name>/hermes  | "You own the hermes repo..." |
```

**Wait for user approval.** The user can adjust domains, add/remove teammates, or approve. Do not spawn teammates until the user approves.

### 4. Create worktrees

Use `superpowers:using-git-worktrees` to create a worktree per teammate. Branch naming convention: `teams/<effort-name>/<domain>`.

### 5. Spawn teammates

Spawn each teammate with a prompt that includes:

- Their domain and boundaries: "You own `<domain>`. Do not modify files outside this domain."
- The relevant sections of the input document for their domain
- Instruction to start in plan mode: "You must plan before implementing. Submit your plan for approval before writing any code."

### 6. Enable delegate mode

Press Shift+Tab to enter delegate mode. From this point forward, you coordinate only — no implementation.

---

## PLAN: Align Before Building

All teammates start in plan mode. This phase has two rounds.

### Round 1: Independent planning

Each teammate explores their domain and writes a plan covering:
- Tasks they'll tackle
- Files they'll create or modify
- Interfaces they expose to or consume from other domains

**Wait for all plans.** Do not approve any plan until every teammate has submitted one.

### Round 2: Cross-review (interacting domains only)

Identify which domains share interfaces — teammates that expose or consume something from each other. For each interacting pair, ask each teammate to review the other's plan.

Reviewers check for:
- Mismatched assumptions about shared interfaces
- Contract conflicts (types, formats, error handling)
- Missing dependencies between domains

Collect feedback. Share conflicts with the responsible teammates and let them revise. Once all conflicts are resolved, approve all plans. Teammates exit plan mode and begin implementation.

**If no domains interact** (fully independent work), skip Round 2 and approve all plans directly.

---

## IMPLEMENT: Teammates Work, You Coordinate

Stay in delegate mode. Do not implement.

### Teammate responsibilities

- **Claim tasks** from the shared task list and mark them in-progress/completed
- **Message other teammates directly** when reaching a point that affects another domain (shared interface, config format, contract change)
- **Commit regularly** on their feature branch

### Your responsibilities

- **Monitor progress.** Watch for:
  - Teammates going idle (may need new tasks or be stuck)
  - Task status lagging (nudge teammates to update the task list)
  - Scope creep (teammate modifying files outside their domain)
- **Resolve escalations.** If two teammates can't agree on a shared interface, make the call or ask the user.
- **Do not implement.** If you notice work that needs doing, assign it to a teammate.

### Handling blocked work

If teammate B needs something teammate A hasn't finished, B messages A directly. If they can't resolve it:
1. B works on a different task while waiting
2. If no other tasks are available, escalate to the lead (you)
3. You decide: reorder work, reassign, or ask the user

### Phase exit

The phase ends when all tasks in the shared task list are completed and no teammates are actively working.

---

## REVIEW: Verify Integration Boundaries

Boundary review only — teammates review each other's work where their domains interact. Independent domains skip teammate review and rely on automated code review during INTEGRATE.

### Steps

1. **Assign boundary reviews.** Using the boundary map from PLAN (plus any new boundaries discovered during IMPLEMENT), pair teammates whose domains share interfaces. Each reviewer examines the other's branch at the interaction points.

2. **Review criteria:**
   - Do shared interfaces match what was agreed in PLAN?
   - Are contracts honored (types, error handling, formats)?
   - Will the domains integrate cleanly?

3. **Fix cycle.** Route issues to the responsible teammate. Both sides of a boundary confirm the resolution. Re-request review only on changed boundaries, not the full domain.

4. **Phase exit.** All boundary reviews are clean.

**If no domains interact**, skip this phase entirely and move to INTEGRATE.

---

## INTEGRATE: PRs, CI, and Cleanup

### 1. Open PRs

Create one PR per teammate branch. Each PR body includes:
- Summary of work done in that domain
- Boundary review findings (if applicable)
- Links to related PRs from other teammates

### 2. Wait for CI and automated code review

Monitor all PRs for:
- CI pipeline results
- Automated code review feedback

### 3. Teammates fix issues

If CI fails or automated review flags problems on a PR:
- Route the feedback to the relevant teammate
- The teammate fixes on their branch and pushes
- The team stays alive until all PRs are green and review-clean

### 4. Report and clean up

Once all PRs pass, report a summary:

```
| Domain  | PR     | Status | Branch                     |
|---------|--------|--------|----------------------------|
| sophia  | #142   | green  | teams/effort-name/sophia   |
| hermes  | #143   | green  | teams/effort-name/hermes   |
```

Then:
- Shut down all teammates (ask each to shut down gracefully)
- Clean up the team
- Worktrees and branches remain — the user merges PRs through their normal process

---

## Rules

1. **Always use delegate mode** — the lead never implements, only coordinates.
2. **One teammate per domain** — no shared ownership of files or directories.
3. **Plan before implementing** — all teammates must have approved plans before writing code.
4. **Communicate at boundaries** — teammates message each other directly about shared interfaces.
5. **Boundary review, not full review** — teammate reviews focus on integration points. Automated review handles single-domain quality.
6. **Team stays alive through INTEGRATE** — teammates fix CI and review issues with full context.
7. **User approves team composition** — never spawn teammates without explicit user approval.

## Required Sub-Skills

- `superpowers:using-git-worktrees` (FORM phase — worktree creation)
