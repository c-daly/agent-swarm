"""Tests for telemetry store interfaces and implementations."""
import pytest
from datetime import date
from lib.stores.interfaces import (
    AnalyticsStore,
    TraceStore,
    GraphStore,
    DaySummary,
    ToolCallRecord,
)


def test_analytics_store_is_abstract():
    """AnalyticsStore cannot be instantiated directly."""
    with pytest.raises(TypeError):
        AnalyticsStore()


def test_trace_store_is_abstract():
    """TraceStore cannot be instantiated directly."""
    with pytest.raises(TypeError):
        TraceStore()


def test_graph_store_is_abstract():
    """GraphStore cannot be instantiated directly."""
    with pytest.raises(TypeError):
        GraphStore()


def test_day_summary_dataclass():
    """DaySummary holds daily aggregated metrics."""
    summary = DaySummary(
        date=date(2026, 1, 20),
        sessions=5,
        total_tokens=10000,
        tool_calls=50,
        cache_hits=30,
        cache_ratio=0.6,
        summarizations_offered=20,
        summarizations_accepted=15,
        avg_compression_ratio=0.1,
        tokens_saved=5000,
    )
    assert summary.sessions == 5
    assert summary.cache_ratio == 0.6


def test_tool_call_record_dataclass():
    """ToolCallRecord holds individual tool call data."""
    record = ToolCallRecord(
        session_id="abc123",
        turn_id="turn1",
        timestamp="2026-01-20T10:00:00Z",
        tool="mcp__router__serena__find_symbol",
        duration_ms=250,
        response_size=5000,
        is_cache_hit=False,
        summary_size=500,
        full_requested=True,
        parent_uuid=None,
        is_sidechain=False,
        git_branch="main",
    )
    assert record.tool == "mcp__router__serena__find_symbol"
    assert record.full_requested is True


# Validation tests
from lib.stores.validation import validate_day_summary, validate_tool_call


def test_validate_day_summary_clean():
    """Clean data passes validation with high confidence."""
    summary = DaySummary(
        date=date(2026, 1, 20),
        sessions=5,
        total_tokens=10000,
        tool_calls=50,
        cache_hits=30,
        cache_ratio=0.6,
        summarizations_offered=20,
        summarizations_accepted=15,
        avg_compression_ratio=0.1,
        tokens_saved=5000,
    )
    result = validate_day_summary(summary)
    assert result.confidence == 1.0
    assert len(result.warnings) == 0


def test_validate_day_summary_calls_no_tokens():
    """Calls without tokens triggers warning."""
    summary = DaySummary(
        date=date(2026, 1, 20),
        sessions=5,
        total_tokens=0,
        tool_calls=50,
        cache_hits=30,
        cache_ratio=0.6,
        summarizations_offered=20,
        summarizations_accepted=15,
        avg_compression_ratio=0.1,
        tokens_saved=0,
    )
    result = validate_day_summary(summary)
    assert result.confidence < 1.0
    assert any("calls but 0 tokens" in w for w in result.warnings)


def test_validate_day_summary_invalid_cache_ratio():
    """Cache ratio > 1.0 triggers warning."""
    summary = DaySummary(
        date=date(2026, 1, 20),
        sessions=5,
        total_tokens=10000,
        tool_calls=50,
        cache_hits=60,
        cache_ratio=1.2,
        summarizations_offered=20,
        summarizations_accepted=15,
        avg_compression_ratio=0.1,
        tokens_saved=5000,
    )
    result = validate_day_summary(summary)
    assert result.confidence < 1.0
    assert any("cache ratio" in w.lower() for w in result.warnings)


def test_validate_tool_call_missing_summary():
    """Tool call with full_requested but no summary_size triggers warning."""
    record = ToolCallRecord(
        session_id="abc123",
        turn_id="turn1",
        timestamp="2026-01-20T10:00:00Z",
        tool="mcp__router__serena__find_symbol",
        duration_ms=250,
        response_size=5000,
        is_cache_hit=False,
        summary_size=None,
        full_requested=True,
        parent_uuid=None,
        is_sidechain=False,
        git_branch="main",
    )
    result = validate_tool_call(record)
    assert result.confidence < 1.0
    assert any("full_requested" in w for w in result.warnings)
