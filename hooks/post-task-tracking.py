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

try:
    from hook_logging import log_error, log_warning, log_info, log_debug, ConfigError, StateError
except ImportError:
    # Fallback: define minimal logging functions
    def log_error(msg, **kw): pass
    def log_warning(msg, **kw): pass
    def log_info(msg, **kw): pass
    def log_debug(msg, **kw): pass
    class ConfigError(Exception): pass
    class StateError(Exception): pass

# Import workflow client for state tracking
try:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
    import workflow_client
    HAS_WORKFLOW_CLIENT = True
except ImportError:
    HAS_WORKFLOW_CLIENT = False
STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"
# DISABLED: No longer writing subagent metrics
# SUBAGENT_METRICS = STATE_DIR / "subagent_metrics.json"
SUBAGENT_METRICS = None

def load_metrics():
    """Load existing subagent metrics."""
    if SUBAGENT_METRICS.exists():
        try:
            return json.loads(SUBAGENT_METRICS.read_text())
        except Exception as e:
            log_warning(f"Caught exception: {e}")

    # Initialize structure
    return {}

def save_metrics(metrics):
    """Save subagent metrics."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SUBAGENT_METRICS.write_text(json.dumps(metrics, indent=2))

def extract_agent_info(tool_output):
    """Extract agent ID and type from Task tool output."""
    # Look for agent ID in output
    # Formats:
    #   - "agentId: abc1234" (async agents)
    #   - "Agent abc1234: ..." (older format)
    #   - "task_id: abc1234" (task output format)

    # Try agentId: format first (most common)
    agent_id_match = re.search(r'agentId:\s*([a-f0-9]{7,})', tool_output, re.IGNORECASE)
    
    # Fall back to other formats
    if not agent_id_match:
        agent_id_match = re.search(r'Agent\s+([a-f0-9]{7,})', tool_output)
    if not agent_id_match:
        agent_id_match = re.search(r'task_id["\s:]+([a-f0-9-]+)', tool_output)

    if not agent_id_match:
        return None, None

    agent_id = agent_id_match.group(1)

    # Try to find agent type (not in output, will be set from tool_input)
    type_match = re.search(r'subagent[_\s]type["\s:]+([a-zA-Z0-9_:-]+)', tool_output, re.IGNORECASE)
    agent_type = type_match.group(1) if type_match else "unknown"

    return agent_id, agent_type

def track_subagent(agent_id, agent_type, prompt=""):
    """Track a spawned subagent in workflow state."""
    # Update workflow state (survives compaction)
    if HAS_WORKFLOW_CLIENT:
        try:
            if workflow_client.workflow_is_active("iterate"):
                agents = workflow_client.workflow_get_value("iterate", "active_agents") or {}
                agents[agent_id] = {
                    "description": prompt[:100] if prompt else "No description",
                    "type": agent_type,
                    "spawned_at": datetime.now().isoformat()
                }
                workflow_client.workflow_update("iterate", {"active_agents": agents})
                log_info(f"Tracked agent {agent_id} in workflow state")
        except Exception as e:
            log_warning(f"Failed to update workflow state: {e}")

def check_new_plugins():
    """Check for and auto-document new plugins (every 10 tool uses)."""
    import subprocess
    from pathlib import Path

    # Track check count
    state_file = Path.home() / ".claude/plugins/agent-swarm/.state/plugin_check_count.txt"
    state_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        count = int(state_file.read_text()) if state_file.exists() else 0
    except (ValueError, IOError) as e:
        log_debug(f"Failed to read plugin check count: {e}")
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
        except Exception as e:
            log_warning(f"Caught exception: {e}")

    state_file.write_text(str(count))
    return None

def main():
    """Post-task hook main."""
    try:
        # Read hook input
        input_data = json.loads(sys.stdin.read())
    except Exception:
        # No input or invalid JSON - allow
        print(json.dumps({"hookSpecificOutput": {}}))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    tool_output_raw = input_data.get("tool_response", {})

    # DEBUG: Log full structure to understand format
    # DISABLED: Debug logging no longer written to file
    debug_file = None  # STATE_DIR / "post_task_debug.log"
    try:
        with open(debug_file, "a") as f:
            f.write(f"\n[{datetime.now().isoformat()}] FULL INPUT DUMP\n")
            f.write(f"  tool_name: {tool_name}\n")
            f.write(f"  input_data keys: {list(input_data.keys())}\n")
            f.write(f"  tool_output type: {type(tool_output_raw)}\n")
            f.write(f"  tool_output repr: {repr(tool_output_raw)[:500]}\n")
            if isinstance(tool_output_raw, dict):
                f.write(f"  tool_output keys: {list(tool_output_raw.keys())}\n")
                # Check for common fields
                for key in ['agentId', 'agent_id', 'task_id', 'id', 'result', 'output']:
                    if key in tool_output_raw:
                        f.write(f"  Found {key}: {tool_output_raw[key]}\n")
    except Exception as e:
        # Log the exception
        try:
            with open(debug_file, "a") as f:
                f.write(f"  ERROR in debug logging: {e}\n")
        except Exception as e:
            log_warning(f"Caught exception: {e}")

    tool_output = tool_output_raw

    # Track Task tool completions
    if tool_name == "Task":
        # DEBUG: Log to see if hook is running
        # DISABLED: Debug logging no longer written to file
        debug_file = None  # STATE_DIR / "post_task_debug.log"
        try:
            with open(debug_file, "a") as f:
                f.write(f"[{datetime.now().isoformat()}] Task tool detected\n")
                f.write(f"  tool_input keys: {list(tool_input.keys())}\n")
                f.write(f"  tool_response type: {type(tool_output)} keys: {list(tool_output.keys()) if isinstance(tool_output, dict) else len(tool_output)}\n")
        except Exception as e:
            log_warning(f"Caught exception: {e}")

        # Extract agent info from input and output
        # subagent_type is in tool_input, agent_id is in tool_output
        subagent_type = tool_input.get("subagent_type", "unknown")
        
        # Extract agent_id from tool_response
        if isinstance(tool_output, dict):
            # Modern format: dict with 'agentId' field
            agent_id = tool_output.get('agentId', None)
        else:
            # Legacy format: string that needs parsing
            agent_id, _ = extract_agent_info(str(tool_output))

        # DEBUG: Log extraction result
        try:
            with open(debug_file, "a") as f:
                f.write(f"  agent_id extracted: {agent_id}\n")
                f.write(f"  subagent_type: {subagent_type}\n")
        except Exception as e:
            log_warning(f"Caught exception: {e}")

        if agent_id:
            try:
                prompt = tool_input.get("prompt", "")
                track_subagent(agent_id, subagent_type, prompt)
                # DEBUG: Confirm tracking
                try:
                    with open(debug_file, "a") as f:
                        f.write(f"  ✅ Tracked successfully\n")
                except Exception as e:
                    log_warning(f"Caught exception: {e}")
            except Exception as e:
                # Don't fail the hook if tracking fails
                try:
                    with open(debug_file, "a") as f:
                        f.write(f"  ❌ Tracking failed: {e}\n")
                except Exception as e:
                    log_warning(f"Caught exception: {e}")

    # Check for new plugins periodically
    plugin_msg = None
    try:
        plugin_msg = check_new_plugins()
    except Exception as e:
        log_warning(f"Caught exception: {e}")

    # Return message if new plugins found
    output = {"hookSpecificOutput": {}}
    if plugin_msg:
        output["hookSpecificOutput"]["message"] = f"📦 {plugin_msg}"

    print(json.dumps(output))

if __name__ == "__main__":
    main()
