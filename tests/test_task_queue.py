"""Tests for TaskQueue infrastructure in iterate_state.py."""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from iterate_state import (
    TaskStatus,
    TaskSource,
    PRIORITY_TEST_FAILURE,
    PRIORITY_GREPTILE_CRITICAL,
    PRIORITY_GREPTILE_WARNING,
    PRIORITY_ORIGINAL,
    PRIORITY_COVERAGE_GAP,
    Task,
    PRState,
    PARALLEL_PHASES,
    SYNC_PHASES,
    TaskQueue,
)


class TestTaskStatusEnum:
    """Test TaskStatus enum."""

    def test_has_pending_status(self):
        """TaskStatus has PENDING value."""
        assert TaskStatus.PENDING == "pending"

    def test_has_running_status(self):
        """TaskStatus has RUNNING value."""
        assert TaskStatus.RUNNING == "running"

    def test_has_completed_status(self):
        """TaskStatus has COMPLETED value."""
        assert TaskStatus.COMPLETED == "completed"

    def test_has_failed_status(self):
        """TaskStatus has FAILED value."""
        assert TaskStatus.FAILED == "failed"

    def test_is_string_enum(self):
        """TaskStatus values are strings and comparable with strings."""
        assert isinstance(TaskStatus.PENDING.value, str)
        # String enum allows direct comparison with strings
        assert TaskStatus.PENDING == "pending"
        # Use .value for explicit string conversion
        assert TaskStatus.PENDING.value == "pending"


class TestTaskSourceEnum:
    """Test TaskSource enum."""

    def test_has_original_source(self):
        """TaskSource has ORIGINAL value."""
        assert TaskSource.ORIGINAL == "original"

    def test_has_greptile_source(self):
        """TaskSource has GREPTILE value."""
        assert TaskSource.GREPTILE == "greptile"

    def test_has_test_failure_source(self):
        """TaskSource has TEST_FAILURE value."""
        assert TaskSource.TEST_FAILURE == "test_failure"

    def test_has_coverage_gap_source(self):
        """TaskSource has COVERAGE_GAP value."""
        assert TaskSource.COVERAGE_GAP == "coverage_gap"

    def test_is_string_enum(self):
        """TaskSource values are strings and comparable with strings."""
        assert isinstance(TaskSource.ORIGINAL.value, str)
        # String enum allows direct comparison with strings
        assert TaskSource.ORIGINAL == "original"
        # Use .value for explicit string conversion
        assert TaskSource.ORIGINAL.value == "original"


class TestPriorityConstants:
    """Test priority constants."""

    def test_test_failure_highest_priority(self):
        """Test failures have highest priority (0)."""
        assert PRIORITY_TEST_FAILURE == 0

    def test_greptile_critical_priority(self):
        """Greptile critical issues have priority 1."""
        assert PRIORITY_GREPTILE_CRITICAL == 1

    def test_greptile_warning_priority(self):
        """Greptile warnings have priority 2."""
        assert PRIORITY_GREPTILE_WARNING == 2

    def test_original_priority(self):
        """Original tasks have priority 3."""
        assert PRIORITY_ORIGINAL == 3

    def test_coverage_gap_lowest_priority(self):
        """Coverage gaps have lowest priority (4)."""
        assert PRIORITY_COVERAGE_GAP == 4

    def test_priority_ordering(self):
        """Priorities are correctly ordered (lower = more urgent)."""
        assert PRIORITY_TEST_FAILURE < PRIORITY_GREPTILE_CRITICAL
        assert PRIORITY_GREPTILE_CRITICAL < PRIORITY_GREPTILE_WARNING
        assert PRIORITY_GREPTILE_WARNING < PRIORITY_ORIGINAL
        assert PRIORITY_ORIGINAL < PRIORITY_COVERAGE_GAP


class TestPhaseConstants:
    """Test phase constants."""

    def test_parallel_phases_defined(self):
        """Parallel phases include test_writing and implement."""
        assert "test_writing" in PARALLEL_PHASES
        assert "implement" in PARALLEL_PHASES

    def test_sync_phases_defined(self):
        """Sync phases include test, coverage, review."""
        assert "test" in SYNC_PHASES
        assert "coverage" in SYNC_PHASES
        assert "review" in SYNC_PHASES

    def test_phases_are_disjoint(self):
        """Parallel and sync phases don't overlap."""
        assert PARALLEL_PHASES.isdisjoint(SYNC_PHASES)


