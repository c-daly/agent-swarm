#!/usr/bin/env python3
"""Tests for iterate_workflow.py - minimal TDD workflow with phase gates."""

import sys
from pathlib import Path

import pytest

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from iterate_workflow import (
    Phase,
    PHASE_TOOLS,
    start,
    stop,
    get_state,
    get_phase,
    is_active,
    set_phase,
    advance_phase,
    set_test_results,
    set_review_status,
    is_tool_allowed,
    status,
    STATE_FILE,
    LOG_FILE,
    _reset_logger,
)


@pytest.fixture(autouse=True)
def clean_state():
    """Clean state before and after each test."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    yield
    if STATE_FILE.exists():
        STATE_FILE.unlink()


@pytest.fixture(autouse=True)
def clean_logging():
    """Clean logging state before and after each test."""
    _reset_logger()
    if LOG_FILE.exists():
        LOG_FILE.unlink()
    yield
    _reset_logger()


class TestPhaseEnum:
    """Tests for Phase enum."""

    def test_phases_exist(self):
        """All expected phases should exist."""
        assert Phase.TEST_WRITING.value == "test_writing"
        assert Phase.IMPLEMENT.value == "implement"
        assert Phase.TEST.value == "test"
        assert Phase.REVIEW.value == "review"
        assert Phase.DONE.value == "done"


class TestPhaseTools:
    """Tests for phase tool restrictions."""

    def test_test_phase_blocks_edit_write(self):
        """Test phase should block Edit and Write."""
        assert "Edit" in PHASE_TOOLS[Phase.TEST]["blocked"]
        assert "Write" in PHASE_TOOLS[Phase.TEST]["blocked"]

    def test_test_phase_allows_read_bash(self):
        """Test phase should allow Read and Bash."""
        assert "Read" in PHASE_TOOLS[Phase.TEST]["allowed"]
        assert "Bash" in PHASE_TOOLS[Phase.TEST]["allowed"]

    def test_implement_phase_allows_editing(self):
        """Implement phase should allow editing tools."""
        assert "Edit" in PHASE_TOOLS[Phase.IMPLEMENT]["allowed"]
        assert "Write" in PHASE_TOOLS[Phase.IMPLEMENT]["allowed"]

    def test_test_writing_allows_editing(self):
        """Test writing phase should allow editing tools."""
        assert "Edit" in PHASE_TOOLS[Phase.TEST_WRITING]["allowed"]
        assert "Write" in PHASE_TOOLS[Phase.TEST_WRITING]["allowed"]


class TestWorkflowStart:
    """Tests for starting the workflow."""

    def test_start_creates_state(self):
        """Start should create state file."""
        start("Test task")
        assert STATE_FILE.exists()

    def test_start_sets_active(self):
        """Start should set active flag."""
        start("Test task")
        assert is_active() is True

    def test_start_sets_task(self):
        """Start should set task description."""
        start("My test task")
        state = get_state()
        assert state["task"] == "My test task"

    def test_start_sets_test_writing_phase(self):
        """Start should begin in test_writing phase."""
        start("Test task")
        assert get_phase() == Phase.TEST_WRITING

    def test_start_with_max_iterations(self):
        """Start should accept max_iterations parameter."""
        start("Test task", max_iterations=10)
        state = get_state()
        assert state["max_iterations"] == 10


class TestWorkflowStop:
    """Tests for stopping the workflow."""

    def test_stop_sets_inactive(self):
        """Stop should set active to False."""
        start("Test task")
        stop()
        assert is_active() is False

    def test_stop_sets_exit_reason(self):
        """Stop should set exit reason."""
        start("Test task")
        stop("custom_reason")
        state = get_state()
        assert state["exit_reason"] == "custom_reason"


class TestPhaseAdvancement:
    """Tests for phase advancement logic."""

    def test_advance_from_test_writing_to_implement(self):
        """Advancing from test_writing should go to implement."""
        start("Test task")
        new_phase = advance_phase()
        assert new_phase == Phase.IMPLEMENT

    def test_advance_from_implement_to_test(self):
        """Advancing from implement should go to test."""
        start("Test task")
        advance_phase()  # test_writing -> implement
        new_phase = advance_phase()
        assert new_phase == Phase.TEST

    def test_advance_from_test_to_review_when_all_pass(self):
        """Advancing from test should go to review when all pass."""
        start("Test task")
        advance_phase()  # test_writing -> implement
        advance_phase()  # implement -> test
        set_test_results(tests_passed=True, lint_passed=True, coverage_ok=True)
        new_phase = advance_phase()
        assert new_phase == Phase.REVIEW

    def test_advance_from_test_kickback_to_test_writing_on_coverage_fail(self):
        """Low coverage should kick back to test_writing."""
        start("Test task")
        advance_phase()  # test_writing -> implement
        advance_phase()  # implement -> test
        set_test_results(tests_passed=True, lint_passed=True, coverage_ok=False)
        new_phase = advance_phase()
        assert new_phase == Phase.TEST_WRITING

    def test_advance_from_test_kickback_to_implement_on_test_fail(self):
        """Failed tests should kick back to implement."""
        start("Test task")
        advance_phase()  # test_writing -> implement
        advance_phase()  # implement -> test
        set_test_results(tests_passed=False, lint_passed=True, coverage_ok=True)
        new_phase = advance_phase()
        assert new_phase == Phase.IMPLEMENT

    def test_advance_from_test_kickback_to_implement_on_lint_fail(self):
        """Failed lint should kick back to implement."""
        start("Test task")
        advance_phase()  # test_writing -> implement
        advance_phase()  # implement -> test
        set_test_results(tests_passed=True, lint_passed=False, coverage_ok=True)
        new_phase = advance_phase()
        assert new_phase == Phase.IMPLEMENT

    def test_advance_from_review_to_done_when_clean(self):
        """Clean review should complete workflow."""
        start("Test task")
        advance_phase()  # test_writing -> implement
        advance_phase()  # implement -> test
        set_test_results(tests_passed=True, lint_passed=True, coverage_ok=True)
        advance_phase()  # test -> review
        set_review_status(clean=True)
        new_phase = advance_phase()
        assert new_phase is None  # Workflow ended
        assert is_active() is False
        state = get_state()
        assert state["exit_reason"] == "review_approved"

    def test_advance_from_review_kickback_to_implement_on_issues(self):
        """Review issues should kick back to implement."""
        start("Test task")
        advance_phase()  # test_writing -> implement
        advance_phase()  # implement -> test
        set_test_results(tests_passed=True, lint_passed=True, coverage_ok=True)
        advance_phase()  # test -> review
        set_review_status(clean=False)
        new_phase = advance_phase()
        assert new_phase == Phase.IMPLEMENT


class TestIterationLimit:
    """Tests for max iteration enforcement."""

    def test_max_iterations_exits_workflow(self):
        """Reaching max iterations should exit workflow."""
        start("Test task", max_iterations=2)

        # Iteration 1: test_writing -> implement -> test (fail) -> implement
        advance_phase()  # test_writing -> implement
        advance_phase()  # implement -> test
        set_test_results(tests_passed=False, lint_passed=True, coverage_ok=True)
        advance_phase()  # test -> implement (kickback, iteration=1)

        # Iteration 2: implement -> test (fail) -> exits
        advance_phase()  # implement -> test
        set_test_results(tests_passed=False, lint_passed=True, coverage_ok=True)
        new_phase = advance_phase()  # test -> exits (iteration=2 >= max=2)

        assert new_phase is None
        assert is_active() is False
        state = get_state()
        assert state["exit_reason"] == "max_iterations"


class TestToolAllowance:
    """Tests for is_tool_allowed function."""

    def test_no_active_workflow_allows_all(self):
        """When no workflow active, all tools should be allowed."""
        allowed, reason = is_tool_allowed("Edit")
        assert allowed is True

    def test_test_phase_blocks_edit(self):
        """Edit should be blocked in test phase."""
        start("Test task")
        set_phase(Phase.TEST)
        allowed, reason = is_tool_allowed("Edit")
        assert allowed is False
        assert "BLOCKED" in reason

    def test_test_phase_blocks_write(self):
        """Write should be blocked in test phase."""
        start("Test task")
        set_phase(Phase.TEST)
        allowed, reason = is_tool_allowed("Write")
        assert allowed is False
        assert "BLOCKED" in reason

    def test_test_phase_allows_read(self):
        """Read should be allowed in test phase."""
        start("Test task")
        set_phase(Phase.TEST)
        allowed, reason = is_tool_allowed("Read")
        assert allowed is True

    def test_implement_phase_allows_edit(self):
        """Edit should be allowed in implement phase."""
        start("Test task")
        set_phase(Phase.IMPLEMENT)
        allowed, reason = is_tool_allowed("Edit")
        assert allowed is True

    def test_mcp_tool_variant_allowed(self):
        """MCP tool variants should be checked correctly."""
        start("Test task")
        set_phase(Phase.TEST)
        # Unknown MCP tool should be allowed by default
        allowed, _ = is_tool_allowed("mcp__some_server__read_file")
        assert allowed is True


class TestStatus:
    """Tests for status output."""

    def test_status_shows_active(self):
        """Status should indicate active workflow."""
        start("Test task")
        output = status()
        assert "[ITERATE] Active" in output

    def test_status_shows_phase(self):
        """Status should show current phase."""
        start("Test task")
        output = status()
        assert "test_writing" in output

    def test_status_shows_task(self):
        """Status should show task description."""
        start("My task")
        output = status()
        assert "My task" in output

    def test_status_shows_not_active_when_stopped(self):
        """Status should indicate inactive after stop."""
        start("Test task")
        stop()
        output = status()
        assert "Not active" in output or "Completed" in output


class TestLogging:
    """Tests for logging functionality."""

    def test_log_file_created_on_start(self):
        """Starting workflow should create log file."""
        start("Test logging task")
        stop()
        assert LOG_FILE.exists(), "Log file should be created after workflow start"

    def test_log_contains_start_entry(self):
        """Log should contain workflow start entry."""
        start("Test logging task")
        stop()
        log_content = LOG_FILE.read_text()
        assert "Workflow started" in log_content, "Log should contain start entry"
        assert "Test logging task" in log_content, "Log should contain task name"

    def test_log_contains_phase_transitions(self):
        """Log should contain phase transition entries."""
        start("Test task")
        advance_phase()  # test_writing -> implement
        stop()
        log_content = LOG_FILE.read_text()
        assert "Phase transition" in log_content, "Log should contain phase transition"
        assert "test_writing" in log_content, "Log should show from phase"
        assert "implement" in log_content, "Log should show to phase"

    def test_log_contains_test_results(self):
        """Log should contain test results recording."""
        start("Test task")
        set_test_results(True, True, False)
        stop()
        log_content = LOG_FILE.read_text()
        assert "Test results recorded" in log_content, "Log should contain test results"

    def test_log_contains_stop_entry(self):
        """Log should contain workflow stop entry."""
        start("Test task")
        stop("test_reason")
        log_content = LOG_FILE.read_text()
        assert "Workflow stopped" in log_content, "Log should contain stop entry"
        assert "test_reason" in log_content, "Log should contain stop reason"

    def test_logging_does_not_break_workflow(self):
        """Logging failures should not break workflow operations."""
        start("Test task")
        new_phase = advance_phase()
        assert new_phase == Phase.IMPLEMENT, "Workflow should work regardless of logging"
        stop()
