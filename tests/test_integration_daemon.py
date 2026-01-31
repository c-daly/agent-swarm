#!/usr/bin/env python3
"""End-to-end integration test for the daemon.

Starts a real daemon process, connects via TCP, performs MCP handshake,
calls tools, verifies results and SQLite recording, then shuts down.
Exercises all 10 modules together.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import threading
import time
from pathlib import Path

import pytest


def _send_rpc(sock: socket.socket, method: str, params: dict | None = None, msg_id: int = 1) -> dict:
    """Send a JSON-RPC request and return the parsed response."""
    request = {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": method,
    }
    if params is not None:
        request["params"] = params

    data = json.dumps(request) + "\n"
    sock.sendall(data.encode("utf-8"))

    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(8192)
        if not chunk:
            break
        buf += chunk

    line = buf.split(b"\n", 1)[0]
    return json.loads(line)


def _send_notification(sock: socket.socket, method: str) -> None:
    """Send a JSON-RPC notification (no id, no response expected)."""
    notif = {"jsonrpc": "2.0", "method": method}
    sock.sendall((json.dumps(notif) + "\n").encode("utf-8"))


@pytest.fixture()
def daemon_env(tmp_path):
    """Set up a daemon with temp directories, start it, yield connection info, shut down."""
    import lib.daemon as daemon_mod
    from lib.controller import Controller
    from lib.router import Router

    # Create minimal config
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "backends.json").write_text("{}")
    (config_dir / "permissions.yaml").write_text(
        "global:\n  allowed: ['*']\n  blocked: []\n  superblocked: []\n"
    )

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Use a random high port
    port = 19900

    # Create real controller and router
    controller = Controller(config_dir=config_dir, data_dir=data_dir)
    router = Router(port=port, controller=controller)

    # Start router in background thread
    server_thread = threading.Thread(target=router.serve_forever, daemon=True)
    server_thread.start()

    # Wait for server to be ready
    for _ in range(20):
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.settimeout(0.5)
            probe.connect(("127.0.0.1", port))
            probe.close()
            break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    else:
        pytest.fail("Daemon did not start")

    yield {
        "port": port,
        "router": router,
        "controller": controller,
        "data_dir": data_dir,
        "config_dir": config_dir,
    }

    # Cleanup
    router.shutdown()
    server_thread.join(timeout=3)


class TestFullStack:
    """End-to-end tests exercising the full daemon stack."""

    def _connect(self, port: int) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(("127.0.0.1", port))
        return sock

    def test_mcp_handshake(self, daemon_env):
        """MCP initialize → notifications/initialized → tools/list works."""
        sock = self._connect(daemon_env["port"])
        try:
            # Initialize
            resp = _send_rpc(sock, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            })
            assert resp["result"]["protocolVersion"] == "2024-11-05"
            assert "tools" in resp["result"]["capabilities"]

            # Notification (no response)
            _send_notification(sock, "notifications/initialized")

            # Tools list
            resp = _send_rpc(sock, "tools/list", msg_id=2)
            tools = resp["result"]["tools"]
            tool_names = [t["name"] for t in tools]
            assert "native__read_file" in tool_names
            assert "router__ping" in tool_names
            assert "workflow__workflow_start" in tool_names
        finally:
            sock.close()

    def test_ping(self, daemon_env):
        """router__ping returns ok."""
        sock = self._connect(daemon_env["port"])
        try:
            _send_rpc(sock, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            })

            resp = _send_rpc(sock, "tools/call", {
                "name": "router__ping",
                "arguments": {},
            }, msg_id=2)
            result = json.loads(resp["result"]["content"][0]["text"])
            assert result["status"] == "ok"
        finally:
            sock.close()

    def test_native_read_file(self, daemon_env):
        """Native read_file works end-to-end."""
        # Create a test file
        test_file = daemon_env["data_dir"] / "test.txt"
        test_file.write_text("hello world\nsecond line\n")

        sock = self._connect(daemon_env["port"])
        try:
            _send_rpc(sock, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            })

            resp = _send_rpc(sock, "tools/call", {
                "name": "native__read_file",
                "arguments": {"file_path": str(test_file)},
            }, msg_id=2)
            result = json.loads(resp["result"]["content"][0]["text"])
            assert "hello world" in result["content"]
            assert result["line_count"] == 2
        finally:
            sock.close()

    def test_workflow_state_lifecycle(self, daemon_env):
        """Start workflow → set value → get value → stop workflow."""
        sock = self._connect(daemon_env["port"])
        try:
            _send_rpc(sock, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            })

            # Start workflow
            resp = _send_rpc(sock, "tools/call", {
                "name": "workflow__workflow_start",
                "arguments": {"workflow_id": "test-wf", "initial_state": {"phase": "init"}},
            }, msg_id=2)
            result = json.loads(resp["result"]["content"][0]["text"])
            assert result["phase"] == "init"

            # Set value
            resp = _send_rpc(sock, "tools/call", {
                "name": "workflow__workflow_set_value",
                "arguments": {"workflow_id": "test-wf", "key": "count", "value": 42},
            }, msg_id=3)
            result = json.loads(resp["result"]["content"][0]["text"])
            assert result is True

            # Get value
            resp = _send_rpc(sock, "tools/call", {
                "name": "workflow__workflow_get_value",
                "arguments": {"workflow_id": "test-wf", "key": "count"},
            }, msg_id=4)
            result = json.loads(resp["result"]["content"][0]["text"])
            assert result == 42

            # Stop workflow
            resp = _send_rpc(sock, "tools/call", {
                "name": "workflow__workflow_stop",
                "arguments": {"workflow_id": "test-wf"},
            }, msg_id=5)
            result = json.loads(resp["result"]["content"][0]["text"])
            assert result is True
        finally:
            sock.close()

    def test_events_recorded_in_sqlite(self, daemon_env):
        """Tool calls are recorded in the SQLite datastore."""
        sock = self._connect(daemon_env["port"])
        try:
            _send_rpc(sock, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            })

            # Make a few calls
            _send_rpc(sock, "tools/call", {
                "name": "router__ping",
                "arguments": {},
            }, msg_id=2)
            _send_rpc(sock, "tools/call", {
                "name": "router__ping",
                "arguments": {},
            }, msg_id=3)
        finally:
            sock.close()

        # Check SQLite directly
        db_path = daemon_env["data_dir"] / "datastore.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT tool, status FROM events WHERE tool = 'router__ping'"
        )
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) >= 2
        assert all(row[1] == "success" for row in rows)

    def test_multiple_clients(self, daemon_env):
        """Multiple clients can connect and make calls concurrently."""
        results = [None, None]

        def client_call(idx):
            sock = self._connect(daemon_env["port"])
            try:
                _send_rpc(sock, "initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": f"client-{idx}", "version": "1.0"},
                })
                resp = _send_rpc(sock, "tools/call", {
                    "name": "router__ping",
                    "arguments": {},
                }, msg_id=2)
                result = json.loads(resp["result"]["content"][0]["text"])
                results[idx] = result["status"]
            finally:
                sock.close()

        t0 = threading.Thread(target=client_call, args=(0,))
        t1 = threading.Thread(target=client_call, args=(1,))
        t0.start()
        t1.start()
        t0.join(timeout=5)
        t1.join(timeout=5)

        assert results[0] == "ok"
        assert results[1] == "ok"

    def test_daemon_shutdown_via_rpc(self, daemon_env):
        """daemon/shutdown RPC triggers graceful shutdown."""
        sock = self._connect(daemon_env["port"])
        try:
            resp = _send_rpc(sock, "daemon/shutdown")
            assert resp["result"]["status"] == "shutting_down"
        finally:
            sock.close()

        # Poll until daemon stops accepting connections (accept loop has 1s timeout)
        stopped = False
        for _ in range(20):
            time.sleep(0.2)
            try:
                probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                probe.settimeout(0.5)
                probe.connect(("127.0.0.1", daemon_env["port"]))
                probe.close()
            except (ConnectionRefusedError, OSError):
                stopped = True
                break
        assert stopped, "Daemon still accepting connections after shutdown"
