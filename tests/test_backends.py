#!/usr/bin/env python3
"""Tests for the external backend manager."""

import io
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lib.backends import BackendConfig, BackendManager, _INTERNAL_BACKENDS
from lib.errors import (
    BackendConnectionError,
    BackendError,
    BackendNotFoundError,
    RequestTimeoutError,
)


# --- Helpers ---


def _write_config(tmp_path, backends=None):
    """Write a backends.json config and return its path."""
    if backends is None:
        backends = {
            "serena": {"command": ["echo", "serena"], "tool_prefix": "serena"},
            "context7": {"command": ["echo", "ctx7"], "tool_prefix": "context7"},
            "native": {"command": ["echo", "native"], "tool_prefix": "native"},
            "workflow": {"command": ["echo", "wf"], "tool_prefix": "workflow"},
        }
    path = tmp_path / "backends.json"
    path.write_text(json.dumps(backends))
    return path


def _make_mock_proc(responses):
    """Create a mock Popen that returns JSON lines from responses list."""
    proc = MagicMock()
    proc.poll.return_value = None  # Process is alive
    proc.pid = 12345

    # Build stdout as a line-buffered reader
    lines = [json.dumps(r) + "\n" for r in responses]
    stdout_buf = io.StringIO("".join(lines))
    proc.stdout = stdout_buf
    proc.stdin = MagicMock()
    proc.stderr = MagicMock()
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = MagicMock()

    return proc


