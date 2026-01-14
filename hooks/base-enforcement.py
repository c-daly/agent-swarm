#!/usr/bin/env python3
"""Base enforcement hook - blocks editing tools when no workflow is active.

This is the foundational enforcement that ensures Edit/Write/NotebookEdit
are blocked unless a workflow (/iterate, /orchestrate) is running.

Each workflow has its own enforcement hook for phase-specific rules.
This hook only handles the "no workflow = no editing" rule.
"""

import sys
import json
from pathlib import Path

# Workflow state files to check
ITERATE_STATE = Path.home() / ".claude" / "state" / "iterate_state.json"
ORCHESTRATE_STATE = Path.home() / ".claude" / "state" / "orchestrate_state.json"

# Tools that require an active workflow
EDITING_TOOLS = {"Edit", "Write", "NotebookEdit"}


def is_any_workflow_active() -> bool:
    """Check if any workflow is currently active."""
    # Check iterate workflow
    if ITERATE_STATE.exists():
        try:
            with open(ITERATE_STATE) as f:
                state = json.load(f)
                if state.get("active"):
                    return True
        except (json.JSONDecodeError, IOError):
            pass

    # Check orchestrate workflow
    if ORCHESTRATE_STATE.exists():
        try:
            with open(ORCHESTRATE_STATE) as f:
                state = json.load(f)
                if state.get("active"):
                    return True
        except (json.JSONDecodeError, IOError):
            pass

    return False


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
            "permissionDecision": "block",
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

    # Only check editing tools
    if tool_name not in EDITING_TOOLS:
        print(json.dumps(allow()))
        return

    # Block editing tools if no workflow is active
    if not is_any_workflow_active():
        print(json.dumps(block(
            f"[NO WORKFLOW] {tool_name} blocked. "
            f"Start /iterate or /orchestrate to edit files."
        )))
        return

    # Workflow is active - allow (workflow-specific hooks handle phase rules)
    print(json.dumps(allow("Workflow active")))


if __name__ == "__main__":
    main()
