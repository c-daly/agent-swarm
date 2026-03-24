#!/usr/bin/env python3
"""Block Agent tool calls that bypass the registration system.

Checks:
1. mode must NOT be "bypassPermissions"
2. prompt must contain a registered agent ID (sub-XXXXXXXX pattern)

This ensures all subagents go through prepare_dispatch and get proper
briefings with mcp-call instructions and caller IDs.
"""
import json
import re
import sys


def block(reason: str):
    print(reason, file=sys.stderr)
    sys.exit(2)


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return  # allow through if we can't parse

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Agent":
        # Not an agent dispatch — allow
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }))
        return

    tool_input = input_data.get("tool_input", {})

    # Check 1: block bypassPermissions
    mode = tool_input.get("mode", "")
    if mode == "bypassPermissions":
        block(
            "[BLOCKED] Agent dispatched with mode: bypassPermissions. "
            "Use prepare_dispatch to register the agent and include the "
            "briefing in the prompt instead."
        )

    # Check 2: prompt must contain a registered agent ID
    prompt = tool_input.get("prompt", "")
    if not re.search(r"sub-[0-9a-f]{8}", prompt):
        block(
            "[BLOCKED] Agent prompt does not contain a registered agent ID "
            "(sub-XXXXXXXX). Call prepare_dispatch first to get an agent ID "
            "and briefing, then include them in the prompt."
        )

    # Passed both checks
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }))


if __name__ == "__main__":
    main()
