"""Tests for dashboard/import.py."""

import importlib
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# import.py is a reserved keyword module name, use importlib
_import_mod = importlib.import_module("dashboard.import")

init_db = _import_mod.init_db
derive_backend = _import_mod.derive_backend
detect_error = _import_mod.detect_error
extract_agent_id_from_filename = _import_mod.extract_agent_id_from_filename
parse_jsonl_file = _import_mod.parse_jsonl_file
find_jsonl_files = _import_mod.find_jsonl_files
dedup_check_duckdb = _import_mod.dedup_check_duckdb
dedup_check_jsonl = _import_mod.dedup_check_jsonl


class TestInitDb:
    def test_creates_tables(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "events" in tables
        assert "import_log" in tables
        assert "session_files" in tables
        assert "content_retrievals" in tables
        assert "agent_types" in tables
        conn.close()

    def test_creates_view(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)
        views = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()]
        assert "v_sessions" in views
        conn.close()

    def test_creates_indexes(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)
        indexes = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()]
        assert "idx_events_timestamp" in indexes
        assert "idx_events_session" in indexes
        assert "idx_events_tool" in indexes
        conn.close()


class TestDeriveBackend:
    def test_router(self):
        assert derive_backend("mcp__router__serena__read_file") == "router"

    def test_plugin(self):
        assert derive_backend("mcp__plugin_memory__search") == "plugin"

    def test_mcp_generic(self):
        assert derive_backend("mcp__context7__query") == "mcp"

    def test_claude_tools(self):
        assert derive_backend("Task") == "claude"
        assert derive_backend("Skill") == "claude"
        assert derive_backend("WebFetch") == "claude"
        assert derive_backend("TaskCreate") == "claude"

    def test_native(self):
        assert derive_backend("Read") == "native"
        assert derive_backend("Bash") == "native"
        assert derive_backend("Edit") == "native"
        assert derive_backend("Write") == "native"


class TestDetectError:
    def test_dict_is_error(self):
        is_err, msg = detect_error({"isError": True, "content": "some error"})
        assert is_err is True
        assert "some error" in msg

    def test_dict_error_key(self):
        is_err, msg = detect_error({"error": "connection failed"})
        assert is_err is True
        assert "connection failed" in msg

    def test_string_error(self):
        is_err, msg = detect_error("Error: file not found")
        assert is_err is True

    def test_string_exception(self):
        is_err, msg = detect_error("Exception: something broke")
        assert is_err is True

    def test_no_error(self):
        is_err, msg = detect_error("all good")
        assert is_err is False
        assert msg == ""

    def test_no_error_dict(self):
        is_err, msg = detect_error({"result": "ok"})
        assert is_err is False

    def test_truncates_to_200(self):
        is_err, msg = detect_error("Error: " + "x" * 500)
        assert is_err is True
        assert len(msg) <= 200


class TestExtractAgentId:
    def test_main_session(self):
        p = Path("/projects/slug/abc123.jsonl")
        assert extract_agent_id_from_filename(p) is None

    def test_subagent(self):
        p = Path("/projects/slug/abc123/subagents/agent-def456.jsonl")
        assert extract_agent_id_from_filename(p) == "def456"

    def test_not_agent_prefix(self):
        p = Path("/projects/slug/abc123/subagents/something.jsonl")
        assert extract_agent_id_from_filename(p) is None


