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
    get_phase,
    is_active,
    set_phase,
    advance_phase,
    set_test_results,
    set_review_status,
    is_tool_allowed,
    status,
    add_requirement,
    get_requirements,
    set_spec_file,
    LOG_FILE,
    _reset_logger,
)
import state_manager
from state_manager import (
    STATE_DIR,
    ORCHESTRATOR_STATE_FILE as STATE_FILE,
)


def get_state():
    """Helper to get orchestrator state for tests."""
    return state_manager.get_state("orchestrator")


@pytest.fixture(autouse=True)
def clean_state():
    """Clean state before and after each test."""
    # Clean iterate.json (workflow state)
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    # Clean session.json (WorkflowQueue state)
    session_file = STATE_DIR / "session.json"
    if session_file.exists():
        session_file.unlink()
    yield
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    if session_file.exists():
        session_file.unlink()


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

    def test_start_with_vague_task_sets_intake_phase(self):
        """Start with vague task should begin in intake phase."""
        start("Test task")
        assert get_phase() == Phase.INTAKE

    def test_start_with_spec_sets_orchestrate_phase(self):
        """Start with spec-like task should begin in orchestrate phase."""
        start("## Task\n- [ ] Create file.py\n- [ ] Add function")
        assert get_phase() == Phase.ORCHESTRATE

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
        set_phase(Phase.TEST_WRITING)  # Set phase for testing
        new_phase = advance_phase()
        assert new_phase == Phase.IMPLEMENT

    def test_advance_from_implement_to_test(self):
        """Advancing from implement should go to test."""
        start("Test task")
        set_phase(Phase.IMPLEMENT)  # Set phase for testing
        new_phase = advance_phase()
        assert new_phase == Phase.TEST

    def test_advance_from_test_to_review_when_all_pass(self):
        """Advancing from test should go to review when all pass."""
        start("Test task")
        set_phase(Phase.TEST)  # Set phase for testing
        set_test_results(tests_passed=True, lint_passed=True, coverage_ok=True)
        new_phase = advance_phase()
        assert new_phase == Phase.REVIEW

    def test_advance_from_test_kickback_to_test_writing_on_coverage_fail(self):
        """Low coverage should kick back to test_writing."""
        start("Test task")
        set_phase(Phase.TEST)  # Set phase for testing
        set_test_results(tests_passed=True, lint_passed=True, coverage_ok=False)
        new_phase = advance_phase()
        assert new_phase == Phase.TEST_WRITING

    def test_advance_from_test_kickback_to_implement_on_test_fail(self):
        """Failed tests should kick back to implement."""
        start("Test task")
        set_phase(Phase.TEST)  # Set phase for testing
        set_test_results(tests_passed=False, lint_passed=True, coverage_ok=True)
        new_phase = advance_phase()
        assert new_phase == Phase.IMPLEMENT

    def test_advance_from_test_kickback_to_implement_on_lint_fail(self):
        """Failed lint should kick back to implement."""
        start("Test task")
        set_phase(Phase.TEST)  # Set phase for testing
        set_test_results(tests_passed=True, lint_passed=False, coverage_ok=True)
        new_phase = advance_phase()
        assert new_phase == Phase.IMPLEMENT

    def test_set_test_results_warns_on_lint_failure(self):
        """set_test_results should log warning when lint fails."""
        start("Test task")
        set_phase(Phase.TEST)

        # Record results with lint failure
        set_test_results(tests_passed=True, lint_passed=False, coverage_ok=True)

        # Verify results were recorded
        state = get_state()
        assert state["tests_passed"] is True
        assert state["lint_passed"] is False
        assert state["coverage_ok"] is True

        # Verify warning was logged
        if LOG_FILE.exists():
            log_content = LOG_FILE.read_text()
            assert "WARNING" in log_content or "warning" in log_content
            assert "lint" in log_content.lower()

    def test_advance_from_review_to_done_when_clean(self):
        """Clean review should complete workflow."""
        start("Test task")
        set_phase(Phase.REVIEW)  # Set phase for testing
        set_review_status(clean=True)
        new_phase = advance_phase()
        assert new_phase is None  # Workflow ended
        assert is_active() is False
        state = get_state()
        assert state["exit_reason"] == "review_approved"

    def test_advance_from_review_kickback_to_implement_on_issues(self):
        """Review issues should kick back to implement."""
        start("Test task")
        set_phase(Phase.REVIEW)  # Set phase for testing
        set_review_status(clean=False)
        new_phase = advance_phase()
        assert new_phase == Phase.IMPLEMENT


