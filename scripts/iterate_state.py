#!/usr/bin/env python3
"""State management for iterate workflow.

Usage:
    python3 iterate_state.py init [--tdd] [--max-iter N]
    python3 iterate_state.py phase <next|back>
    python3 iterate_state.py check
    python3 iterate_state.py exit <reason>
    python3 iterate_state.py show
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# =============================================================================
# Task Queue Enums and Constants
# =============================================================================

class TaskStatus(str, Enum):
    """Status of a task in the queue."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskSource(str, Enum):
    """Source/origin of a task."""
    ORIGINAL = "original"           # User-requested task
    GREPTILE = "greptile"           # From Greptile review
    TEST_FAILURE = "test_failure"   # From test failure
    COVERAGE_GAP = "coverage_gap"   # From coverage analysis


# Priority constants (lower = higher priority)
PRIORITY_TEST_FAILURE = 0
PRIORITY_GREPTILE_CRITICAL = 1
PRIORITY_GREPTILE_WARNING = 2
PRIORITY_ORIGINAL = 3
PRIORITY_COVERAGE_GAP = 4


# Phase execution model
PARALLEL_PHASES = {"test_writing", "implement"}  # Tasks run independently
SYNC_PHASES = {"test", "coverage", "review"}     # Tasks sync per-PR


@dataclass
class Task:
    """A task in the queue."""
    id: str                          # UUID, e.g., "task-a1b2c3d4"
    description: str                 # Human-readable task description
    status: TaskStatus               # Enum: pending, running, completed, failed
    priority: int                    # 0=highest (test_failure), 4=lowest (coverage_gap)
    source: TaskSource               # Enum: original, greptile, test_failure, coverage_gap
    pr_id: str                       # Which PR this task belongs to
    phase: str                       # Current phase: test_writing, implement, test, coverage, review
    iteration: int                   # Which iteration this task was created in
    created_at: str                  # ISO timestamp
    assigned_agent: Optional[str] = None  # Agent ID if currently running
    metadata: dict = field(default_factory=dict)  # Flexible storage


@dataclass
class PRState:
    """State of a PR in the queue."""
    pr_id: str                       # PR identifier
    branch: str                      # Git branch name
    phase: str                       # Current PR phase: test_writing, implement, test, coverage, review, done
    task_ids: list[str]              # All task IDs in this PR
    iteration: int = 0               # Current iteration for this PR


