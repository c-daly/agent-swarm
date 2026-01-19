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
│  Claude Code                                        │
│  (calls MCP tools via stdio)                        │
└─────────────────┬───────────────────────────────────┘
                  │ stdio (MCP protocol)
┌─────────────────▼───────────────────────────────────┐
│  MCP Router (mcp_router.py)                         │
│  - Routes tool calls to backends                    │
│  - Exposes socket listener for external clients     │
│  - Port stored in: ~/.claude/router.port            │
└────────┬────────────────────────────┬───────────────┘
         │ stdio                      │ socket (JSON-RPC)
         │                            │
┌────────▼────────┐          ┌────────▼────────┐
│ workflow_server │          │ Hooks / CLIs    │
│ (backend)       │          │ (via workflow_  │
│ - In-memory     │          │  client.py)     │
│ - Thread-safe   │          │                 │
└─────────────────┘          └─────────────────┘
```

### Communication Paths

1. **Claude → Router → workflow_server**: Standard MCP stdio chain
2. **Hooks → Router → workflow_server**: Socket connection using JSON-RPC
   - Router listens on a socket (port written to `~/.claude/router.port`)
   - workflow_client.py reads port, connects, sends JSON-RPC requests
   - Router routes to workflow backend, returns response

### Why This Architecture?

- Hooks run as separate Python processes (spawned by Claude Code)
- They can't use stdio (that's Claude's exclusive connection)
- Socket connection allows any external process to query workflow state
- Router already manages backend routing, so it's the natural proxy

## Key Decisions

- **Single instance per workflow type**: Can run `/iterate` and `/orchestrate` simultaneously, but not two `/iterate` instances
- **Workflow-agnostic**: Server doesn't know about phases - just stores dicts
- **No validation in server**: Workflows validate their own rules before calling set_state
- **Hooks connect via router socket**: workflow_client.py connects to router's socket listener using JSON-RPC
- **Router manages lifecycle**: workflow_server runs as a backend process managed by the router
- **Port discovery via file**: Router writes port to `~/.claude/router.port` for client discovery

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
- Stdio MCP protocol (receives requests from router)

**`lib/workflow_client.py`** (~80 lines)
- Socket client for hooks and external processes
- Connects to router via port from `~/.claude/router.port`
- Sends JSON-RPC requests, receives responses
- Functions: `workflow_start()`, `workflow_stop()`, `workflow_is_active()`, 
  `workflow_get_state()`, `workflow_get_value()`, `workflow_set_value()`, etc.

### Modify

**`lib/mcp_router.py`**
- Add socket listener thread (alongside stdio)
- Accept JSON-RPC connections from external clients
- Route requests to appropriate backend (same routing logic)
- Write port to `~/.claude/router.port` on startup
- Clean up port file on shutdown

**`config/backends.json`**
- Register workflow backend:
```json
{
  "workflow": {
    "command": ["python3", "lib/workflow_server.py"],
    "cwd": "~/.claude/plugins/agent-swarm"
  }
}
```

**`lib/iterate_workflow.py`**
- Replace state_manager imports with workflow_client
- Keep all validation logic (phase transitions)
- Use workflow_id = "iterate"

**`hooks/iterate-enforcement.py`**
- Import from workflow_client instead of iterate_workflow
- Simpler dependency chain

### Delete

- `lib/state_manager.py` - replaced by MCP server
- `.state/` directory - no longer needed

## Example: Hook Usage

```python
# iterate-enforcement.py
import sys
sys.path.insert(0, "/home/fearsidhe/.claude/plugins/agent-swarm/lib")
from workflow_client import workflow_is_active, workflow_get_value

def main():
    # workflow_client connects to router socket automatically
    if not workflow_is_active("iterate"):
        return allow()
    
    phase = workflow_get_value("iterate", "phase")
    tool_name = input_data.get("tool_name")
    
    if not is_tool_allowed_for_phase(tool_name, phase):
        return block(f"Tool {tool_name} not allowed in {phase} phase")
    
    return allow()
```

### How workflow_client works internally:

```python
# workflow_client.py (simplified)
import socket
import json

def _get_router_port():
    with open(os.path.expanduser("~/.claude/router.port")) as f:
        return int(f.read().strip())

def _call_tool(tool_name: str, arguments: dict):
    port = _get_router_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect(("127.0.0.1", port))
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments}
        }
        s.sendall(json.dumps(request).encode() + b"\n")
        response = json.loads(s.recv(65536).decode())
        return response.get("result")

def workflow_is_active(workflow_id: str) -> bool:
    result = _call_tool("workflow_is_active", {"workflow_id": workflow_id})
    return result.get("content", [{}])[0].get("text") == "true"
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

1. **Create `lib/workflow_server.py`** - MCP server with workflow/agent state tools
2. **Add socket listener to `lib/mcp_router.py`** - Accept external JSON-RPC connections
3. **Register workflow backend in `config/backends.json`** - Router launches workflow_server
4. **Create `lib/workflow_client.py`** - Socket client for hooks to connect to router
5. **Update `lib/iterate_workflow.py`** - Use workflow_client instead of state_manager
6. **Update hooks** - Use workflow_client for state queries
7. **Delete `lib/state_manager.py`** - No longer needed
8. **Test end-to-end** - Verify hooks can query workflow state via router socket

### Verification Steps

After each task:
- Task 1-3: Router starts workflow backend, tools appear in tool list
- Task 4: `python -c "from workflow_client import workflow_is_active; print(workflow_is_active('test'))"` works
- Task 5-6: Run iterate workflow, verify hooks can query state
- Task 7-8: Full integration test
