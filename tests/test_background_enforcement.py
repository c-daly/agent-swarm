#!/usr/bin/env python3
"""Tests for background enforcement hook."""

import json
import subprocess
from pathlib import Path


def run_hook(tool_name: str, tool_input: dict) -> dict:
    """Run the background enforcement hook with given inputs."""
    hook_path = Path(__file__).parent.parent / "hooks" / "background-enforcement.py"
    
    input_data = {
        "tool_name": tool_name,
        "tool_input": tool_input
    }
    
    result = subprocess.run(
        ["python3", str(hook_path)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        check=True
    )
    
    return json.loads(result.stdout)


def test_task_without_run_in_background_is_blocked():
    """Task tool without run_in_background parameter should be blocked."""
    output = run_hook("Task", {"task": "some task"})
    
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "run_in_background=true" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_task_with_run_in_background_true_is_allowed():
    """Task tool with run_in_background=true should be allowed."""
    output = run_hook("Task", {"task": "some task", "run_in_background": True})
    
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_task_with_run_in_background_false_is_blocked():
    """Task tool with run_in_background=false should be blocked."""
    output = run_hook("Task", {"task": "some task", "run_in_background": False})
    
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "run_in_background=true" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_non_task_tools_not_affected():
    """Non-Task tools should not be affected by this hook."""
    output = run_hook("Read", {"file_path": "test.txt"})
    
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_other_tool_without_run_in_background():
    """Other tools without run_in_background should work normally."""
    output = run_hook("Bash", {"command": "echo test"})
    
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
