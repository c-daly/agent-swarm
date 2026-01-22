#!/usr/bin/env python3
"""
Routing Service - Handles server registration and request routing.

Extracted from MCPRouter to provide clean separation of concerns.
Handles only routing logic - no summarization or telemetry.

Usage:
    from lib.routing_service import RoutingService
    
    service = RoutingService()
    service.register_server("backend", ["python", "-m", "backend"])
    response = service.route("backend", "tool_name", {"arg": "value"})
"""

import json
import subprocess
import select
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock, RLock
from typing import Optional


@dataclass
class ServerConfig:
    """Configuration for a registered MCP server."""
    name: str
    command: list[str]
    args: dict = field(default_factory=dict)
    tool_prefix: str = ""
    registered_at: str = ""

    def __post_init__(self):
        if not self.registered_at:
            self.registered_at = datetime.now(timezone.utc).isoformat()


class RoutingService:
    """Service for routing MCP requests to registered backend servers.
    
    Handles:
    - Server registration/unregistration
    - Connection management (spawn on first use, reuse thereafter)
    - Request forwarding with MCP protocol
    - Workflow state caching (survives backend respawns)
    - Thread-safe per-backend access
    """

    def __init__(self):
        """Initialize routing service."""
        self._lock = Lock()
        self._servers: dict[str, ServerConfig] = {}
        self._connections: dict[str, subprocess.Popen] = {}  # Live backend processes
        self._backend_locks: dict[str, RLock] = {}  # Per-backend locks
        
        # Shadow cache for workflow state (survives backend respawns)
        self._workflow_state_cache: dict[str, dict] = {}

    # === Registration API ===

    def register_server(
        self,
        name: str,
        command: list[str],
        args: Optional[dict] = None,
        tool_prefix: str = ""
    ) -> dict:
        """Register an MCP server for routing.

        Args:
            name: Unique server identifier
            command: Subprocess command to spawn server
            args: Optional initialization arguments
            tool_prefix: Prefix for tool names from this server

        Returns:
            Registration confirmation dict
        """
        with self._lock:
            config = ServerConfig(
                name=name,
                command=command,
                args=args or {},
                tool_prefix=tool_prefix
            )
            self._servers[name] = config

            return {
                "status": "registered",
                "name": name,
                "tool_prefix": tool_prefix,
                "registered_at": config.registered_at
            }

    def unregister_server(self, name: str) -> dict:
        """Remove a registered server.

        Args:
            name: Server identifier to remove

        Returns:
            Confirmation dict
        """
        with self._lock:
            existed = self._servers.pop(name, None) is not None
            # Kill connection if exists
            proc = self._connections.pop(name, None)
            if proc:
                proc.terminate()
            return {
                "status": "unregistered" if existed else "not_found",
                "name": name
            }

    def list_servers(self) -> list[dict]:
        """List all registered servers.

        Returns:
            List of server info dicts
        """
        with self._lock:
            return [
                {
                    "name": s.name,
                    "command": s.command,
                    "tool_prefix": s.tool_prefix,
                    "registered_at": s.registered_at
                }
                for s in self._servers.values()
            ]

    def shutdown(self) -> None:
        """Shutdown all backend connections."""
        with self._lock:
            for _, proc in list(self._connections.items()):
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
            self._connections.clear()

    # === Routing ===

    def route(
        self,
        destination: str,
        tool_name: str,
        args: dict
    ) -> dict:
        """Route a tool request to target server.

        Args:
            destination: Target server name
            tool_name: Tool to invoke
            args: Tool arguments

        Returns:
            Response dict from target server (with 'error' key if failed)
        """
        # Get target server
        with self._lock:
            server = self._servers.get(destination)

        if not server:
            return {"error": f"Server '{destination}' not registered"}

        # Forward request
        return self._forward_to_server(server, tool_name, args)

    # === Connection Management ===

    def _get_backend_lock(self, server_name: str) -> RLock:
        """Get or create reentrant lock for a backend server.
        
        Uses RLock to allow recursive calls (e.g., _restore_workflow_state
        calling _forward_to_server while lock is held).
        """
        with self._lock:
            if server_name not in self._backend_locks:
                self._backend_locks[server_name] = RLock()
            return self._backend_locks[server_name]

    def _get_connection(self, server: ServerConfig) -> subprocess.Popen:
        """Get existing connection or spawn new one with handshake.

        Args:
            server: Target server config

        Returns:
            Live subprocess connection

        Raises:
            RuntimeError: If connection cannot be established
        """
        # Return existing connection if we have one
        if server.name in self._connections:
            return self._connections[server.name]

        # Spawn new process
        proc = subprocess.Popen(
            server.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1  # Line buffered
        )

        def send(msg: dict) -> None:
            """Send JSON-RPC message to server."""
            line = json.dumps(msg) + "\n"
            proc.stdin.write(line)  # type: ignore[union-attr]
            proc.stdin.flush()  # type: ignore[union-attr]

        def receive() -> dict:
            """Receive JSON-RPC response from server."""
            line = proc.stdout.readline()  # type: ignore[union-attr]
            if not line:
                raise RuntimeError("Server closed connection")
            return json.loads(line.strip())

        # MCP handshake
        try:
            send({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "mcp-router",
                        "version": "1.0.0"
                    }
                }
            })

            init_response = receive()
            if "error" in init_response:
                proc.kill()
                raise RuntimeError(f"Initialize failed: {init_response['error']}")

            send({
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            })
        except Exception as e:
            proc.kill()
            raise RuntimeError(f"Handshake failed: {e}")

        # Store connection
        self._connections[server.name] = proc
        return proc

    def _forward_to_server(
        self,
        server: ServerConfig,
        tool_name: str,
        args: dict,
        _is_restore: bool = False,
        _is_retry: bool = False
    ) -> dict:
        """Forward request to target MCP server.

        Uses persistent connection (spawns on first use, reuses thereafter).
        Per-backend lock ensures safe concurrent access.

        Args:
            server: Target server config
            tool_name: Tool to invoke
            args: Tool arguments
            _is_restore: Internal flag to prevent infinite recursion during state restore
            _is_retry: Internal flag to prevent infinite recursion on connection failure

        Returns:
            Response dict from target server
        """
        backend_lock = self._get_backend_lock(server.name)

        with backend_lock:
            try:
                # Check if this is a fresh connection (for state restoration)
                is_new_connection = server.name not in self._connections
                proc = self._get_connection(server)

                # Restore cached state if this is a fresh workflow backend
                if is_new_connection and server.name == "workflow" and not _is_restore:
                    self._restore_workflow_state(server.name)

                # Build request with UUID to avoid collisions in high-concurrency
                request_id = str(uuid.uuid4())

                if tool_name == "__list__":
                    # Special: get tool list
                    request = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/list",
                        "params": {}
                    }
                else:
                    # Normal tool call
                    request = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {
                            "name": tool_name,
                            "arguments": args
                        }
                    }

                line = json.dumps(request) + "\n"
                proc.stdin.write(line)  # type: ignore[union-attr]
                proc.stdin.flush()  # type: ignore[union-attr]

                # Receive response with timeout to prevent indefinite blocking
                ready, _, _ = select.select([proc.stdout], [], [], 30.0)
                if not ready:
                    # Timeout - backend not responding, clean up connection
                    self._connections.pop(server.name, None)
                    return {"error": {"code": -32603, "message": f"Timeout waiting for {server.name}"}}

                response_line = proc.stdout.readline()  # type: ignore[union-attr]
                if not response_line:
                    # Connection died, remove and retry once (if not already retrying)
                    self._connections.pop(server.name, None)
                    if _is_retry:
                        return {"error": {"code": -32603, "message": f"Connection to {server.name} failed after retry"}}
                    return self._forward_to_server(server, tool_name, args, _is_restore=_is_restore, _is_retry=True)

                response = json.loads(response_line.strip())

                # Cache workflow state on successful operations
                if server.name == "workflow" and "error" not in response and not _is_restore:
                    self._cache_workflow_state(tool_name, args, response)

                return response

            except json.JSONDecodeError as e:
                self._connections.pop(server.name, None)
                return {"error": f"Invalid JSON response: {e}"}
            except Exception as e:
                self._connections.pop(server.name, None)
                return {"error": str(e)}

    # === Workflow State Caching ===

    def _cache_workflow_state(self, tool_name: str, args: dict, response: dict) -> None:
        """Cache workflow state from set/update/start operations."""
        if tool_name == "workflow_set_state":
            workflow_id = args.get("workflow_id")
            state = args.get("state")
            if workflow_id and state:
                self._workflow_state_cache[workflow_id] = state
        elif tool_name == "workflow_start":
            workflow_id = args.get("workflow_id")
            state = args.get("initial_state")
            if workflow_id and state:
                self._workflow_state_cache[workflow_id] = state
        elif tool_name == "workflow_stop":
            workflow_id = args.get("workflow_id")
            if workflow_id:
                self._workflow_state_cache.pop(workflow_id, None)

    def _restore_workflow_state(self, server_name: str) -> None:
        """Restore cached workflow state to a freshly spawned backend."""
        if server_name != "workflow" or not self._workflow_state_cache:
            return
        # Restore each cached workflow
        server = self._servers.get(server_name)
        if not server:
            return
        for workflow_id, state in self._workflow_state_cache.items():
            try:
                self._forward_to_server(server, "workflow_set_state", {
                    "workflow_id": workflow_id,
                    "state": state
                }, _is_restore=True)
            except Exception:
                pass  # Best effort

    def clear_workflow_cache(self, workflow_id: str | None = None) -> dict:
        """Clear cached workflow state.
        
        Args:
            workflow_id: Specific workflow to clear, or None for all.
            
        Returns:
            Dict with cleared workflow IDs.
        """
        if workflow_id:
            existed = self._workflow_state_cache.pop(workflow_id, None) is not None
            return {"cleared": [workflow_id] if existed else [], "all": False}
        else:
            cleared = list(self._workflow_state_cache.keys())
            self._workflow_state_cache.clear()
            return {"cleared": cleared, "all": True}
