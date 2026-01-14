"""Tests for TaskQueue infrastructure in iterate_state.py."""

import json
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

    @pytest.mark.parametrize("member,expected", [
        (TaskStatus.PENDING, "pending"),
        (TaskStatus.RUNNING, "running"),
        (TaskStatus.COMPLETED, "completed"),
        (TaskStatus.FAILED, "failed"),
    ])
    def test_status_values(self, member, expected):
        """TaskStatus enum has correct string values."""
        assert member == expected
        assert member.value == expected
        assert isinstance(member.value, str)


class TestTaskSourceEnum:
    """Test TaskSource enum."""

    @pytest.mark.parametrize("member,expected", [
        (TaskSource.ORIGINAL, "original"),
        (TaskSource.GREPTILE, "greptile"),
        (TaskSource.TEST_FAILURE, "test_failure"),
        (TaskSource.COVERAGE_GAP, "coverage_gap"),
    ])
    def test_source_values(self, member, expected):
        """TaskSource enum has correct string values."""
        assert member == expected
        assert member.value == expected
        assert isinstance(member.value, str)


class TestPriorityConstants:
    """Test priority constants."""

    @pytest.mark.parametrize("constant,expected", [
        (PRIORITY_TEST_FAILURE, 0),
        (PRIORITY_GREPTILE_CRITICAL, 1),
        (PRIORITY_GREPTILE_WARNING, 2),
        (PRIORITY_ORIGINAL, 3),
        (PRIORITY_COVERAGE_GAP, 4),
    ])
    def test_priority_values(self, constant, expected):
        """Priority constants have correct values (lower = more urgent)."""
        assert constant == expected

    def test_priority_ordering(self):
        """Priorities are correctly ordered (lower = more urgent)."""
        priorities = [PRIORITY_TEST_FAILURE, PRIORITY_GREPTILE_CRITICAL,
                      PRIORITY_GREPTILE_WARNING, PRIORITY_ORIGINAL, PRIORITY_COVERAGE_GAP]
        assert priorities == sorted(priorities)


class TestPhaseConstants:
    """Test phase constants."""

    def test_phase_sets_defined(self):
        """Phase sets contain expected values and are disjoint."""
        assert {"test_writing", "implement"} <= PARALLEL_PHASES
        assert {"test", "coverage", "review"} <= SYNC_PHASES
        assert PARALLEL_PHASES.isdisjoint(SYNC_PHASES)

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


class TestTaskQueueQueryMethods:
    """Test TaskQueue query methods."""

    def test_get_pending_all(self):
        """get_pending returns all pending tasks."""
        q = TaskQueue()
        q.add_task(make_task("t1", status=TaskStatus.PENDING))
        q.add_task(make_task("t2", status=TaskStatus.RUNNING))
        q.add_task(make_task("t3", status=TaskStatus.PENDING))
        pending = q.get_pending()
        assert len(pending) == 2
        assert all(t.status == TaskStatus.PENDING for t in pending)

    def test_get_pending_by_pr(self):
        """get_pending can filter by PR."""
        q = TaskQueue()
        q.add_task(make_task("t1", pr_id="pr-a"))
        q.add_task(make_task("t2", pr_id="pr-b"))
        q.add_task(make_task("t3", pr_id="pr-a"))
        pending = q.get_pending(pr_id="pr-a")
        assert len(pending) == 2
        assert all(t.pr_id == "pr-a" for t in pending)

    def test_get_running(self):
        """get_running returns all running tasks."""
        q = TaskQueue()
        q.add_task(make_task("t1", status=TaskStatus.PENDING))
        q.add_task(make_task("t2", status=TaskStatus.RUNNING))
        q.add_task(make_task("t3", status=TaskStatus.RUNNING))
        running = q.get_running()
        assert len(running) == 2

    def test_has_pending_true(self):
        """has_pending returns True when pending tasks exist."""
        q = TaskQueue()
        q.add_task(make_task("t1"))
        assert q.has_pending() is True

    def test_has_pending_false(self):
        """has_pending returns False when no pending tasks."""
        q = TaskQueue()
        q.add_task(make_task("t1", status=TaskStatus.COMPLETED))
        assert q.has_pending() is False

    def test_has_running_true(self):
        """has_running returns True when running tasks exist."""
        q = TaskQueue()
        q.add_task(make_task("t1", status=TaskStatus.RUNNING))
        assert q.has_running() is True

    def test_has_running_false(self):
        """has_running returns False when no running tasks."""
        q = TaskQueue()
        q.add_task(make_task("t1", status=TaskStatus.PENDING))
        assert q.has_running() is False

    def test_get_tasks_for_pr(self):
        """get_tasks_for_pr returns all tasks for a PR."""
        q = TaskQueue()
        q.add_task(make_task("t1", pr_id="pr-x"))
        q.add_task(make_task("t2", pr_id="pr-y"))
        q.add_task(make_task("t3", pr_id="pr-x", status=TaskStatus.COMPLETED))
        tasks = q.get_tasks_for_pr("pr-x")
        assert len(tasks) == 2
        assert all(t.pr_id == "pr-x" for t in tasks)


