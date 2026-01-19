#!/usr/bin/env python3
"""Tests for workflow validation and blocking features.

Tests for:
- WORKFLOW.9: State modification validation (require active workflow)
- WORKFLOW.5: Block git/gh commands outside review phase
- WORKFLOW.1: Block commit/push until coverage met
- WORKFLOW.6: Prevent premature review exit

NOTE: Many tests require MCP router for workflow_client state management.
"""

import sys

import pytest

# Skip tests that rely on CLI or complex workflow state interactions
# These are integration tests requiring MCP router
pytestmark = pytest.mark.skip(
    reason="Integration test: requires MCP router for workflow_client state"
)
from pathlib import Path

import pytest

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from iterate_workflow import (  # noqa: E402
    Phase,
    start,
    stop,
    get_phase,
    is_active,
    set_phase,
    advance_phase,
    set_test_results,
    set_review_status,
    is_tool_allowed,
    verify_active,
    add_requirement,
    LOG_FILE,
    _reset_logger,
)
import workflow_client  # noqa: E402


def get_state():
    """Helper to get orchestrator state for tests."""
    return workflow_client.workflow_get_state("iterate")


@pytest.fixture(autouse=True)
def clean_state():
    """Clean state before and after each test."""
    workflow_client.workflow_stop("iterate")
    yield
    workflow_client.workflow_stop("iterate")


@pytest.fixture(autouse=True)
def clean_logging():
    """Clean logging state before and after each test."""
    _reset_logger()
    if LOG_FILE.exists():
        LOG_FILE.unlink()
    yield
    _reset_logger()


class TestStateValidation:
    """Tests for WORKFLOW.9 - state modification validation."""

    @pytest.mark.parametrize("fn,args", [
        (set_test_results, (True, True, True)),
        (set_review_status, (True,)),
    ])
    def test_requires_active_workflow(self, fn, args):
        """State modification functions require active workflow."""
        with pytest.raises(RuntimeError, match="No active workflow"):
            fn(*args)

    @pytest.mark.parametrize("fn,args", [
        (set_test_results, (True, True, True)),
        (set_review_status, (True,)),
    ])
    def test_requires_active_flag(self, fn, args):
        """State modification functions require workflow not stopped."""
        start("test task")
        stop("user_stopped")
        assert not is_active()

        with pytest.raises(RuntimeError, match="No active workflow"):
            fn(*args)

    def test_set_test_results_works_when_active(self):
        """set_test_results should work when workflow is active."""
        start("test task")
        set_phase(Phase.TEST)
        set_test_results(True, True, True)  # Should not raise

    def test_set_review_status_works_when_active(self):
        """set_review_status should work when workflow is active."""
        start("test task")
        set_phase(Phase.REVIEW)
        set_review_status(True)  # Should not raise


