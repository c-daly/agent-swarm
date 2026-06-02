#!/usr/bin/env python3
"""Tests for the core orchestrator."""

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from lib.controller import Controller, PROTECTED_KEYS, _is_protected_key
from lib.errors import (
    PermissionDeniedError,
    RouterError,
    WorkflowError,
)


# --- Fixtures ---


_PERM_CONFIG = {
    "global": {
        "allowed": ["native__*", "router__*", "workflow__*", "serena__*"],
        "blocked": [],
        "superblocked": [],
    },
}

_BACKEND_CONFIG = {
    "serena": {"command": ["echo"], "tool_prefix": "serena"},
}


@dataclass
class MockPhaseConfig:
    """Lightweight stand-in for PhaseConfig."""
    name: str
    checkpoint: bool = False


@dataclass
class MockWorkflowConfig:
    """Lightweight stand-in for WorkflowConfig."""
    name: str
    initial_phase: str
    terminal_phase: str
    phases: dict  # name -> MockPhaseConfig
    transitions: dict  # phase -> set of targets


def _make_iterate_config():
    """Build a mock iterate workflow config for testing."""
    return MockWorkflowConfig(
        name="iterate",
        initial_phase="test_writing",
        terminal_phase="complete",
        phases={
            "test_writing": MockPhaseConfig(name="test_writing", checkpoint=False),
            "implement": MockPhaseConfig(name="implement", checkpoint=False),
            "test": MockPhaseConfig(name="test", checkpoint=True),
            "review": MockPhaseConfig(name="review", checkpoint=True),
        },
        transitions={
            "test_writing": {"implement"},
            "implement": {"test"},
            "test": {"implement", "review"},
            "review": {"implement", "complete"},
        },
    )


@pytest.fixture
def ctrl(tmp_path):
    """Create a Controller with minimal config (no workflow configs)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "permissions.yaml").write_text(yaml.dump(_PERM_CONFIG))
    (config_dir / "backends.json").write_text(json.dumps(_BACKEND_CONFIG))

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    c = Controller(config_dir=config_dir, data_dir=data_dir)
    yield c
    c.shutdown()


@pytest.fixture
def ctrl_with_config(tmp_path):
    """Create a Controller with mock workflow configs."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "permissions.yaml").write_text(yaml.dump(_PERM_CONFIG))
    (config_dir / "backends.json").write_text(json.dumps(_BACKEND_CONFIG))

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    wf_configs = {"iterate": _make_iterate_config()}
    c = Controller(
        config_dir=config_dir,
        data_dir=data_dir,
        workflow_configs=wf_configs,
    )
    yield c
    c.shutdown()


# --- Native operations ---


