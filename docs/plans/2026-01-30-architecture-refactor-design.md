# Architecture Refactor Design

**Date:** 2026-01-30
**Status:** Draft
**Scope:** Router, Controller, Telemetry, State, Summarization — full architectural overhaul

## Problem

`mcp_router.py` is a 3,159-line god module handling transport, orchestration, telemetry, response caching, workflow state hosting, socket listening, summarization, and federation (primary/secondary election, proxy forwarding, failover). The controller exists but is underutilized. Telemetry has a dual-write path from an incomplete migration. Workflow state lives in a subprocess and is lost on crash. Federation adds complexity (race-based election, 30-second failover timeouts, split-brain prevention) to solve a problem that shouldn't exist.

The root cause: Claude Code spawns a new MCP server process per session, so multiple sessions don't share state. Federation was built to work around this. The fix is simpler — don't spawn per-session processes.

The client side mirrors this problem. 25+ files independently import `workflow_client` and make ad-hoc socket calls to read/write state. There's no client-side abstraction — everyone speaks raw state operations. A clean server architecture opens the door for a clean client architecture.

## Core Insight

The daemon's job is simple: **forward requests to the right place, and summarize output that's too big.** Everything else — permissions, telemetry, caching, state — is bookkeeping around those two operations.

## Design Principles

- Each concern gets its own class, owned as a property by whatever uses it
- No singletons, no service locators — just composition
- Controller is MVC-style: orchestrates, maps tools to backends, handles errors
- Router is a TCP listener: accepts connections, translates, delegates to Controller
- The daemon is the sole entry point for all tool usage — Claude's native tools are blocked
- Backends are external MCP servers only — native operations (file, shell, search) are handled inline
- The system is purely request-response — Claude never initiates outside a conversation turn
- One process, one state — no federation, no sync, no election
- State is a view into accumulated events
- YAGNI — extract only when complexity demands it

## Architecture

### Deployment Model

```
Startup script (aliased to `claude`):
  ├── Is daemon running? (check port)
  │     ├── No  → start daemon in background
  │     └── Yes → continue
  └── Launch claude normally

Daemon (long-lived, one process, TCP server)
  └── Router (TCP listener on localhost:PORT)
        └── Controller
              ├── self.permissions  = PermissionChecker(...)
              ├── self.backends     = BackendManager(...)  # external only
              ├── self.llm          = LLMService(...)
              ├── self.data         = DataStore(...)
              └── self.cache        = Cache(...)

Claude Code  → TCP → Daemon
Hooks        → TCP → Daemon
Bg agents    → TCP → Daemon
```

All clients are TCP connections. No stdio. No subprocess spawning. No federation. One server, many clients, one state.

### Sole Entry Point

The daemon is the only way tools get executed. Claude Code's native tools (Read, Write, Edit, Glob, Grep, Bash) are blocked by hooks — all operations go through the daemon. This means:

- The Controller sees every operation — file reads, shell commands, searches, everything
- Permissions, telemetry, and summarization apply uniformly to all operations
- No operation bypasses the pipeline

Native operations (file I/O, shell, search) are handled directly by the Controller — they're just code, not a separate backend. External MCP servers (Serena, Context7, Playwright) are the only things BackendManager manages.

### Seven Components

| Component | Responsibility |
|-----------|---------------|
| **Router** | TCP server. Accepts connections from Claude Code (MCP protocol), hooks, background agents. Translates protocol messages to internal format, calls Controller, translates responses back. |
| **Controller** | MVC-style orchestrator. Forwards requests to the right place (inline for native ops, BackendManager for external), summarizes large output via LLM, records events, checks permissions, handles errors. Owns all services as properties. |
| **PermissionChecker** | Access control. Evaluates allow/block rules against tool, agent type, workflow phase. Returns allow/block with guidance. |
| **BackendManager** | External backend subprocess lifecycle only (Serena, Context7, Playwright). Spawns processes, manages MCP handshakes, connection pooling, retry-on-failure. Dumb pipe — receives request, returns response. |
| **LLMService** | LLM capabilities. Summarization today; embeddings, classification, etc. in the future. Abstracts model selection and API calls. |
| **DataStore** | Event persistence and reporting. Append-only event log. Feeds dashboards and analytics. One overarching store that tracks per-session and per-agent state within it. State is a view into accumulated events. DuckDB-backed. |
| **Cache** | Ephemeral content storage. Keyed store for content that might be needed later — full responses before summarization, materialized state for fast reads, etc. In-memory with TTL. |

### Data Flow

