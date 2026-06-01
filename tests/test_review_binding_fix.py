"""Tests for two workflow fixes:

1. develop/review reviewer must be able to run read-only git (review a PR diff)
   while still being blocked from writing/pushing.
2. Subagent role/phase binding: the dispatch hook (prepare_dispatch) binds the
   agent to the live (workflow, phase) once, in the daemon's shared registry;
   mcp-call must NOT re-register on every call (that would clobber the role with
   AGENT_TYPE/WORKFLOW_ID env defaults).
"""
import importlib.util
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
PERMISSIONS_YAML = PROJECT_ROOT / "config" / "permissions.yaml"


# ── Fix #1: develop/review needs read-only git ───────────────────────────────
class TestDevelopReviewGit:
    @pytest.fixture
    def checker(self):
        from permissions import PermissionChecker
        return PermissionChecker(PERMISSIONS_YAML)

    @staticmethod
    def _reviewer():
        from permissions import AgentInfo
        return AgentInfo(agent_id="r", agent_type="reviewer",
                         workflow="develop", phase="review")

    def test_reviewer_can_git_diff(self, checker):
        ok, _ = checker.check("native__bash", {"command": "git diff HEAD"}, self._reviewer())
        assert ok, "reviewer must be able to run 'git diff' in develop/review"

    def test_reviewer_can_gh_pr_diff(self, checker):
        ok, _ = checker.check("native__bash", {"command": "gh pr diff 12"}, self._reviewer())
        assert ok, "reviewer must be able to run 'gh pr diff' in develop/review"

    def test_reviewer_cannot_write(self, checker):
        ok, _ = checker.check("native__write_file", {"file_path": "/x.py"}, self._reviewer())
        assert not ok, "reviewer must NOT write in develop/review"

    def test_reviewer_cannot_git_push(self, checker):
        ok, _ = checker.check("native__bash", {"command": "git push origin main"}, self._reviewer())
        assert not ok, "reviewer must NOT push in develop/review"

    def test_reviewer_cannot_arbitrary_bash(self, checker):
        ok, _ = checker.check("native__bash", {"command": "rm -rf /tmp/x"}, self._reviewer())
        assert not ok, "reviewer must NOT run arbitrary shell in develop/review"


# ── Fix #2a: prepare_dispatch binds the live workflow/phase ──────────────────
@pytest.fixture
def controller():
    from controller import Controller
    with patch.object(Controller, "__init__", lambda self: None):
        ctrl = Controller.__new__(Controller)
        ctrl.permissions = MagicMock()
        ctrl.permissions.register_agent.return_value = MagicMock(
            agent_id="sub-abc123", agent_type="reviewer", roles=[],
            workflow=None, phase=None)
        ctrl._agent_state = {}
        ctrl._agent_set_state = MagicMock()
        ctrl._workflow_configs = {}
        ctrl._state_lock = threading.RLock()
        yield ctrl


class TestPrepareDispatchBinding:
    def test_binds_agent_to_live_workflow_phase(self, controller):
        with patch("controller.assemble_subagent_briefing", return_value=""), \
             patch("controller.get_workflow_state", return_value=("develop", "review")):
            controller._prepare_dispatch({"agent_type": "reviewer"})
        controller.permissions.update_agent_phase.assert_called_once()
        ca = controller.permissions.update_agent_phase.call_args
        assert ca.args[1] == "develop" and ca.args[2] == "review"

    def test_no_binding_when_no_active_workflow(self, controller):
        with patch("controller.assemble_subagent_briefing", return_value=""), \
             patch("controller.get_workflow_state", return_value=(None, None)):
            controller._prepare_dispatch({"agent_type": "reviewer"})
        controller.permissions.update_agent_phase.assert_not_called()


# ── Fix #2b: mcp-call must not re-register (shared daemon state) ──────────────
def _load_mcp_call():
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("mcp_call_mod", str(PROJECT_ROOT / "bin" / "mcp-call"))
    spec = importlib.util.spec_from_loader("mcp_call_mod", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestMcpCallHandshake:
    def test_call_tool_registers_for_handshake(self, monkeypatch):
        """mcp-call must complete the DaemonClient registration handshake:
        call_tool requires the client-side _registered flag. The daemon makes
        register idempotent so this does not clobber the agent's role/phase."""
        mod = _load_mcp_call()
        dc = MagicMock()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=dc)
        cm.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr(mod, "DaemonClient", MagicMock(return_value=cm))
        mod.call_tool("native__read_file", {"_caller": "sub-x", "file_path": "/x"}, caller_id="sub-x")
        dc.register.assert_called_once()
        dc.call_tool.assert_called_once()


class TestRegisterAgentIdempotent:
    """The clobber prevention lives in the daemon handler, not in mcp-call: an
    already-registered agent (bound by prepare_dispatch) is preserved when a
    later registration arrives with default values."""

    def test_existing_registration_preserved(self, controller):
        existing = MagicMock(agent_id="sub-x", agent_type="reviewer",
                             roles=["reviewer"], workflow="develop", phase="review")
        controller.permissions.get_agent.return_value = existing
        controller.permissions.register_agent.reset_mock()
        with patch("controller.assemble_subagent_briefing", return_value=""):
            result = controller._handle_router("register_agent", {
                "agent_id": "sub-x", "agent_type": "implementer", "workflow_id": "iterate"})
        controller.permissions.register_agent.assert_not_called()
        assert result["agent_type"] == "reviewer"
        assert result["workflow_id"] == "develop"
        assert result["phase"] == "review"

    def test_new_registration_creates(self, controller):
        controller.permissions.get_agent.return_value = None
        with patch("controller.assemble_subagent_briefing", return_value=""):
            controller._handle_router("register_agent", {
                "agent_id": "sub-y", "agent_type": "implementer"})
        controller.permissions.register_agent.assert_called_once()
