"""Abstract interfaces for telemetry data stores.

This module defines the repository pattern interfaces for telemetry storage.
Each interface is designed for a specific query pattern:

- AnalyticsStore: Aggregated metrics (daily summaries, tool statistics)
  Best suited for: SQL databases, time-series DBs, OLAP stores like DuckDB

- TraceStore: Individual event records and session data
  Best suited for: Document stores, SQL databases, append-only logs

- GraphStore: Relationship queries between sessions, tools, and events
  Best suited for: Graph databases, or materialized views in SQL
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional


@dataclass
class DaySummary:
    """Daily aggregated metrics for dashboard display.

    Contains pre-computed aggregations suitable for time-series charts
    and daily trend analysis.
    """

    date: date
    sessions: int
    total_tokens: int
    tool_calls: int
    cache_hits: int
    cache_ratio: float
    summarizations_offered: int
    summarizations_accepted: int
    avg_compression_ratio: float
    tokens_saved: int


@dataclass
class ToolCallRecord:
    """Individual tool call event data.

    Captures a single tool invocation with timing, size metrics,
    and context about the session and caching behavior.
    """

    session_id: str
    turn_id: str
    timestamp: str
    tool: str
    duration_ms: int
    response_size: int
    is_cache_hit: bool
    summary_size: Optional[int]
    full_requested: Optional[bool]
    parent_uuid: Optional[str]
    is_sidechain: bool
    git_branch: Optional[str]


@dataclass
class SessionRecord:
    """Session metadata and summary statistics.

    Represents a single Claude session with aggregated metrics
    and metadata for session-level analysis.
    """

    session_id: str
    start_time: str
    end_time: Optional[str]
    total_tokens: int
    tool_calls: int
    cache_hits: int
    git_branch: Optional[str]
    project_path: Optional[str]


@dataclass
class ToolSummary:
    """Aggregated statistics for a single tool.

    Provides overview metrics for tool usage patterns,
    performance characteristics, and caching effectiveness.
    """

    tool_name: str
    call_count: int
    avg_duration_ms: float
    total_response_bytes: int
    cache_hit_rate: float
    summarization_rate: float


@dataclass
class ValidatedMetrics:
    """Cross-validated metrics for data integrity checks.

    Contains metrics computed from multiple sources to verify
    consistency between raw events and aggregated summaries.
    """

    source: str
    computed_total: int
    stored_total: int
    discrepancy: int
    is_valid: bool


class AnalyticsStore(ABC):
    """Interface for aggregated analytics queries.

    Implementations should optimize for:
    - Time-range aggregations
    - Group-by operations (by tool, by day, by session)
    - Pre-computed rollups where beneficial

    Suitable backends: DuckDB, ClickHouse, TimescaleDB, BigQuery
    """

    @abstractmethod
    def get_daily_summary(self, day: date) -> Optional[DaySummary]:
        """Retrieve aggregated metrics for a specific day.

        Args:
            day: The date to retrieve summary for.

        Returns:
            DaySummary with all metrics, or None if no data exists.
        """
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    def get_tool_summaries(self, limit: int = 20) -> list[ToolSummary]:
        """Get top tools by usage with their statistics.

        Args:
            limit: Maximum number of tools to return.

        Returns:
            List of ToolSummary records ordered by call_count descending.
        """
        ...


class TraceStore(ABC):
    """Interface for individual event record queries.

    Implementations should optimize for:
    - Point lookups by session/turn ID
    - Time-ordered event streams
    - Filtering by tool name or session

    Suitable backends: PostgreSQL, SQLite, MongoDB, DuckDB
    """

    @abstractmethod
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
        ...

    @abstractmethod
    def get_session_events(self, session_id: str) -> list[ToolCallRecord]:
        """Get all tool call events for a session in chronological order.

        Args:
            session_id: The session to retrieve events for.

        Returns:
            List of ToolCallRecord ordered by timestamp ascending.
        """
        ...

    @abstractmethod
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
        ...


class GraphStore(ABC):
    """Interface for relationship and graph-based queries.

    Implementations should optimize for:
    - Traversal queries (session -> turns -> tool calls)
    - Pattern matching across sessions
    - Path finding between related events

    Suitable backends: Neo4j, DGraph, or SQL with recursive CTEs
    """

    @abstractmethod
    def get_session_graph(self, session_id: str) -> dict[str, Any]:
        """Build a graph representation of a session's structure.

        Args:
            session_id: The session to build graph for.

        Returns:
            Dict with 'nodes' and 'edges' representing session structure.
            Nodes include turns, tool calls, and responses.
            Edges represent temporal and causal relationships.
        """
        ...

    @abstractmethod
    def find_pattern(
        self, tool_sequence: list[str], max_results: int = 10
    ) -> list[dict[str, Any]]:
        """Find sessions matching a sequence of tool calls.

        Args:
            tool_sequence: Ordered list of tool names to match.
            max_results: Maximum matching sessions to return.

        Returns:
            List of dicts with 'session_id' and 'match_positions'.
        """
        ...

    @abstractmethod
    def trace_path(
        self, from_event: str, to_event: str
    ) -> Optional[list[dict[str, Any]]]:
        """Find the causal path between two events.

        Args:
            from_event: Starting event UUID.
            to_event: Ending event UUID.

        Returns:
            List of events forming the path, or None if no path exists.
        """
        ...
