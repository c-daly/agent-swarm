#!/usr/bin/env python3
"""Task implication logic - completed tasks generate follow-up tasks.

When a task completes, check if it implies new tasks that should be created.
This ensures continuous forward progress without manual prompting.
"""

import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

# Task implication rules: completed task pattern -> implied follow-up tasks
IMPLICATION_RULES = [
    {
        "pattern": r"fix.*commit|commit.*fix",
        "implies": [
            {"content": "Run tests to verify fix", "priority": "high"},
            {"content": "Push changes to trigger CI", "priority": "high"},
        ]
    },
    {
        "pattern": r"push.*changes|git push",
        "implies": [
            {"content": "Monitor CI run status", "priority": "normal"},
            {"content": "Trigger Greptile review if PR exists", "priority": "normal"},
        ]
    },
    {
        "pattern": r"greptile.*review|review.*complete",
        "implies": [
            {"content": "Check review confidence score", "priority": "high"},
            {"content": "Address unresolved review comments", "priority": "high"},
        ]
    },
    {
        "pattern": r"agent.*complete|task.*complete",
        "implies": [
            {"content": "Review agent output for actionable findings", "priority": "normal"},
            {"content": "Create tasks for any issues found", "priority": "normal"},
        ]
    },
    {
        "pattern": r"test.*pass|tests.*pass|ci.*pass",
        "implies": [
            {"content": "Verify all review comments addressed", "priority": "normal"},
            {"content": "Check PR ready for merge", "priority": "normal"},
        ]
    },
    {
        "pattern": r"test.*fail|tests.*fail|ci.*fail",
        "implies": [
            {"content": "Analyze test failures", "priority": "high"},
            {"content": "Fix failing tests", "priority": "high"},
        ]
    },
    {
        "pattern": r"pr.*create|create.*pr|pull request",
        "implies": [
            {"content": "Trigger code review", "priority": "high"},
            {"content": "Monitor CI status", "priority": "normal"},
        ]
    },
    {
        "pattern": r"address.*comment|fix.*comment|resolve.*comment",
        "implies": [
            {"content": "Commit and push the fix", "priority": "normal"},
            {"content": "Mark comment as addressed", "priority": "low"},
        ]
    },
    {
        "pattern": r"implement.*feature|add.*feature",
        "implies": [
            {"content": "Write tests for new feature", "priority": "high"},
            {"content": "Update documentation", "priority": "normal"},
            {"content": "Run full test suite", "priority": "high"},
        ]
    },
]

def get_implied_tasks(completed_task: str, context: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """
    Given a completed task description, return implied follow-up tasks.

    Args:
        completed_task: Description of the completed task
        context: Optional context (e.g., CI status, review score)

    Returns:
        List of implied task dictionaries with content and priority
    """
    context = context or {}
    implied = []
    completed_lower = completed_task.lower()

    for rule in IMPLICATION_RULES:
        if re.search(rule["pattern"], completed_lower, re.IGNORECASE):
            for task in rule["implies"]:
                # Don't add duplicate implications
                if task["content"] not in [t["content"] for t in implied]:
                    implied.append({
                        "content": task["content"],
                        "priority": task["priority"],
                        "source": "implication",
                        "triggered_by": completed_task[:50],
                        "timestamp": datetime.now().isoformat(),
                    })

    # Context-aware implications
    if context.get("ci_status") == "failing":
        implied.insert(0, {
            "content": "Fix CI failures before proceeding",
            "priority": "critical",
            "source": "context",
            "triggered_by": "CI status",
        })

    if context.get("review_score", 5) < 4:
        implied.insert(0, {
            "content": f"Review score {context.get('review_score')}/5 - address concerns before merge",
            "priority": "high",
            "source": "context",
            "triggered_by": "Low review score",
        })

    if context.get("unaddressed_comments", 0) > 0:
        implied.insert(0, {
            "content": f"Address {context.get('unaddressed_comments')} unresolved review comments",
            "priority": "high",
            "source": "context",
            "triggered_by": "Unaddressed comments",
        })

    return implied

def format_implications_prompt(completed_task: str, implied_tasks: List[Dict]) -> str:
    """Format implied tasks as a prompt for the agent."""
    if not implied_tasks:
        return ""

    lines = [f"[TASK IMPLICATIONS] '{completed_task[:40]}...' implies:"]

    critical = [t for t in implied_tasks if t.get("priority") == "critical"]
    high = [t for t in implied_tasks if t.get("priority") == "high"]
    normal = [t for t in implied_tasks if t.get("priority") == "normal"]

    if critical:
        lines.append("\n🚨 CRITICAL:")
        for t in critical:
            lines.append(f"  - {t['content']}")

    if high:
        lines.append("\n⚡ HIGH PRIORITY:")
        for t in high:
            lines.append(f"  - {t['content']}")

    if normal:
        lines.append("\n📋 FOLLOW-UP:")
        for t in normal[:3]:  # Limit to avoid overwhelming
            lines.append(f"  - {t['content']}")

    lines.append("\nAdd these to your queue and continue working.")
    return "\n".join(lines)

# Hook integration
def on_task_complete(task_description: str, task_result: Dict | None = None) -> Dict[str, Any]:
    """Called when a task completes - returns implied tasks for the agent."""
    context = {}

    # Extract context from task result if available
    if task_result:
        context["ci_status"] = task_result.get("ci_status")
        context["review_score"] = task_result.get("review_score")
        context["unaddressed_comments"] = task_result.get("unaddressed_comments")

    implied = get_implied_tasks(task_description, context)

    if implied:
        prompt = format_implications_prompt(task_description, implied)
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": prompt,
            },
            "implied_tasks": implied,
        }

    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
        }
    }

if __name__ == "__main__":
    # Test
    import sys
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
    else:
        task = "Fixed the bug and committed changes"

    result = on_task_complete(task)
    print(json.dumps(result, indent=2))
