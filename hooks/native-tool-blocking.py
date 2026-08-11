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
import socket
import sys
import tempfile
import time

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


DAEMON_PORT = int(os.environ.get("DAEMON_PORT", "7523"))
# Per-user AND per-port so one user's (or one daemon's) health can never gate
# another: a cached "down" for port 7523 must not block a session on a
# different DAEMON_PORT. The per-uid suffix also keeps the path out of another
# local user's namespace; combined with O_NOFOLLOW on every open (below), a
# symlink planted at this name cannot redirect our truncating write onto an
# unrelated file.
_PROBE_UID = getattr(os, "getuid", lambda: "u")()
_PROBE_CACHE = os.path.join(
    tempfile.gettempdir(), f"agent-swarm-daemon-probe-{_PROBE_UID}-{DAEMON_PORT}"
)
_PROBE_TTL = 10.0  # seconds
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)  # 0 on platforms without it


def _probe_daemon() -> bool:
    """Return True if the daemon is actually serving MCP on DAEMON_PORT.

    A TCP connect alone is not sufficient. When the daemon crash-loops on an
    import error, a supervisor can still hold the port while nothing ever
    answers — the port looks healthy and every native tool gets redirected to
    a router tool that never registered. So connect *and* require a response.
    """
    try:
        with socket.create_connection(("127.0.0.1", DAEMON_PORT), timeout=0.3) as s:
            s.settimeout(0.5)
            s.sendall(
                json.dumps({"jsonrpc": "2.0", "id": 0, "method": "tools/list", "params": {}}).encode()
                + b"\n"
            )
            return bool(s.recv(1))
    except OSError:
        return False


def _daemon_healthy() -> bool:
    """Cached _probe_daemon(). The hook runs on every tool call; the probe
    costs a round-trip, and a dead daemon costs the full timeout.

    Only a *healthy* result is cached. An unhealthy daemon is re-probed on the
    next call rather than pinned "down" for the TTL, so a recovery is picked up
    immediately instead of blocking every native tool for up to _PROBE_TTL
    after the daemon is already back. The cache file is per-user and per-port
    (see _PROBE_CACHE) and every open uses O_NOFOLLOW so a symlink planted at
    its name can neither be read through nor redirect the truncating write.
    """
    try:
        cached_at = os.path.getmtime(_PROBE_CACHE)
        if time.time() - cached_at < _PROBE_TTL:
            fd = os.open(_PROBE_CACHE, os.O_RDONLY | _O_NOFOLLOW)
            try:
                return os.read(fd, 1) == b"1"
            finally:
                os.close(fd)
    except OSError:
        pass

    healthy = _probe_daemon()
    if healthy:
        try:
            fd = os.open(
                _PROBE_CACHE,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _O_NOFOLLOW,
                0o600,
            )
            try:
                os.write(fd, b"1")
            finally:
                os.close(fd)
        except OSError:
            pass
    return healthy


DAEMON_DOWN_MESSAGE = (
    "[BLOCKED] '{tool_name}' blocked, but the router daemon is NOT REACHABLE on "
    "port {port} — mcp__router__{analogue} does not exist right now, so there is "
    "no replacement tool to use.\n"
    "This is a daemon failure, not a permission problem. Check:\n"
    "  tail -20 $AGENT_SWARM_ROOT/logs/daemon-stderr.log\n"
    "A missing dependency in the daemon's venv is the usual cause; restart with:\n"
    "  $AGENT_SWARM_ROOT/bin/start-daemon --restart\n"
    "Until it is back, MCP tools from other servers (e.g. serena) still work."
)


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

        # Naming a replacement tool that never registered sends the reader
        # hunting through permissions instead of the daemon log. Say so.
        if not _daemon_healthy():
            block(DAEMON_DOWN_MESSAGE.format(
                tool_name=tool_name, port=DAEMON_PORT, analogue=analogue
            ))
            return

        if agent_id:
            block(
                f"[SUBAGENT BLOCKED] '{tool_name}' not allowed. "
                f"Re-run it through mcp-call WITH your --caller-id. You are already "
                f"registered — do NOT call register. "
                f"Example: mcp-call --caller-id={agent_id} {analogue} '<json_args>'"
            )
        else:
            block(
                f"[BLOCKED] '{tool_name}' blocked. Use mcp__router__{analogue} instead.\n"
                "If mcp__router__* is not available in this session, the daemon is up "
                "but the session's MCP connection is stale — sessions connect at "
                "startup and never retry. Reconnect with /mcp, or start a new session."
            )
        return

    # Rule 4: No analogue → allow through (controller decides)
    print(json.dumps(allow("No router analogue")))


if __name__ == "__main__":
    main()
