"""Regression test for issue #122 -- concurrent-session main-agent clobber.

Two concurrent Claude Code sessions both register their main agent under the
shared key "" (empty string) in permissions._agents. Session B registration
overwrites Session A AgentInfo (workflow/phase binding), so Session A tool
calls suddenly resolve to the wrong phase.

Fix: main-agent caller id is derived from CLAUDE_CODE_SESSION_ID, making it
session-unique ("main:<session_id>"). Both the mcp-router (bin/mcp-router) and
the bootstrap hook (hooks/session-start.py :: register_main_agent) must derive
the same id so they agree on the registry key.

This file tests three layers:
 1. PermissionChecker: two agents with distinct ids do not clobber each other.
 2. mcp-router: CALLER_ID derivation -- when AGENT_SWARM_CALLER_ID is unset,
    CLAUDE_CODE_SESSION_ID is used to produce a unique key.
 3. register_main_agent hook: the id passed to router__register_agent matches
    what mcp-router derives (i.e. "main:<session_id>").
"""
from __future__ import annotations

import importlib.util
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "hooks"))

from lib.permissions import PermissionChecker  # noqa: E402

SESSION_START_PY = PROJECT_ROOT / "hooks" / "session-start.py"
MCP_ROUTER_PY = PROJECT_ROOT / "bin" / "mcp-router"

_TEST_CONFIG = {
    "global": {
        "allowed": ["native__read_file"],
        "blocked": ["native__write_file"],
        "superblocked": [],
    },
    "roles": {},
    "agents": {
        "implementer": {
            "allowed": ["native__write_file", "native__read_file"],
            "blocked": [],
        },
    },
    "workflows": {
        "simple": {
            "plan": {
                "allowed": ["native__read_file"],
                "blocked": ["native__write_file"],
            },
            "implement": {
                "allowed": ["native__write_file", "native__read_file"],
                "blocked": [],
            },
        },
    },
}


@pytest.fixture
def config_path(tmp_path):
    p = tmp_path / "permissions.yaml"
    p.write_text(yaml.dump(_TEST_CONFIG))
    return p


@pytest.fixture
def checker(config_path):
    return PermissionChecker(config_path)


# ---------------------------------------------------------------------------
# Layer 1: PermissionChecker -- distinct agent ids are independent.
# ---------------------------------------------------------------------------


class TestTwoMainAgentsDoNotClobber:
    """Registering two main agents with distinct session-derived ids keeps
    their phase bindings independent."""

    def test_two_sessions_have_independent_bindings(self, checker):
        """Registering session-A main agent then session-B must NOT alter
        session-A workflow/phase binding."""
        id_a = "main:session-aaa"
        id_b = "main:session-bbb"

        checker.register_agent(id_a, "implementer")
        checker.update_agent_phase(id_a, "simple", "plan")

        checker.register_agent(id_b, "implementer")
        checker.update_agent_phase(id_b, "simple", "implement")

        agent_a = checker.get_agent(id_a)
        assert agent_a is not None, "Session A main agent lost from registry"
        assert agent_a.phase == "plan", (
            f"Session A phase was clobbered: expected plan, got {agent_a.phase!r}"
        )

        agent_b = checker.get_agent(id_b)
        assert agent_b is not None
        assert agent_b.phase == "implement"

    def test_clobber_happens_with_shared_empty_key(self, checker):
        """Documents the original bug: both main agents keyed as  means
        the second registration silently overwrites the first.
        This test documents the clobber and must pass on both master and fix.
        """
        shared_key = ""

        checker.register_agent(shared_key, "implementer")
        checker.update_agent_phase(shared_key, "simple", "plan")

        checker.register_agent(shared_key, "implementer")
        checker.update_agent_phase(shared_key, "simple", "implement")

        agent = checker.get_agent(shared_key)
        assert agent.phase == "implement", (
            "Expected the clobber to overwrite to implement; "
            f"got {agent.phase!r}"
        )

    def test_phase_check_isolated_by_session(self, checker):
        """Permission checks for each session resolve to the correct phase
        rules, with no cross-contamination."""
        id_a = "main:session-aaa"
        id_b = "main:session-bbb"

        checker.register_agent(id_a, "implementer")
        checker.update_agent_phase(id_a, "simple", "plan")

        checker.register_agent(id_b, "implementer")
        checker.update_agent_phase(id_b, "simple", "implement")

        agent_a = checker.get_agent(id_a)
        agent_b = checker.get_agent(id_b)

        allowed_a, _ = checker.check("native__write_file", {}, agent_a)
        assert not allowed_a, "Session A (plan phase) should block write_file"

        allowed_b, _ = checker.check("native__write_file", {}, agent_b)
        assert allowed_b, "Session B (implement phase) should allow write_file"


# ---------------------------------------------------------------------------
# Layer 2: mcp-router CALLER_ID derivation.
# ---------------------------------------------------------------------------