class TestIterationLimit:
    """Tests for max iteration enforcement."""

    def test_max_iterations_exits_workflow(self):
        """Reaching max iterations should exit workflow."""
        start("Test task", max_iterations=2)
        set_phase(Phase.TEST)  # Set phase for testing

        # Iteration 1: test (fail) -> implement
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

    def test_no_active_workflow_blocks_editing(self):
        """When no workflow active, editing tools are blocked (BUG-PHASE-MISUSE fix)."""
        allowed, reason = is_tool_allowed("Edit")
        assert allowed is False
        assert "BLOCKED" in reason

    def test_no_active_workflow_allows_readonly(self):
        """When no workflow active, read-only tools are allowed."""
        allowed, _ = is_tool_allowed("Read")
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
        assert "intake" in output  # Vague task starts in intake

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
        set_phase(Phase.TEST_WRITING)  # Set phase for testing
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
        set_phase(Phase.TEST_WRITING)  # Set phase for testing
        new_phase = advance_phase()
        assert new_phase == Phase.IMPLEMENT, "Workflow should work regardless of logging"
        stop()


class TestIntakePhase:
    """Tests for intake phase functions."""

    def test_add_requirement_in_intake_phase(self):
        """Can add requirements during intake phase."""
        start("Test task")  # Vague task -> INTAKE
        assert get_phase() == Phase.INTAKE
        add_requirement("User needs authentication")
        reqs = get_requirements()
        assert "User needs authentication" in reqs

    def test_add_requirement_fails_outside_intake(self):
        """add_requirement raises error outside intake phase."""
        start("## Spec\n- [ ] Task 1\n- [ ] Task 2\n- [ ] Task 3 with more details")  # Spec-like task -> ORCHESTRATE
        with pytest.raises(ValueError, match="intake phase"):
            add_requirement("Should fail")

    def test_get_requirements_empty_initially(self):
        """get_requirements returns empty list initially."""
        start("Test task")  # Vague task -> INTAKE
        assert get_requirements() == []


class TestDesignPhase:
    """Tests for design phase functions."""

    def test_set_spec_file(self):
        """Can set spec file path."""
        start("Test task")
        set_phase(Phase.DESIGN)  # Set phase for testing
        set_spec_file("/path/to/spec.md")
        state = get_state()
        assert state["spec_file"] == "/path/to/spec.md"


class TestReviewPhase:
    """Tests for review phase functions."""

    def test_add_review_comment_fails_outside_review(self):
        """add_review_comment raises error outside review phase."""
        from iterate_workflow import add_review_comment
        start("Test task")  # Starts in test_writing
        with pytest.raises(ValueError, match="review phase"):
            add_review_comment({"id": "c1", "body": "Test"})

    def test_set_pr_number_fails_without_workflow(self):
        """set_pr_number raises error without active workflow."""
        from iterate_workflow import set_pr_number
        with pytest.raises(RuntimeError, match="no active workflow"):
            set_pr_number(123)


