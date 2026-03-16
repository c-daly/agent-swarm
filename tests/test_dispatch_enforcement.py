"""Tests for agent dispatch enforcement — prepare_dispatch and briefing retrieval."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


@pytest.fixture
def controller():
    """Create a Controller with mocked dependencies."""
    from controller import Controller

    with patch.object(Controller, '__init__', lambda self: None):
        ctrl = Controller.__new__(Controller)
        ctrl.permissions = MagicMock()
        ctrl.permissions.register_agent.return_value = MagicMock(
            agent_id="sub-abc123",
            agent_type="implementer",
            roles=["editor", "shell_safe"],
        )
        ctrl._agent_state = {}
        ctrl._state_lock = __import__("threading").RLock()
        yield ctrl


class TestPrepareDispatch:
    def test_returns_agent_id(self, controller):
        result = controller._prepare_dispatch({
            "agent_type": "implementer",
            "description": "test task",
        })
        assert result["success"] is True
        assert result["agent_id"].startswith("sub-")

    def test_returns_briefing(self, controller):
        with patch("controller.assemble_subagent_briefing", return_value="BRIEFING"):
            result = controller._prepare_dispatch({"agent_type": "implementer"})
            assert "BRIEFING" in result["briefing"]

    def test_briefing_includes_identity_header(self, controller):
        with patch("controller.assemble_subagent_briefing", return_value="BRIEFING"):
            result = controller._prepare_dispatch({"agent_type": "implementer"})
            assert f"Agent ID: `{result['agent_id']}`" in result["briefing"]
            assert "mcp-call" in result["briefing"]

    def test_returns_role(self, controller):
        with patch("controller.assemble_subagent_briefing", return_value=""):
            result = controller._prepare_dispatch({"agent_type": "implementer"})
            assert result["agent_type"] == "implementer"

    def test_registers_in_permissions(self, controller):
        controller._prepare_dispatch({"agent_type": "implementer"})
        controller.permissions.register_agent.assert_called_once()

    def test_records_agent_state(self, controller):
        result = controller._prepare_dispatch({
            "agent_type": "implementer",
            "description": "test task",
        })
        agent_id = result["agent_id"]
        assert agent_id in controller._agent_state
        assert controller._agent_state[agent_id]["status"] == "pending"
        assert controller._agent_state[agent_id]["description"] == "test task"

    def test_missing_agent_type_raises(self, controller):
        from lib.errors import RouterError
        with pytest.raises(RouterError):
            controller._prepare_dispatch({"prompt": "do something"})

    def test_extracts_role_from_namespaced_type(self, controller):
        with patch("controller.assemble_subagent_briefing") as mock_brief:
            mock_brief.return_value = ""
            controller._prepare_dispatch({"agent_type": "agent-swarm:implementer"})
            mock_brief.assert_called_once()
            assert mock_brief.call_args[0][0] == "implementer"

    def test_subagent_type_alias(self, controller):
        """Should accept subagent_type as alias for agent_type."""
        result = controller._prepare_dispatch({"subagent_type": "explorer"})
        assert result["success"] is True

    def test_wf_override_only_when_no_active_workflow(self, controller):
        """iterate override should not apply when a workflow is already active."""
        with patch("controller.assemble_subagent_briefing") as mock_brief, \
             patch("controller.get_workflow_state", return_value=("experiment", "work")):
            mock_brief.return_value = ""
            controller._prepare_dispatch({"agent_type": "implementer"})
            _, kwargs = mock_brief.call_args
            assert kwargs.get("workflow_override") is None

    def test_wf_override_defaults_to_iterate(self, controller):
        """iterate override should apply for implementers when no workflow active."""
        with patch("controller.assemble_subagent_briefing") as mock_brief, \
             patch("controller.get_workflow_state", return_value=(None, None)):
            mock_brief.return_value = ""
            controller._prepare_dispatch({"agent_type": "implementer"})
            _, kwargs = mock_brief.call_args
            assert kwargs.get("workflow_override") == "iterate"


class TestGetAgentBriefing:
    def test_returns_main_agent_briefing(self, controller):
        with patch("controller.assemble_agent_briefing", return_value="MAIN BRIEFING"):
            result = controller._get_agent_briefing({})
            assert result["briefing"] == "MAIN BRIEFING"
