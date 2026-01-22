#!/usr/bin/env python3
"""Workflow state modification enforcement hook.

This hook prevents subagents from modifying workflow state directly.
Only the orchestrator (main session without agentId) should control
workflow transitions.

Blocked for subagents:
- workflow_start, workflow_stop, workflow_update
- workflow_set_state, workflow_set_value

Allowed for subagents:
- workflow_get_state, workflow_get_value, workflow_is_active (read-only)
- agent_set_state (only for their own agent state)
"""

import sys
import json

# Workflow state modification tools that subagents cannot use
WORKFLOW_MODIFY_TOOLS = {
    # Base names
    "workflow_start",
    "workflow_stop",
    "workflow_update",
    "workflow_set_state",
    "workflow_set_value",
    # With workflow__ prefix (MCP format)
    "workflow__workflow_start",
    "workflow__workflow_stop",
    "workflow__workflow_update",
    "workflow__workflow_set_state",
    "workflow__workflow_set_value",
}

# Agent state modification tool
AGENT_SET_STATE_TOOLS = {
    "agent_set_state",
    "workflow__agent_set_state",
}


def normalize_tool_name(tool_name: str) -> str:
    """Remove mcp__router__ prefix if present."""
    if tool_name.startswith("mcp__router__"):
        return tool_name[len("mcp__router__"):]
    return tool_name


def allow(reason: str = "") -> dict:
    """Return allow decision."""
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow"
        }
    }
    if reason:
        result["hookSpecificOutput"]["permissionDecisionReason"] = reason
    return result


def block(reason: str) -> dict:
    """Return block decision."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason
        }
    }


def main():
    """Main enforcement logic."""
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps(allow()))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    agent_id = input_data.get("agentId")  # Present if this is a subagent

    # Normalize tool name
    normalized_tool = normalize_tool_name(tool_name)

    # If not a subagent (no agentId), allow everything
    if not agent_id:
        print(json.dumps(allow()))
        return

    # Subagent context - check for blocked tools

    # Block workflow state modification tools
    if normalized_tool in WORKFLOW_MODIFY_TOOLS:
        print(json.dumps(block(
            f"[SUBAGENT BLOCKED] {normalized_tool}: Subagents cannot modify workflow state. "
            f"Only the orchestrator controls workflow transitions."
        )))
        return

    # For agent_set_state, only allow if modifying own state
    if normalized_tool in AGENT_SET_STATE_TOOLS:
        target_agent_id = tool_input.get("agent_id", "")
        if target_agent_id != agent_id:
            print(json.dumps(block(
                f"[SUBAGENT BLOCKED] {normalized_tool}: Subagent '{agent_id}' cannot modify "
                f"another agent's state ('{target_agent_id}'). Subagents can only modify their own state."
            )))
            return

    # All other tools are allowed
    print(json.dumps(allow()))


if __name__ == "__main__":
    main()