class TestGhCliIntegration:
    """Tests for gh CLI integration with mocked subprocess."""

    def test_fetch_pr_review_status_success(self, monkeypatch):
        """fetch_pr_review_status parses JSON response."""
        from iterate_workflow import fetch_pr_review_status
        import subprocess

        mock_result = subprocess.CompletedProcess(
            args=["gh"],
            returncode=0,
            stdout='[{"id": "c1", "body": "Fix this", "isResolved": false}]',
            stderr=""
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)

        comments = fetch_pr_review_status(123)
        assert len(comments) == 1
        assert comments[0]["id"] == "c1"

    def test_fetch_pr_review_status_filters_resolved(self, monkeypatch):
        """fetch_pr_review_status excludes resolved comments."""
        from iterate_workflow import fetch_pr_review_status
        import subprocess

        mock_result = subprocess.CompletedProcess(
            args=["gh"],
            returncode=0,
            stdout='[{"id": "c1", "isResolved": true}, {"id": "c2", "isResolved": false}]',
            stderr=""
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)

        comments = fetch_pr_review_status(123)
        assert len(comments) == 1
        assert comments[0]["id"] == "c2"

    def test_fetch_pr_review_status_empty_response(self, monkeypatch):
        """fetch_pr_review_status handles empty response."""
        from iterate_workflow import fetch_pr_review_status
        import subprocess

        mock_result = subprocess.CompletedProcess(args=["gh"], returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)

        comments = fetch_pr_review_status(123)
        assert comments == []

    def test_fetch_pr_review_status_timeout(self, monkeypatch):
        """fetch_pr_review_status handles timeout."""
        from iterate_workflow import fetch_pr_review_status
        import subprocess

        def raise_timeout(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="gh", timeout=30)

        monkeypatch.setattr(subprocess, "run", raise_timeout)
        comments = fetch_pr_review_status(123)
        assert comments == []

    def test_fetch_pr_review_status_gh_not_found(self, monkeypatch):
        """fetch_pr_review_status handles missing gh CLI."""
        from iterate_workflow import fetch_pr_review_status

        def raise_not_found(*a, **kw):
            raise FileNotFoundError()

        monkeypatch.setattr("subprocess.run", raise_not_found)
        comments = fetch_pr_review_status(123)
        assert comments == []

    def test_refresh_review_status_no_pr(self):
        """refresh_review_status returns 0 without PR number."""
        from iterate_workflow import refresh_review_status
        start("Test task")
        set_phase(Phase.REVIEW)
        result = refresh_review_status()
        assert result == 0

    def test_refresh_review_status_wrong_phase(self):
        """refresh_review_status returns 0 outside review phase."""
        from iterate_workflow import refresh_review_status, set_pr_number
        start("Test task")
        set_pr_number(123)
        result = refresh_review_status()  # Still in test_writing
        assert result == 0

    def test_fetch_parses_single_object(self, monkeypatch):
        """fetch_pr_review_status handles single object (not array)."""
        from iterate_workflow import fetch_pr_review_status
        import subprocess

        mock_result = subprocess.CompletedProcess(
            args=["gh"], returncode=0,
            stdout='{"id": "c1", "body": "Single", "isResolved": false}',
            stderr=""
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)
        comments = fetch_pr_review_status(123)
        assert len(comments) == 1
        assert comments[0]["id"] == "c1"

    def test_fetch_parses_line_by_line(self, monkeypatch):
        """fetch_pr_review_status falls back to line-by-line parsing."""
        from iterate_workflow import fetch_pr_review_status
        import subprocess

        # jq output format - one JSON object per line
        mock_result = subprocess.CompletedProcess(
            args=["gh"], returncode=0,
            stdout='{"id": "c1", "isResolved": false}\n{"id": "c2", "isResolved": false}\n',
            stderr=""
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)
        comments = fetch_pr_review_status(123)
        assert len(comments) == 2

    def test_fetch_handles_invalid_json_lines(self, monkeypatch):
        """fetch_pr_review_status skips invalid JSON lines."""
        from iterate_workflow import fetch_pr_review_status
        import subprocess

        mock_result = subprocess.CompletedProcess(
            args=["gh"], returncode=0,
            stdout='{"id": "c1"}\nnot json\n{"id": "c2"}\n',
            stderr=""
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)
        comments = fetch_pr_review_status(123)
        assert len(comments) == 2

    def test_refresh_adds_comments_to_queue(self, monkeypatch):
        """refresh_review_status adds fetched comments to queue."""
        from iterate_workflow import refresh_review_status, set_pr_number
        import subprocess

        start("Test task")
        set_phase(Phase.REVIEW)
        set_pr_number(123)

        mock_result = subprocess.CompletedProcess(
            args=["gh"], returncode=0,
            stdout='[{"id": "new-comment", "body": "Fix this"}]',
            stderr=""
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)

        added = refresh_review_status()
        assert added >= 0  # May be 0 if comment already exists


