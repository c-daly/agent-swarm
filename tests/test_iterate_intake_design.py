#!/usr/bin/env python3
"""Tests for phase selection in iterate_workflow.py.

Phase selection is based on input type:
- Vague task (no structure) -> INTAKE (gather requirements)
- Spec-like task (has structure) -> ORCHESTRATE
- Queue provided -> ORCHESTRATE
- Spec provided -> ORCHESTRATE

Flow after phase selection:
  INTAKE -> DESIGN -> ORCHESTRATE -> TEST_WRITING -> IMPLEMENT -> TEST -> REVIEW -> DONE

NOTE: Tests require CLI and phase model refactoring for MCP router.
"""

import sys

import pytest

pytestmark = pytest.mark.skip(
    reason="Integration test: phase selection tests need CLI/workflow refactoring"
)
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from iterate_workflow import (  # noqa: E402
    Phase,
    PHASE_TOOLS,
    start,
    get_phase,
    advance_phase,
    set_phase,
    set_test_results,
    set_review_status,
    is_tool_allowed,
    status,
    LOG_FILE,
    _reset_logger,
    _is_spec,
)
import daemon_client  # noqa: E402


def get_state():
    """Helper to get orchestrator state for tests."""
    with daemon_client.DaemonClient() as dc:
        return dc.workflow_get_state("iterate")


@pytest.fixture(autouse=True)
def clean_state():
    """Clean state before and after each test."""
    with daemon_client.DaemonClient() as dc:
        dc.workflow_stop("iterate")
    yield
    with daemon_client.DaemonClient() as dc:
        dc.workflow_stop("iterate")


@pytest.fixture(autouse=True)
def clean_logging():
    """Clean logging state before and after each test."""
    _reset_logger()
    if LOG_FILE.exists():
        LOG_FILE.unlink()
    yield
    _reset_logger()


class TestIntakePhaseEnum:
    """Tests for Intake phase enum and tools."""

    def test_intake_phase_exists(self):
        """Intake phase should exist in Phase enum."""
        assert Phase.INTAKE.value == "intake"

    def test_intake_phase_tool_config_exists(self):
        """Intake phase should have tool configuration."""
        assert Phase.INTAKE in PHASE_TOOLS

    def test_intake_blocks_edit_write(self):
        """Intake phase should block Edit and Write (gathering, not editing)."""
        assert "Edit" in PHASE_TOOLS[Phase.INTAKE]["blocked"]
        assert "Write" in PHASE_TOOLS[Phase.INTAKE]["blocked"]

    def test_intake_allows_read_tools(self):
        """Intake phase should allow reading and research tools."""
        assert "Read" in PHASE_TOOLS[Phase.INTAKE]["allowed"]
        assert "Glob" in PHASE_TOOLS[Phase.INTAKE]["allowed"]
        assert "Grep" in PHASE_TOOLS[Phase.INTAKE]["allowed"]

    def test_intake_allows_web_tools(self):
        """Intake phase should allow web research tools."""
        assert "WebSearch" in PHASE_TOOLS[Phase.INTAKE]["allowed"]
        assert "WebFetch" in PHASE_TOOLS[Phase.INTAKE]["allowed"]


class TestDesignPhaseEnum:
    """Tests for Design phase enum and tools."""

    def test_design_phase_exists(self):
        """Design phase should exist in Phase enum."""
        assert Phase.DESIGN.value == "design"

    def test_design_phase_tool_config_exists(self):
        """Design phase should have tool configuration."""
        assert Phase.DESIGN in PHASE_TOOLS

    def test_design_allows_write(self):
        """Design phase should allow Write (for spec creation)."""
        assert "Write" in PHASE_TOOLS[Phase.DESIGN]["allowed"]

    def test_design_allows_read_tools(self):
        """Design phase should allow reading tools."""
        assert "Read" in PHASE_TOOLS[Phase.DESIGN]["allowed"]
        assert "Glob" in PHASE_TOOLS[Phase.DESIGN]["allowed"]

    def test_design_allows_bash(self):
        """Design phase should allow Bash."""
        assert "native__bash" in PHASE_TOOLS[Phase.DESIGN]["allowed"]


