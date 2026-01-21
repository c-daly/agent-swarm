"""Tests for TelemetryService facade."""

from datetime import date
from unittest.mock import Mock

from lib.telemetry_service import TelemetryService
from lib.stores.interfaces import DaySummary, ToolSummary, AnalyticsStore
from lib.stores.validation import ValidationResult


class TestTelemetryService:
    """Test suite for TelemetryService."""

    def test_get_summary_returns_validation_result(self):
        """get_summary should return ValidationResult with confidence and warnings."""
        # Create mock store with test data
        mock_store = Mock(spec=AnalyticsStore)
        mock_store.get_daily_summary.return_value = DaySummary(
            date=date(2025, 1, 15),
            sessions=5,
            total_tokens=10000,
            tool_calls=50,
            cache_hits=30,
            cache_ratio=0.6,
            summarizations_offered=10,
            summarizations_accepted=8,
            avg_compression_ratio=0.3,
            tokens_saved=5000,
        )

        service = TelemetryService(store=mock_store)
        result = service.get_summary("2025-01-15")

        assert isinstance(result, ValidationResult)
        assert hasattr(result, "confidence")
        assert hasattr(result, "warnings")
        assert hasattr(result, "data")
        assert result.data.sessions == 5

    def test_get_summary_parses_date_string(self):
        """get_summary should parse date string and pass date object to store."""
        mock_store = Mock(spec=AnalyticsStore)
        mock_store.get_daily_summary.return_value = DaySummary(
            date=date(2025, 1, 15),
            sessions=1,
            total_tokens=100,
            tool_calls=5,
            cache_hits=2,
            cache_ratio=0.4,
            summarizations_offered=1,
            summarizations_accepted=1,
            avg_compression_ratio=0.5,
            tokens_saved=50,
        )

        service = TelemetryService(store=mock_store)
        service.get_summary("2025-01-15")

        mock_store.get_daily_summary.assert_called_once_with(date(2025, 1, 15))

    def test_get_tool_breakdown_returns_list(self):
        """get_tool_breakdown should return list of ToolSummary."""
        mock_store = Mock(spec=AnalyticsStore)
        mock_store.get_tool_summaries.return_value = [
            ToolSummary(
                tool_name="read_file",
                call_count=100,
                avg_duration_ms=50.0,
                total_response_bytes=50000,
                cache_hit_rate=0.7,
                summarization_rate=0.3,
            ),
            ToolSummary(
                tool_name="write_file",
                call_count=50,
                avg_duration_ms=30.0,
                total_response_bytes=25000,
                cache_hit_rate=0.5,
                summarization_rate=0.1,
            ),
        ]

        service = TelemetryService(store=mock_store)
        result = service.get_tool_breakdown()

        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(item, ToolSummary) for item in result)
        assert result[0].tool_name == "read_file"

    def test_get_tool_breakdown_accepts_limit(self):
        """get_tool_breakdown should pass limit to store."""
        mock_store = Mock(spec=AnalyticsStore)
        mock_store.get_tool_summaries.return_value = []

        service = TelemetryService(store=mock_store)
        service.get_tool_breakdown(limit=10)

        mock_store.get_tool_summaries.assert_called_once_with(limit=10)

    def test_service_uses_configured_store(self):
        """TelemetryService should use the provided store."""
        mock_store = Mock(spec=AnalyticsStore)

        service = TelemetryService(store=mock_store)

        assert service._store is mock_store

    def test_service_creates_default_store(self, tmp_path):
        """TelemetryService should create DuckDBStore by default."""
        from lib.stores.duckdb_store import DuckDBStore

        # Create a dummy jsonl file so DuckDBStore can initialize
        jsonl_file = tmp_path / "test.jsonl"
        jsonl_file.write_text('{"event": "test"}\n')

        service = TelemetryService(data_dir=str(tmp_path))

        assert isinstance(service._store, DuckDBStore)

    def test_get_summary_handles_none_from_store(self):
        """get_summary should handle None returned from store."""
        mock_store = Mock(spec=AnalyticsStore)
        mock_store.get_daily_summary.return_value = None

        service = TelemetryService(store=mock_store)
        result = service.get_summary("2025-01-15")

        assert result is None

    def test_get_tool_breakdown_default_limit(self):
        """get_tool_breakdown should use default limit of 20."""
        mock_store = Mock(spec=AnalyticsStore)
        mock_store.get_tool_summaries.return_value = []

        service = TelemetryService(store=mock_store)
        service.get_tool_breakdown()

        mock_store.get_tool_summaries.assert_called_once_with(limit=20)
