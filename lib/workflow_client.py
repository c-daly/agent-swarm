#!/usr/bin/env python3
"""
Workflow Client - Socket client for hooks and external processes.

Connects to the MCP router's socket listener to query workflow state.
Used by hooks that run as separate Python processes.

Usage:
    from workflow_client import workflow_is_active, workflow_get_value

    if workflow_is_active("iterate"):
        phase = workflow_get_value("iterate", "phase")
"""

import json
import os
import socket
from pathlib import Path
from typing import Any, Optional


class WorkflowClientError(Exception):
    """Error communicating with workflow server."""
    pass


def _get_router_port() -> int:
    """Get router port from port file."""
    port_file = Path(__file__).parent.parent / ".state" / "router.port"
    if not port_file.exists():
        raise WorkflowClientError(
            f"Router port file not found: {port_file}. "
            "Is the router running?"
        )
    try:
        return int(port_file.read_text().strip())
    except ValueError as e:
        raise WorkflowClientError(f"Invalid port in {port_file}: {e}")


def _call_tool(tool_name: str, arguments: dict) -> Any:
    """Call a workflow tool via the router socket.

    Args:
        tool_name: Tool name without prefix (e.g., "workflow_is_active")
        arguments: Tool arguments dict

    Returns:
        The result from the tool call.

    Raises:
        WorkflowClientError: If communication fails or tool returns error.
    """
    try:
        port = _get_router_port()
    except WorkflowClientError:
        # Router not running - return safe defaults
        return None

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5.0)  # 5 second timeout
            s.connect(("127.0.0.1", port))

            # Send JSON-RPC request
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": f"workflow__{tool_name}",
                    "arguments": arguments
                }
            }
            s.sendall(json.dumps(request).encode() + b"\n")

            # Read response
            data = b""
            while b"\n" not in data:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk

            if not data:
                raise WorkflowClientError("No response from router")

            response = json.loads(data.decode().strip())

            # Check for error
            if "error" in response:
                raise WorkflowClientError(f"Router error: {response['error']}")

            result = response.get("result", {})

            # Handle error in result
            if isinstance(result, dict) and result.get("isError"):
                content = result.get("content", [{}])
                if content:
                    error_text = content[0].get("text", "Unknown error")
                    raise WorkflowClientError(error_text)

            # Extract text content
            if isinstance(result, dict) and "content" in result:
                content = result.get("content", [])
                if content and isinstance(content[0], dict):
                    text = content[0].get("text", "")
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return text

            return result

    except socket.timeout:
        raise WorkflowClientError("Timeout connecting to router")
    except socket.error as e:
        raise WorkflowClientError(f"Socket error: {e}")
    except json.JSONDecodeError as e:
        raise WorkflowClientError(f"Invalid JSON response: {e}")


# ─────────────────────────────────────────────────────────────────
# Workflow Operations
# ─────────────────────────────────────────────────────────────────

def workflow_start(workflow_id: str, initial_state: dict) -> dict:
    """Start a new workflow with initial state.

    Raises WorkflowClientError if workflow already exists.
    """
    return _call_tool("workflow_start", {
        "workflow_id": workflow_id,
        "initial_state": initial_state
    })


def workflow_stop(workflow_id: str) -> bool:
    """Stop and remove workflow state."""
    result = _call_tool("workflow_stop", {"workflow_id": workflow_id})
    if isinstance(result, dict):
        return result.get("success", False)
    return False


def workflow_is_active(workflow_id: str) -> bool:
    """Check if a workflow is currently active."""
    try:
        result = _call_tool("workflow_is_active", {"workflow_id": workflow_id})
        if result is None:
            return False
        if isinstance(result, bool):
            return result
        if isinstance(result, str):
            return result.lower() == "true"
        return False
    except WorkflowClientError:
        return False


def workflow_get_state(workflow_id: str) -> Optional[dict]:
    """Get the full state of a workflow."""
    try:
        return _call_tool("workflow_get_state", {"workflow_id": workflow_id})
    except WorkflowClientError:
        return None


def workflow_set_state(workflow_id: str, state: dict) -> dict:
    """Replace the full state of a workflow."""
    return _call_tool("workflow_set_state", {
        "workflow_id": workflow_id,
        "state": state
    })


def workflow_update(workflow_id: str, updates: dict) -> dict:
    """Merge partial updates into workflow state."""
    return _call_tool("workflow_update", {
        "workflow_id": workflow_id,
        "updates": updates
    })


def workflow_get_value(workflow_id: str, key: str) -> Any:
    """Get a single field from workflow state."""
    try:
        return _call_tool("workflow_get_value", {
            "workflow_id": workflow_id,
            "key": key
        })
    except WorkflowClientError:
        return None


def workflow_set_value(workflow_id: str, key: str, value: Any) -> bool:
    """Set a single field in workflow state."""
    result = _call_tool("workflow_set_value", {
        "workflow_id": workflow_id,
        "key": key,
        "value": value
    })
    if isinstance(result, dict):
        return result.get("success", False)
    return False


# ─────────────────────────────────────────────────────────────────
# Agent Operations
# ─────────────────────────────────────────────────────────────────

def agent_get_state(agent_id: str) -> Optional[dict]:
    """Get the state of an agent."""
    try:
        return _call_tool("agent_get_state", {"agent_id": agent_id})
    except WorkflowClientError:
        return None


def agent_set_state(agent_id: str, state: dict) -> dict:
    """Set the state of an agent."""
    return _call_tool("agent_set_state", {
        "agent_id": agent_id,
        "state": state
    })


def agent_delete(agent_id: str) -> bool:
    """Delete an agent's state."""
    result = _call_tool("agent_delete", {"agent_id": agent_id})
    if isinstance(result, dict):
        return result.get("success", False)
    return False


def list_agents() -> list[str]:
    """List all agent IDs."""
    try:
        result = _call_tool("list_agents", {})
        if isinstance(result, list):
            return result
        return []
    except WorkflowClientError:
        return []
