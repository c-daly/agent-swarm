#!/usr/bin/env python3
"""
Post-task hook: Automatically track subagent completion.

Runs after Task tool completes to log token usage and update metrics.
"""

import sys
import json
import re
from pathlib import Path
from datetime import datetime

STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"
SUBAGENT_METRICS = STATE_DIR / "subagent_metrics.json"

def load_metrics():
    """Load existing subagent metrics."""
    if SUBAGENT_METRICS.exists():
        try:
            return json.loads(SUBAGENT_METRICS.read_text())
        except:
            pass

    # Initialize structure
    return {}

def save_metrics(metrics):
    """Save subagent metrics."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SUBAGENT_METRICS.write_text(json.dumps(metrics, indent=2))

def extract_agent_info(tool_output):
    """Extract agent ID and type from Task tool output."""
    # Look for agent ID in output (format: "Agent <id>: ...")
    # Or task ID from system messages

    # Try to find agent ID
    agent_id_match = re.search(r'Agent ([a-f0-9]{7,})', tool_output)
    if not agent_id_match:
        agent_id_match = re.search(r'task_id["\s:]+([a-f0-9-]+)', tool_output)

    if not agent_id_match:
        return None, None

    agent_id = agent_id_match.group(1)

    # Try to find agent type
    type_match = re.search(r'subagent[_\s]type["\s:]+([a-zA-Z0-9_-]+)', tool_output, re.IGNORECASE)
    agent_type = type_match.group(1) if type_match else "unknown"

    return agent_id, agent_type

def track_subagent(agent_id, agent_type):
    """Track a completed subagent."""
    metrics = load_metrics()

    # Create entry for this agent
    if agent_id not in metrics:
        metrics[agent_id] = {
            "agent_type": agent_type,
            "first_seen": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "completions": 0
        }

    # Update
    metrics[agent_id]["last_updated"] = datetime.now().isoformat()
    metrics[agent_id]["completions"] += 1

    save_metrics(metrics)

def main():
    """Post-task hook main."""
    try:
        # Read hook input
        input_data = json.loads(sys.stdin.read())
    except:
        # No input or invalid JSON - allow
        print(json.dumps({"hookSpecificOutput": {}}))
        return

    tool_name = input_data.get("tool_name", "")
    tool_output = input_data.get("tool_output", {})

    # Only track Task tool completions
    if tool_name != "Task":
        print(json.dumps({"hookSpecificOutput": {}}))
        return

    # Extract agent info from output
    output_str = json.dumps(tool_output)
    agent_id, agent_type = extract_agent_info(output_str)

    if agent_id and agent_type:
        try:
            track_subagent(agent_id, agent_type)
        except Exception as e:
            # Don't fail the hook if tracking fails
            pass

    # Always allow (this is post-task, just for logging)
    print(json.dumps({"hookSpecificOutput": {}}))

if __name__ == "__main__":
    main()
