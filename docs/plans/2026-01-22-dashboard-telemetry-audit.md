# Dashboard vs Telemetry Audit

**Date:** 2026-01-22
**Status:** Analysis Complete
**Scope:** Dashboard charts and their data requirements

## Executive Summary

An audit of the dashboard charts reveals gaps between what charts expect and what the DuckDB telemetry system currently captures. Several charts will show empty/zero data until corresponding telemetry fields are populated.

## Data Source

The telemetry system uses **DuckDB** with this schema (`lib/stores/duckdb_store.py:63-88`):

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    session_id VARCHAR NOT NULL,
    agent_id VARCHAR,
    tool VARCHAR NOT NULL,
    backend VARCHAR NOT NULL,
    duration_ms INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    agent_type VARCHAR,
    workflow_id VARCHAR,
    error_type VARCHAR,
    -- Summarization fields (not yet populated)
    was_summarized BOOLEAN DEFAULT FALSE,
    original_size INTEGER,
    summary_size INTEGER
)
```

## Chart Status Matrix

### Working Charts

| Chart | Function | Required Fields | Status |
|-------|----------|-----------------|--------|
| Tool Usage | `chart_tool_usage()` | tool, COUNT(*) | ✅ Ready |
| Efficiency Trend | `chart_efficiency_trend()` | status, timestamp | ✅ Ready |
| Token Trend | `chart_token_trend()` | input_tokens, output_tokens, timestamp | ✅ Ready |
| Latency | `chart_latency_by_tool()` | duration_ms, tool | ✅ Ready |
| Cache Efficiency | `chart_cache_efficiency()` | cache_read_tokens, cache_creation_tokens | ✅ Ready |
| Activity Heatmap | `chart_activity_heatmap()` | timestamp | ✅ Ready |
| Native vs MCP | `chart_native_vs_mcp()` | backend | ✅ Ready |
| Error Timeline | `chart_error_timeline()` | status, error_type, timestamp | ✅ Ready |
| Subagents | `chart_subagents()` | agent_type, tokens | ✅ Ready |

### Charts Missing Data

| Chart | Function | Required Fields | Issue |
|-------|----------|-----------------|-------|
| Compression Ratio | `chart_compression_ratio()` | original_size, summary_size | Fields never populated |
| Tokens Saved | `chart_tokens_saved()` | original_size, summary_size | Fields never populated |

## Issue Details

### Issue 1: Summarization Charts Have No Data

**Affected:** `chart_compression_ratio()`, `chart_tokens_saved()`
**Location:** `scripts/charts.py:2731-3061`

These charts expect per-event summarization data:

```python
# charts.py:2743 - filters for events with summarization data
efficiency_events = [e for e in events if e.get("full_size", 0) > 0]

# charts.py:2766-2767 - reads summarization metrics
full_chars += e.get("full_size", 0)      # Maps to original_size
summary_chars += e.get("summary_size", 0)
```

**Current behavior:** Shows "No efficiency data found" or renders with zeros.

**DuckDB columns exist but aren't populated:**
- `was_summarized` - always FALSE
- `original_size` - always NULL
- `summary_size` - always NULL

---

### Issue 2: charts.py Still Checks for Legacy v3 JSONL Directory

**Location:** `scripts/charts.py:40-50`

```python
TELEMETRY_V3_DIR = STATE_DIR / "telemetry_v3"

# Checks for JSONL files that don't exist
if TELEMETRY_V3_DIR.exists() and any(TELEMETRY_V3_DIR.glob("**/*.jsonl")):
    _duckdb_store = DuckDBStore(str(TELEMETRY_V3_DIR))
```

This checks for a `telemetry_v3/` directory with JSONL files, but:
- The actual DuckDB lives at `.state/telemetry.duckdb`
- No JSONL files are used anymore

**Impact:** charts.py falls back to v2 JSON instead of querying DuckDB directly.

---

### Issue 3: `_load_telemetry_v3()` Field Mapping

**Location:** `scripts/charts.py:53-190`

When loading from DuckDB, events are mapped but missing summarization fields:

```python
# charts.py:118-142 - fetches events but doesn't include summarization columns
recent = _duckdb_store.conn.execute("""
    SELECT timestamp, tool, backend, status, duration_ms,
           COALESCE(input_tokens, 0) as input_tokens,
           COALESCE(output_tokens, 0) as output_tokens,
           session_id
    FROM events
    ...
""")
```

Missing from SELECT: `was_summarized`, `original_size`, `summary_size`

---

## Recommendations

### 1. Fix charts.py DuckDB Connection

Update `scripts/charts.py` to connect to the actual DuckDB location:

```python
# Current (wrong)
TELEMETRY_V3_DIR = STATE_DIR / "telemetry_v3"
if TELEMETRY_V3_DIR.exists() and any(TELEMETRY_V3_DIR.glob("**/*.jsonl")):
    _duckdb_store = DuckDBStore(str(TELEMETRY_V3_DIR))

# Should be
DUCKDB_PATH = STATE_DIR / "telemetry.duckdb"
if DUCKDB_PATH.exists():
    _duckdb_store = DuckDBStore(str(STATE_DIR))
```

### 2. Handle Missing Summarization Data Gracefully

For `chart_compression_ratio()` and `chart_tokens_saved()`:

Option A: **Hide charts** until data is available
```python
def chart_compression_ratio():
    # Check if any summarization data exists
    if not has_summarization_data():
        return None  # Don't generate chart
```

Option B: **Show "Coming Soon" state**
```python
def chart_compression_ratio():
    if not has_summarization_data():
        return generate_placeholder_chart("Summarization tracking coming soon")
```

### 3. Add Summarization Fields to Event Query

Update `_load_telemetry_v3()` to include summarization columns:

```python
recent = _duckdb_store.conn.execute("""
    SELECT timestamp, tool, backend, status, duration_ms,
           input_tokens, output_tokens, session_id,
           was_summarized, original_size, summary_size  -- Add these
    FROM events
    ...
""")
```

### 4. Delete or Deprecate v2 JSON Code Paths

Once DuckDB is the sole source:
- Remove `load_telemetry()` v2 JSON fallback logic
- Remove `telemetry_schema_v2.py`
- Clean up dual-write in hooks

---

## Files Reference

| File | Purpose | Key Lines |
|------|---------|-----------|
| `scripts/charts.py` | Chart generation | 40-50 (DuckDB init), 53-190 (v3 loader), 2731-3061 (summarization charts) |
| `lib/stores/duckdb_store.py` | DuckDB store | 60-88 (schema), 121-152 (insert) |
| `lib/stores/events.py` | Event dataclass | 10-43 (ToolCallEvent) |
| `.state/telemetry.duckdb` | Production database | 1.5MB, events table |

---

## Next Steps

1. [ ] Fix charts.py to use correct DuckDB path
2. [ ] Decide on summarization charts: hide vs placeholder
3. [ ] Populate summarization fields when MCP router summarizes content
4. [ ] Remove v2 JSON code paths after migration complete
