"""Tests for automatic review polling functionality."""

import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
import sys
from pathlib import Path

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

import orchestrate  # noqa: E402
import iterate_workflow  # noqa: E402
import workflow_client  # noqa: E402


@pytest.fixture(autouse=True)
def setup_teardown():
    """Clear state before and after each test."""
    # Clear orchestrator state
    workflow_client.workflow_stop("iterate")
    # Clear any orchestrate state
    try:
        orchestrate.stop_orchestrate("test_cleanup")
    except Exception:
        pass
    yield
    # Cleanup after test
    workflow_client.workflow_stop("iterate")
    try:
        orchestrate.stop_orchestrate("test_cleanup")
    except Exception:
        pass


@pytest.fixture
def mock_gh_comments():
    """Mock GitHub PR comments response."""
    return [
        {
            "id": "comment-1",
            "body": "Please fix the error handling",
            "path": "lib/orchestrate.py",
            "isResolved": False,
        },
        {
            "id": "comment-2",
            "body": "Add type hints",
            "path": "lib/iterate_workflow.py",
            "isResolved": False,
        },
    ]


class TestCheckReviewPollIntegration:
    """Test check_review_poll() with actual comment fetching."""

    def test_poll_not_triggered_when_inactive(self):
        """Poll should not trigger when orchestrate is inactive."""
        result = orchestrate.check_review_poll()
        assert result is False

    def test_poll_not_triggered_without_push(self):
        """Poll should not trigger when push_pending is False."""
        config = orchestrate.OrchestrateConfig(pr_id="test-pr")
        orchestrate.start_orchestrate(config)

        result = orchestrate.check_review_poll()
        assert result is False

    def test_poll_respects_interval(self):
        """Poll should not trigger before interval elapsed."""
        config = orchestrate.OrchestrateConfig(
            pr_id="test-pr",
            review_poll_interval_minutes=5
        )
        orchestrate.start_orchestrate(config)

        # Set push_pending and last_poll to 2 minutes ago
        state = orchestrate._load_state()
        state.push_pending = True
        two_min_ago = datetime.now(timezone.utc) - timedelta(minutes=2)
        state.last_poll = two_min_ago.isoformat().replace("+00:00", "Z")
        orchestrate._save_state(state)

        result = orchestrate.check_review_poll()
        assert result is False  # Too soon

    def test_poll_triggers_after_interval(self):
        """Poll should trigger after interval elapsed."""
        config = orchestrate.OrchestrateConfig(
            pr_id="test-pr",
            review_poll_interval_minutes=5
        )
        orchestrate.start_orchestrate(config)

        # Set push_pending and last_poll to 6 minutes ago
        state = orchestrate._load_state()
        state.push_pending = True
        six_min_ago = datetime.now(timezone.utc) - timedelta(minutes=6)
        state.last_poll = six_min_ago.isoformat().replace("+00:00", "Z")
        orchestrate._save_state(state)

        result = orchestrate.check_review_poll()
        assert result is True

    def test_first_poll_triggers_immediately(self):
        """First poll should trigger immediately after push."""
        config = orchestrate.OrchestrateConfig(pr_id="test-pr")
        orchestrate.start_orchestrate(config)

        # Set push_pending but no last_poll
        state = orchestrate._load_state()
        state.push_pending = True
        orchestrate._save_state(state)

        result = orchestrate.check_review_poll()
        assert result is True


class TestCommentFetching:
    """Test fetching comments from GitHub."""

    @patch("subprocess.run")
    def test_fetch_pr_review_status_success(self, mock_run, mock_gh_comments):
        """Should fetch and parse PR comments successfully."""
        # Mock gh CLI response
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "\n".join(json.dumps(c) for c in mock_gh_comments)
        mock_run.return_value = mock_result

        comments = iterate_workflow.fetch_pr_review_status(123)

        assert len(comments) == 2
        assert comments[0]["id"] == "comment-1"
        assert comments[1]["id"] == "comment-2"
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_fetch_filters_resolved_comments(self, mock_run):
        """Should filter out resolved comments."""
        comments_with_resolved = [
            {"id": "c1", "body": "Fix this", "isResolved": False},
            {"id": "c2", "body": "Already fixed", "isResolved": True},
            {"id": "c3", "body": "Another issue", "isResolved": False},
        ]

        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "\n".join(json.dumps(c) for c in comments_with_resolved)
        mock_run.return_value = mock_result

        comments = iterate_workflow.fetch_pr_review_status(123)

        assert len(comments) == 2
        assert comments[0]["id"] == "c1"
        assert comments[1]["id"] == "c3"

    @patch("subprocess.run")
    def test_fetch_handles_gh_error(self, mock_run):
        """Should handle gh CLI errors gracefully."""
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "Error: PR not found"
        mock_run.return_value = mock_result

        comments = iterate_workflow.fetch_pr_review_status(123)

        assert comments == []

    @patch("subprocess.run")
    def test_fetch_handles_timeout(self, mock_run):
        """Should handle subprocess timeout."""
        import subprocess  # noqa: E402
        mock_run.side_effect = subprocess.TimeoutExpired("gh", 30)

        comments = iterate_workflow.fetch_pr_review_status(123)

        assert comments == []


