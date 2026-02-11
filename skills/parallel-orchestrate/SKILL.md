---
name: parallel-orchestrate
description: Spawn N independent subagents from a YAML manifest with TDD discipline and git branch isolation
user_invocable: true
---

## Initialize (REQUIRED)
```bash
python3 ~/.claude/plugins/agent-swarm/lib/parallel_orchestrate.py load $ARGUMENTS
```

## Flow
```
load_manifest → spawn_agents → monitor → merge → verify → done
                    ^              |
                    +--- retry ----+
```

Each subagent internally follows: `branch_create → test_writing → implement → test → commit → done`

## Phases

| Phase | Purpose | Actions |
|-------|---------|---------|
| load_manifest | Parse YAML manifest, validate fields | Read manifest, create task objects |
| spawn_agents | Create subagents for pending tasks | Build prompts, spawn via worker_pool |
| monitor | Track subagent progress | Poll status, handle completions/retries |
| merge | Merge completed branches | `git merge --no-ff task/<name>`, delete branch |
| verify | Run full test suite | `pytest` on merged base |
| done | Terminal | Generate summary |

## Gateway Conditions

| Condition | Checks | Used At |
|-----------|--------|---------|
| `branch_exists` | `git branch --list task/<name>` non-empty | Before test_writing (subagent) |
| `tests_written` | Test file has `min_tests`+ `def test_` functions | Before implement (subagent) |
| `all_tests_pass` | `pytest <path>` exits 0 | Before commit (subagent) |
| `all_branches_merged` | No `task/*` branches remain | Before verify |
| `full_suite_passes` | `pytest` on merged base exits 0 | Before done |

## Manifest Format

```yaml
name: my-project
base_branch: dev
max_agents: 3       # max concurrent subagents
max_retries: 2      # per-task retry limit
tasks:
  - name: feature_x
    module_path: src/feature_x.py
    test_path: tests/test_feature_x.py
    description: "Description of what to implement"
    min_tests: 10
```

**Required fields per task:** `name`, `module_path`, `test_path`, `description`
**Optional:** `min_tests` (default: 1)

## CLI

```bash
# Load and validate a manifest
python3 lib/parallel_orchestrate.py load config/manifests/demo_data_structures.yaml

# Check current status
python3 lib/parallel_orchestrate.py status

# Print summary table
python3 lib/parallel_orchestrate.py summary
```

## Retry Logic

- On subagent failure: re-enqueue task with error context injected into description
- Retry count tracked per task
- After `max_retries` exceeded: task marked as `failed`, orchestration continues with remaining tasks

## Orchestrator Rules

- Spawn up to `max_agents` concurrent subagents
- Each subagent gets exclusive file ownership (module_path + test_path)
- Subagents create `task/<name>` branches, never modify base branch
- Merge phase uses `--no-ff` to preserve branch history
- Merge conflicts kick back to monitor phase for re-work
- Full suite must pass on merged base before marking done
