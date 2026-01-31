# Dashboard Implementation Spec

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a dashboard at `dashboard/` in the agent-swarm repo that visualizes telemetry data from Claude Code sessions — tool usage, token accounting, concurrency, summarization, errors, and session replay.

**Architecture:** Python HTTP server (stdlib only at runtime) serving a static Alpine.js + Chart.js frontend. SQLite as the single read store. Import pipeline reads Claude's native JSONL transcripts and legacy DuckDB data into SQLite. Data provider interface with SQLite and Mock implementations. **No file-based state.** The only writable artifact is the SQLite database, and only the import script writes to it. The server is strictly read-only.

**Tech Stack:** Python 3.10+ stdlib (http.server, sqlite3, json, pathlib), Alpine.js 3.x, Chart.js 4.x, DuckDB pip package (import only)

---

## 1. Data Sources

### 1.1 Claude's Native JSONL Transcripts (Primary)

Claude Code writes a JSONL transcript for every session to `~/.claude/projects/<project-slug>/<uuid>.jsonl`. Subagent transcripts go to `<uuid>/subagents/agent-<id>.jsonl`. These files are written by Claude Code itself — not by agent-swarm — and have never stopped being produced.

**Location:** `~/.claude/projects/` (all project directories)

**Format:** One JSON object per line. Entry types:

```
type=file-history-snapshot  — file state at session start
type=progress               — internal progress events
type=user                   — user messages and tool_result blocks
type=assistant              — assistant messages, tool_use blocks, usage data
```

**Tool call data is in `assistant` entries:**

```json
{
  "type": "assistant",
  "sessionId": "0a3112ce-...",
  "timestamp": "2026-01-30T17:40:12.345Z",
  "message": {
    "role": "assistant",
    "type": "message",
    "usage": {
      "input_tokens": 3,
      "output_tokens": 9,
      "cache_read_input_tokens": 13220,
      "cache_creation_input_tokens": 7082
    },
    "content": [
      {
        "type": "tool_use",
        "id": "toolu_01Ud11gfestMz43g8hMArZbc",
        "name": "Task",
        "input": { "description": "...", "prompt": "...", "subagent_type": "Explore" }
      }
    ]
  }
}
```

**Tool results are in `user` entries:**

```json
{
  "type": "user",
  "message": {
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_01Ud11gfestMz43g8hMArZbc",
        "content": "..."
      }
    ]
  }
}
```

