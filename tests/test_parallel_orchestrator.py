"""Tests for the ParallelOrchestrator."""

from unittest.mock import MagicMock, patch

import pytest

from lib.orchestrator import ParallelOrchestrator, SpawnRequest


@pytest.fixture
def manifest_path(tmp_path):
    """Create a manifest file and return its path."""
    content = """\
project: test-project
base_branch: main
max_retries: 2
tasks:
  - name: stack
    description: "Implement a stack"
    target_dir: src/stack
    test_dir: tests/test_stack
    min_tests: 10
  - name: queue
    description: "Implement a queue"
    target_dir: src/queue
    test_dir: tests/test_queue
    min_tests: 10
  - name: linked_list
    description: "Implement a linked list"
    target_dir: src/linked_list
    test_dir: tests/test_linked_list
    min_tests: 10
"""
    path = tmp_path / "manifest.yaml"
    path.write_text(content)
    return str(path)


@pytest.fixture
def orchestrator(tmp_state_dir, manifest_path):
    """Create and load an orchestrator."""
    orch = ParallelOrchestrator()
    orch.load_manifest(manifest_path)
    return orch


class TestLifecycle:
    def test_load_manifest(self, orchestrator):
        assert orchestrator._manifest is not None
        assert orchestrator._manifest.project == "test-project"
        assert len(orchestrator._manifest.tasks) == 3

    def test_start_initializes_state(self, orchestrator):
        orchestrator.start()
        assert orchestrator.is_active()
        assert orchestrator.get_phase() == "spawning"

    def test_start_sets_all_tasks_pending(self, orchestrator):
        orchestrator.start()
        status = orchestrator.get_status()
        for task in orchestrator._manifest.tasks:
            assert status["tasks"][task.name]["status"] == "pending"

    def test_stop_deactivates(self, orchestrator):
        orchestrator.start()
        orchestrator.stop()
        assert not orchestrator.is_active()

    def test_double_start_raises(self, orchestrator):
        orchestrator.start()
        with pytest.raises(RuntimeError, match="already active"):
            orchestrator.start()


class TestSpawn:
    def test_get_pending_tasks(self, orchestrator):
        orchestrator.start()
        pending = orchestrator.get_pending_tasks()
        assert len(pending) == 3
        assert all(isinstance(p, SpawnRequest) for p in pending)

    def test_pending_tasks_have_prompts(self, orchestrator):
        orchestrator.start()
        pending = orchestrator.get_pending_tasks()
        for req in pending:
            assert len(req.prompt) > 0
            assert req.task_name in req.prompt

    def test_record_spawn(self, orchestrator):
        orchestrator.start()
        orchestrator.record_spawn("stack", "worker-1")
        status = orchestrator.get_status()
        assert status["tasks"]["stack"]["status"] == "spawned"
        assert status["tasks"]["stack"]["worker_id"] == "worker-1"

    def test_pending_excludes_spawned(self, orchestrator):
        orchestrator.start()
        orchestrator.record_spawn("stack", "worker-1")
        pending = orchestrator.get_pending_tasks()
        assert len(pending) == 2
        assert all(p.task_name != "stack" for p in pending)


