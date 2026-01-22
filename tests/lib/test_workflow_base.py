# tests/lib/test_workflow_base.py
"""Tests for workflow base classes."""

import sys
from pathlib import Path

import pytest

# Ensure lib is in path
lib_dir = Path(__file__).parent.parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

from workflow_base import (
    WorkflowPhase, PhaseTransition, WorkflowDefinition,
    TransitionResult, KickbackReason, WorkflowEngine
)


def test_phase_definition():
    """Phase should define allowed/blocked tools."""
    phase = WorkflowPhase(
        name="investigate",
        allowed_tools=frozenset({"Read", "Glob", "Grep"}),
        blocked_tools=frozenset({"Edit", "Write"}),
        required_outputs=["hypothesis", "prediction"],
        adversary_gate=True,
    )
    assert phase.name == "investigate"
    assert "Read" in phase.allowed_tools
    assert "Edit" in phase.blocked_tools
    assert phase.adversary_gate is True


def test_workflow_definition():
    """Workflow should define phases and transitions."""
    phases = {
        "start": WorkflowPhase(name="start", allowed_tools=frozenset({"Read"})),
        "end": WorkflowPhase(name="end", allowed_tools=frozenset({"Read"})),
    }
    transitions = {
        "start": PhaseTransition(
            from_phase="start",
            to_phase="end",
            condition=lambda state: state.get("ready", False),
        ),
    }
    workflow = WorkflowDefinition(
        name="test_workflow",
        phases=phases,
        transitions=transitions,
        initial_phase="start",
    )
    assert workflow.name == "test_workflow"
    assert workflow.initial_phase == "start"


def test_transition_with_kickback():
    """Transitions should support kickback logic."""
    def check_result(state):
        if not state.get("tests_pass"):
            return TransitionResult(
                success=False,
                kickback_to="fix",
                reason=KickbackReason.TESTS_FAILED
            )
        return TransitionResult(success=True, next_phase="done")

    state = {"tests_pass": False}
    result = check_result(state)
    assert result.success is False
    assert result.kickback_to == "fix"


def test_workflow_engine_start():
    """Engine should start workflow in initial phase."""
    phases = {
        "triage": WorkflowPhase(name="triage", allowed_tools=frozenset({"Read"})),
        "done": WorkflowPhase(name="done", allowed_tools=frozenset()),
    }
    definition = WorkflowDefinition(
        name="test",
        phases=phases,
        transitions={},
        initial_phase="triage",
    )

    engine = WorkflowEngine(definition)
    state = engine.start(task="Fix the bug")

    assert state["active"] is True
    assert state["phase"] == "triage"
    assert state["task"] == "Fix the bug"
    assert state["iteration"] == 0


def test_workflow_engine_is_tool_allowed():
    """Engine should enforce tool restrictions."""
    phases = {
        "investigate": WorkflowPhase(
            name="investigate",
            allowed_tools=frozenset({"Read", "Glob"}),
            blocked_tools=frozenset({"Edit", "Write"}),
        ),
    }
    definition = WorkflowDefinition(
        name="test",
        phases=phases,
        transitions={},
        initial_phase="investigate",
    )

    engine = WorkflowEngine(definition)
    engine.start(task="Test")

    allowed, reason = engine.is_tool_allowed("Read")
    assert allowed is True

    allowed, reason = engine.is_tool_allowed("Edit")
    assert allowed is False
    assert "blocked" in reason.lower()


def test_workflow_engine_advance_phase():
    """Engine should advance through phases."""
    phases = {
        "start": WorkflowPhase(name="start"),
        "middle": WorkflowPhase(name="middle"),
        "end": WorkflowPhase(name="end"),
    }
    transitions = {
        "start": PhaseTransition(
            from_phase="start",
            to_phase="middle",
            condition=lambda s: TransitionResult(success=True, next_phase="middle"),
        ),
        "middle": PhaseTransition(
            from_phase="middle",
            to_phase="end",
            condition=lambda s: TransitionResult(success=True, next_phase="end"),
        ),
    }
    definition = WorkflowDefinition(
        name="test",
        phases=phases,
        transitions=transitions,
        initial_phase="start",
    )

    engine = WorkflowEngine(definition)
    engine.start(task="Test")

    result = engine.advance()
    assert result.success is True
    assert engine.get_phase() == "middle"


def test_file_pattern_restriction():
    """Engine should restrict edits to allowed file patterns."""
    phases = {
        "reproduce": WorkflowPhase(
            name="reproduce",
            allowed_tools=frozenset({"Edit", "Write"}),
            allowed_file_patterns=frozenset({
                "tests/**",
                "*_test.py",
                "test_*.py",
                "conftest.py",
            }),
        ),
    }
    definition = WorkflowDefinition(
        name="test",
        phases=phases,
        transitions={},
        initial_phase="reproduce",
    )

    engine = WorkflowEngine(definition)
    engine.start(task="Test")

    # Test files should be allowed
    allowed, reason = engine.is_tool_allowed("Edit", file_path="tests/test_foo.py")
    assert allowed is True

    allowed, reason = engine.is_tool_allowed("Edit", file_path="test_bar.py")
    assert allowed is True

    # Non-test files should be blocked
    allowed, reason = engine.is_tool_allowed("Edit", file_path="src/main.py")
    assert allowed is False
    assert "pattern" in reason.lower()


def test_parallel_adversary_check():
    """Adversary checks should support parallel execution."""
    phases = {
        "implement": WorkflowPhase(
            name="implement",
            adversary_gate=True,
            adversary_parallel=True,
        ),
    }
    definition = WorkflowDefinition(
        name="test",
        phases=phases,
        transitions={},
        initial_phase="implement",
    )

    engine = WorkflowEngine(definition)
    engine.start(task="Test")

    # Should return adversary check task ID for parallel execution
    task_id = engine.start_adversary_check()
    assert task_id is not None

    # Can poll for result
    result = engine.get_adversary_result(task_id, block=False)
    # Result may be None if still running (or pending dict if blocking)
