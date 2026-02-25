# Client-Side Architecture Design

**Date**: 2026-01-30
**Branch**: `feature/architecture-refactor-design`
**Companion doc**: `2026-01-30-architecture-refactor-design.md` (daemon/server side)

---

## Motivation

The current client side is bloated with infrastructure that compensates for not having
a proper daemon. Hooks enforce permissions, collect telemetry, block native tools, and
manage state — all because there's no central interception point. The daemon refactor
eliminates that need. The client side reduces to three things:

1. **Agent definitions** — what each agent type is (markdown + config)
2. **Config** — declarative workflow definitions, permissions, backend declarations
3. **Comms** — a thin client to talk to the daemon

Everything else either moves into the daemon or gets deleted.

---

## 1. Interface Contract

### Principle

The daemon exposes one tool per public method on its Controller. The client calls tools.
The daemon enforces permissions, records telemetry, manages state, caches results, and
routes to backends — all internally. The client doesn't know or care about that structure.

### Wire Protocol

Same as the daemon spec: JSON-RPC 2.0 over newline-delimited TCP.

```
Client                          Daemon
  |                               |
  |-- {"jsonrpc":"2.0", ...} \n ->|
  |                               |-- (permission check)
  |                               |-- (route to backend / handle internally)
  |                               |-- (record telemetry)
  |                               |-- (cache if needed)
  |<- {"jsonrpc":"2.0", ...} \n --|
  |                               |
```

### Request Format

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "tool_name",
    "arguments": { ... }
  }
}
```

### Agent Identity

The daemon identifies callers by their TCP connection. When an agent connects, the
daemon associates the connection with a session and agent context. No need to pass
agent_type/phase/session on every call — the daemon tracks it.

Registration happens once at connection time:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "agent/register",
  "params": {
    "agent_id": "abc123",
    "agent_type": "implementer",
    "session_id": "session-xyz",
    "workflow_id": "iterate"
  }
}
```

After registration, all subsequent `tools/call` requests on that connection inherit
the agent context. The daemon uses this to enforce permissions and record telemetry.

### Tool Surface

The daemon exposes tools that map to Controller methods. The client sees a flat list:

**Tool dispatch** (the primary use case):
- `tools/list` — enumerate available tools (filtered by agent permissions)
- `tools/call` — call any tool by name

**Workflow state** (generic, not workflow-specific):
- `workflow/start` — start a named workflow with initial state
- `workflow/stop` — stop a workflow
- `workflow/get_state` — get full workflow state
- `workflow/set_state` — replace full workflow state
- `workflow/update` — merge partial updates
- `workflow/get_value` — get a single key
- `workflow/set_value` — set a single key

**Agent state**:
- `agent/register` — register on this connection
- `agent/get_state` — get agent's state
- `agent/set_state` — set agent's state
- `agent/list` — list all agents in a workflow

**Session**:
- `session/start` — notify daemon of new session
- `session/end` — notify daemon session is ending

That's the complete tool surface. No cache tools (cache is internal). No permission
query tools (permissions are enforced, not queried). No telemetry tools (telemetry
is automatic).

---

## 2. Comm Layer

### DaemonClient

Replaces `workflow_client.py`. A single class, no module-level functions.