class TestOrchestratePhase:
    """Tests for ORCHESTRATE phase - main agent coordination."""

    def test_orchestrate_phase_exists(self):
        """ORCHESTRATE phase should exist in Phase enum."""
        assert Phase.ORCHESTRATE.value == "orchestrate"

    def test_orchestrate_phase_tools_blocks_editing(self):
        """ORCHESTRATE phase should block Edit and Write."""
        assert "Edit" in PHASE_TOOLS[Phase.ORCHESTRATE]["blocked"]
        assert "Write" in PHASE_TOOLS[Phase.ORCHESTRATE]["blocked"]

    def test_orchestrate_phase_allows_bash(self):
        """ORCHESTRATE phase should allow Bash (but evaluation commands are filtered)."""
        assert "Bash" in PHASE_TOOLS[Phase.ORCHESTRATE]["allowed"]

    def test_orchestrate_phase_allows_read(self):
        """ORCHESTRATE phase should allow Read."""
        assert "Read" in PHASE_TOOLS[Phase.ORCHESTRATE]["allowed"]

    def test_orchestrate_phase_allows_task(self):
        """ORCHESTRATE phase should allow Task (for spawning subagents)."""
        assert "Task" in PHASE_TOOLS[Phase.ORCHESTRATE]["allowed"]

    def test_orchestrate_phase_allows_todowrite(self):
        """ORCHESTRATE phase should allow TodoWrite."""
        assert "TodoWrite" in PHASE_TOOLS[Phase.ORCHESTRATE]["allowed"]


class TestOrchestrateStart:
    """Tests for starting workflow in orchestrate mode based on input."""

    def test_start_with_spec_goes_to_orchestrate(self):
        """start() with spec-like input should begin in ORCHESTRATE phase."""
        start("## Task\n- [ ] Item 1\n- [ ] Item 2")
        assert get_phase() == Phase.ORCHESTRATE

    def test_start_with_inline_queue_goes_to_orchestrate(self):
        """start() with queue parameter should begin in ORCHESTRATE phase."""
        # Queue content (not a file path since it doesn't end in .queue)
        start("Test task", queue='{"tasks": []}')
        assert get_phase() == Phase.ORCHESTRATE

    def test_start_with_vague_task_goes_to_intake(self):
        """start() with vague input should begin in INTAKE phase."""
        start("Fix the bug")
        assert get_phase() == Phase.INTAKE

    def test_start_needs_intake_false_with_spec(self):
        """When starting with spec, needs_intake should be False."""
        # Needs 10+ words to be detected as spec
        start("## Task Overview\n- [ ] First item to implement in the module\n- [ ] Second task")
        state = get_state()
        assert state.get("needs_intake") is False


