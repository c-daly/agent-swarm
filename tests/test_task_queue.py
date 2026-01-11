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
