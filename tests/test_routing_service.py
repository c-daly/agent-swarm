"""Tests for RoutingService."""
from lib.routing_service import RoutingService


def test_register_server():
    """Can register a server."""
    service = RoutingService()
    result = service.register_server("test", ["echo", "test"], {})
    
    assert result["status"] == "registered"
    assert result["name"] == "test"
    assert "test" in [s["name"] for s in service.list_servers()]


def test_unregister_server():
    """Can unregister a server."""
    service = RoutingService()
    service.register_server("test", ["echo", "test"], {})
    
    result = service.unregister_server("test")
    
    assert result["status"] == "unregistered"
    assert "test" not in [s["name"] for s in service.list_servers()]


def test_unregister_nonexistent_server():
    """Unregistering nonexistent server returns not_found."""
    service = RoutingService()
    
    result = service.unregister_server("nonexistent")
    
    assert result["status"] == "not_found"


def test_list_servers():
    """Lists all registered servers."""
    service = RoutingService()
    service.register_server("server1", ["cmd1"], {})
    service.register_server("server2", ["cmd2"], {"arg": "value"})
    
    servers = service.list_servers()
    
    assert len(servers) == 2
    server_names = [s["name"] for s in servers]
    assert "server1" in server_names
    assert "server2" in server_names


def test_route_to_unregistered_server_returns_error():
    """Routing to unregistered server returns error."""
    service = RoutingService()
    
    result = service.route("nonexistent", "some_tool", {})
    
    assert "error" in result
    assert "not registered" in result["error"].lower()


def test_server_config_has_timestamp():
    """Registered servers have registration timestamp."""
    service = RoutingService()
    service.register_server("test", ["echo"], {})
    
    servers = service.list_servers()
    
    assert len(servers) == 1
    assert "registered_at" in servers[0]
    assert servers[0]["registered_at"]  # Not empty


def test_server_registration_with_tool_prefix():
    """Can register server with tool prefix."""
    service = RoutingService()
    service.register_server("test", ["echo"], {}, tool_prefix="test_prefix")
    
    servers = service.list_servers()
    
    assert servers[0]["tool_prefix"] == "test_prefix"


def test_shutdown_terminates_connections():
    """Shutdown cleans up all connections."""
    service = RoutingService()
    service.register_server("test", ["echo"], {})
    # Note: This test verifies shutdown doesn't crash
    # Full connection testing requires actual MCP servers
    
    service.shutdown()
    
    # Should not raise exception
    assert True
