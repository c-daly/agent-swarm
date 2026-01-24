#!/usr/bin/env python3
"""Tests for session-start.py memory auto-read functionality."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add hooks to path
hooks_dir = Path(__file__).parent.parent / "hooks"
sys.path.insert(0, str(hooks_dir))


class TestFindRelevantMemories:
    """Tests for find_relevant_memories function."""

    def test_matches_single_keyword(self):
        """Should match memory names containing query keyword."""
        # Import here to avoid import errors during collection
        from importlib import import_module
        session_start = import_module("session-start")
        
        memories = ["handoff-2026-01-24-subagent-tools", "iterate-workflow", "instruction-consolidation"]
        query = "subagent"
        
        result = session_start.find_relevant_memories(query, memories)
        
        assert "handoff-2026-01-24-subagent-tools" in result
        assert len(result) <= 3  # Max 3 memories

    def test_matches_multiple_keywords(self):
        """Should score higher for multiple keyword matches."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        memories = ["handoff-2026-01-24-subagent-tools", "iterate-workflow", "handoff-2026-01-20"]
        query = "subagent tools"
        
        result = session_start.find_relevant_memories(query, memories)
        
        # subagent-tools should be first (matches both keywords)
        assert result[0] == "handoff-2026-01-24-subagent-tools"

    def test_returns_empty_for_no_matches(self):
        """Should return empty list when no memories match."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        memories = ["handoff-2026-01-24-subagent-tools", "iterate-workflow"]
        query = "nonexistent topic"
        
        result = session_start.find_relevant_memories(query, memories)
        
        assert result == []

    def test_limits_to_max_memories(self):
        """Should return at most max_count memories."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        memories = [f"handoff-{i}" for i in range(10)]
        query = "handoff"
        
        result = session_start.find_relevant_memories(query, memories, max_count=2)
        
        assert len(result) <= 2

    def test_case_insensitive_matching(self):
        """Should match regardless of case."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        memories = ["Handoff-SubAgent-Tools"]
        query = "SUBAGENT"
        
        result = session_start.find_relevant_memories(query, memories)
        
        assert len(result) == 1


class TestReadMemorySnippets:
    """Tests for read_memory_snippets function."""

    def test_reads_memory_content(self):
        """Should read and return memory content."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        # Mock file reading
        test_content = "# Test Memory\n\nThis is test content for memory snippet."
        
        with patch.object(Path, 'read_text', return_value=test_content):
            with patch.object(Path, 'exists', return_value=True):
                result = session_start.read_memory_snippets(["test-memory"])
        
        assert "Test Memory" in result or "test content" in result

    def test_truncates_long_content(self):
        """Should truncate content to max_chars."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        test_content = "x" * 2000  # Very long content
        
        with patch.object(Path, 'read_text', return_value=test_content):
            with patch.object(Path, 'exists', return_value=True):
                result = session_start.read_memory_snippets(["test-memory"], max_chars_per_memory=100)
        
        # Result should be limited (100 chars + ellipsis + formatting)
        assert len(result) < 500

    def test_handles_missing_files(self):
        """Should gracefully handle missing memory files."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        with patch.object(Path, 'exists', return_value=False):
            result = session_start.read_memory_snippets(["nonexistent-memory"])
        
        assert result == "" or "not found" in result.lower() or result is not None


class TestSearchEpisodicMemory:
    """Tests for search_episodic_memory function."""

    def test_returns_empty_list_when_cli_not_found(self):
        """Should return empty list if episodic-memory CLI doesn't exist."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        with patch.object(Path, 'exists', return_value=False):
            result = session_start.search_episodic_memory("test query")
        
        assert result == []

    def test_returns_empty_list_on_timeout(self):
        """Should return empty list if search times out."""
        from importlib import import_module
        import subprocess
        session_start = import_module("session-start")
        
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired("cmd", 2)):
            result = session_start.search_episodic_memory("test query")
        
        assert result == []

    def test_parses_cli_output_correctly(self):
        """Should parse CLI output format into structured results."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        mock_output = """Found 2 relevant conversations:

1. [project, 2026-01-24]
   "This is a test snippet about authentication"
   Lines 10-12 in /path/to/file.jsonl

2. [project, 2026-01-23]
   "Another snippet about login"
   Lines 20-22 in /path/to/file2.jsonl
"""
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mock_output
        
        with patch.object(Path, 'exists', return_value=True):
            with patch.object(Path, 'iterdir', return_value=[Path("1.0.15")]):
                with patch.object(Path, 'is_dir', return_value=True):
                    with patch('subprocess.run', return_value=mock_result):
                        result = session_start.search_episodic_memory("authentication")
        
        assert len(result) == 2
        assert result[0]["date"] == "2026-01-24"
        assert "authentication" in result[0]["snippet"]
        assert result[1]["date"] == "2026-01-23"

    def test_truncates_long_snippets(self):
        """Should truncate snippets longer than 150 characters."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        long_snippet = "x" * 200
        mock_output = f"""Found 1 relevant conversations:

1. [project, 2026-01-24]
   "{long_snippet}"
   Lines 10-12 in /path/to/file.jsonl
"""
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mock_output
        
        with patch.object(Path, 'exists', return_value=True):
            with patch.object(Path, 'iterdir', return_value=[Path("1.0.15")]):
                with patch.object(Path, 'is_dir', return_value=True):
                    with patch('subprocess.run', return_value=mock_result):
                        result = session_start.search_episodic_memory("test")
        
        assert len(result) == 1
        assert len(result[0]["snippet"]) <= 150
        assert result[0]["snippet"].endswith("...")


class TestSuggestMemoryOptionsIntegration:
    """Integration tests for suggest_memory_options with auto-read."""

    def test_includes_episodic_results_when_found(self):
        """Should include episodic memory results in output."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        episodic_results = [
            {"date": "2026-01-24", "snippet": "Test conversation about subagent"}
        ]
        
        with patch.object(session_start, 'search_episodic_memory', return_value=episodic_results):
            with patch.object(session_start, 'list_serena_memories', return_value=[]):
                result = session_start.suggest_memory_options("subagent")
        
        assert result["found"] is True
        assert result["conversations"] == episodic_results
        assert "Relevant past conversations" in result["message"]

    def test_includes_relevant_snippets(self):
        """Should include snippets from relevant memories."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        test_content = "# Subagent Tools\n\nImplementing subagent infrastructure."
        
        with patch.object(session_start, 'search_episodic_memory', return_value=[]):
            with patch.object(session_start, 'list_serena_memories', 
                             return_value=["handoff-2026-01-24-subagent-tools", "iterate-workflow"]):
                with patch.object(Path, 'read_text', return_value=test_content):
                    with patch.object(Path, 'exists', return_value=True):
                        result = session_start.suggest_memory_options("subagent tools")
        
        # Message should contain memory content or reference
        assert "subagent" in result["message"].lower() or "Serena" in result["message"]

    def test_fallback_to_manual_search_when_no_results(self):
        """Should show manual search instructions when episodic search returns nothing."""
        from importlib import import_module
        session_start = import_module("session-start")
        
        with patch.object(session_start, 'search_episodic_memory', return_value=[]):
            with patch.object(session_start, 'list_serena_memories', return_value=[]):
                result = session_start.suggest_memory_options("nonexistent query")
        
        assert result["found"] is False
        assert "mcp__plugin_episodic-memory" in result["message"]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