class TestMonitor:
    def test_record_completion_success(self, orchestrator):
        orchestrator.start()
        orchestrator.record_spawn("stack", "w1")
        result = orchestrator.record_completion("stack", success=True)
        assert result == "completed"
        status = orchestrator.get_status()
        assert status["tasks"]["stack"]["status"] == "completed"

    def test_record_completion_failure_retries(self, orchestrator):
        orchestrator.start()
        orchestrator.record_spawn("stack", "w1")
        result = orchestrator.record_completion("stack", success=False, error="test failed")
        assert result == "retrying"
        status = orchestrator.get_status()
        assert status["tasks"]["stack"]["status"] == "pending"
        assert status["tasks"]["stack"]["retries"] == 1

    def test_record_completion_exhausted_retries(self, orchestrator):
        orchestrator.start()
        # Exhaust retries (max_retries=2)
        orchestrator.record_spawn("stack", "w1")
        orchestrator.record_completion("stack", success=False, error="fail 1")
        orchestrator.record_spawn("stack", "w2")
        orchestrator.record_completion("stack", success=False, error="fail 2")
        orchestrator.record_spawn("stack", "w3")
        result = orchestrator.record_completion("stack", success=False, error="fail 3")
        assert result == "failed"
        status = orchestrator.get_status()
        assert status["tasks"]["stack"]["status"] == "failed"

    def test_check_all_done_false(self, orchestrator):
        orchestrator.start()
        assert not orchestrator.check_all_done()

    def test_check_all_done_true(self, orchestrator):
        orchestrator.start()
        for task in orchestrator._manifest.tasks:
            orchestrator.record_spawn(task.name, f"w-{task.name}")
            orchestrator.record_completion(task.name, success=True)
        assert orchestrator.check_all_done()

    def test_check_all_done_with_failures(self, orchestrator):
        orchestrator.start()
        # Complete 2, fail 1 (exhausted retries)
        orchestrator.record_spawn("stack", "w1")
        orchestrator.record_completion("stack", success=True)
        orchestrator.record_spawn("queue", "w2")
        orchestrator.record_completion("queue", success=True)
        # Exhaust linked_list retries
        for i in range(3):
            orchestrator.record_spawn("linked_list", f"w{i}")
            orchestrator.record_completion("linked_list", success=False, error=f"fail {i}")
        assert orchestrator.check_all_done()


class TestPhaseTransitions:
    def test_phase_advances_to_monitoring(self, orchestrator):
        orchestrator.start()
        # Spawn all
        for task in orchestrator._manifest.tasks:
            orchestrator.record_spawn(task.name, f"w-{task.name}")
        assert orchestrator.get_phase() == "monitoring"

    def test_phase_advances_to_merging(self, orchestrator):
        orchestrator.start()
        for task in orchestrator._manifest.tasks:
            orchestrator.record_spawn(task.name, f"w-{task.name}")
            orchestrator.record_completion(task.name, success=True)
        assert orchestrator.get_phase() == "merging"


class TestMerge:
    @patch("lib.orchestrator.subprocess.run")
    def test_merge_all_success(self, mock_run, orchestrator):
        orchestrator.start()
        for task in orchestrator._manifest.tasks:
            orchestrator.record_spawn(task.name, f"w-{task.name}")
            orchestrator.record_completion(task.name, success=True)

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        results = orchestrator.merge_all(cwd="/repo")
        assert len(results) == 3
        assert all(r.success for r in results)

    @patch("lib.orchestrator.subprocess.run")
    def test_merge_conflict(self, mock_run, orchestrator):
        orchestrator.start()
        for task in orchestrator._manifest.tasks:
            orchestrator.record_spawn(task.name, f"w-{task.name}")
            orchestrator.record_completion(task.name, success=True)

        # First merge succeeds, second has conflict
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # checkout main
            MagicMock(returncode=0, stdout="", stderr=""),  # merge stack
            MagicMock(returncode=1, stdout="", stderr="CONFLICT"),  # merge queue
            MagicMock(returncode=0, stdout="", stderr=""),  # abort merge
            MagicMock(returncode=0, stdout="", stderr=""),  # merge linked_list
        ]
        results = orchestrator.merge_all(cwd="/repo")
        failed = [r for r in results if not r.success]
        assert len(failed) == 1
        assert failed[0].branch == "task/queue"

    @patch("lib.orchestrator.subprocess.run")
    def test_merge_skips_failed_tasks(self, mock_run, orchestrator):
        orchestrator.start()
        # stack: completed, queue: failed
        orchestrator.record_spawn("stack", "w1")
        orchestrator.record_completion("stack", success=True)
        for i in range(3):
            orchestrator.record_spawn("queue", f"w{i}")
            orchestrator.record_completion("queue", success=False, error="fail")
        orchestrator.record_spawn("linked_list", "w3")
        orchestrator.record_completion("linked_list", success=True)

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        results = orchestrator.merge_all(cwd="/repo")
        # Should only merge stack and linked_list
        merged_branches = [r.branch for r in results]
        assert "task/queue" not in merged_branches
        assert "task/stack" in merged_branches
        assert "task/linked_list" in merged_branches