class TestTaskQueueEligibility:
    """Test get_eligible_tasks method."""

    def test_eligible_pending_parallel_phase(self):
        """Tasks in parallel phase (test_writing/implement) are eligible."""
        q = TaskQueue()
        q.add_task(make_task("t1", phase="test_writing"))
        q.add_task(make_task("t2", phase="implement"))
        eligible = q.get_eligible_tasks(5)
        assert len(eligible) == 2

    def test_not_eligible_if_running(self):
        """Running tasks are not eligible."""
        q = TaskQueue()
        q.add_task(make_task("t1", status=TaskStatus.RUNNING))
        eligible = q.get_eligible_tasks(5)
        assert len(eligible) == 0

    def test_not_eligible_if_completed(self):
        """Completed tasks are not eligible."""
        q = TaskQueue()
        q.add_task(make_task("t1", status=TaskStatus.COMPLETED))
        eligible = q.get_eligible_tasks(5)
        assert len(eligible) == 0

    def test_eligible_respects_limit(self):
        """get_eligible_tasks respects the n limit."""
        q = TaskQueue()
        for i in range(5):
            q.add_task(make_task(f"t{i}"))
        eligible = q.get_eligible_tasks(2)
        assert len(eligible) == 2

    def test_eligible_priority_order(self):
        """Tasks returned in priority order (lower = first)."""
        q = TaskQueue()
        q.add_task(make_task("low", priority=PRIORITY_COVERAGE_GAP))
        q.add_task(make_task("high", priority=PRIORITY_TEST_FAILURE))
        q.add_task(make_task("mid", priority=PRIORITY_ORIGINAL))
        eligible = q.get_eligible_tasks(3)
        assert eligible[0].id == "high"
        assert eligible[1].id == "mid"
        assert eligible[2].id == "low"


class TestTaskQueuePRManagement:
    """Test PR management methods."""

    def test_get_pr(self):
        """get_pr returns PRState by ID."""
        q = TaskQueue()
        q.add_task(make_task("t1", pr_id="pr-001"))
        pr = q.get_pr("pr-001")
        assert pr is not None
        assert pr.pr_id == "pr-001"

    def test_get_pr_nonexistent(self):
        """get_pr returns None for unknown PR."""
        q = TaskQueue()
        assert q.get_pr("nonexistent") is None

    def test_create_pr(self):
        """create_pr creates new PRState."""
        q = TaskQueue()
        q.add_task(make_task("t1", pr_id="temp"))
        q.add_task(make_task("t2", pr_id="temp"))
        pr = q.create_pr("pr-new", "feature/branch", ["t1", "t2"])
        assert pr.pr_id == "pr-new"
        assert pr.branch == "feature/branch"
        assert pr.phase == "test_writing"
        assert "t1" in pr.task_ids

    def test_get_pr_phase(self):
        """get_pr_phase returns current phase."""
        q = TaskQueue()
        q.add_task(make_task("t1", pr_id="pr-001"))
        assert q.get_pr_phase("pr-001") == "test_writing"

    def test_all_prs_done_false(self):
        """all_prs_done returns False when PRs not done."""
        q = TaskQueue()
        q.add_task(make_task("t1", pr_id="pr-001"))
        assert q.all_prs_done() is False

    def test_all_prs_done_true(self):
        """all_prs_done returns True when all PRs in done phase."""
        q = TaskQueue()
        q.add_task(make_task("t1", pr_id="pr-001"))
        q.prs["pr-001"].phase = "done"
        assert q.all_prs_done() is True

    def test_advance_pr_to_sync_phase(self):
        """advance_pr_to_sync_phase updates PR phase."""
        q = TaskQueue()
        q.add_task(make_task("t1", pr_id="pr-001"))
        q.advance_pr_to_sync_phase("pr-001", "test")
        assert q.prs["pr-001"].phase == "test"

    def test_get_prs_ready_for_sync(self):
        """get_prs_ready_for_sync finds PRs ready for sync phase."""
        q = TaskQueue()
        # PR with all tasks completed implement phase
        q.add_task(make_task("t1", pr_id="pr-ready", phase="implement", status=TaskStatus.COMPLETED))
        q.add_task(make_task("t2", pr_id="pr-ready", phase="implement", status=TaskStatus.COMPLETED))
        # PR with tasks still running
        q.add_task(make_task("t3", pr_id="pr-notready", phase="implement", status=TaskStatus.RUNNING))

        ready = q.get_prs_ready_for_sync("test")
        assert "pr-ready" in ready
        assert "pr-notready" not in ready


