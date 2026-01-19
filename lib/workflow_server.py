#!/usr/bin/env python3
"""
Workflow State MCP Server

An in-memory MCP server for thread-safe workflow and agent state management.
Receives requests via stdio from the router.

Tools:
- workflow_start, workflow_stop, workflow_is_active
- workflow_get_state, workflow_set_state, workflow_update
- workflow_get_value, workflow_set_value
- agent_get_state, agent_set_state, agent_delete, list_agents
"""

import json
import sys
import threading
from copy import deepcopy
from typing import Any


class WorkflowStateServer:
    """Thread-safe in-memory storage for workflow and agent state."""

    def __init__(self):
        self._workflows: dict[str, dict[str, Any]] = {}
        self._agents: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    # ─────────────────────────────────────────────────────────────
    # Workflow Operations
    # ─────────────────────────────────────────────────────────────

    def workflow_start(self, workflow_id: str, initial_state: dict) -> dict:
        """Create a new workflow. Fails if workflow already exists."""
        with self._lock:
            if workflow_id in self._workflows:
                raise ValueError(f"Workflow '{workflow_id}' already exists")
            self._workflows[workflow_id] = deepcopy(initial_state)
            return deepcopy(self._workflows[workflow_id])

    def workflow_stop(self, workflow_id: str) -> bool:
        """Remove workflow state. Returns True if existed."""
        with self._lock:
            if workflow_id in self._workflows:
                del self._workflows[workflow_id]
                return True
            return False

    def workflow_is_active(self, workflow_id: str) -> bool:
        """Check if workflow exists."""
        with self._lock:
            return workflow_id in self._workflows

    def workflow_get_state(self, workflow_id: str) -> dict | None:
        """Get full workflow state. Returns None if not found."""
        with self._lock:
            if workflow_id in self._workflows:
                return deepcopy(self._workflows[workflow_id])
            return None

    def workflow_set_state(self, workflow_id: str, state: dict) -> dict:
        """Replace full workflow state. Creates if doesn't exist."""
        with self._lock:
            self._workflows[workflow_id] = deepcopy(state)
            return deepcopy(self._workflows[workflow_id])

    def workflow_update(self, workflow_id: str, updates: dict) -> dict:
        """Merge partial updates into workflow state."""
        with self._lock:
            if workflow_id not in self._workflows:
                raise ValueError(f"Workflow '{workflow_id}' not found")
            self._workflows[workflow_id].update(deepcopy(updates))
            return deepcopy(self._workflows[workflow_id])

    def workflow_get_value(self, workflow_id: str, key: str) -> Any:
        """Get single field from workflow state."""
        with self._lock:
            if workflow_id not in self._workflows:
                return None
            return deepcopy(self._workflows[workflow_id].get(key))

    def workflow_set_value(self, workflow_id: str, key: str, value: Any) -> bool:
        """Set single field in workflow state."""
        with self._lock:
            if workflow_id not in self._workflows:
                raise ValueError(f"Workflow '{workflow_id}' not found")
            self._workflows[workflow_id][key] = deepcopy(value)
            return True

    # ─────────────────────────────────────────────────────────────
    # Agent Operations
    # ─────────────────────────────────────────────────────────────

    def agent_get_state(self, agent_id: str) -> dict | None:
        """Get agent state. Returns None if not found."""
        with self._lock:
            if agent_id in self._agents:
                return deepcopy(self._agents[agent_id])
            return None

    def agent_set_state(self, agent_id: str, state: dict) -> dict:
        """Set agent state. Creates or replaces."""
        with self._lock:
            self._agents[agent_id] = deepcopy(state)
            return deepcopy(self._agents[agent_id])

    def agent_delete(self, agent_id: str) -> bool:
        """Delete agent state. Returns True if existed."""
        with self._lock:
            if agent_id in self._agents:
                del self._agents[agent_id]
                return True
            return False

    def list_agents(self) -> list[str]:
        """List all agent IDs."""
        with self._lock:
            return list(self._agents.keys())


