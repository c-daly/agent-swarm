#!/usr/bin/env python3
"""Integration tests: DaemonClient -> Router -> Controller round-trip.

Spins up a real Controller + Router on a free port, connects a DaemonClient,
and exercises the full wire protocol end-to-end.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from lib.controller import Controller
from lib.daemon_client import DaemonClient, DaemonError
from lib.router import Router


# ---------------------------------------------------------------------------
# Mock workflow config (same shape as test_controller.py)
# ---------------------------------------------------------------------------

@dataclass
class MockPhaseConfig:
    name: str
    checkpoint: bool = False

@dataclass
class MockWorkflowConfig:
    name: str
    initial_phase: str
    terminal_phase: str
    phases: dict   # name -> MockPhaseConfig
    transitions: dict  # phase -> set of targets


def _make_iterate_config():
    return MockWorkflowConfig(
        name="iterate",
        initial_phase="test_writing",
        terminal_phase="complete",
        phases={
            "test_writing": MockPhaseConfig(name="test_writing"),
            "implement": MockPhaseConfig(name="implement"),
            "test": MockPhaseConfig(name="test", checkpoint=True),
            "review": MockPhaseConfig(name="review", checkpoint=True),
        },
        transitions={
            "test_writing": {"implement"},
            "implement": {"test"},
            "test": {"implement", "review"},
            "review": {"implement", "complete"},
        },
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PERM_CONFIG = {
    "global": {
        "allowed": ["native__*", "router__*", "workflow__*", "serena__*"],
        "blocked": [],
        "superblocked": [],
    },
}

_BACKEND_CONFIG = {
    "serena": {"command": ["echo"], "tool_prefix": "serena"},
}


@pytest.fixture
def server(tmp_path):
    """Start Controller + Router on a free port.  Yields (router, port)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "permissions.yaml").write_text(yaml.dump(_PERM_CONFIG))
    (config_dir / "backends.json").write_text(json.dumps(_BACKEND_CONFIG))

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    wf_configs = {"iterate": _make_iterate_config()}
    ctrl = Controller(config_dir, data_dir, workflow_configs=wf_configs)
    router = Router(port=0, controller=ctrl)  # port 0 => OS picks free port

    # Router.serve_forever binds then loops, so we start it in a thread.
    # But port=0 means we need the actual port after bind.  Unfortunately
    # serve_forever does both bind + accept in one call.  We need to
    # manually do the bind first.
    import socket
    router._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    router._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    router._server.bind(("127.0.0.1", 0))
    actual_port = router._server.getsockname()[1]
    router._port = actual_port

    # Now start serving (it will skip the bind since socket is already bound)
    # We need to patch serve_forever to skip the bind/listen part
    def _serve():
        router._server.listen(32)
        router._server.settimeout(1.0)
        router._running = True
        while router._running:
            try:
                client, addr = router._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with router._connections_lock:
                if router._active_connections >= 64:
                    client.close()
                    continue
                router._active_connections += 1
            try:
                threading.Thread(
                    target=router._handle_connection,
                    args=(client,),
                    daemon=True,
                ).start()
            except Exception:
                with router._connections_lock:
                    router._active_connections -= 1
                client.close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    time.sleep(0.05)  # let the listener settle

    yield router, actual_port

    router.shutdown()
    t.join(timeout=2)


@pytest.fixture
def client(server):
    """DaemonClient connected to the test server."""
    _, port = server
    c = DaemonClient(host="127.0.0.1", port=port, timeout=5.0)
    c.connect()
    yield c
    c.close()


# ===========================================================================
# Tests
# ===========================================================================


class TestMCPHandshake:
    """Verify the MCP initialization handshake works end-to-end."""

    def test_connect_succeeds(self, server):
        _, port = server
        c = DaemonClient(host="127.0.0.1", port=port, timeout=5.0)
        c.connect()  # should not raise
        c.close()

    def test_tools_list_returns_tools(self, client):
        tools = client.list_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0
        names = [t["name"] for t in tools]
        assert "router__ping" in names
        assert "workflow__workflow_start" in names
        assert "workflow__workflow_advance_phase" in names
        assert "workflow__workflow_pass_checkpoint" in names
        # Verify removed tools are gone
        assert "workflow__workflow_set_state" not in names
        assert "workflow__workflow_update" not in names


