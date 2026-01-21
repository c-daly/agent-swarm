# Session Handoff - 2026-01-20 (Session 2)

## Current Task
Iterating through enforcement/infrastructure task queue for agent-swarm plugin.

## Status
- **Phase**: INTAKE (gathering context for debugging tasks)
- **Workflow**: `/iterate` active
- **Blocker**: MCP router went down mid-session, using Serena as fallback

## Key Findings from This Session

### PHASE_TOOLS Analysis (lib/iterate_workflow.py:132-185)
```python
PHASE_TOOLS = {
    Phase.INTAKE: {
        "allowed": {"Read", "Glob", "Grep", "WebSearch", "WebFetch", "Task", "bash"},
        "blocked": {"Edit", "Write", "Bash"},  # Note: lowercase "bash" allowed, "Bash" blocked
    },
    Phase.IMPLEMENT: {
        "allowed": {"Read", "Glob", "Grep", "Edit", "Write", "native__bash"},
        "blocked": {"Bash"},  # Bash blocked, native__bash allowed
    },
    # ... similar for other phases
}
```

**Key insight**: `native__bash` is allowed, `Bash` is blocked. Agents try to call `Bash` (doesn't exist) instead of `mcp__router__native__bash`.

### Tool Discovery Problem (for creativity/exploration task)
I experienced the exact problem we're trying to solve:
1. Tried `Bash` - doesn't exist
2. Tried `mcp__router__*` - router down
3. Remembered Serena is separate MCP server
4. Discovered which Serena tools exist via trial/error
5. Used `search_for_pattern` creatively when `read_file` unavailable

This trial-and-error is what agents need to be better at.

## Task Queue (from TodoWrite)
1. [completed] INTAKE: Explore agent definitions, tool assignments, workflow state flow
2. [in_progress] Debug: Subagent phase initialization - needs agentID passed to state queries
3. [in_progress] Fix: Implementer agents using wrong Bash tool (native vs mcp__router__native__bash)
4. [pending] Enforce: Run independent agents in parallel (single message, multiple Task calls)
5. [pending] Enforce: Use non-blocking background agents, don't block on TaskOutput
6. [pending] Enforce: Orchestrator should not EDIT directly - spawn implementers instead
7. [pending] Task: Clean up stale agent outputs when starting orchestrate phase
8. [pending] Task: Agent timeout/autokill for agents taking too long
9. [pending] Task: Meaningful progress output not visible during workflow
10. [pending] Enforce: Orchestrator should spawn test agents, not run tests directly
11. [pending] Code: Encourage agent experimentation/creativity with MCP tools

## Debugger Agents (were running, status unknown)
- `a87af30`: Investigating subagent phase initialization
- `a3ed941`: Investigating Bash tool confusion

Their output files may be at:
- `/tmp/claude/-home-fearsidhe--claude-plugins-agent-swarm/tasks/a87af30.output`
- `/tmp/claude/-home-fearsidhe--claude-plugins-agent-swarm/tasks/a3ed941.output`

## Key Files for Next Steps
- `lib/iterate_workflow.py` - PHASE_TOOLS dict, phase logic
- `hooks/iterate-enforcement.py` - delegates to `is_tool_allowed()`
- `hooks/subagent-briefing.md` - injected context for subagents
- `agents/implementer.md` - agent definition (needs bash guidance?)
- `lib/workflow_client.py` - has `agent_get_state(agent_id)` for per-agent state

## Solution Patterns Identified
1. **Bash tool fix**: Add guidance in `subagent-briefing.md` about using `mcp__router__native__bash` not `Bash`
2. **Phase initialization**: Hooks receive agentID, should pass to state queries: `agent_get_state(agent_id)` returns agent-specific phase
3. **Tool discovery**: Add examples/prompts encouraging MCP tool exploration when tools fail

## User Feedback This Session
- "remember nonblocking" - don't block on TaskOutput, check output files instead
- "use serena" - multiple MCP servers available, be creative
- "this is exactly what I'm talking about" (re: tool discovery) - agents should explore available tools
- "it's a functional issue that I need to be the same every time" - build enforcement in code, not prompts

## Next Steps
1. Check if debugger agent outputs completed
2. Based on findings, spawn implementer agents to fix:
   - Add bash tool guidance to briefing/agent definition
   - Pass agentID to phase state queries in hooks
3. Continue through task queue
