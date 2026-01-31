#!/usr/bin/env python3
"""Tests for lib/config_new.py"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.config_new import (
    AgentConfig,
    AllConfig,
    BackendConfig,
    ConfigError,
    PhaseConfig,
    WorkflowConfig,
    _parse_frontmatter,
    load_agents,
    load_all,
    load_backends,
    load_permissions,
    load_workflow,
)


# --- BackendConfig ---


class TestBackendConfig:
    def test_frozen(self):
        cfg = BackendConfig(name="test", command=("a", "b"))
        with pytest.raises(AttributeError):
            cfg.name = "other"

    def test_defaults(self):
        cfg = BackendConfig(name="x", command=("cmd",))
        assert cfg.tool_prefix == ""


# --- load_backends ---


class TestLoadBackends:
    def test_load_valid(self, tmp_path):
        cfg = {
            "serena": {"command": ["uvx", "serena"], "tool_prefix": "serena"},
            "context7": {"command": ["npx", "context7"]},
        }
        (tmp_path / "backends.json").write_text(json.dumps(cfg))
        result = load_backends(tmp_path)
        assert len(result) == 2
        assert result["serena"].command == ("uvx", "serena")
        assert result["serena"].tool_prefix == "serena"
        assert result["context7"].tool_prefix == ""

    def test_filters_internal(self, tmp_path):
        cfg = {
            "serena": {"command": ["serena"]},
            "native": {"command": ["native"]},
            "workflow": {"command": ["workflow"]},
        }
        (tmp_path / "backends.json").write_text(json.dumps(cfg))
        result = load_backends(tmp_path)
        assert list(result.keys()) == ["serena"]

    def test_missing_file(self, tmp_path):
        result = load_backends(tmp_path)
        assert result == {}

    def test_invalid_json(self, tmp_path):
        (tmp_path / "backends.json").write_text("{bad json")
        with pytest.raises(ConfigError, match="Failed to load"):
            load_backends(tmp_path)

    def test_not_object(self, tmp_path):
        (tmp_path / "backends.json").write_text("[]")
        with pytest.raises(ConfigError, match="Expected object"):
            load_backends(tmp_path)

    def test_missing_command(self, tmp_path):
        (tmp_path / "backends.json").write_text(json.dumps({"bad": {"tool_prefix": "x"}}))
        with pytest.raises(ConfigError, match="missing required field"):
            load_backends(tmp_path)

    def test_command_not_list(self, tmp_path):
        (tmp_path / "backends.json").write_text(json.dumps({"x": {"command": "str"}}))
        with pytest.raises(ConfigError, match="command must be a list"):
            load_backends(tmp_path)


# --- load_workflow ---


class TestLoadWorkflow:
    def _write_workflow(self, tmp_path, data):
        (tmp_path / "workflow.json").write_text(json.dumps(data))

    def test_load_phases(self, tmp_path):
        self._write_workflow(tmp_path, {
            "phases": {
                "implement": {
                    "description": "Code implementation",
                    "checkpoint": False,
                    "agents": ["implementer"],
                    "model": "opus",
                    "enforce_subagents": True,
                },
                "review": {
                    "description": "Code review",
                    "checkpoint": True,
                    "agents": ["reviewer"],
                },
            },
            "orchestrator": {"model": "opus"},
            "checkpoints": {"implement": False, "review": True},
            "execution": {"prefer_parallel": True},
        })
        result = load_workflow(tmp_path)
        assert result is not None
        assert len(result.phases) == 2

        impl = result.phases["implement"]
        assert impl.name == "implement"
        assert impl.description == "Code implementation"
        assert impl.agents == ("implementer",)
        assert impl.model == "opus"
        assert impl.enforce_subagents is True
        assert impl.checkpoint is False

        review = result.phases["review"]
        assert review.checkpoint is True
        assert review.enforce_subagents is False
        assert review.model is None

    def test_orchestrator_and_execution(self, tmp_path):
        self._write_workflow(tmp_path, {
            "orchestrator": {"model": "opus"},
            "execution": {"max_concurrent_subagents": 3},
        })
        result = load_workflow(tmp_path)
        assert result is not None
        assert result.orchestrator["model"] == "opus"
        assert result.execution["max_concurrent_subagents"] == 3

    def test_missing_file(self, tmp_path):
        assert load_workflow(tmp_path) is None

    def test_invalid_json(self, tmp_path):
        (tmp_path / "workflow.json").write_text("bad")
        with pytest.raises(ConfigError, match="Failed to load"):
            load_workflow(tmp_path)

    def test_not_object(self, tmp_path):
        (tmp_path / "workflow.json").write_text('"string"')
        with pytest.raises(ConfigError, match="Expected object"):
            load_workflow(tmp_path)

    def test_empty_phases(self, tmp_path):
        self._write_workflow(tmp_path, {})
        result = load_workflow(tmp_path)
        assert result is not None
        assert result.phases == {}

    def test_phase_defaults(self, tmp_path):
        self._write_workflow(tmp_path, {"phases": {"test": {}}})
        result = load_workflow(tmp_path)
        phase = result.phases["test"]
        assert phase.description == ""
        assert phase.checkpoint is False
        assert phase.agents == ()
        assert phase.model is None
        assert phase.enforce_subagents is False


# --- _parse_frontmatter ---


class TestParseFrontmatter:
    def test_basic(self):
        text = "---\nname: test\ndescription: A test agent\n---\nBody text here"
        fm, body = _parse_frontmatter(text)
        assert fm["name"] == "test"
        assert fm["description"] == "A test agent"
        assert body == "Body text here"

    def test_no_frontmatter(self):
        text = "Just regular text"
        fm, body = _parse_frontmatter(text)
        assert fm == {}
        assert body == "Just regular text"

    def test_empty_body(self):
        text = "---\nname: x\n---\n"
        fm, body = _parse_frontmatter(text)
        assert fm["name"] == "x"
        assert body == ""

    def test_comments_ignored(self):
        text = "---\nname: x\n# comment\ndescription: y\n---\nbody"
        fm, body = _parse_frontmatter(text)
        assert "comment" not in str(fm)
        assert fm["name"] == "x"
        assert fm["description"] == "y"

    def test_colon_in_value(self):
        text = "---\nname: foo:bar:baz\n---\n"
        fm, _ = _parse_frontmatter(text)
        assert fm["name"] == "foo:bar:baz"

    def test_multiline_body(self):
        text = "---\nname: x\n---\nline1\nline2\nline3"
        _, body = _parse_frontmatter(text)
        assert "line1\nline2\nline3" == body


# --- load_agents ---


class TestLoadAgents:
    def test_load_agents(self, tmp_path):
        (tmp_path / "impl.md").write_text(
            "---\nname: implementer\ntools: Bash(mcp*)\n"
            "description: Code impl\nmodel: opus\n---\n"
            "<constraints>\nStay in scope\n</constraints>"
        )
        (tmp_path / "explorer.md").write_text(
            "---\nname: explorer\ntools: Bash(mcp*)\n"
            "description: Explore code\n---\nExplorer prompt"
        )
        result = load_agents(tmp_path)
        assert len(result) == 2
        assert "implementer" in result
        assert "explorer" in result
        assert result["implementer"].model == "opus"
        assert result["implementer"].tools == "Bash(mcp*)"
        assert "<constraints>" in result["implementer"].prompt
        assert result["explorer"].model is None

    def test_missing_dir(self, tmp_path):
        result = load_agents(tmp_path / "nonexistent")
        assert result == {}

    def test_name_from_filename(self, tmp_path):
        (tmp_path / "my-agent.md").write_text("---\ndescription: test\n---\nbody")
        result = load_agents(tmp_path)
        assert "my-agent" in result

    def test_no_frontmatter(self, tmp_path):
        (tmp_path / "plain.md").write_text("Just plain text, no frontmatter")
        result = load_agents(tmp_path)
        assert result["plain"].prompt == "Just plain text, no frontmatter"
        assert result["plain"].description == ""


# --- load_permissions ---


class TestLoadPermissions:
    def test_exists(self, tmp_path):
        (tmp_path / "permissions.yaml").write_text("global:\n  allowed: []\n")
        result = load_permissions(tmp_path)
        assert result is not None
        assert result.name == "permissions.yaml"

    def test_not_exists(self, tmp_path):
        assert load_permissions(tmp_path) is None


# --- load_all ---


class TestLoadAll:
    def test_load_all(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        (config_dir / "backends.json").write_text(
            json.dumps({"ctx7": {"command": ["npx", "ctx7"], "tool_prefix": "context7"}})
        )
        (config_dir / "workflow.json").write_text(
            json.dumps({"phases": {"test": {"description": "testing"}}, "orchestrator": {}})
        )
        (config_dir / "permissions.yaml").write_text("global:\n  allowed: []\n")
        (agents_dir / "impl.md").write_text(
            "---\nname: implementer\ndescription: impl\n---\nprompt"
        )

        result = load_all(tmp_path)
        assert isinstance(result, AllConfig)
        assert len(result.backends) == 1
        assert result.workflow is not None
        assert len(result.workflow.phases) == 1
        assert len(result.agents) == 1
        assert result.permissions_path is not None

    def test_load_all_empty(self, tmp_path):
        result = load_all(tmp_path)
        assert result.backends == {}
        assert result.workflow is None
        assert result.agents == {}
        assert result.permissions_path is None


# --- Real config files ---


class TestRealConfig:
    """Test against actual project config files."""

    BASE = Path(__file__).parent.parent

    @pytest.mark.skipif(
        not (Path(__file__).parent.parent / "config" / "backends.json").exists(),
        reason="No real config files available",
    )
    def test_real_backends(self):
        result = load_backends(self.BASE / "config")
        assert "serena" in result
        assert "native" not in result
        assert "workflow" not in result

    @pytest.mark.skipif(
        not (Path(__file__).parent.parent / "config" / "workflow.json").exists(),
        reason="No real config files available",
    )
    def test_real_workflow(self):
        result = load_workflow(self.BASE / "config")
        assert result is not None
        assert "implement" in result.phases
        assert result.phases["implement"].agents == ("implementer",)

    @pytest.mark.skipif(
        not (Path(__file__).parent.parent / "agents").exists(),
        reason="No agents directory available",
    )
    def test_real_agents(self):
        result = load_agents(self.BASE / "agents")
        assert "implementer" in result
        assert result["implementer"].model == "opus"
