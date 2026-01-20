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

# Add lib to path for workflow_client
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

try:
    from workflow_client import workflow_get_state, agent_set_state
except ImportError:
    def workflow_get_state(workflow_id: str) -> dict | None:
        return None
    def agent_set_state(agent_id: str, state: dict) -> dict | None:
        return None


def load_session_state() -> dict:
    """Load session state from state server."""
    state = workflow_get_state("session")
    return state if state else {}


def load_iterate_state() -> dict:
    """Load iterate workflow state from state server."""
    state = workflow_get_state("iterate")
    return state if state else {}


def main():
    # Read hook input
    input_data = json.loads(sys.stdin.read())

    # Extract info
    session_id = input_data.get("sessionId", "unknown")[:8]
    agent_type = input_data.get("agentType", "unknown")
    task_desc = input_data.get("task", "implementation task")

    # Generate unique agent ID for this subagent
    agent_id = f"sub-{uuid.uuid4().hex[:8]}"

    # Load all state from state server
    session_state = load_session_state()
    iterate_state = load_iterate_state()

    # Determine context
    phase = iterate_state.get("phase") or session_state.get("phase") or "none"
    mode = iterate_state.get("mode", "")

    # CRITICAL FIX: When spawning implementer in iterate-tdd from orchestrate phase,
    # force the subagent to start in test_writing phase (not parent's orchestrate phase)
    if mode == "iterate-tdd" and phase == "orchestrate" and agent_type == "implementer":
        phase = "test_writing"

    # Store subagent state with its phase
    agent_state = {
        "phase": phase,
        "mode": mode,
        "task": task_desc,
        "parent_session": session_id,
    }
    agent_set_state(agent_id, agent_state)

    # Log and track
    # DISABLED: No longer logging subagent starts to file

    # log_subagent_start(agent_id, agent_type, session_id, phase)
    # DISABLED: Not tracking active agents in file

    # session_state["active_agents"] = session_state.get("active_agents", 0) + 1
    # DISABLED: Not creating state directory for session file

    # STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # DISABLED: No longer writing session state to file

    # STATE_FILE.write_text(json.dumps(session_state, indent=2))

    # Build context to inject based on mode and phase
    additional_context = []
    message_suffix = ""

    # Early exit if no phase
    if not phase or phase == "none":
        pass  # No context to inject

    elif mode == "iterate-tdd":
        # In iterate-tdd mode - check phase for specific handling
        if agent_type == "implementer" and phase in ("orchestrate", "test_writing", "implement"):
            # Subagent spawned by orchestrator for implementation work
            message_suffix = f" (iterate-tdd/{phase})"
            additional_context.append(f"""
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
""")
        else:
            # iterate-tdd but not orchestrate phase - apply phase restrictions
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
                        additional_context.append(f"""
## PHASE RESTRICTIONS (ENFORCED)

**Agent ID:** {agent_id}
**Current phase:** {phase} (iterate-tdd mode)

**BLOCKED TOOLS - DO NOT USE:**
{chr(10).join(f'- {t}' for t in sorted(set(blocked))[:15])}

If you need a blocked tool, STOP and report to orchestrator.
""")
            except Exception:
                pass

    else:
        # Has phase but not iterate-tdd mode - apply generic restrictions
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
                    additional_context.append(f"""
## PHASE RESTRICTIONS (ENFORCED)

**Agent ID:** {agent_id}
**Current phase:** {phase}

**BLOCKED TOOLS - DO NOT USE:**
{chr(10).join(f'- {t}' for t in sorted(set(blocked))[:15])}

If you need a blocked tool, STOP and report to orchestrator.
""")
        except Exception:
            pass

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