class TestVerify:
    @patch("lib.orchestrator.subprocess.run")
    def test_verify_pass(self, mock_run, orchestrator):
        mock_run.return_value = MagicMock(returncode=0, stdout="50 passed")
        ok, msg = orchestrator.verify(cwd="/repo")
        assert ok is True

    @patch("lib.orchestrator.subprocess.run")
    def test_verify_fail(self, mock_run, orchestrator):
        mock_run.return_value = MagicMock(returncode=1, stdout="3 failed")
        ok, msg = orchestrator.verify(cwd="/repo")
        assert ok is False


class TestGateway:
    @patch("lib.orchestrator.subprocess.run")
    def test_check_gateway(self, mock_run, orchestrator):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        ok, msg = orchestrator.check_gateway(
            "branch_exists", {"branch": "task/stack", "cwd": "/repo"}
        )
        assert ok is True

    def test_check_unknown_gateway(self, orchestrator):
        ok, msg = orchestrator.check_gateway("nonexistent", {})
        assert ok is False
        assert "unknown" in msg.lower()


@pytest.fixture
def manifest_with_deps_path(tmp_path):
    """Create a manifest with dependencies."""
    content = """\
project: test-deps
base_branch: main
max_retries: 2
tasks:
  - name: setup
    description: "Project setup"
    target_dir: src
    test_dir: tests
  - name: feature-a
    description: "Feature A"
    target_dir: src/a
    test_dir: tests/a
    depends_on:
      - setup
  - name: feature-b
    description: "Feature B"
    target_dir: src/b
    test_dir: tests/b
    depends_on:
      - setup
  - name: integration
    description: "Integration"
    target_dir: src/int
    test_dir: tests/int
    depends_on:
      - feature-a
      - feature-b
"""
    path = tmp_path / "manifest-deps.yaml"
    path.write_text(content)
    return str(path)


@pytest.fixture
def orch_with_deps(tmp_state_dir, manifest_with_deps_path):
    """Create orchestrator with dependency manifest."""
    orch = ParallelOrchestrator()
    orch.load_manifest(manifest_with_deps_path)
    return orch


