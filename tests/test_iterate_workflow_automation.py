#!/usr/bin/env python3
"""Tests for iterate workflow automation - integration with task_queue.

Tests the automated behavior of:
- Design phase: decompose spec into task_queue
- Review phase: fetch PR comments via gh CLI, convert to tasks, gate advancement
"""

import sys
from pathlib import Path

import pytest

# Add lib and scripts to path
lib_dir = Path(__file__).parent.parent / "lib"
scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(lib_dir))
sys.path.insert(0, str(scripts_dir))

from iterate_workflow import (  # noqa: E402
    Phase,
    start,
    get_state,
    get_phase,
    advance_phase,
    is_review_blocked,
    add_review_comment,
    get_pending_review_tasks,
    mark_review_task_done,
    set_spec_file,
    decompose_spec_to_queue,
    STATE_FILE,
    LOG_FILE,
    _reset_logger,
)


@pytest.fixture(autouse=True)
def clean_state():
    """Clean state before and after each test."""
    # Clean iterate state
    if STATE_FILE.exists():
        STATE_FILE.unlink()

    # Clean task queue (session.json)
    session_file = STATE_FILE.parent / "session.json"
    if session_file.exists():
        session_file.unlink()

    yield

    if STATE_FILE.exists():
        STATE_FILE.unlink()
    if session_file.exists():
        session_file.unlink()


@pytest.fixture(autouse=True)
def clean_logging():
    """Clean logging state before and after each test."""
    _reset_logger()
    if LOG_FILE.exists():
        LOG_FILE.unlink()
    yield
    _reset_logger()


@pytest.fixture
def sample_spec_file(tmp_path):
    """Create a sample spec file for testing."""
    spec_content = """# Feature Spec

## TaskStatus Enum

```python
class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
```

## Task Dataclass

```python
@dataclass
class Task:
    id: str
    description: str
    status: TaskStatus
```

## add_task(task: Task)

Add a task to the queue.
"""
    spec_file = tmp_path / "SPEC.md"
    spec_file.write_text(spec_content)
    return spec_file


class TestDesignPhaseAutomation:
    """Tests for design phase spec decomposition."""

    def test_set_spec_file_stores_path(self, sample_spec_file):
        """set_spec_file should store spec path in state."""
        start("Task", needs_intake=False, needs_design=True)
        set_spec_file(str(sample_spec_file))
        state = get_state()
        assert state.get("spec_file") == str(sample_spec_file)

    def test_decompose_spec_creates_tasks(self, sample_spec_file):
        """decompose_spec_to_queue should create tasks from spec sections."""
        start("Task", needs_intake=False, needs_design=True)
        set_spec_file(str(sample_spec_file))

        tasks = decompose_spec_to_queue()

        # Should have created tasks for enum, dataclass, and method
        assert len(tasks) >= 2
        # Tasks should have descriptions
        assert all(t.get("description") for t in tasks)

    def test_decompose_spec_requires_design_phase(self, sample_spec_file):
        """decompose_spec_to_queue should only work in design phase."""
        start("Task")  # Default: test_writing phase
        set_spec_file(str(sample_spec_file))

        # Should raise or return empty when not in design phase
        with pytest.raises(ValueError, match="design phase"):
            decompose_spec_to_queue()

    def test_decompose_spec_without_spec_file_fails(self):
        """decompose_spec_to_queue should fail if no spec file set."""
        start("Task", needs_intake=False, needs_design=True)

        with pytest.raises(ValueError, match="spec file"):
            decompose_spec_to_queue()


