#!/usr/bin/env python3
"""
Session Start Hook - Auto-search episodic memory

Automatically searches episodic memory at the start of each session
to recover relevant context from past conversations.
"""

import json
import sys
import subprocess
from pathlib import Path

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

    # Return result with suggestion
    output = {
        "hookSpecificOutput": {
            "message": results.get("message", "") if not results.get("found") else
                      f"✓ Found {len(results.get('conversations', []))} relevant past conversations"
        }
    }

    print(json.dumps(output))

if __name__ == "__main__":
    main()
