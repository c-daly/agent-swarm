#!/usr/bin/env python3
"""
Manual test script for MCP Router.

This script tests the router mechanics without requiring a real MCP server.
For full MCP integration, the forwarding logic needs to implement the proper
MCP handshake protocol (initialize, etc.).

Usage:
    python scripts/test_router_manual.py
"""

import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from mcp_router import MCPRouter, RouterResponse  # noqa: E402


def test_registration():
    """Test server registration."""
    print("=== Testing Registration ===")
    router = MCPRouter()

    # Register Serena
    result = router.register_server(
        name="serena",
        command=["uvx", "--from", "git+https://github.com/oraios/serena", "serena", "start-mcp-server"],
        tool_prefix="serena"
    )
    print(f"Registered: {result}")

    # List servers
    servers = router.list_servers()
    print(f"Servers: {servers}")

    return router


def test_response_envelope():
    """Test RouterResponse envelope."""
    print("\n=== Testing Response Envelope ===")

    response = RouterResponse(
        summary="Found 5 Python files matching pattern",
        full={
            "result": {
                "files": [
                    "lib/mcp_router.py",
                    "lib/state_manager.py",
                    "lib/mcp_bridge.py",
                    "scripts/test_router_manual.py",
                    "tests/test_mcp_router.py"
                ]
            }
        },
        correlation_id="req-abc123def456"
    )

    print(f"repr(response):\n{repr(response)}\n")
    print(f"str(response):\n{str(response)}\n")
    print(f"Direct .full access: {response.full}")


def test_hooks():
    """Test hook functionality."""
    print("\n=== Testing Hooks ===")
    router = MCPRouter()

    # Add logging hooks
    request_log = []
    response_log = []

    router.on_request.append(
        lambda dest, tool, args: request_log.append(f"{dest}:{tool}")
    )
    router.on_response.append(
        lambda r: response_log.append(r.correlation_id)
    )

    router.register_server("mock", ["echo", "{}"])

    # Route will fail (no real server) but hooks should fire
    try:
        router.route("mock", "test_tool", {"arg": "value"})
    except Exception as e:
        print(f"Expected error (no real server): {type(e).__name__}")

    print(f"Request hook fired: {request_log}")
    print(f"Response hook fired: {response_log}")


def test_correlation_id():
    """Test correlation ID generation."""
    print("\n=== Testing Correlation IDs ===")
    router = MCPRouter()

    # Same inputs = same ID
    id1 = router._generate_correlation_id("serena", "find_symbol", {"name": "Test"})
    id2 = router._generate_correlation_id("serena", "find_symbol", {"name": "Test"})
    print(f"Same inputs produce same ID: {id1 == id2} ({id1})")

    # Different inputs = different ID
    id3 = router._generate_correlation_id("serena", "find_symbol", {"name": "Other"})
    print(f"Different inputs produce different ID: {id1 != id3}")


def test_fallback_summary():
    """Test fallback summary generation."""
    print("\n=== Testing Fallback Summary ===")
    router = MCPRouter()

    test_cases = [
        {"error": "Something went wrong"},
        {"result": [1, 2, 3, 4, 5]},
        {"result": {"name": "test", "value": 42}},
        {"result": "Hello world"},
    ]

    for response in test_cases:
        summary = router._fallback_summary(response)
        print(f"  {response} -> {summary}")


def main():
    print("MCP Router Manual Test\n")

    test_registration()
    test_response_envelope()
    test_hooks()
    test_correlation_id()
    test_fallback_summary()

    print("\n" + "="*50)
    print("All manual tests completed!")
    print("\nNOTE: Full MCP integration requires implementing proper")
    print("MCP protocol handshake in _forward_to_server method.")
    print("="*50)


if __name__ == "__main__":
    main()
