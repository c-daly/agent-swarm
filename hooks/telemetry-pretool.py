#!/usr/bin/env python3
"""PreToolUse telemetry hook - tracks start of ALL tool calls.

Writes pending request to telemetry system for timing tracking.
Works with telemetry-posttool.py to complete the entry.
"""

import sys
import json
import hashlib
import time
from pathlib import Path

# Shared state files
PENDING_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/telemetry_pending.json"
TELEMETRY_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/telemetry.json"


def load_json(path: Path) -> dict:
    """Load JSON file safely."""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_json(path: Path, data: dict) -> None:
    """Save JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def generate_request_id(tool_name: str, tool_input: dict) -> str:
    """Generate a unique-ish ID for this request."""
    # Use tool name + hash of input + timestamp
    content = json.dumps({"tool": tool_name, "input": tool_input}, sort_keys=True)
    hash_part = hashlib.sha256(content.encode()).hexdigest()[:8]
    return f"req-{int(time.time() * 1000)}-{hash_part}"


def extract_subagent_type(tool_name: str, tool_input: dict) -> str:
    """Extract subagent type if this is a Task tool call."""
    if tool_name == "Task":
        return tool_input.get("subagent_type", "unknown")
    return ""


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        # Invalid input, allow and skip tracking
        print(json.dumps({"decision": "allow"}))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Generate request ID
    request_id = generate_request_id(tool_name, tool_input)

    # Extract metadata
    subagent_type = extract_subagent_type(tool_name, tool_input)

    # Determine backend (MCP tools have prefixes)
    if tool_name.startswith("mcp__"):
        # mcp__plugin_serena_serena__find_symbol -> serena
        parts = tool_name.split("__")
        backend = parts[1] if len(parts) > 1 else "mcp"
    else:
        backend = "claude-native"

    # Store pending request
    pending = load_json(PENDING_FILE)
    pending[request_id] = {
        "tool": tool_name,
        "backend": backend,
        "subagent_type": subagent_type,
        "start_time": time.time(),
        "input_summary": str(tool_input)[:200]  # First 200 chars for debugging
    }

    # Clean old pending requests (older than 5 minutes)
    cutoff = time.time() - 300
    pending = {k: v for k, v in pending.items() if v.get("start_time", 0) > cutoff}

    save_json(PENDING_FILE, pending)

    # Store request_id in a way PostToolUse can find it
    # Use a separate "latest" file keyed by tool_name
    latest_file = Path.home() / ".claude/plugins/agent-swarm/.state/telemetry_latest.json"
    latest = load_json(latest_file)
    latest[tool_name] = request_id
    save_json(latest_file, latest)

    # Allow the tool to proceed (we're just tracking, not blocking)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow"
        }
    }))


if __name__ == "__main__":
    main()
