#!/usr/bin/env python3
"""Thin JSON-RPC client for the agent-swarm daemon.

One instance per consumer. NOT thread-safe — each thread that needs
daemon access should create its own instance.

Connection is persistent for the lifetime of the client. The daemon
tracks agent identity per connection, so a single client instance
represents a single agent.
"""

import json
import socket
from typing import Any, Optional


DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = 7523
RECV_BUFFER = 8192
DEFAULT_TIMEOUT = 30.0
MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB — matches daemon MAX_MESSAGE_SIZE


class DaemonError(Exception):
    """Error returned by the daemon.

    Attributes:
        code: JSON-RPC error code
        message: Human-readable error message
        data: Optional additional error data
    """

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"Daemon error {code}: {message}")


class DaemonClient:
    """Thin JSON-RPC client for the agent-swarm daemon."""

    def __init__(self, host: str = DAEMON_HOST, port: int = DAEMON_PORT,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._request_id: int = 0
        self._registered: bool = False
        self._buf: bytes = b""

    def connect(self) -> None:
        """Connect to daemon and perform MCP handshake."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self._timeout)
        self._sock.connect((self._host, self._port))
        self._buf = b""
        self._request_id = 0
        self._registered = False

        # MCP initialize handshake
        self._request_id += 1
        init_req = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "daemon-client", "version": "1.0"},
            },
        }
        self._sock.sendall(json.dumps(init_req).encode() + b"\n")
        resp_bytes = self._read_response()
        resp = json.loads(resp_bytes.decode())
        if "error" in resp:
            raise ConnectionError(
                f"MCP handshake failed: {resp['error'].get('message', 'unknown')}"
            )

        # Send initialized notification
        notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self._sock.sendall(json.dumps(notif).encode() + b"\n")

    def close(self) -> None:
        """Close connection to daemon."""
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        self._buf = b""

    def register(self, agent_id: str, agent_type: str,
                 session_id: str, workflow_id: str) -> dict:
        """Register this connection's agent identity with the daemon."""
        if self._registered:
            raise RuntimeError("Already registered")
        result = self._call("agent/register", {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "session_id": session_id,
            "workflow_id": workflow_id,
        })
        self._registered = True
        return result

    def call_tool(self, name: str, arguments: dict) -> Any:
        """Call a tool through the daemon."""
        return self._call("tools/call", {
            "name": name,
            "arguments": arguments,
        })

    def list_tools(self) -> list[dict]:
        """List tools available to this agent."""
        result = self._call("tools/list", {})
        return result.get("tools", [])

    def workflow_start(self, workflow_id: str, initial_state: dict) -> dict:
        """Start a named workflow."""
        return self._call("workflow/start", {
            "workflow_id": workflow_id,
            "initial_state": initial_state,
        })

    def workflow_stop(self, workflow_id: str) -> dict:
        """Stop a workflow and clear its state."""
        return self._call("workflow/stop", {"workflow_id": workflow_id})

    def workflow_get_state(self, workflow_id: str) -> dict:
        """Get full workflow state."""
        return self._call("workflow/get_state", {"workflow_id": workflow_id})

    def workflow_get_value(self, workflow_id: str, key: str) -> Any:
        """Get a single value from workflow state."""
        return self._call("workflow/get_value", {
            "workflow_id": workflow_id,
            "key": key,
        })

    def workflow_set_value(self, workflow_id: str, key: str, value: Any) -> dict:
        """Set a single value in workflow state (protected keys rejected)."""
        return self._call("workflow/set_value", {
            "workflow_id": workflow_id,
            "key": key,
            "value": value,
        })

    def workflow_is_active(self, workflow_id: str) -> bool:
        """Check if a workflow is currently active. Returns False on error."""
        try:
            result = self._call("workflow/is_active", {
                "workflow_id": workflow_id,
            })
            return bool(result)
        except (DaemonError, ConnectionError):
            return False

    def workflow_advance_phase(self, workflow_id: str,
                               target_phase: str) -> dict:
        """Request a phase transition in a workflow."""
        return self._call("workflow/advance_phase", {
            "workflow_id": workflow_id,
            "target_phase": target_phase,
        })

    def workflow_pass_checkpoint(self, workflow_id: str) -> dict:
        """Mark the current phase's checkpoint as passed."""
        return self._call("workflow/pass_checkpoint", {
            "workflow_id": workflow_id,
        })

    def agent_get_state(self, agent_id: str) -> Optional[dict]:
        """Get an agent's state."""
        try:
            return self._call("agent/get_state", {"agent_id": agent_id})
        except DaemonError:
            return None

    def agent_set_state(self, agent_id: str, state: dict) -> dict:
        """Set an agent's state."""
        return self._call("agent/set_state", {
            "agent_id": agent_id,
            "state": state,
        })

    def agent_delete(self, agent_id: str) -> dict:
        """Delete an agent's state."""
        return self._call("agent/delete", {"agent_id": agent_id})

    def agent_list(self) -> list[str]:
        """List all registered agent IDs."""
        result = self._call("agent/list", {})
        if isinstance(result, list):
            return result
        return []

    # ─────────────────────────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────────────────────────

    def _call(self, method: str, params: dict) -> Any:
        """Send JSON-RPC request, block for response, return result."""
        if self._sock is None:
            raise ConnectionError("Not connected")
        if not self._registered and method not in ("agent/register", "tools/list"):
            raise RuntimeError("Must call register() before other methods")

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        payload = json.dumps(request).encode() + b"\n"
        self._sock.sendall(payload)

        raw = self._read_response()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ConnectionError(
                "Invalid UTF-8 from daemon — possible protocol desynchronization"
            )
        try:
            response = json.loads(text)
        except json.JSONDecodeError:
            raise ConnectionError(
                "Invalid JSON from daemon — possible protocol desynchronization"
            )

        if response.get("id") != self._request_id:
            raise ConnectionError(
                f"Response ID mismatch: expected {self._request_id}, "
                f"got {response.get('id')}"
            )

        if "error" in response:
            err = response["error"]
            raise DaemonError(
                code=err.get("code", -32603),
                message=err.get("message", "Unknown error"),
                data=err.get("data"),
            )

        return response.get("result")

    def _read_response(self) -> bytes:
        """Read exactly one newline-delimited response from the socket."""
        while b"\n" not in self._buf:
            if len(self._buf) > MAX_RESPONSE_SIZE:
                raise ConnectionError(
                    f"Response exceeds {MAX_RESPONSE_SIZE} bytes — "
                    "possible protocol desynchronization"
                )
            chunk = self._sock.recv(RECV_BUFFER)
            if not chunk:
                raise ConnectionError("Daemon closed connection")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line

    def __enter__(self) -> "DaemonClient":
        self.connect()
        return self

    def __exit__(self, *args) -> None:
        self.close()