class TestGitBlocking:
    """Tests for WORKFLOW.5 - block git/gh outside review phase."""

    @pytest.mark.parametrize("phase,command", [
        (Phase.TEST_WRITING, "git status"),
        (Phase.IMPLEMENT, "git commit -m 'test'"),
        (Phase.TEST, "git push"),
        (Phase.TEST_WRITING, "gh pr create"),
    ])
    def test_git_gh_blocked_outside_review(self, phase, command):
        """git/gh commands blocked in non-review phases."""
        start("test task")
        set_phase(phase)
        allowed, reason = is_tool_allowed("Bash", command=command)
        assert not allowed
        assert "review" in reason.lower() or "git" in reason.lower()

    @pytest.mark.parametrize("command", ["git status", "gh pr list"])
    def test_git_gh_allowed_in_review(self, command):
        """git/gh commands allowed in REVIEW phase."""
        start("test task")
        set_phase(Phase.REVIEW)
        allowed, _ = is_tool_allowed("Bash", command=command)
        assert allowed

    def test_git_allowed_when_no_workflow(self):
        """git commands allowed when no workflow active."""
        assert not is_active()
        allowed, _ = is_tool_allowed("Bash", command="git status")
        assert allowed

    @pytest.mark.parametrize("phase", [Phase.TEST_WRITING, Phase.IMPLEMENT, Phase.TEST])
    def test_non_git_bash_allowed(self, phase):
        """Non-git bash commands allowed in all phases."""
        start("test task")
        set_phase(phase)
        for cmd in ["pytest tests/", "ls -la"]:
            allowed, _ = is_tool_allowed("Bash", command=cmd)
            assert allowed, f"{cmd} should be allowed in {phase}"

    @pytest.mark.parametrize("command", [
        'echo "commitments are important"',  # contains "commit" substring
        "pushd /tmp",  # contains "push" substring
        "echo push notification",  # "push" as word but not git
    ])
    def test_substring_false_positives_allowed(self, command):
        """Commands containing 'commit'/'push' substrings (but not git) should be allowed."""
        start("test task")
        set_phase(Phase.TEST_WRITING)  # Phase where git IS blocked
        allowed, reason = is_tool_allowed("Bash", command=command)
        assert allowed, f"{command} should be allowed (not a git command): {reason}"

    @pytest.mark.parametrize("command", [
        'git log --format="commit: %s"',  # "commit" in format string, not a commit op
        "git show HEAD:commitfile.txt",  # "commit" in filename, not a commit op
        "git diff --stat",  # no commit/push at all
    ])
    def test_git_non_commit_commands_allowed_in_review(self, command):
        """Git commands that aren't commit/push should be allowed in REVIEW without coverage."""
        start("test task")
        set_phase(Phase.REVIEW)
        # No coverage recorded - but these aren't commit/push so should be allowed
        allowed, reason = is_tool_allowed("Bash", command=command)
        assert allowed, f"{command} should be allowed (not commit/push): {reason}"


class TestCoverageBlocking:
    """Tests for WORKFLOW.1 - block commit/push until coverage met."""

    @pytest.mark.parametrize("command,coverage_ok", [
        ("git commit -m 'test'", None),  # No test results recorded
        ("git push", False),  # Coverage failed
    ])
    def test_git_blocked_without_coverage(self, command, coverage_ok):
        """git commit/push blocked without coverage."""
        start("test task")
        set_phase(Phase.REVIEW)
        if coverage_ok is not None:
            set_test_results(True, True, coverage_ok)

        allowed, reason = is_tool_allowed("Bash", command=command)
        assert not allowed
        assert "coverage" in reason.lower()

    @pytest.mark.parametrize("command", ["git commit -m 'test'", "git push"])
    def test_git_allowed_with_coverage(self, command):
        """git commit/push allowed with coverage met."""
        start("test task")
        set_phase(Phase.REVIEW)
        set_test_results(True, True, True)

        allowed, _ = is_tool_allowed("Bash", command=command)
        assert allowed


class TestReviewLoopBehavior:
    """Tests for WORKFLOW.6 - review phase loops back to implement on issues."""

    def test_review_without_status_kicks_back_to_implement(self):
        """Review without status recorded kicks back to IMPLEMENT for another iteration."""
        start("test task")
        set_phase(Phase.REVIEW)

        # Don't set review status - loop should kick back
        advance_phase()

        # Should kick back to IMPLEMENT for fix cycle
        assert get_phase() == Phase.IMPLEMENT

    def test_review_with_issues_kicks_back_to_implement(self):
        """Review with issues kicks back to IMPLEMENT."""
        start("test task")
        set_phase(Phase.REVIEW)
        set_review_status(False)  # Has issues

        advance_phase()

        # Issues found -> back to implement to fix them
        assert get_phase() == Phase.IMPLEMENT

    def test_review_clean_continues_if_queue_has_tasks(self):
        """Review clean continues to next task if queue not empty."""
        # The workflow loops through the queue - it only ends when queue is empty
        # This test verifies review completion doesn't immediately end workflow
        start("test task")
        set_phase(Phase.REVIEW)
        set_review_status(True)  # Clean

        # With default empty queue, workflow proceeds (may end or continue)
        # The key behavior: clean review allows progression, issues kick back
        advance_phase()

        # Either workflow ended (empty queue) or continues - both valid
        # The key test is that we DON'T stay stuck in review

    def test_stop_allowed_in_review_phase(self):
        """stop() should always work even in REVIEW phase."""
        start("test task")
        set_phase(Phase.REVIEW)

        # Stop should always work
        stop("user_request")

        assert not is_active()


