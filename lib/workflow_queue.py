"""Task queue integration for full-dev workflow.

Provides WorkflowQueue class that bridges the TaskQueue infrastructure
with the full-dev workflow, enabling:
- Initialize workflow from a list of tasks
- Convert PR comments to prioritized tasks
- Track completion status
- Gate commits until all comments addressed

Note: WorkflowQueue instances cache queue state on init. For concurrent
access, create short-lived instances or call refresh() before reads.
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add scripts to path for iterate_state imports
# Note: This is required because iterate_state.py lives in scripts/
# which is not a package. Consider moving shared types to lib/ in future.
scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from iterate_state import (
    Task,
    TaskQueue,  # Used for type annotation
    TaskStatus,
    TaskSource,
    PRIORITY_GREPTILE_CRITICAL,
    PRIORITY_GREPTILE_WARNING,
    PRIORITY_ORIGINAL,
    load_queue,
    save_queue,
)

# Maximum length for task descriptions (truncation threshold)
MAX_DESCRIPTION_LENGTH = 100


def _generate_id() -> str:
    """Generate a unique task ID."""
    return f"task-{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    """Generate ISO timestamp for task creation."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _truncate_at_word(text: str, max_length: int) -> str:
    """Truncate text at word boundary, avoiding mid-word cuts.

    Args:
        text: Text to truncate
        max_length: Maximum length (will be shorter if truncated at word boundary)

    Returns:
        Truncated text with "..." suffix if truncated, or original if fits.
    """
    if len(text) <= max_length:
        return text
    # Find last space before max_length, leave room for "..."
    truncated = text[: max_length - 3]
    last_space = truncated.rfind(" ")
    if last_space > max_length // 2:  # Only use word boundary if reasonable
        truncated = truncated[:last_space]
    return truncated + "..."


class WorkflowQueue:
    """Manages task queue for full-dev workflow.

    Provides a simplified interface for:
    - Initializing from a list of task descriptions
    - Converting PR review comments to tasks
    - Tracking task completion
    - Gating commits until all PR comments addressed
    """

    def __init__(self, pr_id: str = "current"):
        """Initialize WorkflowQueue.

        Args:
            pr_id: PR identifier for grouping tasks. Defaults to "current".
        """
        self.queue: TaskQueue = load_queue()
        self.pr_id = pr_id

    def refresh(self) -> None:
        """Reload queue state from disk.

        Call this before reads if the queue may have been modified externally
        (e.g., by another WorkflowQueue instance or subprocess).
        """
        self.queue = load_queue()

    def _create_task(
        self,
        description: str,
        source: TaskSource,
        priority: int,
        phase: str = "implement",
        metadata: Optional[dict] = None,
    ) -> Task:
        """Create a Task with common defaults.

        Args:
            description: Task description
            source: Task source (ORIGINAL, GREPTILE, etc.)
            priority: Task priority (lower = higher priority)
            phase: Task phase, defaults to "implement"
            metadata: Optional metadata dict

        Returns:
            The created Task (not yet added to queue).
        """
        return Task(
            id=_generate_id(),
            description=description,
            status=TaskStatus.PENDING,
            priority=priority,
            source=source,
            pr_id=self.pr_id,
            phase=phase,
            iteration=0,
            created_at=_now_iso(),
            metadata=metadata or {},
        )

    def initialize_from_tasks(self, tasks: list[dict]) -> None:
        """Initialize queue from a list of task descriptions.

        Args:
            tasks: List of task dicts with at least 'description' key.
                   Optional keys: 'priority', 'phase', 'metadata'

        Example:
            wq.initialize_from_tasks([
                {"description": "Implement feature X"},
                {"description": "Add tests", "phase": "test_writing"},
            ])
        """
        for task_spec in tasks:
            task = self._create_task(
                description=task_spec["description"],
                source=TaskSource.ORIGINAL,
                priority=task_spec.get("priority", PRIORITY_ORIGINAL),
                phase=task_spec.get("phase", "implement"),
                metadata=task_spec.get("metadata"),
            )
            self.queue.add_task(task)
        save_queue(self.queue)

    def add_pr_comment(self, comment: dict) -> Task:
        """Convert a PR comment to a task.

        Args:
            comment: Dict with 'id', 'body', and optionally:
                    'severity' ("critical" for high priority)
                    'path' (file path for the comment)

        Returns:
            The created Task object.

        Example:
            task = wq.add_pr_comment({
                "id": "comment-123",
                "body": "Please fix this security issue",
                "severity": "critical",
                "path": "src/auth.py"
            })
        """
        # Determine priority based on severity
        severity = comment.get("severity", "").lower()
        if severity == "critical":
            priority = PRIORITY_GREPTILE_CRITICAL
        else:
            priority = PRIORITY_GREPTILE_WARNING

        # Truncate long descriptions at word boundary
        body = comment.get("body", "")
        truncated_body = _truncate_at_word(body, MAX_DESCRIPTION_LENGTH)
        description = f"Address: {truncated_body}"

        task = self._create_task(
            description=description,
            source=TaskSource.GREPTILE,
            priority=priority,
            phase="implement",
            metadata={
                "comment_id": comment.get("id"),
                "file": comment.get("path"),
            },
        )
        self.queue.add_task(task)
        save_queue(self.queue)
        return task

    def get_next_task(self) -> Optional[Task]:
        """Get the highest priority pending task (peek operation).

        Note: This does NOT mark the task as RUNNING. Use start_task() to
        claim the task before processing, or call mark_done() directly for
        single-consumer workflows.

        Returns:
            The next Task to work on, or None if queue is empty.
        """
        eligible = self.queue.get_eligible_tasks(1)
        return eligible[0] if eligible else None

    def start_task(self, task_id: str, agent_id: str = "main") -> bool:
        """Mark a task as RUNNING to claim it for processing.

        Use this to prevent race conditions when multiple consumers may
        call get_next_task() concurrently.

        Args:
            task_id: ID of the task to start
            agent_id: Identifier for the agent/consumer claiming the task

        Returns:
            True if task was successfully claimed, False if not found or
            already running/completed.
        """
        task = self.queue.get_task(task_id)
        if not task or task.status != TaskStatus.PENDING:
            return False
        self.queue.mark_running(task_id, agent_id)
        save_queue(self.queue)
        return True

    def mark_done(self, task_id: str, result: Optional[dict] = None) -> None:
        """Mark a task as completed.

        Args:
            task_id: ID of the task to complete
            result: Optional result metadata to store
        """
        self.queue.mark_complete(task_id, result)
        save_queue(self.queue)

    def all_done(self) -> bool:
        """Check if all tasks are completed.

        Returns:
            True if no pending or running tasks remain.
        """
        return not self.queue.has_pending() and not self.queue.has_running()

    def get_unaddressed_comments(self) -> list[Task]:
        """Get all unaddressed tasks that came from PR comments.

        A comment task is unaddressed if it is PENDING, RUNNING, or FAILED
        (i.e., not COMPLETED). Only returns tasks for this WorkflowQueue's pr_id.

        Returns:
            List of unaddressed tasks with GREPTILE source for current PR.
        """
        # Get all tasks for this PR, filter to GREPTILE source and non-completed
        pr_tasks = self.queue.get_tasks_for_pr(self.pr_id)
        return [
            t for t in pr_tasks
            if t.source == TaskSource.GREPTILE and t.status != TaskStatus.COMPLETED
        ]

    def can_commit(self) -> bool:
        """Check if it's safe to commit (all PR comments addressed).

        Returns:
            True if no unaddressed PR comment tasks remain.
        """
        return len(self.get_unaddressed_comments()) == 0
