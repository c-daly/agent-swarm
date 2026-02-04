#!/usr/bin/env python3
"""TCP server + MCP/JSON-RPC protocol for the daemon.

Accepts connections, dispatches to Controller, formats responses.
Thread-per-connection model with connection limit.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from typing import TYPE_CHECKING, Any

from lib.errors import PermissionDeniedError, RouterError

if TYPE_CHECKING:
    from lib.controller import Controller

log = logging.getLogger(__name__)

MAX_CONNECTIONS = 64
MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB
CONNECTION_TIMEOUT = 60.0

_MCP_VERSION = "2024-11-05"
_SERVER_INFO = {"name": "agent-swarm", "version": "2.0.0"}


class Router:
    """TCP server that accepts MCP and internal JSON-RPC connections."""

    def __init__(self, port: int, controller: Controller) -> None:
        self._port = port
        self._controller = controller
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._running = False
        self._tools_cache: list[dict] | None = None
        self._active_connections = 0
        self._connections_lock = threading.Lock()

    def serve_forever(self) -> None:
        """Bind, listen, accept connections in a loop."""
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", self._port))
        self._server.listen(32)
        self._server.settimeout(1.0)  # Allow periodic check of _running
        self._running = True
        log.info("Router listening on 127.0.0.1:%d", self._port)

        while self._running:
            try:
                client, addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            with self._connections_lock:
                if self._active_connections >= MAX_CONNECTIONS:
                    self._send_error(client, None, -32603, "Too many connections")
                    client.close()
                    continue
                self._active_connections += 1

            try:
                threading.Thread(
                    target=self._handle_connection,
                    args=(client,),
                    daemon=True,
                ).start()
            except Exception:
                with self._connections_lock:
                    self._active_connections -= 1
                client.close()

    def shutdown(self) -> None:
        """Graceful shutdown."""
        self._running = False
        try:
            self._server.close()
        except OSError:
            pass
        self._controller.shutdown()

    def invalidate_tools_cache(self) -> None:
        """Reset tools cache."""
        self._tools_cache = None

    # --- Connection handling ---

    def _handle_connection(self, client: socket.socket) -> None:
        """Handle a single client connection."""
        client.settimeout(CONNECTION_TIMEOUT)
        buf = b""
        try:
            while self._running:
                try:
                    data = client.recv(4096)
                except socket.timeout:
                    break
                if not data:
                    break

                buf += data
                if len(buf) > MAX_MESSAGE_SIZE:
                    self._send_error(client, None, -32600, "Message too large")
                    break

                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue

                    try:
                        message = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        self._send_error(client, None, -32700, "Parse error")
                        continue

                    if not isinstance(message, dict):
                        self._send_error(client, None, -32600, "Invalid request")
                        continue

                    if message.get("jsonrpc") != "2.0" or "method" not in message:
                        self._send_error(
                            client, message.get("id"), -32600, "Invalid request"
                        )
                        continue

                    response = self._dispatch(message)
                    if response is not None:
                        self._send_response(client, response)
        except Exception as e:
            log.warning("Connection error: %s", e)
        finally:
            try:
                client.close()
            except OSError:
                pass
            with self._connections_lock:
                self._active_connections -= 1

    # --- Dispatch ---

    def _dispatch(self, message: dict) -> dict | None:
        """Route a parsed JSON-RPC message."""
        method = message["method"]

        # JSON-RPC notifications have no id — must not send a response
        is_notification = "id" not in message

        if method == "initialize":
            return self._handle_initialize(message)
        if method == "notifications/initialized" or is_notification:
            return None  # No response for notifications
        if method == "tools/list":
            return self._handle_tools_list(message)
        if method == "tools/call":
            return self._handle_tools_call(message)
        if method == "daemon/shutdown":
            return self._handle_daemon_shutdown(message)

        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def _handle_initialize(self, message: dict) -> dict:
        """MCP handshake response."""
        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {
                "protocolVersion": _MCP_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": _SERVER_INFO,
            },
        }

    def _handle_tools_list(self, message: dict) -> dict:
        """Return all available tools."""
        if self._tools_cache is None:
            native = self._get_native_tool_schemas()
            try:
                backend = self._controller.list_backend_tools()
            except Exception as e:
                log.warning("Failed to list backend tools: %s", e)
                backend = []
            internal = self._get_internal_tool_schemas()
            self._tools_cache = native + backend + internal

        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {"tools": self._tools_cache},
        }

    def _handle_tools_call(self, message: dict) -> dict:
        """Route a tool call to the Controller."""
        msg_id = message.get("id")
        params = message.get("params", {})
        tool_name = params.get("name", "")
        args = params.get("arguments", {})

        try:
            result = self._controller.handle_call(tool_name, dict(args))
        except PermissionDeniedError as e:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(e.response.to_dict())}
                    ],
                    "isError": True,
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {"type": "text", "text": f"Internal error: {e}"}
                    ],
                    "isError": True,
                },
            }

        # Check if result is an error dict
        if isinstance(result, dict) and result.get("isError"):
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {"type": "text", "text": result.get("error", str(result))}
                    ],
                    "isError": True,
                },
            }

        try:
            result_text = json.dumps(result, default=str)
        except (TypeError, ValueError):
            result_text = str(result)

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": result_text}],
            },
        }

    def _handle_daemon_shutdown(self, message: dict) -> dict:
        """Handle daemon/shutdown: respond then shutdown after a brief delay."""
        log.info("Received daemon/shutdown request")
        threading.Thread(target=self._delayed_shutdown, daemon=True).start()
        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {"status": "shutting_down"},
        }

    def _delayed_shutdown(self) -> None:
        """Shutdown after a brief delay to allow the response to be sent."""
        time.sleep(0.1)
        self.shutdown()

    # --- Wire helpers ---

    @staticmethod
    def _send_response(client: socket.socket, response: dict) -> None:
        """Send a JSON-RPC response."""
        try:
            data = json.dumps(response) + "\n"
            client.sendall(data.encode("utf-8"))
        except (OSError, BrokenPipeError):
            pass

    @staticmethod
    def _send_error(
        client: socket.socket, msg_id: Any, code: int, message: str
    ) -> None:
        """Send a JSON-RPC error response."""
        response = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }
        try:
            data = json.dumps(response) + "\n"
            client.sendall(data.encode("utf-8"))
        except (OSError, BrokenPipeError):
            pass

    # --- Tool schemas ---

    @staticmethod
    def _get_native_tool_schemas() -> list[dict]:
        """MCP tool schemas for native operations."""
        return [
            {
                "name": "native__read_file",
                "description": "Read the contents of a file. Supports line offset and limit for large files.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "The absolute path to the file to read"},
                        "offset": {"type": "integer", "description": "Line offset to start reading from (0-indexed)"},
                        "limit": {"type": "integer", "description": "Maximum number of lines to read"},
                    },
                    "required": ["file_path"],
                },
            },
            {
                "name": "native__write_file",
                "description": "Write content to a file. Creates parent directories if needed. Overwrites existing files.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "The absolute path to the file to write"},
                        "content": {"type": "string", "description": "The content to write to the file"},
                    },
                    "required": ["file_path", "content"],
                },
            },
            {
                "name": "native__edit_file",
                "description": "Edit a file by replacing occurrences of a string. Can replace first or all occurrences.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "The absolute path to the file to edit"},
                        "old_string": {"type": "string", "description": "The string to find and replace"},
                        "new_string": {"type": "string", "description": "The replacement string"},
                        "replace_all": {"type": "boolean", "description": "Whether to replace all occurrences (default: false)"},
                    },
                    "required": ["file_path", "old_string", "new_string"],
                },
            },
            {
                "name": "native__glob",
                "description": "Find files matching a glob pattern. Returns matching file paths sorted by modification time.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "The glob pattern to match files against"},
                        "path": {"type": "string", "description": "The directory to search in (default: cwd)"},
                    },
                    "required": ["pattern"],
                },
            },
            {
                "name": "native__grep",
                "description": "Search for a pattern in files. Returns matching file paths or content lines.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "The regex pattern to search for"},
                        "path": {"type": "string", "description": "The directory or file to search in"},
                        "output_mode": {"type": "string", "enum": ["files", "content"], "description": "Output mode (default: files)"},
                        "case_insensitive": {"type": "boolean", "description": "Whether to ignore case when matching"},
                        "file_glob": {"type": "string", "description": "Filter files by glob pattern"},
                    },
                    "required": ["pattern"],
                },
            },
            {
                "name": "native__bash",
                "description": "Execute a shell command and return output. Supports timeout and working directory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The shell command to execute"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds (default: 120, max: 600)"},
                        "cwd": {"type": "string", "description": "Working directory for command execution"},
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "native__task",
                "description": "Spawn a subagent to execute a task. The router owns the full lifecycle: context injection, execution, and result processing.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "The task prompt for the subagent"},
                        "subagent_type": {"type": "string", "description": "Type of subagent (e.g., implementer, explorer, reviewer)"},
                        "model": {"type": "string", "description": "Optional model override (sonnet, opus, haiku)"},
                        "description": {"type": "string", "description": "Short description of the task (for logging)"},
                    },
                    "required": ["prompt", "subagent_type"],
                },
            },
        ]

    @staticmethod
    def _get_internal_tool_schemas() -> list[dict]:
        """MCP tool schemas for internal operations."""
        return [
            {"name": "router__ping", "description": "Health check.", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "router__list_tools", "description": "List all available tool names.", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "router__get_full", "description": "Retrieve full cached content by content_id.", "inputSchema": {"type": "object", "properties": {"content_id": {"type": "string"}}, "required": ["content_id"]}},
            {"name": "router__register_agent", "description": "Register an agent for permission tracking.", "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}, "agent_type": {"type": "string"}, "roles": {"type": "array", "items": {"type": "string"}}}, "required": ["agent_id", "agent_type"]}},
            {"name": "router__update_agent_phase", "description": "Update an agent's workflow phase.", "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}, "workflow": {"type": "string"}, "phase": {"type": "string"}}, "required": ["agent_id", "workflow", "phase"]}},
            {"name": "router__get_allowed_tools", "description": "Get tool patterns allowed for an agent type.", "inputSchema": {"type": "object", "properties": {"agent_type": {"type": "string"}}}},
            {"name": "workflow__workflow_start", "description": "Start a new workflow.", "inputSchema": {"type": "object", "properties": {"workflow_id": {"type": "string"}, "initial_state": {"type": "object"}}, "required": ["workflow_id"]}},
            {"name": "workflow__workflow_stop", "description": "Stop a running workflow.", "inputSchema": {"type": "object", "properties": {"workflow_id": {"type": "string"}}, "required": ["workflow_id"]}},
            {"name": "workflow__workflow_is_active", "description": "Check if a workflow is active.", "inputSchema": {"type": "object", "properties": {"workflow_id": {"type": "string"}}, "required": ["workflow_id"]}},
            {"name": "workflow__workflow_get_state", "description": "Get workflow state.", "inputSchema": {"type": "object", "properties": {"workflow_id": {"type": "string"}}, "required": ["workflow_id"]}},
            {"name": "workflow__workflow_get_value", "description": "Get a single value from workflow state.", "inputSchema": {"type": "object", "properties": {"workflow_id": {"type": "string"}, "key": {"type": "string"}}, "required": ["workflow_id", "key"]}},
            {"name": "workflow__workflow_set_value", "description": "Set a single value in workflow state.", "inputSchema": {"type": "object", "properties": {"workflow_id": {"type": "string"}, "key": {"type": "string"}, "value": {}}, "required": ["workflow_id", "key", "value"]}},
            {"name": "workflow__workflow_advance_phase", "description": "Advance workflow to a new phase.", "inputSchema": {"type": "object", "properties": {"workflow_id": {"type": "string"}, "target_phase": {"type": "string"}}, "required": ["workflow_id", "target_phase"]}},
            {"name": "workflow__workflow_pass_checkpoint", "description": "Mark the current phase checkpoint as passed.", "inputSchema": {"type": "object", "properties": {"workflow_id": {"type": "string"}}, "required": ["workflow_id"]}},
            {"name": "workflow__agent_get_state", "description": "Get agent state.", "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}}, "required": ["agent_id"]}},
            {"name": "workflow__agent_set_state", "description": "Set agent state.", "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}, "state": {"type": "object"}}, "required": ["agent_id", "state"]}},
            {"name": "workflow__agent_delete", "description": "Delete agent state.", "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}}, "required": ["agent_id"]}},
            {"name": "workflow__list_agents", "description": "List all agents with state.", "inputSchema": {"type": "object", "properties": {}}},
        ]
