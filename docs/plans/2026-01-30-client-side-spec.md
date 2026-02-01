# Client-Side Architecture Specification

**Date:** 2026-01-30
**Status:** Draft
**Companion:** `2026-01-30-architecture-refactor-spec.md` (daemon/server side)
**Design doc:** `2026-01-30-client-side-design.md`
**Purpose:** Implementation-ready specification for the client side of the architecture
refactor. A competent developer should be able to implement from this without asking
questions.

---

## Table of Contents

0. [Context, Scope, and Trust Model](#0-context-scope-and-trust-model)
1. [DaemonClient](#1-daemonclient)
2. [Workflow Config Schema](#2-workflow-config-schema)
3. [Agent Definitions](#3-agent-definitions)
4. [Config Loader](#4-config-loader)
5. [Native Tool Redirect Hook](#5-native-tool-redirect-hook)
6. [Deletion Manifest](#6-deletion-manifest)
7. [Migration Sequence](#7-migration-sequence)
8. [Verification Criteria](#8-verification-criteria)

---

## 0. Context, Scope, and Trust Model

### Trust Model

This client operates in a **fully trusted local environment**, identical to the
daemon's trust model (see companion spec §0). Key implications for the client side:

- **DaemonClient is a local-only shim, not a general-purpose API client.** It connects
  to `127.0.0.1` only. No TLS, no authentication, no token exchange.
- **Agent identity is self-reported and unauthenticated.** Any client can claim any
  agent_id and agent_type via `register()`. The daemon records this for coordination
  and telemetry, not for security. All clients run under the same OS user.
- **Agent state isolation is cooperative, not enforced.** A client registered as
  agent "A" can read/write state for agent "B" via `agent_get_state("B")`. This is
  acceptable because all clients are local and trusted. The agent state API is a
  shared coordination store, not a sandboxed per-agent vault.
- **No input hardening at the client.** The client does not sanitize arguments before
  sending to the daemon. The daemon handles malformed input (see companion spec §3
  framing rules).
- **Permission enforcement is entirely daemon-side.** The client sends requests; the
  daemon decides what's allowed. The client never checks permissions locally.

### What This Spec Covers

The client side: everything that is NOT the daemon process. This includes:

- The Python client library that talks to the daemon
- Configuration files that the daemon loads (authored and stored client-side)
- Agent definition files (markdown with protocol metadata)
- The single remaining hook (native tool redirect), if needed
- What gets deleted and how to migrate

### What This Spec Does NOT Cover

- The daemon itself (see companion spec)
- Wire protocol details (see companion spec §10)
- The stdio shim `bin/mcp-router` (see companion spec §11)
- `bin/start-claude` startup script (see companion spec §2)

### Primary Clients of the Daemon

| Client | Transport | Uses DaemonClient? |
|---|---|---|
| Claude Code (main agent) | stdio shim → TCP | No (uses MCP natively) |
| Claude Code (subagents) | stdio shim → TCP | No (uses MCP natively) |
| Native tool redirect hook | TCP socket | Yes |
| Python scripts (testing, admin) | TCP socket | Yes |

Claude Code is the primary consumer. It speaks MCP through the stdio shim
(`bin/mcp-router`), which bridges to TCP. Claude Code does not import Python
libraries — it uses MCP tools. The DaemonClient exists for the remaining
hook (if needed) and for any Python-level consumers (tests, scripts).

### Motivation

The current client side has ~9,000 lines of Python in `lib/` that exist because
there was no daemon to handle permissions, telemetry, state, and tool interception.
Hooks (12+ scripts) compensate for the lack of a central interception point. With
the daemon owning all of these concerns, the client side reduces to:

1. **Config files** — declarative workflow and agent definitions
2. **Agent markdown** — prompt content with protocol metadata
3. **DaemonClient** — ~80-line thin comm layer (for non-Claude consumers)
4. **One hook** — native tool redirect (if Claude Code can't block natively)

---

## 1. DaemonClient

### Purpose

Thin Python client for processes that need to talk to the daemon outside of Claude
Code's MCP layer. Primary consumers: the native tool redirect hook, test harnesses,
and admin scripts.

### Interface

```python
# lib/daemon_client.py

import json
import socket
from typing import Any, Optional


DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = 7523
RECV_BUFFER = 8192
DEFAULT_TIMEOUT = 30.0
MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB — matches daemon MAX_MESSAGE_SIZE


class DaemonError(Exception):
    """Error returned by the daemon.

    Attributes:
        code: JSON-RPC error code
        message: Human-readable error message
        data: Optional additional error data
    """

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"Daemon error {code}: {message}")


class DaemonClient:
    """Thin JSON-RPC client for the agent-swarm daemon.

    One instance per consumer. NOT thread-safe — each thread that needs
    daemon access should create its own instance.

    Connection is persistent for the lifetime of the client. The daemon
    tracks agent identity per connection, so a single client instance
    represents a single agent.
    """

    def __init__(self, host: str = DAEMON_HOST, port: int = DAEMON_PORT,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        """
        Args:
            host: Daemon hostname. Always 127.0.0.1 in practice.
            port: Daemon port. Always 7523 unless overridden.
            timeout: Socket timeout in seconds for all operations.

        Creates:
            self._host: str
            self._port: int
            self._timeout: float
            self._sock: socket.socket | None = None
            self._request_id: int = 0
            self._registered: bool = False  # Set True after register()
            self._buf: bytes = b""  # Read buffer for partial responses
        """

    def connect(self) -> None:
        """Connect to the daemon and perform MCP handshake.

        1. Create socket (AF_INET, SOCK_STREAM)
        2. Set timeout to self._timeout
        3. Connect to (self._host, self._port)
        4. Reset self._buf to b""
        5. Reset self._request_id to 0
        6. Reset self._registered to False
        7. Send MCP ``initialize`` request:
           {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05",
                       "capabilities": {},
                       "clientInfo": {"name": "daemon-client", "version": "1.0"}}}
        8. Read and validate initialize response
        9. Send ``notifications/initialized`` notification:
           {"jsonrpc": "2.0", "method": "notifications/initialized"}

        The MCP handshake is required by the daemon's router before it
        accepts any other method calls.

        Raises:
            ConnectionRefusedError: Daemon is not running
            socket.timeout: Daemon did not respond within timeout
            ConnectionError: MCP handshake failed
        """

    def close(self) -> None:
        """Close connection to daemon.

        1. If self._sock is not None:
           a. self._sock.close()
           b. self._sock = None
        2. Reset self._buf to b""
        """

    def register(self, agent_id: str, agent_type: str,
                 session_id: str, workflow_id: str) -> dict:
        """Register this connection's agent identity with the daemon.

        MUST be called exactly once after connect(), before any other method.
        The daemon associates all subsequent requests on this connection with
        the registered agent context.

        Client-side guard:
        1. If self._registered is True → raise RuntimeError("Already registered")
        2. On success → set self._registered = True

        Args:
            agent_id: Unique identifier for this agent instance
            agent_type: One of the defined agent types (e.g., "implementer",
                       "explorer"). Must match an agent definition the daemon
                       has loaded.
            session_id: Claude Code session ID this agent belongs to
            workflow_id: Active workflow (e.g., "iterate"). Empty string if
                        no workflow is active.

        Returns:
            {"status": "registered"} on success

        Raises:
            DaemonError: If agent_type is unknown or registration fails
        """
        return self._call("agent/register", {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "session_id": session_id,
            "workflow_id": workflow_id,
        })

    def call_tool(self, name: str, arguments: dict) -> Any:
        """Call a tool through the daemon.

        The daemon handles permission checking, telemetry recording,
        result caching, and backend routing. The client just sends
        the request and gets the result.

        Args:
            name: Tool name as exposed by the daemon. Examples:
                  "serena__find_symbol", "native__bash", "native__read_file"
            arguments: Tool-specific arguments dict

        Returns:
            Tool result. Type varies by tool. The daemon returns the result
            as-is from the backend, after optional summarization.

        Raises:
            DaemonError: Permission denied (code -32001), tool not found
                        (code -32002), backend error (code -32003), or
                        other daemon errors
        """
        return self._call("tools/call", {
            "name": name,
            "arguments": arguments,
        })

    def list_tools(self) -> list[dict]:
        """List tools available to this agent.

        The daemon filters the tool list based on the registered agent's
        type, current workflow phase, and permission rules.

        Returns:
            List of tool definitions. Each dict contains:
            {
                "name": str,           # e.g., "serena__find_symbol"
                "description": str,
                "inputSchema": dict    # JSON Schema for arguments
            }
        """
        result = self._call("tools/list", {})
        return result.get("tools", [])

    def workflow_start(self, workflow_id: str, initial_state: dict) -> dict:
        """Start a named workflow.

        Args:
            workflow_id: Workflow identifier. Must match a workflow config
                        file the daemon has loaded (e.g., "iterate").
            initial_state: Initial state dict. Schema is workflow-specific.

        Returns:
            {"status": "started", "workflow_id": workflow_id}

        Raises:
            DaemonError: If workflow_id is unknown or already active
        """
        return self._call("workflow/start", {
            "workflow_id": workflow_id,
            "initial_state": initial_state,
        })

    def workflow_stop(self, workflow_id: str) -> dict:
        """Stop a workflow and clear its state.

        Returns:
            {"status": "stopped", "workflow_id": workflow_id}

        Raises:
            DaemonError: If workflow_id is not active
        """
        return self._call("workflow/stop", {
            "workflow_id": workflow_id,
        })

    def workflow_get_state(self, workflow_id: str) -> dict:
        """Get full workflow state.

        Returns:
            The complete state dict for the workflow.

        Raises:
            DaemonError: If workflow_id is not active
        """
        return self._call("workflow/get_state", {
            "workflow_id": workflow_id,
        })

    # NOTE: workflow_set_state (full replacement) is NOT exposed to clients.
    # Only the daemon internally does full state replacement. Agents use
    # workflow_set_value for individual keys, with protected key enforcement.

    # NOTE: workflow_update (partial merge) is removed. Use workflow_set_value
    # for individual key updates. This keeps the API surface small and avoids
    # ambiguity about merge semantics for nested dicts.

    def workflow_get_value(self, workflow_id: str, key: str) -> Any:
        """Get a single value from workflow state.

        Returns:
            The value, or None if key doesn't exist.
        """
        return self._call("workflow/get_value", {
            "workflow_id": workflow_id,
            "key": key,
        })

    def workflow_set_value(self, workflow_id: str, key: str, value: Any) -> dict:
        """Set a single value in workflow state.

        The daemon enforces protected keys — the following keys cannot be
        written by clients and will raise DaemonError (-32004) if attempted:

        Protected keys (daemon-managed):
        - ``phase`` — use workflow_advance_phase() instead
        - ``*_checkpoint_passed`` — use workflow_pass_checkpoint() instead
        - ``active_agents`` — managed by agent/register and connection lifecycle
        - ``started_at``, ``completed_at`` — daemon-set timestamps
        - ``agent_id``, ``agent_type``, ``session_id``, ``workflow_id`` — identity

        All other keys are free-form agent coordination data. Agents use this
        to track their own progress, share results, and coordinate with each other.

        Returns:
            {"status": "updated", "workflow_id": workflow_id}

        Raises:
            DaemonError: If key is protected (-32004) or workflow not active
        """
        return self._call("workflow/set_value", {
            "workflow_id": workflow_id,
            "key": key,
            "value": value,
        })

    def workflow_is_active(self, workflow_id: str) -> bool:
        """Check if a workflow is currently active.

        Returns:
            True if workflow exists and is active, False otherwise.
            Never raises — returns False on any error.

            **Intentional design:** This method masks connection failures and
            daemon errors by returning False. This is deliberate — callers use
            this for lightweight "is anything running?" checks where False is
            the safe default. If you need to distinguish "workflow not active"
            from "daemon unreachable", use workflow_get_state() instead, which
            raises DaemonError on failure.
        """
        try:
            result = self._call("workflow/is_active", {
                "workflow_id": workflow_id,
            })
            return bool(result)
        except (DaemonError, ConnectionError):
            return False

    def workflow_advance_phase(self, workflow_id: str, target_phase: str) -> dict:
        """Request a phase transition in a workflow.

        The daemon validates the transition against the workflow definition.
        If the current phase has a checkpoint condition, the daemon verifies
        it is met before allowing the transition.

        Args:
            target_phase: Phase to transition to. Must be a valid transition
                         from the current phase per the workflow definition.

        Returns:
            {"status": "advanced", "phase": target_phase}

        Raises:
            DaemonError: If transition is invalid, checkpoint not met, or
                        workflow is not active
        """
        return self._call("workflow/advance_phase", {
            "workflow_id": workflow_id,
            "target_phase": target_phase,
        })

    def workflow_pass_checkpoint(self, workflow_id: str) -> dict:
        """Mark the current phase's checkpoint as passed.

        The daemon sets the ``{current_phase}_checkpoint_passed`` key to True
        in workflow state. Only valid when the current phase has checkpoint: true.

        Returns:
            {"status": "checkpoint_passed", "phase": current_phase}

        Raises:
            DaemonError: If current phase has no checkpoint, or workflow not active
        """
        return self._call("workflow/pass_checkpoint", {
            "workflow_id": workflow_id,
        })

    def agent_get_state(self, agent_id: str) -> Optional[dict]:
        """Get an agent's state.

        Returns:
            Agent state dict, or None if agent not found.
        """
        try:
            return self._call("agent/get_state", {"agent_id": agent_id})
        except DaemonError:
            return None

    def agent_set_state(self, agent_id: str, state: dict) -> dict:
        """Set an agent's state.

        Returns:
            {"status": "updated", "agent_id": agent_id}
        """
        return self._call("agent/set_state", {
            "agent_id": agent_id,
            "state": state,
        })

    def agent_delete(self, agent_id: str) -> dict:
        """Delete an agent's state.

        Returns:
            {"status": "deleted", "agent_id": agent_id}
        """
        return self._call("agent/delete", {"agent_id": agent_id})

    def agent_list(self) -> list[str]:
        """List all registered agent IDs.

        Returns:
            List of agent ID strings.
        """
        result = self._call("agent/list", {})
        if isinstance(result, list):
            return result
        return []

    # ─────────────────────────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────────────────────────

    def _call(self, method: str, params: dict) -> Any:
        """Send JSON-RPC request, block for response, return result.

        1. If self._sock is None → raise ConnectionError("Not connected")
        2. If method != "agent/register" and not self._registered:
           → raise RuntimeError("Must call register() before other methods")
        3. Increment self._request_id
        4. Build request:
           {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}
        5. Serialize to JSON, encode UTF-8, append newline
        6. self._sock.sendall(payload)
        7. Read response via _read_response()
        8. Decode UTF-8. On UnicodeDecodeError → raise ConnectionError(
           "Invalid UTF-8 from daemon — possible protocol desynchronization")
        9. Parse JSON. On JSONDecodeError → raise ConnectionError(
           "Invalid JSON from daemon — possible protocol desynchronization")
        10. Validate response["id"] == self._request_id. On mismatch →
            raise ConnectionError(
            f"Response ID mismatch: expected {self._request_id}, got {response['id']}")
        11. If "error" in response → raise DaemonError(code, message, data)
        12. Return response["result"]

        Raises:
            RuntimeError: Not registered (for non-register methods)
            ConnectionError: Not connected, connection lost, or protocol error
            DaemonError: Daemon returned an error response
            socket.timeout: No response within timeout
        """

    def _read_response(self) -> bytes:
        """Read exactly one newline-delimited response from the socket.

        1. While b"\\n" not in self._buf:
           a. If len(self._buf) > MAX_RESPONSE_SIZE:
              → raise ConnectionError(
                f"Response exceeds {MAX_RESPONSE_SIZE} bytes — "
                "possible protocol desynchronization")
           b. chunk = self._sock.recv(RECV_BUFFER)
           c. If not chunk → raise ConnectionError("Daemon closed connection")
           d. self._buf += chunk
        2. Split on first b"\\n": line, self._buf = self._buf.split(b"\\n", 1)
        3. Return line (as raw bytes — caller handles decoding)

        The buffer (self._buf) persists across calls to handle cases where
        a recv() returns data spanning multiple responses. Each call
        consumes exactly one line and preserves the remainder.

        The MAX_RESPONSE_SIZE cap prevents unbounded memory growth if the
        daemon misbehaves or the connection desynchronizes (e.g., binary
        garbage without newlines).
        """

    def __enter__(self) -> "DaemonClient":
        """Context manager support. Calls connect()."""
        self.connect()
        return self

    def __exit__(self, *args) -> None:
        """Context manager support. Calls close()."""
        self.close()
```

### Error Codes

The daemon returns standard JSON-RPC error codes plus custom codes.
The client surfaces these via DaemonError.

| Code | Meaning | When | Retryable? |
|---|---|---|---|
| -32700 | Parse error | Malformed JSON in request | No — client bug |
| -32600 | Invalid request | Missing required JSON-RPC fields | No — client bug |
| -32601 | Method not found | Unknown method | No — client bug |
| -32602 | Invalid params | Missing or wrong-typed parameters | No — client bug |
| -32603 | Internal error | Unexpected daemon failure | Maybe — transient daemon issue |
| -32001 | Permission denied | Agent not allowed to call this tool in current phase | No — change phase first |
| -32002 | Tool not found | Tool name doesn't match any backend | No — client bug |
| -32003 | Backend error | Backend MCP server returned an error | Maybe — backend may recover |
| -32004 | Workflow error | Invalid workflow operation (bad transition, not active, etc.) | No — logic error |
| -32005 | Registration required | Called a method before agent/register | No — client bug |

**Retryable errors** (-32603, -32003) may succeed on retry if the underlying
issue is transient (e.g., backend temporarily unavailable). All other errors
indicate logic errors or invalid state that won't resolve by retrying.

**`data` field:** The `data` field on DaemonError is optional and its shape
varies by error code. Treat it as opaque diagnostic information for logging.
Do not parse or branch on it.

### Thread Safety

DaemonClient is **NOT thread-safe**. Each thread or async context that
needs daemon access must create its own instance. This is by design:
each connection represents one agent identity, and agents don't share
connections.

### Reconnection Policy

DaemonClient does **NOT** auto-reconnect. If the connection drops:
1. The current `_call()` raises `ConnectionError`
2. The consumer must explicitly call `close()` then `connect()` to reconnect
3. After reconnecting, the consumer must call `register()` again

Auto-reconnection is deliberately omitted because:
- A dropped connection means the daemon may have restarted, invalidating
  all prior state (workflow, agent registration, cached permissions)
- Silent reconnection would mask failures and create subtle bugs
- The consumer needs to decide how to handle the state loss

### Usage Examples

```python
# Hook usage (short-lived)
client = DaemonClient()
client.connect()
client.register("hook-abc", "hook", session_id, "")
result = client.call_tool("native__read_file", {"file_path": "/some/path"})
client.close()

# Context manager usage
with DaemonClient() as client:
    client.register("test-agent", "explorer", "test-session", "iterate")
    tools = client.list_tools()
    state = client.workflow_get_state("iterate")

# Admin script
client = DaemonClient()
client.connect()
client.register("admin", "admin", "admin-session", "")
agents = client.agent_list()
for agent_id in agents:
    state = client.agent_get_state(agent_id)
    print(f"{agent_id}: {state}")
client.close()
```

---

## 2. Workflow Config Schema

### Purpose

Declarative workflow definitions that the daemon loads on startup. Each
YAML file defines a state machine: phases, transitions, tool restrictions,
and agent eligibility. The daemon enforces these rules; the client (Claude
agent) reasons about what to do within the rules.

### File Location

```
config/workflows/
├── iterate.yaml
├── orchestrate.yaml
└── (future workflows)
```

The daemon loads all `*.yaml` files from `config/workflows/` on startup.
Each file defines exactly one workflow.

### Schema

```yaml
# Every field is shown. No optional fields — all must be present.

name: string
# Unique identifier. Used in workflow/start, workflow/get_state, etc.
# Must match the filename without extension (iterate.yaml → name: iterate).
# Regex: ^[a-z][a-z0-9_]{0,63}$

description: string
# Human-readable description. Not used programmatically.

initial_phase: string
# Phase name to start in when workflow/start is called.
# Must reference a phase defined in the phases list.

terminal_phase: string
# Special phase name that indicates workflow completion.
# Does NOT appear in the phases list — it's a virtual state.
# When a transition targets this phase, the daemon marks the
# workflow as complete (workflow/is_active returns false).
# Regex: ^[a-z][a-z0-9_]{0,63}$
#
# Implications of reaching terminal_phase:
# - workflow/is_active returns false
# - workflow/get_state still returns the final state (state persists)
# - workflow/advance_phase is rejected (no transitions from terminal)
# - No tool restrictions apply (no phase = no enforcement)
# - The workflow can be explicitly stopped via workflow/stop to clear state
# - A new instance can be started via workflow/start

max_agents: integer
# Maximum concurrent agents allowed in this workflow.
# The daemon rejects agent/register if this limit is reached.
# Value: 1-64

phases:
  - name: string
    # Phase identifier. Unique within this workflow.
    # Regex: ^[a-z][a-z0-9_]{0,63}$

    allowed_tool_categories: list[string]
    # Which tool categories are available in this phase.
    # Values from the ToolCategory enum:
    #   FILE_READ      — Read file contents (native__read_file, serena__read_file)
    #   FILE_WRITE     — Write/create files (native__write_file, serena__create_text_file)
    #   FILE_SEARCH    — Search files (native__glob, native__grep, serena__find_file)
    #   CODE_QUERY     — Semantic code queries (serena__find_symbol, serena__get_symbols_overview)
    #   CODE_EDIT      — Edit code (serena__replace_content, serena__replace_symbol_body)
    #   SHELL_SAFE     — Shell execution (native__bash)
    #                   CAVEAT: The name "SAFE" is relative. This category allows
    #                   arbitrary shell commands. It is "safe" only in the sense
    #                   that the daemon logs and permission-gates it, not that the
    #                   commands themselves are sandboxed. Workflow authors should
    #                   understand that enabling SHELL_SAFE grants full shell access.
    #   WEB_RESEARCH   — Web access (context7__*, playwright__*)
    #   MEMORY         — Memory tools (memory__*)
    #   SUBAGENT       — Subagent spawning
    #   USER_INTERACTION — User-facing interaction
    # An empty list means NO tools allowed in this phase.

    blocked_tools: list[string]
    # Specific tools blocked regardless of category.
    # These are tool names as exposed by the daemon (e.g., "native__bash").
    # blocked_tools takes precedence over allowed_tool_categories.
    # An empty list means no additional blocks beyond category restrictions.

    eligible_agents: list[string]
    # Agent types allowed to operate in this phase.
    # Values must match agent definition names (e.g., "implementer", "explorer").
    # An empty list means ALL agent types are eligible.

    checkpoint: boolean
    # If true, the daemon requires a checkpoint condition to be met
    # before allowing a transition OUT of this phase.
    #
    # Checkpoint semantics:
    # - When a client calls workflow/advance_phase from a checkpoint phase,
    #   the daemon checks the workflow state for a key named
    #   "{phase_name}_checkpoint_passed" with value true.
    # - If the key is missing or false, the transition is rejected with
    #   DaemonError code -32004.
    # - The client (agent) is responsible for setting this key via
    #   workflow/set_value when the checkpoint condition is met
    #   (e.g., tests pass, review approved).
    #
    # Convention enforcement: The daemon constructs the key name
    # programmatically as f"{current_phase}_checkpoint_passed". This is
    # a fixed convention, not a configurable pattern. Agents MUST use
    # this exact key. Example:
    #   Phase "test" → key "test_checkpoint_passed"
    #   Phase "review" → key "review_checkpoint_passed"
    #
    # The daemon validates the key name at transition time. Typos in
    # client code (e.g., "tests_checkpoint_passed" instead of
    # "test_checkpoint_passed") will simply fail the checkpoint check,
    # surfacing as a -32004 error.

transitions:
  phase_name: list[string]
  # Map of phase name → list of valid target phases.
  # Every phase in the phases list MUST have an entry here.
  # Target phases must be either a defined phase name or terminal_phase.
  # The daemon rejects workflow/advance_phase if the target is not in
  # the list for the current phase.
```

### Validation Rules

The daemon validates workflow configs on startup. If validation fails,
the daemon logs the error and refuses to start.

1. `name` must match filename (without `.yaml` extension)
2. `initial_phase` must reference a phase in the `phases` list
3. `terminal_phase` must NOT be a phase in the `phases` list
4. Every phase name must be unique within the workflow
5. Every phase referenced in `transitions` values must exist in `phases`
   or equal `terminal_phase`
6. Every phase in `phases` must have an entry in `transitions`
7. `allowed_tool_categories` values must be valid ToolCategory names
8. `eligible_agents` values must match loaded agent definition names
9. `max_agents` must be between 1 and 64
10. The workflow graph must be connected: `initial_phase` must be able
    to reach `terminal_phase` through some sequence of transitions

### Example: iterate.yaml

```yaml
name: iterate
description: "TDD implementation loop with review gates"
initial_phase: test_writing
terminal_phase: complete
max_agents: 3

phases:
  - name: test_writing
    allowed_tool_categories:
      - FILE_READ
      - FILE_WRITE
      - CODE_QUERY
      - FILE_SEARCH
      - SHELL_SAFE
    blocked_tools: []
    eligible_agents:
      - implementer
    checkpoint: false

  - name: implement
    allowed_tool_categories:
      - FILE_READ
      - FILE_WRITE
      - CODE_QUERY
      - CODE_EDIT
      - FILE_SEARCH
      - SHELL_SAFE
    blocked_tools: []
    eligible_agents:
      - implementer
    checkpoint: false

  - name: test
    allowed_tool_categories:
      - FILE_READ
      - SHELL_SAFE
    blocked_tools:
      - native__write_file
      - serena__create_text_file
      - serena__replace_content
      - serena__replace_symbol_body
    eligible_agents:
      - debugger
      - implementer
    checkpoint: true

  - name: review
    allowed_tool_categories:
      - FILE_READ
      - CODE_QUERY
      - WEB_RESEARCH
    blocked_tools:
      - native__bash
      - native__write_file
      - serena__create_text_file
      - serena__replace_content
      - serena__replace_symbol_body
    eligible_agents:
      - reviewer
      - adversary
    checkpoint: true

  - name: coverage
    allowed_tool_categories:
      - FILE_READ
      - FILE_WRITE
      - SHELL_SAFE
      - WEB_RESEARCH
    blocked_tools: []
    eligible_agents:
      - reviewer
      - implementer
    checkpoint: false

transitions:
  test_writing:
    - implement
  implement:
    - test
  test:
    - implement
    - coverage
    - review
  coverage:
    - test
    - review
  review:
    - implement
    - complete
```

### Example: orchestrate.yaml

```yaml
name: orchestrate
description: "Task coordination and agent spawning"
initial_phase: plan
terminal_phase: done
max_agents: 1

phases:
  - name: plan
    allowed_tool_categories:
      - FILE_READ
      - FILE_SEARCH
      - CODE_QUERY
      - WEB_RESEARCH
      - USER_INTERACTION
    blocked_tools:
      - native__bash
      - native__write_file
    eligible_agents:
      - architect
    checkpoint: false

  - name: execute
    allowed_tool_categories:
      - FILE_READ
      - FILE_SEARCH
      - CODE_QUERY
      - SUBAGENT
      - USER_INTERACTION
    blocked_tools:
      - native__bash
      - native__write_file
    eligible_agents: []
    checkpoint: false

  - name: finalize
    allowed_tool_categories:
      - FILE_READ
      - SHELL_SAFE
      - USER_INTERACTION
    blocked_tools: []
    eligible_agents: []
    checkpoint: false

transitions:
  plan:
    - execute
  execute:
    - plan
    - finalize
  finalize:
    - execute
    - done
```

---

## 3. Agent Definitions

### Purpose

Define agent types: their prompt content (for Claude) and their protocol
metadata (for the daemon). Each agent is a single markdown file with YAML
frontmatter.

### File Location

```
agents/
├── explorer.md
├── implementer.md
├── reviewer.md
├── architect.md
├── debugger.md
├── researcher.md
├── git-agent.md
└── adversary.md
```

The daemon loads all `*.md` files from `agents/` on startup, parsing the
YAML frontmatter for protocol metadata.

### Format

```markdown
---
name: string
# Agent type identifier. Must be unique across all agent files.
# Used in workflow eligible_agents, agent/register, permission rules.
# Regex: ^[a-z][a-z0-9_-]{0,63}$

model: string
# Claude model to use for this agent type.
# Values: "haiku", "sonnet", "opus"
# Informational — the daemon records this in telemetry but does not
# enforce it (model selection is Claude Code's responsibility).

max_output_chars: integer
# Maximum characters in agent output.
# Informational — guidance for the agent prompt, not daemon-enforced.
# Value: 100-10000

can_write_files: boolean
# Whether this agent type is expected to write files.
# Informational — actual enforcement is via workflow phase permissions.
---

# Agent Name

Prompt content follows the frontmatter. This is the agent's system prompt
or description that gets loaded into the Claude context when this agent
type is spawned.

Everything below the frontmatter separator is treated as raw markdown
and passed to Claude as-is.
```

### Informational vs Enforced Fields

**Explicitly informational fields:** `model`, `max_output_chars`, `can_write_files`.

These fields are metadata for documentation, telemetry, and prompt guidance.
The daemon records them but does **not** enforce them. Enforcement of tool
access and file write permissions is entirely via workflow phase config
(§2 `allowed_tool_categories`, `blocked_tools`). Model selection is Claude
Code's responsibility, not the daemon's.

**Why not enforce them?** Because the same agent type may legitimately need
different capabilities in different workflows or phases. An implementer in
`implement` phase can write files; the same implementer type in a hypothetical
`audit` phase might not. Phase-level enforcement is more flexible and avoids
duplication between agent definitions and workflow configs.

**Prompt content is opaque to the system.** The daemon does not parse, validate,
or inspect the markdown body of agent definitions. It is passed verbatim to
Claude. All behavioral correctness of the agent depends on the quality of its
prompt — this is inherent to prompt-driven systems and not something the daemon
can enforce.

### Validation Rules

The daemon validates agent definitions on startup.

1. Every `.md` file in `agents/` must have valid YAML frontmatter
2. `name` is required and must be unique across all agent files
3. `name` must match the filename without `.md` extension
4. `model` must be one of: "haiku", "sonnet", "opus"
5. `max_output_chars` must be between 100 and 10000
6. `can_write_files` must be a boolean
7. If any `eligible_agents` value in any workflow config references an
   agent name that doesn't exist, the daemon logs a warning (not an error —
   workflows can reference agents that haven't been defined yet)

### Example: implementer.md

```markdown
---
name: implementer
model: sonnet
max_output_chars: 1500
can_write_files: true
---

# Implementer Agent

Code implementation - new functionality, modifications, side-effect safety.

## Tools
| Op | Tool |
|----|------|
| Search code | `serena__search_for_pattern` |
| Read files | `serena__read_file`, `native__read_file` |
| Find symbols | `serena__find_symbol`, `serena__get_symbols_overview` |
| Find files | `native__glob`, `serena__find_file` |
| Run commands | `native__bash` (git, pytest, ruff, gh) |
| Edit code | `serena__replace_content`, `serena__replace_symbol_body` |

## Constraints
- Verify changes compile/pass before completing
- Never modify files outside the task scope
- Report side-effects explicitly in output
```

### What Frontmatter Replaces

| Current | After |
|---|---|
| `lib/agent_protocol.py` `AgentProtocol.name` | Frontmatter `name` |
| `lib/agent_protocol.py` `AgentProtocol.model` | Frontmatter `model` |
| `lib/agent_protocol.py` `AgentProtocol.max_output_chars` | Frontmatter `max_output_chars` |
| `lib/agent_protocol.py` `AgentProtocol.can_write_files` | Frontmatter `can_write_files` |
| `lib/agent_protocol.py` `AgentProtocol.allowed_tool_categories` | Workflow config `phases[].eligible_agents` + `phases[].allowed_tool_categories` |
| `lib/agent_protocol.py` `AgentProtocol.blocked_tools` | Workflow config `phases[].blocked_tools` |
| `lib/agent_protocol.py` `AgentProtocol.allowed_phases` | Workflow config `phases[].eligible_agents` |

The key insight: tool restrictions are phase-specific, not agent-specific.
An implementer in the `implement` phase has different tool access than an
implementer in the `test` phase. This is defined in the workflow config,
not the agent definition.

---

## 4. Config Loader

### Purpose

Single module that loads and validates all client-side configuration.
The daemon calls this on startup.

### Interface

```python
# lib/config.py

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml


CONFIG_DIR = Path(__file__).parent.parent / "config"
AGENTS_DIR = Path(__file__).parent.parent / "agents"


@dataclass(frozen=True)
class PhaseConfig:
    """Single phase within a workflow."""
    name: str
    allowed_tool_categories: frozenset[str]
    blocked_tools: frozenset[str]
    eligible_agents: frozenset[str]
    checkpoint: bool


@dataclass(frozen=True)
class WorkflowConfig:
    """Complete workflow definition."""
    name: str
    description: str
    initial_phase: str
    terminal_phase: str
    max_agents: int
    phases: dict[str, PhaseConfig]       # name → PhaseConfig
    transitions: dict[str, frozenset[str]]  # phase → set of target phases


@dataclass(frozen=True)
class AgentConfig:
    """Agent type definition (from frontmatter)."""
    name: str
    model: str
    max_output_chars: int
    can_write_files: bool
    prompt_content: str    # Everything after the frontmatter


@dataclass(frozen=True)
class BackendConfig:
    """MCP backend configuration."""
    name: str
    command: list[str]
    tool_prefix: str


def load_workflows() -> dict[str, WorkflowConfig]:
    """Load all workflow configs from config/workflows/.

    1. Glob CONFIG_DIR / "workflows" / "*.yaml"
    2. For each file:
       a. Parse YAML
       b. Validate against schema (see §2 Validation Rules)
       c. Build WorkflowConfig
    3. Check for duplicate workflow names across files
    4. Return dict of name → WorkflowConfig

    Raises:
        ConfigError: If any validation fails. Message includes
                    file path and specific validation failure.
    """


def load_agents() -> dict[str, AgentConfig]:
    """Load all agent definitions from agents/.

    1. Glob AGENTS_DIR / "*.md"
    2. For each file:
       a. Split on first "---" / "---" to extract YAML frontmatter
       b. Parse YAML frontmatter
       c. Validate against schema (see §3 Validation Rules)
       d. Build AgentConfig with remaining content as prompt_content
    3. Check for duplicate agent names across files
    4. Return dict of name → AgentConfig

    Raises:
        ConfigError: If any validation fails. Message includes
                    file path and specific validation failure.
    """


def load_backends() -> dict[str, BackendConfig]:
    """Load backend configs from config/backends.json.

    1. Read CONFIG_DIR / "backends.json"
    2. Parse JSON
    3. For each entry:
       a. Validate "command" is a non-empty list of strings
       b. Validate "tool_prefix" is a non-empty string
       c. Build BackendConfig
    4. Return dict of name → BackendConfig

    Raises:
        ConfigError: If file is missing, invalid JSON, or
                    validation fails.
    """


def load_permissions() -> dict:
    """Load permission rules from config/permissions.yaml.

    1. Read CONFIG_DIR / "permissions.yaml"
    2. Parse YAML
    3. Return raw dict (PermissionChecker handles interpretation)

    The daemon's PermissionChecker (see companion spec §5) consumes
    this directly. No client-side validation beyond valid YAML.

    Raises:
        ConfigError: If file is missing or invalid YAML.
    """


def load_all() -> tuple[dict[str, WorkflowConfig],
                         dict[str, AgentConfig],
                         dict[str, BackendConfig],
                         dict]:
    """Load all configuration. Convenience method for daemon startup.

    Returns:
        (workflows, agents, backends, permissions)

    Raises:
        ConfigError: If any config fails to load or validate.
    """
    workflows = load_workflows()
    agents = load_agents()
    backends = load_backends()
    permissions = load_permissions()

    # Cross-validation
    known_agents = set(agents.keys())
    known_backends = set(backends.keys())

    for wf in workflows.values():
        for phase in wf.phases.values():
            # Warn on unknown agents
            for agent_name in phase.eligible_agents:
                if agent_name not in known_agents:
                    import logging
                    logging.warning(
                        f"Workflow '{wf.name}' phase '{phase.name}' "
                        f"references unknown agent '{agent_name}'"
                    )

            # Warn on blocked_tools that don't match any backend's prefix
            for tool_name in phase.blocked_tools:
                prefix = tool_name.split("__")[0] if "__" in tool_name else None
                if prefix and prefix not in known_backends:
                    import logging
                    logging.warning(
                        f"Workflow '{wf.name}' phase '{phase.name}' "
                        f"blocks tool '{tool_name}' but no backend "
                        f"with prefix '{prefix}' is configured"
                    )

    return workflows, agents, backends, permissions


class ConfigError(Exception):
    """Configuration loading or validation error."""
    pass
```

### Frontmatter Parsing

The YAML frontmatter parser is deliberately simple and **strict**:
files that lack valid frontmatter cause a hard startup failure. This is
intentional — a missing or malformed frontmatter block means the daemon
has no protocol metadata for that agent type, which would cause confusing
runtime errors. Fail fast on startup instead.

```python
def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content.

    1. If content does not start with "---\\n" → raise ConfigError
    2. Find second "---\\n" (or "---" at end of file)
    3. yaml.safe_load() the content between the two markers
    4. Return (frontmatter_dict, remaining_content)

    The remaining_content is everything after the closing "---\\n",
    stripped of leading whitespace.
    """
```

---

## 5. Native Tool Redirect Hook

### Context

Claude Code has built-in native tools (Read, Write, Edit, Bash, Glob, Grep)
that execute directly without going through MCP servers. These bypass the
daemon entirely, making them invisible to permissions, telemetry, and caching.

### Best Case: No Hook Needed

If Claude Code supports disabling native tools via configuration (e.g., a
`disabledTools` setting or MCP server configuration that overrides native
tools), then no hook is needed. The daemon exposes equivalent tools via
backends (`native__read_file`, `native__bash`, etc.) and native tools are
simply unavailable.

**Status:** Pending confirmation. If native tool blocking is available via
config, this entire section is deleted and `hooks/` directory is removed.

### Fallback: Single Redirect Hook

If a hook is required:

```
hooks/
└── native-tool-redirect.py
```

### Hook Specification

**File:** `hooks/native-tool-redirect.py`

**Trigger:** PreToolUse hook for tools: Read, Write, Edit, Bash, Glob, Grep

**Behavior:**

```python
#!/usr/bin/env python3
"""Block native Claude Code tools. Force all tool usage through the daemon.

This hook runs in the PreToolUse phase. It blocks the tool call and returns
an error message directing the agent to use the daemon's equivalent tool.
"""

import json
import sys

# Map native tool names to daemon equivalents
NATIVE_TO_DAEMON = {
    "Read": "native__read_file",
    "Write": "native__write_file",
    "Edit": "native__edit_file",
    "Bash": "native__bash",
    "Glob": "native__glob",
    "Grep": "native__grep",
}


def main():
    """
    1. Read hook input from stdin (JSON with tool_name, tool_input)
    2. Look up tool_name in NATIVE_TO_DAEMON
    3. If found:
       a. Print JSON to stdout:
          {"blocked": true, "reason": "Use mcp__router__{equivalent} instead"}
       b. Exit 1 (blocks the tool call)
    4. If not found:
       a. Exit 0 (allow the tool call)
    """
    hook_input = json.loads(sys.stdin.read())
    tool_name = hook_input.get("tool_name", "")

    equivalent = NATIVE_TO_DAEMON.get(tool_name)
    if equivalent:
        result = {
            "blocked": True,
            "reason": f"[BLOCKED] '{tool_name}' blocked. Use mcp__router__{equivalent} instead.",
        }
        print(json.dumps(result))
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
```

**Lines of code:** ~35

**Dependencies:** None (stdlib only)

**This is the only hook.** No other hooks exist. No telemetry hooks, no
enforcement hooks, no session hooks, no subagent hooks. The daemon handles
all of those concerns by virtue of being in the request path.

### Accepted Limitations

This hook is **best-effort**, not airtight:

- **Depends on Claude Code honoring PreToolUse hooks.** If Claude Code changes
  its hook execution model, this hook may stop working. This is an accepted
  coupling to Claude Code's extension API.
- **Depends on stable tool naming.** If Claude Code renames its native tools
  (e.g., "Read" becomes "FileRead"), the NATIVE_TO_DAEMON mapping must be updated.
  This is a maintenance burden, not a design flaw.
- **Blocking is advisory to the agent.** The hook blocks the tool call and
  returns guidance, but cannot force the agent to use the daemon equivalent.
  The agent's prompt must reinforce that native tools are unavailable. Repeated
  blocked calls without progress indicate a prompt issue, not a hook issue.
- **Config-based blocking (best case) eliminates all of these.** If Claude Code
  supports `disabledTools` or equivalent, this hook is deleted entirely and
  none of these limitations apply.

---

## 6. Deletion Manifest

### Entire Directories

| Directory | Action | Reason |
|---|---|---|
| `hooks/` | Delete all except `native-tool-redirect.py` (if needed) | Daemon handles interception, enforcement, telemetry |
| `.state/` | Delete directory | State in daemon's state machine + DuckDB. Logs move to daemon log file. |
| `lib/stores/` | Delete directory | Daemon uses SQLite (lib/datastore.py), not DuckDB. DuckDB only needed by dashboard import script. |

### Files Deleted from `hooks/`

| File | Lines | What It Did | Who Handles It Now |
|---|---|---|---|
| `session-start.py` | ~150 | Memory search, counter reset, capability injection | Daemon: connection registration |
| `session-end.py` | ~100 | Save handoff, cleanup state | Daemon: connection close detection |
| `subagent-enforcement.py` | ~200 | Inject constraints, phase blocks, register agent | Daemon: agent/register + PermissionChecker |
| `subagent-complete.py` | ~150 | Process output, update queue, check push ready | Daemon: connection close + workflow state |
| `base-enforcement.py` | ~100 | Set up base token/tool enforcement | Daemon: PermissionChecker |
| `task-enforcement.py` | ~150 | Validate task scope, prevent overlapping edits | Daemon: PermissionChecker + workflow state |
| `telemetry-pretool.py` | ~80 | Record telemetry event | Daemon: DataStore (automatic) |
| `telemetry-posttool.py` | ~80 | Record telemetry event | Daemon: DataStore (automatic) |
| `post-tool-hook.py` | ~100 | Post-process results, update metrics | Daemon: Controller pipeline |
| `native-tool-blocking.py` | ~50 | Block direct native tool use | Replaced by `native-tool-redirect.py` or config |
| `router-event-hook.py` | ~80 | Capture router events | Daemon: DataStore (automatic) |
| `subagent-briefing.md` | ~20 | Tool reference for subagents | Agent definitions in `agents/*.md` |
| `transcript-debug.py` | ~50 | Debug logging | Daemon: logging |
| `subagent-mcp-bypass.py` | ~50 | MCP bypass for subagents | Daemon: direct access |
| `post-tool-tracking.py` | ~50 | Post-tool tracking | Daemon: DataStore |
| `post-task-tracking.py` | ~50 | Post-task tracking | Daemon: DataStore |

**Total hooks deleted:** ~1,460 lines

### Files Deleted from `lib/`

| File | Lines | What It Did | Who Handles It Now |
|---|---|---|---|
| `mcp_router.py` | ~3,800 | Main MCP router/dispatcher | Daemon itself (lib/router.py + lib/controller.py) |
| `iterate_workflow.py` | ~1,800 | Iterate workflow state machine | Workflow config YAML + daemon workflow engine |
| `orchestrate.py` | ~540 | Orchestration coordination | Workflow config + agent reasoning |
| `mcp_permissions.py` | ~500 | Permission enforcement | Daemon: lib/permissions.py |
| `telemetry_service.py` | ~300 | Event tracking | Daemon: lib/datastore.py |
| `mcp_native.py` | ~300 | Native tool MCP wrapper | Daemon: native backend |
| `workflow_server.py` | ~200 | Workflow state MCP server | Daemon: Controller workflow methods |
| `worker_pool.py` | ~200 | Parallel worker management | Daemon: agent tracking |
| `workflow_queue.py` | ~200 | Task queue | Daemon: workflow state |
| `permission_store.py` | ~200 | Permission storage | Daemon: lib/permissions.py |
| `routing_service.py` | ~200 | Tool routing/selection | Daemon: lib/controller.py |
| `workflow_state_service.py` | ~150 | Content ID storage | Daemon: lib/cache.py |
| `tool_translator.py` | ~150 | Native → MCP translation | Daemon: lib/controller.py |
| `permission_query.py` | ~150 | Permission queries | Daemon: lib/permissions.py |
| `phase_model.py` | ~146 | Phase definitions | config/workflows/*.yaml |
| `agent_protocol.py` | ~115 | Agent protocol definitions | agents/*.md frontmatter |
| `connection_pool.py` | ~100 | Connection pooling | Single daemon connection |
| `config.py` (current) | ~80 | Backend config loading | Rewritten (see §4) |
| `stores/duckdb_store.py` | ~400 | DuckDB telemetry store | Retained: used by daemon's DataStore |
| `stores/interfaces.py` | ~50 | Store interfaces | Retained: used by daemon's DataStore |
| `stores/validation.py` | ~50 | Store validation | Daemon: lib/datastore.py |
| `stores/compression.py` | ~50 | Store compression | Daemon: lib/datastore.py |

**Total lib deleted:** ~9,681 lines

### Files Modified

| File | Action |
|---|---|
| `workflow_client.py` | Delete. Replaced by `daemon_client.py` |

### Files Created

| File | Lines | Purpose |
|---|---|---|
| `lib/daemon_client.py` | ~80 | Thin comm layer (§1) |
| `lib/config.py` | ~120 | Config loading (§4, rewrite of existing) |
| `config/workflows/iterate.yaml` | ~70 | Iterate workflow definition |
| `config/workflows/orchestrate.yaml` | ~50 | Orchestrate workflow definition |
| Agent `*.md` frontmatter | ~5 each | YAML frontmatter added to 8 files |

### Files Unchanged

| File/Directory | Reason |
|---|---|
| `agents/*.md` (body content) | Prompt content stays as-is |
| `skills/` (entire directory) | Prompt templates, pure markdown |
| `config/permissions.yaml` | Daemon loads directly, no changes |
| `config/backends.json` | Daemon loads directly, no changes |
| `bin/mcp-router` | Becomes stdio shim (per daemon spec) |

### Net Change

| Metric | Before | After | Delta |
|---|---|---|---|
| Files in `lib/` (client-side) | ~22 | 2 | -20 |
| Files in `lib/` (total with daemon) | ~30 | ~12 | -18 |
| Lines in `lib/` (deleted client code) | ~9,681 | ~200 | -9,481 |
| Files in `hooks/` | ~16 | 0-1 | -15 to -16 |
| Lines in `hooks/` | ~1,460 | 0-35 | -1,425 to -1,460 |
| Config files | 3 | 5 (+2 workflow YAMLs) | +2 |
| Total lines removed | | | ~10,900 |
| Total lines added | | | ~320 + ~40 frontmatter |

---

## 7. Migration Sequence

### Dependencies

```
Phase 1 (Daemon)
    ↓
Phase 2 (DaemonClient + Config)
    ↓
Phase 3 (Workflow configs + Agent frontmatter)
    ↓
Phase 4 (Wire up daemon to load configs)
    ↓
Phase 5 (Switch traffic)
    ↓
Phase 6 (Delete old code)
    ↓
Phase 7 (Verify)
```

### Phase 1: Build the Daemon

**Prereq:** None
**Deliverable:** Working daemon per companion spec
**Detail:** Out of scope for this spec — see companion spec.

### Phase 2: Build DaemonClient and Config Loader

**Prereq:** Phase 1
**Deliverables:**
- `lib/daemon_client.py` (§1 of this spec)
- `lib/config.py` rewrite (§4 of this spec)

**Steps:**
1. Create `lib/daemon_client.py` with full DaemonClient class
2. Rewrite `lib/config.py` with new config loading functions
3. Write unit tests for DaemonClient against a mock TCP server
4. Write unit tests for config loading with valid and invalid inputs

**Verification:**
- `DaemonClient` can connect to daemon, register, call tools
- `load_workflows()` parses valid YAML and rejects invalid
- `load_agents()` parses frontmatter and rejects invalid
- `load_backends()` parses JSON and rejects invalid

### Phase 3: Create Workflow Configs and Agent Frontmatter

**Prereq:** Phase 2 (config loader must validate them)
**Deliverables:**
- `config/workflows/iterate.yaml`
- `config/workflows/orchestrate.yaml`
- YAML frontmatter on all 8 `agents/*.md` files

**Steps:**
1. Create `config/workflows/` directory
2. Translate `lib/phase_model.py` phases into `iterate.yaml`
3. Translate `config/workflow.json` orchestrate phases into `orchestrate.yaml`
4. Run `load_workflows()` to validate both files
5. Add YAML frontmatter to each agent markdown file
6. Run `load_agents()` to validate all agent files
7. Cross-validate: workflows reference only defined agents

**Verification:**
- `load_all()` succeeds with no errors or warnings
- Workflow transition graphs are connected (initial → terminal reachable)
- All agent types referenced in workflows exist

### Phase 4: Wire Daemon to Load Configs

**Prereq:** Phases 1, 2, 3
**Deliverables:** Daemon uses new config on startup

**Steps:**
1. Daemon's `main()` calls `config.load_all()` on startup
2. Pass `WorkflowConfig` objects to Controller for phase enforcement
3. Pass `AgentConfig` objects for agent registration validation
4. Pass `BackendConfig` objects to BackendManager
5. Pass permissions dict to PermissionChecker

**Verification:**
- Daemon starts with new config and handles tool calls
- Phase restrictions are enforced per workflow config
- Agent registration validates against loaded agent definitions

### Phase 5: Switch Traffic

**Prereq:** Phase 4
**Deliverables:** All consumers use daemon

**Steps:**
1. Ensure `bin/mcp-router` stdio shim is in place
2. Configure Claude Code to use `bin/mcp-router` as its MCP server
3. If native tool blocking via config is available:
   a. Configure it
   b. Skip hook creation
4. If native tool blocking requires a hook:
   a. Create `hooks/native-tool-redirect.py` (§5)
   b. Remove all other hooks
5. Update any remaining Python scripts to use DaemonClient
6. Run a full workflow cycle through the daemon

**Verification:**
- Claude Code tool calls go through daemon (visible in daemon logs)
- Native tools are blocked or redirected
- Workflow state is managed by daemon
- Telemetry is recorded by daemon
- Permissions are enforced by daemon

### Rollback Strategy

Every migration phase is committed to git before proceeding to the next.
If a phase fails:

1. `git log` to find the last known-good commit
2. `git revert` the failing phase's commits
3. The old system (workflow_client + hooks + per-session routers) continues
   to function because it is not modified until Phase 6

**Phase 6 (Delete) is the one-way door.** Before executing Phase 6:
- Phase 5 must be verified working for at least one full workflow cycle
- A git tag `pre-client-deletion` is created as a restore point
- If issues surface after deletion, `git revert` to the tag restores
  all deleted code

### Phase 6: Delete Old Code

**Prereq:** Phase 5 verified working
**Deliverables:** Clean codebase

**Steps (in this order to avoid import errors during transition):**
1. Delete `lib/stores/` directory
2. Delete individual `lib/` files per §6 Deletion Manifest
3. Delete `lib/workflow_client.py`
4. Delete all hooks except `native-tool-redirect.py` (if kept)
5. Delete `.state/` directory contents (keep directory for daemon logs if needed)
6. Delete `config/workflow.json` (replaced by `config/workflows/*.yaml`)
7. Run import checks: `python3 -c "from lib.daemon_client import DaemonClient"`
8. Run import checks: `python3 -c "from lib.config import load_all"`
9. Verify no remaining imports of deleted modules

**Verification:**
- `git status` shows only intended deletions
- No import errors in remaining code
- Daemon still starts and functions

### Phase 7: Verify End-to-End

**Prereq:** Phase 6
**Deliverables:** Confidence that everything works

**Checklist:**
- [ ] Daemon starts on `bin/start-claude`
- [ ] Claude Code connects via stdio shim
- [ ] `tools/list` returns tools filtered by agent type and phase
- [ ] `tools/call` routes to correct backend
- [ ] `tools/call` blocked for unauthorized tools (returns -32001)
- [ ] `workflow/start` creates workflow with initial state
- [ ] `workflow/advance_phase` validates transitions
- [ ] `workflow/advance_phase` enforces checkpoints
- [ ] Agent registration validates agent type against definitions
- [ ] Telemetry events recorded in DuckDB for every tool call
- [ ] Native tools blocked (via config or hook)
- [ ] Multiple concurrent agents function correctly
- [ ] Daemon survives Claude Code session restart (stays alive)
- [ ] `agents/*.md` frontmatter loads correctly
- [ ] `config/workflows/*.yaml` loads and validates correctly
- [ ] No Python files import deleted modules
- [ ] No `.state/` files used for state management (logs are OK)

---

## 8. Verification Criteria

### Acceptance Tests

These are the conditions that must be true for the client-side refactor
to be considered complete. Each maps to a specific behavior.

**AC-1: DaemonClient connects and registers**
```
Given: Daemon is running on port 7523
When: DaemonClient().connect() then register("test", "explorer", "s1", "iterate")
Then: No exception raised, response contains {"status": "registered"}
```

**AC-2: Tool calls route through daemon**
```
Given: Registered DaemonClient
When: call_tool("native__read_file", {"file_path": "/etc/hostname"})
Then: Returns file content (daemon routed to native backend)
```

**AC-3: Permissions enforced by phase**
```
Given: Agent registered as "reviewer" in workflow "iterate", phase "review"
When: call_tool("native__bash", {"command": "ls"})
Then: DaemonError raised with code -32001 (permission denied)
```

**AC-4: Workflow phase transitions validated**
```
Given: Workflow "iterate" in phase "test_writing"
When: workflow_advance_phase("iterate", "review")
Then: DaemonError raised with code -32004 (invalid transition)
When: workflow_advance_phase("iterate", "implement")
Then: Success, phase is now "implement"
```

**AC-5: Checkpoint enforcement**
```
Given: Workflow "iterate" in phase "test", checkpoint: true
When: workflow_advance_phase("iterate", "review")
Then: DaemonError raised (checkpoint not passed)
When: workflow_pass_checkpoint("iterate")
Then: workflow_advance_phase("iterate", "review") succeeds
```

**AC-6: Agent definitions loaded from frontmatter**
```
Given: agents/implementer.md with frontmatter name: implementer, model: sonnet
When: Daemon starts and agent registers as "implementer"
Then: Registration succeeds, daemon records model as "sonnet"
```

**AC-7: Workflow configs loaded from YAML**
```
Given: config/workflows/iterate.yaml with 5 phases
When: Daemon starts
Then: load_workflows() returns WorkflowConfig with 5 PhaseConfigs
And: Transition validation works per the transitions map
```

**AC-8: Native tools blocked**
```
Given: Claude Code session with daemon as MCP server
When: Agent attempts to use native Read tool
Then: Tool is blocked (via config or hook) with guidance to use daemon equivalent
```

**AC-9: No deleted code imported**
```
Given: Refactor complete
When: grep -r "from lib.iterate_workflow" . (and similar for all deleted modules)
Then: No matches in any remaining file
```

**AC-10: Clean file structure**
```
Given: Refactor complete
When: ls lib/
Then: Daemon modules (daemon.py, router.py, controller.py, permissions.py,
      backends.py, llm.py, datastore.py, cache.py, errors.py — per companion spec)
      plus client modules (daemon_client.py, config.py)
      plus stores/ and __init__.py if needed.
      No deleted modules (iterate_workflow.py, mcp_router.py, mcp_permissions.py,
      workflow_client.py, orchestrate.py, worker_pool.py, etc.)
When: ls hooks/
Then: Empty or contains only native-tool-redirect.py
```

### Debugging Strategy

The thin client design means nearly all logic lives in the daemon. This is
a strength (one place to look), but it means client-side bugs often manifest
as daemon-side symptoms. Guidelines for debugging:

- **DaemonError with unexpected code:** Check daemon logs first. The daemon
  logs every request, permission decision, and backend dispatch. The client
  error is a consequence, not a cause.
- **ConnectionError:** Check if daemon is running (`is_running()`). Check if
  another process grabbed the port. Check daemon logs for crash/restart.
- **RuntimeError ("Not registered" / "Already registered"):** Client lifecycle
  bug. The consumer is calling methods in the wrong order.
- **Silent failures (workflow_is_active returns False unexpectedly):** Use
  `workflow_get_state()` instead to get an explicit error.
- **Permission denied on a tool that should be allowed:** Check the workflow
  config YAML (is the agent in `eligible_agents`? is the tool's category in
  `allowed_tool_categories`? is the tool in `blocked_tools`?). Then check
  `config/permissions.yaml` for global overrides.
- **Daemon logs are the single source of truth.** When in doubt, read the
  daemon log. Every tool call, every permission decision, every error is
  recorded there with timestamps and agent context.
