"""Integration tests for telemetry v3 pipeline.

Tests end-to-end flow from event creation through JSONL writing,
compression, and DuckDB querying.
"""

import gzip
import json
import os
import time

import pytest

from lib.stores.compression import compress_old_sessions
from lib.stores.duckdb_store import DuckDBStore
from lib.stores.events import ToolCallEvent
from lib.stores.jsonl_writer import JSONLWriter


class TestEventWritingPipeline:
    """Test ToolCallEvent creation and JSONL writing."""

    def test_create_tool_call_event(self):
        """ToolCallEvent can be created with required fields."""
        event = ToolCallEvent(
            timestamp="2026-01-20T10:00:00Z",
            session_id="sess-001",
            agent_id="agent-001",
            tool="mcp__router__serena__find_symbol",
            backend="serena",
            duration_ms=250,
            status="success",
        )
        assert event.tool == "mcp__router__serena__find_symbol"
        assert event.status == "success"
        assert event.input_tokens == 0  # default

    def test_event_to_dict_excludes_none(self):
        """to_dict excludes None values for compact JSONL."""
        event = ToolCallEvent(
            timestamp="2026-01-20T10:00:00Z",
            session_id="sess-001",
            agent_id="agent-001",
            tool="test_tool",
            backend="native",
            duration_ms=100,
            status="success",
            error_type=None,
            agent_type=None,
        )
        d = event.to_dict()
        assert "error_type" not in d
        assert "agent_type" not in d
        assert "timestamp" in d

    def test_jsonl_writer_creates_session_file(self, tmp_path):
        """JSONLWriter creates session-specific JSONL files."""
        writer = JSONLWriter(str(tmp_path))
        event = ToolCallEvent(
            timestamp="2026-01-20T10:00:00Z",
            session_id="sess-abc",
            agent_id="agent-001",
            tool="test_tool",
            backend="native",
            duration_ms=100,
            status="success",
        )
        writer.write(event)

        session_file = tmp_path / "session-sess-abc.jsonl"
        assert session_file.exists()

    def test_jsonl_writer_appends_events(self, tmp_path):
        """Multiple events are appended to same session file."""
        writer = JSONLWriter(str(tmp_path))

        for i in range(3):
            event = ToolCallEvent(
                timestamp=f"2026-01-20T10:00:0{i}Z",
                session_id="sess-abc",
                agent_id="agent-001",
                tool=f"tool_{i}",
                backend="native",
                duration_ms=100 + i,
                status="success",
            )
            writer.write(event)

        session_file = tmp_path / "session-sess-abc.jsonl"
        lines = session_file.read_text().strip().split("\n")
        assert len(lines) == 3

        # Verify each line is valid JSON
        for line in lines:
            data = json.loads(line)
            assert "tool" in data
            assert "timestamp" in data

    def test_jsonl_content_matches_event(self, tmp_path):
        """Written JSONL content matches original event data."""
        writer = JSONLWriter(str(tmp_path))
        event = ToolCallEvent(
            timestamp="2026-01-20T10:00:00Z",
            session_id="sess-xyz",
            agent_id="agent-001",
            tool="mcp__router__serena__read_file",
            backend="serena",
            duration_ms=500,
            status="success",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=200,
            agent_type="Implementer",
        )
        writer.write(event)

        session_file = tmp_path / "session-sess-xyz.jsonl"
        data = json.loads(session_file.read_text().strip())

        assert data["timestamp"] == "2026-01-20T10:00:00Z"
        assert data["session_id"] == "sess-xyz"
        assert data["tool"] == "mcp__router__serena__read_file"
        assert data["backend"] == "serena"
        assert data["duration_ms"] == 500
        assert data["status"] == "success"
        assert data["input_tokens"] == 1000
        assert data["output_tokens"] == 500
        assert data["cache_read_tokens"] == 200
        assert data["agent_type"] == "Implementer"


