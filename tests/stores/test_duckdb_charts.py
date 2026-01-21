"""Tests for DuckDB chart query methods."""
import json
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
from lib.stores.duckdb_store import DuckDBStore


@pytest.fixture
def store_with_data():
    """Create store with sample JSONL data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sessions_dir = Path(tmpdir)
        session_file = sessions_dir / "session-test.jsonl"
        events = [
            {
                "timestamp": "2026-01-21T10:00:00Z",
                "session_id": "test",
                "agent_id": "a1",
                "tool": "Read",
                "backend": "native",
                "duration_ms": 100,
                "status": "success",
                "input_tokens": 500,
                "output_tokens": 200,
                "cache_read_tokens": 100,
            },
            {
                "timestamp": "2026-01-21T10:01:00Z",
                "session_id": "test",
                "agent_id": "a1",
                "tool": "Task",
                "backend": "native",
                "duration_ms": 5000,
                "status": "success",
                "input_tokens": 10000,
                "output_tokens": 5000,
                "agent_type": "Explore",
            },
            {
                "timestamp": "2026-01-21T10:02:00Z",
                "session_id": "test",
                "agent_id": "a1",
                "tool": "Bash",
                "backend": "native",
                "duration_ms": 150,
                "status": "error",
            },
        ]
        with open(session_file, "w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        yield DuckDBStore(data_dir=str(sessions_dir))


def test_token_spend_by_day(store_with_data):
    """Test daily token spend aggregation with moving average."""
    results = store_with_data.get_token_spend_by_day()
    assert len(results) >= 1
    assert "day" in results[0]
    assert "total_tokens" in results[0]
    assert "moving_avg_7d" in results[0]


def test_token_spend_by_agent_type(store_with_data):
    """Test token spend grouped by agent type."""
    results = store_with_data.get_token_spend_by_agent_type()
    assert len(results) >= 1
    assert "agent_type" in results[0]
    assert "total_tokens" in results[0]


def test_cache_efficiency_trend(store_with_data):
    """Test cache efficiency trend over time."""
    results = store_with_data.get_cache_efficiency_trend()
    assert isinstance(results, list)
    # May be empty if no cache data, but structure should be correct
    if results:
        assert "day" in results[0]
        assert "cache_pct" in results[0]


def test_tool_latency_by_backend(store_with_data):
    """Test latency statistics per backend."""
    results = store_with_data.get_tool_latency_by_backend()
    assert len(results) >= 1
    native_result = next((r for r in results if r["backend"] == "native"), None)
    assert native_result is not None
    assert "avg_latency" in native_result
    assert "p95" in native_result


def test_error_rate_by_tool(store_with_data):
    """Test error rate calculation per tool."""
    results = store_with_data.get_error_rate_by_tool()
    assert len(results) >= 1
    bash_result = next((r for r in results if r["tool"] == "Bash"), None)
    if bash_result:
        assert bash_result["errors"] >= 1
        assert bash_result["error_pct"] > 0
