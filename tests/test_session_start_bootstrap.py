"""Tests covering the session-start bootstrap path.

Two bugs surfaced 2026-05-14 (workflow not active at session start):

Bug A. `register_main_agent` calls `dc.call_tool("router__register_agent", ...)`
which sends JSON-RPC method `tools/call`. The DaemonClient guard in
`_call` requires `register()` first for any method that isn't in the
narrow exempt set, so the bootstrap registration always raises
`RuntimeError("Must call register() before tool calls")`. The hook
swallows it and the main agent never gets phase-bound.

Bug B. `auto_start_workflow` and `register_main_agent` both race the
daemon socket on cold session-start. When the daemon is still binding,
the connect attempt gets ECONNREFUSED. `auto_start_workflow` swallows
the failure at DEBUG level (invisible at default WARNING) and no
workflow is started for the session.

These tests guard the fixes:
- DaemonClient must allow `tools/call` for the bootstrap tool names
  (`router__register_agent`, `router__update_agent_phase`) even before
  `register()` has been called. Any other tool name must still hit the
  guard.
- Both hook functions must retry briefly on `ConnectionRefusedError`
  rather than giving up on the first miss, and must log at WARNING (not
  DEBUG) when retries are exhausted.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
SESSION_START_PY = PROJECT_ROOT / "hooks" / "session-start.py"
DAEMON_CLIENT_PY = PROJECT_ROOT / "lib" / "daemon_client.py"

sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "hooks"))


def _load_session_start(name: str):
    """Fresh module load of hooks/session-start.py for isolation between tests."""
    spec = importlib.util.spec_from_file_location(name, SESSION_START_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_real_daemon_client(name: str):
    """Fresh module load of lib/daemon_client.py to bypass conftest's autouse mock.

    The conftest at tests/conftest.py installs a `MockDaemonClient` over the
    `DaemonClient` attribute of any already-imported `daemon_client` module.
    These tests need the real class to exercise the `_call` guard, so we load
    daemon_client.py under a unique module name that conftest does not patch.
    """
    spec = importlib.util.spec_from_file_location(name, DAEMON_CLIENT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Bug A — DaemonClient guard must let bootstrap tools through `tools/call`.
# ---------------------------------------------------------------------------


class TestDaemonClientBootstrapToolExemption:
    """Allow `router__register_agent` / `router__update_agent_phase` pre-register."""

    def _client_with_fake_sock(self):
        # Load DaemonClient fresh so the conftest autouse mock doesn't apply.
        dc_mod = _load_real_daemon_client(
            f"daemon_client_under_test_{id(self)}_{id(object())}"
        )
        dc = dc_mod.DaemonClient()
        dc._sock = MagicMock()
        dc._registered = False
        dc._read_response = MagicMock(
            return_value=b'{"jsonrpc":"2.0","id":1,"result":{}}'
        )
        return dc

    def test_router_register_agent_bypasses_guard(self):
        dc = self._client_with_fake_sock()
        try:
            dc.call_tool("router__register_agent", {
                "agent_id": "",
                "agent_type": "implementer",
                "roles": ["editor", "shell_full"],
            })
        except RuntimeError as e:
            if "caller-id" in str(e):
                pytest.fail("Guard still blocks router__register_agent before register()")
            raise

    def test_router_update_agent_phase_bypasses_guard(self):
        dc = self._client_with_fake_sock()
        try:
            dc.call_tool("router__update_agent_phase", {
                "agent_id": "",
                "workflow": "simple",
                "phase": "plan",
            })
        except RuntimeError as e:
            if "caller-id" in str(e):
                pytest.fail("Guard still blocks router__update_agent_phase before register()")
            raise

    def test_non_bootstrap_tool_still_guarded(self):
        """Guard must remain in place for any tool that isn't part of bootstrap."""
        dc = self._client_with_fake_sock()
        with pytest.raises(RuntimeError, match="caller-id"):
            dc.call_tool("router__ping", {})


# ---------------------------------------------------------------------------
# Bug B — both hook functions must retry briefly on cold-daemon connect.
# ---------------------------------------------------------------------------


def _connection_refused():
    return ConnectionRefusedError(111, "Connection refused")