**Key fields to extract per tool call:**
- `timestamp` — from the assistant entry
- `session_id` — from `sessionId` field on the entry
- `agent_id` — same as session_id for main sessions; from the filename for subagent files (`agent-<id>.jsonl`)
- `tool` — from `content[].name` where `type=tool_use`
- `tool_use_id` — from `content[].id`, used to match with tool_result
- `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens` — from `message.usage`
- `status` — `"error"` if the matching tool_result contains error indicators (see Section 3.3), else `"success"`
- `duration_ms` — time delta between the tool_use assistant entry and the next entry containing the matching tool_result
- `error_type` — first 200 chars of error content if status is error
- `backend` — derived from tool name prefix: `mcp__router__*` → `"router"`, `mcp__plugin_*` → `"plugin"`, bare names (Read, Bash, Edit, etc.) → `"native"`
- `original_size` — length of tool_result content string
- `was_summarized` — `true` if `original_size > 2000` (matching the controller's `_summarization_threshold`)
- `summary_size` — `min(original_size, 2000)` if `was_summarized`, else `null`

**Existing parser:** `lib/jsonl_extractor.py` already finds and parses these files. It currently extracts session-level token aggregates but not per-tool-call events. The import script should either extend it or reimplement the per-event extraction described above.

### 1.2 Legacy DuckDB (Secondary)

**Location:** `.state/telemetry.duckdb` (997MB)

**Contents:** 19,785 events from Jan 9–31, 2026. 16,016 events (pre-Jan 21) have verified data imported from Claude transcripts. 3,802 events (Jan 27–31) were written directly by the `telemetry-posttool.py` hook and have quality issues:
- Session IDs are timestamp-based fallbacks (`20260127-152310`) instead of UUIDs
- Nearly 1 session per event (broken session tracking)
- Backend names differ (`claude-native` vs `native`)
- 6-day gap from Jan 21–27

**Schema (DuckDB):**

```sql
-- events table
id              INTEGER     NOT NULL
timestamp       TIMESTAMP   NOT NULL
session_id      VARCHAR     NOT NULL
agent_id        VARCHAR     -- nullable
tool            VARCHAR     NOT NULL
backend         VARCHAR     NOT NULL
duration_ms     INTEGER     NOT NULL
status          VARCHAR     NOT NULL
input_tokens    INTEGER     -- nullable
output_tokens   INTEGER     -- nullable
cache_read_tokens    INTEGER  -- nullable
cache_creation_tokens INTEGER -- nullable
agent_type      VARCHAR     -- nullable
workflow_id     VARCHAR     -- nullable
error_type      VARCHAR     -- nullable
was_summarized  BOOLEAN     -- nullable
original_size   INTEGER     -- nullable
summary_size    INTEGER     -- nullable

-- Indexes: idx_events_timestamp, idx_events_session, idx_events_tool

-- content_retrievals table
content_id      VARCHAR     NOT NULL
created_at      TIMESTAMP   -- nullable
retrieved_at    TIMESTAMP   -- nullable
was_retrieved   BOOLEAN     -- nullable

-- agent_types table
agent_id        VARCHAR     NOT NULL
agent_type      VARCHAR     NOT NULL
registered_at   TIMESTAMP   -- nullable
```

**Import strategy:** DuckDB is authoritative for pre-Jan 21 data where it has richer fields (was_summarized, original_size, summary_size, agent_type, workflow_id) that Claude transcripts don't directly provide. Post-Jan 21 DuckDB data should be flagged as `import_source='duckdb_only'` and treated as lower confidence.

### 1.3 Daemon SQLite (Future)

Post-refactor, the daemon's `DataStore` (defined in `lib/datastore.py`) writes events directly to SQLite at `data/datastore.db`. Schema matches the DuckDB events table. The dashboard should be able to read this file directly once the daemon is live — no import needed, just point `--db` at it.

## 2. SQLite Schema

The dashboard uses its own SQLite database. All timestamps stored as ISO 8601 UTC strings.

```sql
-- Main events table
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,          -- ISO 8601 UTC
    session_id TEXT NOT NULL,
    agent_id TEXT DEFAULT '',
    tool TEXT NOT NULL,
    backend TEXT NOT NULL,            -- native, router, plugin, mcp, claude, workflow
    duration_ms INTEGER DEFAULT 0,
    status TEXT NOT NULL,             -- success, error
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    agent_type TEXT DEFAULT '',       -- empty for main agent
    workflow_id TEXT DEFAULT '',
    error_type TEXT DEFAULT '',
    was_summarized INTEGER DEFAULT 0, -- 0 or 1
    original_size INTEGER DEFAULT 0,
    summary_size INTEGER,             -- NULL if not summarized
    import_source TEXT DEFAULT ''     -- 'claude_transcript', 'duckdb', 'duckdb_only', 'daemon'
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_tool ON events(tool);
CREATE INDEX IF NOT EXISTS idx_events_backend ON events(backend);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);

-- Content retrievals (get_full requests)
CREATE TABLE IF NOT EXISTS content_retrievals (
    content_id TEXT PRIMARY KEY,
    created_at TEXT,                  -- ISO 8601 UTC
    retrieved_at TEXT,                -- ISO 8601 UTC, NULL if never retrieved
    was_retrieved INTEGER DEFAULT 0
);

-- Agent type registry
CREATE TABLE IF NOT EXISTS agent_types (
    agent_id TEXT PRIMARY KEY,
    agent_type TEXT NOT NULL,
    registered_at TEXT                -- ISO 8601 UTC
);

-- Import log (prevents duplicate imports)
CREATE TABLE IF NOT EXISTS import_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,             -- 'duckdb', 'claude_transcript', 'daemon'
    source_path TEXT NOT NULL,        -- file path that was imported
    imported_at TEXT NOT NULL,        -- ISO 8601 UTC
    events_inserted INTEGER DEFAULT 0,
    events_skipped INTEGER DEFAULT 0
);

-- Session summary view
CREATE VIEW IF NOT EXISTS v_sessions AS
SELECT
    session_id,
    MIN(timestamp) as start_time,
    MAX(timestamp) as end_time,
    COUNT(*) as event_count,
    SUM(input_tokens) as total_input_tokens,
    SUM(output_tokens) as total_output_tokens,
    SUM(cache_read_tokens) as total_cache_read,
    SUM(cache_creation_tokens) as total_cache_creation,
    SUM(input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens) as total_tokens,
    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
    SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END) as summarization_count,
    COUNT(DISTINCT tool) as unique_tools,
    COUNT(DISTINCT agent_id) as agent_count,
    CAST((julianday(MAX(timestamp)) - julianday(MIN(timestamp))) * 86400000 AS INTEGER) as duration_ms
FROM events
GROUP BY session_id;
```

### 2.1 Deduplication Key

Events are deduplicated by `(timestamp, session_id, agent_id, tool)`. Before inserting, check:

```sql
SELECT COUNT(*) FROM events
WHERE timestamp = ? AND session_id = ? AND agent_id = ? AND tool = ?
```

If count > 0, skip the event. Log it as `events_skipped` in `import_log`.

## 3. Import Script (`dashboard/import.py`)

### 3.1 CLI Interface

```
python dashboard/import.py \
    --db dashboard/data/dashboard.db \
    --claude-projects ~/.claude/projects/ \
    --duckdb .state/telemetry.duckdb \
    --dry-run
```

**Arguments:**
- `--db` (required): Path to output SQLite database. Created if doesn't exist.
- `--claude-projects` (optional): Path to Claude's projects directory. Default: `~/.claude/projects/`
- `--duckdb` (optional): Path to legacy DuckDB file. Omit to skip DuckDB import.
- `--dry-run` (optional): Print what would be imported without writing.
- `--force` (optional): Re-import files already in import_log.

### 3.2 Import Order

1. **DuckDB first** (if `--duckdb` provided):
   - Open DuckDB read-only. Requires `duckdb` pip package.
   - Read all rows from `events` table.
   - For each row, determine `import_source`:
     - If `timestamp < '2026-01-21T12:00:00'`: `import_source = 'duckdb'`
     - Else: `import_source = 'duckdb_only'`
   - Insert into SQLite, deduplicating by `(timestamp, session_id, agent_id, tool)`.
   - Also import `content_retrievals` and `agent_types` tables.
   - Record in `import_log`.

2. **Claude transcripts second** (if `--claude-projects` provided):
   - Walk all `*.jsonl` files under the projects directory recursively.
   - Skip files already in `import_log` (by `source_path`) unless `--force`.
   - For each file, extract per-tool-call events (see Section 3.3).
   - Set `import_source = 'claude_transcript'`.
   - Insert into SQLite, deduplicating. DuckDB data wins on conflict (already inserted in step 1).
   - Record in `import_log`.

### 3.3 Claude Transcript Parsing

For each `.jsonl` file:

1. Read all lines into memory. Parse each as JSON.
2. Build a list of `assistant` entries that contain `tool_use` content blocks.
3. Build a map of `tool_use_id → tool_result` from `user` entries.
4. For each `tool_use` block in each `assistant` entry:

```python
# Extract from assistant entry
timestamp = entry["timestamp"]            # ISO 8601
session_id = entry.get("sessionId", "")   # UUID
usage = entry["message"].get("usage", {})

# Tool info from the content block
tool_name = block["name"]
tool_use_id = block["id"]

# Tokens from usage (these are per-message, not per-tool — see note below)
input_tokens = usage.get("input_tokens", 0)
output_tokens = usage.get("output_tokens", 0)
cache_read = usage.get("cache_read_input_tokens", 0)
cache_creation = usage.get("cache_creation_input_tokens", 0)

# Find matching tool_result
result_content = tool_results_map.get(tool_use_id, "")
is_error = detect_error(result_content)
original_size = len(str(result_content))

# Derive backend from tool name
if tool_name.startswith("mcp__router__"):
    backend = "router"
elif tool_name.startswith("mcp__plugin"):
    backend = "plugin"
elif tool_name.startswith("mcp__"):
    backend = "mcp"
elif tool_name in ("Task", "Skill", "AskUserQuestion", "WebFetch", "WebSearch",
                    "TodoWrite", "EnterPlanMode", "ExitPlanMode"):
    backend = "claude"
else:
    backend = "native"

# Agent ID
# For main session files: agent_id = session_id
# For subagent files (agent-<id>.jsonl): agent_id = <id> from filename
agent_id = extract_agent_id_from_filename(filepath)
```

**Token attribution note:** Claude's `usage` object is per-API-response, not per-tool-call. When an assistant message contains multiple `tool_use` blocks, the tokens are shared across all of them. For messages with N tool calls, divide tokens by N for each event. This is an approximation but better than attributing all tokens to one tool call.

**Error detection** (from `detect_error` in `telemetry-posttool.py`):

```python
def detect_error(content) -> tuple[bool, str]:
    if isinstance(content, dict):
        if content.get("isError"):
            return True, str(content.get("content", ""))[:200]
        if "error" in content:
            return True, str(content["error"])[:200]
    if isinstance(content, str):
        lower = content.lower()
        if any(x in lower for x in ["error:", "exception:", "failed:"]):
            return True, content[:200]
    return False, ""
```

**Duration calculation:** Find the timestamp of the entry containing the matching `tool_result`. Duration = `tool_result_timestamp - tool_use_timestamp` in milliseconds. If no matching result found, duration = 0.

### 3.4 Output

Print a summary after import:

```
Import complete:
  DuckDB: 16,016 inserted, 0 skipped (pre-Jan 21)
  DuckDB: 3,802 inserted, 0 skipped (post-Jan 21, flagged duckdb_only)
  Claude transcripts: 2,179 files processed
    Events: 45,230 inserted, 14,892 skipped (already in DuckDB)
  Total events in database: 50,156
```

## 4. Data Provider Interface

### 4.1 Protocol

```python
# dashboard/providers/__init__.py

from typing import Protocol, Any

class DataProvider(Protocol):
    """Interface for dashboard data access. All methods return JSON-serializable dicts."""

    def overview(self, filters: dict) -> dict: ...
    def tokens(self, filters: dict) -> dict: ...
    def tools(self, filters: dict) -> dict: ...
    def concurrency(self, filters: dict) -> dict: ...
    def summarization(self, filters: dict) -> dict: ...
    def sessions(self, filters: dict) -> dict: ...
    def session_detail(self, session_id: str) -> dict: ...
    def session_replay(self, session_id: str, jsonl_dir: str) -> dict: ...
    def compare(self, filters_a: dict, filters_b: dict) -> dict: ...
    def activity_heatmap(self, filters: dict) -> dict: ...
    def latency(self, filters: dict) -> dict: ...
    def errors(self, filters: dict) -> dict: ...
```

### 4.2 Common Filters

Every provider method accepts a `filters` dict with these optional keys:

```python
{
    "from": "2026-01-15T00:00:00",   # ISO 8601 EST, converted to UTC for query
    "to": "2026-01-20T23:59:59",     # ISO 8601 EST, converted to UTC for query
    "period": "day",                  # hour | day | week | month
    "tool": "Bash,Read",             # comma-separated tool filter
    "backend": "native,router",      # comma-separated backend filter
    "agent_type": "main",            # "main" (agent_id == session_id), "subagent", or specific type
    "status": "success",             # success | error
    "session": "abc123",             # specific session ID
    "sort": "tokens",               # sort dimension (varies by endpoint)
    "limit": 20,                    # max results
    "import_source": "duckdb"       # filter by data provenance
}
```

### 4.3 Filter SQL Builder

Shared utility used by `SqliteProvider`:

```python
# dashboard/providers/filters.py

from datetime import datetime, timedelta, timezone

EST = timezone(timedelta(hours=-5))

def est_to_utc(est_str: str) -> str:
    """Convert EST datetime string to UTC ISO 8601."""
    dt = datetime.fromisoformat(est_str).replace(tzinfo=EST)
    return dt.astimezone(timezone.utc).isoformat()

def utc_to_est(utc_str: str) -> str:
    """Convert UTC ISO 8601 string to EST."""
    dt = datetime.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
    return dt.astimezone(EST).isoformat()

def build_where(filters: dict) -> tuple[str, list]:
    """Build WHERE clause and params from filters dict.

    Returns:
        (where_clause, params) where where_clause includes 'WHERE' prefix
        or empty string if no filters.
    """
    clauses = []
    params = []

    if "from" in filters:
        clauses.append("timestamp >= ?")
        params.append(est_to_utc(filters["from"]))
    if "to" in filters:
        clauses.append("timestamp <= ?")
        params.append(est_to_utc(filters["to"]))
    if "tool" in filters:
        tools = [t.strip() for t in filters["tool"].split(",")]
        placeholders = ",".join("?" * len(tools))
        clauses.append(f"tool IN ({placeholders})")
        params.extend(tools)
    if "backend" in filters:
        backends = [b.strip() for b in filters["backend"].split(",")]
        placeholders = ",".join("?" * len(backends))
        clauses.append(f"backend IN ({placeholders})")
        params.extend(backends)
    if "status" in filters:
        clauses.append("status = ?")
        params.append(filters["status"])
    if "session" in filters:
        clauses.append("session_id = ?")
        params.append(filters["session"])
    if "agent_type" in filters:
        val = filters["agent_type"]
        if val == "main":
            clauses.append("agent_id = session_id")
        elif val == "subagent":
            clauses.append("agent_id != session_id")
        else:
            clauses.append("agent_type = ?")
            params.append(val)
    if "import_source" in filters:
        clauses.append("import_source = ?")
        params.append(filters["import_source"])

    if not clauses:
        return "", []
    return "WHERE " + " AND ".join(clauses), params

def period_group_expr(period: str) -> str:
    """Return SQL expression for grouping timestamps by period.

    All output is in EST. Timestamps in DB are UTC.
    """
    # SQLite doesn't have native timezone support, so we subtract 5 hours
    utc_adj = "datetime(timestamp, '-5 hours')"
    if period == "hour":
        return f"strftime('%Y-%m-%d %H:00', {utc_adj})"
    elif period == "day":
        return f"strftime('%Y-%m-%d', {utc_adj})"
    elif period == "week":
        return f"strftime('%Y-W%W', {utc_adj})"
    elif period == "month":
        return f"strftime('%Y-%m', {utc_adj})"
    return f"strftime('%Y-%m-%d', {utc_adj})"
```

### 4.4 SqliteProvider

```python
# dashboard/providers/sqlite.py

import sqlite3
from pathlib import Path
from .filters import build_where, period_group_expr, utc_to_est

class SqliteProvider:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
```

Each method implementation is specified in Section 5 (API Endpoints) alongside the SQL queries and response shapes.

### 4.5 MockProvider

```python
# dashboard/providers/mock.py

import random
from datetime import datetime, timedelta

class MockProvider:
    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)
        self._generate_data()
```

Generates 5,000 synthetic events across 200 sessions over 14 days. Tool distribution approximates real data: 20% Bash, 15% Read, 10% mcp_router_bash, etc. Error rate ~12%. Summarization rate ~6%. Returns JSON shapes identical to `SqliteProvider`.

Deterministic: same seed always produces same data.

## 5. API Endpoints

### 5.1 Server (`dashboard/server.py`)

Single-file HTTP server. No framework dependencies.

```python
# dashboard/server.py

import argparse
import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

class DashboardHandler(SimpleHTTPRequestHandler):
    provider = None   # Set at startup
    jsonl_dir = None  # Set at startup
    static_dir = None # Set at startup

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api(parsed)
        else:
            # Serve static files from static_dir
            self._serve_static(parsed.path)

    def _handle_api(self, parsed):
        path = parsed.path
        filters = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        # ... route to provider methods (see below)

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        file_path = Path(self.static_dir) / path.lstrip("/")
        if file_path.exists() and file_path.is_file():
            self._send_file(file_path)
        else:
            self.send_error(404)

    def _send_json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

def main():
    parser = argparse.ArgumentParser(description="Dashboard server")
    parser.add_argument("--db", help="Path to SQLite database")
    parser.add_argument("--jsonl", help="Path to Claude projects dir for session replay",
                        default=str(Path.home() / ".claude/projects"))
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--mock", action="store_true", help="Use mock data provider")
    args = parser.parse_args()

    if args.mock:
        from providers.mock import MockProvider
        DashboardHandler.provider = MockProvider()
    else:
        from providers.sqlite import SqliteProvider
        DashboardHandler.provider = SqliteProvider(args.db)

    DashboardHandler.jsonl_dir = args.jsonl
    DashboardHandler.static_dir = str(Path(__file__).parent / "static")

    server = HTTPServer(("127.0.0.1", args.port), DashboardHandler)
    print(f"Dashboard: http://127.0.0.1:{args.port}")
    server.serve_forever()
```

### 5.2 Endpoint Specifications

Each endpoint below specifies: route, SQL query, response JSON shape.

---

#### `GET /api/overview`

Top-level stats for the filtered time range.

**SQL:**

```sql
SELECT
    COUNT(*) as total_events,
    COUNT(DISTINCT session_id) as total_sessions,
    SUM(input_tokens) as total_input,
    SUM(output_tokens) as total_output,
    SUM(cache_read_tokens) as total_cache_read,
    SUM(cache_creation_tokens) as total_cache_creation,
    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as total_errors,
    MIN(timestamp) as first_event,
    MAX(timestamp) as last_event,
    AVG(duration_ms) as avg_duration_ms,
    SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END) as total_summarized,
    COUNT(DISTINCT tool) as unique_tools,
    COUNT(DISTINCT CASE WHEN agent_id != session_id THEN agent_id END) as subagent_count
FROM events
{where}
```

**Response:**

```json
{
  "total_events": 19785,
  "total_sessions": 4268,
  "total_input_tokens": 1877934,
  "total_output_tokens": 1716176,
  "total_cache_read": 1497259372,
  "total_cache_creation": 90437266,
  "total_errors": 2446,
  "error_rate": 0.124,
  "first_event": "2026-01-09T16:18:01-05:00",
  "last_event": "2026-01-31T10:55:21-05:00",
  "avg_duration_ms": 1234.5,
  "total_summarized": 1171,
  "unique_tools": 181,
  "subagent_count": 129
}
```

All timestamps in response are EST.

---

#### `GET /api/tokens?group_by=tool|agent|day`

Token breakdown by the specified dimension.

**SQL (group_by=day, period from filters defaults to "day"):**

```sql
SELECT
    {period_group_expr} as period,
    SUM(input_tokens) as input,
    SUM(output_tokens) as output,
    SUM(cache_read_tokens) as cache_read,
    SUM(cache_creation_tokens) as cache_creation,
    COUNT(*) as event_count
FROM events
{where}
GROUP BY period
ORDER BY period
```

**SQL (group_by=tool):**

```sql
SELECT
    tool,
    SUM(input_tokens + output_tokens) as total_tokens,
    SUM(input_tokens) as input,
    SUM(output_tokens) as output,
    SUM(cache_read_tokens) as cache_read,
    SUM(cache_creation_tokens) as cache_creation,
    COUNT(*) as event_count
FROM events
{where}
GROUP BY tool
ORDER BY total_tokens DESC
LIMIT {limit}
```

**SQL (group_by=agent):**

```sql
SELECT
    CASE WHEN agent_id = session_id THEN 'main' ELSE 'subagent' END as agent_role,
    SUM(input_tokens) as input,
    SUM(output_tokens) as output,
    SUM(cache_read_tokens) as cache_read,
    SUM(cache_creation_tokens) as cache_creation,
    COUNT(*) as event_count
FROM events
{where}
GROUP BY agent_role
```

**Response (group_by=day):**

```json
{
  "group_by": "day",
  "period": "day",
  "data": [
    {
      "period": "2026-01-09",
      "input": 45000,
      "output": 32000,
      "cache_read": 5000000,
      "cache_creation": 200000,
      "event_count": 523
    }
  ]
}
```

---

#### `GET /api/tools?sort=count|errors|tokens`

Tool usage statistics.

**SQL:**

```sql
SELECT
    tool,
    COUNT(*) as call_count,
    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
    CAST(SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*) as error_rate,
    SUM(input_tokens + output_tokens) as total_tokens,
    AVG(duration_ms) as avg_duration_ms,
    SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END) as summarized_count
FROM events
{where}
GROUP BY tool
ORDER BY {sort_column} DESC
LIMIT {limit}
```

Where `sort_column` maps: `count` → `call_count`, `errors` → `error_count`, `tokens` → `total_tokens`.

**Response:**

```json
{
  "sort": "count",
  "data": [
    {
      "tool": "Bash",
      "call_count": 3934,
      "error_count": 245,
      "error_rate": 0.062,
      "total_tokens": 543210,
      "avg_duration_ms": 2341.5,
      "summarized_count": 166
    }
  ]
}
```

---

#### `GET /api/concurrency?session=X`

Overlapping tool calls within a session, showing parallelism.

**SQL:**

```sql
SELECT
    timestamp,
    tool,
    agent_id,
    duration_ms,
    status
FROM events
WHERE session_id = ?
ORDER BY timestamp
```

**Server-side computation:** For each event, compute `end_time = timestamp + duration_ms`. Then for each event, count how many other events in the session overlap in time (their start < this end AND their end > this start). Return events annotated with concurrency level.

**Response:**

```json
{
  "session_id": "abc123",
  "events": [
    {
      "timestamp": "2026-01-15T10:30:00-05:00",
      "tool": "Task",
      "agent_id": "abc123",
      "duration_ms": 15000,
      "status": "success",
      "concurrent_count": 3
    }
  ],
  "max_concurrency": 5,
  "avg_concurrency": 1.8
}
```

---

#### `GET /api/summarization`

Summarization statistics including acceptance rate.

**SQL:**

```sql
-- Summarization stats
SELECT
    COUNT(*) as total_events,
    SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END) as summarized_count,
    AVG(CASE WHEN was_summarized THEN CAST(summary_size AS FLOAT) / NULLIF(original_size, 0) END) as avg_compression_ratio,
    AVG(CASE WHEN was_summarized THEN original_size END) as avg_original_size,
    AVG(CASE WHEN was_summarized THEN summary_size END) as avg_summary_size
FROM events
{where}
```

```sql
-- Full content requests (rejections)
SELECT COUNT(*) as full_content_requests
FROM events
WHERE tool LIKE '%get_full%'
{and_where}
```

```sql
-- Summarization by agent role
SELECT
    CASE WHEN agent_id = session_id THEN 'main' ELSE 'subagent' END as agent_role,
    SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END) as summarized_count,
    COUNT(*) as total_events
FROM events
{where}
GROUP BY agent_role
```

```sql
-- Summarization over time
SELECT
    {period_group_expr} as period,
    SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END) as summarized_count,
    COUNT(*) as total_events
FROM events
{where}
GROUP BY period
ORDER BY period
```

**Response:**

```json
{
  "total_events": 19785,
  "summarized_count": 1171,
  "summarization_rate": 0.059,
  "full_content_requests": 67,
  "rejection_rate": 0.057,
  "avg_compression_ratio": 0.28,
  "avg_original_size": 8542,
  "avg_summary_size": 2000,
  "by_agent_role": [
    {"agent_role": "main", "summarized_count": 1170, "total_events": 14642},
    {"agent_role": "subagent", "summarized_count": 1, "total_events": 5154}
  ],
  "over_time": [
    {"period": "2026-01-09", "summarized_count": 45, "total_events": 523}
  ]
}
```

---

#### `GET /api/sessions?page=N&sort=tokens|errors|events|duration`

Paginated session list.

**SQL:**

```sql
SELECT
    session_id,
    MIN(timestamp) as start_time,
    MAX(timestamp) as end_time,
    COUNT(*) as event_count,
    SUM(input_tokens + output_tokens) as total_tokens,
    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
    COUNT(DISTINCT tool) as unique_tools,
    COUNT(DISTINCT CASE WHEN agent_id != session_id THEN agent_id END) as subagent_count,
    CAST((julianday(MAX(timestamp)) - julianday(MIN(timestamp))) * 86400000 AS INTEGER) as duration_ms
FROM events
{where}
GROUP BY session_id
ORDER BY {sort_column} DESC
LIMIT {limit} OFFSET {offset}
```

Page size is 50. Offset = `(page - 1) * 50`.

**Response:**

```json
{
  "page": 1,
  "total_sessions": 4268,
  "total_pages": 86,
  "sort": "tokens",
  "sessions": [
    {
      "session_id": "abc123",
      "start_time": "2026-01-15T10:30:00-05:00",
      "end_time": "2026-01-15T11:45:00-05:00",
      "event_count": 145,
      "total_tokens": 543210,
      "error_count": 3,
      "unique_tools": 12,
      "subagent_count": 4,
      "duration_ms": 4500000
    }
  ]
}
```

---

#### `GET /api/session/:id`

Single session detail.

**SQL:**

```sql
SELECT
    timestamp, tool, backend, status, duration_ms,
    agent_id, agent_type, input_tokens, output_tokens,
    cache_read_tokens, cache_creation_tokens,
    was_summarized, original_size, summary_size,
    error_type
FROM events
WHERE session_id = ?
ORDER BY timestamp
```

**Response:**

```json
{
  "session_id": "abc123",
  "events": [
    {
      "timestamp": "2026-01-15T10:30:00-05:00",
      "tool": "Read",
      "backend": "native",
      "status": "success",
      "duration_ms": 200,
      "agent_id": "abc123",
      "agent_type": "",
      "input_tokens": 10,
      "output_tokens": 200,
      "cache_read_tokens": 5000,
      "cache_creation_tokens": 0,
      "was_summarized": false,
      "original_size": 1500,
      "summary_size": null,
      "error_type": ""
    }
  ],
  "summary": {
    "total_events": 145,
    "total_tokens": 543210,
    "error_count": 3,
    "duration_ms": 4500000,
    "subagent_count": 4
  }
}
```

---

#### `GET /api/session/:id/replay`

Lazy-load conversation text from Claude's JSONL transcript for session replay.

**Server logic:** Search `jsonl_dir` recursively for a file matching the session_id (either `<session_id>.jsonl` or containing `sessionId` matching). Read the file, extract `user` and `assistant` entries with their text content and timestamps. Strip `tool_use` input details to keep payload small — include tool name and status but not the full input/output.

**Response:**

```json
{
  "session_id": "abc123",
  "messages": [
    {
      "timestamp": "2026-01-15T10:30:00-05:00",
      "role": "user",
      "text": "have a look at the architecture docs"
    },
    {
      "timestamp": "2026-01-15T10:30:05-05:00",
      "role": "assistant",
      "text": "Let me read those files.",
      "tool_calls": [
        {"tool": "Read", "status": "success"}
      ]
    }
  ]
}
```

If no matching JSONL file is found, return `{"session_id": "abc123", "messages": [], "error": "Transcript not found"}`.

---

#### `GET /api/compare?from_a=...&to_a=...&from_b=...&to_b=...`

Before/after comparison. Runs the `overview` query twice with different date ranges and returns both.

**Response:**

```json
{
  "range_a": { "from": "2026-01-09", "to": "2026-01-15", "data": { /* overview shape */ } },
  "range_b": { "from": "2026-01-20", "to": "2026-01-25", "data": { /* overview shape */ } },
  "deltas": {
    "total_events": 1234,
    "total_tokens_pct": -15.3,
    "error_rate_pct": -2.1,
    "avg_duration_ms_pct": -8.5
  }
}
```

`deltas` shows the change from range A to range B. Percentage fields end in `_pct`.

---

#### `GET /api/activity_heatmap`

Event counts by hour-of-day (EST) and day-of-week.

**SQL:**

```sql
SELECT
    CAST(strftime('%w', datetime(timestamp, '-5 hours')) AS INTEGER) as day_of_week,
    CAST(strftime('%H', datetime(timestamp, '-5 hours')) AS INTEGER) as hour_of_day,
    COUNT(*) as event_count
FROM events
{where}
GROUP BY day_of_week, hour_of_day
```

**Response:**

```json
{
  "data": [
    {"day": 0, "hour": 9, "count": 234},
    {"day": 0, "hour": 10, "count": 456}
  ]
}
```

`day`: 0=Sunday, 6=Saturday. `hour`: 0–23 in EST.

---

#### `GET /api/latency?group_by=tool`

Duration histogram.

**SQL:**

```sql
SELECT
    tool,
    COUNT(*) as call_count,
    AVG(duration_ms) as avg_ms,
    MIN(duration_ms) as min_ms,
    MAX(duration_ms) as max_ms,
    -- Histogram buckets: <100ms, 100-500ms, 500-1000ms, 1-5s, 5-30s, 30s+
    SUM(CASE WHEN duration_ms < 100 THEN 1 ELSE 0 END) as bucket_lt100,
    SUM(CASE WHEN duration_ms >= 100 AND duration_ms < 500 THEN 1 ELSE 0 END) as bucket_100_500,
    SUM(CASE WHEN duration_ms >= 500 AND duration_ms < 1000 THEN 1 ELSE 0 END) as bucket_500_1000,
    SUM(CASE WHEN duration_ms >= 1000 AND duration_ms < 5000 THEN 1 ELSE 0 END) as bucket_1s_5s,
    SUM(CASE WHEN duration_ms >= 5000 AND duration_ms < 30000 THEN 1 ELSE 0 END) as bucket_5s_30s,
    SUM(CASE WHEN duration_ms >= 30000 THEN 1 ELSE 0 END) as bucket_30s_plus
FROM events
{where}
GROUP BY tool
ORDER BY call_count DESC
LIMIT {limit}
```

**Response:**

```json
{
  "data": [
    {
      "tool": "Bash",
      "call_count": 3934,
      "avg_ms": 2341,
      "min_ms": 12,
      "max_ms": 120000,
      "histogram": {
        "<100ms": 523,
        "100-500ms": 1200,
        "500ms-1s": 800,
        "1-5s": 900,
        "5-30s": 400,
        "30s+": 111
      }
    }
  ]
}
```

---

#### `GET /api/errors?group_by=type|tool`

Error breakdown.

**SQL (group_by=type):**

```sql
SELECT
    error_type,
    COUNT(*) as count
FROM events
WHERE status = 'error' AND error_type != ''
{and_where}
GROUP BY error_type
ORDER BY count DESC
LIMIT {limit}
```

**SQL (group_by=tool):**

```sql
SELECT
    tool,
    COUNT(*) as error_count,
    (SELECT COUNT(*) FROM events e2 WHERE e2.tool = events.tool {and_where_inner}) as total_count,
    CAST(COUNT(*) AS FLOAT) / (SELECT COUNT(*) FROM events e2 WHERE e2.tool = events.tool {and_where_inner}) as error_rate
FROM events
WHERE status = 'error'
{and_where}
GROUP BY tool
ORDER BY error_count DESC
LIMIT {limit}
```

**Response (group_by=type):**

```json
{
  "group_by": "type",
  "data": [
    {"error_type": "FileNotFound", "count": 234},
    {"error_type": "PermissionDenied", "count": 123}
  ]
}
```

## 6. Frontend

### 6.1 File Structure

```
dashboard/static/
├── index.html      # Shell, nav, Alpine app root
├── app.js          # Alpine components, API client, Chart.js wrappers
├── style.css       # Dark theme
└── vendor/
    ├── alpine.3.14.3.min.js
    └── chart.4.4.7.min.js
```

### 6.2 index.html

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agent Swarm Dashboard</title>
    <link rel="stylesheet" href="/style.css">
    <script defer src="/vendor/alpine.3.14.3.min.js"></script>
    <script src="/vendor/chart.4.4.7.min.js"></script>
    <script src="/app.js"></script>
</head>
<body x-data="dashboard()" class="dark">
    <!-- Top bar -->
    <header>
        <h1>Agent Swarm Dashboard</h1>
        <div class="global-filters" x-data="globalFilters()">
            <input type="date" x-model="from" @change="applyFilters()">
            <input type="date" x-model="to" @change="applyFilters()">
            <button @click="toggleCompare()" :class="{ active: comparing }">Compare</button>
        </div>
    </header>

    <!-- Layout -->
    <div class="layout">
        <!-- Sidebar nav -->
        <nav>
            <a @click="view = 'overview'" :class="{ active: view === 'overview' }">Overview</a>
            <a @click="view = 'tokens'" :class="{ active: view === 'tokens' }">Tokens</a>
            <a @click="view = 'concurrency'" :class="{ active: view === 'concurrency' }">Concurrency</a>
            <a @click="view = 'tools'" :class="{ active: view === 'tools' }">Tools & Errors</a>
            <a @click="view = 'summarization'" :class="{ active: view === 'summarization' }">Summarization</a>
            <a @click="view = 'sessions'" :class="{ active: view === 'sessions' }">Sessions</a>
        </nav>

        <!-- Main content -->
        <main>
            <div x-show="view === 'overview'" x-data="overviewView()"><!-- ... --></div>
            <div x-show="view === 'tokens'" x-data="tokensView()"><!-- ... --></div>
            <div x-show="view === 'concurrency'" x-data="concurrencyView()"><!-- ... --></div>
            <div x-show="view === 'tools'" x-data="toolsView()"><!-- ... --></div>
            <div x-show="view === 'summarization'" x-data="summarizationView()"><!-- ... --></div>
            <div x-show="view === 'sessions'" x-data="sessionsView()"><!-- ... --></div>
        </main>
    </div>
</body>
</html>
```

### 6.3 Alpine Components

Each view is an Alpine component that:
1. Holds local filter state (overrides global filters)
2. Fetches data from the API on mount and when filters change
3. Renders Chart.js charts into `<canvas>` elements

**API client helper:**

```javascript
// In app.js
async function api(endpoint, params = {}) {
    const qs = new URLSearchParams(params).toString();
    const url = qs ? `/api/${endpoint}?${qs}` : `/api/${endpoint}`;
    const res = await fetch(url);
    return res.json();
}
```

**Chart wrapper helper:**

```javascript
function renderChart(canvasId, type, data, options = {}) {
    const canvas = document.getElementById(canvasId);
    if (canvas._chart) canvas._chart.destroy();
    canvas._chart = new Chart(canvas, {
        type,
        data,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { labels: { color: '#ccc' } } },
            scales: {
                x: { ticks: { color: '#999' }, grid: { color: '#333' } },
                y: { ticks: { color: '#999' }, grid: { color: '#333' } }
            },
            ...options
        }
    });
}
```

**Per-chart controls pattern:**

```html
<div class="chart-card">
    <div class="chart-controls">
        <select x-model="localPeriod" @change="refresh()">
            <option value="hour">Hour</option>
            <option value="day" selected>Day</option>
            <option value="week">Week</option>
            <option value="month">Month</option>
        </select>
        <select x-model="localTool" @change="refresh()">
            <option value="">All Tools</option>
            <!-- populated from /api/tools -->
        </select>
        <input type="number" x-model="localLimit" @change="refresh()" min="5" max="100" placeholder="Limit">
    </div>
    <canvas id="chart-id" height="300"></canvas>