class TestReviewPhaseAutomation:
    """Tests for review phase PR comment integration."""

    def test_add_review_comment_creates_task(self):
        """add_review_comment should create a task from PR comment."""
        start("Task")
        # Fast forward to review
        advance_phase()  # test_writing -> implement
        advance_phase()  # implement -> test
        # Set test results and advance to review
        from iterate_workflow import set_test_results
        set_test_results(True, True, True)
        advance_phase()  # test -> review

        assert get_phase() == Phase.REVIEW

        comment = {
            "id": "comment-123",
            "body": "Please add error handling",
            "severity": "warning",
            "path": "src/main.py"
        }
        task = add_review_comment(comment)

        assert task is not None
        assert "error handling" in task.get("description", "").lower()

    def test_add_review_comment_requires_review_phase(self):
        """add_review_comment should only work in review phase."""
        start("Task")  # test_writing phase

        comment = {"id": "c1", "body": "Fix this"}
        with pytest.raises(ValueError, match="review phase"):
            add_review_comment(comment)

    def test_get_pending_review_tasks_returns_unaddressed(self):
        """get_pending_review_tasks should return unaddressed comments."""
        start("Task")
        # Fast forward to review
        advance_phase()
        advance_phase()
        from iterate_workflow import set_test_results
        set_test_results(True, True, True)
        advance_phase()

        # Add two comments
        add_review_comment({"id": "c1", "body": "Issue 1"})
        add_review_comment({"id": "c2", "body": "Issue 2"})

        pending = get_pending_review_tasks()
        assert len(pending) == 2

    def test_mark_review_task_done_removes_from_pending(self):
        """mark_review_task_done should mark task as addressed."""
        start("Task")
        advance_phase()
        advance_phase()
        from iterate_workflow import set_test_results
        set_test_results(True, True, True)
        advance_phase()

        task = add_review_comment({"id": "c1", "body": "Issue 1"})
        task_id = task["id"]

        mark_review_task_done(task_id)

        pending = get_pending_review_tasks()
        assert len(pending) == 0

    def test_is_review_blocked_when_comments_pending(self):
        """is_review_blocked should return True when comments unaddressed."""
        start("Task")
        advance_phase()
        advance_phase()
        from iterate_workflow import set_test_results
        set_test_results(True, True, True)
        advance_phase()

        add_review_comment({"id": "c1", "body": "Issue 1"})

        assert is_review_blocked() is True

    def test_is_review_blocked_false_when_all_addressed(self):
        """is_review_blocked should return False when all addressed."""
        start("Task")
        advance_phase()
        advance_phase()
        from iterate_workflow import set_test_results
        set_test_results(True, True, True)
        advance_phase()

        task = add_review_comment({"id": "c1", "body": "Issue 1"})
        mark_review_task_done(task["id"])

        assert is_review_blocked() is False

    def test_advance_from_review_blocked_when_comments_pending(self):
        """advance_phase from review should fail when comments unaddressed."""
        start("Task")
        advance_phase()
        advance_phase()
        from iterate_workflow import set_test_results, set_review_status
        set_test_results(True, True, True)
        advance_phase()

        # Add unaddressed comment
        add_review_comment({"id": "c1", "body": "Issue 1"})
        set_review_status(True)  # Try to mark as clean

        # Advance should be blocked
        new_phase = advance_phase()
        # Should stay in review or kick back, not go to done
        assert new_phase != Phase.DONE or get_phase() == Phase.REVIEW


class TestIntakePhaseAutomation:
    """Tests for intake phase requirement gathering."""

    def test_intake_stores_requirements(self):
        """Intake phase should allow storing gathered requirements."""
        start("Task", needs_intake=True, needs_design=True)

        from iterate_workflow import add_requirement, get_requirements

        add_requirement("Must support authentication")
        add_requirement("Should have dark mode")

        reqs = get_requirements()
        assert len(reqs) == 2
        assert "authentication" in reqs[0].lower()

    def test_requirements_passed_to_design(self):
        """Requirements should be accessible in design phase."""
        start("Task", needs_intake=True, needs_design=True)

        from iterate_workflow import add_requirement, get_requirements

        add_requirement("Req 1")
        advance_phase()  # intake -> design

        assert get_phase() == Phase.DESIGN
        reqs = get_requirements()
        assert len(reqs) == 1
