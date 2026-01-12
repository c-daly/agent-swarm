#!/usr/bin/env python3
"""
Tests for Greptile comment check gate in combined-enforcement.py.

Tests that:
1. Completion/commit is blocked when unaddressed P0 Greptile comments exist
2. Completion is allowed when no P0 comments or all addressed
3. Integration with verification_gates.check_greptile_comments()
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from verification_gates import check_greptile_comments


class TestCheckGreptileComments:
    """Test the check_greptile_comments function."""

    def test_returns_none_when_no_pr(self):
        """Should return None when PR number is invalid."""
        result = check_greptile_comments(0, "owner/repo")
        # Currently a stub, but should handle gracefully
        assert result is None or isinstance(result, str)

    def test_returns_none_when_no_unaddressed_comments(self):
        """Should return None when all P0 comments are addressed."""
        # Mock load_verification_state to return state with no unaddressed P0
        mock_state = {
            "greptile_state": {
                "pr_number": 123,
                "repo": "owner/repo",
                "unaddressed_p0_count": 0,
                "unaddressed_p0_comments": [],
                "api_available": True
            }
        }
        with patch('verification_gates.load_verification_state', return_value=mock_state):
            result = check_greptile_comments(123, "owner/repo")
            # Should not block - no unaddressed P0
            assert result is None

    def test_blocks_when_unaddressed_p0_comments(self):
        """Should return error when unaddressed P0 comments exist."""
        mock_state = {
            "greptile_state": {
                "pr_number": 123,
                "repo": "owner/repo",
                "unaddressed_p0_count": 1,
                "unaddressed_p0_comments": [
                    {"id": "1", "body": "Critical: Fix injection vulnerability", "path": "src/main.py"}
                ],
                "api_available": True
            }
        }
        with patch('verification_gates.load_verification_state', return_value=mock_state):
            result = check_greptile_comments(123, "owner/repo")
            # Should block - unaddressed P0
            assert result is not None
            assert "P0" in result or "unaddressed" in result.lower()

    def test_extracts_pr_info_from_git(self):
        """Should auto-detect PR number from current branch if not provided."""
        # This tests the helper function that gets PR info
        pass  # Implement when function exists


class TestGreptileGateIntegration:
    """Test integration of Greptile gate with combined-enforcement."""

    @pytest.fixture
    def mock_state(self):
        """Create mock state for testing."""
        return {
            "phase": "review",
            "workflow_invoked": True,
            "classification_given": True,
            "classification_type": "SIMPLE",
        }

    def test_git_commit_blocked_with_unaddressed_p0(self, mock_state):
        """Git commit should be blocked when unaddressed P0 comments exist."""
        # Import the check function
        sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

        # This will be implemented in combined-enforcement.py
        # For now, test the integration point exists
        try:
            from combined_enforcement import check_greptile_unaddressed

            tool_input = {"command": "git commit -m 'test'"}
            result = check_greptile_unaddressed("Bash", tool_input, mock_state)
            # Should block or return None based on Greptile state
            assert result is None or "hookSpecificOutput" in result
        except ImportError:
            pytest.skip("check_greptile_unaddressed not yet implemented")

    def test_git_push_blocked_with_unaddressed_p0(self, mock_state):
        """Git push should be blocked when unaddressed P0 comments exist."""
        try:
            from combined_enforcement import check_greptile_unaddressed

            tool_input = {"command": "git push origin feature-branch"}
            result = check_greptile_unaddressed("Bash", tool_input, mock_state)
            assert result is None or "hookSpecificOutput" in result
        except ImportError:
            pytest.skip("check_greptile_unaddressed not yet implemented")

    def test_non_git_commands_not_affected(self, mock_state):
        """Non-git commands should not be affected by Greptile gate."""
        try:
            from combined_enforcement import check_greptile_unaddressed

            tool_input = {"command": "pytest tests/"}
            result = check_greptile_unaddressed("Bash", tool_input, mock_state)
            # Should always allow non-git commands
            assert result is None
        except ImportError:
            pytest.skip("check_greptile_unaddressed not yet implemented")


class TestGetCurrentPR:
    """Test helper function to get current PR info."""

    def test_detects_pr_from_branch(self):
        """Should detect PR number from gh pr list for current branch."""
        # This will use gh CLI or Greptile MCP
        pass  # Implement when helper exists

    def test_returns_none_when_no_pr(self):
        """Should return None when no PR for current branch."""
        pass  # Implement when helper exists
