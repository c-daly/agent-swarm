# Agent Dispatch Enforcement Design

## Problem

Agents spawned via `Task()` skip registration, briefing assembly, and workflow setup. Skill files tell agents to register before spawning, but agents ignore these instructions. Subagents then can't use router tools (because they're unregistered) and fail silently. The old `_native_task` tried to solve this by owning the full spawn lifecycle including execution, but cross-process communication caused problems and it became dead code.

## Solution

Two components that make dispatch enforcement automatic — no protocol for the agent to follow, no steps to skip.

### 1. PreToolUse hook on `Task` calls

Intercepts every `Task()` call. Extracts the subagent type and other parameters from the tool input. Calls `prepare_dispatch()` on the controller via TCP/JSON-RPC (same pattern as session-start's `call_router()`). If preparation succeeds, allows the call. If it fails (e.g., phase violation), blocks with guidance.

**Hook logic:**
```
if tool_name == "Task":
    result = call_router("prepare_dispatch", {
        agent_type: <from tool input>,
        prompt: <from tool input>,
        description: <from tool input>,
    })
    if result.success → allow
    if result.error → block with guidance
```

### 2. `prepare_dispatch()` — controller method exposed via router

Called by the hook (not by the agent). Performs all spawn housekeeping:

- Validates spawn is allowed in current workflow phase
- Generates agent ID
- Registers agent in permission system
- Assembles role/workflow/phase-specific briefing via `assemble_subagent_briefing()`
- Stores briefing in agent state for later retrieval
- Records agent state

Exposed as `router__prepare_dispatch`.

**Input:**
```json
{
  "agent_type": "implementer",
  "prompt": "Your task is to...",
  "description": "Build experiment harness"
}
```

**Output:**
```json
{
  "success": true,
  "agent_id": "sub-a1b2c3d4"
}
```

### 3. Briefing injection via session-start

When the subagent starts, its session-start hook calls `get_agent_briefing()` on the controller. Instead of returning the generic `assemble_agent_briefing()`, the controller looks up the agent's stored briefing from `prepare_dispatch()` and returns the role/workflow/phase-specific one.

This requires enhancing `get_agent_briefing()` to identify the calling agent and return its specific briefing.

## Data flow

```
Main agent                    Hook                     Controller
    |                          |                          |
    |-- Task(prompt, type) --->|                          |
    |                          |-- prepare_dispatch() --->|
    |                          |                          |-- validate phase
    |                          |                          |-- generate ID
    |                          |                          |-- register permissions
    |                          |                          |-- assemble briefing
    |                          |                          |-- store briefing
    |                          |                          |-- record state
    |                          |<-- success --------------|
    |                          |                          |
    |                     allow|                          |
    |                          |                          |
    |              [Task() proceeds, subagent starts]     |
    |                          |                          |
Subagent                       |                     Controller
    |                          |                          |
    |-- session-start ---------|------------------------->|
    |   get_agent_briefing()   |                          |-- look up agent
    |                          |                          |-- return stored briefing
    |<----- briefing injected ---|--------------------------|
```

## What gets removed

| File | What |
|------|------|
| `lib/controller.py` | `_native_task` method, `"task"` entry in `_handle_native` dispatch table |
| `lib/router.py` | `native__task` tool schema definition |
| `lib/mcp_native.py` | `_handle_task` passthrough handler |
| `lib/protocol_assembly.py` | Comment referencing `native__task` |
| `config/permissions.yaml` | `native__task` from global allowed list |

## What gets modified

| File | What |
|------|------|
| `lib/controller.py` | Add `_prepare_dispatch()` method, enhance `get_agent_briefing` to return agent-specific briefing |
| `lib/router.py` | Add `router__prepare_dispatch` tool schema |

## What gets added

| File | What |
|------|------|
| `hooks/agent-dispatch.py` | PreToolUse hook on `Task` — calls `prepare_dispatch()`, allows or blocks |

## Scope

- **No two-step protocol** — the agent just calls `Task()` normally. The hook does everything automatically.
- **No `complete_dispatch()`** — stale registrations are harmless (unique IDs) and can be cleaned up by session-start or periodically.
- **Briefing is agent-specific** — assembled during `prepare_dispatch()`, stored, and returned by `get_agent_briefing()` when the subagent starts.
- **Dead code removed** — `_native_task` and all references cleaned up.
