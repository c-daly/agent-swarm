#!/usr/bin/env python3
"""SubagentStart enforcement hook.

Runs when a subagent is spawned. Injects workflow context and constraints.
Note: This runs in the PARENT context, not inside the subagent.

Subagents receive:
- Their task description
- Phase constraints (what tools are blocked)
- TDD workflow instructions

Subagents do NOT:
- Call start() (would overwrite orchestrator state)
- Write to iterate.json (orchestrator's state file)
- Load state from state_manager (they get it injected)
"""

import json
import sys
import uuid
from pathlib import Path

# Add lib to path for workflow_client and permission_store
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

try:
    from workflow_client import workflow_get_state, agent_set_state, workflow_is_active
except ImportError:
    def workflow_get_state(workflow_id: str) -> dict | None:
        return None
    def agent_set_state(agent_id: str, state: dict) -> dict | None:
        return None
    def workflow_is_active(workflow_id: str) -> bool:
        return False

try:
    from permission_store import PermissionStore, TOOL_CATEGORIES, get_tool_category
except ImportError:
    # Fallback if permission_store not available
    PermissionStore = None
    TOOL_CATEGORIES = {}
    def get_tool_category(name):
        return None

# Telemetry store for agent type registration
_telemetry_store = None
STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"


def get_telemetry_store():
    """Get or create DuckDBStore for telemetry."""
    global _telemetry_store
    if _telemetry_store is None:
        try:
            from stores.duckdb_store import DuckDBStore
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            _telemetry_store = DuckDBStore(data_dir=str(STATE_DIR))
        except Exception:
            pass  # Telemetry unavailable
    return _telemetry_store


def load_session_state() -> dict:
    """Load session state from state server."""
    state = workflow_get_state("session")
    return state if state else {}


def load_iterate_state() -> dict:
    """Load iterate workflow state from state server."""
    state = workflow_get_state("iterate")
    return state if state else {}


def get_blocked_tools_for_phase(phase: str, perms_dict: dict | None) -> list[str]:
    """Get blocked tools for a phase using PermissionStore if available.

    Args:
        phase: Current workflow phase
        perms_dict: Permissions dict from workflow state (may contain phase_permissions)

    Returns:
        List of blocked tool names
    """
    blocked = []

    # Try to use PermissionStore
    if PermissionStore and perms_dict:
        store = PermissionStore.from_dict(perms_dict)
        if store.phase_permissions:
            blocked.extend(store.phase_permissions.blocked_tools)
            # Add tools from blocked categories
            if store.phase_permissions.allowed_categories:
                for tool_name, category in TOOL_CATEGORIES.items():
                    if category and category not in store.phase_permissions.allowed_categories:
                        if tool_name not in blocked:
                            blocked.append(tool_name)
        return blocked

    # Fallback to phase_model if PermissionStore not available
    try:
        from phase_model import get_phase_info, TOOL_CATEGORIES as PM_CATEGORIES
        phase_info = get_phase_info(phase)
        if phase_info:
            blocked = list(phase_info.blocked_tools)
            for tool, cat in PM_CATEGORIES.items():
                if cat and cat not in phase_info.allowed_categories:
                    if tool not in blocked:
                        blocked.append(tool)
    except Exception:
        pass

    return blocked


def build_tdd_context(agent_id: str, task_desc: str) -> str:
    """Build TDD workflow context for implementer subagents."""
    return f"""
## SUBAGENT WORKFLOW CONTEXT

**Agent ID:** {agent_id}
**Task:** {task_desc}
**Spawned by:** Orchestrator

### TDD Workflow (Follow This Order)

**YOU CANNOT SKIP PHASES.** You MUST follow this exact sequence:

1. **TEST_WRITING** - Write failing tests first
   - These tests define what success looks like
   - Tests should fail initially (no implementation yet)

2. **IMPLEMENT** - Write code to make tests pass
   - Focus on making tests pass, nothing more
   - Keep implementation minimal

3. **TEST** - Run tests and verify
   - All tests must pass
   - Check linting/type checking if applicable

4. **REVIEW** - Self-review before completion
   - Check for obvious issues
   - Ensure code matches requirements

### Important Notes

- **DO NOT** call iterate_workflow.start() - orchestrator manages workflow state
- **DO NOT** write to iterate.json - that's orchestrator's state file
- **REPORT** your completion status when done (pass/fail/blocked)
- Focus only on your assigned task

### Completion

When done, return a summary:
```json
{{
  "agent_id": "{agent_id}",
  "status": "complete|failed|blocked",
  "summary": "What was accomplished",
  "files_modified": ["list of files"],
  "tests_passed": true|false
}}
```
"""


