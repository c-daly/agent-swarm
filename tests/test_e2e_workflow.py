"""End-to-end workflow tests.

These tests exercise full workflow scenarios rather than isolated functions,
catching integration issues that unit tests miss.
"""

import sys
from pathlib import Path

import pytest

# Add paths for imports (pytest pythonpath handles this, but explicit for IDE support)
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from iterate_state import (  # noqa: E402
    TaskQueue,
    Task,
    TaskStatus,
    TaskSource,
    load_state,
    save_state,
    save_queue,
    load_queue,
    advance_phase,
    init_iterate,
    SESSION_FILE,
)


@pytest.fixture
def clean_state(tmp_path, monkeypatch):
    """Provide clean state directory for each test."""
    state_dir = tmp_path / ".state"
    state_dir.mkdir()
    session_file = state_dir / "session.json"

    # Patch the module-level constants
    import iterate_state
    monkeypatch.setattr(iterate_state, "STATE_DIR", state_dir)
    monkeypatch.setattr(iterate_state, "SESSION_FILE", session_file)

    yield state_dir, session_file


class TestKickbackScenarios:
    """Test phase kick-back behavior end-to-end."""

    def test_test_failure_kicks_to_implement(self, clean_state, capsys):
        """When tests fail, kick back to implement phase (not test_writing)."""
        state_dir, session_file = clean_state

        # Initialize TDD workflow
        init_iterate(tdd=True, max_iter=5)

        # Manually advance to test phase
        state = load_state()
        state["iterate_phase"] = "test"
        save_state(state)

        # Kick back (simulating test failure)
        advance_phase("back")

        # Should go to implement, NOT test_writing
        state = load_state()
        assert state["iterate_phase"] == "implement", \
            "Test failure should kick back to implement (fix code), not test_writing"

        captured = capsys.readouterr()
        assert "IMPLEMENT" in captured.out

    def test_coverage_gap_kicks_to_test_writing(self, clean_state, capsys):
        """When coverage is insufficient, kick back to test_writing."""
        state_dir, session_file = clean_state

        # Initialize TDD workflow
        init_iterate(tdd=True, max_iter=5)

        # Manually advance to coverage phase
        state = load_state()
        state["iterate_phase"] = "coverage"
        save_state(state)

        # Kick back (simulating coverage gap)
        advance_phase("back")

        # Should go to test_writing
        state = load_state()
        assert state["iterate_phase"] == "test_writing", \
            "Coverage gap should kick back to test_writing (write more tests)"

        captured = capsys.readouterr()
        assert "TEST_WRITING" in captured.out

    def test_review_failure_kicks_to_implement(self, clean_state, capsys):
        """When review finds issues, kick back to implement."""
        state_dir, session_file = clean_state

        # Initialize TDD workflow
        init_iterate(tdd=True, max_iter=5)

        # Manually advance to review phase
        state = load_state()
        state["iterate_phase"] = "review"
        save_state(state)

        # Kick back (simulating review issues)
        advance_phase("back")

        # Should go to implement
        state = load_state()
        assert state["iterate_phase"] == "implement", \
            "Review issues should kick back to implement"


class TestTaskRetryEscalation:
    """Test task retry and escalation behavior end-to-end."""

    def test_task_retries_before_escalating(self, clean_state):
        """Task should retry MAX_TASK_RETRIES times before escalating."""
        state_dir, session_file = clean_state

        queue = TaskQueue()
        task = Task(
            id="task-retry-test",
            description="Test task for retry",
            status=TaskStatus.RUNNING,
            priority=3,
            source=TaskSource.ORIGINAL,
            pr_id="test-pr",
            phase="implement",
            iteration=0,
            created_at="2026-01-01T00:00:00Z",
        )
        queue.add_task(task)

        # First failure - should NOT escalate
        escalate = queue.mark_failed("task-retry-test", "Error 1")
        assert escalate is False
        assert queue.tasks["task-retry-test"].status == TaskStatus.PENDING
        assert queue.tasks["task-retry-test"].failure_count == 1

        # Second failure - should NOT escalate
        escalate = queue.mark_failed("task-retry-test", "Error 2")
        assert escalate is False
        assert queue.tasks["task-retry-test"].status == TaskStatus.PENDING
        assert queue.tasks["task-retry-test"].failure_count == 2

        # Third failure - SHOULD escalate
        escalate = queue.mark_failed("task-retry-test", "Error 3")
        assert escalate is True
        assert queue.tasks["task-retry-test"].status == TaskStatus.FAILED
        assert queue.tasks["task-retry-test"].failure_count == 3
        assert "task-retry-test" in queue.failed

    def test_failure_count_persists_across_saves(self, clean_state):
        """Failure count should persist when queue is saved and reloaded."""
        state_dir, session_file = clean_state

        queue = TaskQueue()
        task = Task(
            id="task-persist",
            description="Test persistence",
            status=TaskStatus.RUNNING,
            priority=3,
            source=TaskSource.ORIGINAL,
            pr_id="test-pr",
            phase="implement",
            iteration=0,
            created_at="2026-01-01T00:00:00Z",
        )
        queue.add_task(task)

        # Fail once and save
        queue.mark_failed("task-persist", "Error")
        save_queue(queue)

        # Reload and check failure_count preserved
        reloaded = load_queue()
        assert reloaded.tasks["task-persist"].failure_count == 1

        # Fail again through reloaded queue
        reloaded.mark_failed("task-persist", "Error 2")
        assert reloaded.tasks["task-persist"].failure_count == 2


