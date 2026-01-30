# Architecture Refactor Specification

**Date:** 2026-01-30
**Status:** Draft
**Companion:** `2026-01-30-architecture-refactor-design.md`
**Purpose:** Implementation-ready specification. A competent developer should be able to implement from this without asking questions.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Daemon](#2-daemon)
3. [Router](#3-router)
4. [Controller](#4-controller)
5. [PermissionChecker](#5-permissionchecker)
6. [BackendManager](#6-backendmanager)
7. [LLMService](#7-llmservice)
8. [DataStore](#8-datastore)
9. [Cache](#9-cache)
10. [Wire Protocol](#10-wire-protocol)
11. [Client Shim](#11-client-shim)
12. [Configuration](#12-configuration)
13. [Error Handling](#13-error-handling)
14. [Threading Model](#14-threading-model)
15. [Startup & Shutdown](#15-startup--shutdown)
16. [Migration Compatibility](#16-migration-compatibility)

---

## 0. Design Tradeoffs and Trust Model

### Dominant Tradeoff: Simplicity Over Performance

When simplicity and performance conflict, simplicity wins. This daemon is a local orchestrator for a single developer's machine, not a high-throughput server. Specific implications:

- **Thread-per-connection over thread pool.** Simpler, sufficient for expected load (<64 concurrent connections).
- **Serialized backend access over concurrent.** MCP backends (Serena, etc.) are single-threaded servers on stdio. Concurrent calls to the same backend would corrupt the stdio stream. One lock per backend is not a limitation — it's a correctness requirement.
- **In-memory state over distributed state.** One process, one dict, one lock. No distributed consensus, no eventual consistency, no replication.
- **TTL-based cache eviction over LRU.** Simpler, good enough for ephemeral content.

### Trust Model

This daemon operates in a **fully trusted local environment**. All clients (Claude Code, hooks, background agents) run on the same machine under the same user. Specific assumptions:

- **All clients are local and trusted.** The daemon listens on `127.0.0.1` only. No network exposure, no TLS, no authentication.
- **Agent identity (`_caller`) is self-reported and not authenticated.** Any client can claim any identity. This is acceptable because all clients are local processes under the same user. The permission system is a guardrail for AI agent behavior, not a security boundary against adversarial clients.
- **Request sizes are assumed reasonable.** No DDoS protection. Malformed or oversized input is handled gracefully (rejected, not buffered indefinitely) but not treated as an attack vector.
- **`native__bash` and filesystem access are inherently powerful.** The daemon exposes arbitrary shell execution and unrestricted filesystem access. These are gated by permissions, which are guardrails for AI agent coordination, not sandboxes. Any permissions bypass is a bug that degrades agent coordination, not a security breach — the human user already has full access to everything the daemon can do.
- **Failures are assumed rare and recoverable.** Crash → restart → workflows can be restarted. No HA, no replication, no failover (by design — this replaces a system that had fragile failover).

### What This Daemon Is NOT

- Not a production server exposed to the network
- Not a hardened security boundary
- Not a high-availability system
- Not designed for multi-user or multi-machine deployment

It is a **powerful, trusted local orchestrator** for a single developer's AI agent workflow.

---

## 1. Overview

### System Boundaries

```
┌─────────────────────────────────────────────────┐
│ Daemon Process (long-lived, single instance)     │
│                                                  │
│  ┌──────────┐                                    │
│  │  Router   │ ← TCP ← Claude Code (MCP)        │
│  │          │ ← TCP ← Hooks (JSON-RPC)          │
│  │          │ ← TCP ← Background agents          │
│  └────┬─────┘                                    │
│       │                                          │
│  ┌────▼──────────────────────────────────────┐   │
│  │  Controller                                │   │
│  │  ├── PermissionChecker                     │   │
│  │  ├── BackendManager ──→ Serena (subprocess)│   │
│  │  │                  ──→ Context7 (subproc) │   │
│  │  │                  ──→ Playwright (subproc│   │
│  │  ├── LLMService                            │   │
│  │  ├── DataStore ──→ DuckDB file             │   │
│  │  └── Cache (in-memory)                     │   │
│  └────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

### File Layout

```
lib/
├── daemon.py          # Daemon entry point and lifecycle
├── router.py          # TCP server, protocol handling
├── controller.py      # Orchestration, native ops, tool mapping
├── permissions.py     # Permission rule evaluation
├── backends.py        # External MCP backend management
├── llm.py             # LLM capabilities (summarization, etc.)
├── datastore.py       # Event persistence and reporting
├── cache.py           # Ephemeral keyed content storage
├── errors.py          # Exception hierarchy
├── workflow_client.py # Backward-compatible shim for existing callers
└── stores/
    ├── interfaces.py  # Abstract store interfaces
    └── duckdb_store.py # DuckDB implementation

bin/
└── start-claude       # Startup alias script
```

---

## 2. Daemon

### Purpose
Single long-lived process. Owns the Router, which owns the Controller, which owns all services. Started once, stays alive across Claude Code sessions.

### Interface

```python
# lib/daemon.py

import signal
import sys
from pathlib import Path

DEFAULT_PORT = 7523
STATE_DIR = Path(__file__).parent.parent / ".state"
PID_FILE = STATE_DIR / "daemon.pid"
PORT_FILE = STATE_DIR / "daemon.port"
LOG_FILE = STATE_DIR / "daemon.log"

def main(port: int = DEFAULT_PORT) -> None:
    """
    Entry point. Called by bin/start-claude or directly.
    
    1. Acquire exclusive flock on LOCK_FILE (STATE_DIR / "daemon.lock"):
       fd = open(LOCK_FILE, "w")
       fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
       If OSError (EAGAIN) → another daemon is running → abort
       Keep fd open for lifetime of process (released on exit)
    2. Write PID_FILE with os.getpid()
    3. Write PORT_FILE with port number
    3. Configure logging to LOG_FILE
    4. Create Router(port=port)
    5. Register signal handlers (SIGTERM, SIGINT) → graceful shutdown
    6. Call router.serve_forever()  # blocks
    7. On shutdown: clean up PID_FILE, PORT_FILE
    """

def is_running() -> bool:
    """
    Check if daemon is already running.
    
    1. Read PID_FILE
    2. If file doesn't exist → return False
    3. Read PID from file
    4. os.kill(pid, 0) — if no exception → return True
    5. If OSError (process dead) → delete stale PID_FILE → return False
    """

def get_port() -> int | None:
    """
    Get running daemon's port.
    
    1. Read PORT_FILE
    2. If file doesn't exist → return None
    3. Return int(contents)
    """

def shutdown() -> None:
    """
    Request graceful shutdown.
    
    1. Read PID_FILE
    2. os.kill(pid, signal.SIGTERM)
    """
```

### bin/start-claude

```bash
#!/bin/bash
DAEMON_PORT=7523
PLUGIN_DIR="$HOME/.claude/plugins/agent-swarm"

# Check if daemon is running
if ! python3 -c "
import sys; sys.path.insert(0, '$PLUGIN_DIR/lib')
from daemon import is_running
sys.exit(0 if is_running() else 1)
" 2>/dev/null; then
    # Start daemon in background
    python3 "$PLUGIN_DIR/lib/daemon.py" &
    disown
    # Wait for port file to appear (max 5 seconds)
    for i in $(seq 1 50); do
        [ -f "$PLUGIN_DIR/.state/daemon.port" ] && break
        sleep 0.1
    done
fi

# Launch claude normally
claude "$@"
```

---

## 3. Router

### Purpose
TCP server. Accepts connections, identifies protocol (MCP from Claude Code vs internal JSON-RPC from hooks/agents), translates to internal format, delegates to Controller, translates response back.

### Interface

```python
# lib/router.py

import socket
import threading
import json
from typing import Any

class Router:
    """
    TCP server that accepts MCP and internal JSON-RPC connections.
    All connections funnel into Controller.handle_call().
    """
    
    def __init__(self, port: int, controller: "Controller") -> None:
        """
        Args:
            port: TCP port to listen on
            controller: Controller instance to delegate to
        
        Creates:
            self._server: socket.socket (AF_INET, SOCK_STREAM)
            self._controller: Controller
            self._port: int
            self._running: bool = False
            self._tools_cache: list[dict] | None = None  # Cached tools/list response
            self._active_connections: int = 0
            self._connections_lock: threading.Lock
        
        Constants:
            MAX_CONNECTIONS = 64       # Maximum concurrent connections
            MAX_MESSAGE_SIZE = 10_MB   # 10 * 1024 * 1024 bytes
            CONNECTION_TIMEOUT = 60.0  # Per-connection read timeout (seconds)
        """
    
    def serve_forever(self) -> None:
        """
        Bind, listen, accept connections in a loop.
        
        1. self._server.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        2. self._server.bind(("127.0.0.1", self._port))
        3. self._server.listen(backlog=32)
        4. self._running = True
        5. While self._running:
           a. client, addr = self._server.accept()
           b. With self._connections_lock:
              if self._active_connections >= MAX_CONNECTIONS:
                  Send JSON-RPC error (-32603, "Too many connections") + close
                  continue
              self._active_connections += 1
           c. threading.Thread(
                target=self._handle_connection,
                args=(client,),
                daemon=True
              ).start()
        """
    
    def shutdown(self) -> None:
        """
        Graceful shutdown.
        
        1. self._running = False
        2. self._server.close()
        3. self._controller.shutdown()
        """
    
    def _handle_connection(self, client: socket.socket) -> None:
        """
        Handle a single client connection. Each connection may send
        multiple requests (keep-alive) or a single request.
        
        1. client.settimeout(CONNECTION_TIMEOUT)
        2. Try:
           a. Read newline-delimited JSON messages in a loop:
              - Accumulate bytes into buffer
              - If buffer exceeds MAX_MESSAGE_SIZE before newline:
                Send JSON-RPC error (-32600, "Message too large")
                Close connection, exit loop
              - On newline: extract complete message
           b. For each complete message:
              - Try json.loads(). On ValueError:
                Send JSON-RPC error (-32700, "Parse error")
                Continue reading (do not close — client may retry)
              - Validate "jsonrpc" == "2.0" and "method" exists.
                On missing: Send JSON-RPC error (-32600, "Invalid request")
              - response = self._dispatch(message)
              - If response is not None:
                Send json.dumps(response) + "\n"
           c. If client closes connection (recv returns b""), exit loop
           d. On socket.timeout: exit loop (idle connection cleanup)
        3. Finally:
           client.close()
           With self._connections_lock:
               self._active_connections -= 1
        """
    
    def _dispatch(self, message: dict) -> dict:
        """
        Route a parsed JSON-RPC message to the appropriate handler.
        
        Args:
            message: Parsed JSON-RPC request
                {
                    "jsonrpc": "2.0",
                    "id": <str | int>,
                    "method": <str>,
                    "params": <dict>
                }
        
        Returns:
            JSON-RPC response dict
        
        Dispatch rules:
            method == "initialize"
                → self._handle_initialize(message)
            method == "notifications/initialized"
                → None (no response for notifications)
            method == "tools/list"
                → self._handle_tools_list(message)
            method == "tools/call"
                → self._handle_tools_call(message)
            else
                → JSON-RPC error: method not found (-32601)
        """
    
    def _handle_initialize(self, message: dict) -> dict:
        """
        MCP handshake response.
        
        Returns:
            {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "agent-swarm",
                        "version": "2.0.0"
                    }
                }
            }
        """
    
    def _handle_tools_list(self, message: dict) -> dict:
        """
        Return all available tools.
        
        1. If self._tools_cache is None:
           a. native_tools = self._get_native_tool_schemas()
           b. backend_tools = self._controller.list_backend_tools()
           c. internal_tools = self._get_internal_tool_schemas()
           d. self._tools_cache = native_tools + backend_tools + internal_tools
        2. Return:
           {
               "jsonrpc": "2.0",
               "id": message["id"],
               "result": {"tools": self._tools_cache}
           }
        
        Tool names are prefixed:
            native ops:   "native__read_file", "native__bash", etc.
            backends:     "serena__find_symbol", "context7__query_docs", etc.
            internal:     "workflow__workflow_start", "router__ping", etc.
        """
    
    def _handle_tools_call(self, message: dict) -> dict:
        """
        Route a tool call to the Controller.
        
        1. Extract tool_name = message["params"]["name"]
        2. Extract args = message["params"].get("arguments", {})
        3. Try:
              result = self._controller.handle_call(tool_name, args)
           Except PermissionDeniedError as e:
              Return blocked response (see §13)
           Except Exception as e:
              Return error response (see §13)
        4. Format result as MCP response:
           {
               "jsonrpc": "2.0",
               "id": message["id"],
               "result": {
                   "content": [{"type": "text", "text": json.dumps(result)}]
               }
           }
        
        If result is an error dict (has "isError": True):
           {
               "jsonrpc": "2.0",
               "id": message["id"],
               "result": {
                   "content": [{"type": "text", "text": result["message"]}],
                   "isError": True
               }
           }
        """
    
    def invalidate_tools_cache(self) -> None:
        """Reset tools cache. Called when backends are registered/unregistered."""
        self._tools_cache = None
    
    def _get_native_tool_schemas(self) -> list[dict]:
        """
        Return MCP tool schemas for native operations.
        
        Tools:
            native__read_file:
                file_path: str (required)
                offset: int (optional, 0-indexed line)
                limit: int (optional, max lines)
            
            native__write_file:
                file_path: str (required)
                content: str (required)
            
            native__edit_file:
                file_path: str (required)
                old_string: str (required)
                new_string: str (required)
                replace_all: bool (optional, default false)
            
            native__glob:
                pattern: str (required)
                path: str (optional, default cwd)
            
            native__grep:
                pattern: str (required)
                path: str (optional, default cwd)
                output_mode: str (optional, "files" | "content")
                case_insensitive: bool (optional)
                file_glob: str (optional)
            
            native__bash:
                command: str (required)
                timeout: int (optional, default 120, max 600)
                cwd: str (optional)
        
        Each tool schema follows MCP format:
            {
                "name": "native__<op>",
                "description": "<description>",
                "inputSchema": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                }
            }
        """
    
    def _get_internal_tool_schemas(self) -> list[dict]:
        """
        Return MCP tool schemas for internal operations.
        
        Tools:
            router__ping:          {} → {"status": "ok"}
            router__list_tools:    {} → list of tool names
            router__get_full:      {content_id: str} → cached full content
            
            workflow__workflow_start:      {workflow_id: str, initial_state: dict}
            workflow__workflow_stop:       {workflow_id: str}
            workflow__workflow_is_active:  {workflow_id: str} → bool
            workflow__workflow_get_state:  {workflow_id: str} → dict | null
            workflow__workflow_set_state:  {workflow_id: str, state: dict}
            workflow__workflow_update:     {workflow_id: str, updates: dict}
            workflow__workflow_get_value:  {workflow_id: str, key: str} → any
            workflow__workflow_set_value:  {workflow_id: str, key: str, value: any}
            
            workflow__agent_get_state:    {agent_id: str} → dict | null
            workflow__agent_set_state:    {agent_id: str, state: dict}
            workflow__agent_delete:       {agent_id: str}
            workflow__list_agents:        {} → list[str]
            
            router__register_agent:       {agent_id: str, agent_type: str, roles: list[str]}
            router__update_agent_phase:   {agent_id: str, workflow: str, phase: str}
            router__get_allowed_tools:    {agent_type: str?} → list[str]
        """
```

### Connection Handling Detail

```
Client connects via TCP
  ↓
Router spawns thread
  ↓
Read loop:
  ↓
  Read bytes until \n
  ↓
  Parse JSON
  ↓
  _dispatch() → response dict
  ↓
  json.dumps(response) + \n → send
  ↓
  Continue loop (keep-alive)
  ↓
Connection closed → thread exits
```

---

## 4. Controller

### Purpose
MVC-style orchestrator. Receives tool name + args, does the right thing: check permissions, execute (locally or via backend), cache content, summarize if large, record telemetry. Returns result.

### Interface

```python
# lib/controller.py

import uuid
import os
import subprocess
import glob as glob_module
from pathlib import Path
from typing import Any, Optional

class Controller:
    """
    Orchestrates all request handling. Owns all services as properties.
    """
    
    def __init__(
        self,
        config_dir: Path,
        state_dir: Path,
    ) -> None:
        """
        Args:
            config_dir: Path to config/ directory
            state_dir: Path to .state/ directory
        
        Creates:
            self.permissions = PermissionChecker(config_dir / "permissions.yaml")
            self.backends = BackendManager(config_dir / "backends.json")
            self.llm = LLMService()
            self.data = DataStore(state_dir / "datastore.db")
            self.cache = Cache()
            
            self._tool_to_backend: dict[str, str] = {}
                Populated during backend registration.
                Maps "serena__find_symbol" → "serena"
            
            self._workflow_state: dict[str, dict] = {}
                In-memory workflow state. Keyed by workflow_id.
            
            self._agent_state: dict[str, dict] = {}
                In-memory agent state. Keyed by agent_id.
            
            self._state_lock: threading.RLock
                Protects all reads and writes to _workflow_state
                and _agent_state. Must be acquired before any
                mutation or read of these dicts.
            
            self._summarization_threshold: int = 2000
                Characters. Responses larger than this are summarized.
        """
    
    def handle_call(self, tool: str, args: dict) -> Any:
        """
        Main entry point. All tool calls go through here.
        
        Args:
            tool: Fully qualified tool name (e.g., "serena__find_symbol",
                  "native__read_file", "workflow__workflow_get_state",
                  "router__ping")
            args: Tool arguments dict
        
        Returns:
            Result value. Type varies by tool. For summarized responses,
            returns:
                {
                    "summary": str,
                    "content_id": str,
                    "full_available": True
                }
        
        Raises:
            PermissionDeniedError: Tool blocked by permissions
            BackendNotFoundError: Unknown backend prefix
            RequestTimeoutError: Backend didn't respond in time
            RouterError: Any other error
        
        Invariant: The full, unsummarized result is ALWAYS cached.
            Summarization only affects the return value. The caller can
            always retrieve the full content via content_id. The DataStore
            always records the original size, never the summary size as
            "original_size".
        
        Flow:
            0. Start timing:
               start_time = time.monotonic()
            
            1. Parse prefix and tool_name:
               prefix, _, tool_name = tool.partition("__")
               If no "__" → prefix = tool, tool_name = ""
            
            2. Check permissions:
               caller_info = args.pop("_caller", None)
               agent_info = self._resolve_agent(caller_info)
               allowed, blocked = self.permissions.check(
                   tool, args, agent_info
               )
               If not allowed → raise PermissionDeniedError(blocked)
            
            3. Route by prefix:
               "native"   → raw_result = self._handle_native(tool_name, args)
               "router"   → raw_result = self._handle_router(tool_name, args)
               "workflow"  → raw_result = self._handle_workflow(tool_name, args)
               else       → raw_result = self._handle_backend(prefix, tool_name, args)
            
            4. Cache full response (ALWAYS — before summarization):
               content_id = f"c{uuid.uuid4().hex[:12]}"
               original_size = len(str(raw_result))
               self.cache.store(content_id, raw_result)
            
            5. Summarize if needed (affects return value only):
               if original_size > self._summarization_threshold:
                   summary = self.llm.summarize(str(raw_result))
                   was_summarized = True
                   result = {
                       "summary": summary,
                       "content_id": content_id,
                       "full_available": True,
                   }
               else:
                   was_summarized = False
                   result = raw_result
            
            6. Record telemetry event:
               duration_ms = int((time.monotonic() - start_time) * 1000)
               self.data.record_event({
                   "tool": tool,
                   "backend": prefix,
                   "status": "success",
                   "duration_ms": duration_ms,
                   "original_size": original_size,
                   "summary_size": len(str(result)) if was_summarized else None,
                   "was_summarized": was_summarized,
                   "session_id": agent_info.session_id if agent_info else "",
                   "agent_id": agent_info.agent_id if agent_info else "",
                   "agent_type": agent_info.agent_type if agent_info else "",
               })
               
               Duration includes: permission check + dispatch + cache + summarization.
               It does NOT include Router-level protocol parsing or response formatting.
            
            7. Return result
        """
    
    def get_full_content(self, content_id: str) -> Any:
        """
        Retrieve cached full content by content_id.
        
        Args:
            content_id: ID returned in summarized response
        
        Returns:
            Full content, or {"error": "Content not found", "isError": True}
        
        Flow:
            1. content = self.cache.get(content_id)
            2. If content is None → return error
            3. self.data.record_event({
                   "tool": "router__get_full",
                   "backend": "router",
                   "status": "success",
               })
            4. Return content
        """
    
    def list_backend_tools(self) -> list[dict]:
        """
        Query all backends for their tool lists.
        
        Returns:
            List of MCP tool schema dicts, each with name prefixed
            by backend name (e.g., "serena__find_symbol").
        
        Flow:
            1. For each backend in self.backends.list():
               tools = self.backends.list_tools(backend_name)
               For each tool:
                   tool["name"] = f"{backend_name}__{tool['name']}"
                   self._tool_to_backend[tool["name"]] = backend_name
            2. Return all collected tools
        """
    
    def shutdown(self) -> None:
        """
        Graceful shutdown.
        
        1. self.backends.shutdown_all()
        2. self.data.close()
        """
    
    # ── Private: Native operations ──────────────────────────────
    
    def _handle_native(self, tool_name: str, args: dict) -> Any:
        """
        Execute a native operation directly.
        
        Dispatch:
            "read_file"  → self._native_read_file(args)
            "write_file" → self._native_write_file(args)
            "edit_file"  → self._native_edit_file(args)
            "glob"       → self._native_glob(args)
            "grep"       → self._native_grep(args)
            "bash"       → self._native_bash(args)
            else         → raise RouterError(f"Unknown native tool: {tool_name}")
        """
    
    def _native_read_file(self, args: dict) -> dict:
        """
        Read a file from disk.
        
        Args:
            file_path: str (required) — absolute path
            offset: int (optional) — 0-indexed line to start from
            limit: int (optional) — max lines to read
        
        Returns:
            {
                "content": str,    # file contents with line numbers (cat -n format)
                "line_count": int,
                "char_count": int,
                "truncated": bool  # True if offset/limit caused partial read
            }
        
        Errors:
            File not found → {"error": "File not found: <path>", "isError": True}
            Is directory → {"error": "Is a directory: <path>", "isError": True}
            Permission denied → {"error": "Permission denied: <path>", "isError": True}
        """
    
    def _native_write_file(self, args: dict) -> dict:
        """
        Write content to a file. Creates parent directories if needed.
        
        Args:
            file_path: str (required) — absolute path
            content: str (required) — file contents
        
        Returns:
            {"result": "File written: <path>"}
        
        Behavior:
            1. os.makedirs(parent, exist_ok=True)
            2. Write content to file (UTF-8)
        """
    
    def _native_edit_file(self, args: dict) -> dict:
        """
        Find and replace text in a file.
        
        Args:
            file_path: str (required) — absolute path
            old_string: str (required) — text to find
            new_string: str (required) — replacement text
            replace_all: bool (optional, default False) — replace all occurrences
        
        Returns:
            {"result": "Edited: <path>", "replacements": int}
        
        Errors:
            old_string not found → {"error": "String not found in file", "isError": True}
            Multiple matches when replace_all=False →
                {"error": "Multiple matches found. Use replace_all=True or provide more context.", "isError": True}
        """
    
    def _native_glob(self, args: dict) -> dict:
        """
        Find files matching a glob pattern.
        
        Args:
            pattern: str (required) — glob pattern (e.g., "**/*.py")
            path: str (optional) — directory to search in
        
        Returns:
            {"files": list[str]}  # sorted by modification time, most recent first
        """
    
    def _native_grep(self, args: dict) -> dict:
        """
        Search file contents with regex.
        
        Args:
            pattern: str (required) — regex pattern
            path: str (optional) — directory or file to search
            output_mode: str (optional) — "files" (default) or "content"
            case_insensitive: bool (optional)
            file_glob: str (optional) — filter files by glob
        
        Returns:
            If output_mode == "files":
                {"files": list[str]}
            If output_mode == "content":
                {"matches": list[{"file": str, "line": int, "text": str}]}
        
        Implementation:
            Uses subprocess to call rg (ripgrep) if available, else grep.
        """
    
    def _native_bash(self, args: dict) -> dict:
        """
        Execute a shell command.
        
        Args:
            command: str (required) — shell command
            timeout: int (optional, default 120, max 600) — seconds
            cwd: str (optional) — working directory
        
        Returns:
            {
                "exit_code": int,
                "stdout": str,
                "stderr": str,
                "timed_out": bool
            }
        
        Implementation:
            subprocess.run(
                command, shell=True,
                capture_output=True, text=True,
                timeout=timeout, cwd=cwd
            )
        """
    
    # ── Private: Internal router operations ─────────────────────
    
    def _handle_router(self, tool_name: str, args: dict) -> Any:
        """
        Handle router__ prefixed tools.
        
        Dispatch:
            "ping"               → {"status": "ok"}
            "list_tools"         → list of all tool names
            "get_full"           → self.get_full_content(args["content_id"])
            "register_agent"     → self.permissions.register_agent(...)
            "update_agent_phase" → self.permissions.update_agent_phase(...)
            "get_allowed_tools"  → self.permissions.get_allowed_tools(...)
        """
    
    # ── Private: Workflow state operations ──────────────────────
    
    def _handle_workflow(self, tool_name: str, args: dict) -> Any:
        """
        Handle workflow__ prefixed tools. All operate on in-memory dicts.
        
        Dispatch:
            "workflow_start":
                If workflow_id in self._workflow_state → error "already exists"
                self._workflow_state[workflow_id] = initial_state
                self.data.record_event(workflow_start event)
                Return initial_state
            
            "workflow_stop":
                If workflow_id not in self._workflow_state → error "not found"
                del self._workflow_state[workflow_id]
                self.data.record_event(workflow_stop event)
                Return True
            
            "workflow_is_active":
                Return workflow_id in self._workflow_state
            
            "workflow_get_state":
                Return deepcopy(self._workflow_state.get(workflow_id))
            
            "workflow_set_state":
                If workflow_id not in self._workflow_state → error "not found"
                self._workflow_state[workflow_id] = state
                Return state
            
            "workflow_update":
                If workflow_id not in self._workflow_state → error "not found"
                self._workflow_state[workflow_id].update(updates)
                Return self._workflow_state[workflow_id]
            
            "workflow_get_value":
                state = self._workflow_state.get(workflow_id)
                If state is None → return None
                Return state.get(key)
            
            "workflow_set_value":
                If workflow_id not in self._workflow_state → error "not found"
                self._workflow_state[workflow_id][key] = value
                Return True
            
            "agent_get_state":
                Return deepcopy(self._agent_state.get(agent_id))
            
            "agent_set_state":
                self._agent_state[agent_id] = state
                Return state
            
            "agent_delete":
                If agent_id in self._agent_state:
                    del self._agent_state[agent_id]
                Return True
            
            "list_agents":
                Return list(self._agent_state.keys())
        
        Thread safety:
            All workflow/agent state mutations protected by
            self._state_lock: threading.RLock
            All returns are deepcopy to prevent external mutation.
        """
    
    # ── Private: Backend dispatch ───────────────────────────────
    
    def _handle_backend(self, backend: str, tool_name: str, args: dict) -> Any:
        """
        Forward to an external backend via BackendManager.
        
        Args:
            backend: Backend name (e.g., "serena")
            tool_name: Tool name without prefix (e.g., "find_symbol")
            args: Tool arguments
        
        Returns:
            Backend response (parsed from MCP JSON-RPC)
        
        Raises:
            BackendNotFoundError: Backend not registered
            RequestTimeoutError: Backend didn't respond in 30s
            ConnectionError: Backend process died
        """
    
    # ── Private: Summarization ──────────────────────────────────
    
    def _maybe_summarize(self, result: Any, content_id: str) -> Any:
        """
        Summarize result if it exceeds the size threshold.
        
        Args:
            result: Raw result from tool execution
            content_id: Pre-generated content ID for cache retrieval
        
        Returns:
            If len(str(result)) <= 2000:
                result (unchanged)
            Else:
                {
                    "summary": self.llm.summarize(str(result)),
                    "content_id": content_id,
                    "full_available": True
                }
        
        Threshold: 2000 characters (configurable via constructor)
        """
    
    # ── Private: Agent resolution ───────────────────────────────
    
    def _resolve_agent(self, caller: str | None) -> "AgentInfo | None":
        """
        Resolve caller identifier to AgentInfo for permission checking.
        
        Args:
            caller: Value of _caller key from args, or None
        
        Returns:
            AgentInfo from self.permissions.get_agent(caller), or None
        """
```

---

## 5. PermissionChecker

### Purpose
Evaluates allow/block rules for tool calls based on agent type, roles, workflow phase.

### Interface

```python
# lib/permissions.py

from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
import yaml
import fnmatch
import threading

@dataclass
class AgentInfo:
    agent_id: str
    agent_type: str
    roles: list[str] = field(default_factory=list)
    workflow: Optional[str] = None
    phase: Optional[str] = None
    session_id: str = ""

@dataclass
class BlockedResponse:
    blocked: bool = True
    reason: str = ""
    tool: str = ""
    agent_type: str = ""
    agent_id: str = ""
    phase: str = ""
    rule_that_blocked: str = ""
    guidance: str = ""
    
    def to_dict(self) -> dict:
        return {
            "blocked": self.blocked,
            "reason": self.reason,
            "tool": self.tool,
            "agent_type": self.agent_type,
            "agent_id": self.agent_id,
            "phase": self.phase,
            "rule_that_blocked": self.rule_that_blocked,
            "guidance": self.guidance,
        }

class PermissionDeniedError(Exception):
    def __init__(self, response: BlockedResponse):
        self.response = response
        super().__init__(response.reason)

class PermissionChecker:
    """
    Evaluates tool access rules from permissions.yaml.
    Thread-safe for concurrent checks.
    """
    
    def __init__(self, config_path: Path) -> None:
        """
        Load and parse permissions.yaml.
        
        Creates:
            self._rules: dict — parsed YAML
            self._agents: dict[str, AgentInfo] — registered agents
            self._lock: threading.RLock
        """
    
    def check(
        self,
        tool: str,
        args: dict,
        agent: AgentInfo | None = None,
    ) -> tuple[bool, BlockedResponse | None]:
        """
        Check if a tool call is allowed.
        
        Args:
            tool: Fully qualified tool name
            args: Tool arguments (needed for argument-pattern matching)
            agent: Caller's agent info, or None (defaults to global rules)
        
        Returns:
            (True, None) if allowed
            (False, BlockedResponse) if blocked
        
        Evaluation order (formal precedence, highest to lowest):
        
            Level 0: SUPERBLOCK (global only)
                Check tool against global.superblocked patterns.
                If match → BLOCK immediately. No override possible.
            
            Level 1: Workflow/Phase rules
                If agent has workflow + phase set:
                    Check workflows.<workflow>.<phase>.blocked → if match → BLOCK
                    Check workflows.<workflow>.<phase>.allowed → if match → ALLOW
            
            Level 2: Agent-type rules
                If agent has agent_type set:
                    Check agents.<agent_type>.blocked → if match → BLOCK
                    Check agents.<agent_type>.allowed → if match → ALLOW
            
            Level 3: Role-based rules
                For each role in agent.roles (checked in order):
                    Check roles.<role>.blocked → if match → BLOCK
                    Check roles.<role>.allowed → if match → ALLOW
            
            Level 4: Global rules
                Check global.blocked → if match → BLOCK
                Check global.allowed → if match → ALLOW
            
            Level 5: Default
                BLOCK (deny by default)
        
            At each level, blocked is checked before allowed.
            First match at the highest applicable level wins.
            Lower levels are not consulted once a match is found.
        
        Pattern matching:
            "native__read_file"         — exact match
            "serena__*"                 — fnmatch glob on tool name
            "native__bash(pytest*)"     — tool match + fnmatch on args["command"]
            "native__bash(rm -rf*)"     — tool match + fnmatch on args["command"]
        
        Caveat: Argument pattern matching is inherently imperfect. Patterns
        like "native__bash(rm -rf*)" can be bypassed via quoting, shell
        expansion, alternate spellings, or indirect invocation. The permission
        system is a guardrail for AI agent coordination, not a security
        sandbox. See §0 Trust Model.
        """
    
    def register_agent(
        self,
        agent_id: str,
        agent_type: str,
        roles: list[str] | None = None,
    ) -> AgentInfo:
        """
        Register an agent for permission tracking.
        Thread-safe.
        
        Returns: Created AgentInfo
        """
    
    def update_agent_phase(
        self,
        agent_id: str,
        workflow: str,
        phase: str,
    ) -> None:
        """
        Update an agent's current workflow and phase.
        Thread-safe.
        
        Raises: RouterError if agent_id not registered.
        """
    
    def get_agent(self, agent_id: str) -> AgentInfo | None:
        """Return registered agent info, or None."""
    
    def get_allowed_tools(
        self,
        agent_type: str | None = None,
    ) -> list[str]:
        """
        Return list of tool patterns allowed for the given agent type.
        If agent_type is None, return global allowed list.
        """
    
    def reload(self) -> None:
        """Re-read permissions.yaml from disk. Thread-safe."""
```

---

## 6. BackendManager

### Purpose
Manages external MCP server subprocesses. Spawns on first use, reuses connections, handles timeouts and retries. Only manages external backends (Serena, Context7, Playwright) — not native ops.

### Interface

```python
# lib/backends.py

import subprocess
import json
import select
import uuid
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class BackendConfig:
    name: str
    command: list[str]
    tool_prefix: str
    env: dict[str, str] = field(default_factory=dict)

class BackendManager:
    """
    Manages external MCP server subprocesses.
    Thread-safe: per-backend RLock for connection management.
    
    Design note: Access to each backend is serialized (one request at a time
    per backend). This is intentional — MCP backends are single-threaded
    stdio servers. Concurrent writes to the same stdin would corrupt the
    stream. Two requests to different backends CAN execute concurrently.
    
    stderr handling: Backend stderr is piped (subprocess.PIPE) but NOT read
    during normal operation. stderr is only read on connection failure for
    diagnostic logging. This avoids deadlock from stderr buffer filling up —
    if a backend writes excessive stderr, the OS pipe buffer (typically 64KB)
    will eventually block the backend's write. Backends should not write
    large volumes to stderr during normal operation.
    """
    
    def __init__(self, config_path: Path) -> None:
        """
        Load backends.json. Do NOT spawn any backends yet (lazy).
        
        Creates:
            self._configs: dict[str, BackendConfig]  — from backends.json
            self._connections: dict[str, subprocess.Popen]  — active connections
            self._locks: dict[str, threading.RLock]  — per-backend locks
        
        Filter: Only load backends that are NOT "native" or "workflow"
        (those are handled by the Controller directly).
        """
    
    def dispatch(self, backend: str, tool_name: str, args: dict) -> Any:
        """
        Send a tool call to a backend and return the response.
        
        Args:
            backend: Backend name (e.g., "serena")
            tool_name: Tool name without prefix (e.g., "find_symbol")
            args: Tool arguments
        
        Returns:
            Parsed response content from backend
        
        Raises:
            BackendNotFoundError: Backend not in configs
            RequestTimeoutError: No response within 30 seconds
            ConnectionError: Backend process died
        
        Flow:
            1. Acquire self._locks[backend]
            2. conn = self._get_connection(backend)
            3. request = {
                   "jsonrpc": "2.0",
                   "id": str(uuid.uuid4()),
                   "method": "tools/call",
                   "params": {"name": tool_name, "arguments": args}
               }
            4. Write json.dumps(request) + "\n" to conn.stdin
            5. conn.stdin.flush()
            6. Wait for response with select.select(conn.stdout, timeout=30)
            7. If timeout → self._kill_connection(backend) → raise RequestTimeoutError
            8. Read line from conn.stdout
            9. Parse JSON response
            10. If response has "error" → raise RouterError
            11. Extract and return result content
            12. Release lock
        
        On ConnectionError/BrokenPipeError:
            1. self._kill_connection(backend)
            2. Retry once (re-spawn + re-send)
            3. If retry fails → raise ConnectionError
        """
    
    def list_tools(self, backend: str) -> list[dict]:
        """
        Get tool list from a backend.
        
        Flow:
            1. conn = self._get_connection(backend)
            2. Send {"method": "tools/list", "params": {}}
            3. Parse response
            4. Return result["tools"]
        """
    
    def list(self) -> list[str]:
        """Return list of registered backend names."""
    
    def shutdown_all(self) -> None:
        """Kill all backend subprocesses."""
    
    def _get_connection(self, backend: str) -> subprocess.Popen:
        """
        Get or create a connection to a backend.
        
        If backend not in self._connections or process is dead:
            1. Spawn subprocess:
               proc = subprocess.Popen(
                   config.command,
                   stdin=subprocess.PIPE,
                   stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE,
                   text=True,
                   bufsize=1,  # line-buffered
               )
            2. Perform MCP handshake:
               Send: {"jsonrpc":"2.0","id":1,"method":"initialize","params":{
                   "protocolVersion":"2024-11-05",
                   "capabilities":{},
                   "clientInfo":{"name":"agent-swarm","version":"2.0.0"}
               }}
               Read response (validate protocolVersion)
               Send: {"jsonrpc":"2.0","method":"notifications/initialized"}
            3. self._connections[backend] = proc
        
        Return self._connections[backend]
        """
    
    def _kill_connection(self, backend: str) -> None:
        """
        Terminate a backend subprocess.
        
        1. proc = self._connections.pop(backend, None)
        2. If proc: proc.terminate(); proc.wait(timeout=5)
        3. If wait times out: proc.kill()
        """
```

---

## 7. LLMService

### Purpose
General-purpose LLM capabilities. Summarization now, embeddings and other capabilities in the future.

### Interface

```python
# lib/llm.py

import os
import json
from typing import Any

class LLMService:
    """
    LLM capabilities abstraction. Currently supports summarization.
    Designed to grow without changing the Controller interface.
    """
    
    def __init__(self, provider: str = "auto") -> None:
        """
        Args:
            provider: "auto" | "anthropic" | "openai" | "none"
                auto: Try Anthropic first (ANTHROPIC_API_KEY),
                      then OpenAI (OPENAI_API_KEY),
                      then fallback to truncation.
                none: Always use truncation fallback.
        
        Creates:
            self._provider: str — resolved provider
            self._client: API client instance or None
        """
    
    def summarize(self, content: str, max_length: int = 2000) -> str:
        """
        Generate a concise summary of content.
        
        Args:
            content: Text to summarize
            max_length: Target summary length in characters
        
        Returns:
            Summary string
        
        Implementation:
            If self._provider == "anthropic":
                Call Claude Haiku with prompt:
                    "Summarize the following content concisely, preserving
                     key information like file paths, function names, error
                     messages, and data structures. Keep under {max_length}
                     characters.\n\nContent:\n{content}"
                Model: claude-haiku-4-20250414
                Max tokens: max_length // 3
            
            If self._provider == "openai":
                Call GPT-4o-mini with equivalent prompt.
            
            If self._provider == "none" or API call fails:
                Truncation fallback:
                    content[:max_length] + "\n\n... [truncated, full content available via content_id]"
        
        Error handling:
            API errors → log warning → use truncation fallback
            Never raises — always returns a string.
        """
    
    # Future capabilities:
    
    # def embed(self, content: str) -> list[float]:
    #     """Generate embedding vector for content."""
    
    # def classify(self, content: str, categories: list[str]) -> str:
    #     """Classify content into one of the given categories."""
```

---

## 8. DataStore

### Purpose
Event persistence and reporting. Append-only event log backed by DuckDB. Tracks all tool calls, workflow events, and session metadata. Feeds dashboards and analytics.

### Interface

```python
# lib/datastore.py

import duckdb
import threading
from datetime import datetime, date
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass

@dataclass
class EventRecord:
    timestamp: datetime
    tool: str
    backend: str
    status: str               # "success" | "error"
    duration_ms: int = 0
    session_id: str = ""
    agent_id: str = ""
    agent_type: str = ""
    workflow_id: str = ""
    error_type: str = ""
    was_summarized: bool = False
    original_size: int = 0
    summary_size: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

@dataclass
class DaySummary:
    date: date
    total_calls: int
    total_tokens: int
    unique_sessions: int
    unique_tools: int
    error_count: int
    summarization_count: int
    avg_duration_ms: float

@dataclass
class ToolSummary:
    tool_name: str
    call_count: int
    avg_duration_ms: float
    error_rate: float

class DataStore:
    """
    Event persistence and reporting backed by DuckDB.
    Thread-safe for concurrent writes and reads.
    
    Token metrics note: The schema includes token fields (input_tokens,
    output_tokens, cache_read_tokens, cache_creation_tokens) for when
    this data is available. Native tools and most backends do not report
    token usage — these fields will be 0. LLMService summarization calls
    may report token counts if the API returns them. Dashboards should
    treat token fields as "best available data" not "precise measurement."
    """
    
    def __init__(self, db_path: Path) -> None:
        """
        Open or create DuckDB database at db_path.
        Create tables if they don't exist.
        
        Creates:
            self._conn: duckdb.DuckDBPyConnection
            self._lock: threading.RLock
        
        Schema (created on init):
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY DEFAULT nextval('events_id_seq'),
                timestamp TIMESTAMP NOT NULL,
                tool VARCHAR NOT NULL,
                backend VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                duration_ms INTEGER DEFAULT 0,
                session_id VARCHAR DEFAULT '',
                agent_id VARCHAR DEFAULT '',
                agent_type VARCHAR DEFAULT '',
                workflow_id VARCHAR DEFAULT '',
                error_type VARCHAR DEFAULT '',
                was_summarized BOOLEAN DEFAULT FALSE,
                original_size INTEGER DEFAULT 0,
                summary_size INTEGER,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cache_read_tokens INTEGER DEFAULT 0,
                cache_creation_tokens INTEGER DEFAULT 0
            );
            
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
            CREATE INDEX IF NOT EXISTS idx_events_tool ON events(tool);
        """
    
    def record_event(self, event: dict) -> None:
        """
        Insert a single event.
        
        Args:
            event: Dict with keys matching EventRecord fields.
                   Missing keys get defaults.
                   "timestamp" defaults to now if not provided.
        
        Thread-safe: Acquires self._lock.
        """
    
    def get_daily_summary(self, day: date) -> DaySummary | None:
        """
        Get aggregated metrics for a single day.
        
        Returns None if no events on that day.
        
        Query:
            SELECT
                COUNT(*) as total_calls,
                COALESCE(SUM(input_tokens + output_tokens), 0) as total_tokens,
                COUNT(DISTINCT session_id) as unique_sessions,
                COUNT(DISTINCT tool) as unique_tools,
                COUNT(*) FILTER (WHERE status = 'error') as error_count,
                COUNT(*) FILTER (WHERE was_summarized) as summarization_count,
                COALESCE(AVG(duration_ms), 0) as avg_duration_ms
            FROM events
            WHERE CAST(timestamp AS DATE) = ?
        """
    
    def get_tool_summaries(self, limit: int = 20) -> list[ToolSummary]:
        """
        Get tool-level aggregated stats, sorted by call count descending.
        
        Query:
            SELECT
                tool as tool_name,
                COUNT(*) as call_count,
                COALESCE(AVG(duration_ms), 0) as avg_duration_ms,
                COALESCE(
                    CAST(COUNT(*) FILTER (WHERE status = 'error') AS FLOAT) /
                    NULLIF(COUNT(*), 0), 0
                ) as error_rate
            FROM events
            GROUP BY tool
            ORDER BY call_count DESC
            LIMIT ?
        """
    
    def get_session_events(self, session_id: str) -> list[EventRecord]:
        """
        Get all events for a specific session, ordered by timestamp.
        """
    
    def query_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        tool: str | None = None,
        backend: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[EventRecord]:
        """
        Flexible event query with optional filters.
        All parameters are AND-combined.
        """
    
    def close(self) -> None:
        """Close DuckDB connection."""
```

---

## 9. Cache

### Purpose
Ephemeral keyed content storage. Holds full responses for later retrieval (two-step summarization pattern), materialized state, or any content that might be needed later.

### Interface

```python
# lib/cache.py

import threading
import time
from typing import Any, Optional

class Cache:
    """
    In-memory keyed content store with TTL-based expiration.
    Thread-safe.
    """
    
    def __init__(self, default_ttl: int = 300, max_entries: int = 1000) -> None:
        """
        Args:
            default_ttl: Default time-to-live in seconds (default 5 minutes)
            max_entries: Maximum number of cached entries (default 1000).
                         When exceeded, oldest entries (by insertion time)
                         are evicted regardless of TTL.
        
        Creates:
            self._store: dict[str, tuple[Any, float]]  # key → (value, expires_at)
            self._lock: threading.RLock
            self._default_ttl: int
            self._max_entries: int
        """
    
    def store(self, key: str, value: Any, ttl: int | None = None) -> None:
        """
        Store a value with expiration.
        
        Args:
            key: Unique identifier (e.g., content_id)
            value: Content to store (any type, stored by reference)
            ttl: Time-to-live in seconds. None → use default_ttl.
        
        Thread-safe: Acquires self._lock.
        Also triggers self._evict_expired() to clean up.
        If store exceeds max_entries after insertion, evicts oldest
        entries (by insertion time) until within limit.
        """
    
    def get(self, key: str, remove: bool = True) -> Any | None:
        """
        Retrieve a value by key.
        
        Args:
            key: Key to look up
            remove: If True, remove entry after retrieval (one-time access).
                    Default True for two-step retrieval pattern.
        
        Returns:
            Stored value, or None if key not found or expired.
        
        Thread-safe: Acquires self._lock.
        """
    
    def has(self, key: str) -> bool:
        """Check if key exists and is not expired."""
    
    def remove(self, key: str) -> bool:
        """
        Remove a key. Returns True if key existed.
        Thread-safe.
        """
    
    def clear(self) -> None:
        """Remove all entries. Thread-safe."""
    
    def size(self) -> int:
        """Return number of non-expired entries."""
    
    def _evict_expired(self) -> None:
        """
        Remove all entries past their TTL.
        Called internally during store() and periodically.
        Must be called while holding self._lock.
        """
```

---

## 10. Wire Protocol

### MCP Protocol (Claude Code ↔ Router)

Claude Code communicates using MCP 2024-11-05 over TCP. The Router speaks this natively.

#### Framing
- Newline-delimited JSON over TCP
- UTF-8 encoding
- One complete JSON object per line
- LF line endings (`\n`)

#### Handshake

Client (Claude Code) initiates after TCP connect:

```
→ {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"claude-code","version":"1.0.0"}}}
← {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"agent-swarm","version":"2.0.0"}}}
→ {"jsonrpc":"2.0","method":"notifications/initialized"}
```

Note: `notifications/initialized` has no `id` field — it is a notification, no response is sent.

#### Tool Discovery

```
→ {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
← {"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"native__read_file","description":"...","inputSchema":{...}},...]}}
```

#### Tool Call

```
→ {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"serena__find_symbol","arguments":{"name_path":"Controller","include_body":false}}}
← {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"{\"symbols\":[...]}"}]}}
```

#### Tool Call Error

```
← {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"Error: symbol not found"}],"isError":true}}
```

#### Permission Denied

```
← {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"{\"blocked\":true,\"reason\":\"...\",\"tool\":\"...\",\"guidance\":\"...\"}"}],"isError":true}}
```

### Internal Protocol (Hooks/Agents ↔ Router)

Hooks and background agents use the same TCP port and the same JSON-RPC framing. They are distinguished by behavior, not by protocol — they just call different tools.

The `_caller` field in arguments identifies the caller for permission resolution:

```
→ {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"workflow__workflow_is_active","arguments":{"workflow_id":"iterate","_caller":"hook:task-enforcement"}}}
← {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"true"}]}}
```

The `_caller` field is stripped from arguments before dispatching to the tool. It is only used for permission resolution.

### Backend Protocol (Controller ↔ External MCP Servers)

Same MCP protocol over stdio (subprocess stdin/stdout). Newline-delimited JSON.

```
Controller → BackendManager → subprocess stdin:
  {"jsonrpc":"2.0","id":"<uuid>","method":"tools/call","params":{"name":"find_symbol","arguments":{...}}}

