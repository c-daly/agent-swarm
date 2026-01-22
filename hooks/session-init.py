#!/usr/bin/env python3
"""Session initialization hook - consolidated session startup.

Replaces: work_seeker.py, session-start.py
Event: SessionStart
Returns: {"additionalContext": "...permission info..."}

Queries the permission store for active workflow permissions and injects
them into the session context so the agent knows its constraints.
"""
import json
import sys
from pathlib import Path

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

try:
    from permission_query import get_permissions, get_active_workflow_id
except ImportError:
    # Fallback if permission_query not available
    def get_active_workflow_id():
        return None
    def get_permissions(workflow_id=None):
        return None


def format_permissions_for_prompt(perms) -> str:
    """Format PermissionStore as human-readable prompt context.

    Args:
        perms: PermissionStore instance or None

    Returns:
        Formatted string for injection into prompt context
    """
    if not perms:
        return "No active workflow - standard permissions apply."

    lines = [
        f"Active workflow: {perms.workflow_type} ({perms.workflow_id})",
        f"Current phase: {perms.phase}",
    ]

    if perms.phase_permissions:
        pp = perms.phase_permissions

        if pp.blocked_tools:
            # Show first 10 blocked tools to avoid context bloat
            tools = list(pp.blocked_tools)[:10]
            if len(pp.blocked_tools) > 10:
                tools.append(f"...and {len(pp.blocked_tools) - 10} more")
            lines.append(f"Blocked tools: {', '.join(tools)}")

        if pp.blocked_commands:
            cmds = list(pp.blocked_commands)[:5]
            if len(pp.blocked_commands) > 5:
                cmds.append(f"...and {len(pp.blocked_commands) - 5} more")
            lines.append(f"Blocked commands: {', '.join(cmds)}")

        if pp.allowed_categories:
            lines.append(f"Allowed categories: {', '.join(pp.allowed_categories)}")

        if pp.required_tools:
            lines.append(f"Required tools: {', '.join(pp.required_tools)}")

    if perms.is_subagent:
        lines.append("Running as subagent - restricted permissions apply")

    return "\n".join(lines)


def main():
    """Main entry point for SessionStart hook."""
    # Read hook input from stdin
    try:
        _input_data = json.loads(sys.stdin.read())  # noqa: F841
    except json.JSONDecodeError:
        pass  # Input parsed but not used yet

    # Get current permissions from active workflow
    workflow_id = get_active_workflow_id()
    perms = get_permissions(workflow_id) if workflow_id else None

    # Format for prompt injection
    context = format_permissions_for_prompt(perms)

    # Build result - SessionStart uses additionalContext for prompt injection
    result = {
        "additionalContext": context
    }

    print(json.dumps(result))


if __name__ == "__main__":
    main()
