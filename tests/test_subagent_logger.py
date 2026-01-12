"""Tests for lib/subagent_logger.py module."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import subagent_logger
from subagent_logger import (
    log_subagent_event,
    log_phase_transition,
    log_tool_use,
    log_completion,
    read_agent_log,
)


@pytest.fixture
def temp_log_dir(tmp_path):
    """Use a temporary directory for log files."""
    with patch.object(subagent_logger, "LOG_DIR", tmp_path):
        yield tmp_path


class TestLogSubagentEvent:
    def test_creates_log_directory(self, temp_log_dir):
        # Directory shouldn't exist yet (tmp_path creates parent but not our subdir)
        log_subagent_event("test-agent", "start", {"key": "value"})
        assert temp_log_dir.exists()

    def test_creates_log_file(self, temp_log_dir):
        log_subagent_event("agent-123", "start", {})
        log_file = temp_log_dir / "subagent.agent-123.log"
        assert log_file.exists()

    def test_writes_json_entry(self, temp_log_dir):
        log_subagent_event("agent-456", "test_event", {"foo": "bar"})
        log_file = temp_log_dir / "subagent.agent-456.log"
        content = log_file.read_text().strip()
        entry = json.loads(content)

        assert entry["agent_id"] == "agent-456"
        assert entry["event"] == "test_event"
        assert entry["data"] == {"foo": "bar"}
        assert "timestamp" in entry

    def test_appends_multiple_entries(self, temp_log_dir):
        log_subagent_event("agent-multi", "event1", {})
        log_subagent_event("agent-multi", "event2", {})
        log_subagent_event("agent-multi", "event3", {})

        log_file = temp_log_dir / "subagent.agent-multi.log"
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_handles_none_data(self, temp_log_dir):
        log_subagent_event("agent-none", "event", None)
        log_file = temp_log_dir / "subagent.agent-none.log"
        entry = json.loads(log_file.read_text().strip())
        assert entry["data"] == {}


class TestLogPhaseTransition:
    def test_logs_phase_transition(self, temp_log_dir):
        log_phase_transition("agent-phase", "test_writing", "implement")
        log_file = temp_log_dir / "subagent.agent-phase.log"
        entry = json.loads(log_file.read_text().strip())

        assert entry["event"] == "phase_transition"
        assert entry["data"]["from"] == "test_writing"
        assert entry["data"]["to"] == "implement"


class TestLogToolUse:
    def test_logs_successful_tool_use(self, temp_log_dir):
        log_tool_use("agent-tool", "Edit", True, "file.py edited")
        log_file = temp_log_dir / "subagent.agent-tool.log"
        entry = json.loads(log_file.read_text().strip())

        assert entry["event"] == "tool_use"
        assert entry["data"]["tool"] == "Edit"
        assert entry["data"]["success"] is True
        assert entry["data"]["detail"] == "file.py edited"

    def test_logs_failed_tool_use(self, temp_log_dir):
        log_tool_use("agent-fail", "Bash", False, "command failed")
        log_file = temp_log_dir / "subagent.agent-fail.log"
        entry = json.loads(log_file.read_text().strip())

        assert entry["data"]["success"] is False


class TestLogCompletion:
    def test_logs_successful_completion(self, temp_log_dir):
        log_completion("agent-done", "test", True, "all tests passed")
        log_file = temp_log_dir / "subagent.agent-done.log"
        entry = json.loads(log_file.read_text().strip())

        assert entry["event"] == "completion"
        assert entry["data"]["phase"] == "test"
        assert entry["data"]["success"] is True
        assert entry["data"]["reason"] == "all tests passed"

    def test_logs_failed_completion(self, temp_log_dir):
        log_completion("agent-fail", "implement", False, "syntax error")
        log_file = temp_log_dir / "subagent.agent-fail.log"
        entry = json.loads(log_file.read_text().strip())

        assert entry["data"]["success"] is False
        assert entry["data"]["reason"] == "syntax error"


class TestReadAgentLog:
    def test_returns_empty_list_when_no_log(self, temp_log_dir):
        result = read_agent_log("nonexistent-agent")
        assert result == []

    def test_reads_all_entries(self, temp_log_dir):
        log_subagent_event("agent-read", "event1", {"n": 1})
        log_subagent_event("agent-read", "event2", {"n": 2})
        log_subagent_event("agent-read", "event3", {"n": 3})

        entries = read_agent_log("agent-read")
        assert len(entries) == 3
        assert entries[0]["event"] == "event1"
        assert entries[1]["event"] == "event2"
        assert entries[2]["event"] == "event3"

    def test_parses_json_correctly(self, temp_log_dir):
        log_completion("agent-parse", "review", True, "done")
        entries = read_agent_log("agent-parse")

        assert len(entries) == 1
        assert entries[0]["agent_id"] == "agent-parse"
        assert entries[0]["data"]["phase"] == "review"
