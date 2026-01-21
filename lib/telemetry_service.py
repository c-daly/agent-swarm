"""High-level facade for telemetry data access.

Provides a simple interface for dashboard and API consumers to access
telemetry data without needing to know about store implementations.
"""

from datetime import datetime
from typing import Optional, List

from lib.stores.interfaces import AnalyticsStore, ToolSummary
from lib.stores.duckdb_store import DuckDBStore
from lib.stores.validation import ValidationResult, validate_day_summary
from lib.stores.interfaces import DaySummary


class TelemetryService:
    """High-level facade for telemetry data access.

    Provides simplified access to telemetry metrics with automatic
    validation and sensible defaults. Uses DuckDBStore by default
    but accepts any AnalyticsStore implementation.

    Example:
        service = TelemetryService()
        summary = service.get_summary("2025-01-15")
        if summary:
            print(f"Confidence: {summary.confidence}")
            print(f"Tool calls: {summary.data.tool_calls}")
    """

    def __init__(
        self,
        store: Optional[AnalyticsStore] = None,
        data_dir: str = "logs",
    ) -> None:
        """Initialize the telemetry service.

        Args:
            store: Optional AnalyticsStore implementation. If not provided,
                   creates a DuckDBStore with the given data_dir.
            data_dir: Directory for data storage when creating default store.
        """
        self._store = store or DuckDBStore(data_dir=data_dir)

    def get_summary(
        self, date_str: str
    ) -> Optional[ValidationResult[DaySummary]]:
        """Get validated daily summary for a date.

        Args:
            date_str: Date in ISO format (YYYY-MM-DD).

        Returns:
            ValidationResult containing DaySummary with confidence score
            and any warnings, or None if no data exists for the date.
        """
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
        summary = self._store.get_daily_summary(day)

        if summary is None:
            return None

        return validate_day_summary(summary)

    def get_tool_breakdown(self, limit: int = 20) -> List[ToolSummary]:
        """Get tool-by-tool breakdown of usage.

        Args:
            limit: Maximum number of tools to return (default 20).

        Returns:
            List of ToolSummary records ordered by call count descending.
        """
        return self._store.get_tool_summaries(limit=limit)

    def insert_event(self, event: dict) -> None:
        """Insert a telemetry event into the store.

        Args:
            event: Dictionary with event data matching ToolCallEvent fields.
                   Required: timestamp, session_id, tool, backend, duration_ms, status
                   Optional: agent_id, input_tokens, output_tokens, cache_read_tokens,
                            cache_creation_tokens, agent_type, workflow_id, error_type
        """
        self._store.insert_event(event)
