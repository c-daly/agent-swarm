#!/usr/bin/env python3
"""
Session Start Hook - Auto-search episodic memory & reset counters & inject capabilities

Automatically searches episodic memory at the start of each session
to recover relevant context from past conversations.

Also resets enforcement counters for the new conversation.

Runs inventory.py to inject available MCP servers, skills, and capabilities.
"""

import json
import sys
import subprocess
from pathlib import Path

# Add lib to path for workflow_client
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

try:
    from hook_logging import log_error, log_warning, log_info, log_debug, ConfigError, StateError
except ImportError:
    # Fallback: define minimal logging functions
    def log_error(msg, **kw): pass
    def log_warning(msg, **kw): pass
    def log_info(msg, **kw): pass
    def log_debug(msg, **kw): pass
    class ConfigError(Exception): pass
    class StateError(Exception): pass

try:
    from workflow_client import workflow_get_state, workflow_set_state
except ImportError:
    # Fallback if workflow_client not available
    def workflow_get_state(workflow_id: str) -> dict | None:
        return None
    def workflow_set_state(workflow_id: str, state: dict) -> dict | None:
        return None


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
    # DISABLED: Session state file no longer used
    # state_file = state_dir / "session.json"
    state_file = None
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

        # If subagent, inherit phase from orchestrator
        if agent_id:
            iterate_state = load_iterate_state()
            phase = iterate_state.get("phase")
            if phase:
                state["phase"] = phase

        # Write session state to state server
        workflow_set_state("session", state)

        return True
    except Exception as e:
        log_warning(f"Caught Exception: {e}")  # Fail silently, not critical

    return False

def run_inventory():
    """Run inventory.py to discover available capabilities."""
    try:
        inventory_path = Path(__file__).parent.parent / "scripts" / "inventory.py"
        if not inventory_path.exists():
            return None

        result = subprocess.run(
            ["python3", str(inventory_path), "all"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            return result.stdout
        return None

    except Exception:
        return None

def search_episodic_memory(query_terms):
    """Search episodic memory for relevant past conversations."""
    try:
        # Use the episodic-memory plugin search tool
        # Note: This would need to integrate with the actual MCP tool
        # For now, we'll provide a helpful message

        results = {
            "found": False,
            "message": f"💭 Episodic Memory Search:\n"
                      f"   To search past conversations, use:\n"
                      f"   Skill: episodic-memory:search-conversations\n"
                      f"   OR: mcp__plugin_episodic-memory_episodic-memory__search(query='{query_terms}', limit=5)\n"
        }

        return results

    except Exception as e:
        return {
            "found": False,
            "error": str(e)
        }

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

    # Run inventory to discover capabilities
    inventory_output = run_inventory()

    # Get any initial context from the session
    initial_messages = input_data.get("messages", [])

    # Extract potential search terms from first user message
    query_terms = "agent-swarm workflow automation"
    if initial_messages:
        first_msg = initial_messages[0].get("content", "")
        # Simple heuristic: use first few words
        words = first_msg.split()[:5]
        if words:
            query_terms = " ".join(words)

    # Search episodic memory
    results = search_episodic_memory(query_terms)

    # Build output message
    messages = []

    # Add inventory if available
    if inventory_output:
        messages.append("📦 Capability Inventory:\n" + inventory_output[:1000])  # Limit size

    # Add episodic memory suggestion
    if not results.get("found"):
        messages.append(results.get("message", ""))
    else:
        messages.append(f"✓ Found {len(results.get('conversations', []))} relevant past conversations")

    # Return result with suggestion
    output = {
        "systemMessage": "\n\n".join(messages) if messages else ""
    }

    print(json.dumps(output))

if __name__ == "__main__":
    main()