subprocess stdout → BackendManager → Controller:
  {"jsonrpc":"2.0","id":"<uuid>","result":{"content":[{"type":"text","text":"..."}]}}
```

### Protocol Versioning

The MCP protocol version is hardcoded to `2024-11-05`. The Router does not perform version negotiation — it accepts any `protocolVersion` in the initialize request and always responds with `2024-11-05`. If a future MCP version introduces breaking changes, the Router will need to be updated. This is an accepted limitation: version negotiation adds complexity for a scenario that hasn't occurred yet. When it does, the Router is the only component that needs to change.

Internal tool schemas (workflow__, router__) are unversioned. Changes to their signatures are breaking changes that require coordinated updates to the daemon and all clients (shim, hooks, etc.).

Note: Tool names sent to backends do NOT include the prefix. `serena__find_symbol` → sends `find_symbol` to the serena backend. The prefix is stripped by the Controller before dispatch and added back by the Router for tool discovery.

---

## 11. Client Shim

### Purpose
Backward-compatible `workflow_client.py` that points at the daemon's known port instead of discovering via `.state/router.port`. Existing callers (~25 files) need zero code changes.

### Interface

```python
# lib/workflow_client.py

import socket
import json
import os
from pathlib import Path
from typing import Any, Optional

DAEMON_PORT = 7523
STATE_DIR = Path(__file__).parent.parent / ".state"

