#!/usr/bin/env python3
"""Tests for implementer-only-enforcement.py hook.

Tests that only agent-swarm:implementer agents can be spawned during
the orchestrate phase of iterate workflow (TDD enforcement).

NOTE: These are integration tests requiring the MCP router to be running.
The hook runs as a subprocess and uses workflow_client to check state via
socket connection to the router.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Skip entire module - requires MCP router running
pytestmark = pytest.mark.skip(
    reason="Integration test: hook subprocess requires MCP router for workflow_client"
)

# Paths
HOOKS_DIR = Path(__file__).parent.parent / "hooks"
IMPLEMENTER_ONLY_HOOK = HOOKS_DIR / "implementer-only-enforcement.py"


@pytest.fixture
def workflow_client_mock(monkeypatch):
    """Mock workflow_client functions for testing."""
    from unittest.mock import Mock
    
    mock_is_active = Mock(return_value=False)
    mock_get_state = Mock(return_value=None)
    
    # Store mocks for access in tests
    mocks = {
        "is_active": mock_is_active,
        "get_state": mock_get_state
    }
    
    # Patch the workflow_client module
    import sys
    lib_path = Path(__file__).parent.parent / "lib"
    sys.path.insert(0, str(lib_path))
    
    from unittest.mock import MagicMock
    workflow_client = MagicMock()
    workflow_client.workflow_is_active = mock_is_active
    workflow_client.workflow_get_state = mock_get_state
    
    monkeypatch.setitem(sys.modules, "workflow_client", workflow_client)
    
    yield mocks


def run_hook(tool_name: str, tool_input: dict = None) -> dict:
    """Run implementer-only-enforcement.py hook with given input."""
    input_data = {"tool_name": tool_name, "tool_input": tool_input or {}}
    result = subprocess.run(
        [sys.executable, str(IMPLEMENTER_ONLY_HOOK)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class TestImplementerOnlyEnforcement:
    """Tests for enforcing implementer-only spawning during iterate/orchestrate."""
    
    def test_blocks_explorer_during_iterate_orchestrate(self, workflow_client_mock):
        """Block explorer spawn when iterate active and phase is orchestrate."""
        workflow_client_mock["is_active"].return_value = True
        workflow_client_mock["get_state"].return_value = {
            "active": True,
            "phase": "orchestrate",
            "mode": "iterate-tdd"
        }
        
        result = run_hook("Task", {
            "description": "Explore codebase",
            "subagent_type": "agent-swarm:explorer"
        })
        
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "implementer" in result["hookSpecificOutput"]["permissionDecisionReason"].lower()
        assert "orchestrate" in result["hookSpecificOutput"]["permissionDecisionReason"].lower()
    
    def test_allows_implementer_during_iterate_orchestrate(self, workflow_client_mock):
        """Allow implementer spawn when iterate active and phase is orchestrate."""
        workflow_client_mock["is_active"].return_value = True
        workflow_client_mock["get_state"].return_value = {
            "active": True,
            "phase": "orchestrate",
            "mode": "iterate-tdd"
        }
        
        result = run_hook("Task", {
            "description": "Implement feature",
            "subagent_type": "agent-swarm:implementer"
        })
        
        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
    
    def test_allows_explorer_when_iterate_not_active(self, workflow_client_mock):
        """Allow explorer spawn when iterate is not active."""
        workflow_client_mock["is_active"].return_value = False
        workflow_client_mock["get_state"].return_value = None
        
        result = run_hook("Task", {
            "description": "Explore codebase",
            "subagent_type": "agent-swarm:explorer"
        })
        
        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
    
    def test_allows_explorer_during_non_orchestrate_phase(self, workflow_client_mock):
        """Allow explorer spawn when phase is not orchestrate."""
        workflow_client_mock["is_active"].return_value = True
        workflow_client_mock["get_state"].return_value = {
            "active": True,
            "phase": "implement",  # Not orchestrate
            "mode": "iterate-tdd"
        }
        
        result = run_hook("Task", {
            "description": "Explore codebase", 
            "subagent_type": "agent-swarm:explorer"
        })
        
        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
    
    def test_allows_non_task_tools(self, workflow_client_mock):
        """Non-Task tools should always be allowed."""
        workflow_client_mock["is_active"].return_value = True
        workflow_client_mock["get_state"].return_value = {
            "active": True,
            "phase": "orchestrate",
            "mode": "iterate-tdd"
        }
        
        # Test various non-Task tools
        for tool in ["Edit", "Write", "Read", "Bash"]:
            result = run_hook(tool)
            assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
    
    def test_blocks_researcher_during_iterate_orchestrate(self, workflow_client_mock):
        """Block researcher spawn when iterate active and phase is orchestrate."""
        workflow_client_mock["is_active"].return_value = True
        workflow_client_mock["get_state"].return_value = {
            "active": True,
            "phase": "orchestrate",
            "mode": "iterate-tdd"
        }
        
        result = run_hook("Task", {
            "description": "Research API",
            "subagent_type": "agent-swarm:researcher"
        })
        
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "implementer" in result["hookSpecificOutput"]["permissionDecisionReason"].lower()


class TestEdgeCases:
    """Edge case tests."""
    
    def test_missing_subagent_type_field(self, workflow_client_mock):
        """Task without subagent_type field should be allowed (fail-open)."""
        workflow_client_mock["is_active"].return_value = True
        workflow_client_mock["get_state"].return_value = {
            "active": True,
            "phase": "orchestrate",
            "mode": "iterate-tdd"
        }
        
        result = run_hook("Task", {
            "description": "Some task"
            # Missing subagent_type
        })
        
        # Fail-open: allow if we can't determine type
        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
    
    def test_invalid_json_input(self):
        """Invalid JSON input allows (fail-open)."""
        result = subprocess.run(
            [sys.executable, str(IMPLEMENTER_ONLY_HOOK)],
            input="not json",
            capture_output=True,
            text=True,
        )
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
    
    def test_workflow_state_unavailable(self, workflow_client_mock):
        """If workflow state is unavailable, fail-open (allow)."""
        workflow_client_mock["is_active"].return_value = True
        workflow_client_mock["get_state"].return_value = None  # State unavailable
        
        result = run_hook("Task", {
            "description": "Explore codebase",
            "subagent_type": "agent-swarm:explorer"
        })
        
        # Fail-open when state unavailable
        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
