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

    # Extract info - use Claude's agent_id directly
    session_id = input_data.get("session_id", input_data.get("sessionId", "unknown"))[:8]
    agent_type = input_data.get("agent_type", input_data.get("agentType", "unknown"))
    # Use Claude's short agent_id (e.g., "aa289d0")
    claude_agent_id = input_data.get("agent_id", "unknown")
    agent_id = f"{agent_type}-{claude_agent_id}"
    # prompt not in SubagentStart input, get from tool_input if available
    tool_input = input_data.get("tool_input", {})
    prompt = tool_input.get("prompt", tool_input.get("description", "")) if isinstance(tool_input, dict) else ""

    # Get current phase from parent state
    state = load_state(agent_id)
    phase = state.get("phase") or state.get("iterate_phase") or "none"

    # Initialize subagent's isolated state with its phase
    save_state({"phase": phase}, agent_id=agent_id)

    # Log the subagent spawn
    log_subagent_start(agent_type, session_id, phase)

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
                      ## SUBAGENT WORKFLOW - YOUR ID: {agent_id}

                      **Current phase:** test_writing
                      **Sequence:** test_writing → implement → test → coverage → review

                      ### To advance YOUR phase (NOT workflow.py - that's for orchestrator):
                      ```bash
                      python3 -c "import sys; sys.path.insert(0, '/home/fearsidhe/.claude/plugins/agent-swarm/lib'); from agent_state import save_state; save_state({{'phase': 'implement'}}, agent_id='{agent_id}')"

                      BLOCKED TOOLS in test_writing phase - DO NOT USE:
                      {chr(10).join(f'- {t}' for t in sorted(set(blocked))[:15])}

                      When you complete test_writing phase work, advance to next phase, then continue.
                      """
           
        except Exception:
            pass

        # Build visible banner for user
    task_summary = prompt[:60] + "..." if len(prompt) > 60 else prompt
    task_summary = task_summary.replace("\n", " ")
    
    banner = f"""
[ITERATE] ═══════════════════════════════════════════════════════════════
  Agent: {agent_id[:20]} | Phase: {phase}
  Task: {task_summary}
═══════════════════════════════════════════════════════════════════════"""

    result = {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": phase_restrictions if phase_restrictions else None,
            "message": banner
        }
    }

    # Also write to stderr for terminal visibility
    print(banner, file=sys.stderr)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
