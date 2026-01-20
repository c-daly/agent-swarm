#!/usr/bin/env python3
"""PreToolUse hook to enforce parallel Task spawning.

Detects when orchestrators spawn Task agents sequentially instead of in parallel.
Warns on 2+ sequential spawns, blocks on 3rd spawn.
"""

import json
import sys
import time
from pathlib import Path

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

try:
    from workflow_client import workflow_get_state, workflow_update
except ImportError:
    def workflow_get_state(workflow_id: str) -> dict | None:
        return None
    def workflow_update(workflow_id: str, updates: dict) -> dict:
        return {}


def get_enforcement_state() -> dict:
    """Get current parallel enforcement tracking state."""
    session_state = workflow_get_state("session")
    if not session_state:
        return {"recent_spawns": [], "last_output_time": 0}
    
    return session_state.get("parallel_enforcement_state", {
        "recent_spawns": [],
        "last_output_time": 0
    })


def update_enforcement_state(state: dict) -> None:
    """Update parallel enforcement tracking state."""
    try:
        workflow_update("session", {"parallel_enforcement_state": state})
    except Exception:
        pass  # Fail silently if state update fails


def clean_old_spawns(spawns: list, current_time: float, window: float = 5.0) -> list:
    """Remove spawns older than the time window."""
    return [s for s in spawns if current_time - s["timestamp"] < window]


def main():
    """Main hook logic - enforce parallel spawning for Task tool."""
    input_data = json.loads(sys.stdin.read())
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    
    # Only check Task tool
    if tool_name != "Task":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow"
        }}))
        return
    
    current_time = time.time()
    state = get_enforcement_state()
    
    # Clean old spawns (outside 5 second window)
    state["recent_spawns"] = clean_old_spawns(
        state["recent_spawns"],
        current_time,
        window=5.0
    )
    
    # Count recent spawns
    recent_count = len(state["recent_spawns"])
    
    # Record this spawn
    task_desc = tool_input.get("description", "unknown task")
    state["recent_spawns"].append({
        "timestamp": current_time,
        "task_desc": task_desc[:50]  # Truncate for storage
    })
    
    # Determine action based on count
    if recent_count == 0:
        # First spawn - always allow
        update_enforcement_state(state)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow"
        }}))
        return
    
    elif recent_count == 1:
        # Second spawn within window - WARN
        update_enforcement_state(state)
        warning_message = """
## PARALLEL SPAWNING RECOMMENDED

You are spawning Task agents **sequentially** (one after another).

**Issue:** Sequential spawning is inefficient. Agents run one at a time instead of in parallel.

**Solution:** Spawn all independent tasks in ONE message block:

```python
# ❌ Sequential (slow)
Task(description="Task A", ...)  # Wait for response
# ... then later ...
Task(description="Task B", ...)  # Wait for response

# ✅ Parallel (fast)
Task(description="Task A", ...)
Task(description="Task B", ...)
Task(description="Task C", ...)
# All spawn together, run simultaneously
```

**Current spawns in last 5 seconds:** {}

This is a warning. Third sequential spawn will be blocked.
""".format(recent_count + 1)
        
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "additionalContext": warning_message
        }}))
        return
    
    else:
        # Third or more spawn within window - BLOCK
        update_enforcement_state(state)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"[PARALLEL_ENFORCEMENT] Cannot spawn {recent_count + 1} Task agents sequentially. "
                f"You have spawned {recent_count} agents in the last 5 seconds. "
                "Please spawn all independent tasks in ONE message block to run them in parallel. "
                "Example: Task(...) Task(...) Task(...) in a single response."
            )
        }}))
        return


if __name__ == "__main__":
    main()