class TestParseJsonlFile:
    def _make_jsonl(self, tmp_path, entries):
        f = tmp_path / "session.jsonl"
        f.write_text("\n".join(json.dumps(e) for e in entries))
        return f

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        assert parse_jsonl_file(f) == []

    def test_single_tool_call(self, tmp_path):
        entries = [
            {
                "type": "assistant",
                "timestamp": "2026-01-30T10:00:00.000Z",
                "sessionId": "sess-1",
                "message": {
                    "role": "assistant",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_001",
                            "name": "Read",
                            "input": {"file_path": "/tmp/test.py"},
                        }
                    ],
                },
            },
            {
                "type": "user",
                "timestamp": "2026-01-30T10:00:01.000Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_001",
                            "content": "file contents here",
                        }
                    ]
                },
            },
        ]
        f = self._make_jsonl(tmp_path, entries)
        events = parse_jsonl_file(f)
        assert len(events) == 1
        evt = events[0]
        assert evt["tool"] == "Read"
        assert evt["backend"] == "native"
        assert evt["session_id"] == "sess-1"
        assert evt["input_tokens"] == 100
        assert evt["output_tokens"] == 50
        assert evt["status"] == "success"
        assert evt["tool_use_id"] == "toolu_001"
        assert evt["duration_ms"] == 1000

    def test_multiple_tools_divides_tokens(self, tmp_path):
        entries = [
            {
                "type": "assistant",
                "timestamp": "2026-01-30T10:00:00.000Z",
                "sessionId": "sess-1",
                "message": {
                    "role": "assistant",
                    "usage": {
                        "input_tokens": 200,
                        "output_tokens": 100,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                    "content": [
                        {"type": "tool_use", "id": "toolu_001", "name": "Read", "input": {}},
                        {"type": "tool_use", "id": "toolu_002", "name": "Read", "input": {}},
                    ],
                },
            },
            {
                "type": "user",
                "timestamp": "2026-01-30T10:00:01.000Z",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "toolu_001", "content": "ok"},
                        {"type": "tool_result", "tool_use_id": "toolu_002", "content": "ok"},
                    ]
                },
            },
        ]
        f = self._make_jsonl(tmp_path, entries)
        events = parse_jsonl_file(f)
        assert len(events) == 2
        assert events[0]["input_tokens"] == 100
        assert events[1]["input_tokens"] == 100

    def test_error_detection(self, tmp_path):
        entries = [
            {
                "type": "assistant",
                "timestamp": "2026-01-30T10:00:00.000Z",
                "sessionId": "sess-1",
                "message": {
                    "role": "assistant",
                    "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                    "content": [
                        {"type": "tool_use", "id": "toolu_001", "name": "Bash", "input": {}},
                    ],
                },
            },
            {
                "type": "user",
                "timestamp": "2026-01-30T10:00:01.000Z",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "toolu_001", "content": "Error: command not found"},
                    ]
                },
            },
        ]
        f = self._make_jsonl(tmp_path, entries)
        events = parse_jsonl_file(f)
        assert len(events) == 1
        assert events[0]["status"] == "error"
        assert "command not found" in events[0]["error_type"]

    def test_mcp_router_backend(self, tmp_path):
        entries = [
            {
                "type": "assistant",
                "timestamp": "2026-01-30T10:00:00.000Z",
                "sessionId": "sess-1",
                "message": {
                    "role": "assistant",
                    "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                    "content": [
                        {"type": "tool_use", "id": "toolu_001", "name": "mcp__router__serena__read_file", "input": {}},
                    ],
                },
            },
        ]
        f = self._make_jsonl(tmp_path, entries)
        events = parse_jsonl_file(f)
        assert events[0]["backend"] == "router"

    def test_import_source_tag(self, tmp_path):
        entries = [
            {
                "type": "assistant",
                "timestamp": "2026-01-30T10:00:00.000Z",
                "sessionId": "sess-1",
                "message": {
                    "role": "assistant",
                    "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                    "content": [
                        {"type": "tool_use", "id": "toolu_001", "name": "Read", "input": {}},
                    ],
                },
            },
        ]
        f = self._make_jsonl(tmp_path, entries)
        events = parse_jsonl_file(f)
        assert events[0]["import_source"] == "claude_transcript"


class TestDedup:
    def test_duckdb_dedup(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)
        conn.execute(
            "INSERT INTO events (timestamp, session_id, agent_id, tool, backend, status, import_source) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("2026-01-30T10:00:00Z", "sess-1", "", "Read", "native", "success", "duckdb"),
        )
        conn.commit()
        assert dedup_check_duckdb(conn, "2026-01-30T10:00:00Z", "sess-1", "", "Read") is True
        assert dedup_check_duckdb(conn, "2026-01-30T10:00:00Z", "sess-1", "", "Write") is False
        conn.close()

    def test_jsonl_dedup(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)
        conn.execute(
            "INSERT INTO events (timestamp, session_id, agent_id, tool, backend, status, tool_use_id, import_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026-01-30T10:00:00Z", "sess-1", "", "Read", "native", "success", "toolu_001", "claude_transcript"),
        )
        conn.commit()
        assert dedup_check_jsonl(conn, "2026-01-30T10:00:00Z", "sess-1", "", "Read", "toolu_001") is True
        assert dedup_check_jsonl(conn, "2026-01-30T10:00:00Z", "sess-1", "", "Read", "toolu_002") is False
        conn.close()


class TestVSessions:
    def test_session_aggregation(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)
        for i in range(3):
            conn.execute(
                "INSERT INTO events (timestamp, session_id, agent_id, tool, backend, status, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"2026-01-30T10:0{i}:00Z", "sess-1", "sess-1", f"Tool{i}", "native", "success", 100, 50, 10, 5),
            )
        conn.execute(
            "INSERT INTO events (timestamp, session_id, agent_id, tool, backend, status, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026-01-30T10:01:00Z", "sess-1", "sess-1", "Bash", "native", "error", 100, 50, 10, 5),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM v_sessions WHERE session_id = 'sess-1'").fetchone()
        assert row["event_count"] == 4
        assert row["total_input_tokens"] == 400
        assert row["error_count"] == 1
        assert row["unique_tools"] == 4
        conn.close()
