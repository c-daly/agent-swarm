"""Implementer workflow - simple default for general implementation tasks.

A minimal workflow for agents that need to do work without the ceremony
of specialized workflows like debug or iterate. Use this as the default
when no better workflow applies.

Phases:
  WORK → VERIFY → DONE
"""

from enum import Enum
from typing import Optional

import workflow_client
from workflow_base import (
    WorkflowEngine, WorkflowDefinition, WorkflowPhase,
    PhaseTransition, TransitionResult, KickbackReason
)


class ImplementerPhase(str, Enum):
    """Implementer workflow phases."""
    WORK = "work"
    VERIFY = "verify"
    DONE = "done"


# Phase definitions - permissive by default
IMPLEMENTER_PHASES = {
    ImplementerPhase.WORK.value: WorkflowPhase(
        name="work",
        # All tools allowed - this is a permissive default workflow
        allowed_tools=frozenset({
            "Read", "Glob", "Grep", "Edit", "Write", "Bash",
            "Task", "TaskOutput", "WebSearch", "WebFetch"
        }),
        blocked_tools=frozenset(),
    ),
    ImplementerPhase.VERIFY.value: WorkflowPhase(
        name="verify",
        # Verification still allows edits - agent may need to fix issues
        allowed_tools=frozenset({
            "Read", "Glob", "Grep", "Edit", "Write", "Bash",
            "Task", "TaskOutput"
        }),
        blocked_tools=frozenset(),
        requires_verification=True,
    ),
    ImplementerPhase.DONE.value: WorkflowPhase(
        name="done",
        allowed_tools=frozenset(),
    ),
}


def _make_transitions() -> dict[str, PhaseTransition]:
    """Create transition definitions."""

    def work_to_verify(state: dict) -> TransitionResult:  # noqa: ARG001
        """Transition when work is complete."""
        # No strict requirements - agent decides when ready
        return TransitionResult(success=True, next_phase="verify")

    def verify_to_done(state: dict) -> TransitionResult:
        """Check verification passed before completing."""
        tests_pass = state.get("tests_pass", True)  # Default to True if not tracked
        lint_pass = state.get("lint_pass", True)

        if not tests_pass:
            return TransitionResult(
                success=False,
                kickback_to="work",
                reason=KickbackReason.TESTS_FAILED,
                message="Tests failed - fix before completing"
            )
        if not lint_pass:
            return TransitionResult(
                success=False,
                kickback_to="work",
                reason=KickbackReason.LINT_FAILED,
                message="Lint failed - fix before completing"
            )
        return TransitionResult(success=True, next_phase="done")

    return {
        "work": PhaseTransition("work", "verify", condition=work_to_verify),
        "verify": PhaseTransition("verify", "done", condition=verify_to_done),
    }


IMPLEMENTER_DEFINITION = WorkflowDefinition(
    name="implementer",
    phases=IMPLEMENTER_PHASES,
    transitions=_make_transitions(),
    initial_phase="work",
    max_iterations=3,
)


class ImplementerWorkflow:
    """Simple workflow for general implementation tasks.

    Use this as the default when:
    - No specialized workflow (debug, iterate, pr_comment) applies
    - You just need to do work with basic verification
    - Subagents need a workflow but don't need heavy ceremony
    """

    def __init__(self, workflow_id: str = "implementer"):
        self.workflow_id = workflow_id
        self.engine = WorkflowEngine(IMPLEMENTER_DEFINITION, workflow_id=workflow_id)

    def start(self, task: str, **kwargs) -> dict:
        """Start implementer workflow."""
        return self.engine.start(task=task, **kwargs)

    def get_phase(self) -> Optional[str]:
        """Get current phase."""
        return self.engine.get_phase()

    def set_phase(self, phase: str) -> None:
        """Manually set phase (for testing/recovery)."""
        state = self.engine.get_state() or {}
        state["phase"] = phase
        workflow_client.workflow_set_state(self.workflow_id, state)

    def is_tool_allowed(self, tool_name: str, file_path: Optional[str] = None) -> tuple[bool, str]:
        """Check tool restriction."""
        return self.engine.is_tool_allowed(tool_name, file_path=file_path)

    def advance(self, **kwargs) -> TransitionResult:
        """Advance to next phase."""
        return self.engine.advance(**kwargs)

    def record_verification(self, tests_pass: bool, lint_pass: bool) -> None:
        """Record verification results."""
        state = self.engine.get_state() or {}
        state["tests_pass"] = tests_pass
        state["lint_pass"] = lint_pass
        workflow_client.workflow_set_state(self.workflow_id, state)

    def stop(self) -> None:
        """Stop the workflow."""
        self.engine.stop()


