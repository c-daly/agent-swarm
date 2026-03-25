---
name: experiment-batch
description: "Discover and run multiple experiment tasks from a query or manifest"
user_invocable: true
---

# Experiment Batch

Discover multiple tasks, resolve them into per-task goal.yaml files, run experiments, gate integration eval on all task evals passing.

## Usage

`/experiment-batch <run-directory>`

The run directory must contain a `goal.yaml` with a `query` and/or `tasks` field.

## Protocol

### 1. Read

Load `<run-dir>/goal.yaml`. Parse with `batch_resolver.parse_batch_goal()`.

### 2. Resolve

Build the task list:

**If `query` starts with `dir:`:**
- Glob for goal.yaml files, each becomes a task

**If `query` is a GitHub search string:**
- Call `search_issues` MCP tool with the query
- For each issue, call `issue_read` to get full fields
- Parse issue body fields (agora-task template maps 1:1 to goal.yaml)
- Add to task list

**If `tasks` is set:**
- Inline definitions used directly
- Issue references resolved via `issue_read`

Merge query results with explicit tasks. Deduplicate by target path or issue number.

Call `batch_resolver.resolve_tasks()` to create per-task directories with goal.yaml files.

Sort by dependencies via `batch_resolver.sort_by_dependencies()`.

Report resolved task list to user.

### 3. Execute Tasks

For each task (respecting dependency order, parallelizing independent tasks):

1. Start an experiment workflow for the task: `workflow_start("experiment", {task_id, ...})`
2. Advance through ALL phases — the daemon enforces transitions:
   - `read` → `plan` → `work` (dispatch registered implementer)
   - `work` → `eval` (run tests, verify ruff passes)
   - `eval` → `review` (dispatch registered reviewer with goal.yaml objective)
   - `review` requires checkpoint: reviewer must store verdict via `workflow_set_value`
   - `review` → `journal` ONLY after `workflow_pass_checkpoint` with APPROVED verdict
   - `journal` → `decide` → next task or done
3. A task is NOT complete until its workflow reaches the `done` phase
4. The orchestrator CANNOT skip phases, declare tasks done early, or bypass the workflow

**Hard rules:**
- Every implementer must be registered via `prepare_dispatch`
- Every reviewer must be registered via `prepare_dispatch`
- The reviewer prompt must include the task objective and constraints for spec compliance checking
- `workflow_pass_checkpoint` will REJECT if no verdict is stored or verdict is CHANGES_REQUESTED
- Ruff must pass — the reviewer checks this and flags F821/F811 as CRITICAL

If a task fails review and `on_failure: continue`, skip it and proceed. If `on_failure: stop`, halt the batch.

### 4. Task Eval Gate

After all tasks have been attempted:
- Check that ALL task evals passed
- If any failed, report which tasks failed and stop — do not run integration eval
- This is a hard gate, not a soft check

### 5. Integration Eval (optional)

If `<run-dir>/eval/` exists:
- Run: `python -m pytest <run-dir>/eval/ -v -s`
- Parse [METRIC] from output
- If integration fails, identify the likely task from the traceback and kickback to earliest dependency

If no run-level eval/ exists, skip this step.

### 6. Report

Summary table:

| Task | Status | Tests | Notes |
|------|--------|-------|-------|
| #42 sec_ftd | PASS | 18/18 | |
| #43 treasury | PASS | 21/21 | |
| Integration | PASS | 5/5 | |

The agent's job ends at reporting. It does NOT close issues, merge code, or archive the directory. Archiving is a human action.

## Eval Hierarchy

```
tasks/<id>/eval/   →  unit tests per task (must ALL pass first)
eval/              →  integration tests across tasks (runs last, optional)
```

Task evals gate integration eval.

## Run Completion

When the run finishes:
1. Agent comments on each GitHub issue with results (if tasks came from GitHub)
2. Agents do NOT close issues, merge code, or archive the run directory
3. When the human is satisfied, they rename the directory (e.g., `sprint-1` → `sprint-1.done/`)
