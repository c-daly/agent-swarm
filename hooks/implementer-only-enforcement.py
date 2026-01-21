#!/usr/bin/env python3
"""Implementer-only enforcement hook.

Enforces that during the orchestrate phase of iterate workflow (TDD mode),
only agent-swarm:implementer agents can be spawned. This ensures that all
implementation work goes through the TDD loop (test_writing → implement → test → review).

Spawning explorers, researchers, etc. from orchestrate phase bypasses TDD discipline.
"""

import json
import sys
from pathlib import Path

# Add lib to path for workflow_client
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

try:
    from workflow_client import workflow_is_active, workflow_get_state
except ImportError:
    # Fail-open if workflow_client not available
    def workflow_is_active(workflow_id: str) -> bool:
        return False
    def workflow_get_state(workflow_id: str) -> dict | None:
        return None


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
        # Fail-open on invalid input
        print(json.dumps(allow()))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Only check Task tool
    if tool_name != "Task":
        print(json.dumps(allow()))
        return

    # Check if iterate workflow is active
    if not workflow_is_active("iterate"):
        # Not in iterate workflow - allow any agent type
        print(json.dumps(allow()))
        return

    # Get iterate workflow state
    state = workflow_get_state("iterate")
    if not state:
        # Can't get state - fail-open
        print(json.dumps(allow()))
        return

    # Check if in orchestrate phase
    phase = state.get("phase", "")
    if phase != "orchestrate":
        # Not in orchestrate phase - allow any agent type
        print(json.dumps(allow()))
        return

    # In iterate workflow + orchestrate phase - only allow implementer agents
    subagent_type = tool_input.get("subagent_type", "")
    
    if not subagent_type:
        # No subagent_type specified - fail-open
        print(json.dumps(allow()))
        return

    if subagent_type == "agent-swarm:implementer":
        # Implementer allowed
        print(json.dumps(allow("Implementer agent in orchestrate phase")))
        return

    # Non-implementer agent in orchestrate phase - BLOCK
    print(json.dumps(block(
        f"[ITERATE/ORCHESTRATE] Only agent-swarm:implementer agents allowed during "
        f"orchestrate phase of iterate workflow (TDD enforcement). "
        f"Attempted to spawn: {subagent_type}. "
        f"Implementers go through full TDD loop (test_writing → implement → test → review). "
        f"Spawning other agent types bypasses TDD discipline."
    )))


if __name__ == "__main__":
    main()
