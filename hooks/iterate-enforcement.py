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
except ImportError:
    # If module not available, allow everything (fail-open)
    def is_tool_allowed(tool_name: str, command: str | None = None) -> tuple[bool, str]:
        return True, ""
    def is_active() -> bool:
        return False
    def get_phase():
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

    # Extract command for bash tools (for git/gh blocking)
    # native__bash is the routed version through MCP router
    command = tool_input.get("command") if tool_name in ("Bash", "native__bash") else None

    # Check phase-based restrictions
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
