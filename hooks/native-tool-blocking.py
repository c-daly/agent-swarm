#!/usr/bin/env python3
"""Block native tools that have router analogues. Everything else passes through.

Analogue map approach (block-on-hit):
1. mcp__router__* / mcp__plugin_* → allow (already routed)
2. Bash with mcp-call prefix → allow (router access path)
3. Tool in ROUTER_ANALOGUES → block (use router equivalent)
4. Everything else → allow (no analogue, pass through)

This hook is the first gate. Tools that pass through still need
permission from the controller (permissions.yaml).
"""
import json
import os
import sys


MCP_CALL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "mcp-call")

# Native Claude Code tools → router equivalents.
# Tools in this map are BLOCKED — use the router version instead.
# Add new entries as router analogues are built.
ROUTER_ANALOGUES = {
    "Read": "native__read_file",
    "Write": "native__write_file",
    "Edit": "native__edit_file",
    "Glob": "native__glob",
    "Grep": "native__grep",
    "Bash": "native__bash",
    "WebFetch": "native__web_fetch",
    "WebSearch": "native__web_search",
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

    # Rule 1: Router/plugin tools → always allow
    if tool_name.startswith("mcp__router__") or tool_name.startswith("mcp__plugin_"):
        print(json.dumps(allow("Router-mediated")))
        return

    # Rule 2: Bash with mcp-call prefix → allow (router access path)
    if tool_name == "Bash":
        cmd = tool_input.get("command", "").strip()
        if cmd.startswith("mcp-call ") or cmd == "mcp-call" or cmd.startswith(MCP_CALL_PATH):
            print(json.dumps(allow("mcp-call")))
            return

    # Rule 3: Has router analogue → block (force router usage)
    if tool_name in ROUTER_ANALOGUES:
        analogue = ROUTER_ANALOGUES[tool_name]
        agent_id = input_data.get("agentId") or input_data.get("agent_id")
        if agent_id:
            block(
                f"[SUBAGENT BLOCKED] '{tool_name}' not allowed. "
                f"Use mcp-call via Bash: mcp-call {analogue} '<json_args>'"
            )
        else:
            block(
                f"[BLOCKED] '{tool_name}' blocked. "
                f"Use mcp__router__{analogue} instead."
            )
        return

    # Rule 4: No analogue → allow through (controller decides)
    print(json.dumps(allow("No router analogue")))


if __name__ == "__main__":
    main()
