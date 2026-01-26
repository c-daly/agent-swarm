"""Integration tests for router permission enforcement."""

import pytest
import json
import sys
from pathlib import Path
import tempfile
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from mcp_router import MCPRouter


@pytest.fixture
def temp_permissions():
    """Create a temporary permissions config."""
    config = {
        "global": {
            "allowed": ["Read", "mcp__router__*"],
            "blocked": ["Bash", "Edit", "Write"],
            "superblocked": ["Bash(rm -rf*)"],
        },
        "agents": {
            "explorer": {
                "allowed": ["Glob", "Grep"],
                "blocked": ["Task"],
            },
            "implementer": {
                "allowed": ["Edit", "Write"],
                "blocked": [],
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
    
    # Create config directory if it doesn't exist
    config_dir = Path(__file__).parent.parent / "config"
    config_dir.mkdir(exist_ok=True)
    
    # Save to temp file and then to config/permissions.yaml
    config_path = config_dir / "permissions.yaml"
    original_content = None
    if config_path.exists():
        original_content = config_path.read_text()
    
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    
    yield config_path
    
    # Restore original if it existed
    if original_content:
        config_path.write_text(original_content)


class TestRouterPermissionCheck:
    """Test router._check_permission method."""
    
    def test_permission_checker_initialized(self):
        """Router should have permission checker."""
        router = MCPRouter(enable_telemetry=False)
        assert router.permissions is not None
        assert router.agent_registry is not None
    
    def test_global_allowed(self, temp_permissions):
        """Globally allowed tools should pass."""
        router = MCPRouter(enable_telemetry=False)
        router.permissions.reload_config()
        
        allowed, response = router._check_permission("Read", {})
        assert allowed
        assert response is None
    
    def test_global_blocked(self, temp_permissions):
        """Globally blocked tools should fail."""
        router = MCPRouter(enable_telemetry=False)
        router.permissions.reload_config()
        
        allowed, response = router._check_permission("Bash", {"command": "echo test"})
        assert not allowed
        assert response["blocked"]
    
    def test_superblocked_always_fails(self, temp_permissions):
        """Superblocked commands cannot be overridden."""
        router = MCPRouter(enable_telemetry=False)
        router.permissions.reload_config()
        
        # Even with agent_id that might have permissions, superblocked fails
        allowed, response = router._check_permission(
            "Bash", 
            {"command": "rm -rf /", "_agent_id": "test-agent"}
        )
        assert not allowed
        assert "superblocked" in response["reason"]
    
    def test_agent_context_from_registry(self, temp_permissions):
        """Permission check uses agent registry for context."""
        router = MCPRouter(enable_telemetry=False)
        router.permissions.reload_config()
        
        # Register an implementer agent
        router.register_agent("agent-123", "implementer")
        
        # Implementer can use Edit (overrides global block)
        allowed, response = router._check_permission(
            "Edit",
            {"file_path": "test.py", "_agent_id": "agent-123"}
        )
        assert allowed


class TestAgentRegistration:
    """Test agent registration via router."""
    
    def test_register_agent(self):
        """Can register an agent."""
        router = MCPRouter(enable_telemetry=False)
        
        result = router.register_agent("agent-001", "explorer", ["read_only"])
        
        assert result["agent_id"] == "agent-001"
        assert result["agent_type"] == "explorer"
        assert "read_only" in result["roles"]
    
    def test_update_agent_phase(self):
        """Can update agent's workflow phase."""
        router = MCPRouter(enable_telemetry=False)
        router.register_agent("agent-001", "implementer")
        
        result = router.update_agent_phase("agent-001", "iterate", "implement")
        
        assert result["workflow"] == "iterate"
        assert result["phase"] == "implement"
    
    def test_phase_affects_permissions(self, temp_permissions):
        """Agent phase affects permission evaluation."""
        router = MCPRouter(enable_telemetry=False)
        router.permissions.reload_config()
        
        # Register agent and set to orchestrate phase
        router.register_agent("agent-001", "orchestrator")
        router.update_agent_phase("agent-001", "iterate", "orchestrate")
        
        # In orchestrate phase, Edit should be blocked
        allowed, response = router._check_permission(
            "Edit",
            {"file_path": "test.py", "_agent_id": "agent-001"}
        )
        assert not allowed
        
        # Update to implement phase
        router.update_agent_phase("agent-001", "iterate", "implement")
        
        # Now Edit should be allowed
        allowed, response = router._check_permission(
            "Edit",
            {"file_path": "test.py", "_agent_id": "agent-001"}
        )
        assert allowed


class TestBlockedResponse:
    """Test blocked response content."""
    
    def test_blocked_response_structure(self, temp_permissions):
        """Blocked response has expected fields."""
        router = MCPRouter(enable_telemetry=False)
        router.permissions.reload_config()
        
        allowed, response = router._check_permission("Edit", {})
        
        assert not allowed
        assert "blocked" in response
        assert "reason" in response
        assert "guidance" in response
        assert response["blocked"] is True
    
    def test_blocked_response_has_tool(self, temp_permissions):
        """Blocked response includes tool name."""
        router = MCPRouter(enable_telemetry=False)
        router.permissions.reload_config()
        
        allowed, response = router._check_permission("Edit", {})
        
        assert response["tool"] == "Edit"
