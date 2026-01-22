#!/usr/bin/env python3
"""Tests for workflow state modification enforcement.

Verifies that subagents (identified by agentId) cannot modify workflow state.
Only the orchestrator should be able to control workflow transitions.
"""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch
import pytest
import importlib.util


def load_hook_module(hook_name: str):
    """Load a hook script as a module."""
    hook_path = Path(__file__).parent.parent / "hooks" / f"{hook_name}.py"
    spec = importlib.util.spec_from_file_location(hook_name, hook_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[hook_name] = module
    spec.loader.exec_module(module)
    return module


# Workflow state modification tools that should be blocked for subagents
WORKFLOW_STATE_TOOLS = [
    "workflow__workflow_start",
    "workflow__workflow_stop",
    "workflow__workflow_update",
    "workflow__workflow_set_state",
    "workflow__workflow_set_value",
    # With mcp__router__ prefix
    "mcp__router__workflow__workflow_start",
    "mcp__router__workflow__workflow_stop",
    "mcp__router__workflow__workflow_update",
    "mcp__router__workflow__workflow_set_state",
    "mcp__router__workflow__workflow_set_value",
]


class TestSubagentCannotModifyWorkflowState:
    """Test that subagents cannot call workflow state modification tools."""

    @pytest.mark.parametrize("tool_name", WORKFLOW_STATE_TOOLS)
    def test_subagent_blocked_from_workflow_state_tools(self, tool_name):
        """Subagents (with agentId) should be blocked from modifying workflow state."""
        hook = load_hook_module('workflow-state-enforcement')

        hook_input = {
            "tool_name": tool_name,
            "tool_input": {"workflow_id": "iterate"},
            "agentId": "sub-abc12345",
        }

        with patch('sys.stdin', Mock(read=lambda: json.dumps(hook_input))):
            with patch('builtins.print') as mock_print:
                hook.main()

        output = json.loads(mock_print.call_args[0][0])
        hook_output = output["hookSpecificOutput"]

        assert hook_output["permissionDecision"] == "deny", \
            f"Subagent should be blocked from {tool_name}"
        assert "subagent" in hook_output["permissionDecisionReason"].lower() or \
               "orchestrator" in hook_output["permissionDecisionReason"].lower(), \
            "Reason should explain that only orchestrator can modify workflow state"

    def test_orchestrator_allowed_to_modify_workflow_state(self):
        """Orchestrator (no agentId) should be allowed to modify workflow state."""
        hook = load_hook_module('workflow-state-enforcement')

        hook_input = {
            "tool_name": "workflow__workflow_update",
            "tool_input": {"workflow_id": "iterate", "updates": {"phase": "implement"}},
        }

        with patch('sys.stdin', Mock(read=lambda: json.dumps(hook_input))):
            with patch('builtins.print') as mock_print:
                hook.main()

        output = json.loads(mock_print.call_args[0][0])
        hook_output = output["hookSpecificOutput"]

        assert hook_output["permissionDecision"] == "allow", \
            "Orchestrator should be allowed to modify workflow state"

    def test_non_workflow_tools_allowed_for_subagents(self):
        """Subagents should still be able to use non-workflow tools."""
        hook = load_hook_module('workflow-state-enforcement')

        hook_input = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/some/file.py"},
            "agentId": "sub-abc12345",
        }

        with patch('sys.stdin', Mock(read=lambda: json.dumps(hook_input))):
            with patch('builtins.print') as mock_print:
                hook.main()

        output = json.loads(mock_print.call_args[0][0])
        hook_output = output["hookSpecificOutput"]

        assert hook_output["permissionDecision"] == "allow", \
            "Subagent should be allowed to use non-workflow tools"

    @pytest.mark.parametrize("tool_name", [
        "workflow__workflow_get_state",
        "workflow__workflow_get_value",
        "workflow__workflow_is_active",
        "mcp__router__workflow__workflow_get_state",
    ])
    def test_workflow_read_tools_allowed_for_subagents(self, tool_name):
        """Subagents should be able to READ workflow state (just not modify it)."""
        hook = load_hook_module('workflow-state-enforcement')

        hook_input = {
            "tool_name": tool_name,
            "tool_input": {"workflow_id": "iterate"},
            "agentId": "sub-abc12345",
        }

        with patch('sys.stdin', Mock(read=lambda: json.dumps(hook_input))):
            with patch('builtins.print') as mock_print:
                hook.main()

        output = json.loads(mock_print.call_args[0][0])
        hook_output = output["hookSpecificOutput"]

        assert hook_output["permissionDecision"] == "allow", \
            f"Subagent should be allowed to read workflow state via {tool_name}"


class TestAgentStateModification:
    """Test enforcement for agent state modification."""

    def test_subagent_cannot_modify_other_agent_state(self):
        """Subagents should only be able to modify their own agent state."""
        hook = load_hook_module('workflow-state-enforcement')

        hook_input = {
            "tool_name": "workflow__agent_set_state",
            "tool_input": {
                "agent_id": "other-agent-123",
                "state": {"status": "complete"}
            },
            "agentId": "sub-abc12345",
        }

        with patch('sys.stdin', Mock(read=lambda: json.dumps(hook_input))):
            with patch('builtins.print') as mock_print:
                hook.main()

        output = json.loads(mock_print.call_args[0][0])
        hook_output = output["hookSpecificOutput"]

        assert hook_output["permissionDecision"] == "deny", \
            "Subagent should not be able to modify other agent's state"

    def test_subagent_can_modify_own_state(self):
        """Subagents should be able to modify their own agent state."""
        hook = load_hook_module('workflow-state-enforcement')

        hook_input = {
            "tool_name": "workflow__agent_set_state",
            "tool_input": {
                "agent_id": "sub-abc12345",
                "state": {"status": "complete"}
            },
            "agentId": "sub-abc12345",
        }

        with patch('sys.stdin', Mock(read=lambda: json.dumps(hook_input))):
            with patch('builtins.print') as mock_print:
                hook.main()

        output = json.loads(mock_print.call_args[0][0])
        hook_output = output["hookSpecificOutput"]

        assert hook_output["permissionDecision"] == "allow", \
            "Subagent should be allowed to modify its own state"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