def _load_mcp_router(env_override: dict):
    """Load bin/mcp-router under a fresh module name with env overrides.

    bin/mcp-router has no .py extension so spec_from_file_location returns
    None. Use SourceFileLoader directly.

    Module-level CALLER_ID = os.environ.get(...) must be re-evaluated under
    a modified environment, so importlib with a unique name is required.
    """
    import importlib.machinery
    import types

    unique_name = f"mcp_router_test_{id(env_override)}_{id(object())}"
    env_copy = {k: v for k, v in env_override.items() if v is not None}
    absent_keys = [k for k, v in env_override.items() if v is None]

    saved = {k: os.environ.pop(k, None) for k in absent_keys}
    try:
        with patch.dict(os.environ, env_copy):
            loader = importlib.machinery.SourceFileLoader(unique_name, str(MCP_ROUTER_PY))
            mod = types.ModuleType(unique_name)
            mod.__file__ = str(MCP_ROUTER_PY)
            loader.exec_module(mod)
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    return mod


class TestMcpRouterCallerIdDerivation:
    """bin/mcp-router must derive a session-unique CALLER_ID when
    AGENT_SWARM_CALLER_ID is not set."""

    def test_subagent_caller_id_used_directly(self):
        """When AGENT_SWARM_CALLER_ID is set (subagent), it is used as-is."""
        mod = _load_mcp_router({
            "AGENT_SWARM_CALLER_ID": "sub-abc123",
            "CLAUDE_CODE_SESSION_ID": "sess-xyz",
        })
        assert mod.CALLER_ID == "sub-abc123"

    def test_main_agent_derives_session_unique_id(self):
        """When AGENT_SWARM_CALLER_ID is unset, CALLER_ID must incorporate
        CLAUDE_CODE_SESSION_ID so concurrent main sessions get distinct keys."""
        mod = _load_mcp_router({
            "AGENT_SWARM_CALLER_ID": None,
            "CLAUDE_CODE_SESSION_ID": "deadbeef-1234",
        })
        assert mod.CALLER_ID is not None, (
            "CALLER_ID is None -- mcp-router still defaults to None for main session"
        )
        assert mod.CALLER_ID != "", (
            "CALLER_ID is  -- mcp-router still uses the shared-key fallback"
        )
        assert "deadbeef-1234" in mod.CALLER_ID, (
            f"CALLER_ID {mod.CALLER_ID!r} does not incorporate CLAUDE_CODE_SESSION_ID"
        )

    def test_caller_stamp_uses_session_unique_id(self):
        """The _caller field stamped into tools/call uses the session-unique id."""
        mod = _load_mcp_router({
            "AGENT_SWARM_CALLER_ID": None,
            "CLAUDE_CODE_SESSION_ID": "sess-cafebabe",
        })
        caller = mod.CALLER_ID if mod.CALLER_ID is not None else ""
        assert caller != "", (
            "Stamped _caller is  -- two main sessions would clobber in daemon"
        )
        assert "sess-cafebabe" in caller


# ---------------------------------------------------------------------------
# Layer 3: register_main_agent hook uses the session-unique id.
# ---------------------------------------------------------------------------


def _load_session_start(name: str):
    spec = importlib.util.spec_from_file_location(name, SESSION_START_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRegisterMainAgentUsesSessionUniqueId:
    """register_main_agent must pass the session-unique caller id to
    router__register_agent, matching what mcp-router will stamp."""

    def test_main_agent_registered_with_session_id(self):
        """The agent_id passed to router__register_agent must incorporate
        CLAUDE_CODE_SESSION_ID when it is available."""
        session_id = "test-session-99"

        mod = _load_session_start(f"session_start_isolation_{id(self)}")

        good_dc = MagicMock()
        good_dc.call_tool = MagicMock(return_value={})
        good_dc.workflow_get_state = MagicMock(return_value={"phase": "plan"})

        @contextmanager
        def _fake_open(label):
            yield good_dc

        saved = os.environ.pop("AGENT_SWARM_CALLER_ID", None)
        try:
            with patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": session_id}), \
                 patch.dict(sys.modules, {
                     "daemon_client": MagicMock(
                         DaemonClient=MagicMock(return_value=good_dc)
                     )
                 }), \
                 patch.object(mod, "get_active_workflow_id", lambda: "simple"), \
                 patch.object(mod, "_open_daemon_client_with_retry", _fake_open):
                mod.register_main_agent()
        finally:
            if saved is not None:
                os.environ["AGENT_SWARM_CALLER_ID"] = saved

        register_calls = [
            c for c in good_dc.call_tool.call_args_list
            if c.args and c.args[0] == "router__register_agent"
        ]
        assert register_calls, "router__register_agent was never called"

        registered_id = register_calls[0].args[1].get("agent_id", "")
        assert registered_id != "", (
            f"agent_id registered is  -- still using the shared empty key; "
            f"call: {register_calls[0]}"
        )
        assert session_id in registered_id, (
            f"agent_id {registered_id!r} does not contain session id {session_id!r}"
        )
