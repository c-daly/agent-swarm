# Dashboard Design

**Date**: 2026-01-31
**Status**: Draft
**Branch**: feature/architecture-refactor-design

## Purpose

A standalone, shareable dashboard for measuring whether changes to prompts, workflows, configs, and system structure are working. Serves three roles:

1. **Experimentation** — compare before/after metrics across any change
2. **Observability** — see what agents are doing, where tokens go, how concurrency works
3. **Token accounting** — real token usage (not estimates), broken down by tool, agent, session

## Architecture Overview

Three layers:

1. **Python server** (`server.py`) — single-file HTTP server using stdlib (`http.server`, `sqlite3`, `json`). Serves static files and REST API endpoints.

2. **Data provider interface** — abstract layer with three implementations:
   - `SqliteProvider` — reads the daemon's SQLite DataStore (primary, post-refactor)
   - `DuckDbProvider` — reads the existing DuckDB data (for import)
   - `MockProvider` — generates synthetic data using the same interface; dashboard doesn't know the difference

3. **Static web frontend** — HTML + Alpine.js + Chart.js. No build step, no npm. Dark theme.

### Data Flow

```
Browser → Python HTTP API → Provider interface → SQLite (or Mock) → JSON → Chart.js
```

### JSONL Integration

Session replay is lazy-loaded. When a user drills into a specific session, the server reads the matching JSONL file on demand and returns conversation events. Conversation text is not duplicated into SQLite.

### Live State (future)

Optional polling endpoint that proxies the daemon's JSON-RPC API for active agent status. Secondary to historical analysis.

## Dashboard Views

### Overview
- Session count over time (line chart)
- Token spend breakdown: input vs output vs cache_read vs cache_creation (stacked area)
- Success/error rate trend (line chart)
- Active period heatmap (hour-of-day x day-of-week)

### Token Analysis
- Total token spend per session (bar chart, sortable)
- Token distribution by tool (which tools consume the most tokens)
- Cache efficiency: cache_read / (cache_read + input_tokens) over time
- Token spend by agent_type (main vs subagents)

### Concurrency & Performance
- Overlapping tool calls per session (derived from timestamp + duration_ms)
- Agent parallelism: concurrent subagent count over time within sessions
- Tool latency distribution (histogram by tool)
- Backend serialization: per-backend throughput showing where work queues up

### Tool Use & Errors
- Tool frequency (bar chart, filterable by time range)
- Error rate by tool (which tools fail most)
- Error type breakdown
- Native vs MCP tool comparison

### Summarization & Context
- Summarization rate over time
- Summary acceptance rate (accepted vs requested full content via `get_full`)
- Compression ratio distribution (summary_size / original_size)
- Token savings: summarized vs non-summarized events
- Per-agent-type summary acceptance patterns
- Content retrieval patterns

**Note**: Current data shows 1,171 summarized events (6% of all), 67 full-content fetches (6% rejection rate). All summarization currently applies to main agent only — subagent tool calls bypass the controller pre-refactor. Post-refactor, all calls route through the controller and summarization data will be complete.

### Session Explorer
- Searchable session list with summary stats (tokens, duration, tool count, errors)
- Drill into session: timeline view of tool calls with duration bars
- Lazy-load conversation text from JSONL for session replay

### Comparison (Experimentation)
- Select two date ranges for before/after analysis
- Side-by-side charts for any metric

## Chart Controls

Every chart supports:

| Param | Type | Description |
|---|---|---|
| `from`, `to` | datetime | Date range (EST) |
| `period` | string | hour, day, week, month |
| `tool` | string | Comma-separated tool filter |
| `backend` | string | Comma-separated backend filter |
| `agent_type` | string | main, subagent, or specific type |
| `status` | string | success, error |
| `session` | string | Specific session ID |
| `sort` | string | Dimension to sort by |
| `limit` | int | Max results |

Changing a filter re-fetches the API and re-renders the chart without full page reload.

## Data Layer

### SQLite as Canonical Store

The dashboard reads one SQLite database. Three ways data gets there:

1. **Daemon writes directly** (post-refactor) — every tool call, summarization event, content retrieval recorded via DataStore.
2. **DuckDB import** — one-time migration of existing 19,785 events with full column fidelity.
3. **JSONL import** — batch import of 511 session files, deduped against DuckDB data.

### Schema

Events table (matches `lib/datastore.py`):

| Column | Type | Notes |
|---|---|---|
| id | INTEGER | Primary key |
| timestamp | TIMESTAMP | UTC in storage, EST on output |
| session_id | VARCHAR | |
| agent_id | VARCHAR | |
| tool | VARCHAR | |
| backend | VARCHAR | |
| duration_ms | INTEGER | |
| status | VARCHAR | success, error |
| input_tokens | INTEGER | |
| output_tokens | INTEGER | |
| cache_read_tokens | INTEGER | |
| cache_creation_tokens | INTEGER | |
| agent_type | VARCHAR | NULL for JSONL-imported events |
| workflow_id | VARCHAR | NULL for JSONL-imported events |
| error_type | VARCHAR | |
| was_summarized | BOOLEAN | NULL for JSONL-imported events |
| original_size | INTEGER | NULL for JSONL-imported events |
| summary_size | INTEGER | NULL for JSONL-imported events |