def build_phase_restriction_context(agent_id: str, phase: str, mode: str, blocked_tools: list[str]) -> str:
    """Build phase restriction context for subagents."""
    if not blocked_tools:
        return ""

    mode_suffix = f" ({mode} mode)" if mode else ""
    return f"""
## PHASE RESTRICTIONS (ENFORCED)

**Agent ID:** {agent_id}
**Current phase:** {phase}{mode_suffix}

**BLOCKED TOOLS - DO NOT USE:**
{chr(10).join(f'- {t}' for t in sorted(set(blocked_tools))[:15])}

If you need a blocked tool, STOP and report to orchestrator.
"""


def main():
    # Read hook input
    input_data = json.loads(sys.stdin.read())

    # Extract info
    session_id = input_data.get("sessionId", "unknown")[:8]
    agent_type = input_data.get("agentType", "unknown")
    task_desc = input_data.get("task", "implementation task")

    # Use Claude Code's agentId if provided, otherwise generate one
    agent_id = input_data.get("agentId") or f"sub-{uuid.uuid4().hex[:8]}"

    # Register agent type for telemetry (non-blocking)
    try:
        store = get_telemetry_store()
        if store:
            store.register_agent_type(agent_id, agent_type)
    except Exception:
        pass  # Don't fail the hook if telemetry registration fails

    # Load all state from state server
    session_state = load_session_state()
    iterate_state = load_iterate_state()

    # Determine context
    phase = iterate_state.get("phase") or session_state.get("phase") or "none"
    mode = iterate_state.get("mode", "")
    perms_dict = iterate_state.get("permissions") or session_state.get("permissions")

    # CRITICAL: When iterate workflow is active and spawning from orchestrate phase,
    # force ALL subagent types to start in test_writing phase (TDD enforcement)
    if workflow_is_active("iterate") and phase == "orchestrate":
        phase = "test_writing"

    # Store subagent state with its phase
    agent_state = {
        "phase": phase,
        "mode": mode,
        "task": task_desc,
        "parent_session": session_id,
    }
    agent_set_state(agent_id, agent_state)

    # Build context to inject based on mode and phase
    additional_context = []
    message_suffix = ""

    # Early exit if no phase
    if not phase or phase == "none":
        pass  # No context to inject

    elif mode == "iterate-tdd":
        # In iterate-tdd mode
        if agent_type == "implementer" and phase in ("orchestrate", "test_writing", "implement"):
            # Subagent spawned by orchestrator for implementation work
            message_suffix = f" (iterate-tdd/{phase})"
            additional_context.append(build_tdd_context(agent_id, task_desc))
        else:
            # iterate-tdd but not implementer or different phase - apply phase restrictions
            blocked_tools = get_blocked_tools_for_phase(phase, perms_dict)
            if blocked_tools:
                additional_context.append(
                    build_phase_restriction_context(agent_id, phase, "iterate-tdd", blocked_tools)
                )

    else:
        # Has phase but not iterate-tdd mode - apply generic restrictions
        blocked_tools = get_blocked_tools_for_phase(phase, perms_dict)
        if blocked_tools:
            additional_context.append(
                build_phase_restriction_context(agent_id, phase, mode, blocked_tools)
            )

    result = {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": "\n".join(additional_context) if additional_context else None,
            "message": f"Subagent {agent_type} ({agent_id}) started in phase {phase}{message_suffix}"
        }
    }

    print(json.dumps(result))


if __name__ == "__main__":
    main()
