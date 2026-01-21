#!/usr/bin/env python3
"""Tests for parallel-enforcement.py hook."""

import importlib.util
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Add hooks directory to path
hooks_dir = Path(__file__).parent.parent / "hooks"
sys.path.insert(0, str(hooks_dir))

# Import module with hyphen using importlib and register it
spec = importlib.util.spec_from_file_location(
    "parallel_enforcement",
    hooks_dir / "parallel-enforcement.py"
)
parallel_enforcement = importlib.util.module_from_spec(spec)
sys.modules["parallel_enforcement"] = parallel_enforcement  # Register in sys.modules for patching
spec.loader.exec_module(parallel_enforcement)


@pytest.fixture
def mock_workflow_state():
    """Mock workflow state for testing."""
    with patch("parallel_enforcement.workflow_get_state") as mock_get, \
         patch("parallel_enforcement.workflow_update") as mock_update:
        
        state = {"parallel_enforcement_state": {
            "recent_spawns": [],
            "last_output_time": 0
        }}
        
        mock_get.return_value = state
        mock_update.return_value = {}
        
        yield mock_get, mock_update, state


def run_hook(tool_name="Task", tool_input=None):
    """Helper to run the hook with given input."""
    if tool_input is None:
        tool_input = {"description": "test task"}
    
    input_data = {
        "tool_name": tool_name,
        "tool_input": tool_input
    }
    
    with patch("sys.stdin.read", return_value=json.dumps(input_data)):
        # Capture print output
        output = []
        def capture_print(text):
            output.append(text)
        
        with patch("builtins.print", side_effect=capture_print):
            parallel_enforcement.main()
        
        if output:
            return json.loads(output[0])
    
    return None


def test_non_task_tool_allowed(mock_workflow_state):
    """Non-Task tools should always be allowed without checking."""
    result = run_hook(tool_name="Read")
    
    assert result is not None
    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_single_task_spawn_allowed(mock_workflow_state):
    """Single Task spawn should be allowed without warning."""
    mock_get, mock_update, state = mock_workflow_state
    
    result = run_hook(tool_name="Task", tool_input={"description": "First task"})
    
    assert result is not None
    output = result["hookSpecificOutput"]
    assert output["permissionDecision"] == "allow"
    assert "additionalContext" not in output or output.get("additionalContext") is None


def test_rapid_sequential_spawns_trigger_warning(mock_workflow_state):
    """Two Task spawns within 5 seconds should trigger warning on second."""
    mock_get, mock_update, state = mock_workflow_state
    current_time = time.time()
    
    # First spawn
    state["parallel_enforcement_state"]["recent_spawns"] = []
    result1 = run_hook(tool_name="Task", tool_input={"description": "Task 1"})
    assert result1["hookSpecificOutput"]["permissionDecision"] == "allow"
    
    # Simulate first spawn recorded
    state["parallel_enforcement_state"]["recent_spawns"] = [
        {"timestamp": current_time, "task_desc": "Task 1"}
    ]
    
    # Second spawn within 5 seconds - should warn
    result2 = run_hook(tool_name="Task", tool_input={"description": "Task 2"})
    
    assert result2 is not None
    output = result2["hookSpecificOutput"]
    assert output["permissionDecision"] == "allow"
    assert "additionalContext" in output
    assert "PARALLEL SPAWNING RECOMMENDED" in output["additionalContext"]
    assert "sequential" in output["additionalContext"].lower()


def test_third_sequential_spawn_blocked(mock_workflow_state):
    """Third Task spawn within 5 seconds should be blocked."""
    mock_get, mock_update, state = mock_workflow_state
    current_time = time.time()
    
    # Simulate two recent spawns
    state["parallel_enforcement_state"]["recent_spawns"] = [
        {"timestamp": current_time - 2, "task_desc": "Task 1"},
        {"timestamp": current_time - 1, "task_desc": "Task 2"}
    ]
    
    # Third spawn - should block
    result = run_hook(tool_name="Task", tool_input={"description": "Task 3"})
    
    assert result is not None
    output = result["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert "permissionDecisionReason" in output
    assert "PARALLEL_ENFORCEMENT" in output["permissionDecisionReason"]
    assert "parallel" in output["permissionDecisionReason"].lower()


def test_spawns_outside_window_dont_trigger(mock_workflow_state):
    """Spawns more than 5 seconds apart should not trigger warning."""
    mock_get, mock_update, state = mock_workflow_state
    current_time = time.time()
    
    # Simulate old spawn (>5 seconds ago)
    state["parallel_enforcement_state"]["recent_spawns"] = [
        {"timestamp": current_time - 10, "task_desc": "Old task"}
    ]
    
    # New spawn - should be treated as first (old one cleaned)
    result = run_hook(tool_name="Task", tool_input={"description": "New task"})
    
    assert result is not None
    output = result["hookSpecificOutput"]
    assert output["permissionDecision"] == "allow"
    assert "additionalContext" not in output or output.get("additionalContext") is None


def test_clean_old_spawns():
    """Test that old spawns are properly cleaned from state."""
    current_time = time.time()
    spawns = [
        {"timestamp": current_time - 10, "task_desc": "Old 1"},
        {"timestamp": current_time - 2, "task_desc": "Recent 1"},
        {"timestamp": current_time - 1, "task_desc": "Recent 2"},
        {"timestamp": current_time - 7, "task_desc": "Old 2"}
    ]
    
    cleaned = parallel_enforcement.clean_old_spawns(spawns, current_time, window=5.0)
    
    assert len(cleaned) == 2
    assert all(s["task_desc"].startswith("Recent") for s in cleaned)


def test_warning_message_mentions_parallel():
    """Verify warning message is clear about parallel spawning."""
    state = {
        "parallel_enforcement_state": {
            "recent_spawns": [
                {"timestamp": time.time(), "task_desc": "Task 1"}
            ]
        }
    }
    
    with patch("parallel_enforcement.workflow_get_state", return_value=state):
        with patch("parallel_enforcement.workflow_update"):
            result = run_hook(tool_name="Task", tool_input={"description": "Task 2"})
    
    assert result is not None
    output = result["hookSpecificOutput"]
    
    # Check warning contains helpful guidance
    if "additionalContext" in output:
        context = output["additionalContext"]
        assert "parallel" in context.lower() or "PARALLEL" in context
        assert "sequential" in context.lower() or "SEQUENTIAL" in context
        # Should show example code
        assert "Task" in context


def test_state_update_called(mock_workflow_state):
    """Verify that state is updated after each spawn."""
    mock_get, mock_update, state = mock_workflow_state
    
    run_hook(tool_name="Task", tool_input={"description": "Test task"})
    
    # Should have called update with new state
    assert mock_update.called
    call_args = mock_update.call_args
    assert call_args[0][0] == "session"  # First arg is workflow_id
    assert "parallel_enforcement_state" in call_args[0][1]  # Second arg contains state


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
