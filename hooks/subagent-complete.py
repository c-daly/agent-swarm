#!/usr/bin/env python3
"""SubagentStop hook - runs when a subagent completes.

Logs completion and can trigger queue updates.
Note: This runs in the PARENT context, not inside the subagent.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# Import agent_state module for per-agent state isolation
sys.path.insert(0, str(Path.home() / ".claude/plugins/agent-swarm/lib"))
from agent_state import load_state, save_state

STATE_DIR = Path.home() / ".claude" / "plugins" / "agent-swarm" / ".state"
SUBAGENT_LOG = STATE_DIR / "subagent_executions.log"


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
    

    result = {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStop",
            "message": f"Subagent {agent_type} completed in phase {phase}"
        }
    }

    print(json.dumps(result))


if __name__ == "__main__":
    main()