class TestNativeReadFile:
    def test_read_existing_file(self, ctrl, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        result = ctrl.handle_call("native__read_file", {"file_path": str(f)})
        assert result["line_count"] == 3
        assert "line1" in result["content"]

    def test_read_missing_file(self, ctrl):
        result = ctrl.handle_call("native__read_file", {"file_path": "/nonexistent"})
        assert result.get("isError") is True
        assert "not found" in result["error"].lower()

    def test_read_with_offset_and_limit(self, ctrl, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("\n".join(f"line{i}" for i in range(100)))
        result = ctrl.handle_call(
            "native__read_file", {"file_path": str(f), "offset": 10, "limit": 5}
        )
        assert result["line_count"] == 5
        assert result["truncated"] is True


class TestNativeWriteFile:
    def test_write_creates_file(self, ctrl, tmp_path):
        f = tmp_path / "output.txt"
        result = ctrl.handle_call(
            "native__write_file", {"file_path": str(f), "content": "hello"}
        )
        assert "written" in result["result"].lower()
        assert f.read_text() == "hello"

    def test_write_creates_parent_dirs(self, ctrl, tmp_path):
        f = tmp_path / "a" / "b" / "c.txt"
        ctrl.handle_call(
            "native__write_file", {"file_path": str(f), "content": "nested"}
        )
        assert f.read_text() == "nested"


class TestNativeEditFile:
    def test_edit_replaces_text(self, ctrl, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("hello world")
        result = ctrl.handle_call(
            "native__edit_file",
            {"file_path": str(f), "old_string": "hello", "new_string": "goodbye"},
        )
        assert result["replacements"] == 1
        assert f.read_text() == "goodbye world"

    def test_edit_not_found(self, ctrl, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("hello")
        result = ctrl.handle_call(
            "native__edit_file",
            {"file_path": str(f), "old_string": "xyz", "new_string": "abc"},
        )
        assert result.get("isError") is True

    def test_edit_multiple_without_replace_all(self, ctrl, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("aaa bbb aaa")
        result = ctrl.handle_call(
            "native__edit_file",
            {"file_path": str(f), "old_string": "aaa", "new_string": "ccc"},
        )
        assert result.get("isError") is True
        assert "Multiple" in result["error"]

    def test_edit_replace_all(self, ctrl, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("aaa bbb aaa")
        result = ctrl.handle_call(
            "native__edit_file",
            {
                "file_path": str(f),
                "old_string": "aaa",
                "new_string": "ccc",
                "replace_all": True,
            },
        )
        assert result["replacements"] == 2
        assert f.read_text() == "ccc bbb ccc"


class TestNativeBash:
    def test_bash_echo(self, ctrl):
        result = ctrl.handle_call(
            "native__bash", {"command": "echo hello"}
        )
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]

    def test_bash_nonzero_exit(self, ctrl):
        result = ctrl.handle_call(
            "native__bash", {"command": "exit 42"}
        )
        assert result["exit_code"] == 42

    def test_bash_timeout(self, ctrl):
        result = ctrl.handle_call(
            "native__bash", {"command": "sleep 10", "timeout": 1}
        )
        assert result["timed_out"] is True


class TestNativeGlob:
    def test_glob_finds_files(self, ctrl, tmp_path):
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "c.txt").write_text("")
        result = ctrl.handle_call(
            "native__glob", {"pattern": "*.py", "path": str(tmp_path)}
        )
        assert len(result["files"]) == 2


# --- Router operations ---


class TestRouterOps:
    def test_ping(self, ctrl):
        result = ctrl.handle_call("router__ping", {})
        assert result["status"] == "ok"

    def test_register_and_get_agent(self, ctrl):
        result = ctrl.handle_call(
            "router__register_agent",
            {"agent_id": "a1", "agent_type": "explorer", "roles": ["read_only"]},
        )
        assert result["agent_id"] == "a1"
        assert result["agent_type"] == "explorer"

    def test_register_agent_creates_state(self, ctrl):
        """register_agent should create agent state entry."""
        result = ctrl.handle_call(
            "router__register_agent",
            {"agent_id": "sub-test1", "agent_type": "implementer"},
        )
        assert result["agent_id"] == "sub-test1"
        # Agent state should be recorded
        state = ctrl.handle_call(
            "workflow__agent_get_state", {"agent_id": "sub-test1"}
        )
        assert state is not None
        assert state["agent_type"] == "implementer"
        assert state["status"] == "registered"
        assert "registered_at" in state

    def test_update_agent_phase_accepts_workflow_id(self, ctrl):
        """update_agent_phase honors the conventional `workflow_id` key (not just
        the legacy `workflow`) and syncs the display state -- regression for the
        bug that left dispatched workers unbound (blank workflow/phase)."""
        ctrl.handle_call(
            "router__register_agent",
            {"agent_id": "w1", "agent_type": "implementer"},
        )
        ctrl.handle_call(
            "router__update_agent_phase",
            {"agent_id": "w1", "workflow_id": "iterate:w1", "phase": "implement"},
        )
        # permission binding (what drives phase gating) is updated
        agent = ctrl.permissions.get_agent("w1")
        assert agent.workflow == "iterate:w1"
        assert agent.phase == "implement"
        # display state is kept in sync so agent_get_state is truthful
        state = ctrl.handle_call("workflow__agent_get_state", {"agent_id": "w1"})
        assert state["workflow_id"] == "iterate:w1"
        assert state["phase"] == "implement"

    def test_update_agent_phase_legacy_workflow_key(self, ctrl):
        """The legacy `workflow` key still binds (session-start used it)."""
        ctrl.handle_call(
            "router__register_agent",
            {"agent_id": "w2", "agent_type": "implementer"},
        )
        ctrl.handle_call(
            "router__update_agent_phase",
            {"agent_id": "w2", "workflow": "iterate", "phase": "test"},
        )
        assert ctrl.permissions.get_agent("w2").workflow == "iterate"
        assert ctrl.permissions.get_agent("w2").phase == "test"

    def test_register_agent_without_workflow_has_no_phase(self, ctrl):
        """register_agent without workflow_id should have no phase."""
        result = ctrl.handle_call(
            "router__register_agent",
            {"agent_id": "sub-expl1", "agent_type": "explorer"},
        )
        assert result["phase"] is None
        assert result.get("workflow_id") is None

    def test_register_agent_with_workflow_sets_phase(self, ctrl_with_config):
        """register_agent with workflow_id should set initial phase."""
        # Start the iterate workflow first
        ctrl_with_config.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "iterate", "initial_state": {}},
        )
        result = ctrl_with_config.handle_call(
            "router__register_agent",
            {"agent_id": "sub-impl1", "agent_type": "implementer", "workflow_id": "iterate"},
        )
        assert result["workflow_id"] == "iterate"
        assert result["phase"] == "test_writing"  # initial_phase from config

    @pytest.mark.skip(reason="Briefing removed from register_agent return to fix summarization bug. Briefing now injected by _native_task at dispatch time.")
    def test_register_agent_returns_briefing(self, ctrl):
        """register_agent should return an assembled briefing."""
        result = ctrl.handle_call(
            "router__register_agent",
            {"agent_id": "sub-b1", "agent_type": "implementer"},
        )
        assert "briefing" in result
        briefing = result["briefing"]
        # Must contain the tool table (critical for agents to function)
        assert "mcp-call" in briefing
        # Must contain some role-specific content
        assert "implementer" in briefing.lower() or "implement" in briefing.lower()

    def test_unknown_router_tool(self, ctrl):
        with pytest.raises(RouterError, match="Unknown router tool"):
            ctrl.handle_call("router__nonexistent", {})


# --- Workflow state ---


class TestWorkflowState:
    def test_start_adds_daemon_managed_keys(self, ctrl):
        """Starting a workflow (no config) strips protected keys and adds managed ones."""
        state = ctrl.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "wf1", "initial_state": {"custom": "data", "phase": "sneaky"}},
        )
        # Protected key "phase" stripped, daemon sets it to ""
        assert state["phase"] == ""
        # Custom key preserved
        assert state["custom"] == "data"
        # Daemon-managed keys added
        assert "started_at" in state
        assert state["active_agents"] == {}

    def test_start_with_config_sets_initial_phase(self, ctrl_with_config):
        """Starting a configured workflow uses config's initial_phase."""
        state = ctrl_with_config.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "iterate", "initial_state": {"custom": 1}},
        )
        assert state["phase"] == "test_writing"
        assert state["custom"] == 1
        assert "started_at" in state

    def test_start_unknown_workflow_with_config_raises(self, ctrl_with_config):
        """When configs are loaded, unknown workflow_id is rejected."""
        with pytest.raises(WorkflowError, match="Unknown workflow"):
            ctrl_with_config.handle_call(
                "workflow__workflow_start",
                {"workflow_id": "nonexistent", "initial_state": {}},
            )

    def test_start_duplicate_raises(self, ctrl):
        ctrl.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "wf1", "initial_state": {}},
        )
        with pytest.raises(WorkflowError, match="already exists"):
            ctrl.handle_call(
                "workflow__workflow_start",
                {"workflow_id": "wf1", "initial_state": {}},
            )

    def test_stop(self, ctrl):
        ctrl.handle_call(
            "workflow__workflow_start", {"workflow_id": "wf1"}
        )
        result = ctrl.handle_call(
            "workflow__workflow_stop", {"workflow_id": "wf1"}
        )
        assert result is True
        assert ctrl.handle_call(
            "workflow__workflow_is_active", {"workflow_id": "wf1"}
        ) is False

    def test_stop_missing_raises(self, ctrl):
        with pytest.raises(WorkflowError, match="not found"):
            ctrl.handle_call(
                "workflow__workflow_stop", {"workflow_id": "ghost"}
            )

    def test_set_and_get_value_unprotected(self, ctrl):
        """set_value works for non-protected keys."""
        ctrl.handle_call(
            "workflow__workflow_start", {"workflow_id": "wf1"}
        )
        ctrl.handle_call(
            "workflow__workflow_set_value",
            {"workflow_id": "wf1", "key": "my_data", "value": "test"},
        )
        val = ctrl.handle_call(
            "workflow__workflow_get_value",
            {"workflow_id": "wf1", "key": "my_data"},
        )
        assert val == "test"

    def test_is_active(self, ctrl):
        assert ctrl.handle_call(
            "workflow__workflow_is_active", {"workflow_id": "wf1"}
        ) is False
        ctrl.handle_call(
            "workflow__workflow_start", {"workflow_id": "wf1"}
        )
        assert ctrl.handle_call(
            "workflow__workflow_is_active", {"workflow_id": "wf1"}
        ) is True

    def test_returns_are_deep_copies(self, ctrl):
        ctrl.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "wf1", "initial_state": {"items": [1, 2]}},
        )
        state1 = ctrl.handle_call(
            "workflow__workflow_get_state", {"workflow_id": "wf1"}
        )
        state1["items"].append(999)
        state2 = ctrl.handle_call(
            "workflow__workflow_get_state", {"workflow_id": "wf1"}
        )
        assert 999 not in state2["items"]

    def test_set_state_and_update_removed_from_dispatch(self, ctrl):
        """workflow_set_state and workflow_update are no longer in dispatch."""
        ctrl.handle_call(
            "workflow__workflow_start", {"workflow_id": "wf1"}
        )
        with pytest.raises(RouterError, match="Unknown workflow tool"):
            ctrl.handle_call(
                "workflow__workflow_set_state",
                {"workflow_id": "wf1", "state": {"x": 1}},
            )
        with pytest.raises(RouterError, match="Unknown workflow tool"):
            ctrl.handle_call(
                "workflow__workflow_update",
                {"workflow_id": "wf1", "updates": {"y": 2}},
            )

    def test_internal_set_state_still_works(self, ctrl):
        """__wf_set_state is still callable internally (daemon use)."""
        ctrl.handle_call(
            "workflow__workflow_start", {"workflow_id": "wf1"}
        )
        result = ctrl._Controller__wf_set_state({"workflow_id": "wf1", "state": {"x": 1}})
        assert result == {"x": 1}

    def test_internal_update_still_works(self, ctrl):
        """__wf_update is still callable internally (daemon use)."""
        ctrl.handle_call(
            "workflow__workflow_start", {"workflow_id": "wf1"}
        )
        result = ctrl._Controller__wf_update({"workflow_id": "wf1", "updates": {"extra": 99}})
        assert result["extra"] == 99


