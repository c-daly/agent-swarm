# Session Handoff - 2026-01-24 - Subagent Tools

## Current Task
Implementing subagent-tools plan (PR branch: feature/subagent-tools)

## Status
- **Batch 1 COMPLETE**: Documentation cleanup (Tasks 4a, 4b, 4c)
- **Batch 2 PENDING**: Code changes (Tasks 1, 2, 3)
- **Batch 3 PENDING**: Research (Task 5)

## Completed Work

### Task 4a: Rewrote `hooks/subagent-briefing.md`
- Clean mcp-call syntax for shell commands and code tools
- Token efficiency rules
- Memory integration patterns

### Task 4b: Agent files reverted to original
- Removed confusing subagent notes I had added
- Agent docs (explorer.md, etc.) are for main agents, reference CORE_PROTOCOL
- Subagent briefing is separate, injected by hook for Task-spawned agents

### Task 4c: Rewrote `agent_context.md`
- Removed outdated LOGOS/apollo/gh_wrapper references
- Clean mcp-call patterns

## Remaining Work

### Task 1: Add shell aliases to `bin/mcp-call`
```python
SHELL_ALIASES = {"pytest", "ruff", "mypy", "black", "git", "gh", "python", "python3", "poetry"}
```
Handle aliases before is_tool_allowed check, route to native__bash.

### Task 2: Add `router__get_allowed_tools` to `lib/mcp_router.py`
New router method returning allowed aliases and MCP tool patterns for hook consumption.

### Task 3: Modify `hooks/inject-subagent-briefing.sh`
Query router for allowed_tools, inject into Task tool calls to restrict subagent tool visibility.

### Task 5: Research MCP Tool Search
Investigate if ENABLE_TOOL_SEARCH can reduce context bloat from router tools.

## Discovered Issue - Block Messages Need Fixing

When hooks block tools, messages are misleading. Proposed fixes:

**`hooks/base-enforcement.py`:**
```python
# OLD:
"[NO WORKFLOW] Write blocked. Start /iterate or /orchestrate to edit files."

# NEW:
"[NO WORKFLOW] Write blocked. Start a workflow (/iterate or /orchestrate) and spawn Task subagents to edit files."
```

**`hooks/iterate-enforcement.py`:**
```python
# For orchestrate phase blocks, append:
". Use Task tool to spawn a subagent for this operation."
```

## Key Files
- `hooks/subagent-briefing.md` - Rewritten (done)
- `agent_context.md` - Rewritten (done)
- `agents/*.md` - Reverted to original (done)
- `bin/mcp-call` - Needs shell aliases (pending)
- `lib/mcp_router.py` - Needs get_allowed_tools (pending)
- `hooks/inject-subagent-briefing.sh` - Needs allowed_tools injection (pending)
- `hooks/base-enforcement.py` - Needs better block message (discovered)
- `hooks/iterate-enforcement.py` - Needs actionable hints (discovered)

## Plan Reference
Full plan was in original user message. Architecture:
- Subagents call `Bash("mcp-call <alias> [args]")`
- mcp-call translates aliases, sends to router
- Router executes via appropriate backend
- Subagent visibility: `Bash(mcp-call*)` + Router MCP tools, NO native Read/Write/Edit/Glob/Grep
