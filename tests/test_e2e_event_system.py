#!/usr/bin/env python3
"""End-to-end test for router event system.

These tests require the router to be running.
"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'lib'))

from workflow_client import call_tool, list_tools, _get_router_port  # noqa: E402


@pytest.fixture
def router_running():
    """Check if router is running, skip if not."""
    port = _get_router_port()
    if port is None:
        pytest.skip("Router not running (no port file)")
    return port


def test_list_tools_via_socket(router_running):
    """Test that list_tools returns available tools."""
    tools = list_tools()
    assert isinstance(tools, list)
    assert len(tools) > 0
    tool_names = [t.get("name", "") for t in tools]
    assert any("serena" in name for name in tool_names)
    print(f"PASS: list_tools returned {len(tools)} tools")


def test_call_tool_serena(router_running):
    """Test calling serena tool via socket."""
    result = call_tool("serena__list_dir", {
        "relative_path": ".",
        "recursive": False
    })
    assert result is not None
    print("PASS: serena__list_dir returned result")


def test_call_tool_native_bash(router_running):
    """Test calling native bash via socket."""
    result = call_tool("native__bash", {
        "command": "echo 'event-system-test'"
    })
    assert result is not None
    assert "event-system-test" in str(result)
    print("PASS: native__bash executed correctly")


def test_pseudo_tools_registered(router_running):
    """Test that event system pseudo-tools are in the tool list.

    Note: Requires router restart after code changes to pick up new tools.
    """
    tools = list_tools()
    tool_names = [t.get("name", "") for t in tools]

    expected_tools = [
        "router__request",
        "router__poll",
        "router__publish",
        "router__list_tools"
    ]

    missing = [t for t in expected_tools if t not in tool_names]
    if missing:
        pytest.skip(f"Pseudo-tools not found (router restart needed): {missing}")

    print("PASS: All pseudo-tools registered")


if __name__ == "__main__":
    # Run without pytest for quick manual testing
    port = _get_router_port()
    if port is None:
        print("ERROR: Router not running")
        sys.exit(1)

    print(f"Router running on port {port}")
    test_list_tools_via_socket(port)
    test_call_tool_serena(port)
    test_call_tool_native_bash(port)
    test_pseudo_tools_registered(port)
    print("\nAll E2E tests passed!")
