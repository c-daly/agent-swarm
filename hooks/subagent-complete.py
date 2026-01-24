#!/usr/bin/env python3
"""SubagentStop hook - runs when a subagent completes.

Logs completion and can trigger queue updates.
Detects and handles failed agents using agent_recovery module.
Note: This runs in the PARENT context, not inside the subagent.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
import glob

# Add lib to path for workflow_client and agent_recovery
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from workflow_client import (  # noqa: E402
    agent_set_state,
    workflow_is_active,
    workflow_get_value,
    workflow_update,
)
from agent_recovery import detect_failed_agent, handle_failed_agent  # noqa: E402

STATE_DIR = Path.home() / ".claude" / "plugins" / "agent-swarm" / ".state"
STATE_FILE = STATE_DIR / "session.json"
SUBAGENT_LOG = STATE_DIR / "subagent_executions.log"


def load_state() -> dict:
    """Load session state."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def log_subagent_stop(agent_type: str, session_id: str, phase: str) -> None:
    """Log subagent completion to tracking file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(SUBAGENT_LOG, "a") as f:
        f.write(f"{datetime.now().isoformat()} | STOP | agent={agent_type} | session={session_id} | phase={phase}\n")


def extract_agent_completion_info(output_text: str) -> dict:
    """Extract completion info from agent output.

    Looks for JSON block containing agent completion data.
    Handles both markdown code fences and raw JSON.

    Returns dict with: agent_id, status, summary, files_modified, tests_passed
    Returns empty dict if parsing fails.
    """
    if not output_text:
        return {}

    try:
        # Try to find JSON in markdown code fence first
        json_match = re.search(r'```json\s*\n(.*?)\n```', output_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find raw JSON object
            json_match = re.search(r'\{[^}]*"agent_id"[^}]*\}', output_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                return {}

        # Parse the JSON
        data = json.loads(json_str)

        # Extract expected fields with defaults
        return {
            "agent_id": data.get("agent_id", ""),
            "status": data.get("status", "unknown"),
            "summary": data.get("summary", ""),
            "files_modified": data.get("files_modified", []),
            "tests_passed": data.get("tests_passed", None)
        }
    except (json.JSONDecodeError, AttributeError, KeyError):
        # Parsing failed, return empty dict
        return {}


def find_agent_output_file(session_id: str):
    """Find agent output file for given session ID.
    
    Agent output files are in /tmp/claude/.../tasks/{session_id}.output
    """
    try:
        # Search for output file matching session ID
        pattern = f"/tmp/claude/*/tasks/{session_id}.output"
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
        return None
    except Exception:
        return None


def persist_agent_output(session_id: str, agent_type: str) -> dict:
    """Persist agent completion data to state manager.
    
    Extracts completion info from agent output and stores via agent_set_state.
    Also detects and handles failed agents.
    Handles errors gracefully - does not fail if parsing/storage fails.
    
    Returns:
        dict with failure_detected (bool) and failure_reason (str) if failed
    """
    failure_info = {"failure_detected": False, "failure_reason": ""}
    
    try:
        # Find and read agent output file
        output_file = find_agent_output_file(session_id)
        if not output_file:
            return failure_info  # No output file found, skip silently
        
        output_path = Path(output_file)
        if not output_path.exists():
            return failure_info
        
        output_text = output_path.read_text()
        
        # Extract completion info from output
        completion_info = extract_agent_completion_info(output_text)
        if not completion_info or not completion_info.get("agent_id"):
            return failure_info  # No valid completion info found
        
        # Add timestamp and agent type
        completion_info["timestamp"] = datetime.now().isoformat()
        completion_info["agent_type"] = agent_type
        
        # Calculate duration if we can find start time
        # (Would need to be stored somewhere, skipping for now)
        
        # Persist to state manager
        agent_id = completion_info["agent_id"]
        agent_set_state(agent_id, completion_info)
        
        # Detect and handle failed agents
        if detect_failed_agent(agent_id):
            reason = f"Agent output indicates failure (status={completion_info.get('status')}, summary contains error keywords)"
            handle_failed_agent(agent_id, reason=reason)
            failure_info["failure_detected"] = True
            failure_info["failure_reason"] = reason
        
        return failure_info
        
    except Exception:
        # Log error but don't fail the hook
        # (In production, could use logging module)
        return failure_info


def update_workflow_state(session_id: str, agent_type: str) -> None:
    """Move agent from active_agents to completed_tasks in workflow state."""
    try:
        if not workflow_is_active("iterate"):
            return
        
        # Get current active agents
        active = workflow_get_value("iterate", "active_agents") or {}
        
        # Remove this agent from active
        agent_info = active.pop(session_id, None)
        
        # Get completed tasks list
        completed = workflow_get_value("iterate", "completed_tasks") or []
        
        # Add to completed (use description if available, else session_id)
        if agent_info:
            desc = agent_info.get("description", session_id)
        else:
            desc = f"{agent_type}:{session_id}"
        completed.append(desc)
        
        # Update workflow state
        workflow_update("iterate", {
            "active_agents": active,
            "completed_tasks": completed
        })
    except Exception:
        pass  # Don't fail hook on workflow state errors


def main():
    # Read hook input
    input_data = json.loads(sys.stdin.read())

    # Extract info
    session_id = input_data.get("sessionId", "unknown")[:8]
    agent_type = input_data.get("agentType", "unknown")

    # Get current phase
    state = load_state()
    phase = state.get("phase") or state.get("iterate_phase") or "none"

    # Persist agent output to state manager and check for failures
    failure_info = persist_agent_output(session_id, agent_type)

    # Update workflow state - move from active_agents to completed_tasks
    update_workflow_state(session_id, agent_type)

    # Build result with failure status if detected
    message = f"Subagent {agent_type} completed in phase {phase}"
    if failure_info["failure_detected"]:
        message += f" [FAILED: {failure_info['failure_reason']}]"

    result = {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStop",
            "message": message,
            "failure_detected": failure_info["failure_detected"]
        }
    }

    print(json.dumps(result))


if __name__ == "__main__":
    main()
