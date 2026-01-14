#!/usr/bin/env python3
"""Tests for WorkflowQueue - task queue integration for full-dev workflow."""

import sys
from pathlib import Path

import pytest

# Add lib to path
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

# Add scripts to path for iterate_state imports
scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from iterate_state import (
    TaskStatus,
    TaskSource,
    TaskQueue,
    PRIORITY_GREPTILE_CRITICAL,
    PRIORITY_GREPTILE_WARNING,
    PRIORITY_ORIGINAL,
    save_queue,
    load_queue,
    SESSION_FILE,
)

from workflow_queue import WorkflowQueue


@pytest.fixture(autouse=True)
def clean_queue():
    """Clean queue state before and after each test."""
    # Clear the queue by saving an empty one
    empty_queue = TaskQueue()
    save_queue(empty_queue)
    yield
    # Cleanup after test
    empty_queue = TaskQueue()
    save_queue(empty_queue)


class TestWorkflowQueueInit:
    """Tests for WorkflowQueue initialization."""

    def test_creates_with_default_pr_id(self):
        """WorkflowQueue uses 'current' as default pr_id."""
        wq = WorkflowQueue()
        assert wq.pr_id == "current"

    def test_creates_with_custom_pr_id(self):
        """WorkflowQueue accepts custom pr_id."""
        wq = WorkflowQueue(pr_id="pr-123")
        assert wq.pr_id == "pr-123"

    def test_loads_existing_queue(self):
        """WorkflowQueue loads existing queue on init."""
        wq = WorkflowQueue()
        assert wq.queue is not None
        assert isinstance(wq.queue, TaskQueue)

    def test_refresh_reloads_queue(self):
        """refresh() reloads queue state from disk."""
        wq1 = WorkflowQueue()
        wq2 = WorkflowQueue()

        # Add task via wq1
        wq1.initialize_from_tasks([{"description": "Task via wq1"}])

        # wq2 doesn't see it yet (stale cache)
        assert len(wq2.queue.get_pending()) == 0

        # After refresh, wq2 sees the task
        wq2.refresh()
        assert len(wq2.queue.get_pending()) == 1


