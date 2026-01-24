#!/usr/bin/env python3
"""
Integration test: Route a Serena tool call through the MCP router.

Usage:
    python scripts/test_router_serena.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from mcp_router import MCPRouter  # noqa: E402


def main():
    print("=== MCP Router + Serena Integration Test ===\n")

    router = MCPRouter()

    # Register Serena
    print("Registering Serena...")
    result = router.register_server(
        name="serena",
        command=["uvx", "--from", "git+https://github.com/oraios/serena", "serena", "start-mcp-server"],
        tool_prefix="serena"
    )
    print(f"  {result}\n")

    # Try a simple tool call - list available tools
    print("Calling tools/list through router...")

    # Actually, let's try find_symbol which is a real Serena tool
    print("Calling serena find_symbol tool...")
    response = router.route(
        destination="serena",
        tool_name="find_symbol",
        args={"name_path_pattern": "MCPRouter"}
    )

    print("\nResponse:")
    print(f"  Summary: {response.summary}")
    print(f"  Correlation ID: {response.correlation_id}")
    print("\n  Full response (first 500 chars):")
    import json
    full_str = json.dumps(response.full, indent=2)[:500]
    print(f"  {full_str}")


if __name__ == "__main__":
    main()
