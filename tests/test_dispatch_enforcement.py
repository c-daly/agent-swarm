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
        ctrl._workflow_configs = {}
        ctrl._workflow_state = {}
        ctrl.data = MagicMock()
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

    def test_agent_id_uses_full_uuid_entropy(self, controller):
        """agent_id must carry full uuid4 entropy (128-bit / 32 hex chars), not
        a truncated 32-bit prefix. Truncation makes birthday collisions between
        concurrent workers plausible, and a collision entangles two workers in a
        single AgentInfo / iterate instance -- silent governance bypass (#130)."""
        import re
        result = controller._prepare_dispatch({"agent_type": "implementer"})
        assert re.fullmatch(r"sub-[0-9a-f]{32}", result["agent_id"]), (
            f"agent_id {result['agent_id']!r} is not a full-entropy uuid4 hex"
        )

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

    def test_standalone_implementer_starts_bound_iterate_instance(self, controller):
        """A standalone implementer (no active workflow) gets a per-worker iterate
        instance STARTED and is BOUND to its initial phase, so iterate's phase
        gates govern the worker from its first mcp-call (#116). The briefing tells
        the worker to use this sub-id as its --caller-id, so binding it here is
        correct. Previously prepare_dispatch started no instance and left the
        worker unbound -> governed by permissive agent-type rules, bypassing the
        phase gates."""
        controller._workflow_configs = {
            "iterate": MagicMock(initial_phase="test_writing")
        }
        controller.permissions.register_agent.side_effect = (
            lambda agent_id, role=None: MagicMock(
                agent_id=agent_id, agent_type=role, roles=[])
        )
        with patch("controller.assemble_subagent_briefing", return_value=""), \
                patch("controller.get_workflow_state", return_value=(None, None)):
            result = controller._prepare_dispatch({"agent_type": "implementer"})
        agent_id = result["agent_id"]
        wf_id = f"iterate:{agent_id}"
        assert wf_id in controller._workflow_state
        assert controller._workflow_state[wf_id]["phase"] == "test_writing"
        controller.permissions.update_agent_phase.assert_any_call(
            agent_id, wf_id, "test_writing"
        )

    def test_standalone_implementer_briefing_addresses_its_instance(self, controller):
        """The worker's briefing must substitute __WF_ID__ with the full per-instance
        id (iterate:<agent_id>) it is bound to -- not the bare base 'iterate', which
        is not a live workflow the worker could advance or stop (PR #126 greptile P1).
        assemble_subagent_briefing strips the suffix for protocol lookup but keeps
        the full id for the __WF_ID__ substitution."""
        controller._workflow_configs = {
            "iterate": MagicMock(initial_phase="test_writing")
        }
        controller.permissions.register_agent.side_effect = (
            lambda agent_id, role=None: MagicMock(
                agent_id=agent_id, agent_type=role, roles=[])
        )
        with patch("controller.get_workflow_state", return_value=(None, None)):
            result = controller._prepare_dispatch({"agent_type": "implementer"})
        agent_id = result["agent_id"]
        assert f"iterate:{agent_id}" in result["briefing"]

    def test_standalone_implementer_binds_on_instance_collision(self, controller):
        """If iterate:<agent_id> already exists when prepare_dispatch starts a
        worker (an agent_id collision, or a re-dispatch of the sub-id),
        _wf_start raises WorkflowError and its own bind never runs. The except
        branch must still bind THIS agent to the live instance's CURRENT phase,
        otherwise the new worker proceeds unbound and permissions.check silently
        skips all L1 phase gates for it (PR #126 greptile P1)."""
        controller._workflow_configs = {
            "iterate": MagicMock(initial_phase="test_writing")
        }
        controller.permissions.register_agent.side_effect = (
            lambda agent_id, role=None: MagicMock(
                agent_id=agent_id, agent_type=role, roles=[])
        )
        fake_hex = "c0111de0deadbeefcafef00dba5eba11"
        with patch("controller.uuid.uuid4",
                   return_value=MagicMock(hex=fake_hex)):
            wf_id = f"iterate:sub-{fake_hex}"
            # Pre-existing instance bound to a DIFFERENT prior worker, advanced
            # past its initial phase.
            controller._workflow_state[wf_id] = {
                "phase": "implementing", "active_agents": {}}
            with patch("controller.assemble_subagent_briefing", return_value=""), \
                    patch("controller.get_workflow_state", return_value=(None, None)):
                result = controller._prepare_dispatch({"agent_type": "implementer"})
        agent_id = result["agent_id"]
        assert agent_id == f"sub-{fake_hex}"
        # Bound to the existing instance's CURRENT phase, not left ungoverned.
        controller.permissions.update_agent_phase.assert_any_call(
            agent_id, wf_id, "implementing"
        )

    def test_complete_dispatch_stops_worker_iterate_instance(self, controller):
        """complete_dispatch tears down the per-worker iterate instance keyed by
        the agent id, so a finished standalone-implementer worker does not orphan
        it in _workflow_state (#116 binding implies #124-style cleanup)."""
        agent_id = "sub-deadbeef"
        wf_id = f"iterate:{agent_id}"
        controller._workflow_state[wf_id] = {"phase": "test_writing", "active_agents": {}}
        controller._agent_state[agent_id] = {"status": "pending"}
        controller._complete_dispatch({"agent_id": agent_id, "status": "completed"})
        assert wf_id not in controller._workflow_state

    def test_complete_dispatch_skips_wf_stop_without_instance(self, controller):
        """A dispatch with no per-worker iterate instance (a reviewer or any
        non-implementer) completes WITHOUT invoking _wf_stop -- the membership
        guard avoids raising/catching WorkflowError for the common case (PR #126
        review feedback)."""
        controller._agent_state["sub-noinst"] = {"status": "pending"}
        controller._wf_stop = MagicMock()
        controller._complete_dispatch({"agent_id": "sub-noinst", "status": "completed"})
        controller._wf_stop.assert_not_called()

    def test_implementer_inherits_active_workflow(self, controller):
        """An implementer dispatched within an active workflow inherits it
        (does NOT auto-start iterate)."""
        with patch("controller.get_workflow_state", return_value=("develop", "implement")), \
                patch("controller.assemble_subagent_briefing", return_value=""):
            result = controller._prepare_dispatch({"agent_type": "implementer"})
        agent_id = result["agent_id"]
        assert not any(k.startswith("iterate:") for k in controller._workflow_state)
        controller.permissions.update_agent_phase.assert_any_call(
            agent_id, "develop", "implement"
        )

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
        """For a standalone implementer (no active workflow) the briefing override
        is the per-instance iterate id (iterate:<agent_id>) -- the workflow the
        worker is actually bound to, so __WF_ID__ addresses it (PR #126 greptile)."""
        with patch("controller.assemble_subagent_briefing") as mock_brief, \
             patch("controller.get_workflow_state", return_value=(None, None)):
            mock_brief.return_value = ""
            result = controller._prepare_dispatch({"agent_type": "implementer"})
            _, kwargs = mock_brief.call_args
            assert kwargs.get("workflow_override") == f"iterate:{result['agent_id']}"


class TestGetAgentBriefing:
    def test_returns_main_agent_briefing(self, controller):
        with patch("controller.assemble_agent_briefing", return_value="MAIN BRIEFING"):
            result = controller._get_agent_briefing({})
            assert result["briefing"] == "MAIN BRIEFING"



class TestCompleteDispatch:
    def test_completes_agent(self, controller):
        result = controller._prepare_dispatch({
            "agent_type": "implementer",
            "description": "test task",
        })
        agent_id = result["agent_id"]
        complete_result = controller._complete_dispatch({
            "agent_id": agent_id,
            "status": "completed",
        })
        assert complete_result["success"] is True
        assert complete_result["agent_id"] == agent_id
        assert controller._agent_state[agent_id]["status"] == "completed"
        assert "completed_at" in controller._agent_state[agent_id]
        controller.permissions.remove_agent.assert_called_once_with(agent_id)

    def test_missing_agent_id_raises(self, controller):
        from lib.errors import RouterError
        with pytest.raises(RouterError):
            controller._complete_dispatch({})