class TestDependencies:
    def test_only_root_tasks_initially_pending(self, orch_with_deps):
        orch_with_deps.start()
        pending = orch_with_deps.get_pending_tasks()
        names = [p.task_name for p in pending]
        assert names == ["setup"]

    def test_dependents_unlocked_after_dependency_completes(self, orch_with_deps):
        orch_with_deps.start()
        orch_with_deps.record_spawn("setup", "w1")
        orch_with_deps.record_completion("setup", success=True)
        pending = orch_with_deps.get_pending_tasks()
        names = sorted(p.task_name for p in pending)
        assert names == ["feature-a", "feature-b"]

    def test_multi_dependency_waits_for_all(self, orch_with_deps):
        orch_with_deps.start()
        orch_with_deps.record_spawn("setup", "w1")
        orch_with_deps.record_completion("setup", success=True)
        orch_with_deps.record_spawn("feature-a", "w2")
        orch_with_deps.record_completion("feature-a", success=True)
        pending = orch_with_deps.get_pending_tasks()
        names = [p.task_name for p in pending]
        assert "feature-b" in names
        assert "integration" not in names

    def test_multi_dependency_unlocks_when_all_complete(self, orch_with_deps):
        orch_with_deps.start()
        orch_with_deps.record_spawn("setup", "w1")
        orch_with_deps.record_completion("setup", success=True)
        orch_with_deps.record_spawn("feature-a", "w2")
        orch_with_deps.record_completion("feature-a", success=True)
        orch_with_deps.record_spawn("feature-b", "w3")
        orch_with_deps.record_completion("feature-b", success=True)
        pending = orch_with_deps.get_pending_tasks()
        names = [p.task_name for p in pending]
        assert names == ["integration"]

    def test_no_deps_still_works(self, orchestrator):
        """Tasks without depends_on behave as before."""
        orchestrator.start()
        pending = orchestrator.get_pending_tasks()
        assert len(pending) == 3

    def test_failure_propagates_to_direct_dependents(self, orch_with_deps):
        orch_with_deps.start()
        # Exhaust setup retries (max_retries=2, so 3 attempts total)
        for i in range(3):
            orch_with_deps.record_spawn("setup", f"w{i}")
            orch_with_deps.record_completion("setup", success=False, error="fail")
        status = orch_with_deps.get_status()
        assert status["tasks"]["setup"]["status"] == "failed"
        assert status["tasks"]["feature-a"]["status"] == "failed"
        assert status["tasks"]["feature-b"]["status"] == "failed"
        assert status["tasks"]["integration"]["status"] == "failed"

    def test_failure_propagation_message(self, orch_with_deps):
        orch_with_deps.start()
        for i in range(3):
            orch_with_deps.record_spawn("setup", f"w{i}")
            orch_with_deps.record_completion("setup", success=False, error="fail")
        status = orch_with_deps.get_status()
        assert "setup" in status["tasks"]["feature-a"].get("last_error", "")

    def test_partial_failure_only_affects_dependents(self, orch_with_deps):
        orch_with_deps.start()
        orch_with_deps.record_spawn("setup", "w1")
        orch_with_deps.record_completion("setup", success=True)
        # Fail feature-a (exhaust retries)
        for i in range(3):
            orch_with_deps.record_spawn("feature-a", f"w{i}")
            orch_with_deps.record_completion("feature-a", success=False, error="fail")
        status = orch_with_deps.get_status()
        assert status["tasks"]["setup"]["status"] == "completed"
        assert status["tasks"]["feature-a"]["status"] == "failed"
        assert status["tasks"]["feature-b"]["status"] == "pending"  # unaffected
        assert status["tasks"]["integration"]["status"] == "failed"  # depends on feature-a

    def test_check_all_done_after_propagation(self, orch_with_deps):
        orch_with_deps.start()
        for i in range(3):
            orch_with_deps.record_spawn("setup", f"w{i}")
            orch_with_deps.record_completion("setup", success=False, error="fail")
        assert orch_with_deps.check_all_done()


class TestMergeOrder:
    @patch("lib.orchestrator.subprocess.run")
    def test_merge_respects_dependency_order(self, mock_run, orch_with_deps):
        orch_with_deps.start()
        # Complete all tasks
        for name in ["setup", "feature-a", "feature-b", "integration"]:
            orch_with_deps.record_spawn(name, f"w-{name}")
            orch_with_deps.record_completion(name, success=True)

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        results = orch_with_deps.merge_all(cwd="/repo")
        merged = [r.branch for r in results]
        # setup must come before feature-a and feature-b
        # feature-a and feature-b must come before integration
        setup_idx = merged.index("task/setup")
        fa_idx = merged.index("task/feature-a")
        fb_idx = merged.index("task/feature-b")
        int_idx = merged.index("task/integration")
        assert setup_idx < fa_idx
        assert setup_idx < fb_idx
        assert fa_idx < int_idx
        assert fb_idx < int_idx


class TestSummary:
    def test_generate_summary(self, orchestrator):
        orchestrator.start()
        orchestrator.record_spawn("stack", "w1")
        orchestrator.record_completion("stack", success=True)
        summary = orchestrator.generate_summary()
        assert "stack" in summary
        assert "pending" in summary.lower() or "completed" in summary.lower()

    def test_summary_includes_all_tasks(self, orchestrator):
        orchestrator.start()
        summary = orchestrator.generate_summary()
        for task in orchestrator._manifest.tasks:
            assert task.name in summary

    def test_summary_shows_blocked_by(self, orch_with_deps):
        orch_with_deps.start()
        summary = orch_with_deps.generate_summary()
        # integration depends on feature-a and feature-b
        assert "Blocked" in summary or "blocked" in summary


