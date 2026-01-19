# Workflow State MCP Server Design

## Overview

Replace file-based state persistence with an in-memory MCP server for thread-safe, ephemeral workflow state management.

## Problem

The current state_manager.py has a fundamental issue: each CLI invocation and hook runs as a separate Python process. In-memory state doesn't persist across these invocations. The previous solution used file-based persistence, but we want to eliminate state files entirely.

## Solution

A dedicated MCP server that:
- Holds workflow and agent state in memory
- Lives for the duration of the Claude session (managed by Claude Code)
- Provides a generic contract usable by any workflow
- Eliminates all state files

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Claude / Skills / Hooks                            │
│  (consumers - call MCP tools)                       │
└─────────────────┬───────────────────────────────────┘
                  │ MCP protocol
┌─────────────────▼───────────────────────────────────┐
│  workflow MCP server                                │
│  - Generic state store                              │
│  - In-memory (lives for session)                    │
│  - Thread-safe operations                           │
│  Tools: mcp__workflow__*                            │
└─────────────────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────┐
│  iterate_workflow.py (and future workflows)         │
│  - Implements specific workflow logic               │
│  - Owns validation rules (phase transitions)        │
│  - CLI remains for manual invocation                │
└─────────────────────────────────────────────────────┘
```

## Key Decisions

- **Single instance per workflow type**: Can run `/iterate` and `/orchestrate` simultaneously, but not two `/iterate` instances
- **Workflow-agnostic**: Server doesn't know about phases - just stores dicts
- **No validation in server**: Workflows validate their own rules before calling set_state
- **Hooks use lightweight client**: Simple module to query MCP server
- **Configured in .mcp.json**: Claude Code manages server lifecycle

## MCP Tools Contract

### Workflow Operations

| Tool | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `workflow_start` | `workflow_id`, `initial_state` | state dict | Creates workflow (fails if exists) |
| `workflow_stop` | `workflow_id` | success | Removes workflow state |
| `workflow_is_active` | `workflow_id` | boolean | Check if workflow exists |
| `workflow_get_state` | `workflow_id` | state dict or null | Get full state |
| `workflow_set_state` | `workflow_id`, `state` | state dict | Replace full state |
| `workflow_update` | `workflow_id`, `updates` | state dict | Merge partial updates |
| `workflow_get_value` | `workflow_id`, `key` | value or null | Get single field |
| `workflow_set_value` | `workflow_id`, `key`, `value` | success | Set single field |

### Agent Operations

| Tool | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `agent_get_state` | `agent_id` | state dict or null | Get agent state |
| `agent_set_state` | `agent_id`, `state` | state dict | Set agent state |
| `agent_delete` | `agent_id` | success | Remove agent state |
| `list_agents` | - | list of agent_ids | List all agents |

All operations are thread-safe and return deep copies.

## Files

### Create

**`lib/workflow_server.py`** (~150-200 lines)
- MCP server implementing the contract
- In-memory storage with thread locks
- Stdio MCP protocol

**`lib/workflow_client.py`** (~50 lines)
- Lightweight client for hooks
- Simple functions: `get_value()`, `is_active()`, etc.
- Connects to workflow MCP server

### Modify

**`iterate_workflow.py`**
- Replace state_manager imports with workflow_client
- Keep all validation logic (phase transitions)
- Use workflow_id = "iterate"

**`hooks/iterate-enforcement.py`**
- Import from workflow_client instead of iterate_workflow
- Simpler dependency chain

**MCP config (`.mcp.json` or `plugin.json`)**
```json
{
  "mcpServers": {
    "workflow": {
      "command": "python3",
      "args": ["lib/workflow_server.py"]
    }
  }
}
```

### Delete

- `lib/state_manager.py` - replaced by MCP server
- `.state/iterate.json` - no longer created
- `.state/iterate.lock` - no longer needed

## Example: Hook Usage

```python
# iterate-enforcement.py
from workflow_client import get_value, is_active

def main():
    if not is_active("iterate"):
        return allow()
    
    phase = get_value("iterate", "phase")
    tool_name = input_data.get("tool_name")
    
    if not is_tool_allowed_for_phase(tool_name, phase):
        return block(f"Tool {tool_name} not allowed in {phase} phase")
    
    return allow()
```

## Example: Workflow Usage

```python
# iterate_workflow.py
from workflow_client import (
    workflow_start, workflow_stop,
    workflow_get_value, workflow_set_value
)

WORKFLOW_ID = "iterate"

def start(task: str, max_iterations: int = 5):
    initial_state = {
        "active": True,
        "task": task,
        "phase": "intake",
        "iteration": 0,
        "max_iterations": max_iterations,
    }
    workflow_start(WORKFLOW_ID, initial_state)

def set_phase(new_phase: str):
    current = workflow_get_value(WORKFLOW_ID, "phase")
    _validate_phase_transition(current, new_phase)  # local validation
    workflow_set_value(WORKFLOW_ID, "phase", new_phase)
```

## Benefits

1. **No state files** - Eliminates file I/O issues and cleanup concerns
2. **Session-scoped** - State naturally expires when session ends
3. **Thread-safe** - MCP server handles concurrency
4. **Generic** - Same contract works for any workflow
5. **Clean separation** - Server stores, workflows validate
6. **Testable** - Can mock the MCP client for unit tests

## Implementation Order

1. Create `workflow_server.py` with MCP tools
2. Create `workflow_client.py` for hooks
3. Add server to MCP config
4. Update `iterate_workflow.py` to use client
5. Update `iterate-enforcement.py` to use client
6. Delete `state_manager.py`
7. Clean up any remaining state files
