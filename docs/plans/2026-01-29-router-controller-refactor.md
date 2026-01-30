# Router → Controller Refactor Plan

## Problem

`lib/mcp_router.py` (3,162 lines) is a monolith that handles transport (stdio/socket), backend communication, summarization, telemetry, and envelope construction — all inline. Services were extracted (`MCPController`, `SummarizationService`, `TelemetryService`, `WorkflowStateService`) but never wired in. The router still does everything itself.

Consequences:
- Two transport handlers (stdio, socket) duplicate the same inline logic
- Full content is always shipped inline in `{summary, full}` envelopes
- `router__get_full` / content retrieval telemetry never fires (no one calls it)
- No separation of concerns — changes to summarization require editing the 3K-line monolith

## Target Architecture

```
Transport (stdio/socket)
  → translate MCP framing
  → controller.handle_call(tool, args)
      → backend_service.invoke(dest, tool, args) → raw result
      → summarization_service.process(result) → summary + content_id
      → telemetry_service.record(...)
      → return envelope
  ← translate response
  ← send
```

**Router**: thin transport shell — receive, translate, dispatch, respond
**Controller**: orchestrate request lifecycle — invoke, summarize, record, return
**BackendService**: backend process management — connections, JSON-RPC, forwarding
**SummarizationService**: summarize large responses, store full content by content_id
**TelemetryService**: record events, content creation/retrieval
**WorkflowStateService**: content_id → full content storage

### Naming

- `MCPRouter` → stays as transport server (could rename to `MCPServer`/`MCPGateway` later)
- `MCPController` → orchestrator, already exists
- `BackendService` → new, extracted from `route()` and friends
- Other services → already exist, already correct

### Key Principles

- The router is the first and last element for a call. The controller orchestrates behind that boundary.
- The controller calls the backend, not the router. The router doesn't get between the controller and the backend.
- Transport translation (MCP framing ↔ clean tool/args) is the router's job.
- Summarization, telemetry, content storage are the controller's job via services.
- Router management tools (ping, telemetry, list_tools) stay on the router — they're transport infrastructure.
- `router__get_full` delegates to the controller for content retrieval.

## Current State of Extracted Services

| Service | File | Status |
|---------|------|--------|
| MCPController | `lib/mcp_controller.py` (98 lines) | Correct but unused |
| SummarizationService | `lib/summarization_service.py` (91 lines) | Correct but unused |
| TelemetryService | `lib/telemetry_service.py` (102 lines) | Correct but unused |
| WorkflowStateService | `lib/workflow_state_service.py` (36 lines) | Correct but unused |

Tests exist and pass for all services: `test_mcp_controller.py`, `test_content_retrieval_tracking.py`.

## Phased Approach

### Phase 0: Telemetry verification (immediate)

**Goal**: Verify the DuckDB content retrieval tracking works end-to-end.

**Approach**: The `get_full_content()` fix (commit `bc123d9`) added DuckDB recording but it never fires because full content is shipped inline. Write an integration test that:
1. Stores content via `store_content()`
2. Calls `get_full_content()`
3. Verifies DuckDB records the retrieval

This validates the plumbing without architectural changes.

### Phase 1: Extract BackendService

**Goal**: Move backend communication out of the router into its own service.

**What moves**:
- `_get_connection()` — process spawning, MCP handshake
- `_forward_to_server()` — JSON-RPC communication, timeouts, reconnection
- `_get_backend_lock()` — per-backend locking
- `_connections`, `_backend_locks` — connection state
- `register_server()`, `unregister_server()`, `_servers` — server registry

**What stays on router for now** (moves in later phases):
- Workflow proxy / federation proxy logic
- `_ensure_serena_project()` (Serena-specific behavior)
- `_cache_workflow_state()` / `_restore_workflow_state()` (workflow-specific)
- `_extract_summary()` / `_summarize()` (replaced by SummarizationService)

**Result**: `BackendService` with `invoke(destination, tool_name, args) → raw result`. Controller uses it.

### Phase 2: Wire transports to controller

**Goal**: Both stdio and socket handlers call `controller.handle_call()` for backend calls.

**Changes**:
- Router `__init__`: create `MCPController(backend_service, summarization, telemetry, workflow_state)`
- Stdio handler: replace inline route+envelope with `controller.handle_call()`
- Socket handler: same
- `get_full` handlers: delegate to `controller.get_full_content()`

**Result**: Controller orchestrates backend calls. Summarization produces summary + content_id (no inline full). Telemetry fires. Two-step content retrieval works.

### Phase 3: Clean up route()

**Goal**: Remove dead code from router.

**What to remove**:
- `route()` method (replaced by controller + BackendService)
- `_summarize()`, `_extract_summary()`, `_fallback_summary()` (replaced by SummarizationService)
- `RouterResponse` class (no longer needed)
- `format_response_envelope()`, `ResponseCache` (replaced by WorkflowStateService)
- Inline telemetry tracking (replaced by TelemetryService)
- `_content_store`, `store_content()`, `get_full_content()` on router (moved to controller)

### Phase 4: Decompose remaining concerns

**Goal**: Address the things left behind in Phase 1.

- Workflow proxy / federation → routing policy service or stays on BackendService
- `_ensure_serena_project()` → Serena-specific middleware or hook
- Workflow state caching → WorkflowStateService or separate cache service
- `TelemetryCollector` (transport-level call tracking) → its own service on the controller

### Phase 5 (optional): Rename

- `MCPRouter` → `MCPServer` or `MCPGateway`
- Clean up module structure

## Risks

- **Phase 1 is the biggest risk** — extracting from a 3K-line file with lots of internal dependencies. Needs careful testing.
- **Proxy/federation logic** is tangled with routing. Phase 1 may need to include some proxy logic to keep things working.
- **Workflow state caching** is tightly coupled to `_forward_to_server()`. May need to stay with BackendService initially.

## Testing Strategy

- Existing service tests must pass at every phase
- Integration tests for each phase verifying the new wiring
- The router's existing behavior must be preserved — same inputs, same outputs (except the envelope format changes in Phase 2: summary + content_id instead of summary + full)