@pytest.fixture
def worktree_manifest_path(tmp_path):
    """Create a manifest with project_dir set."""
    content = """\
project: test-project
base_branch: main
max_retries: 2
project_dir: hermes
tasks:
  - name: stack
    description: "Implement a stack"
    target_dir: hermes/src/stack
    test_dir: hermes/tests/test_stack
    min_tests: 10
  - name: queue
    description: "Implement a queue"
    target_dir: hermes/src/queue
    test_dir: hermes/tests/test_queue
    min_tests: 10
  - name: linked_list
    description: "Implement a linked list"
    target_dir: hermes/src/linked_list
    test_dir: hermes/tests/test_linked_list
    min_tests: 10
"""
    path = tmp_path / "manifest.yaml"
    path.write_text(content)
    return str(path)


@pytest.fixture
def worktree_orchestrator(tmp_state_dir, worktree_manifest_path):
    """Create orchestrator with project_dir manifest."""
    orch = ParallelOrchestrator()
    orch.load_manifest(worktree_manifest_path)
    return orch


class TestWorktreeLifecycle:
    @patch("lib.orchestrator.subprocess.run")
    def test_start_creates_worktrees(self, mock_run, worktree_orchestrator, tmp_path):
        """start(cwd) calls git worktree add for each task."""
        # rev-parse --verify returns non-zero (branch doesn't exist yet)
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        worktree_orchestrator.start(cwd=str(tmp_path))

        # Should have called git worktree add for each of 3 tasks
        # Plus git rev-parse --verify for each task to check branch existence
        worktree_add_calls = [
            c for c in mock_run.call_args_list
            if "worktree" in c.args[0] and "add" in c.args[0]
        ]
        assert len(worktree_add_calls) == 3

        # Each should include -b flag (new branches)
        for c in worktree_add_calls:
            assert "-b" in c.args[0]

    @patch("lib.orchestrator.subprocess.run")
    def test_start_stores_worktree_dir_in_state(self, mock_run, worktree_orchestrator, tmp_path):
        """start(cwd) stores worktree_dir in per-task state."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        worktree_orchestrator.start(cwd=str(tmp_path))

        status = worktree_orchestrator.get_status()
        for task_name, task_state in status["tasks"].items():
            assert task_state["worktree_dir"] != ""
            assert "test-project" in task_state["worktree_dir"]
            assert task_name in task_state["worktree_dir"]

    @patch("lib.orchestrator.subprocess.run")
    def test_start_reuses_existing_worktrees(self, mock_run, worktree_orchestrator, tmp_path):
        """start(cwd) reuses worktrees that already exist on disk."""
        # Create the worktree directory so it appears to already exist
        project_root = tmp_path / "hermes"
        project_root.mkdir()
        wt_dir = project_root / ".worktrees" / "test-project" / "stack"
        wt_dir.mkdir(parents=True)

        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        worktree_orchestrator.start(cwd=str(tmp_path))

        # Should NOT have called git worktree add for "stack" (it already exists)
        worktree_add_calls = [
            c for c in mock_run.call_args_list
            if "worktree" in c.args[0] and "add" in c.args[0]
        ]
        # Only 2 tasks should get worktree add (queue and linked_list)
        assert len(worktree_add_calls) == 2

    @patch("lib.orchestrator.subprocess.run")
    def test_start_existing_branch_no_b_flag(self, mock_run, worktree_orchestrator, tmp_path):
        """start(cwd) uses no -b flag when branch already exists (retry)."""
        # First call (rev-parse) returns 0 = branch exists, rest return 1
        def side_effect(cmd, **kwargs):
            if "rev-parse" in cmd:
                return MagicMock(returncode=0, stdout="abc123", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        worktree_orchestrator.start(cwd=str(tmp_path))

        worktree_add_calls = [
            c for c in mock_run.call_args_list
            if "worktree" in c.args[0] and "add" in c.args[0]
        ]
        # None should have -b flag since branches "already exist"
        for c in worktree_add_calls:
            assert "-b" not in c.args[0]

    @patch("lib.orchestrator.subprocess.run")
    def test_stop_removes_worktrees(self, mock_run, worktree_orchestrator, tmp_path):
        """stop(cwd) calls git worktree remove for each task."""
        # Start first (branches don't exist)
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        worktree_orchestrator.start(cwd=str(tmp_path))
        mock_run.reset_mock()

        # Now stop
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # Create the worktree dirs so cleanup finds them
        project_root = tmp_path / "hermes"
        project_root.mkdir(exist_ok=True)
        for task_name in ["stack", "queue", "linked_list"]:
            wt = project_root / ".worktrees" / "test-project" / task_name
            wt.mkdir(parents=True, exist_ok=True)

        worktree_orchestrator.stop(cwd=str(tmp_path))

        worktree_remove_calls = [
            c for c in mock_run.call_args_list
            if "worktree" in c.args[0] and "remove" in c.args[0]
        ]
        assert len(worktree_remove_calls) == 3

    @patch("lib.orchestrator.subprocess.run")
    def test_get_pending_tasks_includes_worktree_dir(self, mock_run, worktree_orchestrator, tmp_path):
        """get_pending_tasks() includes worktree_dir in SpawnRequest."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        worktree_orchestrator.start(cwd=str(tmp_path))

        pending = worktree_orchestrator.get_pending_tasks()
        assert len(pending) == 3
        for req in pending:
            assert req.worktree_dir != ""
            assert req.task_name in req.worktree_dir

    @patch("lib.orchestrator.subprocess.run")
    def test_pending_prompt_has_worktree_instructions(self, mock_run, worktree_orchestrator, tmp_path):
        """Pending task prompts mention worktree dir and no branch switching."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        worktree_orchestrator.start(cwd=str(tmp_path))

        pending = worktree_orchestrator.get_pending_tasks()
        for req in pending:
            assert "do NOT create or switch branches" in req.prompt
            assert req.worktree_dir in req.prompt

    def test_start_without_cwd_skips_worktrees(self, worktree_orchestrator):
        """start() without cwd doesn't create worktrees (backward compat)."""
        worktree_orchestrator.start()
        status = worktree_orchestrator.get_status()
        for task_state in status["tasks"].values():
            assert task_state["worktree_dir"] == ""