class TestSaveQueue:
    """Test save_queue persistence function."""

    def test_save_queue_creates_queue_key(self, tmp_path, monkeypatch):
        """save_queue creates 'queue' key in session state."""
        from decomposer import TaskPriority
        from iterate_state import save_queue, TaskQueue, Task, TaskStatus, TaskSource

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{"mode": "iterate-tdd"}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)

        q = TaskQueue()
        q.add_task(Task(
            id="task-001",
            description="Test task",
            status=TaskStatus.PENDING,
            priority=TaskPriority.ORIGINAL,
            source=TaskSource.ORIGINAL,
            pr_id="pr-001",
            phase="test_writing",
            iteration=0,
            created_at="2026-01-11T10:00:00Z",
            metadata={}
        ))
        save_queue(q)

        saved = json.loads(state_file.read_text())
        assert "queue" in saved
        assert "tasks" in saved["queue"]
        assert "task-001" in saved["queue"]["tasks"]

    def test_save_queue_preserves_existing_state(self, tmp_path, monkeypatch):
        """save_queue doesn't overwrite other state keys."""
        from iterate_state import save_queue, TaskQueue

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{"mode": "iterate-tdd", "iterate_phase": "test_writing", "other_key": "preserved"}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)

        q = TaskQueue()
        save_queue(q)

        saved = json.loads(state_file.read_text())
        assert saved["mode"] == "iterate-tdd"
        assert saved["iterate_phase"] == "test_writing"
        assert saved["other_key"] == "preserved"
        assert "queue" in saved

    def test_save_queue_serializes_prs(self, tmp_path, monkeypatch):
        """save_queue includes PR state."""
        from decomposer import TaskPriority
        from iterate_state import save_queue, TaskQueue, Task, TaskStatus, TaskSource

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)

        q = TaskQueue()
        q.add_task(Task(
            id="task-001",
            description="Test",
            status=TaskStatus.PENDING,
            priority=TaskPriority.ORIGINAL,
            source=TaskSource.ORIGINAL,
            pr_id="pr-001",
            phase="test_writing",
            iteration=0,
            created_at="2026-01-11T10:00:00Z",
            metadata={}
        ))
        save_queue(q)

        saved = json.loads(state_file.read_text())
        assert "prs" in saved["queue"]
        assert "pr-001" in saved["queue"]["prs"]

    def test_save_queue_serializes_completed_failed(self, tmp_path, monkeypatch):
        """save_queue includes completed and failed lists."""
        from iterate_state import save_queue, TaskQueue

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)

        q = TaskQueue()
        q.completed = ["task-001", "task-002"]
        q.failed = ["task-003"]
        save_queue(q)

        saved = json.loads(state_file.read_text())
        assert saved["queue"]["completed"] == ["task-001", "task-002"]
        assert saved["queue"]["failed"] == ["task-003"]


