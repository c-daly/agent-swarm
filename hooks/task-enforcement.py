#!/usr/bin/env python3
"""PreToolUse hook for Task tool — consolidated enforcement.

Combines three checks (fail-fast order, cheapest first):
1. Background enforcement: run_in_background=true required
2. Briefing enforcement: prompt must contain SUBAGENT OPERATING PROTOCOL
3. Implementer-only enforcement: during iterate/orchestrate, only implementer agents

Replaces: background-enforcement.py, inject-subagent-briefing.sh, implementer-only-enforcement.py
"""

import json
import sys
from pathlib import Path

# Add lib to path for workflow_client
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

try:
    from workflow_client import workflow_is_active, workflow_get_state
except ImportError:
    def workflow_is_active(workflow_id: str) -> bool:
        return False
    def workflow_get_state(workflow_id: str) -> dict | None:
        return None


def allow(reason: str = "") -> dict:
    """Return allow decision."""
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow"
        }
    }
    if reason:
        result["hookSpecificOutput"]["permissionDecisionReason"] = reason
    return result


def deny(reason: str) -> dict:
    """Return deny decision."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason
        }
    }


def check_background(tool_input: dict) -> dict | None:
    """Check that run_in_background=true is set."""
    if not tool_input.get("run_in_background", False):
        return deny(
            "[BACKGROUND_REQUIRED] Task tool must use run_in_background=true "
            "for parallel execution. Add run_in_background=true to your Task call."
        )
    return None


def check_briefing(tool_input: dict) -> dict | None:
    """Check that prompt contains the subagent briefing marker."""
    prompt = tool_input.get("prompt", "")
    if not prompt:
        # No prompt — allow (Task tool will handle the error)
        return None
    if "SUBAGENT OPERATING PROTOCOL" not in prompt:
        return deny(
            "[BRIEFING_REQUIRED] Task prompt must include subagent briefing.\n\n"
            "Assemble the prompt:\n"
            "1. Read: cat ~/.claude/plugins/agent-swarm/hooks/subagent-briefing.md\n"
            "2. Prepend to your task with header: # SUBAGENT OPERATING PROTOCOL\n"
            "3. Add phase restrictions if in iterate workflow\n"
            "4. Re-call Task with assembled prompt\n\n"
            "Subagent Tools (allowed_tools to include):\n"
            "- Shell: mcp-call pytest, mcp-call ruff, mcp-call git, etc.\n"
            "- Files: mcp-call native__read_file, mcp-call native__write_file\n"
            "- Search: mcp-call native__glob, mcp-call native__grep\n"
            "- Serena: mcp-call serena__find_symbol, etc.\n\n"
            "See 'Subagent Prompt Assembly' in iterate skill for details."
        )
    return None


def check_implementer_only(tool_input: dict) -> dict | None:
    """During iterate/orchestrate phase, only allow implementer agents."""
    if not workflow_is_active("iterate"):
        return None

    state = workflow_get_state("iterate")
    if not state:
        return None

    phase = state.get("phase", "")
    if phase != "orchestrate":
        return None

    subagent_type = tool_input.get("subagent_type", "")
    if not subagent_type:
        return None

    if subagent_type == "agent-swarm:implementer":
        return None

    return deny(
        f"[ITERATE/ORCHESTRATE] Only agent-swarm:implementer agents allowed during "
        f"orchestrate phase of iterate workflow (TDD enforcement). "
        f"Attempted to spawn: {subagent_type}. "
        f"Implementers go through full TDD loop (test_writing → implement → test → review). "
        f"Spawning other agent types bypasses TDD discipline."
    )


def main():
    """Run all Task enforcement checks in fail-fast order."""
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps(allow()))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    if tool_name != "Task":
        print(json.dumps(allow()))
        return

    # Run checks in order: cheapest/most common failures first
    for check in [check_background, check_briefing, check_implementer_only]:
        result = check(tool_input)
        if result is not None:
            print(json.dumps(result))
            return

    print(json.dumps(allow()))


if __name__ == "__main__":
    main()