class TaskQueue:
    """Queue for managing tasks across PRs."""

    def __init__(self):
        """Initialize empty queue."""
        self.tasks: dict[str, Task] = {}      # id -> Task
        self.prs: dict[str, PRState] = {}     # pr_id -> PRState
        self.completed: list[str] = []        # completed task IDs
        self.failed: list[str] = []           # failed task IDs

    def add_task(self, task: Task) -> str:
        """Add a task to the queue.
        
        Creates PRState if pr_id doesn't exist.
        Returns the task ID.
        """
        self.tasks[task.id] = task
        
        # Create PR if needed
        if task.pr_id not in self.prs:
            self.prs[task.pr_id] = PRState(
                pr_id=task.pr_id,
                branch=f"feature/{task.pr_id}",  # Default branch name
                phase="test_writing",
                task_ids=[],
            )
        
        # Add task to PR
        self.prs[task.pr_id].task_ids.append(task.id)
        
        return task.id

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID. Returns None if not found."""
        return self.tasks.get(task_id)

    def mark_running(self, task_id: str, agent_id: str) -> None:
        """Mark a task as running with assigned agent.
        
        Raises ValueError if task is not pending.
        """
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        if task.status != TaskStatus.PENDING:
            raise ValueError(f"Task {task_id} is not pending (status: {task.status})")
        
        task.status = TaskStatus.RUNNING
        task.assigned_agent = agent_id

    def mark_complete(self, task_id: str, result: Optional[dict] = None) -> None:
        """Mark a task as completed.
        
        Optionally stores result in metadata.
        """
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        task.status = TaskStatus.COMPLETED
        task.assigned_agent = None
        if result:
            task.metadata["result"] = result
        
        self.completed.append(task_id)

    def mark_failed(self, task_id: str, error: str) -> None:
        """Mark a task as failed with error message."""
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        task.status = TaskStatus.FAILED
        task.assigned_agent = None
        task.metadata["error"] = error
        
        self.failed.append(task_id)


    # Query methods
    def get_pending(self, pr_id: Optional[str] = None) -> list[Task]:
        """Get all pending tasks, optionally filtered by PR."""
        tasks = [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]
        if pr_id:
            tasks = [t for t in tasks if t.pr_id == pr_id]
        return tasks

    def get_running(self) -> list[Task]:
        """Get all currently running tasks."""
        return [t for t in self.tasks.values() if t.status == TaskStatus.RUNNING]

    def has_pending(self) -> bool:
        """Returns True if any tasks are pending."""
        return any(t.status == TaskStatus.PENDING for t in self.tasks.values())

    def has_running(self) -> bool:
        """Returns True if any tasks are running."""
        return any(t.status == TaskStatus.RUNNING for t in self.tasks.values())

    def get_tasks_for_pr(self, pr_id: str) -> list[Task]:
        """Get all tasks (any status) for a specific PR."""
        return [t for t in self.tasks.values() if t.pr_id == pr_id]

    def get_eligible_tasks(self, n: int) -> list[Task]:
        """Get up to N tasks eligible for work.
        
        Eligibility rules:
        - Status must be pending
        - Task must be in parallel phase (test_writing/implement)
        
        Returns tasks sorted by priority (lower = first).
        """
        eligible = [
            t for t in self.tasks.values()
            if t.status == TaskStatus.PENDING and t.phase in PARALLEL_PHASES
        ]
        # Sort by priority (lower = higher priority)
        eligible.sort(key=lambda t: (t.priority, t.created_at))
        return eligible[:n]

    # PR management methods
    def get_pr(self, pr_id: str) -> Optional[PRState]:
        """Get PR state by ID."""
        return self.prs.get(pr_id)

    def create_pr(self, pr_id: str, branch: str, task_ids: list[str]) -> PRState:
        """Create a new PR grouping tasks.
        
        Tasks must already exist in queue.
        """
        # Update tasks to point to new PR
        for task_id in task_ids:
            if task_id in self.tasks:
                self.tasks[task_id].pr_id = pr_id
        
        pr = PRState(
            pr_id=pr_id,
            branch=branch,
            phase="test_writing",
            task_ids=task_ids.copy(),
        )
        self.prs[pr_id] = pr
        return pr

    def get_pr_phase(self, pr_id: str) -> str:
        """Get current phase for a PR."""
        pr = self.prs.get(pr_id)
        return pr.phase if pr else "unknown"

    def all_prs_done(self) -> bool:
        """Returns True if all PRs are in 'done' phase."""
        if not self.prs:
            return True
        return all(pr.phase == "done" for pr in self.prs.values())

    def advance_pr_to_sync_phase(self, pr_id: str, phase: str) -> None:
        """Manually advance PR to a sync phase (test, coverage, review)."""
        if pr_id in self.prs:
            self.prs[pr_id].phase = phase

    def get_prs_ready_for_sync(self, phase: str) -> list[str]:
        """Get PR IDs where all tasks have completed parallel phases."""
        ready = []
        for pr_id, pr in self.prs.items():
            # Get all tasks for this PR
            pr_tasks = self.get_tasks_for_pr(pr_id)
            # Check if all tasks are completed or in a phase past implement
            all_done = all(
                t.status == TaskStatus.COMPLETED or t.phase in SYNC_PHASES
                for t in pr_tasks
            )
            if all_done and pr_tasks:
                ready.append(pr_id)
        return ready


# =============================================================================
# State Management
# =============================================================================

STATE_DIR = Path.home() / ".claude/plugins/agent-swarm/.state"
SESSION_FILE = STATE_DIR / "session.json"

# Phase order for each mode
DEFAULT_PHASES = ["implement", "test", "coverage", "review"]
TDD_PHASES = ["test_writing", "implement", "test", "coverage", "review"]

EXIT_CONDITIONS = ["tests_pass", "review_approved", "max_reached"]


def load_state() -> dict:
    """Load session state."""
    if not SESSION_FILE.exists():
        return {}
    try:
        return json.loads(SESSION_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def save_state(state: dict) -> None:
    """Save session state."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(state, indent=2) + "\n")


def init_iterate(tdd: bool = True, max_iter: int = 5) -> None:
    """Initialize iterate session. TDD mode is default."""
    state = load_state()

    phases = TDD_PHASES if tdd else DEFAULT_PHASES

    state["mode"] = "iterate-tdd" if tdd else "iterate"
    state["iterate_phases"] = phases
    state["iterate_phase"] = phases[0]
    state["iteration"] = 0
    state["max_iterations"] = max_iter
    state["exit_reason"] = None
    state["workflow_invoked"] = True  # Unlock editing tools

    save_state(state)

    mode_str = "TDD mode"
    print(f"[ITERATE] Initialized - {mode_str}")
    print(f"  Max iterations: {max_iter}")
    print(f"  Starting phase: {phases[0]}")
    print(f"  Phases: {' → '.join(phases)}")


