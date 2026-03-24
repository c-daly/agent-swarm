#!/usr/bin/env python3
"""Prevent claiming work is done when the workflow hasn't completed.

Checks git commit messages for completion claims and verifies
the experiment workflow has actually reached the 'done' phase.
"""
import json
import os
import re
import sys

# Words that indicate a completion claim in commit messages
COMPLETION_WORDS = re.compile(
    r"\b(complete|completed|done|finish|finished|all.*pass|epic.*done)\b",
    re.IGNORECASE,
)


def block(reason: str):
    print(reason, file=sys.stderr)
    sys.exit(2)


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Only check Bash commands that look like git commits
    if tool_name not in ("Bash", "mcp__plugin_agent-swarm_router__native__bash"):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }))
        return

    command = tool_input.get("command", "")
    if "git commit" not in command:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }))
        return

    # Check if the commit message claims completion
    if not COMPLETION_WORDS.search(command):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }))
        return

    # Completion claim detected — check if a workflow is active and done
    try:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        sys.path.insert(0, os.path.join(script_dir, '..', 'lib'))
        from daemon_client import DaemonClient

        with DaemonClient() as dc:
            for wf_id in ("experiment", "experiment-batch"):
                if dc.workflow_is_active(wf_id):
                    state = dc.workflow_get_state(wf_id)
                    phase = state.get("phase", "unknown") if state else "unknown"
                    if phase != "done":
                        block(
                            f"[BLOCKED] Commit claims completion but workflow "
                            f"'{wf_id}' is in phase '{phase}', not 'done'. "
                            f"Complete the workflow before claiming the work is done."
                        )
    except Exception:
        # If we can't check workflow state, allow through
        # (daemon might not be running)
        pass

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }))


if __name__ == "__main__":
    main()
