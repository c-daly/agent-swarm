#!/usr/bin/env python3
"""Tests for non-blocking TaskOutput enforcement hook."""

import json
import subprocess
from pathlib import Path


def run_hook(tool_name: str, tool_input: dict) -> dict:
    """Run the nonblocking enforcement hook with given inputs."""
    hook_path = Path(__file__).parent.parent / "hooks" / "nonblocking-enforcement.py"
    
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


def test_taskoutput_with_block_true_is_blocked():
    """TaskOutput with block=true should be blocked."""
    output = run_hook("TaskOutput", {"agent_id": "test-agent", "block": True})
    
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "block=false" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_taskoutput_with_block_false_is_allowed():
    """TaskOutput with block=false should be allowed."""
    output = run_hook("TaskOutput", {"agent_id": "test-agent", "block": False})
    
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_taskoutput_without_block_is_blocked():
    """TaskOutput without block parameter (defaults to true) should be blocked."""
    output = run_hook("TaskOutput", {"agent_id": "test-agent"})
    
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "block=false" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_non_taskoutput_tools_not_affected():
    """Non-TaskOutput tools should not be affected by this hook."""
    output = run_hook("Read", {"file_path": "test.txt"})
    
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_other_tool_without_block():
    """Other tools without block parameter should work normally."""
    output = run_hook("Task", {"description": "test task"})
    
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
