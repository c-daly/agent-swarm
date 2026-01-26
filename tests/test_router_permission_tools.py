"""Tests for router permission built-in tools."""

import pytest
import json
import sys
from pathlib import Path
import tempfile
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from mcp_router import MCPRouter


@pytest.fixture
def router():
    """Create a router instance."""
    return MCPRouter(enable_telemetry=False)


@pytest.fixture
def temp_permissions():
    """Create a temporary permissions config."""
    config = {
        "global": {
            "allowed": ["Read", "mcp__router__*"],
            "blocked": ["Bash", "Edit"],
            "superblocked": [],
        },
        "agents": {
            "implementer": {
                "allowed": ["Edit", "Write"],
                "blocked": [],
            },
        },
    }
    
    config_dir = Path(__file__).parent.parent / "config"
    config_dir.mkdir(exist_ok=True)
    config_path = config_dir / "permissions.yaml"
    original_content = None
    if config_path.exists():
        original_content = config_path.read_text()
    
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    
    yield config_path
    
    if original_content:
        config_path.write_text(original_content)


class TestRegisterAgent:
    """Test router__register_agent functionality."""
    
    def test_register_agent_success(self, router):
        """Can register an agent."""
        result = router.register_agent("test-agent", "implementer", ["editor"])
        
        assert result["agent_id"] == "test-agent"
        assert result["agent_type"] == "implementer"
        assert "editor" in result["roles"]
    
    def test_register_agent_minimal(self, router):
        """Can register with just id and type."""
        result = router.register_agent("test-agent", "explorer")
        
        assert result["agent_id"] == "test-agent"
        assert result["agent_type"] == "explorer"
        assert result["roles"] == []


class TestUpdateAgentPhase:
    """Test router__update_agent_phase functionality."""
    
    def test_update_phase_success(self, router):
        """Can update agent phase."""
        router.register_agent("test-agent", "implementer")
        
        result = router.update_agent_phase("test-agent", "iterate", "implement")
        
        assert result["agent_id"] == "test-agent"
        assert result["workflow"] == "iterate"
        assert result["phase"] == "implement"
    
    def test_update_phase_without_register(self, router):
        """Update phase without registration returns result."""
        # Should not error, just returns the update
        result = router.update_agent_phase("unknown-agent", "iterate", "implement")
        
        assert result["workflow"] == "iterate"


class TestCheckPermission:
    """Test router__check_permission functionality."""
    
    def test_check_allowed_tool(self, router, temp_permissions):
        """Check returns allowed for permitted tools."""
        router.permissions.reload_config()
        
        allowed, response = router._check_permission("Read", {})
        
        assert allowed
        assert response is None
    
    def test_check_blocked_tool(self, router, temp_permissions):
        """Check returns blocked for denied tools."""
        router.permissions.reload_config()
        
        allowed, response = router._check_permission("Edit", {})
        
        assert not allowed
        assert response["blocked"]
    
    def test_check_with_agent_context(self, router, temp_permissions):
        """Check uses agent context from args."""
        router.permissions.reload_config()
        
        # Implementer can use Edit
        allowed, response = router._check_permission(
            "Edit",
            {"file_path": "test.py", "_agent_type": "implementer"}
        )
        
        assert allowed


class TestReloadPermissions:
    """Test router__reload_permissions functionality."""
    
    def test_reload_updates_config(self, router, temp_permissions):
        """Reload picks up config changes."""
        # Initial state
        router.permissions.reload_config()
        allowed1, _ = router._check_permission("Edit", {})
        assert not allowed1  # Blocked globally
        
        # Update config to allow Edit globally
        config = {
            "global": {
                "allowed": ["Read", "Edit", "mcp__router__*"],
                "blocked": ["Bash"],
                "superblocked": [],
            },
        }
        with open(temp_permissions, "w") as f:
            yaml.dump(config, f)
        
        # Reload
        router.permissions.reload_config()
        
        # Now Edit should be allowed
        allowed2, _ = router._check_permission("Edit", {})
        assert allowed2


class TestTelemetryTracking:
    """Test that blocked calls are tracked in telemetry."""
    
    def test_track_blocked_method_exists(self, router):
        """TelemetryCollector has track_blocked method."""
        router_with_telemetry = MCPRouter(enable_telemetry=True)
        assert hasattr(router_with_telemetry.telemetry, "track_blocked")
    
    def test_track_blocked_increments_count(self):
        """track_blocked increments blocked_count."""
        router = MCPRouter(enable_telemetry=True)
        
        initial_events = len(router.telemetry._events)
        
        router.telemetry.track_blocked("Edit", "blocked by global", "explorer")
        
        # Should have one more event
        assert len(router.telemetry._events) == initial_events + 1
        
        # Event should have blocked flag
        last_event = router.telemetry._events[-1]
        assert last_event["blocked"] is True
        assert last_event["tool"] == "Edit"


class TestPermissionsEnvVar:
    """Test MCP_ROUTER_PERMISSIONS_DISABLED environment variable."""

    def test_env_var_disables_permissions(self, monkeypatch):
        """Setting env var disables permission checking."""
        monkeypatch.setenv("MCP_ROUTER_PERMISSIONS_DISABLED", "1")

        # Need to reimport to pick up env var
        import importlib
        import mcp_router
        importlib.reload(mcp_router)

        router = mcp_router.MCPRouter(enable_telemetry=False)
        assert router.permissions is None

        # Clean up - reload without env var
        monkeypatch.delenv("MCP_ROUTER_PERMISSIONS_DISABLED", raising=False)
        importlib.reload(mcp_router)

    def test_env_var_true_disables_permissions(self, monkeypatch):
        """Setting env var to 'true' disables permission checking."""
        monkeypatch.setenv("MCP_ROUTER_PERMISSIONS_DISABLED", "true")

        import importlib
        import mcp_router
        importlib.reload(mcp_router)

        router = mcp_router.MCPRouter(enable_telemetry=False)
        assert router.permissions is None

        monkeypatch.delenv("MCP_ROUTER_PERMISSIONS_DISABLED", raising=False)
        importlib.reload(mcp_router)

    def test_permissions_enabled_by_default(self, monkeypatch):
        """Permissions are enabled when env var is not set."""
        monkeypatch.delenv("MCP_ROUTER_PERMISSIONS_DISABLED", raising=False)

        import importlib
        import mcp_router
        importlib.reload(mcp_router)

        router = mcp_router.MCPRouter(enable_telemetry=False)
        assert router.permissions is not None

        importlib.reload(mcp_router)
