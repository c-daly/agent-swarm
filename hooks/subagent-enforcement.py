#!/usr/bin/env python3
"""SubagentStart enforcement hook.

Runs when a subagent is spawned. Can validate and log subagent creation.
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


def log_subagent_start(agent_type: str, session_id: str, phase: str) -> None:
    """Log subagent start to tracking file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(SUBAGENT_LOG, "a") as f:
        f.write(f"{datetime.now().isoformat()} | START | agent={agent_type} | session={session_id} | phase={phase}\n")


def main():
    # Read hook input
    input_data = json.loads(sys.stdin.read())

    # Debug: Log raw input to see what we're getting
    debug_log = STATE_DIR / "subagent_debug.log"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(debug_log, "a") as f:
        f.write(f"INPUT: {json.dumps(input_data, default=str)}\n")

    # Extract info - note: field names are snake_case per Claude Code API
    session_id = input_data.get("session_id", input_data.get("sessionId", "unknown"))[:8]
    agent_type = input_data.get("agent_type", input_data.get("agentType", "unknown"))
    agent_id = f"{agent_type}-{session_id}"
    prompt = input_data.get("prompt", "")

    # Initialize subagent with test_writing phase (TDD workflow start)
    initial_phase = "test_writing"
    save_state({"phase": initial_phase}, agent_id=agent_id)

    # Log the subagent spawn
    log_subagent_start(agent_type, session_id, initial_phase)

    # Build phase restrictions to inject
    phase_restrictions = ""
    try:
        sys.path.insert(0, str(Path.home() / ".claude/plugins/agent-swarm/lib"))
        from phase_model import get_phase_info, TOOL_CATEGORIES
        phase_info = get_phase_info(initial_phase)
        if phase_info:
            blocked = list(phase_info.blocked_tools)
            for tool, cat in TOOL_CATEGORIES.items():
                if cat and cat not in phase_info.allowed_categories:
                    if tool not in blocked:
                        blocked.append(tool)
            if blocked:
                phase_restrictions = f"""
## SUBAGENT WORKFLOW - YOUR ID: {agent_id}

**Current phase:** {initial_phase}
**Sequence:** test_writing → implement → test → coverage → review

### To advance YOUR phase:
```bash
python3 -c "import sys; sys.path.insert(0, '/home/fearsidhe/.claude/plugins/agent-swarm/lib'); from agent_state import save_state; save_state({{'phase': 'implement'}}, agent_id='{agent_id}')"
```

**BLOCKED TOOLS in {initial_phase} phase - DO NOT USE:**
{chr(10).join(f'- {t}' for t in sorted(set(blocked))[:15])}

When you complete {initial_phase} phase work, advance to next phase, then continue.
"""
    except Exception:
        pass

    # Build visible banner for user
    task_summary = prompt[:60] + "..." if len(prompt) > 60 else prompt
    task_summary = task_summary.replace("\n", " ")
    
    banner = f"""
[ITERATE] ═══════════════════════════════════════════════════════════════
  Agent: {agent_id[:20]} | Phase: {initial_phase}
  Task: {task_summary}
═══════════════════════════════════════════════════════════════════════"""

    result = {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": phase_restrictions if phase_restrictions else None,
            "message": banner
        }
    }

    print(json.dumps(result))


if __name__ == "__main__":
    main()
