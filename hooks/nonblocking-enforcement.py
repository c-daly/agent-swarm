#!/usr/bin/env python3
"""PreToolUse hook to enforce block=false for TaskOutput tool."""

import json
import sys


def main():
    """Enforce block=false for TaskOutput tool calls."""
    input_data = json.loads(sys.stdin.read())
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    
    # Only check TaskOutput tool
    if tool_name != "TaskOutput":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow"
            }
        }))
        return
    
    # Check block parameter (defaults to True if not specified)
    block = tool_input.get("block", True)
    
    if block:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "[NONBLOCKING_REQUIRED] TaskOutput tool must use block=false "
                    "for parallel agent monitoring. Add block=false to your TaskOutput call."
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
