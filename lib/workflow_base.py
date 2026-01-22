"""Base classes for workflow state machines.

All workflows (debug, PR comment, iterate) inherit from this base.
Provides:
- Phase definitions with tool restrictions
- Transition logic with kickback support
- State management via workflow_client
- Adversary gate integration points
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, FrozenSet, Optional, Any

import workflow_client
from permission_store import PermissionStore, PhasePermissions


class KickbackReason(Enum):
    """Standard reasons for phase kickback."""
    TESTS_FAILED = auto()
    LINT_FAILED = auto()
    COVERAGE_LOW = auto()
    ADVERSARY_REJECTED = auto()
    VERIFICATION_FAILED = auto()
    NEW_COMMENTS = auto()
    CI_FAILED = auto()
    CANNOT_REPRODUCE = auto()
    PREDICTION_NOT_CONFIRMED = auto()
    MAX_ITERATIONS = auto()


@dataclass(frozen=True)
class WorkflowPhase:
    """Definition of a workflow phase."""
    name: str
    allowed_tools: FrozenSet[str] = field(default_factory=frozenset)
    blocked_tools: FrozenSet[str] = field(default_factory=frozenset)
    allowed_file_patterns: FrozenSet[str] = field(default_factory=frozenset)
    required_outputs: list[str] = field(default_factory=list)
    adversary_gate: bool = False
    adversary_parallel: bool = False
    requires_verification: bool = False


@dataclass
class TransitionResult:
    """Result of attempting a phase transition."""
    success: bool
    next_phase: Optional[str] = None
    kickback_to: Optional[str] = None
    reason: Optional[KickbackReason] = None
    message: str = ""


@dataclass
class PhaseTransition:
    """Definition of a transition between phases."""
    from_phase: str
    to_phase: str
    condition: Optional[Callable[[dict], TransitionResult]] = None
    kickback_map: dict[KickbackReason, str] = field(default_factory=dict)


@dataclass
class WorkflowDefinition:
    """Complete definition of a workflow."""
    name: str
    phases: dict[str, WorkflowPhase]
    transitions: dict[str, PhaseTransition]
    initial_phase: str
    max_iterations: int = 5

    def get_phase(self, name: str) -> Optional[WorkflowPhase]:
        """Get phase by name."""
        return self.phases.get(name)

    def get_transition(self, from_phase: str) -> Optional[PhaseTransition]:
        """Get transition from a phase."""
        return self.transitions.get(from_phase)


class WorkflowEngine:
    """Executes a workflow definition as a state machine.

    Handles:
    - State persistence via workflow_client
    - Phase transitions with kickback logic
    - Tool restriction enforcement
    - Iteration counting
    """

    def __init__(self, definition: WorkflowDefinition, workflow_id: Optional[str] = None):
        self.definition = definition
        self.workflow_id = workflow_id or definition.name
        self._pending_objections: list = []

    def start(self, task: str, **initial_state) -> dict:
        """Start the workflow."""
        state = {
            "workflow_type": self.definition.name,
            "workflow_id": self.workflow_id,
            "active": True,
            "phase": self.definition.initial_phase,
            "task": task,
            "iteration": 0,
            "max_iterations": self.definition.max_iterations,
            **initial_state,
        }
        workflow_client.workflow_set_state(self.workflow_id, state)
        return state

    def get_state(self) -> Optional[dict]:
        """Get current workflow state."""
        return workflow_client.workflow_get_state(self.workflow_id)

    def get_phase(self) -> Optional[str]:
        """Get current phase name."""
        state = self.get_state()
        return state.get("phase") if state else None

    def is_active(self) -> bool:
        """Check if workflow is active."""
        state = self.get_state()
        return state.get("active", False) if state else False

    def get_permission_store(self) -> Optional[PermissionStore]:
        """Build PermissionStore from current workflow state.

        Returns:
            PermissionStore configured for current phase, or None if not active
        """
        state = self.get_state()
        if not state or not state.get("active"):
            return None

        phase_name = state.get("phase")
        phase = self.definition.get_phase(phase_name)

        # Build PhasePermissions from WorkflowPhase
        phase_perms = None
        if phase:
            phase_perms = PhasePermissions(
                blocked_tools=phase.blocked_tools,
                allowed_file_patterns=phase.allowed_file_patterns,
            )

        return PermissionStore(
            workflow_active=True,
            workflow_type=self.definition.name,
            workflow_id=self.workflow_id,
            phase=phase_name,
            phase_permissions=phase_perms,
        )

    def is_tool_allowed(
        self,
        tool_name: str,
        command: Optional[str] = None,
        file_path: Optional[str] = None
    ) -> tuple[bool, str]:
        """Check if tool is allowed in current phase.

        Args:
            tool_name: Name of the tool
            command: For Bash, the command string
            file_path: For Edit/Write, the target file path
        """
        store = self.get_permission_store()
        if not store:
            return True, "No active workflow"
        return store.is_tool_allowed(tool_name, file_path=file_path, command=command)

    def add_adversary_objection(self, objection: Any) -> None:
        """Add an adversary objection for current phase."""
        self._pending_objections.append(objection)

    def clear_objections(self) -> None:
        """Clear pending objections (after addressing them)."""
        self._pending_objections.clear()

    def advance(self, override_rationale: Optional[str] = None, user_approved: bool = False) -> TransitionResult:
        """Attempt to advance to next phase."""
        state = self.get_state()
        if not state or not state.get("active"):
            return TransitionResult(success=False, message="Workflow not active")

        current_phase_name = state.get("phase")
        transition = self.definition.get_transition(current_phase_name)

        if not transition:
            return TransitionResult(success=False, message=f"No transition from {current_phase_name}")

        # Evaluate transition condition
        if transition.condition:
            result = transition.condition(state)
        else:
            result = TransitionResult(success=True, next_phase=transition.to_phase)

        if result.success and result.next_phase:
            state["phase"] = result.next_phase
            workflow_client.workflow_set_state(self.workflow_id, state)
        elif result.kickback_to:
            state["phase"] = result.kickback_to
            state["iteration"] = state.get("iteration", 0) + 1
            if state["iteration"] >= state.get("max_iterations", 5):
                state["active"] = False
                state["exit_reason"] = "max_iterations"
                result = TransitionResult(
                    success=False,
                    reason=KickbackReason.MAX_ITERATIONS,
                    message="Max iterations reached"
                )
            workflow_client.workflow_set_state(self.workflow_id, state)

        return result

    def stop(self, reason: str = "user_stopped") -> None:
        """Stop the workflow."""
        state = self.get_state() or {}
        state["active"] = False
        state["exit_reason"] = reason
        workflow_client.workflow_set_state(self.workflow_id, state)

    def start_adversary_check(self) -> Optional[str]:
        """Start adversary check in background (for parallel execution).

        Returns task_id for polling, or None if no adversary gate.
        """
        state = self.get_state()
        if not state:
            return None

        phase = self.definition.get_phase(state.get("phase"))
        if not phase or not phase.adversary_gate:
            return None

        import uuid
        task_id = f"adversary-{uuid.uuid4().hex[:8]}"
        state["_adversary_task_id"] = task_id
        state["_adversary_started"] = True
        workflow_client.workflow_set_state(self.workflow_id, state)

        return task_id

    def get_adversary_result(self, task_id: str, block: bool = False) -> Optional[dict]:
        """Get result of parallel adversary check.

        Args:
            task_id: Task ID from start_adversary_check
            block: If True, wait for result

        Returns:
            Result dict or None if not ready
        """
        state = self.get_state()
        if not state or state.get("_adversary_task_id") != task_id:
            return None

        result = state.get("_adversary_result")
        if result:
            return result

        if not block:
            return None

        return {"status": "pending"}