class TestLoadQueue:
    """Test load_queue persistence function."""

    def test_load_queue_returns_empty_if_no_queue_key(self, tmp_path, monkeypatch):
        """load_queue returns empty TaskQueue if no queue state."""
        from iterate_state import load_queue, TaskQueue

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{"mode": "iterate-tdd"}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)

        q = load_queue()
        assert isinstance(q, TaskQueue)
        assert len(q.tasks) == 0
        assert len(q.prs) == 0

    def test_load_queue_returns_empty_if_no_file(self, tmp_path, monkeypatch):
        """load_queue returns empty TaskQueue if no session file."""
        from iterate_state import load_queue, TaskQueue

        state_file = tmp_path / ".state" / "session.json"
        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)

        q = load_queue()
        assert isinstance(q, TaskQueue)
        assert len(q.tasks) == 0

    def test_load_queue_restores_tasks(self, tmp_path, monkeypatch):
        """load_queue restores task data."""
        from iterate_state import load_queue, TaskStatus

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text(json.dumps({
            "queue": {
                "tasks": {
                    "task-001": {
                        "id": "task-001",
                        "description": "Test task",
                        "status": "pending",
                        "priority": 3,
                        "source": "original",
                        "pr_id": "pr-001",
                        "assigned_agent": None,
                        "phase": "test_writing",
                        "iteration": 0,
                        "created_at": "2026-01-11T10:00:00Z",
                        "metadata": {}
                    }
                },
                "prs": {
                    "pr-001": {
                        "pr_id": "pr-001",
                        "branch": "feature/test",
                        "phase": "test_writing",
                        "task_ids": ["task-001"],
                        "iteration": 0
                    }
                },
                "completed": [],
                "failed": []
            }
        }))

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)

        q = load_queue()
        assert "task-001" in q.tasks
        task = q.tasks["task-001"]
        assert task.description == "Test task"
        assert task.status == TaskStatus.PENDING
        assert task.pr_id == "pr-001"

    def test_load_queue_restores_prs(self, tmp_path, monkeypatch):
        """load_queue restores PR state."""
        from iterate_state import load_queue

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text(json.dumps({
            "queue": {
                "tasks": {},
                "prs": {
                    "pr-001": {
                        "pr_id": "pr-001",
                        "branch": "feature/test",
                        "phase": "implement",
                        "task_ids": ["task-001"],
                        "iteration": 2
                    }
                },
                "completed": [],
                "failed": []
            }
        }))

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)

        q = load_queue()
        assert "pr-001" in q.prs
        pr = q.prs["pr-001"]
        assert pr.branch == "feature/test"
        assert pr.phase == "implement"
        assert pr.iteration == 2

    def test_load_queue_restores_completed_failed(self, tmp_path, monkeypatch):
        """load_queue restores completed and failed lists."""
        from iterate_state import load_queue

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text(json.dumps({
            "queue": {
                "tasks": {},
                "prs": {},
                "completed": ["task-001", "task-002"],
                "failed": ["task-003"]
            }
        }))

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)

        q = load_queue()
        assert q.completed == ["task-001", "task-002"]
        assert q.failed == ["task-003"]

    def test_load_queue_handles_malformed_data(self, tmp_path, monkeypatch):
        """load_queue handles missing fields gracefully."""
        from iterate_state import load_queue

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        # Malformed: missing required fields in task
        state_file.write_text(json.dumps({
            "queue": {
                "tasks": {
                    "task-bad": {"id": "task-bad"}  # Missing most fields
                },
                "prs": {}
            }
        }))

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)

        # Should not raise, returns what it can
        q = load_queue()
        assert isinstance(q, TaskQueue)

    def test_save_load_roundtrip(self, tmp_path, monkeypatch):
        """save then load preserves queue state."""
        from decomposer import TaskPriority
        from iterate_state import save_queue, load_queue, TaskQueue, Task, TaskStatus, TaskSource

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)

        # Create queue with data
        q1 = TaskQueue()
        q1.add_task(Task(
            id="task-001",
            description="First task",
            status=TaskStatus.PENDING,
            priority=TaskPriority.ORIGINAL,
            source=TaskSource.ORIGINAL,
            pr_id="pr-001",
            phase="test_writing",
            iteration=0,
            created_at="2026-01-11T10:00:00Z",
            metadata={"key": "value"}
        ))
        q1.completed = ["old-task-001"]
        q1.failed = ["old-task-002"]

        # Save
        save_queue(q1)

        # Load
        q2 = load_queue()

        # Verify
        assert "task-001" in q2.tasks
        assert q2.tasks["task-001"].description == "First task"
        assert q2.tasks["task-001"].metadata == {"key": "value"}
        assert "pr-001" in q2.prs
        assert q2.completed == ["old-task-001"]
        assert q2.failed == ["old-task-002"]