class WorkflowClientError(Exception):
    """Raised when communication with daemon fails."""
    pass

def _call_tool(tool_name: str, arguments: dict) -> Any:
    """
    Internal: send a tool call to the daemon via TCP.
    
    1. Connect to 127.0.0.1:DAEMON_PORT with 5s timeout
    2. Send JSON-RPC request:
       {
           "jsonrpc": "2.0",
           "id": 1,
           "method": "tools/call",
           "params": {
               "name": f"workflow__{tool_name}",
               "arguments": {**arguments, "_caller": "workflow_client"}
           }
       }
    3. Read response until \n
    4. Parse JSON
    5. If "error" in response → raise WorkflowClientError
    6. Extract result.content[0].text → parse as JSON
    7. Return parsed value
    
    Error handling:
        ConnectionRefusedError → raise WorkflowClientError(
            "Daemon not running. Is agent-swarm daemon started?"
        )
        socket.timeout → raise WorkflowClientError("Daemon timeout")
    """

# ── Public API (unchanged signatures) ──────────────────────────

def workflow_start(workflow_id: str, initial_state: dict) -> dict:
    return _call_tool("workflow_start", {"workflow_id": workflow_id, "initial_state": initial_state})

def workflow_stop(workflow_id: str) -> bool:
    return _call_tool("workflow_stop", {"workflow_id": workflow_id})

