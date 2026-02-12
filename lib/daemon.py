#!/usr/bin/env python3
"""Daemon entry point and lifecycle management.

Single long-lived process. Owns the Router, which owns the Controller,
which owns all services. Started once, stays alive across sessions.
"""

from __future__ import annotations

import fcntl
import json
import logging
import signal
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_PORT = 7523
_BASE_DIR = Path(__file__).parent.parent
LOG_DIR = _BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "daemon.log"
LOCK_FILE = _BASE_DIR / ".daemon.lock"
CONFIG_DIR = _BASE_DIR / "config"
DATA_DIR = _BASE_DIR / "data"


@dataclass(frozen=True)
class PhaseConfig:
    """Per-phase configuration loaded from YAML."""
    checkpoint: bool = False


@dataclass(frozen=True)
class WorkflowConfig:
    """Workflow configuration loaded from YAML."""
    initial_phase: str
    terminal_phase: str
    phases: dict[str, PhaseConfig] = field(default_factory=dict)
    transitions: dict[str, set[str]] = field(default_factory=dict)


def load_workflow_configs(config_dir: Path) -> dict[str, WorkflowConfig]:
    """Load workflow configs from config/workflows/*.yaml.

    Returns dict keyed by workflow name -> WorkflowConfig.
    """
    workflows_dir = config_dir / "workflows"
    if not workflows_dir.is_dir():
        return {}
    configs: dict[str, WorkflowConfig] = {}
    for path in sorted(workflows_dir.glob("*.yaml")):
        with open(path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict) or "name" not in data:
            continue
        name = data["name"]
        phases = {}
        for p in data.get("phases", []):
            phases[p["name"]] = PhaseConfig(checkpoint=p.get("checkpoint", False))
        transitions = {}
        for src, targets in data.get("transitions", {}).items():
            transitions[src] = set(targets) if isinstance(targets, list) else {targets}
        configs[name] = WorkflowConfig(
            initial_phase=data.get("initial_phase", ""),
            terminal_phase=data.get("terminal_phase", ""),
            phases=phases,
            transitions=transitions,
        )
    return configs


def main(port: int = DEFAULT_PORT) -> None:
    """Entry point. Called by bin/start-claude or directly.

    1. Ensure directories exist
    2. Acquire exclusive flock (singleton)
    3. Configure logging
    4. Create Controller and Router
    5. Register signal handlers
    6. Serve forever (blocks)
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    lock_fd = _acquire_lock()
    if lock_fd is None:
        print("Another daemon instance is already running", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("daemon")
    log.info("Starting daemon on port %d", port)

    from lib.controller import Controller
    from lib.router import Router

    workflow_configs = load_workflow_configs(CONFIG_DIR)
    log.info("Loaded workflow configs: %s", list(workflow_configs.keys()))
    controller = Controller(config_dir=CONFIG_DIR, data_dir=DATA_DIR,
                            workflow_configs=workflow_configs)
    router = Router(port=port, controller=controller)

    def handle_signal(signum: int, frame: object) -> None:
        log.info("Received signal %d, shutting down", signum)
        router.shutdown()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        router.serve_forever()
    except Exception as e:
        log.error("Fatal error: %s", e)
    finally:
        log.info("Daemon stopped")
        try:
            lock_fd.close()
            LOCK_FILE.unlink(missing_ok=True)
        except OSError:
            pass


def is_running(port: int = DEFAULT_PORT) -> bool:
    """Check if daemon is already running via TCP connection check."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(("127.0.0.1", port))
        sock.close()
        return True
    except (ConnectionRefusedError, OSError):
        return False


def shutdown(port: int = DEFAULT_PORT) -> bool:
    """Request graceful shutdown via JSON-RPC."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(("127.0.0.1", port))

        request = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "daemon/shutdown",
            "params": {},
        }) + "\n"
        sock.sendall(request.encode("utf-8"))

        # Wait for response
        data = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break
        except socket.timeout:
            pass

        sock.close()
        return True
    except (ConnectionRefusedError, OSError):
        return False


def _acquire_lock() -> object | None:
    """Acquire exclusive flock. Returns file object or None if locked."""
    try:
        fd = open(LOCK_FILE, "w")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError:
        return None


if __name__ == "__main__":
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        if sys.argv[1] == "--shutdown":
            if shutdown():
                print("Shutdown request sent")
            else:
                print("Daemon not running", file=sys.stderr)
                sys.exit(1)
            sys.exit(0)
        elif sys.argv[1] == "--status":
            if is_running():
                print("Daemon is running")
            else:
                print("Daemon is not running")
            sys.exit(0)
        elif sys.argv[1] == "--import-dashboard":
            import json as _json
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(60.0)
            try:
                sock.connect(("127.0.0.1", DEFAULT_PORT))
                # Initialize connection
                sock.sendall(_json.dumps({
                    "jsonrpc": "2.0", "id": 1,
                    "method": "initialize", "params": {},
                }).encode() + b"\n")
                init_resp = sock.recv(8192)
                try:
                    init_data = _json.loads(init_resp.decode().strip())
                    if "error" in init_data:
                        print(f"Initialize failed: {init_data['error']}", file=sys.stderr)
                        sys.exit(1)
                except (_json.JSONDecodeError, UnicodeDecodeError):
                    print("Invalid initialize response", file=sys.stderr)
                    sys.exit(1)
                # Send initialized notification (required by MCP protocol)
                sock.sendall(_json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode() + b"\n")
                # Call import
                sock.sendall(_json.dumps({
                    "jsonrpc": "2.0", "id": 2,
                    "method": "tools/call",
                    "params": {"name": "router__import_dashboard", "arguments": {}},
                }).encode() + b"\n")
                buf = b""
                while b"\n" not in buf:
                    buf += sock.recv(8192)
                result = _json.loads(buf.decode().strip())
                data = result.get("result", {})
                if not isinstance(data, dict):
                    print(f"Import result: {data}")
                else:
                    content_list = data.get("content", [])
                    text = ""
                    if isinstance(content_list, list) and content_list:
                        first = content_list[0]
                        text = first.get("text", "{}") if isinstance(first, dict) else ""
                    try:
                        inner = _json.loads(text) if text else {}
                        print(f"Import: {inner.get('files', 0)} files, "
                              f"{inner.get('inserted', 0)} inserted, "
                              f"{inner.get('skipped', 0)} skipped")
                    except _json.JSONDecodeError:
                        print(f"Import result: {data}")
            except ConnectionRefusedError:
                print("Daemon not running", file=sys.stderr)
                sys.exit(1)
            finally:
                sock.close()
            sys.exit(0)
        else:
            try:
                port = int(sys.argv[1])
            except ValueError:
                print(
                    f"Usage: {sys.argv[0]} [port|--shutdown|--status|--import-dashboard]",
                    file=sys.stderr,
                )
                sys.exit(1)
    main(port)
