#!/usr/bin/env python3
"""PreToolUse hook to enforce TDD by requiring test files before editing Python files."""

import json
import sys
from pathlib import Path


def is_edit_tool(tool_name: str) -> bool:
    """Check if tool is an Edit-type tool, handling MCP router prefixes."""
    # Normalize MCP router prefixes
    normalized = tool_name
    if tool_name.startswith("mcp__router__"):
        # Extract last part: mcp__router__serena__edit_file -> edit_file
        parts = tool_name.split("__")
        normalized = parts[-1] if parts else tool_name

    # Check for edit tools
    return normalized.lower() in ("edit", "edit_file")


def is_test_file(file_path: Path) -> bool:
    """Check if a file is a test file (test_*.py or *_test.py)."""
    name = file_path.name
    return name.startswith("test_") or name.endswith("_test.py")


def find_test_file(impl_path: Path) -> Path | None:
    """Find corresponding test file for an implementation file.

    Searches for test_<module>.py or <module>_test.py in:
    1. Same directory
    2. tests/ directory at same level
    3. tests/ directory at project root (walking up)
    """
    module_name = impl_path.stem  # e.g., "foo" from "foo.py"

    # Possible test file names
    test_names = [f"test_{module_name}.py", f"{module_name}_test.py"]

    # Search in same directory
    for test_name in test_names:
        test_path = impl_path.parent / test_name
        if test_path.exists():
            return test_path

    # Search in sibling tests/ directory
    for test_name in test_names:
        test_path = impl_path.parent / "tests" / test_name
        if test_path.exists():
            return test_path

    # Walk up looking for tests/ directories
    current = impl_path.parent
    for _ in range(10):  # Limit search depth
        parent = current.parent
        if parent == current:  # Reached root
            break

        # Check tests/ at this level
        tests_dir = parent / "tests"
        if tests_dir.is_dir():
            for test_name in test_names:
                test_path = tests_dir / test_name
                if test_path.exists():
                    return test_path

        current = parent

    return None


def allow(reason: str = "") -> dict:
    """Return allow response."""
    return {
        "hookSpecificOutput": {
            "permissionDecision": "allow",
            "permissionDecisionReason": reason
        }
    }


def deny(reason: str) -> dict:
    """Return deny response."""
    return {
        "hookSpecificOutput": {
            "permissionDecision": "deny",
            "permissionDecisionReason": reason
        }
    }


def main():
    """Enforce test existence before editing Python implementation files."""
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, TypeError):
        # Malformed input - fail open
        print(json.dumps(allow("Malformed input - allowing")))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input")

    # Only check Edit-type tools
    if not is_edit_tool(tool_name):
        print(json.dumps(allow()))
        return

    # Handle missing or None tool_input - fail open
    if not tool_input or not isinstance(tool_input, dict):
        print(json.dumps(allow("No tool input - allowing")))
        return

    # Get file path
    file_path_str = tool_input.get("file_path")
    if not file_path_str:
        print(json.dumps(allow("No file path - allowing")))
        return

    file_path = Path(file_path_str)

    # Only check Python files
    if file_path.suffix != ".py":
        print(json.dumps(allow("Not a Python file")))
        return

    # Always allow editing test files
    if is_test_file(file_path):
        print(json.dumps(allow("Editing test file")))
        return

    # Check if corresponding test exists
    test_file = find_test_file(file_path)
    if test_file:
        print(json.dumps(allow(f"Test exists: {test_file.name}")))
        return

    # No test file found - deny
    module_name = file_path.stem
    print(json.dumps(deny(
        f"[TDD] No test file found for {file_path.name}. "
        f"Create tests/test_{module_name}.py first before editing implementation."
    )))


if __name__ == "__main__":
    main()