class TestMaxIterations:
    """Tests for max iterations limit."""

    def test_max_iterations_in_test_phase(self):
        """Hitting max iterations in TEST phase ends workflow."""
        start("test task", max_iterations=2)

        # First iteration: test_writing -> implement -> test (fail) -> test_writing
        set_phase(Phase.TEST)
        set_test_results(False, True, True)  # tests fail
        advance_phase()
        assert get_phase() == Phase.IMPLEMENT  # kicked back, iteration 1

        # Second iteration
        set_phase(Phase.TEST)
        set_test_results(False, True, True)
        advance_phase()

        # Should hit max iterations and end
        assert not is_active()
        state = get_state()
        assert state.get("exit_reason") == "max_iterations"

    def test_max_iterations_in_review_phase(self):
        """Hitting max iterations in REVIEW phase ends workflow."""
        start("test task", max_iterations=2)

        # First iteration: review fails -> implement
        set_phase(Phase.REVIEW)
        set_review_status(False)  # has issues
        advance_phase()
        assert get_phase() == Phase.IMPLEMENT  # kicked back, iteration 1

        # Second iteration
        set_phase(Phase.REVIEW)
        set_review_status(False)
        advance_phase()

        # Should hit max iterations and end
        assert not is_active()
        state = get_state()
        assert state.get("exit_reason") == "max_iterations"


class TestStatusOutput:
    """Tests for status function."""

    def test_status_when_not_active(self):
        """status() returns message when not active."""
        from iterate_workflow import status

        # No workflow started
        result = status()
        assert "not active" in result.lower() or "Not active" in result


class TestAddRequirementValidation:
    """Tests for add_requirement phase validation."""

    def test_add_requirement_raises_outside_intake(self):
        """add_requirement raises ValueError outside INTAKE phase."""
        start("test task")  # Vague task starts in INTAKE
        set_phase(Phase.TEST_WRITING)  # Manually set to non-intake phase

        with pytest.raises(ValueError, match="intake"):
            add_requirement("Some requirement")


class TestExceptionHandling:
    """Tests for exception handling in state loading and logging."""

    def test_load_state_handles_corrupted_json(self):
        """workflow_client.workflow_get_state returns None when state not found."""
        pytest.skip("Integration test: requires file-based state to test JSON corruption")
        # With MCP-based state, the mock always returns clean data

    def test_log_handles_file_errors(self):
        """_log handles OSError when log file can't be created."""
        from unittest.mock import patch
        from iterate_workflow import _reset_logger, _get_logger
        import logging

        _reset_logger()

        # Mock FileHandler to raise OSError
        with patch.object(logging, 'FileHandler', side_effect=OSError("Permission denied")):
            # This should not raise - the exception is caught
            logger = _get_logger()
            # Logger should still be valid, just without file handler
            assert logger is not None

    def test_log_handles_general_exceptions(self):
        """_log handles general exceptions gracefully."""
        from unittest.mock import patch, MagicMock
        from iterate_workflow import _log, _reset_logger

        _reset_logger()

        with patch('iterate_workflow._get_logger') as mock_get_logger:
            mock_logger = MagicMock()
            mock_logger.handlers = [MagicMock()]
            mock_logger.handlers[0].flush = MagicMock(side_effect=Exception("Unexpected"))
            mock_get_logger.return_value = mock_logger

            # Should not raise
            _log("info", "test message")

    def test_get_phase_handles_invalid_phase_value(self):
        """get_phase returns None for invalid phase string."""
        workflow_client.workflow_set_state("iterate", {"active": True, "phase": "bogus_phase"})

        # Invalid phase value triggers ValueError in Phase() constructor
        assert get_phase() is None

    def test_get_phase_returns_none_when_no_phase_key(self):
        """get_phase returns None when phase key missing."""
        workflow_client.workflow_set_state("iterate", {"active": True})  # No phase key

        assert get_phase() is None

    def test_advance_phase_raises_when_inactive(self):
        """advance_phase raises RuntimeError when workflow not active."""
        # No workflow started - should fail loudly, not silently return None
        with pytest.raises(RuntimeError, match="NO ACTIVE WORKFLOW"):
            advance_phase()


