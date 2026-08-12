#!/usr/bin/env python3
"""Tests for the daemon-side permission checker."""

import threading

import pytest
import yaml

from lib.errors import RouterError
from lib.permissions import (
    AgentInfo,
    BlockedResponse,
    PermissionChecker,
    _matches_pattern,
)


# --- Test config ---

_TEST_CONFIG = {
    "global": {
        "allowed": ["native__read_file", "native__glob", "native__grep", "serena__*"],
        "blocked": ["native__write_file", "native__edit_file"],
        "superblocked": [
            "native__bash(rm -rf*)",
            "native__bash(sudo*)",
        ],
    },
    "roles": {
        "editor": {
            "allowed": ["native__write_file", "native__edit_file"],
            "blocked": [],
        },
        "shell_safe": {
            "allowed": ["native__bash(pytest*)"],
            "blocked": [],
        },
    },
    "agents": {
        "explorer": {
            "allowed": ["native__read_file", "native__glob", "native__grep", "serena__*"],
            "blocked": ["native__write_file", "native__edit_file", "native__bash"],
        },
        "implementer": {
            "allowed": [
                "native__write_file",
                "native__edit_file",
                "native__read_file",
                "native__bash(pytest*)",
            ],
            "blocked": ["native__bash(rm*)"],
        },
    },
    "workflows": {
        "iterate": {
            "test": {
                "allowed": ["native__read_file", "native__bash(pytest*)"],
                "blocked": ["native__write_file", "native__edit_file"],
            },
            "implement": {
                "allowed": [
                    "native__write_file",
                    "native__edit_file",
                    "native__read_file",
                    "native__bash(pytest*)",
                ],
                "blocked": [],
            },
        },
    },
}


@pytest.fixture
def config_path(tmp_path):
    """Write test config to a temp file."""
    p = tmp_path / "permissions.yaml"
    p.write_text(yaml.dump(_TEST_CONFIG))
    return p


@pytest.fixture
def checker(config_path):
    return PermissionChecker(config_path)


# --- Pattern matching ---


class TestPatternMatching:
    def test_exact_match(self):
        assert _matches_pattern("native__read_file", "native__read_file", {})

    def test_exact_no_match(self):
        assert not _matches_pattern("native__read_file", "native__write_file", {})

    def test_glob_match(self):
        assert _matches_pattern("serena__*", "serena__find_symbol", {})

    def test_glob_no_match(self):
        assert not _matches_pattern("serena__*", "native__bash", {})

    def test_arg_pattern_bash(self):
        assert _matches_pattern(
            "native__bash(pytest*)", "native__bash", {"command": "pytest tests/"}
        )

    def test_arg_pattern_bash_no_match(self):
        assert not _matches_pattern(
            "native__bash(pytest*)", "native__bash", {"command": "rm -rf /"}
        )

    def test_arg_pattern_file(self):
        assert _matches_pattern(
            "native__edit_file(tests/**)",
            "native__edit_file",
            {"file_path": "tests/test_foo.py"},
        )

    def test_arg_pattern_wrong_tool(self):
        assert not _matches_pattern(
            "native__bash(pytest*)", "native__read_file", {"command": "pytest"}
        )


# --- Superblock ---


class TestSuperblock:
    def test_superblocked_tool_rejected(self, checker):
        allowed, resp = checker.check(
            "native__bash", {"command": "rm -rf /"}, None
        )
        assert not allowed
        assert resp is not None
        assert "superblocked" in resp.reason

    def test_superblocked_sudo(self, checker):
        allowed, resp = checker.check(
            "native__bash", {"command": "sudo apt install foo"}, None
        )
        assert not allowed
        assert "superblocked" in resp.reason

    def test_superblock_overrides_agent_allow(self, checker):
        """Even if agent allows bash, superblock patterns still block."""
        agent = AgentInfo(agent_id="a1", agent_type="implementer")
        allowed, resp = checker.check(
            "native__bash", {"command": "rm -rf /"}, agent
        )
        assert not allowed
        assert "superblocked" in resp.reason


# --- Level precedence ---


