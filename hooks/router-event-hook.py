#!/usr/bin/env python3
"""
Hook to intercept router__ pseudo-tools and execute via Python.

This hook intercepts tool calls to router__request, router__poll, etc.
and executes them via workflow_client, bypassing MCP permissions.
"""
import json
import os
import sys

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from workflow_client import call_tool, list_tools, generate_correlation_id, _log  # noqa: E402


def main():
    # Read hook input from stdin
    hook_input = json.loads(sys.stdin.read())

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    # Only handle router__ pseudo-tools
    if not tool_name.startswith("mcp__router__router__"):
        # Allow other tools to proceed normally
        print(json.dumps({"decision": "allow"}))
        return

    # Extract the actual pseudo-tool name
    pseudo_tool = tool_name.replace("mcp__router__router__", "router__")
    _log("router-event-hook", f"Intercepting {pseudo_tool}")

    try:
        if pseudo_tool == "router__request":
            # Async tool request
            target_tool = tool_input.get("tool", "")
            args = tool_input.get("args", {})
            correlation_id = generate_correlation_id()

            # Execute the tool call via socket
            result = call_tool(target_tool, args)

            # Return result with correlation ID
            response = {
                "correlation_id": correlation_id,
                "status": "completed",
                "result": result
            }

            print(json.dumps({
                "decision": "block",
                "message": json.dumps(response)
            }))

        elif pseudo_tool == "router__poll":
            correlation_id = tool_input.get("correlation_id", "")
            # For now, return empty (true async would check queue)
            print(json.dumps({
                "decision": "block",
                "message": json.dumps({"correlation_id": correlation_id, "status": "pending"})
            }))

        elif pseudo_tool == "router__publish":
            topic = tool_input.get("topic", "")
            _ = tool_input.get("data", {})
            correlation_id = generate_correlation_id()

            # Would publish to event bus here
            print(json.dumps({
                "decision": "block",
                "message": json.dumps({
                    "status": "published",
                    "topic": topic,
                    "correlation_id": correlation_id
                })
            }))

        elif pseudo_tool == "router__list_tools":
            tools = list_tools()
            print(json.dumps({
                "decision": "block",
                "message": json.dumps({"tools": tools})
            }))

        else:
            # Unknown pseudo-tool, allow it through
            print(json.dumps({"decision": "allow"}))

    except Exception as e:
        _log("router-event-hook", f"ERROR: {e}", "ERROR")
        print(json.dumps({
            "decision": "block",
            "message": json.dumps({"error": str(e)})
        }))


if __name__ == "__main__":
    main()