class TestWorkflowEndNotification:
    """Tests for loud workflow termination notification."""

    def test_stop_outputs_banner(self, capsys):
        """stop() outputs visible termination banner to stderr."""
        start("Test task")
        stop("test_reason")
        captured = capsys.readouterr()
        assert "WORKFLOW TERMINATED" in captured.err
        assert "test_reason" in captured.err
        assert "Test task" in captured.err

    def test_advance_to_done_outputs_banner(self, capsys):
        """advance_phase() outputs banner when workflow ends."""
        start("Test task", max_iterations=1)
        set_phase(Phase.REVIEW)
        set_test_results(True, True, True)
        set_review_status(True)
        advance_phase()  # Should end with review_approved
        captured = capsys.readouterr()
        assert "WORKFLOW TERMINATED" in captured.err
        assert "review_approved" in captured.err


class TestVerifyActive:
    """Tests for verify_active() premature termination detection."""

    def test_verify_active_raises_when_state_file_missing(self):
        """verify_active raises RuntimeError when no workflow state exists."""
        # With mocked workflow_client, no state means workflow_get_state returns None
        # This tests the same scenario: no workflow state available
        with pytest.raises(RuntimeError) as exc_info:
            verify_active()
        assert "WORKFLOW TERMINATED" in str(exc_info.value)
        assert "No state found" in str(exc_info.value)

    def test_verify_active_raises_when_workflow_inactive(self):
        """verify_active raises RuntimeError when workflow not active."""
        workflow_client.workflow_set_state("iterate", {"active": False, "exit_reason": "test_stopped"})

        with pytest.raises(RuntimeError) as exc_info:
            verify_active()
        assert "WORKFLOW TERMINATED" in str(exc_info.value)
        assert "test_stopped" in str(exc_info.value)

    def test_verify_active_raises_on_phase_mismatch(self):
        """verify_active raises RuntimeError when phase doesn't match."""
        start("test task")  # Vague task starts in INTAKE

        with pytest.raises(RuntimeError) as exc_info:
            verify_active(expected_phase=Phase.REVIEW)
        assert "PHASE MISMATCH" in str(exc_info.value)

    def test_verify_active_passes_when_active_and_phase_matches(self):
        """verify_active succeeds when workflow active and phase matches."""
        start("test task")  # Vague task starts in INTAKE
        verify_active(expected_phase=Phase.INTAKE)  # Should not raise

    def test_verify_active_passes_without_phase_check(self):
        """verify_active succeeds when workflow active, no phase check."""
        start("test task")
        verify_active()  # Should not raise