class TestDuckDBQueryPipeline:
    """Test DuckDB querying of JSONL telemetry files."""

    @pytest.fixture
    def v3_jsonl_data(self, tmp_path):
        """Create v3 format JSONL files for testing."""
        # Session 1: Multiple tools, success events
        session1_events = [
            {
                "timestamp": "2026-01-20T10:00:00Z",
                "session_id": "sess-001",
                "agent_id": "agent-main",
                "tool": "mcp__router__serena__find_symbol",
                "backend": "serena",
                "duration_ms": 250,
                "status": "success",
                "input_tokens": 500,
                "output_tokens": 200,
                "cache_read_tokens": 100,
                "agent_type": "Implementer",
            },
            {
                "timestamp": "2026-01-20T10:00:01Z",
                "session_id": "sess-001",
                "agent_id": "agent-main",
                "tool": "mcp__router__serena__read_file",
                "backend": "serena",
                "duration_ms": 150,
                "status": "success",
                "input_tokens": 300,
                "output_tokens": 1000,
                "cache_read_tokens": 50,
                "agent_type": "Implementer",
            },
            {
                "timestamp": "2026-01-20T10:00:02Z",
                "session_id": "sess-001",
                "agent_id": "agent-main",
                "tool": "mcp__router__native__bash",
                "backend": "native",
                "duration_ms": 1000,
                "status": "error",
                "error_type": "timeout",
                "input_tokens": 100,
                "output_tokens": 50,
            },
        ]

        # Session 2: Different day, different agent type
        session2_events = [
            {
                "timestamp": "2026-01-21T14:00:00Z",
                "session_id": "sess-002",
                "agent_id": "agent-explore",
                "tool": "mcp__router__serena__search_for_pattern",
                "backend": "serena",
                "duration_ms": 500,
                "status": "success",
                "input_tokens": 800,
                "output_tokens": 400,
                "agent_type": "Explore",
            },
        ]

        # Write session files
        sess1_file = tmp_path / "session-sess-001.jsonl"
        with open(sess1_file, "w") as f:
            for event in session1_events:
                f.write(json.dumps(event) + "\n")

        sess2_file = tmp_path / "session-sess-002.jsonl"
        with open(sess2_file, "w") as f:
            for event in session2_events:
                f.write(json.dumps(event) + "\n")

        return tmp_path

    def test_duckdb_store_reads_v3_events(self, v3_jsonl_data):
        """DuckDBStore can read v3 format JSONL files."""
        store = DuckDBStore(str(v3_jsonl_data))
        # Just verify initialization works with v3 data
        assert store is not None

    def test_token_spend_by_day(self, v3_jsonl_data):
        """get_token_spend_by_day returns daily aggregations."""
        store = DuckDBStore(str(v3_jsonl_data))
        result = store.get_token_spend_by_day(days=30)

        assert len(result) >= 1
        # Check structure
        for row in result:
            assert "day" in row
            assert "total_tokens" in row
            assert "moving_avg_7d" in row

    def test_token_spend_by_agent_type(self, v3_jsonl_data):
        """get_token_spend_by_agent_type groups by agent_type."""
        store = DuckDBStore(str(v3_jsonl_data))
        result = store.get_token_spend_by_agent_type()

        assert len(result) >= 1
        agent_types = {r["agent_type"] for r in result}
        # Should have Implementer from session 1, Explore from session 2
        assert "Implementer" in agent_types or "Explore" in agent_types

        for row in result:
            assert "agent_type" in row
            assert "total_tokens" in row
            assert "sessions" in row

    def test_cache_efficiency_trend(self, v3_jsonl_data):
        """get_cache_efficiency_trend calculates cache percentages."""
        store = DuckDBStore(str(v3_jsonl_data))
        result = store.get_cache_efficiency_trend(days=30)

        assert len(result) >= 1
        for row in result:
            assert "day" in row
            assert "cached" in row
            assert "total_input" in row
            assert "cache_pct" in row

    def test_tool_latency_by_backend(self, v3_jsonl_data):
        """get_tool_latency_by_backend shows latency stats per backend."""
        store = DuckDBStore(str(v3_jsonl_data))
        result = store.get_tool_latency_by_backend()

        assert len(result) >= 1
        backends = {r["backend"] for r in result}
        # Should have both serena and native backends
        assert "serena" in backends or "native" in backends

        for row in result:
            assert "backend" in row
            assert "avg_latency" in row
            assert "p95" in row

    def test_error_rate_by_tool(self, v3_jsonl_data):
        """get_error_rate_by_tool calculates error percentages."""
        store = DuckDBStore(str(v3_jsonl_data))
        result = store.get_error_rate_by_tool()

        assert len(result) >= 1
        # Find the bash tool which had an error
        bash_row = next(
            (r for r in result if "bash" in r["tool"]),
            None
        )
        if bash_row:
            assert bash_row["errors"] >= 1
            assert bash_row["error_pct"] > 0

        for row in result:
            assert "tool" in row
            assert "total_calls" in row
            assert "errors" in row
            assert "error_pct" in row


