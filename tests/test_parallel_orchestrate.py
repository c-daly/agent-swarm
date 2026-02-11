"""Tests for parallel orchestrator."""

from unittest.mock import MagicMock, patch

import pytest
import yaml

from parallel_orchestrate import (
    WORKFLOW_ID,
    ManifestTask,
    ParallelOrchestrator,
    build_subagent_prompt,
    parse_manifest,
)
from workflow_queue import WorkflowQueue


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_manifest_path(tmp_path):
    """Create a valid sample manifest YAML file."""
    manifest = {
        "name": "test-manifest",
        "base_branch": "dev",
        "max_agents": 2,
        "max_retries": 1,
        "tasks": [
            {
                "name": "stack",
                "module_path": "src/stack.py",
                "test_path": "tests/test_stack.py",
                "description": "Thread-safe stack",
                "min_tests": 5,
            },
            {
                "name": "queue",
                "module_path": "src/queue.py",
                "test_path": "tests/test_queue.py",
                "description": "FIFO queue",
                "min_tests": 5,
            },
        ],
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.dump(manifest))
    return str(path)


@pytest.fixture
def orch(sample_manifest_path):
    """Create a ParallelOrchestrator with a loaded manifest."""
    o = ParallelOrchestrator()
    o.load_manifest(sample_manifest_path)
    return o


# ============================================================================
# Manifest Parsing
# ============================================================================


