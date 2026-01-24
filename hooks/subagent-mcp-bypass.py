#!/usr/bin/env python3
"""
Subagent MCP bypass hook.

Auto-approves MCP tool calls from subagents to bypass the "prompts unavailable"
permission denial. This allows subagents to use MCP tools autonomously.

Uses the correct hookSpecificOutput format with permissionDecision: "allow".
"""
import json
import sys

# Tools that should NOT be auto-approved (security/safety)
EXCLUDED_TOOLS = {
    # System-level tools that need explicit permission
    "execute_shell_command",
    "bash",
    "browser_run_code",
}


def should_auto_approve(tool_name: str) -> bool:
    """Check if this MCP tool should be auto-approved for subagents.

    Returns True for most MCP tools, False for dangerous ones.
    """
    # Only handle MCP tools
    if not tool_name.startswith("mcp__"):
        return False

    # Check exclusions by looking for dangerous tool suffixes
    for excluded in EXCLUDED_TOOLS:
        if tool_name.endswith(f"__{excluded}"):
            return False

    return True


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        # Invalid input, allow normal flow
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    agent_id = input_data.get("agentId")

    # Only apply to subagent calls
    if not agent_id:
        sys.exit(0)

    # Check if we should auto-approve this tool
    if not should_auto_approve(tool_name):
        sys.exit(0)

    # Auto-approve the MCP tool using correct hookSpecificOutput format
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": f"Auto-approved for subagent {agent_id}"
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
