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

from iterate_state import (  # noqa: E402
    TaskStatus,
    TaskSource,
    TaskQueue,
    PRIORITY_GREPTILE_CRITICAL,
    PRIORITY_GREPTILE_WARNING,
    PRIORITY_ORIGINAL,
    save_queue,
)

from workflow_queue import WorkflowQueue  # noqa: E402


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


class TestStartTask:
    """Tests for start_task method."""

    def test_marks_task_as_running(self):
        """start_task marks task as RUNNING."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task"}])
        task = wq.get_next_task()
        result = wq.start_task(task.id)

        assert result is True
        # Reload and check status
        wq2 = WorkflowQueue()
        updated_task = wq2.queue.get_task(task.id)
        assert updated_task.status == TaskStatus.RUNNING

    def test_assigns_agent_id(self):
        """start_task assigns agent_id to task."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task"}])
        task = wq.get_next_task()
        wq.start_task(task.id, agent_id="worker-1")

        wq2 = WorkflowQueue()
        updated_task = wq2.queue.get_task(task.id)
        assert updated_task.assigned_agent == "worker-1"

    def test_returns_false_for_nonexistent_task(self):
        """start_task returns False for nonexistent task ID."""
        wq = WorkflowQueue()
        result = wq.start_task("nonexistent-id")
        assert result is False

    def test_returns_false_for_already_running_task(self):
        """start_task returns False if task already running."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task"}])
        task = wq.get_next_task()
        wq.start_task(task.id)  # First call succeeds
        result = wq.start_task(task.id)  # Second call fails
        assert result is False

    def test_returns_false_for_completed_task(self):
        """start_task returns False if task already completed."""
        wq = WorkflowQueue()
        wq.initialize_from_tasks([{"description": "Task"}])
        task = wq.get_next_task()
        wq.mark_done(task.id)
        result = wq.start_task(task.id)
        assert result is False


class TestPRFiltering:
    """Tests for PR-specific filtering."""

    def test_unaddressed_comments_filters_by_pr_id(self):
        """get_unaddressed_comments only returns comments for current PR."""
        wq1 = WorkflowQueue(pr_id="pr-1")
        wq2 = WorkflowQueue(pr_id="pr-2")

        wq1.add_pr_comment({"id": "c1", "body": "Issue in PR 1"})
        wq2.add_pr_comment({"id": "c2", "body": "Issue in PR 2"})

        # wq1 should only see its own comment
        unaddressed1 = wq1.get_unaddressed_comments()
        assert len(unaddressed1) == 1
        assert "PR 1" in unaddressed1[0].description

        # wq2 should only see its own comment
        wq2.refresh()  # Refresh to see wq1's changes
        unaddressed2 = wq2.get_unaddressed_comments()
        assert len(unaddressed2) == 1
        assert "PR 2" in unaddressed2[0].description

    def test_can_commit_respects_pr_filter(self):
        """can_commit only considers comments for current PR."""
        wq1 = WorkflowQueue(pr_id="pr-1")
        wq2 = WorkflowQueue(pr_id="pr-2")

        # Add comment only to pr-1
        wq1.add_pr_comment({"id": "c1", "body": "Issue"})

        # pr-2 should be able to commit (no comments for it)
        wq2.refresh()
        assert wq2.can_commit() is True

        # pr-1 cannot commit
        assert wq1.can_commit() is False

    def test_running_task_blocks_commit(self):
        """RUNNING PR comment task blocks commit."""
        wq = WorkflowQueue()
        task = wq.add_pr_comment({"id": "c1", "body": "Fix this"})
        wq.start_task(task.id)  # Mark as RUNNING

        wq2 = WorkflowQueue()
        assert wq2.can_commit() is False


class TestTruncation:
    """Tests for smart truncation."""

    def test_truncates_at_word_boundary(self):
        """Long comments truncate at word boundary."""
        wq = WorkflowQueue()
        # Create body that would cut mid-word at 100 chars
        body = "This is a long comment that needs to be truncated properly without cutting words in the middle of things"
        task = wq.add_pr_comment({"id": "c1", "body": body})

        # Should not end mid-word
        desc = task.description
        assert not desc.endswith("thin...")  # Would be mid-word cut
        assert "..." in desc  # Should have ellipsis

    def test_short_comments_not_truncated(self):
        """Short comments are not truncated."""
        wq = WorkflowQueue()
        body = "Short comment"
        task = wq.add_pr_comment({"id": "c1", "body": body})

        assert task.description == f"Address: {body}"
        assert "..." not in task.description