class TestInitializeFromTasks:
    """Tests for initialize_from_tasks method."""

    def test_adds_tasks_to_queue(self):
        """initialize_from_tasks adds tasks to queue."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([
            {"description": "Task 1"},
            {"description": "Task 2"},
        ])
        pending = wq.queue.get_pending()
        assert len(pending) == 2

    def test_tasks_have_correct_description(self):
        """Tasks have the provided descriptions."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Fix the bug"}])
        pending = wq.queue.get_pending()
        assert pending[0].description == "Fix the bug"

    def test_tasks_have_pending_status(self):
        """New tasks start with PENDING status."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task"}])
        pending = wq.queue.get_pending()
        assert pending[0].status == TaskStatus.PENDING

    def test_tasks_have_default_priority(self):
        """Tasks without priority get PRIORITY_ORIGINAL."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task"}])
        pending = wq.queue.get_pending()
        assert pending[0].priority == PRIORITY_ORIGINAL

    def test_tasks_accept_custom_priority(self):
        """Tasks can have custom priority."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task", "priority": 1}])
        pending = wq.queue.get_pending()
        assert pending[0].priority == 1

    def test_tasks_have_original_source(self):
        """Tasks from initialize have ORIGINAL source."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task"}])
        pending = wq.queue.get_pending()
        assert pending[0].source == TaskSource.ORIGINAL

    def test_tasks_have_correct_pr_id(self):
        """Tasks are associated with the WorkflowQueue's pr_id."""
        wq = WorkflowQueue(pr_id="pr-456")
        wq.initialize_from_tasks([{"description": "Task"}])
        pending = wq.queue.get_pending()
        assert pending[0].pr_id == "pr-456"

    def test_tasks_have_default_phase(self):
        """Tasks default to 'implement' phase."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task"}])
        pending = wq.queue.get_pending()
        assert pending[0].phase == "implement"

    def test_tasks_accept_custom_phase(self):
        """Tasks can have custom phase."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task", "phase": "test_writing"}])
        pending = wq.queue.get_pending()
        assert pending[0].phase == "test_writing"

    def test_persists_to_disk(self):
        """initialize_from_tasks persists queue to disk."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Persistent task"}])

        # Create new instance to load from disk
        wq2 = WorkflowQueue()
        pending = wq2.queue.get_pending()
        assert len(pending) == 1
        assert pending[0].description == "Persistent task"


class TestAddPRComment:
    """Tests for add_pr_comment method."""

    def test_converts_comment_to_task(self):
        """add_pr_comment creates a task from comment."""
        wq = WorkflowQueue()
        task = wq.add_pr_comment({
            "id": "comment-1",
            "body": "Please fix this issue",
        })
        assert task is not None
        assert "Please fix this issue" in task.description

    def test_task_has_greptile_source(self):
        """PR comment tasks have GREPTILE source."""
        wq = WorkflowQueue()
        task = wq.add_pr_comment({
            "id": "comment-1",
            "body": "Fix this",
        })
        assert task.source == TaskSource.GREPTILE

    def test_critical_comment_has_critical_priority(self):
        """Critical severity comments get PRIORITY_GREPTILE_CRITICAL."""
        wq = WorkflowQueue()
        task = wq.add_pr_comment({
            "id": "comment-1",
            "body": "Security issue",
            "severity": "critical",
        })
        assert task.priority == PRIORITY_GREPTILE_CRITICAL

    def test_non_critical_comment_has_warning_priority(self):
        """Non-critical comments get PRIORITY_GREPTILE_WARNING."""
        wq = WorkflowQueue()
        task = wq.add_pr_comment({
            "id": "comment-1",
            "body": "Style issue",
            "severity": "warning",
        })
        assert task.priority == PRIORITY_GREPTILE_WARNING

    def test_default_priority_is_warning(self):
        """Comments without severity default to WARNING priority."""
        wq = WorkflowQueue()
        task = wq.add_pr_comment({
            "id": "comment-1",
            "body": "Some issue",
        })
        assert task.priority == PRIORITY_GREPTILE_WARNING

    def test_stores_comment_id_in_metadata(self):
        """PR comment ID is stored in task metadata."""
        wq = WorkflowQueue()
        task = wq.add_pr_comment({
            "id": "comment-abc",
            "body": "Issue",
        })
        assert task.metadata.get("comment_id") == "comment-abc"

    def test_stores_file_path_in_metadata(self):
        """File path from comment is stored in task metadata."""
        wq = WorkflowQueue()
        task = wq.add_pr_comment({
            "id": "comment-1",
            "body": "Issue",
            "path": "src/main.py",
        })
        assert task.metadata.get("file") == "src/main.py"

    def test_truncates_long_descriptions(self):
        """Long comment bodies are truncated in task description."""
        wq = WorkflowQueue()
        long_body = "x" * 200
        task = wq.add_pr_comment({
            "id": "comment-1",
            "body": long_body,
        })
        assert len(task.description) <= 120  # "Address: " + 100 chars + buffer

    def test_persists_to_disk(self):
        """add_pr_comment persists task to disk."""
        wq = WorkflowQueue()
        wq.add_pr_comment({
            "id": "comment-persist",
            "body": "Persistent comment",
        })

        # Load fresh instance
        wq2 = WorkflowQueue()
        pending = wq2.queue.get_pending()
        assert any("Persistent comment" in t.description for t in pending)


class TestGetNextTask:
    """Tests for get_next_task method."""

    def test_returns_none_when_empty(self):
        """get_next_task returns None when queue is empty."""
        wq = WorkflowQueue()
        assert wq.get_next_task() is None

    def test_returns_pending_task(self):
        """get_next_task returns a pending task."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task 1"}])
        task = wq.get_next_task()
        assert task is not None
        assert task.description == "Task 1"

    def test_returns_highest_priority_first(self):
        """get_next_task returns highest priority (lowest number) task."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([
            {"description": "Low priority", "priority": 4},
            {"description": "High priority", "priority": 1},
        ])
        task = wq.get_next_task()
        assert task.description == "High priority"


class TestMarkDone:
    """Tests for mark_done method."""

    def test_marks_task_completed(self):
        """mark_done changes task status to COMPLETED."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task"}])
        task = wq.get_next_task()
        wq.mark_done(task.id)

        # Reload and check
        wq2 = WorkflowQueue()
        assert len(wq2.queue.get_pending()) == 0

    def test_stores_result(self):
        """mark_done can store result metadata."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task"}])
        task = wq.get_next_task()
        wq.mark_done(task.id, {"output": "success"})

        # Task ID is in completed list (completed stores IDs as strings)
        wq2 = WorkflowQueue()
        assert task.id in wq2.queue.completed


class TestAllDone:
    """Tests for all_done method."""

    def test_true_when_empty(self):
        """all_done returns True when queue is empty."""
        wq = WorkflowQueue()
        assert wq.all_done() is True

    def test_false_when_pending(self):
        """all_done returns False when tasks are pending."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task"}])
        assert wq.all_done() is False

    def test_true_after_all_completed(self):
        """all_done returns True after all tasks completed."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task"}])
        task = wq.get_next_task()
        wq.mark_done(task.id)
        assert wq.all_done() is True


class TestGetUnaddressedComments:
    """Tests for get_unaddressed_comments method."""

    def test_returns_empty_when_no_comments(self):
        """get_unaddressed_comments returns empty list when no PR comments."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Regular task"}])
        assert wq.get_unaddressed_comments() == []

    def test_returns_pending_pr_comment_tasks(self):
        """get_unaddressed_comments returns pending GREPTILE source tasks."""
        wq = WorkflowQueue()
        wq.add_pr_comment({"id": "c1", "body": "Fix this"})
        wq.add_pr_comment({"id": "c2", "body": "And this"})

        unaddressed = wq.get_unaddressed_comments()
        assert len(unaddressed) == 2

    def test_excludes_completed_comments(self):
        """get_unaddressed_comments excludes completed tasks."""
        wq = WorkflowQueue()
        task = wq.add_pr_comment({"id": "c1", "body": "Fix this"})
        wq.mark_done(task.id)

        unaddressed = wq.get_unaddressed_comments()
        assert len(unaddressed) == 0

    def test_excludes_non_greptile_tasks(self):
        """get_unaddressed_comments excludes ORIGINAL source tasks."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Regular task"}])
        wq.add_pr_comment({"id": "c1", "body": "PR comment"})

        unaddressed = wq.get_unaddressed_comments()
        assert len(unaddressed) == 1
        assert "PR comment" in unaddressed[0].description


class TestCanCommit:
    """Tests for can_commit function."""

    def test_true_when_no_unaddressed_comments(self):
        """can_commit returns True when no unaddressed PR comments."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task"}])
        assert wq.can_commit() is True

    def test_false_when_unaddressed_comments_exist(self):
        """can_commit returns False when unaddressed PR comments exist."""
        wq = WorkflowQueue()
        wq.add_pr_comment({"id": "c1", "body": "Fix this"})
        assert wq.can_commit() is False

    def test_true_after_addressing_all_comments(self):
        """can_commit returns True after all comments addressed."""
        wq = WorkflowQueue()
        task = wq.add_pr_comment({"id": "c1", "body": "Fix this"})
        wq.mark_done(task.id)
        assert wq.can_commit() is True
