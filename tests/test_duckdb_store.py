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


def test_get_summarization_callback_rate_empty(tmp_path):
    """Callback rate returns zeros when no data."""
    store = DuckDBStore(str(tmp_path))
    result = store.get_summarization_callback_rate(days=7)
    
    assert result["total_offered"] == 0
    assert result["total_retrieved"] == 0
    assert result["callback_rate"] == 0.0
    assert result["days"] == 7


def test_get_summarization_callback_rate_with_data(tmp_path):
    """Callback rate calculates correctly from content_retrievals."""
    store = DuckDBStore(str(tmp_path))
    
    # Create 3 summaries
    store.record_content_creation("c001")
    store.record_content_creation("c002")
    store.record_content_creation("c003")
    
    # Retrieve 1 of them
    store.record_content_retrieval("c002")
    
    result = store.get_summarization_callback_rate(days=7)
    
    assert result["total_offered"] == 3
    assert result["total_retrieved"] == 1
    assert result["callback_rate"] == pytest.approx(0.333, rel=0.01)


# ─────────────────────────────────────────────────────────────────────────────
# Summarization Metrics Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def store_with_summarization_data(tmp_path):
    """Create DuckDBStore with events that have summarization data."""
    store = DuckDBStore(str(tmp_path))

    # Event 1: Summarized, original=1000, summary=200 (compression=0.2, saved=200 tokens)
    store.insert_event({
        "timestamp": "2026-01-20T10:00:00Z",
        "session_id": "summ_session",
        "agent_id": "summ_session",
        "tool": "mcp__router__serena__read_file",
        "backend": "serena",
        "duration_ms": 100,
        "status": "success",
        "input_tokens": 500,
        "output_tokens": 200,
        "was_summarized": True,
        "original_size": 1000,
        "summary_size": 200,
    })

    # Event 2: Summarized, original=2000, summary=400 (compression=0.2, saved=400 tokens)
    store.insert_event({
        "timestamp": "2026-01-20T10:00:01Z",
        "session_id": "summ_session",
        "agent_id": "summ_session",
        "tool": "mcp__router__native__read_file",
        "backend": "native",
        "duration_ms": 50,
        "status": "success",
        "input_tokens": 400,
        "output_tokens": 100,
        "was_summarized": True,
        "original_size": 2000,
        "summary_size": 400,
    })

    # Event 3: Summarized, original=500, summary=200 (compression=0.4, saved=75 tokens)
    store.insert_event({
        "timestamp": "2026-01-20T10:00:02Z",
        "session_id": "summ_session",
        "agent_id": "summ_session",
        "tool": "mcp__router__serena__find_symbol",
        "backend": "serena",
        "duration_ms": 200,
        "status": "success",
        "input_tokens": 200,
        "output_tokens": 50,
        "was_summarized": True,
        "original_size": 500,
        "summary_size": 200,
    })

    # Event 4: NOT summarized (should be excluded from summarization metrics)
    store.insert_event({
        "timestamp": "2026-01-20T10:00:03Z",
        "session_id": "summ_session",
        "agent_id": "summ_session",
        "tool": "Bash",
        "backend": "native",
        "duration_ms": 300,
        "status": "success",
        "input_tokens": 100,
        "output_tokens": 50,
        "was_summarized": False,
        "original_size": None,
        "summary_size": None,
    })

    return store


def test_daily_summary_summarizations_offered(store_with_summarization_data):
    """summarizations_offered counts events where was_summarized=True."""
    summary = store_with_summarization_data.get_daily_summary(day=date(2026, 1, 20))

    assert summary is not None
    # 3 events have was_summarized=True
    assert summary.summarizations_offered == 3


def test_daily_summary_summarizations_accepted(store_with_summarization_data):
    """summarizations_accepted equals summarizations_offered for now."""
    summary = store_with_summarization_data.get_daily_summary(day=date(2026, 1, 20))

    assert summary is not None
    # For now, accepted = offered (all summaries are implicitly accepted)
    assert summary.summarizations_accepted == summary.summarizations_offered
    assert summary.summarizations_accepted == 3


def test_daily_summary_avg_compression_ratio(store_with_summarization_data):
    """avg_compression_ratio is average of (summary_size/original_size)."""
    summary = store_with_summarization_data.get_daily_summary(day=date(2026, 1, 20))

    assert summary is not None
    # Event 1: 200/1000 = 0.2
    # Event 2: 400/2000 = 0.2
    # Event 3: 200/500 = 0.4
    # Average: (0.2 + 0.2 + 0.4) / 3 = 0.8 / 3 = 0.2666...
    expected_ratio = (0.2 + 0.2 + 0.4) / 3
    assert float(summary.avg_compression_ratio) == pytest.approx(expected_ratio, rel=0.01)


def test_daily_summary_tokens_saved(store_with_summarization_data):
    """tokens_saved is sum of (original_size - summary_size) / 4."""
    summary = store_with_summarization_data.get_daily_summary(day=date(2026, 1, 20))

    assert summary is not None
    # Event 1: (1000 - 200) / 4 = 200
    # Event 2: (2000 - 400) / 4 = 400
    # Event 3: (500 - 200) / 4 = 75
    # Total: 200 + 400 + 75 = 675
    assert summary.tokens_saved == 675


def test_daily_summary_no_summarization_data(tmp_path):
    """All summarization metrics are zero when no summarized events exist."""
    store = DuckDBStore(str(tmp_path))

    # Insert event without summarization data
    store.insert_event({
        "timestamp": "2026-01-20T10:00:00Z",
        "session_id": "no_summ",
        "agent_id": "no_summ",
        "tool": "Bash",
        "backend": "native",
        "duration_ms": 100,
        "status": "success",
        "input_tokens": 100,
        "output_tokens": 50,
        "was_summarized": False,
    })

    summary = store.get_daily_summary(day=date(2026, 1, 20))

    assert summary is not None
    assert summary.summarizations_offered == 0
    assert summary.summarizations_accepted == 0
    assert summary.avg_compression_ratio == 0.0
    assert summary.tokens_saved == 0
