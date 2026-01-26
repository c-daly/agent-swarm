"""Tests for MCP router permission checker."""

import pytest
from pathlib import Path
import tempfile
import yaml

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from mcp_permissions import (
    PermissionChecker,
    AgentRegistry,
    AgentInfo,
    BlockedResponse,
    check_permission,
)


@pytest.fixture
def temp_config():
    """Create a temporary permissions config."""
    config = {
        "global": {
            "allowed": ["mcp__router__*", "Read"],
            "blocked": ["Bash", "Edit", "Write"],
            "superblocked": ["Bash(rm -rf*)", "Bash(sudo*)"],
        },
        "roles": {
            "editor": {
                "allowed": ["Edit", "Write"],
                "blocked": [],
            },
            "shell_access": {
                "allowed": ["Bash"],
                "blocked": [],
            },
        },
        "agents": {
            "explorer": {
                "allowed": ["Glob", "Grep"],
                "blocked": ["Task"],
            },
            "implementer": {
                "allowed": ["Edit", "Write"],
                "blocked": ["Bash(rm*)"],
            },
        },
        "workflows": {
            "iterate": {
                "orchestrate": {
                    "allowed": ["Task"],
                    "blocked": ["Edit", "Write"],
                },
                "implement": {
                    "allowed": ["Edit", "Write", "Bash(pytest*)"],
                    "blocked": [],
                },
            },
        },
    }
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        yield Path(f.name)


class TestPatternMatching:
    """Test tool pattern matching."""
    
    def test_exact_match(self, temp_config):
        checker = PermissionChecker(temp_config)
        assert checker._matches_pattern("Read", "Read", {})
        assert not checker._matches_pattern("Read", "Write", {})
    
    def test_glob_match(self, temp_config):
        checker = PermissionChecker(temp_config)
        assert checker._matches_pattern("mcp__router__*", "mcp__router__workflow__start", {})
        assert checker._matches_pattern("mcp__router__*", "mcp__router__ping", {})
        assert not checker._matches_pattern("mcp__router__*", "mcp__serena__read", {})
    
    def test_bash_arg_pattern(self, temp_config):
        checker = PermissionChecker(temp_config)
        assert checker._matches_pattern("Bash(rm -rf*)", "Bash", {"command": "rm -rf /"})
        assert checker._matches_pattern("Bash(pytest*)", "Bash", {"command": "pytest tests/"})
        assert not checker._matches_pattern("Bash(rm*)", "Bash", {"command": "echo hello"})
    
    def test_file_arg_pattern(self, temp_config):
        checker = PermissionChecker(temp_config)
        assert checker._matches_pattern("Edit(tests/*)", "Edit", {"file_path": "tests/test.py"})
        assert not checker._matches_pattern("Edit(tests/*)", "Edit", {"file_path": "src/main.py"})


class TestSuperblocked:
    """Test superblocked rules (never overridable)."""
    
    def test_superblocked_always_blocks(self, temp_config):
        checker = PermissionChecker(temp_config)
        
        # Even with roles that allow Bash, superblocked still blocks
        allowed, response = checker.check(
            tool="Bash",
            args={"command": "rm -rf /"},
            roles=["shell_access"],  # This role allows Bash
        )
        
        assert not allowed
        assert response.reason == "superblocked - cannot override"
        assert "global.superblocked" in response.rule_that_blocked
    
    def test_sudo_superblocked(self, temp_config):
        checker = PermissionChecker(temp_config)
        
        allowed, response = checker.check(
            tool="Bash",
            args={"command": "sudo apt install something"},
        )
        
        assert not allowed
        assert "superblocked" in response.reason


