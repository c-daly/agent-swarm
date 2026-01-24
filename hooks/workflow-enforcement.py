#!/usr/bin/env python3
"""Generic workflow enforcement hook.

Dispatches to active workflow's tool restrictions.
Supports: debug, pr_comment, iterate workflows.

This hook consolidates enforcement for all workflow types.
Each workflow registers its own tool restrictions via WorkflowEngine.
"""

import sys
import json
from pathlib import Path

lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

try:
    from workflow_client import workflow_get_state
    from debug_workflow import DebugWorkflow
    from pr_comment_workflow import PRCommentWorkflow
    from iterate_workflow import is_tool_allowed as iterate_is_tool_allowed, is_active as iterate_is_active
except ImportError:
    # Fail open if modules not available
    def workflow_get_state(wf_id):
        return None
    def iterate_is_active():
        return False
    def iterate_is_tool_allowed(tool, command=None):
        return True, ""
    DebugWorkflow = None
    PRCommentWorkflow = None


# Workflows using base classes (WorkflowEngine)
BASE_WORKFLOWS = {
    "debug": DebugWorkflow,
    "pr_comment": PRCommentWorkflow,
}


def allow(reason: str = "") -> dict:
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
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason
        }
    }


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps(allow()))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Normalize MCP prefix
    if tool_name.startswith("mcp__router__"):
        tool_name = tool_name[len("mcp__router__"):]

    # Extract file_path for file-based restrictions
    file_path = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("relative_path")

    # Check each workflow type using base classes
    for wf_id, wf_class in BASE_WORKFLOWS.items():
        if wf_class is None:
            continue

        state = workflow_get_state(wf_id)
        if state and state.get("active"):
            wf = wf_class()

            allowed, reason = wf.is_tool_allowed(tool_name, file_path=file_path)

            if not allowed:
                phase = state.get("phase", "unknown")
                print(json.dumps(block(f"[{wf_id.upper()}:{phase}] {reason}")))
                return

    # Check iterate workflow (uses its own logic, not base classes yet)
    if iterate_is_active():
        command = tool_input.get("command") if tool_name in ("Bash", "native__bash") else None
        allowed, reason = iterate_is_tool_allowed(tool_name, command=command)
        if not allowed:
            print(json.dumps(block(reason)))
            return

    print(json.dumps(allow()))


if __name__ == "__main__":
    main()
