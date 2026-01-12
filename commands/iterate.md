---
name: iterate
description: Autonomous implementation workflow with TDD and Greptile review
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

# /iterate - Autonomous Implementation Workflow

You are now in **iterate mode** - an autonomous implementation workflow.

## CRITICAL: Phase Output Requirements

**At the START of each phase, output a clear banner:**

```
[ITERATE] ═══════════════════════════════════════════════════════════════
  Phase: <PHASE_NAME> | Iteration: <N>/<MAX>
  Task: <brief task description>
═══════════════════════════════════════════════════════════════════════
```

**At the END of each phase, output completion:**

```
[ITERATE] Phase complete: <PHASE_NAME>
  <summary of what was done>
  Advancing to: <NEXT_PHASE>
```

**This is MANDATORY. The user must be able to see discrete phase transitions.**

## Workflow Initialization

Initialize the workflow state:

```bash
python3 ~/.claude/plugins/agent-swarm/lib/workflow.py iterate
```

Then immediately output the phase banner.

## Phases

1. `test_writing` - Write failing tests first
2. `implement` - Write code to make tests pass
3. `test` - Run tests and fix failures
4. `coverage` - Check coverage, add tests if needed
5. `review` - Trigger Greptile review and address feedback

## Phase Execution Pattern

For EACH phase:

```
1. Output phase banner
2. Check phase: python3 ~/.../workflow.py status
3. Do the work for this phase
4. Verify phase completion criteria met
5. Output phase completion
6. Advance: python3 ~/.../workflow.py advance
7. Repeat for next phase
```

## Phase Completion Criteria

| Phase | Complete When |
|-------|---------------|
| test_writing | Tests written that fail (TDD red) |
| implement | Code written, tests should pass |
| test | All tests pass, no lint/type errors |
| coverage | Coverage meets threshold (80%) |
| review | Greptile review complete, issues addressed |

## Compliance Signals

Output these as you work:
```
[ITERATE] Tests: 12 passed, 0 failed
[ITERATE] Coverage: 85% (target: 80%)
[ITERATE] Review: Triggered, waiting for results
[ITERATE] Complete: All checks passed
```

## Important

- **ALWAYS output phase banners** - user must see discrete phases
- Stay autonomous - only escalate on blockers
- Commit frequently with descriptive messages
- Run tests after every significant change
- Address ALL review comments before completing