```python
class DaemonClient:
    """Thin client for the agent-swarm daemon."""

    DAEMON_HOST = "127.0.0.1"
    DAEMON_PORT = 7523

    def __init__(self):
        self._sock = None
        self._request_id = 0

    def connect(self):
        """Connect to the daemon. Raises if daemon is not running."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((self.DAEMON_HOST, self.DAEMON_PORT))

    def register(self, agent_id: str, agent_type: str,
                 session_id: str, workflow_id: str) -> dict:
        """Register this agent with the daemon."""
        return self._call("agent/register", {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "session_id": session_id,
            "workflow_id": workflow_id,
        })

    def call_tool(self, name: str, arguments: dict) -> Any:
        """Call a tool through the daemon."""
        return self._call("tools/call", {
            "name": name,
            "arguments": arguments,
        })

    def list_tools(self) -> list[dict]:
        """List available tools (filtered by agent permissions)."""
        return self._call("tools/list", {})

    def workflow_get_state(self, workflow_id: str) -> dict:
        """Get workflow state."""
        return self._call("workflow/get_state", {
            "workflow_id": workflow_id,
        })

    def workflow_update(self, workflow_id: str, updates: dict) -> dict:
        """Merge partial updates into workflow state."""
        return self._call("workflow/update", {
            "workflow_id": workflow_id,
            "updates": updates,
        })

    # ... remaining workflow/agent/session methods follow the same pattern

    def close(self):
        """Close connection."""
        if self._sock:
            self._sock.close()
            self._sock = None

    def _call(self, method: str, params: dict) -> Any:
        """Send JSON-RPC request, return result or raise on error."""
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        self._sock.sendall(json.dumps(request).encode() + b"\n")

        buf = b""
        while b"\n" not in buf:
            chunk = self._sock.recv(8192)
            if not chunk:
                raise ConnectionError("Daemon closed connection")
            buf += chunk

        line, _ = buf.split(b"\n", 1)
        response = json.loads(line.decode())

        if "error" in response:
            raise DaemonError(response["error"])

        return response.get("result")


class DaemonError(Exception):
    """Error returned by the daemon."""
    pass
```

### Key Differences from `workflow_client.py`

| Current (`workflow_client.py`) | New (`DaemonClient`) |
|---|---|
| Module-level functions | Single class instance |
| Opens new socket per call | Persistent connection |
| Port discovery from `.state/router.port` | Fixed known port |
| Different timeouts per operation | Single connection, daemon manages timeouts |
| Response envelope parsing (summary/full/content_id) | Simple JSON-RPC result |
| Logging to `.state/workflow_client.log` | No client-side logging (daemon logs) |
| 460 lines | ~80 lines |

### Connection Lifecycle

```
Agent starts
  → DaemonClient.connect()
  → DaemonClient.register(agent_id, agent_type, session_id, workflow_id)
  → DaemonClient.call_tool(...) (repeated)
  → DaemonClient.close()
Agent ends
```

The persistent connection lets the daemon track agent lifecycle without explicit
session start/end notifications. Connection open = agent alive. Connection close =
agent done.

---

## 3. Generic Workflow Config

### Current Problem

`iterate_workflow.py` (1800+ lines) hardcodes the iterate workflow as procedural
Python. Phase transitions, enforcement rules, checkpoint conditions — all baked in.
Adding a new workflow means writing another monolith.

### Solution

Workflows become declarative config. The daemon loads workflow definitions and
enforces them. The client (Claude agent) reasons about what to do next; the daemon
ensures it stays within bounds.

### Workflow Definition Schema

```yaml
# config/workflows/iterate.yaml
name: iterate
description: "TDD implementation loop with review gates"

phases:
  - name: test_writing
    allowed_tool_categories: [FILE_READ, FILE_WRITE, CODE_QUERY, FILE_SEARCH, SHELL_SAFE]
    blocked_tools: []
    eligible_agents: [implementer]
    checkpoint: false

  - name: implement
    allowed_tool_categories: [FILE_READ, FILE_WRITE, CODE_QUERY, CODE_EDIT, FILE_SEARCH, SHELL_SAFE]
    blocked_tools: []
    eligible_agents: [implementer]
    checkpoint: false

  - name: test
    allowed_tool_categories: [FILE_READ, SHELL_SAFE]
    blocked_tools: [Edit, Write]
    eligible_agents: [debugger, implementer]
    checkpoint: true  # must pass before advancing

  - name: review
    allowed_tool_categories: [FILE_READ, WEB_RESEARCH]
    blocked_tools: [Edit, Write, Bash]
    eligible_agents: [reviewer, adversary]
    checkpoint: true  # must pass before completing

  - name: coverage
    allowed_tool_categories: [FILE_READ, FILE_WRITE, SHELL_SAFE, WEB_RESEARCH]
    blocked_tools: []
    eligible_agents: [reviewer, implementer]
    checkpoint: false

transitions:
  test_writing: [implement]
  implement: [test]
  test: [implement, coverage, review]  # back to implement on failure
  coverage: [test, review]
  review: [implement, complete]        # back to implement on feedback

initial_phase: test_writing
terminal_phase: complete
```

