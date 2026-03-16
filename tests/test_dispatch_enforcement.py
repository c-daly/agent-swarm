"""Tests for agent dispatch enforcement — prepare_dispatch and briefing retrieval."""
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
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
        ctrl._pending_dispatches = {}
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

    def test_registers_in_permissions(self, controller):
        controller._prepare_dispatch({"agent_type": "implementer"})
        controller.permissions.register_agent.assert_called_once()

    def test_stores_briefing(self, controller):
        with patch("controller.assemble_subagent_briefing", return_value="BRIEFING"):
            result = controller._prepare_dispatch({"agent_type": "implementer"})
            agent_id = result["agent_id"]
            assert agent_id in controller._pending_dispatches
            assert "BRIEFING" in controller._pending_dispatches[agent_id]["briefing"]

    def test_briefing_includes_identity_header(self, controller):
        with patch("controller.assemble_subagent_briefing", return_value="BRIEFING"):
            result = controller._prepare_dispatch({"agent_type": "implementer"})
            agent_id = result["agent_id"]
            briefing = controller._pending_dispatches[agent_id]["briefing"]
            assert f"Agent ID: `{agent_id}`" in briefing
            assert "mcp-call" in briefing

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


class TestGetAgentBriefing:
    def test_returns_stored_briefing(self, controller):
        controller._pending_dispatches["sub-abc123"] = {
            "briefing": "ROLE-SPECIFIC BRIEFING",
            "agent_type": "implementer",
        }
        with patch("controller.assemble_agent_briefing", return_value="GENERIC"):
            result = controller._get_agent_briefing({"agent_id": "sub-abc123"})
            assert result["briefing"] == "ROLE-SPECIFIC BRIEFING"

    def test_falls_back_to_generic(self, controller):
        with patch("controller.assemble_agent_briefing", return_value="GENERIC"):
            result = controller._get_agent_briefing({})
            assert result["briefing"] == "GENERIC"

    def test_unknown_agent_id_falls_back(self, controller):
        with patch("controller.assemble_agent_briefing", return_value="GENERIC"):
            result = controller._get_agent_briefing({"agent_id": "sub-unknown"})
            assert result["briefing"] == "GENERIC"