class TestCompressionPipeline:
    """Test session file compression."""

    def test_compress_old_sessions_skips_recent(self, tmp_path):
        """Recent files are not compressed."""
        # Create a recent JSONL file
        recent_file = tmp_path / "session-recent.jsonl"
        recent_file.write_text('{"test": "data"}\n')

        count = compress_old_sessions(tmp_path, max_age_hours=24)

        assert count == 0
        assert recent_file.exists()
        assert not (tmp_path / "session-recent.jsonl.gz").exists()

    def test_compress_old_sessions_compresses_old(self, tmp_path):
        """Old files are compressed to .jsonl.gz."""
        # Create a file and modify its mtime to simulate age
        old_file = tmp_path / "session-old.jsonl"
        old_file.write_text('{"test": "old_data"}\n')

        # Set mtime to 48 hours ago
        old_time = time.time() - (48 * 3600)
        os.utime(old_file, (old_time, old_time))

        count = compress_old_sessions(tmp_path, max_age_hours=24)

        assert count == 1
        assert not old_file.exists()
        assert (tmp_path / "session-old.jsonl.gz").exists()

    def test_compressed_content_readable(self, tmp_path):
        """Compressed files contain correct data."""
        old_file = tmp_path / "session-verify.jsonl"
        original_data = '{"tool": "test", "status": "success"}\n'
        old_file.write_text(original_data)

        # Set old mtime
        old_time = time.time() - (48 * 3600)
        os.utime(old_file, (old_time, old_time))

        compress_old_sessions(tmp_path, max_age_hours=24)

        gz_file = tmp_path / "session-verify.jsonl.gz"
        with gzip.open(gz_file, "rt") as f:
            content = f.read()

        assert content == original_data

    def test_duckdb_reads_gzipped_files(self, tmp_path):
        """DuckDB can query compressed .jsonl.gz files."""
        # Create a gzipped file directly
        gz_file = tmp_path / "session-compressed.jsonl.gz"
        event = {
            "timestamp": "2026-01-20T10:00:00Z",
            "session_id": "sess-gz",
            "agent_id": "agent-001",
            "tool": "test_tool",
            "backend": "native",
            "duration_ms": 100,
            "status": "success",
            "input_tokens": 500,
            "output_tokens": 200,
        }
        with gzip.open(gz_file, "wt") as f:
            f.write(json.dumps(event) + "\n")

        store = DuckDBStore(str(tmp_path))
        result = store.get_token_spend_by_day(days=30)

        assert len(result) >= 1
        # Verify tokens were read from gzipped file
        total = sum(r["total_tokens"] for r in result)
        assert total == 700  # 500 + 200

    def test_duckdb_reads_mixed_files(self, tmp_path):
        """DuckDB can query both .jsonl and .jsonl.gz in same directory."""
        # Create uncompressed file
        jsonl_file = tmp_path / "session-raw.jsonl"
        raw_event = {
            "timestamp": "2026-01-20T10:00:00Z",
            "session_id": "sess-raw",
            "agent_id": "agent-001",
            "tool": "raw_tool",
            "backend": "native",
            "duration_ms": 100,
            "status": "success",
            "input_tokens": 100,
            "output_tokens": 50,
        }
        with open(jsonl_file, "w") as f:
            f.write(json.dumps(raw_event) + "\n")

        # Create compressed file
        gz_file = tmp_path / "session-gz.jsonl.gz"
        gz_event = {
            "timestamp": "2026-01-20T11:00:00Z",
            "session_id": "sess-gz",
            "agent_id": "agent-002",
            "tool": "gz_tool",
            "backend": "serena",
            "duration_ms": 200,
            "status": "success",
            "input_tokens": 200,
            "output_tokens": 100,
        }
        with gzip.open(gz_file, "wt") as f:
            f.write(json.dumps(gz_event) + "\n")

        store = DuckDBStore(str(tmp_path))
        result = store.get_token_spend_by_day(days=30)

        # Should have combined tokens from both files
        total = sum(r["total_tokens"] for r in result)
        assert total == 450  # (100+50) + (200+100)