# --- Protected keys ---


class TestProtectedKeys:
    def test_is_protected_key_exact_matches(self):
        for key in PROTECTED_KEYS:
            assert _is_protected_key(key), f"{key} should be protected"

    def test_is_protected_key_checkpoint_pattern(self):
        assert _is_protected_key("test_checkpoint_passed")
        assert _is_protected_key("review_checkpoint_passed")
        assert _is_protected_key("x_checkpoint_passed")

    def test_is_not_protected(self):
        assert not _is_protected_key("my_data")
        assert not _is_protected_key("custom_key")
        assert not _is_protected_key("checkpoint_note")  # doesn't end with _checkpoint_passed

    def test_set_value_rejects_phase(self, ctrl):
        ctrl.handle_call(
            "workflow__workflow_start", {"workflow_id": "wf1"}
        )
        with pytest.raises(WorkflowError, match="Protected key 'phase'"):
            ctrl.handle_call(
                "workflow__workflow_set_value",
                {"workflow_id": "wf1", "key": "phase", "value": "hack"},
            )

    def test_set_value_rejects_started_at(self, ctrl):
        ctrl.handle_call(
            "workflow__workflow_start", {"workflow_id": "wf1"}
        )
        with pytest.raises(WorkflowError, match="Protected key"):
            ctrl.handle_call(
                "workflow__workflow_set_value",
                {"workflow_id": "wf1", "key": "started_at", "value": "fake"},
            )

    def test_set_value_rejects_checkpoint_passed(self, ctrl):
        ctrl.handle_call(
            "workflow__workflow_start", {"workflow_id": "wf1"}
        )
        with pytest.raises(WorkflowError, match="Protected key"):
            ctrl.handle_call(
                "workflow__workflow_set_value",
                {"workflow_id": "wf1", "key": "test_checkpoint_passed", "value": "2025-01-01T00:00:00+00:00"},
            )

    def test_start_strips_all_protected_keys(self, ctrl):
        state = ctrl.handle_call(
            "workflow__workflow_start",
            {
                "workflow_id": "wf1",
                "initial_state": {
                    "phase": "sneaky",
                    "started_at": "fake",
                    "active_agents": {"bad": True},
                    "agent_id": "evil",
                    "test_checkpoint_passed": "2025-01-01T00:00:00+00:00",
                    "legit_key": "kept",
                },
            },
        )
        # Protected keys set by daemon, not user values
        assert state["phase"] == ""  # daemon default (no config)
        assert state["started_at"] != "fake"
        assert state["active_agents"] == {}  # daemon default
        assert "agent_id" not in state  # stripped, not re-added by daemon
        assert "test_checkpoint_passed" not in state  # stripped
        # Non-protected key preserved
        assert state["legit_key"] == "kept"


