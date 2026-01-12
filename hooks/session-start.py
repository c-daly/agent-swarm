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

# Hook logging
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
try:
    from hook_logger import log_hook
except ImportError:
    def log_hook(hook_type, hook_name, message=""): pass

log_hook("SessionStart", "session-start", "initializing")

def reset_enforcement_counters():
    """Reset enforcement counters and workflow tracking for new conversation."""
    state_file = Path(__file__).parent.parent / ".state" / "session.json"

    try:
        # Initialize fresh session state with phase executor support
        state = {
            # Enforcement counters
            "last_phase": None,
            "last_tool_time": None,
            "signature_change_reminders": [],
            "files_read": [],
            "read_count": 0,
            "files_edited_this_session": [],
            "search_count": 0,
            "edits_this_response": 0,
            "memory_search_suggested": 1,

            # Phase executor state
            "phase": "intake",
            "action_index": 0,
            "phase_context": {},
            "iteration_counts": {},
            "pending_agents": [],
            "completed_agents": [],
            "user_request": None,
            "workflow_active": False,
        }

        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)

        return True
    except Exception:
        pass  # Fail silently, not critical

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

    # Reset enforcement counters for new conversation
    reset_enforcement_counters()

    # Run inventory to discover capabilities
    inventory_output = run_inventory()

    # Read session data from stdin
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        # No input data, just print suggestion
        input_data = {}

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

    # Add workflow instruction
    workflow_msg = """
═══════════════════════════════════════════════════════════════════════
                        WORKFLOW STATE MACHINE
═══════════════════════════════════════════════════════════════════════

You are an ORCHESTRATOR, not an implementer. Your job is to:
1. Follow the phase script EXACTLY
2. Spawn subagents for actual work
3. Coordinate, don't code

CURRENT PHASE: INTAKE

YOUR FIRST ACTION (MANDATORY):
Before doing ANYTHING else, classify the user's request:

→ Spawn a classifier agent:
  Task(subagent_type="haiku", prompt="Classify this request: [USER REQUEST]

  Determine:
  1. Complexity: trivial | normal | complex
  2. Type: bug_fix | feature | refactor | question | research
  3. Scope: single_file | multi_file | system_wide

  Output JSON only: {complexity, type, scope, reasoning}")

→ Wait for result
→ Store classification and proceed to next phase

DO NOT skip intake. DO NOT read files yourself. SPAWN THE CLASSIFIER.
═══════════════════════════════════════════════════════════════════════
"""
    messages.append(workflow_msg)

    # Add inventory if available (abbreviated)
    if inventory_output:
        # Just note it's available, don't flood context
        messages.append("📦 Capabilities loaded. Use /inventory for details.")

    # Add episodic memory suggestion (abbreviated)
    if not results.get("found"):
        messages.append("💭 Use episodic-memory search for past context if needed.")

    # Return result with suggestion
    output = {
        "systemMessage": "\n".join(messages) if messages else ""
    }

    log_hook("SessionStart", "session-start", "completed - workflow initialized")
    print(json.dumps(output))

if __name__ == "__main__":
    main()