@pytest.fixture
def tiered_manifest_path(tmp_path):
    """Manifest with explicit per-task tiers. max_retries=1 keeps
    escalation tests short: one 'retrying', then the escalation decision."""
    content = """\
project: tiered-project
base_branch: main
max_retries: 1
tasks:
  - name: leaf
    description: "Mechanical leaf task"
    target_dir: src/leaf
    test_dir: tests/test_leaf
    model: haiku
    escalation: sonnet
  - name: core
    description: "Locally-reasoned task"
    target_dir: src/core
    test_dir: tests/test_core
    model: sonnet
"""
    path = tmp_path / "tiered.yaml"
    path.write_text(content)
    return str(path)


@pytest.fixture
def tiered_orchestrator(tmp_state_dir, tiered_manifest_path):
    orch = ParallelOrchestrator()
    orch.load_manifest(tiered_manifest_path)
    return orch


class TestTierPassthrough:
    def test_spawn_requests_carry_manifest_model(self, tiered_orchestrator):
        tiered_orchestrator.start()
        pending = {r.task_name: r for r in tiered_orchestrator.get_pending_tasks()}
        assert pending["leaf"].model == "haiku"
        assert pending["core"].model == "sonnet"

    def test_state_model_overrides_manifest_model(self, tiered_orchestrator):
        """After a tier bump, state['model'] is the current tier."""
        tiered_orchestrator.start()
        tiered_orchestrator._state.update_task("leaf", model="sonnet")
        tiered_orchestrator._state.save()
        pending = {r.task_name: r for r in tiered_orchestrator.get_pending_tasks()}
        assert pending["leaf"].model == "sonnet"


