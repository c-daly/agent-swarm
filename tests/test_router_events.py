# /home/fearsidhe/.claude/plugins/agent-swarm/tests/test_router_events.py
import sys
sys.path.insert(0, '/home/fearsidhe/.claude/plugins/agent-swarm/lib')
from mcp_router import MCPRouter  # noqa: E402

def test_router_event_publish():
    router = MCPRouter()
    result = router.event_publish("test_topic", {"key": "value"}, "test-123")
    assert result["status"] == "published"
    assert result["correlation_id"] == "test-123"

def test_router_event_poll_empty():
    router = MCPRouter()
    result = router.event_poll("nonexistent-id")
    assert result is None

def test_router_event_roundtrip():
    router = MCPRouter()
    router.event_publish("test_topic", {"message": "hello"}, "roundtrip-1")
    # Simulate response being added
    router._event_responses["roundtrip-1"] = {"result": "success"}
    result = router.event_poll("roundtrip-1")
    assert result == {"result": "success"}