def is_active(workflow_id: str = "implementer") -> bool:
    """Check if implementer workflow is active."""
    return workflow_client.workflow_is_active(workflow_id)


def status(workflow_id: str = "implementer") -> str:
    """Get formatted status."""
    if not is_active(workflow_id):
        return f"[IMPLEMENTER:{workflow_id}] Not active"

    wf = ImplementerWorkflow(workflow_id)
    state = wf.engine.get_state() or {}
    phase = state.get("phase", "unknown")
    task = state.get("task", "")[:50]
    iteration = state.get("iteration", 0)

    return f"""[IMPLEMENTER:{workflow_id}] Active
  Phase: {phase}
  Task: {task}
  Iteration: {iteration}"""


if __name__ == "__main__":
    import sys

    def usage():
        print("Usage: python implementer_workflow.py <command> [args]")
        print()
        print("Commands:")
        print("  start <task>             Start implementer workflow")
        print("  status                   Show current status")
        print("  phase                    Show current phase")
        print("  set-phase <phase>        Manually set phase")
        print("  verify <tests> <lint>    Record verification (1=pass, 0=fail)")
        print("  advance                  Advance to next phase")
        print("  stop                     Stop workflow")

    COMMANDS = {"start", "status", "phase", "set-phase", "verify", "advance", "stop", "help"}

    # Support --id flag for custom workflow IDs
    workflow_id = "implementer"
    args = sys.argv[1:]
    if "--id" in args:
        idx = args.index("--id")
        if idx + 1 < len(args):
            workflow_id = args[idx + 1]
            args = args[:idx] + args[idx + 2:]

    if len(args) < 1:
        if is_active(workflow_id):
            print(status(workflow_id))
        else:
            usage()
        sys.exit(0)

    cmd = args[0]

    # Auto-start if first arg isn't a command
    if cmd not in COMMANDS:
        task = " ".join(args)
        wf = ImplementerWorkflow(workflow_id)
        wf.start(task)
        print(status(workflow_id))
        sys.exit(0)

    if cmd == "start":
        task = " ".join(args[1:]) if len(args) > 1 else "General implementation task"
        wf = ImplementerWorkflow(workflow_id)
        wf.start(task)
        print(status(workflow_id))

    elif cmd == "status":
        print(status(workflow_id))

    elif cmd == "phase":
        if is_active(workflow_id):
            wf = ImplementerWorkflow(workflow_id)
            print(wf.get_phase())
        else:
            print("Not active")

    elif cmd == "set-phase":
        if len(args) < 2:
            print("Usage: set-phase <phase>")
            sys.exit(1)
        wf = ImplementerWorkflow(workflow_id)
        wf.set_phase(args[1])
        print(f"Phase set to: {args[1]}")

    elif cmd == "verify":
        if len(args) < 3:
            print("Usage: verify <tests_pass> <lint_pass>")
            sys.exit(1)
        wf = ImplementerWorkflow(workflow_id)
        wf.record_verification(args[1] == "1", args[2] == "1")
        print("Verification recorded")

    elif cmd == "advance":
        wf = ImplementerWorkflow(workflow_id)
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
        wf = ImplementerWorkflow(workflow_id)
        wf.stop()
        print("Workflow stopped")

    elif cmd == "help":
        usage()

    else:
        usage()
        sys.exit(1)
