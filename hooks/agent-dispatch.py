#!/usr/bin/env python3
"""PreToolUse hook — enforce dispatch protocol for Task() calls.

When an agent calls Task(), this hook calls prepare_dispatch() on the
controller to register the subagent before allowing the call through.
The full dispatch state (agent_id, briefing, role) is returned via
additionalContext so the subagent starts with its identity and protocol.
"""

import json
import os
import re
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
    """Return a deny decision.

    PreToolUse honors only "allow" | "deny" | "ask" for permissionDecision;
    the earlier "block" value was silently ignored, so an unbriefed spawn was
    never actually stopped. "deny" blocks the Task call and surfaces the
    reason (the briefing to prepend) back to the caller.
    """
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}


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

    briefing_marker = "## Your Agent Identity"

    # A prompt that already carries the briefing marker was prepared by an earlier
    # register_agent / prepare_dispatch call -- either the register+prepend spawn
    # protocol, or a prior block the spawner has now satisfied. prepare_dispatch
    # mints a fresh agent_id on every call, so calling it again would register a
    # SECOND identity and leave the first as a ghost in the daemon registry. Reuse
    # the agent_id already embedded in the briefing and allow without re-registering.
    if prompt and briefing_marker in prompt:
        m = re.search(r"Agent ID:\s*`?([^\s`]+)", prompt)
        agent_id = m.group(1) if m else "?"
        print(json.dumps(allow(
            reason=f"Agent {agent_id} already briefed; allowed without re-registration",
            additional_context=json.dumps({
                "agent_id": agent_id,
                "briefing": "",
                "agent_type": agent_type,
            }),
        )))
        return

    # Unbriefed: register the agent and assemble its briefing, then decide.
    result = call_router("prepare_dispatch", {
        "agent_type": agent_type,
        "prompt": prompt,
        "description": description,
    })

    if result and result.get("success"):
        agent_id = result.get("agent_id", "?")
        briefing = result.get("briefing", "")
        agent_type_result = result.get("agent_type", agent_type)

        enforce = os.environ.get("AGENT_SWARM_BRIEFING_ENFORCE", "block")
        if enforce not in ("block", "warn", "off"):
            print(
                f"WARNING: unrecognized AGENT_SWARM_BRIEFING_ENFORCE={enforce!r}; "
                f"treating as 'block'",
                file=sys.stderr,
            )
            enforce = "block"

        # Single source of truth for the dispatch state, serialized at point of use.
        dispatch_data = {
            "agent_id": agent_id,
            "briefing": briefing,
            "agent_type": agent_type_result,
        }

        if enforce == "off":
            # Legacy passthrough -- no enforcement
            print(json.dumps(allow(
                reason=f"Agent {agent_id} registered via prepare_dispatch",
                additional_context=json.dumps(dispatch_data),
            )))
        elif enforce == "warn":
            warning = (
                f"WARNING: spawn prompt is unbriefed (missing {briefing_marker!r}). "
                f"agent_id={agent_id}."
            )
            print(json.dumps(allow(
                reason=f"Agent {agent_id} registered via prepare_dispatch (unbriefed, warned)",
                additional_context=json.dumps({**dispatch_data, "warning": warning}),
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