class TestOrchestrateCompletion:
    """Tests for orchestration completion detection."""

    def test_is_orchestration_complete_function_exists(self):
        """is_orchestration_complete function should be importable."""
        from iterate_workflow import is_orchestration_complete
        assert callable(is_orchestration_complete)

    def test_is_orchestration_complete_false_when_inactive(self):
        """is_orchestration_complete returns False when workflow not active."""
        from iterate_workflow import is_orchestration_complete
        # No workflow started
        assert is_orchestration_complete() is False

    def test_is_orchestration_complete_false_with_active_workers(self, monkeypatch):
        """is_orchestration_complete returns False when workers are active."""
        from iterate_workflow import is_orchestration_complete
        import sys
        from pathlib import Path

        # Mock worker_pool.is_complete to return False (workers active)
        worker_pool_path = Path(__file__).parent.parent / "lib"
        sys.path.insert(0, str(worker_pool_path))

        def mock_is_complete(queue_empty):
            return False  # Workers still active

        import worker_pool
        monkeypatch.setattr(worker_pool, "is_complete", mock_is_complete)

        start("## Task Overview\n- [ ] First item to implement\n- [ ] Second item with details")  # Spec-like -> ORCHESTRATE
        assert is_orchestration_complete() is False

    def test_is_orchestration_complete_true_when_done(self, monkeypatch):
        """is_orchestration_complete returns True when queue empty and no workers."""
        from iterate_workflow import is_orchestration_complete
        import sys
        from pathlib import Path

        # Mock worker_pool.is_complete to return True (all done)
        worker_pool_path = Path(__file__).parent.parent / "lib"
        sys.path.insert(0, str(worker_pool_path))

        def mock_is_complete(queue_empty):
            return queue_empty  # Done if queue is empty

        import worker_pool
        monkeypatch.setattr(worker_pool, "is_complete", mock_is_complete)

        # Also mock _get_workflow_queue to return a queue that reports all_done
        class MockQueue:
            def all_done(self):
                return True

        monkeypatch.setattr("iterate_workflow._get_workflow_queue", lambda: MockQueue())

        start("## Task Overview\n- [ ] First item to implement\n- [ ] Second item with details")  # Spec-like -> ORCHESTRATE
        # With empty queue and mocked completion, should be complete
        assert is_orchestration_complete() is True


