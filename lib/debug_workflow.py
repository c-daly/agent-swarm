"""Debug workflow - root cause verification before fixing.

Phases:
  TRIAGE → REPRODUCE → HYPOTHESIZE → PROVE → FIX → VERIFY → PUSH → CHECK_STATUS → DONE
"""

from enum import Enum
from typing import Optional

import workflow_client
from workflow_base import (
    WorkflowEngine, WorkflowDefinition, WorkflowPhase,
    PhaseTransition, TransitionResult, KickbackReason
)


class DebugPhase(str, Enum):
    """Debug workflow phases."""
    TRIAGE = "triage"
    REPRODUCE = "reproduce"
    HYPOTHESIZE = "hypothesize"
    PROVE = "prove"
    FIX = "fix"
    VERIFY = "verify"
    PUSH = "push"
    CHECK_STATUS = "check_status"
    DONE = "done"


# Phase definitions with tool restrictions
DEBUG_PHASES = {
    DebugPhase.TRIAGE.value: WorkflowPhase(
        name="triage",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "WebSearch", "WebFetch"}),
        blocked_tools=frozenset({"Edit", "Write"}),
        required_outputs=["severity", "affected_components", "error_artifacts"],
    ),
    DebugPhase.REPRODUCE.value: WorkflowPhase(
        name="reproduce",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Edit", "Write", "Bash"}),
        allowed_file_patterns=frozenset({
            "tests/**", "*_test.py", "test_*.py",
            "conftest.py", "fixtures/**", "mocks/**"
        }),
        required_outputs=["failing_test"],
    ),
    DebugPhase.HYPOTHESIZE.value: WorkflowPhase(
        name="hypothesize",
        allowed_tools=frozenset({"Read", "Glob", "Grep"}),
        blocked_tools=frozenset({"Edit", "Write"}),
        required_outputs=["hypothesis", "prediction"],
        adversary_gate=True,  # Adversary challenges hypothesis
    ),
    DebugPhase.PROVE.value: WorkflowPhase(
        name="prove",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Bash"}),
        blocked_tools=frozenset({"Edit", "Write"}),
        required_outputs=["prediction_confirmed", "mechanism_traced", "alternative_ruled_out"],
        adversary_gate=True,  # Adversary verifies proof
    ),
    DebugPhase.FIX.value: WorkflowPhase(
        name="fix",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Edit", "Write", "Bash"}),
        adversary_gate=True,  # Adversary checks fix matches proof
    ),
    DebugPhase.VERIFY.value: WorkflowPhase(
        name="verify",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Bash"}),
        blocked_tools=frozenset({"Edit", "Write"}),
        requires_verification=True,
    ),
    DebugPhase.PUSH.value: WorkflowPhase(
        name="push",
        allowed_tools=frozenset({"Bash"}),
    ),
    DebugPhase.CHECK_STATUS.value: WorkflowPhase(
        name="check_status",
        allowed_tools=frozenset({"Read", "Bash"}),
        blocked_tools=frozenset({"Edit", "Write"}),
    ),
    DebugPhase.DONE.value: WorkflowPhase(
        name="done",
        allowed_tools=frozenset(),
    ),
}


