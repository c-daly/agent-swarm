#!/usr/bin/env python3
"""PreToolUse hook — enforce dispatch protocol for Task() calls.

When an agent calls Task(), this hook calls prepare_dispatch() on the
controller to register the subagent before allowing the call through.
The full dispatch state (agent_id, briefing, role) is returned via
additionalContext so the subagent starts with its identity and protocol.
"""

import json
import os
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

    tool_name = input_data.get("tool_name", "")

    # Only intercept Task and Agent tool calls
    if tool_name not in ("Task", "Agent"):
        print(json.dumps(allow()))
        return

    tool_input = input_data.get("tool_input", {})
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
        agent_id = result.get("agent_id", "?")
        briefing = result.get("briefing", "")
        agent_type_result = result.get("agent_type", agent_type)

        # Enforce briefing delivery
        briefing_marker = "## Your Agent Identity"
        enforce = os.environ.get("AGENT_SWARM_BRIEFING_ENFORCE", "block")

        if briefing_marker in prompt:
            # Prompt already contains the briefing -- allow as-is
            dispatch_state = json.dumps({
                "agent_id": agent_id,
                "briefing": briefing,
                "agent_type": agent_type_result,
            })
            print(json.dumps(allow(
                reason=f"Agent {agent_id} registered via prepare_dispatch",
                additional_context=dispatch_state,
            )))
        elif enforce == "off":
            # Legacy passthrough -- no enforcement
            dispatch_state = json.dumps({
                "agent_id": agent_id,
                "briefing": briefing,
                "agent_type": agent_type_result,
            })
            print(json.dumps(allow(
                reason=f"Agent {agent_id} registered via prepare_dispatch",
                additional_context=dispatch_state,
            )))
        elif enforce == "warn":
            warning = (
                f"WARNING: spawn prompt is unbriefed (missing {briefing_marker!r}). "
                f"agent_id={agent_id}."
            )
            dispatch_state = json.dumps({
                "agent_id": agent_id,
                "briefing": briefing,
                "agent_type": agent_type_result,
                "warning": warning,
            })
            print(json.dumps(allow(
                reason=f"Agent {agent_id} registered via prepare_dispatch (unbriefed, warned)",
                additional_context=dispatch_state,
            )))
        else:
            # Default: block and tell the spawner what to prepend
            reason = (
                f"Spawn blocked: prompt is missing the briefing marker {briefing_marker!r}. "
                f"Prepend the following briefing to the prompt and re-spawn:\n"
                f"agent_id: {agent_id}\n"
                f"{briefing_marker}\n"
                f"{briefing}"
            )
            print(json.dumps(block(reason)))
    else:
        # Graceful degradation -- don't break spawning if daemon is down
        print(json.dumps(allow("prepare_dispatch unavailable, allowing through")))


if __name__ == "__main__":
    main()
