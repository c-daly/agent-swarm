# Agent-Swarm Architecture Context

## Workflow State Architecture

### State Flow
All workflow state lives in a single `WorkflowStateServer` instance hosted by the MCP router process. The router stays alive for the entire Claude Code session, so state persists across tool calls and context compaction.

### State Access Paths

| Caller | Access Method | Path |
|--------|-------------|------|
| Main agent (Claude) | MCP tools directly (`mcp__...__workflow__workflow_*`) | Claude → Router → WorkflowStateServer |
| `worker_pool.py` | `import workflow_client` (socket) | Process → Socket → Router → WorkflowStateServer |
| `workflow_base.py` | `import workflow_client` (socket) | Process → Socket → Router → WorkflowStateServer |
| `orchestrate.py` | `import workflow_client` (socket) | Process → Socket → Router → WorkflowStateServer |
| `agent_recovery.py` | `from workflow_client import agent_get_state, ...` | Process → Socket → Router → WorkflowStateServer |
| `permission_query.py` | `import workflow_client` | Process → Socket → Router → WorkflowStateServer |
| `review_gate.py` | `import workflow_client` | Process → Socket → Router → WorkflowStateServer |
| `debug_workflow.py` | `import workflow_client` | Process → Socket → Router → WorkflowStateServer |
| `pr_comment_workflow.py` | `import workflow_client` | Process → Socket → Router → WorkflowStateServer |
| `bin/mcp-call` | `from workflow_client import call_tool, list_tools` | Process → Socket → Router → WorkflowStateServer |
| Hooks | `from workflow_client import ...` | Process → Socket → Router → WorkflowStateServer |
| **`iterate_workflow.py`** | **`_get_server()` → local `WorkflowStateServer()`** | **BUG: In-memory only, dies per process** |

### Key Files

- **`lib/workflow_server.py`** — `WorkflowStateServer` class. Thread-safe in-memory dict storage. Hosted as MCP server by the router (stdio subprocess). Methods: `workflow_start`, `workflow_stop`, `workflow_is_active`, `workflow_get_state`, `workflow_set_state`, `workflow_update`, `workflow_get_value`, `workflow_set_value`, plus agent operations.

- **`lib/workflow_client.py`** — Socket client connecting to the router. Module-level functions with **identical signatures** to `WorkflowStateServer` methods. Used by every file except `iterate_workflow.py`.

- **`lib/iterate_workflow.py`** — Workflow logic (phases, TDD enforcement, kick-back). Called as CLI (`python3 iterate_workflow.py <cmd>`). Each invocation is a new process. Contains `_get_server()` which returns a local `WorkflowStateServer()` singleton — this is the bug.

- **`lib/mcp_router.py`** — Hosts `WorkflowStateServer` as a subprocess. State lives here for the session lifetime.

### iterate_workflow.py Invocation

Called as CLI by the main agent via Bash:
```
python3 iterate_workflow.py start "task" [--agent-id=X] [--spec=X] [--queue=X]
python3 iterate_workflow.py status
python3 iterate_workflow.py phase
python3 iterate_workflow.py advance
python3 iterate_workflow.py test <tests> <lint> <coverage>
python3 iterate_workflow.py review <clean>
python3 iterate_workflow.py set-phase <phase>
python3 iterate_workflow.py stop
```

Also imported by hooks for `is_tool_allowed()`, `is_active()`, `get_phase()`.

### Known Bug: _get_server() State Persistence

`_get_server()` creates a local `WorkflowStateServer()` instance. Since each CLI call is a new process, state dies between invocations. Fix: return `workflow_client` module instead — same API, routes through router socket to persistent state.

The `start()` function's `agent_id` parameter documents dual behavior (orchestrator=persisted, subagent=in-memory) but this is not implemented — all paths use the local singleton.

## Three Uncommitted Fixes (as of 2026-01-29)

1. **Serena auto-activation** — `hooks/session-start.py` puts `project_root` into session state
2. **Router output truncation** — `lib/mcp_router.py` no longer truncates small responses to 200 chars
3. **iterate_workflow.py stderr→stdout** — Status banners go to stdout for router bash capture
