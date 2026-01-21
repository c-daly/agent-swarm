"""Tests for charts module."""

from datetime import date
from unittest.mock import Mock

import pytest

from lib.charts import (
    render_daily_summary,
    render_tool_breakdown,
    render_weekly_trend,
    render_dashboard,
    _format_confidence,
    _render_bar,
    get_token_spend_chart,
    get_agent_token_chart,
    get_cache_efficiency_chart,
    get_tool_latency_chart,
    get_error_rate_chart,
)
from lib.telemetry_service import TelemetryService
from lib.stores.interfaces import DaySummary, ToolSummary, AnalyticsStore
from lib.stores.duckdb_store import DuckDBStore
from lib.stores.validation import ValidationResult


class TestFormatConfidence:
    """Tests for _format_confidence helper."""

    def test_high_confidence_shows_ok(self):
        """Confidence >= 0.8 should show [OK]."""
        assert _format_confidence(1.0) == "[OK]"
        assert _format_confidence(0.8) == "[OK]"

    def test_medium_confidence_shows_warn(self):
        """Confidence between 0.5 and 0.8 should show [WARN]."""
        assert _format_confidence(0.79) == "[WARN]"
        assert _format_confidence(0.5) == "[WARN]"

    def test_low_confidence_shows_low(self):
        """Confidence < 0.5 should show [LOW]."""
        assert _format_confidence(0.49) == "[LOW]"
        assert _format_confidence(0.0) == "[LOW]"


class TestRenderBar:
    """Tests for _render_bar helper."""

    def test_full_bar_at_max(self):
        """Value equal to max should render full bar."""
        bar = _render_bar(100, 100, width=10)
        assert bar == "##########"

    def test_empty_bar_at_zero(self):
        """Zero value should render empty bar."""
        bar = _render_bar(0, 100, width=10)
        assert bar == "----------"

    def test_half_bar(self):
        """Half value should render half-filled bar."""
        bar = _render_bar(50, 100, width=10)
        assert bar == "#####-----"

    def test_handles_zero_max(self):
        """Zero max should return empty bar without error."""
        bar = _render_bar(0, 0, width=10)
        assert bar == "          "  # spaces


