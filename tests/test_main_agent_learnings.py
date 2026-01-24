"""Tests for capturing LEARNING: tags from main agent output at session end.

The session-end hook should:
1. Find the current session's conversation JSONL file
2. Extract LEARNING: tags from assistant messages
3. Log them to EPISODES.md
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime
import importlib.util

# Add paths BEFORE loading the module
sys.path.insert(0, str(Path(__file__).parent.parent / "context"))
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

# Load session-end module (has hyphen, can't use normal import)
HOOKS_DIR = Path(__file__).parent.parent / "hooks"
spec = importlib.util.spec_from_file_location("session_end", HOOKS_DIR / "session-end.py")
session_end = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session_end)


class TestExtractLearningsFromConversation:
    """Test extracting LEARNING: tags from conversation JSONL."""

    def test_extract_learnings_from_assistant_message(self):
        """Should find LEARNING: tags in assistant messages."""
        # Simulate JSONL content with assistant message containing LEARNING:
        jsonl_lines = [
            json.dumps({"type": "assistant", "message": {"content": "Here's the fix.\n\nLEARNING: Always check for null before accessing properties"}}),
        ]

        learnings = session_end.extract_learnings_from_conversation(jsonl_lines)

        assert len(learnings) == 1
        assert "null" in learnings[0].lower()

    def test_extract_multiple_learnings(self):
        """Should find multiple LEARNING: tags across messages."""
        jsonl_lines = [
            json.dumps({"type": "assistant", "message": {"content": "LEARNING: First insight"}}),
            json.dumps({"type": "assistant", "message": {"content": "LEARNING: Second insight"}}),
        ]

        learnings = session_end.extract_learnings_from_conversation(jsonl_lines)

        assert len(learnings) == 2
        assert "First" in learnings[0]
        assert "Second" in learnings[1]

    def test_ignores_user_messages(self):
        """Should not extract from user messages."""
        jsonl_lines = [
            json.dumps({"type": "user", "message": {"content": "LEARNING: User said this"}}),
        ]

        learnings = session_end.extract_learnings_from_conversation(jsonl_lines)

        assert len(learnings) == 0

    def test_handles_empty_content(self):
        """Should handle messages with empty or missing content."""
        jsonl_lines = [
            json.dumps({"type": "assistant", "message": {"content": ""}}),
            json.dumps({"type": "assistant", "message": {}}),
        ]

        learnings = session_end.extract_learnings_from_conversation(jsonl_lines)

        assert len(learnings) == 0

    def test_case_insensitive_matching(self):
        """Should match LEARNING: regardless of case."""
        jsonl_lines = [
            json.dumps({"type": "assistant", "message": {"content": "learning: lowercase tag"}}),
            json.dumps({"type": "assistant", "message": {"content": "Learning: Mixed case"}}),
        ]

        learnings = session_end.extract_learnings_from_conversation(jsonl_lines)

        assert len(learnings) == 2


class TestFindConversationFile:
    """Test finding the conversation JSONL file for a session."""

    def test_finds_file_by_session_id(self, tmp_path):
        """Should find JSONL file matching session ID."""
        # Create mock projects directory structure
        project_dir = tmp_path / "projects" / "-home-user-project"
        project_dir.mkdir(parents=True)

        session_id = "abc12345-1234-5678-9abc-def012345678"
        session_file = project_dir / f"{session_id}.jsonl"
        session_file.write_text('{"type":"assistant","message":{"content":"test"}}')

        with patch.object(session_end, 'get_projects_dir', return_value=tmp_path / "projects"):
            result = session_end.find_conversation_file(session_id)

        assert result is not None
        assert session_id in str(result)

    def test_returns_none_for_missing_file(self, tmp_path):
        """Should return None if session file not found."""
        project_dir = tmp_path / "projects" / "-home-user-project"
        project_dir.mkdir(parents=True)

        with patch.object(session_end, 'get_projects_dir', return_value=tmp_path / "projects"):
            result = session_end.find_conversation_file("nonexistent-session-id")

        assert result is None


class TestLogLearningsToEpisodes:
    """Test logging learnings to EPISODES.md."""

    def test_appends_to_episodes_file(self, tmp_path):
        """Should append learnings to EPISODES.md."""
        context_dir = tmp_path / ".context"
        context_dir.mkdir()
        episodes_file = context_dir / "EPISODES.md"
        episodes_file.write_text("# Episodes\n\n")

        learnings = ["Important insight about error handling"]

        with patch.object(session_end, 'get_context_dir', return_value=context_dir):
            session_end.log_main_agent_learnings(learnings, "main-agent")

        content = episodes_file.read_text()
        assert "Important insight" in content
        assert "main-agent" in content

    def test_creates_context_dir_if_missing(self, tmp_path):
        """Should create .context directory if it doesn't exist."""
        context_dir = tmp_path / ".context"

        learnings = ["Test learning"]

        with patch.object(session_end, 'get_context_dir', return_value=context_dir):
            session_end.log_main_agent_learnings(learnings, "main-agent")

        assert context_dir.exists()
        assert (context_dir / "EPISODES.md").exists()

    def test_handles_empty_learnings(self, tmp_path):
        """Should do nothing for empty learnings list."""
        context_dir = tmp_path / ".context"
        context_dir.mkdir()
        episodes_file = context_dir / "EPISODES.md"
        original_content = "# Episodes\n\n"
        episodes_file.write_text(original_content)

        with patch.object(session_end, 'get_context_dir', return_value=context_dir):
            session_end.log_main_agent_learnings([], "main-agent")

        # File should be unchanged
        assert episodes_file.read_text() == original_content


