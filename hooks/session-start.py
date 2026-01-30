#!/usr/bin/env python3
"""
Session Start Hook - Reset counters & auto-start workflow

Resets enforcement counters for the new conversation and
auto-starts the implementer workflow if none is active.
"""

import json
import sys
import time
from pathlib import Path

# Add lib and context to path
plugin_dir = Path(__file__).parent.parent
lib_dir = plugin_dir / "lib"
context_dir = plugin_dir / "context"
sys.path.insert(0, str(lib_dir))
sys.path.insert(0, str(context_dir))

try:
    from hook_logging import log_warning
except ImportError:
    def log_warning(msg, **kw):
        pass

try:
    from workflow_client import workflow_get_state, workflow_set_state, agent_set_state
except ImportError:
    def workflow_get_state(workflow_id: str) -> dict | None:
        return None
    def workflow_set_state(workflow_id: str, state: dict) -> dict | None:
        return None
    def agent_set_state(agent_id: str, state: dict) -> dict | None:
        return None

try:
    from project_root import find_project_root
except ImportError:
    find_project_root = None


def load_iterate_state() -> dict:
    """Load iterate workflow state from state server."""
    state = workflow_get_state("iterate")
    return state if state else {}


def reset_enforcement_counters(agent_id: str | None = None):
    """Reset enforcement counters but preserve workflow state for new conversation.

    Args:
        agent_id: If provided, this is a subagent - inherit phase from orchestrator.
    """
    # Use absolute path to match pre-compacting.py
    state_dir = Path.home() / ".claude/plugins/agent-swarm/.state"
    compaction_state_file = state_dir / "compaction_state.json"

    try:
        # Check for compaction state (preserved across context compaction)
        compaction_flags = {}
        if compaction_state_file.exists():
            try:
                compaction_data = json.loads(compaction_state_file.read_text())
                compaction_flags = compaction_data.get("flags", {})
                # Delete after reading - one-time use
                compaction_state_file.unlink()
            except (json.JSONDecodeError, IOError) as e:
                log_warning(f"Caught exception: {e}")

        # Initialize fresh session state for counters
        # NOTE: blocked_at and mcp_counts are intentionally NOT included
        # This clears any blocking state from previous sessions
        state = {
            "last_phase": None,
            "last_tool_time": None,
            "signature_change_reminders": [],
            "files_read": [],
            "read_count": 0,
            "files_edited_this_session": [],
            "phase": None,  # Will be set below if subagent
            "search_count": 0,
            "edits_this_response": 0,
            "memory_search_suggested": 1,
            "mcp_counts": {},  # Reset MCP tool counts
            "classification_given": False,  # Reset classification state
            "classification_type": None,
            "workflow_invoked": False,  # Reset workflow state
        }
        # NOTE: blocked_at is NOT set, which clears it

        # Restore flags preserved from compaction
        state.update(compaction_flags)

        # Set project_root so router can auto-activate Serena for the correct project
        if find_project_root is not None:
            try:
                state["project_root"] = str(find_project_root(Path.cwd()))
            except Exception:
                pass

        # If subagent, inherit phase from orchestrator and set per-agent state
        if agent_id:
            iterate_state = load_iterate_state()
            phase = iterate_state.get("phase")
            if phase:
                state["phase"] = phase
            # Store state keyed by agent_id for subagent-specific queries
            agent_set_state(agent_id, state)

        # Write session state to state server (global session for main agent)
        workflow_set_state("session", state)

        return True
    except Exception as e:
        log_warning(f"Caught Exception: {e}")  # Fail silently, not critical

    return False


def main():
    """Session start hook entry point."""

    # Read session data from stdin first (need agentId for reset)
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        input_data = {}

    # Check if this is a subagent (has agentId)
    agent_id = input_data.get("agentId")

    # Reset enforcement counters - pass agent_id to inherit phase if subagent
    reset_enforcement_counters(agent_id)

    # Auto-start implementer workflow for main agent if no workflow active
    # Retry once after a short delay — the router socket may not be ready yet
    if not agent_id:
        for attempt in range(2):
            try:
                from permission_query import get_active_workflow_id
                active_wf = get_active_workflow_id()
                if active_wf is None:
                    from implementer_workflow import ImplementerWorkflow
                    wf = ImplementerWorkflow()
                    wf.start("Default session workflow")
                break  # Success (either started or already active)
            except Exception:
                if attempt == 0:
                    time.sleep(0.5)
                # Second attempt failed — don't block session start

    # Clean up stale output files (only for main agent, not subagents)
    if not agent_id:
        try:
            from output_cleanup import cleanup_stale_outputs
            cleanup_stale_outputs(max_age_hours=48, dry_run=False)
        except Exception:
            pass  # Fail silently - cleanup shouldn't break session start

    # Context injection disabled for token optimization.
    # Hierarchy, inventory, episodic memory, and patterns are no longer
    # injected at session start. Use /ctx or /recall if needed.
    output = {"systemMessage": ""}
    print(json.dumps(output))

if __name__ == "__main__":
    main()
