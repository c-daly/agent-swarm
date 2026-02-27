"""Develop workflow -- PR-based SE team simulation with TDD.

State machine for the develop workflow. Manages phase transitions,
kickback counters, subtask scheduling, and ticket configuration.

State persisted via DaemonClient (granular set_value calls).
Transition validation done here in Python.

Flow:
  intake -> research -> design -> branch -> test_writing -> implement
       -> test -> review -> merge -> acceptance -> complete
"""

import sys
from pathlib import Path
from typing import Optional

lib_dir = Path(__file__).parent
if str(lib_dir) not in sys.path:
    sys.path.insert(0, str(lib_dir))

from daemon_client import DaemonClient, is_daemon_only_key  # noqa: E402

WORKFLOW_ID = "develop"

# Valid transitions: source -> set of valid targets
TRANSITIONS: dict[str, set[str]] = {
    "intake": {"research"},
    "research": {"design"},
    "design": {"branch"},
    "branch": {"test_writing"},
    "test_writing": {"implement"},
    "implement": {"test"},
    "test": {"review", "implement"},
    "review": {"merge", "implement", "test_writing"},
    "merge": {"acceptance", "implement"},
    "acceptance": {"complete", "implement", "test_writing"},
}

CHECKPOINT_PHASES: set[str] = {"design", "test", "review", "acceptance"}
ALL_PHASES: set[str] = set(TRANSITIONS.keys()) | {"complete"}

DEFAULTS: dict = {
    "max_review_retries": 0,
    "max_agent_respawns": 3,
    "max_agents": 8,
    "tickets": {
        "enabled": True,
        "provider": "github",
        "feature_ticket": True,
        "subtask_tickets": True,
        "followup_tickets": True,
    },
}


class DevelopWorkflowError(Exception):
    """Error in develop workflow logic."""


def _get_state() -> dict:
    """Get current develop workflow state from router."""
    with DaemonClient() as dc:
        return dc.workflow_get_state(WORKFLOW_ID) or {}


def _set_state(state: dict) -> None:
    """Persist develop workflow state, routing protected keys correctly."""
    with DaemonClient() as dc:
        if "phase" in state:
            dc.workflow_advance_phase(WORKFLOW_ID, state["phase"])
        for key, value in state.items():
            if is_daemon_only_key(key):
                continue
            dc.workflow_set_value(WORKFLOW_ID, key, value)


def _force_phase(phase: str) -> None:
    """TEST HELPER ONLY -- set phase bypassing validation.

    Also clears any checkpoint flags so checkpoint enforcement
    can be tested fresh from the forced phase.
    """
    state = _get_state()
    state["phase"] = phase
    for key in list(state.keys()):
        if key.endswith("_checkpoint_passed"):
            del state[key]
    _set_state(state)


def start_develop(
    task: str,
    max_review_retries: Optional[int] = None,
    max_agent_respawns: Optional[int] = None,
    tickets_enabled: Optional[bool] = None,
) -> dict:
    """Start a new develop workflow.

    Args:
        task: Description of what to build.
        max_review_retries: Override default (0 = unlimited).
        max_agent_respawns: Override default (3).
        tickets_enabled: Override default (True).

    Returns:
        The initial state dict.
    """
    tickets = dict(DEFAULTS["tickets"])
    if tickets_enabled is not None:
        tickets["enabled"] = tickets_enabled

    state = {
        "active": True,
        "task": task,
        "phase": "intake",
        "max_review_retries": (
            max_review_retries if max_review_retries is not None
            else DEFAULTS["max_review_retries"]
        ),
        "max_agent_respawns": (
            max_agent_respawns if max_agent_respawns is not None
            else DEFAULTS["max_agent_respawns"]
        ),
        "tickets": tickets,
        "kickback_counters": {},
        "subtasks": [],
        "user_stories": [],
        "design_spec": None,
        "feature_ticket": None,
        "team_name": None,
        "agents": {},
    }
    _set_state(state)
    return state


def stop(reason: str = "user_stopped") -> None:
    """Stop the workflow.

    Safe to call when no workflow is active (no-op).
    """
    state = _get_state()
    if not state:
        return
    state["active"] = False
    state["exit_reason"] = reason
    _set_state(state)