def _handshake_response():
    """Standard MCP initialize response."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "test", "version": "1.0"},
        },
    }


# --- Config loading ---


class TestConfigLoading:
    def test_loads_external_backends(self, tmp_path):
        path = _write_config(tmp_path)
        mgr = BackendManager(path)
        names = mgr.list()
        assert "serena" in names
        assert "context7" in names

    def test_skips_internal_backends(self, tmp_path):
        path = _write_config(tmp_path)
        mgr = BackendManager(path)
        names = mgr.list()
        assert "native" not in names
        assert "workflow" not in names

    def test_missing_config_file(self, tmp_path):
        mgr = BackendManager(tmp_path / "nonexistent.json")
        assert mgr.list() == []

    def test_backend_config_dataclass(self):
        cfg = BackendConfig(
            name="serena",
            command=["uvx", "serena"],
            tool_prefix="serena",
            env={"FOO": "bar"},
        )
        assert cfg.name == "serena"
        assert cfg.env == {"FOO": "bar"}


# --- Dispatch ---


class TestDispatch:
    def test_dispatch_unknown_backend(self, tmp_path):
        mgr = BackendManager(_write_config(tmp_path))
        with pytest.raises(BackendNotFoundError):
            mgr.dispatch("nonexistent", "tool", {})

    @patch("lib.backends.select.select")
    @patch("lib.backends.subprocess.Popen")
    def test_dispatch_success(self, mock_popen, mock_select, tmp_path):
        tool_response = {
            "jsonrpc": "2.0",
            "id": "abc",
            "result": {"content": [{"type": "text", "text": "hello"}]},
        }
        proc = _make_mock_proc([_handshake_response(), tool_response])
        mock_popen.return_value = proc
        mock_select.return_value = ([proc.stdout], [], [])

        mgr = BackendManager(_write_config(tmp_path))
        result = mgr.dispatch("serena", "find_symbol", {"name": "Foo"})

        assert result["content"][0]["text"] == "hello"

    @patch("lib.backends.select.select")
    @patch("lib.backends.subprocess.Popen")
    def test_dispatch_backend_error(self, mock_popen, mock_select, tmp_path):
        error_response = {
            "jsonrpc": "2.0",
            "id": "abc",
            "error": {"code": -32603, "message": "Internal error"},
        }
        proc = _make_mock_proc([_handshake_response(), error_response])
        mock_popen.return_value = proc
        mock_select.return_value = ([proc.stdout], [], [])

        mgr = BackendManager(_write_config(tmp_path))
        with pytest.raises(BackendError, match="Internal error"):
            mgr.dispatch("serena", "broken_tool", {})

    @patch("lib.backends.select.select")
    @patch("lib.backends.subprocess.Popen")
    def test_dispatch_timeout(self, mock_popen, mock_select, tmp_path):
        proc = _make_mock_proc([_handshake_response()])
        mock_popen.return_value = proc
        # Handshake succeeds, then tool call times out
        mock_select.side_effect = [
            ([proc.stdout], [], []),  # handshake select
            ([], [], []),  # tool call select — timeout
        ]

        mgr = BackendManager(_write_config(tmp_path))
        with pytest.raises(RequestTimeoutError):
            mgr.dispatch("serena", "slow_tool", {})

    @patch("lib.backends.select.select")
    @patch("lib.backends.subprocess.Popen")
    def test_dispatch_retries_on_broken_pipe(self, mock_popen, mock_select, tmp_path):
        # First process dies, second one works
        dead_proc = _make_mock_proc([_handshake_response()])
        dead_proc.stdin.write.side_effect = [None, BrokenPipeError("dead")]

        tool_response = {
            "jsonrpc": "2.0",
            "id": "x",
            "result": {"content": [{"type": "text", "text": "ok"}]},
        }
        live_proc = _make_mock_proc([_handshake_response(), tool_response])

        mock_popen.side_effect = [dead_proc, live_proc]
        mock_select.return_value = ([MagicMock()], [], [])

        # Patch stdout to return from the correct proc
        mock_select.side_effect = [
            ([dead_proc.stdout], [], []),  # handshake 1
            ([live_proc.stdout], [], []),  # handshake 2
            ([live_proc.stdout], [], []),  # tool call
        ]

        mgr = BackendManager(_write_config(tmp_path))
        result = mgr.dispatch("serena", "tool", {})
        assert result["content"][0]["text"] == "ok"


# --- list_tools ---


class TestListTools:
    @patch("lib.backends.select.select")
    @patch("lib.backends.subprocess.Popen")
    def test_list_tools(self, mock_popen, mock_select, tmp_path):
        tools_response = {
            "jsonrpc": "2.0",
            "id": "abc",
            "result": {
                "tools": [
                    {"name": "find_symbol", "description": "Find a symbol"},
                    {"name": "read_file", "description": "Read a file"},
                ]
            },
        }
        proc = _make_mock_proc([_handshake_response(), tools_response])
        mock_popen.return_value = proc
        mock_select.return_value = ([proc.stdout], [], [])

        mgr = BackendManager(_write_config(tmp_path))
        tools = mgr.list_tools("serena")
        assert len(tools) == 2
        assert tools[0]["name"] == "find_symbol"

    @patch("lib.backends.select.select")
    @patch("lib.backends.subprocess.Popen")
    def test_list_tools_cached(self, mock_popen, mock_select, tmp_path):
        tools_response = {
            "jsonrpc": "2.0",
            "id": "abc",
            "result": {"tools": [{"name": "t1"}]},
        }
        proc = _make_mock_proc([_handshake_response(), tools_response])
        mock_popen.return_value = proc
        mock_select.return_value = ([proc.stdout], [], [])

        mgr = BackendManager(_write_config(tmp_path))
        tools1 = mgr.list_tools("serena")
        tools2 = mgr.list_tools("serena")
        assert tools1 is tools2  # Same cached list

    def test_list_tools_unknown_backend(self, tmp_path):
        mgr = BackendManager(_write_config(tmp_path))
        with pytest.raises(BackendNotFoundError):
            mgr.list_tools("nonexistent")


# --- reconnect_if_needed ---


class TestReconnectIfNeeded:
    def test_unknown_backend_returns_false(self, tmp_path):
        mgr = BackendManager(_write_config(tmp_path))
        assert mgr.reconnect_if_needed("nonexistent") is False

    def test_never_connected_backend_skips_spawn(self, tmp_path):
        """Backend in configs but never connected should not be eagerly spawned."""
        mgr = BackendManager(_write_config(tmp_path))
        assert "serena" not in mgr._connections
        result = mgr.reconnect_if_needed("serena")
        assert result is True
        assert "serena" not in mgr._connections  # still not spawned

    @patch("lib.backends.select.select")
    @patch("lib.backends.subprocess.Popen")
    def test_alive_connection_returns_true_without_respawn(
        self, mock_popen, mock_select, tmp_path
    ):
        proc = _make_mock_proc([_handshake_response()])
        mock_popen.return_value = proc
        mock_select.return_value = ([proc.stdout], [], [])

        mgr = BackendManager(_write_config(tmp_path))
        # proc.poll() returns None (alive) — _get_connection returns early before Popen
        mgr._connections["serena"] = proc  # inject live connection

        result = mgr.reconnect_if_needed("serena")

        assert result is True
        assert mock_popen.call_count == 0  # no new spawn needed

    @patch("lib.backends.select.select")
    @patch("lib.backends.subprocess.Popen")
    def test_dead_connection_clears_cache_and_reconnects(
        self, mock_popen, mock_select, tmp_path
    ):
        dead_proc = MagicMock()
        dead_proc.poll.return_value = 1  # process has exited

        tools_response = {
            "jsonrpc": "2.0", "id": "x",
            "result": {"tools": [{"name": "t1"}]},
        }
        live_proc = _make_mock_proc([_handshake_response(), tools_response])
        mock_popen.return_value = live_proc
        mock_select.return_value = ([live_proc.stdout], [], [])

        mgr = BackendManager(_write_config(tmp_path))
        mgr._connections["serena"] = dead_proc
        mgr._tools_cache["serena"] = [{"name": "stale"}]

        result = mgr.reconnect_if_needed("serena")

        assert result is True
        assert "serena" not in mgr._tools_cache  # cache cleared
        assert mgr._connections["serena"] is live_proc  # new connection stored

    @patch("lib.backends.subprocess.Popen")
    def test_reconnect_failure_returns_false(self, mock_popen, tmp_path):
        dead_proc = MagicMock()
        dead_proc.poll.return_value = 1  # process has exited

        mock_popen.side_effect = FileNotFoundError("uvx not found")

        mgr = BackendManager(_write_config(tmp_path))
        mgr._connections["serena"] = dead_proc

        result = mgr.reconnect_if_needed("serena")

        assert result is False


# --- Connection management ---


class TestConnectionManagement:
    @patch("lib.backends.subprocess.Popen")
    def test_spawn_failure(self, mock_popen, tmp_path):
        mock_popen.side_effect = FileNotFoundError("uvx not found")
        mgr = BackendManager(_write_config(tmp_path))
        with pytest.raises(BackendConnectionError, match="Failed to spawn"):
            mgr.dispatch("serena", "tool", {})

    @patch("lib.backends.select.select")
    @patch("lib.backends.subprocess.Popen")
    def test_handshake_timeout(self, mock_popen, mock_select, tmp_path):
        proc = MagicMock()
        proc.poll.return_value = None
        proc.stdin = MagicMock()
        proc.kill = MagicMock()
        mock_popen.return_value = proc
        mock_select.return_value = ([], [], [])  # select timeout

        mgr = BackendManager(_write_config(tmp_path))
        with pytest.raises(BackendConnectionError, match="handshake timed out"):
            mgr.dispatch("serena", "tool", {})

    @patch("lib.backends.select.select")
    @patch("lib.backends.subprocess.Popen")
    def test_reuses_live_connection(self, mock_popen, mock_select, tmp_path):
        resp1 = {
            "jsonrpc": "2.0",
            "id": "1",
            "result": {"content": [{"type": "text", "text": "a"}]},
        }
        resp2 = {
            "jsonrpc": "2.0",
            "id": "2",
            "result": {"content": [{"type": "text", "text": "b"}]},
        }
        proc = _make_mock_proc([_handshake_response(), resp1, resp2])
        mock_popen.return_value = proc
        mock_select.return_value = ([proc.stdout], [], [])

        mgr = BackendManager(_write_config(tmp_path))
        mgr.dispatch("serena", "t1", {})
        mgr.dispatch("serena", "t2", {})

        # Popen called only once (connection reused)
        assert mock_popen.call_count == 1


# --- Shutdown ---


class TestShutdown:
    @patch("lib.backends.select.select")
    @patch("lib.backends.subprocess.Popen")
    def test_shutdown_all(self, mock_popen, mock_select, tmp_path):
        proc = _make_mock_proc([_handshake_response()])
        mock_popen.return_value = proc
        mock_select.return_value = ([proc.stdout], [], [])

        mgr = BackendManager(_write_config(tmp_path))
        # Force a connection to be created
        mgr._connections["serena"] = proc

        mgr.shutdown_all()
        proc.terminate.assert_called_once()
        assert "serena" not in mgr._connections