def workflow_is_active(workflow_id: str) -> bool:
    return _call_tool("workflow_is_active", {"workflow_id": workflow_id})

def workflow_get_state(workflow_id: str) -> dict | None:
    return _call_tool("workflow_get_state", {"workflow_id": workflow_id})

def workflow_set_state(workflow_id: str, state: dict) -> dict:
    return _call_tool("workflow_set_state", {"workflow_id": workflow_id, "state": state})

def workflow_update(workflow_id: str, updates: dict) -> dict:
    return _call_tool("workflow_update", {"workflow_id": workflow_id, "updates": updates})

def workflow_get_value(workflow_id: str, key: str) -> Any:
    return _call_tool("workflow_get_value", {"workflow_id": workflow_id, "key": key})

def workflow_set_value(workflow_id: str, key: str, value: Any) -> bool:
    return _call_tool("workflow_set_value", {"workflow_id": workflow_id, "key": key, "value": value})

def agent_get_state(agent_id: str) -> dict | None:
    return _call_tool("agent_get_state", {"agent_id": agent_id})

def agent_set_state(agent_id: str, state: dict) -> dict:
    return _call_tool("agent_set_state", {"agent_id": agent_id, "state": state})

def agent_delete(agent_id: str) -> bool:
    return _call_tool("agent_delete", {"agent_id": agent_id})

