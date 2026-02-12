# Agent Registration Briefing Design

**Date:** 2026-02-12
**Status:** Draft

## Problem

Subagents spawned via native Task tool don't receive proper context. The old
`_native_task` path in controller.py assembled briefings and prepended them to
prompts, but native Task is now required for agent team support. Without
briefing injection, agents:

- Try wrong tool patterns (waste turns on blocked tools)
- Don't parallelize independent calls
- Re-read the same files repeatedly
- Drift out of scope
- Don't know what workflow phase they're in
- Pollute their context with raw file contents instead of writing scripts

## Design

### Core: register_agent becomes the single entry point

`register_agent` handles the full agent lifecycle setup. The orchestrator calls
it, gets back everything needed, passes it to Task. No orchestrator-side logic.

### Interface

```python
# MCP tool: mcp__router__router__register_agent
register_agent(
    agent_id: str,          # caller-generated
    agent_type: str,        # "implementer", "explorer", etc.
    workflow_id: str | None # optional workflow association
)
```

### Controller behavior (all in _handle_router)

1. **Register** — existing `permissions.register_agent()`
2. **Phase** — if workflow_id provided, set initial phase from workflow config;
   otherwise no phase (first `advance_phase` moves to initial)
3. **State** — `agent_set_state(agent_id, {...})` with full metadata:
   ```python
   {
       "agent_id": agent_id,
       "agent_type": agent_type,
       "workflow_id": workflow_id,      # or None
       "phase": initial_phase,          # or None
       "status": "registered",
       "registered_at": "<iso timestamp>",
   }
   ```
4. **Briefing** — call `assemble_subagent_briefing(agent_type)` which layers:
   - Tool table (mcp-call patterns — how to actually call tools)
   - Operational rules (parallelize, no dup reads, use scripts for batch ops)
   - Agent type definition (behavioral constraints, room to grow)
   - Workflow + phase context (if active — what phase, expectations, transitions)
5. **Return** — `{agent_id, agent_type, workflow_id, phase, briefing}`

### Orchestrator usage

```
result = register_agent(agent_type="implementer", workflow_id="iterate")
Task(prompt=result.briefing + "\n\n# TASK\n\n" + task_specifics)
```

Faulted/unregistered agents are a fail state — the orchestrator handles cleanup
by querying `list_agents` for status: faulted or timed-out registrations.

### Briefing content principles

Every line must address an **observed failure mode**. No generic advice.

**Tool table** (agents fail without this):
- mcp-call patterns for read, search, edit, find symbols, run commands
- Timeout handling (nohup for commands >30s)

**Operational rules** (agents genuinely don't do these unprompted):
- Parallelize independent tool calls in one message
- Track reads, don't re-read files
- Write scripts for 3+ file operations, return summaries not raw content
- Process data in scripts rather than polluting agent context

**Agent type** (thin now, room to grow):
- Role-specific constraints that prevent known failures
- Primary when no workflow is active

**Workflow + phase** (when active):
- Current phase and expectations
- Tool restrictions from workflow config
- Primary for tool access, overlays agent type

### Status lifecycle

```
registered → running → completed
                    → faulted
```

Status transitions managed by orchestrator via `agent_set_state`.

## Files changed

| File | Change |
|------|--------|
| `lib/controller.py` | Enhance `_handle_router("register_agent")` — add phase init, state recording, briefing assembly |
| `lib/protocol_assembly.py` | Sharpen `assemble_subagent_briefing()` — signal-dense content addressing observed failure modes |

## Not in scope

- Deprecating `_native_task` (can coexist)
- Restructuring agent `.md` files (future — agent types grow over time)
- Hook changes (this design avoids adding hooks)