class TestRegisterAgent:
    """Agent registration via tools/call."""

    def test_register_succeeds(self, client):
        result = client.register(
            agent_id="test-agent-1",
            agent_type="implementer",
        )
        assert result["agent_id"] == "test-agent-1"
        assert result["agent_type"] == "implementer"

    def test_double_register_raises(self, client):
        client.register(agent_id="test-agent-2", agent_type="explorer")
        with pytest.raises(RuntimeError, match="Already registered"):
            client.register(agent_id="test-agent-2", agent_type="explorer")


class TestRouterPing:
    """Health check through the full wire."""

    def test_ping(self, client):
        result = client.call_tool("router__ping", {})
        assert result["status"] == "ok"


class TestWorkflowLifecycle:
    """Full workflow lifecycle through the wire protocol."""

    def test_start_and_get_state(self, client):
        state = client.workflow_start("iterate", {"task": "build feature"})
        assert state["task"] == "build feature"
        assert state["phase"] == "test_writing"
        assert "started_at" in state
        assert state["active_agents"] == {}

    def test_start_strips_protected_keys(self, client):
        state = client.workflow_start("iterate", {
            "task": "ok",
            "phase": "hacked",
            "active_agents": "hacked",
        })
        # Protected keys should be daemon-managed, not user values
        assert state["phase"] == "test_writing"
        assert state["active_agents"] == {}

    def test_get_state_round_trip(self, client):
        client.workflow_start("iterate", {"x": 42})
        state = client.workflow_get_state("iterate")
        assert state["x"] == 42
        assert state["phase"] == "test_writing"

    def test_set_value_normal_key(self, client):
        client.workflow_start("iterate", {})
        client.workflow_set_value("iterate", "notes", "hello")
        val = client.workflow_get_value("iterate", "notes")
        assert val == "hello"

    def test_set_value_protected_key_rejected(self, client):
        client.workflow_start("iterate", {})
        with pytest.raises(DaemonError):
            client.workflow_set_value("iterate", "phase", "hacked")

    def test_set_value_checkpoint_key_rejected(self, client):
        client.workflow_start("iterate", {})
        with pytest.raises(DaemonError):
            client.workflow_set_value("iterate", "test_checkpoint_passed", True)

    def test_is_active(self, client):
        client.workflow_start("iterate", {})
        assert client.workflow_is_active("iterate") is True

    def test_is_active_nonexistent(self, client):
        assert client.workflow_is_active("no-such-wf") is False

    def test_stop(self, client):
        client.workflow_start("iterate", {})
        client.workflow_stop("iterate")
        assert client.workflow_is_active("iterate") is False


class TestPhaseTransitions:
    """advance_phase and pass_checkpoint through the wire."""

    def test_advance_phase_valid(self, client):
        client.workflow_start("iterate", {})
        # test_writing -> implement (no checkpoint on test_writing)
        result = client.workflow_advance_phase("iterate", "implement")
        assert result["status"] == "advanced"
        assert result["phase"] == "implement"
        state = client.workflow_get_state("iterate")
        assert state["phase"] == "implement"

    def test_advance_phase_invalid_target(self, client):
        client.workflow_start("iterate", {})
        # test_writing -> review is NOT a valid transition
        with pytest.raises(DaemonError):
            client.workflow_advance_phase("iterate", "review")

    def test_checkpoint_enforcement(self, client):
        """Cannot advance past a checkpoint phase without passing it."""
        client.workflow_start("iterate", {})
        # Advance to implement, then to test (which has a checkpoint)
        client.workflow_advance_phase("iterate", "implement")
        client.workflow_advance_phase("iterate", "test")
        # Now try to advance test -> review without passing checkpoint
        with pytest.raises(DaemonError, match="[Cc]heckpoint"):
            client.workflow_advance_phase("iterate", "review")

    def test_pass_checkpoint_then_advance(self, client):
        client.workflow_start("iterate", {})
        client.workflow_advance_phase("iterate", "implement")
        client.workflow_advance_phase("iterate", "test")
        # Pass the checkpoint
        result = client.workflow_pass_checkpoint("iterate")
        assert result["status"] == "checkpoint_passed"
        assert result["phase"] == "test"
        # Now advance should work
        result = client.workflow_advance_phase("iterate", "review")
        assert result["status"] == "advanced"
        assert result["phase"] == "review"

    def test_pass_checkpoint_on_non_checkpoint_phase(self, client):
        client.workflow_start("iterate", {})
        # test_writing has no checkpoint
        with pytest.raises(DaemonError, match="does not have a checkpoint"):
            client.workflow_pass_checkpoint("iterate")

    def test_terminal_phase_deactivates(self, client):
        """Advancing to terminal phase marks workflow as inactive."""
        client.workflow_start("iterate", {})
        client.workflow_advance_phase("iterate", "implement")
        client.workflow_advance_phase("iterate", "test")
        client.workflow_pass_checkpoint("iterate")
        client.workflow_advance_phase("iterate", "review")
        client.workflow_pass_checkpoint("iterate")
        client.workflow_advance_phase("iterate", "complete")
        # Should be inactive now
        assert client.workflow_is_active("iterate") is False
        # But state should still have completed_at
        state = client.workflow_get_state("iterate")
        assert "completed_at" in state
        assert state["phase"] == "complete"


