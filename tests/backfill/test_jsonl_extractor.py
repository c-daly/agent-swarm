#!/usr/bin/env python3
"""
Characterization tests for lib/jsonl_extractor.py.
Tests pin current behavior of token extraction and JSONL parsing.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
import time

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))

from jsonl_extractor import (
    get_file_hash,
    load_progress,
    save_progress,
    is_file_processed,
    mark_file_processed,
    extract_session_info,
    parse_jsonl_line,
    extract_tokens_from_message,
    extract_tool_call,
    process_jsonl_file,
    merge_session_into_telemetry,
)

from telemetry_schema_v2 import default_telemetry_v2


class TestParseJsonlLine:
    """Test parse_jsonl_line behavior."""

    def test_parse_valid_json_object(self):
        """Valid JSON object line is parsed."""
        line_dict = {"type": "assistant", "message": "hello"}
        line = json.dumps(line_dict)
        result = parse_jsonl_line(line)
        assert result == line_dict

    def test_parse_valid_json_with_nested_usage(self):
        """Valid JSON with nested usage data is parsed."""
        line_dict = {
            "type": "assistant",
            "message": {"usage": {"input_tokens": 5, "output_tokens": 10}},
        }
        line = json.dumps(line_dict)
        result = parse_jsonl_line(line)
        assert result == line_dict

    def test_parse_invalid_json(self):
        """Invalid JSON returns None."""
        result = parse_jsonl_line("{invalid json}")
        assert result is None

    def test_parse_empty_line(self):
        """Empty line returns None."""
        result = parse_jsonl_line("")
        assert result is None

    def test_parse_whitespace_only(self):
        """Whitespace-only line returns None."""
        result = parse_jsonl_line("   \n")
        assert result is None


class TestExtractTokensFromMessage:
    """Test extract_tokens_from_message behavior."""

    def test_extract_from_usage_field(self):
        """Extracts tokens from top-level usage field."""
        msg = {"usage": {"input_tokens": 5, "output_tokens": 10}}
        result = extract_tokens_from_message(msg)
        assert result is not None
        assert result["input"] == 5
        assert result["output"] == 10
        assert result["source"] == "jsonl"

    def test_extract_from_nested_message_usage(self):
        """Extracts tokens from message.usage field."""
        msg = {"message": {"usage": {"input_tokens": 3, "output_tokens": 7}}}
        result = extract_tokens_from_message(msg)
        assert result is not None
        assert result["input"] == 3
        assert result["output"] == 7

    def test_extract_with_cache_tokens(self):
        """Extracts cache tokens when present."""
        msg = {
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "cache_read_input_tokens": 5,
                "cache_creation_input_tokens": 3,
            }
        }
        result = extract_tokens_from_message(msg)
        assert result is not None
        assert result["cache_read"] == 5
        assert result["cache_creation"] == 3

    def test_extract_no_usage(self):
        """Message without usage returns None."""
        msg = {"type": "user", "content": "hello"}
        result = extract_tokens_from_message(msg)
        assert result is None

    def test_extract_empty_usage(self):
        """Message with empty usage dict returns None (if usage is falsy)."""
        # NOTE: empty dict {} is falsy in the "if usage:" check, so returns None
        msg = {"usage": {}}
        result = extract_tokens_from_message(msg)
        assert result is None

    def test_extract_malformed_usage_crashes(self):
        """Message with non-dict usage causes AttributeError (no graceful handling)."""
        # NOTE: possible bug — function does not check isinstance(usage, dict)
        msg = {"usage": "not a dict"}
        with pytest.raises(AttributeError):
            extract_tokens_from_message(msg)


class TestExtractToolCall:
    """Test extract_tool_call behavior."""

    def test_extract_native_tool(self):
        """Extracts native tool name and backend."""
        msg = {
            "content": [
                {"type": "tool_use", "name": "my_tool", "id": "call_1"}
            ]
        }
        result = extract_tool_call(msg)
        assert result is not None
        tool_name, backend = result
        assert tool_name == "my_tool"
        assert backend == "native"

    def test_extract_mcp_router_tool(self):
        """Extracts mcp__router__ tool and backend."""
        msg = {
            "content": [
                {"type": "tool_use", "name": "mcp__router__native__bash", "id": "call_1"}
            ]
        }
        result = extract_tool_call(msg)
        assert result is not None
        tool_name, backend = result
        assert tool_name == "mcp__router__native__bash"
        assert backend == "native"

    def test_extract_mcp_plugin_tool(self):
        """Extracts mcp__plugin_ tool and backend."""
        msg = {
            "content": [
                {"type": "tool_use", "name": "mcp__plugin_context7__fetch", "id": "call_1"}
            ]
        }
        result = extract_tool_call(msg)
        assert result is not None
        tool_name, backend = result
        assert tool_name == "mcp__plugin_context7__fetch"
        # Backend extraction from plugin_ name
        assert backend == "context7"

    def test_no_tool_use_in_content(self):
        """Non-tool-use message returns None."""
        msg = {"content": [{"type": "text", "text": "hello"}]}
        result = extract_tool_call(msg)
        assert result is None

    def test_no_content_field(self):
        """Message without content returns None."""
        msg = {"type": "text"}
        result = extract_tool_call(msg)
        assert result is None

    def test_multiple_content_items(self):
        """Extracts first tool_use from multiple content items."""
        msg = {
            "content": [
                {"type": "text", "text": "Processing"},
                {"type": "tool_use", "name": "first_tool", "id": "call_1"},
                {"type": "tool_use", "name": "second_tool", "id": "call_2"},
            ]
        }
        result = extract_tool_call(msg)
        assert result is not None
        tool_name, backend = result
        assert tool_name == "first_tool"


class TestGetFileHash:
    """Test get_file_hash behavior."""

    def test_hash_same_file_same_mtime(self, tmp_path):
        """Hash is stable for same file and mtime."""
        f = tmp_path / "test.txt"
        f.write_text("content")
        hash1 = get_file_hash(f)
        hash2 = get_file_hash(f)
        assert hash1 == hash2

    def test_hash_changes_with_mtime(self, tmp_path):
        """Hash changes when file mtime changes."""
        f = tmp_path / "test.txt"
        f.write_text("content")
        hash1 = get_file_hash(f)
        
        # Change mtime
        time.sleep(0.01)  # Small delay to ensure mtime difference
        os.utime(f, None)  # Touch file to update mtime
        hash2 = get_file_hash(f)
        
        assert hash1 != hash2

    def test_hash_changes_with_size(self, tmp_path):
        """Hash changes when file size changes."""
        f = tmp_path / "test.txt"
        f.write_text("content")
        hash1 = get_file_hash(f)
        
        # Modify file
        time.sleep(0.01)
        f.write_text("longer content now")
        hash2 = get_file_hash(f)
        
        assert hash1 != hash2

    def test_hash_format(self, tmp_path):
        """Hash is 12-character hex string."""
        f = tmp_path / "test.txt"
        f.write_text("content")
        h = get_file_hash(f)
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)


class TestProgressTracking:
    """Test progress tracking functions."""

    def test_mark_file_with_real_temp_file(self, tmp_path):
        """Mark and check with real temp file."""
        progress = {"processed": {}}
        f = tmp_path / "session.jsonl"
        f.write_text("line1\n")
        
        tokens = {"input": 100, "output": 50}
        mark_file_processed(f, progress, tokens)
        
        # Now it should be marked as processed
        assert is_file_processed(f, progress)
        
        # Verify structure
        file_key = str(f)
        assert file_key in progress["processed"]
        assert "hash" in progress["processed"][file_key]
        assert "processed_at" in progress["processed"][file_key]
        assert progress["processed"][file_key]["tokens"] == tokens

    def test_mark_file_updates_hash_on_change(self, tmp_path):
        """File is no longer marked processed if content changes."""
        progress = {"processed": {}}
        f = tmp_path / "session.jsonl"
        f.write_text("content1\n")
        
        tokens = {"input": 100, "output": 50}
        mark_file_processed(f, progress, tokens)
        assert is_file_processed(f, progress)
        
        # Change file
        time.sleep(0.01)
        f.write_text("content2\n")
        
        # Now hash should not match
        assert not is_file_processed(f, progress)


class TestExtractSessionInfo:
    """Test extract_session_info behavior."""

    def test_extract_from_path(self, tmp_path):
        """Extracts session ID from file path."""
        f = tmp_path / "my_session.jsonl"
        f.write_text("")
        
        info = extract_session_info(f)
        assert info["session_id"] == "my_session"
        assert info["path"] == str(f)
        assert "date" in info

    def test_extract_with_date_in_filename(self, tmp_path):
        """Extracts date from filename if present."""
        f = tmp_path / "2026-01-15_session.jsonl"
        f.write_text("")
        
        info = extract_session_info(f)
        assert info["date"] == "2026-01-15"

    def test_extract_uses_mtime_if_no_date(self, tmp_path):
        """Falls back to file mtime if no date in filename."""
        f = tmp_path / "session_no_date.jsonl"
        f.write_text("")
        
        info = extract_session_info(f)
        # Should have a date from mtime
        assert "date" in info
        assert len(info["date"]) == 10  # YYYY-MM-DD format


class TestProcessJsonlFile:
    """Test process_jsonl_file behavior."""

    def test_process_empty_file(self, tmp_path):
        """Processing empty file returns structure with zero tokens."""
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        
        result = process_jsonl_file(f)
        assert result["session_id"] == "empty"
        assert result["tokens"]["input"] == 0
        assert result["tokens"]["output"] == 0
        assert result["calls"]["total"] == 0
        assert result["line_count"] == 0

    def test_process_file_with_single_message(self, tmp_path):
        """Processing file with one token-bearing message."""
        f = tmp_path / "session.jsonl"
        msg = {"type": "assistant", "usage": {"input_tokens": 5, "output_tokens": 10}}
        f.write_text(json.dumps(msg) + "\n")
        
        result = process_jsonl_file(f)
        assert result["tokens"]["input"] == 5
        assert result["tokens"]["output"] == 10
        assert result["line_count"] == 1

    def test_process_file_with_tool_call(self, tmp_path):
        """Processing file with tool calls counts them."""
        f = tmp_path / "session.jsonl"
        msg = {
            "type": "assistant",
            "content": [{"type": "tool_use", "name": "my_tool", "id": "c1"}],
        }
        f.write_text(json.dumps(msg) + "\n")
        
        result = process_jsonl_file(f)
        assert result["calls"]["total"] == 1
        assert "my_tool" in result["calls"]["by_tool"]

    def test_process_file_with_mixed_lines(self, tmp_path):
        """Processing file with valid and invalid lines."""
        f = tmp_path / "mixed.jsonl"
        lines = [
            json.dumps({"type": "user", "usage": {"input_tokens": 1, "output_tokens": 0}}),
            "invalid json here",  # This line should be skipped
            json.dumps({"type": "assistant", "usage": {"input_tokens": 2, "output_tokens": 3}}),
        ]
        f.write_text("\n".join(lines) + "\n")
        
        result = process_jsonl_file(f)
        # Should sum tokens from valid lines only
        assert result["tokens"]["input"] == 3
        assert result["tokens"]["output"] == 3
        # Invalid line still counts toward line_count (not skipped in counting)
        assert result["line_count"] == 3

    def test_process_file_with_timestamps(self, tmp_path):
        """Processing file extracts start and end times."""
        f = tmp_path / "timestamps.jsonl"
        ts1 = "2026-01-15T10:00:00Z"
        ts2 = "2026-01-15T10:05:00Z"
        lines = [
            json.dumps({"type": "user", "timestamp": ts1}),
            json.dumps({"type": "assistant", "ts": ts2}),
        ]
        f.write_text("\n".join(lines))
        
        result = process_jsonl_file(f)
        assert result["start"] is not None
        assert result["end"] is not None


class TestMergeSessionIntoTelemetry:
    """Test merge_session_into_telemetry behavior."""

    def test_merge_creates_day_entry(self, tmp_path):
        """Merging creates day entry if missing."""
        telemetry = default_telemetry_v2()
        f = tmp_path / "session.jsonl"
        f.write_text("")
        session_data = {
            "date": "2026-01-15",
            "session_id": "session1",
            "tokens": {"input": 10, "output": 20, "source": "jsonl"},
            "calls": {"total": 2},
            "path": str(f),
        }
        
        merge_session_into_telemetry(telemetry, session_data)
        
        assert "2026-01-15" in telemetry["days"]
        assert "session1" in telemetry["days"]["2026-01-15"]["sessions"]

    def test_merge_accumulates_tokens(self, tmp_path):
        """Merging accumulates tokens across sessions."""
        telemetry = default_telemetry_v2()
        f1 = tmp_path / "s1.jsonl"
        f2 = tmp_path / "s2.jsonl"
        f1.write_text("")
        f2.write_text("")
        
        session1 = {
            "date": "2026-01-15",
            "session_id": "s1",
            "tokens": {"input": 10, "output": 20, "source": "jsonl"},
            "calls": {"total": 1},
            "path": str(f1),
        }
        session2 = {
            "date": "2026-01-15",
            "session_id": "s2",
            "tokens": {"input": 5, "output": 10, "source": "jsonl"},
            "calls": {"total": 1},
            "path": str(f2),
        }
        
        merge_session_into_telemetry(telemetry, session1)
        merge_session_into_telemetry(telemetry, session2)
        
        day_tokens = telemetry["days"]["2026-01-15"]["tokens"]
        assert day_tokens["input"] == 15
        assert day_tokens["output"] == 30

    def test_merge_accumulates_calls(self, tmp_path):
        """Merging accumulates tool calls."""
        telemetry = default_telemetry_v2()
        f = tmp_path / "s1.jsonl"
        f.write_text("")
        
        session = {
            "date": "2026-01-15",
            "session_id": "s1",
            "tokens": {"input": 0, "output": 0, "source": "jsonl"},
            "calls": {"total": 3, "by_tool": {"bash": 2, "grep": 1}},
            "path": str(f),
        }
        
        merge_session_into_telemetry(telemetry, session)
        
        day_calls = telemetry["days"]["2026-01-15"]["calls"]
        assert day_calls["total"] == 3
        assert day_calls["by_tool"]["bash"] == 2
        assert day_calls["by_tool"]["grep"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
