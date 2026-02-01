"""SQLite-backed data provider for the dashboard."""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .filters import build_where, period_group_expr


_ERROR_PATTERNS = [
    ('Timeout waiting for serena', 'Serena Timeout'),
    ('Timeout waiting for native', 'Native Timeout'),
    ('Timeout waiting for', 'MCP Timeout'),
    ('No active project', 'No Active Project'),
    ('[BLOCKED]', 'Hook Blocked'),
    ('PreToolUse:', 'Hook Blocked'),
    ('No such tool available', 'Tool Not Available'),
    ('unknown command', 'Unknown Command'),
    ('Exit code', 'Non-Zero Exit Code'),
    ('exit code', 'Non-Zero Exit Code'),
    ('test session starts', 'Test Failure'),
    ('FAILED', 'Test Failure'),
    ('ModuleNotFoundError', 'Import Error'),
    ('ImportError', 'Import Error'),
    ('FileNotFoundError', 'File Not Found'),
    ('PermissionError', 'Permission Denied'),
    ('ConnectionRefusedError', 'Connection Refused'),
    ('JSONDecodeError', 'JSON Parse Error'),
    ('SyntaxError', 'Syntax Error'),
    ('TypeError', 'Type Error'),
    ('ValueError', 'Value Error'),
    ('KeyError', 'Key Error'),
    ('AttributeError', 'Attribute Error'),
    ('IndexError', 'Index Error'),
    ('RuntimeError', 'Runtime Error'),
    ('OSError', 'OS Error'),
    ('Traceback (most recent call last)', 'Python Traceback'),
    ('retrieval_status', 'Retrieval Status'),
    ('persisted-output', 'Persisted Output'),
    ('Whisper not available', 'Missing Dependency'),
    ('Defaulting to user installation', 'Pip Install Warning'),
    ('Dashboard generated', 'Dashboard Output'),
    ('#!/usr/bin/env python', 'File Content (not error)'),
    ('parentUuid', 'Raw JSON Response'),
    ('jsonrpc', 'Raw JSON Response'),
    ('{"result":', 'Raw Tool Result'),
    ('[{"url":', 'Raw API Response'),
    ('## Documentation', 'Markdown Content'),
    ('# Hooks reference', 'Markdown Content'),
    ('# Workflow', 'Markdown Content'),
    ('# Router', 'Markdown Content'),
    ('### Result', 'Markdown Content'),
    ('The file /home/', 'File Read Error'),
    ('has no ', 'Type Check Error'),
    ('"""', 'File Content (not error)'),
    ('result (', 'Result Too Large'),
    ('{"url":', 'Raw API Response'),
    ('{"content":', 'Raw Content Response'),
    ('TTS not available', 'Missing Dependency'),
    ('usage:', 'CLI Usage Error'),
    ('unknown flag', 'Unknown CLI Flag'),
    ('HANDOFF', 'Handoff Document'),
    ('# Agent Instructions', 'Markdown Content'),
    ('# Plugins reference', 'Markdown Content'),
    ('# Apollo', 'Markdown Content'),
    ('# Integration', 'Markdown Content'),
    ('# Subagent', 'Markdown Content'),
    ('Name: anyio', 'Pip Package Info'),
    ('def main():', 'File Content (not error)'),
    ('INTAKE ->', 'Workflow State'),
    ('Error:', 'Generic Error'),
    ('→', 'File Content (not error)'),
    ('=====', 'Test Output'),
]


def _normalize_error_type(raw: str) -> str:
    if not raw:
        return 'Unknown'
    for pattern, label in _ERROR_PATTERNS:
        if pattern.lower() in raw.lower():
            return label
    # Truncate to first meaningful line
    first_line = raw.split('\n')[0].strip()[:60]
    if first_line:
        return first_line
    return 'Unknown'