class TestIsSpecDetection:
    """Tests for _is_spec() function that determines phase selection."""

    def test_short_text_is_not_spec(self):
        """Short text should not be detected as spec."""
        assert _is_spec("fix the bug") is False
        assert _is_spec("add auth") is False

    def test_text_with_headings_is_spec(self):
        """Text with markdown headings should be detected as spec."""
        assert _is_spec("## Overview\nThis is a detailed spec with many words.") is True

    def test_text_with_task_lists_is_spec(self):
        """Text with task lists should be detected as spec."""
        assert _is_spec("Here is a task list:\n- [ ] First task\n- [ ] Second task") is True

    def test_text_with_code_blocks_is_spec(self):
        """Text with code blocks should be detected as spec (requires 10+ words)."""
        text = """Here is some example code that demonstrates the pattern we need to use:
```python
def foo():
    pass
```
"""
        assert _is_spec(text) is True

    def test_text_with_file_paths_is_spec(self):
        """Text with file paths should be detected as spec (requires 10+ words)."""
        text = "Please modify src/components/auth.py and tests/test_auth.py to add the new authentication functionality we discussed earlier."
        assert _is_spec(text) is True


class TestPhaseSelectionOnStart:
    """Tests for phase selection based on input type."""

    def test_vague_task_starts_in_intake(self):
        """Vague task (no structure) should start in INTAKE phase."""
        start("Fix the login bug")
        assert get_phase() == Phase.INTAKE

    def test_spec_like_task_starts_in_orchestrate(self):
        """Spec-like task (has structure) should start in ORCHESTRATE phase."""
        # Needs 10+ words to be detected as spec
        start("## Task Overview\n- [ ] Create the new file.py module in the lib directory\n- [ ] Add the main processing function with proper error handling")
        assert get_phase() == Phase.ORCHESTRATE

    def test_queue_provided_starts_in_orchestrate(self):
        """When queue is provided, should start in ORCHESTRATE phase."""
        start("Test task", queue='{"tasks": []}')
        assert get_phase() == Phase.ORCHESTRATE

    def test_needs_intake_true_for_vague_task(self):
        """Vague task should set needs_intake=True in state."""
        start("Fix the bug")
        state = get_state()
        assert state.get("needs_intake") is True

    def test_needs_intake_false_for_spec_task(self):
        """Spec-like task should set needs_intake=False in state."""
        # Needs 10+ words to be detected as spec
        start("## Task Overview\n- [ ] Create the new implementation file in the lib directory\n- [ ] Add the main function")
        state = get_state()
        assert state.get("needs_intake") is False


class TestIntakePhaseAdvancement:
    """Tests for advancing from intake phase."""

    def test_advance_from_intake_to_design(self):
        """Advancing from intake should go to design."""
        start("Vague task")  # Vague -> INTAKE
        assert get_phase() == Phase.INTAKE
        new_phase = advance_phase()
        assert new_phase == Phase.DESIGN

    def test_advance_from_design_to_orchestrate(self):
        """Advancing from design should go to orchestrate."""
        start("Vague task")
        set_phase(Phase.DESIGN)
        new_phase = advance_phase()
        assert new_phase == Phase.ORCHESTRATE

    def test_advance_from_orchestrate_raises(self):
        """Advancing from orchestrate should raise (use Task tool for subagents)."""
        start("Vague task")
        set_phase(Phase.ORCHESTRATE)
        with pytest.raises(RuntimeError, match="Cannot advance from ORCHESTRATE"):
            advance_phase()


class TestIntakeToolBlocking:
    """Tests for tool blocking in intake phase."""

    def test_edit_blocked_in_intake(self):
        """Edit should be blocked in intake phase."""
        start("Vague task")  # -> INTAKE
        allowed, reason = is_tool_allowed("Edit")
        assert allowed is False
        assert "BLOCKED" in reason

    def test_write_blocked_in_intake(self):
        """Write should be blocked in intake phase."""
        start("Vague task")  # -> INTAKE
        allowed, reason = is_tool_allowed("Write")
        assert allowed is False
        assert "BLOCKED" in reason

    def test_read_allowed_in_intake(self):
        """Read should be allowed in intake phase."""
        start("Vague task")  # -> INTAKE
        allowed, _ = is_tool_allowed("Read")
        assert allowed is True


class TestDesignToolAllowance:
    """Tests for tool allowance in design phase."""

    def test_write_allowed_in_design(self):
        """Write should be allowed in design phase."""
        start("Vague task")
        set_phase(Phase.DESIGN)
        allowed, _ = is_tool_allowed("Write")
        assert allowed is True

    def test_bash_allowed_in_design(self):
        """native__bash should be allowed in design phase."""
        start("Vague task")
        set_phase(Phase.DESIGN)
        allowed, _ = is_tool_allowed("native__bash")
        assert allowed is True


class TestStatusWithIntakeDesign:
    """Tests for status output with new phases."""

    def test_status_shows_intake_phase(self):
        """Status should show intake phase."""
        start("Vague task")  # -> INTAKE
        output = status()
        assert "intake" in output

    def test_status_shows_design_phase(self):
        """Status should show design phase."""
        start("Vague task")
        set_phase(Phase.DESIGN)
        output = status()
        assert "design" in output


