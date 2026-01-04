#!/usr/bin/env python3
"""
Combined enforcement hook for agent-swarm plugin.

Handles:
1. Phase enforcement - blocks Edit/Write during implement phase unless via subagent
2. Script routing - encourages batch scripts for MCP operations after threshold
3. Autopilot approval - auto-approves tools when autopilot mode enabled

Input: JSON on stdin from Claude Code
Output: JSON with hookSpecificOutput.permissionDecision
"""

import sys
import json
from pathlib import Path

# Configuration
STATE_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}
SEARCH_TOOLS = {"Glob", "Grep", "Read"}
SEARCH_THRESHOLD = 3  # After this many searches, suggest scripts

def load_state() -> dict:
    """Load session state from file."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {}

def save_state(state: dict) -> None:
    """Save session state to file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

def allow(reason: str = None) -> dict:
    """Return allow decision."""
    result = {"hookSpecificOutput": {"permissionDecision": "allow"}}
    if reason:
        result["hookSpecificOutput"]["message"] = reason
    return result

def block(reason: str) -> dict:
    """Return block decision with reason."""
    return {
        "hookSpecificOutput": {
            "permissionDecision": "deny",
            "message": reason
        }
    }

def check_phase_enforcement(tool_name: str, state: dict) -> dict | None:
    """
    Phase enforcement: During 'implement' phase, write tools should only
    be used by subagents, not directly.

    Returns None to allow, or a block decision.
    """
    phase = state.get("phase", "")

    # Only enforce during implement phase
    if phase != "implement":
        return None

    # Check if this is a write tool
    if tool_name not in WRITE_TOOLS:
        return None

    # Check if we're in a subagent context (indicated by state flag)
    if state.get("in_subagent", False):
        return None

    # Block direct write during implement phase
    return block(
        f"[PHASE ENFORCEMENT] During 'implement' phase, use Task tool to spawn "
        f"a subagent for code changes instead of using {tool_name} directly. "
        f"This ensures proper review and context management."
    )

def check_script_routing(tool_name: str, state: dict) -> dict | None:
    """
    Script routing: After threshold searches, suggest using batch scripts.

    Returns None to allow (with optional warning), or a block decision.
    """
    if tool_name not in SEARCH_TOOLS:
        return None

    # Increment search counter
    search_count = state.get("search_count", 0) + 1
    state["search_count"] = search_count
    save_state(state)

    # After threshold, warn but don't block
    if search_count > SEARCH_THRESHOLD:
        # We allow but could add a message to stderr for visibility
        # For now, just allow - blocking searches is too disruptive
        pass

    return None

def check_autopilot(state: dict) -> dict | None:
    """
    Autopilot mode: Auto-approve all tools when enabled.

    Returns allow decision if autopilot is on, None otherwise.
    """
    if state.get("autopilot_override", False):
        return allow("Autopilot mode: auto-approved")
    return None

def main():
    # Read input from stdin
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        # If we can't parse input, allow by default
        print(json.dumps(allow()))
        return

    tool_name = input_data.get("tool_name", "")

    # Load session state
    state = load_state()

    # Check autopilot first - if enabled, approve everything
    result = check_autopilot(state)
    if result:
        print(json.dumps(result))
        return

    # Check phase enforcement
    result = check_phase_enforcement(tool_name, state)
    if result:
        print(json.dumps(result))
        return

    # Check script routing (tracks usage, may warn)
    result = check_script_routing(tool_name, state)
    if result:
        print(json.dumps(result))
        return

    # Default: allow
    print(json.dumps(allow()))

if __name__ == "__main__":
    main()
