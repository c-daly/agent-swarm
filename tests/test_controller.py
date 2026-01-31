#!/usr/bin/env python3
"""Tests for the core orchestrator."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from lib.controller import Controller
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


@pytest.fixture
def ctrl(tmp_path):
    """Create a Controller with minimal config."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "permissions.yaml").write_text(yaml.dump(_PERM_CONFIG))
    (config_dir / "backends.json").write_text(json.dumps(_BACKEND_CONFIG))

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    c = Controller(config_dir=config_dir, data_dir=data_dir)
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

    def test_unknown_router_tool(self, ctrl):
        with pytest.raises(RouterError, match="Unknown router tool"):
            ctrl.handle_call("router__nonexistent", {})


# --- Workflow state ---


class TestWorkflowState:
    def test_start_and_get_state(self, ctrl):
        ctrl.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "wf1", "initial_state": {"phase": "init"}},
        )
        state = ctrl.handle_call(
            "workflow__workflow_get_state", {"workflow_id": "wf1"}
        )
        assert state == {"phase": "init"}

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

    def test_set_and_get_value(self, ctrl):
        ctrl.handle_call(
            "workflow__workflow_start", {"workflow_id": "wf1"}
        )
        ctrl.handle_call(
            "workflow__workflow_set_value",
            {"workflow_id": "wf1", "key": "phase", "value": "test"},
        )
        val = ctrl.handle_call(
            "workflow__workflow_get_value",
            {"workflow_id": "wf1", "key": "phase"},
        )
        assert val == "test"

    def test_update(self, ctrl):
        ctrl.handle_call(
            "workflow__workflow_start",
            {"workflow_id": "wf1", "initial_state": {"a": 1}},
        )
        result = ctrl.handle_call(
            "workflow__workflow_update",
            {"workflow_id": "wf1", "updates": {"b": 2}},
        )
        assert result == {"a": 1, "b": 2}

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
