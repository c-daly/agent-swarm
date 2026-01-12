#!/usr/bin/env python3
"""Work-seeking behavior for agent workflow.

After any task completion, proactively identify next work items.
Inject prompts to keep the agent productive.
"""

import json
from pathlib import Path
from typing import List, Dict, Any

# Sources of pending work
WORK_SOURCES = [
    "todo_list",           # TodoWrite items with status=pending
    "greptile_comments",   # Unaddressed review comments
    "ci_failures",         # Failing CI runs
    "agent_outputs",       # Completed agents needing followup
    "pr_items",            # PRs needing attention
]

def find_pending_work() -> List[Dict[str, Any]]:
    """Scan all sources for pending work items."""
    work_items = []

    # Check todo list
    todo_file = Path.home() / ".claude/todos.json"
    if todo_file.exists():
        try:
            todos = json.loads(todo_file.read_text())
            pending = [t for t in todos if t.get("status") == "pending"]
            for t in pending:
                work_items.append({
                    "source": "todo_list",
                    "description": t.get("content"),
                    "priority": "high" if "P0" in t.get("content", "") else "normal",
                })
        except json.JSONDecodeError:
            pass

    # Check for completed agent outputs needing review
    agent_dir = Path("/tmp/claude")
    if agent_dir.exists():
        last_check_file = Path.home() / ".claude/.last_work_check"
        last_check_time = last_check_file.stat().st_mtime if last_check_file.exists() else 0

        for output_file in agent_dir.glob("**/tasks/*.output"):
            if output_file.stat().st_mtime > last_check_time:
                work_items.append({
                    "source": "agent_output",
                    "description": f"Review agent output: {output_file.name}",
                    "priority": "normal",
                    "file": str(output_file),
                })

    return work_items

def generate_work_prompt(items: List[Dict[str, Any]]) -> str:
    """Generate a prompt directing agent to next work."""
    if not items:
        return ""

    high_priority = [i for i in items if i.get("priority") == "high"]
    normal = [i for i in items if i.get("priority") != "high"]

    prompt_parts = ["[WORK AVAILABLE]"]

    if high_priority:
        prompt_parts.append(f"\nHigh priority ({len(high_priority)}):")
        for item in high_priority[:3]:
            prompt_parts.append(f"  - {item['description']}")

    if normal:
        prompt_parts.append(f"\nPending ({len(normal)}):")
        for item in normal[:5]:
            prompt_parts.append(f"  - {item['description']}")

    prompt_parts.append("\nContinue with next item. Launch parallel agents if multiple independent items exist.")

    return "\n".join(prompt_parts)

def check_for_work() -> Dict[str, Any]:
    """Main entry point - check for work and return hook response."""
    items = find_pending_work()

    if items:
        prompt = generate_work_prompt(items)
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": prompt,
            }
        }

    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
        }
    }

if __name__ == "__main__":
    result = check_for_work()
    print(json.dumps(result))
