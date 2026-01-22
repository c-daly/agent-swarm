"""Tests for implementer workflow."""
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))

from implementer_workflow import IMPLEMENTER_DEFINITION  # noqa: E402


def test_implementer_definition():
    """Implementer workflow should have minimal phases."""
    assert IMPLEMENTER_DEFINITION.name == "implementer"
    assert IMPLEMENTER_DEFINITION.initial_phase == "work"
    assert len(IMPLEMENTER_DEFINITION.phases) == 3
    assert "work" in IMPLEMENTER_DEFINITION.phases
    assert "verify" in IMPLEMENTER_DEFINITION.phases
    assert "done" in IMPLEMENTER_DEFINITION.phases


def test_work_phase_is_permissive():
    """Work phase should allow all common tools."""
    work_phase = IMPLEMENTER_DEFINITION.phases["work"]
    assert "Edit" in work_phase.allowed_tools
    assert "Write" in work_phase.allowed_tools
    assert "Bash" in work_phase.allowed_tools
    assert "Read" in work_phase.allowed_tools
    assert len(work_phase.blocked_tools) == 0


def test_verify_phase_allows_edits():
    """Verify phase should still allow edits (to fix issues)."""
    verify_phase = IMPLEMENTER_DEFINITION.phases["verify"]
    assert "Edit" in verify_phase.allowed_tools
    assert "Write" in verify_phase.allowed_tools
    assert len(verify_phase.blocked_tools) == 0


def test_workflow_transitions():
    """Should be able to transition work → verify → done."""
    assert "work" in IMPLEMENTER_DEFINITION.transitions
    assert "verify" in IMPLEMENTER_DEFINITION.transitions

    work_transition = IMPLEMENTER_DEFINITION.transitions["work"]
    assert work_transition.to_phase == "verify"

    verify_transition = IMPLEMENTER_DEFINITION.transitions["verify"]
    assert verify_transition.to_phase == "done"


def test_max_iterations():
    """Should have low max iterations (simple workflow)."""
    assert IMPLEMENTER_DEFINITION.max_iterations == 3