class TestQueueAddCLI:
    """Test queue add CLI command."""

    def test_queue_add_creates_task(self, tmp_path, monkeypatch, capsys):
        """queue add creates a new task."""
        from iterate_state import main, load_queue

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)
        monkeypatch.setattr("iterate_state.STATE_DIR", state_dir)
        monkeypatch.setattr("sys.argv", ["iterate_state.py", "queue", "add", "Test task description"])

        main()

        q = load_queue()
        assert len(q.tasks) == 1
        task = list(q.tasks.values())[0]
        assert task.description == "Test task description"
        assert task.status == TaskStatus.PENDING

    def test_queue_add_with_pr(self, tmp_path, monkeypatch):
        """queue add --pr creates task in specific PR."""
        from iterate_state import main, load_queue

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)
        monkeypatch.setattr("iterate_state.STATE_DIR", state_dir)
        monkeypatch.setattr("sys.argv", ["iterate_state.py", "queue", "add", "Task", "--pr", "pr-001"])

        main()

        q = load_queue()
        task = list(q.tasks.values())[0]
        assert task.pr_id == "pr-001"

    def test_queue_add_with_priority(self, tmp_path, monkeypatch):
        """queue add --priority sets task priority."""
        from iterate_state import main, load_queue

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)
        monkeypatch.setattr("iterate_state.STATE_DIR", state_dir)
        monkeypatch.setattr("sys.argv", ["iterate_state.py", "queue", "add", "Task", "--priority", "1"])

        main()

        q = load_queue()
        task = list(q.tasks.values())[0]
        assert task.priority == 1


class TestQueueListCLI:
    """Test queue list CLI command."""

    def test_queue_list_shows_tasks(self, tmp_path, monkeypatch, capsys):
        """queue list displays tasks."""
        from iterate_state import main, save_queue, TaskQueue, Task, TaskStatus, TaskSource
        from decomposer import TaskPriority

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)
        monkeypatch.setattr("iterate_state.STATE_DIR", state_dir)

        # Create queue with tasks
        q = TaskQueue()
        q.add_task(Task(
            id="task-001",
            description="First task",
            status=TaskStatus.PENDING,
            priority=TaskPriority.ORIGINAL,
            source=TaskSource.ORIGINAL,
            pr_id="pr-001",
            phase="test_writing",
            iteration=0,
            created_at="2026-01-11T10:00:00Z",
            metadata={}
        ))
        save_queue(q)

        monkeypatch.setattr("sys.argv", ["iterate_state.py", "queue", "list"])
        main()

        captured = capsys.readouterr()
        assert "task-001" in captured.out
        assert "First task" in captured.out

    def test_queue_list_filters_by_status(self, tmp_path, monkeypatch, capsys):
        """queue list --status filters tasks."""
        from iterate_state import main, save_queue, TaskQueue, Task, TaskStatus, TaskSource
        from decomposer import TaskPriority

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)
        monkeypatch.setattr("iterate_state.STATE_DIR", state_dir)

        q = TaskQueue()
        q.add_task(Task(
            id="task-pending",
            description="Pending task",
            status=TaskStatus.PENDING,
            priority=TaskPriority.ORIGINAL,
            source=TaskSource.ORIGINAL,
            pr_id="pr-001",
            phase="test_writing",
            iteration=0,
            created_at="2026-01-11T10:00:00Z",
            metadata={}
        ))
        q.add_task(Task(
            id="task-running",
            description="Running task",
            status=TaskStatus.RUNNING,
            priority=TaskPriority.ORIGINAL,
            source=TaskSource.ORIGINAL,
            pr_id="pr-001",
            phase="implement",
            iteration=0,
            created_at="2026-01-11T10:00:00Z",
            metadata={}
        ))
        save_queue(q)

        monkeypatch.setattr("sys.argv", ["iterate_state.py", "queue", "list", "--status", "pending"])
        main()

        captured = capsys.readouterr()
        assert "task-pending" in captured.out
        assert "task-running" not in captured.out


class TestQueueShowCLI:
    """Test queue show CLI command."""

    def test_queue_show_displays_task(self, tmp_path, monkeypatch, capsys):
        """queue show displays task details."""
        from iterate_state import main, save_queue, TaskQueue, Task, TaskStatus, TaskSource
        from decomposer import TaskPriority

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)
        monkeypatch.setattr("iterate_state.STATE_DIR", state_dir)

        q = TaskQueue()
        q.add_task(Task(
            id="task-001",
            description="Detailed task",
            status=TaskStatus.PENDING,
            priority=TaskPriority.ORIGINAL,
            source=TaskSource.ORIGINAL,
            pr_id="pr-001",
            phase="test_writing",
            iteration=0,
            created_at="2026-01-11T10:00:00Z",
            metadata={"key": "value"}
        ))
        save_queue(q)

        monkeypatch.setattr("sys.argv", ["iterate_state.py", "queue", "show", "task-001"])
        main()

        captured = capsys.readouterr()
        assert "task-001" in captured.out
        assert "Detailed task" in captured.out
        assert "pending" in captured.out.lower()