class TestOrchestratorEnforcement:
    """Test orchestrator tool restrictions end-to-end."""

    def test_orchestrator_mode_blocks_edit(self, clean_state):
        """Edit tool should be blocked when mode=orchestrate."""
        state_dir, session_file = clean_state

        # Set up orchestrate mode
        state = {
            "mode": "orchestrate",
            "workflow_invoked": True,
        }
        save_state(state)

        # Import the check function
        from combined_enforcement import check_orchestrator_restrictions, ORCHESTRATOR_BLOCKED_TOOLS

        # Test Edit is blocked
        result = check_orchestrator_restrictions("Edit", {"file_path": "/test.py"}, state)
        assert result is not None, "Edit should be blocked in orchestrate mode"
        assert "deny" in str(result) or "ORCHESTRATOR" in str(result.get("hookSpecificOutput", {}).get("permissionDecisionReason", ""))

    def test_orchestrator_mode_allows_task(self, clean_state):
        """Task tool should be allowed when mode=orchestrate."""
        state_dir, session_file = clean_state

        state = {
            "mode": "orchestrate",
            "workflow_invoked": True,
        }
        save_state(state)

        from combined_enforcement import check_orchestrator_restrictions

        # Test Task is allowed
        result = check_orchestrator_restrictions("Task", {"prompt": "Do something"}, state)
        assert result is None, "Task should be allowed in orchestrate mode"

    def test_orchestrator_bash_whitelist(self, clean_state):
        """Only whitelisted Bash commands should be allowed for orchestrator."""
        state_dir, session_file = clean_state

        state = {
            "mode": "orchestrate",
            "workflow_invoked": True,
        }
        save_state(state)

        from combined_enforcement import check_orchestrator_restrictions

        # Whitelisted command should be allowed
        result = check_orchestrator_restrictions(
            "Bash",
            {"command": "git status"},
            state
        )
        assert result is None, "git status should be allowed"

        # Non-whitelisted command should be blocked
        result = check_orchestrator_restrictions(
            "Bash",
            {"command": "echo 'hello world'"},
            state
        )
        assert result is not None, "echo should be blocked for orchestrator"

    def test_subagent_not_blocked(self, clean_state):
        """Subagents (mode != orchestrate) should not be blocked."""
        state_dir, session_file = clean_state

        # Subagent state - isolated state, no iterate mode
        state = {
            "workflow_invoked": True,
        }
        save_state(state)

        from combined_enforcement import check_orchestrator_restrictions

        # Edit should be allowed for subagent
        result = check_orchestrator_restrictions("Edit", {"file_path": "/test.py"}, state)
        assert result is None, "Edit should be allowed when mode != orchestrate"


class TestFullWorkflowCycle:
    """Test complete workflow cycles end-to-end."""

    def test_tdd_full_cycle_phases(self, clean_state):
        """Test advancing through all TDD phases."""
        state_dir, session_file = clean_state

        init_iterate(tdd=True, max_iter=5)

        expected_phases = ["test_writing", "implement", "test", "coverage", "review"]

        state = load_state()
        assert state["iterate_phase"] == "test_writing"

        # Advance through all phases
        for i, expected_next in enumerate(expected_phases[1:], 1):
            advance_phase("next")
            state = load_state()
            assert state["iterate_phase"] == expected_next, \
                f"After {i} advances, should be in {expected_next}"

    def test_iteration_increments_on_cycle_complete(self, clean_state):
        """Iteration counter should increment when completing a full cycle."""
        state_dir, session_file = clean_state

        init_iterate(tdd=True, max_iter=5)

        state = load_state()
        assert state["iteration"] == 0

        # Complete full cycle (5 phase advances)
        for _ in range(5):
            advance_phase("next")

        state = load_state()
        # After completing review, advancing should start new iteration
        assert state["iteration"] == 1
        assert state["iterate_phase"] == "test_writing"
