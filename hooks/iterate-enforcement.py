#!/usr/bin/env python3
"""Minimal iterate workflow enforcement hook.

This hook enforces phase-based tool restrictions for the iterate workflow.
It's intentionally simple - only checks if tools are allowed in the current phase.

Output format (PreToolUse):
- {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
- {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "block", "permissionDecisionReason": "..."}}
"""

import sys
import json
from pathlib import Path

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

try:
    from iterate_workflow import is_tool_allowed, is_active, get_phase, status
except ImportError as e:
    # If module not available, allow everything
    def is_tool_allowed(tool_name, command=None):
        return True, ""
    def is_active():
        return False
    def get_phase():
        return None
    def status():
        return "[ITERATE] Module not available"


def allow(reason: str = None) -> dict:
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
            "permissionDecision": "block",
            "permissionDecisionReason": reason
        }
    }


def main():
    """Main enforcement logic."""
    # Parse input
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps(allow()))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Skip if no iterate workflow active
    if not is_active():
        print(json.dumps(allow("No active iterate workflow")))
        return

    # Extract command for Bash tool (for git/gh blocking)
    command = tool_input.get("command") if tool_name == "Bash" else None

    # Check if tool is allowed in current phase
    allowed, reason = is_tool_allowed(tool_name, command=command)

    if not allowed:
        # Add current phase info to the reason
        phase = get_phase()
        phase_name = phase.value if phase else "unknown"
        full_reason = f"[ITERATE:{phase_name}] {reason}"
        print(json.dumps(block(full_reason)))
        return

    print(json.dumps(allow()))


if __name__ == "__main__":
    main()