# --- Phase transitions ---


class TestAdvancePhase:
    def test_advance_without_config(self, ctrl):
        """Without config, any transition is allowed."""
        ctrl.handle_call(
            "workflow__workflow_start", {"workflow_id": "wf1"}
        )
        # Directly set phase internally for testing
        ctrl._Controller__wf_set_state({"workflow_id": "wf1", "state": {"phase": "a"}})
        result = ctrl.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "wf1", "target_phase": "b"},
        )
        assert result == {"status": "advanced", "phase": "b"}

    def test_advance_valid_transition(self, ctrl_with_config):
        ctrl_with_config.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "iterate", "initial_state": {}},
        )
        # test_writing -> implement is valid
        result = ctrl_with_config.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "iterate", "target_phase": "implement"},
        )
        assert result == {"status": "advanced", "phase": "implement"}

    def test_wf_start_accepts_per_instance_id(self, ctrl_with_config):
        """A per-instance workflow id (iterate:<x>) resolves to the base iterate
        config. Regression: the _wf_config :suffix fallback was once dropped,
        which made per-instance _wf_start raise 'Unknown workflow'."""
        result = ctrl_with_config.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "iterate:sub-xyz", "initial_state": {}},
        )
        assert result["phase"] == "test_writing"
        # _wf_config resolves the instance id to the same base config object
        assert (
            ctrl_with_config._wf_config("iterate:sub-xyz")
            is ctrl_with_config._wf_config("iterate")
        )

    def test_advance_invalid_transition(self, ctrl_with_config):
        ctrl_with_config.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "iterate", "initial_state": {}},
        )
        # test_writing -> review is NOT valid
        with pytest.raises(WorkflowError, match="Invalid transition"):
            ctrl_with_config.handle_call(
                "workflow__workflow_advance_phase",
                {"workflow_id": "iterate", "target_phase": "review"},
            )

    def test_advance_blocked_by_checkpoint(self, ctrl_with_config):
        ctrl_with_config.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "iterate", "initial_state": {}},
        )
        # Move to implement, then test
        ctrl_with_config.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "iterate", "target_phase": "implement"},
        )
        ctrl_with_config.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "iterate", "target_phase": "test"},
        )
        # test -> review requires checkpoint
        with pytest.raises(WorkflowError, match="Checkpoint not passed"):
            ctrl_with_config.handle_call(
                "workflow__workflow_advance_phase",
                {"workflow_id": "iterate", "target_phase": "review"},
            )

    def test_checkpoint_does_not_block_failure_loop(self, ctrl_with_config):
        """The TDD failure loop (test -> implement) must stay open on a red
        suite even though the test checkpoint is unpassed -- the checkpoint
        gates only forward progress (test -> review)."""
        ctrl_with_config.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "iterate", "initial_state": {}},
        )
        for target in ("implement", "test"):
            ctrl_with_config.handle_call(
                "workflow__workflow_advance_phase",
                {"workflow_id": "iterate", "target_phase": target},
            )
        # test -> implement (kickback) without the checkpoint: allowed
        result = ctrl_with_config.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "iterate", "target_phase": "implement"},
        )
        assert result == {"status": "advanced", "phase": "implement"}

    def test_advance_after_checkpoint_passed(self, ctrl_with_config):
        ctrl_with_config.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "iterate", "initial_state": {}},
        )
        # Navigate: test_writing -> implement -> test
        ctrl_with_config.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "iterate", "target_phase": "implement"},
        )
        ctrl_with_config.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "iterate", "target_phase": "test"},
        )
        # Pass checkpoint
        ctrl_with_config.handle_call(
            "workflow__workflow_pass_checkpoint",
            {"workflow_id": "iterate"},
        )
        # Now test -> review should work
        result = ctrl_with_config.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "iterate", "target_phase": "review"},
        )
        assert result == {"status": "advanced", "phase": "review"}

    def test_advance_to_terminal_sets_completed_at(self, ctrl_with_config):
        ctrl_with_config.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "iterate", "initial_state": {}},
        )
        # Navigate: test_writing -> implement -> test -> review -> complete
        ctrl_with_config.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "iterate", "target_phase": "implement"},
        )
        ctrl_with_config.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "iterate", "target_phase": "test"},
        )
        ctrl_with_config.handle_call(
            "workflow__workflow_pass_checkpoint",
            {"workflow_id": "iterate"},
        )
        ctrl_with_config.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "iterate", "target_phase": "review"},
        )
        ctrl_with_config.handle_call(
            "workflow__workflow_pass_checkpoint",
            {"workflow_id": "iterate"},
        )
        result = ctrl_with_config.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "iterate", "target_phase": "complete"},
        )
        assert result == {"status": "advanced", "phase": "complete"}
        # State should have completed_at
        state = ctrl_with_config.handle_call(
            "workflow__workflow_get_state", {"workflow_id": "iterate"}
        )
        assert "completed_at" in state
        # is_active should be False (terminal phase)
        assert ctrl_with_config.handle_call(
            "workflow__workflow_is_active", {"workflow_id": "iterate"}
        ) is False

    def test_advance_missing_workflow(self, ctrl):
        with pytest.raises(WorkflowError, match="not found"):
            ctrl.handle_call(
                "workflow__workflow_advance_phase",
                {"workflow_id": "ghost", "target_phase": "x"},
            )


