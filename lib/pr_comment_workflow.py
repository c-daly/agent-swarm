"""PR Comment workflow - understanding before fixing.

Phases:
  UNDERSTAND → FIX → VERIFY → PUSH → CHECK_REVIEWS → DONE
"""

from enum import Enum
from typing import Optional

import workflow_client
from workflow_base import (
    WorkflowEngine, WorkflowDefinition, WorkflowPhase,
    PhaseTransition, TransitionResult, KickbackReason
)


class PRCommentPhase(str, Enum):
    """PR comment workflow phases."""
    UNDERSTAND = "understand"
    FIX = "fix"
    VERIFY = "verify"
    PUSH = "push"
    CHECK_REVIEWS = "check_reviews"
    DONE = "done"


PR_COMMENT_PHASES = {
    PRCommentPhase.UNDERSTAND.value: WorkflowPhase(
        name="understand",
        allowed_tools=frozenset({"Read", "Glob", "Grep"}),
        blocked_tools=frozenset({"Edit", "Write", "Bash"}),
        required_outputs=["articulation", "current_code_problem"],
        adversary_gate=True,  # Adversary validates understanding
    ),
    PRCommentPhase.FIX.value: WorkflowPhase(
        name="fix",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Edit", "Write", "Bash"}),
        adversary_gate=True,  # Adversary checks fix matches understanding
    ),
    PRCommentPhase.VERIFY.value: WorkflowPhase(
        name="verify",
        allowed_tools=frozenset({"Read", "Glob", "Grep", "Bash"}),
        blocked_tools=frozenset({"Edit", "Write"}),
        requires_verification=True,
    ),
    PRCommentPhase.PUSH.value: WorkflowPhase(
        name="push",
        allowed_tools=frozenset({"Bash"}),
    ),
    PRCommentPhase.CHECK_REVIEWS.value: WorkflowPhase(
        name="check_reviews",
        allowed_tools=frozenset({"Read", "Bash"}),
        blocked_tools=frozenset({"Edit", "Write"}),
    ),
    PRCommentPhase.DONE.value: WorkflowPhase(
        name="done",
        allowed_tools=frozenset(),
    ),
}


def _make_transitions() -> dict[str, PhaseTransition]:
    """Create transitions with kickback logic."""

    def understand_to_fix(state: dict) -> TransitionResult:
        if not state.get("articulation"):
            return TransitionResult(
                success=False,
                message="Must articulate reviewer's concern"
            )
        return TransitionResult(success=True, next_phase="fix")

    def fix_to_verify(state: dict) -> TransitionResult:
        return TransitionResult(success=True, next_phase="verify")

    def verify_to_push(state: dict) -> TransitionResult:
        if not state.get("tests_pass") or not state.get("lint_pass"):
            return TransitionResult(
                success=False,
                kickback_to="fix",
                reason=KickbackReason.VERIFICATION_FAILED,
            )
        return TransitionResult(success=True, next_phase="push")

    def push_to_check(state: dict) -> TransitionResult:
        return TransitionResult(success=True, next_phase="check_reviews")

    def check_to_done(state: dict) -> TransitionResult:
        if state.get("new_comments"):
            return TransitionResult(
                success=False,
                kickback_to="understand",
                reason=KickbackReason.NEW_COMMENTS,
                message="New review comments - re-understand"
            )
        return TransitionResult(success=True, next_phase="done")

    return {
        "understand": PhaseTransition("understand", "fix", condition=understand_to_fix),
        "fix": PhaseTransition("fix", "verify", condition=fix_to_verify),
        "verify": PhaseTransition("verify", "push", condition=verify_to_push),
        "push": PhaseTransition("push", "check_reviews", condition=push_to_check),
        "check_reviews": PhaseTransition("check_reviews", "done", condition=check_to_done),
    }


PR_COMMENT_DEFINITION = WorkflowDefinition(
    name="pr_comment",
    phases=PR_COMMENT_PHASES,
    transitions=_make_transitions(),
    initial_phase="understand",
    max_iterations=3,  # Fewer iterations - escalate faster
)