class TestAutoStartRetriesOnColdDaemon:
    """auto_start_workflow must survive a brief startup race with the daemon."""

    def test_retries_then_succeeds(self):
        mod = _load_session_start("session_start_autostart_retry")

        good_dc = MagicMock()
        good_dc.__enter__ = MagicMock(return_value=good_dc)
        good_dc.__exit__ = MagicMock(return_value=False)
        good_dc.workflow_start = MagicMock(return_value={})

        dc_factory = MagicMock(side_effect=[_connection_refused(), good_dc])

        fake_pq = MagicMock()
        fake_pq.get_active_workflow_id = MagicMock(return_value=None)

        with patch.dict(
            "sys.modules",
            {
                "daemon_client": MagicMock(DaemonClient=dc_factory),
                "permission_query": fake_pq,
            },
        ), patch.object(mod.time, "sleep", lambda _s: None):
            mod.auto_start_workflow()

        assert dc_factory.call_count >= 2, (
            "auto_start_workflow did not retry after ConnectionRefusedError"
        )
        good_dc.workflow_start.assert_called_once_with(
            "simple", initial_state={"task": "Auto-started simple workflow"}
        )

    def test_warns_when_retries_exhausted(self):
        mod = _load_session_start("session_start_autostart_warn")

        dc_factory = MagicMock(side_effect=_connection_refused())

        fake_pq = MagicMock()
        fake_pq.get_active_workflow_id = MagicMock(return_value=None)

        warnings: list[str] = []

        with patch.dict(
            "sys.modules",
            {
                "daemon_client": MagicMock(DaemonClient=dc_factory),
                "permission_query": fake_pq,
            },
        ), patch.object(mod.time, "sleep", lambda _s: None), \
                patch.object(mod, "log_warning", lambda msg, **kw: warnings.append(msg)):
            mod.auto_start_workflow()

        assert any("auto-start" in w.lower() or "auto_start" in w.lower()
                   for w in warnings), (
            f"auto_start_workflow swallowed exhaustion silently; warnings={warnings!r}"
        )


class TestRegisterMainAgentRetriesOnColdDaemon:
    """register_main_agent must survive the same startup race."""

    def test_warns_when_retries_exhausted(self):
        mod = _load_session_start("session_start_register_warn")

        dc_factory = MagicMock(side_effect=_connection_refused())

        warnings: list[str] = []

        with patch.dict(
            "sys.modules",
            {"daemon_client": MagicMock(DaemonClient=dc_factory)},
        ), patch.object(mod, "get_active_workflow_id", lambda: "simple"), \
                patch.object(mod.time, "sleep", lambda _s: None), \
                patch.object(mod, "log_warning", lambda msg, **kw: warnings.append(msg)):
            mod.register_main_agent()

        assert any("register_main_agent" in w for w in warnings), (
            f"register_main_agent swallowed exhaustion silently; warnings={warnings!r}"
        )

    def test_retries_then_succeeds(self):
        mod = _load_session_start("session_start_register_retry")

        good_dc = MagicMock()
        # __enter__ returns self; the helper calls __enter__ directly (not via
        # `with`), so that's the entry point for subsequent attribute access.
        good_dc.__enter__ = MagicMock(return_value=good_dc)
        good_dc.__exit__ = MagicMock(return_value=False)
        good_dc.call_tool = MagicMock(return_value={})
        good_dc.workflow_get_state = MagicMock(return_value={"phase": "plan"})

        dc_factory = MagicMock(side_effect=[_connection_refused(), good_dc])

        with patch.dict(
            "sys.modules",
            {"daemon_client": MagicMock(DaemonClient=dc_factory)},
        ), patch.object(mod, "get_active_workflow_id", lambda: "simple"), \
                patch.object(mod.time, "sleep", lambda _s: None):
            mod.register_main_agent()

        assert dc_factory.call_count >= 2, (
            "register_main_agent did not retry after ConnectionRefusedError"
        )
        called_tools = [c.args[0] for c in good_dc.call_tool.call_args_list]
        assert "router__register_agent" in called_tools, (
            f"register_main_agent never registered after retry; calls={called_tools!r}"
        )
