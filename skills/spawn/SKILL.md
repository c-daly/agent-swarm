---
name: spawn
description: How to spawn subagents correctly under the router. Use when delegating work to a specialized agent.
---

## How to Spawn (REQUIRED)

Every subagent runs under the router: its only tool is `Bash(mcp*)`, so it must
call tools via `mcp-call --caller-id=<its id>`. Two steps, never skip either:

1. **Register** the agent to get its id + role/workflow briefing:
   ```
   reg = register_agent(agent_id="<task-id>", agent_type="<role>", workflow_id="<workflow>")
   ```
2. **Prepend the briefing** to the prompt and spawn with the role as `subagent_type`:
   ```
   Task(
     subagent_type="<role>",
     prompt=reg["briefing"] + "\n\n" + <task description + working dir>,
   )
   ```

`reg["briefing"]` carries the agent's id, the `mcp-call`/`--caller-id` convention,
its role rules, and its workflow phases. **Without it the agent has no identity
and its tool calls are denied.**

Do **NOT** spawn native subagent types (`Explore` / `general-purpose` / `Plan`).
They use Claude Code's built-in tools, which the router blocks — they cannot
reach `mcp-call` correctly and will flail.

## Agent Selection

`agent_type` and `subagent_type` are the same role name.

| Need | Role | Model |
|------|------|-------|
| Find code/files | explorer | haiku |
| Web/doc research | researcher | haiku |
| Plan changes | architect | sonnet |
| Write code | implementer | sonnet |
| Review changes | reviewer | sonnet |
| Fix bugs | debugger | sonnet |
| Git operations | git-agent | haiku |

## Prompt Structure (after the briefing)
1. **Task** -- one clear objective
2. **Scope** -- exclusive file list (no other agent touches these)
3. **Output** -- specific return format
4. **Constraints** -- what NOT to do
5. **Acceptance criteria** -- machine-checkable (grep, test exit codes)

Never embed file content in prompts. Give intent + verification criteria.

## Model Selection
- Can downgrade (sonnet -> haiku). Never upgrade without asking the orchestrator.
- Default to cheaper when unsure.

## Parallel Spawning
Independent tasks -> register + `Task` each, multiple in ONE message block.
Max 5 parallel agents.

## File Ownership
Each file modified by AT MOST one concurrent agent.
Overlap -> serialize with `depends_on`, or merge into one task.

## Anti-Patterns
- Don't spawn native subagent types (`Explore`/`general-purpose`/`Plan`) -- no router access
- Don't spawn without registering and prepending the briefing
- Don't spawn for one-liner tasks or <3 tool calls
- Don't use opus for subagents (orchestrator only)
- Don't give vague prompts ("look around")
- Batch related work into one agent