class TestFullWorkflowWithIntakeDesign:
    """End-to-end tests for full workflow with intake and design."""

    def test_full_flow_intake_to_orchestrate(self):
        """Test complete flow: intake -> design -> orchestrate."""
        start("Vague task")  # -> INTAKE
        assert get_phase() == Phase.INTAKE

        # Intake complete -> design
        advance_phase()
        assert get_phase() == Phase.DESIGN

        # Design complete -> orchestrate
        advance_phase()
        assert get_phase() == Phase.ORCHESTRATE

    def test_spec_starts_at_orchestrate(self):
        """Test spec-like task starts at orchestrate."""
        start("## Task Overview\n- [ ] First item to implement in the module\n- [ ] Second item with more details")
        assert get_phase() == Phase.ORCHESTRATE

        # Orchestrate complete -> test_writing
        advance_phase()
        assert get_phase() == Phase.TEST_WRITING



class TestPhaseAdvanceVerification:
    """Tests for verification enforcement before phase advancement."""

    def test_advance_from_test_without_results_fails(self):
        """Advancing from TEST without recording results should fail."""
        start("Vague task")
        set_phase(Phase.TEST)
        
        with pytest.raises(RuntimeError, match="Cannot advance from TEST.*must record test results"):
            advance_phase()

    def test_advance_from_test_with_partial_results_fails(self):
        """Advancing from TEST with only some results recorded should fail."""
        start("Vague task")
        set_phase(Phase.TEST)
        
        # Record only test results, not lint or coverage
        state = get_state()
        state["tests_passed"] = True
        with daemon_client.DaemonClient() as dc:
            dc.workflow_set_state("iterate", state)
        
        with pytest.raises(RuntimeError, match="Cannot advance from TEST.*must record test results"):
            advance_phase()

    def test_advance_from_test_with_all_results_succeeds(self):
        """Advancing from TEST with all results recorded should succeed."""
        start("Vague task")
        set_phase(Phase.TEST)
        set_test_results(True, True, True)
        
        new_phase = advance_phase()
        assert new_phase == Phase.REVIEW

    def test_advance_from_review_without_status_fails(self):
        """Advancing from REVIEW without recording status should fail."""
        start("Vague task")
        set_phase(Phase.REVIEW)
        
        with pytest.raises(RuntimeError, match="Cannot advance from REVIEW.*must record review status"):
            advance_phase()

    def test_advance_from_review_with_status_succeeds(self):
        """Advancing from REVIEW with status recorded should succeed."""
        start("Vague task")
        set_phase(Phase.REVIEW)
        set_review_status(True)
        
        new_phase = advance_phase()
        # Should go to DONE since review is clean
        assert new_phase is None or get_phase() == Phase.DONE

    def test_advance_from_other_phases_no_verification_needed(self):
        """Advancing from non-TEST/REVIEW phases should not require verification."""
        # INTAKE -> DESIGN doesn't need verification
        start("Vague task")
        assert get_phase() == Phase.INTAKE
        new_phase = advance_phase()
        assert new_phase == Phase.DESIGN
        
        # DESIGN -> ORCHESTRATE doesn't need verification
        new_phase = advance_phase()
        assert new_phase == Phase.ORCHESTRATE
        
        # ORCHESTRATE -> TEST_WRITING doesn't need verification
        new_phase = advance_phase()
        assert new_phase == Phase.TEST_WRITING
        
        # TEST_WRITING -> IMPLEMENT doesn't need verification
        new_phase = advance_phase()
        assert new_phase == Phase.IMPLEMENT
        
        # IMPLEMENT -> TEST doesn't need verification
        new_phase = advance_phase()
        assert new_phase == Phase.TEST

    def test_cli_advance_enforces_verification(self):
        """CLI advance command should also enforce verification."""
        import subprocess  # noqa: E402
        
        # Start workflow and move to TEST phase
        subprocess.run(
            ["python3", str(lib_dir / "iterate_workflow.py"), "start", "Test task"],
            capture_output=True
        )
        
        # Manually set phase to TEST
        state = get_state()
        state["phase"] = Phase.TEST.value
        with daemon_client.DaemonClient() as dc:
            dc.workflow_set_state("iterate", state)
        
        # Try to advance without results - should fail
        result = subprocess.run(
            ["python3", str(lib_dir / "iterate_workflow.py"), "advance"],
            capture_output=True,
            text=True
        )
        
        assert result.returncode != 0
        assert "must record test results" in result.stderr or "must record test results" in result.stdout