def list_agents() -> list[str]:
    return _call_tool("list_agents", {})

def call_tool(tool_name: str, arguments: dict) -> Any:
    """
    General-purpose tool call. Sends to daemon as-is.
    Tool name should include prefix (e.g., "serena__find_symbol").
    """
    port = DAEMON_PORT
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30.0)  # longer timeout for general tools
    sock.connect(("127.0.0.1", port))
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {**arguments, "_caller": "workflow_client"}}
    }
    sock.sendall(json.dumps(request).encode() + b"\n")
    response = b""
    while b"\n" not in response:
        chunk = sock.recv(8192)
        if not chunk:
            break
        response += chunk
    sock.close()
    parsed = json.loads(response.decode().strip())
    # Extract and return result
    ...

def list_tools() -> list[dict]:
    """Send tools/list to daemon, return tool schemas."""
    ...

def generate_correlation_id() -> str:
    """Generate a unique correlation ID."""
    import uuid
    return f"req-{uuid.uuid4().hex[:12]}"
```

---

## 12. Configuration

### config/backends.json

Only external backends. No "native" or "workflow" entries.

```json
{
    "serena": {
        "command": ["uvx", "--from", "git+https://github.com/oraios/serena", "serena", "start-mcp-server", "--project", "/home/fearsidhe/.claude/plugins/agent-swarm"],
        "tool_prefix": "serena"
    },
    "context7": {
        "command": ["npx", "-y", "@upstash/context7-mcp"],
        "tool_prefix": "context7"
    },
    "playwright": {
        "command": ["npx", "@playwright/mcp@latest"],
        "tool_prefix": "playwright"
    }
}
```

Schema:
```
{
    "<name>": {
        "command": list[str],      # subprocess command + args
        "tool_prefix": str         # prefix for tool names (usually == name)
    }
}
```

### config/permissions.yaml

No changes to format. See §5 for evaluation semantics. Structure:

```yaml
global:
    allowed: list[str]       # tool patterns
    blocked: list[str]       # tool patterns
    superblocked: list[str]  # tool patterns (never overridable)

