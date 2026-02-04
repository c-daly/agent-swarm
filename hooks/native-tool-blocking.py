#!/usr/bin/env python3
"""Enforce routing: Bash filtering + subagent sandboxing.

Native tool blocking (Read, Write, Edit, Glob, Grep, etc.) is handled
by permissions.deny in .claude/settings.json. This hook only handles:

1. Bash filtering for subagents: only mcp-call commands allowed
2. Subagent sandboxing: force subagents through Bash(mcp-call) only

Main agents can use Bash freely (for git, pytest, etc.).
Subagents must use Bash(mcp-call ...) which routes through the router.
Both paths enforce permissions via the router's permissions.yaml.
"""
import json
import sys
from pathlib import Path

# Dynamically resolve mcp-call path relative to this script
PLUGIN_ROOT = Path(__file__).parent.parent
MCP_CALL_PATH = str(PLUGIN_ROOT / "bin" / "mcp-call")

# Claude Code system/meta tools — infrastructure, not file/code operations.
SYSTEM_TOOLS = {
    "Task", "TaskOutput", "TaskStop",
    "TaskCreate", "TaskGet", "TaskUpdate", "TaskList",
    "TodoWrite",
    "AskUserQuestion",
    "Skill",
    "KillShell",
    "EnterPlanMode", "ExitPlanMode",
    "ToolSearch",
}


def allow(reason: str = ""):
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
    """Block tool via exit code 2 (reliable blocking)."""
    print(reason, file=sys.stderr)
    sys.exit(2)


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps(allow()))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    agent_id = input_data.get("agentId") or input_data.get("agent_id")
    is_subagent = bool(agent_id)

    # --- Subagent handling ---
    if is_subagent:
        # Subagents can only use system tools or Bash(mcp-call)
        if tool_name in SYSTEM_TOOLS:
            print(json.dumps(allow("Subagent system tool")))
            return
        
        if tool_name == "Bash":
            cmd = tool_input.get("command", "").strip()
            # Allow mcp-call commands (check both short and full path)
            if cmd.startswith("mcp-call") or cmd.startswith(MCP_CALL_PATH):
                print(json.dumps(allow("Subagent mcp-call")))
                return
            # Block all other Bash commands for subagents
            block(
                f"[SUBAGENT BLOCKED] Bash command not allowed. "
                f"Use mcp-call: mcp-call <tool> '<json_args>'"
            )
            return
        
        # Block all other tools for subagents
        block(
            f"[SUBAGENT BLOCKED] '{tool_name}' not allowed for subagents. "
            f"Use mcp-call via Bash: mcp-call <tool> '<json_args>'"
        )
        return

    # --- Main agent: allow everything ---
    # Native tool blocking is handled by settings.json deny list
    # Bash commands are allowed (git, pytest, etc.)
    print(json.dumps(allow()))


if __name__ == "__main__":
    main()