class TestTaskDataclass:
    """Test Task dataclass."""

    def test_task_creation_with_required_fields(self):
        """Task can be created with all required fields."""
        task = Task(
            id="task-001",
            description="Test task",
            status=TaskStatus.PENDING,
            priority=PRIORITY_ORIGINAL,
            source=TaskSource.ORIGINAL,
            pr_id="pr-001",
            phase="test_writing",
            iteration=0,
            created_at="2026-01-11T00:00:00Z",
        )
        assert task.id == "task-001"
        assert task.description == "Test task"
        assert task.status == TaskStatus.PENDING
        assert task.priority == PRIORITY_ORIGINAL

    def test_task_default_values(self):
        """Task has correct default values."""
        task = Task(
            id="task-002",
            description="Test",
            status=TaskStatus.PENDING,
            priority=3,
            source=TaskSource.ORIGINAL,
            pr_id="pr-001",
            phase="test_writing",
            iteration=0,
            created_at="2026-01-11T00:00:00Z",
        )
        assert task.assigned_agent is None
        assert task.metadata == {}

    def test_task_with_metadata(self):
        """Task can store metadata."""
        task = Task(
            id="task-003",
            description="Test",
            status=TaskStatus.PENDING,
            priority=3,
            source=TaskSource.ORIGINAL,
            pr_id="pr-001",
            phase="test_writing",
            iteration=0,
            created_at="2026-01-11T00:00:00Z",
            metadata={"file": "test.py", "line": 42},
        )
        assert task.metadata["file"] == "test.py"
        assert task.metadata["line"] == 42

    def test_task_status_transitions(self):
        """Task status can be updated."""
        task = Task(
            id="task-004",
            description="Test",
            status=TaskStatus.PENDING,
            priority=3,
            source=TaskSource.ORIGINAL,
            pr_id="pr-001",
            phase="test_writing",
            iteration=0,
            created_at="2026-01-11T00:00:00Z",
        )
        assert task.status == TaskStatus.PENDING
        task.status = TaskStatus.RUNNING
        assert task.status == TaskStatus.RUNNING


class TestPRStateDataclass:
    """Test PRState dataclass."""

    def test_prstate_creation(self):
        """PRState can be created with required fields."""
        pr = PRState(
            pr_id="pr-001",
            branch="feature/test",
            phase="test_writing",
            task_ids=["task-001", "task-002"],
        )
        assert pr.pr_id == "pr-001"
        assert pr.branch == "feature/test"
        assert pr.phase == "test_writing"
        assert pr.task_ids == ["task-001", "task-002"]

    def test_prstate_default_iteration(self):
        """PRState defaults to iteration 0."""
        pr = PRState(
            pr_id="pr-002",
            branch="feature/test",
            phase="test_writing",
            task_ids=[],
        )
        assert pr.iteration == 0

    def test_prstate_task_ids_list(self):
        """PRState task_ids is a list."""
        pr = PRState(
            pr_id="pr-003",
            branch="feature/test",
            phase="implement",
            task_ids=["task-a", "task-b", "task-c"],
        )
        assert len(pr.task_ids) == 3
        assert "task-b" in pr.task_ids


# Helper to create test tasks
def make_task(id: str, pr_id: str = "pr-001", status: TaskStatus = TaskStatus.PENDING,
              priority: int = PRIORITY_ORIGINAL, phase: str = "test_writing") -> Task:
    """Helper to create test tasks."""
    return Task(
        id=id,
        description=f"Task {id}",
        status=status,
        priority=priority,
        source=TaskSource.ORIGINAL,
        pr_id=pr_id,
        phase=phase,
        iteration=0,
        created_at="2026-01-11T00:00:00Z",
    )


class TestTaskQueueConstructor:
    """Test TaskQueue initialization."""

    def test_empty_queue_on_init(self):
        """TaskQueue starts empty."""
        q = TaskQueue()
        assert len(q.tasks) == 0
        assert len(q.prs) == 0
        assert q.completed == []
        assert q.failed == []

    def test_queue_has_tasks_dict(self):
        """TaskQueue has tasks dictionary."""
        q = TaskQueue()
        assert isinstance(q.tasks, dict)

    def test_queue_has_prs_dict(self):
        """TaskQueue has prs dictionary."""
        q = TaskQueue()
        assert isinstance(q.prs, dict)


