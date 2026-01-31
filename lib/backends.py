#!/usr/bin/env python3
"""External backend manager for the daemon.

Manages MCP server subprocesses (Serena, Context7, Playwright).
Lazy spawn on first use, per-backend locking for serialized access.
"""

from __future__ import annotations

import json
import logging
import os
import select
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lib.errors import (
    BackendConnectionError,
    BackendError,
    BackendNotFoundError,
    RequestTimeoutError,
)

log = logging.getLogger(__name__)

_MCP_VERSION = "2024-11-05"
_CLIENT_INFO = {"name": "agent-swarm", "version": "2.0.0"}
_DEFAULT_TIMEOUT = 30

# Backends handled directly by the Controller, not spawned as subprocesses
_INTERNAL_BACKENDS = {"native", "workflow"}


@dataclass
class BackendConfig:
    """Configuration for a single external backend."""

    name: str
    command: list[str]
    tool_prefix: str
    env: dict[str, str] = field(default_factory=dict)


class BackendManager:
    """Manages external MCP server subprocesses.

    Thread-safe: per-backend RLock for connection management.
    Access to each backend is serialized because MCP backends are
    single-threaded stdio servers.
    """

    def __init__(self, config_path: Path) -> None:
        """Load backends.json. Does NOT spawn any backends yet (lazy)."""
        self._configs: dict[str, BackendConfig] = {}
        self._connections: dict[str, subprocess.Popen] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._tools_cache: dict[str, list[dict]] = {}

        if config_path.exists():
            with open(config_path) as f:
                raw = json.load(f)
            for name, cfg in raw.items():
                if name in _INTERNAL_BACKENDS:
                    continue
                self._configs[name] = BackendConfig(
                    name=name,
                    command=cfg["command"],
                    tool_prefix=cfg.get("tool_prefix", name),
                    env=cfg.get("env", {}),
                )
                self._locks[name] = threading.RLock()

    def dispatch(self, backend: str, tool_name: str, args: dict) -> Any:
        """Send a tool call to a backend and return the response.

        Raises:
            BackendNotFoundError: Backend not in configs.
            RequestTimeoutError: No response within timeout.
            BackendConnectionError: Backend process died.
        """
        if backend not in self._configs:
            raise BackendNotFoundError(f"Backend not found: {backend}")

        with self._locks[backend]:
            return self._dispatch_locked(backend, tool_name, args)

    def list_tools(self, backend: str) -> list[dict]:
        """Get tool list from a backend. Cached after first call."""
        if backend not in self._configs:
            raise BackendNotFoundError(f"Backend not found: {backend}")

        if backend in self._tools_cache:
            return self._tools_cache[backend]

        with self._locks[backend]:
            conn = self._get_connection(backend)
            request = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tools/list",
                "params": {},
            }
            result = self._send_and_receive(conn, request, backend)
            tools = result.get("tools", [])
            self._tools_cache[backend] = tools
            return tools

    def list(self) -> list[str]:
        """Return list of registered backend names."""
        return list(self._configs.keys())

    def shutdown_all(self) -> None:
        """Kill all backend subprocesses."""
        for name in list(self._connections.keys()):
            lock = self._locks.get(name)
            if lock:
                with lock:
                    self._kill_connection(name)

    # --- Internal ---

    def _dispatch_locked(
        self, backend: str, tool_name: str, args: dict, *, retry: bool = True
    ) -> Any:
        """Internal dispatch. Must hold backend lock."""
        try:
            conn = self._get_connection(backend)
            request = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": args},
            }
            return self._send_and_receive(conn, request, backend)
        except (BrokenPipeError, OSError, BackendConnectionError) as e:
            self._kill_connection(backend)
            if retry:
                log.warning("Backend %s failed, retrying: %s", backend, e)
                return self._dispatch_locked(backend, tool_name, args, retry=False)
            raise BackendConnectionError(
                f"Backend {backend} connection failed after retry: {e}"
            )

    def _send_and_receive(
        self, conn: subprocess.Popen, request: dict, backend: str
    ) -> Any:
        """Send JSON-RPC request and read response. Must hold backend lock."""
        line = json.dumps(request) + "\n"
        conn.stdin.write(line)
        conn.stdin.flush()

        ready, _, _ = select.select([conn.stdout], [], [], _DEFAULT_TIMEOUT)
        if not ready:
            self._kill_connection(backend)
            raise RequestTimeoutError(
                f"Backend {backend} timed out after {_DEFAULT_TIMEOUT}s"
            )

        response_line = conn.stdout.readline()
        if not response_line:
            raise BackendConnectionError(f"Backend {backend} closed connection")

        response = json.loads(response_line)

        if "error" in response:
            err = response["error"]
            raise BackendError(
                f"Backend {backend} error: {err.get('message', str(err))}"
            )

        return response.get("result", {})

    def _get_connection(self, backend: str) -> subprocess.Popen:
        """Get or create a connection. Must hold backend lock."""
        conn = self._connections.get(backend)
        if conn is not None and conn.poll() is None:
            return conn

        config = self._configs[backend]
        env = {**os.environ, **config.env} if config.env else None

        try:
            proc = subprocess.Popen(
                config.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
            )
        except (FileNotFoundError, OSError) as e:
            raise BackendConnectionError(f"Failed to spawn {backend}: {e}")

        # MCP handshake
        try:
            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": _MCP_VERSION,
                    "capabilities": {},
                    "clientInfo": _CLIENT_INFO,
                },
            }
            proc.stdin.write(json.dumps(init_request) + "\n")
            proc.stdin.flush()

            ready, _, _ = select.select([proc.stdout], [], [], _DEFAULT_TIMEOUT)
            if not ready:
                proc.kill()
                raise BackendConnectionError(
                    f"Backend {backend} handshake timed out"
                )

            response_line = proc.stdout.readline()
            if not response_line:
                proc.kill()
                raise BackendConnectionError(
                    f"Backend {backend} closed during handshake"
                )

            response = json.loads(response_line)
            if "error" in response:
                proc.kill()
                raise BackendConnectionError(
                    f"Backend {backend} handshake error: {response['error']}"
                )

            # Send initialized notification
            notification = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }
            proc.stdin.write(json.dumps(notification) + "\n")
            proc.stdin.flush()

        except (BrokenPipeError, OSError, json.JSONDecodeError) as e:
            proc.kill()
            raise BackendConnectionError(
                f"Backend {backend} handshake failed: {e}"
            )

        self._connections[backend] = proc
        log.info("Connected to backend: %s (pid=%d)", backend, proc.pid)
        return proc

    def _kill_connection(self, backend: str) -> None:
        """Terminate a backend subprocess. Must hold backend lock."""
        proc = self._connections.pop(backend, None)
        self._tools_cache.pop(backend, None)
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass
        log.info("Disconnected backend: %s", backend)