# ─────────────────────────────────────────────────────────────────
# MCP Tool Definitions
# ─────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "workflow_start",
        "description": "Create a new workflow with initial state. Fails if workflow already exists.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Unique workflow identifier"},
                "initial_state": {"type": "object", "description": "Initial state dict"}
            },
            "required": ["workflow_id", "initial_state"]
        }
    },
    {
        "name": "workflow_stop",
        "description": "Stop and remove workflow state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Workflow identifier"}
            },
            "required": ["workflow_id"]
        }
    },
    {
        "name": "workflow_is_active",
        "description": "Check if a workflow is currently active.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Workflow identifier"}
            },
            "required": ["workflow_id"]
        }
    },
    {
        "name": "workflow_get_state",
        "description": "Get the full state of a workflow.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Workflow identifier"}
            },
            "required": ["workflow_id"]
        }
    },
    {
        "name": "workflow_set_state",
        "description": "Replace the full state of a workflow.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Workflow identifier"},
                "state": {"type": "object", "description": "New state dict"}
            },
            "required": ["workflow_id", "state"]
        }
    },
    {
        "name": "workflow_update",
        "description": "Merge partial updates into workflow state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Workflow identifier"},
                "updates": {"type": "object", "description": "Partial state to merge"}
            },
            "required": ["workflow_id", "updates"]
        }
    },
    {
        "name": "workflow_get_value",
        "description": "Get a single field from workflow state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Workflow identifier"},
                "key": {"type": "string", "description": "Field name"}
            },
            "required": ["workflow_id", "key"]
        }
    },
    {
        "name": "workflow_set_value",
        "description": "Set a single field in workflow state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Workflow identifier"},
                "key": {"type": "string", "description": "Field name"},
                "value": {"description": "Field value (any JSON type)"}
            },
            "required": ["workflow_id", "key", "value"]
        }
    },
    {
        "name": "agent_get_state",
        "description": "Get the state of an agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent identifier"}
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "agent_set_state",
        "description": "Set the state of an agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent identifier"},
                "state": {"type": "object", "description": "Agent state dict"}
            },
            "required": ["agent_id", "state"]
        }
    },
    {
        "name": "agent_delete",
        "description": "Delete an agent's state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent identifier"}
            },
            "required": ["agent_id"]
        }
    },
    {
        "name": "list_agents",
        "description": "List all agent IDs.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]


# ─────────────────────────────────────────────────────────────────
# MCP Server Loop
# ─────────────────────────────────────────────────────────────────

def run_server():
    """Run the MCP server loop on stdio."""
    server = WorkflowStateServer()

    def send(msg: dict) -> None:
        print(json.dumps(msg), flush=True)

    def make_result(text: str) -> dict:
        return {"content": [{"type": "text", "text": text}]}

    def make_error(text: str) -> dict:
        return {"content": [{"type": "text", "text": text}], "isError": True}

    for line in sys.stdin:
        request_id = None
        try:
            request = json.loads(line.strip())
            method = request.get("method", "")
            params = request.get("params", {})
            request_id = request.get("id")

            # MCP handshake
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "workflow-state-server",
                        "version": "1.0.0"
                    }
                }
            elif method == "notifications/initialized":
                continue  # Notification, no response

            # Tool discovery
            elif method == "tools/list":
                result = {"tools": TOOLS}

            # Tool execution
            elif method == "tools/call":
                tool_name = params.get("name", "")
                args = params.get("arguments", {})

                try:
                    if tool_name == "workflow_start":
                        state = server.workflow_start(args["workflow_id"], args["initial_state"])
                        result = make_result(json.dumps(state))

                    elif tool_name == "workflow_stop":
                        success = server.workflow_stop(args["workflow_id"])
                        result = make_result(json.dumps({"success": success}))

                    elif tool_name == "workflow_is_active":
                        active = server.workflow_is_active(args["workflow_id"])
                        result = make_result(str(active).lower())

                    elif tool_name == "workflow_get_state":
                        state = server.workflow_get_state(args["workflow_id"])
                        result = make_result(json.dumps(state))

                    elif tool_name == "workflow_set_state":
                        state = server.workflow_set_state(args["workflow_id"], args["state"])
                        result = make_result(json.dumps(state))

                    elif tool_name == "workflow_update":
                        state = server.workflow_update(args["workflow_id"], args["updates"])
                        result = make_result(json.dumps(state))

                    elif tool_name == "workflow_get_value":
                        value = server.workflow_get_value(args["workflow_id"], args["key"])
                        result = make_result(json.dumps(value))

                    elif tool_name == "workflow_set_value":
                        success = server.workflow_set_value(
                            args["workflow_id"], args["key"], args["value"]
                        )
                        result = make_result(json.dumps({"success": success}))

                    elif tool_name == "agent_get_state":
                        state = server.agent_get_state(args["agent_id"])
                        result = make_result(json.dumps(state))

                    elif tool_name == "agent_set_state":
                        state = server.agent_set_state(args["agent_id"], args["state"])
                        result = make_result(json.dumps(state))

                    elif tool_name == "agent_delete":
                        success = server.agent_delete(args["agent_id"])
                        result = make_result(json.dumps({"success": success}))

                    elif tool_name == "list_agents":
                        agents = server.list_agents()
                        result = make_result(json.dumps(agents))

                    else:
                        result = make_error(f"Unknown tool: {tool_name}")

                except ValueError as e:
                    result = make_error(str(e))
                except KeyError as e:
                    result = make_error(f"Missing required parameter: {e}")

            else:
                result = {"error": f"Unknown method: {method}"}

            # Write response (skip for notifications)
            if request_id is not None:
                send({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result
                })

        except json.JSONDecodeError as e:
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32700, "message": f"Parse error: {e}"}
            })
        except Exception as e:
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": str(e)}
            })


if __name__ == "__main__":
    run_server()
