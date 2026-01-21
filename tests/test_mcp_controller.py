"""Tests for MCPController orchestration."""
from unittest.mock import Mock
from lib.mcp_controller import MCPController


def test_controller_initializes_with_services():
    """Controller can be initialized with injected services."""
    controller = MCPController()
    assert controller is not None


def test_handle_call_routes_to_backend():
    """Controller routes calls through routing service."""
    mock_routing = Mock()
    mock_routing.route.return_value = {"result": "test"}
    
    mock_summarization = Mock()
    mock_summarization.process.return_value = {
        "content": {"result": "test"},
        "was_summarized": False,
        "original_size": 18,
        "summary_size": None,
    }
    
    controller = MCPController(
        routing_service=mock_routing,
        summarization_service=mock_summarization
    )
    result = controller.handle_call("test__echo", {"msg": "hello"})
    
    mock_routing.route.assert_called_once()
    assert result == {"result": "test"}


def test_handle_call_summarizes_large_response():
    """Large responses are summarized."""
    mock_routing = Mock()
    mock_routing.route.return_value = "x" * 5000  # Large response
    
    mock_summarization = Mock()
    mock_summarization.process.return_value = {
        "content": {
            "summary": "truncated...",
            "content_id": "c123",
            "full_available": True
        },
        "was_summarized": True,
        "original_size": 5000,
        "summary_size": 2003,
    }
    
    controller = MCPController(
        routing_service=mock_routing,
        summarization_service=mock_summarization
    )
    result = controller.handle_call("test__read", {})
    
    mock_summarization.process.assert_called_once()
    assert result == {
        "summary": "truncated...",
        "content_id": "c123",
        "full_available": True
    }


def test_telemetry_includes_summarization_stats():
    """Telemetry events include summarization statistics."""
    mock_routing = Mock()
    mock_routing.route.return_value = "x" * 5000
    
    mock_summarization = Mock()
    mock_summarization.process.return_value = {
        "content": {
            "summary": "truncated...",
            "content_id": "c123",
            "full_available": True
        },
        "was_summarized": True,
        "original_size": 5000,
        "summary_size": 2003,
    }
    
    mock_telemetry = Mock()
    
    controller = MCPController(
        routing_service=mock_routing,
        summarization_service=mock_summarization,
        telemetry_service=mock_telemetry
    )
    controller.handle_call("test__read", {})
    
    # Verify telemetry was called with summarization stats
    mock_telemetry.insert_event.assert_called_once()
    event = mock_telemetry.insert_event.call_args[0][0]
    
    assert event["was_summarized"] is True
    assert event["original_size"] == 5000
    assert event["summary_size"] == 2003


def test_content_id_retrieval():
    """Can retrieve full content via content_id."""
    mock_workflow = Mock()
    mock_workflow.get_content.return_value = {"full": "data"}
    
    controller = MCPController(workflow_state_service=mock_workflow)
    result = controller.get_full_content("c123")
    
    mock_workflow.get_content.assert_called_with("c123")
    assert result == {"full": "data"}
