# Handoff: Hooks Refactor Session 3 (2026-02-01)

## Branch
`feature/hooks-refactor` — continuing from session 2

## Current Git State
Only clean changes are the two file deletes (already committed in session 2):
- `hooks/router-event-hook.py` — deleted (dead code)
- `hooks/base-enforcement.py` — deleted (disabled stub)

No other uncommitted changes. Earlier bad changes (file writes replacing workflow_client) were reverted.

## Key Realization: The Architecture

**Deny and replace.** Same pattern as every other built-in tool.

- Deny `Task` in settings.json deny list
- Provide `router__task` (or `native__task`) as the MCP replacement
- Router receives the Task call with full control over prompt, parameters, execution
- Router injects phase context into the prompt using its in-memory workflow state
- Router executes the subagent (implementation detail for next session)
- Response goes through summarization like everything else

This eliminates ALL subagent-related hooks:
- `subagent-enforcement.py` — DELETE (context injection moves to router)
- `subagent-complete.py` — DELETE (completion tracking moves to router)
- `task-enforcement.py` — DELETE (enforcement is in the router tool itself)

The only hook is a one-line PreToolUse:Task that unconditionally denies the built-in Task (no logic, no return value — just blocks it). Everything else is the router's `native__task` tool.

### Hook that remains:
- PreToolUse:Task → unconditional deny (forces Claude Code to use the router tool instead)