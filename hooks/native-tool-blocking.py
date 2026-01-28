#!/usr/bin/env python3
"""Block all native tools - route through MCP router instead.

All native tools are blocked. Use native__* versions through MCP router.
Exception: Bash is allowed when command starts with 'mcp' (for mcp-call).
"""
import json
import sys

# Native tools that are blocked
NATIVE_TOOLS = {
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "NotebookEdit",
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


def block(reason: str):
    """Block tool using JSON deny response."""
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason
        }
    }
    print(json.dumps(result))
    sys.exit(0)


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps(allow()))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Not a native tool - allow
    if tool_name not in NATIVE_TOOLS:
        print(json.dumps(allow()))
        return

    # Bash with mcp* prefix - allow (for mcp-call)
    if tool_name == "Bash":
        cmd = tool_input.get("command", "").strip()
        mcp_call_path = "/home/fearsidhe/.claude/plugins/agent-swarm/bin/mcp-call"
        if cmd.startswith("mcp") or cmd.startswith(mcp_call_path):
            print(json.dumps(allow("mcp-call")))
            return

    # Block all other native tools
    msg = f"[BLOCKED] '{tool_name}' blocked. Use MCP router (mcp__router__native__*) or mcp-call via Bash."
    block(msg)


if __name__ == "__main__":
    main()