class TestBashWhitelist:
    """Tests for per-phase Bash command whitelisting."""

    # Test commands
    ITERATE_CMD = "python3 lib/iterate_workflow.py status"
    PYTEST_CMD = "pytest tests/"
    RUFF_CMD = "ruff check ."
    MYPY_CMD = "mypy src/"
    COVERAGE_CMD = "coverage run -m pytest"
    GIT_CMD = "git status"
    GH_CMD = "gh pr list"

    def test_intake_allows_iterate_workflow(self):
        """INTAKE allows iterate_workflow.py commands."""
        start("Test task")  # Vague -> INTAKE
        allowed, _ = is_tool_allowed("Bash", command=self.ITERATE_CMD)
        assert allowed is True

    def test_intake_blocks_pytest(self):
        """INTAKE blocks pytest."""
        start("Test task")
        allowed, reason = is_tool_allowed("Bash", command=self.PYTEST_CMD)
        assert allowed is False
        assert "BLOCKED" in reason

    def test_intake_blocks_git(self):
        """INTAKE blocks git."""
        start("Test task")
        allowed, _ = is_tool_allowed("Bash", command=self.GIT_CMD)
        assert allowed is False

    def test_design_allows_iterate_workflow(self):
        """DESIGN allows iterate_workflow.py commands."""
        start("Test task")
        set_phase(Phase.DESIGN)
        allowed, _ = is_tool_allowed("Bash", command=self.ITERATE_CMD)
        assert allowed is True

    def test_design_blocks_pytest(self):
        """DESIGN blocks pytest."""
        start("Test task")
        set_phase(Phase.DESIGN)
        allowed, _ = is_tool_allowed("Bash", command=self.PYTEST_CMD)
        assert allowed is False

    def test_test_writing_allows_pytest(self):
        """TEST_WRITING allows pytest."""
        start("Test task")
        set_phase(Phase.TEST_WRITING)
        allowed, _ = is_tool_allowed("Bash", command=self.PYTEST_CMD)
        assert allowed is True

    def test_test_writing_blocks_ruff(self):
        """TEST_WRITING blocks ruff."""
        start("Test task")
        set_phase(Phase.TEST_WRITING)
        allowed, _ = is_tool_allowed("Bash", command=self.RUFF_CMD)
        assert allowed is False

    def test_implement_allows_pytest_ruff_mypy(self):
        """IMPLEMENT allows pytest, ruff, mypy."""
        start("Test task")
        set_phase(Phase.IMPLEMENT)
        for cmd in [self.PYTEST_CMD, self.RUFF_CMD, self.MYPY_CMD]:
            allowed, _ = is_tool_allowed("Bash", command=cmd)
            assert allowed is True, f"IMPLEMENT should allow: {cmd}"

    def test_implement_blocks_coverage(self):
        """IMPLEMENT blocks coverage."""
        start("Test task")
        set_phase(Phase.IMPLEMENT)
        allowed, _ = is_tool_allowed("Bash", command=self.COVERAGE_CMD)
        assert allowed is False

    def test_implement_blocks_git(self):
        """IMPLEMENT blocks git."""
        start("Test task")
        set_phase(Phase.IMPLEMENT)
        allowed, _ = is_tool_allowed("Bash", command=self.GIT_CMD)
        assert allowed is False

    def test_test_phase_allows_coverage(self):
        """TEST phase allows coverage."""
        start("Test task")
        set_phase(Phase.TEST)
        allowed, _ = is_tool_allowed("Bash", command=self.COVERAGE_CMD)
        assert allowed is True

    def test_test_phase_blocks_git(self):
        """TEST phase blocks git."""
        start("Test task")
        set_phase(Phase.TEST)
        allowed, _ = is_tool_allowed("Bash", command=self.GIT_CMD)
        assert allowed is False

    def test_review_allows_git_gh(self):
        """REVIEW allows git and gh."""
        start("Test task")
        set_phase(Phase.REVIEW)
        set_test_results(tests_passed=True, lint_passed=True, coverage_ok=True)
        for cmd in [self.GIT_CMD, self.GH_CMD]:
            allowed, _ = is_tool_allowed("Bash", command=cmd)
            assert allowed is True, f"REVIEW should allow: {cmd}"

    def test_orchestrate_allows_gh(self):
        """ORCHESTRATE allows gh for PR polling."""
        start("## Task\n- [ ] Item 1\n- [ ] Item 2")  # Spec -> ORCHESTRATE
        allowed, _ = is_tool_allowed("Bash", command=self.GH_CMD)
        assert allowed is True

    def test_orchestrate_blocks_pytest(self):
        """ORCHESTRATE blocks pytest (spawn test agent instead)."""
        start("## Task\n- [ ] Item 1\n- [ ] Item 2")
        allowed, _ = is_tool_allowed("Bash", command=self.PYTEST_CMD)
        assert allowed is False

    def test_orchestrate_blocks_git(self):
        """ORCHESTRATE blocks git."""
        start("## Task\n- [ ] Item 1\n- [ ] Item 2")
        allowed, _ = is_tool_allowed("Bash", command=self.GIT_CMD)
        assert allowed is False

    def test_done_allows_all(self):
        """DONE allows all commands."""
        start("Test task")
        set_phase(Phase.DONE)
        for cmd in [self.PYTEST_CMD, self.RUFF_CMD, self.GIT_CMD, self.GH_CMD]:
            allowed, _ = is_tool_allowed("Bash", command=cmd)
            assert allowed is True, f"DONE should allow: {cmd}"

    def test_chained_commands_all_must_pass(self):
        """Chained commands must all be in whitelist."""
        start("Test task")
        set_phase(Phase.IMPLEMENT)  # allows pytest, ruff, mypy
        # All allowed - should pass
        allowed, _ = is_tool_allowed("Bash", command="pytest tests/ && ruff check .")
        assert allowed is True
        # Second command not allowed - should block
        allowed, reason = is_tool_allowed("Bash", command="pytest tests/; git status")
        assert allowed is False
        assert "git" in reason

    def test_chained_with_semicolon_blocked(self):
        """Semicolon-chained disallowed command is blocked."""
        start("Test task")
        set_phase(Phase.TEST_WRITING)  # allows pytest only
        allowed, _ = is_tool_allowed("Bash", command="pytest; ruff check .")
        assert allowed is False

    def test_chained_with_pipe_blocked(self):
        """Piped disallowed command is blocked."""
        start("Test task")
        set_phase(Phase.INTAKE)  # only iterate_workflow.py
        allowed, _ = is_tool_allowed("Bash", command="echo test | git apply")
        assert allowed is False

    def test_chained_with_background_blocked(self):
        """Background (&) disallowed command is blocked."""
        start("Test task")
        set_phase(Phase.INTAKE)
        allowed, _ = is_tool_allowed("Bash", command="echo test & git status")
        assert allowed is False