class TestPrecedence:
    def test_global_allows_read(self, checker):
        allowed, resp = checker.check("native__read_file", {}, None)
        assert allowed
        assert resp is None

    def test_global_blocks_write(self, checker):
        allowed, resp = checker.check("native__write_file", {}, None)
        assert not allowed

    def test_default_deny(self, checker):
        """Unknown tools are denied by default."""
        allowed, resp = checker.check("unknown_tool", {}, None)
        assert not allowed
        assert "not in allowed list" in resp.reason

    def test_agent_allows_overrides_global_block(self, checker):
        """Implementer allows write_file even though global blocks it."""
        agent = AgentInfo(agent_id="a1", agent_type="implementer")
        allowed, resp = checker.check("native__write_file", {}, agent)
        assert allowed

    def test_agent_blocks_override_global_allow(self, checker):
        """Explorer blocks bash even though global doesn't list it."""
        agent = AgentInfo(agent_id="a1", agent_type="explorer")
        allowed, resp = checker.check("native__bash", {"command": "ls"}, agent)
        assert not allowed

    def test_workflow_phase_highest_priority(self, checker):
        """Phase rules override agent-type rules."""
        agent = AgentInfo(
            agent_id="a1",
            agent_type="implementer",
            workflow="iterate",
            phase="test",
        )
        # Phase test blocks write_file, even though implementer allows it
        allowed, resp = checker.check("native__write_file", {}, agent)
        assert not allowed
        assert "phase" in resp.reason

    def test_workflow_implement_allows_write(self, checker):
        """Implement phase allows write_file."""
        agent = AgentInfo(
            agent_id="a1",
            agent_type="implementer",
            workflow="iterate",
            phase="implement",
        )
        allowed, resp = checker.check("native__write_file", {}, agent)
        assert allowed

    def test_per_instance_workflow_resolves_to_base_phase_rules(self, checker):
        """A per-instance id (iterate:<agent_id>, used by parallel workers) is
        governed by the base workflow's phase rules -- the test phase still
        blocks write_file even on an isolated instance."""
        agent = AgentInfo(
            agent_id="a1",
            agent_type="implementer",
            workflow="iterate:a1",
            phase="test",
        )
        allowed, resp = checker.check("native__write_file", {}, agent)
        assert not allowed
        assert "phase" in resp.reason

    def test_per_instance_workflow_implement_allows_write(self, checker):
        """The per-instance implement phase resolves to base iterate.implement."""
        agent = AgentInfo(
            agent_id="a1",
            agent_type="implementer",
            workflow="iterate:deadbeef",
            phase="implement",
        )
        allowed, resp = checker.check("native__write_file", {}, agent)
        assert allowed

    def test_role_allows_overrides_global_block(self, checker):
        """Editor role allows write_file despite global block."""
        agent = AgentInfo(agent_id="a1", agent_type="", roles=["editor"])
        allowed, resp = checker.check("native__write_file", {}, agent)
        assert allowed

    def test_agent_checked_before_role(self, checker):
        """Agent-type rules have higher precedence than role rules."""
        agent = AgentInfo(
            agent_id="a1",
            agent_type="explorer",
            roles=["editor"],
        )
        # Explorer blocks write_file (level 2), editor allows it (level 3).
        # Level 2 wins.
        allowed, resp = checker.check("native__write_file", {}, agent)
        assert not allowed


# --- Agent registry ---