### What This Replaces

| Current Code | Becomes |
|---|---|
| `lib/phase_model.py` (146 lines) | `config/workflows/*.yaml` phase definitions |
| `lib/agent_protocol.py` (115 lines) | `config/workflows/*.yaml` eligible_agents + `agents/*.md` |
| `lib/iterate_workflow.py` phase logic | `config/workflows/iterate.yaml` transitions |
| `config/workflow.json` phase section | `config/workflows/*.yaml` |

### What Stays as Agent Reasoning

The workflow config defines the *rules*. The Claude agent still decides:
- When to advance phases (daemon validates the transition is legal)
- Which tasks to spawn
- How to respond to test failures or review feedback
- When work is complete

This is orchestration-as-reasoning, not orchestration-as-code.

---

## 4. Agent Definitions

### Current State

Agent types are defined in two places:
- `agents/*.md` — markdown descriptions loaded as prompts
- `lib/agent_protocol.py` — Python dataclass with tool categories, blocked tools, phases

### After Refactor

Agent definitions stay as markdown files in `agents/`. The protocol information
(model, tool restrictions, phase eligibility) either:

**Option A**: Lives in the workflow config (eligible_agents per phase) and daemon
permissions config. The markdown files are purely prompt content.

**Option B**: Each agent markdown file includes a YAML frontmatter block with its
protocol, and the daemon reads it on startup.

```markdown
---
name: implementer
model: sonnet
max_output_chars: 1500
can_write_files: true
---

# Implementer Agent

Code implementation - new functionality, modifications, side-effect safety.
...
```

Option A is cleaner (single source of truth in config), but Option B keeps each
agent self-contained. Either way, `lib/agent_protocol.py` is deleted.

---

## 5. Deletion List

### Entire Directories Removed

| Directory | Reason |
|---|---|
| `hooks/` | Daemon handles interception, enforcement, telemetry |
| `.state/` | No state files — daemon uses state machine + DuckDB. Log files are fine. |

### Files Removed from `lib/`

| File | Lines | Reason |
|---|---|---|
| `iterate_workflow.py` | 1800+ | State/phases/enforcement → daemon + config |
| `orchestrate.py` | 540 | Generic workflow in daemon |
| `worker_pool.py` | ~200 | Daemon tracks agents |
| `workflow_queue.py` | ~200 | Daemon manages task state |
| `phase_model.py` | 146 | Becomes workflow config YAML |
| `agent_protocol.py` | 115 | Becomes agent config/frontmatter |
| `mcp_permissions.py` | ~500 | Daemon-side PermissionChecker |
| `permission_store.py` | ~200 | Daemon-side |
| `permission_query.py` | ~150 | Daemon-side |
| `telemetry_service.py` | ~300 | Daemon-side DataStore |
| `routing_service.py` | ~200 | Daemon-side Controller |
| `tool_translator.py` | ~150 | Daemon-side Controller |
| `connection_pool.py` | ~100 | Single daemon connection |
| `workflow_state_service.py` | ~150 | Daemon-side |
| `mcp_router.py` | 3800 | Becomes the daemon itself |
| `mcp_native.py` | ~300 | Daemon-side native backend |
| `workflow_server.py` | ~200 | Daemon-side workflow service |
| `stores/duckdb_store.py` | ~400 | Daemon-side DataStore |
| `stores/interfaces.py` | ~50 | Daemon-side |
| `stores/validation.py` | ~50 | Daemon-side |
| `stores/compression.py` | ~50 | Daemon-side |

