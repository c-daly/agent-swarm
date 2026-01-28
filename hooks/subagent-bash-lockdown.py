#!/usr/bin/env python3
"""
Lock down Bash in subagents to ONLY allow mcp-call.

Subagents must use mcp-call for all external operations.
All other Bash commands are blocked.
"""
import json
import sys

MCP_CALL_PATH = "/home/fearsidhe/.claude/plugins/agent-swarm/bin/mcp-call"


def is_mcp_call(command: str) -> bool:
    """Check if command is mcp-call."""
    command = command.strip()
    return (
        command.startswith("mcp-call ") or
        command.startswith(f"{MCP_CALL_PATH} ") or
        command == "mcp-call" or
        command == MCP_CALL_PATH
    )


def block(reason: str):
    """Block tool by exiting with code 2 (stderr used as message).

    Exit code 2 is the reliable blocking mechanism - JSON deny responses
    are sometimes ignored (Claude Code bug #4669).
    """
    print(reason, file=sys.stderr)
    sys.exit(2)


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    # Claude Code uses camelCase 'agentId'
    agent_id = input_data.get("agentId") or input_data.get("agent_id")

    # Only apply to subagent Bash calls
    if not agent_id:
        sys.exit(0)

    if tool_name != "Bash":
        sys.exit(0)

    command = tool_input.get("command", "")

    if not is_mcp_call(command):
        # Block - only mcp-call allowed
        block(
            "[SUBAGENT LOCKDOWN] Only mcp-call is allowed in subagents. "
            "Use: mcp-call <tool_name> '<json_args>'"
        )

    # Allow mcp-call
    sys.exit(0)


if __name__ == "__main__":
    main()