roles:
    <role_name>:
        allowed: list[str]
        blocked: list[str]

agents:
    <agent_type>:
        allowed: list[str]
        blocked: list[str]

workflows:
    <workflow_name>:
        <phase_name>:
            allowed: list[str]
            blocked: list[str]
```

### .state/ Directory

```
.state/
├── daemon.pid       # PID of daemon process
├── daemon.port      # TCP port of daemon
├── daemon.log       # Daemon log output
└── datastore.db     # DuckDB database
```

---

## 13. Error Handling

### Exception Hierarchy

```python
# lib/errors.py

class RouterError(Exception):
    """Base error for all daemon operations."""
    pass

class PermissionDeniedError(RouterError):
    """Tool blocked by permission rules."""
    def __init__(self, response: "BlockedResponse"):
        self.response = response
        super().__init__(response.reason)

class BackendNotFoundError(RouterError):
    """Requested backend is not registered."""
    pass

class BackendConnectionError(RouterError):
    """Connection to backend subprocess failed."""
    pass

class RequestTimeoutError(RouterError):
    """Backend did not respond within timeout."""
    pass
```

### Error Response Formatting

All errors are translated to MCP-compatible responses by the Router.

| Error Type | JSON-RPC Response |
|------------|-------------------|
| PermissionDeniedError | `{"result": {"content": [{"type": "text", "text": "<BlockedResponse as JSON>"}], "isError": true}}` |
| BackendNotFoundError | `{"result": {"content": [{"type": "text", "text": "Backend not found: <name>"}], "isError": true}}` |
| BackendConnectionError | `{"result": {"content": [{"type": "text", "text": "Backend connection failed: <detail>"}], "isError": true}}` |
| RequestTimeoutError | `{"result": {"content": [{"type": "text", "text": "Request timed out after 30s"}], "isError": true}}` |
| RouterError (generic) | `{"result": {"content": [{"type": "text", "text": "Internal error: <message>"}], "isError": true}}` |
| JSON parse error | `{"error": {"code": -32700, "message": "Parse error"}}` |
| Method not found | `{"error": {"code": -32601, "message": "Method not found: <method>"}}` |
| Unexpected exception | `{"error": {"code": -32603, "message": "Internal error: <message>"}}` |

### Error Recording

All errors are recorded in the DataStore:

```python
self.data.record_event({
    "tool": tool,
    "backend": prefix,
    "status": "error",
    "error_type": type(e).__name__,
    "duration_ms": elapsed,
    ...
})
```

---

## 14. Threading Model

### Daemon Process
Single process, multiple threads.

### Thread Allocation
- **Main thread**: Runs `Router.serve_forever()` accept loop
- **Per-connection thread**: One daemon thread per TCP connection (spawned on accept)
- **Maximum 64 concurrent connections** (enforced by Router). New connections beyond this limit receive a JSON-RPC error and are closed immediately.
- **No thread pool**: Threads are created and destroyed per connection. Acceptable because connections are short-lived (single request-response for hooks) or medium-lived (Claude session). The 64-connection cap prevents thread explosion.

### Lock Strategy
- **Per-backend RLock** (in BackendManager): Prevents concurrent access to same backend subprocess stdin/stdout
- **State RLock** (in Controller): Protects `_workflow_state` and `_agent_state` dicts
- **DataStore RLock**: Protects DuckDB write operations
- **Cache RLock**: Protects `_store` dict
- **PermissionChecker RLock**: Protects `_agents` dict

### Concurrency Rules
1. Backend dispatch acquires only the per-backend lock — two requests to different backends can execute concurrently
2. Native ops do not hold any backend locks — they can execute concurrently with backend requests
3. Workflow state mutations are serialized via the state lock
4. DataStore writes are serialized but fast (single INSERT)
5. Cache operations are serialized but O(1)
6. Permission checks acquire only the agents lock for agent lookup, then release — rule evaluation is read-only on immutable config

### Deadlock Prevention
- Locks are never nested except: state_lock → data._lock (recording workflow events). This ordering is fixed and consistent.
- Backend locks are never held while acquiring other locks.
- No lock is held during LLM calls (summarization happens without locks).

---

## 15. Startup & Shutdown

### Startup Sequence

```
1. bin/start-claude (or manual: python3 lib/daemon.py)
2. daemon.main():
   a. Check is_running() → abort if already running
   b. Write PID_FILE
   c. Configure logging to LOG_FILE
   d. Create Controller(config_dir, state_dir):
      i.   PermissionChecker(permissions.yaml) — load rules
      ii.  BackendManager(backends.json) — load configs (no spawn)
      iii. LLMService() — detect provider
      iv.  DataStore(datastore.db) — open/create DB, create tables
      v.   Cache() — empty store
   e. Create Router(port, controller)
   f. Write PORT_FILE
   g. Register SIGTERM/SIGINT handlers → Router.shutdown()
   h. Router.serve_forever() — blocks
