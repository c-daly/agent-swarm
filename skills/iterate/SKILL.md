---
name: iterate
description: Autonomous TDD implementation workflow with phase gates.
user_invocable: true
---

# Iterate

## Phases

```
test_writing → implement → test → review
```

| Phase | Purpose | Allowed | Blocked |
|-------|---------|---------|---------|
| test_writing | Write tests first (TDD) | Read, Glob, Grep, Edit, Write, Bash | - |
| implement | Make tests pass | Read, Glob, Grep, Edit, Write, Bash | - |
| test | Run tests + adversary gate | Read, Glob, Grep, Bash | Edit, Write |
| review | Verify quality, commit+push | Read, Glob, Grep, Edit, Write, Bash | - |

## Phase Flow

### test_writing
- Write tests for task requirements
- Cover edge cases
- No implementation yet
- → implement

### implement
- Write code to make tests pass
- Follow existing conventions
- Minimal changes only
- → test

### test
- Run pytest, ruff, coverage
- Call adversary_gate tool (autonomous: analyzes, writes tests, runs them)
- No manual editing — adversary tool writes directly
- Adversary returns: pass/fail + confidence verdict

### review
- Check quality, conventions, correctness
- clean → commit + push → done
- issues → implement

## Adversary Gate

Called during test phase. Autonomous tool that:
1. Analyzes implementation for untested paths, edge cases, boundary conditions
2. Writes adversarial tests directly (agent or heuristic, swappable)
3. Runs them
4. Returns verdict: pass/fail + confidence (weak/strong)

Implementer does not manage the adversary. Reacts to outcomes only.

## Kick-back Table

| Result | → Phase |
|--------|---------|
| all tests pass + confident | review |
| adversary tests fail | implement |
| tests pass + weak suite | test_writing |
| review clean | done (commit+push) |
| review issues | implement |

## CLI

```bash
python3 lib/iterate_workflow.py start "desc" [max_iter]
python3 lib/iterate_workflow.py status
python3 lib/iterate_workflow.py phase
python3 lib/iterate_workflow.py advance
python3 lib/iterate_workflow.py set-phase <phase>
python3 lib/iterate_workflow.py stop
```

## Exit Conditions
- `review_approved`: review clean, committed+pushed
- `max_iterations`: hit limit (default: 5)
- `user_stopped`: manual stop
