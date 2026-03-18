#!/usr/bin/env python3
"""PreToolUse hook — enforce dispatch protocol for Task() calls.

When an agent calls Task(), this hook calls prepare_dispatch() on the
controller to register the subagent before allowing the call through.
The full dispatch state (agent_id, briefing, role) is returned via
additionalContext so the subagent starts with its identity and protocol.
"""

import json
import socket
import sys

DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = 7523


def call_router(tool_name: str, args: dict = None, timeout: float = 5.0) -> dict | None:
    """Call router tool via TCP/JSON-RPC. Unwraps MCP content envelope."""
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
            result = response.get("result", {})
            # Unwrap MCP content envelope
            if isinstance(result, dict) and "content" in result:
                content = result["content"]
                if content and isinstance(content[0], dict):
                    text = content[0].get("text", "")
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return {"text": text}
            return result
    except Exception:
        return None


def allow(reason: str = "", additional_context: str = "") -> dict:
    """Return allow decision, optionally with additionalContext."""
    result = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
    if reason:
        result["hookSpecificOutput"]["permissionDecisionReason"] = reason
    if additional_context:
        result["hookSpecificOutput"]["additionalContext"] = additional_context
    return result


def block(reason: str) -> dict:
    """Return block decision."""
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "block", "permissionDecisionReason": reason}}


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return

    tool_name = input_data.get("toolName", "")

    # Only intercept Task and Agent tool calls
    if tool_name not in ("Task", "Agent"):
        print(json.dumps(allow()))
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
        # Return full dispatch state as JSON in additionalContext
        dispatch_state = json.dumps({
            "agent_id": result.get("agent_id"),
            "briefing": result.get("briefing", ""),
            "agent_type": result.get("agent_type", agent_type),
        })
        print(json.dumps(allow(
            reason=f"Agent {result.get('agent_id', '?')} registered via prepare_dispatch",
            additional_context=dispatch_state,
        )))
    else:
        # Graceful degradation — don't break spawning if daemon is down
        print(json.dumps(allow("prepare_dispatch unavailable, allowing through")))


if __name__ == "__main__":
    main()
