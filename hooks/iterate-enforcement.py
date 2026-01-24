#!/usr/bin/env python3
"""Iterate workflow enforcement hook.

This hook enforces phase-based tool restrictions for the /iterate workflow.
It ONLY applies when /iterate is active - base-enforcement.py handles the
"no workflow = no editing" rule.

Each workflow owns its own enforcement logic.
"""

import sys
import json
from pathlib import Path

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

try:
    from iterate_workflow import is_tool_allowed, is_active, get_phase
    from workflow_client import agent_get_state
except ImportError:
    # If module not available, allow everything (fail-open)
    def is_tool_allowed(tool_name: str, command: str | None = None) -> tuple[bool, str]:
        return True, ""
    def is_active() -> bool:
        return False
    def get_phase():
        return None
    def agent_get_state(agent_id: str) -> dict | None:
        return None


def is_tool_allowed_for_agent(tool_name: str, agent_id: str, command: str | None = None) -> tuple[bool, str, str]:
    """Check tool permission for a specific agent using its stored phase.
    
    Returns (allowed, reason, phase_name).
    """
    agent_state = agent_get_state(agent_id)
    if not agent_state:
        # No agent state found, fall back to global
        allowed, reason = is_tool_allowed(tool_name, command=command)
        phase = get_phase()
        return allowed, reason, phase.value if phase else "unknown"
    
    # Get agent's phase from stored state
    phase_name = agent_state.get("phase", "unknown")
    
    # Import phase model to check restrictions
    try:
        from phase_model import get_phase_info, TOOL_CATEGORIES
        phase_info = get_phase_info(phase_name)
        if not phase_info:
            return True, "", phase_name
        
        # Check if tool is explicitly blocked
        if tool_name in phase_info.blocked_tools:
            return False, f"Tool '{tool_name}' blocked in {phase_name} phase", phase_name
        
        # Check tool category
        tool_cat = TOOL_CATEGORIES.get(tool_name)
        if tool_cat and tool_cat not in phase_info.allowed_categories:
            return False, f"Tool '{tool_name}' (category: {tool_cat}) not allowed in {phase_name} phase", phase_name
        
        return True, "", phase_name
    except ImportError:
        return True, "", phase_name


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
    """Main enforcement logic - only applies when /iterate is active."""
    # Parse input
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps(allow()))
        return

    # Skip if /iterate is not active - base-enforcement handles no-workflow case
    if not is_active():
        print(json.dumps(allow()))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Normalize MCP router prefix (mcp__router__native__bash -> native__bash)
    if tool_name.startswith("mcp__router__"):
        tool_name = tool_name[len("mcp__router__"):]

    # Extract command for bash tools (for git/gh blocking)
    # native__bash is the routed version through MCP router
    command = tool_input.get("command") if tool_name in ("Bash", "native__bash") else None

    # Check if this is a subagent with stored state
    agent_id = input_data.get("agentId")
    
    if agent_id:
        # Use agent-specific phase enforcement
        allowed, reason, phase_name = is_tool_allowed_for_agent(tool_name, agent_id, command=command)
        if not allowed:
            full_reason = f"[ITERATE:{phase_name}] {reason}"
            print(json.dumps(block(full_reason)))
            return
    else:
        # Use global iterate workflow phase enforcement
        allowed, reason = is_tool_allowed(tool_name, command=command)
        if not allowed:
            phase = get_phase()
            phase_name = phase.value if phase else "unknown"
            full_reason = f"[ITERATE:{phase_name}] {reason}"
            print(json.dumps(block(full_reason)))
            return

    print(json.dumps(allow()))


if __name__ == "__main__":
    main()