class SqliteProvider:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")

    def _query(self, sql: str, params: list | None = None) -> list[dict]:
        rows = self._conn.execute(sql, params or []).fetchall()
        return [dict(r) for r in rows]

    def _query_one(self, sql: str, params: list | None = None) -> dict:
        row = self._conn.execute(sql, params or []).fetchone()
        return dict(row) if row else {}

    # -- health (not in protocol, but used by server) --

    def health(self) -> dict:
        stats = self._query_one(
            "SELECT COUNT(*) as total_events, COUNT(DISTINCT session_id) as total_sessions, "
            "MIN(timestamp) as first_event, MAX(timestamp) as last_event FROM events"
        )
        imports = self._query(
            "SELECT source, MAX(imported_at) as last_import, SUM(events_inserted) as total_inserted "
            "FROM import_log GROUP BY source"
        )
        db_size = os.path.getsize(self._db_path) if os.path.exists(self._db_path) else 0
        return {
            "status": "ok",
            "db_path": self._db_path,
            "db_size_bytes": db_size,
            "total_events": stats.get("total_events", 0),
            "total_sessions": stats.get("total_sessions", 0),
            "first_event": stats.get("first_event", ""),
            "last_event": stats.get("last_event", ""),
            "imports": imports,
        }

    # -- DataProvider protocol methods --

    def overview(self, filters: dict) -> dict:
        where, params = build_where(filters)
        row = self._query_one(
            f"SELECT COUNT(*) as total_events, COUNT(DISTINCT session_id) as total_sessions, "
            f"SUM(input_tokens) as total_input, SUM(output_tokens) as total_output, "
            f"SUM(cache_read_tokens) as total_cache_read, SUM(cache_creation_tokens) as total_cache_creation, "
            f"SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as total_errors, "
            f"MIN(timestamp) as first_event, MAX(timestamp) as last_event, "
            f"AVG(duration_ms) as avg_duration_ms, "
            f"SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END) as total_summarized, "
            f"COUNT(DISTINCT tool) as unique_tools, "
            f"COUNT(DISTINCT CASE WHEN agent_id != session_id THEN agent_id END) as subagent_count "
            f"FROM events {where}",
            params,
        )
        total = row.get("total_events", 0) or 0
        errors = row.get("total_errors", 0) or 0
        return {
            "total_events": total,
            "total_sessions": row.get("total_sessions", 0) or 0,
            "total_input_tokens": row.get("total_input", 0) or 0,
            "total_output_tokens": row.get("total_output", 0) or 0,
            "total_cache_read": row.get("total_cache_read", 0) or 0,
            "total_cache_creation": row.get("total_cache_creation", 0) or 0,
            "total_errors": errors,
            "error_rate": round(errors / total, 3) if total else 0,
            "first_event": row.get("first_event", ""),
            "last_event": row.get("last_event", ""),
            "avg_duration_ms": round(row.get("avg_duration_ms", 0) or 0, 1),
            "total_summarized": row.get("total_summarized", 0) or 0,
            "unique_tools": row.get("unique_tools", 0) or 0,
            "subagent_count": row.get("subagent_count", 0) or 0,
        }

    def tokens(self, filters: dict) -> dict:
        group_by = filters.pop("group_by", "day")
        limit = int(filters.pop("limit", 50))
        where, params = build_where(filters)
        period = filters.get("period", "day")

        if group_by == "tool":
            rows = self._query(
                f"SELECT tool, SUM(input_tokens + output_tokens) as total_tokens, "
                f"SUM(input_tokens) as input, SUM(output_tokens) as output, "
                f"SUM(cache_read_tokens) as cache_read, SUM(cache_creation_tokens) as cache_creation, "
                f"COUNT(*) as event_count FROM events {where} "
                f"GROUP BY tool ORDER BY total_tokens DESC LIMIT ?",
                params + [limit],
            )
            return {"group_by": "tool", "data": rows}

        elif group_by == "agent":
            rows = self._query(
                f"SELECT CASE "
                f"  WHEN agent_id = session_id THEN 'main' "
                f"  WHEN agent_type != '' THEN agent_type "
                f"  ELSE 'subagent (legacy)' "
                f"END as agent_role, "
                f"SUM(input_tokens) as input, SUM(output_tokens) as output, "
                f"SUM(cache_read_tokens) as cache_read, SUM(cache_creation_tokens) as cache_creation, "
                f"COUNT(*) as event_count FROM events {where} GROUP BY agent_role "
                f"ORDER BY (SUM(input_tokens) + SUM(output_tokens)) DESC",
                params,
            )
            return {"group_by": "agent", "data": rows}

        else:
            pge = period_group_expr(period)
            rows = self._query(
                f"SELECT {pge} as period, SUM(input_tokens) as input, SUM(output_tokens) as output, "
                f"SUM(cache_read_tokens) as cache_read, SUM(cache_creation_tokens) as cache_creation, "
                f"COUNT(*) as event_count FROM events {where} GROUP BY period ORDER BY period",
                params,
            )
            return {"group_by": group_by, "period": period, "data": rows}

    def tools(self, filters: dict) -> dict:
        sort = filters.pop("sort", "count")
        limit = int(filters.pop("limit", 50))
        where, params = build_where(filters)

        sort_map = {"count": "call_count", "errors": "error_count", "tokens": "total_tokens"}
        sort_col = sort_map.get(sort, "call_count")

        rows = self._query(
            f"SELECT tool, COUNT(*) as call_count, "
            f"SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count, "
            f"CAST(SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*) as error_rate, "
            f"SUM(input_tokens + output_tokens) as total_tokens, "
            f"AVG(duration_ms) as avg_duration_ms, "
            f"SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END) as summarized_count "
            f"FROM events {where} GROUP BY tool ORDER BY {sort_col} DESC LIMIT ?",
            params + [limit],
        )
        for r in rows:
            r["error_rate"] = round(r.get("error_rate", 0) or 0, 3)
            r["avg_duration_ms"] = round(r.get("avg_duration_ms", 0) or 0, 1)
        return {"sort": sort, "data": rows}

    def concurrency(self, filters: dict) -> dict:
        session_id = filters.get("session", "")
        if not session_id:
            return self._concurrency_aggregate(filters)

        rows = self._query(
            "SELECT timestamp, tool, agent_id, duration_ms, status "
            "FROM events WHERE session_id = ? ORDER BY timestamp",
            [session_id],
        )

        events = []
        for r in rows:
            ts = r["timestamp"]
            dur = r.get("duration_ms", 0) or 0
            try:
                start = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                end = start + timedelta(milliseconds=dur)
            except (ValueError, TypeError):
                start = end = None
            events.append({**r, "_start": start, "_end": end})

        for i, evt in enumerate(events):
            if evt["_start"] is None:
                evt["concurrent_count"] = 0
                continue
            count = 0
            for j, other in enumerate(events):
                if i == j or other["_start"] is None:
                    continue
                if other["_start"] < evt["_end"] and other["_end"] > evt["_start"]:
                    count += 1
            evt["concurrent_count"] = count

        result_events = []
        for evt in events:
            del evt["_start"]
            del evt["_end"]
            result_events.append(evt)

        concurrencies = [e["concurrent_count"] for e in result_events]
        max_c = max(concurrencies) if concurrencies else 0
        avg_c = round(sum(concurrencies) / len(concurrencies), 1) if concurrencies else 0

        return {
            "session_id": session_id,
            "events": result_events,
            "max_concurrency": max_c,
            "avg_concurrency": avg_c,
        }

    def _concurrency_aggregate(self, filters: dict) -> dict:
        where, params = build_where(filters)
        period = filters.get("period", "day")
        pge = period_group_expr(period)

        # Subagent spawning per session
        sessions = self._query(
            f"SELECT session_id, COUNT(DISTINCT agent_id) as num_agents, "
            f"COUNT(DISTINCT CASE WHEN agent_id != session_id THEN agent_id END) as num_subagents, "
            f"COUNT(*) as event_count, "
            f"SUM(input_tokens + output_tokens) as total_tokens, "
            f"MIN(timestamp) as start_time, "
            f"MAX(timestamp) as end_time "
            f"FROM events {where} "
            f"GROUP BY session_id HAVING num_subagents > 0 "
            f"ORDER BY num_subagents DESC",
            params,
        )

        # Top sessions (limit 20 for display)
        top_sessions = sessions[:20]

        # Distribution histogram: how many sessions had N subagents
        dist = {}
        for s in sessions:
            n = s["num_subagents"]
            bucket = str(n) if n <= 10 else "11-20" if n <= 20 else "21-50" if n <= 50 else "50+"
            dist[bucket] = dist.get(bucket, 0) + 1

        # Subagents spawned per period
        and_clause = "AND agent_id != session_id" if where else "WHERE agent_id != session_id"
        over_time = self._query(
            f"SELECT {pge} as period, "
            f"COUNT(DISTINCT CASE WHEN agent_id != session_id THEN agent_id END) as subagents_spawned, "
            f"COUNT(DISTINCT session_id) as sessions_with_subagents, "
            f"COUNT(*) as subagent_events "
            f"FROM events {where} {and_clause} "
            f"GROUP BY period ORDER BY period",
            params,
        )

        # Agent type breakdown
        by_type = self._query(
            f"SELECT CASE "
            f"  WHEN agent_type != '' THEN agent_type "
            f"  ELSE 'legacy (pre-tracking)' "
            f"END as agent_type, "
            f"COUNT(DISTINCT agent_id) as agent_count, "
            f"COUNT(*) as event_count, "
            f"SUM(input_tokens + output_tokens) as total_tokens "
            f"FROM events {where} {and_clause} "
            f"GROUP BY agent_type ORDER BY agent_count DESC",
            params,
        )

        return {
            "mode": "aggregate",
            "total_sessions_with_subagents": len(sessions),
            "total_subagents_spawned": sum(s["num_subagents"] for s in sessions),
            "top_sessions": top_sessions,
            "distribution": dist,
            "over_time": over_time,
            "by_type": by_type,
        }

    def summarization(self, filters: dict) -> dict:
        where, params = build_where(filters)
        period = filters.get("period", "day")

        stats = self._query_one(
            f"SELECT COUNT(*) as total_events, "
            f"SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END) as summarized_count, "
            f"AVG(CASE WHEN was_summarized THEN CAST(summary_size AS FLOAT) / NULLIF(original_size, 0) END) as avg_compression_ratio, "
            f"AVG(CASE WHEN was_summarized THEN original_size END) as avg_original_size, "
            f"AVG(CASE WHEN was_summarized THEN summary_size END) as avg_summary_size, "
            f"SUM(CASE WHEN was_summarized THEN original_size ELSE 0 END) as total_original_size, "
            f"SUM(CASE WHEN was_summarized THEN summary_size ELSE 0 END) as total_summary_size "
            f"FROM events {where}",
            params,
        )

        # Full content requests
        and_where = where.replace("WHERE ", "AND ") if where else ""
        fcr = self._query_one(
            f"SELECT COUNT(*) as full_content_requests FROM events "
            f"WHERE tool LIKE '%get_full%' {and_where}",
            params,
        )

        # get_full rate scoped to period where get_full was available
        gf_first = self._query_one(
            "SELECT MIN(timestamp) as t FROM events WHERE tool LIKE '%get_full%'",
            [],
        )
        gf_since = gf_first.get("t") or ""
        if gf_since:
            gf_scoped = self._query_one(
                f"SELECT COUNT(*) as summaries_since "
                f"FROM events WHERE was_summarized = 1 AND timestamp >= ? {and_where}",
                [gf_since] + list(params),
            )
            summaries_since_gf = gf_scoped.get("summaries_since", 0) or 0
        else:
            summaries_since_gf = 0

        # By agent role (with actual agent_type)
        by_role = self._query(
            f"SELECT CASE "
            f"  WHEN agent_id = session_id THEN 'main' "
            f"  WHEN agent_type != '' THEN agent_type "
            f"  ELSE 'subagent (legacy)' "
            f"END as agent_role, "
            f"SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END) as summarized_count, "
            f"COUNT(*) as total_events, "
            f"SUM(CASE WHEN was_summarized THEN original_size ELSE 0 END) as total_original, "
            f"SUM(CASE WHEN was_summarized THEN summary_size ELSE 0 END) as total_summary "
            f"FROM events {where} GROUP BY agent_role ORDER BY summarized_count DESC",
            params,
        )

        # Over time with compression ratio and token savings
        pge = period_group_expr(period)
        over_time = self._query(
            f"SELECT {pge} as period, "
            f"SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END) as summarized_count, "
            f"COUNT(*) as total_events, "
            f"SUM(CASE WHEN was_summarized THEN original_size ELSE 0 END) as original_size, "
            f"SUM(CASE WHEN was_summarized THEN summary_size ELSE 0 END) as summary_size, "
            f"AVG(CASE WHEN was_summarized THEN CAST(summary_size AS FLOAT) / NULLIF(original_size, 0) END) as compression_ratio "
            f"FROM events {where} GROUP BY period ORDER BY period",
            params,
        )

        # Top tools by summarization
        by_tool = self._query(
            f"SELECT tool, "
            f"SUM(CASE WHEN was_summarized THEN 1 ELSE 0 END) as summarized_count, "
            f"COUNT(*) as total_events, "
            f"AVG(CASE WHEN was_summarized THEN CAST(summary_size AS FLOAT) / NULLIF(original_size, 0) END) as avg_compression, "
            f"SUM(CASE WHEN was_summarized THEN original_size - summary_size ELSE 0 END) as bytes_saved "
            f"FROM events {where} "
            f"GROUP BY tool HAVING summarized_count > 0 "
            f"ORDER BY summarized_count DESC LIMIT 20",
            params,
        )
        for r in by_tool:
            r["avg_compression"] = round(r.get("avg_compression", 0) or 0, 2)

        total = stats.get("total_events", 0) or 0
        summarized = stats.get("summarized_count", 0) or 0
        full_reqs = fcr.get("full_content_requests", 0) or 0
        effective = summarized - full_reqs
        total_orig = stats.get("total_original_size", 0) or 0
        total_summ = stats.get("total_summary_size", 0) or 0
        gf_rate = round(full_reqs / summaries_since_gf, 3) if summaries_since_gf else None

        return {
            "total_events": total,
            "summarized_count": summarized,
            "summarization_rate": round(summarized / total, 3) if total else 0,
            "full_content_requests": full_reqs,
            "effective_summarized": effective,
            "rejection_rate": round(full_reqs / summarized, 3) if summarized else 0,
            "get_full_rate": gf_rate,
            "get_full_since": gf_since or None,
            "summaries_since_get_full": summaries_since_gf,
            "avg_compression_ratio": round(stats.get("avg_compression_ratio", 0) or 0, 2),
            "avg_original_size": round(stats.get("avg_original_size", 0) or 0, 0),
            "avg_summary_size": round(stats.get("avg_summary_size", 0) or 0, 0),
            "total_original_size": total_orig,
            "total_summary_size": total_summ,
            "total_bytes_saved": total_orig - total_summ,
            "by_agent_role": by_role,
            "over_time": over_time,
            "by_tool": by_tool,
        }

    def sessions(self, filters: dict) -> dict:
        page = int(filters.pop("page", 1))
        sort = filters.pop("sort", "tokens")
        limit = 50
        offset = (page - 1) * limit
        where, params = build_where(filters)

        sort_map = {
            "tokens": "total_tokens",
            "errors": "error_count",
            "events": "event_count",
            "duration": "duration_ms",
        }
        sort_col = sort_map.get(sort, "total_tokens")

        rows = self._query(
            f"SELECT session_id, MIN(timestamp) as start_time, MAX(timestamp) as end_time, "
            f"COUNT(*) as event_count, SUM(input_tokens + output_tokens) as total_tokens, "
            f"SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count, "
            f"COUNT(DISTINCT tool) as unique_tools, "
            f"COUNT(DISTINCT CASE WHEN agent_id != session_id THEN agent_id END) as subagent_count, "
            f"CAST((julianday(MAX(timestamp)) - julianday(MIN(timestamp))) * 86400000 AS INTEGER) as duration_ms "
            f"FROM events {where} GROUP BY session_id ORDER BY {sort_col} DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )

        total_row = self._query_one(
            f"SELECT COUNT(DISTINCT session_id) as cnt FROM events {where}", params
        )
        total_sessions = total_row.get("cnt", 0) or 0
        total_pages = max(1, (total_sessions + limit - 1) // limit)

        return {
            "page": page,
            "total_sessions": total_sessions,
            "total_pages": total_pages,
            "sort": sort,
            "sessions": rows,
        }

    def sessions_aggregate(self, filters: dict) -> dict:
        """Per-period session aggregates for charting."""
        where, params = build_where(filters)
        period = filters.get("period", "day")
        pge = period_group_expr(period)

        # Aggregate session-level metrics by period
        # Inner query: per-session stats. Outer query: average across sessions per period.
        buckets = self._query(
            f"SELECT period, COUNT(*) as session_count, "
            f"AVG(event_count) as avg_events, "
            f"AVG(total_tokens) as avg_tokens, "
            f"AVG(avg_dur) as avg_duration, "
            f"SUM(error_count) as total_errors, "
            f"AVG(error_count) as avg_errors "
            f"FROM ("
            f"  SELECT {pge} as period, session_id, "
            f"  COUNT(*) as event_count, "
            f"  SUM(input_tokens + output_tokens) as total_tokens, "
            f"  AVG(duration_ms) as avg_dur, "
            f"  SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count "
            f"  FROM events {where} GROUP BY period, session_id"
            f") GROUP BY period ORDER BY period",
            params,
        )

        totals = self._query_one(
            f"SELECT COUNT(DISTINCT session_id) as total_sessions, "
            f"COUNT(*) as total_events, "
            f"SUM(input_tokens + output_tokens) as total_tokens, "
            f"SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as total_errors "
            f"FROM events {where}",
            params,
        )

        return {
            "buckets": buckets,
            "total_sessions": totals.get("total_sessions", 0) or 0,
            "total_events": totals.get("total_events", 0) or 0,
            "total_tokens": totals.get("total_tokens", 0) or 0,
            "total_errors": totals.get("total_errors", 0) or 0,
        }

    def session_detail(self, session_id: str) -> dict:
        events = self._query(
            "SELECT timestamp, tool, backend, status, duration_ms, agent_id, agent_type, "
            "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, "
            "was_summarized, original_size, summary_size, error_type "
            "FROM events WHERE session_id = ? ORDER BY timestamp",
            [session_id],
        )

        if not events:
            return {"session_id": session_id, "events": [], "summary": {}}

        total_tokens = sum(e.get("input_tokens", 0) + e.get("output_tokens", 0) for e in events)
        error_count = sum(1 for e in events if e.get("status") == "error")
        subagents = set(e["agent_id"] for e in events if e.get("agent_id") != session_id)

        for e in events:
            e["was_summarized"] = bool(e.get("was_summarized"))

        return {
            "session_id": session_id,
            "events": events,
            "summary": {
                "total_events": len(events),
                "total_tokens": total_tokens,
                "error_count": error_count,
                "duration_ms": 0,
                "subagent_count": len(subagents),
            },
        }

    def session_replay(self, session_id: str, jsonl_dir: str) -> dict:
        row = self._query_one(
            "SELECT file_path FROM session_files WHERE session_id = ?", [session_id]
        )
        file_path = row.get("file_path", "")
        if not file_path or not Path(file_path).exists():
            return {"session_id": session_id, "messages": [], "error": "Transcript not found"}

        messages = []
        for line in Path(file_path).read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = entry.get("type", "")
            ts = entry.get("timestamp", "")

            if etype == "user":
                msg = entry.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    messages.append({"timestamp": ts, "role": "user", "text": content})
                elif isinstance(content, list):
                    texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                    if texts:
                        messages.append({"timestamp": ts, "role": "user", "text": "\n".join(texts)})

            elif etype == "assistant":
                msg = entry.get("message", {})
                content = msg.get("content", [])
                if isinstance(content, str):
                    messages.append({"timestamp": ts, "role": "assistant", "text": content})
                elif isinstance(content, list):
                    texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                    tool_calls = [
                        {"tool": b.get("name", ""), "status": "pending"}
                        for b in content if isinstance(b, dict) and b.get("type") == "tool_use"
                    ]
                    m = {"timestamp": ts, "role": "assistant", "text": "\n".join(texts)}
                    if tool_calls:
                        m["tool_calls"] = tool_calls
                    messages.append(m)

        return {"session_id": session_id, "messages": messages}

    def compare(self, filters_a: dict, filters_b: dict) -> dict:
        data_a = self.overview(filters_a)
        data_b = self.overview(filters_b)

        def pct_change(a, b):
            if not a:
                return 0
            return round((b - a) / a * 100, 1)

        return {
            "range_a": {"from": filters_a.get("from", ""), "to": filters_a.get("to", ""), "data": data_a},
            "range_b": {"from": filters_b.get("from", ""), "to": filters_b.get("to", ""), "data": data_b},
            "deltas": {
                "total_events": (data_b.get("total_events", 0) or 0) - (data_a.get("total_events", 0) or 0),
                "total_tokens_pct": pct_change(
                    (data_a.get("total_input_tokens", 0) or 0) + (data_a.get("total_output_tokens", 0) or 0),
                    (data_b.get("total_input_tokens", 0) or 0) + (data_b.get("total_output_tokens", 0) or 0),
                ),
                "error_rate_pct": pct_change(
                    data_a.get("error_rate", 0) or 0, data_b.get("error_rate", 0) or 0
                ),
                "avg_duration_ms_pct": pct_change(
                    data_a.get("avg_duration_ms", 0) or 0, data_b.get("avg_duration_ms", 0) or 0
                ),
            },
        }

    def activity_heatmap(self, filters: dict) -> dict:
        where, params = build_where(filters)
        rows = self._query(
            f"SELECT CAST(strftime('%w', timestamp, '-5 hours') AS INTEGER) as day_of_week, "
            f"CAST(strftime('%H', timestamp, '-5 hours') AS INTEGER) as hour_of_day, "
            f"COUNT(*) as event_count FROM events {where} GROUP BY day_of_week, hour_of_day",
            params,
        )
        return {
            "data": [{"day": r["day_of_week"], "hour": r["hour_of_day"], "count": r["event_count"]} for r in rows]
        }

    def latency(self, filters: dict) -> dict:
        limit = int(filters.pop("limit", 50))
        where, params = build_where(filters)

        rows = self._query(
            f"SELECT tool, COUNT(*) as call_count, AVG(duration_ms) as avg_ms, "
            f"MIN(duration_ms) as min_ms, MAX(duration_ms) as max_ms, "
            f"SUM(CASE WHEN duration_ms < 100 THEN 1 ELSE 0 END) as bucket_lt100, "
            f"SUM(CASE WHEN duration_ms >= 100 AND duration_ms < 500 THEN 1 ELSE 0 END) as bucket_100_500, "
            f"SUM(CASE WHEN duration_ms >= 500 AND duration_ms < 1000 THEN 1 ELSE 0 END) as bucket_500_1000, "
            f"SUM(CASE WHEN duration_ms >= 1000 AND duration_ms < 5000 THEN 1 ELSE 0 END) as bucket_1s_5s, "
            f"SUM(CASE WHEN duration_ms >= 5000 AND duration_ms < 30000 THEN 1 ELSE 0 END) as bucket_5s_30s, "
            f"SUM(CASE WHEN duration_ms >= 30000 THEN 1 ELSE 0 END) as bucket_30s_plus "
            f"FROM events {where} GROUP BY tool ORDER BY call_count DESC LIMIT ?",
            params + [limit],
        )

        data = []
        for r in rows:
            data.append({
                "tool": r["tool"],
                "call_count": r["call_count"],
                "avg_ms": round(r.get("avg_ms", 0) or 0, 0),
                "min_ms": r.get("min_ms", 0) or 0,
                "max_ms": r.get("max_ms", 0) or 0,
                "histogram": {
                    "<100ms": r.get("bucket_lt100", 0) or 0,
                    "100-500ms": r.get("bucket_100_500", 0) or 0,
                    "500ms-1s": r.get("bucket_500_1000", 0) or 0,
                    "1-5s": r.get("bucket_1s_5s", 0) or 0,
                    "5-30s": r.get("bucket_5s_30s", 0) or 0,
                    "30s+": r.get("bucket_30s_plus", 0) or 0,
                },
            })
        return {"data": data}

    def errors(self, filters: dict) -> dict:
        group_by = filters.pop("group_by", "type")
        limit = int(filters.pop("limit", 50))
        where, params = build_where(filters)

        if group_by == "tool":
            and_where = where.replace("WHERE ", "AND ") if where else ""
            rows = self._query(
                f"WITH tool_totals AS ( "
                f"  SELECT tool, COUNT(*) as total_count FROM events {where} GROUP BY tool "
                f"), tool_errors AS ( "
                f"  SELECT tool, COUNT(*) as error_count FROM events "
                f"  WHERE status = 'error' {and_where} GROUP BY tool "
                f") SELECT e.tool, e.error_count, t.total_count, "
                f"CAST(e.error_count AS FLOAT) / t.total_count as error_rate "
                f"FROM tool_errors e JOIN tool_totals t ON e.tool = t.tool "
                f"ORDER BY e.error_count DESC LIMIT ?",
                params + params + [limit],
            )
            for r in rows:
                r["error_rate"] = round(r.get("error_rate", 0) or 0, 3)
            return {"group_by": "tool", "data": rows}

        else:
            and_where = where.replace("WHERE ", "AND ") if where else ""
            rows = self._query(
                f"SELECT error_type, COUNT(*) as count FROM events "
                f"WHERE status = 'error' AND error_type != '' {and_where} "
                f"GROUP BY error_type ORDER BY count DESC",
                params,
            )
            # Normalize raw error strings into human-readable categories, then re-aggregate
            merged: dict[str, int] = {}
            for r in rows:
                label = _normalize_error_type(r["error_type"])
                merged[label] = merged.get(label, 0) + r["count"]
            data = sorted(
                [{"error_type": k, "count": v} for k, v in merged.items()],
                key=lambda x: x["count"], reverse=True,
            )[:limit]
            return {"group_by": "type", "data": data}
