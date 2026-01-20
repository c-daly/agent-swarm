"""Tests for agent output persistence in SubagentStop hook."""

import pytest
import json
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock, call
import sys
import importlib.util

# Import hook module (has hyphen in filename, can't use regular import)
hooks_dir = Path(__file__).parent.parent / "hooks"
spec = importlib.util.spec_from_file_location("subagent_complete", hooks_dir / "subagent-complete.py")
subagent_complete = importlib.util.module_from_spec(spec)
sys.modules['subagent_complete'] = subagent_complete
spec.loader.exec_module(subagent_complete)


class TestAgentOutputExtraction:
    """Test extraction of agent completion data from output."""

    def test_extract_valid_json_output(self):
        """Should extract all fields from valid JSON output."""
        from subagent_complete import extract_agent_completion_info
        
        output = """```json
{
  "agent_id": "sub-abc123",
  "status": "complete",
  "summary": "Implemented feature X",
  "files_modified": ["file1.py", "file2.py"],
  "tests_passed": true
}
```"""
        
        result = extract_agent_completion_info(output)
        
        assert result["agent_id"] == "sub-abc123"
        assert result["status"] == "complete"
        assert result["summary"] == "Implemented feature X"
        assert result["files_modified"] == ["file1.py", "file2.py"]
        assert result["tests_passed"] is True

    def test_extract_json_in_markdown(self):
        """Should extract JSON from markdown code fence."""
        from subagent_complete import extract_agent_completion_info
        
        output = """Some text before

```json
{
  "agent_id": "sub-xyz789",
  "status": "failed",
  "summary": "Tests failed",
  "files_modified": [],
  "tests_passed": false
}
```

Some text after"""
        
        result = extract_agent_completion_info(output)
        
        assert result["agent_id"] == "sub-xyz789"
        assert result["status"] == "failed"
        assert result["tests_passed"] is False

    def test_extract_partial_json(self):
        """Should handle missing optional fields gracefully."""
        from subagent_complete import extract_agent_completion_info
        
        output = """```json
{
  "agent_id": "sub-partial",
  "status": "complete"
}
```"""
        
        result = extract_agent_completion_info(output)
        
        assert result["agent_id"] == "sub-partial"
        assert result["status"] == "complete"
        assert result["summary"] == ""
        assert result["files_modified"] == []
        assert result["tests_passed"] is None

    def test_extract_malformed_json(self):
        """Should return empty dict on JSON parse error."""
        from subagent_complete import extract_agent_completion_info
        
        output = """```json
{
  "agent_id": "sub-bad",
  "status": "complete"
  missing comma and brace
```"""
        
        result = extract_agent_completion_info(output)
        
        assert result == {}

    def test_extract_no_json(self):
        """Should return empty dict when no JSON present."""
        from subagent_complete import extract_agent_completion_info
        
        output = "Just some plain text output with no JSON"
        
        result = extract_agent_completion_info(output)
        
        assert result == {}

    def test_extract_raw_json_without_fence(self):
        """Should extract raw JSON object without markdown fence."""
        from subagent_complete import extract_agent_completion_info
        
        output = 'Task complete: {"agent_id": "sub-raw123", "status": "complete", "summary": "Done"}'
        
        result = extract_agent_completion_info(output)
        
        assert result["agent_id"] == "sub-raw123"
        assert result["status"] == "complete"


class TestAgentStatePersistence:
    """Test persistence of agent state to workflow state manager."""

    @patch('subagent_complete.agent_set_state')
    @patch('subagent_complete.find_agent_output_file')
    @patch('subagent_complete.Path')
    def test_agent_state_persisted_on_completion(self, mock_path_cls, mock_find_file, mock_set_state):
        """Agent state should be persisted when subagent completes."""
        from subagent_complete import persist_agent_output
        
        # Setup mocks
        mock_find_file.return_value = "/tmp/claude/session/tasks/abc12345.output"
        mock_output_path = MagicMock()
        mock_output_path.exists.return_value = True
        mock_output_path.read_text.return_value = """```json
{
  "agent_id": "sub-abc123",
  "status": "complete",
  "summary": "Task completed successfully",
  "files_modified": ["file1.py"],
  "tests_passed": true
}
```"""
        mock_path_cls.return_value = mock_output_path
        
        # Call function
        persist_agent_output("abc12345", "implementer")
        
        # Verify agent_set_state was called
        assert mock_set_state.called
        call_args = mock_set_state.call_args[0]
        assert call_args[0] == "sub-abc123"  # agent_id
        assert call_args[1]["status"] == "complete"
        assert call_args[1]["summary"] == "Task completed successfully"
        assert call_args[1]["agent_type"] == "implementer"

    @patch('subagent_complete.agent_set_state')
    @patch('subagent_complete.find_agent_output_file')
    @patch('subagent_complete.Path')
    def test_agent_state_includes_timestamp(self, mock_path_cls, mock_find_file, mock_set_state):
        """Persisted state should include timestamp."""
        from subagent_complete import persist_agent_output
        
        mock_find_file.return_value = "/tmp/output.txt"
        mock_output_path = MagicMock()
        mock_output_path.exists.return_value = True
        mock_output_path.read_text.return_value = '{"agent_id": "sub-123", "status": "complete"}'
        mock_path_cls.return_value = mock_output_path
        
        persist_agent_output("session123", "explorer")
        
        assert mock_set_state.called
        state_data = mock_set_state.call_args[0][1]
        assert "timestamp" in state_data

    @patch('subagent_complete.agent_set_state')
    @patch('subagent_complete.find_agent_output_file')
    def test_handles_missing_output_file(self, mock_find_file, mock_set_state):
        """Should not crash if output file is missing."""
        from subagent_complete import persist_agent_output
        
        mock_find_file.return_value = None
        
        # Should not raise exception
        persist_agent_output("missing_session", "implementer")
        
        # Should not call agent_set_state
        assert not mock_set_state.called

    @patch('subagent_complete.agent_set_state')
    @patch('subagent_complete.find_agent_output_file')
    @patch('subagent_complete.Path')
    def test_handles_empty_output(self, mock_path_cls, mock_find_file, mock_set_state):
        """Should not crash on empty output."""
        from subagent_complete import persist_agent_output
        
        mock_find_file.return_value = "/tmp/output.txt"
        mock_output_path = MagicMock()
        mock_output_path.exists.return_value = True
        mock_output_path.read_text.return_value = ""
        mock_path_cls.return_value = mock_output_path
        
        # Should not raise exception
        persist_agent_output("session_empty", "implementer")
        
        # Should not call agent_set_state (no valid data)
        assert not mock_set_state.called