class TestAgentRegistry:
    def test_register_and_get(self, checker):
        info = checker.register_agent("a1", "explorer", ["read_only"])
        assert info.agent_id == "a1"
        assert info.agent_type == "explorer"
        assert info.roles == ["read_only"]

        retrieved = checker.get_agent("a1")
        assert retrieved is info

    def test_register_derives_session_id_from_main_agent_id(self, checker):
        # The main agent's id embeds the Claude session uuid ("main:<uuid>");
        # session_id is derived from it so every event row can be grouped by
        # session instead of being left empty.
        info = checker.register_agent("main:d1c9ae99-817d", "implementer")
        assert info.session_id == "d1c9ae99-817d"

    def test_register_derives_session_id_from_subagent_id(self, checker):
        # A subagent has no separate session source daemon-side; its caller-id
        # (== agent_id) is the stable grouping key, so session_id falls back to
        # the agent_id rather than staying empty.
        info = checker.register_agent("sub-deadbeef", "explorer")
        assert info.session_id == "sub-deadbeef"

    def test_register_explicit_session_id_wins(self, checker):
        # An explicit session_id (e.g. AGENT_SESSION_ID threaded by mcp-call,
        # which may be the parent session) takes precedence over derivation.
        info = checker.register_agent("sub-x", "explorer", session_id="sess-123")
        assert info.session_id == "sess-123"

    def test_register_empty_agent_id_has_empty_session_id(self, checker):
        info = checker.register_agent("", "")
        assert info.session_id == ""

    def test_get_missing(self, checker):
        assert checker.get_agent("nonexistent") is None

    def test_update_phase(self, checker):
        checker.register_agent("a1", "implementer")
        checker.update_agent_phase("a1", "iterate", "test")
        agent = checker.get_agent("a1")
        assert agent.workflow == "iterate"
        assert agent.phase == "test"

    def test_update_phase_unregistered_raises(self, checker):
        with pytest.raises(RouterError):
            checker.update_agent_phase("ghost", "iterate", "test")

    def test_remove_agent(self, checker):
        checker.register_agent("a1", "explorer")
        checker.remove_agent("a1")
        assert checker.get_agent("a1") is None

    def test_remove_missing_no_error(self, checker):
        checker.remove_agent("nonexistent")  # Should not raise


# --- get_allowed_tools ---


class TestGetAllowedTools:
    def test_global_allowed(self, checker):
        tools = checker.get_allowed_tools()
        assert "native__read_file" in tools
        assert "serena__*" in tools

    def test_agent_type_allowed(self, checker):
        tools = checker.get_allowed_tools("explorer")
        assert "native__read_file" in tools
        assert "serena__*" in tools

    def test_unknown_agent_falls_back_to_global(self, checker):
        tools = checker.get_allowed_tools("nonexistent_type")
        assert tools == checker.get_allowed_tools()


# --- BlockedResponse ---


class TestBlockedResponse:
    def test_to_dict(self):
        br = BlockedResponse(
            reason="blocked",
            tool="native__bash",
            agent_type="explorer",
            rule_that_blocked="native__bash",
        )
        d = br.to_dict()
        assert d["blocked"] is True
        assert d["reason"] == "blocked"
        assert d["tool"] == "native__bash"

    def test_default_values(self):
        br = BlockedResponse()
        assert br.blocked is True
        assert br.reason == ""


# --- Reload ---


class TestReload:
    def test_reload_picks_up_changes(self, config_path, checker):
        # Initially blocks write
        allowed, _ = checker.check("native__write_file", {}, None)
        assert not allowed

        # Modify config to allow write globally
        new_config = dict(_TEST_CONFIG)
        new_config["global"] = {
            "allowed": ["native__write_file"],
            "blocked": [],
            "superblocked": [],
        }
        config_path.write_text(yaml.dump(new_config))
        checker.reload()

        allowed, _ = checker.check("native__write_file", {}, None)
        assert allowed


# --- Missing config ---


class TestMissingConfig:
    def test_missing_config_defaults_to_deny_all(self, tmp_path):
        checker = PermissionChecker(tmp_path / "nonexistent.yaml")
        allowed, resp = checker.check("native__read_file", {}, None)
        assert not allowed
        assert "not in allowed list" in resp.reason


# --- Thread safety ---


class TestThreadSafety:
    def test_concurrent_register_and_check(self, checker):
        errors = []

        def register_loop():
            try:
                for i in range(50):
                    checker.register_agent(f"agent-{i}", "explorer")
            except Exception as e:
                errors.append(e)

        def check_loop():
            try:
                for _ in range(50):
                    checker.check("native__read_file", {}, None)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register_loop) for _ in range(4)]
        threads += [threading.Thread(target=check_loop) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
