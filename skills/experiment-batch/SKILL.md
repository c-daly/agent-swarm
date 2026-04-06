---
name: experiment-batch
description: Discover and run multiple experiment tasks from a query or manifest
user_invocable: true
---

# Experiment Batch

Discover multiple tasks, group them into execution units, generate eval tests per group, run experiments, gate on eval pass.

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

### 3. Group

Call `batch_resolver.group_tasks()` to organize tasks into execution units.

Grouping strategies (auto-detected):
- **Epic labels** on GitHub issues → group by epic
- **Explicit `group` field** in task definitions → group by field
- **No grouping available** → flat (each task is its own unit)

Within each group, tasks are ordered by component dependency:
`adapter/glossary → analysis/quant → api → frontend/app-shell`

Report the group structure to the user.

### 4. Execute Groups

For each group (can pipeline — generate eval for next group while current executes):

#### 4a. Generate eval tests for the group

Run experiment-setup (Steps 2-5) for each task in the group:
- Generate per-task eval tests from the spec and interface contracts
- Generate group-level integration eval that tests the vertical slice (adapter → analysis → API flow)
- Store in `tasks/<id>/eval/` and `groups/<name>/eval/`

The gateway condition `eval_tests_exist` blocks advancing to work phase without eval tests.

#### 4b. Execute tasks within the group

Respecting component dependency order within the group, parallelizing independent tasks:

1. Start an experiment workflow for the task: `workflow_start("experiment", {task_id, ...})`
2. Advance through ALL phases — the daemon enforces transitions:
   - `read` → `plan` → `work` (dispatch registered implementer)
   - `work` → `eval` (run eval tests, verify ruff passes)
   - `eval` → `review` (dispatch registered reviewer with goal.yaml objective)
   - `review` requires checkpoint: reviewer must store verdict via `workflow_set_value`
   - `review` → `journal` ONLY after `workflow_pass_checkpoint` with APPROVED verdict
   - `journal` → `decide` → next task or done
3. A task is NOT complete until its workflow reaches the `done` phase

**Hard rules:**
- Every implementer must be registered via `prepare_dispatch`
- Every reviewer must be registered via `prepare_dispatch`
- Use `agent-swarm:reviewer` agent type for reviews (requires Bash access)
- The reviewer prompt must include the task objective and constraints for spec compliance checking
- `workflow_pass_checkpoint` will REJECT if no verdict is stored or verdict is CHANGES_REQUESTED
- Ruff must pass — the reviewer checks this and flags F821/F811 as CRITICAL

#### 4c. Group eval gate

After all tasks in a group complete:
- Run group-level integration eval (if exists)
- If any task failed and `on_failure: continue`, note it and proceed
- If `on_failure: stop`, halt the batch

### 5. Integration Eval

After all groups have been executed:
- Run `<run-dir>/eval/` integration tests (if exists)
- Parse [METRIC] from output
- If integration fails, identify the likely group/task from the traceback

### 6. Report

Summary table:

| Group | Task | Status | Tests | Notes |
|-------|------|--------|-------|-------|
| short-intel | #9 yahoo_quotes | PASS | 8/8 | |
| short-intel | #13 short_composite | PASS | 12/12 | |
| short-intel | Integration | PASS | 3/3 | |
| Full Integration | | PASS | 5/5 | |

The agent's job ends at reporting. It does NOT close issues, merge code, or archive the directory.

## Eval Hierarchy

```
tasks/<id>/eval/       →  per-task tests (interface contract)
groups/<name>/eval/    →  group integration tests (vertical slice)
eval/                  →  full integration tests (all groups)
```

Each level gates the next.

## Run Completion

When the run finishes:
1. Agent comments on each GitHub issue with results (if tasks came from GitHub)
2. Agents do NOT close issues, merge code, or archive the run directory
3. When the human is satisfied, they rename the directory (e.g., `run-2` → `run-2.done/`)