```

### Shutdown Sequence

```
1. SIGTERM received (or SIGINT)
2. Signal handler calls Router.shutdown():
   a. self._running = False
   b. self._server.close() — unblocks accept()
   c. Drain in-flight requests:
      Wait up to 5 seconds for self._active_connections to reach 0.
      Check every 100ms. If still >0 after 5s, proceed anyway
      (daemon threads will be killed on process exit).
   d. Controller.shutdown():
      i.  BackendManager.shutdown_all() — terminate all subprocesses
      ii. DataStore.close() — close DuckDB
3. daemon.main() resumes after serve_forever():
   a. Delete PID_FILE
   b. Delete PORT_FILE
   c. Exit process
```

### Crash Recovery

If daemon crashes without cleanup:
1. PID_FILE contains stale PID
2. PORT_FILE contains stale port
3. Next `is_running()` call:
   - Reads PID_FILE
   - os.kill(pid, 0) → OSError (process dead)
   - Deletes stale PID_FILE
   - Returns False
4. Startup script restarts daemon normally

Backend subprocesses (Serena, etc.) are children of the daemon. When daemon dies, they receive SIGHUP. If they don't handle it, they die too. On daemon restart, BackendManager spawns fresh instances on first use.

DuckDB state is durable — survives daemon restart.
Workflow state (in-memory) and Cache are lost on daemon crash. This is acceptable — workflows can be restarted, and cache is ephemeral by design.

---

## 16. Migration Compatibility

### Stdio Shim (Required)

Claude Code only supports stdio for MCP server communication. It spawns MCP servers as subprocesses and talks to them over stdin/stdout. There is no native support for TCP, SSE, or HTTP connections to remote MCP servers.

Therefore, a **stdio-to-TCP bridge shim** is required. Claude Code spawns the shim as a subprocess (same as today), and the shim bridges stdio to the daemon's TCP port.

#### Shim Implementation

```python
#!/usr/bin/env python3
"""
bin/mcp-router — stdio-to-TCP bridge shim.

Claude Code spawns this as a subprocess. It bridges MCP JSON-RPC
over stdio to the daemon's TCP port. No logic, no state, pure pipe.

Replaces the old 3,159-line mcp_router.py with ~30 lines.
"""
import json
import socket
import sys
import os

