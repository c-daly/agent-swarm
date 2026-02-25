#!/usr/bin/env python3
"""Tests for the SQLite event store."""

from datetime import date, datetime

import pytest

from lib.datastore import DataStore, DaySummary, EventRecord, ToolSummary


@pytest.fixture
def store(tmp_path):
    """Create a fresh DataStore with a temp SQLite file."""
    s = DataStore(tmp_path / "test.db")
    yield s
    s.close()


def _make_event(**overrides):
    """Create a minimal event dict with overrides."""
    base = {
        "tool": "native__bash",
        "backend": "native",
        "status": "success",
        "duration_ms": 100,
        "session_id": "sess-1",
        "timestamp": datetime(2026, 1, 30, 12, 0, 0).isoformat(),
    }
    base.update(overrides)
    return base


class TestRecordAndQuery:
    def test_record_and_retrieve(self, store):
        store.record_event(_make_event())
        events = store.get_session_events("sess-1")
        assert len(events) == 1
        assert events[0].tool == "native__bash"
        assert events[0].backend == "native"
        assert isinstance(events[0], EventRecord)

    def test_defaults(self, store):
        store.record_event({"tool": "x", "backend": "y", "status": "success"})
        events = store.query_events(tool="x")
        assert len(events) == 1
        assert events[0].duration_ms == 0
        assert events[0].session_id == ""

    def test_timestamp_defaults_to_now(self, store):
        store.record_event({"tool": "t", "backend": "b", "status": "success"})
        events = store.query_events(tool="t")
        assert len(events) == 1
        assert events[0].timestamp.year >= 2026

    def test_error_event(self, store):
        store.record_event(_make_event(status="error", error_type="BackendError"))
        events = store.query_events(status="error")
        assert len(events) == 1
        assert events[0].error_type == "BackendError"

    def test_query_by_tool(self, store):
        store.record_event(_make_event(tool="bash"))
        store.record_event(_make_event(tool="grep"))
        assert len(store.query_events(tool="bash")) == 1

    def test_query_by_backend(self, store):
        store.record_event(_make_event(backend="serena"))
        store.record_event(_make_event(backend="native"))
        assert len(store.query_events(backend="serena")) == 1

    def test_query_by_session(self, store):
        store.record_event(_make_event(session_id="a"))
        store.record_event(_make_event(session_id="b"))
        assert len(store.query_events(session_id="a")) == 1

    def test_query_limit(self, store):
        for i in range(10):
            store.record_event(_make_event(session_id=f"s-{i}"))
        assert len(store.query_events(limit=5)) == 5

    def test_query_time_range(self, store):
        store.record_event(_make_event(timestamp=datetime(2026, 1, 1, 10, 0).isoformat()))
        store.record_event(_make_event(timestamp=datetime(2026, 1, 2, 10, 0).isoformat()))
        store.record_event(_make_event(timestamp=datetime(2026, 1, 3, 10, 0).isoformat()))
        results = store.query_events(
            start=datetime(2026, 1, 2),
            end=datetime(2026, 1, 2, 23, 59),
        )
        assert len(results) == 1

    def test_query_combined_filters(self, store):
        store.record_event(_make_event(tool="bash", status="success"))
        store.record_event(_make_event(tool="bash", status="error"))
        store.record_event(_make_event(tool="grep", status="error"))
        results = store.query_events(tool="bash", status="error")
        assert len(results) == 1

    def test_summarization_fields(self, store):
        store.record_event(_make_event(
            was_summarized=True,
            original_size=5000,
            summary_size=500,
        ))
        events = store.get_session_events("sess-1")
        assert events[0].was_summarized is True
        assert events[0].original_size == 5000
        assert events[0].summary_size == 500

    def test_token_fields(self, store):
        store.record_event(_make_event(
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=20,
            cache_creation_tokens=10,
        ))
        events = store.get_session_events("sess-1")
        assert events[0].input_tokens == 100
        assert events[0].output_tokens == 50
        assert events[0].cache_read_tokens == 20
        assert events[0].cache_creation_tokens == 10


class TestDailySummary:
    def test_summary(self, store):
        store.record_event(_make_event(
            duration_ms=100, input_tokens=50, output_tokens=30,
        ))
        store.record_event(_make_event(duration_ms=200, status="error"))
        store.record_event(_make_event(duration_ms=300, was_summarized=True))
        summary = store.get_daily_summary(date(2026, 1, 30))
        assert summary is not None
        assert summary.total_calls == 3
        assert summary.total_tokens == 80
        assert summary.error_count == 1
        assert summary.summarization_count == 1
        assert summary.avg_duration_ms == pytest.approx(200.0)

    def test_unique_counts(self, store):
        store.record_event(_make_event(session_id="s1", tool="bash"))
        store.record_event(_make_event(session_id="s1", tool="grep"))
        store.record_event(_make_event(session_id="s2", tool="bash"))
        summary = store.get_daily_summary(date(2026, 1, 30))
        assert summary.unique_sessions == 2
        assert summary.unique_tools == 2

    def test_no_events_returns_none(self, store):
        assert store.get_daily_summary(date(2099, 1, 1)) is None


class TestToolSummaries:
    def test_summaries_ordered_by_count(self, store):
        for _ in range(5):
            store.record_event(_make_event(tool="bash"))
        for _ in range(3):
            store.record_event(_make_event(tool="grep"))
        store.record_event(_make_event(tool="grep", status="error"))

        summaries = store.get_tool_summaries()
        assert len(summaries) == 2
        assert summaries[0].tool_name == "bash"
        assert summaries[0].call_count == 5
        assert summaries[1].tool_name == "grep"
        assert summaries[1].call_count == 4
        assert summaries[1].error_rate == pytest.approx(0.25)

    def test_limit(self, store):
        for i in range(10):
            store.record_event(_make_event(tool=f"tool-{i}"))
        assert len(store.get_tool_summaries(limit=3)) == 3


class TestDataStoreLifecycle:
    def test_persistence_across_connections(self, tmp_path):
        db_path = tmp_path / "persist.db"
        s1 = DataStore(db_path)
        s1.record_event(_make_event())
        s1.close()

        s2 = DataStore(db_path)
        events = s2.get_session_events("sess-1")
        assert len(events) == 1
        s2.close()

    def test_creates_parent_dirs(self, tmp_path):
        db_path = tmp_path / "a" / "b" / "test.db"
        s = DataStore(db_path)
        s.record_event(_make_event())
        s.close()
        assert db_path.exists()

    def test_wal_mode(self, tmp_path):
        s = DataStore(tmp_path / "wal.db")
        mode = s._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        s.close()
