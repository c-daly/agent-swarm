"""Tests for OrchestrationState."""

import json
import os

from lib.orchestration_state import OrchestrationState


class TestOrchestrationStateBasics:
    def test_new_state_does_not_exist(self, tmp_state_dir):
        state = OrchestrationState("test-project")
        assert not state.exists()

    def test_save_creates_file(self, tmp_state_dir):
        state = OrchestrationState("test-project")
        state.set("phase", "init")
        state.save()
        assert state.exists()

    def test_round_trip(self, tmp_state_dir):
        state = OrchestrationState("test-project")
        state.set("phase", "spawning")
        state.set("tasks", {"stack": {"status": "pending"}})
        state.save()

        loaded = OrchestrationState("test-project")
        loaded.load()
        assert loaded.get("phase") == "spawning"
        assert loaded.get("tasks") == {"stack": {"status": "pending"}}

    def test_get_missing_key_returns_default(self, tmp_state_dir):
        state = OrchestrationState("test-project")
        assert state.get("missing") is None
        assert state.get("missing", "fallback") == "fallback"

    def test_clear_removes_file(self, tmp_state_dir):
        state = OrchestrationState("test-project")
        state.set("phase", "init")
        state.save()
        assert state.exists()

        state.clear()
        assert not state.exists()

    def test_clear_nonexistent_is_noop(self, tmp_state_dir):
        state = OrchestrationState("test-project")
        state.clear()  # Should not raise


class TestOrchestrationStateNested:
    def test_set_nested_key(self, tmp_state_dir):
        state = OrchestrationState("test-project")
        state.set("tasks", {})
        state.set("tasks.stack", {"status": "pending"})
        assert state.get("tasks") == {"stack": {"status": "pending"}}

    def test_get_nested_key(self, tmp_state_dir):
        state = OrchestrationState("test-project")
        state.set("tasks", {"stack": {"status": "running", "retries": 2}})
        assert state.get("tasks.stack.status") == "running"
        assert state.get("tasks.stack.retries") == 2

    def test_get_nested_missing_returns_default(self, tmp_state_dir):
        state = OrchestrationState("test-project")
        state.set("tasks", {})
        assert state.get("tasks.stack.status", "unknown") == "unknown"


class TestUpdateTask:
    def test_update_task_creates_entry(self, tmp_state_dir):
        state = OrchestrationState("test-project")
        state.update_task("stack", status="spawned", worker_id="w1")
        tasks = state.get("tasks")
        assert tasks["stack"]["status"] == "spawned"
        assert tasks["stack"]["worker_id"] == "w1"

    def test_update_task_merges(self, tmp_state_dir):
        state = OrchestrationState("test-project")
        state.update_task("stack", status="spawned")
        state.update_task("stack", retries=1)
        task = state.get("tasks")["stack"]
        assert task["status"] == "spawned"
        assert task["retries"] == 1

    def test_update_task_overwrites_field(self, tmp_state_dir):
        state = OrchestrationState("test-project")
        state.update_task("stack", status="spawned")
        state.update_task("stack", status="completed")
        assert state.get("tasks")["stack"]["status"] == "completed"


class TestAtomicWrite:
    def test_atomic_write_produces_valid_json(self, tmp_state_dir):
        state = OrchestrationState("test-project")
        state.set("data", list(range(100)))
        state.save()

        path = tmp_state_dir / "test-project.json"
        data = json.loads(path.read_text())
        assert data["data"] == list(range(100))

    def test_state_file_path_uses_env_var(self, tmp_state_dir):
        state = OrchestrationState("myproj")
        state.set("x", 1)
        state.save()

        expected = tmp_state_dir / "myproj.json"
        assert expected.exists()


class TestEnvOverride:
    def test_default_state_dir_without_env(self, tmp_path):
        old = os.environ.pop("ORCHESTRATION_STATE_DIR", None)
        try:
            state = OrchestrationState("test-project")
            # Should use plugin_root/.state/
            assert ".state" in str(state._state_path)
        finally:
            if old:
                os.environ["ORCHESTRATION_STATE_DIR"] = old