Additional tables:
- `content_retrievals` — content_id, created_at, retrieved_at, was_retrieved
- `agent_types` — agent_id, agent_type, registered_at
- `import_log` — source, timestamp, row counts (prevents duplicate imports)

Views:
- `sessions` — aggregates per-session: total tokens, event count, error count, duration, summarization count
- `turns` — clusters events by timestamp gaps (>5s gap = new turn)

### Import Strategy

DuckDB is authoritative for events it contains. Import order:

1. DuckDB → SQLite (all events, full columns)
2. JSONL → SQLite (only events not already present, dedup by `(timestamp, session_id, agent_id, tool)`)
3. Log import metadata so it's not re-run accidentally

### Mock Provider

- Generates realistic synthetic data matching real distributions
- Deterministic with seed for reproducible testing
- Same interface as SqliteProvider — returns identical JSON shapes
- Supports all filter params
- Never touches SQLite

## Server & API

Single file `server.py`, stdlib only. Configured via CLI args:

```
python server.py --db /path/to/datastore.db --jsonl /path/to/telemetry_v3/ --port 8080
python server.py --mock --port 8080
```

### Endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/overview` | Top-line stats: sessions, events, tokens, error rate, date range |
| `GET /api/tokens?group_by=tool\|agent\|day` | Token breakdown by dimension |
| `GET /api/tools?sort=count\|errors\|tokens` | Tool usage stats |
| `GET /api/concurrency?session=X` | Overlapping events for a session |
| `GET /api/summarization` | Summarization stats, acceptance rate |
| `GET /api/sessions?page=N&sort=tokens\|errors` | Paginated session list |
| `GET /api/session/:id` | Single session detail |
| `GET /api/session/:id/replay` | JSONL conversation replay (lazy-loaded) |
| `GET /api/compare?a=daterange&b=daterange` | Before/after comparison |
| `GET /api/activity_heatmap` | Hour x day-of-week event counts |
| `GET /api/latency?group_by=tool` | Duration histogram buckets |
| `GET /api/errors?group_by=type\|tool` | Error breakdown |

All endpoints accept common filter params (from, to, period, tool, backend, agent_type, status, session, sort, limit). All timestamps returned in EST.

## Frontend

Single-page app, no build step:

- **`index.html`** — Shell with nav sidebar, main content area. Loads Alpine.js and Chart.js from CDN.
- **`app.js`** — Alpine.js components, one per view. Each fetches its API endpoint on mount, feeds data to Chart.js.
- **`style.css`** — Dark theme.

### Layout
- Left sidebar: nav links (Overview, Tokens, Concurrency, Tools & Errors, Summarization, Sessions)
- Top bar: global date range picker, comparison mode toggle
- Main area: chart grid for active view

### Interaction
- Date range picker filters all charts on the current view
- Click session in any chart → drills into Session Explorer
- Click tool name → filters to that tool across views
- Comparison mode: select two date ranges, charts show side-by-side
- Per-chart controls for time period, filters, sort, limit

## Repo Structure

```
agent-swarm-dashboard/
├── server.py              # HTTP server + REST API + static file serving
├── import.py              # DuckDB/JSONL → SQLite migration
├── providers/
│   ├── __init__.py        # DataProvider protocol/interface
│   ├── sqlite.py          # SqliteProvider
│   ├── duckdb.py          # DuckDbProvider (for import)
│   └── mock.py            # MockProvider
├── static/
│   ├── index.html         # Shell + Alpine components
│   ├── app.js             # Chart components, routing, filter state
│   ├── style.css          # Dark theme
│   └── vendor/            # Local fallback copies of Alpine.js, Chart.js
├── README.md
├── requirements.txt       # duckdb (import only), stdlib otherwise
└── .gitignore
```

### Dependencies
- **Runtime**: Python 3.10+ stdlib only (sqlite3, http.server, json, pathlib)
- **Import only**: `duckdb` pip package
- **Frontend**: Alpine.js + Chart.js from CDN, vendor fallbacks checked in

## Current Data State

As of 2026-01-31:

| Source | Size | Events | Notes |
|---|---|---|---|
| DuckDB (main) | 997MB | 19,785 | Jan 9-31, full columns, authoritative |
| DuckDB (v3) | 268K | 0 | Empty, schema only |
| JSONL files | 5.8MB | ~511 files | Raw v3 telemetry, basic fields only |
| SQLite (daemon) | — | — | Not yet instantiated in production |

Key stats from existing data:
- 4,268 distinct sessions
- 5,154 subagent events (26% of total)
- 1.9M input tokens, 1.7M output tokens, 1.5B cache_read tokens
- 1,171 summarized events (6%), 67 full-content requests (6% rejection)
- 17,341 success / 2,446 errors
- 181 distinct tools, 6 backends, 72 error types
