#!/usr/bin/env python3
"""
Combined enforcement hook for agent-swarm plugin.

Enforces:
1. Phase restrictions - tools allowed per phase
2. Subagent requirements - implement phase requires subagents
3. Token efficiency - blocks excessive direct tool use
4. Scope discipline - prevents off-task exploration
5. Autopilot mode - auto-approves when enabled
"""

import sys
import json
from pathlib import Path

# Configuration
STATE_FILE = Path.home() / ".claude/plugins/agent-swarm/.state/session.json"
CONFIG_FILE = Path.home() / ".claude/plugins/agent-swarm/config/workflow.json"

# Tool categories
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}
SEARCH_TOOLS = {"Glob", "Grep", "Read"}
RESEARCH_TOOLS = {"WebSearch", "WebFetch"}
SUBAGENT_TOOLS = {"Task"}
GIT_TOOLS = {"Bash"}  # git commands via bash

# Phase restrictions
PHASE_ALLOWED_TOOLS = {
    "intake": {"Read", "Glob", "Grep", "AskUserQuestion"},
    "research": {"WebSearch", "WebFetch", "Read", "Task"},
    "explore": {"Glob", "Grep", "Read", "Task"},
    "design": {"Read", "Glob", "Grep", "Task", "AskUserQuestion"},
    "implement": {"Task", "Read"},  # Write only via subagent
    "review": {"Read", "Glob", "Grep", "Bash", "Task"},
    "debug": {"Read", "Glob", "Grep", "Bash", "Edit", "Write", "Task"},
    "git": {"Bash", "Read"},
    "": set(),  # No phase = no restrictions
}

# Tools always allowed regardless of phase
ALWAYS_ALLOWED = {"TodoWrite", "AskUserQuestion"}

# Thresholds
MAX_DIRECT_SEARCHES = 3  # After this, must use scripts
MAX_FILE_READS = 5  # After this, must use subagent

def load_json(path: Path) -> dict:
    """Load JSON file safely."""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {}

def save_state(state: dict) -> None:
    """Save session state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

def allow(reason: str = None) -> dict:
    """Return allow decision."""
    result = {"hookSpecificOutput": {"permissionDecision": "allow"}}
    if reason:
        result["hookSpecificOutput"]["message"] = reason
    return result

def block(reason: str) -> dict:
    """Return block decision."""
    return {
        "hookSpecificOutput": {
            "permissionDecision": "deny",
            "message": reason
        }
    }

def check_autopilot(state: dict) -> dict | None:
    """Autopilot mode bypasses all enforcement."""
    if state.get("autopilot_override", False):
        return allow("[AUTOPILOT] Auto-approved")
    return None

def check_phase_restrictions(tool_name: str, state: dict) -> dict | None:
    """Enforce phase-specific tool restrictions."""
    phase = state.get("phase", "")

    # No phase = no restrictions
    if not phase:
        return None

    # Always allowed tools
    if tool_name in ALWAYS_ALLOWED:
        return None

    # Check phase restrictions
    allowed_tools = PHASE_ALLOWED_TOOLS.get(phase, set())

    # During implement phase, write tools require subagent context
    if phase == "implement" and tool_name in WRITE_TOOLS:
        if not state.get("in_subagent", False):
            return block(
                f"[PHASE: {phase}] {tool_name} blocked. "
                f"During implement phase, use Task tool to spawn a subagent. "
                f"Direct edits bypass review and context management."
            )

    # Strict phase enforcement (if enabled in config)
    config = load_json(CONFIG_FILE)
    if config.get("strict_phase_enforcement", False):
        if tool_name not in allowed_tools and tool_name not in ALWAYS_ALLOWED:
            return block(
                f"[PHASE: {phase}] {tool_name} not allowed in this phase. "
                f"Allowed: {', '.join(allowed_tools)}"
            )

    return None

def check_token_efficiency(tool_name: str, state: dict) -> dict | None:
    """Enforce token-saving measures."""

    # Track search tool usage
    if tool_name in SEARCH_TOOLS:
        count = state.get("search_count", 0) + 1
        state["search_count"] = count
        save_state(state)

        if count > MAX_DIRECT_SEARCHES:
            return block(
                f"[TOKEN EFFICIENCY] {count} direct searches used. "
                f"Use a batch script instead:\n"
                f"```python\n"
                f"from mcp_bridge import native_glob, native_grep\n"
                f"# Batch your searches\n"
                f"```\n"
                f"Or spawn an Explorer subagent with Task tool."
            )

    # Track file reads
    if tool_name == "Read":
        count = state.get("read_count", 0) + 1
        state["read_count"] = count
        save_state(state)

        if count > MAX_FILE_READS:
            return block(
                f"[TOKEN EFFICIENCY] {count} direct file reads. "
                f"Spawn an Explorer subagent to aggregate findings, "
                f"or use a script to read and summarize."
            )

    return None

def check_scope_discipline(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Prevent off-task exploration."""
    phase = state.get("phase", "")
    task_summary = state.get("task_summary", "")

    # Only enforce during active phases
    if not phase or phase in ("intake", "research", "explore"):
        return None

    # Check if spawning subagent without clear purpose
    if tool_name == "Task":
        prompt = tool_input.get("prompt", "")
        if len(prompt) < 20:
            return block(
                f"[SCOPE] Subagent prompt too vague. "
                f"Provide clear, specific instructions for the subagent."
            )

    return None

def check_git_safety(tool_name: str, tool_input: dict, state: dict) -> dict | None:
    """Prevent dangerous git operations."""
    if tool_name != "Bash":
        return None

    command = tool_input.get("command", "")

    # Dangerous patterns
    dangerous = [
        "git push --force",
        "git push -f",
        "git reset --hard",
        "git clean -fd",
        "git checkout .",  # Discards all changes
    ]

    for pattern in dangerous:
        if pattern in command:
            return block(
                f"[GIT SAFETY] Dangerous command blocked: {pattern}\n"
                f"This operation is destructive. Use explicit approval."
            )

    # Warn about amending
    if "git commit --amend" in command:
        phase = state.get("phase", "")
        if phase != "git":
            return block(
                f"[GIT SAFETY] Amend outside git phase. "
                f"Switch to git phase first, or get explicit approval."
            )

    return None

def main():
    # Read input from stdin
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps(allow()))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Load session state
    state = load_json(STATE_FILE)

    # Check autopilot first
    result = check_autopilot(state)
    if result:
        print(json.dumps(result))
        return

    # Run all enforcement checks
    checks = [
        check_phase_restrictions(tool_name, state),
        check_token_efficiency(tool_name, state),
        check_scope_discipline(tool_name, tool_input, state),
        check_git_safety(tool_name, tool_input, state),
    ]

    for result in checks:
        if result:
            print(json.dumps(result))
            return

    # Default: allow
    print(json.dumps(allow()))

if __name__ == "__main__":
    main()
