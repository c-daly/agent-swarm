#!/usr/bin/env python3
"""Block all tools except router-mediated access.

Whitelist approach:
1. mcp__router__* or mcp__plugin_* tools → allow (going through router)
2. Bash with mcp-call/mcp prefix → allow (subagent access to router)
3. Claude Code system/meta tools → allow (infrastructure, not file ops)
4. Everything else → block

Main agents use mcp__router__* directly.
Subagents use Bash(mcp-call ...) which routes through the router.
Both paths enforce permissions via the router's permissions.yaml.
"""
import json
import sys


MCP_CALL_PATH = "/home/fearsidhe/.claude/plugins/agent-swarm/bin/mcp-call"

# Claude Code system/meta tools — infrastructure, not file/code operations.
# These don't need router mediation because they don't touch files or run code.
SYSTEM_TOOLS = {
    "TaskOutput", "TaskStop",
    "TaskCreate", "TaskGet", "TaskUpdate", "TaskList",
    "TodoWrite",
    "AskUserQuestion",
    "Skill",
    "KillShell",
    "EnterPlanMode", "ExitPlanMode",
    "ToolSearch",
}

# Native Claude Code Task tool is blocked — use mcp__router__native__task instead
# which routes through the router's permission system.
BLOCKED_NATIVE_TOOLS = {"Task"}


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
    # Claude Code passes agentId for subagent tool calls
    agent_id = input_data.get("agentId") or input_data.get("agent_id")
    is_subagent = bool(agent_id)

    # Subagents: ONLY Bash(mcp-call) allowed — no direct stdio router access
    if is_subagent:
        if tool_name == "Bash":
            cmd = tool_input.get("command", "").strip()
            if cmd.startswith("mcp") or cmd.startswith(MCP_CALL_PATH):
                print(json.dumps(allow("Subagent mcp-call")))
                return
        # Allow system tools subagents need (TaskOutput for reporting, etc.)
        if tool_name in SYSTEM_TOOLS:
            print(json.dumps(allow("Subagent system tool")))
            return
        block(
            f"[SUBAGENT BLOCKED] '{tool_name}' not allowed for subagents. "
            f"Use mcp-call via Bash: mcp-call <tool> '<json_args>'"
        )
        return

    # Main agent rules below

    # Rule 0: Block native Task tool — use router-mediated native__task instead
    if tool_name in BLOCKED_NATIVE_TOOLS:
        block(
            f"[BLOCKED] Native '{tool_name}' tool blocked. "
            f"Use mcp__router__native__task to spawn SDK agents through the router."
        )
        return

    # Rule 1: MCP router/plugin tools → allow (router enforces permissions)
    if tool_name.startswith("mcp__router__") or tool_name.startswith("mcp__plugin_"):
        print(json.dumps(allow("Router-mediated tool")))
        return

    # Rule 2: Bash with mcp prefix → allow (mcp-call access to router)
    if tool_name == "Bash":
        cmd = tool_input.get("command", "").strip()
        if cmd.startswith("mcp") or cmd.startswith(MCP_CALL_PATH):
            print(json.dumps(allow("mcp-call")))
            return

    # Rule 3: Claude Code system tools → allow (not file operations)
    if tool_name in SYSTEM_TOOLS:
        print(json.dumps(allow("System tool")))
        return

    # Rule 4: Everything else → block
    block(
        f"[BLOCKED] '{tool_name}' blocked. "
        f"Use mcp__router__* tools (main agent) or mcp-call via Bash (subagent)."
    )


if __name__ == "__main__":
    main()
