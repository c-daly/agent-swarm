"""Permission query interface.

Simple functions to query permissions from workflow state.
Agents call these at session start to get their PermissionStore.
"""

from typing import Optional

from daemon_client import DaemonClient
from permission_store import PermissionStore


# Known workflow IDs to check when no specific ID given
_KNOWN_WORKFLOWS = ["iterate", "debug", "pr_comment", "simple", "develop", "experiment", "orchestrate", "delegate"]


def get_active_workflow_id() -> Optional[str]:
    """Get ID of currently active workflow, if any."""
    with DaemonClient() as dc:
        for wf_id in _KNOWN_WORKFLOWS:
            if dc.workflow_is_active(wf_id):
                return wf_id
    return None


def get_permissions(workflow_id: Optional[str] = None) -> Optional[PermissionStore]:
    """Get PermissionStore from workflow state."""
    if workflow_id is None:
        workflow_id = get_active_workflow_id()
        if workflow_id is None:
            return None

    with DaemonClient() as dc:
        if not dc.workflow_is_active(workflow_id):
            return None
        state = dc.workflow_get_state(workflow_id)

    if state is None:
        return None

    permissions_data = state.get("permissions")
    if permissions_data is None:
        return PermissionStore(
            workflow_active=True,
            workflow_id=workflow_id,
            workflow_type=state.get("workflow_type", workflow_id),
            phase=state.get("phase", "none"),
        )

    return PermissionStore.from_dict(permissions_data)


def is_tool_allowed(
    tool_name: str,
    workflow_id: Optional[str] = None,
    **context
) -> tuple[bool, str]:
    """Check if tool is allowed."""
    store = get_permissions(workflow_id)
    if store is None:
        return True, ""
    return store.is_tool_allowed(tool_name, **context)