def get_phase() -> Optional[str]:
    """Return the current phase name, or None if no workflow."""
    state = _get_state()
    return state.get("phase") if state else None


def is_active() -> bool:
    """Return True if a develop workflow is currently active."""
    state = _get_state()
    return bool(state and state.get("active"))


def advance_phase(target: str) -> dict:
    """Advance to the given target phase.

    Validates:
    - Workflow is active
    - Target is a known phase
    - Transition from current phase to target is allowed
    - Checkpoint has been passed if current phase requires it

    Returns:
        Updated state dict.

    Raises:
        DevelopWorkflowError: On any validation failure.
    """
    state = _get_state()
    if not state or not state.get("active"):
        raise DevelopWorkflowError("Workflow not active")

    current = state["phase"]

    if target not in ALL_PHASES:
        raise DevelopWorkflowError(
            f"Unknown phase: {target}. Valid: {sorted(ALL_PHASES)}"
        )

    valid_targets = TRANSITIONS.get(current, set())
    if target not in valid_targets:
        raise DevelopWorkflowError(
            f"Invalid transition: {current} -> {target}. "
            f"Valid targets from {current}: {sorted(valid_targets)}"
        )

    # Checkpoint enforcement: must pass checkpoint before leaving
    if current in CHECKPOINT_PHASES:
        ck_key = f"{current}_checkpoint_passed"
        if not state.get(ck_key):
            raise DevelopWorkflowError(
                f"Checkpoint not passed for phase {current}. "
                f"Call pass_checkpoint() before advancing."
            )

    state["phase"] = target
    # Clear checkpoint flag for the phase we just left
    state.pop(f"{current}_checkpoint_passed", None)

    if target == "complete":
        state["active"] = False

    _set_state(state)
    return state


def pass_checkpoint() -> None:
    """Mark the current phase checkpoint as passed.

    No-op if workflow is inactive or current phase is not a checkpoint.
    """
    state = _get_state()
    if not state or not state.get("active"):
        return
    current = state["phase"]
    if current in CHECKPOINT_PHASES:
        state[f"{current}_checkpoint_passed"] = True
        _set_state(state)


def record_kickback(source: str) -> None:
    """Record a kickback from the given source phase.

    Increments the counter for that source. If max_review_retries > 0
    and the count exceeds it, raises DevelopWorkflowError.

    Args:
        source: Phase name that triggered the kickback.

    Raises:
        DevelopWorkflowError: If max retries exceeded.
    """
    state = _get_state()
    counters = state.get("kickback_counters", {})
    count = counters.get(source, 0) + 1

    max_retries = state.get("max_review_retries", 0)
    if max_retries > 0 and count > max_retries:
        raise DevelopWorkflowError(
            f"Max retries ({max_retries}) exceeded for kickback source "
            f"{source}. Attempted: {count}"
        )

    counters[source] = count
    state["kickback_counters"] = counters
    _set_state(state)


def add_subtask(subtask: dict) -> None:
    """Add a subtask to the workflow.

    If status is not set, defaults to pending.
    """
    state = _get_state()
    if "status" not in subtask:
        subtask = {**subtask, "status": "pending"}
    state.setdefault("subtasks", []).append(subtask)
    _set_state(state)


def get_eligible_subtasks() -> list[dict]:
    """Return subtasks whose dependencies are all completed.

    A subtask is eligible if:
    - Its status is pending
    - All IDs in its depends_on list have status completed
    """
    state = _get_state()
    subtasks = state.get("subtasks", [])
    completed_ids = {
        s["id"] for s in subtasks if s.get("status") == "completed"
    }
    return [
        s for s in subtasks
        if s.get("status") == "pending"
        and all(d in completed_ids for d in s.get("depends_on", []))
    ]


def complete_subtask(subtask_id) -> None:
    """Mark a subtask as completed by ID."""
    state = _get_state()
    for s in state.get("subtasks", []):
        if s["id"] == subtask_id:
            s["status"] = "completed"
            break
    _set_state(state)