class TestCommentProcessing:
    """Test processing comments into tasks."""

    def test_process_review_comments_adds_tasks(self, mock_gh_comments):
        """Should convert comments to tasks in queue."""
        config = orchestrate.OrchestrateConfig(pr_id="test-pr")
        orchestrate.start_orchestrate(config)

        # Enable orchestrate state
        state = orchestrate._load_state()
        state.push_pending = True
        orchestrate._save_state(state)

        count = orchestrate.process_review_comments(mock_gh_comments)

        assert count == 2

    def test_process_comments_resets_push_pending(self, mock_gh_comments):
        """Should reset push_pending when comments added."""
        config = orchestrate.OrchestrateConfig(pr_id="test-pr")
        orchestrate.start_orchestrate(config)

        state = orchestrate._load_state()
        state.push_pending = True
        orchestrate._save_state(state)

        orchestrate.process_review_comments(mock_gh_comments)

        state = orchestrate._load_state()
        assert state.push_pending is False
        assert state.review_pending is False

    def test_process_no_comments_unchanged(self):
        """Should not change state when no comments."""
        config = orchestrate.OrchestrateConfig(pr_id="test-pr")
        orchestrate.start_orchestrate(config)

        state = orchestrate._load_state()
        state.push_pending = True
        orchestrate._save_state(state)

        count = orchestrate.process_review_comments([])

        assert count == 0
        state = orchestrate._load_state()
        assert state.push_pending is True  # Still pending


class TestReviewPhaseAutoFetch:
    """Test automatic comment fetching when entering REVIEW phase."""

    @patch("iterate_workflow.refresh_review_status")
    def test_advance_to_review_triggers_fetch(self, mock_refresh):
        """Should auto-fetch comments when entering REVIEW phase."""
        # Start workflow and advance to TEST phase
        iterate_workflow.start("test task")
        iterate_workflow.set_phase(iterate_workflow.Phase.TEST)

        # Set test results to pass and PR number
        state = workflow_client.workflow_get_state("iterate")
        state["tests_passed"] = True
        state["lint_passed"] = True
        state["coverage_ok"] = True
        state["pr_number"] = 123
        workflow_client.workflow_set_state("iterate", state)

        # Advance to REVIEW phase
        iterate_workflow.advance_phase()

        # Should have called refresh_review_status
        mock_refresh.assert_called_once_with(123)

    def test_advance_to_review_without_pr_skips_fetch(self):
        """Should skip auto-fetch when PR number not set."""
        # Start workflow and advance to TEST phase
        iterate_workflow.start("test task")
        iterate_workflow.set_phase(iterate_workflow.Phase.TEST)

        # Set test results to pass but NO PR number
        state = workflow_client.workflow_get_state("iterate")
        state["tests_passed"] = True
        state["lint_passed"] = True
        state["coverage_ok"] = True
        # pr_number not set
        workflow_client.workflow_set_state("iterate", state)

        # Advance to REVIEW phase - should not raise error
        phase = iterate_workflow.advance_phase()

        assert phase == iterate_workflow.Phase.REVIEW


class TestEndToEndPolling:
    """End-to-end tests for automatic polling workflow."""

    @patch("subprocess.run")
    def test_complete_polling_cycle(self, mock_run, mock_gh_comments):
        """Test complete cycle: push → poll → fetch → process."""
        # Setup orchestrate
        config = orchestrate.OrchestrateConfig(
            pr_id="test-pr",
            review_poll_interval_minutes=5
        )
        orchestrate.start_orchestrate(config)

        # Setup iterate workflow with PR number
        iterate_workflow.start("test task")
        state = workflow_client.workflow_get_state("iterate")
        state["pr_number"] = 123
        workflow_client.workflow_set_state("iterate", state)

        # Simulate push (sets push_pending=True)
        orch_state = orchestrate._load_state()
        orch_state.push_pending = True
        orchestrate._save_state(orch_state)

        # Mock gh CLI response
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "\n".join(json.dumps(c) for c in mock_gh_comments)
        mock_run.return_value = mock_result

        # Trigger poll check (should poll immediately on first check)
        polled = orchestrate.check_review_poll()

        assert polled is True

        # Fetch and process comments
        comments = iterate_workflow.fetch_pr_review_status(123)
        assert len(comments) == 2

        tasks_added = orchestrate.process_review_comments(comments)
        assert tasks_added == 2

        # Verify state updated
        orch_state = orchestrate._load_state()
        assert orch_state.push_pending is False
        assert orch_state.last_poll is not None