# --- Pass checkpoint ---


class TestPassCheckpoint:
    def test_pass_checkpoint_without_config(self, ctrl):
        """Without config, checkpoint sets the key unconditionally."""
        ctrl.handle_call(
            "workflow__workflow_start", {"workflow_id": "wf1"}
        )
        ctrl._Controller__wf_set_state({"workflow_id": "wf1", "state": {"phase": "test"}})
        result = ctrl.handle_call(
            "workflow__workflow_pass_checkpoint",
            {"workflow_id": "wf1"},
        )
        assert result == {"status": "checkpoint_passed", "phase": "test"}
        state = ctrl.handle_call(
            "workflow__workflow_get_state", {"workflow_id": "wf1"}
        )
        assert isinstance(state["test_checkpoint_passed"], str)  # ISO timestamp

    def test_pass_checkpoint_with_config(self, ctrl_with_config):
        ctrl_with_config.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "iterate", "initial_state": {}},
        )
        # Navigate to test phase (which has checkpoint: true)
        ctrl_with_config.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "iterate", "target_phase": "implement"},
        )
        ctrl_with_config.handle_call(
            "workflow__workflow_advance_phase",
            {"workflow_id": "iterate", "target_phase": "test"},
        )
        result = ctrl_with_config.handle_call(
            "workflow__workflow_pass_checkpoint",
            {"workflow_id": "iterate"},
        )
        assert result == {"status": "checkpoint_passed", "phase": "test"}

    def test_pass_checkpoint_rejects_non_checkpoint_phase(self, ctrl_with_config):
        """Phase without checkpoint: true rejects pass_checkpoint."""
        ctrl_with_config.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "iterate", "initial_state": {}},
        )
        # test_writing has checkpoint: false
        with pytest.raises(WorkflowError, match="does not have a checkpoint"):
            ctrl_with_config.handle_call(
                "workflow__workflow_pass_checkpoint",
                {"workflow_id": "iterate"},
            )

    def test_pass_checkpoint_no_phase(self, ctrl):
        """Empty phase raises error."""
        ctrl.handle_call(
            "workflow__workflow_start", {"workflow_id": "wf1"}
        )
        # phase is "" by default (no config)
        with pytest.raises(WorkflowError, match="No active phase"):
            ctrl.handle_call(
                "workflow__workflow_pass_checkpoint",
                {"workflow_id": "wf1"},
            )

    def test_pass_checkpoint_missing_workflow(self, ctrl):
        with pytest.raises(WorkflowError, match="not found"):
            ctrl.handle_call(
                "workflow__workflow_pass_checkpoint",
                {"workflow_id": "ghost"},
            )


