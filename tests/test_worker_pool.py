#!/usr/bin/env python3
"""Tests for worker_pool.py - worker pool management for parallel subagents.

Uses DaemonClient for in-memory state via MCP router
instead of JSON file. Tests use autouse fixture to isolate state.
"""

import sys
from pathlib import Path

import pytest

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

import daemon_client  # noqa: E402
from worker_pool import (  # noqa: E402
    start,
    stop,
    get_state,
    is_active,
    should_spawn_worker,
    spawn_worker,
    on_worker_complete,
    get_active_workers,
    is_complete,
)


@pytest.fixture(autouse=True)
def clean_state_manager():
    """Clean workflow state before and after each test."""
    with daemon_client.DaemonClient() as dc:
        dc.workflow_stop("worker_pool")
    yield
    with daemon_client.DaemonClient() as dc:
        dc.workflow_stop("worker_pool")


class TestOrchestrateStart:
    """Tests for starting orchestration."""

    def test_start_creates_active_state(self):
        """start() creates active orchestration state."""
        start(max_agents=3)
        assert is_active() is True
        state = get_state()
        assert state["max_agents"] == 3
        assert state["active_workers"] == []

    def test_start_with_task_description(self):
        """start() stores task description."""
        start(max_agents=2, task="Build feature X")
        state = get_state()
        assert state["task"] == "Build feature X"

    def test_start_while_active_raises(self):
        """start() raises if orchestration already active."""
        start(max_agents=2)
        with pytest.raises(RuntimeError, match="already active"):
            start(max_agents=3)


class TestOrchestrateStop:
    """Tests for stopping orchestration."""

    def test_stop_deactivates(self):
        """stop() deactivates orchestration."""
        start(max_agents=2)
        stop()
        assert is_active() is False
        state = get_state()
        assert state["exit_reason"] == "user_stopped"

    def test_stop_without_active_raises(self):
        """stop() raises if no active orchestration."""
        with pytest.raises(RuntimeError, match="not active"):
            stop()


class TestShouldSpawnWorker:
    """Tests for spawn decision logic."""

    def test_should_spawn_when_under_max_and_queue_has_work(self):
        """Should spawn when active < max and queue has tasks."""
        start(max_agents=3)
        # With empty active_workers and work available
        assert should_spawn_worker(queue_has_work=True) is True

    def test_should_not_spawn_when_at_max(self):
        """Should not spawn when at max_agents."""
        start(max_agents=2)
        spawn_worker("task-1", "Task 1 description")
        spawn_worker("task-2", "Task 2 description")
        assert should_spawn_worker(queue_has_work=True) is False

    def test_should_not_spawn_when_queue_empty(self):
        """Should not spawn when queue is empty."""
        start(max_agents=3)
        assert should_spawn_worker(queue_has_work=False) is False

    def test_should_not_spawn_when_inactive(self):
        """Should not spawn when orchestration not active."""
        assert should_spawn_worker(queue_has_work=True) is False


class TestSpawnWorker:
    """Tests for worker spawning."""

    def test_spawn_worker_adds_to_active(self):
        """spawn_worker() adds worker to active list."""
        start(max_agents=3)
        spawn_worker("task-123", "Implement feature")
        workers = get_active_workers()
        assert len(workers) == 1
        assert workers[0]["task_id"] == "task-123"
        assert workers[0]["task_description"] == "Implement feature"

    def test_spawn_worker_returns_worker_id(self):
        """spawn_worker() returns generated worker ID."""
        start(max_agents=3)
        worker_id = spawn_worker("task-456", "Fix bug")
        assert worker_id is not None
        assert worker_id.startswith("worker-")

    def test_spawn_worker_at_max_raises(self):
        """spawn_worker() raises when at max_agents."""
        start(max_agents=1)
        spawn_worker("task-1", "Task 1")
        with pytest.raises(RuntimeError, match="max agents"):
            spawn_worker("task-2", "Task 2")


class TestOnWorkerComplete:
    """Tests for worker completion handling."""

    def test_on_complete_removes_from_active(self):
        """on_worker_complete() removes worker from active list."""
        start(max_agents=3)
        worker_id = spawn_worker("task-123", "Task")
        on_worker_complete(worker_id, success=True)
        assert len(get_active_workers()) == 0

    def test_on_complete_tracks_result(self):
        """on_worker_complete() records success/failure."""
        start(max_agents=3)
        worker_id = spawn_worker("task-123", "Task")
        on_worker_complete(worker_id, success=True, result={"files_changed": 3})
        state = get_state()
        assert len(state["completed_workers"]) == 1
        assert state["completed_workers"][0]["success"] is True

    def test_on_complete_unknown_worker_raises(self):
        """on_worker_complete() raises for unknown worker."""
        start(max_agents=3)
        with pytest.raises(ValueError, match="Unknown worker"):
            on_worker_complete("worker-unknown", success=True)


class TestIsComplete:
    """Tests for completion detection."""

    def test_complete_when_no_workers_and_queue_empty(self):
        """is_complete() returns True when no workers and queue empty."""
        start(max_agents=3)
        assert is_complete(queue_empty=True) is True

    def test_not_complete_when_workers_active(self):
        """is_complete() returns False when workers still active."""
        start(max_agents=3)
        spawn_worker("task-1", "Task")
        assert is_complete(queue_empty=True) is False

    def test_not_complete_when_queue_has_work(self):
        """is_complete() returns False when queue has work."""
        start(max_agents=3)
        assert is_complete(queue_empty=False) is False

    def test_not_complete_when_inactive(self):
        """is_complete() returns False when not active."""
        assert is_complete(queue_empty=True) is False
