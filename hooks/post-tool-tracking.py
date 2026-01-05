#!/usr/bin/env python3
"""
Post-tool tracking hook for agent-swarm plugin.

Tracks:
1. Subagent spawns (Task tool completions)
2. Function signature changes (Edit/Write tools)
"""

import sys
import json
import re
from datetime import datetime
from pathlib import Path

# Configuration
METRICS_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/subagent_metrics.json"
STATE_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"

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

def extract_agent_id(output: str) -> str | None:
    """Extract agent_id from Task tool output using regex."""
    # Pattern: agent_id: <id> or "agent_id": "<id>"
    patterns = [
        r'agentId["\']?\s*:\s*["\']?([a-zA-Z0-9_-]+)',
        r'Agent ID:\s*([a-zA-Z0-9_-]+)',
        r'Spawned:\s*([a-zA-Z0-9_-]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            return match.group(1)

    return None

def track_subagent(tool_input: dict, tool_output: str) -> None:
    """Track subagent spawn from Task tool."""
    # Extract agent_id from output
    agent_id = extract_agent_id(tool_output)

    if not agent_id:
        # No agent_id found, skip silently
        return

    # Load existing metrics
    metrics = load_json(METRICS_FILE)

    # Get agent type from input
    agent_type = tool_input.get("subagent_type", "unknown")

    # Store metric
    metrics[agent_id] = {
        "spawned_at": datetime.now().isoformat(),
        "agent_type": agent_type,
        "status": "running",
        "prompt": tool_input.get("prompt", "")[:100]  # First 100 chars
    }

    save_json(METRICS_FILE, metrics)

def detect_signature_change(tool_name: str, tool_input: dict) -> None:
    """Detect function signature changes and store reminder."""
    if tool_name not in {"Edit", "Write", "NotebookEdit"}:
        return

    # Check for signature-like patterns in the content
    content = tool_input.get("new_string", "") or tool_input.get("content", "")

    # Patterns that indicate function/method signatures
    signature_patterns = [
        r'def\s+\w+\s*\([^)]*\)',  # Python
        r'function\s+\w+\s*\([^)]*\)',  # JavaScript
        r'(public|private|protected)?\s*\w+\s+\w+\s*\([^)]*\)',  # Java/TypeScript
        r'=>\s*\(',  # Arrow functions
    ]

    has_signature = any(re.search(p, content) for p in signature_patterns)

    if not has_signature:
        return

    # Load state and add reminder
    state = load_json(STATE_FILE)

    reminders = state.get("signature_change_reminders", [])
    file_path = tool_input.get("file_path", "unknown")

    reminder = {
        "file": file_path,
        "timestamp": datetime.now().isoformat(),
        "tool": tool_name
    }

    # Avoid duplicates
    if not any(r["file"] == file_path for r in reminders[-5:]):
        reminders.append(reminder)
        # Keep only last 10 reminders
        state["signature_change_reminders"] = reminders[-10:]
        save_json(STATE_FILE, state)

def main():
    # Read input from stdin
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        # Invalid input, return empty response
        print(json.dumps({}))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    tool_output = str(input_data.get("tool_output", ""))

    # Track subagent spawns
    if tool_name == "Task":
        track_subagent(tool_input, tool_output)

    # Detect signature changes
    detect_signature_change(tool_name, tool_input)

    # PostToolUse hooks don't need to return anything
    print(json.dumps({}))

if __name__ == "__main__":
    main()
