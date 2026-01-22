"""Permission query interface.

Simple functions to query permissions from workflow state.
Agents call these at session start to get their PermissionStore.
"""

from typing import Optional

import workflow_client
from permission_store import PermissionStore


# Known workflow IDs to check when no specific ID given
_KNOWN_WORKFLOWS = ["iterate", "debug", "pr_comment", "implementer"]


def get_active_workflow_id() -> Optional[str]:
    """Get ID of currently active workflow, if any.

    Checks known workflow IDs in order and returns the first active one.

    Returns:
        Workflow ID if one is active, None otherwise.
    """
    for wf_id in _KNOWN_WORKFLOWS:
        if workflow_client.workflow_is_active(wf_id):
            return wf_id
    return None


def get_permissions(workflow_id: Optional[str] = None) -> Optional[PermissionStore]:
    """Get PermissionStore from workflow state.

    Args:
        workflow_id: Specific workflow ID, or None to try active workflow

    Returns:
        PermissionStore if workflow active and has permissions, None otherwise.
    """
    # If no workflow ID specified, try to find active one
    if workflow_id is None:
        workflow_id = get_active_workflow_id()
        if workflow_id is None:
            return None

    # Check if workflow is active
    if not workflow_client.workflow_is_active(workflow_id):
        return None

    # Get workflow state
    state = workflow_client.workflow_get_state(workflow_id)
    if state is None:
        return None

    # Extract permissions from state
    permissions_data = state.get("permissions")
    if permissions_data is None:
        # No permissions key - return minimal store indicating workflow is active
        return PermissionStore(
            workflow_active=True,
            workflow_id=workflow_id,
            workflow_type=state.get("workflow_type", workflow_id),
            phase=state.get("phase", "none"),
        )

    # Deserialize from dict
    return PermissionStore.from_dict(permissions_data)


def is_tool_allowed(
    tool_name: str,
    workflow_id: Optional[str] = None,
    **context
) -> tuple[bool, str]:
    """Check if tool is allowed.

    Convenience wrapper around get_permissions().is_tool_allowed()

    Args:
        tool_name: Name of tool to check
        workflow_id: Optional specific workflow ID
        **context: Additional context (file_path, command, etc.)

    Returns:
        (True, "") if allowed or no workflow
        (False, reason) if blocked
    """
    store = get_permissions(workflow_id)

    # No workflow means no restrictions (except base enforcement elsewhere)
    if store is None:
        return True, ""

    return store.is_tool_allowed(tool_name, **context)