class TestGracefulErrorHandling:
    """Test that errors are handled gracefully without failing the hook."""

    @patch('subagent_complete.agent_set_state')
    @patch('subagent_complete.find_agent_output_file')
    @patch('subagent_complete.Path')
    def test_continues_on_parse_error(self, mock_path_cls, mock_find_file, mock_set_state):
        """Hook should complete even if JSON parsing fails."""
        from subagent_complete import persist_agent_output
        
        mock_find_file.return_value = "/tmp/output.txt"
        mock_output_path = MagicMock()
        mock_output_path.exists.return_value = True
        mock_output_path.read_text.return_value = "Not valid JSON at all"
        mock_path_cls.return_value = mock_output_path
        
        # Should not raise exception
        persist_agent_output("session_bad", "implementer")
        
        # Should not call agent_set_state (parsing failed)
        assert not mock_set_state.called

    @patch('subagent_complete.agent_set_state')
    @patch('subagent_complete.find_agent_output_file')
    @patch('subagent_complete.Path')
    def test_continues_on_state_save_error(self, mock_path_cls, mock_find_file, mock_set_state):
        """Hook should complete even if agent_set_state fails."""
        from subagent_complete import persist_agent_output
        
        mock_find_file.return_value = "/tmp/output.txt"
        mock_output_path = MagicMock()
        mock_output_path.exists.return_value = True
        mock_output_path.read_text.return_value = '{"agent_id": "sub-123", "status": "complete"}'
        mock_path_cls.return_value = mock_output_path
        
        # Make agent_set_state raise an exception
        mock_set_state.side_effect = Exception("State save failed")
        
        # Should not raise exception (error is caught)
        persist_agent_output("session_error", "implementer")

    @patch('subagent_complete.find_agent_output_file')
    @patch('subagent_complete.Path')
    def test_continues_on_file_read_error(self, mock_path_cls, mock_find_file):
        """Hook should complete even if file reading fails."""
        from subagent_complete import persist_agent_output
        
        mock_find_file.return_value = "/tmp/output.txt"
        mock_output_path = MagicMock()
        mock_output_path.exists.return_value = True
        mock_output_path.read_text.side_effect = IOError("Permission denied")
        mock_path_cls.return_value = mock_output_path
        
        # Should not raise exception
        persist_agent_output("session_io_error", "implementer")


class TestFindAgentOutputFile:
    """Test finding agent output files."""

    @patch('subagent_complete.glob.glob')
    def test_finds_output_file(self, mock_glob):
        """Should find output file matching session ID."""
        from subagent_complete import find_agent_output_file
        
        mock_glob.return_value = ["/tmp/claude/abc/tasks/session123.output"]
        
        result = find_agent_output_file("session123")
        
        assert result == "/tmp/claude/abc/tasks/session123.output"
        mock_glob.assert_called_once_with("/tmp/claude/*/tasks/session123.output")

    @patch('subagent_complete.glob.glob')
    def test_returns_none_when_not_found(self, mock_glob):
        """Should return None when output file not found."""
        from subagent_complete import find_agent_output_file
        
        mock_glob.return_value = []
        
        result = find_agent_output_file("nonexistent")
        
        assert result is None

    @patch('subagent_complete.glob.glob')
    def test_handles_glob_error(self, mock_glob):
        """Should return None if glob raises an exception."""
        from subagent_complete import find_agent_output_file
        
        mock_glob.side_effect = OSError("Glob failed")
        
        result = find_agent_output_file("error_session")
        
        assert result is None
