#!/usr/bin/env python3
"""PreToolUse telemetry hook - records tool call start time.

Stores start_time keyed by tool_name for telemetry-posttool.py to read.
Single-file state replaces the old 3-file (pending/latest/telemetry) approach.
"""

import json
import sys
import time
from pathlib import Path

STATE_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/telemetry_pending.json"


def load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Determine backend
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        backend = parts[1] if len(parts) > 1 else "mcp"
    else:
        backend = "claude-native"

    # Extract subagent info if Task tool
    subagent_type = ""
    if tool_name == "Task":
        subagent_type = tool_input.get("subagent_type", "")

    # Store pending entry keyed by tool_name (latest wins)
    pending = load_json(STATE_FILE)

    # Clean entries older than 5 minutes
    cutoff = time.time() - 300
    pending = {k: v for k, v in pending.items() if v.get("t", 0) > cutoff}

    pending[tool_name] = {
        "t": time.time(),
        "b": backend,
        "s": subagent_type,
    }
    save_json(STATE_FILE, pending)


if __name__ == "__main__":
    main()
