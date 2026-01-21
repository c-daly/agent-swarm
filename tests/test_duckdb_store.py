"""Tests for DuckDB store implementation."""

import json
from datetime import date

import pytest

from lib.stores.duckdb_store import DuckDBStore


@pytest.fixture
def sample_jsonl(tmp_path):
    """Create sample JSONL data for testing."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()

    jsonl_file = project_dir / "session-abc123.jsonl"

    events = [
        {
            "type": "assistant",
            "timestamp": "2026-01-20T10:00:00Z",
            "uuid": "turn1",
            "sessionId": "abc123",
            "costUSD": 0.05,
            "durationMs": 1500,
            "message": {"usage": {"input_tokens": 1000, "output_tokens": 500}},
        },
        {
            "type": "tool_use",
            "timestamp": "2026-01-20T10:00:01Z",
            "uuid": "tool1",
            "sessionId": "abc123",
            "toolName": "mcp__router__serena__find_symbol",
            "durationMs": 250,
        },
        {
            "type": "tool_result",
            "timestamp": "2026-01-20T10:00:02Z",
            "uuid": "result1",
            "sessionId": "abc123",
            "toolUseResult": {"content": "x" * 5000},
        },
    ]

    with open(jsonl_file, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    return tmp_path


def test_duckdb_store_init(sample_jsonl):
    """DuckDBStore initializes with data directory."""
    store = DuckDBStore(str(sample_jsonl))
    assert store is not None


def test_duckdb_store_get_daily_summary(sample_jsonl):
    """DuckDBStore can aggregate daily summaries."""
    store = DuckDBStore(str(sample_jsonl))
    summary = store.get_daily_summary(day=date(2026, 1, 20))
    assert summary is not None
    assert summary.date == date(2026, 1, 20)
    assert summary.total_tokens > 0


def test_duckdb_store_query_tool_calls(sample_jsonl):
    """DuckDBStore can query individual tool calls."""
    store = DuckDBStore(str(sample_jsonl))
    calls = store.query_tool_calls()
    assert len(calls) >= 1
    assert calls[0].tool == "mcp__router__serena__find_symbol"


def test_duckdb_store_get_sessions(sample_jsonl):
    """DuckDBStore can list sessions."""
    store = DuckDBStore(str(sample_jsonl))
    sessions = store.get_sessions()
    assert len(sessions) >= 1
    assert sessions[0].session_id == "abc123"
