---
name: experiment
description: Autonomous experiment workflow with eval gates, journal memory, and team support.
user_invocable: true
---

# Experiment

Ticket-driven autonomous experiment workflow. Read a ticket, plan an approach, execute, eval, journal what you learn, iterate until success criteria are met.

## Phase Flow

```
read -> plan -> work -> eval -> review -> journal -> decide
                 ^                |                    |
                 +--- kickback ---+                    |
                 ^                                     |
                 +------------- kickback --------------+
                                                       |
                                                       +-> done
```

| Phase | Purpose | Allowed | Blocked |
|-------|---------|---------|---------|
| read | Load goal.yaml, constraints, journal | Read, Glob, Grep | Write, Edit, Bash |
| plan | Form hypothesis, decide approach | Read, Glob, Grep, Web | Write, Edit, Bash |
| work | Execute plan (solo or team) | Read, Write, Edit, Bash | eval/** files |
| eval | Run eval, parse metrics | Read, Bash(pytest/python) | Write, Edit |
| review | Code quality and security review | Read, Glob, Grep, Bash(pytest/ruff) | Write, Edit |
| journal | Record results and learnings | Read, Write(journal/) | Bash |
| decide | Check criteria, kickback or done | Read | Write, Edit, Bash |

## Protocol

### 1. Read
- Load `goal.yaml` — defines objective, success criteria, eval path
- Load `constraints.yaml` if present — time limits, do-not-do, escalation triggers
- Read all journal entries — prior attempts and learnings
- Set execution mode in workflow state: standalone or integration
- Set environment in workflow state: local (default) or from goal.yaml

### 2. Plan
- Review journal for failed approaches — **never repeat without a new hypothesis**
- Review constraints for forbidden approaches and known findings
- Form a hypothesis and plan of attack
- Decide execution strategy:
  - **Solo**: single agent works sequentially
  - **Team**: spawn agents for independent parallel tracks
  - **Fan-out**: test N hypotheses simultaneously, pick best result
- Store hypothesis in workflow state: `workflow_set_value(wf_id, "current_hypothesis", ...)`

### 3. Work
- **Standalone mode**: work in `experiments/<name>/workspace/`
- **Integration mode**: work in git worktree on target repo
- For fan-out: coordinator spawns N agents in isolated worktrees, each testing a different approach
- Eval scripts (`experiments/*/eval/**`) are **never writable** in any mode
- Teams: use `TeamCreate`, `SendMessage`, standard agent-swarm patterns

### 4. Eval
- Run eval specified in goal.yaml
- Pytest evals: `python -m pytest <eval_path> -v -s`
- Custom evals: `python <eval_script>`
- Parse metrics from output (`[METRIC] key=value` format)
- Store results: `workflow_set_value(wf_id, "last_eval_metrics", ...)`
- If eval crashes (not failure — error): kickback to work to fix

### 5. Review
- Spawn the `reviewer` agent on the changes made during work phase
- Reviewer runs `pytest` and `ruff check .`, checks for side-effects, security issues, test coverage
- Reviewer outputs a verdict: **APPROVED** or **CHANGES_REQUESTED** with issues list
- Store verdict: `workflow_set_value(wf_id, "review_verdict", ...)`
- **APPROVED** -> advance to journal
- **CHANGES_REQUESTED** -> kickback to work with review findings as context

### 6. Journal
- Write a journal entry recording:
  - Hypothesis tested
  - Changes made
  - Eval results
  - Diagnosis of why it did or didn't work
  - Next direction (if applicable)
- Journal entries are append-only, numbered, never modified
- For fan-out: journal ALL approaches tested, not just the best one

### 7. Decide
- Coordinator checks metrics against success criteria from goal.yaml
- **Primary criterion met** -> advance to done
- **Not met** -> kickback to plan with accumulated journal context
- Check constraints: if escalation conditions are met, stop workflow and alert user
- Check iteration count: if max reached, stop with `exit_reason: max_iterations`

## Kickback Table

| From | To | Condition |
|------|----|-----------|
| eval | work | Eval crashed (import error, script error) |
| review | work | Verdict is CHANGES_REQUESTED |
| decide | plan | Success criteria not met |
| decide | done | Primary success criterion met |

## Execution Modes

Determined by `goal.yaml` during read phase:

- **Standalone** (`target:` absent): agent works in `workspace/` directory
- **Integration** (`target:` present): workflow creates git worktree on target repo

## Execution Environments

Determined by `goal.yaml` `environment:` field:

- **local** (default): work runs on this machine
- Extensible: remote backends can be registered (RunPod, Modal, etc.)

## Team Support

For complex experiments, the coordinator can:
1. Spawn researcher agents during plan phase for literature/codebase exploration
2. Spawn implementer agents during work phase for parallel hypothesis testing
3. Each agent gets an isolated worktree
4. All agents share the journal as coordination memory

Fan-out pattern for parallel hypothesis testing:
```
coordinator (plan): identifies N approaches worth trying
coordinator (work): spawns N agents, each in own worktree
coordinator (eval): runs eval on each agent's result
coordinator (review): reviewer checks code quality
coordinator (journal): journals ALL results
coordinator (decide): picks best, or kickback to plan with all learnings
```

## Constraints Enforcement

| Constraint | Enforcement |
|------------|-------------|
| `time_limits.max_hours_per_run` | Workflow tracks elapsed time, auto-stops |
| `do_not_do` | Injected as context in plan phase |
| `escalate_if` | Checked in decide phase, stops workflow if triggered |
| `known_findings` | Injected as context in plan phase |
| Eval immutability | `experiments/*/eval/**` blocked in all write-capable phases |

## CLI

```bash
python3 lib/experiment_workflow.py start <experiment_dir> "description" [--max-iterations N]
python3 lib/experiment_workflow.py status
python3 lib/experiment_workflow.py phase
python3 lib/experiment_workflow.py advance <phase>
python3 lib/experiment_workflow.py stop
```

## Exit Conditions
- `success`: primary success criterion met
- `max_iterations`: hit iteration limit
- `escalation`: constraints escalation condition triggered
- `user_stopped`: manual stop