DAEMON_PORT = 7523

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect(("127.0.0.1", DAEMON_PORT))
    except ConnectionRefusedError:
        # Daemon not running — print error and exit
        error = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32603, "message": "Daemon not running. Run start-claude to start it."}
        }
        sys.stdout.write(json.dumps(error) + "\n")
        sys.stdout.flush()
        sys.exit(1)

    # Bridge: stdin → TCP, TCP → stdout
    import threading

    def stdin_to_tcp():
        """Read from stdin (Claude Code), forward to daemon TCP."""
        for line in sys.stdin:
            sock.sendall(line.encode())

    def tcp_to_stdout():
        """Read from daemon TCP, forward to stdout (Claude Code)."""
        buf = b""
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                sys.stdout.write(line.decode() + "\n")
                sys.stdout.flush()

    reader = threading.Thread(target=tcp_to_stdout, daemon=True)
    reader.start()
    stdin_to_tcp()
    sock.close()

if __name__ == "__main__":
    main()
```

#### Claude Code Configuration

**No change to Claude Code settings.** `bin/mcp-router` remains the entry point — it's just a 30-line shim now instead of a 3,159-line server.

```json
{
    "mcpServers": {
        "router": {
            "command": "python3",
            "args": ["/path/to/agent-swarm/bin/mcp-router"]
        }
    }
}
```

Claude Code spawns the shim, which connects to the daemon. From Claude Code's perspective, nothing changed — it's still talking to an MCP server over stdio.

### What Changes for Hooks

Nothing. Hooks import `workflow_client`, which now points at the daemon's known port (7523) instead of discovering via `.state/router.port`. All function signatures are identical.

### What Changes for mcp-call

Nothing. `bin/mcp-call` imports `workflow_client`, which follows the shim automatically.

### What Gets Deleted

After migration is stable:
- `lib/mcp_router.py` (3,159 lines — replaced by daemon + shim)
- `lib/mcp_controller.py` (old, unused)
- `lib/routing_service.py` (absorbed into BackendManager)
- `lib/summarization_service.py` (absorbed into LLMService)
- `lib/workflow_server.py` (state is in Controller)
- `lib/workflow_state_service.py` (state is in Controller)
- `lib/telemetry_service.py` (absorbed into DataStore)
- `lib/telemetry_schema_v2.py` (DuckDB is the schema)
- `lib/native_tools.py` (native ops are in Controller)
- `lib/mcp_native.py` (native ops are in Controller)
- `bin/mcp-native` (native ops are in Controller)
- All federation code (primary/secondary/election/failover)
- `.state/router.port` (replaced by `.state/daemon.port`)
- `.state/telemetry/` directory (DuckDB replaces JSON files)

`bin/mcp-router` stays — but as a 30-line shim instead of a server entry point.

### Backward Compatibility Period

During migration, both the old `bin/mcp-router` and new daemon can coexist:
- Old router reads `.state/router.port`
- New daemon writes `.state/daemon.port`
- `workflow_client.py` shim reads `.state/daemon.port`
- Old clients reading `.state/router.port` continue to work if old router is still running

Once all clients are verified working through the daemon, delete the old code.
