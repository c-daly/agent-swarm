#!/usr/bin/env python3
"""PreToolUse hook for Task tool — thin client to router enforcement.

All enforcement logic lives in the router (router__check_task_enforcement).
This hook just forwards the tool_input and relays the decision.
If the router is unreachable, fail-closed (block the call).
"""

import json
import os
import socket
import sys


DAEMON_PORT = int(os.environ.get("DAEMON_PORT", "7523"))


def _call_router(tool_input: dict) -> dict:
    """Call router's check_task_enforcement tool."""
    port = DAEMON_PORT

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3.0)
            s.connect(("127.0.0.1", port))

            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "router__check_task_enforcement",
                    "arguments": {"tool_input": tool_input, "_caller": "main_agent"},
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
                return {"decision": "deny", "reason": "[ROUTER_DOWN] No response from router."}

            response = json.loads(data.decode().strip())

            if "error" in response:
                return {"decision": "deny", "reason": f"[ROUTER_ERROR] {response['error']}"}

            result = response.get("result", {})
            # Unwrap MCP content envelope
            if isinstance(result, dict) and "content" in result:
                content = result["content"]
                if content and isinstance(content[0], dict):
                    text = content[0].get("text", "")
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        pass
            if isinstance(result, dict) and "decision" in result:
                return result
            return {"decision": "deny", "reason": "[ROUTER_ERROR] Unexpected response format."}

    except (socket.timeout, socket.error, json.JSONDecodeError) as e:
        return {"decision": "deny", "reason": f"[ROUTER_DOWN] {e}"}


def allow(reason: str = "") -> dict:
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }
    if reason:
        result["hookSpecificOutput"]["permissionDecisionReason"] = reason
    return result


def deny(reason: str) -> None:
    """Block tool via exit code 2."""
    print(reason, file=sys.stderr)
    sys.exit(2)


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps(allow()))
        return

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Task":
        print(json.dumps(allow()))
        return

    tool_input = input_data.get("tool_input", {})
    result = _call_router(tool_input)

    if result.get("decision") == "allow":
        print(json.dumps(allow()))
    else:
        deny(result.get("reason", "[BLOCKED] Task call denied by router."))


if __name__ == "__main__":
    main()