class TestEscalation:
    def test_escalates_after_max_retries(self, tiered_orchestrator):
        tiered_orchestrator.start()
        assert tiered_orchestrator.record_completion(
            "leaf", success=False, error="red"
        ) == "retrying"
        result = tiered_orchestrator.record_completion(
            "leaf", success=False, error="still red"
        )
        assert result == "escalated"
        task_state = tiered_orchestrator.get_status()["tasks"]["leaf"]
        assert task_state["status"] == "pending"
        assert task_state["model"] == "sonnet"
        assert task_state["retries"] == 0
        assert task_state["escalated_from"] == "haiku"

    def test_escalated_task_redispatches_at_higher_tier(self, tiered_orchestrator):
        tiered_orchestrator.start()
        tiered_orchestrator.record_completion("leaf", success=False, error="e")
        tiered_orchestrator.record_completion("leaf", success=False, error="e")
        pending = {r.task_name: r for r in tiered_orchestrator.get_pending_tasks()}
        assert pending["leaf"].model == "sonnet"

    def test_fails_for_good_at_escalation_tier(self, tiered_orchestrator):
        tiered_orchestrator.start()
        tiered_orchestrator.record_completion("leaf", success=False, error="e1")
        assert tiered_orchestrator.record_completion(
            "leaf", success=False, error="e2"
        ) == "escalated"
        assert tiered_orchestrator.record_completion(
            "leaf", success=False, error="e3"
        ) == "retrying"
        result = tiered_orchestrator.record_completion(
            "leaf", success=False, error="e4"
        )
        assert result == "failed"
        task_state = tiered_orchestrator.get_status()["tasks"]["leaf"]
        assert task_state["status"] == "failed"

    def test_fable_escalation_fails_without_redispatch(self, tiered_orchestrator):
        # core has escalation fable -> no spawnable higher tier, so
        # exhausted retries mean failed (skill routes to escalate phase,
        # where Fable handles it personally).
        tiered_orchestrator.start()
        assert tiered_orchestrator.record_completion(
            "core", success=False, error="e1"
        ) == "retrying"
        result = tiered_orchestrator.record_completion(
            "core", success=False, error="e2"
        )
        assert result == "failed"

    def test_escalation_does_not_poison_dependents(self, tmp_path, tmp_state_dir):
        """Escalation must NOT propagate failure to dependent tasks.

        When a task is escalated (bumped to higher tier), _propagate_failure
        is NOT called.  A downstream task that depends on the escalated task
        must remain in its normal waiting state (status "pending"), not
        acquire the "failed" status that _propagate_failure would set.
        """
        manifest_yaml = """\
project: esc-dep-test
base_branch: main
max_retries: 1
tasks:
  - name: leaf
    description: leaf task
    target_dir: src/leaf
    test_dir: tests/test_leaf
    model: haiku
    escalation: sonnet
  - name: dep
    description: dependent task
    target_dir: src/dep
    test_dir: tests/test_dep
    max_retries: 1
    depends_on:
      - leaf
"""
        path = tmp_path / "esc-dep.yaml"
        path.write_text(manifest_yaml)
        orch = ParallelOrchestrator()
        orch.load_manifest(str(path))
        orch.start()
        # Two failures drive leaf to escalation (max_retries=1).
        orch.record_completion("leaf", success=False, error="e1")
        result = orch.record_completion("leaf", success=False, error="e2")
        assert result == "escalated"
        # dep must NOT be failed - escalation skips _propagate_failure.
        dep_state = orch.get_status()["tasks"]["dep"]
        assert dep_state["status"] != "failed"
        assert dep_state["status"] == "pending"