# --- Agent state ---


class TestAgentState:
    def test_set_and_get(self, ctrl):
        ctrl.handle_call(
            "workflow__agent_set_state",
            {"agent_id": "a1", "state": {"name": "explorer"}},
        )
        result = ctrl.handle_call(
            "workflow__agent_get_state", {"agent_id": "a1"}
        )
        assert result == {"name": "explorer"}

    def test_get_missing(self, ctrl):
        result = ctrl.handle_call(
            "workflow__agent_get_state", {"agent_id": "ghost"}
        )
        assert result is None

    def test_delete(self, ctrl):
        ctrl.handle_call(
            "workflow__agent_set_state",
            {"agent_id": "a1", "state": {"x": 1}},
        )
        ctrl.handle_call("workflow__agent_delete", {"agent_id": "a1"})
        assert ctrl.handle_call(
            "workflow__agent_get_state", {"agent_id": "a1"}
        ) is None

    def test_list_agents(self, ctrl):
        ctrl.handle_call(
            "workflow__agent_set_state", {"agent_id": "a1", "state": {}}
        )
        ctrl.handle_call(
            "workflow__agent_set_state", {"agent_id": "a2", "state": {}}
        )
        agents = ctrl.handle_call("workflow__list_agents", {})
        assert set(agents) == {"a1", "a2"}