</div>
```

### 6.4 View Specifications

**Overview View** — 4 chart cards:
1. Sessions over time (line) — `/api/tokens?group_by=day` → plot `event_count`
2. Token spend (stacked area) — `/api/tokens?group_by=day` → stack input/output/cache_read/cache_creation
3. Success/error rate (line) — `/api/tokens?group_by=day` + `/api/errors` → compute rates
4. Activity heatmap (matrix) — `/api/activity_heatmap` → Chart.js matrix plugin or custom canvas

**Tokens View** — 4 chart cards:
1. Token spend per session (bar) — `/api/sessions?sort=tokens&limit=20`
2. Tokens by tool (horizontal bar) — `/api/tokens?group_by=tool`
3. Cache efficiency over time (line) — `/api/tokens?group_by=day` → compute `cache_read / (cache_read + input)`
4. Tokens by agent role (pie/doughnut) — `/api/tokens?group_by=agent`

**Concurrency View** — 3 chart cards:
1. Session selector dropdown → `/api/sessions?sort=events&limit=50`
2. Timeline (horizontal bar / gantt-like) — `/api/concurrency?session=X` → draw overlapping bars
3. Concurrency stats — max, avg concurrent events

**Tools & Errors View** — 4 chart cards:
1. Tool frequency (horizontal bar) — `/api/tools?sort=count`
2. Error rate by tool (horizontal bar) — `/api/tools?sort=errors`
3. Error type breakdown (pie) — `/api/errors?group_by=type`
4. Native vs MCP comparison (grouped bar) — `/api/tools` → group by backend prefix

**Summarization View** — 4 chart cards:
1. Summarization rate over time (line) — `/api/summarization` → `over_time`
2. Acceptance rate (gauge/number) — `/api/summarization` → `rejection_rate`
3. Compression ratio distribution (histogram) — needs per-event data, use `/api/session/:id` for drilldown
4. By agent role (grouped bar) — `/api/summarization` → `by_agent_role`

**Sessions View** — table + detail panel:
1. Paginated table — `/api/sessions`
2. Click row → detail panel showing timeline from `/api/session/:id`
3. "Replay" button → loads `/api/session/:id/replay` and shows conversation

### 6.5 Dark Theme

```css
/* dashboard/static/style.css */
:root {
    --bg-primary: #1a1a2e;
    --bg-secondary: #16213e;
    --bg-card: #1e2a4a;
    --text-primary: #e0e0e0;
    --text-secondary: #999;
    --accent: #4fc3f7;
    --error: #ef5350;
    --success: #66bb6a;
    --border: #2a3a5e;
}

