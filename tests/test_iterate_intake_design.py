#!/usr/bin/env python3
"""Tests for intake and design phases in iterate_workflow.py.

These phases are optional and come before the TDD loop:
  [intake] -> [design] -> test_writing -> implement -> test -> review -> done

Intake: Gather requirements from user (no editing)
Design: Write spec and decompose into task_queue
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
    get_state,
    get_phase,
    advance_phase,
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


class TestStartWithIntake:
    """Tests for starting workflow with intake phase."""

    def test_start_with_intake_true(self):
        """Start with needs_intake=True should begin in intake phase."""
        start("Explore and implement feature X", needs_intake=True)
        assert get_phase() == Phase.INTAKE

    def test_start_with_intake_false(self):
        """Start with needs_intake=False should begin in test_writing phase."""
        start("Clear task", needs_intake=False)
        assert get_phase() == Phase.TEST_WRITING

    def test_start_default_is_test_writing(self):
        """Default start (no needs_intake) should begin in test_writing."""
        start("My task")
        assert get_phase() == Phase.TEST_WRITING

    def test_start_with_needs_design_only(self):
        """Start with needs_design=True (no intake) should begin in design phase."""
        start("Feature with clear reqs", needs_intake=False, needs_design=True)
        assert get_phase() == Phase.DESIGN

    def test_start_with_both_intake_and_design(self):
        """Start with both intake and design should begin in intake."""
        start("Complex feature", needs_intake=True, needs_design=True)
        assert get_phase() == Phase.INTAKE

    def test_state_stores_needs_design_flag(self):
        """State should store needs_design flag for later phase transitions."""
        start("Task", needs_intake=True, needs_design=True)
        state = get_state()
        assert state.get("needs_design") is True


class TestIntakePhaseAdvancement:
    """Tests for advancing from intake phase."""

    def test_advance_from_intake_to_design(self):
        """Advancing from intake should go to design when needs_design=True."""
        start("Task", needs_intake=True, needs_design=True)
        new_phase = advance_phase()
        assert new_phase == Phase.DESIGN

    def test_advance_from_intake_to_test_writing(self):
        """Advancing from intake should go to test_writing when needs_design=False."""
        start("Task", needs_intake=True, needs_design=False)
        new_phase = advance_phase()
        assert new_phase == Phase.TEST_WRITING

    def test_advance_from_intake_default_to_test_writing(self):
        """Advancing from intake with default should go to test_writing."""
        start("Task", needs_intake=True)  # needs_design defaults to False
        new_phase = advance_phase()
        assert new_phase == Phase.TEST_WRITING


class TestDesignPhaseAdvancement:
    """Tests for advancing from design phase."""

    def test_advance_from_design_to_test_writing(self):
        """Advancing from design should always go to test_writing."""
        start("Task", needs_intake=False, needs_design=True)
        assert get_phase() == Phase.DESIGN
        new_phase = advance_phase()
        assert new_phase == Phase.TEST_WRITING


class TestIntakeToolBlocking:
    """Tests for tool blocking in intake phase."""

    def test_edit_blocked_in_intake(self):
        """Edit should be blocked in intake phase."""
        start("Task", needs_intake=True)
        allowed, reason = is_tool_allowed("Edit")
        assert allowed is False
        assert "BLOCKED" in reason

    def test_write_blocked_in_intake(self):
        """Write should be blocked in intake phase."""
        start("Task", needs_intake=True)
        allowed, reason = is_tool_allowed("Write")
        assert allowed is False
        assert "BLOCKED" in reason

    def test_read_allowed_in_intake(self):
        """Read should be allowed in intake phase."""
        start("Task", needs_intake=True)
        allowed, _ = is_tool_allowed("Read")
        assert allowed is True


class TestDesignToolAllowance:
    """Tests for tool allowance in design phase."""

    def test_write_allowed_in_design(self):
        """Write should be allowed in design phase."""
        start("Task", needs_intake=False, needs_design=True)
        allowed, _ = is_tool_allowed("Write")
        assert allowed is True

    def test_bash_allowed_in_design(self):
        """Bash should be allowed in design phase."""
        start("Task", needs_intake=False, needs_design=True)
        allowed, _ = is_tool_allowed("Bash")
        assert allowed is True


class TestStatusWithIntakeDesign:
    """Tests for status output with new phases."""

    def test_status_shows_intake_phase(self):
        """Status should show intake phase."""
        start("My task", needs_intake=True)
        output = status()
        assert "intake" in output

    def test_status_shows_design_phase(self):
        """Status should show design phase."""
        start("My task", needs_intake=False, needs_design=True)
        output = status()
        assert "design" in output


class TestFullWorkflowWithIntakeDesign:
    """End-to-end tests for full workflow with intake and design."""

    def test_full_flow_intake_design_to_done(self):
        """Test complete flow: intake -> design -> test_writing -> ... -> done."""
        start("Complex feature", needs_intake=True, needs_design=True)
        assert get_phase() == Phase.INTAKE

        # Intake complete -> design
        advance_phase()
        assert get_phase() == Phase.DESIGN

        # Design complete -> test_writing
        advance_phase()
        assert get_phase() == Phase.TEST_WRITING

        # From here it's the standard TDD flow
        advance_phase()  # -> implement
        assert get_phase() == Phase.IMPLEMENT

    def test_flow_design_only(self):
        """Test flow with just design phase (no intake)."""
        start("Feature with reqs", needs_intake=False, needs_design=True)
        assert get_phase() == Phase.DESIGN

        advance_phase()  # -> test_writing
        assert get_phase() == Phase.TEST_WRITING

    def test_flow_intake_only(self):
        """Test flow with just intake phase (no design)."""
        start("Feature needing discovery", needs_intake=True, needs_design=False)
        assert get_phase() == Phase.INTAKE

        advance_phase()  # -> test_writing (skips design)
        assert get_phase() == Phase.TEST_WRITING
