---
name: parallel-orchestrate
description: "Orchestrate N independent TDD subagents from a YAML task manifest with worktree isolation"
user_invocable: true
---

# Parallel Orchestrate

Orchestrate N independent TDD subagents from a YAML task manifest. Each subagent works in its own git worktree (isolated directory + branch), writes tests first, implements until green, then commits. You monitor progress, retry failures, merge branches, and verify the full suite.

## Inputs

You need two things:
- **`<manifest.yaml>`** — path to the YAML task manifest
- **`<cwd>`** — workspace root (e.g., `~/projects/LOGOS`). The orchestrator resolves `project_dir` relative to this.

## Initialize

```bash
python3 lib/orchestrator.py load <manifest.yaml>
python3 lib/orchestrator.py start <manifest.yaml> <cwd>
```

The `start` command creates a git worktree per task under `{project_dir}/.worktrees/{project}/`, so each subagent gets an isolated directory with its branch already checked out. No branch conflicts when running in parallel.

## Flow

```
LOAD → START → SPAWN → MONITOR → MERGE → VERIFY → COMPLETE → STOP
                 ↑         |                |
                 └── RETRY ─┘          (fail: fix/rollback/continue)
         (blocked tasks wait for dependencies)
```

### Phase 1: SPAWN
Get pending tasks:

```bash
python3 lib/orchestrator.py pending <manifest.yaml> --json
```

This returns a JSON array. For each entry, register the worker, then
spawn it using the **Agent tool** (the spawn protocol — see
`skills/spawn/SKILL.md`):

- `reg = router__register_agent(agent_id="<task_name>-w<n>", agent_type="implementer", roles=["editor", "shell_full"])`
- Use `subagent_type: "implementer"` — never a native type
  (`general-purpose`/`Explore`/`Plan`): native types have no router
  access and will flail
- `prompt`: `reg["briefing"] + "\n\n" +` the `prompt` field verbatim —
  the briefing carries the worker's identity/caller-id; the prompt
  already contains worktree paths and "do NOT switch branches"
  instructions
- The `worktree_dir` field tells you where the subagent will work (for your reference)
- Run subagents **in parallel** — worktrees give each one an isolated directory

After spawning each subagent, record it:

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
python3 lib/orchestrator.py merge <manifest.yaml> <cwd>
```

### Phase 4: VERIFY
Run full suite verification:

```bash
python3 lib/orchestrator.py verify <manifest.yaml> <cwd>
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

3. Stop orchestration (cleans up worktrees):

```bash
python3 lib/orchestrator.py stop <manifest.yaml> <cwd>
```

### Summary
Generate a markdown summary at any point:

```bash
python3 lib/orchestrator.py summary <manifest.yaml>
```

### Stop
Stop orchestration (cleans up worktrees):

```bash
python3 lib/orchestrator.py stop <manifest.yaml> <cwd>
```

## CLI Reference

| Command | Args | Description |
|---------|------|-------------|
| `load` | `<manifest.yaml>` | Parse manifest, show task count |
| `start` | `<manifest.yaml> <cwd>` | Initialize state, create worktrees, set all tasks pending |
| `pending` | `<manifest.yaml> [--json]` | Show pending SpawnRequests (use `--json` for structured output) |
| `spawned` | `<manifest.yaml> <task> <worker>` | Record task spawn |
| `complete` | `<manifest.yaml> <task> [error]` | Record completion (error = failure) |
| `status` | `<manifest.yaml>` | Show JSON state |
| `merge` | `<manifest.yaml> <cwd>` | Merge completed branches |
| `verify` | `<manifest.yaml> <cwd>` | Run full test suite |
| `summary` | `<manifest.yaml>` | Markdown summary table |
| `stop` | `<manifest.yaml> <cwd>` | Deactivate orchestration, remove worktrees |

## Manifest Format

```yaml
project: my-project          # Project name (used for state file)
base_branch: main             # Branch to create task branches from
max_retries: 2                # Max retry attempts per task
project_dir: .                # Git repo root relative to cwd (default: ".")

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

When `project_dir` is set (e.g., `hermes`), paths in `target_dir` / `test_dir` should be relative to `cwd` (e.g., `hermes/src/feature`). The orchestrator strips the prefix in worktree prompts automatically.

## Rules

1. **Never skip TDD** — subagents must write tests FIRST
2. **One branch per task** — no cross-task file modifications
3. **Retry before failing** — exhaust max_retries before marking failed
4. **Merge order matters** — merge in topological order to minimize conflicts
5. **Verify after merge** — always run full suite after merging all branches
6. **Don't modify subagent branches** — only subagents write to their branches
7. **Subagents do NOT manage branches** — worktrees handle isolation; subagents must not create or switch branches
8. **Use `--json` for automation** — when calling `pending` programmatically, use `--json` for reliable parsing

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