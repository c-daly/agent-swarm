---
name: parallel-orchestrate
description: "Orchestrate N independent TDD subagents from a YAML task manifest with branch isolation"
---

# Parallel Orchestrate

Orchestrate N independent TDD subagents from a YAML task manifest. Each subagent works on its own git branch, writes tests first, implements until green, then commits. You monitor progress, retry failures, merge branches, and verify the full suite.

## Initialize

```bash
python3 lib/orchestrator.py load <manifest.yaml>
python3 lib/orchestrator.py start <manifest.yaml>
```

## Flow

```
LOAD → START → SPAWN → MONITOR → MERGE → VERIFY → COMPLETE → DONE
                 ↑         |                |
                 └─ RETRY ─┘          (fail: fix/rollback/continue)
         (blocked tasks wait for dependencies)
```

### Phase 1: SPAWN
Get pending tasks and spawn subagents:

```bash
python3 lib/orchestrator.py pending <manifest.yaml>
```

For each SpawnRequest, use the Task tool to launch a subagent:
- Use `subagent_type: "general-purpose"`
- Pass the `prompt` from the SpawnRequest verbatim
- Record the spawn:

```bash
python3 lib/orchestrator.py spawned <manifest.yaml> <task_name> <worker_id>
```

### Phase 2: MONITOR
When a subagent completes, record the result:

```bash
# Success
python3 lib/orchestrator.py complete <manifest.yaml> <task_name>

# Failure (include error message)
python3 lib/orchestrator.py complete <manifest.yaml> <task_name> "error message"
```

Check status:
```bash
python3 lib/orchestrator.py status <manifest.yaml>
```

If result is "retrying", go back to SPAWN phase for that task.

### Phase 3: MERGE
Once all tasks are completed/failed, merge branches:

```bash
python3 lib/orchestrator.py merge <manifest.yaml> <project_cwd>
```

### Phase 4: VERIFY
Run full suite verification:

```bash
python3 lib/orchestrator.py verify <project_cwd>
```

**If verification fails**, present these options to the user:

1. **Fix and retry** — Investigate failures, apply fixes on the current branch, and re-run verification
2. **Rollback** — Undo the merge and report which tasks caused conflicts
3. **Continue anyway** — Accept the failures and proceed to completion

### Phase 5: COMPLETION
After verification passes (or user chose "continue anyway"):

1. Generate the final summary:

```bash
python3 lib/orchestrator.py summary <manifest.yaml>
```

2. Hand off to `superpowers:finishing-a-development-branch` to decide how to integrate the work (merge, PR, or cleanup). This is a **REQUIRED SUB-SKILL** — do not skip.

3. Stop orchestration:

```bash
python3 lib/orchestrator.py stop <manifest.yaml>
```

### Summary
Generate a markdown summary at any point:

```bash
python3 lib/orchestrator.py summary <manifest.yaml>
```

### Stop
Stop orchestration:

```bash
python3 lib/orchestrator.py stop <manifest.yaml>
```

## CLI Reference

| Command | Args | Description |
|---------|------|-------------|
| `load` | `<manifest.yaml>` | Parse manifest, show task count |
| `start` | `<manifest.yaml>` | Initialize state, set all tasks pending |
| `pending` | `<manifest.yaml>` | Show pending SpawnRequests with prompts |
| `spawned` | `<manifest.yaml> <task> <worker>` | Record task spawn |
| `complete` | `<manifest.yaml> <task> [error]` | Record completion (error = failure) |
| `status` | `<manifest.yaml>` | Show JSON state |
| `merge` | `<manifest.yaml> <cwd>` | Merge completed branches |
| `verify` | `<cwd>` | Run full test suite |
| `summary` | `<manifest.yaml>` | Markdown summary table |
| `stop` | `<manifest.yaml>` | Deactivate orchestration |

## Manifest Format

```yaml
project: my-project          # Project name (used for state file)
base_branch: main             # Branch to create task branches from
max_retries: 2                # Max retry attempts per task

tasks:
  - name: feature-name        # Unique task identifier
    description: |             # What to implement
      Detailed description...
    target_dir: src/feature    # Implementation directory
    test_dir: tests/feature    # Test directory
    min_tests: 10              # Minimum test functions required
    branch_name: custom/name   # Optional (defaults to task/<name>)
    depends_on:                # Optional: tasks that must complete first
      - other-task-name
```

## Rules

1. **Never skip TDD** — subagents must write tests FIRST
2. **One branch per task** — no cross-task file modifications
3. **Retry before failing** — exhaust max_retries before marking failed
4. **Merge order matters** — merge in manifest order to minimize conflicts
5. **Verify after merge** — always run full suite after merging all branches
6. **Don't modify subagent branches** — only subagents write to their branches

## Dependencies

Tasks can declare dependencies with `depends_on`. A task won't be spawned until all its dependencies are `completed`.

- If a dependency fails (exhausts retries), all tasks that depend on it are automatically marked `failed`
- Branches are merged in topological order (dependencies first)
- Circular dependencies are rejected at parse time

Example: `setup -> feature-a -> integration`

```yaml
tasks:
  - name: setup
    description: Initialize project
    target_dir: src
    test_dir: tests
  - name: feature-a
    description: Build feature A
    target_dir: src/a
    test_dir: tests/a
    depends_on: [setup]
  - name: integration
    description: Integration tests
    target_dir: src/int
    test_dir: tests/int
    depends_on: [feature-a]
```
