#!/usr/bin/env python3
"""Tests for automatic PR review status checking.

Tests for WORKFLOW-REVIEW: Auto-check review status during review phase.
The workflow should automatically fetch PR comments from GitHub and
populate the review task queue.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from iterate_workflow import (
    Phase,
    start,
    stop,
    get_phase,
    set_phase,
    advance_phase,
    set_test_results,
    is_review_blocked,
    get_pending_review_tasks,
    _reset_logger,
)
import state_manager  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state():
    """Clean state before and after each test."""
    state_manager.delete_state("orchestrator")
    _reset_logger()
    yield
    state_manager.delete_state("orchestrator")
    _reset_logger()


class TestFetchPRReviewStatus:
    """Tests for fetching PR review status from GitHub."""

    def test_fetch_pr_comments_returns_list(self):
        """fetch_pr_review_status should return list of comments."""
        # Import after potential module changes
        from iterate_workflow import fetch_pr_review_status

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps([
                    {"id": "123", "body": "Fix this bug", "path": "src/main.py"},
                    {"id": "456", "body": "Add tests", "path": "tests/test_main.py"},
                ])
            )

            comments = fetch_pr_review_status(10)

            assert len(comments) == 2
            assert comments[0]["id"] == "123"
            assert comments[1]["body"] == "Add tests"

    def test_fetch_pr_comments_handles_empty(self):
        """fetch_pr_review_status returns empty list when no comments."""
        from iterate_workflow import fetch_pr_review_status

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="[]")

            comments = fetch_pr_review_status(10)

            assert comments == []

    def test_fetch_pr_comments_handles_gh_failure(self):
        """fetch_pr_review_status returns empty list on gh failure."""
        from iterate_workflow import fetch_pr_review_status

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Not found")

            comments = fetch_pr_review_status(999)

            assert comments == []

    def test_fetch_filters_resolved_comments(self):
        """fetch_pr_review_status should not return resolved comments."""
        from iterate_workflow import fetch_pr_review_status

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps([
                    {"id": "123", "body": "Fix bug", "isResolved": False},
                    {"id": "456", "body": "Already fixed", "isResolved": True},
                ])
            )

            comments = fetch_pr_review_status(10)

            # Should only return unresolved comments
            assert len(comments) == 1
            assert comments[0]["id"] == "123"


class TestAutoPopulateReviewQueue:
    """Tests for auto-populating review queue on phase entry."""

    def test_entering_review_fetches_comments(self):
        """Advancing to review phase should fetch PR comments."""
        from iterate_workflow import fetch_pr_review_status, set_pr_number

        start("test task")
        set_pr_number(10)  # Must set PR number for auto-fetch
        set_phase(Phase.TEST)
        set_test_results(True, True, True)

        with patch("iterate_workflow.fetch_pr_review_status") as mock_fetch:
            mock_fetch.return_value = [
                {"id": "123", "body": "Fix this"},
            ]

            advance_phase()  # -> review

            assert get_phase() == Phase.REVIEW
            # fetch should have been called with the PR number
            mock_fetch.assert_called_once_with(10)

    def test_fetched_comments_added_to_queue(self):
        """Fetched comments should appear in pending review tasks."""
        start("test task")
        set_phase(Phase.REVIEW)

        with patch("iterate_workflow.fetch_pr_review_status") as mock_fetch:
            mock_fetch.return_value = [
                {"id": "PR-123", "body": "Fix the bug in line 42"},
            ]

            # Trigger auto-fetch (e.g., via refresh function)
            from iterate_workflow import refresh_review_status
            refresh_review_status(10)

            tasks = get_pending_review_tasks()
            assert len(tasks) >= 1
            assert any("Fix the bug" in t["description"] for t in tasks)


class TestReviewBlockingWithAutoCheck:
    """Tests for blocking advancement until comments addressed."""

    def test_review_blocked_with_unaddressed_comments(self):
        """Should block review advancement if fetched comments unaddressed."""
        start("test task")
        set_phase(Phase.REVIEW)

        with patch("iterate_workflow.fetch_pr_review_status") as mock_fetch:
            mock_fetch.return_value = [
                {"id": "123", "body": "Critical fix needed"},
            ]

            from iterate_workflow import refresh_review_status
            refresh_review_status(10)

            assert is_review_blocked() is True

    def test_review_unblocked_after_addressing_comments(self):
        """Should unblock after all fetched comments addressed."""
        from iterate_workflow import mark_review_task_done, refresh_review_status

        start("test task")
        set_phase(Phase.REVIEW)

        with patch("iterate_workflow.fetch_pr_review_status") as mock_fetch:
            mock_fetch.return_value = [
                {"id": "123", "body": "Fix this"},
            ]

            refresh_review_status(10)

            # Address the comment
            tasks = get_pending_review_tasks()
            for task in tasks:
                mark_review_task_done(task["id"])

            assert is_review_blocked() is False


class TestPRNumberTracking:
    """Tests for tracking PR number in workflow state."""

    def test_pr_number_stored_in_state(self):
        """PR number should be stored in state for auto-refresh."""
        from iterate_workflow import set_pr_number, get_pr_number

        start("test task")
        set_pr_number(42)

        assert get_pr_number() == 42

    def test_pr_number_persists_across_loads(self):
        """PR number should persist after state reload."""
        from iterate_workflow import set_pr_number, get_pr_number
        import state_manager

        start("test task")
        set_pr_number(123)

        # Force reload
        state = state_manager.get_state("orchestrator")
        assert state.get("pr_number") == 123

    def test_advance_to_review_uses_stored_pr(self):
        """Advancing to review should use stored PR number for fetch."""
        from iterate_workflow import set_pr_number

        start("test task")
        set_pr_number(10)
        set_phase(Phase.TEST)
        set_test_results(True, True, True)

        with patch("iterate_workflow.fetch_pr_review_status") as mock_fetch:
            mock_fetch.return_value = []

            advance_phase()  # -> review

            # Should fetch using stored PR number
            mock_fetch.assert_called_with(10)