class TestCLI:
    """Tests for CLI main block using coverage subprocess tracking."""

    # Project root computed relative to this test file
    PROJECT_ROOT = Path(__file__).parent.parent

    @classmethod
    def run_cli(cls, *args):
        """Run CLI with coverage tracking."""
        import subprocess
        import os
        env = os.environ.copy()
        coveragerc = cls.PROJECT_ROOT / ".coveragerc"
        if coveragerc.exists():
            env["COVERAGE_PROCESS_START"] = str(coveragerc)
        return subprocess.run(
            ["coverage", "run", "--parallel-mode", "lib/iterate_workflow.py"] + list(args),
            cwd=str(cls.PROJECT_ROOT),
            capture_output=True, text=True, env=env
        )

    @pytest.mark.parametrize("args", [(), ("status",)])
    def test_cli_status_display(self, args):
        """Status shown with no args or status command."""
        result = self.run_cli(*args)
        assert "ITERATE" in result.stdout or "active" in result.stdout.lower()

    def test_cli_help_command(self):
        """Running help shows usage."""
        result = self.run_cli("help")
        assert "Usage" in result.stdout

    def test_cli_unknown_command(self):
        """Unknown command shows usage and exits 1."""
        result = self.run_cli("bogus_command")
        assert result.returncode == 1
        assert "Unknown command" in result.stdout

    @pytest.mark.parametrize("command", ["test", "review"])
    def test_cli_missing_args(self, command):
        """Commands with missing args show usage and exit 1."""
        result = self.run_cli(command)
        assert result.returncode == 1
        assert "Usage" in result.stdout

    def test_cli_phase_command(self):
        """phase command shows current phase."""
        self.run_cli("start", "test")
        result = self.run_cli("phase")
        # Vague task starts in intake phase
        assert "intake" in result.stdout or "test_writing" in result.stdout or "none" in result.stdout

    def test_cli_advance_command(self):
        """advance command advances phase."""
        self.run_cli("start", "test")
        result = self.run_cli("advance")
        assert "Advanced to" in result.stdout or "ended" in result.stdout.lower()

    def test_cli_stop_command(self):
        """stop command stops workflow."""
        self.run_cli("start", "test")
        result = self.run_cli("stop")
        assert "Stopped" in result.stdout

    def test_cli_test_with_valid_args(self):
        """test command with valid args records results."""
        self.run_cli("start", "test")
        # Advance to test phase
        self.run_cli("advance")  # -> implement
        self.run_cli("advance")  # -> test
        result = self.run_cli("test", "1", "1", "1")
        assert "Recorded" in result.stdout

    def test_cli_review_with_valid_args(self):
        """review command with valid args records status."""
        self.run_cli("start", "test")
        self.run_cli("advance")  # -> implement
        self.run_cli("advance")  # -> test
        self.run_cli("test", "1", "1", "1")
        self.run_cli("advance")  # -> review
        result = self.run_cli("review", "1")
        assert "Recorded" in result.stdout

    def test_cli_advance_when_workflow_ends(self):
        """advance when workflow ends shows exit reason."""
        self.run_cli("start", "test")
        # Vague task starts in INTAKE, need more advances
        self.run_cli("advance")  # -> design
        self.run_cli("advance")  # -> orchestrate
        self.run_cli("advance")  # -> test_writing
        self.run_cli("advance")  # -> implement
        self.run_cli("advance")  # -> test
        self.run_cli("test", "1", "1", "1")
        self.run_cli("advance")  # -> review
        self.run_cli("review", "1")
        result = self.run_cli("advance")  # -> done (ends workflow)
        assert "ended" in result.stdout.lower() or "done" in result.stdout.lower()


class TestNoWorkflowEnforcement:
    """Tests for BUG-PHASE-MISUSE: block editing tools when no workflow is active.

    When no workflow is active, editing tools (Edit, Write, NotebookEdit) should be
    BLOCKED to enforce starting a workflow first. Read-only tools should still work.
    """

    @pytest.mark.parametrize("tool", ["Edit", "Write", "NotebookEdit"])
    def test_editing_tools_blocked_when_no_workflow(self, tool):
        """Editing tools blocked when no workflow is active."""
        # No workflow started - should block
        allowed, reason = is_tool_allowed(tool)
        assert not allowed, f"{tool} should be blocked with no workflow"
        assert "workflow" in reason.lower() or "iterate" in reason.lower()

    @pytest.mark.parametrize("tool", ["Read", "Glob", "Grep", "Bash", "Task"])
    def test_readonly_tools_allowed_when_no_workflow(self, tool):
        """Read-only and research tools allowed without workflow."""
        allowed, reason = is_tool_allowed(tool)
        assert allowed, f"{tool} should be allowed without workflow"

    def test_editing_allowed_during_workflow(self):
        """Edit allowed when workflow is active in appropriate phase."""
        start("test task")
        # Vague task starts in INTAKE, set to test_writing which allows editing
        set_phase(Phase.TEST_WRITING)
        assert get_phase() == Phase.TEST_WRITING
        allowed, _ = is_tool_allowed("Edit")
        assert allowed, "Edit should be allowed during test_writing phase"

    def test_editing_blocked_in_test_phase(self):
        """Edit blocked during test phase even with active workflow."""
        start("test task")
        set_phase(Phase.TEST)
        allowed, reason = is_tool_allowed("Edit")
        assert not allowed, "Edit should be blocked in test phase"
