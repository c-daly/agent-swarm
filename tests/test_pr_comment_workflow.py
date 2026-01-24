# tests/lib/test_pr_comment_workflow.py
"""Tests for PR comment workflow using base classes."""

import sys
from pathlib import Path

import pytest

# Ensure lib is in path
lib_dir = Path(__file__).parent.parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from pr_comment_workflow import PRCommentWorkflow


def test_pr_comment_workflow_phases():
    """PR comment workflow should have required phases."""
    wf = PRCommentWorkflow()

    expected = ["understand", "fix", "verify", "push", "check_reviews", "done"]
    for phase in expected:
        assert wf.engine.definition.get_phase(phase) is not None


def test_understand_blocks_editing():
    """UNDERSTAND phase should block all editing."""
    wf = PRCommentWorkflow()
    wf.start(comment="Please rename this variable", pr_number=123)

    assert wf.get_phase() == "understand"

    allowed, _ = wf.is_tool_allowed("Read")
    assert allowed is True

    allowed, _ = wf.is_tool_allowed("Edit")
    assert allowed is False


def test_understand_has_adversary_gate():
    """UNDERSTAND should have adversary gate."""
    wf = PRCommentWorkflow()
    wf.start(comment="Test", pr_number=123)

    phase = wf.engine.definition.get_phase("understand")
    assert phase.adversary_gate is True


def test_fix_allows_editing():
    """FIX phase should allow editing."""
    wf = PRCommentWorkflow()
    wf.start(comment="Test", pr_number=123)
    wf.set_phase("fix")

    allowed, _ = wf.is_tool_allowed("Edit")
    assert allowed is True

    allowed, _ = wf.is_tool_allowed("Write")
    assert allowed is True


def test_verify_blocks_editing():
    """VERIFY phase should block editing."""
    wf = PRCommentWorkflow()
    wf.start(comment="Test", pr_number=123)
    wf.set_phase("verify")

    allowed, _ = wf.is_tool_allowed("Edit")
    assert allowed is False

    allowed, _ = wf.is_tool_allowed("Bash")
    assert allowed is True


def test_max_iterations_lower():
    """PR comment workflow should have fewer max iterations."""
    wf = PRCommentWorkflow()
    assert wf.engine.definition.max_iterations == 3