class TestAgentState:
    """Agent state operations through the wire."""

    def test_set_and_get(self, client):
        client.agent_set_state("ag-1", {"status": "working"})
        state = client.agent_get_state("ag-1")
        assert state["status"] == "working"

    def test_get_nonexistent_returns_none(self, client):
        state = client.agent_get_state("no-such-agent")
        assert state is None

    def test_delete(self, client):
        client.agent_set_state("ag-2", {"x": 1})
        client.agent_delete("ag-2")
        state = client.agent_get_state("ag-2")
        assert state is None

    def test_list(self, client):
        client.agent_set_state("ag-a", {"x": 1})
        client.agent_set_state("ag-b", {"x": 2})
        agents = client.agent_list()
        assert "ag-a" in agents
        assert "ag-b" in agents


class TestNativeToolCall:
    """Verify a native tool call routes through the full stack."""

    def test_bash_echo(self, client):
        result = client.call_tool("native__bash", {"command": "echo hello"})
        assert "hello" in str(result)

    def test_read_file(self, client, tmp_path):
        p = tmp_path / "testfile.txt"
        p.write_text("line1\nline2\n")
        result = client.call_tool("native__read_file", {"file_path": str(p)})
        assert "line1" in str(result)


class TestErrorPropagation:
    """Verify errors propagate correctly through the wire."""

    def test_unknown_tool_raises(self, client):
        with pytest.raises(DaemonError):
            client.call_tool("workflow__nonexistent_tool", {})

    def test_workflow_not_found_returns_none(self, client):
        """get_state for non-existent workflow returns None, not an error."""
        result = client.workflow_get_state("no-such-workflow")
        assert result is None

    def test_start_unknown_workflow_raises(self, client):
        """When workflow_configs is set, unknown workflow IDs are rejected."""
        with pytest.raises(DaemonError):
            client.workflow_start("unknown-wf", {})


class TestMultipleClients:
    """Verify multiple simultaneous client connections work."""

    def test_two_clients_independent_state(self, server):
        _, port = server
        c1 = DaemonClient(host="127.0.0.1", port=port, timeout=5.0)
        c2 = DaemonClient(host="127.0.0.1", port=port, timeout=5.0)
        c1.connect()
        c2.connect()

        try:
            # Both can call tools independently
            r1 = c1.call_tool("router__ping", {})
            r2 = c2.call_tool("router__ping", {})
            assert r1["status"] == "ok"
            assert r2["status"] == "ok"

            # Agent state is shared (same Controller)
            c1.call_tool("workflow__agent_set_state", {
                "agent_id": "shared-agent",
                "state": {"from": "client1"},
            })
            state = c2.call_tool("workflow__agent_get_state", {
                "agent_id": "shared-agent",
            })
            assert state["from"] == "client1"
        finally:
            c1.close()
            c2.close()
