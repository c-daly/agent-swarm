#!/usr/bin/env python3
"""Base enforcement hook - blocks editing tools when no workflow is active.

This is the foundational enforcement that ensures Edit/Write/NotebookEdit
are blocked unless a workflow (/iterate, /orchestrate) is running.

Each workflow has its own enforcement hook for phase-specific rules.
This hook only handles the "No workflow = no editing" rule.
"""

import sys
import json
from pathlib import Path

# Add lib to path for workflow_client
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

try:
    from workflow_client import workflow_is_active
except ImportError:
    # If workflow_client not available, check if router is running
    # If not, allow everything (fail-open during bootstrap)
    def workflow_is_active(workflow_id: str) -> bool:
        return False

# Tools that require an active workflow (normalized names - no mcp__router__ prefix)
EDITING_TOOLS = {
    # Native editing tools
    "Edit", "Write", "NotebookEdit",
    # MCP native tools
    "native__write_file",
    "native__edit_file",
    # Serena text manipulation tools
    "serena__create_text_file",
    "serena__replace_content",
    "serena__replace_symbol_body",
    "serena__insert_after_symbol",
    "serena__insert_before_symbol",
    # Legacy MCP plugin format (with mcp__plugin prefix)
    "mcp__plugin_serena_serena__create_text_file",
    "mcp__plugin_serena_serena__replace_content",
    "mcp__plugin_serena_serena__replace_symbol_body",
    "mcp__plugin_serena_serena__insert_after_symbol",
    "mcp__plugin_serena_serena__insert_before_symbol",
}


def is_any_workflow_active() -> bool:
    """Check if any workflow is currently active via state server."""
    # Check known workflows via workflow_client
    # workflow_client handles connection errors gracefully (returns False)
    for workflow_id in ("iterate", "orchestrate", "pr_comment", "debug"):
        if workflow_is_active(workflow_id):
            return True
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
            "permissionDecision": "deny",
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

    # Normalize MCP router prefix (mcp__router__native__bash -> native__bash)
    if tool_name.startswith("mcp__router__"):
        tool_name = tool_name[len("mcp__router__"):]

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
