"""Workflow state management for iterate/orchestrate workflows.

Provides a class-based interface for managing workflow state, replacing
the standalone iterate_state.py script with a reusable module.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Add scripts to path for TaskQueue import
_scripts_path = Path(__file__).parent.parent / "scripts"
if str(_scripts_path) not in sys.path:
    sys.path.insert(0, str(_scripts_path))

try:
    from iterate_state import TaskQueue, TaskStatus, load_queue, save_queue
    QUEUE_AVAILABLE = True
except ImportError:
    QUEUE_AVAILABLE = False

# State management - use agent_state for per-agent isolation
from agent_state import load_state as _load_state, save_state as _save_state, STATE_DIR


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
        initial_phase = self.PHASES[0] if self.PHASES else None
        state["iterate_phase"] = initial_phase
        state["phase"] = initial_phase  # Unified phase field (INT.5)
        state["iteration"] = 0
        state["max_iterations"] = self.max_iterations
        state["exit_reason"] = None
        state["workflow_invoked"] = True  # Unlock editing tools
        state["phase_banner_shown"] = False  # SAFE.5.1: Require banner before work
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
        state["phase"] = phase  # Keep unified field in sync
        state["phase_banner_shown"] = False  # SAFE.5.3: Require new banner
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
            state["phase"] = next_phase  # Keep unified field in sync
            state["phase_banner_shown"] = False  # SAFE.5.3: Require new banner
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

    @classmethod
    def mark_banner_shown(cls) -> None:
        """Mark that the phase banner has been shown (SAFE.5.1)."""
        state = _load_state()
        state["phase_banner_shown"] = True
        _save_state(state)

    @classmethod
    def is_banner_shown(cls) -> bool:
        """Check if the phase banner has been shown (SAFE.5.2)."""
        state = _load_state()
        return state.get("phase_banner_shown", False)


class IterateWorkflow(Workflow):
    """Iterate workflow - always TDD."""

    # TDD phases - subagents use these, orchestrator stays in "orchestrate"
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

    @classmethod
    def get_phase_tasks(cls, phase: str | None = None) -> list[Any]:
        """Get tasks for a specific phase (or current phase).

        Args:
            phase: Phase to get tasks for, or None for current phase

        Returns:
            List of Task objects for the phase
        """
        if not QUEUE_AVAILABLE:
            return []
        queue = load_queue()
        if not queue:
            return []
        if phase is None:
            phase = cls.current_phase()
        return [t for t in queue.tasks.values() if t.phase == phase]

    @classmethod
    def phase_complete(cls, phase: str | None = None) -> bool:
        """Check if all tasks for a phase are completed.

        Args:
            phase: Phase to check, or None for current phase

        Returns:
            True if all phase tasks are completed (or no tasks exist)
        """
        tasks = cls.get_phase_tasks(phase)
        if not tasks:
            return True  # No tasks = phase complete
        return all(t.status == TaskStatus.COMPLETED for t in tasks)

    @classmethod
    def check_auto_advance(cls) -> str | None:
        """Check if phase is complete and auto-advance if so.

        Returns:
            New phase name if advanced, None if staying in current phase
        """
        if cls.phase_complete():
            return cls.advance_phase()
        return None

    @classmethod
    def get_queue_summary(cls) -> str:
        """Get a summary of the task queue status."""
        if not QUEUE_AVAILABLE:
            return "Queue not available"
        queue = load_queue()
        if not queue:
            return "No queue loaded"

        tasks = list(queue.tasks.values())
        by_phase: dict[str, dict[str, int]] = {}
        for t in tasks:
            if t.phase not in by_phase:
                by_phase[t.phase] = {"total": 0, "completed": 0, "pending": 0}
            by_phase[t.phase]["total"] += 1
            if t.status == TaskStatus.COMPLETED:
                by_phase[t.phase]["completed"] += 1
            elif t.status == TaskStatus.PENDING:
                by_phase[t.phase]["pending"] += 1

        lines = ["=== Queue Summary ==="]
        for phase in cls.PHASES:
            if phase in by_phase:
                stats = by_phase[phase]
                lines.append(f"  {phase}: {stats['completed']}/{stats['total']} done")
        total = len(tasks)
        completed = len([t for t in tasks if t.status == TaskStatus.COMPLETED])
        lines.append(f"  Total: {completed}/{total} ({100*completed//total if total else 0}%)")
        return "\n".join(lines)


# Priority names for display
PRIORITY_NAMES = {
    0: "CRITICAL",
    1: "HIGH",
    2: "MEDIUM",
    3: "LOW",
    4: "DONE",
}


def _make_progress_bar(done: int, total: int, width: int = 20) -> str:
    """Create a visual progress bar.

    Args:
        done: Number of completed items
        total: Total number of items
        width: Width of the bar in characters

    Returns:
        Formatted progress bar string like "[========            ] 8/20"
    """
    if total == 0:
        return f"[{'=' * width}] 0/0"
    filled = int(width * done / total)
    empty = width - filled
    return f"[{'=' * filled}{' ' * empty}] {done}/{total}"


def show_queue_status() -> str:
    """Display queue status with visual progress bars per priority group.

    Returns:
        Formatted string showing queue progress by priority group.
    """
    state = _load_state()
    queue_data = state.get("queue", {})
    tasks = queue_data.get("tasks", {})

    if not tasks:
        return "[QUEUE] No tasks - queue empty"

    # Group by priority
    by_priority: dict[int, dict[str, int]] = {}
    for task_data in tasks.values():
        priority = task_data.get("priority", 3)
        status = task_data.get("status", "pending")

        if priority not in by_priority:
            by_priority[priority] = {"total": 0, "completed": 0, "running": 0, "pending": 0}

        by_priority[priority]["total"] += 1
        if status == "completed":
            by_priority[priority]["completed"] += 1
        elif status == "running":
            by_priority[priority]["running"] += 1
        else:
            by_priority[priority]["pending"] += 1

    # Build output
    lines = ["=== Queue Status ==="]

    # Sort by priority (0 = highest)
    for priority in sorted(by_priority.keys()):
        stats = by_priority[priority]
        name = PRIORITY_NAMES.get(priority, f"P{priority}")
        bar = _make_progress_bar(stats["completed"], stats["total"], width=15)
        running_indicator = f" ({stats['running']} running)" if stats["running"] > 0 else ""
        lines.append(f"  {name:<10} {bar}{running_indicator}")

    # Overall totals
    total_tasks = len(tasks)
    completed_tasks = sum(1 for t in tasks.values() if t.get("status") == "completed")
    running_tasks = sum(1 for t in tasks.values() if t.get("status") == "running")
    pending_tasks = total_tasks - completed_tasks - running_tasks

    pct = int(100 * completed_tasks / total_tasks) if total_tasks > 0 else 100
    lines.append(f"  {'TOTAL':<10} {_make_progress_bar(completed_tasks, total_tasks, width=15)} {pct}%")

    if running_tasks > 0:
        lines.append(f"  Active: {running_tasks} task(s) running")

    return "\n".join(lines)


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

    # stop (alias for reset with clearer semantics)
    subparsers.add_parser("stop", help="Stop active workflow")

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
    elif args.command == "stop":
        if Workflow.is_active():
            Workflow.reset()
            print("[WORKFLOW] Stopped")
        else:
            print("[WORKFLOW] No active workflow to stop")
    elif args.command == "advance":
        next_phase = Workflow.advance_phase()
        if next_phase:
            print(f"[WORKFLOW] Advanced to: {next_phase}")
        else:
            print("[WORKFLOW] Already at final phase")
