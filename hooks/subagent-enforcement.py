#!/usr/bin/env python3
"""SubagentStart enforcement hook.

Runs when a subagent is spawned. Can validate and log subagent creation.
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


def log_subagent_start(agent_type: str, session_id: str, phase: str) -> None:
    """Log subagent start to tracking file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(SUBAGENT_LOG, "a") as f:
        f.write(f"{datetime.now().isoformat()} | START | agent={agent_type} | session={session_id} | phase={phase}\n")


def main():
    # Read hook input
    input_data = json.loads(sys.stdin.read())

    # Extract info
    session_id = input_data.get("sessionId", "unknown")[:8]
    agent_type = input_data.get("agentType", "unknown")

    # Get current phase
    state = load_state()
    phase = state.get("phase") or state.get("iterate_phase") or "none"

    # Log the subagent spawn
    log_subagent_start(agent_type, session_id, phase)
    
    # Increment active agent count
    state["active_agents"] = state.get("active_agents", 0) + 1
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

    # Build phase restrictions to inject
    phase_restrictions = ""
    if phase and phase != "none":
        try:
            sys.path.insert(0, str(Path.home() / ".claude/plugins/agent-swarm/lib"))
            from phase_model import get_phase_info, TOOL_CATEGORIES
            phase_info = get_phase_info(phase)
            if phase_info:
                blocked = list(phase_info.blocked_tools)
                for tool, cat in TOOL_CATEGORIES.items():
                    if cat and cat not in phase_info.allowed_categories:
                        if tool not in blocked:
                            blocked.append(tool)
                if blocked:
                    phase_restrictions = f"""
## PHASE RESTRICTIONS (ENFORCED)
Current phase: {phase}
**BLOCKED TOOLS - DO NOT USE:**
{chr(10).join(f'- {t}' for t in sorted(set(blocked))[:15])}

If you need a blocked tool, STOP and report to orchestrator.
"""
        except Exception:
            pass

    result = {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": phase_restrictions if phase_restrictions else None,
            "message": f"Subagent {agent_type} started in phase {phase}"
        }
    }

    print(json.dumps(result))


if __name__ == "__main__":
    main()
