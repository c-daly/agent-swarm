#!/usr/bin/env python3
"""State file protection hook - blocks edits to .state/ directory.

Prevents accidental or unauthorized modification of workflow state files.
Only allows edits when allow_state_edits=true in .state/config.json.
"""

import sys
import json
from pathlib import Path

STATE_DIR = Path.home() / ".claude" / "plugins" / "agent-swarm" / ".state"
CONFIG_FILE = STATE_DIR / "config.json"

# Tools that write files
WRITE_TOOLS = {
    "Write", "Edit", "NotebookEdit",
    "mcp__router__native__write_file",
    "mcp__router__native__edit_file",
    "mcp__router__serena__create_text_file",
    "mcp__router__serena__replace_content",
    "mcp__router__serena__replace_symbol_body",
}


def is_state_edit_allowed() -> bool:
    """Check if state edits are explicitly allowed via config."""
    if not CONFIG_FILE.exists():
        return False
    try:
        with open(CONFIG_FILE) as f:
            config = json.load(f)
            return config.get("allow_state_edits", False) is True
    except (json.JSONDecodeError, IOError):
        return False


def is_state_path(file_path: str) -> bool:
    """Check if the path targets the .state directory."""
    try:
        path = Path(file_path).resolve()
        state_resolved = STATE_DIR.resolve()
        return str(path).startswith(str(state_resolved))
    except Exception:
        return False


def get_file_path_from_input(tool_name: str, tool_input: dict) -> str | None:
    """Extract file path from tool input based on tool type."""
    # Native tools
    if "file_path" in tool_input:
        return tool_input["file_path"]
    # Serena tools
    if "relative_path" in tool_input:
        # Serena uses relative paths from project root
        return str(STATE_DIR.parent / tool_input["relative_path"])
    return None


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

    # Only check write tools
    if tool_name not in WRITE_TOOLS:
        print(json.dumps(allow()))
        return

    # Get the target file path
    file_path = get_file_path_from_input(tool_name, tool_input)
    if not file_path:
        print(json.dumps(allow()))
        return

    # Check if targeting state directory
    if not is_state_path(file_path):
        print(json.dumps(allow()))
        return

    # State path targeted - check if explicitly allowed
    if is_state_edit_allowed():
        print(json.dumps(allow("State edits enabled via config")))
        return

    # Block state edits
    print(json.dumps(block(
        f"[STATE PROTECTED] Cannot edit {file_path}. "
        f"State files are protected. Set allow_state_edits=true in .state/config.json to override."
    )))


if __name__ == "__main__":
    main()
