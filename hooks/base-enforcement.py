#!/usr/bin/env python3
"""Base enforcement hook - blocks editing tools when no workflow is active.

This is the foundational enforcement that ensures Edit/Write/NotebookEdit
are blocked unless a workflow (/iterate, /orchestrate) is running.

Additionally, it protects .state/ directory from writes unless explicitly
allowed via .state/config.json (allow_state_edits: true).

Each workflow has its own enforcement hook for phase-specific rules.
This hook only handles:
1. State file protection (checked FIRST)
2. "No workflow = no editing" rule
"""

import sys
import json
from pathlib import Path

# Workflow state files to check
STATE_DIR = Path.home() / ".claude" / "plugins" / "agent-swarm" / ".state"
STATE_CONFIG = STATE_DIR / "config.json"
ITERATE_STATE = STATE_DIR / "iterate.json"
ORCHESTRATE_STATE = STATE_DIR / "orchestrate.json"

# Tools that require an active workflow (includes router variants)
EDITING_TOOLS = {
    "Edit", "Write", "NotebookEdit",
    "mcp__router__native__write_file",
    "mcp__router__native__edit_file",
    "mcp__router__serena__create_text_file",
    "mcp__router__serena__replace_content",
    "mcp__plugin_serena_serena__create_text_file",
    "mcp__plugin_serena_serena__replace_content",
}


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


def is_state_edit_allowed() -> bool:
    """Check if .state/ edits are explicitly allowed via config."""
    if not STATE_CONFIG.exists():
        return False
    try:
        with open(STATE_CONFIG) as f:
            config = json.load(f)
            return config.get("allow_state_edits", False) is True
    except (json.JSONDecodeError, IOError):
        return False


def is_state_path(file_path: str) -> bool:
    """Check if a path targets the .state/ directory."""
    if not file_path:
        return False
    try:
        # Resolve the path to handle relative paths and symlinks
        resolved = Path(file_path).resolve()
        state_resolved = STATE_DIR.resolve()
        # Check if the path is within .state/
        return state_resolved in resolved.parents or resolved == state_resolved
    except (ValueError, OSError):
        return False


def get_file_path_from_input(tool_name: str, tool_input: dict) -> str | None:
    """Extract file path from tool input based on tool type."""
    # Native Claude tools
    if tool_name in ("Edit", "Write"):
        return tool_input.get("file_path")
    if tool_name == "NotebookEdit":
        return tool_input.get("notebook_path")
    
    # Router native tools
    if tool_name in ("mcp__router__native__write_file", "mcp__router__native__edit_file"):
        return tool_input.get("file_path")
    
    # Serena tools (use relative_path)
    if tool_name in (
        "mcp__router__serena__create_text_file",
        "mcp__router__serena__replace_content",
        "mcp__plugin_serena_serena__create_text_file",
        "mcp__plugin_serena_serena__replace_content",
    ):
        rel_path = tool_input.get("relative_path")
        if rel_path:
            # Serena uses paths relative to project root
            return str(STATE_DIR.parent / rel_path)
    
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
    """Main enforcement logic."""
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps(allow()))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Only check editing tools
    if tool_name not in EDITING_TOOLS:
        print(json.dumps(allow()))
        return

    # CHECK 1: State file protection (checked FIRST, before workflow check)
    file_path = get_file_path_from_input(tool_name, tool_input)
    if file_path and is_state_path(file_path):
        if not is_state_edit_allowed():
            print(json.dumps(block(
                f"[STATE PROTECTED] {tool_name} blocked. "
                f"Cannot write to .state/ directory. "
                f"Set allow_state_edits=true in .state/config.json to enable."
            )))
            return

    # CHECK 2: Block editing tools if no workflow is active
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