class TestEndToEndFlow:
    """Test complete telemetry pipeline from write to query."""

    def test_write_and_query_single_session(self, tmp_path):
        """Write events with JSONLWriter, query with DuckDBStore."""
        writer = JSONLWriter(str(tmp_path))

        # Write multiple events
        events = [
            ToolCallEvent(
                timestamp="2026-01-20T10:00:00Z",
                session_id="e2e-sess",
                agent_id="agent-001",
                tool="tool_a",
                backend="native",
                duration_ms=100,
                status="success",
                input_tokens=500,
                output_tokens=200,
            ),
            ToolCallEvent(
                timestamp="2026-01-20T10:00:01Z",
                session_id="e2e-sess",
                agent_id="agent-001",
                tool="tool_b",
                backend="serena",
                duration_ms=250,
                status="success",
                input_tokens=300,
                output_tokens=150,
                cache_read_tokens=100,
            ),
            ToolCallEvent(
                timestamp="2026-01-20T10:00:02Z",
                session_id="e2e-sess",
                agent_id="agent-001",
                tool="tool_c",
                backend="native",
                duration_ms=50,
                status="error",
                error_type="not_found",
                input_tokens=100,
                output_tokens=20,
            ),
        ]
        for event in events:
            writer.write(event)

        # Query with DuckDB
        store = DuckDBStore(str(tmp_path))

        # Check token spend
        token_data = store.get_token_spend_by_day(days=30)
        assert len(token_data) == 1
        assert token_data[0]["total_tokens"] == 1270  # sum of all tokens

        # Check error rates
        error_data = store.get_error_rate_by_tool()
        tool_c = next((r for r in error_data if r["tool"] == "tool_c"), None)
        assert tool_c is not None
        assert tool_c["error_pct"] == 100.0

        # Check latency by backend
        latency_data = store.get_tool_latency_by_backend()
        native = next((r for r in latency_data if r["backend"] == "native"), None)
        assert native is not None
        # Native has tool_a (100ms) and tool_c (50ms), avg should be 75
        assert native["avg_latency"] == 75.0

    def test_write_multiple_sessions_query_aggregated(self, tmp_path):
        """Write events across sessions, verify aggregation."""
        writer = JSONLWriter(str(tmp_path))

        # Session 1: Implementer agent
        for i in range(5):
            event = ToolCallEvent(
                timestamp=f"2026-01-20T10:00:0{i}Z",
                session_id="sess-impl",
                agent_id="agent-impl",
                tool="serena_tool",
                backend="serena",
                duration_ms=200,
                status="success",
                input_tokens=100,
                output_tokens=50,
                agent_type="Implementer",
            )
            writer.write(event)

        # Session 2: Explore agent
        for i in range(3):
            event = ToolCallEvent(
                timestamp=f"2026-01-20T11:00:0{i}Z",
                session_id="sess-explore",
                agent_id="agent-explore",
                tool="search_tool",
                backend="serena",
                duration_ms=300,
                status="success",
                input_tokens=200,
                output_tokens=100,
                agent_type="Explore",
            )
            writer.write(event)

        store = DuckDBStore(str(tmp_path))

        # Check agent type breakdown
        agent_data = store.get_token_spend_by_agent_type()
        impl = next((r for r in agent_data if r["agent_type"] == "Implementer"), None)
        explore = next((r for r in agent_data if r["agent_type"] == "Explore"), None)

        assert impl is not None
        assert impl["total_tokens"] == 750  # 5 * (100 + 50)
        assert impl["sessions"] == 1

        assert explore is not None
        assert explore["total_tokens"] == 900  # 3 * (200 + 100)
        assert explore["sessions"] == 1

    def test_write_compress_query_flow(self, tmp_path):
        """Full flow: write events, compress old, query all."""
        writer = JSONLWriter(str(tmp_path))

        # Write old session
        old_event = ToolCallEvent(
            timestamp="2026-01-15T10:00:00Z",
            session_id="old-sess",
            agent_id="agent-old",
            tool="old_tool",
            backend="native",
            duration_ms=100,
            status="success",
            input_tokens=1000,
            output_tokens=500,
        )
        writer.write(old_event)

        # Simulate old file by modifying mtime
        old_file = tmp_path / "session-old-sess.jsonl"
        old_time = time.time() - (48 * 3600)
        os.utime(old_file, (old_time, old_time))

        # Write new session
        new_event = ToolCallEvent(
            timestamp="2026-01-20T10:00:00Z",
            session_id="new-sess",
            agent_id="agent-new",
            tool="new_tool",
            backend="serena",
            duration_ms=200,
            status="success",
            input_tokens=500,
            output_tokens=250,
        )
        writer.write(new_event)

        # Compress old sessions
        compressed = compress_old_sessions(tmp_path, max_age_hours=24)
        assert compressed == 1

        # Verify file states
        assert not (tmp_path / "session-old-sess.jsonl").exists()
        assert (tmp_path / "session-old-sess.jsonl.gz").exists()
        assert (tmp_path / "session-new-sess.jsonl").exists()

        # Query should include both
        store = DuckDBStore(str(tmp_path))
        token_data = store.get_token_spend_by_day(days=30)

        total_tokens = sum(r["total_tokens"] for r in token_data)
        assert total_tokens == 2250  # (1000+500) + (500+250)

    def test_cache_efficiency_calculation(self, tmp_path):
        """Verify cache efficiency is calculated correctly."""
        writer = JSONLWriter(str(tmp_path))

        # Event with cache hit
        event1 = ToolCallEvent(
            timestamp="2026-01-20T10:00:00Z",
            session_id="cache-sess",
            agent_id="agent-001",
            tool="cached_tool",
            backend="serena",
            duration_ms=100,
            status="success",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=800,  # 80% cache hit
        )
        writer.write(event1)

        # Event without cache
        event2 = ToolCallEvent(
            timestamp="2026-01-20T10:00:01Z",
            session_id="cache-sess",
            agent_id="agent-001",
            tool="uncached_tool",
            backend="native",
            duration_ms=200,
            status="success",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=0,
        )
        writer.write(event2)

        store = DuckDBStore(str(tmp_path))
        cache_data = store.get_cache_efficiency_trend(days=30)

        assert len(cache_data) == 1
        day_data = cache_data[0]
        assert day_data["cached"] == 800
        assert day_data["total_input"] == 2000  # 1000 + 1000
        assert day_data["cache_pct"] == 40.0  # 800/2000 * 100
