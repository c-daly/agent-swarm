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

def check_new_plugins():
    """Check for and auto-document new plugins (every 10 tool uses)."""
    import subprocess
    from pathlib import Path

    # Track check count
    state_file = Path.home() / ".claude/plugins/agent-swarm/.state/plugin_check_count.txt"
    state_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        count = int(state_file.read_text()) if state_file.exists() else 0
    except:
        count = 0

    count += 1

    # Check every 10 tools
    if count % 10 == 0:
        try:
            doc_script = Path(__file__).parent.parent / "scripts/document_plugins.py"
            result = subprocess.run(
                ["python3", str(doc_script)],
                capture_output=True,
                text=True,
                timeout=5
            )

            # If new plugins were documented, return message
            if "new plugin" in result.stdout.lower():
                state_file.write_text("0")  # Reset counter
                return result.stdout
        except:
            pass

    state_file.write_text(str(count))
    return None

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
    tool_input = input_data.get("tool_input", {})
    tool_output = input_data.get("tool_output", {})

    # Track Task tool completions
    if tool_name == "Task":
        # Extract agent info from input and output
        # subagent_type is in tool_input, agent_id is in tool_output
        subagent_type = tool_input.get("subagent_type", "unknown")
        
        output_str = json.dumps(tool_output)
        agent_id, _ = extract_agent_info(output_str)

        if agent_id:
            try:
                track_subagent(agent_id, subagent_type)
            except Exception as e:
                # Don't fail the hook if tracking fails
                pass

    # Check for new plugins periodically
    plugin_msg = None
    try:
        plugin_msg = check_new_plugins()
    except:
        pass

    # Return message if new plugins found
    output = {"hookSpecificOutput": {}}
    if plugin_msg:
        output["hookSpecificOutput"]["message"] = f"📦 {plugin_msg}"

    print(json.dumps(output))

if __name__ == "__main__":
    main()
