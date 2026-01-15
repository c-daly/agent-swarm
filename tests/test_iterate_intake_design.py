#!/usr/bin/env python3
"""Tests for phase selection in iterate_workflow.py.

Phase selection is based on input type:
- Vague task (no structure) -> INTAKE (gather requirements)
- Spec-like task (has structure) -> ORCHESTRATE
- Queue provided -> ORCHESTRATE
- Spec provided -> ORCHESTRATE

Flow after phase selection:
  INTAKE -> DESIGN -> ORCHESTRATE -> TEST_WRITING -> IMPLEMENT -> TEST -> REVIEW -> DONE
"""

import sys
from pathlib import Path

import pytest

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
    is_tool_allowed,
    status,
    LOG_FILE,
    _reset_logger,
    _is_spec,
)
import state_manager  # noqa: E402
from state_manager import ORCHESTRATOR_STATE_FILE as STATE_FILE  # noqa: E402


def get_state():
    """Helper to get orchestrator state for tests."""
    return state_manager.get_state("orchestrator")


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
        """Design phase should allow Bash (for decomposer)."""
        assert "Bash" in PHASE_TOOLS[Phase.DESIGN]["allowed"]


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

    def test_advance_from_orchestrate_to_test_writing(self):
        """Advancing from orchestrate should go to test_writing."""
        start("Vague task")
        set_phase(Phase.ORCHESTRATE)
        new_phase = advance_phase()
        assert new_phase == Phase.TEST_WRITING


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
        """Bash should be allowed in design phase."""
        start("Vague task")
        set_phase(Phase.DESIGN)
        allowed, _ = is_tool_allowed("Bash")
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
