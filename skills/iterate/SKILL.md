---
name: iterate
description: Autonomous TDD implementation workflow with phase gates
user_invocable: true
---

## Initialize (REQUIRED)
```bash
python3 ~/.claude/plugins/agent-swarm/lib/iterate_workflow.py $ARGUMENTS
```

## Flow
```
ORCHESTRATE -> [spawn subagents] -> queue empty? -> done
Subagents: test_writing -> implement -> test -> review -> done (kickback on failure)
```

## Phases

| Phase | Purpose | Allowed | Blocked |
|-------|---------|---------|---------|
| orchestrate | Coordinate workers | Read, Task, TaskOutput, TodoWrite | Edit, Write, Bash |
| test_writing | Write tests first | Read, Glob, Grep, Edit, Write, Bash | - |
| implement | Make tests pass | Read, Glob, Grep, Edit, Write, Bash | - |
| test | Run pytest/lint/cov | Read, Glob, Grep, Bash | Edit, Write |
| review | Fix issues | Read, Glob, Grep, Edit, Write, Bash | - |

## Orchestrator Rules

In ORCHESTRATE: spawn subagents for ALL work. No direct implementation.
- 1 task -> 1 agent. N tasks -> N agents in ONE message block (parallel).
- Use `TaskOutput(block=false)` for non-blocking monitoring.
- Insufficient context -> `set-phase intake` to gather context first.

## Task Queue

ALL work flows through the queue. Spawn agents, mark done, push when queue empty.
- No two concurrent agents modify the same file (exclusive ownership).
- Push once per batch, not per task.

## Subagent Prompts Must Include
1. Architectural context (how component fits)
2. Constraints (what NOT to do + why)
3. TDD instruction: write tests FIRST, then implement
4. File scope (exclusive ownership list)
5. Acceptance criteria (machine-checkable)

Never embed file content in prompts. Give intent + criteria.
One agent = complete TDD cycle. Don't split test/implement across agents.

## Kick-back

| Result | Next Phase |
|--------|------------|
| All tests pass | review |
| Coverage low | test_writing |
| Tests/lint fail | implement |
| Review clean | done |
| Review issues | implement |

## CLI
```bash
python3 lib/iterate_workflow.py start "desc" [max_iter]  # Start
python3 lib/iterate_workflow.py status                    # Status
python3 lib/iterate_workflow.py phase                     # Current phase
python3 lib/iterate_workflow.py advance                   # Next phase
python3 lib/iterate_workflow.py test <t> <l> <c>          # Record (1=pass 0=fail)
python3 lib/iterate_workflow.py review <clean>            # Record (1=clean 0=issues)
python3 lib/iterate_workflow.py set-phase <phase>         # Manual override
python3 lib/iterate_workflow.py stop                      # Stop
```

## Exit Conditions
- `orchestration_complete`: queue empty + no active workers
- `review_approved`: review clean
- `max_iterations`: hit limit (default: 5)
- `user_stopped`: manual `/iterate stop`
