"""Tests for DuckDB store implementation."""

from datetime import date

import pytest

from lib.stores.duckdb_store import DuckDBStore


@pytest.fixture
def store_with_data(tmp_path):
    """Create DuckDBStore with sample event data."""
    store = DuckDBStore(str(tmp_path))
    
    # Insert sample events
    events = [
        {
            "timestamp": "2026-01-20T10:00:00Z",
            "session_id": "abc123",
            "agent_id": "abc123",
            "tool": "mcp__router__serena__find_symbol",
            "backend": "serena",
            "duration_ms": 250,
            "status": "success",
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_read_tokens": 100,
            "cache_creation_tokens": 50,
        },
        {
            "timestamp": "2026-01-20T10:00:01Z",
            "session_id": "abc123",
            "agent_id": "abc123",
            "tool": "mcp__router__native__read_file",
            "backend": "native",
            "duration_ms": 150,
            "status": "success",
            "input_tokens": 500,
            "output_tokens": 2000,
        },
        {
            "timestamp": "2026-01-20T10:00:02Z",
            "session_id": "def456",
            "agent_id": "def456",
            "tool": "Bash",
            "backend": "native",
            "duration_ms": 1000,
            "status": "error",
            "error_type": "timeout",
            "input_tokens": 200,
            "output_tokens": 0,
        },
    ]
    
    for event in events:
        store.insert_event(event)
    
    return store


def test_duckdb_store_init(tmp_path):
    """DuckDBStore initializes with data directory."""
    store = DuckDBStore(str(tmp_path))
    assert store is not None
    assert store.db_path.exists()


def test_duckdb_store_insert_event(tmp_path):
    """DuckDBStore can insert events."""
    store = DuckDBStore(str(tmp_path))
    
    event = {
        "timestamp": "2026-01-20T10:00:00Z",
        "session_id": "test123",
        "agent_id": "test123",
        "tool": "TestTool",
        "backend": "test",
        "duration_ms": 100,
        "status": "success",
    }
    
    store.insert_event(event)
    
    # Verify insertion
    result = store.conn.execute("SELECT COUNT(*) FROM events").fetchone()
    assert result[0] == 1


def test_duckdb_store_get_daily_summary(store_with_data):
    """DuckDBStore can aggregate daily summaries."""
    summary = store_with_data.get_daily_summary(day=date(2026, 1, 20))
    assert summary is not None
    assert summary.date == date(2026, 1, 20)
    assert summary.total_tokens == 4200  # (1000+500) + (500+2000) + (200+0)
    assert summary.tool_calls == 3
    assert summary.sessions == 2  # abc123 and def456


def test_duckdb_store_query_tool_calls(store_with_data):
    """DuckDBStore can query individual tool calls."""
    calls = store_with_data.query_tool_calls()
    assert len(calls) == 3
    # Most recent first
    assert calls[0].tool == "Bash"
    assert calls[0].session_id == "def456"


def test_duckdb_store_query_tool_calls_filtered(store_with_data):
    """DuckDBStore can filter tool calls by session."""
    calls = store_with_data.query_tool_calls(session_id="abc123")
    assert len(calls) == 2
    assert all(c.session_id == "abc123" for c in calls)


def test_duckdb_store_get_sessions(store_with_data):
    """DuckDBStore can list sessions."""
    sessions = store_with_data.get_sessions()
    assert len(sessions) == 2
    session_ids = {s.session_id for s in sessions}
    assert session_ids == {"abc123", "def456"}


def test_duckdb_store_get_tool_summaries(store_with_data):
    """DuckDBStore can aggregate tool summaries."""
    summaries = store_with_data.get_tool_summaries()
    assert len(summaries) >= 1
    # Find the Bash tool summary
    bash_summary = next((s for s in summaries if s.tool_name == "Bash"), None)
    assert bash_summary is not None
    assert bash_summary.call_count == 1


def test_duckdb_store_persistence(tmp_path):
    """DuckDBStore persists data across instances."""
    # Create store and insert data
    store1 = DuckDBStore(str(tmp_path))
    store1.insert_event({
        "timestamp": "2026-01-20T10:00:00Z",
        "session_id": "persist_test",
        "agent_id": "persist_test",
        "tool": "TestTool",
        "backend": "test",
        "duration_ms": 100,
        "status": "success",
    })
    
    # Close and reopen
    store1.conn.close()
    
    store2 = DuckDBStore(str(tmp_path))
    calls = store2.query_tool_calls(session_id="persist_test")
    assert len(calls) == 1
    assert calls[0].tool == "TestTool"
