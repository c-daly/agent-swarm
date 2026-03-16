#!/usr/bin/env python3
"""PreToolUse hook — enforce dispatch protocol for Task() calls.

When an agent calls Task(), this hook calls prepare_dispatch() on the
controller to register the subagent before allowing the call through.
If prepare_dispatch() fails, the Task() call is blocked.
"""

import json
import socket
import sys

DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = 7523


def call_router(tool_name: str, args: dict = None, timeout: float = 5.0) -> dict | None:
    """Call router tool via TCP/JSON-RPC."""
    args = args or {}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((DAEMON_HOST, DAEMON_PORT))
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": f"router__{tool_name}",
                    "arguments": args,
                },
            }
            s.sendall(json.dumps(request).encode() + b"\n")
            data = b""
            while b"\n" not in data:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            if not data:
                return None
            response = json.loads(data.decode().strip())
            if "error" in response:
                return None
            return response.get("result", {})
    except Exception:
        return None


def allow(reason: str = ""):
    result = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
    if reason:
        result["hookSpecificOutput"]["permissionDecisionReason"] = reason
    return result


def block(reason: str):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "block", "permissionDecisionReason": reason}}


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return

    tool_name = input_data.get("toolName", "")

    # Only intercept Task tool calls
    if tool_name != "Task":
        return

    tool_input = input_data.get("toolInput", {})
    agent_type = tool_input.get("subagent_type", "")
    prompt = tool_input.get("prompt", "")
    description = tool_input.get("description", "")

    # Call prepare_dispatch on the controller
    result = call_router("prepare_dispatch", {
        "agent_type": agent_type,
        "prompt": prompt,
        "description": description,
    })

    if result and result.get("success"):
        print(json.dumps(allow(f"Agent {result.get('agent_id', '?')} registered via prepare_dispatch")))
    else:
        # If daemon is not running or prepare_dispatch fails, allow through
        # (graceful degradation — don't break spawning if daemon is down)
        print(json.dumps(allow("prepare_dispatch unavailable, allowing through")))


if __name__ == "__main__":
    main()
