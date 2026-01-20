#!/usr/bin/env python3
"""PreToolUse hook to enforce max_agents limit for Task tool."""

import json
import sys
from pathlib import Path

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))


def main():
    """Main hook logic - enforce max_agents for Task tool."""
    input_data = json.loads(sys.stdin.read())
    tool_name = input_data.get("tool_name", "")
    
    # Only check Task tool
    if tool_name != "Task":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}))
        return
    
    # Check if spawning is allowed
    try:
        from worker_pool import should_spawn_worker, is_active
        
        if not is_active():
            # Worker pool not active - allow (no enforcement)
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}))
            return
            
        if not should_spawn_worker(queue_has_work=True):
            # At max agents - block
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "[MAX_AGENTS] Cannot spawn more agents. Wait for existing agents to complete."
                }
            }))
            return
            
    except ImportError:
        pass  # worker_pool not available - allow
    
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}))


if __name__ == "__main__":
    main()
