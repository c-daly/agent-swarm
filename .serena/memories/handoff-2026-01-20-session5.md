# Session Handoff - 2026-01-20 Session 5

## Current Task
Fix router concurrency issue blocking parallel agent execution

## Status
- Phase: IMPLEMENT (iterate workflow)
- Progress: Identified root cause, user approved 3-part fix, not yet implemented
- Blockers: Router deadlocks when multiple agents make concurrent MCP calls

## Router Concurrency Issue
**Root Cause:** `lib/mcp_router.py:1043-1123` - `_forward_to_server()` holds backend lock during blocking `readline()`:
```python
with backend_lock:  # Lock acquired
    # ... setup ...
    response_line = proc.stdout.readline()  # BLOCKING while holding lock!
```

**Approved Fix (all 3 together):**
1. Don't hold lock during I/O - only during connection setup
2. Add timeout to readline()
3. Use asyncio for non-blocking I/O

## Failed Agents (killed due to router deadlock)
- a79ec0b - Phase banners fix
- a78b996 - Serena auto-activation fix  
- aa00c52 - max_agents enforcement

## Task Queue (prioritized)
1. **Fix: Router concurrency** - CRITICAL, blocks all parallel work
2. Fix: Iterate workflow output - show phase banners
3. Enforce: Orchestrator must check max_agents before spawning
4. Fix: Serena auto-activation regression
5. Enforce: All agents must use run_in_background=true
6. Enforce: Orchestrator should not EDIT directly - spawn implementers
7. Enforce: Subagents write tests when none exist
8. Task: Persist agent outputs via state manager
9. Enforce: Run independent agents in parallel
10. Task: Handle failed/bad-state subagents
11. Task: Clean up stale agent outputs
12. Task: Agent timeout/autokill
13. Enforce: Orchestrator should spawn test agents
14. Code: Encourage agent experimentation with MCP tools

## User Directive
- Only spawn ONE agent at a time until router is fixed
- All agents must use run_in_background=true

## Key Files
- `lib/mcp_router.py` - Router with concurrency bug
- `lib/iterate_workflow.py` - Phase banner functions exist but not auto-called
- `hooks/session-start.py` - Needs Serena auto-activation logic
- `config/workflow.json` - max_agents=3 setting

## Next Steps
1. Implement router concurrency fix in `lib/mcp_router.py`
2. Test with single agent
3. Then work through task queue one agent at a time