class TestCaptureMainAgentLearnings:
    """Test the full learning capture flow."""

    def test_captures_learnings_from_session(self, tmp_path):
        """Should capture learnings from session JSONL and log to EPISODES.md."""
        # Setup mock conversation file
        project_dir = tmp_path / "projects" / "-home-user-project"
        project_dir.mkdir(parents=True)

        session_id = "test-session-id"
        session_file = project_dir / f"{session_id}.jsonl"
        session_file.write_text(
            json.dumps({"type": "assistant", "message": {"content": "LEARNING: Test insight"}}) + "\n"
        )

        # Setup mock context directory
        context_dir = tmp_path / ".context"
        context_dir.mkdir()

        with patch.object(session_end, 'get_projects_dir', return_value=tmp_path / "projects"):
            with patch.object(session_end, 'get_context_dir', return_value=context_dir):
                count = session_end.capture_main_agent_learnings(session_id)

        assert count == 1
        assert (context_dir / "EPISODES.md").exists()
        assert "Test insight" in (context_dir / "EPISODES.md").read_text()

    def test_returns_zero_for_no_learnings(self, tmp_path):
        """Should return 0 when no LEARNING: tags found."""
        project_dir = tmp_path / "projects" / "-home-user-project"
        project_dir.mkdir(parents=True)

        session_id = "test-session-id"
        session_file = project_dir / f"{session_id}.jsonl"
        session_file.write_text(
            json.dumps({"type": "assistant", "message": {"content": "Just a normal response"}}) + "\n"
        )

        context_dir = tmp_path / ".context"

        with patch.object(session_end, 'get_projects_dir', return_value=tmp_path / "projects"):
            with patch.object(session_end, 'get_context_dir', return_value=context_dir):
                count = session_end.capture_main_agent_learnings(session_id)

        assert count == 0

    def test_handles_missing_session_file(self, tmp_path):
        """Should handle gracefully when session file not found."""
        project_dir = tmp_path / "projects" / "-home-user-project"
        project_dir.mkdir(parents=True)

        with patch.object(session_end, 'get_projects_dir', return_value=tmp_path / "projects"):
            count = session_end.capture_main_agent_learnings("nonexistent-session")

        assert count == 0
