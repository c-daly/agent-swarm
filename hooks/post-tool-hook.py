#!/usr/bin/env python3
"""PostToolUse tracking hook — consolidated.

Tracks:
1. Subagent spawns via workflow state (Task tool completions)
2. New plugin detection (periodic check)

Replaces: post-tool-tracking.py, post-task-tracking.py
"""

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from hook_logging import log_info, log_warning, log_debug
except ImportError:
    def log_info(msg, **kw): pass
    def log_warning(msg, **kw): pass
    def log_debug(msg, **kw): pass

# Import workflow client for state tracking
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

try:
    import workflow_client
    HAS_WORKFLOW_CLIENT = True
except ImportError:
    HAS_WORKFLOW_CLIENT = False

STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"


def extract_agent_id(tool_output) -> str | None:
    """Extract agent ID from Task tool output."""
    if isinstance(tool_output, dict):
        agent_id = tool_output.get("agentId")
        if agent_id:
            return agent_id

    output_str = str(tool_output)
    patterns = [
        r'agentId["\']?\s*:\s*["\']?([a-zA-Z0-9_-]+)',
        r'Agent\s+([a-f0-9]{7,})',
        r'task_id["\s:]+([a-f0-9-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, output_str, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def track_subagent(agent_id: str, agent_type: str, prompt: str) -> None:
    """Track a spawned subagent in workflow state."""
    if not HAS_WORKFLOW_CLIENT:
        return
    try:
        if workflow_client.workflow_is_active("iterate"):
            agents = workflow_client.workflow_get_value("iterate", "active_agents") or {}
            agents[agent_id] = {
                "description": prompt[:100] if prompt else "No description",
                "type": agent_type,
                "spawned_at": datetime.now().isoformat(),
            }
            workflow_client.workflow_update("iterate", {"active_agents": agents})
            log_info(f"Tracked agent {agent_id} in workflow state")
    except Exception as e:
        log_warning(f"Failed to update workflow state: {e}")


def check_new_plugins() -> str | None:
    """Check for and auto-document new plugins (every 10 tool uses)."""
    count_file = STATE_DIR / "plugin_check_count.txt"
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        count = int(count_file.read_text()) if count_file.exists() else 0
    except (ValueError, IOError):
        count = 0

    count += 1

    if count % 10 == 0:
        try:
            doc_script = Path(__file__).parent.parent / "scripts/document_plugins.py"
            result = subprocess.run(
                ["python3", str(doc_script)],
                capture_output=True, text=True, timeout=5,
            )
            if "new plugin" in result.stdout.lower():
                count_file.write_text("0")
                return result.stdout
        except Exception as e:
            log_warning(f"Plugin check failed: {e}")

    count_file.write_text(str(count))
    return None


def main():
    """Post-tool tracking hook main."""
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, Exception):
        print(json.dumps({}))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    tool_output = input_data.get("tool_response", {})

    # Track Task tool completions in workflow state
    if tool_name == "Task":
        agent_id = extract_agent_id(tool_output)
        if agent_id:
            subagent_type = tool_input.get("subagent_type", "unknown")
            prompt = tool_input.get("prompt", "")
            track_subagent(agent_id, subagent_type, prompt)

    # Periodic plugin check
    output = {"hookSpecificOutput": {}}
    try:
        plugin_msg = check_new_plugins()
        if plugin_msg:
            output["hookSpecificOutput"]["message"] = plugin_msg
    except Exception as e:
        log_warning(f"Plugin check failed: {e}")

    print(json.dumps(output))


if __name__ == "__main__":
    main()
