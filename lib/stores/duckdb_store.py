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

from .interfaces import (
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
        import glob as glob_module

        # Build list of patterns that have matching files
        # Use recursive glob to find files in subdirectories
        patterns = []
        jsonl_pattern = str(self.data_dir / "**" / "*.jsonl")
        gz_pattern = str(self.data_dir / "**" / "*.jsonl.gz")

        if glob_module.glob(jsonl_pattern, recursive=True):
            patterns.append(jsonl_pattern)
        if glob_module.glob(gz_pattern, recursive=True):
            patterns.append(gz_pattern)

        if not patterns:
            # No files found, create empty view
            self.conn.execute("""
                CREATE OR REPLACE VIEW events AS
                SELECT NULL as timestamp WHERE false
            """)
            return

        # Create main events view from all JSONL files (raw and gzipped)
        patterns_sql = ", ".join(f"'{p}'" for p in patterns)
        self.conn.execute(f"""
            CREATE OR REPLACE VIEW events AS
            SELECT * FROM read_json_auto(
                [{patterns_sql}],
                format='newline_delimited',
                ignore_errors=true,
                union_by_name=true
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
                WHERE CAST(timestamp AS TIMESTAMP)::DATE = '{day_str}'::DATE
            ),
            event_stats AS (
                SELECT
                    COUNT(DISTINCT session_id) as sessions,
                    COALESCE(SUM(
                        COALESCE(input_tokens, 0) +
                        COALESCE(output_tokens, 0)
                    ), 0) as total_tokens,
                    COUNT(*) as tool_calls,
                    0 as cache_hits
                FROM day_events
            )
            SELECT
                '{day_str}'::DATE as date,
                COALESCE(e.sessions, 0) as sessions,
                COALESCE(e.total_tokens, 0) as total_tokens,
                COALESCE(e.tool_calls, 0) as tool_calls,
                COALESCE(e.cache_hits, 0) as cache_hits,
                0.0 as cache_ratio,
                0 as summarizations_offered,
                0 as summarizations_accepted,
                0.0 as avg_compression_ratio,
                0 as tokens_saved
            FROM event_stats e
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
                tool as tool_name,
                COUNT(*) as call_count,
                COALESCE(AVG(duration_ms), 0) as avg_duration_ms,
                0 as total_response_bytes,
                0.0 as cache_hit_rate,
                0.0 as summarization_rate
            FROM events
            WHERE CAST(timestamp AS TIMESTAMP)::DATE >= '{start_str}'::DATE
              AND CAST(timestamp AS TIMESTAMP)::DATE <= '{end_str}'::DATE
              AND tool IS NOT NULL
            GROUP BY tool
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
                tool as tool_name,
                COUNT(*) as call_count,
                COALESCE(AVG(duration_ms), 0) as avg_duration_ms,
                0 as total_response_bytes,
                0.0 as cache_hit_rate,
                0.0 as summarization_rate
            FROM events
            WHERE tool IS NOT NULL
            GROUP BY tool
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
        conditions = []

        if session_id:
            conditions.append(f"session_id = '{session_id}'")
        if tool_name:
            conditions.append(f"tool LIKE '{tool_name}%'")
        if start_time:
            conditions.append(f"CAST(timestamp AS TIMESTAMP) >= '{start_time}'::TIMESTAMP")
        if end_time:
            conditions.append(f"CAST(timestamp AS TIMESTAMP) <= '{end_time}'::TIMESTAMP")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        results = self.conn.execute(f"""
            SELECT
                session_id,
                agent_id as turn_id,
                timestamp,
                tool,
                COALESCE(duration_ms, 0) as duration_ms,
                0 as response_size,
                false as is_cache_hit,
                NULL as summary_size,
                NULL as full_requested,
                NULL as parent_uuid,
                false as is_sidechain,
                NULL as git_branch
            FROM events
            WHERE {where_clause}
            ORDER BY CAST(timestamp AS TIMESTAMP) DESC
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
                session_id,
                agent_id as turn_id,
                timestamp,
                tool,
                COALESCE(duration_ms, 0) as duration_ms,
                0 as response_size,
                false as is_cache_hit,
                NULL as summary_size,
                NULL as full_requested,
                NULL as parent_uuid,
                false as is_sidechain,
                NULL as git_branch
            FROM events
            WHERE session_id = '{session_id}'
            ORDER BY CAST(timestamp AS TIMESTAMP) ASC
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
            conditions.append(f"MIN(CAST(timestamp AS TIMESTAMP))::DATE >= '{start_date.isoformat()}'::DATE")
        if end_date:
            conditions.append(f"MIN(CAST(timestamp AS TIMESTAMP))::DATE <= '{end_date.isoformat()}'::DATE")

        having_clause = f"HAVING {' AND '.join(conditions)}" if conditions else ""

        results = self.conn.execute(f"""
            WITH session_stats AS (
                SELECT
                    session_id,
                    MIN(CAST(timestamp AS TIMESTAMP)) as start_time,
                    MAX(CAST(timestamp AS TIMESTAMP)) as end_time,
                    SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) as total_tokens,
                    COUNT(*) as tool_calls,
                    0 as cache_hits,
                    NULL as git_branch,
                    NULL as project_path
                FROM events
                WHERE session_id IS NOT NULL
                GROUP BY session_id
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

    # -------------------------------------------------------------------------
    # Chart Query Methods (Telemetry v3)
    # -------------------------------------------------------------------------

    def get_token_spend_by_day(self, days: int = 30) -> list[dict]:
        """Get daily token spend with 7-day moving average.

        Args:
            days: Number of days to look back.

        Returns:
            List of dicts with day, total_tokens, and moving_avg_7d.
        """
        result = self.conn.execute(f"""
            SELECT
                CAST(timestamp AS TIMESTAMP)::DATE as day,
                SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) as total_tokens,
                AVG(SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0))) OVER (
                    ORDER BY CAST(timestamp AS TIMESTAMP)::DATE ROWS 6 PRECEDING
                ) as moving_avg_7d
            FROM events
            WHERE CAST(timestamp AS TIMESTAMP) >= CURRENT_DATE - INTERVAL '{days} days'
            GROUP BY CAST(timestamp AS TIMESTAMP)::DATE
            ORDER BY day
        """).fetchall()
        return [
            {"day": str(r[0]), "total_tokens": r[1], "moving_avg_7d": r[2]}
            for r in result
        ]

    def get_token_spend_by_agent_type(self) -> list[dict]:
        """Get token spend grouped by agent type.

        Returns:
            List of dicts with agent_type, total_tokens, and sessions.
        """
        result = self.conn.execute("""
            SELECT
                COALESCE(agent_type, 'main') as agent_type_name,
                SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) as total_tokens,
                COUNT(DISTINCT session_id) as sessions
            FROM events
            GROUP BY COALESCE(agent_type, 'main')
            ORDER BY total_tokens DESC
        """).fetchall()
        return [
            {"agent_type": r[0], "total_tokens": r[1], "sessions": r[2]}
            for r in result
        ]

    def get_cache_efficiency_trend(self, days: int = 30) -> list[dict]:
        """Get cache efficiency percentage over time.

        Args:
            days: Number of days to look back.

        Returns:
            List of dicts with day, cached, total_input, and cache_pct.
        """
        result = self.conn.execute(f"""
            SELECT
                CAST(timestamp AS TIMESTAMP)::DATE as day,
                SUM(COALESCE(cache_read_tokens, 0)) as cached,
                SUM(COALESCE(input_tokens, 0)) as total_input,
                ROUND(
                    100.0 * SUM(COALESCE(cache_read_tokens, 0)) /
                    NULLIF(SUM(COALESCE(input_tokens, 0)), 0),
                    1
                ) as cache_pct
            FROM events
            WHERE CAST(timestamp AS TIMESTAMP) >= CURRENT_DATE - INTERVAL '{days} days'
            GROUP BY CAST(timestamp AS TIMESTAMP)::DATE
            ORDER BY day
        """).fetchall()
        return [
            {"day": str(r[0]), "cached": r[1], "total_input": r[2], "cache_pct": r[3]}
            for r in result
        ]

    def get_tool_latency_by_backend(self) -> list[dict]:
        """Get average and P95 latency per backend.

        Returns:
            List of dicts with backend, avg_latency, and p95.
        """
        result = self.conn.execute("""
            SELECT
                backend,
                ROUND(AVG(duration_ms), 2) as avg_latency,
                ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms), 2) as p95
            FROM events
            WHERE duration_ms > 0
            GROUP BY backend
        """).fetchall()
        return [
            {"backend": r[0], "avg_latency": r[1], "p95": r[2]}
            for r in result
        ]

    def get_error_rate_by_tool(self, limit: int = 20) -> list[dict]:
        """Get error percentage per tool.

        Args:
            limit: Maximum number of tools to return.

        Returns:
            List of dicts with tool, total_calls, errors, and error_pct.
        """
        result = self.conn.execute(f"""
            SELECT
                tool,
                COUNT(*) as total_calls,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors,
                ROUND(
                    100.0 * SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) / COUNT(*),
                    1
                ) as error_pct
            FROM events
            GROUP BY tool
            ORDER BY error_pct DESC
            LIMIT {limit}
        """).fetchall()
        return [
            {"tool": r[0], "total_calls": r[1], "errors": r[2], "error_pct": r[3]}
            for r in result
        ]
