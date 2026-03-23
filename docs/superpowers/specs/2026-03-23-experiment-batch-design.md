# Experiment Batch — Design Spec

## Problem

`/experiment` runs a single ticket. To run autonomously across multiple tasks, the agent needs:
1. A way to discover which tasks to work on
2. A single directory per run, not per-task
3. Lightweight structure — per-task subdirectories only when needed

## Goal.yaml Structure

A batch goal.yaml defines a run — one directory, N tasks.

### Query-based discovery

```yaml
query: "repo:c-daly/agora label:experiment-ready is:open"

success_criteria:
  - metric: test_pass_rate
    threshold: 1.0
    primary: true
```

The agent resolves the query via GitHub search (`search_issues` MCP tool) at run time. The query uses standard GitHub search syntax — labels, milestones, projects, assignees, date ranges, etc.

### Explicit task list

```yaml
tasks:
  - issue: 42
  - issue: 43
  - issue: 44

success_criteria:
  - metric: test_pass_rate
    threshold: 1.0
    primary: true
```

### Inline task definitions

```yaml
tasks:
  - target: agora/adapters/sec_ftd_adapter.py
    objective: "Build SEC FTD adapter..."
  - target: agora/adapters/treasury_adapter.py
    objective: "Build Treasury adapter..."

success_criteria:
  - metric: test_pass_rate
    threshold: 1.0
    primary: true
```

### Mixed (query + explicit)

```yaml
query: "repo:c-daly/agora label:experiment-ready is:open"
tasks:
  - target: agora/analysis/yield_curve.py
    objective: "Build yield curve analysis..."

success_criteria:
  - metric: test_pass_rate
    threshold: 1.0
    primary: true
```

Query results are merged with explicit tasks. Duplicates (same issue number or same target) are deduplicated.

## Directory Layout

```
experiments/<run-name>/
  goal.yaml          # batch definition: query/task list + run-level defaults
  constraints.yaml   # optional, run-level defaults
  journal/           # run-level journal (append-only, numbered entries)
  tasks/             # per-task subdirs, always created during resolve
    <task-id>/
      goal.yaml      # this task's objective, target, success_criteria, eval
      eval/          # eval scripts for this task (if needed)
      constraints.yaml  # task-specific constraints (if needed)
```

The run-level goal.yaml stays small — just the query and defaults. During the resolve phase, each task gets its own `tasks/<id>/goal.yaml` generated from the GitHub issue or inline definition. This keeps the run-level file from growing with task count.

Per-task goal.yaml inherits run-level defaults (success_criteria, constraints) and can override them. Per-task eval/ and constraints.yaml are optional — tasks without them use the run-level defaults.

## Task Resolution

### From GitHub issues

The agent calls `search_issues` with the query, then for each issue:
1. Reads issue fields (the agora-task template maps 1:1 to goal.yaml fields)
2. Creates `tasks/<issue-number>/goal.yaml` with: objective, target, success_criteria, eval, environment
3. If the issue has custom eval scripts, places them in `tasks/<issue-number>/eval/`
4. Fields not specified in the task goal.yaml inherit from the run-level goal.yaml

### From explicit tasks

Inline task definitions are used directly. Issue references (e.g., `issue: 42`) are resolved via `issue_read` MCP tool.

### From local directory (fallback)

```yaml
query: "dir:experiments/*/goal.yaml"
```

Globs for goal.yaml files, each becomes a task. This preserves backward compatibility with the per-ticket structure.

## Execution

### Flow

```
resolve → execute tasks → gate: all task evals pass → integration eval → journal → report
```

1. **Resolve**: Run query, build task list, deduplicate, create per-task goal.yaml files.
2. **Execute tasks**: For each task, run the experiment workflow (read → plan → work → eval → review). Independent tasks run in parallel. Tasks share the run directory unless they need isolation (conflicting target files → worktrees).
3. **Task eval gate**: ALL task-level evals must pass before proceeding. If any task eval fails, kickback to that task — do not attempt integration. This is a hard gate, not a soft check.
4. **Integration eval**: Run the run-level eval (`eval/` in the run directory). These are integration tests that verify tasks work together. Only runs once every task is individually green.
5. **Integration kickback**: If integration eval fails, identify which task's interface is the likely cause (from the traceback/error) and kickback to the earliest dependency in the chain.
6. **Journal**: Append run-level journal entries. Each task's result is recorded: task ID, hypothesis, outcome, metrics.
7. **Report**: Summary of all tasks — passed, failed, skipped.

### Eval hierarchy

```
tasks/<id>/eval/   →  unit tests per task (must ALL pass first)
eval/              →  integration tests across tasks (runs last)
```

Task evals gate integration eval. Integration eval is optional — runs without one are complete when all task evals pass.

### Run completion

When a run completes (all tasks pass + integration eval passes, or `on_failure: stop` triggered):

1. Agent comments on each GitHub issue with results (if tasks came from GitHub)
2. Agents do NOT close issues or merge code — humans decide what ships
3. Run directory is renamed to signal completion:
   ```
   experiments/sprint-1/  →  experiments/sprint-1.done/
   ```
   This prevents re-processing on subsequent runs. The directory retains its journal and results for reference until manually deleted.

### Parallelism

Tasks are independent by default. The agent spawns parallel experiment runners for independent tasks. Tasks that modify the same target file are serialized automatically.

### Failure handling

Configurable via goal.yaml:

```yaml
on_failure: continue  # default: keep going with remaining tasks
# or
on_failure: stop      # halt batch on first failure
```

### Dependencies

Optional, specified per-task:

```yaml
tasks:
  - issue: 42
    id: treasury_adapter
  - issue: 43
    id: yield_curve
    depends_on: [treasury_adapter]
```

Tasks with unmet dependencies are deferred until prerequisites pass. If a prerequisite fails, dependent tasks are skipped.

## Journal Format

Run-level journal, not per-task:

```markdown
# Journal Entry 001 — Task: SEC FTD Adapter (#42)

**Hypothesis:** ...
**Changes:** ...
**Eval:** test_pass_rate=1.0000 (18/18)
**Review:** APPROVED
**Result:** SUCCESS
```

Entries are numbered sequentially across the whole run.

## Skill Interface

```bash
# Query-based
/experiment-batch experiments/sprint-1/

# The goal.yaml in that directory defines the query/tasks
```

The skill reads goal.yaml from the provided directory, resolves tasks, and runs them.

## Backward Compatibility

The existing per-ticket structure (`experiments/<name>/goal.yaml` with eval/ and journal/ per ticket) still works with `/experiment`. The batch skill is a new layer on top — it discovers and orchestrates multiple `/experiment` runs.

For the `dir:` query type, each discovered per-ticket goal.yaml becomes a task in the batch.
