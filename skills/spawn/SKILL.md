---
name: spawn
description: How to spawn subagents correctly. Use this reference when you need to delegate work to a specialized agent.
---

## Agent Selection

| Need | Agent | Model | subagent_type |
|------|-------|-------|---------------|
| Find code/files | explorer | haiku | Explore |
| Web/doc research | researcher | haiku | general-purpose |
| Plan changes | architect | sonnet | Plan |
| Write code | implementer | sonnet | general-purpose |
| Review changes | reviewer | sonnet | general-purpose |
| Fix bugs | debugger | sonnet | general-purpose |
| Git operations | git-agent | haiku | general-purpose |

## Prompt Structure (REQUIRED)
1. **Task** -- one clear objective
2. **Scope** -- exclusive file list (no other agent touches these)
3. **Output** -- specific return format
4. **Constraints** -- what NOT to do
5. **Acceptance criteria** -- machine-checkable (grep, test exit codes)

Never embed file content in prompts. Give intent + verification criteria.

## Model Selection
- Can downgrade (sonnet -> haiku). Never upgrade without asking orchestrator.
- Default to cheaper when unsure.

## Parallel Spawning
Independent tasks -> multiple Task calls in ONE message block.
Max 5 parallel agents.

## File Ownership
Each file modified by AT MOST one concurrent agent.
Overlap -> serialize with `depends_on`, or merge into one task.

## Anti-Patterns
- Don't spawn for one-liner tasks or <3 tool calls
- Don't use opus for subagents (orchestrator only)
- Don't give vague prompts ("look around")
- Batch related work into one agent