class TestParseManifest:
    def test_valid_manifest(self, sample_manifest_path):
        manifest = parse_manifest(sample_manifest_path)
        assert manifest.name == "test-manifest"
        assert manifest.base_branch == "dev"
        assert manifest.max_agents == 2
        assert manifest.max_retries == 1
        assert len(manifest.tasks) == 2
        assert manifest.tasks[0].name == "stack"
        assert manifest.tasks[1].name == "queue"

    def test_missing_name_raises(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(yaml.dump({"tasks": [{"name": "x", "module_path": "x", "test_path": "x", "description": "x"}]}))
        with pytest.raises(ValueError, match="name"):
            parse_manifest(str(path))

    def test_missing_tasks_raises(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(yaml.dump({"name": "foo"}))
        with pytest.raises(ValueError, match="tasks"):
            parse_manifest(str(path))

    def test_missing_task_field_raises(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(yaml.dump({
            "name": "foo",
            "tasks": [{"name": "x"}],  # missing module_path, test_path, description
        }))
        with pytest.raises(ValueError, match="module_path"):
            parse_manifest(str(path))

    def test_duplicate_task_names_rejected(self, tmp_path):
        task = {"name": "dup", "module_path": "x", "test_path": "x", "description": "x"}
        path = tmp_path / "bad.yaml"
        path.write_text(yaml.dump({"name": "foo", "tasks": [task, task]}))
        with pytest.raises(ValueError, match="Duplicate"):
            parse_manifest(str(path))

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_manifest("/nonexistent/manifest.yaml")

    def test_empty_manifest_raises(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text("")
        with pytest.raises(ValueError, match="empty"):
            parse_manifest(str(path))

    def test_defaults_applied(self, tmp_path):
        path = tmp_path / "minimal.yaml"
        path.write_text(yaml.dump({
            "name": "minimal",
            "tasks": [{"name": "x", "module_path": "x.py", "test_path": "t.py", "description": "desc"}],
        }))
        manifest = parse_manifest(str(path))
        assert manifest.base_branch == "dev"
        assert manifest.max_agents == 3
        assert manifest.max_retries == 2
        assert manifest.tasks[0].min_tests == 1


# ============================================================================
# Prompt Generation
# ============================================================================


class TestBuildSubagentPrompt:
    def test_contains_branch_name(self):
        task = ManifestTask(name="stack", module_path="src/stack.py", test_path="tests/test_stack.py", description="Stack", min_tests=10)
        prompt = build_subagent_prompt(task, "dev")
        assert "task/stack" in prompt

    def test_contains_file_scope(self):
        task = ManifestTask(name="queue", module_path="src/queue.py", test_path="tests/test_queue.py", description="Queue", min_tests=5)
        prompt = build_subagent_prompt(task, "main")
        assert "src/queue.py" in prompt
        assert "tests/test_queue.py" in prompt

    def test_contains_tdd_instructions(self):
        task = ManifestTask(name="x", module_path="x.py", test_path="t.py", description="X", min_tests=3)
        prompt = build_subagent_prompt(task, "dev")
        assert "failing tests FIRST" in prompt
        assert "TDD" in prompt

    def test_contains_min_tests(self):
        task = ManifestTask(name="x", module_path="x.py", test_path="t.py", description="X", min_tests=15)
        prompt = build_subagent_prompt(task, "dev")
        assert "15+" in prompt

    def test_contains_base_branch(self):
        task = ManifestTask(name="x", module_path="x.py", test_path="t.py", description="X")
        prompt = build_subagent_prompt(task, "main")
        assert "main" in prompt


# ============================================================================
# Orchestrator Lifecycle
# ============================================================================


class TestOrchestratorLifecycle:
    def test_start_creates_workflow_state(self, orch):
        orch.start()
        import workflow_client
        state = workflow_client.workflow_get_state(WORKFLOW_ID)
        assert state is not None
        assert state["manifest_name"] == "test-manifest"
        assert "stack" in state["tasks"]
        assert "queue" in state["tasks"]

    def test_start_sets_phase(self, orch):
        orch.start()
        assert orch.get_phase() == "spawn_agents"

    def test_start_without_manifest_raises(self):
        orch = ParallelOrchestrator()
        with pytest.raises(RuntimeError, match="No manifest"):
            orch.start()

    def test_start_twice_raises(self, orch):
        orch.start()
        with pytest.raises(RuntimeError):
            orch.start()

    def test_stop_deactivates(self, orch):
        orch.start()
        orch.stop()
        import workflow_client
        assert not workflow_client.workflow_is_active(WORKFLOW_ID)

    def test_check_status_returns_tasks(self, orch):
        orch.start()
        status = orch.check_status()
        assert "stack" in status
        assert status["stack"]["status"] == "pending"
        assert "queue" in status
        assert status["queue"]["status"] == "pending"

    def test_check_status_empty_when_not_started(self):
        orch = ParallelOrchestrator()
        assert orch.check_status() == {}


# ============================================================================
# Task Queue Integration
# ============================================================================


class TestTaskQueue:
    def test_manifest_tasks_in_queue(self, orch):
        orch.start()
        wq = WorkflowQueue(pr_id="test-manifest")
        wq.refresh()
        task = wq.get_next_task()
        assert task is not None
        assert "stack" in task.description or "queue" in task.description


# ============================================================================
# Retry Logic
# ============================================================================


class TestRetryLogic:
    def test_failed_task_retried(self, orch):
        orch.start()

        # Simulate spawning a worker
        import worker_pool
        worker_id = worker_pool.spawn_worker("task-1", "stack task")
        orch._worker_task_map[worker_id] = "stack"

        outcome = orch.handle_completion(worker_id, success=False, result={"error": "tests failed"})
        assert outcome == "retrying"

        # Check retry count incremented
        status = orch.check_status()
        assert status["stack"]["retries"] == 1
        assert status["stack"]["status"] == "pending"

    def test_max_retries_exceeded_marks_failed(self, orch):
        orch.start()

        import worker_pool

        # First attempt fails -> retry
        w1 = worker_pool.spawn_worker("task-1", "stack")
        orch._worker_task_map[w1] = "stack"
        outcome = orch.handle_completion(w1, success=False, result={"error": "err1"})
        assert outcome == "retrying"

        # Second attempt fails -> max_retries=1, so this is the retry, now exceeds
        w2 = worker_pool.spawn_worker("task-2", "stack retry")
        orch._worker_task_map[w2] = "stack"
        outcome = orch.handle_completion(w2, success=False, result={"error": "err2"})
        assert outcome == "failed"

        status = orch.check_status()
        assert status["stack"]["status"] == "failed"

    def test_successful_completion(self, orch):
        orch.start()

        import worker_pool
        w = worker_pool.spawn_worker("task-1", "stack")
        orch._worker_task_map[w] = "stack"
        outcome = orch.handle_completion(w, success=True)
        assert outcome == "completed"

        status = orch.check_status()
        assert status["stack"]["status"] == "completed"


# ============================================================================
# Merge
# ============================================================================


class TestMerge:
    def test_merge_calls_git_for_completed_tasks(self, orch):
        orch.start()

        # Mark stack as completed
        import workflow_client
        state = workflow_client.workflow_get_state(WORKFLOW_ID)
        state["tasks"]["stack"]["status"] = "completed"
        workflow_client.workflow_set_state(WORKFLOW_ID, state)

        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("parallel_orchestrate.subprocess.run", return_value=mock_result) as mock_run:
            results = orch.merge_all()

        assert len(results) == 1
        assert results[0]["task_name"] == "stack"
        assert results[0]["success"] is True

        # Verify git merge was called
        calls = mock_run.call_args_list
        merge_call = calls[0]
        assert "merge" in merge_call[0][0]
        assert "task/stack" in merge_call[0][0]

    def test_merge_conflict_kicks_back_to_monitor(self, orch):
        orch.start()

        import workflow_client
        state = workflow_client.workflow_get_state(WORKFLOW_ID)
        state["tasks"]["stack"]["status"] = "completed"
        workflow_client.workflow_set_state(WORKFLOW_ID, state)

        mock_result = MagicMock(returncode=1, stdout="", stderr="CONFLICT")
        with patch("parallel_orchestrate.subprocess.run", return_value=mock_result):
            results = orch.merge_all()

        assert results[0]["success"] is False
        assert "conflict" in results[0]["message"].lower()
        assert orch.get_phase() == "monitor"

    def test_merge_skips_non_completed_tasks(self, orch):
        orch.start()
        # All tasks are "pending", none should be merged
        mock_result = MagicMock(returncode=0)
        with patch("parallel_orchestrate.subprocess.run", return_value=mock_result) as mock_run:
            results = orch.merge_all()

        assert len(results) == 0
        mock_run.assert_not_called()


# ============================================================================
# Verify
# ============================================================================


class TestVerify:
    def test_verify_success_sets_done(self, orch):
        orch.start()
        mock_result = MagicMock(returncode=0, stdout="10 passed\n", stderr="")
        with patch("gateway_conditions.subprocess.run", return_value=mock_result):
            passed, msg = orch.verify()
        assert passed is True
        assert orch.get_phase() == "done"

    def test_verify_failure_kicks_back_to_merge(self, orch):
        orch.start()
        mock_result = MagicMock(returncode=1, stdout="3 failed\n", stderr="")
        with patch("gateway_conditions.subprocess.run", return_value=mock_result):
            passed, msg = orch.verify()
        assert passed is False
        assert orch.get_phase() == "merge"


# ============================================================================
# Summary
# ============================================================================


class TestSummary:
    def test_summary_contains_task_names(self, orch):
        orch.start()
        summary = orch.generate_summary()
        assert "stack" in summary
        assert "queue" in summary

    def test_summary_contains_phase(self, orch):
        orch.start()
        summary = orch.generate_summary()
        assert "spawn_agents" in summary

    def test_summary_contains_table_headers(self, orch):
        orch.start()
        summary = orch.generate_summary()
        assert "| Task |" in summary
        assert "| Status |" in summary

    def test_summary_empty_when_not_started(self):
        orch = ParallelOrchestrator()
        summary = orch.generate_summary()
        assert "No orchestration" in summary