class TestRenderDailySummary:
    """Tests for render_daily_summary function."""

    def _make_service(self, summary: DaySummary | None) -> TelemetryService:
        """Create a TelemetryService with mocked store."""
        mock_store = Mock(spec=AnalyticsStore)
        mock_store.get_daily_summary.return_value = summary
        return TelemetryService(store=mock_store)

    def test_renders_basic_metrics(self):
        """Should render all basic metrics from summary."""
        summary = DaySummary(
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
        service = self._make_service(summary)

        output = render_daily_summary(service, "2025-01-15")

        assert "2025-01-15" in output
        assert "5" in output  # sessions
        assert "50" in output  # tool_calls
        assert "10000" in output  # total_tokens
        assert "60.0%" in output  # cache_ratio

    def test_shows_confidence_indicator(self):
        """Should include confidence indicator in output."""
        summary = DaySummary(
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
        service = self._make_service(summary)

        output = render_daily_summary(service, "2025-01-15")

        assert "[OK]" in output

    def test_shows_warnings_when_present(self):
        """Should display warnings from validation."""
        summary = DaySummary(
            date=date(2025, 1, 15),
            sessions=0,
            total_tokens=0,
            tool_calls=0,
            cache_hits=0,
            cache_ratio=0.0,
            summarizations_offered=0,
            summarizations_accepted=0,
            avg_compression_ratio=0.0,
            tokens_saved=0,
        )
        service = self._make_service(summary)

        output = render_daily_summary(service, "2025-01-15")

        assert "Warnings:" in output
        assert "No data recorded" in output

    def test_handles_no_data(self):
        """Should handle case when no data exists for date."""
        service = self._make_service(None)

        output = render_daily_summary(service, "2025-01-15")

        assert "No data available" in output


class TestRenderToolBreakdown:
    """Tests for render_tool_breakdown function."""

    def _make_service(self, tools: list[ToolSummary]) -> TelemetryService:
        """Create a TelemetryService with mocked store."""
        mock_store = Mock(spec=AnalyticsStore)
        mock_store.get_tool_summaries.return_value = tools
        return TelemetryService(store=mock_store)

    def test_renders_tool_list(self):
        """Should render list of tools with statistics."""
        tools = [
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
        service = self._make_service(tools)

        output = render_tool_breakdown(service, limit=10)

        assert "read_file" in output
        assert "write_file" in output
        assert "100" in output
        assert "50" in output

    def test_renders_horizontal_bars(self):
        """Should include visual bar representation."""
        tools = [
            ToolSummary(
                tool_name="read_file",
                call_count=100,
                avg_duration_ms=50.0,
                total_response_bytes=50000,
                cache_hit_rate=0.7,
                summarization_rate=0.3,
            ),
        ]
        service = self._make_service(tools)

        output = render_tool_breakdown(service, limit=10)

        assert "#" in output  # bar characters

    def test_handles_empty_list(self):
        """Should handle empty tool list gracefully."""
        service = self._make_service([])

        output = render_tool_breakdown(service, limit=10)

        assert "No tool data available" in output

    def test_respects_limit_parameter(self):
        """Should pass limit to service."""
        mock_store = Mock(spec=AnalyticsStore)
        mock_store.get_tool_summaries.return_value = []
        service = TelemetryService(store=mock_store)

        render_tool_breakdown(service, limit=5)

        mock_store.get_tool_summaries.assert_called_once_with(limit=5)


class TestRenderWeeklyTrend:
    """Tests for render_weekly_trend function."""

    def test_renders_7_days(self):
        """Should attempt to render 7 days of data."""
        mock_store = Mock(spec=AnalyticsStore)
        mock_store.get_daily_summary.return_value = None
        service = TelemetryService(store=mock_store)

        output = render_weekly_trend(service, "2025-01-15")

        # Should have called for 7 days
        assert mock_store.get_daily_summary.call_count == 7

    def test_shows_missing_data_indicator(self):
        """Should show placeholder for days with no data."""
        mock_store = Mock(spec=AnalyticsStore)
        mock_store.get_daily_summary.return_value = None
        service = TelemetryService(store=mock_store)

        output = render_weekly_trend(service, "2025-01-15")

        assert "--" in output

    def test_calculates_averages(self):
        """Should calculate and display averages."""
        mock_store = Mock(spec=AnalyticsStore)
        summary = DaySummary(
            date=date(2025, 1, 15),
            sessions=5,
            total_tokens=1000,
            tool_calls=100,
            cache_hits=50,
            cache_ratio=0.5,
            summarizations_offered=10,
            summarizations_accepted=8,
            avg_compression_ratio=0.3,
            tokens_saved=500,
        )
        mock_store.get_daily_summary.return_value = summary
        service = TelemetryService(store=mock_store)

        output = render_weekly_trend(service, "2025-01-15")

        assert "Average" in output


class TestRenderDashboard:
    """Tests for render_dashboard function."""

    def test_combines_all_sections(self):
        """Should include all chart sections."""
        mock_store = Mock(spec=AnalyticsStore)
        summary = DaySummary(
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
        tools = [
            ToolSummary(
                tool_name="read_file",
                call_count=100,
                avg_duration_ms=50.0,
                total_response_bytes=50000,
                cache_hit_rate=0.7,
                summarization_rate=0.3,
            ),
        ]
        mock_store.get_daily_summary.return_value = summary
        mock_store.get_tool_summaries.return_value = tools
        service = TelemetryService(store=mock_store)

        output = render_dashboard(service=service, date_str="2025-01-15")

        assert "Daily Summary" in output
        assert "Tool Usage Breakdown" in output
        assert "Weekly Trend" in output

    def test_creates_service_when_not_provided(self):
        """Should create TelemetryService if not provided (uses mock)."""
        # This test verifies the code path exists; actual DuckDB integration
        # is tested elsewhere. We patch TelemetryService to avoid DB issues.
        from unittest.mock import patch

        mock_service = Mock(spec=TelemetryService)
        mock_service.get_summary.return_value = None
        mock_service.get_tool_breakdown.return_value = []

        with patch("lib.charts.TelemetryService", return_value=mock_service):
            output = render_dashboard(date_str="2025-01-15", data_dir="/tmp")

        # Should not raise, and should return some output
        assert isinstance(output, str)

    def test_accepts_custom_service(self):
        """Should use provided service instead of creating one."""
        mock_store = Mock(spec=AnalyticsStore)
        mock_store.get_daily_summary.return_value = None
        mock_store.get_tool_summaries.return_value = []
        service = TelemetryService(store=mock_store)

        render_dashboard(service=service, date_str="2025-01-15")

        # Verify our mock store was used
        assert mock_store.get_daily_summary.called


class TestGetTokenSpendChart:
    """Tests for get_token_spend_chart JSON endpoint."""

    def test_returns_list_of_dicts(self):
        """Should return list of dicts with day, total_tokens, moving_avg."""
        mock_store = Mock(spec=DuckDBStore)
        mock_store.get_token_spend_by_day.return_value = [
            {"day": "2025-01-15", "total_tokens": 10000, "moving_avg_7d": 8000},
            {"day": "2025-01-16", "total_tokens": 12000, "moving_avg_7d": 9000},
        ]

        result = get_token_spend_chart(mock_store, days=30)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["day"] == "2025-01-15"
        assert result[0]["total_tokens"] == 10000
        mock_store.get_token_spend_by_day.assert_called_once_with(days=30)

    def test_handles_empty_data(self):
        """Should return empty list when no data exists."""
        mock_store = Mock(spec=DuckDBStore)
        mock_store.get_token_spend_by_day.return_value = []

        result = get_token_spend_chart(mock_store)

        assert result == []

    def test_default_days_parameter(self):
        """Should default to 30 days."""
        mock_store = Mock(spec=DuckDBStore)
        mock_store.get_token_spend_by_day.return_value = []

        get_token_spend_chart(mock_store)

        mock_store.get_token_spend_by_day.assert_called_once_with(days=30)


class TestGetAgentTokenChart:
    """Tests for get_agent_token_chart JSON endpoint."""

    def test_returns_list_by_agent_type(self):
        """Should return list of dicts with agent_type and total_tokens."""
        mock_store = Mock(spec=DuckDBStore)
        mock_store.get_token_spend_by_agent_type.return_value = [
            {"agent_type": "Explore", "total_tokens": 50000, "sessions": 10},
            {"agent_type": "main", "total_tokens": 30000, "sessions": 5},
        ]

        result = get_agent_token_chart(mock_store)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["agent_type"] == "Explore"
        assert result[0]["total_tokens"] == 50000

    def test_handles_empty_data(self):
        """Should return empty list when no data exists."""
        mock_store = Mock(spec=DuckDBStore)
        mock_store.get_token_spend_by_agent_type.return_value = []

        result = get_agent_token_chart(mock_store)

        assert result == []


class TestGetCacheEfficiencyChart:
    """Tests for get_cache_efficiency_chart JSON endpoint."""

    def test_returns_cache_trend_data(self):
        """Should return list of dicts with day and cache_pct."""
        mock_store = Mock(spec=DuckDBStore)
        mock_store.get_cache_efficiency_trend.return_value = [
            {"day": "2025-01-15", "cached": 5000, "total_input": 10000, "cache_pct": 50.0},
        ]

        result = get_cache_efficiency_chart(mock_store, days=7)

        assert isinstance(result, list)
        assert result[0]["cache_pct"] == 50.0
        mock_store.get_cache_efficiency_trend.assert_called_once_with(days=7)

    def test_handles_empty_data(self):
        """Should return empty list when no cache data."""
        mock_store = Mock(spec=DuckDBStore)
        mock_store.get_cache_efficiency_trend.return_value = []

        result = get_cache_efficiency_chart(mock_store)

        assert result == []


class TestGetToolLatencyChart:
    """Tests for get_tool_latency_chart JSON endpoint."""

    def test_returns_latency_by_backend(self):
        """Should return list of dicts with backend, avg_latency, p95."""
        mock_store = Mock(spec=DuckDBStore)
        mock_store.get_tool_latency_by_backend.return_value = [
            {"backend": "native", "avg_latency": 50.5, "p95": 150.0},
            {"backend": "serena", "avg_latency": 200.0, "p95": 500.0},
        ]

        result = get_tool_latency_chart(mock_store)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["backend"] == "native"
        assert result[0]["avg_latency"] == 50.5

    def test_handles_empty_data(self):
        """Should return empty list when no latency data."""
        mock_store = Mock(spec=DuckDBStore)
        mock_store.get_tool_latency_by_backend.return_value = []

        result = get_tool_latency_chart(mock_store)

        assert result == []


class TestGetErrorRateChart:
    """Tests for get_error_rate_chart JSON endpoint."""

    def test_returns_error_rates_by_tool(self):
        """Should return list of dicts with tool, errors, error_pct."""
        mock_store = Mock(spec=DuckDBStore)
        mock_store.get_error_rate_by_tool.return_value = [
            {"tool": "Bash", "total_calls": 100, "errors": 5, "error_pct": 5.0},
            {"tool": "Read", "total_calls": 200, "errors": 2, "error_pct": 1.0},
        ]

        result = get_error_rate_chart(mock_store, limit=10)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["tool"] == "Bash"
        assert result[0]["error_pct"] == 5.0
        mock_store.get_error_rate_by_tool.assert_called_once_with(limit=10)

    def test_handles_empty_data(self):
        """Should return empty list when no error data."""
        mock_store = Mock(spec=DuckDBStore)
        mock_store.get_error_rate_by_tool.return_value = []

        result = get_error_rate_chart(mock_store)

        assert result == []

    def test_default_limit(self):
        """Should default to 20 tools."""
        mock_store = Mock(spec=DuckDBStore)
        mock_store.get_error_rate_by_tool.return_value = []

        get_error_rate_chart(mock_store)

        mock_store.get_error_rate_by_tool.assert_called_once_with(limit=20)