body.dark {
    background: var(--bg-primary);
    color: var(--text-primary);
    font-family: 'SF Mono', 'Fira Code', monospace;
    margin: 0;
}

/* ... full CSS to be implemented following these variables */
```

## 7. Directory Structure

```
dashboard/
├── server.py                  # HTTP server + API routing
├── import.py                  # DuckDB/Claude transcript → SQLite import
├── providers/
│   ├── __init__.py            # DataProvider protocol
│   ├── sqlite.py              # SqliteProvider implementation
│   ├── mock.py                # MockProvider implementation
│   └── filters.py             # Shared filter/SQL builder utilities
├── static/
│   ├── index.html             # Shell + Alpine component structure
│   ├── app.js                 # Alpine components, API client, Chart.js rendering
│   ├── style.css              # Dark theme
│   └── vendor/
│       ├── alpine.3.14.3.min.js
│       └── chart.4.4.7.min.js
├── data/                      # .gitignored, holds dashboard.db after import
│   └── .gitkeep
├── tests/
│   ├── test_import.py         # Import script tests
│   ├── test_sqlite_provider.py # Provider query tests
│   ├── test_mock_provider.py  # Mock data shape validation
│   ├── test_filters.py        # Filter builder tests
│   └── test_server.py         # API endpoint integration tests
├── requirements.txt           # duckdb (import only)
└── .gitignore                 # data/*.db
```

## 8. Usage

```bash
# First time: import historical data
cd agent-swarm
python dashboard/import.py \
    --db dashboard/data/dashboard.db \
    --duckdb .state/telemetry.duckdb \
    --claude-projects ~/.claude/projects/

# Run dashboard
python dashboard/server.py \
    --db dashboard/data/dashboard.db \
    --port 8080

# Dev with mock data (no database needed)
python dashboard/server.py --mock --port 8080

# Re-import (incremental, skips already-imported files)
python dashboard/import.py \
    --db dashboard/data/dashboard.db \
    --claude-projects ~/.claude/projects/
```

## 9. Testing Strategy

Each task in the implementation plan includes specific tests. General approach:

- **Import tests:** Create temp SQLite DB, import from fixture JSONL files and a small DuckDB fixture. Verify event counts, deduplication, import_source flags.
- **Provider tests:** Use an in-memory SQLite DB seeded with known events. Verify each provider method returns correct shapes and values.
- **Filter tests:** Unit tests for `build_where()` and `period_group_expr()`. Verify EST→UTC conversion.
- **Mock tests:** Verify MockProvider returns same JSON shapes as SqliteProvider.
- **Server tests:** Use `unittest` with `HTTPServer` on a random port. Hit each endpoint, verify 200 status and JSON shape.
- **No frontend tests** — manual verification via browser.
