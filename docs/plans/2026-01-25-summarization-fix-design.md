# Summarization Fix Design

**Date:** 2026-01-25  
**Status:** Ready for implementation  
**Goal:** Fix subagent summarization path and add telemetry for callback rate tracking

## Problem Statement

Subagents connecting via socket layer receive raw tool responses instead of summarized responses. This causes:
1. Higher token usage for subagent sessions
2. No visibility into summarization effectiveness
3. Zero callback rate (agents never request full content because they don't know they can)

## Root Cause Analysis

Two summarization paths exist:
- **Main MCP path** (`mcp_router.py` line ~2517): Returns `{summary, full}` envelope with LLM-generated structured summaries
- **Socket path** (`mcp_router.py` line ~1186): Returns raw `full_content` directly, bypassing summarization entirely

The socket handler calls `self.route()` which returns a `RouterResponse` with both `summary` and `full` fields, but only uses `route_response.full`.

## Design

### Change 1: Fix Socket Response Format

**File:** `lib/mcp_router.py`  
**Location:** `_handle_socket_client` method, around line 1180-1186

**Before:**
```python
result = full_content
```

**After:**
```python
envelope = {
    "summary": route_response.summary,
    "full": full_content,
    "content_id": route_response.correlation_id,
    "guidance": "Use this summary to proceed. If you need specific details, make a targeted follow-up query rather than requesting full content. Full retrieval via router__poll(correlation_id='<id>') should be a last resort."
}
result = envelope
```

### Change 2: Track Summarization in Socket Path

**File:** `lib/mcp_router.py`  
**Location:** After creating the envelope in `_handle_socket_client`

Add telemetry recording:
```python
# Track content creation for callback rate analysis
if route_response.correlation_id:
    try:
        self._duckdb_store.record_content_creation(route_response.correlation_id)
    except Exception:
        pass  # Non-critical telemetry
```

### Change 3: Add Callback Rate Query

**File:** `lib/stores/duckdb_store.py`  
**New method:**

```python
def get_summarization_callback_rate(self, days: int = 7) -> dict:
    """Get summarization callback rate for the past N days.
    
    Returns:
        Dict with total_offered, total_retrieved, callback_rate
    """
    result = self.conn.execute("""
        SELECT 
            COUNT(*) as total_offered,
            COUNT(*) FILTER (WHERE was_retrieved = TRUE) as total_retrieved
        FROM content_retrievals
        WHERE created_at >= CURRENT_DATE - INTERVAL ? DAY
    """, [days]).fetchone()
    
    total_offered = result[0] or 0
    total_retrieved = result[1] or 0
    callback_rate = total_retrieved / total_offered if total_offered > 0 else 0.0
    
    return {
        "total_offered": total_offered,
        "total_retrieved": total_retrieved,
        "callback_rate": callback_rate,
        "days": days
    }
```

### Change 4: Enhance content_retrievals Table (Optional)

For deeper analysis, consider adding columns:
```sql
ALTER TABLE content_retrievals ADD COLUMN original_size INTEGER;
ALTER TABLE content_retrievals ADD COLUMN summary_size INTEGER;
ALTER TABLE content_retrievals ADD COLUMN tool_name VARCHAR;
```

This enables:
- Compression ratio analysis per tool
- Identifying which tools benefit most from summarization

## Verification

After implementation:
1. Run a subagent task and verify it receives `{summary, full, content_id, guidance}` envelope
2. Check `content_retrievals` table populates for socket requests
3. Query callback rate: should be >0% if working (agents should occasionally need full content)
4. If callback rate stays at 0%, summaries may be sufficient OR guidance is too discouraging

## Open Questions

1. Should callback rate target be configurable? (e.g., if >10%, summaries may be too aggressive)
2. Should we add a dashboard widget for real-time callback rate visualization?

## Files to Modify

1. `lib/mcp_router.py` - Socket handler fix (~10 lines)
2. `lib/stores/duckdb_store.py` - Callback rate query (~15 lines)
3. `lib/charts.py` - Optional dashboard widget

## Estimated Scope

Small change, high impact. Core fix is ~10 lines in socket handler.
