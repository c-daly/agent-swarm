#!/usr/bin/env python3
"""PreToolUse hook to enforce run_in_background=true for Task tool."""

import json
import sys


def main():
    """Enforce run_in_background=true for Task tool calls."""
    input_data = json.loads(sys.stdin.read())
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    
    # Only check Task tool
    if tool_name != "Task":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow"
            }
        }))
        return
    
    # Check run_in_background parameter
    run_in_background = tool_input.get("run_in_background", False)
    
    if not run_in_background:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "[BACKGROUND_REQUIRED] Task tool must use run_in_background=true "
                    "for parallel execution. Add run_in_background=true to your Task call."
                )
            }
        }))
        return
    
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow"
        }
    }))


if __name__ == "__main__":
    main()
