#!/usr/bin/env python3
"""SubagentStop hook - runs when a subagent completes.

Logs completion and can trigger queue updates.
Note: This runs in the PARENT context, not inside the subagent.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

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


def main():
    # Read hook input
    input_data = json.loads(sys.stdin.read())

    # Extract info - note: field names are snake_case per Claude Code API
    session_id = input_data.get("session_id", input_data.get("sessionId", "unknown"))[:8]
    agent_type = input_data.get("agent_type", input_data.get("agentType", "unknown"))
    agent_id = f"{agent_type}-{session_id}"
    result = input_data.get("result", {})
    success = result.get("exitCode") == 0 if isinstance(result, dict) else False

    # Get current phase
    state = load_state()
    phase = state.get("phase") or state.get("iterate_phase") or "none"

    # Log the subagent completion
    log_subagent_stop(agent_type, session_id, phase)
    
    # Add logging via subagent_logger
    try:
        sys.path.insert(0, str(Path.home() / ".claude/plugins/agent-swarm/lib"))
        from subagent_logger import log_completion
        summary = result.get("summary", "") if isinstance(result, dict) else str(result)
        log_completion(agent_id, phase, success, summary[:100])
    except Exception as e:
        pass  # Logging failure should not block completion
    
    # Decrement active agent count
    state["active_agents"] = max(0, state.get("active_agents", 0) - 1)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

    result = {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStop",
            "message": f"Subagent {agent_type} completed in phase {phase}"
        }
    }

    print(json.dumps(result))


if __name__ == "__main__":
    main()