**Estimated deletion**: ~9,000+ lines of Python

### Files Modified

| File | Change |
|---|---|
| `workflow_client.py` | Rewrite as `DaemonClient` (~80 lines) |
| `config.py` | Simplified — loads workflow YAML + agent config |

### Files Unchanged

| File/Directory | Reason |
|---|---|
| `agents/*.md` | Prompt definitions stay (possibly add YAML frontmatter) |
| `skills/` | Prompt templates — pure markdown, no code |
| `config/permissions.yaml` | Daemon loads this directly |
| `config/backends.json` | Daemon loads this directly |
| `bin/mcp-router` | Becomes the stdio shim (per daemon spec) |

---

## 6. Hooks

### Best Case: No Hooks

If Claude Code supports blocking native tools via configuration (e.g., 
`disabled_tools` in settings or MCP server config), then no hooks are needed.
The daemon is the sole tool provider. Native tools are simply not available.

### Fallback: Minimal Hooks

If native tool blocking requires a hook:

```
hooks/
  native-tool-redirect.py   # Block native tools, return guidance to use daemon
```

One file. One purpose. No enforcement, no telemetry, no state management.

Session and agent lifecycle notifications are handled by the persistent TCP
connection — connect = start, disconnect = end. No hooks needed.

---

## 7. Migration Path

### Phase 1: Build the Daemon (per companion spec)

No client changes yet. Daemon runs alongside existing system.

### Phase 2: Build DaemonClient

- Create `lib/daemon_client.py` (new ~80-line file)
- Keep `workflow_client.py` alive for backward compatibility
- Both can coexist — different consumers use different clients

### Phase 3: Migrate Consumers

Move consumers from `workflow_client` to `DaemonClient` one at a time:
- Hooks that read/write state → if hooks are being eliminated, just delete them
- Skills that import workflow_client → update imports
- Any remaining lib code → update imports

### Phase 4: Deploy Workflow Config

- Create `config/workflows/iterate.yaml` from current `phase_model.py` + `workflow.json`
- Validate daemon enforces phases correctly
- Delete `iterate_workflow.py`, `phase_model.py`, `agent_protocol.py`

### Phase 5: Delete

- Remove `hooks/` directory (or reduce to single redirect hook)
- Remove `.state/` directory (state files only; log files may move to a `logs/` directory)
- Remove all deleted `lib/` files
- Remove `workflow_client.py`

### Phase 6: Verify

- All agents function through daemon
- Permissions enforced server-side
- Telemetry recorded automatically
- Workflows advance correctly
- No file-based state anywhere

---

## 8. Post-Refactor Client Structure

```
agent-swarm/
├── agents/                      # Agent prompt definitions
│   ├── explorer.md
│   ├── implementer.md
│   ├── reviewer.md
│   ├── architect.md
│   ├── debugger.md
│   ├── researcher.md
│   ├── git-agent.md
│   └── adversary.md
│
├── skills/                      # Workflow prompt templates
│   ├── iterate/SKILL.md
│   ├── orchestrate/SKILL.md
│   ├── implement/SKILL.md
│   ├── debug/SKILL.md
│   ├── verify/SKILL.md
│   ├── spawn/SKILL.md
│   └── ...
│
├── config/                      # Declarative configuration
│   ├── backends.json            # MCP backend declarations
│   ├── permissions.yaml         # Permission rules
│   └── workflows/               # Workflow definitions
│       ├── iterate.yaml
│       └── orchestrate.yaml
│
├── lib/                         # Minimal client code
│   ├── daemon_client.py         # Thin comm layer (~80 lines)
│   └── config.py                # Config loading
│
├── bin/                         # Entry points
│   └── mcp-router               # stdio shim → daemon
│
└── hooks/                       # Minimal or empty
    └── native-tool-redirect.py  # Only if needed
```

From ~30 files and 9,000+ lines in `lib/` to 2 files and ~120 lines.