def advance_phase(direction: str = "next") -> None:
    """Advance or retreat to a phase."""
    state = load_state()

    if state.get("mode") not in ("iterate", "iterate-tdd"):
        print("ERROR: Not in iterate mode. Run 'iterate_state.py init' first.", file=sys.stderr)
        sys.exit(1)

    phases = state.get("iterate_phases", DEFAULT_PHASES)
    current = state.get("iterate_phase", phases[0])
    current_idx = phases.index(current) if current in phases else 0

    if direction == "next":
        if current_idx == len(phases) - 1:
            # Completed loop, start new iteration
            state["iteration"] = state.get("iteration", 0) + 1
            state["iterate_phase"] = phases[0]

            if state["iteration"] >= state.get("max_iterations", 5):
                state["exit_reason"] = "max_reached"
                print(f"[ITERATE] Max iterations ({state['max_iterations']}) reached")
                print("  Checkpoint required for user approval")
            else:
                print(f"[ITERATE] Starting iteration {state['iteration'] + 1}")
                print(f"  Phase: {phases[0]}")
        else:
            state["iterate_phase"] = phases[current_idx + 1]
            print(f"[ITERATE] Phase: {state['iterate_phase']}")

    elif direction == "back":
        # Kick-back logic
        mode = state.get("mode")

        if current in ("test", "coverage"):
            # Test/coverage failure - go back to appropriate phase
            if mode == "iterate-tdd":
                state["iterate_phase"] = "test_writing"
                print("[ITERATE] Kicked back to TEST_WRITING (fix the spec)")
            else:
                state["iterate_phase"] = "implement"
                print("[ITERATE] Kicked back to IMPLEMENT (fix the code)")
        elif current == "review":
            # Review failure - go back to implement
            state["iterate_phase"] = "implement"
            print("[ITERATE] Kicked back to IMPLEMENT (address review issues)")
        else:
            print(f"[ITERATE] Cannot go back from {current}", file=sys.stderr)
            sys.exit(1)

    save_state(state)


def check_status() -> None:
    """Check current iterate status."""
    state = load_state()

    if state.get("mode") not in ("iterate", "iterate-tdd"):
        print("Not in iterate mode")
        return

    exit_reason = state.get("exit_reason")
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 5)
    phase = state.get("iterate_phase", "unknown")
    mode = state.get("mode")

    if exit_reason:
        print(f"[ITERATE] EXIT: {exit_reason}")
        print(f"  Completed {iteration} iterations")
        print("  Ready for checkpoint")
    else:
        print(f"[ITERATE] Mode: {mode}")
        print(f"  Iteration: {iteration + 1}/{max_iter}")
        print(f"  Phase: {phase}")
        print("  Status: Running")


def mark_exit(reason: str) -> None:
    """Mark exit condition."""
    if reason not in EXIT_CONDITIONS:
        print(f"ERROR: Invalid exit reason '{reason}'", file=sys.stderr)
        print(f"Valid reasons: {', '.join(EXIT_CONDITIONS)}", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    state["exit_reason"] = reason
    save_state(state)

    print(f"[ITERATE] Exit marked: {reason}")


def show_state() -> None:
    """Show full iterate state."""
    state = load_state()

    iterate_keys = ["mode", "iterate_phases", "iterate_phase", "iteration",
                    "max_iterations", "exit_reason", "workflow_invoked"]

    iterate_state = {k: state.get(k) for k in iterate_keys if k in state}

    if iterate_state:
        print(json.dumps(iterate_state, indent=2))
    else:
        print("No iterate state found")


def main():
    parser = argparse.ArgumentParser(description="Iterate workflow state management")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize iterate session")
    init_parser.add_argument("--no-tdd", action="store_true", help="Skip TDD mode (implement first)")
    init_parser.add_argument("--max-iter", type=int, default=5, help="Max iterations (default: 5)")

    # phase command
    phase_parser = subparsers.add_parser("phase", help="Advance or retreat phase")
    phase_parser.add_argument("direction", choices=["next", "back"], help="Direction")

    # check command
    subparsers.add_parser("check", help="Check current status")

    # exit command
    exit_parser = subparsers.add_parser("exit", help="Mark exit condition")
    exit_parser.add_argument("reason", choices=EXIT_CONDITIONS, help="Exit reason")

    # show command
    subparsers.add_parser("show", help="Show full state")

    args = parser.parse_args()

    if args.command == "init":
        init_iterate(tdd=not args.no_tdd, max_iter=args.max_iter)
    elif args.command == "phase":
        advance_phase(args.direction)
    elif args.command == "check":
        check_status()
    elif args.command == "exit":
        mark_exit(args.reason)
    elif args.command == "show":
        show_state()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
