# Router Refactor Design

**Date:** 2026-01-21  
**Status:** Draft  
**Branch:** move_files_to_db

## Problem Statement

The current `mcp_router.py` has grown into a monolith with mixed responsibilities:
- Tool routing to backend MCP servers
- Response summarization
- Telemetry recording
- Workflow state management
- File-based code that should be removed

Additionally, several hooks are redundant now that the router handles telemetry:
- `mcp-summarizer.py` - dead code (not registered)
- `telemetry-posttool.py` - redundant with router telemetry

## Design Goals

1. **Single Responsibility** - Each service handles one concern
2. **Independence** - Services don't import each other
3. **No Files** - All persistence through DuckDB or workflow state
4. **Thin Controller** - Router becomes orchestration-only layer

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   MCPController (thin)                   │
│  Just wiring: route → summarize → record → return       │
└─────────────────────────────────────────────────────────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Routing    │  │ Summarize   │  │ Telemetry   │  │  Workflow   │
│  Service    │  │  Service    │  │  Service    │  │   State     │
│             │  │             │  │ (existing)  │  │  Service    │
│             │  │             │  │             │  │             │
│ Routes to   │  │ Truncates   │  │ Records to  │  │ content_id  │
│ backends    │  │ big results │  │ DuckDB      │  │ storage,    │
│             │  │             │  │             │  │ operational │
│             │  │             │  │             │  │ data        │
└─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
```

## File Structure

```
lib/
├── mcp_controller.py          # Thin orchestration (~50 lines)
├── routing_service.py         # Backend routing logic
├── summarization_service.py   # Summarization logic
├── workflow_state_service.py  # content_id storage, operational data
└── telemetry_service.py       # Already exists, unchanged
```

## Service Responsibilities

### MCPController (`mcp_controller.py`)
- Entry point for MCP tool calls
- Wires services together in sequence: route → summarize → record → return
- No business logic - just orchestration
- ~50 lines of code

### RoutingService (`routing_service.py`)
- Routes MCP tool calls to appropriate backend servers
- Manages server connections and health
- Handles server-specific protocols
- Returns raw results to controller

### SummarizationService (`summarization_service.py`)
- Determines if response needs summarization (size threshold)
- Generates summaries for large responses
- Stores full content via WorkflowStateService
- Returns `{summary, content_id, full_available}` or passthrough

### TelemetryService (`telemetry_service.py`)
- Already exists with correct interface
- `insert_event(event)` - records to DuckDB
- `get_summary()`, `get_tool_breakdown()` - reads for dashboard
- No changes needed

### WorkflowStateService (`workflow_state_service.py`)
- Stores content_id → full content mapping
- Manages operational data for hooks/agents
- Exposes workflow MCP contract:
  - `workflow_set_value(workflow_id, key, value)`
  - `workflow_get_value(workflow_id, key)`
  - `workflow_update(workflow_id, updates)`
- TTL support for content cleanup (future optimization)

## Two-Step Content Retrieval

1. Client calls tool → Controller routes → gets large result
2. SummarizationService generates summary, stores full content via WorkflowStateService
3. Returns `{summary, content_id: "abc123", full_available: true}`
4. Client calls same endpoint with `{content_id: "abc123"}`
5. Controller detects content_id, retrieves from WorkflowStateService
6. Returns full content, removes from storage

## Changes Required

### Phase 1: Remove Dead Code
- [ ] Delete `hooks/mcp-summarizer.py`
- [ ] Remove from `hooks.json` if present
- [ ] Delete any `last_summary.json` references

### Phase 2: Remove Redundant Hooks
- [ ] Remove telemetry writing from `telemetry-posttool.py`
- [ ] Evaluate if hook is needed at all

### Phase 3: Router Uses TelemetryService
- [ ] Replace `save_telemetry_v2` calls with `TelemetryService.insert_event`
- [ ] Remove file-based telemetry code
- [ ] Remove `telemetry.json` file references

### Phase 4: Extract Services
- [ ] Create `routing_service.py` - extract routing logic
- [ ] Create `summarization_service.py` - extract summarization logic
- [ ] Create `workflow_state_service.py` - extract workflow state logic
- [ ] Create `mcp_controller.py` - thin orchestration layer
- [ ] Deprecate `mcp_router.py`

### Phase 5: Content ID via Workflow MCP
- [ ] SummarizationService stores content via workflow MCP contract
- [ ] Controller handles content_id passthrough
- [ ] Remove any file-based content storage

## Migration Notes

- Existing `telemetry_service.py` already has the right interface
- Migration script (`migrate_jsonl_to_duckdb.py`) handles historical data
- Session IDs link real-time telemetry to transcript-based actual tokens

## Testing Strategy

- Unit tests for each service in isolation
- Integration test for full flow through controller
- Verify telemetry records correctly to DuckDB
- Verify two-step retrieval works end-to-end