# --- Permissions ---


class TestPermissions:
    def test_blocked_tool_raises(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "permissions.yaml").write_text(
            yaml.dump({
                "global": {
                    "allowed": [],
                    "blocked": ["native__bash"],
                    "superblocked": [],
                },
            })
        )
        (config_dir / "backends.json").write_text("{}")
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        ctrl = Controller(config_dir=config_dir, data_dir=data_dir)
        with pytest.raises(PermissionDeniedError):
            ctrl.handle_call("native__bash", {"command": "echo hi"})
        ctrl.shutdown()


# --- Summarization ---


class TestSummarization:
    def test_small_result_not_summarized(self, ctrl, tmp_path):
        f = tmp_path / "small.txt"
        f.write_text("small content")
        result = ctrl.handle_call("native__read_file", {"file_path": str(f)})
        assert "summary" not in result
        assert "content" in result  # raw result

    def test_large_result_summarized(self, ctrl, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("x" * 5000)
        ctrl._summarization_threshold = 100  # lower threshold for test
        result = ctrl.handle_call("native__read_file", {"file_path": str(f)})
        assert "summary" in result
        assert "content_id" in result
        assert result["full_available"] is True

    def test_full_content_retrievable(self, ctrl, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("x" * 5000)
        ctrl._summarization_threshold = 100
        result = ctrl.handle_call("native__read_file", {"file_path": str(f)})
        content_id = result["content_id"]
        full = ctrl.get_full_content(content_id)
        assert full is not None
        assert "content" in full  # raw read_file result


# --- Telemetry recording ---


class TestTelemetry:
    def test_events_recorded(self, ctrl, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        ctrl.handle_call("native__read_file", {"file_path": str(f)})
        events = ctrl.data.query_events(tool="native__read_file")
        assert len(events) >= 1
        assert events[0].status == "success"


class TestWorkflowStartBinding:
    def test_workflow_start_binds_caller(self, ctrl_with_config):
        c = ctrl_with_config
        agent = c.permissions.register_agent("orch", "pm")
        assert agent.workflow != "iterate"  # not bound to it yet
        c._wf_start({"workflow_id": "iterate"}, agent)
        bound = c.permissions.get_agent("orch")
        assert bound.workflow == "iterate"
        assert bound.phase == "test_writing"  # iterate's initial phase

    def test_workflow_start_without_caller_is_safe(self, ctrl_with_config):
        c = ctrl_with_config
        c._wf_start({"workflow_id": "iterate"}, None)  # no caller -> no binding, no crash
        assert "iterate" in c._workflow_state