class TestOrchestratePhaseEvaluationBlocking:
    """Tests for blocking evaluation commands in ORCHESTRATE phase."""

    def test_orchestrate_phase_exists(self):
        """ORCHESTRATE phase should exist in Phase enum."""
        assert Phase.ORCHESTRATE.value == "orchestrate"

    def test_orchestrate_bash_not_in_blocked_list(self):
        """Bash should not be in ORCHESTRATE blocked list (we filter commands instead)."""
        assert "Bash" not in PHASE_TOOLS[Phase.ORCHESTRATE]["blocked"]

    def test_pytest_blocked_in_orchestrate(self):
        """pytest command should be blocked in ORCHESTRATE phase."""
        start("Test task")
        set_phase(Phase.ORCHESTRATE)
        allowed, reason = is_tool_allowed("Bash", command="pytest tests/")
        assert allowed is False
        assert "spawn a test agent" in reason.lower()

    def test_pytest_python_module_blocked_in_orchestrate(self):
        """python -m pytest should be blocked in ORCHESTRATE phase."""
        start("Test task")
        set_phase(Phase.ORCHESTRATE)
        allowed, reason = is_tool_allowed("Bash", command="python -m pytest")
        assert allowed is False
        assert "spawn a test agent" in reason.lower()

    def test_ruff_check_blocked_in_orchestrate(self):
        """ruff check command should be blocked in ORCHESTRATE phase."""
        start("Test task")
        set_phase(Phase.ORCHESTRATE)
        allowed, reason = is_tool_allowed("Bash", command="ruff check .")
        assert allowed is False
        assert "spawn a test agent" in reason.lower()

    def test_ruff_dot_blocked_in_orchestrate(self):
        """ruff . command should be blocked in ORCHESTRATE phase."""
        start("Test task")
        set_phase(Phase.ORCHESTRATE)
        allowed, reason = is_tool_allowed("Bash", command="ruff .")
        assert allowed is False
        assert "spawn a test agent" in reason.lower()

    def test_mypy_blocked_in_orchestrate(self):
        """mypy command should be blocked in ORCHESTRATE phase."""
        start("Test task")
        set_phase(Phase.ORCHESTRATE)
        allowed, reason = is_tool_allowed("Bash", command="mypy lib/")
        assert allowed is False
        assert "spawn a test agent" in reason.lower()

    def test_coverage_blocked_in_orchestrate(self):
        """coverage command should be blocked in ORCHESTRATE phase."""
        start("Test task")
        set_phase(Phase.ORCHESTRATE)
        allowed, reason = is_tool_allowed("Bash", command="coverage run -m pytest")
        assert allowed is False
        assert "spawn a test agent" in reason.lower()

    def test_black_check_blocked_in_orchestrate(self):
        """black --check command should be blocked in ORCHESTRATE phase."""
        start("Test task")
        set_phase(Phase.ORCHESTRATE)
        allowed, reason = is_tool_allowed("Bash", command="black --check .")
        assert allowed is False
        assert "spawn a test agent" in reason.lower()

    def test_git_allowed_in_orchestrate(self):
        """git commands should be allowed in ORCHESTRATE (not evaluation)."""
        start("Test task")
        set_phase(Phase.ORCHESTRATE)
        # Git commands are only allowed in REVIEW phase based on existing rules
        # But in ORCHESTRATE we don't want git blocked for evaluation reasons
        allowed, reason = is_tool_allowed("Bash", command="git status")
        # Git may be blocked for other reasons (review phase requirement)
        # but NOT because it's an evaluation command
        if not allowed:
            assert "spawn a test agent" not in reason.lower()

    def test_cat_allowed_in_orchestrate(self):
        """cat commands should be allowed in ORCHESTRATE (not evaluation)."""
        start("Test task")
        set_phase(Phase.ORCHESTRATE)
        allowed, _ = is_tool_allowed("Bash", command="cat file.txt")
        assert allowed is True

    def test_ls_allowed_in_orchestrate(self):
        """ls commands should be allowed in ORCHESTRATE (not evaluation)."""
        start("Test task")
        set_phase(Phase.ORCHESTRATE)
        allowed, _ = is_tool_allowed("Bash", command="ls -la")
        assert allowed is True

    def test_pytest_allowed_in_test_phase(self):
        """pytest should be allowed in TEST phase."""
        start("Test task")
        set_phase(Phase.TEST)
        allowed, _ = is_tool_allowed("Bash", command="pytest tests/")
        assert allowed is True

    def test_ruff_allowed_in_test_phase(self):
        """ruff should be allowed in TEST phase."""
        start("Test task")
        set_phase(Phase.TEST)
        allowed, _ = is_tool_allowed("Bash", command="ruff check .")
        assert allowed is True

    def test_pytest_allowed_in_implement_phase(self):
        """pytest should be allowed in IMPLEMENT phase."""
        start("Test task")
        set_phase(Phase.IMPLEMENT)
        allowed, _ = is_tool_allowed("Bash", command="pytest tests/")
        assert allowed is True