class TestQueueRemoveCLI:
    """Test queue remove CLI command."""

    def test_queue_remove_removes_pending_task(self, tmp_path, monkeypatch):
        """queue remove removes a pending task."""
        from iterate_state import main, save_queue, load_queue, TaskQueue, Task, TaskStatus, TaskSource
        from decomposer import TaskPriority

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)
        monkeypatch.setattr("iterate_state.STATE_DIR", state_dir)

        q = TaskQueue()
        q.add_task(Task(
            id="task-001",
            description="To remove",
            status=TaskStatus.PENDING,
            priority=TaskPriority.ORIGINAL,
            source=TaskSource.ORIGINAL,
            pr_id="default",
            phase="test_writing",
            iteration=0,
            created_at="2026-01-11T10:00:00Z",
            metadata={}
        ))
        save_queue(q)

        monkeypatch.setattr("sys.argv", ["iterate_state.py", "queue", "remove", "task-001"])
        main()

        q2 = load_queue()
        assert "task-001" not in q2.tasks


class TestQueueEligibleCLI:
    """Test queue eligible CLI command."""

    def test_queue_eligible_shows_eligible_tasks(self, tmp_path, monkeypatch, capsys):
        """queue eligible shows tasks ready for work."""
        from iterate_state import main, save_queue, TaskQueue, Task, TaskStatus, TaskSource
        from decomposer import TaskPriority

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)
        monkeypatch.setattr("iterate_state.STATE_DIR", state_dir)

        q = TaskQueue()
        q.add_task(Task(
            id="task-eligible",
            description="Eligible",
            status=TaskStatus.PENDING,
            priority=TaskPriority.ORIGINAL,
            source=TaskSource.ORIGINAL,
            pr_id="pr-001",
            phase="test_writing",
            iteration=0,
            created_at="2026-01-11T10:00:00Z",
            metadata={}
        ))
        save_queue(q)

        monkeypatch.setattr("sys.argv", ["iterate_state.py", "queue", "eligible"])
        main()

        captured = capsys.readouterr()
        assert "task-eligible" in captured.out


class TestPRListCLI:
    """Test pr list CLI command."""

    def test_pr_list_shows_prs(self, tmp_path, monkeypatch, capsys):
        """pr list shows all PRs."""
        from iterate_state import main, save_queue, TaskQueue, Task, TaskStatus, TaskSource
        from decomposer import TaskPriority

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)
        monkeypatch.setattr("iterate_state.STATE_DIR", state_dir)

        q = TaskQueue()
        q.add_task(Task(
            id="task-001",
            description="Task",
            status=TaskStatus.PENDING,
            priority=TaskPriority.ORIGINAL,
            source=TaskSource.ORIGINAL,
            pr_id="pr-001",
            phase="test_writing",
            iteration=0,
            created_at="2026-01-11T10:00:00Z",
            metadata={}
        ))
        save_queue(q)

        monkeypatch.setattr("sys.argv", ["iterate_state.py", "pr", "list"])
        main()

        captured = capsys.readouterr()
        assert "pr-001" in captured.out


class TestPRShowCLI:
    """Test pr show CLI command."""

    def test_pr_show_displays_pr(self, tmp_path, monkeypatch, capsys):
        """pr show displays PR details."""
        from iterate_state import main, save_queue, TaskQueue, Task, TaskStatus, TaskSource
        from decomposer import TaskPriority

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        state_file = state_dir / "session.json"
        state_file.write_text('{}')

        monkeypatch.setattr("iterate_state.SESSION_FILE", state_file)
        monkeypatch.setattr("iterate_state.STATE_DIR", state_dir)

        q = TaskQueue()
        q.add_task(Task(
            id="task-001",
            description="Task",
            status=TaskStatus.PENDING,
            priority=TaskPriority.ORIGINAL,
            source=TaskSource.ORIGINAL,
            pr_id="pr-001",
            phase="test_writing",
            iteration=0,
            created_at="2026-01-11T10:00:00Z",
            metadata={}
        ))
        save_queue(q)

        monkeypatch.setattr("sys.argv", ["iterate_state.py", "pr", "show", "pr-001"])
        main()

        captured = capsys.readouterr()
        assert "pr-001" in captured.out
        assert "task-001" in captured.out
