#!/usr/bin/env python3
"""Tests for base-enforcement.py hook.

Tests that Edit/Write/NotebookEdit are blocked when no workflow is active,
and allowed when any workflow is active.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Paths
HOOKS_DIR = Path(__file__).parent.parent / "hooks"
BASE_ENFORCEMENT = HOOKS_DIR / "base-enforcement.py"
ITERATE_STATE = Path.home() / ".claude" / "state" / "iterate_state.json"
ORCHESTRATE_STATE = Path.home() / ".claude" / "state" / "orchestrate_state.json"


@pytest.fixture(autouse=True)
def clean_state():
    """Clean workflow state before and after each test."""
    for state_file in [ITERATE_STATE, ORCHESTRATE_STATE]:
        if state_file.exists():
            state_file.unlink()
    yield
    for state_file in [ITERATE_STATE, ORCHESTRATE_STATE]:
        if state_file.exists():
            state_file.unlink()


def run_hook(tool_name: str, tool_input: dict = None) -> dict:
    """Run base-enforcement.py hook with given input."""
    input_data = {"tool_name": tool_name, "tool_input": tool_input or {}}
    result = subprocess.run(
        [sys.executable, str(BASE_ENFORCEMENT)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def set_iterate_active(active: bool = True):
    """Set iterate workflow state."""
    ITERATE_STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(ITERATE_STATE, "w") as f:
        json.dump({"active": active}, f)


def set_orchestrate_active(active: bool = True):
    """Set orchestrate workflow state."""
    ORCHESTRATE_STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(ORCHESTRATE_STATE, "w") as f:
        json.dump({"active": active}, f)


class TestNoWorkflowBlocking:
    """Tests for blocking editing tools when no workflow is active."""

    @pytest.mark.parametrize("tool", ["Edit", "Write", "NotebookEdit"])
    def test_editing_tools_blocked(self, tool):
        """Editing tools blocked when no workflow active."""
        result = run_hook(tool)
        assert result["hookSpecificOutput"]["permissionDecision"] == "block"
        assert "NO WORKFLOW" in result["hookSpecificOutput"]["permissionDecisionReason"]

    @pytest.mark.parametrize("tool", ["Read", "Glob", "Grep", "Bash", "Task"])
    def test_readonly_tools_allowed(self, tool):
        """Read-only tools allowed without workflow."""
        result = run_hook(tool)
        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"


class TestWorkflowActive:
    """Tests for allowing editing when workflow is active."""

    @pytest.mark.parametrize("tool", ["Edit", "Write", "NotebookEdit"])
    def test_editing_allowed_with_iterate(self, tool):
        """Editing tools allowed when /iterate is active."""
        set_iterate_active(True)
        result = run_hook(tool)
        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"

    @pytest.mark.parametrize("tool", ["Edit", "Write", "NotebookEdit"])
    def test_editing_allowed_with_orchestrate(self, tool):
        """Editing tools allowed when /orchestrate is active."""
        set_orchestrate_active(True)
        result = run_hook(tool)
        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_inactive_workflow_still_blocks(self):
        """Workflow file exists but active=false still blocks."""
        set_iterate_active(False)
        result = run_hook("Edit")
        assert result["hookSpecificOutput"]["permissionDecision"] == "block"


class TestEdgeCases:
    """Edge case tests."""

    def test_invalid_json_input(self):
        """Invalid JSON input allows (fail-open)."""
        result = subprocess.run(
            [sys.executable, str(BASE_ENFORCEMENT)],
            input="not json",
            capture_output=True,
            text=True,
        )
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_corrupted_state_file(self):
        """Corrupted state file treated as inactive."""
        ITERATE_STATE.parent.mkdir(parents=True, exist_ok=True)
        with open(ITERATE_STATE, "w") as f:
            f.write("not json")
        result = run_hook("Edit")
        assert result["hookSpecificOutput"]["permissionDecision"] == "block"
