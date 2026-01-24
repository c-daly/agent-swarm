# tests/lib/test_debug_workflow.py
"""Tests for debug workflow using base classes."""

import sys
from pathlib import Path

import pytest

# Ensure lib is in path
lib_dir = Path(__file__).parent.parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from debug_workflow import DebugWorkflow, DebugPhase


def test_debug_workflow_phases():
    """Debug workflow should have all required phases."""
    wf = DebugWorkflow()

    expected_phases = [
        "triage", "reproduce", "hypothesize", "prove",
        "fix", "verify", "push", "check_status", "done"
    ]

    for phase in expected_phases:
        assert wf.engine.definition.get_phase(phase) is not None


def test_debug_workflow_triage_restrictions():
    """TRIAGE phase should block editing."""
    wf = DebugWorkflow()
    wf.start(bug_report="Test failure in auth module")

    assert wf.get_phase() == "triage"

    allowed, reason = wf.is_tool_allowed("Read")
    assert allowed is True

    allowed, reason = wf.is_tool_allowed("Edit")
    assert allowed is False


def test_debug_workflow_reproduce_test_only():
    """REPRODUCE should only allow editing test files."""
    wf = DebugWorkflow()
    wf.start(bug_report="Test")
    wf.set_phase("reproduce")

    # Test file allowed
    allowed, _ = wf.is_tool_allowed("Edit", file_path="tests/test_auth.py")
    assert allowed is True

    # Non-test file blocked
    allowed, _ = wf.is_tool_allowed("Edit", file_path="src/auth.py")
    assert allowed is False


def test_debug_workflow_hypothesize_gate():
    """HYPOTHESIZE should have adversary gate."""
    wf = DebugWorkflow()
    wf.start(bug_report="Test")
    wf.set_phase("hypothesize")

    phase = wf.engine.definition.get_phase("hypothesize")
    assert phase.adversary_gate is True


def test_debug_workflow_prove_gate():
    """PROVE should have adversary gate."""
    wf = DebugWorkflow()
    wf.start(bug_report="Test")

    phase = wf.engine.definition.get_phase("prove")
    assert phase.adversary_gate is True
    assert "Edit" in phase.blocked_tools


def test_debug_workflow_fix_allows_editing():
    """FIX phase should allow editing source files."""
    wf = DebugWorkflow()
    wf.start(bug_report="Test")
    wf.set_phase("fix")

    allowed, _ = wf.is_tool_allowed("Edit", file_path="src/main.py")
    assert allowed is True

    allowed, _ = wf.is_tool_allowed("Write", file_path="lib/new_file.py")
    assert allowed is True