#### Standard Request
```
Claude sends MCP JSON-RPC via TCP
  ↓
Router accepts connection, translates to internal format
  ↓
Controller.handle_call(tool, args):
    1. self.permissions.check(tool, agent_info)
    2. if native op → execute directly (file read, shell, search)
       if external → self.backends.dispatch(backend, tool, args)
    3. self.cache.store(content_id, response)   # hold content
    4. result = self.llm.summarize(response)     # if too large
    5. self.data.record(event)                   # bookkeeping
    6. return result
  ↓
Router translates result to MCP response, sends over TCP
  ↓
Claude receives response
```

#### Content Retrieval
```
Claude requests full content by content_id
  ↓
Router → Controller.get_full_content(content_id):
    1. content = self.cache.get(content_id)
    2. self.data.record(retrieval_event)
    3. return content
  ↓
Router → Claude
```

#### Hook/Background Agent Request
```
Hook/agent connects via TCP (same port, same protocol)
  ↓
Router → Controller.handle_call(...)   # same pipeline
  ↓
Router → caller
```

### Key Design Decisions

**1. Daemon model — one process, one state.**
No federation, no primary/secondary, no election, no proxy forwarding, no failover. One daemon owns all state. Every client connects to it. Workflow state never gets lost because the daemon persists. If the daemon dies, the startup script restarts it.

**2. Sole entry point.**
The daemon handles all tool usage. Claude's native tools are blocked. Native operations (file, shell, search) are inline code in the Controller. External MCP servers (Serena, Context7, Playwright) are the only backends. Nothing bypasses the Controller.

**3. TCP only.**
No stdio. Claude Code connects to the daemon as a remote MCP server over TCP. Hooks and background agents use the same TCP connection. One transport, one code path.

**4. Mostly forwarding + summarization.**
The Controller's core job is simple: forward the request to the right place, summarize the output if it's too big. Everything else (permissions, telemetry, caching) is bookkeeping.

**5. Controller maps tools to backends and handles errors.**
No separate ToolRegistry or ErrorHandler classes. Both are orchestration concerns. Extract if they grow too complex.

**6. DataStore tracks everything.**
One overarching store with per-session, per-agent state. Events go in, reporting and state queries come out. DuckDB-backed for persistence and concurrent access.

**7. Cache is separate from DataStore.**
Cache is ephemeral — TTL, eviction, fast reads. Content that might be needed later goes here. DataStore is append-only persistence for reporting. Different lifecycle, different class.

**8. LLMService is general-purpose.**
Not "SummarizationService." Summarization is one capability. Designed to grow (embeddings, classification) without changing the Controller interface.

**9. No native backend.**
No `bin/mcp-native`, no `native_tools.py`, no "native" backend registration. File reads, writes, glob, grep, bash — the Controller just does them.

### What Gets Eliminated

| Current | Fate |
|---------|------|
| Federation (primary/secondary/election/failover) | Eliminated — one daemon, no federation needed |
| `TelemetryCollector` (in mcp_router.py) | Absorbed into Controller + DataStore |
| `ResponseCache` (in mcp_router.py) | Replaced by Cache |
| `WorkflowStateServer` subprocess | Eliminated — state lives in DataStore/Cache |
| `WorkflowStateService` | Eliminated — Cache handles content storage |
| `workflow_server.py` | Eliminated |
| `workflow_client.py` | Replaced by shim, then client SDK |
| `native_tools.py` | Eliminated — native ops are inline in Controller |
| `bin/mcp-native` | Eliminated — no native backend |
| `routing_service.py` | Absorbed into BackendManager |
| Dual-write telemetry | Eliminated — single write path to DataStore |
| `telemetry.json` v2 file | Eliminated — DataStore (DuckDB) is the single source |
| `MCPRouter` class (3,159 lines) | Replaced by Router (~200 lines) + Controller (~300 lines) |
| stdio transport | Eliminated — TCP only |
| Per-session MCP server spawning | Eliminated — daemon is always running |
| Port file discovery + PID checking | Simplified — daemon runs on known port |

### DataStore Structure

```
DataStore
  ├── sessions
  │     ├── session_1: { agent_type, phase, started_at, ... }
  │     ├── session_2: { ... }
  │     └── session_3: { ... }
  ├── agents
  │     ├── agent_abc: { type, session, state, ... }
  │     └── agent_def: { ... }
  ├── events (append-only)
  │     └── every tool call, permission check, etc.
  └── aggregates
        └── computed from events for reporting
```

State is a view into events. Cache materializes current state for fast reads. DataStore is the source of truth for everything.

