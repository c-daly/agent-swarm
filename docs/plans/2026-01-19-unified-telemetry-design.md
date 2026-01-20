# Unified Telemetry Schema v2.0

## Overview
Replace current fragmented structures with a single coherent schema.

## Key Schema Decisions
1. `days{}` replaces: daily_summaries, historical_timeline, aggregates
2. `by_session` nested under each day for session drill-down  
3. `source` field marks data origin ("jsonl" = actual, "router" = estimate)
4. `filters` section for pre-computed dashboard dropdowns
5. Rolling aggregates computed on write, not read

## Implementation Phases
1. Schema Migration - Create v2.0, migrate existing data, backup v1
2. JSONL Processing - Extraction, SessionStart hook, track processed
3. Router Integration - Write v2.0 schema, add summarization tracking
4. Dashboard Update - Update charts.py, implement filter bar
5. Session Drill-Down - Add session selector, detail view
6. Cleanup - Remove legacy code, update documentation

## Success Criteria
1. days[date].calls.total matches actual count from logs
2. Token values from JSONL show source: "jsonl"
3. All dropdowns affect chart rendering
4. Can view metrics for individual sessions
5. Existing charts work during migration

## Field Mapping
| Old Field | New Location |
|-----------|--------------|
| daily_summaries[date].calls | days[date].calls.total |
| daily_summaries[date].tokens | days[date].tokens.input + output |
| aggregates.tool_usage | days[date].calls.by_tool |
| cache_stats | days[date].tokens.cache_* |

---

## Implementation Status (2026-01-19)

### Completed Tasks

1. **Schema Module (`lib/telemetry_schema_v2.py`)**
   - TypedDict definitions for all v2 structures
   - Factory functions: `default_token_data()`, `default_day_data()`, `default_telemetry_v2()`
   - Update functions: `ensure_day()`, `update_timing_stats()`, `merge_tokens()`, `merge_calls()`
   - Aggregate functions: `recompute_aggregates()`, `update_filter_options()`
   - I/O functions: `load_telemetry_v2()`, `save_telemetry_v2()`

2. **Migration Script (`scripts/migrate_telemetry_v2.py`)**
   - Converts v1 schema to v2 schema
   - Preserves all historical data
   - Maintains events array for backward compatibility
   - Populates filter options from aggregates

3. **JSONL Extraction (`lib/jsonl_extractor.py`)**
   - Chunked processing for large file sets (~1027 files, ~656MB)
   - Progress tracking via `jsonl_processing_progress.json`
   - Functions: `find_jsonl_files()`, `process_jsonl_file()`, `process_batch()`

4. **SessionStart Hook (`hooks/telemetry-sessionstart.py`)**
   - Incremental JSONL processing (25 files per session)
   - Registered in `hooks/hooks.json`

5. **Updated Telemetry Hooks**
   - `hooks/telemetry-posttool.py`: Now writes v2 schema
   - Tracks per-session token/call data
   - Uses `source` field ("jsonl" vs "router")

6. **Charts Dashboard (`scripts/charts.py`)**
   - Added `load_telemetry()` helper for v2 compatibility
   - Maintains backward compatibility with v1 structure
   - All 14 chart functions updated

### Filter Infrastructure

The v2 schema now provides filter data:
- `filters.available_tools`: 55 tools
- `filters.available_backends`: 8 backends
- `filters.available_sessions`: populated per-day

A visual filter bar UI in the dashboard would be future work.

### Files Modified/Created

**New Files:**
- `lib/telemetry_schema_v2.py`
- `lib/jsonl_extractor.py`
- `scripts/migrate_telemetry_v2.py`
- `hooks/telemetry-sessionstart.py`
- `docs/plans/2026-01-19-unified-telemetry-design.md`

**Modified Files:**
- `hooks/telemetry-posttool.py`
- `hooks/hooks.json`
- `scripts/charts.py`

**Data Files:**
- `.state/telemetry.json` (now v2 schema)
- `.state/telemetry.v1.backup.json` (backup of original)
- `.state/jsonl_processing_progress.json` (JSONL progress tracking)

### Backward Compatibility

- `events[]` array preserved for chart functions
- `load_telemetry()` helper converts v2 to v1 views when needed
- Legacy `daily_summaries` accessible via helper
