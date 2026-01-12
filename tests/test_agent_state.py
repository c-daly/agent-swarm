"""Tests for lib/agent_state.py module."""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import agent_state  # noqa: E402
from agent_state import (  # noqa: E402
    get_agent_id,
    get_state_file,
    load_state,
    save_state,
    cleanup_agent_state,
)


@pytest.fixture
def temp_state_dir(tmp_path):
    """Use a temporary directory for state files."""
    with patch.object(agent_state, "STATE_DIR", tmp_path):
        yield tmp_path


class TestGetAgentId:
    def test_returns_main_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CLAUDE_AGENT_ID", None)
            assert get_agent_id() == "main"

    def test_returns_env_value_when_set(self):
        with patch.dict(os.environ, {"CLAUDE_AGENT_ID": "subagent-abc123"}):
            assert get_agent_id() == "subagent-abc123"


class TestGetStateFile:
    def test_main_agent_uses_session_json(self, temp_state_dir):
        result = get_state_file("main")
        assert result == temp_state_dir / "session.json"

    def test_subagent_uses_prefixed_file(self, temp_state_dir):
        result = get_state_file("worker-123")
        assert result == temp_state_dir / "session.worker-123.json"

    def test_none_uses_get_agent_id(self, temp_state_dir):
        with patch.dict(os.environ, {"CLAUDE_AGENT_ID": "test-agent"}):
            result = get_state_file(None)
            assert result == temp_state_dir / "session.test-agent.json"


class TestLoadState:
    def test_returns_empty_dict_when_file_missing(self, temp_state_dir):
        # temp_state_dir fixture activates the patch
        assert temp_state_dir.exists() or True  # Ensure fixture is used
        result = load_state("nonexistent")
        assert result == {}

    def test_returns_parsed_json(self, temp_state_dir):
        state_file = temp_state_dir / "session.test.json"
        temp_state_dir.mkdir(parents=True, exist_ok=True)
        state_file.write_text('{"phase": "implement", "count": 5}')
        result = load_state("test")
        assert result == {"phase": "implement", "count": 5}

    def test_returns_empty_dict_on_invalid_json(self, temp_state_dir):
        state_file = temp_state_dir / "session.bad.json"
        temp_state_dir.mkdir(parents=True, exist_ok=True)
        state_file.write_text("not valid json {")
        result = load_state("bad")
        assert result == {}


class TestSaveState:
    def test_creates_directory_and_file(self, temp_state_dir):
        save_state({"key": "value"}, "new-agent")
        state_file = temp_state_dir / "session.new-agent.json"
        assert state_file.exists()
        assert json.loads(state_file.read_text()) == {"key": "value"}

    def test_overwrites_existing_file(self, temp_state_dir):
        state_file = temp_state_dir / "session.update.json"
        temp_state_dir.mkdir(parents=True, exist_ok=True)
        state_file.write_text('{"old": "data"}')

        save_state({"new": "data"}, "update")
        assert json.loads(state_file.read_text()) == {"new": "data"}




class TestFileLocking:
    """Tests for file locking behavior - G3 race condition fix."""

    def test_lock_file_created_on_save(self, temp_state_dir):
        """Save should create a .lock file alongside the state file."""
        save_state({"test": "data"})
        state_file = get_state_file()
        lock_file = state_file.parent / (state_file.name + ".lock")

        assert lock_file.exists(), "Lock file should be created"

    def test_concurrent_writes_no_corruption(self, temp_state_dir):
        """Multiple concurrent writes should not corrupt state."""
        import threading

        errors = []
        iterations = 50

        def increment_counter(thread_id):
            for _ in range(iterations):
                try:
                    def updater(state):
                        state["counter"] = state.get("counter", 0) + 1
                        state[f"thread_{thread_id}"] = True
                        return state
                    agent_state.update_state(updater)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=increment_counter, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent writes caused errors: {errors}"

        final_state = load_state()
        expected = iterations * 5  # 5 threads * 50 iterations each
        assert final_state.get("counter") == expected, \
            f"Counter should be {expected}, got {final_state.get('counter')} (lost updates without locking)"

    def test_concurrent_reads_safe(self, temp_state_dir):
        """Multiple concurrent reads should not block or error."""
        import threading

        save_state({"data": "test", "items": list(range(100))})

        results = []
        errors = []

        def read_state(thread_id):
            for _ in range(20):
                try:
                    state = load_state()
                    results.append((thread_id, state.get("data")))
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=read_state, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent reads caused errors: {errors}"
        assert len(results) == 100, f"Expected 100 reads, got {len(results)}"
        assert all(r[1] == "test" for r in results), "All reads should return correct data"

    def test_update_state_handles_invalid_json(self, temp_state_dir):
        """update_state should handle corrupted JSON gracefully."""
        state_file = get_state_file()
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("not valid json {{{")

        def updater(state):
            state["fixed"] = True
            return state

        result = agent_state.update_state(updater)
        assert result == {"fixed": True}, "Should start fresh on invalid JSON"


class TestCleanupAgentState:
    def test_refuses_to_cleanup_main(self, temp_state_dir):
        # Create main session file
        temp_state_dir.mkdir(parents=True, exist_ok=True)
        main_file = temp_state_dir / "session.json"
        main_file.write_text('{"protected": true}')

        result = cleanup_agent_state("main")
        assert result is False
        assert main_file.exists()

    def test_removes_subagent_state_file(self, temp_state_dir):
        temp_state_dir.mkdir(parents=True, exist_ok=True)
        state_file = temp_state_dir / "session.worker-456.json"
        state_file.write_text('{"temp": "data"}')

        result = cleanup_agent_state("worker-456")
        assert result is True
        assert not state_file.exists()

    def test_returns_false_when_file_missing(self, temp_state_dir):
        assert temp_state_dir.exists() or True  # Ensure fixture is used
        result = cleanup_agent_state("nonexistent-agent")
        assert result is False