## Client Architecture

### Current State

68 files communicate with the router across 5 patterns:

| Pattern | Files | How |
|---------|-------|-----|
| Socket via `workflow_client` | ~25+ (hooks, workflows, worker pool, agent recovery) | Import `workflow_client`, call functions like `workflow_get_state()` |
| MCP tool calls (`mcp__router__*`) | Claude, skills, subagents | Tool name prefix routing |
| Direct `MCPRouter` instantiation | `native_tools.py`, `routing_service.py`, tests | Python method calls |
| Subagent tool access (`mcp-call`) | Background agents via Bash | `bin/mcp-call` → `workflow_client.call_tool()` |
| Hook interception | All hooks | PreToolUse/PostToolUse → `workflow_client` |

The dominant interface is `workflow_client.py` — imported by ~25 files.

### Migration Path (Shim Strategy)

The shim keeps `workflow_client.py` as a backward-compatible wrapper that points at the daemon's known port instead of discovering via `.state/router.port`. Most callers need zero code changes.

| Client Category | Migration |
|----------------|-----------|
| **`workflow_client` importers** (~25 files) | Shim: `workflow_client.py` points to daemon's known port. Zero changes in callers. |
| **`bin/mcp-call`** | Uses `workflow_client` internally — follows for free via shim. |
| **`bin/mcp-router`** | Becomes the daemon entry point. |
| **Claude Code config** | Change from stdio subprocess to TCP remote server. |
| **`native_tools.py`** | Eliminated — Controller handles native ops directly. |
| **`routing_service.py`** | Absorbed into BackendManager inside the daemon. |
| **Test files** | Update to mock daemon connection or use test daemon. |
| **Config (`backends.json`)** | Still read by daemon's BackendManager — no change (minus native entry). |
| **Config (`permissions.yaml`)** | Still read by daemon's PermissionChecker — no change. |

### Future: Client SDK

The shim preserves backward compatibility but doesn't fix the client-side sprawl. The daemon simplification opens the door for a clean client SDK with higher-level operations:

```python
# Instead of raw state operations everywhere:
from workflow_client import workflow_is_active, workflow_get_state, workflow_set_value

# Higher-level client:
from agent_swarm import client

client.is_workflow_active("iterate")
client.get_phase()
client.record_event(...)
client.check_permission(tool, agent)
```

This is a follow-on project — not part of this refactor. The shim buys time. The SDK is the eventual clean state.

## Migration Strategy

### Phase 1: Build the daemon
- Create daemon entry point (TCP server on known port)
- Create Router class (TCP listener, MCP protocol handling)
- Create Controller with handle_call pipeline (including inline native ops)
- Wire in existing PermissionChecker

### Phase 2: Extract services
- BackendManager from RoutingService (external backends only)
- LLMService from SummarizationService + LLMClient
- DataStore wrapping DuckDB
- Cache for ephemeral content

### Phase 3: Connect Claude Code
- Configure Claude Code to connect to daemon as remote MCP server
- Create startup alias script (start daemon if not running)
- Deploy `workflow_client` shim (point to known daemon port)
- Verify Claude sessions work through the daemon
- Verify hooks work through the shim

### Phase 4: Migrate state
- Move workflow state into DataStore/Cache
- Move telemetry into DataStore
- Eliminate dual-write

### Phase 5: Cleanup
- Delete federation code, WorkflowStateServer
- Delete per-session MCP server entry point
- Delete stdio transport code
- Delete `native_tools.py`, `bin/mcp-native`, `routing_service.py`
- Update tests

### Phase 6 (Future): Client SDK
- Design client SDK with higher-level operations
- Migrate hooks from raw `workflow_client` to SDK
- Migrate workflows from raw `workflow_client` to SDK
- Retire `workflow_client` shim

## Target File Structure

```
lib/
├── daemon.py              # Entry point — starts daemon process
├── router.py              # Router — TCP server, protocol handling
├── controller.py          # Controller — orchestration + native ops
├── permissions.py         # PermissionChecker
├── backends.py            # BackendManager (external only: serena, context7, playwright)
├── llm.py                 # LLMService
├── datastore.py           # DataStore — events, state, reporting
├── cache.py               # Cache — ephemeral content
├── errors.py              # Exception hierarchy (keep)
├── workflow_client.py     # Shim — backward-compatible wrapper pointing to daemon
└── stores/
    ├── interfaces.py      # Abstract store interfaces (keep)
    └── duckdb_store.py    # DuckDB implementation (keep, used by DataStore)

bin/
└── start-claude           # Startup script (alias target)
```
