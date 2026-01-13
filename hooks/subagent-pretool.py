#!/usr/bin/env python3
"""PreToolUse hook for subagents - enforces phase restrictions.

This script runs INSIDE subagent sessions via frontmatter hooks.
It blocks tools that are not allowed in the current phase.
"""

import json
import sys
from pathlib import Path

# Import agent_state module for per-agent state isolation
sys.path.insert(0, str(Path.home() / ".claude/plugins/agent-swarm/lib"))
from agent_state import load_state

STATE_DIR = Path.home() / ".claude" / "plugins" / "agent-swarm" / ".state"


def main():
    # Read hook input
    input_data = json.loads(sys.stdin.read())
    tool_name = input_data.get("tool_name", "")

    # Get current phase
    state = load_state()
    phase = state.get("phase") or state.get("iterate_phase") or "none"

    # If no active workflow, allow everything
    if not state.get("workflow_invoked", False):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                    }
                }
            )
        )
        return

    # Get phase restrictions
    try:
        sys.path.insert(0, str(Path.home() / ".claude/plugins/agent-swarm/lib"))
        from phase_model import get_phase_info, TOOL_CATEGORIES

        phase_info = get_phase_info(phase)
        if phase_info:
            # Check if tool is explicitly blocked
            if tool_name in phase_info.blocked_tools:
                print(
                    json.dumps(
                        {
                            "hookSpecificOutput": {
                                "hookEventName": "PreToolUse",
                                "permissionDecision": "deny",
                                "reason": f"[BLOCKED] Tool '{tool_name}' not allowed in {phase} phase. Report to orchestrator.",
                            }
                        }
                    )
                )
                return

            # Check if tool category is allowed
            tool_cat = TOOL_CATEGORIES.get(tool_name)
            if tool_cat and tool_cat not in phase_info.allowed_categories:
                print(
                    json.dumps(
                        {
                            "hookSpecificOutput": {
                                "hookEventName": "PreToolUse",
                                "permissionDecision": "deny",
                                "reason": f"[BLOCKED] Tool '{tool_name}' (category: {tool_cat.value}) not allowed in {phase} phase.",
                            }
                        }
                    )
                )
                return
    except Exception:
        pass  # Allow if we can't check

    # Allow the tool
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                }
            }
        )
    )


if __name__ == "__main__":
    main()
