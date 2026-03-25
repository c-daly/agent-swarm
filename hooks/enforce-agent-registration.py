#!/usr/bin/env python3
"""Block Agent tool calls that bypass the registration system.

Checks:
1. mode must NOT be "bypassPermissions"
2. prompt must contain a registered agent ID (verified with daemon)
"""
import json
import os
import re
import sys


def block(reason: str):
    print(reason, file=sys.stderr)
    sys.exit(2)


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Agent":
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

    # Check 2: prompt must contain a registered agent ID, verified with daemon
    prompt = tool_input.get("prompt", "")
    match = re.search(r"sub-[0-9a-f]{8}", prompt)
    if not match:
        block(
            "[BLOCKED] Agent prompt does not contain a registered agent ID "
            "(sub-XXXXXXXX). Call prepare_dispatch first to get an agent ID "
            "and briefing, then include them in the prompt."
        )

    # Check 3: verify the ID is actually registered with the daemon
    agent_id = match.group(0)
    try:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        sys.path.insert(0, os.path.join(script_dir, '..', 'lib'))
        from daemon_client import DaemonClient

        with DaemonClient() as dc:
            state = dc.agent_get_state(agent_id)
            if not state:
                block(
                    f"[BLOCKED] Agent ID '{agent_id}' is not registered with "
                    f"the daemon. Call prepare_dispatch first — do not fabricate IDs."
                )
    except Exception as exc:
        # If daemon is unreachable, block rather than allow
        block(
            f"[BLOCKED] Cannot verify agent ID '{agent_id}' with daemon: {exc}. "
            f"Ensure the daemon is running."
        )

    # Passed all checks
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }))


if __name__ == "__main__":
    main()
