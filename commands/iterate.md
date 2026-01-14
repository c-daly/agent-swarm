---
name: iterate
description: Autonomous TDD implementation workflow with phase gates
arguments:
  - name: --max
    description: Maximum iterations before forced exit (default 5)
    required: false
allowed_tools:
  - Edit
  - Write
  - Bash
  - Read
  - Glob
  - Grep
  - Task
  - TodoWrite
  - AskUserQuestion
  - mcp__plugin_serena_serena__*
  - mcp__plugin_greptile_greptile__*
---

# /iterate - TDD Implementation Workflow

You are now in **iterate mode** - a TDD development loop with phase gates.

## Initialize

```bash
python3 ~/.claude/plugins/agent-swarm/lib/iterate_workflow.py start "$ARGUMENTS" ${--max:-5}
```

## Phases

| Phase | Purpose | What to Do |
|-------|---------|------------|
| **test_writing** | Write tests first | Create failing tests that define expected behavior |
| **implement** | Make tests pass | Write code until tests pass |
| **test** | Verify everything | Run pytest, lint, coverage. Record results. |
| **review** | Fix review issues | Address Greptile comments |

## Phase Flow

```
test_writing → implement → test → review → done
      ↑            ↑         |       |
      |            |         v       v
      +-- coverage +-- fail -+  issues
```

## Per-Phase Instructions

### test_writing
1. Write tests that define expected behavior
2. Tests should FAIL initially (TDD red)
3. When done: `python3 lib/iterate_workflow.py advance`

### implement
1. Write/modify code to make tests pass
2. Commit changes frequently
3. When done: `python3 lib/iterate_workflow.py advance`

### test (NO EDITING ALLOWED)
Run verification, then record results:
```bash
# Run tests
pytest tests/ -v

# Run lint
ruff check .

# Run coverage
pytest --cov=. --cov-report=term-missing

# Record results (1=pass, 0=fail)
python3 lib/iterate_workflow.py test <tests> <lint> <coverage>

# Advance (kick-back or proceed)
python3 lib/iterate_workflow.py advance
```

### review
1. Push to remote (triggers Greptile)
2. Check for review comments
3. Fix any issues found
4. Record: `python3 lib/iterate_workflow.py review <1=clean|0=issues>`
5. Advance: `python3 lib/iterate_workflow.py advance`

## Phase Banners

Output at START of each phase:
```
[ITERATE] ═══════════════════════════════════════════════════════════════
  Phase: <PHASE_NAME> | Iteration: <N>/<MAX>
  Task: <brief task description>
═══════════════════════════════════════════════════════════════════════
```

Output at END of each phase:
```
[ITERATE] Phase complete: <PHASE_NAME>
  <summary of what was done>
  Advancing to: <NEXT_PHASE>
```

## Check Status

```bash
python3 ~/.claude/plugins/agent-swarm/lib/iterate_workflow.py status
```

## Exit Conditions

- `review_approved` - Review clean, workflow complete
- `max_iterations` - Hit limit (default: 5)
- `user_stopped` - User ran `/iterate stop`

## DO NOT

- Skip phases (follow the order)
- Use Edit/Write in test phase (blocked by hook)
- Ignore kick-back logic
- Bypass verification
