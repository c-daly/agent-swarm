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

ALWAYS_ALLOW = False  # Set to True to bypass all tool blocking (debug use only)

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
    result = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
    if reason:
        result["hookSpecificOutput"]["permissionDecisionReason"] = reason
    return result


def block(reason: str):
    """Block tool via exit code 2 (reliable blocking)."""
    print(reason, file=sys.stderr)
    sys.exit(2)


def _is_clean_mcp_call(cmd: str) -> bool:
    """True iff `cmd` is a single mcp-call invocation with no shell chaining,
    piping, command substitution, or redirection OUTSIDE its quoted arguments.

    The router only ever sees the inner native__* call mcp-call forwards;
    anything the outer shell could additionally run (``mcp-call ... ; rm -rf``)
    never reaches the router's permission check, so it must be rejected here.
    A ``&&`` inside the quoted JSON argument is the inner command (which the
    router does police) and is fine.
    """
    # Newline/CR injection: shlex treats \n as whitespace and silently drops
    # it, so `mcp-call ...\nrm -rf /` would tokenize clean while the shell runs
    # both lines. Reject outright.
    if "\n" in cmd or "\r" in cmd:
        return False

    import shlex

    # backtick command substitution outside single quotes -> reject.
    # Escape-aware: a backslash escapes the next char outside single quotes, so
    # \" does not flip the double-quote state. A backtick is active substitution
    # anywhere except inside single quotes (incl. inside double quotes).
    in_s = in_d = escape = False
    for ch in cmd:
        if escape:
            escape = False
            continue
        if ch == "\\" and not in_s:
            escape = True
            continue
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == "`" and not in_s:
            return False
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return False
    if not tokens:
        return False
    first = tokens[0]
    if first != "mcp-call" and not first.endswith("/mcp-call"):
        return False
    # any unquoted shell operator / grouping token -> reject (chaining, pipes,
    # subshells, $()/<() substitution and redirects all surface as these)
    for tok in tokens[1:]:
        if tok and set(tok) <= set("&|;()<>"):
            return False
    return True


def main():
    if ALWAYS_ALLOW:
        print(json.dumps(allow("ALWAYS_ALLOW bypass")))
        return
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

    # Rule 2: a single, un-chained mcp-call → allow (router access path). A
    # compound command (mcp-call ... ; rm -rf) must NOT pass here: the extra
    # commands would run in the agent's shell, never reaching the router.
    if tool_name == "Bash":
        cmd = tool_input.get("command", "").strip()
        if _is_clean_mcp_call(cmd):
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
            block(f"[BLOCKED] '{tool_name}' blocked. Use mcp__router__{analogue} instead.")
        return

    # Rule 4: No analogue → allow through (controller decides)
    print(json.dumps(allow("No router analogue")))


if __name__ == "__main__":
    main()