class PRCommentWorkflow:
    """PR Comment workflow - understanding before fixing."""

    def __init__(self):
        self.engine = WorkflowEngine(PR_COMMENT_DEFINITION, workflow_id="pr_comment")

    def start(self, comment: str, pr_number: int, **kwargs) -> dict:
        """Start workflow for a PR comment."""
        return self.engine.start(
            task=f"Address PR comment: {comment[:50]}...",
            comment=comment,
            pr_number=pr_number,
            **kwargs
        )

    def get_phase(self) -> Optional[str]:
        return self.engine.get_phase()

    def set_phase(self, phase: str) -> None:
        """Manually set phase (for testing/recovery)."""
        state = self.engine.get_state() or {}
        state["phase"] = phase
        workflow_client.workflow_set_state("pr_comment", state)

    def is_tool_allowed(self, tool_name: str, **kwargs) -> tuple[bool, str]:
        return self.engine.is_tool_allowed(tool_name, **kwargs)

    def advance(self, **kwargs) -> TransitionResult:
        """Advance to next phase."""
        return self.engine.advance(**kwargs)

    def record_understanding(self, articulation: str, problem: str) -> None:
        """Record understanding of reviewer's concern."""
        state = self.engine.get_state() or {}
        state["articulation"] = articulation
        state["current_code_problem"] = problem
        workflow_client.workflow_set_state("pr_comment", state)

    def record_verification(self, tests_pass: bool, lint_pass: bool) -> None:
        """Record verification results."""
        state = self.engine.get_state() or {}
        state["tests_pass"] = tests_pass
        state["lint_pass"] = lint_pass
        workflow_client.workflow_set_state("pr_comment", state)

    def stop(self) -> None:
        """Stop the workflow."""
        self.engine.stop()


def is_active() -> bool:
    """Check if pr_comment workflow is active."""
    return workflow_client.workflow_is_active("pr_comment")


def status() -> str:
    """Get formatted status."""
    if not is_active():
        return "[PR-COMMENT] Not active"

    wf = PRCommentWorkflow()
    state = wf.engine.get_state() or {}
    phase = state.get("phase", "unknown")
    pr = state.get("pr_number", "?")
    comment = state.get("comment", "")[:40]

    return f"""[PR-COMMENT] Active
  Phase: {phase}
  PR: #{pr}
  Comment: {comment}..."""


if __name__ == "__main__":
    import sys

    def usage():
        print("Usage: python pr_comment_workflow.py <command> [args]")
        print()
        print("Commands:")
        print("  start <comment> <pr_num>  Start workflow for PR comment")
        print("  status                    Show current status")
        print("  phase                     Show current phase")
        print("  set-phase <phase>         Manually set phase")
        print("  understand <art> <prob>   Record understanding")
        print("  verify <tests> <lint>     Record verification (1=pass, 0=fail)")
        print("  advance                   Advance to next phase")
        print("  stop                      Stop workflow")

    COMMANDS = {"start", "status", "phase", "set-phase", "understand",
                "verify", "advance", "stop", "help"}

    if len(sys.argv) < 2:
        if is_active():
            print(status())
        else:
            usage()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "start":
        if len(sys.argv) < 4:
            print("Usage: start <comment> <pr_number>")
            sys.exit(1)
        comment = sys.argv[2]
        pr_num = int(sys.argv[3])
        wf = PRCommentWorkflow()
        wf.start(comment, pr_num)
        print(status())

    elif cmd == "status":
        print(status())

    elif cmd == "phase":
        if is_active():
            wf = PRCommentWorkflow()
            print(wf.get_phase())
        else:
            print("Not active")

    elif cmd == "set-phase":
        if len(sys.argv) < 3:
            print("Usage: set-phase <phase>")
            sys.exit(1)
        wf = PRCommentWorkflow()
        wf.set_phase(sys.argv[2])
        print(f"Phase set to: {sys.argv[2]}")

    elif cmd == "understand":
        if len(sys.argv) < 4:
            print("Usage: understand <articulation> <problem>")
            sys.exit(1)
        wf = PRCommentWorkflow()
        wf.record_understanding(sys.argv[2], sys.argv[3])
        print("Understanding recorded")

    elif cmd == "verify":
        if len(sys.argv) < 4:
            print("Usage: verify <tests_pass> <lint_pass>")
            sys.exit(1)
        wf = PRCommentWorkflow()
        wf.record_verification(sys.argv[2] == "1", sys.argv[3] == "1")
        print("Verification recorded")

    elif cmd == "advance":
        wf = PRCommentWorkflow()
        result = wf.advance()
        if result.success:
            print(f"Advanced to: {result.next_phase}")
        else:
            if result.kickback_to:
                print(f"Kicked back to: {result.kickback_to}")
                print(f"Reason: {result.message}")
            else:
                print(f"Cannot advance: {result.message}")

    elif cmd == "stop":
        wf = PRCommentWorkflow()
        wf.stop()
        print("Workflow stopped")

    elif cmd == "help":
        usage()

    else:
        usage()
        sys.exit(1)