class TestTaskQueueAddTask:
    """Test TaskQueue.add_task method."""

    def test_add_task_stores_in_dict(self):
        """add_task stores task in tasks dict."""
        q = TaskQueue()
        task = make_task("task-001")
        q.add_task(task)
        assert "task-001" in q.tasks
        assert q.tasks["task-001"] == task

    def test_add_task_returns_id(self):
        """add_task returns the task ID."""
        q = TaskQueue()
        task = make_task("task-002")
        result = q.add_task(task)
        assert result == "task-002"

    def test_add_task_creates_pr_if_needed(self):
        """add_task creates PRState if pr_id doesn't exist."""
        q = TaskQueue()
        task = make_task("task-003", pr_id="pr-new")
        q.add_task(task)
        assert "pr-new" in q.prs
        assert q.prs["pr-new"].pr_id == "pr-new"

    def test_add_task_adds_to_pr_task_ids(self):
        """add_task adds task ID to PRState.task_ids."""
        q = TaskQueue()
        task = make_task("task-004", pr_id="pr-001")
        q.add_task(task)
        assert "task-004" in q.prs["pr-001"].task_ids

    def test_add_multiple_tasks_same_pr(self):
        """Multiple tasks can be added to same PR."""
        q = TaskQueue()
        q.add_task(make_task("task-a", pr_id="pr-001"))
        q.add_task(make_task("task-b", pr_id="pr-001"))
        q.add_task(make_task("task-c", pr_id="pr-001"))
        assert len(q.prs["pr-001"].task_ids) == 3


class TestTaskQueueGetTask:
    """Test TaskQueue.get_task method."""

    def test_get_existing_task(self):
        """get_task returns task by ID."""
        q = TaskQueue()
        task = make_task("task-005")
        q.add_task(task)
        result = q.get_task("task-005")
        assert result == task

    def test_get_nonexistent_task(self):
        """get_task returns None for unknown ID."""
        q = TaskQueue()
        result = q.get_task("task-nonexistent")
        assert result is None


class TestTaskQueueMarkRunning:
    """Test TaskQueue.mark_running method."""

    def test_mark_running_updates_status(self):
        """mark_running sets status to RUNNING."""
        q = TaskQueue()
        q.add_task(make_task("task-006"))
        q.mark_running("task-006", "agent-0")
        assert q.tasks["task-006"].status == TaskStatus.RUNNING

    def test_mark_running_sets_agent(self):
        """mark_running sets assigned_agent."""
        q = TaskQueue()
        q.add_task(make_task("task-007"))
        q.mark_running("task-007", "agent-1")
        assert q.tasks["task-007"].assigned_agent == "agent-1"

    def test_mark_running_raises_if_not_pending(self):
        """mark_running raises ValueError if task not pending."""
        q = TaskQueue()
        task = make_task("task-008", status=TaskStatus.COMPLETED)
        q.add_task(task)
        with pytest.raises(ValueError):
            q.mark_running("task-008", "agent-0")


class TestTaskQueueMarkComplete:
    """Test TaskQueue.mark_complete method."""

    def test_mark_complete_updates_status(self):
        """mark_complete sets status to COMPLETED."""
        q = TaskQueue()
        q.add_task(make_task("task-009", status=TaskStatus.RUNNING))
        q.mark_complete("task-009")
        assert q.tasks["task-009"].status == TaskStatus.COMPLETED

    def test_mark_complete_adds_to_completed_list(self):
        """mark_complete adds task ID to completed list."""
        q = TaskQueue()
        q.add_task(make_task("task-010", status=TaskStatus.RUNNING))
        q.mark_complete("task-010")
        assert "task-010" in q.completed

    def test_mark_complete_with_result(self):
        """mark_complete can store result in metadata."""
        q = TaskQueue()
        q.add_task(make_task("task-011", status=TaskStatus.RUNNING))
        q.mark_complete("task-011", result={"output": "success"})
        assert q.tasks["task-011"].metadata.get("result") == {"output": "success"}


class TestTaskQueueMarkFailed:
    """Test TaskQueue.mark_failed method."""

    def test_mark_failed_updates_status(self):
        """mark_failed sets status to FAILED."""
        q = TaskQueue()
        q.add_task(make_task("task-012", status=TaskStatus.RUNNING))
        q.mark_failed("task-012", "Error message")
        assert q.tasks["task-012"].status == TaskStatus.FAILED

    def test_mark_failed_adds_to_failed_list(self):
        """mark_failed adds task ID to failed list."""
        q = TaskQueue()
        q.add_task(make_task("task-013", status=TaskStatus.RUNNING))
        q.mark_failed("task-013", "Error")
        assert "task-013" in q.failed

    def test_mark_failed_stores_error(self):
        """mark_failed stores error in metadata."""
        q = TaskQueue()
        q.add_task(make_task("task-014", status=TaskStatus.RUNNING))
        q.mark_failed("task-014", "Something went wrong")
        assert q.tasks["task-014"].metadata.get("error") == "Something went wrong"
