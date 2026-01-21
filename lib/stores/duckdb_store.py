"""DuckDB-backed implementation of telemetry stores.

Uses DuckDB to query JSONL files directly without data import.
DuckDB's read_json_auto function scans files on-demand, making this
suitable for analytics over append-only telemetry logs.
"""

from datetime import date
from pathlib import Path
from typing import Optional

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore

from lib.stores.interfaces import (
    AnalyticsStore,
    DaySummary,
    SessionRecord,
    ToolCallRecord,
    ToolSummary,
    TraceStore,
)


class DuckDBStore(AnalyticsStore, TraceStore):
    """DuckDB implementation querying JSONL telemetry files directly.

    This store creates an in-memory DuckDB connection and sets up views
    over JSONL files using glob patterns. Queries execute against the
    raw files without requiring data import or ETL.

    Attributes:
        data_dir: Path to directory containing JSONL telemetry files.
        conn: DuckDB connection instance.
    """

    def __init__(self, data_dir: str) -> None:
        """Initialize DuckDB store with data directory.

        Args:
            data_dir: Path to directory containing session JSONL files.
                      Files are expected to match pattern **/*.jsonl

        Raises:
            ImportError: If duckdb package is not installed.
        """
        if duckdb is None:
            raise ImportError(
                "duckdb is required for DuckDBStore. Install with: pip install duckdb"
            )

        self.data_dir = Path(data_dir)
        self.conn = duckdb.connect(":memory:")
        self._setup_views()

    def _setup_views(self) -> None:
        """Create views over JSONL files for querying."""
        jsonl_pattern = str(self.data_dir / "**" / "*.jsonl")

        # Create main events view from all JSONL files
        self.conn.execute(f"""
            CREATE OR REPLACE VIEW events AS
            SELECT * FROM read_json_auto(
                '{jsonl_pattern}',
                format='newline_delimited',
                ignore_errors=true
            )
        """)

    def get_daily_summary(self, day: date) -> Optional[DaySummary]:
        """Retrieve aggregated metrics for a specific day.

        Args:
            day: The date to retrieve summary for.

        Returns:
            DaySummary with all metrics, or None if no data exists.
        """
        day_str = day.isoformat()

        result = self.conn.execute(f"""
            WITH day_events AS (
                SELECT *
                FROM events
                WHERE timestamp::DATE = '{day_str}'::DATE
            ),
            assistant_stats AS (
                SELECT
                    COUNT(DISTINCT sessionId) as sessions,
                    COALESCE(SUM(
                        COALESCE(message.usage.input_tokens, 0) +
                        COALESCE(message.usage.output_tokens, 0)
                    ), 0) as total_tokens
                FROM day_events
                WHERE type = 'assistant'
            ),
            tool_stats AS (
                SELECT
                    COUNT(*) as tool_calls,
                    0 as cache_hits
                FROM day_events
                WHERE type = 'tool_use'
            )
            SELECT
                '{day_str}'::DATE as date,
                COALESCE(a.sessions, 0) as sessions,
                COALESCE(a.total_tokens, 0) as total_tokens,
                COALESCE(t.tool_calls, 0) as tool_calls,
                COALESCE(t.cache_hits, 0) as cache_hits,
                0.0 as cache_ratio,
                0 as summarizations_offered,
                0 as summarizations_accepted,
                0.0 as avg_compression_ratio,
                0 as tokens_saved
            FROM assistant_stats a, tool_stats t
        """).fetchone()

        if result is None or result[1] == 0:  # No sessions means no data
            return None

        return DaySummary(
            date=result[0],
            sessions=result[1],
            total_tokens=result[2],
            tool_calls=result[3],
            cache_hits=result[4],
            cache_ratio=result[5],
            summarizations_offered=result[6],
            summarizations_accepted=result[7],
            avg_compression_ratio=result[8],
            tokens_saved=result[9],
        )

    def aggregate_by_tool(
        self, start_date: date, end_date: date
    ) -> list[ToolSummary]:
        """Get tool-level aggregations over a date range.

        Args:
            start_date: Start of date range (inclusive).
            end_date: End of date range (inclusive).

        Returns:
            List of ToolSummary records, one per distinct tool.
        """
        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        results = self.conn.execute(f"""
            SELECT
                toolName as tool_name,
                COUNT(*) as call_count,
                COALESCE(AVG(durationMs), 0) as avg_duration_ms,
                0 as total_response_bytes,
                0.0 as cache_hit_rate,
                0.0 as summarization_rate
            FROM events
            WHERE type = 'tool_use'
              AND timestamp::DATE >= '{start_str}'::DATE
              AND timestamp::DATE <= '{end_str}'::DATE
              AND toolName IS NOT NULL
            GROUP BY toolName
            ORDER BY call_count DESC
        """).fetchall()

        return [
            ToolSummary(
                tool_name=row[0],
                call_count=row[1],
                avg_duration_ms=float(row[2]),
                total_response_bytes=row[3],
                cache_hit_rate=row[4],
                summarization_rate=row[5],
            )
            for row in results
        ]

    def get_tool_summaries(self, limit: int = 20) -> list[ToolSummary]:
        """Get top tools by usage with their statistics.

        Args:
            limit: Maximum number of tools to return.

        Returns:
            List of ToolSummary records ordered by call_count descending.
        """
        results = self.conn.execute(f"""
            SELECT
                toolName as tool_name,
                COUNT(*) as call_count,
                COALESCE(AVG(durationMs), 0) as avg_duration_ms,
                0 as total_response_bytes,
                0.0 as cache_hit_rate,
                0.0 as summarization_rate
            FROM events
            WHERE type = 'tool_use'
              AND toolName IS NOT NULL
            GROUP BY toolName
            ORDER BY call_count DESC
            LIMIT {limit}
        """).fetchall()

        return [
            ToolSummary(
                tool_name=row[0],
                call_count=row[1],
                avg_duration_ms=float(row[2]),
                total_response_bytes=row[3],
                cache_hit_rate=row[4],
                summarization_rate=row[5],
            )
            for row in results
        ]

    def query_tool_calls(
        self,
        session_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
    ) -> list[ToolCallRecord]:
        """Query tool call records with optional filters.

        Args:
            session_id: Filter to specific session.
            tool_name: Filter to specific tool (supports prefix match).
            start_time: ISO timestamp for range start.
            end_time: ISO timestamp for range end.
            limit: Maximum records to return.

        Returns:
            List of ToolCallRecord matching filters, ordered by timestamp desc.
        """
        conditions = ["type = 'tool_use'"]

        if session_id:
            conditions.append(f"sessionId = '{session_id}'")
        if tool_name:
            conditions.append(f"toolName LIKE '{tool_name}%'")
        if start_time:
            conditions.append(f"timestamp >= '{start_time}'")
        if end_time:
            conditions.append(f"timestamp <= '{end_time}'")

        where_clause = " AND ".join(conditions)

        results = self.conn.execute(f"""
            SELECT
                sessionId as session_id,
                uuid as turn_id,
                timestamp,
                toolName as tool,
                COALESCE(durationMs, 0) as duration_ms,
                0 as response_size,
                false as is_cache_hit,
                NULL as summary_size,
                NULL as full_requested,
                NULL as parent_uuid,
                false as is_sidechain,
                NULL as git_branch
            FROM events
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT {limit}
        """).fetchall()

        return [
            ToolCallRecord(
                session_id=row[0],
                turn_id=row[1],
                timestamp=str(row[2]),
                tool=row[3],
                duration_ms=row[4],
                response_size=row[5],
                is_cache_hit=row[6],
                summary_size=row[7],
                full_requested=row[8],
                parent_uuid=row[9],
                is_sidechain=row[10],
                git_branch=row[11],
            )
            for row in results
        ]

    def get_session_events(self, session_id: str) -> list[ToolCallRecord]:
        """Get all tool call events for a session in chronological order.

        Args:
            session_id: The session to retrieve events for.

        Returns:
            List of ToolCallRecord ordered by timestamp ascending.
        """
        results = self.conn.execute(f"""
            SELECT
                sessionId as session_id,
                uuid as turn_id,
                timestamp,
                toolName as tool,
                COALESCE(durationMs, 0) as duration_ms,
                0 as response_size,
                false as is_cache_hit,
                NULL as summary_size,
                NULL as full_requested,
                NULL as parent_uuid,
                false as is_sidechain,
                NULL as git_branch
            FROM events
            WHERE type = 'tool_use'
              AND sessionId = '{session_id}'
            ORDER BY timestamp ASC
        """).fetchall()

        return [
            ToolCallRecord(
                session_id=row[0],
                turn_id=row[1],
                timestamp=str(row[2]),
                tool=row[3],
                duration_ms=row[4],
                response_size=row[5],
                is_cache_hit=row[6],
                summary_size=row[7],
                full_requested=row[8],
                parent_uuid=row[9],
                is_sidechain=row[10],
                git_branch=row[11],
            )
            for row in results
        ]

    def get_sessions(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 50,
    ) -> list[SessionRecord]:
        """List sessions with optional date filtering.

        Args:
            start_date: Filter sessions starting on or after this date.
            end_date: Filter sessions starting on or before this date.
            limit: Maximum sessions to return.

        Returns:
            List of SessionRecord ordered by start_time descending.
        """
        conditions = []

        if start_date:
            conditions.append(f"MIN(timestamp)::DATE >= '{start_date.isoformat()}'::DATE")
        if end_date:
            conditions.append(f"MIN(timestamp)::DATE <= '{end_date.isoformat()}'::DATE")

        having_clause = f"HAVING {' AND '.join(conditions)}" if conditions else ""

        results = self.conn.execute(f"""
            WITH session_stats AS (
                SELECT
                    sessionId as session_id,
                    MIN(timestamp) as start_time,
                    MAX(timestamp) as end_time,
                    SUM(CASE WHEN type = 'assistant' THEN
                        COALESCE(message.usage.input_tokens, 0) +
                        COALESCE(message.usage.output_tokens, 0)
                    ELSE 0 END) as total_tokens,
                    SUM(CASE WHEN type = 'tool_use' THEN 1 ELSE 0 END) as tool_calls,
                    0 as cache_hits,
                    NULL as git_branch,
                    NULL as project_path
                FROM events
                WHERE sessionId IS NOT NULL
                GROUP BY sessionId
                {having_clause}
            )
            SELECT * FROM session_stats
            ORDER BY start_time DESC
            LIMIT {limit}
        """).fetchall()

        return [
            SessionRecord(
                session_id=row[0],
                start_time=str(row[1]),
                end_time=str(row[2]) if row[2] else None,
                total_tokens=int(row[3]) if row[3] else 0,
                tool_calls=int(row[4]) if row[4] else 0,
                cache_hits=row[5],
                git_branch=row[6],
                project_path=row[7],
            )
            for row in results
        ]
