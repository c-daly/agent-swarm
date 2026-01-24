#!/usr/bin/env python3
"""Tests for test-existence-enforcement hook."""

import json
import subprocess
from pathlib import Path


HOOK_PATH = Path(__file__).parent.parent / "hooks" / "test-existence-enforcement.py"


def run_hook(tool_name: str, tool_input: dict) -> dict:
    """Run the hook with given input and return the output."""
    input_data = {
        "tool_name": tool_name,
        "tool_input": tool_input
    }
    
    result = subprocess.run(
        ["python3", str(HOOK_PATH)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True
    )
    
    return json.loads(result.stdout)


def test_allow_when_test_exists(tmp_path):
    """Edit should be allowed when corresponding test file exists."""
    # Setup: Create implementation file and its test
    impl_file = tmp_path / "lib" / "foo.py"
    impl_file.parent.mkdir(parents=True)
    impl_file.write_text("def foo(): pass")
    
    test_file = tmp_path / "tests" / "test_foo.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_foo(): pass")
    
    # Run hook
    output = run_hook("Edit", {"file_path": str(impl_file)})
    
    # Assert allowed
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_deny_when_no_test_exists(tmp_path):
    """Edit should be denied when no test file exists."""
    # Setup: Create implementation file without test
    impl_file = tmp_path / "lib" / "bar.py"
    impl_file.parent.mkdir(parents=True)
    impl_file.write_text("def bar(): pass")
    
    # Run hook
    output = run_hook("Edit", {"file_path": str(impl_file)})
    
    # Assert denied
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "TDD" in output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "test" in output["hookSpecificOutput"]["permissionDecisionReason"].lower()


def test_allow_when_editing_test_file_itself(tmp_path):
    """Edit should always be allowed when editing a test file."""
    # Setup: Create test file
    test_file = tmp_path / "tests" / "test_something.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_something(): pass")
    
    # Run hook
    output = run_hook("Edit", {"file_path": str(test_file)})
    
    # Assert allowed
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_allow_when_editing_test_file_with_suffix(tmp_path):
    """Edit should be allowed for *_test.py pattern files."""
    # Setup: Create test file with _test suffix
    test_file = tmp_path / "tests" / "something_test.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_something(): pass")
    
    # Run hook
    output = run_hook("Edit", {"file_path": str(test_file)})
    
    # Assert allowed
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_allow_for_non_python_files(tmp_path):
    """Edit should be allowed for non-Python files."""
    # Test various non-Python files
    files_to_test = [
        tmp_path / "config.json",
        tmp_path / "README.md",
        tmp_path / "setup.cfg",
        tmp_path / "pyproject.toml",
    ]
    
    for file_path in files_to_test:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("content")
        
        # Run hook
        output = run_hook("Edit", {"file_path": str(file_path)})
        
        # Assert allowed
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow", \
            f"Should allow editing {file_path.name}"


def test_allow_non_edit_tools():
    """Hook should allow all non-Edit tools."""
    # Test various other tools
    tools_to_test = ["Read", "Write", "Bash", "Glob", "Grep"]
    
    for tool_name in tools_to_test:
        output = run_hook(tool_name, {"file_path": "/some/path.py"})
        
        # Assert allowed
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow", \
            f"Should allow {tool_name} tool"


def test_handles_missing_file_path():
    """Hook should handle missing file_path gracefully."""
    # Run hook without file_path
    output = run_hook("Edit", {})
    
    # Should allow (fail-open for safety)
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_handles_malformed_tool_input():
    """Hook should handle malformed input gracefully."""
    # Run hook with None tool_input
    input_data = {
        "tool_name": "Edit",
        "tool_input": None
    }
    
    result = subprocess.run(
        ["python3", str(HOOK_PATH)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True
    )
    
    output = json.loads(result.stdout)
    
    # Should allow (fail-open for safety)
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_normalizes_mcp_router_prefix():
    """Hook should handle mcp__router__ prefixed tool names."""
    # Test with MCP router prefix
    output = run_hook("mcp__router__serena__edit_file", {"file_path": "/tmp/foo.py"})
    
    # Should still apply logic (in this case, deny since no test exists)
    assert "hookSpecificOutput" in output
    assert "permissionDecision" in output["hookSpecificOutput"]


def test_test_file_discovery_from_nested_path(tmp_path):
    """Test discovery should work for nested implementation files."""
    # Setup: Create nested implementation file
    impl_file = tmp_path / "lib" / "subdir" / "module.py"
    impl_file.parent.mkdir(parents=True)
    impl_file.write_text("def func(): pass")
    
    # Create corresponding test
    test_file = tmp_path / "tests" / "test_module.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_func(): pass")
    
    # Run hook
    output = run_hook("Edit", {"file_path": str(impl_file)})
    
    # Assert allowed
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