class TestLayeredPermissions:
    """Test permission layer precedence."""
    
    def test_global_allows(self, temp_config):
        checker = PermissionChecker(temp_config)
        
        allowed, _ = checker.check(tool="Read", args={})
        assert allowed
    
    def test_global_blocks(self, temp_config):
        checker = PermissionChecker(temp_config)
        
        allowed, response = checker.check(tool="Edit", args={})
        assert not allowed
    
    def test_role_overrides_global_block(self, temp_config):
        checker = PermissionChecker(temp_config)
        
        # Without role, Edit is blocked
        allowed, _ = checker.check(tool="Edit", args={})
        assert not allowed
        
        # With editor role, Edit is allowed
        allowed, _ = checker.check(tool="Edit", args={}, roles=["editor"])
        assert allowed
    
    def test_agent_adds_permissions(self, temp_config):
        checker = PermissionChecker(temp_config)
        
        # Explorer can use Glob even though it's not in global allowed
        allowed, _ = checker.check(tool="Glob", args={}, agent_type="explorer")
        assert allowed
    
    def test_agent_blocks_override(self, temp_config):
        checker = PermissionChecker(temp_config)
        
        # Explorer blocks Task
        allowed, response = checker.check(tool="Task", args={}, agent_type="explorer")
        assert not allowed
    
    def test_workflow_phase_blocks(self, temp_config):
        checker = PermissionChecker(temp_config)
        
        # In orchestrate phase, Edit is blocked
        allowed, response = checker.check(
            tool="Edit",
            args={},
            workflow="iterate",
            phase="orchestrate",
        )
        assert not allowed
    
    def test_workflow_phase_allows(self, temp_config):
        checker = PermissionChecker(temp_config)
        
        # In implement phase, Edit is allowed
        allowed, _ = checker.check(
            tool="Edit",
            args={},
            workflow="iterate",
            phase="implement",
        )
        assert allowed


class TestBlockedResponse:
    """Test blocked response content."""
    
    def test_blocked_response_has_guidance(self, temp_config):
        checker = PermissionChecker(temp_config)
        
        _, response = checker.check(tool="Edit", args={})
        
        assert response.blocked
        assert response.guidance
        assert len(response.guidance) > 0
    
    def test_superblocked_guidance(self, temp_config):
        checker = PermissionChecker(temp_config)
        
        _, response = checker.check(tool="Bash", args={"command": "sudo rm -rf /"})
        
        assert "never permitted" in response.guidance.lower()
    
    def test_phase_blocked_guidance(self, temp_config):
        checker = PermissionChecker(temp_config)
        
        _, response = checker.check(
            tool="Edit",
            args={},
            agent_type="implementer",
            workflow="iterate",
            phase="orchestrate",
        )
        
        assert "iterate/orchestrate" in response.phase


class TestAgentRegistry:
    """Test agent registration and lookup."""
    
    def test_register_and_get(self):
        registry = AgentRegistry()
        
        info = registry.register("agent-123", "implementer", ["editor"])
        
        assert info.agent_id == "agent-123"
        assert info.agent_type == "implementer"
        assert "editor" in info.roles
        
        retrieved = registry.get("agent-123")
        assert retrieved == info
    
    def test_get_unknown_agent(self):
        registry = AgentRegistry()
        
        assert registry.get("unknown") is None
    
    def test_update_phase(self):
        registry = AgentRegistry()
        registry.register("agent-123", "implementer")
        
        registry.update_phase("agent-123", "iterate", "implement")
        
        info = registry.get("agent-123")
        assert info.workflow == "iterate"
        assert info.phase == "implement"
    
    def test_remove_agent(self):
        registry = AgentRegistry()
        registry.register("agent-123", "implementer")
        
        registry.remove("agent-123")
        
        assert registry.get("agent-123") is None
    
    def test_list_agents(self):
        registry = AgentRegistry()
        registry.register("agent-1", "explorer")
        registry.register("agent-2", "implementer")
        
        agents = registry.list_agents()
        
        assert "agent-1" in agents
        assert "agent-2" in agents


class TestDefaultDeny:
    """Test that unknown tools are denied by default."""
    
    def test_unknown_tool_blocked(self, temp_config):
        checker = PermissionChecker(temp_config)
        
        allowed, response = checker.check(tool="UnknownTool", args={})
        
        assert not allowed
        assert "not in allowed list" in response.reason


class TestConvenienceFunction:
    """Test the check_permission convenience function."""
    
    def test_check_permission_allowed(self, temp_config):
        allowed, response = check_permission(
            tool="Read",
            config_path=temp_config,
        )
        
        assert allowed
        assert response is None
    
    def test_check_permission_blocked(self, temp_config):
        allowed, response = check_permission(
            tool="Edit",
            config_path=temp_config,
        )
        
        assert not allowed
        assert isinstance(response, dict)
        assert response["blocked"]
