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
        
        # Even with agent_type that might have permissions, superblocked fails
        allowed, response = router._check_permission(
            "Bash", 
            {"command": "rm -rf /", "_agent_type": "implementer"}
        )
        assert not allowed
        assert "superblocked" in response["reason"]
    
    def test_agent_type_from_metadata(self, temp_permissions):
        """Permission check uses inline _agent_type metadata."""
        router = MCPRouter(enable_telemetry=False)
        router.permissions.reload_config()
        
        # Implementer can use Edit (overrides global block)
        allowed, response = router._check_permission(
            "Edit",
            {"file_path": "test.py", "_agent_type": "implementer"}
        )
        assert allowed
    
    def test_explorer_blocked_from_task(self, temp_permissions):
        """Explorer agent type cannot use Task."""
        router = MCPRouter(enable_telemetry=False)
        router.permissions.reload_config()
        
        allowed, response = router._check_permission(
            "Task",
            {"prompt": "test", "_agent_type": "explorer"}
        )
        assert not allowed


class TestPhasePermissions:
    """Test workflow phase based permissions."""
    
    def test_orchestrate_phase_blocks_edit(self, temp_permissions):
        """In orchestrate phase, Edit should be blocked."""
        router = MCPRouter(enable_telemetry=False)
        router.permissions.reload_config()
        
        allowed, response = router._check_permission(
            "Edit",
            {"file_path": "test.py", "_workflow": "iterate", "_phase": "orchestrate"}
        )
        assert not allowed
    
    def test_implement_phase_allows_edit(self, temp_permissions):
        """In implement phase, Edit should be allowed."""
        router = MCPRouter(enable_telemetry=False)
        router.permissions.reload_config()
        
        allowed, response = router._check_permission(
            "Edit",
            {"file_path": "test.py", "_workflow": "iterate", "_phase": "implement"}
        )
        assert allowed
    
    def test_implement_phase_allows_pytest(self, temp_permissions):
        """In implement phase, Bash(pytest*) should be allowed."""
        router = MCPRouter(enable_telemetry=False)
        router.permissions.reload_config()
        
        allowed, response = router._check_permission(
            "Bash",
            {"command": "pytest tests/", "_workflow": "iterate", "_phase": "implement"}
        )
        assert allowed
    
    def test_implement_phase_blocks_other_bash(self, temp_permissions):
        """In implement phase, non-pytest Bash should still be blocked."""
        router = MCPRouter(enable_telemetry=False)
        router.permissions.reload_config()
        
        allowed, response = router._check_permission(
            "Bash",
            {"command": "echo hello", "_workflow": "iterate", "_phase": "implement"}
        )
        assert not allowed


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
    
    def test_metadata_stripped_from_args(self, temp_permissions):
        """Metadata fields should be stripped from args."""
        router = MCPRouter(enable_telemetry=False)
        router.permissions.reload_config()
        
        args = {
            "file_path": "test.py",
            "_agent_id": "agent-123",
            "_agent_type": "implementer",
            "_workflow": "iterate",
            "_phase": "implement",
        }
        
        allowed, _ = router._check_permission("Edit", args)
        
        # Metadata should be removed
        assert "_agent_id" not in args
        assert "_agent_type" not in args
        assert "_workflow" not in args
        assert "_phase" not in args
        # Real args should remain
        assert "file_path" in args
