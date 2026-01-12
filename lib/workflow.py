"""Workflow state management for iterate/orchestrate workflows.

Provides a class-based interface for managing workflow state, replacing
the standalone iterate_state.py script with a reusable module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# State management
STATE_DIR = Path.home() / ".claude" / "plugins" / "agent-swarm" / ".state"
SESSION_FILE = STATE_DIR / "session.json"


def _load_state() -> dict[str, Any]:
    """Load session state from file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if SESSION_FILE.exists():
        return json.loads(SESSION_FILE.read_text())
    return {}


def _save_state(state: dict[str, Any]) -> None:
    """Save session state to file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(state, indent=2))


class Workflow:
    """Base class for workflow state management."""

    # Phase definitions (override in subclasses)
    PHASES: list[str] = []
    MODE: str = "base"

    def __init__(self, max_iterations: int = 5) -> None:
        """Initialize workflow and set workflow_invoked flag."""
        self.max_iterations = max_iterations
        self._init_state()

    def _init_state(self) -> None:
        """Initialize workflow state."""
        state = _load_state()
        state["mode"] = self.MODE
        state["iterate_phases"] = self.PHASES
        state["iterate_phase"] = self.PHASES[0] if self.PHASES else None
        state["iteration"] = 0
        state["max_iterations"] = self.max_iterations
        state["exit_reason"] = None
        state["workflow_invoked"] = True  # Unlock editing tools
        _save_state(state)

    @classmethod
    def is_active(cls) -> bool:
        """Check if any workflow is currently active."""
        state = _load_state()
        return state.get("workflow_invoked", False)

    @classmethod
    def current_phase(cls) -> str | None:
        """Get current workflow phase."""
        state = _load_state()
        return state.get("iterate_phase")

    @classmethod
    def current_mode(cls) -> str | None:
        """Get current workflow mode."""
        state = _load_state()
        return state.get("mode")

    @classmethod
    def transition_phase(cls, phase: str) -> None:
        """Transition to a new phase."""
        state = _load_state()
        phases = state.get("iterate_phases", [])
        if phase not in phases:
            raise ValueError(f"Invalid phase '{phase}'. Valid: {phases}")
        state["iterate_phase"] = phase
        _save_state(state)

    @classmethod
    def advance_phase(cls) -> str | None:
        """Advance to the next phase. Returns new phase or None if at end."""
        state = _load_state()
        phases = state.get("iterate_phases", [])
        current = state.get("iterate_phase")
        if current not in phases:
            return None
        idx = phases.index(current)
        if idx + 1 < len(phases):
            next_phase = phases[idx + 1]
            state["iterate_phase"] = next_phase
            _save_state(state)
            return next_phase
        return None

    @classmethod
    def increment_iteration(cls) -> int:
        """Increment iteration counter. Returns new count."""
        state = _load_state()
        state["iteration"] = state.get("iteration", 0) + 1
        _save_state(state)
        return state["iteration"]

    @classmethod
    def check_exit(cls) -> str | None:
        """Check if workflow should exit. Returns exit reason or None."""
        state = _load_state()
        # Already exited
        if state.get("exit_reason"):
            return state["exit_reason"]
        # Max iterations reached
        iteration = state.get("iteration", 0)
        max_iter = state.get("max_iterations", 5)
        if iteration >= max_iter:
            state["exit_reason"] = "max_reached"
            _save_state(state)
            return "max_reached"
        return None

    @classmethod
    def mark_exit(cls, reason: str) -> None:
        """Mark workflow as exited with reason."""
        state = _load_state()
        state["exit_reason"] = reason
        state["workflow_invoked"] = False
        _save_state(state)

    @classmethod
    def reset(cls) -> None:
        """Reset workflow state."""
        state = _load_state()
        state["workflow_invoked"] = False
        state["mode"] = None
        state["iterate_phases"] = []
        state["iterate_phase"] = None
        state["iteration"] = 0
        state["exit_reason"] = None
        _save_state(state)


class IterateWorkflow(Workflow):
    """Iterate workflow - always TDD."""

    PHASES = ["test_writing", "implement", "test", "coverage", "review"]

    def __init__(self, max_iterations: int = 5) -> None:
        """Initialize iterate workflow.

        Args:
            max_iterations: Maximum iterations before forced exit
        """
        # PHASES is set at class level
        self.MODE = "iterate-tdd"
        super().__init__(max_iterations)

    def show_status(self) -> str:
        """Return human-readable status string."""
        state = _load_state()
        phase = state.get("iterate_phase", "unknown")
        iteration = state.get("iteration", 0)
        max_iter = state.get("max_iterations", 5)
        phases = " -> ".join(self.PHASES)
        return (
            f"[ITERATE] TDD mode\n"
            f"  Phase: {phase}\n"
            f"  Iteration: {iteration}/{max_iter}\n"
            f"  Phases: {phases}"
        )


class OrchestrateWorkflow(Workflow):
    """Orchestrate workflow with user checkpoints."""

    PHASES = ["intake", "design", "implement", "verify", "review"]
    MODE = "orchestrate"

    def __init__(self, max_iterations: int = 10) -> None:
        """Initialize orchestrate workflow."""
        super().__init__(max_iterations)

    def show_status(self) -> str:
        """Return human-readable status string."""
        state = _load_state()
        phase = state.get("iterate_phase", "unknown")
        iteration = state.get("iteration", 0)
        max_iter = state.get("max_iterations", 10)
        phases = " -> ".join(self.PHASES)
        return (
            f"[ORCHESTRATE] Checkpoint mode\n"
            f"  Phase: {phase}\n"
            f"  Iteration: {iteration}/{max_iter}\n"
            f"  Phases: {phases}"
        )


# CLI support for manual invocation
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Workflow state management")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # iterate init
    init_parser = subparsers.add_parser("iterate", help="Initialize iterate workflow")
    init_parser.add_argument("--max", type=int, default=5, help="Max iterations")

    # orchestrate init
    orch_parser = subparsers.add_parser("orchestrate", help="Initialize orchestrate workflow")
    orch_parser.add_argument("--max", type=int, default=10, help="Max iterations")

    # status
    subparsers.add_parser("status", help="Show workflow status")

    # reset
    subparsers.add_parser("reset", help="Reset workflow state")

    # advance
    subparsers.add_parser("advance", help="Advance to next phase")

    args = parser.parse_args()

    if args.command == "iterate":
        wf = IterateWorkflow(max_iterations=args.max)
        print(wf.show_status())
    elif args.command == "orchestrate":
        wf = OrchestrateWorkflow(max_iterations=args.max)
        print(wf.show_status())
    elif args.command == "status":
        if Workflow.is_active():
            mode = Workflow.current_mode()
            if mode and "iterate" in mode:
                # Recreate with current state
                state = _load_state()
                tdd = mode == "iterate-tdd"
                print(f"[ITERATE] {'TDD' if tdd else 'Quick'} mode")
                print(f"  Phase: {state.get('iterate_phase')}")
                print(f"  Iteration: {state.get('iteration')}/{state.get('max_iterations')}")
            elif mode == "orchestrate":
                state = _load_state()
                print("[ORCHESTRATE] Checkpoint mode")
                print(f"  Phase: {state.get('iterate_phase')}")
                print(f"  Iteration: {state.get('iteration')}/{state.get('max_iterations')}")
            else:
                print(f"[WORKFLOW] Active (mode: {mode})")
        else:
            print("[WORKFLOW] No active workflow")
    elif args.command == "reset":
        Workflow.reset()
        print("[WORKFLOW] Reset complete")
    elif args.command == "advance":
        next_phase = Workflow.advance_phase()
        if next_phase:
            print(f"[WORKFLOW] Advanced to: {next_phase}")
        else:
            print("[WORKFLOW] Already at final phase")