def _make_transitions() -> dict[str, PhaseTransition]:
    """Create transition definitions with kickback logic."""

    def triage_to_reproduce(state: dict) -> TransitionResult:
        required = ["severity", "affected_components", "error_artifacts"]
        missing = [r for r in required if not state.get(r)]
        if missing:
            return TransitionResult(
                success=False,
                message=f"Missing triage outputs: {missing}"
            )
        return TransitionResult(success=True, next_phase="reproduce")

    def reproduce_to_hypothesize(state: dict) -> TransitionResult:
        if not state.get("failing_test"):
            return TransitionResult(
                success=False,
                kickback_to="triage",
                reason=KickbackReason.CANNOT_REPRODUCE,
                message="Cannot reproduce - need more context"
            )
        return TransitionResult(success=True, next_phase="hypothesize")

    def hypothesize_to_prove(state: dict) -> TransitionResult:
        if not state.get("hypothesis") or not state.get("prediction"):
            return TransitionResult(
                success=False,
                message="Hypothesis and prediction required"
            )
        return TransitionResult(success=True, next_phase="prove")

    def prove_to_fix(state: dict) -> TransitionResult:
        if not state.get("prediction_confirmed"):
            return TransitionResult(
                success=False,
                kickback_to="hypothesize",
                reason=KickbackReason.PREDICTION_NOT_CONFIRMED,
                message="Prediction not confirmed - revise hypothesis"
            )
        return TransitionResult(success=True, next_phase="fix")

    def fix_to_verify(state: dict) -> TransitionResult:
        return TransitionResult(success=True, next_phase="verify")

    def verify_to_push(state: dict) -> TransitionResult:
        tests_pass = state.get("tests_pass", False)
        lint_pass = state.get("lint_pass", False)

        if not tests_pass or not lint_pass:
            return TransitionResult(
                success=False,
                kickback_to="prove",
                reason=KickbackReason.VERIFICATION_FAILED,
                message="Verification failed - re-examine root cause"
            )
        return TransitionResult(success=True, next_phase="push")

    def push_to_check(state: dict) -> TransitionResult:
        return TransitionResult(success=True, next_phase="check_status")

    def check_to_done(state: dict) -> TransitionResult:
        ci_pass = state.get("ci_pass", False)
        no_new_comments = not state.get("new_review_comments", False)

        if not ci_pass or not no_new_comments:
            return TransitionResult(
                success=False,
                kickback_to="prove",
                reason=KickbackReason.CI_FAILED if not ci_pass else KickbackReason.NEW_COMMENTS,
                message="Check status failed - revisit understanding"
            )
        return TransitionResult(success=True, next_phase="done")

    return {
        "triage": PhaseTransition("triage", "reproduce", condition=triage_to_reproduce),
        "reproduce": PhaseTransition("reproduce", "hypothesize", condition=reproduce_to_hypothesize),
        "hypothesize": PhaseTransition("hypothesize", "prove", condition=hypothesize_to_prove),
        "prove": PhaseTransition("prove", "fix", condition=prove_to_fix),
        "fix": PhaseTransition("fix", "verify", condition=fix_to_verify),
        "verify": PhaseTransition("verify", "push", condition=verify_to_push),
        "push": PhaseTransition("push", "check_status", condition=push_to_check),
        "check_status": PhaseTransition("check_status", "done", condition=check_to_done),
    }


DEBUG_DEFINITION = WorkflowDefinition(
    name="debug",
    phases=DEBUG_PHASES,
    transitions=_make_transitions(),
    initial_phase="triage",
    max_iterations=5,
)


class DebugWorkflow:
    """Debug workflow - enforces root cause verification."""

    def __init__(self):
        self.engine = WorkflowEngine(DEBUG_DEFINITION, workflow_id="debug")

    def start(self, bug_report: str, **kwargs) -> dict:
        """Start debug workflow."""
        return self.engine.start(task=bug_report, bug_report=bug_report, **kwargs)

    def get_phase(self) -> Optional[str]:
        """Get current phase."""
        return self.engine.get_phase()

    def set_phase(self, phase: str) -> None:
        """Manually set phase (for testing/recovery)."""
        state = self.engine.get_state() or {}
        state["phase"] = phase
        workflow_client.workflow_set_state("debug", state)

    def is_tool_allowed(self, tool_name: str, file_path: Optional[str] = None) -> tuple[bool, str]:
        """Check tool restriction."""
        return self.engine.is_tool_allowed(tool_name, file_path=file_path)

    def advance(self, **kwargs) -> TransitionResult:
        """Advance to next phase."""
        return self.engine.advance(**kwargs)

    def record_triage(self, severity: str, components: list, artifacts: list) -> None:
        """Record triage outputs."""
        state = self.engine.get_state() or {}
        state["severity"] = severity
        state["affected_components"] = components
        state["error_artifacts"] = artifacts
        workflow_client.workflow_set_state("debug", state)

    def record_hypothesis(self, hypothesis: str, prediction: str) -> None:
        """Record hypothesis and prediction."""
        state = self.engine.get_state() or {}
        state["hypothesis"] = hypothesis
        state["prediction"] = prediction
        workflow_client.workflow_set_state("debug", state)
