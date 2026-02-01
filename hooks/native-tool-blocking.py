#!/usr/bin/env python3
"""Enforce routing: Bash filtering + subagent sandboxing.

Native tool blocking (Read, Write, Edit, Glob, Grep, etc.) is handled
by permissions.deny in .claude/settings.json. This hook only handles:

1. Bash filtering: allow mcp-call commands, block raw file I/O
2. Subagent sandboxing: force subagents through Bash(mcp-call) only

Main agents use mcp__router__* directly (allowed by settings).
Subagents use Bash(mcp-call ...) which routes through the router.
Both paths enforce permissions via the router's permissions.yaml.
"""
import json
import sys


MCP_CALL_PATH = "/home/fearsidhe/.claude/plugins/agent-swarm/bin/mcp-call"

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

    # --- Bash filtering (both main agent and subagents) ---
    if tool_name == "Bash":
        cmd = tool_input.get("command", "").strip()
        if cmd.startswith("mcp") or cmd.startswith(MCP_CALL_PATH):
            print(json.dumps(allow("mcp-call")))
            return
        block(
            f"[BLOCKED] Bash blocked — only mcp-call commands allowed. "
            f"Use mcp__router__native__bash (main agent) or mcp-call via Bash (subagent)."
        )
        return

    # --- Subagent sandboxing ---
    if is_subagent:
        if tool_name in SYSTEM_TOOLS:
            print(json.dumps(allow("Subagent system tool")))
            return
        block(
            f"[SUBAGENT BLOCKED] '{tool_name}' not allowed for subagents. "
            f"Use mcp-call via Bash: mcp-call <tool> '<json_args>'"
        )
        return

    # --- Main agent: everything else allowed (config deny handles native tools) ---
    print(json.dumps(allow()))


if __name__ == "__main__":
    main()
