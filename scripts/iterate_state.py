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

# Add lib to path for workflow_client import
_lib_dir = Path(__file__).parent.parent / "lib"
if str(_lib_dir) not in sys.path:
    sys.path.insert(0, str(_lib_dir))


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
    depends_on: list[str] = field(default_factory=list)  # Task IDs this depends on
    metadata: dict = field(default_factory=dict)  # Flexible storage
    repo: Optional[str] = None       # Repository name (e.g., "sophia", "hermes") for multi-repo support
    repo_path: Optional[str] = None  # Absolute path to repo (e.g., "/home/user/projects/LOGOS/sophia")


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

    def retry_or_escalate(self, task_id: str, error: str, max_retries: int = 3) -> bool:
        """Retry a failed task or escalate if max retries exceeded.

        Args:
            task_id: Task to retry
            error: Error message from this attempt
            max_retries: Maximum retry attempts before escalating

        Returns:
            True if task was reset to pending (will retry)
            False if max retries exceeded (escalated)
        """
        import sys

        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Track retry attempts
        retry_count = task.metadata.get("retry_count", 0) + 1
        task.metadata["retry_count"] = retry_count

        # Log the failure
        errors = task.metadata.get("errors", [])
        errors.append({"attempt": retry_count, "error": error})
        task.metadata["errors"] = errors
        print(f"[QUEUE] Task {task_id} failed (attempt {retry_count}/{max_retries}): {error}", file=sys.stderr)

        if retry_count < max_retries:
            # Reset to pending for retry
            task.status = TaskStatus.PENDING
            task.assigned_agent = None
            print(f"[QUEUE] Task {task_id} reset to pending for retry", file=sys.stderr)
            return True
        else:
            # Max retries exceeded - mark permanently failed
            self.mark_failed(task_id, f"Exceeded {max_retries} attempts. Last error: {error}")
            print(f"[QUEUE] Task {task_id} ESCALATED - exceeded {max_retries} retries", file=sys.stderr)
            return False

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
        - All dependencies must be completed (committed/done)

        Returns tasks sorted by priority (lower = first).
        """
        eligible = []
        for t in self.tasks.values():
            if t.status != TaskStatus.PENDING:
                continue
            if t.phase not in PARALLEL_PHASES:
                continue
            # Check dependencies - all must be completed
            deps_satisfied = True
            for dep_id in t.depends_on:
                dep_task = self.tasks.get(dep_id)
                if dep_task and dep_task.status != TaskStatus.COMPLETED:
                    deps_satisfied = False
                    break
            if deps_satisfied:
                eligible.append(t)

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

    def is_pr_ready_for_push(self, pr_id: str) -> bool:
        """Check if all tasks in a PR are committed (ready for batch push).

        Returns True if ALL tasks for this PR have status COMPLETED.
        This is the gate for batched push - we don't push until all tasks commit.
        """
        pr_tasks = self.get_tasks_for_pr(pr_id)
        if not pr_tasks:
            return False
        return all(t.status == TaskStatus.COMPLETED for t in pr_tasks)

    def get_pr_push_status(self, pr_id: str) -> dict:
        """Get detailed push status for a PR.

        Returns dict with:
        - ready: bool - whether all tasks are committed
        - completed: int - number of completed tasks
        - total: int - total tasks in PR
        - pending: list[str] - IDs of tasks not yet committed
        """
        pr_tasks = self.get_tasks_for_pr(pr_id)
        completed = [t for t in pr_tasks if t.status == TaskStatus.COMPLETED]
        pending = [t.id for t in pr_tasks if t.status != TaskStatus.COMPLETED]

        return {
            "ready": len(pending) == 0 and len(pr_tasks) > 0,
            "completed": len(completed),
            "total": len(pr_tasks),
            "pending": pending,
        }

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

STATE_DIR = Path(__file__).resolve().parent.parent / ".state"
SESSION_FILE = STATE_DIR / "session.json"
STATE_FILE = SESSION_FILE  # Alias for queue persistence tests

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


def save_queue(queue: "TaskQueue") -> None:
    """Save queue state to workflow_client under 'queue' key.

    Note: Queue is ephemeral - resets on process restart.
    """
    import workflow_client

    # Get existing session state (for compatibility with other keys)
    state = load_state()

    # Serialize tasks
    tasks_data = {}
    for task_id, task in queue.tasks.items():
        tasks_data[task_id] = {
            "id": task.id,
            "description": task.description,
            "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
            "priority": task.priority,
            "source": task.source.value if hasattr(task.source, 'value') else str(task.source),
            "pr_id": task.pr_id,
            "assigned_agent": task.assigned_agent,
            "phase": task.phase,
            "iteration": task.iteration,
            "created_at": task.created_at,
            "depends_on": task.depends_on,
            "metadata": task.metadata,
        }

    # Serialize PRs
    prs_data = {}
    for pr_id, pr in queue.prs.items():
        prs_data[pr_id] = {
            "pr_id": pr.pr_id,
            "branch": pr.branch,
            "phase": pr.phase,
            "task_ids": pr.task_ids,
            "iteration": pr.iteration,
        }

    queue_data = {
        "tasks": tasks_data,
        "prs": prs_data,
        "completed": queue.completed,
        "failed": queue.failed,
    }

    # Save to workflow_client (in-memory via MCP, ephemeral)
    workflow_client.workflow_set_state("queue", queue_data)

    # Also save to session.json for backwards compatibility
    state["queue"] = queue_data
    save_state(state)


def load_queue() -> "TaskQueue":
    """Load queue from workflow_client via MCP.

    Returns empty TaskQueue if no queue state exists.
    Handles missing/malformed data gracefully.
    Note: Queue is ephemeral - resets on process restart.
    """
    import workflow_client

    queue = TaskQueue()

    # Load from workflow_client (single source of truth)
    queue_data = workflow_client.workflow_get_state("queue")
    
    if not queue_data:
        return queue

    # Restore tasks
    tasks_data = queue_data.get("tasks", {})
    for task_id, task_dict in tasks_data.items():
        try:
            # Convert status string to enum
            status_str = task_dict.get("status", "pending")
            try:
                status = TaskStatus(status_str)
            except ValueError:
                status = TaskStatus.PENDING

            # Convert source string to enum
            source_str = task_dict.get("source", "original")
            try:
                source = TaskSource(source_str)
            except ValueError:
                source = TaskSource.ORIGINAL

            task = Task(
                id=task_dict.get("id", task_id),
                description=task_dict.get("description", ""),
                status=status,
                priority=task_dict.get("priority", PRIORITY_ORIGINAL),
                source=source,
                pr_id=task_dict.get("pr_id", "default"),
                assigned_agent=task_dict.get("assigned_agent"),
                phase=task_dict.get("phase", "test_writing"),
                iteration=task_dict.get("iteration", 0),
                created_at=task_dict.get("created_at", ""),
                depends_on=task_dict.get("depends_on", []),
                metadata=task_dict.get("metadata", {}),
            )
            queue.tasks[task_id] = task
        except Exception:
            # Skip malformed tasks
            continue

    # Restore PRs
    prs_data = queue_data.get("prs", {})
    for pr_id, pr_dict in prs_data.items():
        try:
            pr = PRState(
                pr_id=pr_dict.get("pr_id", pr_id),
                branch=pr_dict.get("branch", ""),
                phase=pr_dict.get("phase", "test_writing"),
                task_ids=pr_dict.get("task_ids", []),
                iteration=pr_dict.get("iteration", 0),
            )
            queue.prs[pr_id] = pr
        except Exception:
            # Skip malformed PRs
            continue

    # Restore completed/failed lists
    queue.completed = queue_data.get("completed", [])
    queue.failed = queue_data.get("failed", [])

    return queue


# =============================================================================
# CLI - Queue and PR management only
# Workflow functions (init, phase, check, exit, show) moved to iterate_workflow.py
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Task queue and PR management (workflow commands in iterate_workflow.py)"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # -------------------------------------------------------------------------
    # Queue commands
    # -------------------------------------------------------------------------
    queue_parser = subparsers.add_parser("queue", help="Task queue operations")
    queue_subparsers = queue_parser.add_subparsers(dest="queue_command", help="Queue subcommand")

    # queue add
    queue_add = queue_subparsers.add_parser("add", help="Add a task to the queue")
    queue_add.add_argument("description", help="Task description")
    queue_add.add_argument("--pr", default="default", help="PR ID (default: default)")
    queue_add.add_argument("--priority", type=int, default=PRIORITY_ORIGINAL, help="Priority (0=highest)")
    queue_add.add_argument("--branch", help="Branch name (creates PR if needed)")
    queue_add.add_argument("--depends", help="Comma-separated task IDs this depends on")

    # queue list
    queue_list = queue_subparsers.add_parser("list", help="List tasks")
    queue_list.add_argument("--status", choices=["pending", "running", "completed", "failed"],
                           help="Filter by status")
    queue_list.add_argument("--pr", help="Filter by PR ID")

    # queue show
    queue_show = queue_subparsers.add_parser("show", help="Show task details")
    queue_show.add_argument("task_id", help="Task ID to show")

    # queue remove
    queue_remove = queue_subparsers.add_parser("remove", help="Remove a pending task")
    queue_remove.add_argument("task_id", help="Task ID to remove")

    # queue eligible
    queue_eligible = queue_subparsers.add_parser("eligible", help="Show eligible tasks")
    queue_eligible.add_argument("--count", type=int, default=10, help="Max tasks to show")

    # -------------------------------------------------------------------------
    # PR commands
    # -------------------------------------------------------------------------
    pr_parser = subparsers.add_parser("pr", help="PR operations")
    pr_subparsers = pr_parser.add_subparsers(dest="pr_command", help="PR subcommand")

    # pr list
    pr_subparsers.add_parser("list", help="List all PRs")

    # pr show
    pr_show = pr_subparsers.add_parser("show", help="Show PR details")
    pr_show.add_argument("pr_id", help="PR ID to show")

    # pr create
    pr_create = pr_subparsers.add_parser("create", help="Create a PR grouping tasks")
    pr_create.add_argument("pr_id", help="PR ID to create")
    pr_create.add_argument("--branch", required=True, help="Branch name")
    pr_create.add_argument("--tasks", nargs="+", required=True, help="Task IDs to include")

    # -------------------------------------------------------------------------
    # Push command (gated)
    # -------------------------------------------------------------------------
    push_parser = subparsers.add_parser("push", help="Gated push - only proceeds if all PR tasks are committed")
    push_parser.add_argument("--pr", required=True, help="PR ID to push")
    push_parser.add_argument("--dry-run", action="store_true", help="Check status without pushing")
    push_parser.add_argument("--repo-path", help="Path to repository (for multi-repo support)")

    args = parser.parse_args()

    if args.command == "queue":
        handle_queue_command(args)
    elif args.command == "pr":
        handle_pr_command(args)
    elif args.command == "push":
        cmd_gated_push(args.pr, args.dry_run, getattr(args, 'repo_path', None))
    else:
        parser.print_help()
        sys.exit(1)


def handle_queue_command(args) -> None:
    """Handle queue subcommands."""
    if args.queue_command == "add":
        depends = args.depends.split(",") if args.depends else []
        cmd_queue_add(args.description, args.pr, args.priority, args.branch, depends)
    elif args.queue_command == "list":
        cmd_queue_list(args.status, args.pr)
    elif args.queue_command == "show":
        cmd_queue_show(args.task_id)
    elif args.queue_command == "remove":
        cmd_queue_remove(args.task_id)
    elif args.queue_command == "eligible":
        cmd_queue_eligible(args.count)
    else:
        print("Usage: iterate_state.py queue {add|list|show|remove|eligible}")
        sys.exit(1)


def handle_pr_command(args) -> None:
    """Handle pr subcommands."""
    if args.pr_command == "list":
        cmd_pr_list()
    elif args.pr_command == "show":
        cmd_pr_show(args.pr_id)
    elif args.pr_command == "create":
        cmd_pr_create(args.pr_id, args.branch, args.tasks)
    else:
        print("Usage: iterate_state.py pr {list|show|create}")
        sys.exit(1)


# =============================================================================
# Queue CLI Commands
# =============================================================================

def cmd_queue_add(description: str, pr_id: str, priority: int, branch: str | None, depends: list[str] | None = None) -> None:
    """Add a task to the queue."""
    import uuid
    from datetime import datetime, timezone

    queue = load_queue()

    # Validate dependencies exist
    depends = depends or []
    for dep_id in depends:
        if dep_id and dep_id not in queue.tasks:
            print(f"Warning: dependency {dep_id} not found in queue", file=sys.stderr)

    task_id = f"task-{uuid.uuid4().hex[:8]}"
    task = Task(
        id=task_id,
        description=description,
        status=TaskStatus.PENDING,
        priority=priority,
        source=TaskSource.ORIGINAL,
        pr_id=pr_id,
        assigned_agent=None,
        phase="test_writing",
        iteration=0,
        created_at=datetime.now(timezone.utc).isoformat(),
        depends_on=[d for d in depends if d],  # Filter empty strings
        metadata={},
    )

    queue.add_task(task)

    # If branch provided and PR doesn't exist, update PR branch
    if branch and pr_id in queue.prs:
        queue.prs[pr_id].branch = branch

    save_queue(queue)
    print(f"Added task: {task_id}")
    if depends:
        print(f"  Depends on: {', '.join(depends)}")


def cmd_queue_list(status_filter: str | None, pr_filter: str | None) -> None:
    """List tasks with optional filters."""
    queue = load_queue()

    tasks = list(queue.tasks.values())

    # Apply filters
    if status_filter:
        tasks = [t for t in tasks if t.status.value == status_filter]
    if pr_filter:
        tasks = [t for t in tasks if t.pr_id == pr_filter]

    if not tasks:
        print("No tasks found.")
        return

    # Print header
    print(f"{'ID':<16} {'Status':<10} {'Pri':<4} {'Phase':<14} {'PR':<12} Description")
    print("-" * 80)

    for task in sorted(tasks, key=lambda t: (t.priority, t.created_at)):
        desc = task.description[:30] + "..." if len(task.description) > 30 else task.description
        print(f"{task.id:<16} {task.status.value:<10} {task.priority:<4} {task.phase:<14} {task.pr_id:<12} {desc}")


def cmd_queue_show(task_id: str) -> None:
    """Show detailed task information."""
    queue = load_queue()
    task = queue.get_task(task_id)

    if not task:
        print(f"Task not found: {task_id}", file=sys.stderr)
        sys.exit(1)

    print(f"ID:          {task.id}")
    print(f"Description: {task.description}")
    print(f"Status:      {task.status.value}")
    print(f"Priority:    {task.priority}")
    print(f"Source:      {task.source.value}")
    print(f"PR ID:       {task.pr_id}")
    print(f"Agent:       {task.assigned_agent or 'None'}")
    print(f"Phase:       {task.phase}")
    print(f"Iteration:   {task.iteration}")
    print(f"Created:     {task.created_at}")
    if task.metadata:
        print(f"Metadata:    {json.dumps(task.metadata, indent=2)}")


def cmd_queue_remove(task_id: str) -> None:
    """Remove a pending task."""
    queue = load_queue()
    task = queue.get_task(task_id)

    if not task:
        print(f"Task not found: {task_id}", file=sys.stderr)
        sys.exit(1)

    if task.status != TaskStatus.PENDING:
        print(f"Cannot remove task with status: {task.status.value}", file=sys.stderr)
        sys.exit(1)

    # Remove from queue
    del queue.tasks[task_id]

    # Remove from PR task list
    if task.pr_id in queue.prs:
        pr = queue.prs[task.pr_id]
        if task_id in pr.task_ids:
            pr.task_ids.remove(task_id)

    save_queue(queue)
    print(f"Removed task: {task_id}")


def cmd_queue_eligible(count: int) -> None:
    """Show tasks eligible for work."""
    queue = load_queue()
    eligible = queue.get_eligible_tasks(count)

    if not eligible:
        print("No eligible tasks.")
        return

    print(f"{'ID':<16} {'Pri':<4} {'Phase':<14} {'PR':<12} Description")
    print("-" * 70)

    for task in eligible:
        desc = task.description[:30] + "..." if len(task.description) > 30 else task.description
        print(f"{task.id:<16} {task.priority:<4} {task.phase:<14} {task.pr_id:<12} {desc}")


# =============================================================================
# PR CLI Commands
# =============================================================================

def cmd_pr_list() -> None:
    """List all PRs."""
    queue = load_queue()

    if not queue.prs:
        print("No PRs found.")
        return

    print(f"{'PR ID':<16} {'Phase':<14} {'Tasks':<8} Branch")
    print("-" * 60)

    for pr_id, pr in queue.prs.items():
        print(f"{pr.pr_id:<16} {pr.phase:<14} {len(pr.task_ids):<8} {pr.branch}")


def cmd_pr_show(pr_id: str) -> None:
    """Show PR details."""
    queue = load_queue()
    pr = queue.get_pr(pr_id)

    if not pr:
        print(f"PR not found: {pr_id}", file=sys.stderr)
        sys.exit(1)

    print(f"PR ID:     {pr.pr_id}")
    print(f"Branch:    {pr.branch}")
    print(f"Phase:     {pr.phase}")
    print(f"Iteration: {pr.iteration}")
    print(f"\nTasks ({len(pr.task_ids)}):")

    for task_id in pr.task_ids:
        task = queue.get_task(task_id)
        if task:
            print(f"  {task.id}: [{task.status.value}] {task.description[:40]}")


def cmd_pr_create(pr_id: str, branch: str, task_ids: list[str]) -> None:
    """Create a PR grouping existing tasks."""
    queue = load_queue()

    # Verify all tasks exist
    for task_id in task_ids:
        if task_id not in queue.tasks:
            print(f"Task not found: {task_id}", file=sys.stderr)
            sys.exit(1)

    # Create or update PR
    if pr_id in queue.prs:
        pr = queue.prs[pr_id]
        pr.branch = branch
        pr.task_ids = task_ids
    else:
        pr = PRState(
            pr_id=pr_id,
            branch=branch,
            phase="test_writing",
            task_ids=task_ids,
            iteration=0,
        )
        queue.prs[pr_id] = pr

    # Update task PR IDs
    for task_id in task_ids:
        queue.tasks[task_id].pr_id = pr_id

    save_queue(queue)
    print(f"Created PR: {pr_id} with {len(task_ids)} tasks")


# =============================================================================
# Gated Push Command
# =============================================================================

def cmd_gated_push(pr_id: str, dry_run: bool = False, repo_path: Optional[str] = None) -> None:
    """Gated push - only proceeds if all tasks in PR are committed.

    This is called by subagents when they complete their work.
    If not all tasks are committed yet, it logs and returns (deferred push).
    If all tasks are committed, it executes the actual git push.

    Args:
        pr_id: PR identifier to push
        dry_run: If True, just check status without pushing
        repo_path: Optional path to repository. If provided, git commands run in that directory.
    """
    import subprocess

    queue = load_queue()

    # Check if PR exists
    if pr_id not in queue.prs:
        print(f"[PUSH] PR not found: {pr_id}", file=sys.stderr)
        sys.exit(1)

    pr = queue.prs[pr_id]
    status = queue.get_pr_push_status(pr_id)

    # Check if ready
    if not status["ready"]:
        # Not ready - log and return (deferred push)
        print(f"[PUSH] Deferred - waiting on {len(status['pending'])} tasks")
        print(f"  PR: {pr_id}")
        print(f"  Completed: {status['completed']}/{status['total']}")
        print(f"  Pending: {', '.join(status['pending'][:5])}")
        if len(status['pending']) > 5:
            print(f"    ... and {len(status['pending']) - 5} more")
        return  # Exit cleanly - this is expected behavior

    # Ready to push
    print(f"[PUSH] All tasks committed for PR: {pr_id}")
    print(f"  Branch: {pr.branch}")
    print(f"  Tasks: {status['total']}")
    if repo_path:
        print(f"  Repo: {repo_path}")

    if dry_run:
        print("  (dry-run - would push here)")
        return

    # Execute git push (in repo_path if specified)
    try:
        result = subprocess.run(
            ["git", "push", "-u", "origin", pr.branch],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=repo_path  # Run in target repo directory
        )

        if result.returncode == 0:
            print(f"[PUSH] Success - pushed {pr.branch}")
            # Update PR phase to in_review
            pr.phase = "review"
            save_queue(queue)
        else:
            print(f"[PUSH] Failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)

    except subprocess.TimeoutExpired:
        print("[PUSH] Timed out", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("[PUSH] git not found", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
